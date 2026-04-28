@echo off
echo Finding and killing process on port 8003...
FOR /F "tokens=5" %%i IN ('netstat -aon ^| findstr ":8003" ^| findstr "LISTENING"') DO (
    echo Killing process with PID %%i on port 8003.
    taskkill /F /PID %%i
)
echo.
