@echo off
cd /d "%~dp0"
python gen\gen.py %*
git add input/
git diff --cached --quiet -- input/
if errorlevel 1 (
    echo [*] Commit ^& push folder input/...
    git commit -m "update input combos" -- input/
    git pull --rebase origin main
    git push origin main
    echo [OK] input/ berhasil di-commit ^& push.
) else (
    echo [*] Tidak ada perubahan baru di folder input/.
)
