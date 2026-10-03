@echo off
REM Builds PersonalScheduler.exe  (run this from the personal_scheduler folder)
python -m venv venv
call venv\Scripts\activate.bat
pip install PySide6 pyinstaller
pyinstaller --noconfirm --windowed --name PersonalScheduler --icon assets\icon.ico main.py
echo.
echo Done!  Your app is in:  dist\PersonalScheduler\PersonalScheduler.exe
pause
