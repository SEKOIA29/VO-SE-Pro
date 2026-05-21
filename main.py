# main.py
import sys
import os
import platform
import ctypes
import ctypes.util
import json

import importlib
from importlib.util import find_spec


# --- [1] リソースパス解決関数 (PyInstaller対応) ---
def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_engine_library_path():
    system = platform.system()
    if system == "Windows":
        lib_names = ("vose_core.dll",)
    elif system == "Darwin":
        lib_names = ("libvose_core.dylib", "vose_core.dylib")
    else:
        lib_names = ("libvose_core.so", "vose_core.so")

    for lib_name in lib_names:
        dll_path = get_resource_path(os.path.join("bin", lib_name))
        if os.path.exists(dll_path):
            return dll_path

    return get_resource_path(os.path.join("bin", lib_names[0]))


# --- [2] 設定管理クラス (ConfigHandler) ---
class ConfigHandler:
    def __init__(self, config_path="temp/config.json"):
        self.config_path = config_path
        self.default_config = {
            "last_save_dir": os.path.expanduser("~"),
            "default_voice": "mei_normal",
            "volume": 0.8
        }

    def load_config(self):
        if not os.path.exists(self.config_path):
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            self.save_config(self.default_config)
            return self.default_config
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return self.default_config

    def save_config(self, config_dict):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Config save error: {e}")


# --- [3] エンジンクラス (VoSeEngine) ---
class VoSeEngine:
    def __init__(self):
        self.os_name = platform.system()
        self.c_engine = None
        self._load_c_engine()

    def _load_c_engine(self):
        """
        OSに応じたライブラリ（DLL/dylib）を最適なパスからロードします。
        型チェックエラー（_MEIPASS）を回避し、Mac実機構造に対応した完全版です。
        """
        # 1. 基本的なリソースパス
        dll_path = get_engine_library_path()

        # 2. Mac特有のフォールバック処理
        if self.os_name == "Darwin":
            if not os.path.exists(dll_path):
                meipass = getattr(sys, '_MEIPASS', None)
                if meipass:
                    bundle_dir = os.path.dirname(os.path.dirname(meipass))
                    alt_path = os.path.join(bundle_dir, "Frameworks", "bin", os.path.basename(dll_path))
                    if os.path.exists(alt_path):
                        dll_path = alt_path
                        print(f"[Info] Mac Frameworks path used: {dll_path}")

        # 3. 最終的なロード実行
        if os.path.exists(dll_path):
            try:
                abs_dll_path = os.path.abspath(dll_path)

                if self.os_name == "Windows":
                    self.c_engine = ctypes.CDLL(abs_dll_path)
                else:
                    self.c_engine = ctypes.CDLL(abs_dll_path, mode=10)  # RTLD_GLOBAL

                # --- C関数の型定義 (歌唱・読み上げの両方に対応) ---
                if hasattr(self.c_engine, 'process_voice'):
                    self.c_engine.process_voice.argtypes = [
                        ctypes.POINTER(ctypes.c_float),
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_float)
                    ]
                    self.c_engine.process_voice.restype = None

                print(f"[Success] C-Engine loaded: {abs_dll_path}")
            except Exception as e:
                print(f"[Error] Failed to load C-Engine: {e}")
                if hasattr(sys, 'stderr'):
                    import traceback
                    traceback.print_exc()
                self.c_engine = None  # 失敗時は明示的に None を保証
        else:
            # [FIX-1] 警告のみで続行せず、理由を明記したうえで None を確定する
            # main() 側で QMessageBox.warning を表示するため、ここでは print のみ
            print(f"[Warning] C-Engine file not found at: {dll_path}")
            self.c_engine = None  # 明示的に None を保証（後続クラッシュ防止）

    def analyze_intonation(self, text):
        """【読み上げ用】音韻解析"""
        print(f"\n--- 読み上げ解析実行: '{text}' ---")
        try:
            pyopenjtalk = importlib.import_module("pyopenjtalk")
            labels = pyopenjtalk.extract_fullcontext(text)
            return labels
        except Exception as e:
            return [f"Analysis failed: {str(e)}"]

    def analyze_singing_pitch(self, notes, sample_rate=48000, frame_period_ms=5.0):
        """
        【歌唱用】ノート列からF0カーブを生成する。
        notes: [{'note_number': 60, 'duration': 0.5}, ...] を想定。
        pitch / note も受け付ける。
        """
        print("--- 歌唱ピッチ解析実行 ---")
        np = importlib.import_module("numpy")
        
        if not notes:
            return np.zeros(1, dtype=np.float32)

        frame_sec = max(frame_period_ms / 1000.0, 1e-4)
        min_hz = 20.0
        max_hz = 5000.0

        hz_segments = []
        for note in notes:
            duration = float(note.get("duration", 0.0) or 0.0)
            if duration <= 0:
                continue

            midi_note = note.get("note_number", note.get("pitch", note.get("note", 69)))
            try:
                midi_value = float(midi_note)
            except (TypeError, ValueError):
                midi_value = 69.0

            hz = 440.0 * (2.0 ** ((midi_value - 69.0) / 12.0))
            hz = min(max(hz, min_hz), max_hz)

            frame_count = max(1, int(round(duration / frame_sec)))
            hz_segments.append(np.full(frame_count, hz, dtype=np.float32))

        if not hz_segments:
            return np.zeros(1, dtype=np.float32)

        f0_curve = np.concatenate(hz_segments)

        # ノート境界を滑らかに補間（簡易ポルタメント）
        smooth_window = max(1, int(round(0.03 / frame_sec)))  # 約30ms
        if smooth_window > 1 and len(f0_curve) > smooth_window:
            kernel = np.hanning(smooth_window)
            kernel_sum = float(kernel.sum())
            if kernel_sum > 0:
                kernel /= kernel_sum
                f0_curve = np.convolve(f0_curve, kernel, mode='same').astype(np.float32)
        return f0_curve

    def process_with_c(self, data_array, f0_array=None):
        """
        【共通処理】波形データとピッチデータをC++エンジンに送り込みます。
        """
        if not self.c_engine or not hasattr(self.c_engine, 'process_voice'):
            print("[Warning] C-Engine not available, skipping processing")
            return data_array

        try:
            np = importlib.import_module("numpy")

            # 波形データの準備
            wav_float = np.ascontiguousarray(data_array, dtype=np.float32)
            wav_ptr = wav_float.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            length = len(wav_float)

            # [FIX-2] f0_float を明示的に保持し、GCによるダングリングポインタを防ぐ
            f0_float = None
            f0_ptr = None
            if f0_array is not None:
                f0_float = np.ascontiguousarray(f0_array, dtype=np.float32)
                f0_ptr = f0_float.ctypes.data_as(ctypes.POINTER(ctypes.c_float))

            # C++エンジンの呼び出し
            # wav_float・f0_float はこのスコープを抜けるまで生存が保証される
            self.c_engine.process_voice(wav_ptr, length, f0_ptr)

            # [FIX-3] wav_float を返すことで GC による早期解放を防ぐ
            return wav_float

        except Exception as e:
            print(f"C-Process error: {e}")
            return data_array


