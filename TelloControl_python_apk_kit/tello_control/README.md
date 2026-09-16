# Tello Control — スマホ用 Tello ドローン コントローラ (Python / Kivy)

パソコンで Python を書いて **Android スマホのアプリ (APK)** として配布するための一式です。
Ryze/DJI **Tello / Tello EDU** を Wi-Fi 経由 (UDP) で操作し、次の 4 機能を備えます。

| 機能 | 実装 | 内容 |
|---|---|---|
| **水平器** | `widgets.AttitudeIndicator` | テレメトリの `pitch` / `roll` / `yaw` からピッチラダー付き姿勢指示器を canvas 描画。右バンクで地平線が反時計回りに傾き、機首上げで地平線が下がる。機首方位 (HDG) も表示 |
| **高度・回転操作** | 左スティック + ボタン | メイン画面左スティック = **YAW(旋回) ↔ ALT(上昇/下降)**、右スティック = SIDE(左右) ↔ FWD/BACK。加えて `up/down 30`・`cw/ccw 45` による正確なステップ操作 |
| **緊急停止** | `TelloLink.emergency()` | 最下段の赤い大ボタン。**別ソケット**から `emergency` を送るので、コマンド応答待ちで詰まっていても必ず届く。`rc` 入力も同時にゼロ化。ソフト着陸は隣の LAND |
| **カメラ記録** | `streamon` + UDP 11111 受信 | Tello の H.264 映像を UDP 11111 で受け、`.h264` としてスマホに連続書き込み (録画時間・容量を REC インジケータに表示) |

> **注意 (設計上の前提)**: Tello は自機が Wi-Fi アクセスポイントになります。スマホは
> **`TELLO-xxxx` の Wi-Fi に接続**してからアプリを使います (この間スマホはインターネットに出られません)。
> 接続先は常に **192.168.10.1** 固定です。だから本アプリは外部ライブラリを一切使わず、
> 標準ライブラリの `socket` だけで完結させています (Android 上での依存地獄を避けるため)。

---

## 1. ファイル構成

```
tello_control/
├── main.py                 # 画面と操作ロジック (Kivy)  ← アプリ本体
├── tello.py                # Tello との UDP 通信 (標準ライブラリのみ / Kivy 非依存)
├── widgets.py              # 水平器・アナログ操縦桿 (canvas 描画)
├── android_helpers.py      # WifiLock / 画面常時点灯 / 保存先パス (pyjnius)
├── buildozer.spec          # APK ビルド設定 (権限・画面向き・API レベル)
├── main.kv                 # (空) KV は使わず Python 側で構築
├── fonts/                  # ↑任意: 日本語表示用フォントを置く (README 6 章)
├── tests/test_tello_link.py# 偽 Tello を立てる自動テスト (PC で実行)
└── .github/workflows/build.yml  # GitHub Actions で APK を自動ビルド
```

---

## 2. PC で動作確認する (実機・APK 不要)

```bash
python3 -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install kivy

cd tello_control
python tests/test_tello_link.py     # 通信ロジックの自動テスト (偽 Tello を起動)
python main.py                      # 画面の確認 (クリック/ドラッグでスティックが動く)
```

`tests/test_tello_link.py` は `127.0.0.1` に偽の Tello (UDP サーバ) を立て、
`command` 応答 / テレメトリ受信 / `rc` 10Hz 連続送信 / `streamon` 後の映像受信 /
`.h264` 録画ファイル生成 / `emergency` 送出 を順に検証します。
**実機なしで検証できるのはここまで**で、実際の飛行挙動は実機で確かめてください。

---

## 3. APK をビルドする

### 方法 A: Linux (ネイティブ) — いちばん素直

Ubuntu 22.04 以降を推奨。

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv \
                    autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
                    libncursesw5-dev libtinfo6 cmake libffi-dev libssl-dev

python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip setuptools
pip install "buildozer==1.5.0" cython

