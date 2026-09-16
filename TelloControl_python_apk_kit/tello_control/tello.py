# -*- coding: utf-8 -*-
"""tello.py -- Tello (Ryze/DJI) を UDP で直接操作する最小クライアント.

外部ライブラリに依存せず標準ライブラリだけで動くので、
python-for-android (Kivy) 上でもそのまま使用できる。

ネットワーク構成 (Tello の Wi-Fi AP に接続した状態):
    192.168.10.1:8889/udp  コマンド送信 (要 "command" で SDK モードへ)
    自機 IP:8890/udp       状態テレメトリ "pitch:0;roll:0;yaw:0;...;bat:88;"
    自機 IP:11111/udp      H.264 (Annex-B) 映像ストリーム

使い方:
    link = TelloLink(log=print)
    if link.connect():
        link.streamon()
        link.start_recording("/sdcard/.../TelloRec")
        link.takeoff()
        link.set_rc("ud", 30)      # 上昇
        link.set_rc("yaw", -40)    # 左旋回
        link.set_rc("ud", 0); link.set_rc("yaw", 0)
        link.land()
"""

import os
import socket
import threading
import time

TELLO_IP = "192.168.10.1"
CMD_PORT = 8889
STATE_PORT = 8890
VIDEO_PORT = 11111
LOCAL_CMD_PORT = 9000

RC_HZ = 10.0            # rc コマンド送信周期 (Tello は ~10Hz を推奨)
SW_VERSION = "1.0.0"


