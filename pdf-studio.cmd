@echo off
rem Launch PDF Studio using the bundled virtualenv.
setlocal EnableExtensions
set "here=%~dp0"

if exist "%here%.venv\Scripts\python.exe" (
    set "python=%here%.venv\Scripts\python.exe"
    goto :run
)

rem No virtualenv: fall back to whatever Python is on PATH, but only if it
rem already has the dependencies -- otherwise say how to get them.
set "python=py"
where py >nul 2>&1 || set "python=python"

"%python%" -c "import PySide6, fitz" >nul 2>&1
if errorlevel 1 (
    echo Missing dependencies. Create the environment first:>&2
    echo   py -m venv .venv>&2
    echo   .venv\Scripts\pip install -r requirements.txt>&2
    exit /b 1
)

:run
"%python%" "%here%run.py" %*
exit /b %errorlevel%
