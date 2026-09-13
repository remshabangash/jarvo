"""Mocked tests for the OS resolver modules.

Windows resolver runs real on this machine, so its filesystem-touching
helpers are tested with monkeypatched os.walk / subprocess. macOS and Linux
modules are exercised through imports (module-level code must be valid on
any OS) plus mocked subprocess/webbrowser for their launch functions.
"""
import subprocess
import sys
from types import SimpleNamespace

import pytest

import app_resolver._common as common
from app_resolver import windows


@pytest.fixture
def no_focus(monkeypatch):
    """winfocus is a real Windows API call — never run it in tests."""
    calls = []
    monkeypatch.setattr(windows.winfocus, "bring_to_front_async",
                        lambda *a, **k: calls.append(a))
    return calls


class TestWindowsGuards:
    def test_empty_name(self, no_focus):
        assert windows.resolve_and_open("").startswith("Error:")

    def test_not_an_app(self, no_focus):
        assert windows.resolve_and_open("screenshot").startswith("Error:")

    def test_url_map_short_circuit(self, no_focus, monkeypatch):
        opened = []
        monkeypatch.setattr(windows.webbrowser, "open", lambda u: opened.append(u))
        assert windows.resolve_and_open("youtube") == "Opened youtube"
        assert opened == ["https://www.youtube.com"]

    def test_domain_opens_browser(self, no_focus, monkeypatch):
        opened = []
        monkeypatch.setattr(windows.webbrowser, "open", lambda u: opened.append(u))
        assert windows.resolve_and_open("example.com").endswith("in browser")
        assert opened == ["https://example.com"]

    def test_startmenu_exact_match_launches(self, no_focus, monkeypatch):
        launched = []
        monkeypatch.setattr(windows, "_start_menu_apps",
                            lambda: {"notepad plus": "C:/lnk/notepad++.lnk"})
        monkeypatch.setattr(windows.os, "startfile",
                            lambda p: launched.append(p), raising=False)
        assert windows.resolve_and_open("notepad plus") == "Opened notepad plus"
        assert launched == ["C:/lnk/notepad++.lnk"]

    def test_exe_fallback(self, no_focus, monkeypatch):
        launched = []
        monkeypatch.setattr(windows, "_start_menu_apps", lambda: {})
        monkeypatch.setattr(windows.os, "startfile",
                            lambda p: launched.append(p), raising=False)
        assert windows.resolve_and_open("notepad") == "Opened notepad"
        assert launched == ["notepad.exe"]

    def test_unknown_goes_to_web_search(self, no_focus, monkeypatch):
        searched = []
        monkeypatch.setattr(windows, "_start_menu_apps", lambda: {})
        import executor
        monkeypatch.setattr("executor.web_search", lambda q: searched.append(q))
        reply = windows.resolve_and_open("zzz-unknown-zzz")
        assert "search khol di" in reply
        assert searched and searched[0].startswith("zzz-unknown-zzz")


class TestWindowsUwpLookup:
    def test_cache_parses_powershell_output(self, monkeypatch):
        fake = subprocess.CompletedProcess([], 0,
            stdout="Notepad|abc123\nCalculator|xyz789\n", stderr="")
        monkeypatch.setattr(windows.subprocess, "run", lambda *a, **k: fake)
        windows._UWP_CACHE = None  # force re-scan
        assert windows._uwp_lookup("notepad") == "shell:AppsFolder\\abc123"
        assert windows._uwp_lookup("calculator").endswith("xyz789")
        windows._UWP_CACHE = None  # restore for other tests


class TestMacosResolver:
    def test_module_logic_offline(self, monkeypatch):
        if "app_resolver.macos" not in sys.modules:
            pytest.skip("non-darwin machine: module logic tested via import only")
        import app_resolver.macos as macos
        opened = []
        monkeypatch.setattr(macos.webbrowser, "open", lambda u: opened.append(u))
        assert macos.resolve_and_open("youtube") == "Opened youtube"
        monkeypatch.setattr(macos.subprocess, "run",
                            lambda *a, **k: SimpleNamespace(returncode=0))
        assert macos.resolve_and_open("safari") == "Opened safari"

    def test_app_names_table(self):
        # table must exist and be sane regardless of OS
        from app_resolver.macos import _APP_NAMES
        assert _APP_NAMES["chrome"] == "Google Chrome"
        assert _APP_NAMES["terminal"] == "Terminal"


class TestLinuxResolver:
    def test_module_logic_offline(self, monkeypatch):
        import app_resolver.linux as linux
        opened = []
        monkeypatch.setattr(linux.webbrowser, "open", lambda u: opened.append(u))
        assert linux.resolve_and_open("youtube") == "Opened youtube"

    def test_desktop_parse_and_launch(self, monkeypatch, tmp_path):
        import app_resolver.linux as linux
        d = tmp_path / "applications"
        d.mkdir()
        (d / "vlc.desktop").write_text(
            "[Desktop Entry]\nName=VLC\nExec=/usr/bin/vlc\nType=Application\n")
        monkeypatch.setattr(linux, "_XDG_DIRS", [str(d)])
        linux._DESKTOP_CACHE = None
        apps = linux._desktop_apps()
        assert apps["vlc"][0] == "VLC"
        monkeypatch.setattr(linux.subprocess, "run",
                            lambda *a, **k: SimpleNamespace(returncode=0))
        assert linux.resolve_and_open("vlc") == "Opened vlc"
        linux._DESKTOP_CACHE = None

    def test_path_executable_fallback(self, monkeypatch):
        import app_resolver.linux as linux
        linux._DESKTOP_CACHE = None
        monkeypatch.setattr(linux, "_desktop_apps", lambda: {})
        monkeypatch.setattr(linux.shutil, "which", lambda name: "/usr/bin/vim" if name == "vim" else None)
        spawned = []
        monkeypatch.setattr(linux.subprocess, "Popen", lambda cmd, **k: spawned.append(cmd))
        assert linux.resolve_and_open("vim") == "Opened vim"
        assert spawned == [["/usr/bin/vim"]]
        linux._DESKTOP_CACHE = None
