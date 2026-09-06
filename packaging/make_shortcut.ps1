param([string]$Prefix)

$shortcutDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Tkinter USD 3D Viewer"
New-Item -ItemType Directory -Force -Path $shortcutDir | Out-Null

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $shortcutDir "Tkinter USD 3D Viewer.lnk"))
$shortcut.TargetPath = Join-Path $Prefix "pythonw.exe"
$shortcut.Arguments = '"' + (Join-Path $Prefix "app.py") + '"'
$shortcut.WorkingDirectory = $Prefix
$shortcut.IconLocation = Join-Path $Prefix "icon.ico"
$shortcut.Save()
