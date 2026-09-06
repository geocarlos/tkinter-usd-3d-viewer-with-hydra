@echo off
"%windir%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%PREFIX%\make_shortcut.ps1" -Prefix "%PREFIX%"
exit /b 0
