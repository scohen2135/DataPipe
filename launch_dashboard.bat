@echo off
cd /d C:\Users\scohe\DataPipe

echo Fetching latest games...
.\.venv\Scripts\python.exe pipeline.py

echo Restarting dashboard...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

start /min cmd /c "cd /d C:\Users\scohe\DataPipe && .\.venv\Scripts\streamlit run dashboard.py"
timeout /t 5 /nobreak > nul

start http://localhost:8501
