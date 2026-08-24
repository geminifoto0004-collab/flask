@echo off
setlocal
cd /d "%~dp0.."

rem 1) Vendor the local ORDER source into this repo. Do not commit yet.
python scripts\vendor_order_tracking.py
if errorlevel 1 goto :fail

rem 2) Mirror ORDER-owned visitor UI into Render's startup-safe template path.
python scripts\sync_order_shared_ui.py
if errorlevel 1 goto :fail

rem 3) One commit keeps ORDER UI + Render mirror atomic. Render-only speed services stay untouched.
git add order_tracking templates\customer_share_live_fast.html templates\tracking\customer_share_public.html templates\tracking\_guest_share_common.html
if errorlevel 1 goto :fail

git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Sync latest ORDER source for Render"
  if errorlevel 1 goto :fail
) else (
  echo Git: ORDER source and shared visitor UI already up to date
)

git push
if errorlevel 1 goto :fail

echo.
echo ORDER source + shared Render visitor UI synced successfully.
pause
exit /b 0

:fail
echo.
echo ORDER sync FAILED. Local ORDER was not modified.
pause
exit /b 1
