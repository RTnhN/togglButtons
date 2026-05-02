Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = """" & scriptDir & "\.venv\Scripts\pythonw.exe"" -m toggl_buttons.main"
shell.CurrentDirectory = scriptDir
shell.Run command, 0, False
