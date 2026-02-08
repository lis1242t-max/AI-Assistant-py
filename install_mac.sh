#!/bin/bash
# Скрипт автоматической установки зависимостей для AI Assistant (macOS/Linux)

echo "🚀 Установка зависимостей для AI Assistant..."
echo ""

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 не найден!"
    echo "Установите Python 3.8+ с https://www.python.org"
    exit 1
fi

echo "✓ Python найден: $(python3 --version)"
echo ""

# Проверка pip
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 не найден!"
    echo "Установка pip..."
    python3 -m ensurepip --upgrade
fi

echo "✓ pip найден: $(pip3 --version)"
echo ""

# Установка зависимостей
echo "📦 Установка библиотек..."
echo ""

pip3 install --upgrade pip

echo "  → Устанавливаю PyQt6..."
pip3 install PyQt6 PyQt6-WebEngine

echo "  → Устанавливаю PyOpenGL..."
pip3 install PyOpenGL PyOpenGL-accelerate

echo "  → Устанавливаю requests..."
pip3 install requests

echo ""
echo "✅ Все зависимости установлены!"
echo ""

# Проверка установки
echo "🔍 Проверка установленных библиотек..."
echo ""

python3 -c "from PyQt6 import QtWidgets, QtGui, QtCore; print('  ✓ PyQt6')" 2>/dev/null || echo "  ✗ PyQt6 - ОШИБКА"
python3 -c "from PyQt6.QtOpenGLWidgets import QOpenGLWidget; print('  ✓ PyQt6 OpenGL')" 2>/dev/null || echo "  ✗ PyQt6 OpenGL - ОШИБКА"
python3 -c "from OpenGL.GL import *; print('  ✓ PyOpenGL')" 2>/dev/null || echo "  ✗ PyOpenGL - ОШИБКА"
python3 -c "import requests; print('  ✓ requests')" 2>/dev/null || echo "  ✗ requests - ОШИБКА"

echo ""
echo "🎉 Готово! Теперь можно запустить приложение:"
echo "   python3 ai_assistant_google.py"
echo ""
echo "⚠️  Не забудьте установить и запустить Ollama:"
echo "   https://ollama.ai"
echo "   ollama run llama3"
