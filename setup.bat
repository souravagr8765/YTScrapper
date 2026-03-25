@echo off
echo Installing YTScrapper dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed. Make sure Python 3.9+ is installed.
    pause
    exit /b 1
)
echo.
echo Done! Run the scraper with:
echo   python main.py
pause
