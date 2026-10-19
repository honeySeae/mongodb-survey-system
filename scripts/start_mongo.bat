@echo off
REM Local development only: double-click to start MongoDB in the foreground.
REM Keep this window open while developing. Press Ctrl+C to stop MongoDB.
REM Optional argument: config file path (default C:\data\mongod.cfg, see README).
REM This file is ASCII-only on purpose: cmd.exe misparses UTF-8 Chinese text.
title MongoDB - survey dev

set "MONGO_CFG=C:\data\mongod.cfg"
if not "%~1"=="" set "MONGO_CFG=%~1"

REM Use mongod from PATH; otherwise look in the default install directory
set "MONGOD=mongod"
where mongod >nul 2>nul
if errorlevel 1 (
    set "MONGOD="
    for /d %%D in ("%ProgramFiles%\MongoDB\Server\*") do (
        if exist "%%D\bin\mongod.exe" set "MONGOD=%%D\bin\mongod.exe"
    )
)
if "%MONGOD%"=="" (
    echo [ERROR] mongod not found. Install MongoDB or add its bin folder to PATH.
    pause
    exit /b 1
)

if not exist "%MONGO_CFG%" (
    echo [ERROR] Config file not found: %MONGO_CFG%
    echo         Create it as described in README.
    pause
    exit /b 1
)

echo Starting MongoDB ...
echo   mongod : %MONGOD%
echo   config : %MONGO_CFG%
echo Logs go to the file set in the config (default C:\data\log\mongod.log),
echo so this window stays quiet while MongoDB is running.
echo KEEP THIS WINDOW OPEN while developing. Press Ctrl+C to stop MongoDB.
echo.
"%MONGOD%" --config "%MONGO_CFG%"
echo.
echo MongoDB has stopped (exit code %errorlevel%).
echo If you did not stop it yourself, check the log file.
echo Common cause: another MongoDB is already running on port 27017.
pause
