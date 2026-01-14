# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import pyopenjtalk

block_cipher = None

# 1. pyopenjtalkのインストールディレクトリから辞書の場所を自動特定
# これにより、GitHub Actions環境でもあなたのMac環境でも正しく辞書を拾えます
pyopenjtalk_dir = os.path.dirname(pyopenjtalk.__file__)
dic_path = os.path.join(pyopenjtalk_dir, "dic")

# 2. 同梱するファイルのリストを作成
# (元ファイルパス, 実行ファイル内での展開先フォルダ)
added_files = [
    (dic_path, 'pyopenjtalk/dic'), # Open JTalk辞書データ
]

# Windowsビルドの場合のみ、CエンジンのDLLを含める
if sys.platform == 'win32':
    added_files.append(('bin/libvo_se.dll', 'bin'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=['pyopenjtalk'], # 動的ロードに備えて明示
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
    console=True,  # 開発中はエラーログが見えるようTrueに設定。完成時はFalseへ
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

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
