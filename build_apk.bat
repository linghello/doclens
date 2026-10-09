@echo off
REM ============================================================
REM  DocLens - Windows one-click APK build entry
REM
REM  Usage (double-click, or from cmd):
REM      build_apk.bat            -> debug APK
REM      build_apk.bat release    -> release APK
REM      build_apk.bat clean      -> wipe build cache
REM
REM  ---------------------------------------------------------
REM  WHY THIS FILE IS PURE ASCII + CRLF -- DO NOT "FIX" IT:
REM
REM  cmd.exe reads a .bat with the OEM code page (936 here), NOT
REM  UTF-8. If you save this file as UTF-8 with Chinese comments,
REM  every 3-byte UTF-8 char is decoded as 1.5 GBK chars, and the
REM  leftover lead byte EATS the next byte -- including newlines.
REM  Lines fuse together and the parser shreds the script, giving
REM  errors like:  'cho.' is not recognized as an internal command.
REM
REM  So: keep this file ASCII-only and CRLF. Chinese text belongs
REM  in README.md, not in here.
REM  ---------------------------------------------------------
setlocal EnableExtensions

set "PROJ=%~dp0"
if "%PROJ:~-1%"=="\" set "PROJ=%PROJ:~0,-1%"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=debug"

echo.
echo === DocLens APK builder ===
echo   project : %PROJ%
echo   mode    : %MODE%
echo.

if not exist "%PROJ%\buildozer.spec" (
    echo [X] buildozer.spec not found next to this .bat
    echo     Put this file in the doclens project root.
    echo.
    pause
    exit /b 1
)

if not exist "%PROJ%\build_apk.sh" (
    echo [X] build_apk.sh not found next to this .bat
    echo.
    pause
    exit /b 1
)

REM ---- 1) is wsl.exe available at all? ----------------------
where wsl.exe >nul 2>&1
if errorlevel 1 (
    echo [X] wsl.exe not found on this machine.
    echo.
    echo     You need WSL2 + Ubuntu before an APK can be built.
    echo     Open an ADMIN PowerShell and run:
    echo.
    echo         wsl --install -d Ubuntu
    echo.
    echo     Then reboot, open Ubuntu once to finish setup,
    echo     and double-click this file again.
    echo.
    echo     No WSL and do not want one? See README.md section 2b:
    echo     you can build the APK for free in the cloud instead.
    echo.
    pause
    exit /b 1
)

REM ---- 2) is a distro actually registered? ------------------
REM   `wsl -e true` fails when no distro is installed yet.
wsl.exe -e true >nul 2>&1
if errorlevel 1 (
    echo [X] WSL is installed but has NO Linux distro yet.
    echo.
    echo     Open an ADMIN PowerShell and run:
    echo.
    echo         wsl --install -d Ubuntu
    echo.
    echo     Then reboot, open Ubuntu once to finish setup,
    echo     and double-click this file again.
    echo.
    pause
    exit /b 1
)

REM ---- 3) hand off to bash --------------------------------
REM   We call `bash build_apk.sh`, NOT `./build_apk.sh`:
REM   on /mnt/c the exec bit often does not stick, so ./script.sh
REM   can fail with Permission denied even after chmod +x.
REM
REM   And we use --cd with a WINDOWS path on purpose: WSL converts
REM   it itself. The old version used `for /f` + `wslpath`, which is
REM   exactly the construct that breaks in a batch file.
echo   Launching build inside WSL...
echo   First run downloads Android SDK/NDK (3-5 GB), 30-90 min.
echo   Keep this window open.
echo.

wsl.exe --cd "%PROJ%" -e bash -lc "bash build_apk.sh %MODE%"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo [X] Build failed with exit code %RC%.
    echo     Scroll up for the real error. Common causes:
    echo       - SDK license not accepted   - NDK download timed out
    echo       - not enough disk space      - network blocked
) else (
    echo === Done ===
    echo APK should now be in the  bin\  folder next to this file.
)
echo.
pause
endlocal
exit /b %RC%
