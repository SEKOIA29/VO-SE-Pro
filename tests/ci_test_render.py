import ctypes
import os
import numpy as np

def test_engine():
    engine_path = os.environ.get('ENGINE_PATH', 'bin/vose_core.dll')
    if not os.path.exists(engine_path):
        raise FileNotFoundError(f"Engine not found at {engine_path}")

    # エンジンのロード
    lib = ctypes.CDLL(engine_path)
    
    # バージョンチェックなどの疎通確認
    # (ここに execute_render を1音だけ呼ぶコードを記述)
    print(f"✅ Engine loaded successfully: {engine_path}")
    
    # 将来的にはここで生成されたWAVのサイズが0でないか等をチェック
    return True

if __name__ == "__main__":
    if test_engine():
        print("🚀 CI Test Passed!")
    else:
        exit(1)
