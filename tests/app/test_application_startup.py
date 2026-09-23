from __future__ import annotations

import sys

import pytest

import pogled_assist.main as main_module
from pogled_assist import app_icon
from pogled_assist.windows import dpi


def test_app_icon_finds_project_asset_and_returns_empty_icon_when_missing(monkeypatch, tmp_path):
    root = tmp_path / "app"
    icon = root / "assets" / "icon.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"not a real image")
    monkeypatch.setattr(app_icon, "get_project_root", lambda: root)

    assert app_icon.app_icon_path() == icon

    icon.unlink()
    monkeypatch.setattr(app_icon, "__file__", str(tmp_path / "package" / "app_icon.py"))
    assert app_icon.app_icon_path() is None
    assert app_icon.load_app_icon().isNull()


def test_app_icon_prefers_frozen_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    icon = bundle / "assets" / "icon.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"icon")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(app_icon, "get_project_root", lambda: tmp_path / "other")

    assert app_icon.app_icon_path() == icon


def test_dpi_awareness_uses_modern_api_then_falls_back(monkeypatch):
    calls = []

    class Shcore:
        def SetProcessDpiAwareness(self, value):
            calls.append(("modern", value))

    class User32:
        def SetProcessDPIAware(self):
            calls.append(("fallback", None))

    monkeypatch.setattr(dpi.sys, "platform", "win32")
    monkeypatch.setattr(
        "ctypes.windll",
        type("Windll", (), {"shcore": Shcore(), "user32": User32()})(),
        raising=False,
    )
    dpi.enable_windows_dpi_awareness()
    assert calls == [("modern", 2)]

    calls.clear()

    class BrokenShcore:
        def SetProcessDpiAwareness(self, _value):
            raise OSError("unsupported")

    monkeypatch.setattr(
        "ctypes.windll",
        type("Windll", (), {"shcore": BrokenShcore(), "user32": User32()})(),
        raising=False,
    )
    dpi.enable_windows_dpi_awareness()
    assert calls == [("fallback", None)]


@pytest.mark.parametrize(
    ("arguments", "simulate_gaze"),
    [([], False), ([main_module.MOUSE_GAZE_SIMULATION_ARG], True)],
)
def test_main_builds_and_runs_application(monkeypatch, tmp_path, arguments, simulate_gaze):
    import PySide6.QtWidgets

    from pogled_assist import toolbar

    calls = []
    test_app = PySide6.QtWidgets.QApplication.instance()

    class FakeIcon:
        def isNull(self):
            return False

    class FakeApp:
        def __init__(self, args):
            calls.append(("app", args))

        def setApplicationName(self, name):
            calls.append(("name", name))

        def setOrganizationName(self, name):
            calls.append(("org", name))

        def setWindowIcon(self, _icon):
            calls.append(("app_icon", True))

        def exec(self):
            return 17

        @staticmethod
        def instance():
            return test_app

    class FakeWindow:
        def __init__(self, *, simulate_gaze=False):
            calls.append(("simulate_gaze", simulate_gaze))

        def setWindowIcon(self, _icon):
            calls.append(("window_icon", True))

        def show(self):
            calls.append(("show", True))

    monkeypatch.setattr(
        main_module, "setup_application_logging", lambda: calls.append(("logging", True))
    )
    monkeypatch.setattr(
        main_module, "enable_windows_dpi_awareness", lambda: calls.append(("dpi", True))
    )
    monkeypatch.setattr(
        main_module, "install_qt_message_handler", lambda: calls.append(("qt_logging", True))
    )
    monkeypatch.setattr(PySide6.QtWidgets, "QApplication", FakeApp)
    monkeypatch.setattr(app_icon, "load_app_icon", FakeIcon)
    monkeypatch.setattr(app_icon, "app_icon_path", lambda: tmp_path / "icon.png")
    monkeypatch.setattr(toolbar, "HotbarWindow", FakeWindow)
    monkeypatch.setattr(main_module.sys, "argv", ["run_gaze_mouse.py", *arguments])

    assert main_module.main() == 17
    assert ("show", True) in calls
    assert ("name", "Pogled Assist") in calls
    assert ("org", "Pogled Assist") in calls
    assert ("simulate_gaze", simulate_gaze) in calls


def test_frozen_application_rejects_mouse_gaze_simulation(monkeypatch, capsys):
    monkeypatch.setattr(main_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        main_module.sys,
        "argv",
        ["PogledAssist.exe", main_module.MOUSE_GAZE_SIMULATION_ARG],
    )

    assert main_module.main() == 2
    assert "only from a development checkout" in capsys.readouterr().out


def test_main_routes_package_smoke_test_without_starting_gui(monkeypatch):
    monkeypatch.setattr(main_module.sys, "argv", ["PogledAssist.exe", "--package-smoke-test"])
    monkeypatch.setattr(main_module, "package_smoke_test", lambda: 23)

    assert main_module.main() == 23