cd tello_control
buildozer android debug          # 初回は SDK/NDK を自動DLするため 20〜40 分
ls -lh bin/                      # telloctl-1.0.0-arm64-v8a_armeabi-v7a-debug.apk
```

### 方法 B: Windows / macOS — Docker を使う (推奨)

Buildozer は Linux 前提なので、Docker で Linux 環境を用意するのが最も失敗が少ない方法です。

```bash
# リポジトリのルートで
docker run --rm -v "$PWD":/home/user/hostcwd \
  -v "$HOME/.buildozer":/home/user/.buildozer \
  kivy/buildozer:latest android debug
```

### 方法 C: GitHub Actions — 手元に環境を作らず APK を得る (最も簡単)

`.github/workflows/build.yml` をそのまま使えます。GitHub に push すると APK が
**Actions の Artifacts** からダウンロードできます。

```yaml
name: Build APK
on: [push, workflow_dispatch]

jobs:
  build-android:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build with Buildozer
        uses: ArtemSBulgakov/buildozer-action@v1
        id: buildozer
        with:
          command: buildozer android debug
          workdir: .                 # buildozer.spec のあるディレクトリ
          buildozer_version: stable
      - uses: actions/upload-artifact@v4
        with:
          name: apk
          path: ${{ steps.buildozer.outputs.filename }}
```

> **リポジトリのルート = `buildozer.spec` のあるディレクトリ** にしてください。
> 本キットをそのまま GitHub に push すればそのままビルドできます。

---

## 4. スマホへ配布 (インストール) する

1. ビルドで得た `bin/telloctl-1.0.0-...-debug.apk` をスマホへ移す
   (USB / Google Drive / メールなど何でも可)。
2. スマホの「設定 → アプリ → 提供元不明のアプリ」で、ファイルアプリにインストール許可を与える。
3. APK をタップしてインストール (Play ストアを通さないため「提供元不明」の警告が出るが正常)。
4. 起動後、初回にストレージ権限のダイアログが出たら許可。

### 配布を本格化する場合 (release ビルド)

```bash
# キーストア作成
keytool -genkey -v -keystore tello.keystore -alias tello -keyalg RSA -keysize 2048 -validity 10000

# buildozer.spec に追記
#   android.release_artifact = apk
#   android.keystore = /absolute/path/tello.keystore
#   android.keystore_passwd = ****
#   android.keyalias = tello
#   android.keyalias_passwd = ****

