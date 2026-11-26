@echo off
REM Daily sync for vessel_intel. Run by Windows Task Scheduler at 02:00 UTC.
REM Edit PROJECT below if the project lives somewhere else.
set PROJECT=G:\Vessel Arrival BD Tracker\vessel_intel_phase1\vessel_intel
cd /d "%PROJECT%"
if not exist logs mkdir logs
call venv\Scripts\activate.bat 2>nul || call ..\venv\Scripts\activate.bat
echo ==== %date% %time% ==== >> logs\daily_sync.log
python manage.py daily_sync >> logs\daily_sync.log 2>&1
