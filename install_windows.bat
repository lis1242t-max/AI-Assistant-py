@echo off
REM Скрипт автоматической установки зависимостей для AI Assistant (Windows)

echo ============================================
echo   AI Assistant - Установка зависимостей
echo ============================================
echo.

REM Проверка Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python не найден!
    echo.
    echo Установите Python 3.8+ с https://www.python.org
    echo Важно: При установке отметьте "Add Python to PATH"
    pause
    exit /b 1
)

echo [OK] Python найден
python --version
echo.

REM Проверка pip
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] pip не найден!
    echo Переустановите Python с отметкой "Add Python to PATH"
    pause
    exit /b 1
)

echo [OK] pip найден
pip --version
echo.

REM Обновление pip
echo Обновление pip...
python -m pip install --upgrade pip
echo.

REM Установка зависимостей
echo ============================================
echo   Установка библиотек...
echo ============================================
echo.

echo [1/4] Устанавливаю PyQt6...
pip install PyQt6 PyQt6-WebEngine
if %errorlevel% neq 0 (
    echo [!] Ошибка установки PyQt6
    pause
    exit /b 1
)
echo.

echo [2/4] Устанавливаю PyOpenGL...
pip install PyOpenGL PyOpenGL-accelerate
if %errorlevel% neq 0 (
    echo [!] Ошибка установки PyOpenGL
    pause
    exit /b 1
)
echo.

echo [3/4] Устанавливаю requests...
pip install requests
if %errorlevel% neq 0 (
    echo [!] Ошибка установки requests
    pause
    exit /b 1
)
echo.

echo [4/4] Устанавливаю numpy (опционально)...
pip install numpy
echo.

echo ============================================
echo   Проверка установленных библиотек
echo ============================================
echo.

python -c "from PyQt6 import QtWidgets, QtGui, QtCore; print('  [OK] PyQt6')" 2>nul || echo   [X] PyQt6 - ОШИБКА
python -c "from PyQt6.QtOpenGLWidgets import QOpenGLWidget; print('  [OK] PyQt6 OpenGL')" 2>nul || echo   [X] PyQt6 OpenGL - ОШИБКА
python -c "from OpenGL.GL import *; print('  [OK] PyOpenGL')" 2>nul || echo   [X] PyOpenGL - ОШИБКА
python -c "import requests; print('  [OK] requests')" 2>nul || echo   [X] requests - ОШИБКА

echo.
echo ============================================
echo   Готово!
echo ============================================
echo.
echo Теперь можно запустить приложение:
echo    python ai_assistant_google.py
echo.
echo ВАЖНО: Не забудьте установить Ollama:
echo    https://ollama.ai/download
echo    После установки запустите: ollama run llama3
echo.
pause
