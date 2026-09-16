# -*- coding: utf-8 -*-
"""android_helpers.py -- Android 専用の補助処理 (pyjnius).

すべて try/except で保護してあり、失敗してもアプリは動作を続ける。
デスクトップ (PC) では単に False / None を返す。
"""

from kivy.utils import platform

_locks = []


def acquire_locks():
    """Wi-Fi / マルチキャストのロックを取得する.

    画面が消えても UDP テレメトリと映像が届くようにするために必要。
    """
    if platform != "android":
        return False
    acquired = False
    try:
        from jnius import autoclass, cast
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        WifiManager = autoclass("android.net.wifi.WifiManager")
        activity = PythonActivity.mActivity
        wifi = cast("android.net.wifi.WifiManager",
                    activity.getSystemService(Context.WIFI_SERVICE))
        if wifi is None:
            return False
        try:
            lock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "tello:wifi")
        except Exception:
            lock = wifi.createWifiLock("tello:wifi")
        lock.setReferenceCounted(False)
        lock.acquire()
        _locks.append(lock)
        acquired = True
        try:
            mlock = wifi.createMulticastLock("tello:mcast")
            mlock.setReferenceCounted(False)
            mlock.acquire()
            _locks.append(mlock)
        except Exception:
            pass
    except Exception:
        return acquired
    return acquired


def release_locks():
    for lock in _locks:
        try:
            lock.release()
        except Exception:
            pass
    del _locks[:]


def keep_screen_on():
    """飛行中に画面が消えないようにする."""
    if platform != "android":
        return False
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
        PythonActivity.mActivity.getWindow().addFlags(LayoutParams.FLAG_KEEP_SCREEN_ON)
        return True
    except Exception:
        return False


def external_files_dir():
    """アプリ専用の外部フォルダ (PC から取り出しやすい). Android 以外は None.

    例: /storage/emulated/0/Android/data/<package>/files
    Android 11 以降はストレージ権限なしで読み書きできる。
    """
    if platform != "android":
        return None
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        f = PythonActivity.mActivity.getExternalFilesDir(None)
        if f is not None:
            return f.getAbsolutePath()
    except Exception:
        pass
    return None


def request_storage_permissions():
    """古い Android (10 以前) で /sdcard へ保存するための権限要求."""
    if platform != "android":
        return False
    try:
        from android.permissions import Permission, request_permissions
        request_permissions([Permission.WRITE_EXTERNAL_STORAGE,
                             Permission.READ_EXTERNAL_STORAGE])
        return True
    except Exception:
        return False
