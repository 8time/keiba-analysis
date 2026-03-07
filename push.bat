chcp 65001 > nul
@echo off
echo =======================================
echo   Pushing updates to GitHub...
echo =======================================

git add .
git commit -m "Auto-deploy update"
git push origin main

echo =======================================
echo   Done!
echo =======================================
pause
