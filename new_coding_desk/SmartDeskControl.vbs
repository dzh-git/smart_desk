Option Explicit

Dim shell, fileSystem, scriptDirectory, controllerScript, powerShellPath, command
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
controllerScript = fileSystem.BuildPath(scriptDirectory, "smartdesk_control.ps1")
powerShellPath = shell.ExpandEnvironmentStrings("%ProgramFiles%\PowerShell\7\pwsh.exe")
If Not fileSystem.FileExists(powerShellPath) Then
    powerShellPath = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe")
End If

If Not fileSystem.FileExists(powerShellPath) Then
    MsgBox "PowerShell 7 was not found. Install it with: winget install Microsoft.PowerShell", 16, "SmartDesk"
    WScript.Quit 1
End If

command = """" & powerShellPath & """ -NoLogo -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & controllerScript & """"

shell.Run command, 0, False
