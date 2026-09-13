"""app_resolver — cross-platform application launcher resolution.

open_app is NOT limited to a predefined app list: it resolves ANY spoken app
name through a per-OS cascade. This package picks the right resolver for the
current platform at import time; executor.py just calls `resolve_and_open`.

Windows:
  1. Known websites (URL map)
  2. Start Menu shortcut scan (every installed desktop app, cached once)
  3. Known exe names (fallback for apps without shortcuts)
  4. UWP / Microsoft Store apps via PowerShell Get-StartApps
  5. Anything that looks like a domain -> opened in the browser
  6. Otherwise an HONEST failure (never a fake success or surprise search)

macOS:
  1. Known websites (URL map)
  2. Known app names via `open -a`
  3. /Applications folder scan (cached)

Linux:
  1. Known websites (URL map)
  2. .desktop file scan (system + user applications, cached)
  3. PATH executables via shutil.which
  4. Domain-like input -> browser
  5. Otherwise an honest failure
"""
import sys

if sys.platform == "win32":
    from .windows import resolve_and_open
elif sys.platform == "darwin":
    from .macos import resolve_and_open
else:
    from .linux import resolve_and_open

__all__ = ["resolve_and_open"]
