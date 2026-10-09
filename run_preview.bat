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
set "VENV_PY=C:\Users\35853\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if not exist "%PROJ%\main.py" goto :no_main

echo.
echo === DocLens desktop preview ===
echo.

REM ---- 1) prefer the project venv -------------------------
if not exist "%VENV_PY%" goto :try_path
"%VENV_PY%" -c "import kivy" >nul 2>&1
if errorlevel 1 goto :try_path
set "PY=%VENV_PY%"
goto :run

REM ---- 2) fall back to python.exe on PATH ----------------
:try_path
where python.exe >nul 2>&1
if errorlevel 1 goto :no_python
python.exe -c "import kivy" >nul 2>&1
if errorlevel 1 goto :no_python
set "PY=python.exe"
goto :run

REM ---- 3) run -------------------------------------------
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

REM ---- error paths --------------------------------------
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
echo     Tried:
echo       %VENV_PY%
echo       python.exe on PATH
echo.
echo     Install Kivy into the venv with:
echo.
echo       "%VENV_PY%" -m pip install "kivy==2.3.1"
echo.
pause
endlocal
exit /b 1