def _check_runtime_requirements():
    """
    起動前に実行環境をチェックし、足りない要件をユーザーへ明示する。
    """
    missing = []

    for module_name in ("numpy", "pyopenjtalk", "PySide6"):
        if find_spec(module_name) is None:
            missing.append(f"Python package: {module_name}")
    
    # Linux では PySide6 が libGL.so.1 を必要とするため、先に明示的に確認する
    if platform.system() == "Linux":
        libgl_path = ctypes.util.find_library("GL")
        if not libgl_path:
            missing.append("OS library: libGL.so.1 (mesa-libGL)")
        else:
            try:
                ctypes.CDLL(libgl_path)
            except OSError:
                missing.append("OS library: libGL.so.1 (mesa-libGL)")

    return missing


# --- [4] メイン実行処理 ---
def main():
    missing = _check_runtime_requirements()
    if missing:
        print("[Fatal] 起動に必要な依存関係が不足しています。")
        for item in missing:
            print(f"  - {item}")
        print("requirements.txt と OS 依存ライブラリをインストールして再実行してください。")
        if platform.system() == "Linux":
            print("例: Ubuntu/Debian -> sudo apt-get install -y libgl1")
        sys.exit(1)

    # Linuxヘッドレス環境（DISPLAYなし）では offscreen を既定にして起動を継続
    if platform.system() == "Linux":
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            print("[Info] Linux headless mode detected. QT_QPA_PLATFORM=offscreen を使用します。")

    try:
        QtWidgets = importlib.import_module("PySide6.QtWidgets")
        QtGui = importlib.import_module("PySide6.QtGui")
        QtCore = importlib.import_module("PySide6.QtCore")
    except Exception as e:
        print(f"[Fatal] GUI モジュールの読み込みに失敗しました: {e}")
        sys.exit(1)

    try:
        MainWindow = importlib.import_module("modules.gui.main_window").MainWindow
    except Exception as e:
        print(f"[Fatal] メインウィンドウの読み込みに失敗しました: {e}")
        if hasattr(sys, "stderr"):
            import traceback
            traceback.print_exc()
        sys.exit(1)

    QApplication = QtWidgets.QApplication
    QMessageBox = QtWidgets.QMessageBox
    QIcon = QtGui.QIcon
    QTimer = QtCore.QTimer
    Qt = QtCore.Qt

    app = QApplication(sys.argv)
    app.setApplicationName("VO-SE Pro")

    for icon_rel in ("assets/icon.png", "assets/icon.icns", "assets/icon.ico"):
        icon_path = get_resource_path(icon_rel)
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break
    # [FIX-1] DLL未検出時は warning ダイアログで明示。エラーではなく warning に留め、
    #         アプリは起動継続（合成・歌唱機能のみ無効化）とする。
    dll_path = get_engine_library_path()
    if not os.path.exists(dll_path):
        QMessageBox.warning(
            None,
            "コアエンジン未検出",
            f"VO-SE Core Engine が見つかりません。\n"
            f"音声合成・歌声合成機能は利用できません。\n\n"
            f"期待されるパス:\n{dll_path}"
        )

    config_handler = ConfigHandler()
    config = config_handler.load_config()
    engine = VoSeEngine()

    try:
        window = MainWindow()
    except Exception as e:
        QMessageBox.critical(None, "起動エラー", f"メイン画面の初期化でエラーが発生しました。\n{e}")
        if hasattr(sys, "stderr"):
            import traceback
            traceback.print_exc()
        sys.exit(1)

    window.vo_se_engine = engine
    window.config = config

    # ステータスバーの状態を動的に更新（MainWindowにupdate_statusメソッドがあると仮定）
    if engine.c_engine:
        window.statusBar().showMessage("VO-SE Core Engine: Ready")
    else:
        window.statusBar().showMessage("VO-SE Core Engine: Not Found (Offline Mode)")

    def show_main_window():
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()
        window_handle = window.windowHandle()
        if window_handle is not None:
            window_handle.requestActivate()

    def release_startup_frontmost_hint():
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        show_main_window()

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    show_main_window()
    QTimer.singleShot(0, show_main_window)
    QTimer.singleShot(300, show_main_window)
    QTimer.singleShot(1200, release_startup_frontmost_hint)

    result = app.exec()
    config_handler.save_config(config)
    sys.exit(result)


if __name__ == "__main__":
    main()
