import main


def test_runtime_requirement_check_reports_python_packages(monkeypatch):
    monkeypatch.setattr(main.platform, "system", lambda: "UnknownOS")
    monkeypatch.setattr(main, "find_spec", lambda module_name: None)

    missing = main._check_runtime_requirements()

    assert "Python package: PySide6" in missing
    assert "Python package: sounddevice" in missing
    assert "Python package: soundfile" in missing


def test_runtime_requirement_check_reports_linux_os_libraries(monkeypatch):
    monkeypatch.setattr(main.platform, "system", lambda: "Linux")
    monkeypatch.setattr(main, "find_spec", lambda module_name: object())
    monkeypatch.setattr(main, "_is_os_library_loadable", lambda library_name: False)

    missing = main._check_runtime_requirements()

    assert "OS library: libGL.so.1 (libgl1)" in missing
    assert "OS library: libxcb-cursor.so.0 (libxcb-cursor0)" in missing
    assert "OS library: libportaudio.so.2 (portaudio19-dev)" in missing


def test_runtime_requirement_check_skips_available_libraries(monkeypatch):
    monkeypatch.setattr(main.platform, "system", lambda: "Linux")
    monkeypatch.setattr(main, "find_spec", lambda module_name: object())
    monkeypatch.setattr(main, "_is_os_library_loadable", lambda library_name: True)

    assert main._check_runtime_requirements() == []


def test_runtime_requirement_check_skips_macos_bundled_os_libraries(monkeypatch):
    monkeypatch.setattr(main.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(main, "find_spec", lambda module_name: object())
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main, "_is_os_library_loadable", lambda library_name: False)

    assert main._check_runtime_requirements() == []
