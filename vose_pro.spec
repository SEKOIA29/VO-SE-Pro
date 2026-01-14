# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import pyopenjtalk

block_cipher = None

# --- 1. 辞書とDLLの場所を自動特定（エラー回避ロジック） ---
added_files = []

try:
    # pyopenjtalkのインストール先を取得
    pyj_dir = os.path.dirname(pyopenjtalk.__file__)
    # 辞書フォルダ(dic)のパス候補
    dic_path = os.path.join(pyj_dir, "dic")
    
    if os.path.exists(dic_path):
        added_files.append((dic_path, 'pyopenjtalk/dic'))
        print(f"DEBUG: Dictionary found at {dic_path}")
    else:
        # フォルダがない場合はエラーにせず、ログだけ残す
        print("DEBUG: pyopenjtalk/dic NOT found. Skipping to avoid build error.")
except Exception as e:
    print(f"DEBUG: Error locating dictionary: {e}")

# Windows用CエンジンのDLL（存在する場合のみ追加）
if sys.platform == 'win32':
    dll_path = os.path.join('bin', 'libvo_se.dll')
    if os.path.exists(dll_path):
        added_files.append((dll_path, 'bin'))
        print(f"DEBUG: Added DLL from {dll_path}")
    else:
        print(f"DEBUG: DLL NOT found at {dll_path}")

# --- 2. ビルド設定 ---
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=added_files, # ここで安全なリストを渡す
    hiddenimports=['pyopenjtalk', 'numpy'],
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
    console=True, 
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
