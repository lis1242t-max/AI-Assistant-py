"""
error_handler.py — Центральная система проверок и самовосстановления.

Содержит:
  • startup_checks()          — полный набор проверок при запуске
  • check_ollama_health()     — Ollama запущена? пытается запустить если нет
  • check_database_health()   — целостность SQLite БД, пересоздание при поломке
  • check_required_files()    — наличие .py-файлов рядом с run.py
  • check_settings_file()     — валидация и починка app_settings.json
  • check_python_packages()   — нужные pip-пакеты установлены?
  • install_global_exception_hook()  — перехватывает все необработанные исключения
  • safe_call(fn, *a, **kw)   — вызов с авторепортом ошибки
  • log_error(tag, exc)       — пишет в errors.log
  • guarded(tag)              — декоратор для методов класса
"""

import os
import sys
import json
import time
import sqlite3
import logging
import platform
import subprocess
import traceback
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Any, Optional

# ── Платформа ─────────────────────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"
IS_MACOS   = sys.platform == "darwin"
IS_LINUX   = sys.platform.startswith("linux")

# ── Пути ──────────────────────────────────────────────────────────────────
APP_DIR      = Path(sys.argv[0]).resolve().parent if sys.argv[0] else Path.cwd()
ERROR_LOG    = APP_DIR / "errors.log"
SETTINGS_FILE = APP_DIR / "app_settings.json"

# ── Ollama ─────────────────────────────────────────────────────────────────
OLLAMA_HOST    = "http://localhost:11434"
OLLAMA_TIMEOUT = 5   # секунд ожидания ответа
OLLAMA_START_WAIT = 12  # секунд после попытки запуска

# ── Логгер ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("error_handler")


# ══════════════════════════════════════════════════════════════════════════════
# ЛОГИРОВАНИЕ ОШИБОК
# ══════════════════════════════════════════════════════════════════════════════

def log_error(tag: str, exc: BaseException, extra: str = "") -> str:
    """
    Пишет ошибку в errors.log и возвращает строку описания.
    Никогда не падает сам по себе.
    """
    tb = traceback.format_exc()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"\n{'='*60}",
        f"[{ts}] [{tag}] {type(exc).__name__}: {exc}",
    ]
    if extra:
        lines.append(f"  Контекст: {extra}")
    if tb and tb.strip() != "NoneType: None":
        lines.append(tb)
    text = "\n".join(lines)

    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass   # диск может быть недоступен — молча игнорируем

    print(text)
    return f"{type(exc).__name__}: {exc}"


