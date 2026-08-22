Option Explicit

Dim shell, fileSystem, scriptDirectory, controllerScript, command
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
controllerScript = fileSystem.BuildPath(scriptDirectory, "smartdesk_control.ps1")
command = "pwsh.exe -NoLogo -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & controllerScript & """"

shell.Run command, 0, False
