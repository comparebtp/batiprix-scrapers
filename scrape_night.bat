@echo off
echo === CompareBTP Nightly Scrape ===
echo Started: %date% %time%

cd /d "C:\Users\User\btp-comparateur"
"C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe" scrape_night.py

echo.
echo Finished: %date% %time%
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: Some spiders failed. Check data\scrape_log_%date:~6,4%-%date:~3,2%-%date:~0,2%.txt
)
pause
