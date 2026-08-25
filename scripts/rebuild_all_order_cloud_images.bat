@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo ORDER CLOUD IMAGE GLOBAL REBUILD
echo ============================================================
echo Step 1 only scans every known customer on B2-1/B2-2.
echo Nothing is deleted during preview.
echo.
python scripts\order_cloud_rebuild_all.py --preview
if errorlevel 1 goto :fail

echo.
echo Preview passed.
echo This rebuild keeps local tracking.db and local images untouched.
echo It removes old customer cloud images, then uploads only current ACTIVE order images.
echo Existing customer share URLs remain the same.
echo.
set /p CONFIRM=Type REBUILD-ALL to continue: 
if /I not "%CONFIRM%"=="REBUILD-ALL" goto :cancel

echo.
python scripts\order_cloud_rebuild_all.py --execute --confirm REBUILD-ALL
if errorlevel 1 goto :fail

echo.
echo ORDER cloud image rebuild completed successfully.
pause
exit /b 0

:cancel
echo.
echo Cancelled. No destructive rebuild was started.
pause
exit /b 2

:fail
echo.
echo ORDER cloud image rebuild FAILED or was blocked by a safety check.
echo Review the error above. Local ORDER data was not modified.
pause
exit /b 1
