# -*- coding: utf-8 -*-
"""main.py -- Tello ドローン スマホ用コントローラ (Kivy).

画面構成 (横画面):
    ┌──────────────────────────────────────────────────────────────┐
    │ LINK / BAT / ALT / SPD / TOF / REC  ← ステータスバー          │
    ├──────────────┬───────────────────────┬───────────────────────┤
    │ 水平器        │ 操縦桿(左)             │ CONNECT / STREAM      │
    │ (姿勢/機首方位)│ YAW ↔ / ALT ↕          │ ● REC / ■ STOP        │
    │ テレメトリ表  ├───────────────────────┤ ▲+30cm / ▼-30cm       │
    │ ログ          │ 操縦桿(右)             │ ↺45° / ↻45°          │
    │              │ SIDE ↔ / FWD ↕         │ HOLD / 速度リミッタ    │
    ├──────────────┴───────────────────────┴───────────────────────┤
    │ 離陸        │ 着陸        │  緊急停止 (EMERGENCY STOP)        │
    └──────────────────────────────────────────────────────────────┘

ファイル構成:
    tello.py            Tello との UDP 通信 (標準ライブラリのみ / Android でも動作)
    widgets.py          水平器・操縦桿 (canvas 描画)
    android_helpers.py  WifiLock / 画面常時点灯 / 保存先
    main.py             本ファイル (画面と操作ロジック)
"""

import os
import threading
import time
from collections import deque

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.utils import platform

import android_helpers as ah
from tello import SW_VERSION, TelloLink
from widgets import AttitudeIndicator, Joystick

# --------------------------------------------------------------------- 配色
BG = (0.06, 0.07, 0.10, 1)
PANEL = (0.10, 0.12, 0.17, 1)
FG = (0.90, 0.93, 0.98, 1)
DIMTXT = (0.58, 0.64, 0.74, 1)
GREEN = (0.12, 0.52, 0.30, 1)
BLUE = (0.12, 0.33, 0.64, 1)
ORANGE = (0.76, 0.44, 0.07, 1)
RED = (0.70, 0.09, 0.11, 1)
GREY = (0.24, 0.28, 0.36, 1)
CYAN = (0.08, 0.44, 0.50, 1)

# 日本語フォント (同梱すれば日本語ログが表示できる / 無い場合は英字のみ)
FONT_PATHS = ("fonts/NotoSansJP-Regular.otf", "fonts/NotoSansJP-Regular.ttf",
              "fonts/NotoSansCJKjp-Regular.otf", "fonts/ipaexg.ttf")


def register_font():
    for p in FONT_PATHS:
        try:
            if os.path.exists(p):
                LabelBase.register(name="AppFont", fn_regular=p)
                return "AppFont"
        except Exception:
            pass
    return None


class Panel(BoxLayout):
    """半透明の背景板つきコンテナ."""

    def __init__(self, **kw):
        super(Panel, self).__init__(**kw)
        with self.canvas.before:
            Color(*PANEL)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size


class Flat(Button):
    """背景色をべた塗りにするボタン (Kivy 既定テクスチャを使わない)."""

    def __init__(self, bg=GREY, **kw):
        kw.setdefault("background_normal", "")
        kw.setdefault("background_down", "")
        kw.setdefault("background_color", bg)
        kw.setdefault("color", FG)
        kw.setdefault("font_size", sp(13))
        super(Flat, self).__init__(**kw)


def mono(text="", size=sp(11), color=FG, font=None, **kw):
    kw.setdefault("size_hint_x", 1)
    kw.setdefault("halign", "left")
    kw.setdefault("valign", "middle")
    return Label(text=text, font_size=size, color=color,
                 font_name=(font or "Roboto"), **kw)


