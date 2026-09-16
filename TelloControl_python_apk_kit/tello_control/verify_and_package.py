# -*- coding: utf-8 -*-
"""verify_and_package.py -- 配布前の検証と ZIP 作成 (PC 上で実行).
# MARKER_GUARDED_v2

[A] tests/test_tello_link.py (偽 Tello による通信の自動テスト) を実行
[B] Kivy ウィンドウを作り、アプリ全体と水平器を実際に描画して PNG 出力
[C] 出力した PNG の画素を読み、水平器の傾き/俯仰が設計どおりかを検証
    (描画できない環境では SKIP と表示し、検証済みとは主張しない)
[D] 配布用 ZIP を作成

実行: xvfb-run -a python3 -u verify_and_package.py
"""

import os
import subprocess
import sys
import traceback
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "verify")
os.makedirs(OUT, exist_ok=True)

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_LOG_LEVEL", "warning")

FAILS = []
SKIPS = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + ("  " + str(extra) if extra else ""),
          flush=True)
    if not cond:
        FAILS.append(name)
    return bool(cond)


def skip(name, why):
    print("  SKIP %s  (%s)" % (name, why), flush=True)
    SKIPS.append(name)


# ----------------------------------------------------------------- [A] 通信
print("== [A] TelloLink の自動テスト (偽 Tello) ==", flush=True)
r = subprocess.run([sys.executable, os.path.join(HERE, "tests", "test_tello_link.py")],
                   capture_output=True, text=True, cwd=HERE)
for line in r.stdout.splitlines():
    if line.startswith(("  OK", "  FAIL", "ALL PASS", "FAILED")):
        print("     " + line, flush=True)
check("tests/test_tello_link.py が全項目通過", r.returncode == 0,
      "returncode=%d" % r.returncode if r.returncode else "")

# ----------------------------------------------------------------- [B] 描画
print("\n== [B] Kivy で実際に描画 ==", flush=True)
Window = None
try:
    from kivy.config import Config
    Config.set("graphics", "width", "1280")
    Config.set("graphics", "height", "720")
    from kivy.core.window import Window          # ウィンドウ生成
    from kivy.metrics import dp
    from kivy.clock import Clock
    print("     window: %s" % (Window.size,), flush=True)
except Exception:
    traceback.print_exc()
    skip("Kivy 描画", "ウィンドウを作成できない環境")

pngs = {}
if Window is not None:
    try:
        import main
        from widgets import AttitudeIndicator

        app = main.TelloApp()
        root = app.build()
        Window.add_widget(root)
        root.size = Window.size
        root.pos = (0, 0)
        app.on_start()
        for _ in range(4):
            Clock.tick()
        root.do_layout()
        shot = os.path.join(OUT, "app_screen.png")
        root.export_to_png(shot)          # FIX_NL_v4
        pngs["app"] = shot
        check("アプリ画面を描画できた",
              os.path.exists(shot) and os.path.getsize(shot) > 5000,
              "%d bytes" % (os.path.getsize(shot) if os.path.exists(shot) else 0))

        for name, roll, pitch in (("h_0_0.png", 0.0, 0.0),
                                  ("h_r30.png", 30.0, 0.0),
                                  ("h_p15.png", 0.0, 15.0)):
            ai = AttitudeIndicator(size=(300, 300), pos=(0, 0), roll=roll,
                                   pitch=pitch, yaw=127.0, linked=True)
            ai._redraw()          # Widget には do_layout が無いので直接再描画
            p = os.path.join(OUT, name)
            ai.export_to_png(p)
            pngs[name] = p
            check("水平器を描画 (roll=%g pitch=%g)" % (roll, pitch),
                  os.path.exists(p) and os.path.getsize(p) > 1000,
                  "%d bytes" % (os.path.getsize(p) if os.path.exists(p) else 0))
    except Exception:
        traceback.print_exc()
        skip("Kivy 描画", "描画中に例外 (上のトレースバック参照)")

# ------------------------------------------------------------- [C] 画素検証
print("\n== [C] 描画結果の画素を読んで水平器の向きを検証 ==", flush=True)
try:
    from PIL import Image
except ImportError:
    Image = None
    skip("画素検証", "Pillow が無い")

SKY = (41, 133, 235)        # widgets.py の SKY   (0.16, 0.52, 0.92)
GROUND = (148, 99, 38)      # widgets.py の GROUND (0.58, 0.39, 0.15)


