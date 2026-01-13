# -*- mode: python ; coding: utf-8 -*-
import sys
import os

# プロジェクトのルートパスを取得
project_root = os.path.abspath(os.getcwd())

block_cipher = None

# --- OS別のバイナリ・データ設定 ---
if sys.platform == "win32":
    # Windows用設定
    engine_file = (os.path.join('bin', 'libvo_se.dll'), 'bin')
    icon_file = os.path.join('assets', 'icon.ico')
    # Open JTalk一式を同梱
    extra_datas = [
        (os.path.join('bin', 'open_jtalk'), os.path.join('bin', 'open_jtalk')),
        (os.path.join('models', 'onset_detector.onnx'), 'models'),
        ('voice_banks', 'voice_banks'),
        (os.path.join('assets', 'license.txt'), 'assets'),
    ]
elif sys.platform == "darwin":
    # macOS用設定
    engine_file = (os.path.join('bin', 'libvo_se.dylib'), 'bin')
    icon_file = os.path.join('assets', 'icon.icns')
    extra_datas = [
        (os.path.join('models', 'onset_detector.onnx'), 'models'),
        ('voice_banks', 'voice_banks'),
        (os.path.join('assets', 'license.txt'), 'assets'),
    ]
else:
    # Linux等（必要に応じて）
    engine_file = (os.path.join('bin', 'libvo_se.so'), 'bin')
    icon_file = None
    extra_datas = []

# --- 解析設定 ---
a = Analysis(
    ['main.py'],                 # エントリーポイント
    pathex=[project_root],
    binaries=[engine_file],      # CエンジンDLL
    datas=extra_datas,           # AIモデル、Open JTalk、音源、規約
    hiddenimports=[
        'onnxruntime',
        'numpy',
        'PySide6.QtCore',
        'PySide6.QtWidgets',
        'PySide6.QtGui',
        'PySide6.QtPrintSupport', # GUIの印刷/PDF書き出し等で必要になる場合がある
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --- 実行ファイル生成設定 ---
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VO-SE_Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,               # GUIアプリなので黒い画面（コンソール）は出さない
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

# --- フォルダへの収集設定 ---
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VO-SE_Pro',
)

# --- macOS専用：.appパッケージ化設定 ---
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name='VO-SE_Pro.app',
        icon=icon_file,
        bundle_identifier='com.vosepro.vocal-synth',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'CFBundleDocumentTypes': [
                {
                    'CFBundleTypeName': 'ZIP Archive',
                    'CFBundleTypeRole': 'Viewer',
                    'LSHandlerRank': 'Alternate',
                    'LSItemContentTypes': ['public.zip-archive']
                }
            ]
        },
    )
