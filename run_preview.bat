@echo off
REM ============================================================
REM  DocLens - Windows desktop preview
REM
REM  Runs the EXACT SAME Kivy code that goes into the APK, but in a
REM  desktop window. No WSL, no Android SDK, no phone needed.
REM
REM  This is the fastest way to see / judge the UI. The APK is just
REM  this same Python code frozen by buildozer, so what you see here
REM  is what you get on the phone.
REM
REM  PURE ASCII + CRLF ON PURPOSE. Do not save as UTF-8.
REM  See the header of build_apk.bat for the full explanation.
REM ============================================================
setlocal EnableExtensions
set "PROJ=%~dp0"
if "%PROJ:~-1%"=="\" set "PROJ=%PROJ:~0,-1%"

if not exist "%PROJ%\main.py" goto :no_main

echo.
echo === DocLens desktop preview ===
echo.

REM ---- find a Python that already has Kivy ----------------
REM   Search order:
REM     1. .venv in the project folder   (standard, portable)
REM     2. venv  in the project folder
REM     3. LOCAL_VENV below              (per-machine override)
REM     4. python.exe on PATH

if not exist "%PROJ%\.venv\Scripts\python.exe" goto :try_venv2
"%PROJ%\.venv\Scripts\python.exe" -c "import kivy" >nul 2>&1
if errorlevel 1 goto :try_venv2
set "PY=%PROJ%\.venv\Scripts\python.exe"
goto :run

:try_venv2
if not exist "%PROJ%\venv\Scripts\python.exe" goto :try_local
"%PROJ%\venv\Scripts\python.exe" -c "import kivy" >nul 2>&1
if errorlevel 1 goto :try_local
set "PY=%PROJ%\venv\Scripts\python.exe"
goto :run

:try_local
REM   Per-machine override. Written with %USERPROFILE% so this repo
REM   carries no hard-coded username; on another machine the path
REM   simply does not exist and we fall through to python.exe on PATH.
set "LOCAL_VENV=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%LOCAL_VENV%" goto :try_path
"%LOCAL_VENV%" -c "import kivy" >nul 2>&1
if errorlevel 1 goto :try_path
set "PY=%LOCAL_VENV%"
goto :run

:try_path
where python.exe >nul 2>&1
if errorlevel 1 goto :no_python
python.exe -c "import kivy" >nul 2>&1
if errorlevel 1 goto :no_python
set "PY=python.exe"
goto :run

REM ---- run ------------------------------------------------
:run
echo   python  : %PY%
echo   project : %PROJ%
echo.
echo   Close the app window to quit.
echo   This console doubles as a log: if anything crashes,
echo   the traceback shows up right here.
echo.

"%PY%" "%PROJ%\main.py"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
    echo [X] Exited with code %RC% -- read the traceback above.
) else (
    echo === Preview closed normally ===
)
echo.
pause
endlocal
exit /b %RC%

REM ---- error paths ----------------------------------------
:no_main
echo [X] main.py not found next to this .bat
echo     Put this file in the doclens project root.
echo.
pause
endlocal
exit /b 1

:no_python
echo [X] No Python with Kivy found.
echo.
echo     Create a venv in the project folder and install Kivy:
echo.
echo       python -m venv .venv
echo       .venv\Scripts\python.exe -m pip install "kivy==2.3.1" pillow
echo.
echo     Then double-click this file again.
echo.
pause
endlocal
exit /b 1
