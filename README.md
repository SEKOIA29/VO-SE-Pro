# VO-SE Pro (Voice Synthesis Engine Professional)

VO-SE Pro は、Python による高度な日本語言語解析と、C言語による高速な信号処理を組み合わせた、ハイブリッド型の音声合成・音声処理プラットフォームです。

## 🚀 特徴

- **ハイブリッド設計**: ロジック制御と解析を Python、重い数値計算を C言語 (DLL/dylib) で分担。
- **日本語解析**: `pyopenjtalk` を内蔵し、フルコンテキストラベル（アクセントや音素情報）の抽出に対応。
- **クロスプラットフォーム**: Windows (.exe) および macOS (.app) の両環境に対応したビルド構成。
- **自動ビルド (CI/CD)**: GitHub Actions により、コードを Push するだけで実行バイナリを自動生成。

## 📂 プロジェクト構成

```text
VO-SE_Pro/
├── .github/                    # GitHub自動化設定
│   └── workflows/
│       └── build.yml           # GitHub Actions用ビルド定義
├── assets/                     # デザイン・法務資産
│   ├── icon.ico                # Windows用アイコン (256x256)
│   ├── icon.icns               # macOS用アイコン
│   ├── splash.png              # 起動時のスプラッシュ画像
│   └── license.txt             # ユーザーへの利用規約
├── bin/                        # ビルド済みバイナリ（AppInitializerがここをチェック）
│   ├── libvo_se.dll            # Windows用エンジン (ビルド後に生成)
│   └── libvo_se.dylib          # macOS用エンジン (ビルド後に生成)
├
├── modules/                    # Pythonプログラム（中身）
│    ├── __init__.py
│   │
│   ├── ai/                     # 【AI解析担当】
│   │   ├── __init__.py
│   │   ├── ai_manager.py          # ONNXモデルのロードと推論実行
│   │   
│   │
│   ├── auodio/                 # 【C言語連携担当】
│   │   ├── __init__.py
│   │   ├──voice_manager.py
│   │   ├──vo_se_engine.py
│   │   └── audio_output.py
│   │
│   ├── talk/                   # 【喋り（Open JTalk）担当】
│   │   ├── __init__.py
│   │   └── talk_manager.py     # subprocessによるOpen JTalk制御
│   │
│   ├── gui/                    # 【UI/画面表示担当】
│   │   ├── __init__.py
│   │   ├── main_window.py      # メイン画面とメニューバー
│   │   ├── app_main.py 
│   │   ├──timeline_widget.py      
│   │   ├──widgets.py
│   │   ├── graph_editor_widgetl.py     
│   │   └── keyboard_sidebar_widget.py         
│   │
│   ├── data/                    # 【UI/画面表示担当】
│   │   ├── __init__.py
│   │   ├── data_models.py     #
│   │   ├── midi_manager.py     # midi
│   │   ├── talk_panel.py       # 
│   │   └── text_analyzer.py         # 
│
│   │
│   └── utils/                  # 【共通ツール担当】
│       ├── __init__.py
│       ├── initializer.py      # 起動時のファイル存在チェック
│       ├── config_handler.py   # 設定(json)の保存・読み込み
│       └── zip_handler.py      # ZIPインポートの解凍処理
│   
├── src/                        # C言語エンジン（中身）
│   ├── vo_se_engine.c          # エンジンメインソース
│   └── vo_se_engine.h          # 構造体定義ヘッダー
├── voice_banks/                # 歌声ライブラリ
│   └── default_voice/          # サンプル音源フォルダ
│       ├── oto.ini             # 原音設定ファイル
│       └── a.wav               # 各種音声データ
├── output/                     # 合成された音声の保存先（自動生成）
├── temp/                       # 作業用一時フォルダ（自動生成）
├── .gitignore                  # Git管理から除外するリスト
├── main.py                     # アプリ起動エントリポイント
├── Makefile                    # ローカルビルド用コマンド集（未実装）
├── README.md                   # 開発者・ユーザー向け説明書
├── requirements.txt            # Pythonライブラリ依存リスト
└── vose_pro.spec               # PyInstallerパッケージング定義

