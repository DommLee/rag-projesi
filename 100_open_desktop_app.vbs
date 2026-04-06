Set shell = CreateObject("WScript.Shell")
root = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
cmd = "cmd /c """ & root & "\100_open_desktop_app.bat"""
shell.Run cmd, 0, False

