@echo off
setlocal

cd /d "%~dp0"

pyinstaller --clean --noconfirm OctoBeat.spec
if errorlevel 1 exit /b %errorlevel%

echo Build complete: dist\OctoBeat\OctoBeat.exe
endlocal
