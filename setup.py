"""
setup.py — установка зависимостей для AI Assistant
Запуск: python setup.py

Создаёт виртуальное окружение (venv) в папке проекта и устанавливает
все зависимости туда. Если venv уже существует — пропускает создание.
"""

import sys
import subprocess
import os
from pathlib import Path


PACKAGES = [
    "PyQt6",
    "PyQt6-Qt6",
    "PyQt6-sip",
    "requests",
    "PyOpenGL",
    "PyOpenGL-accelerate",
    "ddgs",
    "beautifulsoup4",
    "deep-translator",
    "pyspellchecker",
    # Голосовой ввод
    "sounddevice",
    "SpeechRecognition",
    "numpy",
]

# Папка venv рядом с этим файлом
VENV_DIR = Path(__file__).parent / "venv"


def get_venv_python():
    """Возвращает путь к Python внутри venv."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def get_venv_pip():
    """Возвращает путь к pip внутри venv."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def create_venv():
    """Создаёт виртуальное окружение."""
    print(f"Создание виртуального окружения в: {VENV_DIR}")
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(VENV_DIR)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  ✗ Ошибка при создании venv: {result.stderr.strip()}")
        sys.exit(1)
    print("  ✓ venv создан")


def install_packages():
    """Устанавливает пакеты в venv."""
    pip = get_venv_pip()
    python = get_venv_python()

    # Обновляем pip в venv
    print("\nОбновление pip...")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print("\nУстановка зависимостей AI Assistant...")
    for pkg in PACKAGES:
        print(f"  -> {pkg}...")
        result = subprocess.run(
            [str(pip), "install", pkg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            print(f"  OK {pkg} установлен")
        else:
            err = result.stderr.decode(errors="replace").strip().splitlines()
            last_err = err[-1] if err else "неизвестная ошибка"
            print(f"  ERR {pkg} — ошибка: {last_err}")


def main():
    if VENV_DIR.exists() and get_venv_python().exists():
        print(f"venv уже существует: {VENV_DIR}")
        print("  Пропускаем создание, обновляем пакеты...\n")
    else:
        create_venv()

    install_packages()

    print(f"\nГотово!")
    print(f"\nЗапуск приложения:")
    if sys.platform == "win32":
        print(f"  venv\\Scripts\\python.exe run.py")
    else:
        print(f"  venv/bin/python run.py")
    print(f"\nИли просто: python run.py  (он сам активирует venv)")


if __name__ == "__main__":
    main()