class TelloLink(object):
    """Tello への UDP リンク (コマンド / 状態 / 映像 の 3 系統)."""

    def __init__(self, ip=TELLO_IP, log=None):
        self.ip = ip
        self.log = log if log is not None else (lambda *a: None)

        # --- 状態 ---
        self.state = {}
        self.state_time = 0.0
        self.connected = False
        self.streaming = False
        self.flying = False

        # --- ソケット ---
        self._cmd = None            # 応答ありコマンド用
        self._state_sock = None     # テレメトリ受信
        self._video_sock = None     # 映像受信
        self._emerg_sock = None     # 緊急停止用 (ロックを迂回)

        self._cmd_lock = threading.RLock()
        self._running = False
        self._threads = []

        # --- 操縦入力 (-100..100) ---
        self._rc = {"lr": 0.0, "fb": 0.0, "ud": 0.0, "yaw": 0.0}
        self._rc_lock = threading.Lock()

        # --- 映像統計 ---
        self.video_bytes = 0
        self.video_packets = 0
        self.video_bps = 0.0
        self.video_fps = 0.0
        self.video_active = False
        self._win_bytes = 0
        self._win_packets = 0
        self._win_t = 0.0

        # --- 録画 ---
        self.recording = False
        self.rec_path = None
        self.rec_bytes = 0
        self.rec_started = 0.0
        self._rec_fh = None
        self._rec_synced = False
        self._rec_lock = threading.RLock()

    # ------------------------------------------------------------------ 接続
    def connect(self, timeout=7.0):
        """ソケットを開いて SDK モードに入る. 成功したら True."""
        if self.connected:
            return True
        try:
            self._cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._cmd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._cmd.bind(("", LOCAL_CMD_PORT))
            except OSError:
                self._cmd.bind(("", 0))
            self._cmd.settimeout(0.5)

            self._state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._state_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._state_sock.bind(("", STATE_PORT))
            except OSError as e:
                self.log("状態ポート %d を開けません: %s" % (STATE_PORT, e))
            self._state_sock.settimeout(0.5)

            self._video_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._video_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._video_sock.bind(("", VIDEO_PORT))
            except OSError as e:
                self.log("映像ポート %d を開けません: %s" % (VIDEO_PORT, e))
            self._video_sock.settimeout(0.5)

            self._emerg_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._emerg_sock.settimeout(0.5)
        except OSError as e:
            self.log("ソケット作成に失敗: %s" % e)
            self._close_all()
            return False

        resp = self.send("command", wait=True, timeout=timeout)
        if resp is None:
            self.log("応答がありません (TELLO-xxxx の Wi-Fi に接続していますか?)")
            self._close_all()
            return False

        self.connected = True
        self._running = True
        self._win_t = time.time()
        self._start_threads()
        self.log("SDK モード開始 (%s)" % resp)
        return True

    def disconnect(self):
        self.stop_recording()
        try:
            if self.streaming:
                self.send("streamoff", wait=False)
        except Exception:
            pass
        self._running = False
        self.connected = False
        self.streaming = False
        self.state = {}
        self.state_time = 0.0
        self._close_all()
        self.log("切断しました")

    def _close_all(self):
        for name in ("_cmd", "_state_sock", "_video_sock", "_emerg_sock"):
            s = getattr(self, name, None)
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
                setattr(self, name, None)

    def _start_threads(self):
        for fn, tag in ((self._state_loop, "state"),
                        (self._video_loop, "video"),
                        (self._rc_loop, "rc")):
            t = threading.Thread(target=fn, name="tello-" + tag)
            t.daemon = True
            t.start()
            self._threads.append(t)

    # -------------------------------------------------------------- コマンド送信
    @staticmethod
    def _drain(sock):
        sock.setblocking(False)
        try:
            while True:
                sock.recvfrom(4096)
        except Exception:
            pass
        finally:
            sock.setblocking(True)
            sock.settimeout(0.5)

    def send(self, cmd, wait=True, timeout=3.0):
        """コマンドを送る. wait=False なら応答を待たない (rc 用)."""
        with self._cmd_lock:
            sock = self._cmd
            if sock is None:
                return None
            self._drain(sock)
            try:
                sock.sendto(cmd.encode("ascii", "ignore"), (self.ip, CMD_PORT))
            except OSError as e:
                self.log("送信失敗 %s: %s" % (cmd, e))
                return None
            if not wait:
                return "sent"
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data, _addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    return None
                return data.decode("utf-8", "ignore").strip()
            self.log("応答なし: %s" % cmd)
            return None

    # -------------------------------------------------------------- 基本操作
    def takeoff(self):
        r = self.send("takeoff", timeout=15.0)
        if r == "ok":
            self.flying = True
        return r

    def land(self):
        r = self.send("land", timeout=15.0)
        if r == "ok":
            self.flying = False
        return r

    def emergency(self):
        """緊急停止. モーターを即座に止める (機体はその場で落下する).

        通常コマンドのロックを迂回して別ソケットから送るので、
        何かコマンドが詰まっていても必ず送信される。
        """
        with self._rc_lock:
            for k in self._rc:
                self._rc[k] = 0.0
        ok = False
        for sock in (self._emerg_sock, self._cmd):
            if sock is None:
                continue
            try:
                sock.sendto(b"emergency", (self.ip, CMD_PORT))
                ok = True
            except OSError as e:
                self.log("緊急停止の送信失敗: %s" % e)
        self.flying = False
        return ok

    def streamon(self):
        r = self.send("streamon", timeout=5.0)
        if r == "ok":
            self.streaming = True
            self._win_t = time.time()
        return r

    def streamoff(self):
        r = self.send("streamoff", timeout=5.0)
        self.streaming = False
        self.video_active = False
        return r

    def set_rc(self, axis, value):
        """軸ごとの操縦入力を設定 (-100..100). 実送信は _rc_loop が行う."""
        if axis not in self._rc:
            return
        try:
            v = max(-100.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            v = 0.0
        with self._rc_lock:
            self._rc[axis] = v

    def rc_values(self):
        with self._rc_lock:
            return dict(self._rc)

    def reset_rc(self):
        with self._rc_lock:
            for k in self._rc:
                self._rc[k] = 0.0

    # -------------------------------------------------------------- 受信スレッド
    def _state_loop(self):
        sock = self._state_sock
        while self._running and sock is not None:
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            st = {}
            for part in data.decode("utf-8", "ignore").split(";"):
                if ":" in part:
                    k, v = part.split(":", 1)
                    st[k.strip()] = v.strip()
            if st:
                self.state = st
                self.state_time = time.time()

    def _video_loop(self):
        sock = self._video_sock
        while self._running and sock is not None:
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            n = len(data)
            now = time.time()
            self.video_bytes += n
            self.video_packets += 1
            self.video_active = True
            if now - self._win_t >= 1.0:
                dt = max(1e-3, now - self._win_t)
                self.video_fps = (self.video_packets - self._win_packets) / dt
                self.video_bps = (self.video_bytes - self._win_bytes) / dt
                self._win_packets = self.video_packets
                self._win_bytes = self.video_bytes
                self._win_t = now

            fh = self._rec_fh
            if fh is None:
                continue
            if not self._rec_synced:
                # 先頭の壊れたフレームを避けるため NAL 開始コードまで待つ
                if data[:4] == b"\x00\x00\x00\x01" or data[:3] == b"\x00\x00\x01":
                    self._rec_synced = True
                else:
                    continue
            try:
                fh.write(data)
                self.rec_bytes += n
            except OSError as e:
                self.log("録画の書き込みに失敗: %s" % e)
                self._rec_fh = None

    def _rc_loop(self):
        """操縦入力を 10Hz で送り続ける. これが機体のキープアライブも兼ねる."""
        period = 1.0 / RC_HZ
        while self._running:
            v = self.rc_values()
            self.send("rc %d %d %d %d" % (int(round(v["lr"])), int(round(v["fb"])),
                                          int(round(v["ud"])), int(round(v["yaw"]))),
                      wait=False)
            time.sleep(period)

    # -------------------------------------------------------------- 録画
    def start_recording(self, directory):
        with self._rec_lock:
            if self._rec_fh is not None:
                return self.rec_path
            try:
                if not os.path.isdir(directory):
                    os.makedirs(directory)
            except OSError as e:
                self.log("保存先を作成できません: %s" % e)
                return None
            name = time.strftime("TELLO_%Y%m%d_%H%M%S.h264", time.localtime())
            path = os.path.join(directory, name)
            try:
                self._rec_fh = open(path, "wb")
            except OSError as e:
                self.log("録画ファイルを作成できません: %s" % e)
                return None
            self.rec_path = path
            self.rec_bytes = 0
            self.rec_started = time.time()
            self.recording = True
            self._rec_synced = False
            self.log("録画開始: %s" % path)
            return path

    def stop_recording(self):
        with self._rec_lock:
            fh = self._rec_fh
            self._rec_fh = None
            self.recording = False
            if fh is None:
                return None
            try:
                fh.flush()
                os.fsync(fh.fileno())
            except OSError:
                pass
            try:
                fh.close()
            except OSError:
                pass
            self.log("録画停止: %s (%.2f MB)" % (self.rec_path, self.rec_bytes / 1048576.0))
            return self.rec_path

    def rec_elapsed(self):
        if not self.recording or not self.rec_started:
            return 0.0
        return time.time() - self.rec_started

    # -------------------------------------------------------------- テレメトリ
    def fnum(self, key, default=0.0):
        try:
            return float(self.state.get(key, default))
        except (TypeError, ValueError):
            return default

    def state_age(self):
        if not self.state_time:
            return -1.0
        return time.time() - self.state_time