class TelloApp(App):

    # ------------------------------------------------------------- 構築
    def build(self):
        self.font = register_font()
        self.link = TelloLink(log=self.log)
        self.logs = deque(maxlen=7)
        self._rec_dir = None
        self._busy = False
        self._connected_ui = False

        root = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(4))
        with root.canvas.before:
            Color(*BG)
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=lambda *a: setattr(self._bg, "pos", root.pos),
                  size=lambda *a: setattr(self._bg, "size", root.size))

        root.add_widget(self._build_statusbar())
        root.add_widget(self._build_main())
        root.add_widget(self._build_actions())

        Clock.schedule_interval(self.update, 0.2)
        self.log("Tello Control v%s" % SW_VERSION)
        return root

    # ------------------------------------------------ 上部ステータスバー
    def _build_statusbar(self):
        bar = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(4))
        with bar.canvas.before:
            Color(0.08, 0.09, 0.13, 1)
            self._bar_rect = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(pos=lambda *a: setattr(self._bar_rect, "pos", bar.pos),
                 size=lambda *a: setattr(self._bar_rect, "size", bar.size))
        self.l_status = {}
        for key, text, weight in (("link", "LINK: ---", 1.3),
                                  ("bat", "BAT: --%", 1.0),
                                  ("alt", "ALT: --- m", 1.0),
                                  ("spd", "SPD: -- m/s", 1.1),
                                  ("tof", "TOF: --- cm", 1.0),
                                  ("rec", "REC: OFF", 1.2)):
            lbl = mono(text, sp(12), FG, self.font, size_hint_x=weight)
            self.l_status[key] = lbl
            bar.add_widget(lbl)
        return bar

    # ------------------------------------------------------------ 本体部
    def _build_main(self):
        main = BoxLayout(orientation="horizontal", spacing=dp(4))

        # ---- 左: 水平器 + テレメトリ ----
        left = Panel(orientation="vertical", size_hint_x=0.40, spacing=dp(3),
                     padding=dp(3))
        self.horizon = AttitudeIndicator(font_name=(self.font or ""))
        left.add_widget(self.horizon)

        tel = GridLayout(cols=4, size_hint_y=None, height=dp(74), spacing=dp(2))
        self.l_tel = {}
        rows = (("PITCH", "0.0"), ("ROLL", "0.0"),
                ("YAW", "0.0"), ("H", "0"),
                ("VGX", "0"), ("VGY", "0"),
                ("VGZ", "0"), ("BARO", "0"),
                ("TEMP", "0"), ("BAT", "0"),
                ("LINK", "0.0"), ("VIDEO", "0 kbps"))
        for name, _v in rows:
            tel.add_widget(mono(name, sp(10), DIMTXT, self.font))
            lbl = mono("--", sp(11), FG, self.font, halign="right")
            self.l_tel[name] = lbl
            tel.add_widget(lbl)
        left.add_widget(tel)

        self.l_log = mono("", sp(10), CYAN, self.font, valign="top",
                          size_hint_y=0.45)
        self.l_log.bind(size=lambda *a: setattr(
            self.l_log, "text_size", (self.l_log.width, self.l_log.height)))
        left.add_widget(self.l_log)
        main.add_widget(left)

        # ---- 中央: 操縦桿 2 本 ----
        center = Panel(orientation="horizontal", size_hint_x=0.36,
                       spacing=dp(6), padding=dp(4))
        self.js_alt = Joystick(caption="YAW  <->   ALT (UP/DOWN)",
                               font_name=(self.font or ""))
        self.js_fb = Joystick(caption="SIDE <->   FWD/BACK",
                              font_name=(self.font or ""))
        center.add_widget(self.js_alt)
        center.add_widget(self.js_fb)
        main.add_widget(center)

        # ---- 右: スイッチ類 ----
        right = Panel(orientation="vertical", size_hint_x=0.24, spacing=dp(4),
                      padding=dp(4))

        self.b_conn = Flat(text="CONNECT", bg=BLUE)
        self.b_conn.bind(on_release=self.on_connect)
        right.add_widget(self.b_conn)

        self.b_stream = Flat(text="STREAM ON", bg=CYAN)
        self.b_stream.bind(on_release=self.on_stream)
        right.add_widget(self.b_stream)

        self.b_rec = Flat(text="●  REC", bg=ORANGE)
        self.b_rec.bind(on_release=self.on_record)
        right.add_widget(self.b_rec)

        row1 = BoxLayout(spacing=dp(4), size_hint_y=None, height=dp(38))
        b_up = Flat(text="▲ +30cm", bg=GREY)
        b_up.bind(on_release=lambda *a: self.step_cmd("up 30"))
        b_dn = Flat(text="▼ -30cm", bg=GREY)
        b_dn.bind(on_release=lambda *a: self.step_cmd("down 30"))
        row1.add_widget(b_up)
        row1.add_widget(b_dn)
        right.add_widget(row1)

        row2 = BoxLayout(spacing=dp(4), size_hint_y=None, height=dp(38))
        b_ccw = Flat(text="↺ 45°", bg=GREY)
        b_ccw.bind(on_release=lambda *a: self.step_cmd("ccw 45"))
        b_cw = Flat(text="↻ 45°", bg=GREY)
        b_cw.bind(on_release=lambda *a: self.step_cmd("cw 45"))
        row2.add_widget(b_ccw)
        row2.add_widget(b_cw)
        right.add_widget(row2)

        self.b_hold = Flat(text="HOLD (rc 0)", bg=(0.20, 0.42, 0.30, 1))
        self.b_hold.bind(on_release=self.on_hold)
        right.add_widget(self.b_hold)

        right.add_widget(mono("速度リミッタ (%)", sp(10), DIMTXT, self.font,
                              size_hint_y=None, height=dp(16)))
        self.s_max = Slider(min=20, max=100, value=60, step=5,
                            size_hint_y=None, height=dp(28))
        right.add_widget(self.s_max)
        self.l_max = mono("60 %  (rc 上限)", sp(10), DIMTXT, self.font,
                          size_hint_y=None, height=dp(14), halign="center")
        self.s_max.bind(value=lambda *a: setattr(
            self.l_max, "text", "%d %%  (rc 上限)" % int(self.s_max.value)))
        right.add_widget(self.l_max)

        for js in (self.js_alt, self.js_fb):
            js.bind(value=self._apply_rc)
        self.s_max.bind(value=self._apply_rc)
        main.add_widget(right)
        return main

    # ------------------------------------------------------ 下部の操作列
    def _build_actions(self):
        act = BoxLayout(size_hint_y=None, height=dp(62), spacing=dp(6))
        self.b_takeoff = Flat(text="TAKE OFF", bg=GREEN, font_size=sp(17))
        self.b_takeoff.bind(on_release=self.on_takeoff)
        self.b_land = Flat(text="LAND", bg=BLUE, font_size=sp(17))
        self.b_land.bind(on_release=self.on_land)
        self.b_emerg = Flat(text="■ EMERGENCY STOP (モーター即停止)",
                            bg=RED, font_size=sp(17), size_hint_x=2.0)
        self.b_emerg.bind(on_release=self.on_emergency)
        act.add_widget(self.b_takeoff)
        act.add_widget(self.b_land)
        act.add_widget(self.b_emerg)
        return act

    # ------------------------------------------------------------- ログ
    def log(self, msg):
        line = time.strftime("%H:%M:%S ") + str(msg)
        print("[tello]", line)
        self.logs.append(line)

    def _async(self, fn, *args):
        """UI を止めないようにコマンド送信を別スレッドで実行する."""
        if self._busy:
            self.log("処理中です…")
            return
        self._busy = True

        def run():
            try:
                fn(*args)
            except Exception as e:      # 例外でアプリを落とさない
                self.log("エラー: %s" % e)
            finally:
                self._busy = False

        threading.Thread(target=run, daemon=True).start()

    # --------------------------------------------------------- ボタン動作
    def on_connect(self, *_a):
        if self.link.connected:
            self._async(self.link.disconnect)
        else:
            self._async(self.link.connect)

    def on_takeoff(self, *_a):
        if not self._ensure_link():
            return
        self._async(self.link.takeoff)

    def on_land(self, *_a):
        if not self._ensure_link():
            return
        self._async(self.link.land)

    def on_emergency(self, *_a):
        """緊急停止. 確認なしで即送信する (安全側に倒した設計)."""
        self.js_alt.value = [0.0, 0.0]
        self.js_fb.value = [0.0, 0.0]
        ok = self.link.emergency()
        self.log("EMERGENCY STOP 送信%s" % ("" if ok else "失敗"))
        if self.link.recording:
            self.log("録画は継続中です (■ STOP で保存)")

    def on_stream(self, *_a):
        if not self._ensure_link():
            return
        self._async(self.link.streamoff if self.link.streaming
                    else self.link.streamon)

    def on_record(self, *_a):
        if not self._ensure_link():
            return
        if self.link.recording:
            path = self.link.stop_recording()
            self.log("保存完了: %s" % (path or "-"))
        else:
            if not self.link.streaming:
                self.link.streamon()
            path = self.link.start_recording(self._get_rec_dir())
            if path is None:
                self.log("録画を開始できませんでした")

    def on_hold(self, *_a):
        self.js_alt.value = [0.0, 0.0]
        self.js_fb.value = [0.0, 0.0]
        self.link.reset_rc()
        self.log("操縦入力 0 (ホバリング)")

    def step_cmd(self, cmd):
        """正確な高度・旋回操作 (up/down/cw/ccw)."""
        if not self._ensure_link():
            return
        self.log("送信: %s" % cmd)
        self._async(self.link.send, cmd, True, 6.0)

    def _ensure_link(self):
        if not self.link.connected:
            self.log("未接続です (CONNECT を押してください)")
            return False
        return True

    # -------------------------------------------------------- 操縦入力
    def _apply_rc(self, *_a):
        if not self.link.connected:
            return
        lim = float(self.s_max.value)
        yaw, alt = self.js_alt.value
        side, fwd = self.js_fb.value
        self.link.set_rc("yaw", yaw * lim)
        self.link.set_rc("ud", alt * lim)
        self.link.set_rc("lr", side * lim)
        self.link.set_rc("fb", fwd * lim)

    def _get_rec_dir(self):
        if self._rec_dir is None:
            base = ah.external_files_dir()
            if not base:
                base = ("/sdcard/TelloControl" if platform == "android"
                        else os.path.join(os.path.expanduser("~"), "TelloControl"))
            self._rec_dir = os.path.join(base, "videos")
        return self._rec_dir

    # ------------------------------------------------------------ 表示更新
    def update(self, _dt):
        lk = self.link
        age = lk.state_age()
        live = lk.connected and 0 <= age < 1.5

        st = lk.state
        self.horizon.linked = live
        self.horizon.pitch = lk.fnum("pitch")
        self.horizon.roll = lk.fnum("roll")
        self.horizon.yaw = lk.fnum("yaw")

        t = self.l_tel
        t["PITCH"].text = "%+.1f" % lk.fnum("pitch")
        t["ROLL"].text = "%+.1f" % lk.fnum("roll")
        t["YAW"].text = "%+.0f" % lk.fnum("yaw")
        t["H"].text = "%.2f m" % (lk.fnum("h") / 100.0)
        t["VGX"].text = "%+.0f" % lk.fnum("vgx")
        t["VGY"].text = "%+.0f" % lk.fnum("vgy")
        t["VGZ"].text = "%+.0f" % lk.fnum("vgz")
        t["BARO"].text = "%.0f" % lk.fnum("baro")
        t["TEMP"].text = "%.0f/%.0f" % (lk.fnum("templ"), lk.fnum("temph"))
        t["BAT"].text = "%d %%" % int(lk.fnum("bat"))
        t["LINK"].text = ("%.1fs" % age) if age >= 0 else "--"
        t["VIDEO"].text = "%.0f kbps" % (lk.video_bps / 1000.0) if lk.streaming \
            else "off"

        s = self.l_status
        s["link"].text = "LINK: %s" % ("OK" if live else ("NO TELEM" if lk.connected else "---"))
        s["link"].color = FG if live else DIMTXT
        s["bat"].text = "BAT: %d%%" % int(lk.fnum("bat"))
        s["bat"].color = RED if lk.fnum("bat") < 20 else FG
        s["alt"].text = "ALT: %.2f m" % (lk.fnum("h") / 100.0)
        spd = (lk.fnum("vgx") ** 2 + lk.fnum("vgy") ** 2 + lk.fnum("vgz") ** 2) ** 0.5
        s["spd"].text = "SPD: %.1f m/s" % (spd / 100.0)
        s["tof"].text = "TOF: %d cm" % int(lk.fnum("tof"))
        if lk.recording:
            s["rec"].text = "● REC %02d:%02d %.1fMB" % (
                int(lk.rec_elapsed()) // 60, int(lk.rec_elapsed()) % 60,
                lk.rec_bytes / 1048576.0)
            s["rec"].color = RED
        else:
            s["rec"].text = "REC: OFF"
            s["rec"].color = DIMTXT

        # ボタンの表示状態
        self.b_conn.text = "DISCONNECT" if lk.connected else "CONNECT"
        self.b_conn.background_color = GREY if lk.connected else BLUE
        self.b_stream.text = "STREAM OFF" if lk.streaming else "STREAM ON"
        self.b_rec.text = ("■ STOP REC" if lk.recording else "●  REC")
        self.l_log.text = "\n".join(self.logs)

    # ------------------------------------------------------------ ライフサイクル
    def on_start(self):
        try:
            ah.request_storage_permissions()
            if ah.acquire_locks():
                self.log("WifiLock 取得 (画面消灯でも通信継続)")
            ah.keep_screen_on()
        except Exception as e:
            self.log("端末初期化の一部に失敗: %s" % e)

    def on_pause(self):
        return True          # バックグラウンドでも状態を保持

    def on_stop(self):
        try:
            if self.link.flying:
                self.log("終了処理: 着陸します")
                self.link.land()
            if self.link.recording:
                self.link.stop_recording()
            self.link.disconnect()
        except Exception:
            pass
        ah.release_locks()


if __name__ == "__main__":
    TelloApp().run()
