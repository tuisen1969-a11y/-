[app]

# ---- アプリ情報 -------------------------------------------------------------
title = Tello Control
package.name = telloctl
package.domain = org.example

# ソースはこのディレクトリ
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,txt,md,otf,ttf,spec

version = 1.0.0

# 依存は Kivy のみ (Tello との通信は標準ライブラリの socket で行う)
requirements = python3,kivy

# ---- 画面 -------------------------------------------------------------------
# 横画面。ステータスバーを隠さない (fullscreen = 0) と Wi-Fi 状態が確認しやすい
orientation = landscape
fullscreen = 0

# ---- Android 権限 -----------------------------------------------------------
# INTERNET               : UDP ソケット (必須)
# ACCESS_WIFI_STATE      : Wi-Fi 状態の取得 / WifiLock
# ACCESS_NETWORK_STATE   : 接続状態の確認
# CHANGE_WIFI_MULTICAST_STATE : MulticastLock (取りこぼし防止)
# WAKE_LOCK              : 画面 OFF 中も通信を維持
# WRITE/READ_EXTERNAL_STORAGE : Android 10 以前で /sdcard へ録画保存する場合
# ※ カメラ権限は不要 (撮影するのは Tello 側のカメラ)
android.permissions = INTERNET,ACCESS_WIFI_STATE,ACCESS_NETWORK_STATE,CHANGE_WIFI_MULTICAST_STATE,WAKE_LOCK,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# ---- SDK / NDK --------------------------------------------------------------
# android.api は手元の buildozer が対応する値に合わせて調整してください
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
# android.ndk = 25b        # 未指定なら buildozer の既定値が使われる (推奨)

android.accept_sdk_license = True
android.allow_backup = False
android.wakelock = True

# ---- ログ (デバッグ時は 2) --------------------------------------------------
log_level = 2
