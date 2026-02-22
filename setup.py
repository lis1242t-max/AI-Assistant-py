"""
setup.py — установка зависимостей для AI Assistant
Запуск: python setup.py
"""

import sys
import subprocess


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
]


def install():
    print("Установка зависимостей AI Assistant...\n")

    for pkg in PACKAGES:
        print(f"  → {pkg}...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            print(f"  ✓ {pkg} установлен")
        else:
            err = result.stderr.decode(errors="replace").strip().splitlines()[-1]
            print(f"  ✗ {pkg} — ошибка: {err}")

    print("\nГотово. Запускайте: python run.py")


if __name__ == "__main__":
    install()