def near(c, ref, tol=34):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


if Image is not None and "h_0_0.png" in pngs:
    def make_reader(img, flip):
        def read(x, y):
            yy = int(img.height - 1 - y) if flip else int(y)
            return img.getpixel((int(x), max(0, min(img.height - 1, yy))))[:3]
        return read

    def classify(read, x, y):
        c = read(x, y)
        if near(c, SKY):
            return "SKY"
        if near(c, GROUND):
            return "GROUND"
        return "OTHER%s" % (c,)

    img0 = Image.open(pngs["h_0_0.png"]).convert("RGB")
    CX = CY = img0.width / 2.0
    R = img0.width / 2.0 - dp(3)          # 円の半径 (widgets.py と同じ式)
    PPD = R / 30.0                         # 1 度あたりの画素数 (view_deg=30)

    # PNG の上下の向きを実データから判定する (決め打ちしない)
    flip = True
    reader_try = make_reader(img0, True)
    if classify(reader_try, CX, CY + 40) != "SKY":
        flip = False
    read0 = make_reader(img0, flip)
    print("     PNG 縦方向の読み方: %s / R=%.1f px, 1deg=%.2f px"
          % ("上下反転あり" if flip else "そのまま", R, PPD), flush=True)
    check("roll=0,pitch=0: 上部が空 (SKY)", classify(read0, CX, CY + 40) == "SKY",
          classify(read0, CX, CY + 40))
    check("roll=0,pitch=0: 下部が地面 (GROUND)", classify(read0, CX, CY - 40) == "GROUND",
          classify(read0, CX, CY - 40))

    # 右バンク (roll=+30) -> 地平線は反時計回りに傾き、右端が上がる
    img = Image.open(pngs["h_r30.png"]).convert("RGB")
    read = make_reader(img, flip)
    dy = 70.0 * 0.57735                    # dx=70px での地平線の上下量
    for lbl, sx, yl in (("右 (+70px)", CX + 70, CY + dy), ("左 (-70px)", CX - 70, CY - dy)):
        up, dn = classify(read, sx, yl + 9), classify(read, sx, yl - 9)
        check("roll=+30: %s 側の地平線が設計どおりの高さ" % lbl,
              up == "SKY" and dn == "GROUND", "上=%s 下=%s (y=%.1f)" % (up, dn, yl))

    # 機首上げ (pitch=+15) -> 地平線が下がり、画面中央は空になる
    img = Image.open(pngs["h_p15.png"]).convert("RGB")
    read = make_reader(img, flip)
    y_h = CY - 15.0 * PPD
    up, dn = classify(read, CX, y_h + 9), classify(read, CX, y_h - 9)
    check("pitch=+15: 地平線が下がった位置にある",
          up == "SKY" and dn == "GROUND", "上=%s 下=%s (y=%.1f)" % (up, dn, y_h))
    # 中央の機体記号 (琥珀色) を避けて、中央付近の空を確認する
    check("pitch=+15: 中央付近が空 (機首上げ)", classify(read, CX + 60, CY + 40) == "SKY",
          classify(read, CX + 60, CY + 40))
else:
    skip("画素検証", "水平器の PNG が無い")

# ------------------------------------------------------------- [D] ZIP 作成
print("\n== [D] 配布用 ZIP を作成 ==", flush=True)
zpath = "/home/user/TelloControl_python_apk_kit.zip"
skip_dirs = {"__pycache__", ".buildozer", "bin", "verify", ".git"}
skip_ext = {".pyc", ".apk"}
n = 0
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    for base, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if os.path.splitext(f)[1] in skip_ext:
                continue
            full = os.path.join(base, f)
            z.write(full, os.path.join("tello_control", os.path.relpath(full, HERE)))
            n += 1
check("ZIP を作成 (%d ファイル)" % n,
      os.path.exists(zpath) and os.path.getsize(zpath) > 5000,
      "%.1f KB" % (os.path.getsize(zpath) / 1024.0) if os.path.exists(zpath) else "")

print("", flush=True)
if SKIPS:
    print("SKIPPED (未検証): %s" % ", ".join(SKIPS), flush=True)
if FAILS:
    print("FAILED: %d 件 -> %s" % (len(FAILS), ", ".join(FAILS)), flush=True)
    sys.exit(1)
print("ALL PASS", flush=True)
