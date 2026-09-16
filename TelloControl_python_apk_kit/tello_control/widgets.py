# -*- coding: utf-8 -*-
"""widgets.py -- Tello コントローラ用の自作ウィジェット (Kivy).

  AttitudeIndicator : 水平器 (姿勢指示器). ピッチ / ロール / 機首方位を表示
  Joystick          : アナログ操縦桿. 円形パッドから -1.0〜+1.0 を出力

地平線・ピッチラダーは **座標をすべて Python 側で計算** して頂点を直接与える
(Mesh / Line に絶対座標を渡す) ので、行列命令の適用順に依存せず、
描画結果を画素単位で検証できる。テキストは CoreLabel のテクスチャを貼る。
"""

from math import cos, hypot, radians, sin

from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, Mesh, Rectangle
from kivy.graphics.stencil_instructions import (StencilPop, StencilPush,
                                                StencilUnUse, StencilUse)
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.widget import Widget

WHITE = (1.00, 1.00, 1.00, 1.0)
SKY = (0.16, 0.52, 0.92, 1.0)
GROUND = (0.58, 0.39, 0.15, 1.0)
LINE = (0.92, 0.95, 1.00, 1.0)
AMBER = (1.00, 0.72, 0.16, 1.0)
CYAN = (0.25, 0.88, 0.95, 1.0)
GREY = (0.48, 0.53, 0.61, 1.0)
DIM = (0.64, 0.70, 0.80, 1.0)

# FONT_FIX_v3


def draw_text(text, center, font_size=13, color=WHITE, font_name=None):
    """canvas に直接テキストを描く (子 Label を使わないので挙動が安定).

    font_name が未指定のときは kwarg 自体を渡さない (None を渡すと例外になるため)。
    """
    kw = {"text": text, "font_size": font_size, "color": color}
    if font_name:
        kw["font_name"] = font_name
    lbl = CoreLabel(**kw)
    lbl.refresh()
    tex = lbl.texture
    Color(*color)
    Rectangle(texture=tex, size=tex.size,
              pos=(center[0] - tex.size[0] / 2.0, center[1] - tex.size[1] / 2.0))


def _quad(p0, p1, p2, p3, color):
    """4 頂点 (絶対座標) の四角形を塗る."""
    Color(*color)
    Mesh(vertices=[p0[0], p0[1], 0, 0, p1[0], p1[1], 0, 0,
                   p2[0], p2[1], 0, 0, p3[0], p3[1], 0, 0],
         indices=[0, 1, 2, 0, 2, 3], mode="triangles")


class AttitudeIndicator(Widget):
    """水平器 (姿勢指示器).

    pitch = 機首上げが正, roll = 右バンクが正 (Tello のテレメトリと同じ符号)。
    機体の傾きに対して「世界の地平線」がどう見えるかを計算して描画する:
      ・機首上げ (pitch > 0) → 地平線が画面下へ移動し、空が広く見える
      ・右バンク (roll > 0) → 地平線が反時計回りに傾き、右側が上がる
    目盛り板 (ピッチラダー) は地平線と一緒に回り、上下に固定された琥珀色の
    指針でバンク角を読む。中央の琥珀色の記号が機体そのもの (常に画面中央)。
    """

    pitch = NumericProperty(0.0)
    roll = NumericProperty(0.0)
    yaw = NumericProperty(0.0)
    linked = BooleanProperty(False)
    font_name = StringProperty('')
    view_deg = NumericProperty(30.0)     # 画面半径あたりの視野角 [deg]

    def __init__(self, **kwargs):
        super(AttitudeIndicator, self).__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw, pitch=self._redraw,
                  roll=self._redraw, yaw=self._redraw, linked=self._redraw,
                  font_name=self._redraw)
        self._redraw()

    def _redraw(self, *args):
        self.canvas.clear()
        w, h = self.size
        if w < 20 or h < 20:
            return
        cx, cy = self.center
        r = min(w, h) * 0.5 - dp(3)
        ppd = r / float(self.view_deg or 30.0)      # 1 度あたりの画素数

        a = radians(self.roll)
        ca, sa = cos(a), sin(a)
        dirx, diry = ca, sa                          # 地平線の向き (画面座標)
        upx, upy = -sa, ca                           # 目盛り板の「上」方向
        hx, hy = cx, cy - self.pitch * ppd            # 地平線の中心 (機首上げで下がる)
        S = r * 6.0

        with self.canvas:
            # --- 円形のクリップ領域 ---
            StencilPush()
            Color(1, 1, 1, 1)
            Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))
            StencilUse()

            # --- 空と地面 (地平線で区切った半平面) ---
            ax, ay = hx + dirx * S, hy + diry * S
            bx, by = hx - dirx * S, hy - diry * S
            _quad((ax, ay), (bx, by),
                  (bx + upx * S, by + upy * S), (ax + upx * S, ay + upy * S), SKY)
            _quad((ax, ay), (bx, by),
                  (bx - upx * S, by - upy * S), (ax - upx * S, ay - upy * S), GROUND)

            Color(*LINE)
            Line(points=[ax, ay, bx, by], width=1.4)

            # --- ピッチラダー ---
            for deg in range(-60, 70, 10):
                if deg == 0:
                    continue
                px = hx + upx * deg * ppd
                py = hy + upy * deg * ppd
                half = r * (0.52 if abs(deg) % 20 == 0 else 0.26)
                Color(*LINE)
                Line(points=[px - dirx * half, py - diry * half,
                             px + dirx * half, py + diry * half], width=1.0)
                tick = r * 0.055 * (1 if deg > 0 else -1)
                Line(points=[px - dirx * half, py - diry * half,
                             px - dirx * half + upx * tick,
                             py - diry * half + upy * tick], width=1.0)
                Line(points=[px + dirx * half, py + diry * half,
                             px + dirx * half + upx * tick,
                             py + diry * half + upy * tick], width=1.0)
                if abs(deg) % 20 == 0:
                    q = half + r * 0.17
                    draw_text("%d" % abs(deg), (px - dirx * q, py - diry * q),
                              sp(10), LINE, self.font_name)
                    draw_text("%d" % abs(deg), (px + dirx * q, py + diry * q),
                              sp(10), LINE, self.font_name)

            StencilUnUse()
            Color(1, 1, 1, 1)
            Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))
            StencilPop()

            # --- ここから下はクリップ外 (枠・バンク目盛り・機体記号) ---
            Color(*LINE)
            Line(circle=(cx, cy, r), width=1.6)

            for deg in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60):
                t = radians(90.0 - deg + self.roll)      # 目盛り板はロールと一緒に回る
                ln = r * 0.11 if (deg % 30 == 0 or deg in (-10, 10)) else r * 0.06
                Color(*LINE)
                Line(points=[cx + r * cos(t), cy + r * sin(t),
                             cx + (r - ln) * cos(t), cy + (r - ln) * sin(t)], width=1.2)

            Color(*AMBER)                                # 上下固定のバンク指針
            Line(points=[cx - r * 0.05, cy + r * 0.90,
                         cx, cy + r * 0.99,
                         cx + r * 0.05, cy + r * 0.90], width=2.0)

            w2 = r * 0.44                                # 機体記号 (常に中央)
            Line(points=[cx - w2, cy, cx - w2 * 0.34, cy], width=3.0)
            Line(points=[cx + w2 * 0.34, cy, cx + w2, cy], width=3.0)
            Line(points=[cx - w2 * 0.34, cy, cx - w2 * 0.14, cy], width=3.0)
            Line(points=[cx + w2 * 0.14, cy, cx + w2 * 0.34, cy], width=3.0)
            Ellipse(pos=(cx - dp(1.5), cy - dp(1.5)), size=(dp(3), dp(3)))

            hdg = "HDG %03d" % (int(round(self.yaw)) % 360)
            draw_text(hdg, (cx, cy - r * 0.66), sp(13),
                      AMBER if self.linked else GREY, self.font_name)


