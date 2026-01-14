# VO-SE Pro (Voice Synthesis Engine Professional)

VO-SE Pro は、Python による高度な日本語言語解析と、C言語による高速な信号処理を組み合わせた、ハイブリッド型の音声合成・音声処理プラットフォームです。

## 🚀 特徴

- **ハイブリッド設計**: ロジック制御と解析を Python、重い数値計算を C言語 (DLL/dylib) で分担。
- **日本語解析**: `pyopenjtalk` を内蔵し、フルコンテキストラベル（アクセントや音素情報）の抽出に対応。
- **クロスプラットフォーム**: Windows (.exe) および macOS (.app) の両環境に対応したビルド構成。
- **自動ビルド (CI/CD)**: GitHub Actions により、コードを Push するだけで実行バイナリを自動生成。

## 📂 プロジェクト構成

```text
VO-SE-Pro/
├── .github/workflows/
│   └── build.yml        # GitHub Actions による自動ビルド設定
├── src/
│   └── vo_se_engine.c   # C言語エンジンソース (音声処理の心臓部)
├── bin/
│   └── (libvo_se.dll)   # ビルド時に生成される動的ライブラリ
├── main.py              # Python メインロジック
├── vose_pro.spec        # PyInstaller パッケージ化設定
├── requirements.txt     # 依存ライブラリ一覧
└── README.md            # 本ドキュメント