buildozer android release        # bin/ に署名済み APK が出る
```

署名済み **zip 化** した APK を Google Drive 等に置けば、リンクを配るだけでインストールできます。
(Play ストア配布なら `.aab`。`android.release_artifact = aab` に変更して `buildozer android release`)

---

## 5. 操作方法 (アプリ画面)

| 場所 | 操作 | 動作 |
|---|---|---|
| 右上 | `CONNECT` | Tello へ UDP 接続し SDK モード開始 (`command`) |
| 右上 | `STREAM ON/OFF` | 映像ストリーム開始/停止 (`streamon` / `streamoff`) |
| 右上 | `● REC / ■ STOP REC` | 映像を `.h264` として録画開始/停止 |
| 右上 | `▲ +30cm` / `▼ -30cm` | 高度を 30cm 上げる / 下げる (正確な上下移動) |
| 右上 | `↺ 45°` / `↻ 45°` | 左 / 右へ 45° 旋回 |
| 右上 | `HOLD (rc 0)` | 操縦入力を 0 に戻す (ホバリング) |
| 右上 | 速度リミッタ | スティック出力の上限 (%) を制限。初心者は 40〜60% 推奨 |
| 左スティック | 上下 / 左右 | **ALT (上昇・下降)** / **YAW (左・右旋回)** |
| 右スティック | 上下 / 左右 | **FWD/BACK (前進・後退)** / **SIDE (左・右移動)** |
| 左下 | `TAKE OFF` | 自動離陸 (`takeoff`) |
| 中下 | `LAND` | 自動着陸 (`land`) — **通常はこちら** |
| 右下 | `■ EMERGENCY STOP` | モーター即停止 (`emergency`) — 衝突回避の最終手段 |

**安全のための実装**
- スティックから指を離すと必ず値が 0 に戻ります (`on_touch_up`)。入力が抜けたまま機体が流れる事故を防ぎます。
- `rc` は操縦入力が 0 でも **10Hz で送信し続けます**。Tello は 15 秒間コマンドが無いと自動着陸する仕様なので、これがキープアライブを兼ねます。
- バッテリー残量が 20% 未満になるとステータスバーの `BAT` が赤くなります。
- アプリ終了時 (`on_stop`) は**飛行中なら自動着陸**を送ってから切断します。
- テレメトリが 1.5 秒以上途切れると `LINK: NO TELEM` を表示し、機首方位表示を灰色に落とします (古い値を信じない設計)。

---

## 6. 日本語を表示したい場合

同梱フォントを入れない場合、画面は英字のみ (Kivy 既定の Roboto は日本語グリフを持たないため)。
日本語ログ・日本語ラベルを出したいときは、**SIL Open Font License** のフォントを
`fonts/NotoSansJP-Regular.otf` として置いてください (ライセンス条件を必ず確認のこと)。

```bash
mkdir -p tello_control/fonts
# 入手した NotoSansJP-Regular.otf を tello_control/fonts/ へコピー
```

`main.py` の `register_font()` が自動検出して全ラベル・水平器に適用します。
(`buildozer.spec` の `source.include_exts` に `otf,ttf` を既に含めてあります)

---

## 7. トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| `応答がありません` | スマホが `TELLO-xxxx` の Wi-Fi に接続されていない。設定で一度接続し、モバイルデータ通信を OFF にする |
| 接続直後は動くが数十秒で切れる | 画面消灯で Wi-Fi が省電力に入っている。本アプリは WifiLock を取得しますが、端末設定「Wi-Fi を常に有効」も確認 |
| テレメトリが来ない (`LINK: NO TELEM`) | 8890 番ポートが他アプリに占有されている。Tello 公式アプリ等を終了してから起動 |
| 映像が乱れる | Tello の映像は H.264 で、電波状況に敏感。スマホと機体の距離を縮める |
| ビルドが `android.api` で失敗 | 手元の Buildozer/SDK が対応する値に `android.api` を下げる (例 `33`) |
| ビルドが `armeabi-v7a` で失敗 | `android.archs = arm64-v8a` のみにする (最近のスマホはこれで動く) |
| ストレージ権限で失敗 | Android 11 以降はアプリ専用領域 (`Android/data/<package>/files/videos`) に保存され、権限不要。PC からはファイルアプリで取り出せる |

---

## 8. 検証済み / 未検証

**検証済み (PC 上で実行)**
- 全モジュールの構文チェックと Kivy による `main.py` の import
- `tests/test_tello_link.py`: 偽 Tello に対する接続・応答・テレメトリ・`rc` 送出・
  映像受信・`.h264` 録画ファイル生成・`emergency` 送出

**未検証 (実機が必要)**
- 実機 Tello との飛行、実空での水平器の追従、映像の実時間表示、APK ビルドそのもの

---

## 9. 参考資料

- [Tello SDK 2.0 User Guide (PDF)](https://dl-cdn.ryzerobotics.com/downloads/Tello/Tello%20SDK%202.0%20User%20Guide.pdf) — ポート番号・`rc`・`emergency`・15 秒自動着陸の仕様
- [Buildozer 公式ドキュメント (specifications)](https://buildozer.readthedocs.io/en/latest/specifications.html) — `android.permissions` / `orientation` / `source.include_exts`
- [Buildozer リポジトリ](https://github.com/kivy/buildozer) / [公式 Docker イメージ](https://hub.docker.com/r/kivy/buildozer)
- [Buildozer Action (GitHub Actions)](https://github.com/marketplace/actions/buildozer-action) — クラウドで APK をビルド
- [Kivy on Android (pyjnius)](https://kivy.org/doc/stable/guide/android.html) — Java API 呼び出しの仕組み
