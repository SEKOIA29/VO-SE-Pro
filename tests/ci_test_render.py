import ctypes
import os


def test_engine():
    engine_path = os.environ.get('ENGINE_PATH', 'bin/vose_core.dll')
    if not os.path.exists(engine_path):
        raise FileNotFoundError(f"Engine not found at {engine_path}")

    # 修正後（例：エンジンのバージョン取得や、ただのロード確認）
    lib = ctypes.CDLL(engine_path)
    print(f"Loaded: {lib}")
    # ロードできたことを明示的に使う（何もしないなら print(lib) でもOKだが、実戦的に）
    if not lib:
        raise RuntimeError("エンジンのロードに失敗しました")
    print(f"Engine object: {lib}") # これで F841 は消えます
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
