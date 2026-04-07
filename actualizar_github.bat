@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

if not exist ".git" (
    echo ERROR: Esta carpeta no es un repositorio Git.
    pause
    exit /b 1
)

for /f "delims=" %%i in ('git branch --show-current') do set BRANCH=%%i

echo Branch actual: %BRANCH%
echo.

git status --short
echo.

set /p COMMIT_MSG=Escribi el mensaje del commit: 

if "%COMMIT_MSG%"=="" (
    set COMMIT_MSG=Actualizacion rapida
)

git add .
git commit -m "%COMMIT_MSG%"
git push origin %BRANCH%

pause