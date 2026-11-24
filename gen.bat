@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

"%PY%" gen\gen.py %* || goto :err

if not exist "input\" goto :nochange
git add -- input/ || goto :err
git diff --cached --quiet -- input/
if errorlevel 2 goto :err
if not errorlevel 1 goto :nochange

echo [*] Commit ^& push folder input/...
git commit -m "update input combos" -- input/ || goto :err
git pull --rebase --autostash origin main || goto :err
git push origin main || goto :err
echo [OK] input/ berhasil di-commit ^& push.
goto :end

:nochange
echo [*] Tidak ada perubahan baru di folder input/.
goto :end

:err
echo [!] Gagal menjalankan gen.bat.
if "%~1"=="" pause
exit /b 1

:end
if "%~1"=="" pause
exit /b 0
