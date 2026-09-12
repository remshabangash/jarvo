' Runs the wake-word listener completely in the background — no console
' window, no taskbar icon. Double-click this file to test it manually,
' or place a shortcut to it in your Startup folder (see SETUP_AUTOSTART.md).
Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strPath
WshShell.Run """" & strPath & "\venv\Scripts\pythonw.exe"" """ & strPath & "\wake_listener.py""", 0, False