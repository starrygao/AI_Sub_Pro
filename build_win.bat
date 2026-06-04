@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM Build AI Sub Pro Windows .exe
REM Run this script on a Windows machine with Python, PyInstaller, and ffmpeg installed

echo === AI Sub Pro Windows Build ===
echo.

REM Check Python
python --version 2>nul || (echo ERROR: Python not found. Install Python 3.9+ & exit /b 1)

REM Check PyInstaller
python -c "import PyInstaller" 2>nul || (echo ERROR: PyInstaller not found. Run: pip install pyinstaller & exit /b 1)

REM Check Node/npm for local frontend assets
where npm >nul 2>&1 || (echo ERROR: npm not found. Install Node.js and run: npm install & exit /b 1)

REM Check ffmpeg
where ffmpeg >nul 2>&1 || (echo ERROR: ffmpeg not found. Install ffmpeg and add to PATH & exit /b 1)
where ffprobe >nul 2>&1 || (echo ERROR: ffprobe not found. Install ffmpeg and add to PATH & exit /b 1)

echo [1/5] Checking dependencies... OK
echo.

REM Get ffmpeg paths
for /f "tokens=*" %%i in ('where ffmpeg') do set FFMPEG_PATH=%%i
for /f "tokens=*" %%i in ('where ffprobe') do set FFPROBE_PATH=%%i

echo   ffmpeg: %FFMPEG_PATH%
echo   ffprobe: %FFPROBE_PATH%

if "%AISUBPRO_BUNDLE_LOCAL_ASR%"=="" set "AISUBPRO_BUNDLE_LOCAL_ASR=0"
set "ASR_MODEL_DATA_ARGS="
set "ASR_BACKEND_ARGS="
if "%AISUBPRO_BUNDLE_LOCAL_ASR%"=="1" (
    if exist "models\asr" set "ASR_MODEL_DATA_ARGS=--add-data models\asr;models\asr"
    python -c "import faster_whisper" 2>nul && set "ASR_BACKEND_ARGS=!ASR_BACKEND_ARGS! --hidden-import faster_whisper --collect-all faster_whisper"
    python -c "import mlx_whisper" 2>nul && set "ASR_BACKEND_ARGS=!ASR_BACKEND_ARGS! --hidden-import mlx_whisper --collect-all mlx --collect-all mlx_whisper"
    python -c "import whisper" 2>nul && set "ASR_BACKEND_ARGS=!ASR_BACKEND_ARGS! --hidden-import whisper"
    echo   Local ASR packaging: enabled
) else (
    echo   Local ASR packaging: disabled
)

echo.
echo [2/5] Building frontend assets...
call npm run build:css || exit /b 1

echo.
echo [3/5] Cleaning build directory...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [4/5] Running PyInstaller...
python -m PyInstaller ^
    --name "AI Sub Pro" ^
    --onedir ^
    --noconfirm ^
    --clean ^
    --add-data "app\static;app\static" ^
    --add-data "app;app" ^
    %ASR_MODEL_DATA_ARGS% ^
    --add-binary "%FFMPEG_PATH%;bin" ^
    --add-binary "%FFPROBE_PATH%;bin" ^
    --hidden-import uvicorn ^
    --hidden-import uvicorn.logging ^
    --hidden-import uvicorn.loops ^
    --hidden-import uvicorn.loops.auto ^
    --hidden-import uvicorn.protocols ^
    --hidden-import uvicorn.protocols.http ^
    --hidden-import uvicorn.protocols.http.auto ^
    --hidden-import uvicorn.protocols.websockets ^
    --hidden-import uvicorn.protocols.websockets.auto ^
    --hidden-import uvicorn.protocols.websockets.websockets_sansio_impl ^
    --hidden-import uvicorn.lifespan ^
    --hidden-import uvicorn.lifespan.on ^
    --hidden-import fastapi ^
    --hidden-import pydantic ^
    --hidden-import starlette ^
    --hidden-import openai ^
    --hidden-import httpx ^
    --hidden-import anyio ^
    --hidden-import h11 ^
    --hidden-import websockets ^
    %ASR_BACKEND_ARGS% ^
    --collect-all openai ^
    --collect-all starlette ^
    --exclude-module pytest ^
    --exclude-module tensorboard ^
    --exclude-module torch.utils.tensorboard ^
    --icon NONE ^
	    app\main.py

echo.
echo [5/5] Creating launcher...
(
echo @echo off
echo cd /d "%%~dp0"
echo set "URL=http://127.0.0.1:18090"
echo powershell -NoProfile -Command "try { [void](Invoke-WebRequest -UseBasicParsing -Uri '%%URL%%' -TimeoutSec 1); exit 0 } catch { exit 1 }" ^>nul 2^>nul
echo if not errorlevel 1 ^(
echo   echo AI Sub Pro is already running.
echo   start "" "%%URL%%"
echo   exit /b 0
echo ^)
echo start "" "AI Sub Pro\AI Sub Pro.exe" --headless
echo for /l %%%%i in ^(1,1,60^) do ^(
echo   powershell -NoProfile -Command "try { [void](Invoke-WebRequest -UseBasicParsing -Uri '%%URL%%' -TimeoutSec 1); exit 0 } catch { exit 1 }" ^>nul 2^>nul
echo   if not errorlevel 1 ^(
echo     start "" "%%URL%%"
echo     exit /b 0
echo   ^)
echo   timeout /t 1 /nobreak ^>nul
echo ^)
echo echo ERROR: AI Sub Pro did not become ready at %%URL%%
echo exit /b 1
) > "dist\Start AI Sub Pro.bat"

echo.
echo === Build Complete! ===
echo   Output: dist\AI Sub Pro\
echo   Run:    dist\Start AI Sub Pro.bat
echo.
pause
