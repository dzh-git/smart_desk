Option Explicit

Dim shell, fileSystem, scriptDirectory, launcherPath, iconPath
Dim desktopDirectory, shortcutPath, shortcut

Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
launcherPath = fileSystem.BuildPath(scriptDirectory, "SmartDeskControl.vbs")
iconPath = fileSystem.BuildPath(scriptDirectory, "assets\SmartDeskControl.ico")

If Not fileSystem.FileExists(launcherPath) Then
    MsgBox "SmartDeskControl.vbs was not found.", 16, "SmartDesk"
    WScript.Quit 1
End If

If Not fileSystem.FileExists(iconPath) Then
    MsgBox "SmartDeskControl.ico was not found.", 16, "SmartDesk"
    WScript.Quit 1
End If

desktopDirectory = shell.SpecialFolders("Desktop")
shortcutPath = fileSystem.BuildPath(desktopDirectory, "SmartDesk Meeting Control.lnk")
Set shortcut = shell.CreateShortcut(shortcutPath)

shortcut.TargetPath = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\wscript.exe")
shortcut.Arguments = """" & launcherPath & """"
shortcut.WorkingDirectory = scriptDirectory
shortcut.IconLocation = iconPath & ",0"
shortcut.Description = "SmartDesk Meeting Control"
shortcut.WindowStyle = 7
shortcut.Save

MsgBox "SmartDesk shortcut created on the desktop.", 64, "SmartDesk"
