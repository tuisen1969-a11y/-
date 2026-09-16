# -*- coding: utf-8 -*-
"""test_tello_link.py -- 偽 Tello (UDP サーバ) を立てて TelloLink を検証する.

実機なしで「コマンド送信 → 応答」「テレメトリ受信」「映像受信 → 録画ファイル」
「rc 連続送信」「emergency」が機能するかを確認できる。
Kivy に依存しないので PC の素の Python で実行できる。
"""

import os
import socket
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tello import CMD_PORT, STATE_PORT, VIDEO_PORT, TelloLink  # noqa: E402

STATE = ("pitch:5;roll:-3;yaw:127;vgx:10;vgy:-4;vgz:2;templ:62;temph:66;"
         "tof:180;h:150;bat:88;baro:152.30;time:12;agx:0.10;agy:0.20;agz:-0.90;")


class FakeTello(threading.Thread):
    """最低限の Tello もどき: コマンド受信・応答, テレメトリ送出, 映像送出."""

    def __init__(self):
        super(FakeTello, self).__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", CMD_PORT))
        self.commands = []
        self.running = True
        self.flying = False
        self.streaming = False
        self.client = ("127.0.0.1", 0)

    def run(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048)
            except OSError:
                break
            cmd = data.decode("ascii", "ignore").strip()
            self.commands.append(cmd)
            self.client = addr
            if cmd == "takeoff":
                self.flying = True
            elif cmd in ("land", "emergency"):
                self.flying = False
                if cmd == "emergency":
                    self.streaming = False
            elif cmd == "streamon":
                self.streaming = True
                threading.Thread(target=self._stream_video, daemon=True).start()
            try:
                self.sock.sendto(b"ok", addr)
            except OSError:
                pass

    def _stream_video(self):
        v = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        while self.running and self.streaming:
            try:
                v.sendto(b"\x00\x00\x00\x01" + bytes(1000), ("127.0.0.1", VIDEO_PORT))
            except OSError:
                break
            time.sleep(0.02)
        v.close()

    def emit_state(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for _ in range(12):
            if not self.running:
                break
            try:
                s.sendto(STATE.encode(), ("127.0.0.1", STATE_PORT))
            except OSError:
                break
            time.sleep(0.05)
        s.close()


def main():
    fails = []

    def check(name, cond, extra=""):
        print(("  OK   " if cond else "  FAIL ") + name + (" " + str(extra) if extra else ""))
        if not cond:
            fails.append(name)

    fake = FakeTello()
    fake.start()
    time.sleep(0.2)

    link = TelloLink(ip="127.0.0.1", log=lambda m: print("      [link]", m))
    check("connect()", link.connect() is True)
    check("SDK モード要求が届いた", "command" in fake.commands)

    threading.Thread(target=fake.emit_state, daemon=True).start()
    check("takeoff", link.takeoff() == "ok")
    time.sleep(1.0)
    check("テレメトリ受信 (bat)", link.state.get("bat") == "88", link.state.get("bat"))
    check("テレメトリ受信 (pitch/roll/yaw)",
          (link.fnum("pitch"), link.fnum("roll"), link.fnum("yaw")) == (5.0, -3.0, 127.0))

    check("streamon", link.streamon() == "ok")
    time.sleep(1.2)
    check("映像パケット受信", link.video_packets > 10, link.video_packets)

    link.set_rc("ud", 40)
    link.set_rc("yaw", -35)
    time.sleep(0.45)
    rc = [c for c in fake.commands if c.startswith("rc ")]
    check("rc 連続送信 (10Hz 前後)", len(rc) >= 3, rc[-1] if rc else "none")
    check("rc の値が反映 (ud=40, yaw=-35)",
          any(c.split() == ["rc", "0", "0", "40", "-35"] for c in rc), rc[-1] if rc else "")
    link.reset_rc()

    d = tempfile.mkdtemp(prefix="tello_test_")
    path = link.start_recording(d)
    check("録画ファイル作成", bool(path) and os.path.exists(path), path)
    time.sleep(0.8)
    link.stop_recording()
    size = os.path.getsize(path)
    check("録画データが書き込まれた", size > 1000, "%d bytes" % size)
    with open(path, "rb") as fh:
        head = fh.read(4)
    check("Annex-B の NAL 開始コードで始まる", head == b"\x00\x00\x00\x01", head)
    check("録画停止後に recording=False", link.recording is False)

    check("emergency 送信", link.emergency() is True)
    for _ in range(20):          # 機体側の受信処理を待つ (最大 1 秒)
        if "emergency" in fake.commands:
            break
        time.sleep(0.05)
    check("emergency が機体へ届いた", "emergency" in fake.commands, fake.commands[-3:])
    check("緊急停止で rc が 0 に戻る",
          all(abs(v) < 0.001 for v in link.rc_values().values()), link.rc_values())

    check("streamoff", link.streamoff() == "ok")
    check("land", link.land() == "ok")
    link.disconnect()
    check("切断後 connected=False", link.connected is False)

    fake.running = False
    try:
        fake.sock.close()
    except OSError:
        pass

    print()
    if fails:
        print("FAILED: %d 件 -> %s" % (len(fails), ", ".join(fails)))
        return 1
    print("ALL PASS (実機なしで検証できる範囲)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
