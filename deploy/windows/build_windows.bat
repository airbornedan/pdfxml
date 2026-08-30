@echo off
setlocal
title PDFXML - build pdfxml.exe

rem Builds dist\pdfxml.exe with PyInstaller. Run this ON WINDOWS -- the
rem exe cannot be cross-built from Linux. Lives in deploy\windows\ but
rem does its work from the project root two levels up.

set "HERE=%~dp0"
set "ROOT=%~dp0..\.."

rem --- must run from a real local path, not a VMware / network share ---
if "%HERE:~0,2%"=="\\" (
    echo.
    echo This folder is on a network or VMware shared folder:
    echo   %HERE%
    echo.
    echo Copy the whole PDFXML folder to a local disk first, e.g.
    echo   %USERPROFILE%\Desktop\PDFXML
    echo then run this from there. PyInstaller is slow and unreliable
    echo building across a share.
    echo.
    pause
    exit /b 1
)

cd /d "%ROOT%"
set "ROOT=%CD%"
if not exist "deploy\windows\pdfxml.spec" (
    echo.
    echo Could not find deploy\windows\pdfxml.spec -- run this from an
    echo intact checkout of the PDFXML project.
    echo.
    pause
    exit /b 1
)

rem --- require Python 3.12 specifically (matched wheels) ---
set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY (
    for /f "delims=" %%v in ('python -c "import sys;print('%%d.%%d'%%sys.version_info[:2])" 2^>nul') do set "PYVER=%%v"
    if "%PYVER%"=="3.12" set "PY=python"
)
if not defined PY (
    echo.
    echo Python 3.12 was not found. Install it from
    echo https://www.python.org/downloads/ -- check "Add python.exe to PATH" --
    echo then run this again. Any other version, 3.8 or 3.13 included, will not work.
    echo.
    pause
    exit /b 1
)

rem --- build environment at the project root, separate from any run-time venv ---
if not exist ".venv-build\Scripts\python.exe" (
    echo Creating build environment...
    %PY% -m venv .venv-build
    if errorlevel 1 ( echo. & echo Could not create .venv-build. & pause & exit /b 1 )
)
set "VPY=.venv-build\Scripts\python.exe"

echo Installing build dependencies...
"%VPY%" -m pip install --disable-pip-version-check -r deploy\windows\requirements-desktop.txt
if errorlevel 1 ( echo. & echo Dependency install failed -- see the messages above. & pause & exit /b 1 )

echo.
echo Building pdfxml.exe -- this takes a few minutes...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
"%VPY%" -m PyInstaller --noconfirm --clean deploy\windows\pdfxml.spec
if errorlevel 1 ( echo. & echo Build failed -- see the messages above. & pause & exit /b 1 )

echo.
if exist "dist\pdfxml.exe" (
    echo Done.  ->  %ROOT%\dist\pdfxml.exe
    echo.
    echo Copy that one file to the intern's machine and double-click it.
    echo First run: Windows SmartScreen may warn "unknown publisher" --
    echo choose "More info" then "Run anyway", or code-sign the exe.
) else (
    echo Build finished but dist\pdfxml.exe is missing -- check the log above.
)
echo.
pause