class Joystick(Widget):
    """アナログ操縦桿. value = [横(-1..1), 縦(-1..1)] を出力する."""

    value = ListProperty([0.0, 0.0])
    caption = StringProperty('')
    font_name = StringProperty('')
    deadzone = NumericProperty(0.12)

    def __init__(self, **kwargs):
        super(Joystick, self).__init__(**kwargs)
        self._touch = None
        self.bind(pos=self._redraw, size=self._redraw, value=self._redraw,
                  caption=self._redraw, font_name=self._redraw)
        self._redraw()

    # ------------------------------------------------------------ タッチ操作
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._touch = touch
            touch.grab(self)
            self._set_from(touch.pos)
            return True
        return super(Joystick, self).on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._touch is not None and touch.grab_current is self:
            self._set_from(touch.pos)
            return True
        return super(Joystick, self).on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._touch is not None and touch.grab_current is self:
            touch.ungrab(self)
            self._touch = None
            self.value = [0.0, 0.0]      # 指を離したら必ず中立へ
            return True
        return super(Joystick, self).on_touch_up(touch)

    def _set_from(self, pos):
        r = min(self.width, self.height) * 0.5
        if r <= 1:
            return
        dx = (pos[0] - self.center_x) / r
        dy = (pos[1] - self.center_y) / r
        d = hypot(dx, dy)
        if d > 1.0:
            dx /= d
            dy /= d
            d = 1.0
        if d < self.deadzone:
            dx = 0.0
            dy = 0.0
        self.value = [dx, dy]

    # ------------------------------------------------------------ 描画
    def _redraw(self, *args):
        self.canvas.clear()
        w, h = self.size
        if w < 20 or h < 20:
            return
        cx, cy = self.center
        r = min(w, h) * 0.5 - dp(2)
        knob = r * 0.30
        travel = r - knob - dp(2)
        vx, vy = self.value
        active = abs(vx) > 0.001 or abs(vy) > 0.001

        with self.canvas:
            Color(0.10, 0.12, 0.17, 1)
            Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))
            Color(0.30, 0.36, 0.46, 1)
            Line(circle=(cx, cy, r), width=1.6)
            Line(circle=(cx, cy, r * 0.45), width=1.0)
            Line(points=[cx - r, cy, cx + r, cy], width=1.0)
            Line(points=[cx, cy - r, cx, cy + r], width=1.0)
            Color(*(CYAN if active else (0.56, 0.63, 0.73, 1)))
            Ellipse(pos=(cx + vx * travel - knob, cy + vy * travel - knob),
                    size=(2 * knob, 2 * knob))
            if self.caption:
                draw_text(self.caption, (cx, cy + r * 0.82), sp(11), DIM,
                          self.font_name)
            draw_text("%+d / %+d" % (int(round(vx * 100)), int(round(vy * 100))),
                      (cx, cy - r * 0.82), sp(11), CYAN if active else DIM,
                      self.font_name)