def _plog(tag: str, msg: str):
    """Вывод в консоль с тегом."""
    print(f"[{tag}] {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# ДЕКОРАТОРЫ
# ══════════════════════════════════════════════════════════════════════════════

def guarded(tag: str = "GUARD", default=None, reraise: bool = False):
    """
    Декоратор — оборачивает метод/функцию в try/except.
    Логирует ошибку и возвращает default вместо падения.

    Использование:
        @guarded("SEND_MSG")
        def send_message(self): ...

        @guarded("INIT_DB", reraise=True)
        def init_db(): ...
    """
    def decorator(fn: Callable):
        import functools
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                log_error(tag, exc, extra=f"fn={fn.__qualname__}")
                if reraise:
                    raise
                return default
        return wrapper
    return decorator


def safe_call(fn: Callable, *args, tag: str = "SAFE_CALL",
              default=None, **kwargs) -> Any:
    """
    Вызывает fn(*args, **kwargs).
    При исключении логирует и возвращает default.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        log_error(tag, exc, extra=f"fn={getattr(fn, '__name__', fn)}")
        return default


# ══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА OLLAMA
# ══════════════════════════════════════════════════════════════════════════════

def check_ollama_health(host: str = OLLAMA_HOST, auto_fix: bool = True) -> dict:
    """
    Проверяет, отвечает ли Ollama по API.
    Если не отвечает — пытается запустить процесс и ждёт.

    Returns:
        {
          "ok": bool,
          "reachable": bool,
          "started_by_us": bool,
          "error": str | None,
          "models": list,       # список установленных моделей
        }
    """
    import requests

    result = {
        "ok": False,
        "reachable": False,
        "started_by_us": False,
        "error": None,
        "models": [],
    }

    def _ping() -> Optional[list]:
        """Возвращает список моделей или None."""
        try:
            resp = requests.get(f"{host}/api/tags", timeout=OLLAMA_TIMEOUT)
            if resp.status_code == 200:
                return resp.json().get("models", [])
        except Exception:
            pass
        return None

    models = _ping()
    if models is not None:
        result["ok"] = True
        result["reachable"] = True
        result["models"] = models
        _plog("OLLAMA", f"✅ Ollama отвечает. Моделей: {len(models)}")
        return result

    if not auto_fix:
        result["error"] = "Ollama не отвечает (auto_fix=False)"
        _plog("OLLAMA", f"❌ {result['error']}")
        return result

    # ── Пытаемся запустить Ollama ──────────────────────────────────────────
    _plog("OLLAMA", "⚠️ Ollama не отвечает — пробуем запустить...")
    started = _try_start_ollama()
    if started:
        result["started_by_us"] = True
        _plog("OLLAMA", f"🔄 Ollama запущена, ждём {OLLAMA_START_WAIT} сек...")
        for attempt in range(OLLAMA_START_WAIT):
            time.sleep(1)
            models = _ping()
            if models is not None:
                result["ok"] = True
                result["reachable"] = True
                result["models"] = models
                _plog("OLLAMA", f"✅ Ollama готова (попытка {attempt+1})")
                return result
        result["error"] = "Ollama запущена, но не ответила API за отведённое время"
    else:
        result["error"] = "Не удалось запустить Ollama"

    _plog("OLLAMA", f"❌ {result['error']}")
    return result


def _try_start_ollama() -> bool:
    """Пытается запустить 'ollama serve' в фоне. Возвращает True если команда найдена."""
    popen_kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WINDOWS:
        popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        if IS_WINDOWS:
            # На Windows Ollama обычно установлена как сервис
            subprocess.Popen(["ollama", "serve"], **popen_kw)
        elif IS_MACOS:
            # Сначала пробуем как приложение, потом как демон
            try:
                subprocess.Popen(["open", "-a", "Ollama"], **popen_kw)
            except Exception:
                env = os.environ.copy()
                subprocess.Popen(["ollama", "serve"], env=env, **popen_kw)
        else:
            # Linux — просто запускаем в фоне
            subprocess.Popen(["ollama", "serve"], **popen_kw)
        return True
    except FileNotFoundError:
        _plog("OLLAMA", "❌ Команда 'ollama' не найдена. Ollama не установлена.")
        return False
    except Exception as e:
        _plog("OLLAMA", f"❌ Ошибка запуска Ollama: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА БАЗ ДАННЫХ
# ══════════════════════════════════════════════════════════════════════════════

def check_database_health(db_path: str, required_tables: list = None,
                           auto_fix: bool = True) -> dict:
    """
    Проверяет SQLite БД: доступность, целостность, наличие таблиц.
    При обнаружении повреждения делает бэкап и пересоздаёт.

    Args:
        db_path:         путь к .db файлу
        required_tables: список имён таблиц, которые должны быть
        auto_fix:        пересоздать если повреждена

    Returns:
        {"ok": bool, "repaired": bool, "error": str | None}
    """
    result = {"ok": False, "repaired": False, "error": None}

    # 1. Доступность файла
    db = Path(db_path)
    if db.exists() and not os.access(db_path, os.R_OK | os.W_OK):
        result["error"] = f"Нет прав на чтение/запись: {db_path}"
        _plog("DB", f"❌ {result['error']}")
        return result

    # 2. SQLite integrity_check
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        cur  = conn.cursor()
        cur.execute("PRAGMA integrity_check")
        ic = cur.fetchone()
        if ic is None or ic[0] != "ok":
            raise sqlite3.DatabaseError(f"integrity_check вернул: {ic}")

        # 3. Наличие нужных таблиц
        if required_tables:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            existing = {r[0] for r in cur.fetchall()}
            missing  = set(required_tables) - existing
            if missing:
                raise sqlite3.DatabaseError(f"Отсутствуют таблицы: {missing}")

        conn.close()
        result["ok"] = True
        _plog("DB", f"✅ {db.name} — в порядке")
        return result

    except sqlite3.DatabaseError as exc:
        result["error"] = str(exc)
        _plog("DB", f"⚠️ {db.name} повреждена: {exc}")

        if not auto_fix:
            return result

        # 4. Бэкап и удаление
        backup = Path(str(db_path) + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        try:
            if db.exists():
                import shutil
                shutil.copy2(db_path, backup)
                _plog("DB", f"📦 Бэкап сохранён: {backup.name}")
                db.unlink()
        except Exception as e:
            _plog("DB", f"⚠️ Не удалось сделать бэкап: {e}")

        # 5. Пересоздаём (пустую)
        try:
            conn = sqlite3.connect(db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()
            conn.close()
            result["repaired"] = True
            result["ok"] = True
            _plog("DB", f"✅ {db.name} пересоздана (данные потеряны, бэкап: {backup.name})")
        except Exception as e2:
            result["error"] = f"Не удалось пересоздать: {e2}"
            _plog("DB", f"❌ {result['error']}")

        return result

    except Exception as exc:
        result["error"] = log_error("DB_CHECK", exc, extra=db_path)
        return result


# ══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА ФАЙЛОВ
# ══════════════════════════════════════════════════════════════════════════════

# Файлы, которые должны лежать рядом с run.py
REQUIRED_FILES = {
    "llama_handler.py":           "Обработчик LLaMA-моделей (обязательный)",
    "model_downloader.py":        "Диалоги скачивания моделей (обязательный)",
    "chat_manager.py":            "Менеджер чатов (обязательный)",
    "context_memory_manager.py":  "Менеджер памяти LLaMA (обязательный)",
}

OPTIONAL_FILES = {
    "deepseek_memory_manager.py": "Память DeepSeek",
    "vision_handler.py":          "Обработка изображений (Vision)",
    "forbidden_english_words.py": "Фильтр английских слов",
}

# Файлы, которые могут лежать в подпапках проекта.
# Формат: { "имя_файла.py": ("описание", ["папка1", "папка2", ...]) }
# Поиск идёт сначала в корне, затем по указанным подпапкам.
SUBDIR_OPTIONAL_FILES = {
    "deepseek_config.py": ("Конфигурация DeepSeek", ["ai_config"]),
    "mistral_config.py":  ("Конфигурация Mistral",  ["ai_config"]),
    "qwen_config.py":     ("Конфигурация Qwen",     ["ai_config"]),
}


def _find_file_in_dirs(base, fname: str, subdirs: list) -> bool:
    """Возвращает True если файл найден в base или в одной из subdirs."""
    if (base / fname).is_file():
        return True
    return any((base / sub / fname).is_file() for sub in subdirs)


def check_required_files(base_dir: str = None) -> dict:
    """
    Проверяет наличие обязательных и опциональных файлов.
    Файлы из SUBDIR_OPTIONAL_FILES ищутся также в подпапках (ai_config и др.),
    чтобы не ругаться на конфиги, перемещённые в подпапку.
    """
    base = Path(base_dir) if base_dir else APP_DIR
    result = {
        "ok": True,
        "missing_required": [],
        "missing_optional": [],
        "error": None,
    }

    for fname, desc in REQUIRED_FILES.items():
        if not (base / fname).is_file():
            result["missing_required"].append(fname)
            _plog("FILES", f"❌ Отсутствует обязательный файл: {fname} — {desc}")

    for fname, desc in OPTIONAL_FILES.items():
        if not (base / fname).is_file():
            result["missing_optional"].append(fname)
            _plog("FILES", f"⚠️ Отсутствует опциональный файл: {fname} — {desc}")

    for fname, (desc, subdirs) in SUBDIR_OPTIONAL_FILES.items():
        if not _find_file_in_dirs(base, fname, subdirs):
            result["missing_optional"].append(fname)
            locations = ", ".join(["корень"] + subdirs)
            _plog("FILES", f"⚠️ Не найден: {fname} — {desc} (искали в: {locations})")
        else:
            _plog("FILES", f"✅ {fname} найден")

    if result["missing_required"]:
        result["ok"] = False
        result["error"] = (
            "Отсутствуют обязательные файлы: "
            + ", ".join(result["missing_required"])
        )
        _plog("FILES", f"❌ {result['error']}")
    else:
        _plog("FILES", "✅ Все обязательные файлы на месте")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА НАСТРОЕК
# ══════════════════════════════════════════════════════════════════════════════

SETTINGS_DEFAULTS = {
    "first_launch_done":  False,
    "ai_model_key":       "llama3",
    "theme":              "dark",
    "language":           "russian",
}

SETTINGS_VALID_MODELS  = {"llama3", "deepseek"}
SETTINGS_VALID_THEMES  = {"dark", "light"}
SETTINGS_VALID_LANGS   = {"russian", "english"}


def check_settings_file(path: str = None, auto_fix: bool = True) -> dict:
    """
    Читает app_settings.json, проверяет и при необходимости восстанавливает.

    Returns:
        {"ok": bool, "repaired": bool, "settings": dict, "error": str | None}
    """
    settings_path = Path(path) if path else SETTINGS_FILE
    result = {"ok": False, "repaired": False, "settings": {}, "error": None}

    # Файл не существует — создаём с дефолтами
    if not settings_path.exists():
        if auto_fix:
            _write_settings(settings_path, SETTINGS_DEFAULTS)
            result["ok"] = True
            result["repaired"] = True
            result["settings"] = dict(SETTINGS_DEFAULTS)
            _plog("SETTINGS", "✅ app_settings.json создан с дефолтными настройками")
        else:
            result["error"] = "Файл настроек не найден"
        return result

    # Читаем
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            raise ValueError("Файл пустой")
        settings = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        _plog("SETTINGS", f"⚠️ Не удалось разобрать JSON: {exc}")
        if auto_fix:
            _write_settings(settings_path, SETTINGS_DEFAULTS)
            result["repaired"] = True
            result["settings"] = dict(SETTINGS_DEFAULTS)
            result["ok"] = True
            _plog("SETTINGS", "✅ app_settings.json пересоздан")
        else:
            result["error"] = str(exc)
        return result

    # Валидация значений
    repaired = False
    if settings.get("ai_model_key") not in SETTINGS_VALID_MODELS:
        _plog("SETTINGS", f"⚠️ Неизвестная модель '{settings.get('ai_model_key')}' → llama3")
        settings["ai_model_key"] = "llama3"
        repaired = True

    if settings.get("theme") not in SETTINGS_VALID_THEMES:
        settings["theme"] = "dark"
        repaired = True

    if settings.get("language") not in SETTINGS_VALID_LANGS:
        settings["language"] = "russian"
        repaired = True

    # Добавляем отсутствующие ключи
    for k, v in SETTINGS_DEFAULTS.items():
        if k not in settings:
            settings[k] = v
            repaired = True

    if repaired and auto_fix:
        _write_settings(settings_path, settings)
        result["repaired"] = True
        _plog("SETTINGS", "✅ app_settings.json исправлен")
    else:
        _plog("SETTINGS", "✅ app_settings.json в порядке")

    result["ok"] = True
    result["settings"] = settings
    return result


def _write_settings(path: Path, data: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _plog("SETTINGS", f"❌ Не удалось записать настройки: {e}")


def load_settings(path: str = None) -> dict:
    """Безопасно читает app_settings.json. Возвращает dict (никогда не падает)."""
    try:
        p = Path(path) if path else SETTINGS_FILE
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return dict(SETTINGS_DEFAULTS)


def save_settings(data: dict, path: str = None):
    """Безопасно пишет app_settings.json. Никогда не падает."""
    try:
        p = Path(path) if path else SETTINGS_FILE
        existing = load_settings(path)
        existing.update(data)
        _write_settings(p, existing)
    except Exception as e:
        _plog("SETTINGS", f"❌ save_settings: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА PYTHON-ПАКЕТОВ
# ══════════════════════════════════════════════════════════════════════════════

# Формат: "import_name": "pip_name"
# import_name — имя для importlib.import_module() (может отличаться от pip-имени!)
# Например: PyOpenGL устанавливается через pip, но импортируется как OpenGL
REQUIRED_PACKAGES = {
    "PyQt6":    "PyQt6",
    "requests": "requests",
}

OPTIONAL_PACKAGES = {
    "OpenGL": "PyOpenGL",   # pip install PyOpenGL → import OpenGL
    "PIL":    "Pillow",     # pip install Pillow   → import PIL
    "numpy":  "numpy",
}


def check_python_packages(auto_install: bool = False) -> dict:
    """
    Проверяет наличие нужных Python-пакетов.
    При auto_install=True пытается установить недостающие через pip.

    Returns:
        {"ok": bool, "missing": list, "installed": list, "failed": list}
    """
    import importlib
    result = {"ok": True, "missing": [], "installed": [], "failed": []}

    # ── Обязательные — блокируют запуск если не установить ────────────────
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            result["missing"].append(pip_name)
            _plog("PACKAGES", f"❌ Пакет не найден: {pip_name}")

            if auto_install:
                _plog("PACKAGES", f"🔄 Устанавливаем {pip_name}...")
                if _pip_install(pip_name):
                    try:
                        importlib.import_module(import_name)
                        result["missing"].remove(pip_name)
                        result["installed"].append(pip_name)
                        _plog("PACKAGES", f"✅ {pip_name} установлен")
                    except ImportError:
                        result["failed"].append(pip_name)
                        _plog("PACKAGES", f"❌ {pip_name} установлен, но import не работает")
                else:
                    result["failed"].append(pip_name)
                    _plog("PACKAGES", f"❌ Не удалось установить {pip_name}")

    # ok = True только если список missing пустой
    result["ok"] = len(result["missing"]) == 0

    # ── Опциональные — не блокируют запуск ────────────────────────────────
    for import_name, pip_name in OPTIONAL_PACKAGES.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            _plog("PACKAGES", f"⚠️ Опциональный пакет отсутствует: {pip_name}")
            if auto_install:
                _plog("PACKAGES", f"🔄 Устанавливаем {pip_name}...")
                if _pip_install(pip_name):
                    _plog("PACKAGES", f"✅ {pip_name} установлен")
                else:
                    _plog("PACKAGES", f"⚠️ Не удалось установить {pip_name} — продолжаем без него")

    if result["ok"]:
        _plog("PACKAGES", "✅ Все обязательные пакеты доступны")

    return result


def _pip_install(package: str) -> bool:
    """Кросс-платформенная установка pip. Работает на Windows / macOS / Linux."""
    cmd = [sys.executable, "-m", "pip", "install", package]
    try:
        if IS_LINUX or IS_MACOS:
            # Сначала без флага (venv, conda)
            try:
                subprocess.run(cmd, check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return True
            except subprocess.CalledProcessError:
                # Системный Python — нужен --break-system-packages (PEP 668)
                subprocess.run(cmd + ["--break-system-packages"], check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return True
        else:
            # Windows
            subprocess.run(cmd, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
    except Exception as e:
        _plog("PACKAGES", f"⚠️ pip install {package}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА ДИСКОВОГО ПРОСТРАНСТВА
# ══════════════════════════════════════════════════════════════════════════════

def check_disk_space(path: str = None, min_gb: float = 1.0) -> dict:
    """
    Проверяет свободное место на диске, где лежит приложение.

    Returns:
        {"ok": bool, "free_gb": float, "total_gb": float, "warn": bool}
    """
    import shutil
    check_path = path or str(APP_DIR)
    result = {"ok": True, "free_gb": 0.0, "total_gb": 0.0, "warn": False}
    try:
        usage = shutil.disk_usage(check_path)
        free  = usage.free  / 1024**3
        total = usage.total / 1024**3
        result["free_gb"]  = round(free,  2)
        result["total_gb"] = round(total, 2)

        if free < min_gb:
            result["ok"]   = False
            result["warn"] = True
            _plog("DISK", f"⚠️ Мало места: {free:.1f} GB свободно (минимум {min_gb} GB)")
        elif free < min_gb * 2:
            result["warn"] = True
            _plog("DISK", f"⚠️ Место на исходе: {free:.1f} GB свободно")
        else:
            _plog("DISK", f"✅ Свободно: {free:.1f} GB / {total:.1f} GB")
    except Exception as e:
        _plog("DISK", f"⚠️ Не удалось проверить диск: {e}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЙ ПЕРЕХВАТЧИК ИСКЛЮЧЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════

_qt_app_ref = None   # слабая ссылка на QApplication для диалогов

def install_global_exception_hook(qt_app=None):
    """
    Устанавливает sys.excepthook и (если передан qt_app) Qt exception handler.
    Все необработанные исключения логируются и показываются пользователю.
    """
    global _qt_app_ref
    _qt_app_ref = qt_app

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        if issubclass(exc_type, SystemExit):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n{'='*60}\n"
            f"[{ts}] НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ\n"
            f"{tb_str}"
        )
        print(entry)
        try:
            with open(ERROR_LOG, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass

        # Показываем диалог если есть Qt
        _show_crash_dialog(exc_type, exc_value, tb_str)

    sys.excepthook = _excepthook

    # Перехват в потоках (Python 3.8+)
    def _thread_excepthook(args):
        if args.exc_type and not issubclass(args.exc_type, (SystemExit, KeyboardInterrupt)):
            tb_str = "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            )
            log_error("THREAD", args.exc_value or Exception("Unknown"), extra=tb_str[:300])

    threading.excepthook = _thread_excepthook
    _plog("HOOK", "✅ Глобальный перехватчик исключений установлен")


def _show_crash_dialog(exc_type, exc_value, tb_str: str):
    """Пробует показать QMessageBox с описанием краша."""
    try:
        from PyQt6 import QtWidgets
        app = QtWidgets.QApplication.instance()
        if app is None:
            return

        short_msg = f"{exc_type.__name__}: {exc_value}"
        hint = _get_recovery_hint(exc_type, exc_value)

        msg_box = QtWidgets.QMessageBox()
        msg_box.setWindowTitle("⚠️ Необработанная ошибка")
        msg_box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
        msg_box.setText(
            f"Произошла непредвиденная ошибка:\n\n{short_msg}"
            + (f"\n\n💡 {hint}" if hint else "")
        )
        msg_box.setDetailedText(tb_str[-3000:])  # последние 3000 символов
        msg_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok
        )
        msg_box.exec()
    except Exception:
        pass   # Qt мог не инициализироваться


def _get_recovery_hint(exc_type, exc_value) -> str:
    """Возвращает подсказку по типу ошибки."""
    exc_str = str(exc_value).lower()
    name    = exc_type.__name__

    hints = {
        "ConnectionRefusedError":    "Ollama не запущена. Запустите приложение Ollama.",
        "ModuleNotFoundError":       "Не найден Python-пакет. Запустите: pip install -r requirements.txt",
        "ImportError":               "Проблема с импортом. Проверьте наличие всех .py файлов рядом с run.py.",
        "PermissionError":           "Нет прав доступа к файлу или папке.",
        "FileNotFoundError":         "Файл не найден. Проверьте что все файлы приложения на месте.",
        "sqlite3.DatabaseError":     "Повреждена база данных. Программа попробует восстановить при перезапуске.",
        "MemoryError":               "Не хватает оперативной памяти. Закройте другие приложения.",
        "RuntimeError":              "Ошибка выполнения. Попробуйте перезапустить программу.",
        "JSONDecodeError":           "Повреждён файл настроек. Удалите app_settings.json и перезапустите.",
    }

    for key, hint in hints.items():
        if key.lower() in name.lower() or key.lower() in exc_str:
            return hint

    if "ollama" in exc_str or "11434" in exc_str:
        return "Ollama не запущена или не отвечает. Запустите приложение Ollama."
    if "timeout" in exc_str:
        return "Превышено время ожидания. Проверьте подключение к Ollama."
    if "disk" in exc_str or "space" in exc_str or "no space" in exc_str:
        return "Закончилось место на диске."

    return ""


# ══════════════════════════════════════════════════════════════════════════════
# ПОЛНЫЙ НАБОР ПРОВЕРОК ПРИ ЗАПУСКЕ
# ══════════════════════════════════════════════════════════════════════════════

def startup_checks(
    base_dir:       str  = None,
    check_ollama:   bool = True,
    check_dbs:      list = None,   # список путей к .db файлам
    check_packages: bool = True,
    check_space:    bool = True,
    check_files:    bool = True,
    check_settings: bool = True,
    auto_fix:       bool = True,
    qt_app               = None,
) -> dict:
    """
    Запускает все проверки подряд.
    Возвращает сводный отчёт.

    Пример использования в main():
        report = startup_checks(
            check_dbs=["chats.db", "chat_memory.db"],
            qt_app=app,
        )
        if not report["fatal"]:
            window = MainWindow()
    """
    report = {
        "fatal":    False,   # если True — запуск невозможен
        "warnings": [],
        "fixes":    [],
        "checks":   {},
    }

    _plog("STARTUP", "=" * 55)
    _plog("STARTUP", "Запуск диагностики приложения...")
    _plog("STARTUP", "=" * 55)

    base = base_dir or str(APP_DIR)

    # ── 1. Пакеты Python ─────────────────────────────────────────────────
    if check_packages:
        r = check_python_packages(auto_install=auto_fix)
        report["checks"]["packages"] = r
        if r["missing"]:          # fatal только если реально есть нераскрытые пакеты
            report["fatal"] = True
            report["warnings"].append(
                f"❌ Не установлены пакеты: {r['missing']}"
            )
        if r.get("installed"):
            report["fixes"].append(f"Установлены пакеты: {', '.join(r['installed'])}")

    # ── 2. Файлы приложения ───────────────────────────────────────────────
    if check_files:
        r = check_required_files(base_dir=base)
        report["checks"]["files"] = r
        if not r["ok"]:
            report["fatal"] = True
            report["warnings"].append(r["error"])
        if r["missing_optional"]:
            report["warnings"].append(
                f"⚠️ Опциональные файлы отсутствуют: {r['missing_optional']}"
            )

    # ── 3. Настройки ──────────────────────────────────────────────────────
    if check_settings:
        r = check_settings_file(auto_fix=auto_fix)
        report["checks"]["settings"] = r
        if not r["ok"]:
            report["warnings"].append(f"⚠️ Проблема с настройками: {r['error']}")
        if r.get("repaired"):
            report["fixes"].append("app_settings.json восстановлен")

    # ── 4. Базы данных ────────────────────────────────────────────────────
    if check_dbs:
        db_results = {}
        for db_path in check_dbs:
            full_path = db_path if os.path.isabs(db_path) else os.path.join(base, db_path)
            r = check_database_health(full_path, auto_fix=auto_fix)
            db_name = Path(db_path).name
            db_results[db_name] = r
            if not r["ok"]:
                report["warnings"].append(f"❌ БД {db_name}: {r['error']}")
            if r.get("repaired"):
                report["fixes"].append(f"БД {db_name} пересоздана")
        report["checks"]["databases"] = db_results

    # ── 5. Диск ───────────────────────────────────────────────────────────
    if check_space:
        r = check_disk_space(path=base, min_gb=0.5)
        report["checks"]["disk"] = r
        if not r["ok"]:
            report["warnings"].append(
                f"⚠️ Мало места на диске: {r['free_gb']:.1f} GB"
            )
        elif r["warn"]:
            report["warnings"].append(
                f"⚠️ Свободного места мало: {r['free_gb']:.1f} GB"
            )

    # ── 6. Ollama ─────────────────────────────────────────────────────────
    if check_ollama:
        r = check_ollama_health(auto_fix=auto_fix)
        report["checks"]["ollama"] = r
        if r.get("started_by_us"):
            report["fixes"].append("Ollama запущена автоматически")
        if not r["reachable"]:
            # Ollama недоступна — это не фатальная ошибка,
            # программа может работать для выбора модели и скачивания
            report["warnings"].append(
                "⚠️ Ollama не отвечает. ИИ-чат будет недоступен до запуска Ollama."
            )
        elif not r["models"]:
            report["warnings"].append(
                "⚠️ Ollama запущена, но модели не установлены. "
                "Используйте «Выбор модели» для скачивания."
            )

    # ── 7. Глобальный хук исключений ─────────────────────────────────────
    install_global_exception_hook(qt_app=qt_app)

    # ── Итог ─────────────────────────────────────────────────────────────
    _plog("STARTUP", "=" * 55)
    if report["fatal"]:
        _plog("STARTUP", "❌ ДИАГНОСТИКА ПРОВАЛЕНА — запуск невозможен")
    elif report["warnings"]:
        _plog("STARTUP", f"⚠️ Завершено с предупреждениями ({len(report['warnings'])})")
    else:
        _plog("STARTUP", "✅ Все проверки пройдены")

    for w in report["warnings"]:
        _plog("STARTUP", f"  • {w}")
    for f in report["fixes"]:
        _plog("STARTUP", f"  🔧 {f}")
    _plog("STARTUP", "=" * 55)

    return report


# ══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ УТИЛИТЫ ДЛЯ run.py
# ══════════════════════════════════════════════════════════════════════════════

def safe_db_connect(db_path: str, timeout: float = 10.0) -> Optional[sqlite3.Connection]:
    """
    Открывает соединение с SQLite.
    При поломке БД — пробует починить и переоткрыть.
    Возвращает Connection или None.
    """
    try:
        conn = sqlite3.connect(db_path, timeout=timeout)
        conn.execute("SELECT 1")   # быстрая проверка
        return conn
    except sqlite3.DatabaseError as exc:
        _plog("DB", f"⚠️ Не удалось открыть {db_path}: {exc} — попытка починки...")
        check_database_health(db_path, auto_fix=True)
        try:
            return sqlite3.connect(db_path, timeout=timeout)
        except Exception as e2:
            log_error("DB_CONNECT", e2, extra=db_path)
            return None
    except Exception as exc:
        log_error("DB_CONNECT", exc, extra=db_path)
        return None


def safe_json_load(path: str, default=None) -> Any:
    """Читает JSON-файл. При любой ошибке возвращает default."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}
    except Exception as e:
        log_error("JSON_LOAD", e, extra=path)
        return default if default is not None else {}


def safe_json_save(path: str, data: dict) -> bool:
    """Пишет JSON-файл. При ошибке логирует и возвращает False."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log_error("JSON_SAVE", e, extra=path)
        return False


def build_fatal_error_message(report: dict) -> str:
    """Формирует текст сообщения о фатальной ошибке запуска."""
    lines = ["Не удалось запустить приложение.\n"]
    for w in report["warnings"]:
        lines.append(f"• {w}")
    lines.append("\nЧто делать:")
    # Подбираем советы по содержимому ошибок
    all_text = " ".join(report["warnings"]).lower()
    if "пакет" in all_text or "package" in all_text:
        pkg_check = report.get("checks", {}).get("packages", {})
        missing = pkg_check.get("missing", [])
        if missing:
            lines.append(f"1. Установите зависимости: pip install {' '.join(missing)}")
        else:
            lines.append("1. Перезапустите программу — пакеты были установлены автоматически")
    if "файл" in all_text or "file" in all_text:
        lines.append("2. Убедитесь что все .py файлы лежат рядом с run.py")
    if "ollama" in all_text:
        lines.append("3. Установите и запустите Ollama: https://ollama.ai")
    if "бд" in all_text or "база данных" in all_text:
        lines.append("4. Удалите повреждённые .db файлы — они будут пересозданы")
    if report["fixes"]:
        lines.append(f"\nАвтоматически исправлено: {', '.join(report['fixes'])}")
    return "\n".join(lines)