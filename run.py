import os
import sys
import re
import traceback
import sqlite3
import subprocess
import threading
import time
import platform
from datetime import datetime
from typing import Any
from PyQt6 import QtWidgets, QtGui, QtCore
import requests
import json

# ── Директория приложения и настройка путей ─────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# Явно добавляем папку ai_config (там лежат deepseek_config, mistral_config, qwen_config)
_AI_CONFIG_DIR = os.path.join(APP_DIR, "ai_config")
if os.path.isdir(_AI_CONFIG_DIR) and _AI_CONFIG_DIR not in sys.path:
    sys.path.insert(1, _AI_CONFIG_DIR)
    print(f"[PATH] ✓ ai_config добавлен в sys.path")

# Дополнительно сканируем остальные подпапки проекта (на случай будущих переносов)
_SKIP_DIRS = {"__pycache__", ".git", ".hg", ".venv", "venv", "env",
              "node_modules", "dist", "build", ".idea", ".vscode", "ai_config"}
for _dp, _dns, _fns in os.walk(APP_DIR, topdown=True):
    _dns[:] = [d for d in _dns if d not in _SKIP_DIRS and not d.startswith(".")]
    if _dp != APP_DIR and any(f.endswith(".py") for f in _fns) and _dp not in sys.path:
        sys.path.insert(1, _dp)
        print(f"[PATH] + {os.path.relpath(_dp, APP_DIR)}")
try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from OpenGL.GL import *
    _OPENGL_AVAILABLE = True
except ImportError:
    _OPENGL_AVAILABLE = False
    QOpenGLWidget = object  # заглушка чтобы не падали наследования
    print("[IMPORT] ⚠️ PyOpenGL не установлен — OpenGL-функции недоступны")
# Импорт менеджера чатов
from chat_manager import ChatManager
from context_memory_manager import ContextMemoryManager
# Singleton для LLaMA/общей памяти — аналогично _DS_MEMORY и _MISTRAL_MEMORY
# БЕЗ синглтона каждый get_memory_manager("llama") создаёт новый объект.
# Хотя ContextMemoryManager читает из SQLite и данные не теряются,
# единый объект гарантирует консистентность и упрощает отладку.
_CTX_MEMORY = ContextMemoryManager()
from ai_file_generator import (
    parse_generated_files,
    GeneratedFileWidget,
    FILE_GENERATION_PROMPT,
    detect_file_request,
    build_file_injection,
)

# ── Улучшенный подтекст — персональные предпочтения общения ─────────────────
try:
    from enhanced_subtext import get_subtext_injection, get_subtext_reminder, SubtextSettingBlock, subtext_track_message, SubtextManager as _SubtextManager
    _SUBTEXT_AVAILABLE = True
    print("[IMPORT] ✓ enhanced_subtext загружен")
except ImportError:
    _SUBTEXT_AVAILABLE = False
    def get_subtext_injection(): return ""
    def get_subtext_reminder(): return ""
    def subtext_track_message(msg): pass
    class _SubtextManager:
        @staticmethod
        def load(): return {}
    SubtextSettingBlock = None
    print("[IMPORT] ⚠️ enhanced_subtext.py не найден — функция недоступна")

# Постпроцессинг ответов (применяет фильтры к готовому тексту)
# mx_pipe удалён

# ui_render_hooks удалён

# Отдельная память для DeepSeek — изолирована от LLaMA (deepseek_memory.db)
try:
    from deepseek_memory_manager import DeepSeekMemoryManager
    # ─── СИНГЛТОН: один инстанс на всё время работы программы ───────────────
    # Это критично: _current_chat_id хранится в объекте, и если каждый раз
    # создавать новый DeepSeekMemoryManager() — состояние теряется и память
    # никогда не чистится при смене чата.
    _DS_MEMORY = DeepSeekMemoryManager()
    print("[IMPORT] ✓ deepseek_memory_manager загружен (singleton)")
except ImportError:
    print("[IMPORT] ⚠️ deepseek_memory_manager.py не найден — используется общая память")
    DeepSeekMemoryManager = None
    _DS_MEMORY = None

# ═══════════════════════════════════════════════════════════════
# ИСПРАВЛЕНИЕ №1: Импорт запрещенных английских слов (исправлено)
# ═══════════════════════════════════════════════════════════════
# Импорт списка запрещённых английских слов
FORBIDDEN_WORDS_DICT = {}
FORBIDDEN_WORDS_SET = set()
TOP_FORBIDDEN_FOR_PROMPT = []

try:
    # Пытаемся импортировать только FORBIDDEN_WORDS_DICT (он точно есть в файле)
    from forbidden_english_words import FORBIDDEN_WORDS_DICT as _imported_dict
    FORBIDDEN_WORDS_DICT = _imported_dict
    # Создаём SET из ключей словаря
    FORBIDDEN_WORDS_SET = set(FORBIDDEN_WORDS_DICT.keys())
    # TOP_FORBIDDEN_FOR_PROMPT оставляем пустым (он не используется критично)
    TOP_FORBIDDEN_FOR_PROMPT = []
    print(f"[IMPORT] ✓ Загружен список запрещённых английских слов ({len(FORBIDDEN_WORDS_DICT)} слов)")
except ImportError as e:
    print(f"[IMPORT] ⚠️ Файл forbidden_english_words.py не найден: {e}")
    print("[IMPORT] ⚠️ Фильтр английских слов будет работать с базовым словарём")
    FORBIDDEN_WORDS_DICT = {}
    FORBIDDEN_WORDS_SET = set()
    TOP_FORBIDDEN_FOR_PROMPT = []
except Exception as e:
    print(f"[IMPORT] ⚠️ Ошибка при импорте: {e}")
    print("[IMPORT] ⚠️ Фильтр английских слов будет работать с базовым словарём")
    FORBIDDEN_WORDS_DICT = {}
    FORBIDDEN_WORDS_SET = set()
    TOP_FORBIDDEN_FOR_PROMPT = []

# -------------------------
# Platform detection (для совместимости с Windows)
# -------------------------
IS_WINDOWS = sys.platform == "win32"

# ── Windows: включаем скруглённые углы через DWM ─────────────────────────────
# На Windows 10/11 WA_TranslucentBackground + border-radius в CSS не даёт
# нативных скруглений — углы отрисовываются квадратными поверх фона рабочего стола.
# Решение: применяем DWM DWMWCP_ROUND через ctypes, а фон заполняем сами.
def _apply_windows_rounded(widget, radius: int = 12):
    """
    Включает нативные скруглённые углы на Windows 11 через DWM API.
    На Windows 10 и других платформах — молчаливо игнорируется.
    Вызывать после show() виджета.
    """
    if not IS_WINDOWS:
        return
    try:
        import ctypes, ctypes.wintypes
        hwnd = int(widget.winId())
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2        # скруглённые
        DWMWCP_ROUNDSMALL = 3   # чуть меньше скруглённые (для мелких попапов)
        preference = DWMWCP_ROUNDSMALL if radius <= 10 else DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(ctypes.c_int(preference)),
            ctypes.sizeof(ctypes.c_int)
        )
    except Exception:
        pass  # Win10 / DWM недоступен — не критично


def _fix_popup_on_windows(widget):
    """
    Для всплывающих меню/диалогов на Windows: убираем WA_TranslucentBackground
    (он ломает рендер на Win10) и включаем нативные скруглённые углы через DWM.
    """
    if not IS_WINDOWS:
        return
    # WA_TranslucentBackground вызывает чёрные/белые углы на Win10 без Aero Glass
    widget.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, False)
    widget.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, False)



# ── Логотипы моделей встроены как base64 ─────────────────────────────────────
# Для надёжности: не зависят от расположения файлов на диске.
# Fallback: если файл assets/logos/<model>_logo.png существует рядом — берётся он.
import base64 as _b64

# ── Голосовой ввод ────────────────────────────────────────────────────────────
try:
    import sounddevice as _sd
    import numpy as _np
    _VOICE_AVAILABLE = True
except ImportError:
    _sd = None
    _np = None
    _VOICE_AVAILABLE = False
    print("[VOICE] sounddevice/numpy не установлен — голосовой ввод недоступен")

try:
    import speech_recognition as _sr
    _SR_AVAILABLE = True
except ImportError:
    _sr = None
    _SR_AVAILABLE = False
    print("[VOICE] SpeechRecognition не установлен — голосовой ввод недоступен")
_MODEL_LOGOS_B64 = {
    "llama3":   "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",
    "deepseek": "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",
    "mistral":  "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",
}
# DeepSeek R1 использует тот же логотип что и DeepSeek
_MODEL_LOGOS_B64["deepseek-r1"] = _MODEL_LOGOS_B64["deepseek"]
# Qwen логотип (встроен как base64; также подхватывается из logo/qwen_logo.png)
_MODEL_LOGOS_B64["qwen"] = "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"

def _get_model_logo_pixmap(model_key: str, size: int = 30) -> "QtGui.QPixmap":
    """Возвращает QPixmap логотипа модели.
    Порядок поиска:
      1. logo/{model_key}_logo.png     ← папка пользователя (приоритет)
      2. assets/logos/{model_key}_logo.png
      3. встроенный base64
    """
    from PyQt6 import QtGui, QtCore

    _search_paths = [
        os.path.join(APP_DIR, "logo",          f"{model_key}_logo.png"),
        os.path.join(APP_DIR, "assets", "logos", f"{model_key}_logo.png"),
    ]
    for file_path in _search_paths:
        px = QtGui.QPixmap(file_path)
        if not px.isNull():
            return px.scaled(size, size,
                             QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                             QtCore.Qt.TransformationMode.SmoothTransformation)

    # Встроенный base64
    b64 = _MODEL_LOGOS_B64.get(model_key, "")
    if b64:
        data = _b64.b64decode(b64)
        px2 = QtGui.QPixmap()
        # JPEG или PNG — loadFromData определяет формат автоматически
        px2.loadFromData(data)
        if not px2.isNull():
            return px2.scaled(size, size,
                              QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                              QtCore.Qt.TransformationMode.SmoothTransformation)
    return QtGui.QPixmap()  # пустой — покажем fallback-букву


# ═══════════════════════════════════════════════════════════════
# Apple-style Font System для Windows
# На Windows: Segoe UI Variable (Win11) / Segoe UI (Win10) —
# ближайший аналог SF Pro, с субпиксельным рендерингом.
# ═══════════════════════════════════════════════════════════════
def _apple_font(size: int, weight=None):
    """Шрифт в стиле Apple: Segoe UI Variable на Windows, Inter на других."""
    from PyQt6 import QtGui
    if IS_WINDOWS:
        candidates = ["Segoe UI Variable", "Segoe UI", "Inter"]
        chosen = next((n for n in candidates if n in QtGui.QFontDatabase.families()), "Segoe UI")
        font = QtGui.QFont(chosen, size)
        font.setHintingPreference(QtGui.QFont.HintingPreference.PreferNoHinting)
        try:
            font.setStyleStrategy(
                QtGui.QFont.StyleStrategy.PreferAntialias |
                QtGui.QFont.StyleStrategy.PreferQuality
            )
        except Exception:
            font.setStyleStrategy(QtGui.QFont.StyleStrategy.PreferAntialias)
    else:
        font = QtGui.QFont("Inter", size)
    if weight is not None:
        font.setWeight(weight)
    return font


# ── LLaMA-слой вынесен в llama_handler.py ──────────────────────────────
import llama_handler
from llama_handler import (
    USE_OLLAMA, OLLAMA_HOST, OLLAMA_MODEL, SUPPORTED_MODELS,
    # llama_handler.ASSISTANT_NAME — не импортируем, читаем напрямую: llama_handler.ASSISTANT_NAME
    AI_MODE_FAST, AI_MODE_THINKING, AI_MODE_PRO,
    SYSTEM_PROMPTS, MODE_STRATEGY_RULES,
    get_current_ollama_model, get_current_display_name,
    call_ollama_chat, warm_up_model, unload_model, unload_all_models,
)
# Мутируемые глобалы LLaMA — доступ только через модуль:
#   llama_handler.CURRENT_AI_MODEL_KEY   — текущая модель
#   llama_handler._APP_SHUTTING_DOWN     — флаг закрытия приложения
#   llama_handler._OLLAMA_SESSION        — HTTP-сессия

APP_TITLE = "AI Assistant"

# ── Регистрируем DeepSeek-R1 8B как отдельную модель ─────────────────────
# SUPPORTED_MODELS — мутируемый словарь из llama_handler
if "deepseek-r1" not in llama_handler.SUPPORTED_MODELS:
    llama_handler.SUPPORTED_MODELS["deepseek-r1"] = (
        "deepseek-r1:8b",   # ollama model name
        "DeepSeek R1",      # display name
    )
    SUPPORTED_MODELS["deepseek-r1"] = llama_handler.SUPPORTED_MODELS["deepseek-r1"]

# ── Регистрируем Qwen 3 как отдельную модель ───────────────────────────────
if "qwen" not in llama_handler.SUPPORTED_MODELS:
    llama_handler.SUPPORTED_MODELS["qwen"] = (
        "qwen3:14b",
        "Qwen 3",
    )
    SUPPORTED_MODELS["qwen"] = llama_handler.SUPPORTED_MODELS["qwen"]


# ── Регистрируем Mistral Nemo как отдельную модель ──────────────────────────
# Без этого change_ai_model("mistral") завершается с "Неизвестная модель"
# (проверка model_key not in SUPPORTED_MODELS на строке ~12179).
if "mistral" not in llama_handler.SUPPORTED_MODELS:
    llama_handler.SUPPORTED_MODELS["mistral"] = (
        "mistral-nemo:12b",  # будет перезаписано после импорта mistral_config
        "Mistral Nemo",
    )
    SUPPORTED_MODELS["mistral"] = llama_handler.SUPPORTED_MODELS["mistral"]

# Импортируем конфигурацию Mistral Nemo
try:
    from mistral_config import (
        get_mistral_system_prompt,
        clean_mistral_response,
        MISTRAL_MODEL_NAME,
        MISTRAL_DISPLAY_NAME,
        MISTRAL_OLLAMA_PULL,
    )
    print("[IMPORT] ✓ mistral_config загружен")
except ImportError:
    print("[IMPORT] ⚠️ mistral_config.py не найден — Mistral недоступен")
    def get_mistral_system_prompt(language, mode): return ""
    def clean_mistral_response(text): return text
    MISTRAL_MODEL_NAME    = "mistral-nemo:12b"
    MISTRAL_DISPLAY_NAME  = "Mistral Nemo"
    MISTRAL_OLLAMA_PULL   = "ollama pull mistral-nemo:12b"

# Обновляем SUPPORTED_MODELS["mistral"] с реальным именем модели
llama_handler.SUPPORTED_MODELS["mistral"] = (MISTRAL_MODEL_NAME, MISTRAL_DISPLAY_NAME)
SUPPORTED_MODELS["mistral"] = llama_handler.SUPPORTED_MODELS["mistral"]
print(f"[INIT] SUPPORTED_MODELS['mistral'] = {SUPPORTED_MODELS['mistral']}")

# Импортируем конфигурацию Qwen 3
try:
    from qwen_config import (
        get_qwen_system_prompt,
        clean_qwen_response,
        QWEN_MODEL_NAME,
        QWEN_DISPLAY_NAME,
        QWEN_OLLAMA_PULL,
    )
    print("[IMPORT] ✓ qwen_config загружен")
except ImportError:
    print("[IMPORT] ⚠️ qwen_config.py не найден — Qwen недоступен")
    def get_qwen_system_prompt(language, mode): return ""
    def clean_qwen_response(text): return text
    QWEN_MODEL_NAME   = "qwen3:14b"
    QWEN_DISPLAY_NAME = "Qwen 3"
    QWEN_OLLAMA_PULL  = "ollama pull qwen3:14b"

# Импортируем менеджер памяти Mistral
try:
    from mistral_memory_manager import MistralMemoryManager
    # ─── СИНГЛТОН: один инстанс на всё время работы программы ───────────────
    # Критично: если каждый раз создавать новый MistralMemoryManager() —
    # состояние теряется и запись в БД может завершаться ошибкой.
    _MISTRAL_MEMORY = MistralMemoryManager()
    print("[IMPORT] ✓ mistral_memory_manager загружен (singleton)")
except ImportError:
    print("[IMPORT] ⚠️ mistral_memory_manager.py не найден — используется общая память")
    MistralMemoryManager = None
    _MISTRAL_MEMORY = None

# Импортируем менеджер памяти Qwen
try:
    from qwen_memory_manager import QwenMemoryManager
    _QWEN_MEMORY = QwenMemoryManager()
    print("[IMPORT] ✓ qwen_memory_manager загружен (singleton)")
except ImportError:
    print("[IMPORT] ⚠️ qwen_memory_manager.py не найден — используется общая память")
    QwenMemoryManager = None
    _QWEN_MEMORY = None

# Импортируем конфигурацию DeepSeek
try:
    from deepseek_config import (
        get_deepseek_system_prompt,
        get_deepseek_math_prompt,
        clean_deepseek_latex,
        detect_user_correction,
        is_simple_arithmetic,
        compute_simple_arithmetic,
        is_garbage_math_response,
        sanitize_deepseek_math,
        sanitize_deepseek_file_response,
        DEEPSEEK_MODEL_NAME,
        DEEPSEEK_DISPLAY_NAME,
        DEEPSEEK_OLLAMA_PULL,
    )
    print("[IMPORT] ✓ deepseek_config загружен")
except ImportError:
    print("[IMPORT] ⚠️ deepseek_config.py не найден — DeepSeek недоступен")
    def get_deepseek_system_prompt(language, mode): return ""
    def get_deepseek_math_prompt(mode): return ""
    def clean_deepseek_latex(text): return text
    def detect_user_correction(msg): return False
    def is_simple_arithmetic(msg): return False, ""
    def compute_simple_arithmetic(expr, language="russian"): return None
    def is_garbage_math_response(resp): return False
    def sanitize_deepseek_math(resp, q, language="russian"): return resp
    def sanitize_deepseek_file_response(resp): return resp
    DEEPSEEK_MODEL_NAME = "deepseek-llm:7b-chat"
    DEEPSEEK_DISPLAY_NAME = "DeepSeek"
    DEEPSEEK_OLLAMA_PULL = "ollama pull deepseek-llm:7b-chat"


# Импортируем модуль для работы с Vision (LLaMA 3.2 Vision)
try:
    from vision_handler import (
        OLLAMA_VISION_MODEL,
        call_ollama_vision,
        process_image_file,
        is_image_file,
    )
    print("[IMPORT] ✓ vision_handler загружен")
except ImportError as _ve:
    print(f"[IMPORT] ⚠️ vision_handler.py не найден: {_ve}")
    OLLAMA_VISION_MODEL = "llama3.2-vision"
    def call_ollama_vision(image_path, prompt, max_tokens=800, timeout=120):
        return "❌ vision_handler.py не найден. Скопируйте файл рядом с run.py."
    def process_image_file(file_path, file_name, user_message, ai_mode, language):
        return {"success": False, "content": "❌ vision_handler.py не найден."}
    def is_image_file(file_path):
        import os
        return os.path.splitext(file_path)[1].lower() in {".png",".jpg",".jpeg",".gif",".bmp",".webp"}

# ── Диалоги скачивания/удаления моделей ────────────────────────────────
from model_downloader import (
    check_model_in_ollama,
    get_ollama_models_dir,
    set_ollama_models_env_and_restart,
    delete_model_files_from_disk,
    LlamaDownloadDialog,
    DeepSeekDownloadDialog,
    DeepSeekR1DownloadDialog,
    MistralDownloadDialog,
    DEEPSEEK_R1_MODEL_NAME,
    DEEPSEEK_R1_OLLAMA_PULL,
)

# ── Система проверок и самовосстановления ───────────────────────────────
from attachment_manager import AttachmentMixin
from error_handler import (
    startup_checks,
    check_ollama_health,
    check_database_health,
    check_settings_file,
    check_disk_space,
    install_global_exception_hook,
    guarded,
    safe_call,
    safe_db_connect,
    safe_json_load,
    safe_json_save,
    log_error,
    load_settings,
    save_settings,
    build_fatal_error_message,
)


# Google / DuckDuckGo helper config
DB_FILE = "chat_memory.db" 
MAX_HISTORY_LOAD = 15

# Текущий язык интерфейса — изменяется при авто-определении языка пользователя
CURRENT_LANGUAGE = "russian"

# Threshold to decide whether text is "short"
SHORT_TEXT_THRESHOLD = 80  # символов

# ════════════════════════════════════════════════════════════════
# ИСПРАВЛЕНИЕ №2: Расширенный список сокращений для обработки
# ════════════════════════════════════════════════════════════════
# Словарь сокращений которые должны генерировать ответ
import random as _random

# ─── Разговорные ответы без вызова АИ ────────────────────────────────────────
# Используются когда сообщение — чисто социальное (спасибо, ок, привет…).
# АИ при этом НЕ вызывается, чтобы исключить галлюцинации о предыдущем контексте.

_CONV_RESPONSES_RU = [
    "Пожалуйста! 😊",
    "Рад помочь! 😊",
    "Всегда пожалуйста! 😊",
    "Обращайтесь! 😊",
    "Не за что! 😊",
]
_CONV_RESPONSES_EN = [
    "You're welcome! 😊",
    "Happy to help! 😊",
    "Anytime! 😊",
    "Glad I could help! 😊",
    "No problem! 😊",
]
_CONV_SIMPLE = ["👍", "😊", "👍"]

def _conversational_response(text: str) -> str:
    """Подобрать простой ответ на разговорное сообщение по тексту."""
    t = text.lower()
    is_ru = any(c in t for c in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    # Благодарность
    if any(w in t for w in ("спасибо", "благодар", "спс", "thanks", "thx", "thank")):
        return _random.choice(_CONV_RESPONSES_RU if is_ru else _CONV_RESPONSES_EN)
    # Подтверждение / нейтральное
    return _random.choice(_CONV_SIMPLE)


def is_short_acknowledgment(text: str):
    """
    Проверяет является ли сообщение чисто разговорным (без вопросов/команд).
    Использует _is_conversational_message — единый детектор для всего приложения.
    Возвращает (True, ответ) если да, иначе (False, "").
    Примечание: _is_conversational_message определена ниже перед get_ai_response,
    поэтому здесь используем её через обёртку с отложенной привязкой.
    """
    stripped = text.strip()
    if len(stripped) > 80:
        return False, ""
    if "?" in stripped[:-1]:
        return False, ""
    import re as _re
    _pat = _re.compile(
        r"""^(?:
            спасибо[\w\s]{0,30}  | большое\s+спасибо | огромное\s+спасибо | благодар[\w]{1,10}[\s\w]{0,20} |
            ок[её]?й? | хорошо | понял[аи]? | понятно | ясно | отлично | супер |
            норм(?:ально)? | ладно | угу | ага | да | нет | конечно | договорились |
            всё\s+(?:ясно|понятно|окей|хорошо) |
            круто[\s!]* | класс[\s!]* | прекрасно[\s!]* | замечательно[\s!]* |
            шикарно[\s!]* | бомба[\s!]* | огонь[\s!]* | красота[\s!]* |
            привет[\w\s]{0,15} | здравствуй[\w\s]{0,15} | добрый\s+\w+ |
            пон(?:ял[аи]?)? | спс | хз |
            thanks?[\s\w]{0,25} | thank\s+you[\s\w]{0,25} | thx[\s!]* | ty[\s!]* |
            ok(?:ay)? | k{1,2} | got\s+it | i\s+see | understood | sure |
            ye[sp]|yup | cool[\s!]* | great[\s!]* | awesome[\s!]* |
            nice[\s!]* | perfect[\s!]* | sounds?\s+good | alright | roger |
            hi[\s\w]{0,10} | hello[\s\w]{0,10} | hey[\s\w]{0,10} | idk
        )[!?.,\s]*$""",
        _re.VERBOSE | _re.IGNORECASE | _re.UNICODE,
    )
    if _pat.match(stripped):
        return True, _conversational_response(stripped)
    return False, ""


# AI_MODE_* импортируются из llama_handler

# -------------------------
# Adaptive Intelligent Web Search System
# -------------------------


# ══════════════════════════════════════════════════════════════════
# ВЫНЕСЕНО В ОТДЕЛЬНЫЕ МОДУЛИ
# ══════════════════════════════════════════════════════════════════
from web_search import (
    # Поиск и анализ источников
    analyze_intent_for_search,
    google_search,
    deep_web_search,
    fallback_web_search,
    fetch_page_content,
    rank_and_select_sources,
    version_search_pipeline,
    summarize_sources,
    compress_search_results,
    detect_question_parts,
    validate_answer,
    build_final_answer_prompt,
    build_contextual_search_query,
    # Разговорные ответы
    is_short_acknowledgment,
    _conversational_response,
    # Иконка и UI-утилиты
    create_app_icon,
    _build_multi_size_icon,
    _apply_macos_dock_icon,
    create_menu_icon,
    # Языковые и текстовые утилиты
    detect_language_switch,
    detect_forget_command,
    detect_role_command,
    extract_forget_target,
    selective_forget_memory,
    detect_math_problem,
    detect_message_language,
    format_text_with_markdown_and_math,
    remove_english_words_from_russian,
    check_spelling_and_suggest,
    translate_to_russian,
    detect_language_of_text,
    # Константы
    INTERNET_REQUIRED_KEYWORDS,
    NO_INTERNET_KEYWORDS,
)

from ai_core import (
    get_ai_response,
    get_memory_manager,
    clear_chat_all_memories,
    clear_all_memories_global,
    on_chat_switched_all_memories,
    init_db,
    is_short_text,
    DB_FILE,
    MAX_HISTORY_LOAD,
    SHORT_TEXT_THRESHOLD,
)

# -------------------------
# Animated Checkbox
# -------------------------
class AnimatedCheckBox(QtWidgets.QCheckBox):
    """Чекбокс с плавной анимацией масштабирования через размер шрифта"""
    
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        
        # Флаг блокировки быстрых нажатий
        self.animation_in_progress = False
        
        try:
            # Сохраняем исходный размер шрифта с проверкой
            self.original_font = self.font()
            self.original_font_size = self.original_font.pointSize()
            if self.original_font_size <= 0:
                self.original_font_size = 11  # Дефолт для чекбоксов
            
            # Анимация размера шрифта
            self.font_animation = QtCore.QVariantAnimation()
            self.font_animation.setDuration(180)  # Быстро и плавно
            self.font_animation.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
            self.font_animation.valueChanged.connect(self.update_font_size)
        except Exception as e:
            print(f"[AnimatedCheckBox] Ошибка инициализации: {e}")
            self.original_font_size = 11
    
    def update_font_size(self, size):
        """Обновляет размер шрифта для эффекта масштабирования"""
        try:
            if hasattr(self, 'original_font') and size > 0:
                new_font = QtGui.QFont(self.original_font)
                new_font.setPointSize(int(size))
                self.setFont(new_font)
        except Exception as e:
            print(f"[AnimatedCheckBox] Ошибка update_font_size: {e}")
    
    def nextCheckState(self):
        """Переопределяем для добавления анимации"""
        if self.animation_in_progress:
            return
        
        try:
            # Запускаем анимацию
            self.start_animation()
        except Exception as e:
            print(f"[AnimatedCheckBox] Ошибка анимации: {e}")
        
        # Вызываем родительский метод
        super().nextCheckState()
    
    def start_animation(self):
        """Плавная анимация увеличения/уменьшения при клике"""
        try:
            self.animation_in_progress = True
            
            # Останавливаем текущую анимацию
            if hasattr(self, 'font_animation') and self.font_animation.state() == QtCore.QAbstractAnimation.State.Running:
                self.font_animation.stop()
            
            # Вычисляем размеры
            increase_size = self.original_font_size + 2  # Увеличение на 2pt
            
            # Анимация: нормальный → увеличенный → нормальный
            self.font_animation.setStartValue(self.original_font_size)
            self.font_animation.setKeyValueAt(0.5, increase_size)  # Середина - увеличение
            self.font_animation.setEndValue(self.original_font_size)  # Конец - возврат
            self.font_animation.start()
            
            # Разблокируем
            QtCore.QTimer.singleShot(180, lambda: setattr(self, 'animation_in_progress', False))
        except Exception as e:
            print(f"[AnimatedCheckBox] Ошибка start_animation: {e}")
            self.animation_in_progress = False

# -------------------------
# Glass Tooltip (стеклянная подсказка)
# -------------------------
class GlassTooltip(QtWidgets.QLabel):
    """Стеклянная подсказка с автоисчезновением"""
    
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        # Tool + FramelessWindowHint + StaysOnTop — работает на Win/Mac/Linux без мигания
        self.setWindowFlags(
            QtCore.Qt.WindowType.Tool |
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        # WA_TranslucentBackground нужен на всех платформах для прозрачного фона
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)

        # Стиль стеклянной подсказки — фон рисуется через paintEvent, не CSS
        self.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                padding: 8px 14px;
                color: #2d3748;
                font-family: Inter;
                font-size: 13px;
                font-weight: 500;
            }
        """)
        
        # Эффект прозрачности для анимации
        self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)
        
        # Анимация появления
        self.fade_in = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in.setDuration(350)  # 350ms - более плавная анимация
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)
        self.fade_in.setEasingCurve(QtCore.QEasingCurve.Type.OutExpo)  # Более естественная кривая
        
        # Анимация исчезновения
        self.fade_out = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out.setDuration(300)  # 300ms - плавное исчезновение
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QtCore.QEasingCurve.Type.InExpo)  # Симметричная кривая для исчезновения
        self.fade_out.finished.connect(self.hide)

    def paintEvent(self, event):
        """Рисуем стеклянный фон через QPainter — правильные скруглённые углы на всех платформах."""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)
        p.setClipPath(path)
        p.fillPath(path, QtGui.QColor(255, 255, 255, 210))
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 220))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)
        p.end()
        super().paintEvent(event)

    def show_at(self, global_pos):
        """Показать подсказку в указанной позиции"""
        self.adjustSize()
        # Позиционируем чуть ниже кнопки
        self.move(global_pos.x() - self.width() // 2, global_pos.y() + 10)
        self.show()
        self.fade_in.start()
        
        # Автоматически скрыть через 2 секунды
        QtCore.QTimer.singleShot(2000, self.hide_animated)
    
    def hide_animated(self):
        """Плавно скрыть подсказку"""
        self.fade_out.start()

# -------------------------
# FadingScrollArea — top-edge gradient overlay
# -------------------------
class _FadingViewport(QtWidgets.QWidget):
    """
    Drop-in replacement for the default QScrollArea viewport.

    paintEvent():
      1. Calls the normal viewport paint (all child message widgets render).
      2. Paints ONE semi-transparent gradient rect on top.
         • Colour: BLACK with varying alpha → creates subtle fade effect
           without "whitening" the content like white overlay did.
         • Alpha ramp: 0 … ~40 (out of 255) over FADE_HEIGHT pixels.
      3. Zero pixmap allocation per frame — QPainter draws directly into
         the device.  Single drawRect call.  Smooth at 60 fps.
      4. WA_TransparentForMouseEvents ensures gradient doesn't block clicks.
    """
    FADE_HEIGHT = 40   # Height of fade gradient in pixels

    def __init__(self, parent=None):
        super().__init__(parent)
        # ✅ Градиент не должен блокировать клики мыши на MessageWidget
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        # ✅ 1. ОБЯЗАТЕЛЬНО: Normal paint — every child widget (messages) draws itself FIRST.
        super().paintEvent(event)

        # 2. Paint the gradient overlay on top.
        #    Only worth painting when there is something to scroll over
        #    (i.e. content is taller than the viewport).
        scroll_area = self.parent()                          # the QScrollArea
        if scroll_area is None:
            return
        sb = scroll_area.verticalScrollBar()
        if sb is None or sb.maximum() == 0:
            # Nothing scrollable → no messages are hidden → skip.
            return

        # ✅ 3. Создаём QPainter ПОСЛЕ super().paintEvent()
        painter = QtGui.QPainter(self)
        
        # ✅ 4. ОБЯЗАТЕЛЬНО: Устанавливаем режим композиции ПЕРЕД рисованием
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)

        # ✅ 5. Используем полупрозрачный ЧЁРНЫЙ градиент вместо белого
        # Чёрный градиент создаёт затемнение (fade to dark), а не осветление (забеливание)
        # ✅ 6. Градиент рисуется только в верхней зоне FADE_HEIGHT, НЕ по всей высоте
        # ✅ ИСПРАВЛЕНО: Уменьшена интенсивность для более мягкого эффекта
        w = self.width()
        h = self.FADE_HEIGHT  # Только верхняя зона

        grad = QtGui.QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0,  QtGui.QColor(0, 0, 0, 25))   # ✅ Чёрный с alpha 25 вверху (мягче)
        grad.setColorAt(0.5,  QtGui.QColor(0, 0, 0, 10))   # ✅ Чёрный с alpha 10 в середине
        grad.setColorAt(1.0,  QtGui.QColor(0, 0, 0, 0))    # ✅ Полностью прозрачный внизу

        painter.setBrush(grad)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, w, h)  # Рисуем только в верхней зоне FADE_HEIGHT
        painter.end()


# -------------------------
# Скруглённый всплывающий попап (для Источников)
# -------------------------
class RoundedPopup(QtWidgets.QFrame):
    """QFrame с настоящими скруглёнными углами через paintEvent"""
    
    def __init__(self, radius=14, bg="#ffffff", border_color="rgba(200,205,225,0.9)", parent=None):
        super().__init__(parent)
        self._radius = radius
        self._bg = bg
        self._border_color = border_color
        self.setWindowFlags(
            QtCore.Qt.WindowType.Popup |
            QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        # Прозрачный фон у самого виджета — рисуем сами
        self.setStyleSheet("background: transparent; border: none;")
    
    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QPainterPath, QPen
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        path = QtGui.QPainterPath()
        path.addRoundedRect(
            QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
            self._radius, self._radius
        )
        
        # Заливка
        painter.setClipPath(path)
        painter.fillPath(path, QtGui.QColor(self._bg))
        
        # Граница
        pen = QtGui.QPen(QtGui.QColor(self._border_color))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()


# ─────────────────────────────────────────────────────────────────────────────
# Кастомный QGraphicsEffect: opacity + горизонтальный сдвиг без конфликта с layout
# ─────────────────────────────────────────────────────────────────────────────
class _SlideOpacityEffect(QtWidgets.QGraphicsEffect):
    """
    Рисует источник (виджет) со смещением по X и заданной прозрачностью.
    Поскольку рисование происходит в системе координат эффекта,
    layout-менеджер Qt не замечает сдвига и не борется с анимацией.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity: float = 0.0
        self._offset_x: float = 0.0

    # ── Qt-свойства (нужны QPropertyAnimation) ───────────────────────────────
    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, v: float):
        self._opacity = max(0.0, min(1.0, v))
        self.update()

    opacity_val = QtCore.pyqtProperty(float, _get_opacity, _set_opacity)

    def _get_offset_x(self) -> float:
        return self._offset_x

    def _set_offset_x(self, v: float):
        self._offset_x = v
        self.update()

    offset_x_val = QtCore.pyqtProperty(float, _get_offset_x, _set_offset_x)

    # ── Рисование ────────────────────────────────────────────────────────────
    def draw(self, painter: QtGui.QPainter):
        # В PyQt6 sourcePixmap возвращает (QPixmap, QPoint)
        result = self.sourcePixmap(QtCore.Qt.CoordinateSystem.LogicalCoordinates)
        if isinstance(result, tuple):
            pixmap, offset = result
        else:
            pixmap, offset = result, QtCore.QPoint()
        if pixmap.isNull():
            return
        painter.save()
        painter.setOpacity(self._opacity)
        painter.translate(self._offset_x, 0)
        painter.drawPixmap(offset, pixmap)
        painter.restore()

    def boundingRectFor(self, src_rect: QtCore.QRectF) -> QtCore.QRectF:
        # НЕ расширяем по горизонтали: если расширять, Qt пересчитывает ширины
        # всех соседних MessageWidget → они обрезают текст во время анимации.
        # Слайд-эффект просто клипируется по границе виджета — визуально незаметно,
        # т.к. offset за 380ms никогда не достигает края пузыря.
        return src_rect


# ── TTS-движок (вынесен в tts_engine.py) ──────────────────────────────────
try:
    from tts_engine import get_engine as _get_tts_engine, normalize_text as _tts_normalize
    _TTS_AVAILABLE = True
    print("[TTS] ✓ tts_engine загружен")
except ImportError:
    _TTS_AVAILABLE = False
    _get_tts_engine = None
    _tts_normalize = None
    print("[TTS] ⚠ tts_engine.py не найден")


# -------------------------
# Message widget (с адаптивным размером эмодзи)
# -------------------------
class MessageWidget(QtWidgets.QWidget):
    """Виджет для отображения сообщения"""

    def __init__(self, speaker: str, text: str, add_controls: bool = False,
                 language: str = "russian", main_window=None, parent=None, thinking_time: float = 0, action_history: list = None, attached_files: list = None, sources: list = None, is_acknowledgment: bool = False, generated_files: list = None):
        super().__init__(parent)
        
        # ✅ КРИТИЧНО: Size policy для виджета сообщения
        # Preferred по горизонтали - занимает предпочтительную ширину
        # Minimum по вертикали - НЕ позволяет layout сжимать виджет ниже его содержимого
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,   # Horizontal - предпочтительная ширина
            QtWidgets.QSizePolicy.Policy.Minimum      # Vertical - НЕ сжимается!
        )
        
        self.text = text
        self.language = language
        self.speaker = speaker  # Сохраняем спикера
        self.main_window = main_window  # Ссылка на главное окно
        self.copy_button = None  # Ссылка на кнопку копирования для анимации
        self.thinking_time = thinking_time  # Время обдумывания в секундах
        self.action_history = action_history or []  # История действий
        self.is_acknowledgment = is_acknowledgment  # Быстрый ответ без AI (нет регенерации)
        self.attached_files = list(attached_files) if attached_files else []  # Файлы для восстановления при отмене
        
        # ── История перегенерации ─────────────────────────────────────────
        # Каждая запись: {"text": str, "thinking_time": float, "action_history": list, "sources": list}
        self._regen_history = [{"text": text, "thinking_time": thinking_time, "action_history": action_history or [], "sources": sources or [], "speaker": speaker}]
        self._regen_idx = 0          # текущий индекс
        self._regen_prev_btn = None  # кнопка «‹»
        self._regen_next_btn = None  # кнопка «›»
        self._regen_counter = None   # метка «2/3»
        
        # Создаём кастомный эффект (opacity + slide без конфликта с layout)
        self._slide_eff = _SlideOpacityEffect(self)
        self.setGraphicsEffect(self._slide_eff)
        # opacity_effect — алиас для обратной совместимости со старым кодом
        self.opacity_effect = self._slide_eff

        # ═══════════════════════════════════════════════════════════════════════
        # ПОЛУЧАЕМ НАСТРОЙКИ LIQUID GLASS И ТЕМЫ ИЗ ГЛАВНОГО ОКНА
        # ═══════════════════════════════════════════════════════════════════════
        liquid_glass = True  # По умолчанию включено
        theme = "light"  # По умолчанию светлая
        
        if main_window:
            # Пытаемся загрузить сохранённые настройки
            try:
                if os.path.exists("app_settings.json"):
                    with open("app_settings.json", "r", encoding="utf-8") as f:
                        settings = json.load(f)
                        liquid_glass = settings.get("liquid_glass", True)
                        theme = settings.get("theme", "light")
            except Exception as e:
                print(f"[MSG_WIDGET] Не удалось загрузить настройки: {e}")

        # Сохраняем настройки для возможности обновления стилей
        self.current_theme = theme
        self.current_liquid_glass = liquid_glass

        # ═══════════════════════════════════════════════════════════════════════
        # ПРАВИЛЬНАЯ ЛОГИКА: СНАЧАЛА ТЕМА, ПОТОМ СТЕКЛО
        # ═══════════════════════════════════════════════════════════════════════
        # 
        # ЛОГИКА:
        # 1. Определяем базовые цвета по speaker
        # 2. Определяем тему (light/dark)
        # 3. Применяем liquid_glass (glass/matte)
        # 
        # РЕЗУЛЬТАТ:
        # Light + Glass → светлые стеклянные пузыри
        # Light + NoGlass → светлые матовые пузыри
        # Dark + Glass → тёмные стеклянные пузыри (НЕ светлые!)
        # Dark + NoGlass → тёмные матовые пузыри
        # ═══════════════════════════════════════════════════════════════════════
        
        # Цвет и выравнивание пузыря
        if speaker == "Вы":
            color = "#667eea"
            align = QtCore.Qt.AlignmentFlag.AlignRight
        elif speaker == "Система":
            color = "#48bb78"
            align = QtCore.Qt.AlignmentFlag.AlignCenter
        else:  # Ассистент
            color = "#764ba2"
            align = QtCore.Qt.AlignmentFlag.AlignLeft
        
        # Применяем стили на основе темы и liquid_glass
        if theme == "dark":
            # ═══ ТЁМНАЯ ТЕМА ═══
            if liquid_glass:
                # ТЁМНОЕ СТЕКЛО (прозрачное, с blur)
                bubble_bg = "rgba(35, 35, 40, 0.75)"
                bubble_border = "rgba(50, 50, 55, 0.6)"
                text_color = "#f0f0f0"
                btn_bg = "rgba(45, 45, 50, 0.55)"
                btn_bg_hover = "rgba(55, 55, 60, 0.65)"
                btn_border = "rgba(60, 60, 65, 0.4)"
                # Стекло не использует box-shadow
                box_shadow = "none"
            else:
                # ТЁМНЫЙ МАТОВЫЙ (solid, без прозрачности)
                # Добавляем легкую тень для depth
                bubble_bg = "rgb(43, 43, 48)"
                bubble_border = "rgba(60, 60, 65, 0.95)"  # Чуть темнее border
                text_color = "#f0f0f0"
                btn_bg = "rgb(38, 38, 42)"
                btn_bg_hover = "rgb(48, 48, 52)"
                btn_border = "rgba(58, 58, 62, 0.95)"
                # Subtle elevation с тенью
                box_shadow = "0 2px 8px rgba(0, 0, 0, 0.3)"
        else:
            # ═══ СВЕТЛАЯ ТЕМА ═══
            if liquid_glass:
                # СВЕТЛОЕ СТЕКЛО (прозрачное, с blur)
                bubble_bg = "rgba(255, 255, 255, 0.45)"
                bubble_border = "rgba(255, 255, 255, 0.65)"
                text_color = "#1a202c"
                btn_bg = "rgba(255, 255, 255, 0.55)"
                btn_bg_hover = "rgba(255, 255, 255, 0.75)"
                btn_border = "rgba(255, 255, 255, 0.72)"
                # Стекло не использует box-shadow
                box_shadow = "none"
            else:
                # СВЕТЛЫЙ МАТОВЫЙ (solid, без прозрачности)
                # Добавляем легкую тень для depth
                bubble_bg = "rgb(242, 242, 245)"
                bubble_border = "rgba(200, 200, 205, 0.95)"  # Чуть темнее border
                text_color = "#1a1a1a"
                btn_bg = "rgb(235, 235, 240)"
                btn_bg_hover = "rgb(225, 225, 230)"
                btn_border = "rgba(200, 200, 205, 0.95)"
                # Subtle elevation с тенью
                box_shadow = "0 2px 8px rgba(0, 0, 0, 0.15)"
        
        # Сохраняем стили для использования в кнопках и обновлениях
        self.bubble_bg = bubble_bg
        self.bubble_border = bubble_border
        self.box_shadow = box_shadow
        self.btn_bg = btn_bg
        self.btn_bg_hover = btn_bg_hover
        self.btn_border = btn_border
        self.text_color = text_color
        
        # Определяем цвет иконок в зависимости от liquid_glass и темы
        if liquid_glass:
            if theme == "dark":
                self.icon_color = "#a0a0b0"
            else:
                self.icon_color = "#5a6aaa"
            self.hover_border_color = "rgba(102, 126, 234, 0.40)"
            self.pressed_border_color = "rgba(102, 126, 234, 0.55)"
        else:
            if theme == "dark":
                self.icon_color = "#a0a0b0"
            else:
                self.icon_color = "#5a6aaa"
            self.hover_border_color = btn_border
            self.pressed_border_color = btn_border

        # краткость текста
        short = is_short_text(text)

        # Фиксированные размеры кнопок
        btn_size = 36
        emoji_size = 15
        btn_radius = btn_size // 2

        # главный layout
        main_layout = QtWidgets.QHBoxLayout(self)
        # Для симметрии: сообщения пользователя сдвигаем вправо, ИИ влево
        if align == QtCore.Qt.AlignmentFlag.AlignRight:
            # Сообщения пользователя - ближе к правому краю
            main_layout.setContentsMargins(80, 11, 6, 11)
        elif align == QtCore.Qt.AlignmentFlag.AlignLeft:
            # Сообщения ИИ - ближе к левому краю
            main_layout.setContentsMargins(6, 11, 80, 11)
        else:
            # Системные сообщения - по центру сверху с равными отступами
            main_layout.setContentsMargins(80, 11, 80, 11)
        main_layout.setSpacing(6)
        if align == QtCore.Qt.AlignmentFlag.AlignRight:
            main_layout.addStretch()
        elif speaker == "Система":
            # ✅ Для системных сообщений - центрируем пузырь
            main_layout.addStretch()

        # вертикальный столбик: метка времени (если есть) + пузырь + панель кнопок (вне пузыря)
        col_widget = QtWidgets.QWidget()
        # ✅ Minimum по вертикали - НЕ позволяет сжимать содержимое
        col_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        col_layout = QtWidgets.QVBoxLayout(col_widget)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(2)
        
        # Метка времени обдумывания (только для ИИ, если thinking_time > 0)
        if speaker != "Вы" and speaker != "Система" and thinking_time > 0:
            time_label = QtWidgets.QLabel(f"⏱ думал ~{thinking_time:.1f} с")
            time_label.setStyleSheet("""
                QLabel {
                    color: rgba(90, 106, 170, 0.75);
                    font-size: 11px;
                    font-style: italic;
                    padding: 2px 8px;
                    background: transparent;
                }
            """)
            time_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            col_layout.addWidget(time_label)

        # пузырь сообщения
        message_container = QtWidgets.QWidget()
        message_container.setObjectName("messageContainer")
        message_container.setMaximumWidth(900)
        message_container.setMinimumWidth(200)
        # ✅ Minimum по вертикали - bubble НЕ сжимается ниже размера текста
        message_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        message_container.setStyleSheet(f"""
            #messageContainer {{
                background-color: {self.bubble_bg};
                border: 1.5px solid {self.bubble_border};
                border-radius: 24px;
                padding: {'28px 44px' if speaker == 'Система' else '26px 34px'};
            }}
        """)
        
        # Сохраняем ссылку для обновления стилей
        self.message_container = message_container
        
        container_layout = QtWidgets.QVBoxLayout(message_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)  # Уменьшено с 6 до 4 для компактности пузыря

        # ─── Файловые бейджи (только для сообщений пользователя с прикреплёнными файлами) ───
        # ═══════════════════════════════════════════════════════════════════
        # ОТОБРАЖЕНИЕ ПРИКРЕПЛЕННЫХ ФАЙЛОВ (ВЫШЕ ПУЗЫРЯ, НЕ ВНУТРИ)
        # ═══════════════════════════════════════════════════════════════════
        if speaker == "Вы" and attached_files and len(attached_files) > 0:
            # Создаём контейнер для файлов ОТДЕЛЬНО от пузыря
            files_container = QtWidgets.QWidget()
            
            # Используем FlowLayout для красивого размещения файлов
            # Если файлов много - они автоматически перенесутся на новую строку
            files_layout = QtWidgets.QHBoxLayout(files_container)
            files_layout.setContentsMargins(0, 0, 0, 8)  # Отступ снизу до пузыря
            files_layout.setSpacing(8)
            files_layout.addStretch()  # Выравнивание справа для сообщений пользователя
            
            # Создаём вложенный контейнер для файлов с переносом
            files_wrapper = QtWidgets.QWidget()
            files_grid = QtWidgets.QGridLayout(files_wrapper)
            files_grid.setSpacing(6)
            files_grid.setContentsMargins(0, 0, 0, 0)
            
            # Показываем бейдж для каждого файла (максимум 3 в строке)
            for idx, file_path_or_name in enumerate(attached_files):
                row = idx // 3  # Строка
                col = idx % 3   # Столбец
                
                # Поддерживаем как полные пути так и просто имена файлов
                display_name_full = os.path.basename(file_path_or_name) if os.sep in file_path_or_name or '/' in file_path_or_name else file_path_or_name
                
                if is_image_file(file_path_or_name):
                    file_emoji = "🖼️"
                elif is_text_file(file_path_or_name):
                    file_emoji = "📄"
                else:
                    file_emoji = "📎"
                display_name = display_name_full if len(display_name_full) <= 30 else display_name_full[:27] + "…"
                # ═══════════════════════════════════════════════════════════════
                # КЛИКАБЕЛЬНАЯ КНОПКА вместо обычного Label
                # ═══════════════════════════════════════════════════════════════
                file_badge = QtWidgets.QPushButton(f"{file_emoji} {display_name}")
                file_badge.setFont(_apple_font(11))
                file_badge.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
                file_badge.setStyleSheet(f"""
                    QPushButton {{
                        color: rgba(102, 126, 234, 1.0);
                        background: rgba(102, 126, 234, 0.12);
                        border: 1px solid rgba(102, 126, 234, 0.28);
                        border-radius: 10px;
                        padding: 4px 10px;
                        text-align: left;
                    }}
                    QPushButton:hover {{
                        background: rgba(102, 126, 234, 0.20);
                        border: 1px solid rgba(102, 126, 234, 0.40);
                    }}
                    QPushButton:pressed {{
                        background: rgba(102, 126, 234, 0.28);
                    }}
                """)
                
                # Сохраняем полный путь как атрибут кнопки для открытия
                file_badge.setProperty("file_name", file_path_or_name)
                file_badge.clicked.connect(lambda checked=False, fn=file_path_or_name: self.open_attached_file(fn))
                
                files_grid.addWidget(file_badge, row, col)
            
            files_layout.addWidget(files_wrapper)
            
            # Добавляем контейнер файлов в главный layout (ВЫШЕ пузыря)
            col_layout.addWidget(files_container, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        message_label = QtWidgets.QLabel()
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
            QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        # Ограничиваем максимальную ширину текста
        message_label.setMaximumWidth(850)
        # ✅ Minimum по вертикали - текст НЕ сжимается ниже своего размера
        message_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        
        font = _apple_font(18)
        message_label.setFont(font)
        message_label.setStyleSheet(f"""
            QLabel {{
                color: {self.text_color};
                padding: 6px;
                line-height: 1.6;
                word-wrap: break-word;
            }}
        """)
        
        # Сохраняем ссылку для обновления стилей
        self.message_label = message_label
        
        # Применяем форматирование markdown и математических символов
        formatted_text = format_text_with_markdown_and_math(text)
        display_text = f"<b style='color:{color};'>{speaker}:</b><br>{formatted_text}"
        message_label.setText(display_text)
        self._speaker_color = color  # сохраняем для _regen_apply_entry
        message_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        
        # ✅ MessageWidget только обновляет себя, БЕЗ управления родителем
        # Layout автоматически пересчитает размеры после добавления виджета

        # Центрируем текст если его мало
        if short:
            message_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        container_layout.addWidget(message_label)


        # Добавляем контейнер с правильным выравниванием
        if align == QtCore.Qt.AlignmentFlag.AlignCenter:
            # Система - строго по центру
            col_layout.addWidget(message_container, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        elif align == QtCore.Qt.AlignmentFlag.AlignLeft:
            # AI - слева
            col_layout.addWidget(message_container, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        else:
            # Пользователь - справа
            col_layout.addWidget(message_container, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        # Решаем сторону для панели кнопок
        if speaker == "Вы":
            controls_side = "right"
        elif speaker == "Система":
            controls_side = "center"  # ✅ Системные сообщения - кнопки по центру
        else:
            controls_side = "left"

        # панель кнопок (вне пузыря)
        controls_widget = QtWidgets.QWidget()
        self.controls_widget = controls_widget   # ← сохраняем для stream-финализации
        controls_layout = QtWidgets.QHBoxLayout(controls_widget)
        controls_layout.setSpacing(10)
        bubble_padding = 18

        if controls_side == "left":
            controls_layout.setContentsMargins(bubble_padding, 4, 0, 6)
        elif controls_side == "right":
            controls_layout.setContentsMargins(0, 4, bubble_padding, 6)
        else:
            controls_layout.setContentsMargins(0, 4, 0, 6)

        # Кнопка копирования - ВСЕГДА видна для ИИ и пользователя
        copy_btn = QtWidgets.QPushButton()
        copy_btn.setText("📋")
        copy_btn.setToolTip("Копировать")
        copy_btn.setFixedSize(btn_size, btn_size)
        copy_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        copy_btn.clicked.connect(self.copy_text)
        copy_btn.setVisible(add_controls)
        self.copy_btn = copy_btn
        copy_btn.setObjectName("floatingControl")
        copy_btn.setStyleSheet(f"""
            QPushButton#floatingControl {{
                background: {self.btn_bg};
                color: {self.icon_color};
                border: 1px solid {self.btn_border};
                border-radius: {btn_radius}px;
                font-size: {emoji_size}px;
            }}
            QPushButton#floatingControl:hover {{ 
                background: {self.btn_bg_hover};
                border: 1px solid {self.hover_border_color};
            }}
            QPushButton#floatingControl:pressed {{ 
                background: {self.btn_bg_hover};
                border: 1px solid {self.pressed_border_color};
            }}
        """)
        self.copy_button = copy_btn  # Сохраняем ссылку для анимации
        controls_layout.addWidget(copy_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
        # Кнопка редактирования (только для пользователя)
        if speaker == "Вы":
            edit_btn = QtWidgets.QPushButton()
            edit_btn.setText("✏️")
            edit_btn.setToolTip("Редактировать")
            edit_btn.setFixedSize(btn_size, btn_size)
            edit_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            edit_btn.clicked.connect(self.edit_message)
            # ✅ Кнопка редактирования создаётся, но видимостью управляет add_message_widget
            edit_btn.setVisible(add_controls)
            edit_btn.setObjectName("floatingControl")
            edit_btn.setStyleSheet(f"""
                QPushButton#floatingControl {{
                    background: {self.btn_bg};
                    color: {self.icon_color};
                    border: 1px solid {self.btn_border};
                    border-radius: {btn_radius}px;
                    font-size: {emoji_size}px;
                }}
                QPushButton#floatingControl:hover {{ 
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.hover_border_color};
                }}
                QPushButton#floatingControl:pressed {{ 
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.pressed_border_color};
                }}
            """)
            controls_layout.addWidget(edit_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
            # Сохраняем ссылку на кнопку редактирования
            self.edit_button = edit_btn
        else:
            self.edit_button = None

        # Кнопка озвучки (только для ИИ)
        self.tts_button = None
        # copy_btn и regenerate_btn уже присвоены выше — не перезаписываем
        self.regenerate_btn = None
        self._tts_proc = None   # subprocess (say/espeak/pyttsx3 thread)
        if speaker != "Вы" and speaker != "Система" and add_controls:
            tts_btn = QtWidgets.QPushButton()
            tts_btn.setText("🔊")
            tts_btn.setToolTip("Озвучить ответ")
            tts_btn.setFixedSize(btn_size, btn_size)
            tts_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            tts_btn.setCheckable(True)
            tts_btn.setObjectName("floatingControl")
            tts_btn.setStyleSheet(f"""
                QPushButton#floatingControl {{
                    background: {self.btn_bg};
                    color: {self.icon_color};
                    border: 1px solid {self.btn_border};
                    border-radius: {btn_radius}px;
                    font-size: {emoji_size}px;
                }}
                QPushButton#floatingControl:hover {{
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.hover_border_color};
                }}
                QPushButton#floatingControl:checked {{
                    background: rgba(102, 126, 234, 0.18);
                    border: 1px solid rgba(102, 126, 234, 0.55);
                }}
                QPushButton#floatingControl:pressed {{
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.pressed_border_color};
                }}
            """)
            tts_btn.clicked.connect(self._toggle_tts)
            controls_layout.addWidget(tts_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.tts_button = tts_btn

        
        if speaker != "Вы" and speaker != "Система" and add_controls and not self.is_acknowledgment:
            regenerate_btn = QtWidgets.QPushButton()
            regenerate_btn.setText("🔄")
            regenerate_btn.setToolTip("Перегенерировать ответ")
            regenerate_btn.setFixedSize(btn_size, btn_size)
            regenerate_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            regenerate_btn.clicked.connect(self.regenerate_response)
            # ✅ ИСПРАВЛЕНИЕ: Кнопка перегенерации видна всегда (игнорируем short)
            regenerate_btn.setVisible(add_controls)
            regenerate_btn.setObjectName("floatingControl")
            self.regenerate_btn = regenerate_btn
            regenerate_btn.setStyleSheet(f"""
                QPushButton#floatingControl {{
                    background: {self.btn_bg};
                    color: {self.icon_color};
                    border: 1px solid {self.btn_border};
                    border-radius: {btn_radius}px;
                    font-size: {emoji_size}px;
                }}
                QPushButton#floatingControl:hover {{ 
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.hover_border_color};
                }}
                QPushButton#floatingControl:pressed {{ 
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.pressed_border_color};
                }}
            """)
            controls_layout.addWidget(regenerate_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
            
            # ── Кнопки навигации ‹ 1/1 › ─────────────────────────────────────
            # ВАЖНО: НЕ используем objectName("floatingControl") — иначе глобальный
            # стиль перебивает размеры и кнопки выглядят асимметрично.
            _ns = 28  # nav size
            _nr = _ns // 2
            _nav_btn_css = f"""
                QPushButton {{
                    background: {self.btn_bg};
                    color: {self.icon_color};
                    border: 1px solid {self.btn_border};
                    border-radius: {_nr}px;
                    font-size: 14px;
                    font-weight: 600;
                    min-width: {_ns}px;
                    max-width: {_ns}px;
                    min-height: {_ns}px;
                    max-height: {_ns}px;
                    padding: 0px;
                    margin: 0px;
                }}
                QPushButton:hover {{
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.hover_border_color};
                }}
                QPushButton:pressed {{ background: {self.btn_bg_hover}; }}
                QPushButton:disabled {{
                    opacity: 0.35;
                }}
            """
            _nav_lbl_css = f"""
                QLabel {{
                    color: {self.icon_color};
                    font-size: 11px;
                    font-weight: 600;
                    background: transparent;
                    border: none;
                    min-width: 28px;
                    max-width: 28px;
                    min-height: {_ns}px;
                    max-height: {_ns}px;
                    padding: 0px;
                    margin: 0px;
                }}
            """

            # Группируем ‹ 1/1 › в один QWidget для симметрии
            nav_group = QtWidgets.QWidget()
            nav_group.setVisible(False)  # скрыт пока 1 вариант
            nav_group_layout = QtWidgets.QHBoxLayout(nav_group)
            nav_group_layout.setContentsMargins(0, 0, 0, 0)
            nav_group_layout.setSpacing(2)

            prev_btn = QtWidgets.QPushButton("‹")
            prev_btn.setFixedSize(_ns, _ns)
            prev_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            prev_btn.setStyleSheet(_nav_btn_css)
            prev_btn.setEnabled(False)
            prev_btn.setToolTip("Предыдущий вариант")
            prev_btn.clicked.connect(self._regen_go_prev)

            counter_lbl = QtWidgets.QLabel("1/1")
            counter_lbl.setFixedSize(28, _ns)
            counter_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            counter_lbl.setStyleSheet(_nav_lbl_css)

            next_btn = QtWidgets.QPushButton("›")
            next_btn.setFixedSize(_ns, _ns)
            next_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            next_btn.setStyleSheet(_nav_btn_css)
            next_btn.setEnabled(False)
            next_btn.setToolTip("Следующий вариант")
            next_btn.clicked.connect(self._regen_go_next)

            nav_group_layout.addWidget(prev_btn)
            nav_group_layout.addWidget(counter_lbl)
            nav_group_layout.addWidget(next_btn)

            controls_layout.addWidget(nav_group, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

            self._regen_prev_btn = prev_btn
            self._regen_counter  = counter_lbl
            self._regen_next_btn = next_btn
            self._regen_nav_group = nav_group
            
            # Сохраняем ссылку на кнопку регенерации для управления видимостью
            self.regenerate_button = regenerate_btn
        else:
            self.regenerate_button = None

        controls_widget.setVisible(add_controls)

        # ── Кнопка "Источники" (только для ассистента, только если был поиск) ──
        self._sources_popup = None
        if speaker != "Вы" and speaker != "Система" and add_controls and sources and not self.is_acknowledgment:
            src_btn = QtWidgets.QPushButton("🔗 Источники")
            src_btn.setToolTip("Показать источники")
            src_btn.setFixedHeight(btn_size)
            src_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            src_btn.setObjectName("sourcesBtn")
            src_btn.setStyleSheet(f"""
                QPushButton#sourcesBtn {{
                    background: {self.btn_bg};
                    color: {self.icon_color};
                    border: 1px solid {self.btn_border};
                    border-radius: {btn_radius}px;
                    font-size: 12px;
                    padding: 0px 10px;
                }}
                QPushButton#sourcesBtn:hover {{
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.hover_border_color};
                }}
                QPushButton#sourcesBtn:pressed {{
                    background: {self.btn_bg_hover};
                }}
            """)
            self.sources_button = src_btn  # Сохраняем для обновления темы

            # Сохраняем источники в замыкании
            _sources = list(sources)

            def _toggle_sources(checked, btn=src_btn, srcs=_sources):
                # Безопасная проверка — C++ объект мог быть уже удалён
                if self._sources_popup is not None:
                    try:
                        visible = self._sources_popup.isVisible()
                    except RuntimeError:
                        self._sources_popup = None
                        visible = False
                    if visible:
                        # Плавное закрытие: fade-out + slide-down
                        popup_ref = self._sources_popup
                        self._sources_popup = None

                        _close_eff = QtWidgets.QGraphicsOpacityEffect(popup_ref)
                        popup_ref.setGraphicsEffect(_close_eff)
                        _close_eff.setOpacity(1.0)

                        _close_op = QtCore.QPropertyAnimation(_close_eff, b"opacity")
                        _close_op.setDuration(180)
                        _close_op.setStartValue(1.0)
                        _close_op.setEndValue(0.0)
                        _close_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

                        cur_geo = popup_ref.geometry()
                        _close_geo = QtCore.QPropertyAnimation(popup_ref, b"geometry")
                        _close_geo.setDuration(180)
                        _close_geo.setStartValue(cur_geo)
                        _close_geo.setEndValue(
                            QtCore.QRect(cur_geo.x(), cur_geo.y() + 10,
                                         cur_geo.width(), cur_geo.height())
                        )
                        _close_geo.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

                        def _do_close(p=popup_ref):
                            try:
                                p.close()
                            except Exception:
                                pass

                        _close_op.finished.connect(_do_close)
                        _close_op.start()
                        _close_geo.start()
                        popup_ref._close_anims = [_close_op, _close_geo, _close_eff]
                        return

                is_dark = getattr(self, 'current_theme', 'light') == 'dark'

                # Цвета по теме
                if is_dark:
                    bg = "#1e1e26"; border_c = "rgba(80,80,110,0.8)"
                    hdr_c = "#8888a8"; card_bg = "#26263a"; card_hover = "#30304a"
                    card_border = "rgba(70,70,100,0.6)"; link_c = "#8ab4f8"
                    domain_c = "#6688cc"; div_c = "rgba(80,80,110,0.3)"; text_bg = "#1e1e26"
                else:
                    bg = "#ffffff"; border_c = "rgba(200,205,225,0.9)"
                    hdr_c = "#888899"; card_bg = "#f5f6fc"; card_hover = "#eaedff"
                    card_border = "rgba(210,215,235,0.8)"; link_c = "#1a56db"
                    domain_c = "#5566aa"; div_c = "rgba(205,210,230,0.6)"; text_bg = "#ffffff"

                popup = RoundedPopup(
                    radius=14,
                    bg=bg,
                    border_color=border_c
                )
                popup.setMinimumWidth(320)
                popup.setMaximumWidth(440)

                outer = QtWidgets.QVBoxLayout(popup)
                outer.setContentsMargins(0, 0, 0, 0)
                outer.setSpacing(0)

                # ── Заголовок ──
                hdr_w = QtWidgets.QWidget()
                hdr_w.setStyleSheet("background: transparent;")
                hl = QtWidgets.QHBoxLayout(hdr_w)
                hl.setContentsMargins(14, 12, 14, 10)
                hl.setSpacing(6)
                ico_l = QtWidgets.QLabel("🔗")
                ico_l.setStyleSheet("background: transparent; font-size: 13px;")
                hl.addWidget(ico_l)
                cnt = len(srcs[:8])
                hdr_t = QtWidgets.QLabel(f"Источники · {cnt}")
                hdr_t.setStyleSheet(f"background: transparent; color: {hdr_c}; font-size: 12px; font-weight: 600; letter-spacing: 0.3px;")
                hl.addWidget(hdr_t)
                hl.addStretch()
                outer.addWidget(hdr_w)

                # Разделитель
                sep = QtWidgets.QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background: {div_c}; margin: 0 12px;")
                outer.addWidget(sep)

                # ── Список карточек ──
                list_w = QtWidgets.QWidget()
                list_w.setStyleSheet("background: transparent;")
                ll = QtWidgets.QVBoxLayout(list_w)
                ll.setContentsMargins(10, 8, 10, 10)
                ll.setSpacing(5)

                import urllib.parse as _up
                for i, src_item in enumerate(srcs[:8]):
                    # Совместимость: tuple или list
                    stitle = src_item[0] if len(src_item) > 0 else ""
                    surl = src_item[1] if len(src_item) > 1 else ""
                    try:
                        domain = _up.urlparse(surl).netloc.replace("www.", "") or surl[:25]
                    except Exception:
                        domain = surl[:25]

                    card = QtWidgets.QFrame()
                    card.setFixedHeight(58)
                    card.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
                    card.setToolTip(surl)
                    card.setStyleSheet(f"""
                        QFrame {{
                            background: {card_bg};
                            border: 1px solid {card_border};
                            border-radius: 9px;
                        }}
                        QFrame:hover {{
                            background: {card_hover};
                            border: 1px solid {link_c};
                        }}
                    """)

                    ci = QtWidgets.QHBoxLayout(card)
                    ci.setContentsMargins(10, 8, 10, 8)
                    ci.setSpacing(10)

                    # Favicon placeholder
                    fav_l = QtWidgets.QLabel("🌐")
                    fav_l.setFixedSize(22, 22)
                    fav_l.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                    fav_l.setStyleSheet("background: transparent; border: none; font-size: 15px;")
                    ci.addWidget(fav_l)

                    # Текст
                    tc = QtWidgets.QVBoxLayout()
                    tc.setSpacing(2)
                    tc.setContentsMargins(0, 0, 0, 0)

                    short_t = (stitle[:50] + "…") if len(stitle) > 50 else stitle
                    t_lbl = QtWidgets.QLabel(short_t)
                    t_lbl.setStyleSheet(f"background: transparent; color: {link_c}; font-size: 12px; font-weight: 600; border: none;")
                    t_lbl.setWordWrap(False)
                    tc.addWidget(t_lbl)

                    d_lbl = QtWidgets.QLabel(domain)
                    d_lbl.setStyleSheet(f"background: transparent; color: {domain_c}; font-size: 10px; border: none;")
                    tc.addWidget(d_lbl)

                    ci.addLayout(tc)
                    ci.addStretch()

                    arr = QtWidgets.QLabel("↗")
                    arr.setStyleSheet(f"background: transparent; color: {domain_c}; font-size: 13px; border: none;")
                    ci.addWidget(arr)

                    # Клик — открыть URL
                    _u = surl
                    def _on_click(_, url=_u):
                        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
                        popup.close()
                    card.mousePressEvent = _on_click
                    ll.addWidget(card)

                    # Асинхронная загрузка favicon
                    _fav_ref = fav_l
                    _fav_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=32"
                    def _fetch_fav(fu=_fav_url, lbl=_fav_ref):
                        try:
                            r = __import__('requests').get(fu, timeout=3)
                            if r.status_code == 200 and len(r.content) > 100:
                                px = QtGui.QPixmap()
                                px.loadFromData(r.content)
                                if not px.isNull():
                                    def _apply(p=px, l=lbl):
                                        try:
                                            l.setPixmap(p.scaled(22, 22,
                                                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                                QtCore.Qt.TransformationMode.SmoothTransformation))
                                            l.setText("")
                                        except RuntimeError:
                                            pass
                                    QtCore.QTimer.singleShot(0, _apply)
                        except Exception:
                            pass
                    __import__('threading').Thread(target=_fetch_fav, daemon=True).start()

                outer.addWidget(list_w)
                popup.adjustSize()

                # Позиционирование над кнопкой (с проверкой границ экрана)
                btn_global = btn.mapToGlobal(QtCore.QPoint(0, 0))
                ph = popup.sizeHint().height()
                pw = popup.sizeHint().width()
                x = btn_global.x()
                y = btn_global.y() - ph - 8
                scr = QtWidgets.QApplication.screenAt(btn_global)
                if scr:
                    sg = scr.geometry()
                    if x + pw > sg.right() - 8:
                        x = sg.right() - pw - 8
                    if x < sg.left() + 8:
                        x = sg.left() + 8
                    if y < sg.top() + 8:
                        y = btn_global.y() + btn.height() + 8

                popup.move(x, y)
                self._sources_popup = popup
                popup.destroyed.connect(lambda: setattr(self, '_sources_popup', None))

                # Плавное появление: fade-in + slide-up
                popup.show()
                popup.raise_()
                _p_eff = QtWidgets.QGraphicsOpacityEffect(popup)
                popup.setGraphicsEffect(_p_eff)
                _p_eff.setOpacity(0.0)
                _p_op = QtCore.QPropertyAnimation(_p_eff, b"opacity")
                _p_op.setDuration(220)
                _p_op.setStartValue(0.0)
                _p_op.setEndValue(1.0)
                _p_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                # slide-up: стартуем на 12px ниже
                _p_start_geo = QtCore.QRect(x, y + 12, popup.width(), popup.height())
                _p_end_geo   = QtCore.QRect(x, y,      popup.width(), popup.height())
                _p_geo = QtCore.QPropertyAnimation(popup, b"geometry")
                _p_geo.setDuration(220)
                _p_geo.setStartValue(_p_start_geo)
                _p_geo.setEndValue(_p_end_geo)
                _p_geo.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                def _src_cleanup(p=popup, e=_p_eff):
                    try: p.setGraphicsEffect(None)
                    except RuntimeError: pass
                _p_op.finished.connect(_src_cleanup)
                _p_op.start()
                _p_geo.start()
                # держим ссылки
                popup._src_anims = [_p_op, _p_geo, _p_eff]

            src_btn.clicked.connect(_toggle_sources)
            # Кнопка «Источники» — в один ряд с copy/regenerate
            controls_layout.addWidget(src_btn)

        # Добавляем панель под пузырём
        if controls_side == "left":
            col_layout.addWidget(controls_widget, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        elif controls_side == "right":
            col_layout.addWidget(controls_widget, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        else:
            col_layout.addWidget(controls_widget, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)

        # ── Карточки сгенерированных файлов (под кнопками) ──────────────
        self._generated_files = list(generated_files) if generated_files else []
        self._generated_files_widget = None
        if speaker != "Вы" and speaker != "Система" and self._generated_files:
            gen_widget = GeneratedFileWidget(
                self._generated_files,
                main_window=main_window,
                parent=self
            )
            col_layout.addWidget(gen_widget, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
            self._generated_files_widget = gen_widget
        
        # Вставляем в главный layout
        main_layout.addWidget(col_widget)
        if align == QtCore.Qt.AlignmentFlag.AlignLeft:
            main_layout.addStretch()
        elif speaker == "Система":
            # ✅ Для системных сообщений - добавляем stretch ПОСЛЕ для полного центрирования
            main_layout.addStretch()
        
        # ✅ ПЛАВНАЯ АНИМАЦИЯ: opacity + slide через _SlideOpacityEffect
        # Полный Mac-стиль на всех платформах
        if speaker == "Вы":
            _start_offset = 40.0
        elif speaker == "Система":
            _start_offset = 0.0
        else:
            _start_offset = -40.0

        self._slide_eff._offset_x = _start_offset
        self._slide_eff._opacity = 0.0
        self._anim_start_offset = _start_offset   # сохраняем для animate_remove

        # Анимация прозрачности 0 → 1
        self._anim_opacity = QtCore.QPropertyAnimation(self._slide_eff, b"opacity_val")
        self._anim_opacity.setDuration(380)
        self._anim_opacity.setStartValue(0.0)
        self._anim_opacity.setEndValue(1.0)
        self._anim_opacity.setEasingCurve(QtCore.QEasingCurve.Type.OutQuart)

        # Анимация сдвига _start_offset → 0
        self._anim_slide = QtCore.QPropertyAnimation(self._slide_eff, b"offset_x_val")
        self._anim_slide.setDuration(380)
        self._anim_slide.setStartValue(_start_offset)
        self._anim_slide.setEndValue(0.0)
        self._anim_slide.setEasingCurve(QtCore.QEasingCurve.Type.OutQuart)

        # Группа — оба эффекта идут параллельно
        self._appear_group = QtCore.QParallelAnimationGroup(self)
        self._appear_group.addAnimation(self._anim_opacity)
        self._appear_group.addAnimation(self._anim_slide)
        # Запуск — из add_message_widget через QTimer

    @QtCore.pyqtSlot()
    def _start_appear_animation(self):
        """
        Запускает параллельную fade+slide анимацию появления.
        Вызывается через QTimer из add_message_widget после layout.
        """
        if not hasattr(self, '_appear_group'):
            return
        try:
            self._appear_group.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._appear_group.finished.connect(self._on_appear_finished)
        self._appear_group.start()

    def _on_appear_finished(self):
        """После появления убираем эффект чтобы не было цветовых артефактов."""
        try:
            self.setGraphicsEffect(None)
            # Чистим ссылки
            for attr in ('_slide_eff', 'opacity_effect', '_appear_group',
                         '_anim_opacity', '_anim_slide'):
                if hasattr(self, attr):
                    delattr(self, attr)
        except Exception:
            pass

    def animate_remove(self, on_done_callback=None):
        """
        Плавно убирает виджет (обратная анимация: slide-out + fade-out),
        затем вызывает on_done_callback (там должны быть removeWidget + deleteLater).
        Если эффект уже снят (анимация давно завершилась) — создаём новый.
        """
        # Останавливаем appear-анимацию если она ещё идёт
        if hasattr(self, '_appear_group'):
            self._appear_group.stop()

        # Направление исхода: туда откуда пришло (или по speaker)
        start_offset = getattr(self, '_anim_start_offset', None)
        if start_offset is None:
            start_offset = 40.0 if getattr(self, 'speaker', '') == "Вы" else -40.0

        # Пересоздаём эффект (мог быть снят после appear)
        eff = _SlideOpacityEffect(self)
        eff._opacity = 1.0
        eff._offset_x = 0.0
        self.setGraphicsEffect(eff)

        # Анимации fade-out и slide-out
        fade_out = QtCore.QPropertyAnimation(eff, b"opacity_val")
        fade_out.setDuration(260)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QtCore.QEasingCurve.Type.InQuart)

        slide_out = QtCore.QPropertyAnimation(eff, b"offset_x_val")
        slide_out.setDuration(260)
        slide_out.setStartValue(0.0)
        slide_out.setEndValue(start_offset * 0.7)  # чуть меньше чтобы не улетал далеко
        slide_out.setEasingCurve(QtCore.QEasingCurve.Type.InQuart)

        self._remove_group = QtCore.QParallelAnimationGroup(self)
        self._remove_group.addAnimation(fade_out)
        self._remove_group.addAnimation(slide_out)

        def _finish():
            try:
                self.setGraphicsEffect(None)
            except Exception:
                pass
            if on_done_callback:
                on_done_callback()

        self._remove_group.finished.connect(_finish)
        self._remove_group.start(
            QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped
        )

    def _remove_graphics_effect_after_animation(self):
        """Оставлено для обратной совместимости."""
        self._on_appear_finished()


    def _cleanup_graphics_effect(self):
        """
        Завершает анимацию появления - удаляет graphicsEffect.
        
        ВАЖНО: Удаляем graphicsEffect чтобы избежать искажения цветов!
        После анимации эффект больше не нужен.
        """
        try:
            # Удаляем graphicsEffect полностью
            self.setGraphicsEffect(None)
            # Очищаем ссылки
            if hasattr(self, 'opacity_effect'):
                delattr(self, 'opacity_effect')
        except RuntimeError:
            # Объект уже удалён - игнорируем
            pass

    def update_message_styles(self, theme: str, liquid_glass: bool):
        """
        Обновляет стили виджета при изменении настроек темы или liquid_glass.
        
        ВАЖНО: НЕ пересоздаёт виджет, только обновляет стили.
        Layout НЕ изменяется.
        
        Параметры:
        - theme: "light" или "dark"
        - liquid_glass: True/False
        """
        # Сохраняем новые настройки
        self.current_theme = theme
        self.current_liquid_glass = liquid_glass
        
        # Пересчитываем стили по той же логике что и в __init__
        if theme == "dark":
            if liquid_glass:
                # ТЁМНОЕ СТЕКЛО
                bubble_bg = "rgba(35, 35, 40, 0.75)"
                bubble_border = "rgba(50, 50, 55, 0.6)"
                text_color = "#f0f0f0"
                btn_bg = "rgba(45, 45, 50, 0.55)"
                btn_bg_hover = "rgba(55, 55, 60, 0.65)"
                btn_border = "rgba(60, 60, 65, 0.4)"
                icon_color = "#a0a0b0"
                hover_border_color = "rgba(102, 126, 234, 0.40)"
                pressed_border_color = "rgba(102, 126, 234, 0.55)"
                box_shadow = "none"  # Стекло без тени
            else:
                # ТЁМНЫЙ МАТОВЫЙ (с чуть темнее border для depth)
                bubble_bg = "rgb(43, 43, 48)"
                bubble_border = "rgba(60, 60, 65, 0.95)"
                text_color = "#f0f0f0"
                btn_bg = "rgb(38, 38, 42)"
                btn_bg_hover = "rgb(48, 48, 52)"
                btn_border = "rgba(58, 58, 62, 0.95)"
                icon_color = "#a0a0b0"
                hover_border_color = btn_border
                pressed_border_color = btn_border
                box_shadow = "0 2px 8px rgba(0, 0, 0, 0.3)"  # Матовый с тенью
        else:
            if liquid_glass:
                # СВЕТЛОЕ СТЕКЛО
                bubble_bg = "rgba(255, 255, 255, 0.45)"
                bubble_border = "rgba(255, 255, 255, 0.65)"
                text_color = "#1a202c"
                btn_bg = "rgba(255, 255, 255, 0.55)"
                btn_bg_hover = "rgba(255, 255, 255, 0.75)"
                btn_border = "rgba(255, 255, 255, 0.72)"
                icon_color = "#5a6aaa"
                hover_border_color = "rgba(102, 126, 234, 0.40)"
                pressed_border_color = "rgba(102, 126, 234, 0.55)"
                box_shadow = "none"  # Стекло без тени
            else:
                # СВЕТЛЫЙ МАТОВЫЙ (с чуть темнее border для depth)
                bubble_bg = "rgb(242, 242, 245)"
                bubble_border = "rgba(200, 200, 205, 0.95)"
                text_color = "#1a1a1a"
                btn_bg = "rgb(235, 235, 240)"
                btn_bg_hover = "rgb(225, 225, 230)"
                btn_border = "rgba(200, 200, 205, 0.95)"
                icon_color = "#5a6aaa"
                hover_border_color = btn_border
                pressed_border_color = btn_border
                box_shadow = "0 2px 8px rgba(0, 0, 0, 0.15)"  # Матовый с тенью
        
        # Сохраняем новые стили
        self.bubble_bg = bubble_bg
        self.bubble_border = bubble_border
        self.box_shadow = box_shadow  # ✅ ИСПРАВЛЕНИЕ: Добавлено сохранение box_shadow
        self.btn_bg = btn_bg
        self.btn_bg_hover = btn_bg_hover
        self.btn_border = btn_border
        self.text_color = text_color
        self.icon_color = icon_color
        self.hover_border_color = hover_border_color
        self.pressed_border_color = pressed_border_color
        
        # Применяем стили к message_container
        if hasattr(self, 'message_container') and self.message_container:
            # ✅ ИСПРАВЛЕНИЕ: Используем тот же стиль что и в __init__
            self.message_container.setStyleSheet(f"""
                #messageContainer {{
                    background-color: {bubble_bg};
                    border: 1.5px solid {bubble_border};
                    border-radius: 24px;
                    padding: 26px 34px;
                }}
            """)
        
        # Применяем стили к message_label
        if hasattr(self, 'message_label') and self.message_label:
            self.message_label.setStyleSheet(f"""
                QLabel {{
                    color: {text_color};
                    padding: 8px;
                    line-height: 1.6;
                    word-wrap: break-word;
                }}
            """)
        
        # Обновляем стили кнопок (если они есть)
        btn_size = 36
        btn_radius = btn_size // 2
        emoji_size = 15
        
        button_style = f"""
            QPushButton#floatingControl {{
                background: {btn_bg};
                color: {icon_color};
                border: 1px solid {btn_border};
                border-radius: {btn_radius}px;
                font-size: {emoji_size}px;
            }}
            QPushButton#floatingControl:hover {{ 
                background: {btn_bg_hover};
                border: 1px solid {hover_border_color};
            }}
            QPushButton#floatingControl:pressed {{ 
                background: {btn_bg_hover};
                border: 1px solid {pressed_border_color};
            }}
        """
        
        # Применяем к кнопке копирования
        if hasattr(self, 'copy_button') and self.copy_button:
            self.copy_button.setStyleSheet(button_style)
        
        # Применяем ко всем floatingControl кнопкам
        for button in self.findChildren(QtWidgets.QPushButton):
            if button.objectName() == "floatingControl":
                button.setStyleSheet(button_style)

        # Отдельно обновляем кнопку источников (у неё другой objectName)
        if hasattr(self, 'sources_button') and self.sources_button:
            try:
                self.sources_button.setStyleSheet(f"""
                    QPushButton#sourcesBtn {{
                        background: {btn_bg};
                        color: {icon_color};
                        border: 1px solid {btn_border};
                        border-radius: {btn_radius}px;
                        font-size: 12px;
                        padding: 0px 10px;
                    }}
                    QPushButton#sourcesBtn:hover {{
                        background: {btn_bg_hover};
                        border: 1px solid {hover_border_color};
                    }}
                    QPushButton#sourcesBtn:pressed {{
                        background: {btn_bg_hover};
                    }}
                """)
            except RuntimeError:
                pass

        # Обновляем тему карточек сгенерированных файлов
        if hasattr(self, '_generated_files_widget') and self._generated_files_widget is not None:
            try:
                self._generated_files_widget.update_theme(theme, liquid_glass)
            except RuntimeError:
                pass

        # Обновляем кнопку TTS
        if hasattr(self, 'tts_button') and self.tts_button:
            try:
                self.tts_button.setStyleSheet(f"""
                    QPushButton#floatingControl {{
                        background: {btn_bg};
                        color: {icon_color};
                        border: 1px solid {btn_border};
                        border-radius: {btn_radius}px;
                        font-size: {emoji_size}px;
                    }}
                    QPushButton#floatingControl:hover {{
                        background: {btn_bg_hover};
                        border: 1px solid {hover_border_color};
                    }}
                    QPushButton#floatingControl:checked {{
                        background: rgba(102, 126, 234, 0.18);
                        border: 1px solid rgba(102, 126, 234, 0.55);
                    }}
                    QPushButton#floatingControl:pressed {{
                        background: {btn_bg_hover};
                        border: 1px solid {pressed_border_color};
                    }}
                """)
            except RuntimeError:
                pass

        print(f"[MSG_UPDATE] Стили обновлены: theme={theme}, liquid_glass={liquid_glass}")


    def copy_text(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.text)

        if self.copy_button:
            original_text = self.copy_button.text()
            # Просто меняем иконку на галочку — стиль не трогаем вообще
            self.copy_button.setText("✓")
            QtCore.QTimer.singleShot(1500, lambda: self._restore_copy_button(original_text, None))
    
    def _restore_copy_button(self, original_text, original_style):
        """Восстановление оригинального вида кнопки"""
        if self.copy_button:
            try:
                self.copy_button.setText(original_text)
            except RuntimeError:
                self.copy_button = None

    # ──────────────────────────────────────────────────────────────────────
    # TTS — Озвучка текста ответа ИИ (движок: tts_engine.py)
    # ──────────────────────────────────────────────────────────────────────

    def _toggle_tts(self):
        """Запускает или останавливает озвучку ответа."""
        btn = self.tts_button
        if btn is None:
            return

        # Если уже играет — стоп
        if getattr(self, '_tts_active', False):
            self._stop_tts()
            return

        if not _TTS_AVAILABLE:
            print("[TTS] tts_engine.py не загружен — озвучка недоступна")
            return

        if not self.text or not self.text.strip():
            return

        self._tts_active = True
        btn.setText("⏹")
        btn.setToolTip("Остановить озвучку")
        btn.setChecked(True)

        def _on_done():
            # Вызывается из фонового потока — переходим в GUI через invokeMethod
            try:
                QtCore.QMetaObject.invokeMethod(
                    self, "_tts_done",
                    QtCore.Qt.ConnectionType.QueuedConnection
                )
            except Exception:
                pass

        engine = _get_tts_engine()
        engine.speak(self.text, on_done=_on_done)



    @QtCore.pyqtSlot()
    def _tts_done(self):
        """Вызывается по завершении озвучки (в GUI-потоке)."""
        self._tts_active = False
        btn = self.tts_button
        if btn:
            try:
                btn.setText("🔊")
                btn.setToolTip("Озвучить ответ")
                btn.setChecked(False)
            except RuntimeError:
                pass

    def _stop_tts(self):
        """Принудительно останавливает озвучку."""
        self._tts_active = False
        if _TTS_AVAILABLE:
            try:
                _get_tts_engine().stop()
            except Exception:
                pass
        btn = self.tts_button
        if btn:
            try:
                btn.setText("🔊")
                btn.setToolTip("Озвучить ответ")
                btn.setChecked(False)
            except RuntimeError:
                pass


    def fade_out_and_delete(self):
        """
        Плавное исчезновение виджета через прозрачность.
        Использует _SlideOpacityEffect (совместимо с новой системой анимаций).
        """
        # Останавливаем TTS при удалении виджета
        self._stop_tts()

        # Останавливаем appear-анимацию если ещё идёт
        if hasattr(self, '_appear_group'):
            try:
                self._appear_group.stop()
            except Exception:
                pass

        # Создаём свежий эффект (appear мог его снять)
        eff = _SlideOpacityEffect(self)
        eff._opacity = 1.0
        eff._offset_x = 0.0
        self.setGraphicsEffect(eff)

        fade = QtCore.QPropertyAnimation(eff, b"opacity_val")
        fade.setDuration(300)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        def safe_delete():
            try:
                self.setGraphicsEffect(None)
                self.deleteLater()
                print("[FADE_OUT] Системное сообщение плавно удалено")
            except RuntimeError:
                pass
            except Exception as ex:
                print(f"[FADE_OUT] Ошибка: {ex}")

        fade.finished.connect(safe_delete)
        self._fade_out_anim = fade  # держим ссылку
        fade.start()
        print("[FADE_OUT] Запущена анимация fade-out")



    def _regen_update_nav(self):
        """Обновить кнопки навигации и счётчик после изменения истории."""
        total = len(self._regen_history)
        idx   = self._regen_idx
        show  = total > 1
        
        # Показываем/скрываем group-контейнер целиком
        nav_group = getattr(self, '_regen_nav_group', None)
        if nav_group:
            nav_group.setVisible(show)
        else:
            # Fallback: управляем по отдельности (старый код)
            for w in [self._regen_prev_btn, self._regen_counter, self._regen_next_btn]:
                if w:
                    w.setVisible(show)
        
        if show:
            if self._regen_counter:
                self._regen_counter.setText(f"{idx + 1}/{total}")
            if self._regen_prev_btn:
                self._regen_prev_btn.setEnabled(idx > 0)
            if self._regen_next_btn:
                self._regen_next_btn.setEnabled(idx < total - 1)

    def _regen_go_prev(self):
        """Показать предыдущий вариант ответа."""
        if self._regen_idx > 0:
            self._regen_idx -= 1
            self._regen_apply_entry(self._regen_idx)

    def _regen_go_next(self):
        """Показать следующий вариант ответа."""
        if self._regen_idx < len(self._regen_history) - 1:
            self._regen_idx += 1
            self._regen_apply_entry(self._regen_idx)

    def _regen_apply_entry(self, idx: int):
        """Применить запись из истории: обновить текст, имя модели и счётчик."""
        if idx < 0 or idx >= len(self._regen_history):
            return
        entry = self._regen_history[idx]
        self.text = entry["text"]
        # Обновляем имя модели (при перегенерации через другую модель)
        if entry.get("speaker"):
            self.speaker = entry["speaker"]
        
        # Обновляем текст пузыря
        if hasattr(self, 'message_label') and self.message_label:
            try:
                formatted = format_text_with_markdown_and_math(entry["text"])
            except Exception:
                formatted = entry["text"]
            color = getattr(self, '_speaker_color', '#4CAF50')
            self.message_label.setText(
                f"<b style='color:{color};'>{self.speaker}:</b><br>{formatted}"
            )
        
        self._regen_update_nav()

    def add_regen_entry(self, text: str, thinking_time: float = 0,
                        action_history: list = None, sources: list = None,
                        speaker: str = None):
        """
        Добавить новый вариант в историю перегенерации.
        speaker — имя модели (может отличаться при force_model_key).
        """
        entry = {
            "text": text,
            "thinking_time": thinking_time,
            "action_history": action_history or [],
            "sources": sources or [],
            "speaker": speaker or self.speaker,
        }
        self._regen_history.append(entry)
        self._regen_idx = len(self._regen_history) - 1
        self._regen_apply_entry(self._regen_idx)
        self._regen_update_nav()
        # Восстанавливаем яркость после перегенерации
        self._set_regen_dim(False)
        # ВАЖНО: _persist_regen_history НЕ вызываем здесь — она должна вызываться
        # ПОСЛЕ save_message в handle_response, иначе обновляется старая запись БД.
        print(f"[REGEN_HISTORY] Вариант {self._regen_idx + 1}/{len(self._regen_history)}, модель: {entry['speaker']}")

    def _set_regen_dim(self, dimmed: bool):
        """Затемнить/восстановить пузырь во время перегенерации.
        
        ВАЖНО: после fade-in анимации setGraphicsEffect(None) убивает opacity_effect.
        Поэтому мы всегда создаём НОВЫЙ эффект, а не переиспользуем старый.
        """
        try:
            if dimmed:
                # Создаём свежий эффект и вешаем на виджет
                eff = QtWidgets.QGraphicsOpacityEffect(self)
                self.setGraphicsEffect(eff)
                self.opacity_effect = eff
                eff.setOpacity(1.0)
                anim = QtCore.QPropertyAnimation(eff, b"opacity")
                anim.setDuration(200)
                anim.setStartValue(1.0)
                anim.setEndValue(0.38)
                anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                anim.start()
                self._dim_anim = anim
            else:
                # Берём текущий эффект (может быть нашим dim-эффектом)
                eff = self.graphicsEffect()
                if eff is None:
                    return  # уже чистый, ничего делать не нужно
                cur_opacity = eff.opacity() if hasattr(eff, 'opacity') else 0.38
                anim = QtCore.QPropertyAnimation(eff, b"opacity")
                anim.setDuration(250)
                anim.setStartValue(cur_opacity)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                # После восстановления убираем эффект (иначе он искажает цвета)
                anim.finished.connect(lambda: self.setGraphicsEffect(None))
                anim.start()
                self._dim_anim = anim
        except Exception as e:
            print(f"[DIM] Ошибка затемнения: {e}")

    def _persist_regen_history(self):
        """Сохранить историю перегенерации в БД через main_window."""
        try:
            mw = self.main_window
            if not mw:
                return
            chat_id = getattr(mw, 'current_chat_id', None)
            if not chat_id:
                return
            cm = getattr(mw, 'chat_manager', None)
            if not cm:
                return
            msg_id = cm.get_last_assistant_message_id(chat_id)
            if not msg_id:
                return
            cm.update_regen_history(chat_id, msg_id, self._regen_history)
            print(f"[REGEN_HISTORY] ✓ Сохранено в БД msg_id={msg_id}, вариантов={len(self._regen_history)}")
        except Exception as e:
            print(f"[REGEN_HISTORY] ⚠️ Ошибка сохранения: {e}")

    def regenerate_response(self):
        """Перегенерировать ответ ассистента — показывает меню выбора модели"""
        parent_window = self.window()
        if not hasattr(parent_window, 'regenerate_last_response'):
            return

        # ── Определяем текущую модель и список альтернатив ──────────
        current_key  = llama_handler.CURRENT_AI_MODEL_KEY
        current_name = llama_handler.SUPPORTED_MODELS.get(current_key, ("", "LLaMA 3"))[1]

        # Список всех моделей кроме текущей — для пунктов «перегенерировать через»
        _all_keys  = list(llama_handler.SUPPORTED_MODELS.keys())
        _alt_keys  = [k for k in _all_keys if k != current_key]

        # ── Создаём контекстное меню ─────────────────────────────────
        menu = QtWidgets.QMenu(self)
        menu.setWindowFlags(
            QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint
        )
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        menu.aboutToShow.connect(lambda: _apply_windows_rounded(menu, radius=12))

        is_dark = getattr(parent_window, 'current_theme', 'dark') == 'dark'

        # Единый стиль для main menu и submenu — одинаковый вид
        _c = {
            "bg":       "rgba(28,28,32,0.98)"  if is_dark else "rgba(255,255,255,0.98)",
            "border":   "rgba(60,60,70,0.8)"   if is_dark else "rgba(200,200,215,0.9)",
            "text":     "#e0e0e0"               if is_dark else "#1a202c",
            "sel_bg":   "rgba(60,60,75,0.9)"   if is_dark else "rgba(225,228,248,0.95)",
            "sel_txt":  "#ffffff"               if is_dark else "#0f172a",
            "sep":      "rgba(80,80,100,0.4)"  if is_dark else "rgba(180,185,200,0.5)",
            "arrow":    "#9999bb"               if is_dark else "#6677aa",
            "dim":      "rgba(140,140,160,0.5)" if is_dark else "rgba(120,130,150,0.6)",
        }
        _shared_style = f"""
            QMenu {{
                background: {_c['bg']};
                border: 1px solid {_c['border']};
                border-radius: 12px;
                padding: 4px 4px;
                min-width: 200px;
            }}
            QMenu::item {{
                padding: 8px 32px 8px 14px;
                border-radius: 8px;
                color: {_c['text']};
                font-size: 13px;
                font-weight: 500;
                margin: 1px 2px;
            }}
            QMenu::item:selected {{
                background: {_c['sel_bg']};
                color: {_c['sel_txt']};
            }}
            QMenu::item:disabled {{
                color: {_c['dim']};
                background: transparent;
            }}
            QMenu::separator {{
                height: 1px;
                background: {_c['sep']};
                margin: 3px 10px;
            }}
            QMenu::right-arrow {{
                width: 6px;
                height: 6px;
                margin-right: 8px;
            }}
        """
        menu.setStyleSheet(_shared_style)

        act_same  = menu.addAction(f"Перегенерировать  ({current_name})")
        menu.addSeparator()

        # ── Подменю «Другая модель» ───────────────────────────────────
        # Используем нативный QMenu::item::menu-arrow для стрелки.
        # Ключ: стили submenu совпадают с родительским — нет двойной рамки.
        submenu = QtWidgets.QMenu("Другая модель...", menu)
        submenu.setWindowFlags(
            QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint
        )
        submenu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        submenu.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        submenu.aboutToShow.connect(lambda: _apply_windows_rounded(submenu, radius=12))
        submenu.setStyleSheet(_shared_style)

        _alt_actions = {}
        for _alt_key in _alt_keys:
            _alt_display = llama_handler.SUPPORTED_MODELS.get(_alt_key, ("", _alt_key))[1]
            _installed   = check_model_in_ollama(
                llama_handler.SUPPORTED_MODELS.get(_alt_key, (_alt_key,))[0]
            )
            _suffix = "" if _installed else "  (не скачана)"
            _act    = submenu.addAction(f"{_alt_display}{_suffix}")
            _alt_actions[_act] = (_alt_key, _installed, _alt_display)

        menu.addMenu(submenu)

        # ── Показываем меню рядом с кнопкой ─────────────────────────
        btn = self.regenerate_button
        if btn:
            pos = btn.mapToGlobal(QtCore.QPoint(0, btn.height() + 4))
        else:
            pos = QtGui.QCursor.pos()

        chosen = menu.exec(pos)
        if chosen is None:
            return

        if chosen == act_same:
            parent_window.regenerate_last_response()
        elif chosen in _alt_actions:
            _target_key, _is_installed, _target_display = _alt_actions[chosen]
            if _is_installed:
                parent_window.regenerate_last_response(force_model_key=_target_key)
            else:
                # Модель не скачана — предлагаем скачать
                reply = QtWidgets.QMessageBox.question(
                    self.window(),
                    f"{_target_display} не установлена",
                    f"{_target_display} ещё не скачана.\n\nХотите скачать её сейчас?",
                    QtWidgets.QMessageBox.StandardButton.Yes |
                    QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.Yes,
                )
                if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                    _pw = self.window()
                    if hasattr(_pw, '_start_model_download'):
                        _pw._start_model_download(_target_key)
    
    def edit_message(self):
        """Редактировать сообщение пользователя"""
        parent_window = self.window()
        if hasattr(parent_window, 'edit_last_message'):
            parent_window.edit_last_message(self.text)
    

# -------------------------
# Worker
# -------------------------

    def open_attached_file(self, file_name):
        """Открыть прикреплённый файл при клике.
        
        Если передан полный путь — используем его напрямую.
        Если только имя файла (старые сообщения из БД) — ищем по имени в known paths.
        Для изображений показывает мини-просмотрщик внутри приложения.
        """
        print(f"[FILE_OPEN] Клик по файлу: {file_name}")

        # ── 1. Определяем реальный путь ────────────────────────────────
        # Если это уже абсолютный путь — используем как есть
        if os.path.isabs(file_name) and os.path.exists(file_name):
            file_path = file_name
        else:
            # Старые записи из БД содержат только basename — ищем в текущих attached_files
            file_path = None
            if self.main_window and hasattr(self.main_window, 'attached_files'):
                for fp in self.main_window.attached_files:
                    if os.path.basename(fp) == os.path.basename(file_name):
                        file_path = fp
                        break
            # Последняя попытка — относительный путь как есть
            if not file_path:
                file_path = os.path.abspath(file_name)

        file_path = os.path.normpath(file_path)
        print(f"[FILE_OPEN] Путь: {file_path}")

        # ── 2. Проверяем существование ──────────────────────────────────
        if not os.path.exists(file_path):
            print(f"[FILE_OPEN] ✗ Не найден: {file_path}")
            QtWidgets.QMessageBox.warning(
                self, "Файл не найден",
                f"Файл не найден по пути:\n{file_path}\n\n"
                f"Возможно, файл был перемещён или удалён.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            return

        # ── 3. Изображения — показываем мини-просмотрщик ───────────────
        if is_image_file(file_path):
            print(f"[FILE_OPEN] Открываю изображение в просмотрщике")
            self._show_image_viewer(file_path)
            return

        # ── 4. Текстовые файлы — мини-просмотрщик внутри приложения ──────
        if is_text_file(file_path):
            print(f"[FILE_OPEN] Открываю текстовый файл в просмотрщике")
            self._show_text_viewer(file_path)
            return

        # ── 5. Остальные файлы — системное приложение ──────────────────
        print(f"[FILE_OPEN] ✓ Открываю в системном приложении: {file_path}")
        try:
            if sys.platform == 'darwin':
                subprocess.run(['open', file_path], check=True)
            elif sys.platform == 'win32':
                os.startfile(file_path)
            else:
                subprocess.run(['xdg-open', file_path], check=True)
            print(f"[FILE_OPEN] ✅ Открыт успешно")
        except Exception as e:
            print(f"[FILE_OPEN] ✗ Ошибка: {e}")
            QtWidgets.QMessageBox.warning(
                self, "Ошибка открытия",
                f"Не удалось открыть файл:\n{file_path}\n\n{e}",
                QtWidgets.QMessageBox.StandardButton.Ok
            )

    def _show_image_viewer(self, file_path: str):
        """Мини-просмотрщик изображений — показывает фото в окошке внутри приложения."""
        viewer = _ImageViewerDialog(file_path, parent=self)
        viewer.exec()

    def _show_text_viewer(self, file_path: str):
        """Мини-просмотрщик текстовых файлов."""
        viewer = _TextViewerDialog(file_path, parent=self)
        viewer.exec()

    def _preview_file(self, file_path: str):
        """Открывает предпросмотр файла: изображение или текст."""
        if is_image_file(file_path):
            self._show_image_viewer(file_path)
        elif is_text_file(file_path):
            self._show_text_viewer(file_path)
        else:
            self.open_file(file_path)



# ═══════════════════════════════════════════════════════════════════════════
# МИНИ-ПРОСМОТРЩИК ИЗОБРАЖЕНИЙ
# ═══════════════════════════════════════════════════════════════════════════

class _ImageViewerDialog(QtWidgets.QDialog):
    """Мини-окно для просмотра изображений с zoom/pan."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle(os.path.basename(file_path))
        self.setModal(True)
        self.setMinimumSize(400, 300)
        self.resize(800, 600)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self._pixmap_orig = QtGui.QPixmap(file_path)
        if self._pixmap_orig.isNull():
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Не удалось загрузить изображение.")
            QtCore.QTimer.singleShot(0, self.close)
            return
        self._build_ui()
        QtCore.QTimer.singleShot(50, self._fit_to_window)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._canvas = _ImageCanvas(self._pixmap_orig, self)
        layout.addWidget(self._canvas, stretch=1)

        bar = QtWidgets.QWidget()
        bar.setStyleSheet("background:#1a1b2e;border-top:1px solid rgba(102,126,234,0.25);")
        bar.setFixedHeight(48)
        bl = QtWidgets.QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(10)

        path_lbl = QtWidgets.QLabel(self.file_path)
        path_lbl.setStyleSheet("color:rgba(180,185,220,0.7);font-size:11px;")
        bl.addWidget(path_lbl, stretch=1)

        btn_style = ("QPushButton{color:white;background:rgba(102,126,234,0.25);"
                     "border:1px solid rgba(102,126,234,0.4);border-radius:8px;"
                     "padding:5px 14px;font-size:13px;}"
                     "QPushButton:hover{background:rgba(102,126,234,0.45);}"
                     "QPushButton:pressed{background:rgba(102,126,234,0.6);}")

        for label, slot in [("⊡ По размеру", self._fit_to_window),
                             ("↗ В приложении", self._open_external),
                             ("✕ Закрыть", self.close)]:
            btn = QtWidgets.QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(slot)
            bl.addWidget(btn)

        layout.addWidget(bar)
        self._canvas.request_fit = self._fit_to_window
        self.setStyleSheet("QDialog{background:#0d0e1a;}")

    def _fit_to_window(self):
        if self._pixmap_orig.isNull():
            return
        cw, ch = self._canvas.width(), self._canvas.height()
        pw, ph = self._pixmap_orig.width(), self._pixmap_orig.height()
        if pw == 0 or ph == 0 or cw == 0 or ch == 0:
            return
        scale = min(cw / pw, ch / ph) * 0.95
        self._canvas.set_transform(scale, QtCore.QPointF(0, 0))

    def _open_external(self):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", self.file_path], check=True)
            elif sys.platform == "win32":
                os.startfile(self.file_path)
            else:
                subprocess.run(["xdg-open", self.file_path], check=True)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Не удалось открыть:\n{e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0, self._fit_to_window)


class _ImageCanvas(QtWidgets.QWidget):
    """Холст с zoom (колесо мыши) и pan (перетаскивание)."""

    def __init__(self, pixmap: QtGui.QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._scale = 1.0
        self._offset = QtCore.QPointF(0, 0)
        self._drag_start = None
        self._drag_offset_start = None
        self.request_fit = None
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.OpenHandCursor))

    def set_transform(self, scale: float, offset: QtCore.QPointF):
        self._scale = scale
        self._offset = offset
        self.update()

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        cx = self.width() / 2 + self._offset.x()
        cy = self.height() / 2 + self._offset.y()
        w = self._pixmap.width() * self._scale
        h = self._pixmap.height() * self._scale
        rect = QtCore.QRectF(cx - w / 2, cy - h / 2, w, h)
        painter.drawPixmap(rect, self._pixmap, QtCore.QRectF(self._pixmap.rect()))
        painter.end()

    def wheelEvent(self, event):
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self._scale = max(0.05, min(self._scale * factor, 20.0))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_start = event.position()
            self._drag_offset_start = QtCore.QPointF(self._offset)
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            delta = event.position() - self._drag_start
            self._offset = self._drag_offset_start + delta
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.OpenHandCursor))

    def mouseDoubleClickEvent(self, event):
        if self.request_fit:
            self.request_fit()



# ═══════════════════════════════════════════════════════════════════════════
# МИНИ-ПРОСМОТРЩИК ТЕКСТОВЫХ ФАЙЛОВ
# ═══════════════════════════════════════════════════════════════════════════

_TEXT_EXTENSIONS = {
    '.txt', '.md', '.py', '.js', '.ts', '.html', '.css', '.json', '.xml',
    '.csv', '.log', '.yaml', '.yml', '.ini', '.cfg', '.toml', '.sh',
    '.bat', '.c', '.cpp', '.h', '.java', '.rs', '.go', '.php', '.rb',
    '.swift', '.kt', '.sql', '.env', '.gitignore',
}

def is_text_file(file_path: str) -> bool:
    """Возвращает True если файл — текстовый (по расширению)."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in _TEXT_EXTENSIONS


class _TextViewerDialog(QtWidgets.QDialog):
    """Мини-окно для просмотра текстовых файлов."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle(os.path.basename(file_path))
        self.setModal(True)
        self.setMinimumSize(500, 400)
        self.resize(800, 600)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self._build_ui()
        self._load_content()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._text_edit = QtWidgets.QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont((QtGui.QFont("Cascadia Code", 12) if IS_WINDOWS else QtGui.QFont("Menlo", 12)))
        self._text_edit.setStyleSheet(
            "QPlainTextEdit { background:#0d0e1a; color:#c8d0e7; "
            "border:none; padding:12px; }"
        )
        layout.addWidget(self._text_edit, stretch=1)

        bar = QtWidgets.QWidget()
        bar.setStyleSheet("background:#1a1b2e;border-top:1px solid rgba(102,126,234,0.25);")
        bar.setFixedHeight(48)
        bl = QtWidgets.QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(10)

        path_lbl = QtWidgets.QLabel(self.file_path)
        path_lbl.setStyleSheet("color:rgba(180,185,220,0.7);font-size:11px;")
        bl.addWidget(path_lbl, stretch=1)

        btn_style = (
            "QPushButton{color:white;background:rgba(102,126,234,0.25);"
            "border:1px solid rgba(102,126,234,0.4);border-radius:8px;"
            "padding:5px 14px;font-size:13px;}"
            "QPushButton:hover{background:rgba(102,126,234,0.45);}"
            "QPushButton:pressed{background:rgba(102,126,234,0.6);}"
        )
        for label, slot in [("↗ В приложении", self._open_external),
                              ("✕ Закрыть", self.close)]:
            btn = QtWidgets.QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(slot)
            bl.addWidget(btn)

        layout.addWidget(bar)
        self.setStyleSheet("QDialog{background:#0d0e1a;}")

    def _load_content(self):
        try:
            for enc in ("utf-8", "cp1251", "latin-1"):
                try:
                    with open(self.file_path, "r", encoding=enc) as f:
                        text = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = "[Не удалось прочитать файл — неизвестная кодировка]"
            # Ограничиваем до 200 КБ для производительности
            if len(text) > 200_000:
                text = text[:200_000] + "\n\n[... файл обрезан до 200 КБ ...]"
            self._text_edit.setPlainText(text)
        except Exception as e:
            self._text_edit.setPlainText(f"[Ошибка чтения файла: {e}]")

    def _open_external(self):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", self.file_path], check=True)
            elif sys.platform == "win32":
                os.startfile(self.file_path)
            else:
                subprocess.run(["xdg-open", self.file_path], check=True)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Не удалось открыть:\n{e}")


class ThinkingBubbleWidget(QtWidgets.QWidget):
    """
    Простой пульсирующий кружок пока ИИ думает.
    Рисуется через paintEvent — никаких дочерних виджетов.
    """

    _R_MIN = 6
    _R_MAX = 11

    def __init__(self, model_name: str = "", theme: str = "light",
                 liquid_glass: bool = True, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(40)
        # Растягиваем на всю ширину, чтобы cx считался правильно
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

        # Серый цвет — нейтральный
        if theme == "dark":
            self._color = QtGui.QColor(190, 190, 195)
        else:
            self._color = QtGui.QColor(155, 155, 163)

        # Состояние пульса
        self._radius  = float(self._R_MIN)
        self._alpha   = 0.45
        self._r_dir   = 1

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        step = 0.18 * self._r_dir
        self._radius += step
        if self._radius >= self._R_MAX:
            self._radius = self._R_MAX
            self._r_dir  = -1
        elif self._radius <= self._R_MIN:
            self._radius = self._R_MIN
            self._r_dir  = 1
        t = (self._radius - self._R_MIN) / (self._R_MAX - self._R_MIN)
        self._alpha = 0.35 + 0.60 * t
        try:
            self.update()
        except RuntimeError:
            self._timer.stop()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        c = QtGui.QColor(self._color)
        c.setAlphaF(self._alpha)
        painter.setBrush(QtGui.QBrush(c))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        # cx = messages_layout margin (5) + MessageWidget AI left margin (6) + bubble_padding (18) + R_MAX
        # Это совпадает с центром кнопки копировать под пузырём ИИ
        cx = 5 + 6 + 18 + self._R_MAX
        cy = self.height() // 2
        r  = int(self._radius)
        painter.drawEllipse(QtCore.QPoint(cx, cy), r, r)
        painter.end()

    def fade_out_and_remove(self, on_done=None):
        self._timer.stop()
        self._opacity_eff = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_eff)
        self._opacity_eff.setOpacity(1.0)
        anim = QtCore.QPropertyAnimation(self._opacity_eff, b"opacity", self)
        anim.setDuration(150)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        if on_done:
            anim.finished.connect(on_done)
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim


class WorkerSignals(QtCore.QObject):
    # (response_text, list of (title, url) source tuples)
    finished = QtCore.pyqtSignal(str, list)
    chunk    = QtCore.pyqtSignal(str)   # очередной токен из стрима

class AIWorker(QtCore.QRunnable):
    def __init__(self, user_message: str, current_language: str, deep_thinking: bool, use_search: bool, should_forget: bool = False, chat_manager=None, chat_id=None, file_paths: list = None, ai_mode: str = AI_MODE_FAST, model_key_override: str = None):
        super().__init__()
        self.user_message = user_message
        self.current_language = current_language
        self.deep_thinking = deep_thinking
        self.use_search = use_search
        self.should_forget = should_forget
        self.chat_manager = chat_manager
        self.chat_id = chat_id
        self.file_paths = file_paths if file_paths else []
        self.ai_mode = ai_mode
        self._cancelled = False
        # Уникальный ID запроса — для защиты от "призраков" после стопа
        self.request_id = id(self)
        self.signals = WorkerSignals()
        # model_key_override — явная модель для перегенерации другой моделью
        # Если не передан — берём текущую активную модель из глобала
        self.model_key = model_key_override if model_key_override is not None else llama_handler.CURRENT_AI_MODEL_KEY

    @QtCore.pyqtSlot()
    def run(self):
        try:
            if llama_handler._APP_SHUTTING_DOWN or self._cancelled:
                return

            # ── Ожидание готовности Ollama (актуально для первого сообщения) ──
            # При старте программы Ollama запускается в фоне. Если пользователь
            # успел написать раньше — делаем до 5 попыток по 3 секунды (15 сек).
            for _attempt in range(5):
                try:
                    requests.get("http://localhost:11434/api/tags", timeout=2)
                    break  # Ollama отвечает — продолжаем
                except Exception:
                    if self._cancelled or llama_handler._APP_SHUTTING_DOWN:
                        return
                    if _attempt < 4:
                        print(f"[WORKER] ⏳ Ollama не готова, попытка {_attempt + 1}/5 — ждём 3с...")
                        time.sleep(3)
                    # На последней попытке просто идём дальше — get_ai_response
                    # сам вернёт ошибку если Ollama так и не поднялась

            def _on_chunk(token: str):
                if self._cancelled or llama_handler._APP_SHUTTING_DOWN:
                    return
                try:
                    self.signals.chunk.emit(token)
                except RuntimeError:
                    pass

            response, sources = get_ai_response(
                self.user_message,
                self.current_language,
                self.deep_thinking,
                self.use_search,
                self.should_forget,
                self.chat_manager,
                self.chat_id,
                self.file_paths,
                self.ai_mode,
                self.model_key,
                on_chunk=_on_chunk,
                cancelled_flag=lambda: self._cancelled or llama_handler._APP_SHUTTING_DOWN,
            )
            # Проверяем ещё раз после долгого ожидания ответа от Ollama
            if self._cancelled or llama_handler._APP_SHUTTING_DOWN:
                print(f"[WORKER] ⚠️ Запрос {self.request_id} отменён — ответ сброшен")
                return
            if hasattr(self, 'signals') and self.signals is not None:
                try:
                    self.signals.finished.emit(response, sources)
                except RuntimeError:
                    pass
        except Exception as e:
            if self._cancelled:
                return
            if hasattr(self, 'signals') and self.signals is not None:
                try:
                    self.signals.finished.emit(f"[Ошибка] {e}", [])
                except RuntimeError:
                    pass

# -------------------------
# Main Window
# -------------------------

# ═══════════════════════════════════════════════════════════════════════════
# ПОЛЕ ВВОДА С ПРОВЕРКОЙ ОРФОГРАФИИ
# Красные волнистые подчёркивания + контекстное меню с вариантами замены.
# Работает через pyspellchecker (pip install pyspellchecker).
# Если библиотека не установлена — поле работает как обычный QLineEdit.
# ═══════════════════════════════════════════════════════════════════════════

class SpellCheckLineEdit(QtWidgets.QLineEdit):
    """
    QLineEdit с живой проверкой орфографии:
    — красные волнистые подчёркивания под ошибочными словами
    — ПКМ → контекстное меню с вариантами исправления
    """

    _SQUIGGLE_COLOR = QtGui.QColor(210, 60, 60, 170)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._spell_ru = None
        self._spell_en = None
        self._spell_ok = False
        try:
            from spellchecker import SpellChecker
            self._spell_ru = SpellChecker(language='ru')
            self._spell_en = SpellChecker(language='en')
            self._spell_ok = True
            print("[SPELL_INPUT] ✓ pyspellchecker загружен")
        except ImportError:
            print("[SPELL_INPUT] ⚠️ pyspellchecker не установлен")
        except Exception as e:
            print(f"[SPELL_INPUT] ⚠️ Ошибка инициализации: {e}")

        # Хранит готовые пиксельные координаты для рисования:
        # [(x0_px, x1_px, suggestions), ...]
        # Считается в _run_spell_check (вне paintEvent) — там cursorRect надёжен.
        self._squiggles: list = []
        # Флаг защиты от рекурсии: setCursorPosition внутри _char_x
        # вызывает cursorPositionChanged → _on_cursor_moved → _char_x → ...
        self._computing_positions: bool = False

        # Для контекстного меню — символьные позиции
        self._misspelled: list = []

        self._spell_timer = QtCore.QTimer(self)
        self._spell_timer.setSingleShot(True)
        self._spell_timer.setInterval(500)
        self._spell_timer.timeout.connect(self._run_spell_check)

        self.textChanged.connect(self._on_text_changed)
        # Обновляем позиции когда курсор двигается (горизонтальный скролл меняется)
        self.cursorPositionChanged.connect(self._on_cursor_moved)

        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _on_text_changed(self, _text: str):
        self._squiggles  = []
        self._misspelled = []
        if self._spell_ok:
            self._spell_timer.start()

    def _on_cursor_moved(self, _old: int, _new: int):
        """Курсор двинулся → скролл мог измениться → пересчитываем пиксели.
        Защита: если сдвиг курсора вызван нами самими из _char_x — игнорируем."""
        if self._misspelled and not self._computing_positions:
            self._update_pixel_positions()

    @staticmethod
    def _is_russian(word: str) -> bool:
        return any('\u0400' <= c <= '\u04FF' for c in word)

    def _char_x(self, char_index: int) -> float:
        """
        Пиксельный X символа char_index в координатах виджета.
        Вызывается ТОЛЬКО вне paintEvent.

        Принцип: временно перемещаем курсор в char_index, читаем
        cursorRect().x(). Флаг _computing_positions блокирует рекурсию:
        setCursorPosition → cursorPositionChanged → _on_cursor_moved → _char_x.
        """
        self._computing_positions = True
        try:
            saved = self.cursorPosition()
            self.setCursorPosition(char_index)
            x = float(self.cursorRect().x())
            self.setCursorPosition(saved)
        finally:
            self._computing_positions = False
        return x

    def _update_pixel_positions(self):
        """Пересчитывает пиксельные X0/X1 для уже найденных ошибок."""
        fm      = self.fontMetrics()
        text    = self.text()
        result  = []
        for start, length, suggestions in self._misspelled:
            if start < 0 or start + length > len(text):
                continue
            x0 = self._char_x(start)
            x1 = x0 + fm.horizontalAdvance(text[start:start + length])
            result.append((x0, x1, suggestions))
        self._squiggles = result
        self.update()

    def _run_spell_check(self):
        if not self._spell_ok:
            return
        text = self.text()
        if not text.strip():
            self._misspelled = []
            self._squiggles  = []
            self.update()
            return

        # Запускаем тяжёлую часть (spell.candidates) в фоновом потоке,
        # чтобы не блокировать UI при большом количестве ошибок.
        import threading
        threading.Thread(target=self._spell_check_worker, args=(text,), daemon=True).start()

    def _spell_check_worker(self, text: str):
        """Фоновый поток: находит ошибки и суффесции, затем обновляет UI через QTimer."""
        # Лимит: не больше 15 слов — остальные просто не подчёркиваем.
        # candidates() может занимать ~30-50 мс на слово на больших словарях.
        _MAX_MISSPELLED = 15

        chars = []
        for m in re.finditer(r'[а-яёА-ЯЁa-zA-Z]{2,}', text):
            if len(chars) >= _MAX_MISSPELLED:
                break
            word     = m.group()
            start    = m.start()
            length   = len(word)
            word_low = word.lower()
            spell    = self._spell_ru if self._is_russian(word) else self._spell_en

            if word_low in spell:
                continue

            try:
                candidates  = spell.candidates(word_low) or set()
                suggestions = sorted(candidates)[:4]
            except Exception:
                suggestions = []

            chars.append((start, length, suggestions))

        # Возвращаемся в основной поток через singleShot(0)
        QtCore.QTimer.singleShot(0, lambda c=chars: self._apply_spell_results(c, text))

    def _apply_spell_results(self, chars: list, original_text: str):
        """Применяет результаты spell-check в основном потоке."""
        # Игнорируем результат если текст уже изменился
        if self.text() != original_text:
            return
        self._misspelled = chars
        fm = self.fontMetrics()
        squiggles = []
        for start, length, suggestions in chars:
            x0 = self._char_x(start)
            x1 = x0 + fm.horizontalAdvance(original_text[start:start + length])
            squiggles.append((x0, x1, suggestions))
        self._squiggles = squiggles
        self.update()

    def _run_spell_check_sync(self):
        """Заглушка — оставлена для совместимости, не используется."""
        pass

    # ── QStyle content rect ───────────────────────────────────────────────
    def _text_content_rect(self) -> QtCore.QRect:
        opt = QtWidgets.QStyleOptionFrame()
        self.initStyleOption(opt)
        return self.style().subElementRect(
            QtWidgets.QStyle.SubElement.SE_LineEditContents, opt, self
        )

    # ── Рисуем волнистые подчёркивания ───────────────────────────────────
    def paintEvent(self, event):
        try:
            super().paintEvent(event)
            if not self._squiggles:
                return

            painter = QtGui.QPainter(self)
            if not painter.isActive():
                return

            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

            fm           = self.fontMetrics()
            content_rect = self._text_content_rect()
            # Baseline: центр текста + ascent + зазор под буквами
            text_top   = content_rect.top() + (content_rect.height() - fm.height()) // 2
            baseline_y = float(text_top + fm.ascent() + 5)

            pen = QtGui.QPen(self._SQUIGGLE_COLOR, 1.4)
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)

            clip_left  = float(content_rect.x())
            clip_right = float(self.width() - 4)

            for x0, x1, _ in self._squiggles:
                # Клиппинг по видимой области
                rx0 = max(x0, clip_left)
                rx1 = min(x1, clip_right)
                if rx1 <= rx0:
                    continue

                step = 4.0
                amp  = 1.8
                path = QtGui.QPainterPath()
                path.moveTo(rx0, baseline_y)

                x = rx0
                while x < rx1:
                    mid = min(x + step / 2, rx1)
                    nx  = min(x + step,     rx1)
                    path.quadTo(mid, baseline_y + amp, nx, baseline_y)
                    x = nx

                painter.drawPath(path)

            painter.end()

        except KeyboardInterrupt:
            try: painter.end()
            except Exception: pass
        except Exception as _e:
            print(f"[SpellCheckLineEdit.paintEvent] ⚠️ {_e}")
            try: painter.end()
            except Exception: pass

    # ── Контекстное меню ─────────────────────────────────────────────────
    def _show_context_menu(self, pos: QtCore.QPoint):
        menu = self.createStandardContextMenu()

        cursor_pos = self._pos_to_char_index(pos)
        hit_entry  = None
        for start, length, suggestions in self._misspelled:
            if start <= cursor_pos < start + length:
                hit_entry = (start, length, suggestions)
                break

        if hit_entry:
            start, length, suggestions = hit_entry
            wrong_word = self.text()[start:start + length]

            menu.insertSeparator(menu.actions()[0])

            if suggestions:
                for sug in reversed(suggestions):
                    act = QtGui.QAction(f"  ✏️  {sug}", self)
                    act.setFont(QtGui.QFont(
                        self.font().family(),
                        self.font().pointSize(),
                        QtGui.QFont.Weight.Bold
                    ))
                    act.triggered.connect(
                        lambda checked=False, s=sug, st=start, ln=length:
                        self._apply_correction(st, ln, s)
                    )
                    menu.insertAction(menu.actions()[0], act)

                header = QtGui.QAction(f'Исправить "{wrong_word}":', self)
                header.setEnabled(False)
                hf = QtGui.QFont(self.font().family(), self.font().pointSize() - 1)
                hf.setItalic(True)
                header.setFont(hf)
                menu.insertAction(menu.actions()[0], header)
            else:
                no_sug = QtGui.QAction(f'❓ Нет вариантов для "{wrong_word}"', self)
                no_sug.setEnabled(False)
                menu.insertAction(menu.actions()[0], no_sug)

        menu.exec(self.mapToGlobal(pos))

    def _pos_to_char_index(self, pos: QtCore.QPoint) -> int:
        """Преобразует координату клика мышью в индекс символа."""
        fm     = self.fontMetrics()
        text   = self.text()
        # X начала текста — из кеша или вычислить
        if self._squiggles or not text:
            x0_text = self._char_x(0) if text else float(self._text_content_rect().x())
        else:
            x0_text = float(self._text_content_rect().x())

        x          = pos.x() - x0_text
        cumulative = 0.0
        for i, ch in enumerate(text):
            char_w = fm.horizontalAdvance(ch)
            if cumulative + char_w / 2 >= x:
                return i
            cumulative += char_w
        return len(text)

    def _apply_correction(self, start: int, length: int, replacement: str):
        text     = self.text()
        original = text[start:start + length]
        if original and original[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        self.setText(text[:start] + replacement + text[start + length:])
        self.setCursorPosition(start + len(replacement))
        self._spell_timer.start()



# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# ВЕКТОРНЫЕ ИКОНКИ ДЛЯ КНОПОК (Windows не рендерит эмодзи в кнопках)
# Рисуем стрелки/квадрат через QPainter — красиво на всех платформах
# ═══════════════════════════════════════════════════════════════════════════

def _make_arrow_right_icon(size: int, color: QtGui.QColor) -> QtGui.QIcon:
    """Стрелка вправо → для кнопки отправить."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(color, size * 0.13, QtCore.Qt.PenStyle.SolidLine,
                     QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    cx, cy = size / 2, size / 2
    tip_x = size * 0.72
    tail_x = size * 0.28
    arm = size * 0.22
    # Хвост
    p.drawLine(QtCore.QPointF(tail_x, cy), QtCore.QPointF(tip_x, cy))
    # Верхнее перо
    p.drawLine(QtCore.QPointF(tip_x, cy), QtCore.QPointF(tip_x - arm, cy - arm))
    # Нижнее перо
    p.drawLine(QtCore.QPointF(tip_x, cy), QtCore.QPointF(tip_x - arm, cy + arm))
    p.end()
    return QtGui.QIcon(pm)


def _make_stop_icon(size: int, color: QtGui.QColor) -> QtGui.QIcon:
    """Квадрат ■ для кнопки остановить генерацию."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QBrush(color))
    margin = size * 0.28
    r = int(size * 0.10)
    rect = QtCore.QRectF(margin, margin, size - margin * 2, size - margin * 2)
    p.drawRoundedRect(rect, r, r)
    p.end()
    return QtGui.QIcon(pm)


def _make_arrow_down_icon(size: int, color: QtGui.QColor) -> QtGui.QIcon:
    """Стрелка вниз ↓ для кнопки скролла вниз."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(color, size * 0.13, QtCore.Qt.PenStyle.SolidLine,
                     QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    cx = size / 2
    tip_y = size * 0.72
    tail_y = size * 0.28
    arm = size * 0.22
    p.drawLine(QtCore.QPointF(cx, tail_y), QtCore.QPointF(cx, tip_y))
    p.drawLine(QtCore.QPointF(cx, tip_y), QtCore.QPointF(cx - arm, tip_y - arm))
    p.drawLine(QtCore.QPointF(cx, tip_y), QtCore.QPointF(cx + arm, tip_y - arm))
    p.end()
    return QtGui.QIcon(pm)


def _set_send_icon(btn: QtWidgets.QPushButton, color_hex: str = "#3a3a3a"):
    """Устанавливает иконку стрелки вправо на кнопку отправки (Windows-safe)."""
    if IS_WINDOWS:
        icon = _make_arrow_right_icon(36, QtGui.QColor(color_hex))
        btn.setIcon(icon)
        btn.setIconSize(QtCore.QSize(28, 28))
        btn.setText("")
    else:
        btn.setIcon(QtGui.QIcon())
        btn.setText("→")


def _set_stop_icon(btn: QtWidgets.QPushButton, color_hex: str = "#3a3a3a"):
    """Устанавливает иконку стоп на кнопку отправки (Windows-safe)."""
    if IS_WINDOWS:
        icon = _make_stop_icon(36, QtGui.QColor(color_hex))
        btn.setIcon(icon)
        btn.setIconSize(QtCore.QSize(26, 26))
        btn.setText("")
    else:
        btn.setIcon(QtGui.QIcon())
        btn.setText("⏸")


def _set_scroll_down_icon(btn: QtWidgets.QPushButton, color_hex: str = "#3a3a3a"):
    """Устанавливает иконку стрелки вниз на кнопку скролла (Windows-safe)."""
    if IS_WINDOWS:
        icon = _make_arrow_down_icon(36, QtGui.QColor(color_hex))
        btn.setIcon(icon)
        btn.setIconSize(QtCore.QSize(28, 28))
        btn.setText("")
    else:
        btn.setIcon(QtGui.QIcon())
        btn.setText("⬇")


# БАЗОВЫЙ КЛАСС: NoFocusButton
# Кнопка без focus ring — переопределяет paintEvent чтобы убрать системный
# focus rect, который не убирается через QSS на всех платформах
# ═══════════════════════════════════════════════════════════════════════════

class NoFocusButton(QtWidgets.QPushButton):
    """QPushButton без системного focus ring на всех платформах."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    
    def paintEvent(self, event):
        try:
            opt = QtWidgets.QStyleOptionButton()
            self.initStyleOption(opt)
            opt.state &= ~QtWidgets.QStyle.StateFlag.State_HasFocus
            painter = QtGui.QPainter(self)
            if not painter.isActive():
                return
            self.style().drawControl(QtWidgets.QStyle.ControlElement.CE_PushButton, opt, painter, self)
            painter.end()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# НОВЫЙ КОМПОНЕНТ 1: SCROLL TO BOTTOM BUTTON
# Floating overlay кнопка "⬇ вниз" - НЕ участвует в layout
# ═══════════════════════════════════════════════════════════════════════════

class ChatListDelegate(QtWidgets.QStyledItemDelegate):
    """
    Делегат для двухстрочного отображения чатов:
      Строка 1: название чата (жирный, основной цвет)
      Строка 2: превью последнего сообщения (мелкий, серый)
    Разделитель между пунктами — тонкая линия снизу каждого элемента.
    """

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme

    def set_theme(self, theme: str):
        self._theme = theme

    def paint(self, painter, option, index):
        painter.save()

        is_selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        is_hovered  = bool(option.state & QtWidgets.QStyle.StateFlag.State_MouseOver)
        is_dark     = self._theme == "dark"

        rect = option.rect

        # ── Фон ──────────────────────────────────────────────────────
        if is_selected:
            bg = QtGui.QColor(139, 92, 246, 70) if is_dark else QtGui.QColor(102, 126, 234, 45)
            border = QtGui.QColor(124, 77, 236) if is_dark else QtGui.QColor(82, 106, 214)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            r = QtCore.QRectF(rect).adjusted(2, 1, -2, -1)
            painter.drawRoundedRect(r, 10, 10)
            # Акцентная полоска слева
            painter.setBrush(border)
            painter.drawRoundedRect(QtCore.QRectF(rect.left() + 2, rect.top() + 6,
                                                   3, rect.height() - 12), 2, 2)
        elif is_hovered:
            bg = QtGui.QColor(255, 255, 255, 30) if is_dark else QtGui.QColor(0, 0, 0, 12)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            r = QtCore.QRectF(rect).adjusted(2, 1, -2, -1)
            painter.drawRoundedRect(r, 10, 10)

        # ── Текст ─────────────────────────────────────────────────────
        full_text = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        lines = full_text.split("\n", 1)
        title   = lines[0]
        preview = lines[1] if len(lines) > 1 else ""

        title_color   = QtGui.QColor("#f0f0f0" if is_dark else "#1a1a1a")
        preview_color = QtGui.QColor("#888888" if is_dark else "#888888")
        if is_selected:
            title_color   = QtGui.QColor("#ffffff" if is_dark else "#1a1a1a")
            preview_color = QtGui.QColor("#cccccc" if is_dark else "#555555")

        left_pad = 18 if is_selected else 14
        text_x = rect.left() + left_pad
        text_w = rect.width() - left_pad - 10

        if preview:
            # Две строки
            title_font = QtGui.QFont(painter.font())
            title_font.setPointSize(13)
            title_font.setWeight(QtGui.QFont.Weight.DemiBold)
            painter.setFont(title_font)
            painter.setPen(title_color)
            title_rect = QtCore.QRect(text_x, rect.top() + 9, text_w, 20)
            painter.drawText(title_rect, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                             title)

            prev_font = QtGui.QFont(painter.font())
            prev_font.setPointSize(11)
            prev_font.setWeight(QtGui.QFont.Weight.Normal)
            painter.setFont(prev_font)
            painter.setPen(preview_color)
            prev_rect = QtCore.QRect(text_x, rect.top() + 31, text_w, 18)
            fm = QtGui.QFontMetrics(prev_font)
            elided = fm.elidedText(preview, QtCore.Qt.TextElideMode.ElideRight, text_w)
            painter.drawText(prev_rect, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                             elided)
        else:
            # Одна строка
            title_font = QtGui.QFont(painter.font())
            title_font.setPointSize(13)
            title_font.setWeight(QtGui.QFont.Weight.DemiBold if is_selected else QtGui.QFont.Weight.Medium)
            painter.setFont(title_font)
            painter.setPen(title_color)
            title_rect = QtCore.QRect(text_x, rect.top(), text_w, rect.height())
            painter.drawText(title_rect, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                             title)

        # ── Разделитель снизу (очень тонкий, только когда не выделен) ──
        if not is_selected:
            sep_color = QtGui.QColor(80, 80, 85, 40) if is_dark else QtGui.QColor(0, 0, 0, 18)
            painter.setPen(QtGui.QPen(sep_color, 0.5))
            sep_y = rect.bottom()
            painter.drawLine(rect.left() + 14, sep_y, rect.right() - 14, sep_y)

        painter.restore()

    def sizeHint(self, option, index):
        full_text = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        has_preview = "\n" in full_text
        return QtCore.QSize(option.rect.width(), 58 if has_preview else 42)


class ScrollToBottomButton(QtWidgets.QPushButton):
    """
    Floating overlay кнопка "⬇ вниз" для скроллинга к низу.
    
    КРИТИЧЕСКИЕ ПРАВИЛА:
    - НЕ участвует в layout сообщений
    - НЕ вызывает автоскролл
    - Только индикатор наличия непрочитанных сообщений внизу
    - Позиция: overlay поверх scroll_area
    """
    
    def __init__(self, parent=None):
        super().__init__("" if IS_WINDOWS else "⬇", parent)
        
        self.setObjectName("scrollToBottomBtn")
        self.setFixedSize(50, 50)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        # Изначально скрыта
        self.hide()
        
        # Применяем стиль по умолчанию (светлая тема + glass)
        # На этом этапе добавится тень через graphicsEffect
        self.apply_theme_styles(theme="light", liquid_glass=True)
        _set_scroll_down_icon(self)  # Windows-safe иконка
        
        # ═══════════════════════════════════════════════════════════════
        # ПЛАВНОЕ ПОЯВЛЕНИЕ/ИСЧЕЗНОВЕНИЕ через opacity
        # ═══════════════════════════════════════════════════════════════
        # ВАЖНО: Создаём ПОСЛЕ apply_theme_styles, но используем CSS drop-shadow вместо graphicsEffect
        # так как graphicsEffect можно установить только один
        
        # Создаём эффект прозрачности (заменит тень)
        self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)  # Изначально невидима
        
        # Анимация fade in/out
        self.fade_animation = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(400)  # 400ms - более плавная и приятная анимация
        self.fade_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutExpo)  # Более естественная кривая
        
        # Флаг текущего состояния видимости (для предотвращения лишних анимаций)
        self._is_visible_animated = False
    
    def apply_theme_styles(self, theme: str = "light", liquid_glass: bool = True):
        """
        Применить стили в зависимости от темы и liquid glass.
        
        Вызывается при изменении настроек темы.
        """
        if theme == "dark":
            if liquid_glass:
                # ТЁМНАЯ ТЕМА + СТЕКЛО - тёмное полупрозрачное стекло
                bg_start = "rgba(35, 35, 40, 0.75)"
                bg_end = "rgba(28, 28, 32, 0.75)"
                border = "rgba(50, 50, 55, 0.6)"
                hover_bg_start = "rgba(45, 45, 50, 0.85)"
                hover_bg_end = "rgba(38, 38, 42, 0.85)"
                hover_border = "rgba(139, 92, 246, 0.5)"
                text_color = "#e6e6e6"
                shadow_color = "rgba(0, 0, 0, 0.7)"
            else:
                # ТЁМНАЯ ТЕМА БЕЗ СТЕКЛА - матовый тёмный
                bg_start = "rgb(43, 43, 48)"
                bg_end = "rgb(38, 38, 42)"
                border = "rgba(60, 60, 65, 0.95)"
                hover_bg_start = "rgb(53, 53, 58)"
                hover_bg_end = "rgb(48, 48, 52)"
                hover_border = "rgba(139, 92, 246, 0.7)"
                text_color = "#f0f0f0"
                shadow_color = "rgba(0, 0, 0, 0.5)"
        else:
            if liquid_glass:
                # СВЕТЛАЯ ТЕМА + СТЕКЛО - светлое полупрозрачное стекло
                bg_start = "rgba(255, 255, 255, 0.75)"
                bg_end = "rgba(255, 255, 255, 0.65)"
                border = "rgba(255, 255, 255, 0.85)"
                hover_bg_start = "rgba(255, 255, 255, 0.90)"
                hover_bg_end = "rgba(255, 255, 255, 0.80)"
                hover_border = "rgba(102, 126, 234, 0.65)"
                text_color = "#2d3748"
                shadow_color = "rgba(0, 0, 0, 0.15)"
            else:
                # СВЕТЛАЯ ТЕМА БЕЗ СТЕКЛА - матовый светлый
                bg_start = "rgb(242, 242, 245)"
                bg_end = "rgb(235, 235, 240)"
                border = "rgba(210, 210, 215, 0.95)"
                hover_bg_start = "rgb(235, 235, 240)"
                hover_bg_end = "rgb(225, 225, 230)"
                hover_border = "rgba(102, 126, 234, 0.8)"
                text_color = "#1a1a1a"
                shadow_color = "rgba(0, 0, 0, 0.2)"
        
        self.setStyleSheet(f"""
            #scrollToBottomBtn {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {bg_start},
                    stop:1 {bg_end});
                border: 1px solid {border};
                border-radius: 25px;
                color: {text_color};
                font-size: 20px;
                font-weight: bold;
            }}
            #scrollToBottomBtn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {hover_bg_start},
                    stop:1 {hover_bg_end});
                border: 1px solid {hover_border};
            }}
        """)
        # Тень НЕ добавляем, так как используем opacity_effect для анимации
    
    def update_position(self, parent_width, parent_height):
        """
        Обновить позицию кнопки (центр снизу).
        НЕ вызывается автоматически - только вручную при resize.
        """
        x = (parent_width - self.width()) // 2
        y = parent_height - self.height() - 90  # 90px от низа (не налезает на input bar)
        self.move(x, y)
        self.raise_()
    
    def smooth_show(self):
        """
        Плавное появление кнопки через fade in анимацию.
        
        ОПТИМИЗАЦИЯ: Проверяем текущее состояние чтобы не запускать
        лишние анимации если кнопка уже видна.
        """
        # Если кнопка уже показана - ничего не делаем
        if self._is_visible_animated:
            return
        
        # Показываем виджет (но он невидим из-за opacity=0)
        if not self.isVisible():
            self.show()
        
        # Запускаем fade in анимацию
        self.fade_animation.stop()
        self.fade_animation.setStartValue(self.opacity_effect.opacity())
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.start()
        
        self._is_visible_animated = True
    
    def smooth_hide(self):
        """
        Плавное исчезновение кнопки через fade out анимацию.
        
        ОПТИМИЗАЦИЯ: Проверяем текущее состояние чтобы не запускать
        лишние анимации если кнопка уже скрыта.
        """
        # Если кнопка уже скрыта - ничего не делаем
        if not self._is_visible_animated:
            return
        
        # Запускаем fade out анимацию
        self.fade_animation.stop()
        self.fade_animation.setStartValue(self.opacity_effect.opacity())
        self.fade_animation.setEndValue(0.0)
        
        # После завершения анимации скрываем виджет
        def on_fade_out_finished():
            if self.opacity_effect.opacity() == 0.0:
                self.hide()
        
        # Отключаем старый обработчик если был
        try:
            self.fade_animation.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        
        self.fade_animation.finished.connect(on_fade_out_finished)
        self.fade_animation.start()
        
        self._is_visible_animated = False


# ═══════════════════════════════════════════════════════════════════════════
# НОВЫЙ КОМПОНЕНТ 2: SETTINGS VIEW
# Экран настроек - замена chat_area
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# iOS-STYLE TOGGLE SWITCH
# ═══════════════════════════════════════════════════════════════
class ToggleSwitch(QtWidgets.QAbstractButton):
    """Анимированный iOS-переключатель."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        # ВАЖНО: _thumb должен быть инициализирован ДО setCheckable/setChecked
        # т.к. Qt может вызвать paintEvent или property getter сразу
        self._thumb = 0.0
        self.setCheckable(True)
        self.setFixedSize(56, 30)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

        self._anim = QtCore.QPropertyAnimation(self, b"_thumb_pos", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

        self.toggled.connect(self._start_anim)

        # Устанавливаем состояние ПОСЛЕ создания анимации
        if checked:
            self._thumb = 1.0
            self.setChecked(True)

    # ── свойство для анимации ────────────────────────────────────
    def _get_thumb(self):
        return self._thumb

    def _set_thumb(self, v):
        self._thumb = v
        self.update()

    _thumb_pos = QtCore.pyqtProperty(float, _get_thumb, _set_thumb)

    def _start_anim(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._thumb)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    # ── рисуем ──────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2
        # Интерполируем цвет трека между серым и синим
        t = self._thumb
        r_c = int(200 + (33  - 200) * t)
        g_c = int(200 + (150 - 200) * t)
        b_c = int(204 + (243 - 204) * t)
        track_color = QtGui.QColor(r_c, g_c, b_c)
        p.setBrush(QtGui.QBrush(track_color))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, r, r)
        # Ползунок
        margin = 3
        thumb_diam = h - margin * 2
        travel = w - thumb_diam - margin * 2
        thumb_x = margin + self._thumb * travel
        p.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
        p.drawEllipse(QtCore.QRectF(thumb_x, margin, thumb_diam, thumb_diam))
        p.end()

    def sizeHint(self):
        return QtCore.QSize(56, 30)

class SettingsView(QtWidgets.QWidget):
    """
    Экран настроек приложения.
    
    КРИТИЧЕСКИЕ ПРАВИЛА:
    - НЕ влияет на messages_layout
    - НЕ создаёт новое окно
    - Заменяет содержимое chat_container через QStackedWidget
    - Sidebar и input bar остаются видимыми
    """
    
    # Сигналы
    settings_applied = QtCore.pyqtSignal(dict)
    close_requested = QtCore.pyqtSignal()
    delete_all_chats_requested = QtCore.pyqtSignal()  # Новый сигнал для удаления всех чатов
    delete_all_models_requested = QtCore.pyqtSignal()  # Сигнал удаления всех моделей ИИ
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("settingsView")
        
        # Текущие настройки (сохранённые и применённые)
        self.current_settings = {
            "theme": "light",
            "liquid_glass": True,
            "auto_scroll": False,
            "show_tts": True,
            "show_regen": True,
            "show_copy": True,
            "show_user_copy": True,
            "show_user_edit": True,
        }
        
        # Временные настройки (pending - до нажатия "Применить")
        self.pending_settings = {
            "theme": "light",
            "liquid_glass": True,
            "auto_scroll": False,
            "show_tts": True,
            "show_regen": True,
            "show_copy": True,
            "show_user_copy": True,
            "show_user_edit": True,
        }
        
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        """Инициализация UI"""
        
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── QStackedWidget: страница 0 = главное меню, страница 1 = Интерфейс ──
        self.pages_stack = QtWidgets.QStackedWidget()
        main_layout.addWidget(self.pages_stack)

        # ════════════════════════════════════════════════════════
        # СТРАНИЦА 0: Главное меню настроек
        # ════════════════════════════════════════════════════════
        main_page = QtWidgets.QWidget()
        main_page_layout = QtWidgets.QVBoxLayout(main_page)
        main_page_layout.setContentsMargins(40, 30, 40, 30)
        main_page_layout.setSpacing(20)

        # Заголовок
        title = QtWidgets.QLabel("⚙️ Настройки")
        title.setObjectName("settingsTitle")
        title.setFont(_apple_font(28, weight=QtGui.QFont.Weight.Bold))
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        main_page_layout.addWidget(title)

        # Контейнер настроек (скроллируемый)
        settings_container = QtWidgets.QWidget()
        settings_container.setObjectName("settingsContainer")
        settings_layout = QtWidgets.QVBoxLayout(settings_container)
        settings_layout.setSpacing(16)

        # ═══════════════════════════════════════════════
        # ПУНКТ: Интерфейс (переход на подстраницу)
        # ═══════════════════════════════════════════════
        interface_btn = QtWidgets.QPushButton("🖥  Интерфейс")
        interface_btn.setObjectName("settingsNavBtn")
        interface_btn.setFont(_apple_font(16, weight=QtGui.QFont.Weight.Medium))
        interface_btn.setMinimumHeight(56)
        interface_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        interface_btn.setLayoutDirection(QtCore.Qt.LayoutDirection.LeftToRight)
        interface_btn.clicked.connect(lambda: self._slide_pages(0, 1))
        settings_layout.addWidget(interface_btn)

        # ═══════════════════════════════════════════════
        # НАСТРОЙКА: Автоскролл
        # ═══════════════════════════════════════════════
        scroll_group = self.create_setting_group(
            "Автоскролл",
            "Автоматически прокручивать вниз при новых сообщениях"
        )

        scroll_row = QtWidgets.QHBoxLayout()
        scroll_row.setSpacing(14)
        scroll_row.setContentsMargins(0, 4, 0, 4)

        scroll_label = QtWidgets.QLabel("Включить автоскролл")
        scroll_label.setObjectName("scrollToggleLabel")
        scroll_label.setFont(_apple_font(14))

        self.auto_scroll_toggle = ToggleSwitch(
            checked=self.current_settings.get("auto_scroll", True)
        )
        self.auto_scroll_toggle.toggled.connect(self._on_auto_scroll_toggled)

        scroll_row.addWidget(self.auto_scroll_toggle)
        scroll_row.addWidget(scroll_label)
        scroll_row.addStretch()
        scroll_group.layout().addLayout(scroll_row)
        settings_layout.addWidget(scroll_group)

        # ═══════════════════════════════════════════════
        # УЛУЧШЕННЫЙ ПОДТЕКСТ
        # ═══════════════════════════════════════════════
        if SubtextSettingBlock is not None:
            self.subtext_block = SubtextSettingBlock()
            settings_layout.addWidget(self.subtext_block)

        # ═══════════════════════════════════════════════
        # ОПАСНАЯ ЗОНА: Удаление всех чатов
        # ═══════════════════════════════════════════════
        danger_group = self.create_setting_group(
            "⚠️ Опасная зона",
            "Необратимые действия. Будьте осторожны!"
        )

        delete_all_layout = QtWidgets.QVBoxLayout()
        delete_all_layout.setSpacing(10)

        self.delete_all_chats_btn = QtWidgets.QPushButton("🗑️ Удалить все чаты")
        self.delete_all_chats_btn.setObjectName("deleteAllChatsBtn")
        self.delete_all_chats_btn.setFont(_apple_font(13, weight=QtGui.QFont.Weight.Medium))
        self.delete_all_chats_btn.setMinimumHeight(45)
        self.delete_all_chats_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.delete_all_chats_btn.clicked.connect(self.request_delete_all_chats)

        delete_all_layout.addWidget(self.delete_all_chats_btn)

        self.delete_all_models_btn = QtWidgets.QPushButton("🤖 Удалить все модели ИИ")
        self.delete_all_models_btn.setObjectName("deleteAllModelsBtn")
        self.delete_all_models_btn.setFont(_apple_font(13, weight=QtGui.QFont.Weight.Medium))
        self.delete_all_models_btn.setMinimumHeight(45)
        self.delete_all_models_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.delete_all_models_btn.setStyleSheet(
            "QPushButton#deleteAllModelsBtn {"
            "  background: rgba(254, 226, 226, 0.85);"
            "  border: 2px solid rgba(252, 165, 165, 0.7);"
            "  border-radius: 14px;"
            "  color: #dc2626;"
            "  font-weight: 600;"
            "}"
            "QPushButton#deleteAllModelsBtn:hover {"
            "  background: rgba(254, 202, 202, 1.0);"
            "}"
        )
        self.delete_all_models_btn.clicked.connect(self.request_delete_all_models)
        delete_all_layout.addWidget(self.delete_all_models_btn)

        danger_group.layout().addLayout(delete_all_layout)
        settings_layout.addWidget(danger_group)

        settings_layout.addStretch()

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidget(settings_container)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll_area.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.main_scroll_area = scroll_area   # для сброса позиции при открытии
        main_page_layout.addWidget(scroll_area, stretch=1)

        # Кнопка «Назад к чату» на главной странице настроек
        back_btn = QtWidgets.QPushButton("← Назад к чату")
        back_btn.setObjectName("settingsBackBtn")
        back_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Medium))
        back_btn.setMinimumHeight(50)
        back_btn.setContentsMargins(40, 0, 40, 0)
        back_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        back_btn.clicked.connect(self.close_requested.emit)
        main_page_layout.addWidget(back_btn)

        # Версия — правый нижний угол
        _ver_lbl = QtWidgets.QLabel("v3.0.1")
        _ver_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignBottom)
        _ver_lbl.setFont(_apple_font(11))
        _ver_lbl.setStyleSheet("color: #94a3b8;")
        main_page_layout.addWidget(_ver_lbl)

        self.pages_stack.addWidget(main_page)  # index 0

        # СТРАНИЦА 1: Интерфейс (навигация к подменю)
        # ════════════════════════════════════════════════════════
        iface_page = QtWidgets.QWidget()
        iface_layout = QtWidgets.QVBoxLayout(iface_page)
        iface_layout.setContentsMargins(40, 30, 40, 30)
        iface_layout.setSpacing(20)

        iface_title = QtWidgets.QLabel("🖥  Интерфейс")
        iface_title.setObjectName("settingsTitle")
        iface_title.setFont(_apple_font(28, weight=QtGui.QFont.Weight.Bold))
        iface_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        iface_layout.addWidget(iface_title)

        iface_nav_container = QtWidgets.QWidget()
        iface_nav_container.setObjectName("settingsContainer")
        iface_nav_layout = QtWidgets.QVBoxLayout(iface_nav_container)
        iface_nav_layout.setSpacing(12)

        themes_nav_btn = QtWidgets.QPushButton("🎨  Темы")
        themes_nav_btn.setObjectName("settingsNavBtn")
        themes_nav_btn.setFont(_apple_font(16, weight=QtGui.QFont.Weight.Medium))
        themes_nav_btn.setMinimumHeight(56)
        themes_nav_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        themes_nav_btn.clicked.connect(lambda: self._slide_pages(1, 2))
        iface_nav_layout.addWidget(themes_nav_btn)

        glass_nav_btn = QtWidgets.QPushButton("🪟  Liquid Glass")
        glass_nav_btn.setObjectName("settingsNavBtn")
        glass_nav_btn.setFont(_apple_font(16, weight=QtGui.QFont.Weight.Medium))
        glass_nav_btn.setMinimumHeight(56)
        glass_nav_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        glass_nav_btn.clicked.connect(lambda: self._slide_pages(1, 3))
        iface_nav_layout.addWidget(glass_nav_btn)

        elements_nav_btn = QtWidgets.QPushButton("🧩  Элементы")
        elements_nav_btn.setObjectName("settingsNavBtn")
        elements_nav_btn.setFont(_apple_font(16, weight=QtGui.QFont.Weight.Medium))
        elements_nav_btn.setMinimumHeight(56)
        elements_nav_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        elements_nav_btn.clicked.connect(lambda: self._slide_pages(1, 4))
        iface_nav_layout.addWidget(elements_nav_btn)

        iface_nav_layout.addStretch()

        iface_nav_scroll = QtWidgets.QScrollArea()
        iface_nav_scroll.setObjectName("settingsScrollArea")
        iface_nav_scroll.setWidget(iface_nav_container)
        iface_nav_scroll.setWidgetResizable(True)
        iface_nav_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        iface_nav_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        iface_layout.addWidget(iface_nav_scroll, stretch=1)

        iface_back_btn = QtWidgets.QPushButton("← Назад к настройкам")
        iface_back_btn.setObjectName("settingsBackBtn")
        iface_back_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Medium))
        iface_back_btn.setMinimumHeight(50)
        iface_back_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        iface_back_btn.clicked.connect(lambda: self._slide_pages(1, 0))
        iface_layout.addWidget(iface_back_btn)

        self.pages_stack.addWidget(iface_page)  # index 1

        # ════════════════════════════════════════════════════════
        # СТРАНИЦА 2: Темы
        # ════════════════════════════════════════════════════════
        themes_page = QtWidgets.QWidget()
        themes_layout = QtWidgets.QVBoxLayout(themes_page)
        themes_layout.setContentsMargins(40, 30, 40, 30)
        themes_layout.setSpacing(20)

        themes_title = QtWidgets.QLabel("🎨  Темы")
        themes_title.setObjectName("settingsTitle")
        themes_title.setFont(_apple_font(28, weight=QtGui.QFont.Weight.Bold))
        themes_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        themes_layout.addWidget(themes_title)

        themes_container = QtWidgets.QWidget()
        themes_container.setObjectName("settingsContainer")
        themes_settings_layout = QtWidgets.QVBoxLayout(themes_container)
        themes_settings_layout.setSpacing(16)

        theme_group = self.create_setting_group(
            "Тема оформления",
            "Переключение между светлой и тёмной темой"
        )
        theme_layout = QtWidgets.QHBoxLayout()
        theme_layout.setSpacing(15)
        self.theme_light_btn = QtWidgets.QPushButton("☀️ Светлая")
        self.theme_light_btn.setObjectName("themeLightBtn")
        self.theme_light_btn.setCheckable(True)
        self.theme_light_btn.setChecked(True)
        self.theme_light_btn.clicked.connect(lambda: self.set_theme("light"))
        self.theme_dark_btn = QtWidgets.QPushButton("🌙 Тёмная")
        self.theme_dark_btn.setObjectName("themeDarkBtn")
        self.theme_dark_btn.setCheckable(True)
        self.theme_dark_btn.clicked.connect(lambda: self.set_theme("dark"))
        theme_layout.addWidget(self.theme_light_btn)
        theme_layout.addWidget(self.theme_dark_btn)
        theme_group.layout().addLayout(theme_layout)
        themes_settings_layout.addWidget(theme_group)

        themes_settings_layout.addStretch()

        themes_scroll = QtWidgets.QScrollArea()
        themes_scroll.setObjectName("settingsScrollArea")
        themes_scroll.setWidget(themes_container)
        themes_scroll.setWidgetResizable(True)
        themes_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        themes_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        themes_layout.addWidget(themes_scroll, stretch=1)

        themes_back_btn = QtWidgets.QPushButton("← Назад к интерфейсу")
        themes_back_btn.setObjectName("settingsBackBtn")
        themes_back_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Medium))
        themes_back_btn.setMinimumHeight(50)
        themes_back_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        themes_back_btn.clicked.connect(lambda: self._slide_pages(2, 1))
        themes_layout.addWidget(themes_back_btn)

        self.pages_stack.addWidget(themes_page)  # index 2

        # ════════════════════════════════════════════════════════
        # СТРАНИЦА 3: Liquid Glass
        # ════════════════════════════════════════════════════════
        glass_page = QtWidgets.QWidget()
        glass_layout_outer = QtWidgets.QVBoxLayout(glass_page)
        glass_layout_outer.setContentsMargins(40, 30, 40, 30)
        glass_layout_outer.setSpacing(20)

        glass_page_title = QtWidgets.QLabel("🪟  Liquid Glass")
        glass_page_title.setObjectName("settingsTitle")
        glass_page_title.setFont(_apple_font(28, weight=QtGui.QFont.Weight.Bold))
        glass_page_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        glass_layout_outer.addWidget(glass_page_title)

        glass_container = QtWidgets.QWidget()
        glass_container.setObjectName("settingsContainer")
        glass_settings_layout = QtWidgets.QVBoxLayout(glass_container)
        glass_settings_layout.setSpacing(16)

        glass_group = self.create_setting_group(
            "Liquid Glass",
            "Стеклянный эффект для элементов интерфейса"
        )
        preview_layout = QtWidgets.QHBoxLayout()
        preview_layout.setSpacing(20)
        preview_layout.setContentsMargins(0, 8, 0, 8)
        try:
            if os.path.exists("app_settings.json"):
                with open("app_settings.json", "r", encoding="utf-8") as _f:
                    _s = json.load(_f)
                    _theme = _s.get("theme", "light")
            else:
                _theme = "light"
        except Exception:
            _theme = "light"
        self.preview_glass_bubble = self._make_preview_bubble(liquid_glass=True, theme=_theme, label="Со стеклом")
        self.preview_matte_bubble = self._make_preview_bubble(liquid_glass=False, theme=_theme, label="Без стекла")
        preview_layout.addWidget(self.preview_glass_bubble)
        preview_layout.addWidget(self.preview_matte_bubble)
        glass_group.layout().addLayout(preview_layout)
        glass_btn_layout = QtWidgets.QHBoxLayout()
        glass_btn_layout.setSpacing(15)
        self.glass_on_btn = QtWidgets.QPushButton("🪟 Включено")
        self.glass_on_btn.setObjectName("glassOnBtn")
        self.glass_on_btn.setCheckable(True)
        self.glass_on_btn.setChecked(True)
        self.glass_on_btn.clicked.connect(lambda: self.set_liquid_glass(True))
        self.glass_off_btn = QtWidgets.QPushButton("🔲 Выключено")
        self.glass_off_btn.setObjectName("glassOffBtn")
        self.glass_off_btn.setCheckable(True)
        self.glass_off_btn.clicked.connect(lambda: self.set_liquid_glass(False))
        glass_btn_layout.addWidget(self.glass_on_btn)
        glass_btn_layout.addWidget(self.glass_off_btn)
        glass_group.layout().addLayout(glass_btn_layout)
        glass_settings_layout.addWidget(glass_group)
        glass_settings_layout.addStretch()

        glass_scroll = QtWidgets.QScrollArea()
        glass_scroll.setObjectName("settingsScrollArea")
        glass_scroll.setWidget(glass_container)
        glass_scroll.setWidgetResizable(True)
        glass_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        glass_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        glass_layout_outer.addWidget(glass_scroll, stretch=1)

        glass_back_btn = QtWidgets.QPushButton("← Назад к интерфейсу")
        glass_back_btn.setObjectName("settingsBackBtn")
        glass_back_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Medium))
        glass_back_btn.setMinimumHeight(50)
        glass_back_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        glass_back_btn.clicked.connect(lambda: self._slide_pages(3, 1))
        glass_layout_outer.addWidget(glass_back_btn)

        self.pages_stack.addWidget(glass_page)  # index 3

        # ════════════════════════════════════════════════════════
        # СТРАНИЦА 4: Элементы интерфейса
        # ════════════════════════════════════════════════════════
        elements_page = QtWidgets.QWidget()
        elements_layout = QtWidgets.QVBoxLayout(elements_page)
        elements_layout.setContentsMargins(40, 30, 40, 30)
        elements_layout.setSpacing(20)

        elements_title = QtWidgets.QLabel("🧩  Элементы")
        elements_title.setObjectName("settingsTitle")
        elements_title.setFont(_apple_font(28, weight=QtGui.QFont.Weight.Bold))
        elements_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        elements_layout.addWidget(elements_title)

        elements_container = QtWidgets.QWidget()
        elements_container.setObjectName("settingsContainer")
        elements_settings_layout = QtWidgets.QVBoxLayout(elements_container)
        elements_settings_layout.setSpacing(16)

        elements_group = self.create_setting_group(
            "Элементы управления",
            "Отключённые элементы скрываются во всех сообщениях"
        )

        def _make_element_row(label_text, setting_key, default=True):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(14)
            row.setContentsMargins(0, 4, 0, 4)
            toggle = ToggleSwitch(checked=self.current_settings.get(setting_key, default))
            lbl = QtWidgets.QLabel(label_text)
            lbl.setFont(_apple_font(14))
            def _on_toggle(checked, key=setting_key):
                self.current_settings[key] = checked
                self.save_settings()
                self.settings_applied.emit(self.current_settings)
            toggle.toggled.connect(_on_toggle)
            row.addWidget(toggle)
            row.addWidget(lbl)
            row.addStretch()
            return row

        elements_group.layout().addLayout(_make_element_row("🔊  Озвучка (ИИ)",        "show_tts",       True))
        elements_group.layout().addLayout(_make_element_row("🔄  Перегенерация (ИИ)",  "show_regen",     True))
        elements_group.layout().addLayout(_make_element_row("📋  Копировать (ИИ)",     "show_copy",      True))
        elements_group.layout().addLayout(_make_element_row("📋  Копировать (Вы)",     "show_user_copy", True))
        elements_group.layout().addLayout(_make_element_row("✏️  Редактировать (Вы)",  "show_user_edit", True))

        elements_settings_layout.addWidget(elements_group)
        elements_settings_layout.addStretch()

        elements_scroll = QtWidgets.QScrollArea()
        elements_scroll.setObjectName("settingsScrollArea")
        elements_scroll.setWidget(elements_container)
        elements_scroll.setWidgetResizable(True)
        elements_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        elements_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        elements_layout.addWidget(elements_scroll, stretch=1)

        elements_back_btn = QtWidgets.QPushButton("← Назад к интерфейсу")
        elements_back_btn.setObjectName("settingsBackBtn")
        elements_back_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Medium))
        elements_back_btn.setMinimumHeight(50)
        elements_back_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        elements_back_btn.clicked.connect(lambda: self._slide_pages(4, 1))
        elements_layout.addWidget(elements_back_btn)

        self.pages_stack.addWidget(elements_page)  # index 4

        self.apply_settings_styles()
    
    def create_setting_group(self, title: str, description: str) -> QtWidgets.QGroupBox:
        """Создать группу настроек"""
        
        group = QtWidgets.QGroupBox()
        group.setObjectName("settingGroup")
        
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(12)
        
        title_label = QtWidgets.QLabel(title)
        title_label.setFont(_apple_font(18, weight=QtGui.QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        desc_label = QtWidgets.QLabel(description)
        desc_label.setObjectName("descLabel")
        desc_label.setFont(_apple_font(13))
        desc_label.setStyleSheet("color: #475569;")
        layout.addWidget(desc_label)
        
        return group
    
    def _make_preview_bubble(self, liquid_glass: bool, theme: str, label: str) -> QtWidgets.QWidget:
        """
        Создаёт превью-пузырь. Оба пузыря одинаковой структуры для симметрии.
        Оба имеют обёртку-фон: у стеклянного — контрастный, у матового — прозрачный.
        objectNames совпадают с apply_settings_styles.
        """
        prefix = "Glass" if liquid_glass else "Matte"

        # Внешний контейнер (подпись + обёртка + пузырь) — одинаковая структура для обоих
        outer = QtWidgets.QWidget()
        outer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred
        )
        outer_layout = QtWidgets.QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(6)

        # Подпись
        lbl = QtWidgets.QLabel(label)
        lbl.setObjectName("previewColLabel")
        lbl.setFont(_apple_font(11))
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        outer_layout.addWidget(lbl)

        # Обёртка — одинаковая у обоих (симметрия). У стеклянного — с фоном (через CSS),
        # у матового — прозрачная. Padding одинаковый.
        wrapper = QtWidgets.QWidget()
        wrapper.setObjectName(f"preview{prefix}Bg")
        wrapper_layout = QtWidgets.QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(10, 10, 10, 10)

        # Пузырь — objectName совпадает с apply_settings_styles
        bubble = QtWidgets.QWidget()
        bubble.setObjectName(f"preview{prefix}Bubble")
        bubble.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred
        )
        bubble_layout = QtWidgets.QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(20, 16, 20, 16)
        bubble_layout.setSpacing(4)

        # Имя спикера
        name_lbl = QtWidgets.QLabel("LLaMA 3:")
        name_lbl.setObjectName(f"preview{prefix}Name")
        name_lbl.setFont(_apple_font(13, weight=QtGui.QFont.Weight.Bold))
        bubble_layout.addWidget(name_lbl)

        # Текст
        msg_text = "Привет! Это стеклянный стиль." if liquid_glass else "Привет! Это матовый стиль."
        msg_lbl = QtWidgets.QLabel(msg_text)
        msg_lbl.setObjectName(f"preview{prefix}Text")
        msg_lbl.setFont(_apple_font(13))
        msg_lbl.setWordWrap(True)
        bubble_layout.addWidget(msg_lbl)

        wrapper_layout.addWidget(bubble)
        outer_layout.addWidget(wrapper)
        return outer

    # ── Плавный слайд-переход между страницами pages_stack ───────────────────
    def _slide_pages(self, from_index: int, to_index: int):
        """
        Slide + fade переход между страницами pages_stack.
        from_index=0→to_index=1  : слайд влево  (вход в подраздел)
        from_index=1→to_index=0  : слайд вправо (возврат назад)
        """
        if getattr(self, '_pages_animating', False):
            return
        self._pages_animating = True

        stack = self.pages_stack
        w = stack.width()
        direction = 1 if to_index > from_index else -1
        dur = 300

        new_page = stack.widget(to_index)
        old_page = stack.widget(from_index)

        new_page.setGeometry(direction * w, 0, w, stack.height())
        stack.setCurrentIndex(to_index)
        new_page.show()
        new_page.raise_()

        # ── Fade-out старой страницы ─────────────────────────────────────────
        eff_out = QtWidgets.QGraphicsOpacityEffect(old_page)
        old_page.setGraphicsEffect(eff_out)
        a_out_op = QtCore.QPropertyAnimation(eff_out, b"opacity")
        a_out_op.setDuration(dur // 2)
        a_out_op.setStartValue(1.0)
        a_out_op.setEndValue(0.0)
        a_out_op.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)

        # ── Fade-in новой страницы ───────────────────────────────────────────
        eff_in = QtWidgets.QGraphicsOpacityEffect(new_page)
        new_page.setGraphicsEffect(eff_in)
        eff_in.setOpacity(0.0)
        a_in_op = QtCore.QPropertyAnimation(eff_in, b"opacity")
        a_in_op.setDuration(dur)
        a_in_op.setStartValue(0.0)
        a_in_op.setEndValue(1.0)
        a_in_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        # ── Slide старой страницы ────────────────────────────────────────────
        a_old = QtCore.QPropertyAnimation(old_page, b"pos")
        a_old.setDuration(dur)
        a_old.setStartValue(QtCore.QPoint(0, 0))
        a_old.setEndValue(QtCore.QPoint(-direction * w // 3, 0))  # уходит на 1/3 — параллакс
        a_old.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        # ── Slide новой страницы ─────────────────────────────────────────────
        a_new = QtCore.QPropertyAnimation(new_page, b"pos")
        a_new.setDuration(dur)
        a_new.setStartValue(QtCore.QPoint(direction * w, 0))
        a_new.setEndValue(QtCore.QPoint(0, 0))
        a_new.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        grp = QtCore.QParallelAnimationGroup(self)
        grp.addAnimation(a_out_op)
        grp.addAnimation(a_in_op)
        grp.addAnimation(a_old)
        grp.addAnimation(a_new)

        def _on_done():
            old_page.move(0, 0)
            new_page.move(0, 0)
            try:
                old_page.setGraphicsEffect(None)
                new_page.setGraphicsEffect(None)
            except RuntimeError:
                pass
            self._pages_animating = False
            self._pages_anim_group = None

        grp.finished.connect(_on_done)
        self._pages_anim_group = grp
        grp.start()

    # ── Дебаунс для темы и стекла ─────────────────────────────────────────────
    def set_theme(self, theme: str):
        """Мгновенно применить тему при нажатии кнопки."""
        self.pending_settings["theme"] = theme
        self.current_settings["theme"] = theme

        self.theme_light_btn.setChecked(theme == "light")
        self.theme_dark_btn.setChecked(theme == "dark")

        self.save_settings()
        self.settings_applied.emit(self.current_settings)
        self.apply_settings_styles()
        print(f"[SETTINGS] Тема: {theme}")

    def set_liquid_glass(self, enabled: bool):
        """Мгновенно применить настройку стекла при нажатии кнопки."""
        self.pending_settings["liquid_glass"] = enabled
        self.current_settings["liquid_glass"] = enabled

        self.glass_on_btn.setChecked(enabled)
        self.glass_off_btn.setChecked(not enabled)

        self.save_settings()
        self.settings_applied.emit(self.current_settings)
        self.apply_settings_styles()
        print(f"[SETTINGS] Стекло: {'вкл' if enabled else 'выкл'}")
    
    def scroll_to_top(self):
        """Сбрасывает прокрутку в самый верх — вызывается каждый раз при открытии настроек."""
        if hasattr(self, 'main_scroll_area'):
            self.main_scroll_area.verticalScrollBar().setValue(0)

    def load_settings(self):
        """Загрузить сохранённые настройки"""
        try:
            if os.path.exists("app_settings.json"):
                with open("app_settings.json", "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.current_settings.update(saved)
                    # Копируем в pending settings
                    self.pending_settings.update(saved)
        except Exception as e:
            print(f"[SETTINGS] Ошибка загрузки: {e}")
        
        # Устанавливаем визуальное состояние кнопок согласно current settings
        theme = self.current_settings.get("theme", "light")
        liquid_glass = self.current_settings.get("liquid_glass", True)
        self.theme_light_btn.setChecked(theme == "light")
        self.theme_dark_btn.setChecked(theme == "dark")
        self.glass_on_btn.setChecked(liquid_glass)
        self.glass_off_btn.setChecked(not liquid_glass)
        # Синхронизируем toggle автоскролла
        auto_scroll = self.current_settings.get("auto_scroll", True)
        if hasattr(self, 'auto_scroll_toggle'):
            self.auto_scroll_toggle.setChecked(auto_scroll)
        
        # Применяем стили к самому окну настроек
        self.apply_settings_styles()
    
    def save_settings(self):
        """Сохранить настройки"""
        try:
            with open("app_settings.json", "w", encoding="utf-8") as f:
                json.dump(self.current_settings, f, indent=2)
            print("[SETTINGS] ✓ Настройки сохранены")
        except Exception as e:
            print(f"[SETTINGS] ✗ Ошибка сохранения: {e}")
    
    def _on_auto_scroll_toggled(self, checked: bool):
        """Мгновенно применяет автоскролл — без кнопки 'Применить'."""
        self.pending_settings["auto_scroll"] = checked
        self.current_settings["auto_scroll"] = checked
        # Сохраняем немедленно
        self.save_settings()
        # Уведомляем главное окно прямо сейчас
        self.settings_applied.emit(self.current_settings)

    def request_delete_all_chats(self):
        """Запросить подтверждение удаления всех чатов"""
        print("[SETTINGS] Запрос на удаление всех чатов")
        self.delete_all_chats_requested.emit()

    def request_delete_all_models(self):
        """Запросить подтверждение удаления всех моделей ИИ"""
        print("[SETTINGS] Запрос на удаление всех моделей ИИ")
        self.delete_all_models_requested.emit()
    
    def update_delete_all_btn_state(self, has_chats_with_messages: bool):
        """
        Обновить состояние кнопки 'Удалить все чаты'.
        Отключает кнопку если нет ни одного чата с сообщениями.
        """
        if hasattr(self, 'delete_all_chats_btn'):
            self.delete_all_chats_btn.setEnabled(has_chats_with_messages)
            if has_chats_with_messages:
                self.delete_all_chats_btn.setCursor(
                    QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
                self.delete_all_chats_btn.setToolTip("")
            else:
                self.delete_all_chats_btn.setCursor(
                    QtGui.QCursor(QtCore.Qt.CursorShape.ForbiddenCursor))
                self.delete_all_chats_btn.setToolTip("Нет чатов для удаления")
    
    def apply_settings(self):
        """
        Применить настройки к приложению.
        
        ВАЖНО: Это единственное место где pending_settings копируется в current_settings
        и отправляется сигнал settings_applied.
        """
        # Копируем pending settings в current settings
        self.current_settings.update(self.pending_settings)
        
        # Сохраняем в файл
        self.save_settings()
        
        # Отправляем сигнал главному окну для применения стилей
        self.settings_applied.emit(self.current_settings)
        
        print(f"[SETTINGS] ✓ Настройки применены: {self.current_settings}")
        # НЕ закрываем настройки автоматически - пользователь сам решает когда вернуться
    
    def apply_settings_styles(self):
        """Применить стили с поддержкой тем"""
        
        # Определяем текущую тему из настроек
        theme = self.current_settings.get("theme", "light")
        liquid_glass = self.current_settings.get("liquid_glass", True)
        
        print(f"[SETTINGS_VIEW] apply_settings_styles: theme={theme}, liquid_glass={liquid_glass}")
        
        if theme == "dark":
            if liquid_glass:
                # ТЁМНАЯ ТЕМА + СТЕКЛО - тёмное стекло
                colors = {
                    "bg": "rgba(24, 24, 28, 0.65)",
                    "title": "#e6e6e6",
                    "group_bg": "rgba(30, 30, 35, 0.60)",
                    "group_border": "rgba(50, 50, 55, 0.5)",
                    "text": "#e6e6e6",
                    "desc": "#b0b0b0",
                    "btn_bg": "rgba(45, 45, 50, 0.50)",
                    "btn_border": "rgba(60, 60, 65, 0.40)",
                    "btn_text": "#b0b0b0",
                    "btn_checked_bg_start": "rgba(139, 92, 246, 0.70)",
                    "btn_checked_bg_end": "rgba(124, 58, 237, 0.70)",
                    "btn_checked_border": "rgba(139, 92, 246, 0.80)",
                    "btn_hover_bg": "rgba(55, 55, 60, 0.70)",
                    "btn_hover_border": "rgba(139, 92, 246, 0.40)",
                    "back_btn_bg": "rgba(30, 30, 35, 0.60)",
                    "back_btn_border": "rgba(50, 50, 55, 0.60)",
                    "back_btn_text": "#b0b0b0",
                    "apply_btn_start": "rgba(34, 197, 94, 0.70)",
                    "apply_btn_end": "rgba(22, 163, 74, 0.80)",
                    "apply_btn_border": "rgba(34, 197, 94, 0.80)",
                    
                    # Кнопка удаления всех чатов
                    "delete_all_btn_bg": "rgba(220, 85, 85, 0.15)",
                    "delete_all_btn_hover": "rgba(220, 85, 85, 0.25)",
                    "delete_all_btn_text": "#e89999",
                    "delete_all_btn_border": "rgba(220, 85, 85, 0.3)",
                    "delete_all_btn_disabled_bg": "rgba(60, 60, 65, 0.4)",
                    "delete_all_btn_disabled_border": "rgba(80, 80, 85, 0.4)",
                    "delete_all_btn_disabled_text": "rgba(120, 120, 125, 0.7)",
                    "preview_glass_container": "rgba(60, 75, 115, 0.72)",
                    "preview_glass_bg": "rgba(60, 60, 80, 0.80)",
                    "preview_glass_border": "rgba(120, 120, 180, 0.85)",
                    "preview_glass_text": "#e8e8ff",
                    "preview_matte_bg": "rgb(43, 43, 48)",
                    "preview_matte_border": "rgba(60, 60, 65, 0.95)",
                    "preview_matte_text": "#e0e0e0",
                    "preview_accent": "#9b7fe8",
                }
            else:
                # ТЁМНАЯ ТЕМА БЕЗ СТЕКЛА - матовый тёмный
                colors = {
                    "bg": "rgb(28, 28, 31)",
                    "title": "#f0f0f0",
                    "group_bg": "rgb(32, 32, 36)",
                    "group_border": "rgba(55, 55, 60, 0.9)",
                    "text": "#f0f0f0",
                    "desc": "#c0c0c0",
                    "btn_bg": "rgb(48, 48, 52)",
                    "btn_border": "rgb(68, 68, 72)",
                    "btn_text": "#c0c0c0",
                    "btn_checked_bg_start": "rgba(139, 92, 246, 1.0)",
                    "btn_checked_bg_end": "rgba(124, 58, 237, 1.0)",
                    "btn_checked_border": "rgba(139, 92, 246, 1.0)",
                    "btn_hover_bg": "rgb(58, 58, 62)",
                    "btn_hover_border": "rgba(139, 92, 246, 0.6)",
                    "back_btn_bg": "rgb(32, 32, 36)",
                    "back_btn_border": "rgba(55, 55, 60, 0.95)",
                    "back_btn_text": "#c0c0c0",
                    "apply_btn_start": "rgba(34, 197, 94, 1.0)",
                    "apply_btn_end": "rgba(22, 163, 74, 1.0)",
                    "apply_btn_border": "rgba(34, 197, 94, 1.0)",
                    
                    # Кнопка удаления всех чатов
                    "delete_all_btn_bg": "rgba(220, 85, 85, 0.15)",
                    "delete_all_btn_hover": "rgba(220, 85, 85, 0.25)",
                    "delete_all_btn_text": "#e89999",
                    "delete_all_btn_border": "rgba(220, 85, 85, 0.3)",
                    "delete_all_btn_disabled_bg": "rgba(60, 60, 65, 0.4)",
                    "delete_all_btn_disabled_border": "rgba(80, 80, 85, 0.4)",
                    "delete_all_btn_disabled_text": "rgba(120, 120, 125, 0.7)",
                    "preview_glass_container": "rgba(60, 75, 115, 0.72)",
                    "preview_glass_bg": "rgba(60, 60, 80, 0.80)",
                    "preview_glass_border": "rgba(120, 120, 180, 0.85)",
                    "preview_glass_text": "#e8e8ff",
                    "preview_matte_bg": "rgb(43, 43, 48)",
                    "preview_matte_border": "rgba(60, 60, 65, 0.95)",
                    "preview_matte_text": "#e0e0e0",
                    "preview_accent": "#9b7fe8",
                }
        else:
            # СВЕТЛАЯ ТЕМА
            if liquid_glass:
                # СВЕТЛАЯ ТЕМА + СТЕКЛО
                colors = {
                    "bg": "rgba(255, 255, 255, 0.55)",
                    "title": "#222222",
                    "group_bg": "rgba(255, 255, 255, 0.75)",
                    "group_border": "rgba(255, 255, 255, 0.85)",
                    "text": "#222222",
                    "desc": "#5a5a5a",
                    "btn_bg": "rgba(255, 255, 255, 0.82)",
                    "btn_border": "rgb(200, 210, 222)",
                    "btn_text": "#3a3a3a",
                    "btn_checked_bg_start": "rgba(102, 126, 234, 0.80)",
                    "btn_checked_bg_end": "rgba(118, 75, 162, 0.80)",
                    "btn_checked_border": "rgba(102, 126, 234, 0.90)",
                    "btn_hover_bg": "rgba(255, 255, 255, 0.85)",
                    "btn_hover_border": "rgba(102, 126, 234, 0.50)",
                    "back_btn_bg": "rgba(255, 255, 255, 0.75)",
                    "back_btn_border": "rgba(203, 213, 225, 0.75)",
                    "back_btn_text": "#3a3a3a",
                    "apply_btn_start": "rgba(34, 197, 94, 0.80)",
                    "apply_btn_end": "rgba(22, 163, 74, 0.90)",
                    "apply_btn_border": "rgba(34, 197, 94, 0.90)",
                    
                    # Кнопка удаления всех чатов
                    "delete_all_btn_bg": "rgba(220, 85, 85, 0.08)",
                    "delete_all_btn_hover": "rgba(220, 85, 85, 0.15)",
                    "delete_all_btn_text": "#c85555",
                    "delete_all_btn_border": "rgba(220, 85, 85, 0.2)",
                    "delete_all_btn_disabled_bg": "rgba(220, 220, 225, 0.5)",
                    "delete_all_btn_disabled_border": "rgba(200, 200, 205, 0.5)",
                    "delete_all_btn_disabled_text": "rgba(160, 160, 165, 0.8)",
                    "preview_glass_container": "rgba(110, 140, 185, 0.72)",
                    "preview_glass_bg": "rgba(200, 210, 240, 0.75)",
                    "preview_glass_border": "rgba(150, 170, 220, 0.90)",
                    "preview_glass_text": "#1a1a3a",
                    "preview_matte_bg": "rgb(242, 242, 245)",
                    "preview_matte_border": "rgba(200, 200, 205, 0.95)",
                    "preview_matte_text": "#1a1a1a",
                    "preview_accent": "#667eea",
                }
            else:
                # СВЕТЛАЯ ТЕМА БЕЗ СТЕКЛА - плоский
                colors = {
                    "bg": "rgb(246, 246, 248)",
                    "title": "#1a1a1a",
                    "group_bg": "rgb(252, 252, 254)",
                    "group_border": "rgba(210, 210, 215, 0.95)",
                    "text": "#1a1a1a",
                    "desc": "#4a4a4a",
                    "btn_bg": "rgb(242, 242, 245)",
                    "btn_border": "rgb(210, 210, 215)",
                    "btn_text": "#2a2a2a",
                    "btn_checked_bg_start": "rgba(102, 126, 234, 1.0)",
                    "btn_checked_bg_end": "rgba(118, 75, 162, 1.0)",
                    "btn_checked_border": "rgba(102, 126, 234, 1.0)",
                    "btn_hover_bg": "rgb(235, 235, 240)",
                    "btn_hover_border": "rgba(102, 126, 234, 0.7)",
                    "back_btn_bg": "rgb(246, 246, 248)",
                    "back_btn_border": "rgba(210, 210, 215, 0.95)",
                    "back_btn_text": "#2a2a2a",
                    "apply_btn_start": "rgba(34, 197, 94, 1.0)",
                    "apply_btn_end": "rgba(22, 163, 74, 1.0)",
                    "apply_btn_border": "rgba(34, 197, 94, 1.0)",
                    
                    # Кнопка удаления всех чатов
                    "delete_all_btn_bg": "rgba(220, 85, 85, 0.08)",
                    "delete_all_btn_hover": "rgba(220, 85, 85, 0.15)",
                    "delete_all_btn_text": "#c85555",
                    "delete_all_btn_border": "rgba(220, 85, 85, 0.2)",
                    "delete_all_btn_disabled_bg": "rgba(220, 220, 225, 0.5)",
                    "delete_all_btn_disabled_border": "rgba(200, 200, 205, 0.5)",
                    "delete_all_btn_disabled_text": "rgba(160, 160, 165, 0.8)",
                    "preview_glass_container": "rgba(110, 140, 185, 0.72)",
                    "preview_glass_bg": "rgba(200, 210, 240, 0.75)",
                    "preview_glass_border": "rgba(150, 170, 220, 0.90)",
                    "preview_glass_text": "#1a1a3a",
                    "preview_matte_bg": "rgb(242, 242, 245)",
                    "preview_matte_border": "rgba(200, 200, 205, 0.95)",
                    "preview_matte_text": "#1a1a1a",
                    "preview_accent": "#667eea",
                }
        
        style = f"""
            #settingsView {{
                background: {colors["bg"]};
            }}
            
            #settingsTitle {{
                color: {colors["title"]};
                font-size: 32px;
            }}
            
            #settingGroup {{
                background: {colors["group_bg"]};
                border: 1px solid {colors["group_border"]};
                border-radius: 18px;
                padding: 24px;
            }}
            
            #settingGroup QLabel {{
                color: {colors["text"]};
            }}
            
            #settingGroup QLabel[objectName="descLabel"] {{
                color: {colors["desc"]};
            }}
            
            #themeLightBtn, #themeDarkBtn,
            #glassOnBtn, #glassOffBtn {{
                background: {colors["btn_bg"]};
                border: 2px solid {colors["btn_border"]};
                border-radius: 12px;
                padding: 16px 22px;
                font-size: 15px;
                font-weight: 600;
                color: {colors["btn_text"]};
                min-height: 50px;
            }}
            
            #themeLightBtn:checked, #themeDarkBtn:checked,
            #glassOnBtn:checked, #glassOffBtn:checked {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors["btn_checked_bg_start"]},
                    stop:1 {colors["btn_checked_bg_end"]});
                border: 2px solid {colors["btn_checked_border"]};
                color: white;
            }}
            
            #themeLightBtn:hover, #themeDarkBtn:hover,
            #glassOnBtn:hover, #glassOffBtn:hover {{
                background: {colors["btn_hover_bg"]};
                border: 2px solid {colors["btn_hover_border"]};
            }}
            
            #themeLightBtn:checked:hover, #themeDarkBtn:checked:hover,
            #glassOnBtn:checked:hover, #glassOffBtn:checked:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors["btn_checked_bg_start"]},
                    stop:1 {colors["btn_checked_bg_end"]});
                border: 2px solid {colors["btn_checked_border"]};
                color: white;
            }}
            
            #settingsBackBtn {{
                background: {colors["back_btn_bg"]};
                border: 2px solid {colors["back_btn_border"]};
                border-radius: 14px;
                color: {colors["back_btn_text"]};
            }}
            
            #settingsBackBtn:hover {{
                background: {colors["btn_hover_bg"]};
                border: 2px solid {colors["btn_hover_border"]};
            }}
            
            #settingsApplyBtn {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors["apply_btn_start"]},
                    stop:1 {colors["apply_btn_end"]});
                border: 2px solid {colors["apply_btn_border"]};
                border-radius: 14px;
                color: white;
            }}
            
            #settingsApplyBtn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(34, 197, 94, 0.95),
                    stop:1 rgba(22, 163, 74, 1.0));
            }}

            #settingsNavBtn {{
                background: {colors["group_bg"]};
                border: 2px solid {colors["group_border"]};
                border-radius: 14px;
                color: {colors["text"]};
                text-align: left;
                padding-left: 18px;
                font-weight: 600;
            }}

            #settingsNavBtn:hover {{
                background: {colors["btn_hover_bg"]};
                border: 2px solid {colors["btn_hover_border"]};
            }}
            
            #deleteAllChatsBtn {{
                background: {colors["delete_all_btn_bg"]};
                border: 2px solid {colors["delete_all_btn_border"]};
                border-radius: 14px;
                color: {colors["delete_all_btn_text"]};
                font-weight: 600;
            }}
            
            #deleteAllChatsBtn:hover {{
                background: {colors["delete_all_btn_hover"]};
            }}
            
            #deleteAllChatsBtn:disabled {{
                background: {colors["delete_all_btn_disabled_bg"]};
                border: 2px solid {colors["delete_all_btn_disabled_border"]};
                color: {colors["delete_all_btn_disabled_text"]};
                font-weight: 400;
            }}
            
            #previewGlassBg {{
                background: {colors["preview_glass_container"]};
                border-radius: 16px;
            }}
            #previewGlassBubble {{
                background: {colors["preview_glass_bg"]};
                border: 1.5px solid {colors["preview_glass_border"]};
                border-radius: 24px;
            }}
            #previewGlassName {{ color: {colors["preview_accent"]}; background: transparent; }}
            #previewGlassText {{ color: {colors["preview_glass_text"]}; background: transparent; }}
            
            #previewMatteBg {{
                background: transparent;
                border-radius: 16px;
            }}
            #previewMatteBubble {{
                background: {colors["preview_matte_bg"]};
                border: 1.5px solid {colors["preview_matte_border"]};
                border-radius: 24px;
            }}
            #previewMatteName {{ color: {colors["preview_accent"]}; background: transparent; }}
            #previewMatteText {{ color: {colors["preview_matte_text"]}; background: transparent; }}
            
            #previewColLabel {{ color: {colors["desc"]}; background: transparent; }}
        """
        
        self.setStyleSheet(style)
        print(f"[SETTINGS_VIEW] ✓ Стили применены")







# ══════════════════════════════════════════════════════════════════════════════
# ГОЛОСОВОЙ ВВОД
# ══════════════════════════════════════════════════════════════════════════════

class WhisperDownloadDialog(QtWidgets.QDialog):
    """
    Диалог скачивания модели Whisper base.
    Показывает прогресс, сохраняет в ~/.cache/whisper (постоянный кэш).
    После скачивания модель остаётся между перезапусками программы.
    """
    download_finished = QtCore.pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Скачивание Whisper")
        self.setFixedSize(420, 220)
        self.setWindowFlags(QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.FramelessWindowHint)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        title = QtWidgets.QLabel("🎤  Загрузка Whisper base")
        title.setFont(_apple_font(16, weight=QtGui.QFont.Weight.Bold))
        layout.addWidget(title)

        self._status_lbl = QtWidgets.QLabel("Подготовка…")
        self._status_lbl.setFont(_apple_font(12))
        self._status_lbl.setWordWrap(True)
        layout.addWidget(self._status_lbl)

        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 0)   # бесконечный пока не известен размер
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet("""
            QProgressBar { background: rgba(102,126,234,0.15); border-radius: 4px; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #667eea,stop:1 #764ba2); border-radius: 4px; }
        """)
        layout.addWidget(self._progress)

        self._info_lbl = QtWidgets.QLabel("Модель сохраняется в ~/.cache/whisper и остаётся между перезапусками программы")
        self._info_lbl.setFont(_apple_font(11))
        self._info_lbl.setStyleSheet("color: #7888aa;")
        self._info_lbl.setWordWrap(True)
        layout.addWidget(self._info_lbl)

        self._cancel_btn = QtWidgets.QPushButton("Отмена")
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel_btn)

        self._cancelled = False
        self._thread = None
        QtCore.QTimer.singleShot(100, self._start_download)

    def _start_download(self):
        import threading
        self._thread = threading.Thread(target=self._do_download, daemon=True)
        self._thread.start()

    def _do_download(self):
        try:
            QtCore.QMetaObject.invokeMethod(self, "_set_status",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, "Скачиваю модель Whisper base (~150 MB)…"))
            import whisper
            import os
            # Whisper сам скачивает в ~/.cache/whisper при load_model
            # Это постоянный кэш — не удаляется при закрытии программы
            model = whisper.load_model("base")
            if self._cancelled:
                return
            QtCore.QMetaObject.invokeMethod(self, "_on_done",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bool, True),
                QtCore.Q_ARG(str, "✅ Whisper base успешно скачан"))
        except ImportError:
            QtCore.QMetaObject.invokeMethod(self, "_on_done",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bool, False),
                QtCore.Q_ARG(str, "Whisper не установлен. Выполните: pip install openai-whisper"))
        except Exception as e:
            QtCore.QMetaObject.invokeMethod(self, "_on_done",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bool, False),
                QtCore.Q_ARG(str, f"Ошибка: {e}"))

    @QtCore.pyqtSlot(str)
    def _set_status(self, text: str):
        self._status_lbl.setText(text)

    @QtCore.pyqtSlot(bool, str)
    def _on_done(self, success: bool, msg: str):
        self._progress.setRange(0, 1)
        self._progress.setValue(1 if success else 0)
        self._status_lbl.setText(msg)
        self._cancel_btn.setText("Закрыть")
        self.download_finished.emit(success, msg)
        if success:
            QtCore.QTimer.singleShot(2000, self.accept)

    def _on_cancel(self):
        self._cancelled = True
        self.reject()


class VoiceRecorder(QtCore.QObject):
    """
    Умная запись голоса + транскрипция.
    - Автоопределение языка (Whisper локально или Google multi-lang)
    - Детектирование музыки / шума — не транскрибирует не-речь
    - VAD: обрезает тишину в начале и конце
    - Авто-стоп после 2 сек тишины
    - level_updated(float 0..1) для плавной анимации
    - status_updated(str) для статусной строки
    """
    recording_started  = QtCore.pyqtSignal()
    recording_stopped  = QtCore.pyqtSignal()
    transcription_done = QtCore.pyqtSignal(str)
    error_occurred     = QtCore.pyqtSignal(str)
    level_updated      = QtCore.pyqtSignal(float)
    status_updated     = QtCore.pyqtSignal(str)

    SAMPLE_RATE   = 16000
    CHANNELS      = 1
    CHUNK_SEC     = 0.05      # 50 мс — маленький чанк для плавного уровня
    SILENCE_SEC   = 3.0       # авто-стоп после N сек тишины (больше для нечёткой речи)
    MIN_REC_SEC   = 0.3       # минимальная длина для транскрипции

    # Пороги RMS (int16) — снижены чтобы ловить тихую и нечёткую речь
    RMS_SILENCE   = 90        # ниже = точно тишина (было 180)
    RMS_SPEECH    = 250       # выше = есть речь (было 400)

    # Языки для Google (приоритет: вверх списка важнее)
    GOOGLE_LANGS  = ["ru-RU", "en-US", "uk-UA", "de-DE",
                     "fr-FR", "es-ES", "zh-CN", "ja-JP",
                     "ko-KR", "it-IT", "pt-BR", "pl-PL"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recording  = False
        self._frames     = []
        self._stop_event = threading.Event()
        self._lock       = threading.Lock()
        # Кеш: проверяем движки один раз
        self._has_whisper = self._check_whisper()
        self._has_google  = self._check_google()
        print(f"[VOICE] Whisper={'✓' if self._has_whisper else '✗'}  "
              f"Google={'✓' if self._has_google else '✗'}  "
              f"sounddevice={'✓' if _VOICE_AVAILABLE else '✗'}")

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if not _VOICE_AVAILABLE:
            self.error_occurred.emit(
                "Установите:\npip install sounddevice numpy"
            )
            return
        if not self._has_whisper and not self._has_google:
            self.error_occurred.emit(
                "Нет движка распознавания.\n"
                "Установите один из:\n"
                "  pip install openai-whisper   ← рекомендуется\n"
                "  pip install SpeechRecognition"
            )
            return
        with self._lock:
            if self._recording:
                return
            self._recording = True
            self._frames    = []
        self._stop_event.clear()
        threading.Thread(target=self._record_loop, daemon=True).start()
        self.recording_started.emit()

    def stop(self):
        with self._lock:
            if not self._recording:
                return
        self._stop_event.set()

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ── Поток записи ─────────────────────────────────────────────────────────

    def _record_loop(self):
        import math as _math
        chunk_size     = int(self.SAMPLE_RATE * self.CHUNK_SEC)
        silence_chunks = int(self.SILENCE_SEC / self.CHUNK_SEC)
        silent_count   = 0
        has_speech     = False
        start_time     = __import__('time').time()
        smooth_level   = 0.0

        try:
            with _sd.InputStream(samplerate=self.SAMPLE_RATE,
                                  channels=self.CHANNELS,
                                  dtype="int16",
                                  blocksize=chunk_size) as stream:
                self.status_updated.emit("🔴 Говорите…")
                while not self._stop_event.is_set():
                    data, _ = stream.read(chunk_size)
                    chunk   = data.copy().flatten()
                    with self._lock:
                        self._frames.append(chunk)

                    # RMS → уровень 0..1 с экспоненциальным сглаживанием
                    sq  = _np.mean(chunk.astype(_np.float32) ** 2)
                    rms = _math.sqrt(max(float(sq), 0.0))
                    raw_level   = min(rms / 3000.0, 1.0)
                    smooth_level = smooth_level * 0.6 + raw_level * 0.4
                    self.level_updated.emit(smooth_level)

                    # VAD: трекинг тишины
                    if rms > self.RMS_SPEECH:
                        has_speech   = True
                        silent_count = 0
                    elif rms < self.RMS_SILENCE:
                        silent_count += 1
                    else:
                        silent_count = max(silent_count - 1, 0)

                    # Авто-стоп по тишине (только после начала речи)
                    elapsed = __import__('time').time() - start_time
                    if (has_speech
                            and silent_count >= silence_chunks
                            and elapsed >= self.MIN_REC_SEC + self.SILENCE_SEC):
                        self.status_updated.emit("⏹ Молчание — останавливаю…")
                        break

        except Exception as e:
            with self._lock:
                self._recording = False
            self.level_updated.emit(0.0)
            self.error_occurred.emit(f"Ошибка записи: {e}")
            return

        with self._lock:
            self._recording = False
        self.level_updated.emit(0.0)
        self.recording_stopped.emit()

        # Собираем буфер
        with self._lock:
            frames = list(self._frames)
        if not frames:
            self.error_occurred.emit("Нет аудио — попробуйте ещё раз")
            return

        audio = _np.concatenate(frames, axis=0)
        dur   = len(audio) / self.SAMPLE_RATE
        if dur < self.MIN_REC_SEC:
            self.error_occurred.emit("Запись слишком короткая — попробуйте ещё раз")
            return

        # Детектирование музыки / шума
        if self._is_music_or_noise(audio):
            self.error_occurred.emit(
                "Обнаружен фоновый шум или музыка.\n"
                "Попробуйте говорить чётче или уменьшите громкость фона."
            )
            return

        # VAD: обрезаем тишину по краям
        audio = self._vad_trim(audio)
        if len(audio) < self.SAMPLE_RATE * self.MIN_REC_SEC:
            self.error_occurred.emit("Речь не обнаружена — попробуйте ещё раз")
            return

        self.status_updated.emit("⏳ Распознаю речь…")
        self._transcribe(audio)

    # ── Анализ аудио ─────────────────────────────────────────────────────────

    def _is_music_or_noise(self, audio: Any) -> bool:
        """
        Определяет явную инструментальную музыку без голоса.
        Намеренно консервативная — лучше пропустить шум, чем заблокировать речь.
        НЕ блокирует: пение, нечёткую речь, речь с фоновой музыкой, акценты.
        Блокирует ТОЛЬКО: чистый инструментал (нет речевой энергии) + очень стабильный.
        """
        import math as _math
        try:
            sig = audio.astype(_np.float32)
            seg = sig[:self.SAMPLE_RATE]
            if len(seg) < self.SAMPLE_RATE // 3:
                return False   # слишком мало данных — не блокировать

            fft  = _np.abs(_np.fft.rfft(seg))
            freq = _np.fft.rfftfreq(len(seg), 1.0 / self.SAMPLE_RATE)

            # Проверяем долю энергии в широком речевом диапазоне 80–5000 Гц
            m     = (freq >= 80) & (freq <= 5000)
            total = float(_np.sum(fft)) + 1e-9
            ratio = float(_np.sum(fft[m])) / total

            # Если речевой диапазон занят — это речь (или пение), не блокируем
            if ratio >= 0.25:
                return False

            # Только при очень низкой речевой энергии проверяем тональность
            fft_s = fft.copy(); fft_s[~m] = 0
            top = sorted(range(len(fft_s)), key=lambda i: -fft_s[i])[:20]
            clean, used = [], set()
            for p in sorted(top, key=lambda i: -fft_s[i]):
                if all(abs(p - u) >= 5 for u in used):
                    clean.append(p); used.add(p)
                if len(clean) >= 6: break

            if len(clean) < 2:
                return False

            pf   = [freq[i] for i in clean]
            base = pf[0]
            if base < 60:
                return False

            harm = sum(1 for f in pf[1:] if abs((f / base) - round(f / base)) < 0.10)
            harm_ratio = harm / max(len(pf) - 1, 1)

            # Стабильность: музыка = ровная огибающая, речь/пение = резкая
            ch = int(self.SAMPLE_RATE * 0.1)
            rms_v = [
                _math.sqrt(max(float(_np.mean(sig[i:i+ch].astype(_np.float32)**2)), 0))
                for i in range(0, len(sig) - ch, ch)
            ]
            if len(rms_v) > 2:
                mu = sum(rms_v) / len(rms_v) + 1e-9
                cv = _math.sqrt(sum((x - mu)**2 for x in rms_v) / len(rms_v)) / mu
            else:
                cv = 1.0

            # Блокируем только ОЧЕНЬ тональный + очень стабильный + нет речи
            return harm_ratio > 0.85 and cv < 0.22

        except Exception:
            return False   # при любой ошибке — не блокировать

    def _vad_trim(self, audio: Any) -> Any:
        """Обрезает только явную тишину по краям. Консервативно — не режет тихую речь."""
        trim_thr = max(50, self.RMS_SILENCE * 0.55)  # намного ниже основного порога
        chunk    = int(self.SAMPLE_RATE * 0.05)
        rms_vals = []
        for i in range(0, len(audio), chunk):
            sq = _np.mean(audio[i:i+chunk].astype(_np.float32)**2)
            rms_vals.append(float(sq) ** 0.5)
        first = next((i for i, r in enumerate(rms_vals) if r > trim_thr), None)
        last  = next((i for i, r in reversed(list(enumerate(rms_vals))) if r > trim_thr), None)
        if first is None or last is None:
            return audio
        # Большой запас: ±8 чанков (400 мс) — не обрезаем начало/конец фразы
        s = max(0, (first - 8) * chunk)
        e = min(len(audio), (last + 9) * chunk)
        return audio[s:e]

    # ── Транскрипция ─────────────────────────────────────────────────────────

    def _transcribe(self, audio: Any):
        if self._has_whisper:
            self._transcribe_whisper(audio)
        elif self._has_google:
            self._transcribe_google(audio)
        else:
            self.error_occurred.emit("Нет движка распознавания")

    # Кэш модели Whisper в памяти — грузим один раз за сессию
    _whisper_model_cache = None

    def _transcribe_whisper(self, audio: Any):
        """
        Whisper — локальный, автоопределение языка.
        Модель кэшируется в памяти (_whisper_model_cache) и на диске
        (~/.cache/whisper) — не скачивается повторно между запусками.
        """
        try:
            import whisper, ssl, urllib.request as _ur

            # Если модель ещё не загружена в память
            if VoiceRecorder._whisper_model_cache is None:
                self.status_updated.emit("⏳ Загрузка Whisper…")
                _orig_ctx = ssl._create_default_https_context
                ssl._create_default_https_context = ssl._create_unverified_context
                _orig_opener = _ur.build_opener(
                    _ur.HTTPSHandler(context=ssl._create_unverified_context()))
                _ur.install_opener(_orig_opener)
                try:
                    # load_model читает из ~/.cache/whisper если уже скачано,
                    # иначе скачивает и кэширует там же автоматически
                    VoiceRecorder._whisper_model_cache = whisper.load_model("base")
                    print("[VOICE] Whisper base загружен в память")
                finally:
                    ssl._create_default_https_context = _orig_ctx

            model = VoiceRecorder._whisper_model_cache
            self.status_updated.emit("🎤 Распознаю…")

            af32 = audio.astype(_np.float32) / 32768.0
            result = model.transcribe(af32, fp16=False)
            text = (result.get("text") or "").strip()
            lang = result.get("language", "?")
            print(f"[VOICE] Whisper: lang={lang} text={text[:60]}")
            if text:
                self.status_updated.emit(f"✅ Язык: {lang}")
                self.transcription_done.emit(text)
            else:
                if self._has_google:
                    self._transcribe_google(audio)
                else:
                    self.error_occurred.emit("Речь не распознана")
        except ImportError:
            self._has_whisper = False
            if self._has_google:
                self._transcribe_google(audio)
            else:
                self.error_occurred.emit("Whisper недоступен; установите SpeechRecognition")
        except Exception as e:
            self.error_occurred.emit(f"Whisper ошибка: {e}")

    def _transcribe_google(self, audio: Any):
        """Google Web Speech — пробует несколько языков по очереди."""
        try:
            import io, wave
            import speech_recognition as sr_lib

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(self.CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(self.SAMPLE_RATE)
                wf.writeframes(audio.tobytes())
            buf.seek(0)

            rec = sr_lib.Recognizer()
            rec.energy_threshold         = 100   # было 300 — ловим тихую речь
            rec.dynamic_energy_threshold = True
            rec.pause_threshold          = 1.2
            with sr_lib.AudioFile(buf) as src:
                aud = rec.record(src)

            best_text, best_conf, best_lang = "", -1.0, ""

            for lang in self.GOOGLE_LANGS:
                try:
                    # show_all=True возвращает варианты с confidence
                    result = rec.recognize_google(aud, language=lang, show_all=True)
                    if not result:
                        continue
                    alts = result.get('alternative', []) if isinstance(result, dict) else []
                    if not alts:
                        continue
                    text = alts[0].get('transcript', '')
                    conf = float(alts[0].get('confidence', 0.5))
                    if text and conf > best_conf:
                        best_conf, best_text, best_lang = conf, text, lang
                    if best_conf >= 0.88:   # достаточно уверен — не продолжаем
                        break
                except sr_lib.UnknownValueError:
                    continue
                except sr_lib.RequestError as e:
                    self.error_occurred.emit(f"Ошибка сети: {e}")
                    return

            if best_text:
                print(f"[VOICE] Google: lang={best_lang} conf={best_conf:.2f} text={best_text[:60]}")
                self.status_updated.emit(f"✅ {best_lang}")
                self.transcription_done.emit(best_text)
            else:
                self.error_occurred.emit(
                    "Речь не распознана.\n"
                    "Совет: pip install openai-whisper — лучше работает офлайн."
                )
        except ImportError:
            self.error_occurred.emit("pip install SpeechRecognition")
        except Exception as e:
            self.error_occurred.emit(f"Ошибка распознавания: {e}")

    # ── Проверка движков ──────────────────────────────────────────────────────

    @staticmethod
    def _check_whisper() -> bool:
        try: import whisper; return True       # noqa
        except ImportError: return False

    @staticmethod
    def _check_google() -> bool:
        try: import speech_recognition; return True   # noqa
        except ImportError: return False


class MainWindow(AttachmentMixin, QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        global CURRENT_LANGUAGE
        self.current_language = CURRENT_LANGUAGE
        self.deep_thinking = False
        self.use_search = False
        self.is_generating = False
        self._regen_target_widget = None  # виджет-цель для add_regen_entry
        self.current_user_message = ""
        self.current_worker = None
        
        # ✅ ИСПРАВЛЕНИЕ: Список активных workers для предотвращения RuntimeError
        # WorkerSignals не должен удаляться пока worker работает
        self.active_workers = []  # Сильные ссылки на workers
        
        # Режим работы AI
        self.ai_mode = AI_MODE_FAST  # По умолчанию быстрый режим
        # Загружаем сохранённую модель из настроек
        self._load_model_preference()
        # При запуске: выгружаем все модели кроме выбранной (на случай грязного завершения),
        # затем загружаем в память только активную модель
        unload_all_models(except_key=llama_handler.CURRENT_AI_MODEL_KEY, synchronous=False)
        warm_up_model(llama_handler.CURRENT_AI_MODEL_KEY)
        
        # Таймер обдумывания
        self.thinking_start_time = None
        self.thinking_elapsed_time = 0
        
        # Режим редактирования
        self.is_editing = False
        self.editing_message_text = ""
        
        # Прикреплённые файлы (до 5 файлов одновременно)
        self.attached_files = []
        
        # ═══════════════════════════════════════════════════════════════
        # СИСТЕМА ХРАНЕНИЯ ФАЙЛОВ ОТКЛЮЧЕНА
        # ═══════════════════════════════════════════════════════════════
        # Файлы больше не копируются и не сохраняются
        # Используются только исходные пути для анализа AI
        print(f"[CHAT_FILES] ℹ️ Система хранения файлов отключена")
        
        
        # ═══════════════════════════════════════════════════════════════
        # DRAG-AND-DROP: Включаем поддержку перетаскивания файлов
        # ═══════════════════════════════════════════════════════════════
        self.setAcceptDrops(True)
        print("[DRAG-DROP] ✓ Поддержка перетаскивания файлов включена")
        
        
        # Менеджер чатов
        self.chat_manager = ChatManager()
        
        # Текущая тема и настройки интерфейса
        self.current_theme = "light"
        self.current_liquid_glass = True
        
        # ═══════════════════════════════════════════════════════════════
        # ЛОГИКА СТАРТОВОГО ЧАТА
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: Удаляем все старые ПУСТЫЕ чаты (без пользовательских сообщений)
        print("[STARTUP] Очистка старых пустых чатов...")
        self._cleanup_empty_chats_on_startup()

        # ШАГ 2: Проверяем можно ли восстановить последний чат
        # Если с момента закрытия прошло < 20 секунд — открываем тот же чат,
        # иначе (долгий перерыв или первый запуск) — создаём новый чат.
        _restored_chat_id = None
        _RESUME_THRESHOLD_SEC = 20
        try:
            if os.path.exists("app_settings.json"):
                with open("app_settings.json", "r", encoding="utf-8") as _sf:
                    _saved = json.load(_sf)
                _last_chat_id = _saved.get("last_chat_id")
                _last_close_ts = _saved.get("last_close_ts", 0)
                _elapsed = time.time() - _last_close_ts
                if _last_chat_id and _elapsed < _RESUME_THRESHOLD_SEC:
                    # Проверяем что чат реально существует
                    _all = self.chat_manager.get_all_chats()
                    _ids = {c["id"] for c in _all}
                    if _last_chat_id in _ids:
                        _restored_chat_id = _last_chat_id
                        print(f"[STARTUP] ⚡ Быстрый перезапуск ({_elapsed:.1f}с) — восстанавливаем чат ID={_last_chat_id}")
                    else:
                        print(f"[STARTUP] Чат ID={_last_chat_id} не найден — создаём новый")
                else:
                    print(f"[STARTUP] Пауза {_elapsed:.0f}с ≥ {_RESUME_THRESHOLD_SEC}с — создаём новый чат")
        except Exception as _re:
            print(f"[STARTUP] ⚠️ Ошибка чтения last_chat_id: {_re}")

        if _restored_chat_id:
            # Восстанавливаем существующий чат
            self.chat_manager.set_active_chat(_restored_chat_id)
            self.current_chat_id = _restored_chat_id
            on_chat_switched_all_memories(_restored_chat_id)
            self.startup_chat_id = None          # не «стартовый пустой», уже с историей
            self.startup_chat_has_messages = True
            print(f"[STARTUP] ✓ Восстановлен чат ID={_restored_chat_id}")
        else:
            # Создаём новый пустой чат
            new_chat_id = self.chat_manager.create_chat("Новый чат")
            self.chat_manager.set_active_chat(new_chat_id)
            self.current_chat_id = new_chat_id
            on_chat_switched_all_memories(new_chat_id)
            self.startup_chat_id = new_chat_id
            self.startup_chat_has_messages = False
            print(f"[STARTUP] Создан новый стартовый чат ID={new_chat_id}")

        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 850)

        icon_pixmap = create_app_icon()
        self.setWindowIcon(QtGui.QIcon(icon_pixmap))

        # ── Animated background widget (lives behind everything) ──
        self.bg_widget = QtWidgets.QWidget()
        self.bg_widget.setObjectName("bgWidget")

        # Главный контейнер
        main_container = QtWidgets.QWidget()
        main_container.setObjectName("mainContainer")
        self.setCentralWidget(main_container)
        self.main_container = main_container   # нужен в resizeEvent для overlay-sidebar
        container_layout = QtWidgets.QHBoxLayout(main_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # ─────────────────────────────────────────────────────────────────────
        # SIDEBAR — OVERLAY DRAWER
        # Не в layout! Позиционируется абсолютно поверх контента.
        # Начальная позиция: x = -SIDEBAR_W (полностью за левым краем).
        # При открытии: pos.x анимируется от -280 до 0.
        # При закрытии: обратно. Контент никуда не сдвигается.
        # ─────────────────────────────────────────────────────────────────────
        SIDEBAR_W = 280
        self._SIDEBAR_W   = SIDEBAR_W
        self._sidebar_open = False    # флаг состояния (вместо sidebar.width())

        self.sidebar = QtWidgets.QWidget(main_container)  # дочерний, но НЕ в layout
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(SIDEBAR_W)
        self.sidebar.move(-SIDEBAR_W, 0)   # за левым краем — невидим
        self.sidebar.raise_()              # поверх всего

        # ── Тень sidebar — отдельный виджет-градиент справа от панели ────────
        # QGraphicsDropShadowEffect нельзя совмещать с QGraphicsOpacityEffect
        # (Qt поддерживает только один graphicsEffect на виджет).
        # Решение: узкий QLabel с градиентом от чёрного к прозрачному.
        SHADOW_W = 22
        self._sb_shadow_widget = QtWidgets.QLabel(main_container)
        self._sb_shadow_widget.setObjectName("sidebarShadow")
        self._sb_shadow_widget.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._sb_shadow_widget.setStyleSheet(
            "background: qlineargradient("
            "x1:0,y1:0,x2:1,y2:0,"
            "stop:0 rgba(0,0,0,55), stop:1 rgba(0,0,0,0));"
            "border:none;"
        )
        # Изначально скрыт вместе с sidebar (за левым краем)
        self._sb_shadow_widget.setGeometry(-SHADOW_W, 0, SHADOW_W, 400)
        self._sb_shadow_widget.hide()

        sidebar_layout = QtWidgets.QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 12, 0, 0)
        sidebar_layout.setSpacing(0)

        # Кнопка "Новый чат"
        new_chat_btn = NoFocusButton("+ Новый чат")
        new_chat_btn.setObjectName("newChatBtn")
        new_chat_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        new_chat_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        new_chat_btn.clicked.connect(self.create_new_chat)
        sidebar_layout.addWidget(new_chat_btn)

        # Список чатов
        self.chats_list = QtWidgets.QListWidget()
        self.chats_list.setObjectName("chatsList")
        self.chats_list.itemClicked.connect(self.switch_chat)
        self.chats_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.chats_list.customContextMenuRequested.connect(self.show_delete_panel)
        # Кастомный делегат: двухстрочные элементы + разделители
        self._chat_list_delegate = ChatListDelegate(theme="light", parent=self.chats_list)
        self.chats_list.setItemDelegate(self._chat_list_delegate)
        self.chats_list.setMouseTracking(True)  # нужно для hover
        # Предотвращаем выход hover-фона за границы виджета
        self.chats_list.setViewportMargins(6, 8, 6, 8)  # отступы со всех сторон — hover не вылезает
        self.chats_list.viewport().setAutoFillBackground(False)
        self.chats_list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)  # убираем рамку QFrame
        sidebar_layout.addWidget(self.chats_list)

        # ═══════════════════════════════════════════════
        # НОВОЕ: Кнопка настроек (закреплена снизу sidebar)
        # ═══════════════════════════════════════════════
        self.settings_btn = NoFocusButton("⚙️ Настройки")
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.settings_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.settings_btn.clicked.connect(self.open_settings)
        sidebar_layout.addWidget(self.settings_btn)


        # sidebar НЕ добавляем в container_layout — он overlay

        # ── Dim-overlay: затемняет контент когда sidebar открыт ──────────────
        # Клик по overlay закрывает sidebar (как в мобильных приложениях).
        self._dim_overlay = QtWidgets.QWidget(main_container)
        self._dim_overlay.setObjectName("dimOverlay")
        self._dim_overlay.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._dim_overlay.hide()
        self._dim_overlay.installEventFilter(self)   # клик по нему → close sidebar
        # Панель удаления (справа от sidebar)
        self.delete_panel = QtWidgets.QWidget()
        self.delete_panel.setObjectName("deletePanel")
        self.delete_panel.setFixedWidth(0)  # Изначально скрыта
        delete_layout = QtWidgets.QVBoxLayout(self.delete_panel)
        delete_layout.setContentsMargins(0, 12, 0, 0)
        delete_layout.setSpacing(10)
        
        delete_layout.addStretch()
        
        # Кнопка удаления
        self.delete_chat_btn = QtWidgets.QPushButton("🗑️ Удалить чат")
        self.delete_chat_btn.setObjectName("deleteChatBtn")
        self.delete_chat_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.delete_chat_btn.clicked.connect(self.delete_selected_chat)
        delete_layout.addWidget(self.delete_chat_btn)
        
        delete_layout.addStretch()
        
        container_layout.addWidget(self.delete_panel)
        
        # ID чата для удаления
        self.chat_to_delete = None

        # Основная область
        central = QtWidgets.QWidget()
        central.setObjectName("central")
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title block
        title_widget = QtWidgets.QWidget()
        title_widget.setObjectName("titleWidget")
        self.title_widget = title_widget  # Сохраняем ссылку для blur эффекта
        title_layout = QtWidgets.QHBoxLayout(title_widget)
        title_layout.setContentsMargins(15, 12, 15, 12)
        title_layout.setSpacing(15)

        # Кнопка меню (иконка трёх полосок)
        self.menu_btn = NoFocusButton()
        self.menu_btn.setObjectName("menuBtn")
        self.menu_btn.setFixedSize(50, 50)
        self.menu_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.menu_btn.clicked.connect(self.toggle_sidebar)
        # Иконка будет установлена после применения темы
        title_layout.addWidget(self.menu_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

        title_layout.addStretch()
        title_label = QtWidgets.QLabel(APP_TITLE)
        title_label.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        title_label.mousePressEvent = lambda event: self.show_model_info()
        title_label.setObjectName("titleLabel")
        font_title = _apple_font(22, weight=QtGui.QFont.Weight.Bold)
        title_label.setFont(font_title)
        title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(title_label, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
        title_layout.addStretch()

        # Кастомная кнопка очистки с подсказкой
        class ClearButtonWithTooltip(QtWidgets.QPushButton):
            def __init__(self, text, parent=None):
                super().__init__(text, parent)
                self.glass_tooltip = None
            
            def enterEvent(self, event):
                # При наведении на неактивную кнопку показываем подсказку
                if not self.isEnabled():
                    if not self.glass_tooltip:
                        self.glass_tooltip = GlassTooltip("Нет сообщений для очистки")
                    # Показываем подсказку под кнопкой
                    button_center = self.rect().center()
                    global_pos = self.mapToGlobal(QtCore.QPoint(button_center.x(), self.height()))
                    self.glass_tooltip.show_at(global_pos)
                super().enterEvent(event)
            
            def leaveEvent(self, event):
                # Скрываем подсказку при уходе курсора
                if self.glass_tooltip:
                    self.glass_tooltip.hide()
                super().leaveEvent(event)
        
        self.clear_btn = ClearButtonWithTooltip("🗑️ Очистить")
        self.clear_btn.setObjectName("clearBtn")
        font_clear = _apple_font(13, weight=QtGui.QFont.Weight.Bold)
        self.clear_btn.setFont(font_clear)
        self.clear_btn.setFixedSize(120, 44)
        self.clear_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.clear_btn.clicked.connect(self.clear_chat)
        title_layout.addWidget(self.clear_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

        title_layout.addSpacing(8)

        main_layout.addWidget(title_widget)


        # ═══════════════════════════════════════════════════════════════
        # Chat display - QStackedWidget для переключения чат/настройки
        # ═══════════════════════════════════════════════════════════════
        self.content_stack = QtWidgets.QStackedWidget()
        self.content_stack.setObjectName("contentStack")
        
        # ✅ ИСПРАВЛЕНИЕ: Устанавливаем прозрачный фон для content_stack
        # Это предотвращает белое мигание при переключении страниц
        self.content_stack.setStyleSheet("QStackedWidget { background: transparent; }")

        # ═══════════════════════════════════════════════
        # PAGE 0: CHAT VIEW (существующий функционал)
        # ═══════════════════════════════════════════════
        chat_container = QtWidgets.QWidget()
        chat_container.setObjectName("chatContainer")
        chat_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        chat_layout = QtWidgets.QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("scrollArea")
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        self.scroll_area.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )

        self.scroll_area.setStyleSheet("background: transparent;")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")

        self.messages_widget = QtWidgets.QWidget()
        
        self.messages_layout = QtWidgets.QVBoxLayout()
        self.messages_layout.setContentsMargins(5, 5, 5, 20)
        self.messages_layout.setSpacing(8)
        self.messages_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        
        self.messages_widget.setLayout(self.messages_layout)
        
        self.messages_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum
        )

        self.messages_widget.setStyleSheet("background: transparent;")

        self.scroll_area.setWidget(self.messages_widget)
        
        # ═══════════════════════════════════════════════════════════════
        # УСТАНОВКА EVENT FILTER ДЛЯ БЛОКИРОВКИ SCROLL INPUT ВО ВРЕМЯ LAYOUT
        # ═══════════════════════════════════════════════════════════════
        # КРИТИЧНО: Устанавливаем фильтр событий на viewport, а не scroll_area.
        # EventFilter для обновления кнопки "вниз" после wheel событий
        self.scroll_area.viewport().installEventFilter(self)
        
        # EventFilter для обработки resize (обновление позиции кнопки)
        self.scroll_area.installEventFilter(self)
        
        print("[INIT] ✓ messages_layout выровнен вверх без stretch")
        print("[INIT] ✓ БЕЗ автоскролла - пользователь управляет прокруткой сам")
        print("[INIT] ✓ Event filter установлен для обновления кнопки после скролла")
        print("[INIT] ✓ Layout обновляется СИНХРОННО через adjustSize()")
        
        print("[ДИАГНОСТИКА] messages_widget.parent():", self.messages_widget.parent())
        print("[ДИАГНОСТИКА] scroll_area.viewport():", self.scroll_area.viewport())
        print("[ДИАГНОСТИКА] Совпадают?", self.messages_widget.parent() == self.scroll_area.viewport())
        
        # ═══════════════════════════════════════════════
        # НОВОЕ: FLOATING КНОПКА "ВНИЗ" (overlay)
        # ═══════════════════════════════════════════════
        # АРХИТЕКТУРА: Полностью пассивный overlay
        # - НЕ подключена к сигналам scrollbar (valueChanged, rangeChanged)
        # - НЕ вызывает update(), repaint(), updateGeometry()
        # - НЕ влияет на layout сообщений
        # - Обновляется ТОЛЬКО явно после завершения layout
        # - Обновляется после ручного скролла через eventFilter
        self.scroll_to_bottom_btn = ScrollToBottomButton(self.scroll_area)
        self.scroll_to_bottom_btn.clicked.connect(self.manual_scroll_to_bottom)
        
        # Позиционируем кнопку один раз при создании
        # Дальше позиция обновляется только при resize окна (см. eventFilter)
        self.scroll_to_bottom_btn.update_position(
            self.scroll_area.width(),
            self.scroll_area.height()
        )
        
        chat_layout.addWidget(self.scroll_area)
        
        # ═══════════════════════════════════════════════
        # PAGE 1: SETTINGS VIEW
        # ═══════════════════════════════════════════════
        self.settings_view = SettingsView()
        self.settings_view.close_requested.connect(self.close_settings)
        self.settings_view.settings_applied.connect(self.on_settings_applied)
        self.settings_view.delete_all_chats_requested.connect(self.confirm_delete_all_chats)
        self.settings_view.delete_all_models_requested.connect(self.confirm_delete_all_models)
        
        # Добавляем страницы в stack
        self.content_stack.addWidget(chat_container)  # index 0
        self.content_stack.addWidget(self.settings_view)  # index 1
        
        # Показываем чат по умолчанию
        self.content_stack.setCurrentIndex(0)
        
        main_layout.addWidget(self.content_stack, stretch=1)

        # ═══════════════════════════════════════════════════════════════
        # ФАЙЛОВЫЕ ЧИПЫ — показываются над полем ввода когда файлы прикреплены
        # ═══════════════════════════════════════════════════════════════
        self.file_chip_container = QtWidgets.QWidget()
        self.file_chip_container.setObjectName("fileChipContainer")
        # ✅ ИСПРАВЛЕНИЕ: Устанавливаем максимальную высоту чтобы окно не увеличивалось
        self.file_chip_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Maximum  # Максимальный размер ограничен
        )
        self.file_chip_container.setMaximumHeight(120)  # Максимум ~2 ряда чипов
        self.file_chip_container.setStyleSheet("#fileChipContainer { background: transparent; border: none; }")
        self.file_chip_container.hide()  # Скрыт по умолчанию

        # Layout будет создан динамически в update_file_chips()
        main_layout.addWidget(self.file_chip_container)

        # Input elements - добавляем в main_layout ПОСЛЕ scroll area
        input_container = QtWidgets.QWidget()
        input_container.setObjectName("inputContainer")
        input_container.setStyleSheet("#inputContainer { background: transparent; border: none; }")
        # ✅ КРИТИЧНО: Fixed size policy для footer
        input_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,  # Изменено с Expanding на Preferred
            QtWidgets.QSizePolicy.Policy.Fixed
        )
        input_container.setFixedHeight(85)  # Фиксированная высота footer
        
        input_layout = QtWidgets.QHBoxLayout(input_container)
        input_layout.setContentsMargins(25, 15, 25, 10)
        input_layout.setSpacing(15)

        # Кнопка добавления файла
        self.attach_btn = NoFocusButton("+")
        self.attach_btn.setObjectName("attachBtn")
        font_attach = _apple_font(26, weight=QtGui.QFont.Weight.Bold)
        self.attach_btn.setFont(font_attach)
        self.attach_btn.setFixedSize(60, 60)
        self.attach_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.attach_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.attach_btn.clicked.connect(self.show_attach_menu)
        input_layout.addWidget(self.attach_btn)

        # ── Поле ввода с кнопкой микрофона внутри ───────────────────────────
        self.input_wrapper = QtWidgets.QFrame()
        self.input_wrapper.setObjectName("inputField")
        self.input_wrapper.setMinimumHeight(60)
        self.input_wrapper.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        _wrap_layout = QtWidgets.QHBoxLayout(self.input_wrapper)
        _wrap_layout.setContentsMargins(20, 0, 8, 0)
        _wrap_layout.setSpacing(4)

        self.input_field = SpellCheckLineEdit()
        self.input_field.setPlaceholderText("Введите сообщение...")
        self.input_field.setObjectName("inputFieldInner")
        font_input = _apple_font(14)
        self.input_field.setFont(font_input)
        self.input_field.setMinimumHeight(56)
        self.input_field.returnPressed.connect(self.send_message)
        _wrap_layout.addWidget(self.input_field, stretch=1)

        # ── Кнопка микрофона (внутри поля ввода) ────────────────────────────
        self.mic_btn = NoFocusButton("🎤")
        self.mic_btn.setObjectName("micBtnInline")
        font_mic = _apple_font(20)
        self.mic_btn.setFont(font_mic)
        self.mic_btn.setFixedSize(44, 44)
        self.mic_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.mic_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.mic_btn.setCheckable(True)
        self.mic_btn.clicked.connect(self._toggle_voice)
        _wrap_layout.addWidget(self.mic_btn)

        input_layout.addWidget(self.input_wrapper, stretch=1)

        # Инициализируем VoiceRecorder
        self._voice = VoiceRecorder(self)
        self._voice.recording_started.connect(self._on_recording_started)
        self._voice.recording_stopped.connect(self._on_recording_stopped)
        self._voice.transcription_done.connect(self._on_transcription_done)
        self._voice.error_occurred.connect(self._on_voice_error)
        self._voice.level_updated.connect(self._on_voice_level)
        self._voice.status_updated.connect(self._on_voice_status)

        # Кнопка выбора режима AI (новая)
        self.mode_btn = NoFocusButton(self.ai_mode)
        self.mode_btn.setObjectName("modeBtn")
        font_mode = _apple_font(12, weight=QtGui.QFont.Weight.Medium)
        self.mode_btn.setFont(font_mode)
        self.mode_btn.setFixedSize(95, 60)
        self.mode_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.mode_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.mode_btn.clicked.connect(self.show_mode_menu)
        input_layout.addWidget(self.mode_btn)

        self.send_btn = NoFocusButton("→")
        self.send_btn.setObjectName("sendBtn")
        font_btn = _apple_font(22, weight=QtGui.QFont.Weight.Bold)
        self.send_btn.setFont(font_btn)
        _set_send_icon(self.send_btn)  # Windows-safe: вектор вместо эмодзи
        self.send_btn.setFixedSize(60, 60)
        self.send_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.send_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_btn)

        # ✅ КРИТИЧНО: Добавляем input_container в main_layout с stretch=0
        main_layout.addWidget(input_container, 0)
        
        # Store reference
        self.input_container = input_container

        # Статус - fixed at bottom
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("statusLabel")
        font_status = _apple_font(11)
        self.status_label.setFont(font_status)
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.status_label.setContentsMargins(30, 0, 30, 10)
        # ✅ ИСПРАВЛЕНИЕ ДЁРГАНЬЯ: фиксированная высота предотвращает
        # пересчёт layout при смене текста (анимация точек "...")
        self.status_label.setFixedHeight(24)
        main_layout.addWidget(self.status_label)


        # Добавляем основную область в контейнер
        container_layout.addWidget(central)

        self.threadpool = QtCore.QThreadPool()

        # Устанавливаем фильтр событий для автозакрытия sidebar при клике по рабочей области
        self.messages_widget.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)
        chat_container.installEventFilter(self)

        # Загружаем сохранённые настройки
        saved_settings = self.load_saved_settings()
        theme = saved_settings.get("theme", "light")
        liquid_glass = saved_settings.get("liquid_glass", True)
        
        print(f"[INIT] Загружены настройки: тема={theme}, стекло={liquid_glass}")
        
        # КРИТИЧНО: Обновляем self.current_theme ДО применения стилей
        # Без этого меню + и режимов не знают какая тема активна
        self.current_theme = theme
        self.current_liquid_glass = liquid_glass
        self.auto_scroll_enabled = saved_settings.get("auto_scroll", False)
        
        # Применяем стили с загруженными настройками
        self.apply_styles(theme=theme, liquid_glass=liquid_glass)
        
        # Применяем тему к кнопке "вниз"
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.scroll_to_bottom_btn.apply_theme_styles(theme=theme, liquid_glass=liquid_glass)
        
        # Обновляем settings_view с правильной темой
        if hasattr(self, 'settings_view'):
            self.settings_view.current_settings["theme"] = theme
            self.settings_view.current_settings["liquid_glass"] = liquid_glass
            self.settings_view.pending_settings["theme"] = theme
            self.settings_view.pending_settings["liquid_glass"] = liquid_glass
            self.settings_view.apply_settings_styles()
        
        self.load_chats_list()
        self.load_current_chat()
        
        # Флаг первого показа для финализации layout
        self._first_show_done = False
    
    # ═══════════════════════════════════════════════════════════════════════
    # SYSTEM TRAY ICON
    # ═══════════════════════════════════════════════════════════════════════

    def load_saved_settings(self) -> dict:
        """Загрузить сохранённые настройки из файла"""
        try:
            if os.path.exists("app_settings.json"):
                with open("app_settings.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"[SETTINGS] Ошибка загрузки настроек: {e}")
        
        # Возвращаем значения по умолчанию
        return {"theme": "light", "liquid_glass": True}
    
    def showEvent(self, event):
        """
        Обработчик первого показа окна.
        
        КРИТИЧНО: После первого показа окна выполняем финализацию layout.
        Это исправляет баг, когда layout не обновляется до первого скролла.
        """
        super().showEvent(event)
        
        if not self._first_show_done:
            self._first_show_done = True
            # Каскадное появление элементов при запуске
            self._start_window_fade_in()
            # Откладываем финализацию на следующий цикл event loop
            # Это гарантирует что все виджеты полностью отрендерены
            QtCore.QTimer.singleShot(0, self._finalize_initial_layout)

    def _start_window_fade_in(self):
        """
        Каскадное появление элементов UI при запуске.

        Шапка: slide-down (maxHeight 0 → натуральный) + fade-in одновременно.
        Остальные блоки: только fade-in с нарастающей задержкой.

        Хронология:
          0ms   — шапка начинает slide-down + fade
          160ms — область чата (fade)
          300ms — контейнер ввода (fade)
          400ms — строка статуса (fade)
        """
        self.setWindowOpacity(1.0)
        # Хранилище анимаций — чтобы GC не удалил их раньше завершения
        self._startup_anims = []

        # ─────────────────────────────────────────────────────────
        # ШАПКА: slide-down (0 → натуральная высота) + fade одновременно
        # ─────────────────────────────────────────────────────────
        if hasattr(self, 'title_widget'):
            tw = self.title_widget

            # Узнаём натуральную высоту (sizeHint) до того как спрячем
            natural_h = tw.sizeHint().height()
            if natural_h < 10:
                natural_h = 74  # fallback

            # Скрываем шапку: высота 0, opacity 0
            tw.setMaximumHeight(0)
            tw.setMinimumHeight(0)

            eff_tw = QtWidgets.QGraphicsOpacityEffect(tw)
            tw.setGraphicsEffect(eff_tw)
            eff_tw.setOpacity(0.0)
            self._startup_anims.append(eff_tw)

            # Анимация высоты: 0 → natural_h
            anim_h = QtCore.QPropertyAnimation(tw, b"maximumHeight")
            anim_h.setDuration(480)
            anim_h.setStartValue(0)
            anim_h.setEndValue(natural_h)
            anim_h.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            self._startup_anims.append(anim_h)

            # Анимация прозрачности: 0 → 1
            anim_op = QtCore.QPropertyAnimation(eff_tw, b"opacity")
            anim_op.setDuration(420)
            anim_op.setStartValue(0.0)
            anim_op.setEndValue(1.0)
            anim_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            self._startup_anims.append(anim_op)

            def _cleanup_header():
                try:
                    tw.setMaximumHeight(16777215)   # QWIDGETSIZE_MAX — снимаем ограничение
                    tw.setMinimumHeight(0)
                    tw.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            anim_h.finished.connect(_cleanup_header)

            # Запускаем обе анимации одновременно через таймер (чтобы layout успел)
            def _start_header():
                try:
                    anim_h.start()
                    anim_op.start()
                except RuntimeError:
                    pass

            QtCore.QTimer.singleShot(0, _start_header)

        # ─────────────────────────────────────────────────────────
        # Fade-in остальных элементов — ПОСЛЕ шапки
        # Шапка занимает ~480мс. Остальное стартует после неё,
        # чтобы каждый элемент появлялся отдельно, красиво.
        #
        # Хронология (от старта):
        #   0ms   — шапка slide-down (480ms)
        #   520ms — область чата
        #   680ms — контейнер ввода
        #   800ms — строка статуса
        # ─────────────────────────────────────────────────────────
        def _make_fade(widget, delay_ms: int, duration_ms: int = 400):
            eff = QtWidgets.QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(eff)
            eff.setOpacity(0.0)

            anim = QtCore.QPropertyAnimation(eff, b"opacity")
            anim.setDuration(duration_ms)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

            self._startup_anims.extend([eff, anim])

            def _cleanup():
                try:
                    widget.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            anim.finished.connect(_cleanup)

            def _start():
                try:
                    eff.setOpacity(0.0)
                    anim.start()
                except RuntimeError:
                    pass

            QtCore.QTimer.singleShot(delay_ms, _start)

        # ── Область чата — после шапки ───────────────────────────
        if hasattr(self, 'scroll_area'):
            _make_fade(self.scroll_area, delay_ms=520, duration_ms=420)

        # ── Контейнер ввода ───────────────────────────────────────
        if hasattr(self, 'input_container'):
            _make_fade(self.input_container, delay_ms=680, duration_ms=400)

        # ── Строка статуса ────────────────────────────────────────
        if hasattr(self, 'status_label'):
            _make_fade(self.status_label, delay_ms=800, duration_ms=320)
    
    def _finalize_initial_layout(self):
        """
        Финализация layout после первого показа окна.
        
        АЛГОРИТМ:
        1. Дождаться завершения layout через event loop (уже сделано через singleShot(0))
        2. Обновить только контейнер сообщений
        3. НЕ вызывать автоскролл
        4. НЕ использовать processEvents, updateGeometry, adjustSize
        """
        try:
            # Мягкое обновление контейнера сообщений
            if hasattr(self, 'messages_widget'):
                self.messages_widget.update()
            
            # Обновляем scroll area
            if hasattr(self, 'scroll_area'):
                self.scroll_area.update()
            
            print("[LAYOUT_FINALIZE] ✓ Layout финализирован после первого показа")
        except Exception as e:
            print(f"[LAYOUT_FINALIZE] ✗ Ошибка: {e}")
    
    def closeEvent(self, event):
        """
        Закрытие окна — мгновенное даже если ИИ генерирует ответ.
        Перед выходом синхронно выгружает все модели из памяти Ollama,
        чтобы при следующем запуске не было «призрачных» загруженных весов.
        os._exit(0) убивает процесс сразу после выгрузки.
        """
        import os as _os, threading as _thr

        print("[CLOSE] Закрытие приложения...")

        # 0. Сохраняем текущий chat_id и время закрытия (для восстановления при быстром перезапуске)
        try:
            _s = {}
            if os.path.exists("app_settings.json"):
                with open("app_settings.json", "r", encoding="utf-8") as _sf:
                    _s = json.load(_sf)
            _s["last_chat_id"] = getattr(self, "current_chat_id", None)
            _s["last_close_ts"] = time.time()
            with open("app_settings.json", "w", encoding="utf-8") as _sf:
                json.dump(_s, _sf, indent=2)
            print(f"[CLOSE] ✓ Сохранён last_chat_id={_s['last_chat_id']}")
        except Exception as _ce:
            print(f"[CLOSE] ⚠️ Не удалось сохранить last_chat_id: {_ce}")

        # 1. Флаг — воркеры не шлют сигналы
        llama_handler._APP_SHUTTING_DOWN = True

        # 2. Отменяем текущего воркера
        if hasattr(self, 'current_worker') and self.current_worker is not None:
            try:
                self.current_worker._cancelled = True
            except Exception:
                pass

        # 3. Скрываем окно сразу — UI не подвисает
        self.hide()
        event.accept()

        # 4. Синхронно выгружаем ВСЕ модели из памяти Ollama.
        #    Timeout 4с на каждую — суммарно не более ~12с для 3 моделей.
        #    Если Ollama недоступна — просто пропускаем, не блокируем выход.
        print("[CLOSE] Выгружаем все модели из памяти Ollama…")
        unload_all_models(except_key=None, synchronous=True, timeout=4)
        print("[CLOSE] ✓ Модели выгружены")

        # 5. Закрываем HTTP-сессию
        try:
            llama_handler._OLLAMA_SESSION.close()
        except Exception:
            pass

        # 6. Останавливаем Ollama, если мы её сами запускали
        try:
            from ollama_manager import stop_managed_ollama
            stop_managed_ollama()
        except Exception:
            pass

        # 7. os._exit(0) — убивает процесс немедленно
        print("[CLOSE] ✓ os._exit(0)")
        _os._exit(0)

    def resizeEvent(self, event):
        """
        Обработка изменения размера окна.
        
        КРИТИЧНО:
        - Обновляем ТОЛЬКО позицию overlay-кнопки "вниз"
        - Обновляем размер blur overlay если он существует
        - Обновляем высоту sidebar (overlay — ширина фиксирована, высота = окно)
        - НЕ трогаем layout сообщений
        - НЕ вызываем updateGeometry или invalidate
        """
        super().resizeEvent(event)
        
        # Обновляем позицию overlay-кнопки при изменении размера scroll_area
        if hasattr(self, 'scroll_to_bottom_btn') and hasattr(self, 'scroll_area'):
            self.scroll_to_bottom_btn.update_position(
                self.scroll_area.width(),
                self.scroll_area.height()
            )
        
        # ✅ Обновляем размер blur overlay
        if hasattr(self, '_blur_overlay') and self._blur_overlay.isVisible():
            self._blur_overlay.setGeometry(self.rect())

        # ✅ Sidebar overlay — подстраиваем высоту под новый размер контейнера
        if hasattr(self, 'sidebar') and hasattr(self, 'main_container'):
            h = self.main_container.height()
            W = getattr(self, '_SIDEBAR_W', 280)
            is_open = getattr(self, '_sidebar_open', False)
            x = 0 if is_open else -W
            self.sidebar.setGeometry(x, 0, W, h)
            # Shadow widget — справа от sidebar, та же высота
            if hasattr(self, '_sb_shadow_widget'):
                sw = self._sb_shadow_widget
                sw.setGeometry(x + W, 0, 22, h)

        # ✅ Dim overlay — всегда занимает весь main_container
        if hasattr(self, '_dim_overlay') and hasattr(self, 'main_container'):
            if self._dim_overlay.isVisible():
                self._dim_overlay.setGeometry(self.main_container.rect())

        # ✅ Если меню не открыто — гарантируем что кнопка «+» видима
        # (защита от случая когда graphicsEffect остался с opacity=0 после ресайза)
        if not getattr(self, '_menu_is_open', False):
            if hasattr(self, 'attach_btn'):
                self.attach_btn.setGraphicsEffect(None)
    
    # position_input_elements() удалён - footer теперь в layout
    
    def apply_styles(self, theme: str = "light", liquid_glass: bool = True):
        """
        Применить стили с поддержкой тем и liquid glass.
        
        Параметры:
        - theme: "light" или "dark"
        - liquid_glass: True/False - включить/выключить стеклянные эффекты
        """
        
        print(f"[APPLY_STYLES] Применение стилей: theme={theme}, liquid_glass={liquid_glass}")
        
        # Обновляем иконку меню в зависимости от темы
        if hasattr(self, 'menu_btn'):
            menu_icon = create_menu_icon(theme=theme)
            self.menu_btn.setIcon(QtGui.QIcon(menu_icon))
            self.menu_btn.setIconSize(QtCore.QSize(50, 50))
        
        # ═══════════════════════════════════════════════════════════
        # ЦВЕТОВЫЕ ПАЛИТРЫ - 4 ВАРИАНТА
        # ═══════════════════════════════════════════════════════════
        
        if theme == "dark":
            if liquid_glass:
                # ТЁМНАЯ ТЕМА + СТЕКЛО - тёмное стекло, НЕ светлое
                colors = {
                    "main_bg": "#1e1e21",  # Тёмный фон
                    "central_bg": "rgba(30, 30, 35, 0.70)",  # Тёмное полупрозрачное стекло
                    "sidebar_bg": "rgba(22, 22, 27, 0.93)",  # Тёмное стекло для sidebar
                    
                    "central_border": "rgba(50, 50, 55, 0.4)",  # Мягкие тёмные границы
                    "sidebar_border": "rgba(50, 50, 55, 0.12)",
                    
                    "text_primary": "#e6e6e6",  # Светлый текст для читаемости
                    "text_secondary": "#b0b0b0",
                    "text_tertiary": "#808080",
                    
                    "btn_bg": "rgba(45, 45, 50, 0.55)",  # Тёмные полупрозрачные кнопки
                    "btn_bg_hover": "rgba(55, 55, 60, 0.65)",
                    "btn_border": "rgb(60, 60, 65)",
                    
                    "input_bg_start": "rgba(38, 38, 44, 0.58)",  # Тёмные инпуты
                    "input_bg_end": "rgba(38, 38, 44, 0.58)",
                    "input_btn_bg": "rgba(30, 30, 35, 0.70)",    # Фон кнопок — одинаковый с шапкой
                    "input_btn_bg_hover": "rgba(50, 50, 58, 0.80)",
                    "input_border": "rgb(55, 55, 62)",
                    "input_focus_border": "rgb(95, 62, 168)",
                    
                    "accent_primary": "rgba(139, 92, 246, 0.3)",  # Фиолетовый акцент
                    "accent_hover": "rgb(124, 77, 236)",
                    
                    "title_bg": "rgba(30, 30, 35, 0.70)",
                    "title_border": "rgb(50, 50, 55)",
                    
                    # Мягкая красная кнопка очистки для тёмной темы
                    "clear_btn_bg": "rgba(220, 85, 85, 0.15)",
                    "clear_btn_hover": "rgba(220, 85, 85, 0.25)",
                    "clear_btn_pressed": "rgba(220, 85, 85, 0.35)",
                    "clear_btn_text": "#e89999",
                    "clear_btn_text_hover": "#f0aaaa",
                    "clear_btn_border": "rgba(220, 85, 85, 0.3)",
                    "clear_btn_border_hover": "rgba(220, 85, 85, 0.45)",
                }
            else:
                # ТЁМНАЯ ТЕМА БЕЗ СТЕКЛА - матовый тёмный интерфейс
                colors = {
                    "main_bg": "#1e1e21",
                    "central_bg": "rgb(32, 32, 36)",  # НЕПРОЗРАЧНЫЙ тёмно-серый
                    "sidebar_bg": "rgb(28, 28, 31)",  # НЕПРОЗРАЧНЫЙ
                    
                    "central_border": "rgba(55, 55, 60, 0.9)",  # Чёткие границы
                    "sidebar_border": "rgba(55, 55, 60, 0.18)",
                    
                    "text_primary": "#f0f0f0",  # Очень светлый текст для контраста
                    "text_secondary": "#c0c0c0",
                    "text_tertiary": "#909090",
                    
                    "btn_bg": "rgb(48, 48, 52)",  # НЕПРОЗРАЧНЫЕ кнопки
                    "btn_bg_hover": "rgb(58, 58, 62)",
                    "btn_border": "rgb(68, 68, 72)",
                    
                    "input_bg_start": "rgba(42, 42, 46, 0.72)",
                    "input_bg_end": "rgba(42, 42, 46, 0.72)",
                    "input_btn_bg": "rgba(32, 32, 36, 0.90)",
                    "input_btn_bg_hover": "rgba(50, 50, 56, 0.95)",
                    "input_border": "rgb(58, 58, 62)",
                    "input_focus_border": "rgb(95, 62, 168)",
                    
                    "accent_primary": "rgba(139, 92, 246, 0.45)",
                    "accent_hover": "rgb(124, 77, 236)",
                    
                    "title_bg": "rgb(32, 32, 36)",
                    "title_border": "rgba(55, 55, 60, 0.9)",
                    
                    # Мягкая красная кнопка очистки для тёмной темы
                    "clear_btn_bg": "rgba(220, 85, 85, 0.15)",
                    "clear_btn_hover": "rgba(220, 85, 85, 0.25)",
                    "clear_btn_pressed": "rgba(220, 85, 85, 0.35)",
                    "clear_btn_text": "#e89999",
                    "clear_btn_text_hover": "#f0aaaa",
                    "clear_btn_border": "rgba(220, 85, 85, 0.3)",
                    "clear_btn_border_hover": "rgba(220, 85, 85, 0.45)",
                }
        else:
            # СВЕТЛАЯ ТЕМА
            if liquid_glass:
                # СВЕТЛАЯ ТЕМА + СТЕКЛО - классический Liquid Glass
                colors = {
                    "main_bg": "#a1a1aa",
                    "central_bg": "rgba(255, 255, 255, 0.55)",
                    "sidebar_bg": "rgba(228, 229, 236, 0.93)",
                    
                    "central_border": "rgba(255, 255, 255, 0.72)",
                    "sidebar_border": "rgba(0, 0, 0, 0.08)",
                    
                    "text_primary": "#222222",  # Тёмный текст для контраста
                    "text_secondary": "#3a3a3a",
                    "text_tertiary": "#5a5a5a",
                    
                    "btn_bg": "rgba(255, 255, 255, 0.80)",
                    "btn_bg_hover": "rgba(255, 255, 255, 0.78)",
                    "btn_border": "rgba(255, 255, 255, 0.70)",
                    
                    "input_bg_start": "rgba(248, 248, 250, 0.70)",
                    "input_bg_end": "rgba(242, 242, 245, 0.70)",
                    "input_btn_bg": "rgba(255, 255, 255, 0.55)",
                    "input_btn_bg_hover": "rgba(255, 255, 255, 0.72)",
                    "input_border": "rgb(210, 210, 220)",
                    "input_focus_border": "rgb(72, 94, 185)",
                    
                    "accent_primary": "rgba(102, 126, 234, 0.18)",
                    "accent_hover": "rgb(82, 106, 214)",
                    
                    "title_bg": "rgba(255, 255, 255, 0.55)",
                    "title_border": "rgb(210, 215, 225)",
                    
                    # Мягкая красная кнопка очистки для светлой темы
                    "clear_btn_bg": "rgba(220, 85, 85, 0.08)",
                    "clear_btn_hover": "rgba(220, 85, 85, 0.15)",
                    "clear_btn_pressed": "rgba(220, 85, 85, 0.22)",
                    "clear_btn_text": "#c85555",
                    "clear_btn_text_hover": "#b84444",
                    "clear_btn_border": "rgba(220, 85, 85, 0.2)",
                    "clear_btn_border_hover": "rgba(220, 85, 85, 0.35)",
                }
            else:
                # СВЕТЛАЯ ТЕМА БЕЗ СТЕКЛА - плоский iOS-like
                colors = {
                    "main_bg": "#d4d4d8",  # Светло-серый фон
                    "central_bg": "rgb(252, 252, 254)",  # НЕПРОЗРАЧНЫЙ белый
                    "sidebar_bg": "rgb(246, 246, 248)",  # НЕПРОЗРАЧНЫЙ светло-серый
                    
                    "central_border": "rgba(210, 210, 215, 0.95)",
                    "sidebar_border": "rgba(210, 210, 215, 0.20)",
                    
                    "text_primary": "#1a1a1a",  # Очень тёмный текст
                    "text_secondary": "#2a2a2a",
                    "text_tertiary": "#4a4a4a",
                    
                    "btn_bg": "rgb(242, 242, 245)",  # НЕПРОЗРАЧНЫЕ кнопки
                    "btn_bg_hover": "rgb(235, 235, 240)",
                    "btn_border": "rgb(210, 210, 215)",
                    
                    "input_bg_start": "rgba(248, 248, 250, 0.75)",
                    "input_bg_end": "rgba(242, 242, 245, 0.75)",
                    "input_btn_bg": "rgba(252, 252, 254, 0.90)",
                    "input_btn_bg_hover": "rgba(240, 240, 245, 0.95)",
                    "input_border": "rgb(210, 210, 215)",
                    "input_focus_border": "rgb(72, 94, 185)",
                    
                    "accent_primary": "rgba(102, 126, 234, 0.25)",
                    "accent_hover": "rgb(82, 106, 214)",
                    
                    "title_bg": "rgb(252, 252, 254)",
                    "title_border": "rgb(210, 210, 215)",
                    
                    # Мягкая красная кнопка очистки для светлой темы
                    "clear_btn_bg": "rgba(220, 85, 85, 0.08)",
                    "clear_btn_hover": "rgba(220, 85, 85, 0.15)",
                    "clear_btn_pressed": "rgba(220, 85, 85, 0.22)",
                    "clear_btn_text": "#c85555",
                    "clear_btn_text_hover": "#b84444",
                    "clear_btn_border": "rgba(220, 85, 85, 0.2)",
                    "clear_btn_border_hover": "rgba(220, 85, 85, 0.35)",
                }
        
        style = f"""
        /* ═══════════════════════════════════════════════
           GLOBAL — убираем focus ring у всех кнопок
           ═══════════════════════════════════════════════ */
        QPushButton {{
            outline: none;
        }}
        QPushButton:focus {{
            outline: none;
        }}
        QToolButton {{
            outline: none;
        }}
        QToolButton:focus {{
            outline: none;
        }}

        /* ═══════════════════════════════════════════════
           BASE — основной фон
           ═══════════════════════════════════════════════ */
        QMainWindow {{
            background: {colors["main_bg"]};
        }}

        /* ═══════════════════════════════════════════════
           CENTRAL PANEL — основная панель
           ═══════════════════════════════════════════════ */
        #central {{
            background: {colors["central_bg"]};
            border-radius: 0px;
        }}

        /* ═══════════════════════════════════════════════
           SIDEBAR — боковая панель
           ═══════════════════════════════════════════════ */
        #sidebar {{
            background: {colors["sidebar_bg"]};
            border-right: 1px solid {colors["sidebar_border"]};
            border-radius: 0px;
        }}
        /* Тень sidebar — отдельный виджет не нужен, имитируем через border */

        /* ── New-chat button ── */
        #newChatBtn {{
            background: {colors["btn_bg"]};
            color: {colors["text_secondary"]};
            border: 1.5px solid {colors["btn_border"]};
            border-radius: 14px;
            padding: 18px 20px;
            margin: 12px 10px;
            font-size: 16px;
            font-weight: 700;
            text-align: left;
        }}
        #newChatBtn:hover {{
            background: {colors["btn_bg_hover"]};
            border: 1.5px solid {colors["accent_hover"]};
        }}

        /* ── Chat list ── */
        #chatsList {{
            background: transparent;
            border: none;
            outline: none;
            padding: 4px 6px;
        }}
        #chatsList::item {{
            padding: 10px 12px;
            margin: 1px 0px;
            border-radius: 10px;
            border: none;
            color: {colors["text_secondary"]};
            font-size: 13px;
            font-weight: 500;
        }}
        #chatsList::item:hover {{
            background: {colors["btn_bg"]};
            color: {colors["text_primary"]};
        }}
        #chatsList::item:selected {{
            background: {colors["accent_primary"]};
            color: {colors["text_primary"]};
            font-weight: 600;
            border-left: 3px solid {colors["accent_hover"]};
            padding-left: 9px;
        }}

        /* ── Settings button ── */
        #settingsBtn {{
            background: {colors["btn_bg"]};
            color: {colors["text_secondary"]};
            border: 1.5px solid {colors["btn_border"]};
            border-radius: 14px;
            padding: 18px 20px;
            margin: 12px 10px;
            font-size: 16px;
            font-weight: 700;
            text-align: left;
        }}
        #settingsBtn:hover {{
            background: {colors["btn_bg_hover"]};
            border: 1.5px solid {colors["accent_hover"]};
        }}


        /* ── Delete panel ── */
        #deletePanel {{
            background: {colors["sidebar_bg"]};
            border-left: 1px solid {colors["sidebar_border"]};
            padding: 15px;
        }}
        #deleteChatBtn {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(239, 68, 68, 0.75),
                stop:1 rgba(220, 38, 38, 0.85));
            color: white;
            border: none;
            border-radius: 12px;
            padding: 14px 20px;
            font-size: 14px;
            font-weight: 700;
        }}
        #deleteChatBtn:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(239, 68, 68, 0.90),
                stop:1 rgba(185, 28, 28, 0.95));
        }}
        #deleteChatBtn:pressed {{
            background: rgba(185, 28, 28, 0.95);
        }}

        /* ═══════════════════════════════════════════════
           TITLE BAR
           ═══════════════════════════════════════════════ */
        #menuBtn {{
            background: transparent;
            color: {colors["text_secondary"]};
            border: none;
            border-radius: 12px;
            padding: 0px;
            margin: 0px;
            min-width: 50px;
            max-width: 50px;
            min-height: 50px;
            max-height: 50px;
        }}
        #menuBtn:hover {{
            background: {colors["btn_bg"]};
            border-radius: 12px;
            margin: 6px;
        }}
        #menuBtn:pressed {{
            background: {colors["btn_bg_hover"]};
            border-radius: 12px;
            margin: 6px;
        }}

        #titleWidget {{
            background: {colors["title_bg"]};
            border: 1.5px solid {colors["title_border"]};
            border-radius: 18px;
            margin: 10px 15px;
            padding-top: 12px;
            padding-bottom: 12px;
        }}
        #titleLabel {{
            color: {colors["text_secondary"]};
            font-size: 22px;
            font-weight: 700;
            padding: 5px;
        }}

        #clearBtn {{
            background: {colors["clear_btn_bg"]};
            color: {colors["clear_btn_text"]};
            border: 1px solid {colors["clear_btn_border"]};
            border-radius: 12px;
            font-size: 12px;
            font-weight: 700;
            padding: 6px 10px;
            max-width: 105px;
            min-width: 95px;
        }}
        #clearBtn:hover {{
            background: {colors["clear_btn_hover"]};
            border: 1px solid {colors["clear_btn_border_hover"]};
            color: {colors["clear_btn_text_hover"]};
        }}
        #clearBtn:pressed {{
            background: {colors["clear_btn_pressed"]};
            color: {colors["clear_btn_text_hover"]};
        }}

        #settingsHeaderBtn {{
            background: transparent;
            border: none;
            border-radius: 12px;
            padding: 4px;
            font-size: 18px;
        }}
        #settingsHeaderBtn:hover {{
            background: {colors["clear_btn_hover"]};
            border: 1px solid {colors["clear_btn_border"]};
        }}
        #settingsHeaderBtn:pressed {{
            background: {colors["clear_btn_pressed"]};
        }}

        /* ═══════════════════════════════════════════════
           CHAT SCROLL AREA
           ═══════════════════════════════════════════════ */
        #chatContainer {{ background: transparent; }}

        QScrollArea            {{ background: transparent; border: none; }}
        QScrollArea > QWidget  {{ background: transparent; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}

        QScrollBar:vertical {{
            background: transparent;
            width: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: transparent;
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: transparent;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{ height: 0px; }}

        /* ── Input field (wrapper) ── */
        #inputField {{
            background: {colors["input_btn_bg"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
        }}
        #inputField:focus-within {{
            border: 1.5px solid {colors["input_focus_border"]};
            background: {colors["input_btn_bg_hover"]};
        }}
        #inputFieldInner {{
            background: transparent;
            color: {colors["text_primary"]};
            border: none;
            border-radius: 0px;
            padding: 0px 5px;
            font-size: 16px;
        }}
        #inputFieldInner:focus {{
            border: none;
            outline: none;
        }}
        #inputFieldInner::placeholder {{
            color: {colors["text_tertiary"]};
        }}

        /* ── Attach button ── */
        #attachBtn {{
            background: {colors["input_btn_bg"]};
            color: {colors["text_tertiary"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 28px;
            font-weight: bold;
            text-align: center;
            padding: 0px;
            line-height: 60px;
            outline: none;
        }}
        #attachBtn:hover {{
            background: {colors["input_btn_bg_hover"]};
            border: 1.5px solid {colors["input_focus_border"]};
            outline: none;
        }}
        #attachBtn:focus {{
            outline: none;
            border: 1.5px solid {colors["input_border"]};
        }}
        #attachBtn:pressed {{
            background: {colors["accent_primary"]};
            border: 1.5px solid {colors["accent_hover"]};
            outline: none;
        }}

        /* ── Send button ── */
        #sendBtn {{
            background: {colors["input_btn_bg"]};
            color: {colors["text_tertiary"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 26px;
            outline: none;
        }}
        #sendBtn:hover {{
            background: {colors["input_btn_bg_hover"]};
            border: 1.5px solid {colors["input_focus_border"]};
            outline: none;
        }}
        #sendBtn:focus {{
            outline: none;
            border: 1.5px solid {colors["input_border"]};
        }}
        #sendBtn:pressed {{
            background: {colors["accent_primary"]};
            border: 1.5px solid {colors["accent_hover"]};
            outline: none;
        }}
        #sendBtn:disabled {{
            color: {colors["text_tertiary"]};
            border: 1.5px solid {colors["input_border"]};
            outline: none;
        }}
        
        /* ── Mode button ── */
        #modeBtn {{
            background: {colors["input_btn_bg"]};
            color: {colors["text_tertiary"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 12px;
            font-weight: 600;
            text-align: center;
            padding: 0px 10px;
            outline: none;
        }}
        #modeBtn:hover {{
            background: {colors["input_btn_bg_hover"]};
            border: 1.5px solid {colors["input_focus_border"]};
        }}
        #modeBtn:pressed {{
            background: {colors["accent_primary"]};
            border: 1.5px solid {colors["accent_hover"]};
        }}
        #modeBtn:focus {{
            outline: none;
            border: 1.5px solid {colors["input_border"]};
        }}

        /* ── Mic button inline (inside input field) ── */
        #micBtnInline {{
            background: transparent;
            color: {colors["text_tertiary"]};
            border: none;
            border-radius: 22px;
            font-size: 20px;
            outline: none;
        }}
        #micBtnInline:hover {{
            background: {colors["input_btn_bg_hover"]};
            color: {colors["text_secondary"]};
            outline: none;
        }}
        #micBtnInline:checked {{
            background: rgba(220, 50, 50, 0.75);
            color: #ffffff;
            outline: none;
        }}
        #micBtnInline:pressed {{
            background: rgba(200,40,40,0.75);
            color: white;
            outline: none;
        }}
        #micBtnInline:focus {{
            outline: none;
            border: none;
        }}

        /* ── Mic button ── */
        #micBtn {{
            background: {colors["input_btn_bg"]};
            color: {colors["text_secondary"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 20px;
            outline: none;
        }}
        #micBtn:hover {{
            background: {colors["input_btn_bg_hover"]};
            border: 1.5px solid {colors["input_focus_border"]};
            outline: none;
        }}
        #micBtn:focus {{
            outline: none;
            border: 1.5px solid {colors["input_border"]};
        }}
        #micBtn:pressed {{
            background: rgba(200,40,40,0.75);
            border: 1.5px solid rgba(220,60,60,0.9);
            color: white;
            outline: none;
        }}
        #micBtnActive {{
            background: rgba(200,40,40,0.75);
            color: white;
            border: 1.5px solid rgba(220,60,60,0.9);
            border-radius: 30px;
            font-size: 20px;
            outline: none;
        }}
        #micBtnWait {{
            background: rgba(120,90,200,0.6);
            color: white;
            border: 1.5px solid rgba(140,110,220,0.8);
            border-radius: 30px;
            font-size: 20px;
            outline: none;
        }}

        /* ── Mic button ── */
        #micBtn {{
            background: {colors["input_btn_bg"]};
            color: {colors["text_tertiary"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 20px;
            outline: none;
        }}
        #micBtn:hover {{
            background: {colors["input_btn_bg_hover"]};
            border: 1.5px solid {colors["input_focus_border"]};
            outline: none;
        }}
        #micBtn:checked {{
            background: rgba(220, 50, 50, 0.75);
            border: 1.5px solid rgba(255, 80, 80, 0.85);
            color: #ffffff;
            outline: none;
        }}
        #micBtn:pressed {{
            background: {colors["accent_primary"]};
            outline: none;
        }}
        #micBtn:focus {{
            outline: none;
            border: 1.5px solid {colors["input_border"]};
        }}

        /* ── Status label ── */
        #statusLabel {{
            color: {colors["text_tertiary"]};
            padding-left: 5px;
            font-style: italic;
        }}

        """
        self.setStyleSheet(style)

        # Windows: обновляем векторные иконки кнопок с правильным цветом темы
        if IS_WINDOWS and hasattr(self, "send_btn"):
            _icon_color = colors["text_tertiary"]
            if not self.is_generating:
                _set_send_icon(self.send_btn, _icon_color)
            else:
                _set_stop_icon(self.send_btn, _icon_color)
        if IS_WINDOWS and hasattr(self, "scroll_to_bottom_btn"):
            _icon_color = colors["text_tertiary"]
            _set_scroll_down_icon(self.scroll_to_bottom_btn, _icon_color)

        try:
            self.scroll_area.viewport().setStyleSheet("background: transparent;")
            self.messages_widget.setStyleSheet("background: transparent;")
        except Exception:
            pass
        
        # ═══════════════════════════════════════════════════════════════════════
        # ОБНОВЛЕНИЕ СТИЛЕЙ СУЩЕСТВУЮЩИХ ВИДЖЕТОВ СООБЩЕНИЙ
        # ═══════════════════════════════════════════════════════════════════════
        # Когда пользователь переключает тему или liquid_glass,
        # нужно обновить стили всех существующих MessageWidget
        try:
            updated_count = 0
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    # Проверяем что это MessageWidget (у него есть метод update_message_styles)
                    if hasattr(widget, 'update_message_styles'):
                        widget.update_message_styles(theme, liquid_glass)
                        updated_count += 1
            
            if updated_count > 0:
                print(f"[APPLY_STYLES] ✓ Обновлено {updated_count} виджетов сообщений")
        except Exception as e:
            print(f"[APPLY_STYLES] ✗ Ошибка обновления виджетов: {e}")
        
        print(f"[APPLY_STYLES] ✓ Стили применены успешно: theme={theme}, liquid_glass={liquid_glass}")

        # Сбрасываем зависший QGraphicsOpacityEffect на кнопке режима
        if hasattr(self, 'mode_btn'):
            self.mode_btn.setGraphicsEffect(None)

    
    def show_model_info(self):
        """Показать информацию о модели при клике на заголовок"""
        current = get_current_display_name()
        QtWidgets.QMessageBox.information(
            self,
            "Информация о модели",
            f"{current} — локальная модель\n\nРаботает полностью офлайн на вашем компьютере.",
            QtWidgets.QMessageBox.StandardButton.Ok
        )

    def _check_first_launch(self):
        """
        Проверяет первый запуск: если LLaMA 3 не установлена — предлагает скачать.
        Флаг first_launch_done сохраняется ТОЛЬКО после того как пользователь
        согласился. Если нажал «Нет» — при следующем запуске снова предложит.
        """
        # Ollama не запущена — проверять модели бессмысленно, диалог не показываем
        from ollama_manager import is_ollama_running as _oll_running
        if not _oll_running():
            print("[FIRST_LAUNCH] ⏭ Ollama API не отвечает — пропускаем проверку моделей")
            return

        try:
            s = load_settings()
            if s.get("first_launch_done", False):
                # Флаг стоит, но модели нет — сбрасываем
                if not check_model_in_ollama("llama3"):
                    print("[FIRST_LAUNCH] Флаг стоит, но LLaMA 3 не установлена — предлагаем снова.")
                    save_settings({"first_launch_done": False})
                else:
                    print("[FIRST_LAUNCH] ✅ LLaMA 3 установлена, всё хорошо.")
                    return
        except Exception as e:
            log_error("FIRST_LAUNCH_READ", e)

        print("[FIRST_LAUNCH] Первый запуск — проверяем наличие LLaMA 3...")

        if check_model_in_ollama("llama3"):
            print("[FIRST_LAUNCH] ✅ LLaMA 3 уже установлена.")
            self._save_first_launch_flag()
            return

        print("[FIRST_LAUNCH] ⚠️ LLaMA 3 не найдена — показываем диалог скачивания.")

        reply = QtWidgets.QMessageBox.question(
            self,
            "LLaMA 3 не найдена",
            "⚠️ LLaMA 3 не скачана.\n\nЭто основная модель ассистента (~4.7 GB).\nХотите скачать её сейчас?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            dl_dialog = LlamaDownloadDialog(self)
            dl_dialog.show()
            self._save_first_launch_flag()

    # ══════════════════════════════════════════════════════════════════════
    # ГОЛОСОВОЙ ВВОД
    # ══════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # ГОЛОСОВОЙ ВВОД — UI
    # ══════════════════════════════════════════════════════════════════════

    def _toggle_voice(self):
        """Нажатие кнопки микрофона: старт / стоп записи."""
        if self._voice.is_recording:
            self._voice.stop()
        else:
            self._voice.start()

    # ── Сигналы от VoiceRecorder ──────────────────────────────────────────

    def _on_recording_started(self):
        """Запись началась."""
        self._voice_recording = True
        self._mic_smooth_level = 0.0
        self._mic_anim_phase   = 0

        self.mic_btn.setText("⏹")
        self.mic_btn.setChecked(True)
        self.mic_btn.setToolTip("Остановить запись")
        self.input_field.setPlaceholderText("🔴 Говорите… (нажмите ⏹ для остановки)")
        self.input_field.setEnabled(False)

        # Запускаем таймер анимации
        if not hasattr(self, '_mic_anim_timer'):
            self._mic_anim_timer = QtCore.QTimer(self)
            self._mic_anim_timer.setInterval(40)   # 25 fps
            self._mic_anim_timer.timeout.connect(self._mic_anim_tick)
        self._mic_anim_timer.start()

        if hasattr(self, 'status_label'):
            self.status_label.setText("🔴 Запись…")

    def _on_recording_stopped(self):
        """Запись остановлена, начинается транскрипция."""
        self._voice_recording = False
        if hasattr(self, '_mic_anim_timer'):
            self._mic_anim_timer.stop()
        self.level_updated_emit(0.0)

        self.mic_btn.setText("⏳")
        self.mic_btn.setChecked(False)
        self.mic_btn.setToolTip("Распознавание…")
        self.input_field.setPlaceholderText("⏳ Распознаю речь…")
        # Фиолетовый цвет «обработка»
        self._mic_apply_color(120, 80, 200, 0.65)

        if hasattr(self, 'status_label'):
            self.status_label.setText("⏳ Распознавание речи…")

    def _on_transcription_done(self, text: str):
        """Текст готов — вставляем в поле ввода."""
        self.input_field.setEnabled(True)
        current = self.input_field.text().strip()
        self.input_field.setText((current + " " + text).strip() if current else text)
        self.input_field.setFocus()
        self.input_field.setCursorPosition(len(self.input_field.text()))
        self.input_field.setPlaceholderText("Введите сообщение...")
        self._reset_mic_btn()
        if hasattr(self, 'status_label'):
            self.status_label.setText("")
        print(f"[VOICE] Распознано: {text}")

    def _on_voice_error(self, message: str):
        """Ошибка записи или распознавания."""
        self._voice_recording = False
        if hasattr(self, '_mic_anim_timer'):
            self._mic_anim_timer.stop()
        self.input_field.setEnabled(True)
        self.input_field.setPlaceholderText("Введите сообщение...")
        self._reset_mic_btn()
        if hasattr(self, 'status_label'):
            self.status_label.setText(f"⚠️ {message}")
            QtCore.QTimer.singleShot(5000, lambda: (
                self.status_label.setText("") if hasattr(self, 'status_label') else None
            ))
        print(f"[VOICE] Ошибка: {message}")

    def _on_voice_level(self, level: float):
        """Обновляем сглаженный уровень громкости (уже сглажен в VoiceRecorder)."""
        self._mic_smooth_level = level

    def _on_voice_status(self, status: str):
        """Текстовый статус от VoiceRecorder."""
        if hasattr(self, 'status_label'):
            self.status_label.setText(status)
            if status.startswith("✅"):
                QtCore.QTimer.singleShot(3000, lambda: (
                    self.status_label.setText("") if hasattr(self, 'status_label') else None
                ))

    # ── Анимация кнопки ───────────────────────────────────────────────────

    def _mic_anim_tick(self):
        """
        Пульсация кнопки во время записи.
        Сочетает уровень голоса + медленную синусоиду — без дёрганья.
        """
        import math
        self._mic_anim_phase = (getattr(self, '_mic_anim_phase', 0) + 1) % 360
        level = getattr(self, '_mic_smooth_level', 0.0)

        # Тихая пульсация базового ритма + всплески от голоса
        pulse    = 0.5 + 0.5 * math.sin(math.radians(self._mic_anim_phase * 3))
        combined = level * 0.75 + pulse * 0.25

        r = int(185 + 70  * combined)
        g = int(15  + 10  * (1 - combined))
        b = int(15  + 10  * (1 - combined))
        a = 0.62 + 0.38 * combined
        self._mic_apply_color(r, g, b, a)

    def _mic_apply_color(self, r: int, g: int, b: int, a: float):
        """Применяет rgba-цвет к кнопке микрофона."""
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        a = max(0.0, min(1.0, a))
        self.mic_btn.setStyleSheet(
            f"QPushButton {{"
            f" background: rgba({r},{g},{b},{a:.2f});"
            f" border: none; border-radius: 22px;"
            f" font-size: 20px; color: white; outline: none;"
            f"}}"
        )

    def level_updated_emit(self, _level: float):
        """Заглушка для совместимости — уровень сбрасывается в 0."""
        self._mic_smooth_level = 0.0

    def _reset_mic_btn(self):
        """Возвращает кнопку в исходное состояние (тема)."""
        self.mic_btn.setText("🎤")
        self.mic_btn.setChecked(False)
        self.mic_btn.setToolTip("Голосовой ввод")
        self.mic_btn.setStyleSheet("")
        try:
            self.mic_btn.style().unpolish(self.mic_btn)
            self.mic_btn.style().polish(self.mic_btn)
        except Exception:
            pass

    def keyPressEvent(self, event):
        """Пробел во время записи — останавливает запись."""
        if event.key() == QtCore.Qt.Key.Key_Space and self._voice.is_recording:
            self._voice.stop()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        """Перехватываем Escape в поле ввода для остановки записи."""
        if (obj is self.input_field
                and getattr(self, '_voice_recording', False)
                and event.type() == QtCore.QEvent.Type.KeyPress
                and event.key() == QtCore.Qt.Key.Key_Escape):
            self._voice.stop()
            return True
        return super().eventFilter(obj, event)



    def _save_first_launch_flag(self):
        """Сохраняет флаг first_launch_done = True."""
        save_settings({"first_launch_done": True})
        print("[FIRST_LAUNCH] ✅ Флаг first_launch_done сохранён")

    def _load_model_preference(self):
        """Загружает сохранённую модель из файла настроек."""
        try:
            s = load_settings()
            saved_key = s.get("ai_model_key", "llama3")
            # ВАЖНО: проверяем через llama_handler.SUPPORTED_MODELS, а не через
            # локальную копию SUPPORTED_MODELS — она снимается при импорте, до того
            # как qwen/mistral/deepseek-r1 регистрируются в словаре.
            if saved_key in llama_handler.SUPPORTED_MODELS:
                llama_handler.CURRENT_AI_MODEL_KEY = saved_key
                llama_handler.ASSISTANT_NAME = get_current_display_name()
                print(f"[MODEL] Загружена модель из настроек: {llama_handler.ASSISTANT_NAME}")
            else:
                print(f"[MODEL] Неизвестная модель в настройках '{saved_key}' → llama3")
                llama_handler.CURRENT_AI_MODEL_KEY = "llama3"
        except Exception as e:
            log_error("LOAD_MODEL_PREF", e)

    def _save_model_preference(self):
        """Сохраняет выбранную модель в файл настроек."""
        save_settings({"ai_model_key": llama_handler.CURRENT_AI_MODEL_KEY})

    def change_ai_model(self, model_key: str):
        """
        Переключает активную модель.
        Выгружает ВСЕ остальные модели из памяти Ollama (keep_alive=0),
        затем загружает только выбранную.
        """
        if model_key not in SUPPORTED_MODELS:
            print(f"[MODEL] Неизвестная модель: {model_key}")
            return
        if llama_handler.CURRENT_AI_MODEL_KEY == model_key:
            return

        print(f"[MODEL] Смена модели: {llama_handler.CURRENT_AI_MODEL_KEY} → {model_key}")

        # Выгружаем ВСЕ модели кроме новой — синхронно (synchronous=True),
        # чтобы старая модель была полностью выгружена из RAM до загрузки новой.
        # Без этого обе модели одновременно занимают память при переключении.
        unload_all_models(except_key=model_key, synchronous=True)

        llama_handler.CURRENT_AI_MODEL_KEY = model_key
        llama_handler.ASSISTANT_NAME = get_current_display_name()
        self._save_model_preference()
        display = get_current_display_name()
        print(f"[MODEL] ✓ Активная модель: {display} ({get_current_ollama_model()})")
        # Загружаем только новую модель
        warm_up_model(model_key)
        # Показываем красивый тост-баннер о смене модели
        QtCore.QTimer.singleShot(80, lambda: self._show_model_switch_toast(model_key, display))
        # Подготавливаем кастомный вариант модели для Enhanced Subtext (если включён)


    def show_model_selector(self):
        """
        Переработанное меню выбора модели ИИ.
        Полностью адаптируется под тему (dark/light) и liquid_glass.
        Плавное появление (fade + scale) и закрытие.
        """
        is_dark        = self.current_theme == "dark"
        is_glass       = getattr(self, "current_liquid_glass", True)

        # ═══════════════════════════════════════════════════════════════
        # ПАЛИТРА — адаптируется под все 4 комбинации тема × стекло
        # ═══════════════════════════════════════════════════════════════
        if is_dark and is_glass:
            bg_overlay      = "rgba(0, 0, 0, 0.55)"
            bg_card         = "rgba(24, 24, 28, 242)"         # = bg dark+glass
            card_border     = "rgba(90, 90, 130, 0.55)"
            title_col       = "#e8e8f8"
            sub_col         = "rgba(160, 160, 195, 0.75)"
            sep_col         = "rgba(80, 80, 115, 0.35)"
            row_bg          = "rgba(45, 45, 65, 0.70)"
            row_hover       = "rgba(60, 60, 88, 0.85)"
            row_border      = "rgba(70, 70, 105, 0.55)"
            badge_installed = "rgba(50, 200, 120, 0.18)"
            badge_border    = "rgba(50, 200, 120, 0.40)"
            badge_text      = "#52c87a"
            badge_miss_bg   = "rgba(200, 100, 60, 0.15)"
            badge_miss_bdr  = "rgba(200, 100, 60, 0.35)"
            badge_miss_txt  = "#e07a50"
            close_col       = "rgba(140, 140, 180, 0.65)"
            close_hover     = "#c0c0e0"
        elif is_dark and not is_glass:
            bg_overlay      = "rgba(0, 0, 0, 0.60)"
            bg_card         = "rgb(28, 28, 31)"               # = bg dark solid
            card_border     = "rgba(65, 65, 90, 0.90)"
            title_col       = "#e2e2f2"
            sub_col         = "#8888aa"
            sep_col         = "rgba(65, 65, 90, 0.55)"
            row_bg          = "rgb(36, 36, 48)"
            row_hover       = "rgb(48, 48, 64)"
            row_border      = "rgba(62, 62, 88, 0.90)"
            badge_installed = "rgba(50, 200, 120, 0.18)"
            badge_border    = "rgba(50, 200, 120, 0.40)"
            badge_text      = "#52c87a"
            badge_miss_bg   = "rgba(200, 100, 60, 0.15)"
            badge_miss_bdr  = "rgba(200, 100, 60, 0.35)"
            badge_miss_txt  = "#e07a50"
            close_col       = "#66668a"
            close_hover     = "#aaaacc"
        elif not is_dark and is_glass:
            bg_overlay      = "rgba(30, 30, 60, 0.25)"
            bg_card         = "rgba(240, 240, 245, 235)"      # = bg light+glass
            card_border     = "rgba(255, 255, 255, 0.85)"
            title_col       = "#1a1a3a"
            sub_col         = "rgba(80, 90, 140, 0.70)"
            sep_col         = "rgba(180, 185, 220, 0.40)"
            row_bg          = "rgba(255, 255, 255, 0.55)"
            row_hover       = "rgba(240, 242, 255, 0.90)"
            row_border      = "rgba(200, 205, 235, 0.65)"
            badge_installed = "rgba(30, 180, 100, 0.12)"
            badge_border    = "rgba(30, 180, 100, 0.35)"
            badge_text      = "#1aaa60"
            badge_miss_bg   = "rgba(200, 80, 40, 0.10)"
            badge_miss_bdr  = "rgba(200, 80, 40, 0.30)"
            badge_miss_txt  = "#cc5530"
            close_col       = "rgba(100, 110, 170, 0.60)"
            close_hover     = "#3a3a7a"
        else:  # light + matte
            bg_overlay      = "rgba(30, 30, 60, 0.30)"
            bg_card         = "rgb(246, 246, 248)"            # = bg light solid
            card_border     = "rgba(200, 205, 230, 0.95)"
            title_col       = "#1a1a3a"
            sub_col         = "#7788aa"
            sep_col         = "rgba(195, 200, 225, 0.70)"
            row_bg          = "rgb(240, 241, 250)"
            row_hover       = "rgb(228, 230, 248)"
            row_border      = "rgba(200, 205, 232, 0.95)"
            badge_installed = "rgba(30, 180, 100, 0.12)"
            badge_border    = "rgba(30, 180, 100, 0.35)"
            badge_text      = "#1aaa60"
            badge_miss_bg   = "rgba(200, 80, 40, 0.10)"
            badge_miss_bdr  = "rgba(200, 80, 40, 0.30)"
            badge_miss_txt  = "#cc5530"
            close_col       = "#8899bb"
            close_hover     = "#2a2a5a"

        active_grad = "qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #667eea,stop:1 #764ba2)"

        # ═══════════════════════════════════════════════════════════════
        # ДИАЛОГ — полупрозрачный оверлей поверх главного окна
        # ═══════════════════════════════════════════════════════════════
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Выбор модели ИИ")
        dialog.setWindowFlags(
            QtCore.Qt.WindowType.Dialog |
            QtCore.Qt.WindowType.FramelessWindowHint
        )
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)

        # Диалог покрывает всё главное окно (backdrop overlay)
        geo = self.geometry()
        dialog.setFixedSize(geo.width(), geo.height())
        dialog.move(geo.x(), geo.y())

        # Корневой layout — центрирует карточку по всему оверлею
        root_layout = QtWidgets.QVBoxLayout(dialog)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Затемнённый фон (клик по нему закрывает меню)
        dialog.setStyleSheet(f"background: {bg_overlay};")

        # ── КАРТОЧКА ────────────────────────────────────────────────
        card = QtWidgets.QFrame()
        card.setFixedWidth(430)
        card.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        card.setStyleSheet(f"""
            QFrame#modelCard {{
                background: {bg_card};
                border: 1px solid {card_border};
                border-radius: 24px;
            }}
        """)
        card.setObjectName("modelCard")
        root_layout.addWidget(card)

        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(22, 20, 22, 18)
        cl.setSpacing(0)

        # ── Шапка с иконкой и крестиком ─────────────────────────────
        header_row = QtWidgets.QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)

        # Иконка слева (декоративная)
        header_icon = QtWidgets.QLabel("🤖")
        header_icon.setStyleSheet(
            ("background: transparent; border: none; font-family: 'Segoe UI Emoji', 'Apple Color Emoji', sans-serif; font-size: 20px;" if IS_WINDOWS else "background: transparent; border: none; font-size: 20px;")
        )
        header_row.addWidget(header_icon)
        header_row.addStretch()

        # Кнопка закрытия ×
        x_btn = QtWidgets.QPushButton("×")
        x_btn.setFixedSize(28, 28)
        x_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        x_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        x_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {close_col};
                font-size: 20px;
                font-weight: 300;
                padding: 0px;
            }}
            QPushButton:hover {{
                color: {close_hover};
            }}
        """)
        header_row.addWidget(x_btn)
        cl.addLayout(header_row)

        cl.addSpacing(4)

        # ── Заголовок ────────────────────────────────────────────────
        title_lbl = QtWidgets.QLabel("Выбор модели ИИ")
        title_lbl.setStyleSheet(
            f"color: {title_col}; font-size: 19px; font-weight: 700; "
            f"background: transparent; border: none; letter-spacing: -0.3px;"
        )
        cl.addWidget(title_lbl)

        cl.addSpacing(4)

        hint_lbl = QtWidgets.QLabel("Все модели работают локально · без интернета")
        hint_lbl.setStyleSheet(
            f"color: {sub_col}; font-size: 12px; background: transparent; border: none;"
        )
        cl.addWidget(hint_lbl)

        cl.addSpacing(16)

        # ── Разделитель ──────────────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {sep_col}; border: none;")
        cl.addWidget(sep)

        cl.addSpacing(12)

        # ── Функция создания карточки модели ─────────────────────────
        def make_model_card(
            model_logo_key: str, name: str, desc: str,
            tag: str, is_active: bool, is_installed: bool
        ) -> QtWidgets.QPushButton:
            btn = QtWidgets.QPushButton()
            btn.setFixedHeight(74)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

            if is_active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {active_grad};
                        border: none;
                        border-radius: 16px;
                        padding: 0px;
                    }}
                    QPushButton:hover {{
                        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                            stop:0 #7b8ff5,stop:1 #8860b8);
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {row_bg};
                        border: 1px solid {row_border};
                        border-radius: 16px;
                        padding: 0px;
                    }}
                    QPushButton:hover {{
                        background: {row_hover};
                        border: 1px solid rgba(102, 126, 234, 0.50);
                    }}
                """)

            hl = QtWidgets.QHBoxLayout(btn)
            hl.setContentsMargins(16, 0, 16, 0)
            hl.setSpacing(14)

            # ── Иконка модели: PNG-логотип в скруглённом контейнере ───────
            icon_frame = QtWidgets.QWidget()
            icon_frame.setFixedSize(42, 42)
            icon_frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            if is_active:
                icon_frame.setStyleSheet(
                    "background: rgba(255,255,255,0.18); border-radius: 12px; border: none;"
                )
            else:
                if is_dark:
                    icon_frame.setStyleSheet(
                        "background: rgba(255,255,255,0.07); border-radius: 12px; border: none;"
                    )
                else:
                    icon_frame.setStyleSheet(
                        "background: rgba(102,126,234,0.10); border-radius: 12px; border: none;"
                    )

            icon_inner = QtWidgets.QVBoxLayout(icon_frame)
            icon_inner.setContentsMargins(5, 5, 5, 5)
            icon_inner.setSpacing(0)

            icon_lbl = QtWidgets.QLabel()
            icon_lbl.setFixedSize(32, 32)
            icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            icon_lbl.setStyleSheet("background: transparent; border: none;")

            # Загружаем логотип модели (сначала файл, потом base64)
            _px = _get_model_logo_pixmap(model_logo_key, size=30)
            if not _px.isNull():
                icon_lbl.setPixmap(_px)
            else:
                # Fallback: первая буква модели
                icon_lbl.setText(name[0].upper())
                icon_lbl.setStyleSheet(
                    f"background: transparent; border: none; "
                    f"font-size: 18px; font-weight: 700; "
                    f"color: {'#ffffff' if is_active else title_col};"
                )

            icon_inner.addWidget(icon_lbl, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
            hl.addWidget(icon_frame)

            # Текстовый блок
            vl = QtWidgets.QVBoxLayout()
            vl.setSpacing(3)
            vl.setContentsMargins(0, 0, 0, 0)

            name_col   = "#ffffff" if is_active else title_col
            desc_col   = "rgba(255,255,255,0.68)" if is_active else sub_col

            name_lbl = QtWidgets.QLabel(name)
            name_lbl.setStyleSheet(
                f"color: {name_col}; font-size: 15px; font-weight: 700; "
                f"background: transparent; border: none;"
            )
            name_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            vl.addWidget(name_lbl)

            desc_lbl = QtWidgets.QLabel(desc)
            desc_lbl.setStyleSheet(
                f"color: {desc_col}; font-size: 11px; "
                f"background: transparent; border: none;"
            )
            desc_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            vl.addWidget(desc_lbl)

            hl.addLayout(vl)
            hl.addStretch()

            # Правая зона: бейдж статуса + чекмарк
            right_vl = QtWidgets.QVBoxLayout()
            right_vl.setSpacing(4)
            right_vl.setContentsMargins(0, 0, 0, 0)
            right_vl.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight)

            # Бейдж «Установлена» / «Не скачана»
            badge = QtWidgets.QLabel("✓ Установлена" if is_installed else "↓ Не скачана")
            if is_active:
                badge.setStyleSheet(
                    "background: rgba(255,255,255,0.20); border-radius: 6px; "
                    "color: rgba(255,255,255,0.85); font-size: 10px; font-weight: 600; "
                    "padding: 2px 7px; border: none;"
                )
            elif is_installed:
                badge.setStyleSheet(
                    f"background: {badge_installed}; border: 1px solid {badge_border}; "
                    f"border-radius: 6px; color: {badge_text}; "
                    f"font-size: 10px; font-weight: 600; padding: 2px 7px;"
                )
            else:
                badge.setStyleSheet(
                    f"background: {badge_miss_bg}; border: 1px solid {badge_miss_bdr}; "
                    f"border-radius: 6px; color: {badge_miss_txt}; "
                    f"font-size: 10px; font-weight: 600; padding: 2px 7px;"
                )
            badge.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            right_vl.addWidget(badge, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

            # Чекмарк активной модели
            if is_active:
                check = QtWidgets.QLabel("●")
                check.setStyleSheet(
                    "color: rgba(255,255,255,0.90); font-size: 10px; "
                    "background: transparent; border: none;"
                )
                check.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                right_vl.addWidget(check, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

            hl.addLayout(right_vl)
            return btn

        # Проверяем установленность
        llama_installed       = check_model_in_ollama("llama3")
        deepseek_installed    = check_model_in_ollama(DEEPSEEK_MODEL_NAME)
        deepseek_r1_installed = check_model_in_ollama(DEEPSEEK_R1_MODEL_NAME)
        mistral_installed     = check_model_in_ollama(MISTRAL_MODEL_NAME)
        qwen_installed        = check_model_in_ollama(QWEN_MODEL_NAME)

        # ── Кнопка удаления модели ───────────────────────────────────
        def _make_delete_btn(model_key, model_name, ollama_name, is_installed):
            """Красная кнопка 🗑 — видна только если модель установлена."""
            if not is_installed:
                # Невидимый спейсер нужного размера
                ph = QtWidgets.QWidget()
                ph.setFixedSize(36, 74)
                ph.setStyleSheet("background: transparent;")
                return ph

            btn = QtWidgets.QPushButton("🗑")
            btn.setFixedSize(36, 36)
            btn.setToolTip(f"Удалить {model_name} с диска")
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            if is_dark:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(200,60,60,0.12);
                        border: 1px solid rgba(200,70,70,0.30);
                        border-radius: 9px; font-size: 15px;
                        color: rgba(220,90,90,0.70);
                    }
                    QPushButton:hover {
                        background: rgba(200,55,55,0.28);
                        border: 1px solid rgba(220,80,80,0.65);
                        color: #ee5555;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(200,60,60,0.07);
                        border: 1px solid rgba(200,70,70,0.25);
                        border-radius: 9px; font-size: 15px;
                        color: rgba(190,60,60,0.65);
                    }
                    QPushButton:hover {
                        background: rgba(200,55,55,0.18);
                        border: 1px solid rgba(200,60,60,0.55);
                        color: #cc2222;
                    }
                """)

            def _on_delete_clicked():
                reply = QtWidgets.QMessageBox.question(
                    dialog,
                    f"Удалить {model_name}?",
                    f"⚠️ Вы уверены, что хотите удалить {model_name} с диска?\n\n"
                    f"Это освободит ~{'4.7' if model_key == 'llama3' else '4.9' if model_key == 'deepseek-r1' else '4.1' if model_key == 'deepseek' else '22' if model_key == 'qwen' else '7.1'} GB, "
                    f"но потом придётся скачивать заново.",
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.No
                )
                if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                    dialog.accept()
                    self._delete_model(model_key, model_name, ollama_name)

            btn.clicked.connect(_on_delete_clicked)

            # Обёртка для выравнивания по центру строки 74px
            wrap = QtWidgets.QWidget()
            wrap.setFixedSize(40, 74)
            wrap.setStyleSheet("background: transparent;")
            wl = QtWidgets.QVBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignHCenter)
            wl.addWidget(btn)
            return wrap

        # ── Карточки моделей с кнопками удаления ───────────────────
        llama_btn = make_model_card(
            "llama3", "LLaMA 3",
            "Универсальная · быстрая · поддержка поиска",
            "8B", llama_handler.CURRENT_AI_MODEL_KEY == "llama3", llama_installed
        )
        llama_row = QtWidgets.QHBoxLayout()
        llama_row.setContentsMargins(0, 0, 0, 0)
        llama_row.setSpacing(6)
        llama_row.addWidget(llama_btn)
        llama_row.addWidget(_make_delete_btn("llama3", "LLaMA 3", "llama3", llama_installed))
        cl.addLayout(llama_row)
        cl.addSpacing(10)

        # ── Группа DeepSeek (7B + R1) ────────────────────────────────
        # Обёртка-контейнер с общим бордером и подписью
        ds_group = QtWidgets.QFrame()
        ds_group.setObjectName("dsGroup")
        if is_dark:
            ds_group.setStyleSheet("""
                QFrame#dsGroup {
                    background: rgba(255,255,255,0.03);
                    border: 1px solid rgba(255,255,255,0.10);
                    border-radius: 18px;
                }
            """)
        else:
            ds_group.setStyleSheet("""
                QFrame#dsGroup {
                    background: rgba(102,126,234,0.04);
                    border: 1px solid rgba(102,126,234,0.18);
                    border-radius: 18px;
                }
            """)
        ds_group_layout = QtWidgets.QVBoxLayout(ds_group)
        ds_group_layout.setContentsMargins(10, 10, 10, 10)
        ds_group_layout.setSpacing(6)

        # Заголовок группы
        ds_group_label = QtWidgets.QLabel("DeepSeek")
        ds_group_label.setStyleSheet(
            f"color: {sub_col}; font-size: 10px; font-weight: 600; "
            f"letter-spacing: 0.8px; background: transparent; border: none; "
            f"text-transform: uppercase; padding-left: 6px;"
        )
        ds_group_layout.addWidget(ds_group_label)

        deepseek_btn = make_model_card(
            "deepseek", "DeepSeek",
            "Аналитика · математика · код",
            "7B", llama_handler.CURRENT_AI_MODEL_KEY == "deepseek", deepseek_installed
        )
        deepseek_row = QtWidgets.QHBoxLayout()
        deepseek_row.setContentsMargins(0, 0, 0, 0)
        deepseek_row.setSpacing(6)
        deepseek_row.addWidget(deepseek_btn)
        deepseek_row.addWidget(_make_delete_btn("deepseek", "DeepSeek 7B", DEEPSEEK_MODEL_NAME, deepseek_installed))
        ds_group_layout.addLayout(deepseek_row)

        # ── DeepSeek R1 8B ───────────────────────────────────────────
        deepseek_r1_btn = make_model_card(
            "deepseek", "DeepSeek R1",
            "Цепочка рассуждений · R1 · точнее на задачах",
            "8B", llama_handler.CURRENT_AI_MODEL_KEY == "deepseek-r1", deepseek_r1_installed
        )
        deepseek_r1_row = QtWidgets.QHBoxLayout()
        deepseek_r1_row.setContentsMargins(0, 0, 0, 0)
        deepseek_r1_row.setSpacing(6)
        deepseek_r1_row.addWidget(deepseek_r1_btn)
        deepseek_r1_row.addWidget(_make_delete_btn(
            "deepseek-r1", "DeepSeek R1 8B", DEEPSEEK_R1_MODEL_NAME, deepseek_r1_installed))
        ds_group_layout.addLayout(deepseek_r1_row)

        cl.addWidget(ds_group)
        cl.addSpacing(10)

        mistral_btn = make_model_card(
            "mistral", "Mistral Nemo",
            "Многоязычный · гибкий · 12B параметров",
            "12B", llama_handler.CURRENT_AI_MODEL_KEY == "mistral", mistral_installed
        )
        mistral_row = QtWidgets.QHBoxLayout()
        mistral_row.setContentsMargins(0, 0, 0, 0)
        mistral_row.setSpacing(6)
        mistral_row.addWidget(mistral_btn)
        mistral_row.addWidget(_make_delete_btn("mistral", "Mistral Nemo", MISTRAL_MODEL_NAME, mistral_installed))
        cl.addLayout(mistral_row)

        cl.addSpacing(8)  # Отступ между карточками моделей

        qwen_btn = make_model_card(
            "qwen", "Qwen",
            "Быстрая · гибридная · 14B параметров",
            "14B", llama_handler.CURRENT_AI_MODEL_KEY == "qwen", qwen_installed
        )
        qwen_row = QtWidgets.QHBoxLayout()
        qwen_row.setContentsMargins(0, 0, 0, 0)
        qwen_row.setSpacing(6)
        qwen_row.addWidget(qwen_btn)
        qwen_row.addWidget(_make_delete_btn("qwen", "Qwen", QWEN_MODEL_NAME, qwen_installed))
        cl.addLayout(qwen_row)

        cl.addSpacing(16)

        # ── Нижний разделитель ───────────────────────────────────────
        sep2 = QtWidgets.QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {sep_col}; border: none;")
        cl.addWidget(sep2)

        cl.addSpacing(8)

        # ── Кнопка «Дополнительные» ──────────────────────────────────
        extra_btn = QtWidgets.QPushButton("⬇  Дополнительные")
        extra_btn.setFixedHeight(36)
        extra_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        extra_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        extra_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {close_col};
                border: 1px solid {sep_col};
                border-radius: 10px;
                font-size: 13px;
                font-weight: 500;
                padding: 0 18px;
            }}
            QPushButton:hover {{
                color: {close_hover};
                border: 1px solid rgba(102, 126, 234, 0.40);
                background: rgba(102, 126, 234, 0.07);
            }}
        """)
        cl.addWidget(extra_btn, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        cl.addSpacing(8)

        # ── Кнопка «Закрыть» ─────────────────────────────────────────
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.setFixedHeight(36)
        close_btn.setMinimumWidth(110)
        close_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        close_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {close_col};
                border: 1px solid {sep_col};
                border-radius: 10px;
                font-size: 13px;
                font-weight: 500;
                padding: 0 18px;
            }}
            QPushButton:hover {{
                color: {close_hover};
                border: 1px solid rgba(102, 126, 234, 0.40);
                background: rgba(102, 126, 234, 0.07);
            }}
        """)
        cl.addWidget(close_btn, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        # ═══════════════════════════════════════════════════════════════
        # АНИМАЦИЯ ПОЯВЛЕНИЯ: fade + slide-up карточки
        # ═══════════════════════════════════════════════════════════════
        dialog.setWindowOpacity(0.0)
        dialog.show()

        # ── Overlay fade ────────────────────────────────────────────────────
        _fade_overlay = QtCore.QPropertyAnimation(dialog, b"windowOpacity")
        _fade_overlay.setDuration(240)
        _fade_overlay.setStartValue(0.0)
        _fade_overlay.setEndValue(1.0)
        _fade_overlay.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        # ── Карточка: opacity + slide-up ────────────────────────────────────
        card_effect = QtWidgets.QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(card_effect)
        card_effect.setOpacity(0.0)

        _fade_card = QtCore.QPropertyAnimation(card_effect, b"opacity")
        _fade_card.setDuration(300)
        _fade_card.setStartValue(0.0)
        _fade_card.setEndValue(1.0)
        _fade_card.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        # Slide-up: карточка стартует на 32px ниже
        _card_start_pos = card.pos()
        _card_start_low = QtCore.QPoint(_card_start_pos.x(), _card_start_pos.y() + 32)
        card.move(_card_start_low)

        _slide_card = QtCore.QPropertyAnimation(card, b"pos")
        _slide_card.setDuration(340)
        _slide_card.setStartValue(_card_start_low)
        _slide_card.setEndValue(_card_start_pos)
        _slide_card.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        _anim_group_in = QtCore.QParallelAnimationGroup()
        _anim_group_in.addAnimation(_fade_overlay)
        _anim_group_in.addAnimation(_fade_card)
        _anim_group_in.addAnimation(_slide_card)

        def _on_open_done():
            try:
                card.setGraphicsEffect(None)
                card.move(_card_start_pos)
            except RuntimeError:
                pass

        _anim_group_in.finished.connect(_on_open_done)
        dialog._open_anim = _anim_group_in
        dialog._card_start_pos = _card_start_pos
        _anim_group_in.start()

        # ═══════════════════════════════════════════════════════════════
        # ПЛАВНОЕ ЗАКРЫТИЕ: fade-out overlay + карточка
        # ═══════════════════════════════════════════════════════════════
        def _fade_and_close(callback=None):
            # Если анимация открытия ещё идёт — останавливаем
            if dialog._open_anim and dialog._open_anim.state() == QtCore.QAbstractAnimation.State.Running:
                dialog._open_anim.stop()
            card.setGraphicsEffect(None)  # убираем старый эффект если остался

            close_eff = QtWidgets.QGraphicsOpacityEffect(card)
            card.setGraphicsEffect(close_eff)
            close_eff.setOpacity(1.0)

            cur_pos = card.pos()
            _co = QtCore.QPropertyAnimation(close_eff, b"opacity")
            _co.setDuration(200)
            _co.setStartValue(1.0)
            _co.setEndValue(0.0)
            _co.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            _fo = QtCore.QPropertyAnimation(dialog, b"windowOpacity")
            _fo.setDuration(220)
            _fo.setStartValue(dialog.windowOpacity())
            _fo.setEndValue(0.0)
            _fo.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            # Slide-down при закрытии
            _sc = QtCore.QPropertyAnimation(card, b"pos")
            _sc.setDuration(220)
            _sc.setStartValue(cur_pos)
            _sc.setEndValue(QtCore.QPoint(cur_pos.x(), cur_pos.y() + 24))
            _sc.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            _group = QtCore.QParallelAnimationGroup()
            _group.addAnimation(_co)
            _group.addAnimation(_fo)
            _group.addAnimation(_sc)

            def _on_close_done():
                card.setGraphicsEffect(None)
                dialog.accept()
                if callback:
                    callback()

            _group.finished.connect(_on_close_done)
            dialog._close_anim = _group
            _group.start()

        # Клик по затемнённому фону — закрывает
        class _OverlayClickFilter(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                    if obj is dialog:
                        # Клик вне карточки → закрываем
                        cp = event.position().toPoint() if hasattr(event, "position") else event.pos()
                        if not card.geometry().contains(cp):
                            _fade_and_close()
                            return True
                return False

        _click_filter = _OverlayClickFilter(dialog)
        dialog.installEventFilter(_click_filter)
        dialog._click_filter = _click_filter  # держим ссылку

        x_btn.clicked.connect(lambda: _fade_and_close())
        close_btn.clicked.connect(lambda: _fade_and_close())

        # ── Выбор LLaMA ─────────────────────────────────────────────
        def _select_llama():
            def _after():
                if not llama_installed:
                    # LLaMA не скачана — предлагаем скачать
                    reply = QtWidgets.QMessageBox.question(
                        self,
                        "LLaMA 3 не установлена",
                        "⚠️ LLaMA 3 ещё не скачана (~4.7 GB).\n\nХотите скачать её сейчас?\nМожно выбрать диск для сохранения.",
                        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.Yes
                    )
                    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                        dl_dialog = LlamaDownloadDialog(self)
                        dl_dialog.download_finished.connect(
                            lambda ok, msg: (
                                self.change_ai_model("llama3"),
                                self._save_first_launch_flag()
                            ) if ok else None
                        )
                        dl_dialog.show()
                elif llama_handler.CURRENT_AI_MODEL_KEY != "llama3":
                    self.change_ai_model("llama3")
            _fade_and_close(_after)

        # ── Выбор DeepSeek ──────────────────────────────────────────
        def _select_deepseek():
            def _after():
                if llama_handler.CURRENT_AI_MODEL_KEY == "deepseek":
                    return
                if deepseek_installed:
                    self.change_ai_model("deepseek")
                else:
                    reply = QtWidgets.QMessageBox.question(
                        self,
                        "Модель не найдена",
                        "⚠️ DeepSeek не скачан.\n\nХотите скачать его сейчас? (~4.1 GB, несколько минут)",
                        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.Yes
                    )
                    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                        self._start_deepseek_download()
            _fade_and_close(_after)

        # ── Выбор DeepSeek-R1 8B ────────────────────────────────────
        def _select_deepseek_r1():
            def _after():
                if llama_handler.CURRENT_AI_MODEL_KEY == "deepseek-r1":
                    return
                if deepseek_r1_installed:
                    self.change_ai_model("deepseek-r1")
                else:
                    reply = QtWidgets.QMessageBox.question(
                        self,
                        "Модель не найдена",
                        "⚠️ DeepSeek-R1 8B не скачан (~4.9 GB).\n\n"
                        "Это версия с цепочкой рассуждений — отвечает обдуманнее.\n\n"
                        "Хотите скачать её сейчас?",
                        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.Yes
                    )
                    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                        self._start_deepseek_r1_download()
            _fade_and_close(_after)

        # ── Выбор Mistral ───────────────────────────────────────────
        def _select_mistral():
            def _after():
                if llama_handler.CURRENT_AI_MODEL_KEY == "mistral":
                    return
                if mistral_installed:
                    self.change_ai_model("mistral")
                else:
                    reply = QtWidgets.QMessageBox.question(
                        self,
                        "Модель не найдена",
                        "⚠️ Mistral Nemo 12B не скачан (~7.1 GB).\n\n"
                        "Хотите скачать его сейчас?",
                        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.Yes
                    )
                    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                        self._start_mistral_download()
            _fade_and_close(_after)

        def _select_qwen():
            def _after():
                if llama_handler.CURRENT_AI_MODEL_KEY == "qwen":
                    return
                if qwen_installed:
                    self.change_ai_model("qwen")
                else:
                    reply = QtWidgets.QMessageBox.question(
                        self,
                        "Модель не найдена",
                        "⚠️ Qwen 3 не скачана (~9 GB).\n\n"
                        "Мощная модель с 14B параметрами.\n"
                        "Требует ~9 GB дискового пространства.\n\n"
                        "Хотите скачать её сейчас?",
                        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.Yes
                    )
                    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                        self._start_qwen_download()
            _fade_and_close(_after)

        llama_btn.clicked.connect(_select_llama)
        deepseek_btn.clicked.connect(_select_deepseek)
        deepseek_r1_btn.clicked.connect(_select_deepseek_r1)
        mistral_btn.clicked.connect(_select_mistral)
        qwen_btn.clicked.connect(_select_qwen)
        def _open_extra():
            # Закрываем текущий диалог без callback-цепочки,
            # затем открываем новый через QTimer — избегаем двойного exec()
            _fade_and_close()
            QtCore.QTimer.singleShot(260, self._show_extra_models_dialog)
        extra_btn.clicked.connect(_open_extra)

        dialog.exec()

    def _show_extra_models_dialog(self):
        """
        Диалог «Дополнительные» — скачивание специальных моделей:
          - LLaMA 3.2 (Vision)  — для распознавания изображений
          - Whisper (base)       — локальное распознавание голоса
        Модели нельзя выбрать как активную — они вспомогательные.
        Whisper скачивается в ~/.cache/whisper и кэшируется между запусками.
        """
        import os, pathlib

        is_dark  = self.current_theme == "dark"
        is_glass = getattr(self, "current_liquid_glass", True)

        # Палитра — берём те же переменные что в show_model_selector
        if is_dark and is_glass:
            bg_card   = "rgba(28, 28, 38, 0.88)"
            card_border = "rgba(90, 90, 130, 0.55)"
            title_col   = "#e8e8f8"
            sub_col     = "rgba(160, 160, 195, 0.75)"
            sep_col     = "rgba(80, 80, 115, 0.35)"
            close_col   = "rgba(140, 140, 180, 0.65)"
            close_hover = "#c0c0e0"
            bg_overlay  = "rgba(0,0,0,0.55)"
            row_bg      = "rgba(45, 45, 65, 0.70)"
            row_hover   = "rgba(60, 60, 88, 0.85)"
        elif is_dark:
            bg_card     = "rgb(26, 26, 34)"
            card_border = "rgba(65, 65, 90, 0.90)"
            title_col   = "#e2e2f2"; sub_col = "#8888aa"
            sep_col     = "rgba(65, 65, 90, 0.55)"
            close_col   = "#66668a"; close_hover = "#aaaacc"
            bg_overlay  = "rgba(0,0,0,0.60)"
            row_bg      = "rgb(36, 36, 48)"; row_hover = "rgb(48, 48, 64)"
        elif is_glass:
            bg_card     = "rgba(255, 255, 255, 0.78)"
            card_border = "rgba(255, 255, 255, 0.85)"
            title_col   = "#1a1a3a"; sub_col = "rgba(80, 90, 140, 0.70)"
            sep_col     = "rgba(180, 185, 220, 0.40)"
            close_col   = "rgba(100, 110, 170, 0.60)"; close_hover = "#3a3a7a"
            bg_overlay  = "rgba(30, 30, 60, 0.25)"
            row_bg      = "rgba(255, 255, 255, 0.55)"; row_hover = "rgba(240, 242, 255, 0.90)"
        else:
            bg_card     = "rgb(248, 248, 252)"
            card_border = "rgba(200, 205, 230, 0.95)"
            title_col   = "#1a1a3a"; sub_col = "#7788aa"
            sep_col     = "rgba(195, 200, 225, 0.70)"
            close_col   = "#8899bb"; close_hover = "#2a2a5a"
            bg_overlay  = "rgba(30, 30, 60, 0.30)"
            row_bg      = "rgb(240, 241, 250)"; row_hover = "rgb(228, 230, 248)"

        # Проверяем наличие Whisper-модели в кэше
        whisper_cache = pathlib.Path.home() / ".cache" / "whisper"
        whisper_cached = any(whisper_cache.glob("base*")) if whisper_cache.exists() else False

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Дополнительные модели")
        dialog.setWindowFlags(QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.FramelessWindowHint)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        geo = self.geometry()
        dialog.setFixedSize(geo.width(), geo.height())
        dialog.move(geo.x(), geo.y())
        dialog.setStyleSheet(f"background: {bg_overlay};")

        root_layout = QtWidgets.QVBoxLayout(dialog)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        card = QtWidgets.QFrame()
        card.setFixedWidth(440)
        card.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Minimum)
        card.setStyleSheet(f"""
            QFrame#extraCard {{
                background: {bg_card};
                border: 1px solid {card_border};
                border-radius: 24px;
            }}
        """)
        card.setObjectName("extraCard")
        root_layout.addWidget(card)

        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(22, 20, 22, 18)
        cl.setSpacing(0)

        # Шапка
        header_row = QtWidgets.QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        hi = QtWidgets.QLabel("⬇")
        hi.setStyleSheet("background:transparent;border:none;font-size:20px;")
        header_row.addWidget(hi)
        header_row.addStretch()
        x_btn = QtWidgets.QPushButton("×")
        x_btn.setFixedSize(28, 28)
        x_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        x_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        x_btn.setStyleSheet(f"QPushButton{{background:transparent;border:none;color:{close_col};font-size:20px;font-weight:300;}}QPushButton:hover{{color:{close_hover};}}")
        header_row.addWidget(x_btn)
        cl.addLayout(header_row)
        cl.addSpacing(4)

        title_lbl = QtWidgets.QLabel("Дополнительные модели")
        title_lbl.setStyleSheet(f"color:{title_col};font-size:19px;font-weight:700;background:transparent;border:none;letter-spacing:-0.3px;")
        cl.addWidget(title_lbl)
        cl.addSpacing(4)
        hint_lbl = QtWidgets.QLabel("Вспомогательные модели · нельзя выбрать как активную")
        hint_lbl.setStyleSheet(f"color:{sub_col};font-size:12px;background:transparent;border:none;")
        cl.addWidget(hint_lbl)
        cl.addSpacing(16)

        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{sep_col};border:none;")
        cl.addWidget(sep)
        cl.addSpacing(14)

        # ── Вспомогательная функция: строка модели ──────────────────
        def _make_extra_row(icon, name, desc, size_str, is_cached, on_download, on_delete):
            row_widget = QtWidgets.QFrame()
            row_widget.setFixedHeight(72)
            row_widget.setStyleSheet(f"""
                QFrame {{
                    background: {row_bg};
                    border: 1px solid {sep_col};
                    border-radius: 14px;
                }}
                QFrame:hover {{
                    background: {row_hover};
                }}
            """)
            hl = QtWidgets.QHBoxLayout(row_widget)
            hl.setContentsMargins(14, 0, 14, 0)
            hl.setSpacing(12)

            icon_lbl = QtWidgets.QLabel(icon)
            icon_lbl.setFixedSize(36, 36)
            icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setStyleSheet(f"background:{'rgba(255,255,255,0.12)' if is_dark else 'rgba(102,126,234,0.10)'};border-radius:10px;border:none;font-size:18px;")
            icon_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            hl.addWidget(icon_lbl)

            txt = QtWidgets.QVBoxLayout()
            txt.setSpacing(2)
            n_lbl = QtWidgets.QLabel(name)
            n_lbl.setStyleSheet(f"color:{title_col};font-size:14px;font-weight:700;background:transparent;border:none;")
            n_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            txt.addWidget(n_lbl)
            d_lbl = QtWidgets.QLabel(desc)
            d_lbl.setStyleSheet(f"color:{sub_col};font-size:11px;background:transparent;border:none;")
            d_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            txt.addWidget(d_lbl)
            hl.addLayout(txt)
            hl.addStretch()

            # Правая часть: бейдж + кнопка (скачать ИЛИ удалить)
            right = QtWidgets.QVBoxLayout()
            right.setSpacing(4)
            right.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight)

            badge = QtWidgets.QLabel("✓ Скачана" if is_cached else size_str)
            if is_cached:
                badge.setStyleSheet("background:rgba(50,200,120,0.18);border:1px solid rgba(50,200,120,0.40);border-radius:6px;color:#52c87a;font-size:10px;font-weight:600;padding:2px 7px;")
            else:
                badge.setStyleSheet(f"background:rgba(102,126,234,0.12);border:1px solid rgba(102,126,234,0.35);border-radius:6px;color:#667eea;font-size:10px;font-weight:600;padding:2px 7px;")
            badge.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            right.addWidget(badge, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

            if is_cached:
                # Уже скачана — показываем кнопку удаления
                action_btn = QtWidgets.QPushButton("🗑  Удалить")
                action_btn.setFixedHeight(26)
                action_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
                action_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
                action_btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(200,60,60,0.15);
                        color: #ee5555; border: 1px solid rgba(200,70,70,0.40);
                        border-radius: 8px; font-size: 11px; font-weight: 600; padding: 0 12px;
                    }
                    QPushButton:hover {
                        background: rgba(200,55,55,0.30);
                        border: 1px solid rgba(220,80,80,0.65);
                    }
                """)
                action_btn.clicked.connect(on_delete)
            else:
                # Не скачана — показываем кнопку скачивания
                action_btn = QtWidgets.QPushButton("⬇  Скачать")
                action_btn.setFixedHeight(26)
                action_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
                action_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
                action_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #667eea,stop:1 #764ba2);
                        color: white; border: none; border-radius: 8px;
                        font-size: 11px; font-weight: 600; padding: 0 12px;
                    }}
                    QPushButton:hover {{
                        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #7b8ff5,stop:1 #8860b8);
                    }}
                """)
                action_btn.clicked.connect(on_download)

            right.addWidget(action_btn, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
            hl.addLayout(right)
            return row_widget

        # ── LLaMA 3.2 Vision ─────────────────────────────────────────
        llama32_installed = False
        try:
            import requests as _req
            _r = _req.get("http://localhost:11434/api/tags", timeout=1)
            _models = [m.get("name","") for m in _r.json().get("models",[])]
            llama32_installed = any("llama3.2" in m for m in _models)
        except Exception:
            pass

        def _dl_llama32():
            _close2()
            QtCore.QTimer.singleShot(300, self._download_llama32_vision)

        def _del_llama32():
            reply = QtWidgets.QMessageBox.question(
                self, "Удалить LLaMA 3.2 Vision?",
                "Удалить LLaMA 3.2 Vision с диска? Модель займёт ~2.0 GB при повторной скачке.",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                _close2()
                QtCore.QTimer.singleShot(300, lambda: self._delete_ollama_model("llama3.2-vision"))

        cl.addWidget(_make_extra_row("🦙", "LLaMA 3.2 Vision", "Распознавание изображений · ~2.0 GB",
                                     "~2.0 GB", llama32_installed, _dl_llama32, _del_llama32))
        cl.addSpacing(10)

        # ── Whisper base ──────────────────────────────────────────────
        def _dl_whisper():
            _close2()
            QtCore.QTimer.singleShot(300, self._download_whisper_model)

        def _del_whisper():
            reply = QtWidgets.QMessageBox.question(
                self, "Удалить Whisper base?",
                "Удалить модель Whisper base (~150 MB) из кэша? Папка: ~/.cache/whisper",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                _close2()
                QtCore.QTimer.singleShot(300, self._delete_whisper_model)

        cl.addWidget(_make_extra_row("🎤", "Whisper base", "Локальное распознавание голоса · офлайн · ~150 MB",
                                     "~150 MB", whisper_cached, _dl_whisper, _del_whisper))

        cl.addSpacing(16)
        sep2 = QtWidgets.QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background:{sep_col};border:none;")
        cl.addWidget(sep2)
        cl.addSpacing(10)

        close2_btn = QtWidgets.QPushButton("Закрыть")
        close2_btn.setFixedHeight(36)
        close2_btn.setMinimumWidth(110)
        close2_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        close2_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        close2_btn.setStyleSheet(f"""
            QPushButton{{background:transparent;color:{close_col};border:1px solid {sep_col};border-radius:10px;font-size:13px;font-weight:500;padding:0 18px;}}
            QPushButton:hover{{color:{close_hover};border:1px solid rgba(102,126,234,0.40);background:rgba(102,126,234,0.07);}}
        """)
        cl.addWidget(close2_btn, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        # Fade-in
        dialog.setWindowOpacity(0.0)
        dialog.show()
        _fo2 = QtCore.QPropertyAnimation(dialog, b"windowOpacity")
        _fo2.setDuration(220); _fo2.setStartValue(0.0); _fo2.setEndValue(1.0)
        _fo2.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        dialog._open_anim2 = _fo2
        _fo2.start()

        def _close2():
            _fc = QtCore.QPropertyAnimation(dialog, b"windowOpacity")
            _fc.setDuration(180); _fc.setStartValue(1.0); _fc.setEndValue(0.0)
            _fc.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
            def _do_close():
                try:
                    dialog.close()
                    self._extra_models_dialog = None
                except Exception:
                    pass
            _fc.finished.connect(_do_close)
            dialog._close_anim2 = _fc
            _fc.start()

        x_btn.clicked.connect(_close2)
        close2_btn.clicked.connect(_close2)

        class _OvFilter2(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() == QtCore.QEvent.Type.MouseButtonPress and obj is dialog:
                    cp = event.position().toPoint() if hasattr(event, "position") else event.pos()
                    if not card.geometry().contains(cp):
                        _close2()
                        return True
                return False
        _cf2 = _OvFilter2(dialog)
        dialog.installEventFilter(_cf2)
        dialog._click_filter2 = _cf2
        # Используем show() вместо exec() — не блокируем event loop
        # Храним ссылку чтобы GC не удалил диалог
        self._extra_models_dialog = dialog
        dialog.show()

    def _download_llama32_vision(self):
        """Скачивает LLaMA 3.2 Vision через ollama pull."""
        import subprocess, threading
        def _pull():
            try:
                subprocess.run(["ollama", "pull", "llama3.2-vision"], check=True)
                QtCore.QMetaObject.invokeMethod(
                    self, "_on_llama32_downloaded", QtCore.Qt.ConnectionType.QueuedConnection
                )
            except Exception as e:
                print(f"[LLAMA32] Ошибка: {e}")
        threading.Thread(target=_pull, daemon=True).start()
        self.status_label.setText("⏬ Скачиваю LLaMA 3.2 Vision…")

    def _delete_ollama_model(self, model_name: str):
        """Удаляет модель из Ollama через ollama rm."""
        import subprocess, threading
        def _rm():
            try:
                subprocess.run(["ollama", "rm", model_name], check=True)
                QtCore.QMetaObject.invokeMethod(
                    self.status_label, "setText",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, f"✅ {model_name} удалена")
                )
                QtCore.QTimer.singleShot(3000, lambda: self.status_label.setText(""))
            except Exception as e:
                print(f"[DELETE_MODEL] Ошибка: {e}")
        threading.Thread(target=_rm, daemon=True).start()
        self.status_label.setText(f"🗑 Удаляю {model_name}…")

    def _delete_whisper_model(self):
        """Удаляет кэш Whisper base из ~/.cache/whisper."""
        import pathlib, shutil
        whisper_cache = pathlib.Path.home() / ".cache" / "whisper"
        deleted = []
        if whisper_cache.exists():
            for f in whisper_cache.glob("base*"):
                try:
                    f.unlink()
                    deleted.append(f.name)
                except Exception as e:
                    print(f"[DELETE_WHISPER] {e}")
        # Сбрасываем кэш модели в памяти
        # Сбрасываем кэш модели в памяти
        VoiceRecorder._whisper_model_cache = None
        VoiceRecorder._whisper_model_cache = None
        if deleted:
            self.status_label.setText(f"✅ Whisper удалён: {', '.join(deleted)}")
        else:
            self.status_label.setText("⚠️ Файлы Whisper не найдены")
        QtCore.QTimer.singleShot(3000, lambda: self.status_label.setText(""))

    @QtCore.pyqtSlot()
    def _on_llama32_downloaded(self):
        self.status_label.setText("✅ LLaMA 3.2 Vision скачана")
        QtCore.QTimer.singleShot(4000, lambda: self.status_label.setText(""))

    def _download_whisper_model(self):
        """Скачивает модель Whisper base с прогрессом."""
        self._whisper_dl_dialog = WhisperDownloadDialog(self)
        self._whisper_dl_dialog.show()

    def _start_deepseek_download(self):
        """Открывает диалог скачивания DeepSeek и после успеха активирует модель."""
        dl_dialog = DeepSeekDownloadDialog(self)
        dl_dialog.download_finished.connect(
            lambda success, msg: self._on_deepseek_downloaded(success, msg)
        )
        dl_dialog.show()

    def _on_deepseek_downloaded(self, success: bool, message: str):
        """Вызывается после завершения скачивания DeepSeek."""
        if success:
            self.change_ai_model("deepseek")
        else:
            print(f"[MODEL] Скачивание DeepSeek не удалось: {message}")

    def _start_deepseek_r1_download(self):
        """Открывает диалог скачивания DeepSeek-R1 8B и после успеха активирует модель."""
        dl_dialog = DeepSeekR1DownloadDialog(self)
        dl_dialog.download_finished.connect(
            lambda success, msg: self._on_deepseek_r1_downloaded(success, msg)
        )
        dl_dialog.show()

    def _on_deepseek_r1_downloaded(self, success: bool, message: str):
        """Вызывается после завершения скачивания DeepSeek-R1 8B."""
        if success:
            self.change_ai_model("deepseek-r1")
        else:
            print(f"[MODEL] Скачивание DeepSeek-R1 не удалось: {message}")

    def _start_mistral_download(self):
        """Открывает диалог скачивания Mistral Nemo и после успеха активирует модель."""
        dl_dialog = MistralDownloadDialog(self)
        dl_dialog.download_finished.connect(
            lambda success, msg: self._on_mistral_downloaded(success, msg)
        )
        dl_dialog.show()

    def _on_mistral_downloaded(self, success: bool, message: str):
        """Вызывается после завершения скачивания Mistral Nemo."""
        if success:
            self.change_ai_model("mistral")
        else:
            print(f"[MODEL] Скачивание Mistral Nemo не удалось: {message}")

    def _start_qwen_download(self):
        """Открывает диалог скачивания Qwen 3 и после успеха активирует модель."""
        from model_downloader import QwenDownloadDialog
        # ВАЖНО: сохраняем как self._qwen_dl_dialog, иначе Python сразу
        # уничтожает локальную переменную и окно закрывается мгновенно.
        self._qwen_dl_dialog = QwenDownloadDialog(self)
        self._qwen_dl_dialog.download_finished.connect(
            lambda success, msg: self._on_qwen_downloaded(success, msg)
        )
        self._qwen_dl_dialog.show()

    def _on_qwen_downloaded(self, success: bool, message: str):
        """Вызывается после завершения скачивания Qwen 3."""
        if success:
            self.change_ai_model("qwen")
        else:
            print(f"[MODEL] Скачивание Qwen не удалось: {message}")

    def _start_model_download(self, model_key: str):
        """
        Универсальный метод запуска скачивания модели по ключу.
        Используется из меню перегенерации.
        """
        if model_key == "llama3":
            dl = LlamaDownloadDialog(self)
            dl.download_finished.connect(
                lambda ok, msg: self.change_ai_model("llama3") if ok else None
            )
            dl.show()
        elif model_key == "deepseek":
            self._start_deepseek_download()
        elif model_key == "deepseek-r1":
            self._start_deepseek_r1_download()
        elif model_key == "mistral":
            self._start_mistral_download()
        elif model_key == "qwen":
            self._start_qwen_download()

    # ─────────────────────────────────────────────────────────────────
    def _delete_model(self, model_key: str, model_name: str, ollama_name: str):
        """
        Удаляет модель ФИЗИЧЕСКИ С ДИСКА:
          1. Находит реальную папку с файлами Ollama
          2. Запускает «ollama rm» (удаляет из реестра)
          3. Дополнительно вручную удаляет manifest и blob-файлы
        """
        print(f"[DELETE] Удаляем {model_name} (ollama: {ollama_name}) …")

        prog = QtWidgets.QProgressDialog(
            f"Удаление {model_name}…", None, 0, 0, self
        )
        prog.setWindowTitle("Удаление модели")
        prog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        if IS_WINDOWS:
            prog.setWindowFlags(
                QtCore.Qt.WindowType.Dialog |
                QtCore.Qt.WindowType.WindowTitleHint
            )
        prog.show()
        QtWidgets.QApplication.processEvents()

        err = ""
        rm_ok = False

        # ── 1. Запускаем ollama rm ──────────────────────────────────
        try:
            kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if IS_WINDOWS:
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            proc = subprocess.run(
                ["ollama", "rm", ollama_name], timeout=60, **kwargs
            )
            rm_ok = (proc.returncode == 0)
            if not rm_ok:
                err = (proc.stdout or "").strip() or f"Код {proc.returncode}"
                print(f"[DELETE] ollama rm вернул ошибку: {err}")
        except FileNotFoundError:
            err = "Ollama не найдена."
        except subprocess.TimeoutExpired:
            err = "Тайм-аут команды ollama rm"
        except Exception as e:
            err = str(e)

        # ── 2. Физически удаляем файлы с диска ─────────────────────
        #    (делаем даже если ollama rm упал — вдруг файлы всё равно остались)
        models_dir = get_ollama_models_dir()
        bytes_freed, deleted = delete_model_files_from_disk(ollama_name, models_dir)
        print(f"[DELETE] Удалено файлов: {len(deleted)}, "
              f"освобождено: {bytes_freed / 1024**3:.2f} GB")
        print(f"[DELETE] Папка моделей: {models_dir}")

        prog.close()

        # ── 3. Итог ─────────────────────────────────────────────────
        fully_ok = rm_ok or (len(deleted) > 0)
        if not fully_ok:
            QtWidgets.QMessageBox.critical(
                self, "Ошибка удаления",
                f"❌ Не удалось удалить {model_name}.\n\n{err}\n\n"
                f"Проверьте что Ollama запущена и попробуйте снова.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            return

        was_active = (llama_handler.CURRENT_AI_MODEL_KEY == model_key)

        ALL_MODELS = {
            "llama3":   ("llama3",           "LLaMA 3"),
            "deepseek": (DEEPSEEK_MODEL_NAME, "DeepSeek"),
        }
        remaining = {
            k: dname
            for k, (oname, dname) in ALL_MODELS.items()
            if k != model_key and check_model_in_ollama(oname)
        }

        freed_str = f"\n\nОсвобождено: {bytes_freed / 1024**3:.1f} GB" if bytes_freed > 0 else ""

        if not remaining:
            QtWidgets.QMessageBox.warning(
                self, "⚠️ Модели не установлены",
                f"✅ {model_name} удалена с диска.{freed_str}\n\n"
                "⚠️ У вас не установлено ни одной модели ИИ.\n\n"
                "Без модели пользоваться ассистентом невозможно.\n"
                "Откройте «Выбор модели» и скачайте любую модель.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            save_settings({"first_launch_done": False})
        else:
            other_key  = list(remaining.keys())[0]
            other_name = remaining[other_key]
            msg = f"✅ {model_name} успешно удалена с диска.{freed_str}"
            if was_active:
                msg += f"\n\nПрограмма переключена на {other_name}."
            QtWidgets.QMessageBox.information(
                self, "Модель удалена", msg,
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            if was_active:
                self.change_ai_model(other_key)

        self._refresh_model_ui()

    def _refresh_model_ui(self):
        """Обновляет UI-элементы, зависящие от текущей активной модели."""
        try:
            # Пробуем обновить заголовок/лейбл если они есть
            for attr in ("model_label", "ai_name_label", "header_model_lbl",
                         "current_model_label", "model_name_lbl"):
                w = getattr(self, attr, None)
                if w and hasattr(w, "setText"):
                    try:
                        w.setText(get_current_display_name())
                    except Exception:
                        pass
        except Exception as e:
            print(f"[MODEL_UI] _refresh_model_ui: {e}")


    def _show_model_switch_toast(self, model_key: str, display_name: str):
        """
        Красивый тост-баннер при смене модели ИИ.

        Анимация:
          Появление    — карточка вылетает снизу + fade-in (320ms, OutBack)
          Пауза        — висит по центру экрана (1200ms)
          Исчезновение — улетает вверх + fade-out (280ms, InCubic)

        Карточка: логотип + название + "Модель активирована" + пульсирующая точка.
        """
        is_dark  = self.current_theme == "dark"
        is_glass = getattr(self, "current_liquid_glass", True)

        if is_dark and is_glass:
            bg     = "rgba(28, 28, 40, 0.93)"
            border = "rgba(100, 100, 160, 0.55)"
            name_c = "#e8e8ff"
            sub_c  = "rgba(160, 160, 200, 0.80)"
            dot_c  = "#6ee89a"
            logo_bg = "rgba(255,255,255,0.12)"
        elif is_dark:
            bg     = "rgb(26, 26, 36)"
            border = "rgba(70, 70, 100, 0.90)"
            name_c = "#e2e2f2"
            sub_c  = "#8888aa"
            dot_c  = "#52c87a"
            logo_bg = "rgba(255,255,255,0.08)"
        elif is_glass:
            bg     = "rgba(255, 255, 255, 0.82)"
            border = "rgba(200, 210, 240, 0.85)"
            name_c = "#1a1a3a"
            sub_c  = "rgba(80, 90, 150, 0.75)"
            dot_c  = "#22aa66"
            logo_bg = "rgba(102,126,234,0.10)"
        else:
            bg     = "rgb(248, 248, 252)"
            border = "rgba(200, 205, 230, 0.95)"
            name_c = "#1a1a3a"
            sub_c  = "#7788aa"
            dot_c  = "#1aaa60"
            logo_bg = "rgba(102,126,234,0.08)"

        # ── Прозрачный оверлей поверх главного окна ─────────────────
        overlay = QtWidgets.QWidget(self)
        overlay.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.setGeometry(self.rect())
        overlay.show()
        overlay.raise_()

        # ── Карточка ─────────────────────────────────────────────────
        card = QtWidgets.QFrame(overlay)
        card.setFixedWidth(300)
        card.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border: 1.5px solid {border};
                border-radius: 22px;
            }}
        """)

        cl = QtWidgets.QHBoxLayout(card)
        cl.setContentsMargins(16, 14, 20, 14)
        cl.setSpacing(14)

        # Логотип
        logo_lbl = QtWidgets.QLabel()
        logo_lbl.setFixedSize(44, 44)
        logo_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        logo_lbl.setStyleSheet(
            f"background: {logo_bg}; border-radius: 12px; border: none;"
        )
        px = _get_model_logo_pixmap(model_key, size=28)
        if not px.isNull():
            logo_lbl.setPixmap(px)
        else:
            logo_lbl.setText(display_name[0].upper())
            logo_lbl.setFont(_apple_font(20, weight=QtGui.QFont.Weight.Bold))
            logo_lbl.setStyleSheet(
                logo_lbl.styleSheet() +
                f"color: {'#aaaaee' if is_dark else '#667eea'};"
            )
        cl.addWidget(logo_lbl)

        # Текст
        txt = QtWidgets.QVBoxLayout()
        txt.setSpacing(2)
        txt.setContentsMargins(0, 0, 0, 0)

        name_lbl = QtWidgets.QLabel(display_name)
        name_lbl.setFont(_apple_font(15, weight=QtGui.QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {name_c}; background: transparent; border: none;")
        txt.addWidget(name_lbl)

        sub_lbl = QtWidgets.QLabel("Модель активирована")
        sub_lbl.setFont(_apple_font(11))
        sub_lbl.setStyleSheet(f"color: {sub_c}; background: transparent; border: none;")
        txt.addWidget(sub_lbl)

        cl.addLayout(txt)
        cl.addStretch()

        # Пульсирующая точка-индикатор
        dot = QtWidgets.QLabel("●")
        dot.setStyleSheet(
            f"color: {dot_c}; background: transparent; border: none; font-size: 13px;"
        )
        cl.addWidget(dot, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

        card.adjustSize()

        # ── Позиционирование: центр по X, чуть выше центра по Y ────
        ow, oh = overlay.width(), overlay.height()
        cx = (ow - 300) // 2
        final_y = int(oh * 0.42)
        start_y = final_y + 40
        card.move(cx, start_y)
        card.show()

        # ── Анимация появления ────────────────────────────────────────
        eff_in = QtWidgets.QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(eff_in)
        eff_in.setOpacity(0.0)

        a_pos_in = QtCore.QPropertyAnimation(card, b"pos")
        a_pos_in.setDuration(300)
        a_pos_in.setStartValue(QtCore.QPoint(cx, start_y))
        a_pos_in.setEndValue(QtCore.QPoint(cx, final_y))
        a_pos_in.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)

        a_op_in = QtCore.QPropertyAnimation(eff_in, b"opacity")
        a_op_in.setDuration(280)
        a_op_in.setStartValue(0.0)
        a_op_in.setEndValue(1.0)
        a_op_in.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        grp_in = QtCore.QParallelAnimationGroup()
        grp_in.addAnimation(a_pos_in)
        grp_in.addAnimation(a_op_in)

        # ── Анимация исчезновения ─────────────────────────────────────
        def _start_hide():
            card.setGraphicsEffect(None)
            eff_out = QtWidgets.QGraphicsOpacityEffect(card)
            card.setGraphicsEffect(eff_out)
            eff_out.setOpacity(1.0)
            hide_y = final_y - 28

            a_pos_out = QtCore.QPropertyAnimation(card, b"pos")
            a_pos_out.setDuration(280)
            a_pos_out.setStartValue(QtCore.QPoint(cx, final_y))
            a_pos_out.setEndValue(QtCore.QPoint(cx, hide_y))
            a_pos_out.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            a_op_out = QtCore.QPropertyAnimation(eff_out, b"opacity")
            a_op_out.setDuration(260)
            a_op_out.setStartValue(1.0)
            a_op_out.setEndValue(0.0)
            a_op_out.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            grp_out = QtCore.QParallelAnimationGroup()
            grp_out.addAnimation(a_pos_out)
            grp_out.addAnimation(a_op_out)

            def _cleanup():
                try:
                    overlay.hide()
                    overlay.deleteLater()
                except RuntimeError:
                    pass

            grp_out.finished.connect(_cleanup)
            card._out_anims = [eff_out, a_pos_out, a_op_out, grp_out]
            grp_out.start()

        def _on_in_done():
            card.setGraphicsEffect(None)
            QtCore.QTimer.singleShot(1200, _start_hide)

        grp_in.finished.connect(_on_in_done)
        card._in_anims = [eff_in, a_pos_in, a_op_in, grp_in]
        grp_in.start()

        # Пульс точки-индикатора
        _dot_eff = QtWidgets.QGraphicsOpacityEffect(dot)
        dot.setGraphicsEffect(_dot_eff)
        _dot_pulse = QtCore.QPropertyAnimation(_dot_eff, b"opacity")
        _dot_pulse.setDuration(700)
        _dot_pulse.setStartValue(1.0)
        _dot_pulse.setKeyValueAt(0.5, 0.25)
        _dot_pulse.setEndValue(1.0)
        _dot_pulse.setLoopCount(3)
        _dot_pulse.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)
        card._dot_anims = [_dot_eff, _dot_pulse]
        _dot_pulse.start()

        # Быстрый pulse кнопки режима в шапке
        if hasattr(self, "mode_btn"):
            _mb_eff = QtWidgets.QGraphicsOpacityEffect(self.mode_btn)
            self.mode_btn.setGraphicsEffect(_mb_eff)
            _mb_pulse = QtCore.QPropertyAnimation(_mb_eff, b"opacity")
            _mb_pulse.setDuration(220)
            _mb_pulse.setStartValue(1.0)
            _mb_pulse.setKeyValueAt(0.5, 0.30)
            _mb_pulse.setEndValue(1.0)
            _mb_pulse.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)

            def _mb_done():
                try:
                    self.mode_btn.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            _mb_pulse.finished.connect(_mb_done)
            card._mb_anims = [_mb_eff, _mb_pulse]
            _mb_pulse.start()

    def _apply_element_visibility(self,
                                   show_tts: bool = True,
                                   show_regen: bool = True,
                                   show_copy: bool = True,
                                   show_user_copy: bool = True,
                                   show_user_edit: bool = True):
        """
        Применяет видимость кнопок ко всем существующим MessageWidget.
        Скрывает controls_widget целиком когда все его кнопки скрыты.
        Системные сообщения (add_controls=False) не трогаем — у них нет кнопок.
        """
        try:
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if not item:
                    continue
                w = item.widget()
                if not w or not hasattr(w, 'speaker') or not hasattr(w, 'controls_widget'):
                    continue

                cw = w.controls_widget
                if cw is None:
                    continue

                # Системные сообщения создаются с add_controls=False —
                # их controls_widget изначально скрыт, не трогаем его.
                if w.speaker == "Система":
                    continue

                is_user      = (w.speaker == "Вы")
                is_assistant = not is_user

                if is_assistant:
                    # ИИ: copy(ИИ), tts, regen
                    if getattr(w, 'copy_btn', None) is not None:
                        w.copy_btn.setVisible(show_copy)
                    if getattr(w, 'tts_button', None) is not None:
                        w.tts_button.setVisible(show_tts)
                    if getattr(w, 'regenerate_btn', None) is not None:
                        w.regenerate_btn.setVisible(show_regen)
                    if getattr(w, 'regenerate_button', None) is not None:
                        w.regenerate_button.setVisible(show_regen)
                    any_visible = show_copy or show_tts or show_regen

                else:
                    # Пользователь: copy(user), edit
                    if getattr(w, 'copy_btn', None) is not None:
                        w.copy_btn.setVisible(show_user_copy)
                    if getattr(w, 'edit_button', None) is not None:
                        w.edit_button.setVisible(show_user_edit)
                    any_visible = show_user_copy or show_user_edit

                try:
                    cw.setVisible(any_visible)
                except RuntimeError:
                    pass

        except Exception as _e:
            print(f"[ELEMENTS] Ошибка применения видимости: {_e}")

    def _restore_mode_btn_animated(self):
        """Плавно восстанавливает mode_btn после закрытия меню.
        Хранится как метод — ссылки не теряются при удалении proxy."""
        try:
            self.mode_btn.setGraphicsEffect(None)
        except Exception:
            pass
        _eff = QtWidgets.QGraphicsOpacityEffect(self.mode_btn)
        self.mode_btn.setGraphicsEffect(_eff)
        _eff.setOpacity(0.0)
        _anim = QtCore.QPropertyAnimation(_eff, b"opacity")
        _anim.setDuration(220)
        _anim.setStartValue(0.0)
        _anim.setEndValue(1.0)
        _anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuint)
        def _done():
            try:
                self.mode_btn.setGraphicsEffect(None)
            except Exception:
                pass
        _anim.finished.connect(_done)
        _anim.start()
        # Держим ссылку в self
        self._mode_btn_restore_anim = [_eff, _anim]
        try:
            self.mode_btn.clearFocus()
            self.input_field.setFocus()
        except Exception:
            pass

    def _restore_attach_btn_animated(self):
        """Плавно восстанавливает attach_btn после закрытия меню."""
        try:
            self.attach_btn.setGraphicsEffect(None)
        except Exception:
            pass
        _eff = QtWidgets.QGraphicsOpacityEffect(self.attach_btn)
        self.attach_btn.setGraphicsEffect(_eff)
        _eff.setOpacity(0.0)
        _anim = QtCore.QPropertyAnimation(_eff, b"opacity")
        _anim.setDuration(220)
        _anim.setStartValue(0.0)
        _anim.setEndValue(1.0)
        _anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuint)
        def _done():
            try:
                self.attach_btn.setGraphicsEffect(None)
            except Exception:
                pass
        _anim.finished.connect(_done)
        _anim.start()
        self._attach_btn_restore_anim = [_eff, _anim]
        try:
            self.attach_btn.clearFocus()
            self.input_field.setFocus()
        except Exception:
            pass

    def animate_mode_change(self, new_mode: str):
        """Плавная смена режима: fade-out → смена текста → fade-in."""
        if self.ai_mode == new_mode:
            return
        self.ai_mode = new_mode
        self.deep_thinking = new_mode != AI_MODE_FAST
        print(f"[MODE] Анимация смены режима → {new_mode}")
        for attr in ('_mode_fade_out', '_mode_fade_in'):
            anim = getattr(self, attr, None)
            if anim:
                anim.stop()
        effect = QtWidgets.QGraphicsOpacityEffect(self.mode_btn)
        self.mode_btn.setGraphicsEffect(effect)
        fade_out = QtCore.QPropertyAnimation(effect, b"opacity")
        fade_out.setDuration(110)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        fade_in = QtCore.QPropertyAnimation(effect, b"opacity")
        fade_in.setDuration(180)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
        fade_out.finished.connect(lambda: self.mode_btn.setText(new_mode))
        fade_out.finished.connect(fade_in.start)
        fade_in.finished.connect(lambda: self.mode_btn.setGraphicsEffect(None))
        self._mode_fade_out = fade_out
        self._mode_fade_in = fade_in
        fade_out.start()

    def show_mode_menu(self):
        """Показать меню выбора режима работы AI с премиум iOS-like анимацией"""

        # Guard: не открываем повторно пока идёт анимация открытия
        if getattr(self, '_mode_menu_animating', False):
            return
        self._mode_menu_animating = True
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: СОЗДАНИЕ МЕНЮ
        # ═══════════════════════════════════════════════════════════════
        menu = QtWidgets.QMenu(self)
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Прозрачное меню (работает на Windows и macOS/Linux)
        menu.setWindowFlags(QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint)
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        _fix_popup_on_windows(menu)
        menu.aboutToShow.connect(lambda: _apply_windows_rounded(menu, radius=18))
        
        # Стеклянные стили — как settingGroup в настройках
        is_glass = getattr(self, "current_liquid_glass", True)
        # Фон меню = цвет bg страницы настроек (за settingGroup блоками)
        if is_dark and is_glass:
            _menu_bg     = "rgba(24, 24, 28, 242)"     # bg dark+glass
            _menu_border = "rgba(50, 50, 55, 128)"
            _item_color  = "#e6e6e6"
            _sel_bg      = "rgba(60, 60, 80, 200)"
            _sel_color   = "#ffffff"
            _sep_color   = "rgba(50, 50, 55, 90)"
        elif is_dark:
            _menu_bg     = "rgb(28, 28, 31)"           # bg dark solid
            _menu_border = "rgba(55, 55, 60, 230)"
            _item_color  = "#f0f0f0"
            _sel_bg      = "rgba(48, 48, 62, 240)"
            _sel_color   = "#ffffff"
            _sep_color   = "rgba(55, 55, 60, 140)"
        elif is_glass:
            _menu_bg     = "rgba(240, 240, 245, 235)"  # bg light+glass
            _menu_border = "rgba(210, 212, 222, 200)"
            _item_color  = "#222222"
            _sel_bg      = "rgba(228, 230, 252, 230)"
            _sel_color   = "#1a1a3a"
            _sep_color   = "rgba(200, 202, 218, 120)"
        else:
            _menu_bg     = "rgb(246, 246, 248)"        # bg light solid
            _menu_border = "rgba(210, 210, 215, 242)"
            _item_color  = "#1a1a1a"
            _sel_bg      = "rgba(228, 230, 252, 242)"
            _sel_color   = "#1a1a3a"
            _sep_color   = "rgba(210, 210, 215, 178)"

        menu.setStyleSheet(f"""
            QMenu {{
                background: {_menu_bg};
                border: 1px solid {_menu_border};
                border-radius: 18px;
                padding: 8px;
            }}
            QMenu::item {{
                padding: 12px 24px;
                border-radius: 12px;
                color: {_item_color};
                font-family: "Segoe UI Variable", "Segoe UI", Inter, -apple-system, sans-serif;
                font-size: 14px;
                font-weight: 600;
                margin: 2px 4px;
                background: transparent;
            }}
            QMenu::item:selected {{
                background: {_sel_bg};
                color: {_sel_color};
            }}
            QMenu::separator {{
                height: 1px;
                background: {_sep_color};
                margin: 4px 12px;
            }}
            QMenu::indicator {{ width: 0px; height: 0px; }}
        """)
        
        # ── Карточка модели через QWidgetAction (кликабельная!) ──
        _model_widget_action = QtWidgets.QWidgetAction(menu)
        _model_card = QtWidgets.QPushButton()
        _model_card.setFixedHeight(52)
        _model_card.setFixedWidth(210 - 8)  # _MENU_W минус отступы обёртки
        _model_card.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

        _current_display = get_current_display_name()

        if is_dark:
            _card_bg     = "rgba(55, 55, 70, 0.7)"
            _card_bg_h   = "rgba(70, 70, 90, 0.85)"
            _card_border = "rgba(80, 80, 110, 0.6)"
            _icon_color  = "#9aa8cc"
            _name_color  = "#d0d8f0"
            _sub_color   = "#7888aa"
        else:
            _card_bg     = "rgba(235, 238, 250, 0.85)"
            _card_bg_h   = "rgba(220, 225, 245, 0.95)"
            _card_border = "rgba(200, 208, 230, 0.8)"
            _icon_color  = "#6677aa"
            _name_color  = "#1a2040"
            _sub_color   = "#8899bb"

        _model_card.setStyleSheet(f"""
            QPushButton {{
                background: {_card_bg};
                border: 1px solid {_card_border};
                border-radius: 10px;
                text-align: left;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: {_card_bg_h};
                border: 1px solid rgba(102, 126, 234, 0.5);
            }}
        """)

        # Внутренний layout карточки
        _cl = QtWidgets.QHBoxLayout(_model_card)
        _cl.setContentsMargins(12, 0, 14, 0)
        _cl.setSpacing(10)
        _cl.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter)

        _icon_lbl = QtWidgets.QLabel()
        _icon_lbl.setFixedSize(26, 26)
        _icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        _icon_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        _icon_lbl.setStyleSheet("background: transparent; border: none;")
        # Логотип текущей модели — берём из встроенного base64
        _model_px = _get_model_logo_pixmap(llama_handler.CURRENT_AI_MODEL_KEY, size=22)
        if not _model_px.isNull():
            _icon_lbl.setPixmap(_model_px)
        else:
            _icon_lbl.setText(llama_handler.SUPPORTED_MODELS.get(
                llama_handler.CURRENT_AI_MODEL_KEY, ("", "?"))[1][:1])
            _icon_lbl.setStyleSheet(
                f"background: transparent; border: none; font-size: 15px; font-weight: 700; color: {_icon_color};"
            )
        _cl.addWidget(_icon_lbl, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        _text_col = QtWidgets.QVBoxLayout()
        _text_col.setSpacing(1)
        _text_col.setContentsMargins(0, 8, 0, 8)

        _sub_lbl = QtWidgets.QLabel("Текущая модель  ›")
        _sub_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"color: {_sub_color}; font-size: 10px; font-weight: 400;"
        )
        _sub_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        _text_col.addWidget(_sub_lbl, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        _name_lbl = QtWidgets.QLabel(_current_display)
        _name_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"color: {_name_color}; font-size: 14px; font-weight: 700;"
        )
        _name_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        _text_col.addWidget(_name_lbl, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        _cl.addLayout(_text_col, 0)
        _cl.addStretch()

        # При клике на карточку — восстанавливаем кнопку и открываем выбор модели
        def _on_model_card_click():
            menu.close()
            # Немедленно восстанавливаем кнопку — show_model_selector может
            # открыть exec() и _on_close_done не успеет отработать
            QtCore.QTimer.singleShot(50, self._restore_mode_btn_animated)
            QtCore.QTimer.singleShot(60, self.show_model_selector)
        _model_card.clicked.connect(_on_model_card_click)

        _wrap = QtWidgets.QWidget()
        _wl = QtWidgets.QVBoxLayout(_wrap)
        _wl.setContentsMargins(4, 4, 4, 2)
        _wl.addWidget(_model_card)

        _model_widget_action.setDefaultWidget(_wrap)
        menu.addAction(_model_widget_action)
        menu.addSeparator()

        # ── Режимы: QWidgetAction с кастомным рендером ───────────────────────
        # QMenu::item никогда не выглядит хорошо — используем виджеты напрямую
        _MENU_W = 210  # фиксированная ширина строк

        _mode_cfg = [
            (AI_MODE_FAST,     "⚡", "Быстрый",   AI_MODE_FAST),
            (AI_MODE_THINKING, "🧠", "Думающий",  AI_MODE_THINKING),
            (AI_MODE_PRO,      "🚀", "Про",        AI_MODE_PRO),
        ]

        if is_dark and is_glass:
            _row_bg_normal  = "rgba(45, 45, 50, 0.50)"  # = btn_bg dark+glass
            _row_bg_active  = "rgba(80, 82, 120, 0.65)"
            _row_border_act = "rgba(110, 120, 210, 0.50)"
            _row_border_n   = "rgba(55, 55, 75, 0.35)"
            _row_hover      = "rgba(65, 65, 85, 0.65)"
            _txt_active     = "#ffffff"
            _txt_normal     = "#c8c8de"
            _chk_col        = "#8899ff"
        elif is_dark:
            _row_bg_normal  = "rgb(48, 48, 52)"  # = btn_bg dark solid
            _row_bg_active  = "rgba(70, 72, 100, 0.95)"
            _row_border_act = "rgba(100, 110, 200, 0.60)"
            _row_border_n   = "rgba(55, 55, 65, 0.60)"
            _row_hover      = "rgba(55, 55, 72, 0.95)"
            _txt_active     = "#ffffff"
            _txt_normal     = "#c8c8de"
            _chk_col        = "#8899ff"
        elif is_glass:
            _row_bg_normal  = "rgba(255, 255, 255, 0.82)"  # = btn_bg light+glass
            _row_bg_active  = "rgba(225, 228, 255, 0.90)"
            _row_border_act = "rgba(140, 155, 230, 0.55)"
            _row_border_n   = "rgba(215, 218, 235, 0.70)"
            _row_hover      = "rgba(238, 240, 255, 0.90)"
            _txt_active     = "#1a1a3a"
            _txt_normal     = "#3a3a5a"
            _chk_col        = "#5566cc"
        else:
            _row_bg_normal  = "rgb(242, 242, 245)"  # = btn_bg light solid
            _row_bg_active  = "rgba(225, 228, 252, 0.95)"
            _row_border_act = "rgba(140, 155, 230, 0.65)"
            _row_border_n   = "rgba(210, 212, 225, 0.80)"
            _row_hover      = "rgb(235, 237, 252)"
            _txt_active     = "#1a1a3a"
            _txt_normal     = "#3a3a5a"
            _chk_col        = "#5566cc"

        _mode_btns = []
        for _mk2, _emoji, _label, _target in _mode_cfg:
            _active = (self.ai_mode == _mk2)

            _wa = QtWidgets.QWidgetAction(menu)
            _row = QtWidgets.QWidget()
            _row.setFixedSize(_MENU_W, 36)

            # Каждая строка — как блок из настроек: явный фон и граница
            if _active:
                _row.setStyleSheet(f"""
                    QWidget {{
                        background: {_row_bg_active};
                        border: 1px solid {_row_border_act};
                        border-radius: 12px;
                    }}
                """)
            else:
                _row.setStyleSheet(f"""
                    QWidget {{
                        background: {_row_bg_normal};
                        border: 1px solid {_row_border_n};
                        border-radius: 12px;
                    }}
                    QWidget:hover {{
                        background: {_row_hover};
                        border: 1px solid {_row_border_act};
                    }}
                """)

            _rl = QtWidgets.QHBoxLayout(_row)
            _rl.setContentsMargins(12, 0, 12, 0)
            _rl.setSpacing(9)

            # Emoji
            _e = QtWidgets.QLabel(_emoji)
            _e.setFixedSize(22, 22)
            _e.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            _e.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            _e.setStyleSheet("background: transparent; border: none; font-size: 15px;")
            _rl.addWidget(_e)

            # Label
            _t = QtWidgets.QLabel(_label)
            _t.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            _t.setStyleSheet(
                f"background: transparent; border: none; "
                f"color: {_txt_active if _active else _txt_normal}; "
                f"font-size: 14px; font-weight: {'700' if _active else '600'};"
            )
            _rl.addWidget(_t)

            # Галочка активного — сразу после текста, без растяжки
            if _active:
                _c = QtWidgets.QLabel(" ✓")
                _c.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                _c.setStyleSheet(
                    f"background: transparent; border: none; "
                    f"color: {_chk_col}; font-size: 13px; font-weight: 700;"
                )
                _rl.addWidget(_c)
            _rl.addStretch()

            _wa.setDefaultWidget(_row)
            menu.addAction(_wa)

            # Обёртка: делаем строку кликабельной через btn поверх
            _btn = QtWidgets.QPushButton(_row)
            _btn.setGeometry(0, 0, _MENU_W, 36)
            _btn.setFlat(True)
            _btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            _btn.setStyleSheet("QPushButton { background: transparent; border: none; }")
            _mode_btns.append((_btn, _target))

        # Подключаем обработчики — guard от двойного срабатывания
        _mode_handled = [False]
        for _btn, _target in _mode_btns:
            def _h(checked=False, k=_target):
                if _mode_handled[0]:
                    return
                _mode_handled[0] = True
                menu.close()
                self.animate_mode_change(k)
            _btn.clicked.connect(_h)

        # stub-переменные (triggered.connect ниже на них не вызывается)
        fast_action     = None
        thinking_action = None
        pro_action      = None
        
        # Получаем позицию кнопки
        button_rect = self.mode_btn.rect()
        button_global_pos = self.mode_btn.mapToGlobal(button_rect.bottomLeft())
        
        # Реальный размер меню без показа его на экране
        menu.ensurePolished()
        menu.adjustSize()
        _sh = menu.sizeHint()
        menu_width  = _sh.width()  if _sh.width()  > 10 else 220
        menu_height = _sh.height() if _sh.height() > 10 else 300
        
        # Получаем геометрию окна приложения
        window_geometry = self.geometry()
        window_top = self.mapToGlobal(QtCore.QPoint(0, 0)).y()
        window_bottom = self.mapToGlobal(QtCore.QPoint(0, window_geometry.height())).y()
        
        # Вычисляем позицию ВВЕРХ от кнопки
        menu_pos_up = QtCore.QPoint(
            button_global_pos.x() - (menu_width - self.mode_btn.width()) // 2,  # Центрируем по кнопке
            button_global_pos.y() - self.mode_btn.height() - menu_height - 8
        )
        
        # Проверяем, выходит ли меню за верхнюю границу окна
        if menu_pos_up.y() < window_top + 80:  # 80px отступ от верха (title bar)
            # Если выходит за верх - показываем ВНИЗ от кнопки
            menu_pos = QtCore.QPoint(
                button_global_pos.x() - (menu_width - self.mode_btn.width()) // 2,
                button_global_pos.y() + 8
            )
            print("[MODE_MENU] Меню открывается вниз (не хватает места сверху)")
        else:
            # Показываем вверх
            menu_pos = menu_pos_up
            print("[MODE_MENU] Меню открывается вверх")
        
        # ── Общий класс прокси для анимации открытия/закрытия ────────────────
        class _BurstProxy(QtWidgets.QWidget):
            """
            Вырастает из rect кнопки до rect меню.
            Нижний край зафиксирован (bottom anchor) — прокси растёт вверх.
            paintEvent рисует скруглённый блок с radius = min(16, w/2, h/2):
              - маленький  →  кружок (как кнопка)
              - большой    →  карточка меню
            """
            def __init__(self, bg_color, geo):
                super().__init__(
                    None,
                    QtCore.Qt.WindowType.Tool |
                    QtCore.Qt.WindowType.FramelessWindowHint |
                    QtCore.Qt.WindowType.WindowStaysOnTopHint,
                )
                self._bg = bg_color
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
                self.setGeometry(geo)
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

            def paintEvent(self, event):
                p = QtGui.QPainter(self)
                p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                r = self.rect()
                radius = min(16, r.width() // 2, r.height() // 2)
                path = QtGui.QPainterPath()
                path.addRoundedRect(QtCore.QRectF(r), radius, radius)
                p.setClipPath(path)
                p.fillRect(r, self._bg)
                p.end()

        _btn_tl = self.mode_btn.mapToGlobal(QtCore.QPoint(0, 0))
        _btn_w  = self.mode_btn.width()
        _btn_h  = self.mode_btn.height()
        _btn_bottom = _btn_tl.y() + _btn_h   # нижняя граница кнопки — якорь

        # Меню центрировано по кнопке, нижний край = нижний край кнопки
        # Edge-clamp по X: не выходим за края окна
        _win_tl    = self.mapToGlobal(QtCore.QPoint(0, 0))
        _win_w     = self.width()
        _ideal_x   = _btn_tl.x() + _btn_w // 2 - menu_width // 2
        _clamped_x = max(_win_tl.x() + 8, min(_ideal_x, _win_tl.x() + _win_w - menu_width - 8))

        # start = кнопка
        # end   = меню над кнопкой, bottom = top кнопки, центрировано по X
        _start_geo     = QtCore.QRect(_btn_tl.x(), _btn_tl.y(), _btn_w, _btn_h)
        _proxy_end_geo = QtCore.QRect(_clamped_x,
                                       _btn_tl.y() - menu_height,
                                       menu_width, menu_height)

        _menu_bg = QtGui.QColor(30, 30, 35, 245) if is_dark else QtGui.QColor(255, 255, 255, 245)

        # Кнопка затемняется (не исчезает) пока прокси анимируется
        _dim_eff = QtWidgets.QGraphicsOpacityEffect(self.mode_btn)
        self.mode_btn.setGraphicsEffect(_dim_eff)
        _dim_anim = QtCore.QPropertyAnimation(_dim_eff, b"opacity")
        _dim_anim.setDuration(80)
        _dim_anim.setStartValue(1.0)
        _dim_anim.setEndValue(0.0)
        _dim_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuart)
        _dim_anim.start()

        open_proxy = _BurstProxy(_menu_bg, _start_geo)
        open_proxy.show()
        open_proxy.raise_()
        _apply_windows_rounded(open_proxy, radius=16)

        _o_geo = QtCore.QPropertyAnimation(open_proxy, b"geometry")
        _o_geo.setDuration(320)
        _o_geo.setStartValue(_start_geo)
        _o_geo.setEndValue(_proxy_end_geo)
        _o_geo.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
        _o_geo.start()
        open_proxy._anims = [_o_geo, _dim_eff, _dim_anim]

        def _on_open_done():
            self._mode_menu_animating = False
            try:
                open_proxy.close()
            except Exception:
                pass
            menu.popup(_proxy_end_geo.topLeft())

        _o_geo.finished.connect(_on_open_done)

        # ── Режимы управляются через _btn.clicked (см. выше) ────────────────

        # ─────────────────────────────────────────────────────────────────
        # ЗАКРЫТИЕ: proxy схлопывается обратно в кнопку (bottom anchor)
        # ─────────────────────────────────────────────────────────────────
        _close_started = [False]

        def _animate_mode_close():
            if _close_started[0]:
                return
            _close_started[0] = True

            cur_geo = menu.geometry()
            try:
                px = menu.grab()
            except Exception:
                px = None

            class _CloseProxy(QtWidgets.QWidget):
                def __init__(self, pixmap, geo):
                    super().__init__(
                        None,
                        QtCore.Qt.WindowType.Tool |
                        QtCore.Qt.WindowType.FramelessWindowHint |
                        QtCore.Qt.WindowType.WindowStaysOnTopHint,
                    )
                    self._px = pixmap
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
                    self.setGeometry(geo)

                def paintEvent(self, event):
                    if not self._px:
                        return
                    p = QtGui.QPainter(self)
                    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                    p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                    r = self.rect()
                    radius = min(16, r.width() // 2, r.height() // 2)
                    path = QtGui.QPainterPath()
                    path.addRoundedRect(QtCore.QRectF(r), radius, radius)
                    p.setClipPath(path)
                    p.drawPixmap(r, self._px)
                    p.end()

            proxy = _CloseProxy(px, cur_geo)
            proxy.show()
            proxy.raise_()
            _apply_windows_rounded(proxy, radius=16)

            # Кнопка сейчас спрятана — цель: вернуться к её rect
            _btn_now    = self.mode_btn.mapToGlobal(QtCore.QPoint(0, 0))
            _close_end  = QtCore.QRect(_btn_now.x(), _btn_now.y(),
                                        self.mode_btn.width(), self.mode_btn.height())

            _c_geo = QtCore.QPropertyAnimation(proxy, b"geometry")
            _c_geo.setDuration(260)
            _c_geo.setStartValue(cur_geo)
            _c_geo.setEndValue(_close_end)
            _c_geo.setEasingCurve(QtCore.QEasingCurve.Type.InBack)

            _c_eff = QtWidgets.QGraphicsOpacityEffect(proxy)
            proxy.setGraphicsEffect(_c_eff)
            _c_eff.setOpacity(1.0)
            _c_op = QtCore.QPropertyAnimation(_c_eff, b"opacity")
            _c_op.setDuration(260)
            _c_op.setStartValue(1.0)
            _c_op.setKeyValueAt(0.55, 0.95)
            _c_op.setKeyValueAt(0.85, 0.3)
            _c_op.setEndValue(0.0)
            _c_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            def _on_close_done():
                try:
                    proxy.close()
                except Exception:
                    pass
                self._restore_mode_btn_animated()

            _c_geo.finished.connect(_on_close_done)
            _c_op.start()
            _c_geo.start()
            # Храним в self — иначе WA_DeleteOnClose убьёт анимы вместе с proxy
            self._mode_close_proxy_anims = [proxy, _c_op, _c_geo, _c_eff]

        menu.aboutToHide.connect(_animate_mode_close)
    
    def eventFilter(self, obj, event):
        """
        Фильтр событий для:
        1. Обновления кнопки "вниз" после ручного скролла
        2. Позиционирования floating кнопки при resize
        3. Автозакрытия sidebar при клике вне его
        
        ПРОСТАЯ АРХИТЕКТУРА:
        - Wheel события НИКОГДА не блокируются
        - После wheel → обновляем кнопку через invokeMethod
        - При resize → обновляем позицию кнопки
        - НЕТ сложной синхронизации, НЕТ флагов
        """
        # ═══════════════════════════════════════════════
        # ОБРАБОТКА WHEEL СОБЫТИЙ (прокрутка колесиком)
        # ═══════════════════════════════════════════════
        try:
            # Проверяем что это viewport нашего scroll_area
            if hasattr(self, 'scroll_area') and obj == self.scroll_area.viewport():
                # Если это wheel событие
                if event.type() == QtCore.QEvent.Type.Wheel:
                    result = super().eventFilter(obj, event)
                    QtCore.QMetaObject.invokeMethod(
                        self,
                        "_update_button_after_scroll",
                        QtCore.Qt.ConnectionType.QueuedConnection
                    )
                    return result
        except RuntimeError:
            # scroll_area или его viewport был удалён — игнорируем
            pass

        # ═══════════════════════════════════════════════
        # ОБРАБОТКА RESIZE SCROLL_AREA (изменение размера)
        # ═══════════════════════════════════════════════
        try:
            if (hasattr(self, 'scroll_area')
                    and obj == self.scroll_area
                    and event.type() == QtCore.QEvent.Type.Resize):
                if hasattr(self, 'scroll_to_bottom_btn'):
                    self.scroll_to_bottom_btn.update_position(
                        self.scroll_area.width(),
                        self.scroll_area.height()
                    )
        except RuntimeError:
            pass
        
        # ═══════════════════════════════════════════════
        # АВТОЗАКРЫТИЕ SIDEBAR (клик вне sidebar)
        # ═══════════════════════════════════════════════
        if (obj is getattr(self, '_dim_overlay', None)
                and event.type() == QtCore.QEvent.Type.MouseButtonPress
                and getattr(self, '_sidebar_open', False)):
            self.toggle_sidebar()
            return True

        # Для всех остальных случаев - стандартная обработка
        return super().eventFilter(obj, event)
    
    @QtCore.pyqtSlot()
    def _update_button_after_scroll(self):
        """Обновляет layout и видимость кнопки "вниз" после ручного скролла."""
        try:
            scrollbar = self.scroll_area.verticalScrollBar()
            current_value = scrollbar.value()
            
            self.messages_layout.invalidate()
            self.messages_layout.activate()
            self.messages_widget.updateGeometry()
            
            self.scroll_area.viewport().update()
            
            scrollbar.setValue(current_value)
        except RuntimeError:
            return
        
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.update_scroll_button_visibility()
    
    def toggle_thinking(self, state=None):
        # Блокируем переключение во время генерации
        if self.is_generating:
            return
        
        # Если вызвано напрямую (из меню), просто используем текущее состояние
        if state is None:
            return
        
        self.deep_thinking = (state == QtCore.Qt.CheckState.Checked.value)

    def toggle_search(self, state=None):
        # Блокируем переключение во время генерации
        if self.is_generating:
            return
        
        # Если вызвано напрямую (из меню), просто используем текущее состояние
        if state is None:
            return
        
        self.use_search = (state == QtCore.Qt.CheckState.Checked.value)

    def _show_search_toast(self, enabled: bool):
        """
        Toast-уведомление при переключении умного поиска.
        Аналогично _show_model_switch_toast — вылетает снизу, висит, улетает вверх.
        """
        is_dark  = self.current_theme == "dark"
        is_glass = getattr(self, "current_liquid_glass", True)

        if is_dark and is_glass:
            bg     = "rgba(28, 28, 40, 0.93)"
            border = "rgba(100, 100, 160, 0.55)"
            name_c = "#e8e8ff"
            sub_c  = "rgba(160, 160, 200, 0.80)"
            dot_c  = "#6ee89a" if enabled else "#e87a6e"
            icon_bg = "rgba(255,255,255,0.12)"
        elif is_dark:
            bg     = "rgb(26, 26, 36)"
            border = "rgba(70, 70, 100, 0.90)"
            name_c = "#e2e2f2"
            sub_c  = "#8888aa"
            dot_c  = "#52c87a" if enabled else "#e07070"
            icon_bg = "rgba(255,255,255,0.08)"
        elif is_glass:
            bg     = "rgba(255, 255, 255, 0.82)"
            border = "rgba(200, 210, 240, 0.85)"
            name_c = "#1a1a3a"
            sub_c  = "rgba(80, 90, 150, 0.75)"
            dot_c  = "#22aa66" if enabled else "#cc4444"
            icon_bg = "rgba(102,126,234,0.10)"
        else:
            bg     = "rgb(248, 248, 252)"
            border = "rgba(200, 205, 230, 0.95)"
            name_c = "#1a1a3a"
            sub_c  = "#7788aa"
            dot_c  = "#1aaa60" if enabled else "#cc4444"
            icon_bg = "rgba(102,126,234,0.08)"

        # ── Overlay ───────────────────────────────────────────────────
        overlay = QtWidgets.QWidget(self)
        overlay.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.setGeometry(self.rect())
        overlay.show()
        overlay.raise_()

        # ── Карточка ─────────────────────────────────────────────────
        card = QtWidgets.QFrame(overlay)
        card.setFixedWidth(300)
        card.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border: 1.5px solid {border};
                border-radius: 22px;
            }}
        """)

        cl = QtWidgets.QHBoxLayout(card)
        cl.setContentsMargins(16, 14, 20, 14)
        cl.setSpacing(14)

        # Иконка поиска
        icon_lbl = QtWidgets.QLabel("🔍")
        icon_lbl.setFixedSize(44, 44)
        icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            f"background: {icon_bg}; border-radius: 12px; border: none; font-size: 20px;"
        )
        cl.addWidget(icon_lbl)

        # Текст
        txt = QtWidgets.QVBoxLayout()
        txt.setSpacing(2)
        txt.setContentsMargins(0, 0, 0, 0)

        name_lbl = QtWidgets.QLabel("Умный поиск")
        name_lbl.setFont(_apple_font(15, weight=QtGui.QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {name_c}; background: transparent; border: none;")
        txt.addWidget(name_lbl)

        status_text = "Включён" if enabled else "Отключён"
        sub_lbl = QtWidgets.QLabel(status_text)
        sub_lbl.setFont(_apple_font(11))
        sub_lbl.setStyleSheet(f"color: {sub_c}; background: transparent; border: none;")
        txt.addWidget(sub_lbl)

        cl.addLayout(txt)
        cl.addStretch()

        # Пульсирующая точка
        dot = QtWidgets.QLabel("●")
        dot.setStyleSheet(
            f"color: {dot_c}; background: transparent; border: none; font-size: 13px;"
        )
        cl.addWidget(dot, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

        card.adjustSize()

        # ── Позиционирование ─────────────────────────────────────────
        ow, oh = overlay.width(), overlay.height()
        cx = (ow - 300) // 2
        final_y = int(oh * 0.42)
        start_y = final_y + 40
        card.move(cx, start_y)
        card.show()

        # ── Появление ────────────────────────────────────────────────
        eff_in = QtWidgets.QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(eff_in)
        eff_in.setOpacity(0.0)

        a_pos_in = QtCore.QPropertyAnimation(card, b"pos")
        a_pos_in.setDuration(300)
        a_pos_in.setStartValue(QtCore.QPoint(cx, start_y))
        a_pos_in.setEndValue(QtCore.QPoint(cx, final_y))
        a_pos_in.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)

        a_op_in = QtCore.QPropertyAnimation(eff_in, b"opacity")
        a_op_in.setDuration(280)
        a_op_in.setStartValue(0.0)
        a_op_in.setEndValue(1.0)
        a_op_in.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        grp_in = QtCore.QParallelAnimationGroup()
        grp_in.addAnimation(a_pos_in)
        grp_in.addAnimation(a_op_in)

        # ── Исчезновение ─────────────────────────────────────────────
        def _start_hide():
            card.setGraphicsEffect(None)
            eff_out = QtWidgets.QGraphicsOpacityEffect(card)
            card.setGraphicsEffect(eff_out)

            a_pos_out = QtCore.QPropertyAnimation(card, b"pos")
            a_pos_out.setDuration(280)
            a_pos_out.setStartValue(QtCore.QPoint(cx, final_y))
            a_pos_out.setEndValue(QtCore.QPoint(cx, final_y - 28))
            a_pos_out.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            a_op_out = QtCore.QPropertyAnimation(eff_out, b"opacity")
            a_op_out.setDuration(260)
            a_op_out.setStartValue(1.0)
            a_op_out.setEndValue(0.0)
            a_op_out.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            grp_out = QtCore.QParallelAnimationGroup()
            grp_out.addAnimation(a_pos_out)
            grp_out.addAnimation(a_op_out)

            def _cleanup():
                try:
                    overlay.hide()
                    overlay.deleteLater()
                except RuntimeError:
                    pass

            grp_out.finished.connect(_cleanup)
            card._out_anims = [eff_out, a_pos_out, a_op_out, grp_out]
            grp_out.start()

        def _on_in_done():
            card.setGraphicsEffect(None)
            QtCore.QTimer.singleShot(1200, _start_hide)

        grp_in.finished.connect(_on_in_done)
        card._in_anims = [eff_in, a_pos_in, a_op_in, grp_in]
        grp_in.start()

        # Пульс точки
        _dot_eff = QtWidgets.QGraphicsOpacityEffect(dot)
        dot.setGraphicsEffect(_dot_eff)
        _dot_pulse = QtCore.QPropertyAnimation(_dot_eff, b"opacity")
        _dot_pulse.setDuration(700)
        _dot_pulse.setStartValue(1.0)
        _dot_pulse.setKeyValueAt(0.5, 0.25)
        _dot_pulse.setEndValue(1.0)
        _dot_pulse.setLoopCount(3)
        _dot_pulse.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)
        card._dot_anims = [_dot_eff, _dot_pulse]
        _dot_pulse.start()



    def show_attach_menu(self):
        """Показать меню с опциями Search и Attach file с премиум iOS-like анимацией + blur эффект"""

        # Guard: не открываем повторно пока идёт анимация открытия
        if getattr(self, '_attach_menu_animating', False):
            return
        self._attach_menu_animating = True
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: СОЗДАНИЕ МЕНЮ
        # ═══════════════════════════════════════════════════════════════
        menu = QtWidgets.QMenu(self)
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Прозрачное меню без артефактов (работает на Windows и macOS/Linux)
        menu.setWindowFlags(QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint)
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        _fix_popup_on_windows(menu)  # Win10/11: убираем TranslucentBackground, включаем DWM-скруглённые
        menu.aboutToShow.connect(lambda: _apply_windows_rounded(menu, radius=20))
        
        # Адаптивные стили в зависимости от темы
        is_glass = getattr(self, "current_liquid_glass", True)
        if is_dark and is_glass:
            _abg = "rgba(24, 24, 28, 242)"; _ab = "rgba(50, 50, 55, 128)"
            _aic = "#e6e6e6"; _asel = "rgba(60, 60, 80, 200)"; _asc = "#ffffff"
            _asep = "rgba(50, 50, 55, 90)"
        elif is_dark:
            _abg = "rgb(28, 28, 31)"; _ab = "rgba(55, 55, 60, 230)"
            _aic = "#f0f0f0"; _asel = "rgba(48, 48, 62, 240)"; _asc = "#ffffff"
            _asep = "rgba(55, 55, 60, 140)"
        elif is_glass:
            _abg = "rgba(240, 240, 245, 235)"; _ab = "rgba(210, 212, 222, 200)"
            _aic = "#222222"; _asel = "rgba(228, 230, 252, 230)"; _asc = "#1a1a3a"
            _asep = "rgba(200, 202, 218, 120)"
            _abg = "rgb(246, 246, 248)"; _ab = "rgba(210, 210, 215, 242)"
            _aic = "#1a1a1a"; _asel = "rgba(228, 230, 252, 242)"; _asc = "#1a1a3a"
            _asep = "rgba(210, 210, 215, 178)"
            _asep = "rgba(210, 210, 215, 0.70)"

        menu.setStyleSheet(f"""
            QMenu {{
                background: {_abg};
                border: 1px solid {_ab};
                border-radius: 18px;
                padding: 8px;
            }}
            QMenu::item {{
                padding: 12px 40px;
                border-radius: 12px;
                color: {_aic};
                font-size: 14px;
                font-weight: 600;
                margin: 3px 4px;
                background: transparent;
                min-width: 190px;
            }}
            QMenu::item:selected {{
                background: {_asel};
                color: {_asc};
            }}
            QMenu::separator {{
                height: 1px;
                background: {_asep};
                margin: 6px 16px;
            }}
        """)
        
        # ПОИСК — название фиксированное, состояние отражается галочкой
        search_label = "🔍 Умный поиск"
        search_action = menu.addAction(search_label)
        search_action.setCheckable(True)
        search_action.setChecked(self.use_search)
        
        # Разделитель
        menu.addSeparator()
        
        # Attach file опция — показываем количество прикреплённых файлов
        files_count = len(self.attached_files)
        if files_count > 0:
            if files_count >= 5:
                # Достигнут лимит - можно только открепить
                file_action = menu.addAction(f"📎 Файлов: {files_count}/5 (максимум)")
                file_action.setEnabled(False)
                clear_action = menu.addAction(f"✕  Открепить все ({files_count})")
            else:
                # Можно добавить ещё файлы
                file_action = menu.addAction(f"📎 Добавить файл ({files_count}/5)")
                clear_action = menu.addAction(f"✕  Открепить все ({files_count})")
        else:
            file_action = menu.addAction("📎 Прикрепить файл")
            clear_action = None
        
        # Вычисляем позицию меню НАД кнопкой с edge avoidance
        button_rect = self.attach_btn.rect()
        button_global_pos = self.attach_btn.mapToGlobal(button_rect.topLeft())
        button_center = self.attach_btn.mapToGlobal(button_rect.center())
        
        # Реальный размер меню без показа его на экране
        menu.ensurePolished()
        menu.adjustSize()
        _sh = menu.sizeHint()
        menu_width  = _sh.width()  if _sh.width()  > 10 else 320
        menu_height = _sh.height() if _sh.height() > 10 else 160
        
        # ═══════════════════════════════════════════════════════════════
        # EDGE AVOIDANCE - гарантируем что меню не выходит за границы окна
        # ═══════════════════════════════════════════════════════════════
        
        # Получаем размеры окна приложения
        app_geometry = self.geometry()
        window_global_pos = self.mapToGlobal(QtCore.QPoint(0, 0))
        window_width = app_geometry.width()
        
        # Минимальный отступ от краёв окна
        EDGE_PADDING = 12
        
        # Вычисляем идеальную позицию (центр меню по центру кнопки)
        ideal_menu_x = button_center.x() - menu_width // 2
        
        # Применяем clamp - ограничиваем позицию границами окна
        # Левая граница: минимум EDGE_PADDING от левого края окна
        min_x = window_global_pos.x() + EDGE_PADDING
        # Правая граница: максимум так, чтобы правый край меню был на EDGE_PADDING от правого края окна
        max_x = window_global_pos.x() + window_width - menu_width - EDGE_PADDING
        
        # Clamp позиции
        clamped_menu_x = max(min_x, min(ideal_menu_x, max_x))
        
        # Финальная позиция меню
        menu_pos = QtCore.QPoint(
            clamped_menu_x,  # X с edge avoidance
            button_global_pos.y() - menu_height - 8  # Y: над кнопкой с отступом
        )
        
        # Отладочная информация
        print(f"[POPOVER] Позиционирование меню:")
        print(f"  Кнопка центр: x={button_center.x()}")
        print(f"  Окно: x={window_global_pos.x()}, width={window_width}")
        print(f"  Меню ширина: {menu_width}")
        print(f"  Идеальная позиция: x={ideal_menu_x}")
        print(f"  Границы: min_x={min_x}, max_x={max_x}")
        print(f"  Финальная позиция: x={clamped_menu_x}")
        print(f"  Сдвиг от идеала: {clamped_menu_x - ideal_menu_x}px")
        
        class _BurstProxy(QtWidgets.QWidget):
            def __init__(self, bg_color, geo):
                super().__init__(
                    None,
                    QtCore.Qt.WindowType.Tool |
                    QtCore.Qt.WindowType.FramelessWindowHint |
                    QtCore.Qt.WindowType.WindowStaysOnTopHint,
                )
                self._bg = bg_color
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
                self.setGeometry(geo)
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

            def paintEvent(self, event):
                p = QtGui.QPainter(self)
                p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                r = self.rect()
                radius = min(20, r.width() // 2, r.height() // 2)
                path = QtGui.QPainterPath()
                path.addRoundedRect(QtCore.QRectF(r), radius, radius)
                p.setClipPath(path)
                p.fillRect(r, self._bg)
                p.end()

        _btn_tl    = self.attach_btn.mapToGlobal(QtCore.QPoint(0, 0))
        _btn_w     = self.attach_btn.width()
        _btn_h     = self.attach_btn.height()
        _btn_bottom = _btn_tl.y() + _btn_h

        # Центрировано по кнопке, нижний край = нижний край кнопки
        _win_tl    = self.mapToGlobal(QtCore.QPoint(0, 0))
        _win_w     = self.width()
        _ideal_x   = _btn_tl.x() + _btn_w // 2 - menu_width // 2
        _clamped_x = max(_win_tl.x() + 8, min(_ideal_x, _win_tl.x() + _win_w - menu_width - 8))

        _start_geo     = QtCore.QRect(_btn_tl.x(), _btn_tl.y(), _btn_w, _btn_h)
        _proxy_end_geo = QtCore.QRect(_clamped_x,
                                       _btn_tl.y() - menu_height,
                                       menu_width, menu_height)

        _menu_bg = QtGui.QColor(30, 30, 35, 245) if is_dark else QtGui.QColor(255, 255, 255, 245)

        # Кнопка затемняется пока прокси анимируется
        _dim_eff = QtWidgets.QGraphicsOpacityEffect(self.attach_btn)
        self.attach_btn.setGraphicsEffect(_dim_eff)
        _dim_anim = QtCore.QPropertyAnimation(_dim_eff, b"opacity")
        _dim_anim.setDuration(80)
        _dim_anim.setStartValue(1.0)
        _dim_anim.setEndValue(0.0)
        _dim_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuart)
        _dim_anim.start()

        open_proxy = _BurstProxy(_menu_bg, _start_geo)
        open_proxy.show()
        open_proxy.raise_()
        _apply_windows_rounded(open_proxy, radius=16)

        _o_geo = QtCore.QPropertyAnimation(open_proxy, b"geometry")
        _o_geo.setDuration(320)
        _o_geo.setStartValue(_start_geo)
        _o_geo.setEndValue(_proxy_end_geo)
        _o_geo.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
        _o_geo.start()
        open_proxy._anims = [_o_geo, _dim_eff, _dim_anim]

        def _on_open_done():
            self._attach_menu_animating = False
            try:
                open_proxy.close()
            except Exception:
                pass
            menu.popup(_proxy_end_geo.topLeft())
            self._apply_menu_blur_effect()

        _o_geo.finished.connect(_on_open_done)

        # ── Обработка действий через сигналы ──
        def _do_search():
            self.use_search = not self.use_search
            print(f"[MENU] Умный поиск {'ВКЛ' if self.use_search else 'ВЫКЛ'}")
            QtCore.QTimer.singleShot(80, lambda: self._show_search_toast(self.use_search))

        search_action.triggered.connect(_do_search)
        file_action.triggered.connect(self.attach_file)
        if clear_action:
            clear_action.triggered.connect(self.clear_attached_file)

        # ─────────────────────────────────────────────────────────────────
        # ЗАКРЫТИЕ: proxy схлопывается обратно в кнопку «+»
        # ─────────────────────────────────────────────────────────────────
        _close_started = [False]

        def _animate_close():
            if _close_started[0]:
                return
            _close_started[0] = True

            cur_geo = menu.geometry()
            try:
                px = menu.grab()
            except Exception:
                px = None

            class _CloseProxy(QtWidgets.QWidget):
                def __init__(self, pixmap, geo):
                    super().__init__(
                        None,
                        QtCore.Qt.WindowType.Tool |
                        QtCore.Qt.WindowType.FramelessWindowHint |
                        QtCore.Qt.WindowType.WindowStaysOnTopHint,
                    )
                    self._px = pixmap
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
                    self.setGeometry(geo)

                def paintEvent(self, event):
                    if not self._px:
                        return
                    p = QtGui.QPainter(self)
                    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                    p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                    r = self.rect()
                    radius = min(20, r.width() // 2, r.height() // 2)
                    path = QtGui.QPainterPath()
                    path.addRoundedRect(QtCore.QRectF(r), radius, radius)
                    p.setClipPath(path)
                    p.drawPixmap(r, self._px)
                    p.end()

            proxy = _CloseProxy(px, cur_geo)
            proxy.show()
            proxy.raise_()
            _apply_windows_rounded(proxy, radius=16)

            _btn_now   = self.attach_btn.mapToGlobal(QtCore.QPoint(0, 0))
            _close_end = QtCore.QRect(_btn_now.x(), _btn_now.y(),
                                       self.attach_btn.width(), self.attach_btn.height())

            _c_geo = QtCore.QPropertyAnimation(proxy, b"geometry")
            _c_geo.setDuration(260)
            _c_geo.setStartValue(cur_geo)
            _c_geo.setEndValue(_close_end)
            _c_geo.setEasingCurve(QtCore.QEasingCurve.Type.InBack)

            _c_eff = QtWidgets.QGraphicsOpacityEffect(proxy)
            proxy.setGraphicsEffect(_c_eff)
            _c_eff.setOpacity(1.0)
            _c_op = QtCore.QPropertyAnimation(_c_eff, b"opacity")
            _c_op.setDuration(260)
            _c_op.setStartValue(1.0)
            _c_op.setKeyValueAt(0.55, 0.95)
            _c_op.setKeyValueAt(0.85, 0.3)
            _c_op.setEndValue(0.0)
            _c_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            def _on_close_done():
                try:
                    proxy.close()
                except Exception:
                    pass
                self._restore_attach_btn_animated()


            _c_geo.finished.connect(_on_close_done)
            self._remove_menu_blur_effect()
            _c_op.start()
            _c_geo.start()
            self._attach_close_proxy_anims = [proxy, _c_op, _c_geo, _c_eff]

        menu.aboutToHide.connect(_animate_close)
    
    def _apply_menu_blur_effect(self):
        """Применить реальный blur эффект через снимок экрана"""
        print("[BLUR] Применяю blur эффект через снимок экрана")
        
        # ✅ Устанавливаем флаг что меню открыто
        self._menu_is_open = True
        
        # ✅ Сохраняем состояние кнопки "вниз" перед blur
        if hasattr(self, 'scroll_to_bottom_btn'):
            self._scroll_btn_was_visible = self.scroll_to_bottom_btn._is_visible_animated
        else:
            self._scroll_btn_was_visible = False
        
        # ═══════════════════════════════════════════════════════════════
        # 1. СОЗДАНИЕ РАЗМЫТОГО СНИМКА ЭКРАНА
        # ═══════════════════════════════════════════════════════════════
        
        # Создаем или переиспользуем overlay
        if not hasattr(self, '_blur_overlay'):
            self._blur_overlay = QtWidgets.QLabel(self)
            self._blur_overlay.setObjectName("blurOverlay")
            self._blur_overlay.setScaledContents(True)
            
            # Создаём opacity эффект для анимации появления
            self._overlay_opacity = QtWidgets.QGraphicsOpacityEffect(self._blur_overlay)
            self._blur_overlay.setGraphicsEffect(self._overlay_opacity)
            self._overlay_opacity.setOpacity(0.0)
        else:
            # Очищаем старый pixmap перед созданием нового
            self._blur_overlay.clear()
        
        # ШАГ 1: Делаем снимок экрана (скрываем overlay если он виден)
        self._blur_overlay.hide()
        QtWidgets.QApplication.processEvents()
        snapshot = self.grab()
        
        # ШАГ 2: Применяем blur к снимку
        # Создаем временный QLabel для применения blur effect
        temp_label = QtWidgets.QLabel()
        temp_label.setPixmap(snapshot)
        temp_label.resize(snapshot.size())
        
        # Применяем blur эффект
        blur_effect = QtWidgets.QGraphicsBlurEffect()
        blur_effect.setBlurRadius(15)  # Средний blur
        temp_label.setGraphicsEffect(blur_effect)
        
        # Рендерим размытый результат в новый pixmap
        blurred_pixmap = QtGui.QPixmap(snapshot.size())
        blurred_pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        
        painter = QtGui.QPainter(blurred_pixmap)
        temp_label.render(painter)
        painter.end()
        
        # Удаляем временный label
        temp_label.deleteLater()
        
        # ШАГ 3: Применяем затемнение поверх размытого снимка
        # Создаём полупрозрачный слой для затемнения
        overlay = QtGui.QPixmap(blurred_pixmap.size())
        is_dark = self.current_theme == "dark"
        
        if is_dark:
            overlay.fill(QtGui.QColor(0, 0, 0, 80))  # Легкое затемнение
        else:
            overlay.fill(QtGui.QColor(255, 255, 255, 80))  # Легкое осветление
        
        # Накладываем затемнение на размытый снимок
        final_painter = QtGui.QPainter(blurred_pixmap)
        final_painter.drawPixmap(0, 0, overlay)
        final_painter.end()
        
        # ШАГ 4: Устанавливаем размытый снимок в overlay
        self._blur_overlay.setPixmap(blurred_pixmap)
        self._blur_overlay.setGeometry(self.rect())
        self._blur_overlay.raise_()
        self._blur_overlay.show()
        
        # Анимация появления overlay
        if not hasattr(self, '_overlay_anim'):
            self._overlay_anim = QtCore.QPropertyAnimation(self._overlay_opacity, b"opacity")
        
        self._overlay_anim.stop()
        self._overlay_anim.setDuration(300)
        self._overlay_anim.setStartValue(0.0)
        self._overlay_anim.setEndValue(1.0)
        self._overlay_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._overlay_anim.start()
        
        # Кнопка «+» управляется через _dim_anim в show_attach_menu — не трогаем
        
        # ═══════════════════════════════════════════════════════════════
        # 3. FADE OUT КНОПКИ "ВНИЗ" (используем её существующий opacity effect)
        # ═══════════════════════════════════════════════════════════════
        if hasattr(self, 'scroll_to_bottom_btn') and self.scroll_to_bottom_btn.isVisible():
            # Останавливаем текущую анимацию
            self.scroll_to_bottom_btn.fade_animation.stop()
            
            # Плавно скрываем кнопку
            self.scroll_to_bottom_btn.fade_animation.setDuration(250)
            self.scroll_to_bottom_btn.fade_animation.setStartValue(
                self.scroll_to_bottom_btn.opacity_effect.opacity()
            )
            self.scroll_to_bottom_btn.fade_animation.setEndValue(0.0)
            self.scroll_to_bottom_btn.fade_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            self.scroll_to_bottom_btn.fade_animation.start()
        
        print("[BLUR] Blur эффект применён, кнопка + скрыта")
    
    def _dim_input_for_generation(self):
        """
        Плавно затемняет поле ввода и кнопку голоса во время генерации ИИ.
        Opacity: 1.0 → 0.35 за 250мс.
        Также блокирует mic_btn программно.
        """
        targets = []
        if hasattr(self, 'input_wrapper'):
            targets.append(self.input_wrapper)
        if hasattr(self, 'mic_btn'):
            targets.append(self.mic_btn)
            try:
                self.mic_btn.setEnabled(False)
            except RuntimeError:
                pass

        self._input_dim_effs = []
        self._input_dim_anims = []

        for w in targets:
            eff = QtWidgets.QGraphicsOpacityEffect(w)
            w.setGraphicsEffect(eff)
            eff.setOpacity(1.0)

            anim = QtCore.QPropertyAnimation(eff, b"opacity")
            anim.setDuration(250)
            anim.setStartValue(1.0)
            anim.setEndValue(0.35)
            anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            anim.start()

            self._input_dim_effs.append(eff)
            self._input_dim_anims.append(anim)

    def _restore_input_after_generation(self):
        """
        Плавно восстанавливает яркость поля ввода и кнопки голоса.
        Opacity: 0.35 → 1.0 за 220мс. Разблокирует mic_btn.
        """
        targets = []
        if hasattr(self, 'input_wrapper'):
            targets.append(self.input_wrapper)
        if hasattr(self, 'mic_btn'):
            targets.append(self.mic_btn)

        restore_anims = []
        restore_effs = []

        for w in targets:
            # Берём текущий эффект или создаём новый
            cur_eff = w.graphicsEffect()
            if not isinstance(cur_eff, QtWidgets.QGraphicsOpacityEffect):
                cur_eff = QtWidgets.QGraphicsOpacityEffect(w)
                w.setGraphicsEffect(cur_eff)

            cur_op = cur_eff.opacity()

            anim = QtCore.QPropertyAnimation(cur_eff, b"opacity")
            anim.setDuration(220)
            anim.setStartValue(cur_op)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

            def _make_cleanup(widget, effect, animation):
                def _cleanup():
                    try:
                        widget.setGraphicsEffect(None)
                    except RuntimeError:
                        pass
                animation.finished.connect(_cleanup)
            _make_cleanup(w, cur_eff, anim)

            anim.start()
            restore_anims.append(anim)
            restore_effs.append(cur_eff)

        # Разблокируем mic_btn после анимации
        if hasattr(self, 'mic_btn'):
            def _unlock_mic():
                try:
                    self.mic_btn.setEnabled(True)
                except RuntimeError:
                    pass
            QtCore.QTimer.singleShot(220, _unlock_mic)

        # Держим ссылки
        self._input_restore_anims = restore_anims
        self._input_restore_effs = restore_effs

    def _apply_regen_blur_effect(self):
        """
        Плавный blur-оверлей на время перегенерации ответа.
        Аналог _apply_menu_blur_effect, но:
         - не прячет кнопку «+»
         - не ставит флаг _menu_is_open
         - чуть мягче (blurRadius=10 вместо 15)
        """
        print("[REGEN_BLUR] Применяю blur для перегенерации")

        if not hasattr(self, '_regen_blur_overlay'):
            self._regen_blur_overlay = QtWidgets.QLabel(self)
            self._regen_blur_overlay.setObjectName("regenBlurOverlay")
            self._regen_blur_overlay.setScaledContents(True)
            self._regen_blur_eff = QtWidgets.QGraphicsOpacityEffect(self._regen_blur_overlay)
            self._regen_blur_overlay.setGraphicsEffect(self._regen_blur_eff)
            self._regen_blur_eff.setOpacity(0.0)
        else:
            self._regen_blur_overlay.clear()

        self._regen_blur_overlay.hide()
        QtWidgets.QApplication.processEvents()
        snapshot = self.grab()

        temp = QtWidgets.QLabel()
        temp.setPixmap(snapshot)
        temp.resize(snapshot.size())
        blur_fx = QtWidgets.QGraphicsBlurEffect()
        blur_fx.setBlurRadius(10)
        temp.setGraphicsEffect(blur_fx)

        blurred = QtGui.QPixmap(snapshot.size())
        blurred.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(blurred)
        temp.render(p)
        p.end()
        temp.deleteLater()

        # Лёгкое затемнение / осветление поверх
        tint = QtGui.QPixmap(blurred.size())
        if self.current_theme == "dark":
            tint.fill(QtGui.QColor(0, 0, 0, 55))
        else:
            tint.fill(QtGui.QColor(255, 255, 255, 55))
        p2 = QtGui.QPainter(blurred)
        p2.drawPixmap(0, 0, tint)
        p2.end()

        self._regen_blur_overlay.setPixmap(blurred)
        self._regen_blur_overlay.setGeometry(self.rect())
        # Поднимаем оверлей, но НЕ выше кнопки отправки — поле ввода блокировано,
        # но пользователь видит кнопку стоп.
        self._regen_blur_overlay.raise_()
        self._regen_blur_overlay.show()

        if not hasattr(self, '_regen_blur_anim'):
            self._regen_blur_anim = QtCore.QPropertyAnimation(self._regen_blur_eff, b"opacity")
        self._regen_blur_anim.stop()
        self._regen_blur_anim.setDuration(280)
        self._regen_blur_anim.setStartValue(0.0)
        self._regen_blur_anim.setEndValue(1.0)
        self._regen_blur_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._regen_blur_anim.start()
        print("[REGEN_BLUR] Blur оверлей показан")

    def _remove_regen_blur_effect(self):
        """Плавно убирает blur-оверлей после завершения перегенерации."""
        print("[REGEN_BLUR] Убираю blur оверлей")
        if not hasattr(self, '_regen_blur_anim') or not hasattr(self, '_regen_blur_overlay'):
            return

        cur_op = self._regen_blur_eff.opacity() if hasattr(self, '_regen_blur_eff') else 1.0
        self._regen_blur_anim.stop()
        self._regen_blur_anim.setDuration(220)
        self._regen_blur_anim.setStartValue(cur_op)
        self._regen_blur_anim.setEndValue(0.0)
        self._regen_blur_anim.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

        try:
            self._regen_blur_anim.finished.disconnect()
        except (RuntimeError, TypeError):
            pass

        def _cleanup():
            try:
                self._regen_blur_overlay.hide()
                self._regen_blur_overlay.clear()
                print("[REGEN_BLUR] Overlay скрыт")
            except RuntimeError:
                pass

        self._regen_blur_anim.finished.connect(_cleanup)
        self._regen_blur_anim.start()

    def _remove_menu_blur_effect(self):
        """Убрать overlay эффект и восстановить кнопку + при закрытии меню"""
        print("[BLUR] Убираю overlay эффект")
        
        # ✅ Устанавливаем флаг что меню закрыто
        self._menu_is_open = False
        
        # ═══════════════════════════════════════════════════════════════
        # 1. FADE OUT OVERLAY
        # ═══════════════════════════════════════════════════════════════
        if hasattr(self, '_overlay_anim') and hasattr(self, '_blur_overlay'):
            # Получаем текущее значение opacity
            current_opacity = self._overlay_opacity.opacity()
            
            self._overlay_anim.stop()
            self._overlay_anim.setDuration(250)
            self._overlay_anim.setStartValue(current_opacity)
            self._overlay_anim.setEndValue(0.0)
            self._overlay_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            
            # После завершения анимации - скрываем overlay
            def cleanup_overlay():
                # ✅ Проверяем что меню действительно закрыто
                if hasattr(self, '_menu_is_open') and self._menu_is_open:
                    print("[BLUR] Пропускаю cleanup - меню снова открыто")
                    return
                
                if hasattr(self, '_blur_overlay'):
                    self._blur_overlay.hide()
                    # Очищаем pixmap для освобождения памяти
                    self._blur_overlay.clear()
                    print("[BLUR] Overlay скрыт и очищен")
            
            # Отключаем предыдущие коллбэки
            try:
                self._overlay_anim.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            
            self._overlay_anim.finished.connect(cleanup_overlay)
            self._overlay_anim.start()
        
        # Кнопка «+» восстанавливается через _restore_attach_btn_animated — не трогаем
        
        # ═══════════════════════════════════════════════════════════════
        # 3. FADE IN КНОПКИ "ВНИЗ" (восстанавливаем если была видна до blur)
        # ═══════════════════════════════════════════════════════════════
        if hasattr(self, 'scroll_to_bottom_btn'):
            # Останавливаем текущую анимацию
            self.scroll_to_bottom_btn.fade_animation.stop()
            
            # ✅ ИСПРАВЛЕНИЕ: Используем сохраненное состояние
            if hasattr(self, '_scroll_btn_was_visible') and self._scroll_btn_was_visible:
                print("[BLUR] Восстанавливаю кнопку 'вниз' - она была видна до blur")
                # Плавно восстанавливаем видимость
                self.scroll_to_bottom_btn.fade_animation.setDuration(300)
                self.scroll_to_bottom_btn.fade_animation.setStartValue(
                    self.scroll_to_bottom_btn.opacity_effect.opacity()
                )
                self.scroll_to_bottom_btn.fade_animation.setEndValue(1.0)
                self.scroll_to_bottom_btn.fade_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                self.scroll_to_bottom_btn.fade_animation.start()
            else:
                print("[BLUR] Кнопка 'вниз' не восстанавливается - она не была видна до blur")
        
        print("[BLUR] Кнопка + восстановлена")
    

    # ═══════════════════════════════════════════════════════════════
    # МЕТОДЫ УПРАВЛЕНИЯ ФАЙЛАМИ ЧАТОВ
    # ═══════════════════════════════════════════════════════════════
    
    def start_status_animation(self):
        """Показывает виджет-заглушку пузыря ИИ пока модель думает."""
        # Убираем старый виджет если вдруг остался
        self.stop_status_animation()

        # Читаем настройки темы
        try:
            _theme = getattr(self, 'current_theme', 'light')
            _glass = getattr(self, 'current_liquid_glass', True)
        except Exception:
            _theme = 'light'
            _glass = True

        # Имя текущей модели
        try:
            _model_name = get_current_display_name()
        except Exception:
            _model_name = "ИИ"

        self._thinking_bubble = ThinkingBubbleWidget(
            model_name=_model_name,
            theme=_theme,
            liquid_glass=_glass,
            parent=self.messages_widget,
        )
        self.messages_layout.addWidget(self._thinking_bubble)
        self._thinking_bubble.show()

        # Всегда скроллим вниз — пользователь только что отправил сообщение.
        # Задержка 360ms: больше чем анимация автоскролла (260ms + 20ms старт + запас),
        # чтобы она не перезаписала позицию назад к старому максимуму.
        def _scroll():
            try:
                self.messages_layout.activate()
                sb = self.scroll_area.verticalScrollBar()
                sb.setValue(sb.maximum())
            except Exception:
                pass
        QtCore.QTimer.singleShot(360, _scroll)

    def stop_status_animation(self):
        """Убирает виджет-заглушку пузыря ИИ (плавное исчезновение)."""
        self.status_label.clear()
        self.status_label.setText("")

        # Останавливаем стрим если он шёл
        if hasattr(self, '_stream_flush_timer'):
            self._stream_flush_timer.stop()
        self._stream_active = False
        self._stream_buf    = ""

        bubble = getattr(self, '_thinking_bubble', None)
        if bubble is None:
            return
        self._thinking_bubble = None

        def _remove():
            try:
                self.messages_layout.removeWidget(bubble)
                bubble.setParent(None)
                bubble.deleteLater()
            except Exception:
                pass

        try:
            bubble.fade_out_and_remove(on_done=_remove)
        except Exception:
            _remove()

    # ──────────────────────────────────────────────────────────────────────────
    # СТРИМИНГ: побуквенный вывод токенов от Ollama
    # ──────────────────────────────────────────────────────────────────────────

    def _on_stream_chunk(self, token: str):
        """
        Слот — вызывается из AIWorker для каждого токена.
        Работает в GUI-потоке благодаря Qt::AutoConnection.

        Логика:
        1. Первый токен → убираем кружок, создаём пустой пузырь ИИ.
        2. Каждый следующий токен → дописываем в буфер.
        3. Flush-таймер каждые 40 мс → переносит буфер в message_label.
        """
        if not getattr(self, '_stream_active', False):
            # ─── Первый токен: инициализируем стрим ───────────────────────
            self._stream_raw       = ""   # весь накопленный текст
            self._stream_buf       = ""   # буфер между flush-тиками
            self._char_queue       = []   # очередь символов для побуквенного вывода
            self._displayed_text   = ""   # уже отображённый текст

            # Убираем пульсирующий кружок (внутри сбрасывает _stream_active в False)
            self.stop_status_animation()
            # Ставим флаг ПОСЛЕ stop_status_animation — иначе он сбросит его
            self._stream_active    = True

            # Узнаём имя спикера (та же логика что в handle_response)
            try:
                _mk = (self.current_worker.model_key
                       if hasattr(self, 'current_worker') and self.current_worker
                       else llama_handler.CURRENT_AI_MODEL_KEY)
                _spk = llama_handler.SUPPORTED_MODELS.get(
                    _mk,
                    llama_handler.SUPPORTED_MODELS.get(llama_handler.CURRENT_AI_MODEL_KEY)
                )[1]
            except Exception:
                _spk = llama_handler.ASSISTANT_NAME
            self._stream_speaker = _spk

            # Создаём пустой пузырь ИИ (кнопки создаются, но скрыты — покажем при финализации)
            _regen_target = getattr(self, '_regen_target_widget', None)
            if _regen_target is None:
                # Обычный ответ — новый виджет
                self._stream_widget = MessageWidget(
                    _spk, "",
                    add_controls=True,   # кнопки создаются в layout (controls_widget.setVisible будет False по умолчанию)
                    language=self.current_language,
                    main_window=self,
                    parent=self.messages_widget,
                )
                # Скрываем кнопки до финализации
                if hasattr(self._stream_widget, 'controls_widget'):
                    self._stream_widget.controls_widget.setVisible(False)
                # Блокируем пересчёт высоты при первых символах — предотвращаем резкий прыжок
                if hasattr(self._stream_widget, 'message_container'):
                    self._stream_widget.message_container.setMinimumHeight(64)
                self.messages_layout.addWidget(self._stream_widget)
                self._stream_widget.show()
                # Анимация появления
                if hasattr(self._stream_widget, '_start_appear_animation'):
                    QtCore.QTimer.singleShot(20, self._stream_widget._start_appear_animation)
                # Скролл вниз
                def _sc_first():
                    try:
                        self.messages_layout.activate()
                        self.scroll_area.verticalScrollBar().setValue(
                            self.scroll_area.verticalScrollBar().maximum()
                        )
                    except Exception:
                        pass
                QtCore.QTimer.singleShot(40, _sc_first)
            else:
                # Перегенерация — не создаём виджет, handle_response сам обновит
                self._stream_widget = None

            # Запускаем flush-таймер
            if not hasattr(self, '_stream_flush_timer'):
                self._stream_flush_timer = QtCore.QTimer(self)
                self._stream_flush_timer.setInterval(16)
                self._stream_flush_timer.timeout.connect(self._stream_flush)
            self._stream_flush_timer.start()

        # Добавляем токен в буфер и очередь символов
        self._stream_raw += token
        self._stream_buf += token
        self._char_queue.extend(list(token))

    def _stream_flush(self):
        """Вызывается каждые 16 мс — побуквенно выводит символы из очереди."""
        char_queue = getattr(self, '_char_queue', None)
        if not char_queue:
            return
        mw = getattr(self, '_stream_widget', None)
        if mw is None:
            if char_queue is not None:
                char_queue.clear()
            return
        try:
            # Адаптивная скорость: если очередь накопилась — выводим быстрее
            q_len = len(char_queue)
            if q_len > 80:
                chars_per_tick = 6
            elif q_len > 30:
                chars_per_tick = 4
            else:
                chars_per_tick = 2

            batch = char_queue[:chars_per_tick]
            del char_queue[:chars_per_tick]
            self._displayed_text += "".join(batch)
            self._stream_buf = ""

            # Быстрый plain-вывод без markdown (markdown применяется в финале)
            safe = (self._displayed_text
                    .replace('&', '&amp;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;')
                    .replace('\n', '<br>'))

            # Блокируем лишние repaint во время setText
            mw.message_label.setUpdatesEnabled(False)
            mw.message_label.setText(
                f"<b style='color:{mw._speaker_color};'>{mw.speaker}:</b><br>{safe}"
            )
            mw.message_label.setUpdatesEnabled(True)

            # Плавный рост пузыря: фиксируем минимальную высоту, не даём сжиматься
            if hasattr(mw, 'message_container'):
                new_h = mw.message_container.sizeHint().height()
                cur_min = mw.message_container.minimumHeight()
                if new_h > cur_min:
                    mw.message_container.setMinimumHeight(new_h)

            mw.message_label.update()

            # Автоскролл если пользователь внизу
            sb = self.scroll_area.verticalScrollBar()
            if sb.value() >= sb.maximum() - 80:
                sb.setValue(sb.maximum())
        except Exception:
            if char_queue is not None:
                char_queue.clear()

    def toggle_sidebar(self):
        """
        Drawer-анимация боковой панели.

        Sidebar — overlay поверх контента (pos.x: -SIDEBAR_W → 0).
        Shadow — отдельный виджет-градиент (pos.x синхронен с sidebar).
        Fade контента через QGraphicsOpacityEffect — НЕ конфликтует с тенью.

        Открытие : OutBack 360ms (лёгкая пружина) + fade-in 220ms с задержкой 60ms
        Закрытие : InCubic 250ms + fade-out 130ms мгновенно
        """
        is_opening = not self._sidebar_open
        self._sidebar_open = is_opening

        W  = self._SIDEBAR_W
        SW = 22   # ширина shadow-виджета
        h  = self.main_container.height()

        cur_x = self.sidebar.x()
        target_x = 0 if is_opening else -W

        # ── Скрываем панель удаления при закрытии ───────────────────────────
        if not is_opening:
            self.hide_delete_panel()

        # ── Останавливаем предыдущие анимации ────────────────────────────────
        for attr in ('_sb_pos_anim', '_sb_shadow_anim', '_sb_fade_anim',
                     '_sb_dim_anim', 'animation', 'animation2'):
            a = getattr(self, attr, None)
            if a:
                try:
                    a.stop()
                except RuntimeError:
                    pass

        # ════════════════════════════════════════════════════════════════════
        # 1. SLIDE sidebar + shadow — оригинальная анимация OutCubic
        # ════════════════════════════════════════════════════════════════════
        if is_opening:
            dur  = 300
            ease = QtCore.QEasingCurve.Type.OutCubic
        else:
            dur  = 220
            ease = QtCore.QEasingCurve.Type.InOutCubic

        # Sidebar pos animation
        self._sb_pos_anim = QtCore.QPropertyAnimation(self.sidebar, b"pos")
        self._sb_pos_anim.setDuration(dur)
        self._sb_pos_anim.setStartValue(QtCore.QPoint(cur_x, 0))
        self._sb_pos_anim.setEndValue(QtCore.QPoint(target_x, 0))
        self._sb_pos_anim.setEasingCurve(ease)

        # Shadow widget pos animation (прямо справа от sidebar)
        cur_shadow_x = cur_x + W
        target_shadow_x = target_x + W
        self._sb_shadow_widget.setGeometry(cur_shadow_x, 0, SW, h)

        self._sb_shadow_anim = QtCore.QPropertyAnimation(self._sb_shadow_widget, b"pos")
        self._sb_shadow_anim.setDuration(dur)
        self._sb_shadow_anim.setStartValue(QtCore.QPoint(cur_shadow_x, 0))
        self._sb_shadow_anim.setEndValue(QtCore.QPoint(target_shadow_x, 0))
        self._sb_shadow_anim.setEasingCurve(ease)

        # Обратная совместимость для open_settings
        self.animation  = self._sb_pos_anim
        self.animation2 = self._sb_pos_anim

        # ════════════════════════════════════════════════════════════════════
        # 2. Без fade контента — чистый слайд как в оригинале
        # ════════════════════════════════════════════════════════════════════
        self._sb_fade_anim = None  # не используется

        # ════════════════════════════════════════════════════════════════════
        # 3. DIM overlay
        # ════════════════════════════════════════════════════════════════════
        is_dark = getattr(self, 'current_theme', 'light') == 'dark'
        dim_color = "rgba(0,0,0,18)" if is_dark else "rgba(0,0,0,12)"
        self._dim_overlay.setStyleSheet(f"background:{dim_color}; border:none;")

        if not hasattr(self, '_dim_opacity_eff') or self._dim_opacity_eff is None:
            self._dim_opacity_eff = QtWidgets.QGraphicsOpacityEffect(self._dim_overlay)
            self._dim_overlay.setGraphicsEffect(self._dim_opacity_eff)

        old_dim = getattr(self, '_sb_dim_anim', None)
        if old_dim:
            try: old_dim.stop()
            except RuntimeError: pass

        if is_opening:
            self._dim_overlay.setGeometry(self.main_container.rect())
            # Поднимаем sidebar ПЕРЕД stackUnder, иначе при первом открытии
            # sidebar окажется ниже central (central добавляется в layout позже всех),
            # и stackUnder поместит overlay ниже central — клики проваливаются сквозь.
            self.sidebar.raise_()
            self._dim_overlay.stackUnder(self.sidebar)
            self._dim_overlay.show()
            self.sidebar.raise_()
            self._sb_shadow_widget.raise_()

            self._dim_opacity_eff.setOpacity(0.0)
            self._sb_dim_anim = QtCore.QPropertyAnimation(self._dim_opacity_eff, b"opacity")
            self._sb_dim_anim.setDuration(360)
            self._sb_dim_anim.setStartValue(0.0)
            self._sb_dim_anim.setEndValue(1.0)
            self._sb_dim_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
            self._sb_dim_anim.start()
        else:
            self._sb_dim_anim = QtCore.QPropertyAnimation(self._dim_opacity_eff, b"opacity")
            self._sb_dim_anim.setDuration(250)
            self._sb_dim_anim.setStartValue(self._dim_opacity_eff.opacity())
            self._sb_dim_anim.setEndValue(0.0)
            self._sb_dim_anim.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)
            self._sb_dim_anim.finished.connect(lambda: self._dim_overlay.hide())
            self._sb_dim_anim.start()

        # ════════════════════════════════════════════════════════════════════
        # 4. CLEANUP по завершении
        # ════════════════════════════════════════════════════════════════════
        if is_opening:
            self._sb_shadow_widget.show()
        else:
            def _on_close_done():
                try:
                    self._sb_shadow_widget.hide()
                    self._sb_shadow_widget.move(-22, 0)
                except RuntimeError:
                    pass
            self._sb_pos_anim.finished.connect(_on_close_done)

        # ── Запуск ───────────────────────────────────────────────────────────
        self._sb_pos_anim.start()
        self._sb_shadow_anim.start()

        print(f"[SIDEBAR] {'▶ Открываю' if is_opening else '◀ Закрываю'} drawer")



    def manual_scroll_to_bottom(self):
        """
        Ручной скролл вниз при нажатии на кнопку с ПЛАВНОЙ анимацией.
        НЕ автоматический - только по клику пользователя.
        
        ОБНОВЛЕНИЕ LAYOUT:
        Когда пользователь нажимает кнопку "вниз", делаем полное
        обновление layout чтобы все накопленные сообщения отобразились корректно.
        
        ПЛАВНЫЙ СКРОЛЛ:
        Используем QPropertyAnimation для плавного скролла вниз.
        """
        print("[MANUAL_SCROLL] 🔄 Обновление layout перед скроллом вниз...")
        
        # Полное обновление layout для корректного отображения всех сообщений
        self.messages_layout.invalidate()
        self.messages_layout.activate()
        self.messages_widget.updateGeometry()
        # ✅ ИСПРАВЛЕНИЕ ДЁРГАНЬЯ: update() вместо repaint() + processEvents()
        self.scroll_area.viewport().update()
        
        # ═══════════════════════════════════════════════════════════════
        # ПЛАВНЫЙ СКРОЛЛ ВНИЗ
        # ═══════════════════════════════════════════════════════════════
        scrollbar = self.scroll_area.verticalScrollBar()
        
        # Создаём анимацию скролла
        if not hasattr(self, '_scroll_animation'):
            self._scroll_animation = QtCore.QPropertyAnimation(scrollbar, b"value")
        
        self._scroll_animation.stop()  # Останавливаем предыдущую если есть
        self._scroll_animation.setDuration(600)  # 600ms - более плавная и приятная анимация
        self._scroll_animation.setStartValue(scrollbar.value())
        self._scroll_animation.setEndValue(scrollbar.maximum())
        self._scroll_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutExpo)  # Более естественная кривая
        
        # Когда скролл завершится - плавно скрываем кнопку
        def on_scroll_finished():
            self.scroll_to_bottom_btn.smooth_hide()
        
        # Отключаем старый обработчик если был
        try:
            self._scroll_animation.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        
        self._scroll_animation.finished.connect(on_scroll_finished)
        self._scroll_animation.start()
        
        print("[MANUAL_SCROLL] ✓ Запущен плавный скролл вниз")
    
    def update_scroll_button_visibility(self):
        """
        Обновить видимость overlay-кнопки "вниз" на основе положения scrollBar.
        
        ═══ ПОЛНОСТЬЮ ПАССИВНЫЙ OVERLAY - АРХИТЕКТУРА ═══
        
        КРИТИЧНО - ПРАВИЛА ПАССИВНОСТИ:
        1. НЕ подключен к сигналам scrollbar (valueChanged, rangeChanged)
        2. Вызывается ТОЛЬКО явно:
           - После завершения layout в add_message_widget()
           - После ручного скролла в _update_button_after_scroll()
           - При resize окна в eventFilter
        3. ТОЛЬКО читает состояние scrollbar - НЕ изменяет его
        4. ТОЛЬКО меняет visibility (show/hide) - НЕ вызывает:
           - update(), repaint()
           - updateGeometry(), adjustSize()
           - invalidate(), activate() на любом layout
           - update_position() (позиция обновляется только в resize)
        
        ГАРАНТИИ:
        - НЕ влияет на layout сообщений
        - НЕ вызывает пересчёт геометрии
        - НЕ создаёт race condition с layout-pass
        - Layout уже завершён через adjustSize() до вызова этой функции
        
        ЛОГИКА:
        - ScrollBar внизу → hide()
        - ScrollBar не внизу → show()
        - Контент помещается → hide()
        """
        # Проверяем что мы на странице чата, а не настроек
        if hasattr(self, 'content_stack') and self.content_stack.currentIndex() != 0:
            self.scroll_to_bottom_btn.smooth_hide()
            return
        
        scrollbar = self.scroll_area.verticalScrollBar()
        
        # Проверяем что контент больше viewport
        if scrollbar.maximum() == 0:
            self.scroll_to_bottom_btn.smooth_hide()
            return
        
        # Если автоскролл включён — кнопка всегда скрыта
        if getattr(self, "auto_scroll_enabled", False):
            self.scroll_to_bottom_btn.smooth_hide()
            return

        # Показываем кнопку если НЕ внизу (с порогом 10px)
        if scrollbar.value() < scrollbar.maximum() - 10:
            # ПЛАВНОЕ ПОЯВЛЕНИЕ вместо резкого show()
            self.scroll_to_bottom_btn.smooth_show()
        else:
            # ПЛАВНОЕ ИСЧЕЗНОВЕНИЕ вместо резкого hide()
            self.scroll_to_bottom_btn.smooth_hide()
    
    def check_has_chats_with_messages(self) -> bool:
        """
        Проверить есть ли хоть один чат с сообщениями.
        Если все чаты пустые (или чатов вообще нет) — возвращает False.
        """
        try:
            import sqlite3 as _sq
            import chat_manager as _cm
            conn = _sq.connect(_cm.CHATS_DB)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM chat_messages")
            count = cur.fetchone()[0]
            conn.close()
            return count > 0
        except Exception as e:
            print(f"[CHECK_CHATS] Ошибка: {e}")
            return False

    def open_settings(self):
        """Открыть настройки — плавный crossfade + мягкий slide-up."""
        if getattr(self, '_settings_transitioning', False):
            return
        self._settings_transitioning = True

        if hasattr(self, 'scroll_to_bottom_btn'):
            self.scroll_to_bottom_btn.smooth_hide()

        if hasattr(self, 'menu_btn'):
            try:
                self.menu_btn.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.menu_btn.clicked.connect(self.close_settings)

        if hasattr(self, 'settings_view'):
            self.settings_view.apply_settings_styles()
            self.settings_view.update_delete_all_btn_state(
                self.check_has_chats_with_messages()
            )

        def _run():
            sv = getattr(self, 'settings_view', None)
            cs = getattr(self, 'content_stack', None)
            if sv is None or cs is None:
                self._settings_transitioning = False
                return

            chat_w = cs.widget(0)
            h = cs.height()

            # ── Fade-out чата (мягко) ────────────────────────────────────────
            eff_chat = QtWidgets.QGraphicsOpacityEffect(chat_w)
            chat_w.setGraphicsEffect(eff_chat)

            ao_op = QtCore.QPropertyAnimation(eff_chat, b"opacity")
            ao_op.setDuration(180)
            ao_op.setStartValue(1.0)
            ao_op.setEndValue(0.0)
            ao_op.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)

            def _show_settings():
                try:
                    chat_w.setGraphicsEffect(None)
                except RuntimeError:
                    pass
                for attr in ('scroll_area', 'title_label', 'clear_btn', 'input_container'):
                    w = getattr(self, attr, None)
                    if w: w.hide()

                cs.setCurrentIndex(1)
                sv.scroll_to_top()   # всегда открываем с самого верха
                OFFSET = max(24, h // 14)   # небольшое смещение — не резкое
                sv.move(0, OFFSET)
                sv.show()

                # ── Slide-up (маленький) + fade-in настроек ──────────────
                eff_sv = QtWidgets.QGraphicsOpacityEffect(sv)
                sv.setGraphicsEffect(eff_sv)
                eff_sv.setOpacity(0.0)

                a_op = QtCore.QPropertyAnimation(eff_sv, b"opacity")
                a_op.setDuration(380)
                a_op.setStartValue(0.0)
                a_op.setEndValue(1.0)
                a_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

                a_pos = QtCore.QPropertyAnimation(sv, b"pos")
                a_pos.setDuration(400)
                a_pos.setStartValue(QtCore.QPoint(0, OFFSET))
                a_pos.setEndValue(QtCore.QPoint(0, 0))
                a_pos.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

                grp = QtCore.QParallelAnimationGroup(self)
                grp.addAnimation(a_op)
                grp.addAnimation(a_pos)

                def _done():
                    try:
                        sv.setGraphicsEffect(None)
                        sv.move(0, 0)
                    except RuntimeError:
                        pass
                    self._settings_transitioning = False

                grp.finished.connect(_done)
                self._settings_open_grp = grp
                grp.start()

            ao_op.finished.connect(_show_settings)
            self._settings_chat_out_anim = ao_op
            ao_op.start()

        if getattr(self, '_sidebar_open', False):
            self.toggle_sidebar()
            QtCore.QTimer.singleShot(240, _run)
        else:
            QtCore.QTimer.singleShot(10, _run)

    def close_settings(self):
        """Закрыть настройки — мягкий fade-out вниз, чат плавно появляется."""
        if getattr(self, '_settings_transitioning', False):
            return
        self._settings_transitioning = True

        sv = getattr(self, 'settings_view', None)
        cs = getattr(self, 'content_stack', None)
        if sv is None or cs is None:
            self._settings_transitioning = False
            return

        if hasattr(self, 'menu_btn'):
            try:
                self.menu_btn.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.menu_btn.clicked.connect(self.toggle_sidebar)

        h = cs.height()
        OFFSET = max(24, h // 14)

        # ── Fade-out + мягкий slide-down настроек ───────────────────────────
        eff_sv = QtWidgets.QGraphicsOpacityEffect(sv)
        sv.setGraphicsEffect(eff_sv)

        a_op = QtCore.QPropertyAnimation(eff_sv, b"opacity")
        a_op.setDuration(220)
        a_op.setStartValue(1.0)
        a_op.setEndValue(0.0)
        a_op.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)

        a_pos = QtCore.QPropertyAnimation(sv, b"pos")
        a_pos.setDuration(240)
        a_pos.setStartValue(QtCore.QPoint(0, 0))
        a_pos.setEndValue(QtCore.QPoint(0, OFFSET))
        a_pos.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)

        grp_out = QtCore.QParallelAnimationGroup(self)
        grp_out.addAnimation(a_op)
        grp_out.addAnimation(a_pos)

        def _switch():
            try:
                sv.setGraphicsEffect(None)
                sv.move(0, 0)
            except RuntimeError:
                pass

            cs.setCurrentIndex(0)
            for attr in ('scroll_area', 'title_label', 'clear_btn', 'input_container'):
                w = getattr(self, attr, None)
                if w: w.show()

            # ── Fade-in чата ─────────────────────────────────────────────
            chat_w = cs.widget(0)
            eff_in = QtWidgets.QGraphicsOpacityEffect(chat_w)
            chat_w.setGraphicsEffect(eff_in)
            eff_in.setOpacity(0.0)

            a_in_op = QtCore.QPropertyAnimation(eff_in, b"opacity")
            a_in_op.setDuration(320)
            a_in_op.setStartValue(0.0)
            a_in_op.setEndValue(1.0)
            a_in_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

            def _done():
                try:
                    chat_w.setGraphicsEffect(None)
                except RuntimeError:
                    pass
                self._settings_transitioning = False
                QtCore.QTimer.singleShot(80, lambda: QtCore.QMetaObject.invokeMethod(
                    self, "_update_button_after_scroll",
                    QtCore.Qt.ConnectionType.QueuedConnection
                ))

            a_in_op.finished.connect(_done)
            self._settings_close_in_anim = a_in_op
            a_in_op.start()

        grp_out.finished.connect(_switch)
        self._settings_close_grp = grp_out
        grp_out.start()

    def _after_close_settings(self):
        """Устарело — совместимость."""
        pass

    def _animate_stack_transition(self, from_index: int, to_index: int, callback=None):
        """Устарело — совместимость."""
        if hasattr(self, 'content_stack'):
            self.content_stack.setCurrentIndex(to_index)
        if callback:
            callback()



    def on_settings_applied(self, settings: dict):
        """Обработка применения настроек с плавной crossfade анимацией смены темы"""
        print(f"[SETTINGS] Применены настройки: {settings}")
        
        # Получаем параметры
        theme = settings.get("theme", "light")
        liquid_glass = settings.get("liquid_glass", True)
        self.auto_scroll_enabled = settings.get("auto_scroll", False)
        print(f"[SETTINGS] Автоскролл: {'включён' if self.auto_scroll_enabled else 'выключен'}")

        # Применяем видимость элементов управления сообщений
        show_tts       = settings.get("show_tts",       True)
        show_regen     = settings.get("show_regen",     True)
        show_copy      = settings.get("show_copy",      True)
        show_user_copy = settings.get("show_user_copy", True)
        show_user_edit = settings.get("show_user_edit", True)
        # Обновляем существующие сообщения
        self._apply_element_visibility(show_tts, show_regen, show_copy, show_user_copy, show_user_edit)
        # Сохраняем для новых сообщений
        self._ui_show_tts       = show_tts
        self._ui_show_regen     = show_regen
        self._ui_show_copy      = show_copy
        self._ui_show_user_copy = show_user_copy
        self._ui_show_user_edit = show_user_edit

        
        # Проверяем, изменилась ли тема
        theme_changed = (self.current_theme != theme)
        glass_changed = (self.current_liquid_glass != liquid_glass)
        
        if theme_changed or glass_changed:
            # КРИТИЧНО: Останавливаем и очищаем предыдущую анимацию если она ещё идёт
            if hasattr(self, '_crossfade_group') and self._crossfade_group:
                self._crossfade_group.stop()
                self._crossfade_group.deleteLater()
                self._crossfade_group = None
            
            if hasattr(self, '_old_overlay') and self._old_overlay:
                self._old_overlay.deleteLater()
                self._old_overlay = None
            
            if hasattr(self, '_new_overlay') and self._new_overlay:
                self._new_overlay.deleteLater()
                self._new_overlay = None
            
            # ПЛАВНАЯ CROSSFADE АНИМАЦИЯ СМЕНЫ ТЕМЫ
            print(f"[SETTINGS] Запускаю crossfade анимацию: {self.current_theme} → {theme}")
            
            # ШАГ 1: Делаем скриншот СТАРОЙ темы
            old_pixmap = self.grab()
            
            # ШАГ 2: Применяем НОВУЮ тему (мгновенно, но скрыто под оверлеем)
            self.current_theme = theme
            self.current_liquid_glass = liquid_glass
            self.apply_styles(theme=theme, liquid_glass=liquid_glass)
            
            # Обновляем цвета файлового чипа при смене темы
            if hasattr(self, 'file_chip_container') and self.file_chip_container.isVisible():
                is_dark = (theme == 'dark')
                if is_dark:
                    self.file_chip.setStyleSheet("""
                        #fileChip {
                            background: rgba(102, 126, 234, 0.20);
                            border: 1px solid rgba(102, 126, 234, 0.40);
                            border-radius: 14px;
                            padding: 2px 6px;
                        }
                    """)
                    self.file_chip_label.setStyleSheet("color: #8fa3f5; background: transparent; border: none;")
                    self.file_chip_remove_btn.setStyleSheet("""
                        QPushButton {
                            background: rgba(102, 126, 234, 0.25);
                            color: #8fa3f5;
                            border: none;
                            border-radius: 11px;
                        }
                        QPushButton:hover {
                            background: rgba(239, 68, 68, 0.30);
                            color: #f87171;
                        }
                    """)
                else:
                    self.file_chip.setStyleSheet("""
                        #fileChip {
                            background: rgba(102, 126, 234, 0.15);
                            border: 1px solid rgba(102, 126, 234, 0.35);
                            border-radius: 14px;
                            padding: 2px 6px;
                        }
                    """)
                    self.file_chip_label.setStyleSheet("color: #667eea; background: transparent; border: none;")
                    self.file_chip_remove_btn.setStyleSheet("""
                        QPushButton {
                            background: rgba(102, 126, 234, 0.2);
                            color: #667eea;
                            border: none;
                            border-radius: 11px;
                        }
                        QPushButton:hover {
                            background: rgba(239, 68, 68, 0.25);
                            color: #ef4444;
                        }
                    """)
            
            # Обновляем стили всех существующих виджетов сообщений
            if hasattr(self, 'messages_layout'):
                for i in range(self.messages_layout.count()):
                    item = self.messages_layout.itemAt(i)
                    if item:
                        w = item.widget()
                        if w and hasattr(w, 'update_message_styles'):
                            try:
                                w.update_message_styles(theme, liquid_glass)
                            except RuntimeError:
                                pass

            # Обновляем стили кнопки "вниз"
            if hasattr(self, 'scroll_to_bottom_btn'):
                self.scroll_to_bottom_btn.apply_theme_styles(theme=theme, liquid_glass=liquid_glass)
            # Обновляем тему делегата списка чатов
            if hasattr(self, '_chat_list_delegate'):
                self._chat_list_delegate.set_theme(theme)
                self.chats_list.update()
            
            # Обновляем стили настроек
            if hasattr(self, 'settings_view'):
                self.settings_view.apply_settings_styles()
            
            # Принудительно обновляем всё
            self.update()
            QtWidgets.QApplication.processEvents()
            
            # ШАГ 3: Делаем скриншот НОВОЙ темы
            new_pixmap = self.grab()
            
            # ШАГ 4: Создаём два оверлея для crossfade
            # Оверлей со старой темой (будет исчезать)
            old_overlay = QtWidgets.QLabel(self)
            old_overlay.setPixmap(old_pixmap)
            old_overlay.setGeometry(0, 0, self.width(), self.height())
            old_overlay.setScaledContents(True)
            old_overlay.show()
            old_overlay.raise_()
            
            # Оверлей с новой темой (будет проявляться)
            new_overlay = QtWidgets.QLabel(self)
            new_overlay.setPixmap(new_pixmap)
            new_overlay.setGeometry(0, 0, self.width(), self.height())
            new_overlay.setScaledContents(True)
            new_overlay.show()
            new_overlay.raise_()
            
            # Эффекты прозрачности
            old_effect = QtWidgets.QGraphicsOpacityEffect(old_overlay)
            old_overlay.setGraphicsEffect(old_effect)
            old_effect.setOpacity(1.0)
            
            new_effect = QtWidgets.QGraphicsOpacityEffect(new_overlay)
            new_overlay.setGraphicsEffect(new_effect)
            new_effect.setOpacity(0.0)
            
            # ШАГ 5: Анимация crossfade
            # Старая тема исчезает
            old_fade = QtCore.QPropertyAnimation(old_effect, b"opacity")
            old_fade.setDuration(400)  # 400ms
            old_fade.setStartValue(1.0)
            old_fade.setEndValue(0.0)
            old_fade.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)
            
            # Новая тема появляется
            new_fade = QtCore.QPropertyAnimation(new_effect, b"opacity")
            new_fade.setDuration(400)  # 400ms
            new_fade.setStartValue(0.0)
            new_fade.setEndValue(1.0)
            new_fade.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)
            
            # Группируем анимации для синхронного запуска
            animation_group = QtCore.QParallelAnimationGroup(self)
            animation_group.addAnimation(old_fade)
            animation_group.addAnimation(new_fade)
            
            def on_crossfade_finished():
                # Удаляем оверлеи
                old_overlay.deleteLater()
                new_overlay.deleteLater()
                print("[SETTINGS] ✓ Crossfade анимация завершена")
                
                # Очищаем ссылки
                self._old_overlay = None
                self._new_overlay = None
                self._crossfade_group = None
            
            animation_group.finished.connect(on_crossfade_finished)
            animation_group.start()
            
            # Сохраняем ссылки
            self._crossfade_group = animation_group
            self._old_overlay = old_overlay
            self._new_overlay = new_overlay
            
        else:
            # Если тема не изменилась, просто применяем стили без анимации
            self.current_theme = theme
            self.current_liquid_glass = liquid_glass
            
            self.apply_styles(theme=theme, liquid_glass=liquid_glass)
            
            # Обновляем стили всех существующих виджетов сообщений
            if hasattr(self, 'messages_layout'):
                for i in range(self.messages_layout.count()):
                    item = self.messages_layout.itemAt(i)
                    if item:
                        w = item.widget()
                        if w and hasattr(w, 'update_message_styles'):
                            try:
                                w.update_message_styles(theme, liquid_glass)
                            except RuntimeError:
                                pass

            # Обновляем стили кнопки "вниз"
            if hasattr(self, 'scroll_to_bottom_btn'):
                self.scroll_to_bottom_btn.apply_theme_styles(theme=theme, liquid_glass=liquid_glass)
                print("[SETTINGS] ✓ Стили кнопки 'вниз' обновлены")
            
            # Обновляем стили настроек
            if hasattr(self, 'settings_view'):
                self.settings_view.apply_settings_styles()
        
        print("[SETTINGS] ✓ Стили успешно обновлены")


    def show_delete_panel(self, pos):
        """Показать контекстное меню при правом клике на чат"""
        item = self.chats_list.itemAt(pos)
        if not item:
            return
        
        chat_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Создаём контекстное меню
        context_menu = QtWidgets.QMenu(self)
        
        # Адаптивные стили в зависимости от темы
        if is_dark:
            context_menu.setStyleSheet("""
                QMenu {
                    background-color: rgba(30, 30, 35, 0.85);
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 12px;
                    padding: 6px;
                }
                QMenu::item {
                    padding: 10px 20px;
                    border-radius: 8px;
                    color: #e0e0e0;
                }
                QMenu::item:selected {
                    background-color: rgba(220, 38, 38, 0.25);
                    color: #ff6b6b;
                }
            """)
        else:
            context_menu.setStyleSheet("""
                QMenu {
                    background-color: rgba(255, 255, 255, 0.72);
                    border: 1px solid rgba(255, 255, 255, 0.85);
                    border-radius: 12px;
                    padding: 6px;
                }
                QMenu::item {
                    padding: 10px 20px;
                    border-radius: 8px;
                    color: #2d3748;
                }
                QMenu::item:selected {
                    background-color: rgba(239, 68, 68, 0.15);
                    color: #dc2626;
                }
            """)
        
        # Пункт "Удалить чат"
        delete_action = context_menu.addAction("🗑️ Удалить чат")
        
        # Показываем меню и обрабатываем выбор
        action = context_menu.exec(self.chats_list.mapToGlobal(pos))

        # ── Восстанавливаем выделение на реально активном чате ──────────
        # Правый клик визуально выделяет item в QListWidget, но switch_chat
        # не вызывается — поэтому вручную возвращаем курсор к current_chat_id.
        for _i in range(self.chats_list.count()):
            _it = self.chats_list.item(_i)
            if _it and _it.data(QtCore.Qt.ItemDataRole.UserRole) == self.current_chat_id:
                self.chats_list.setCurrentItem(_it)
                break

        if action == delete_action:
            self.delete_chat_by_id(chat_id)

    def hide_delete_panel(self):
        """Скрыть панель удаления"""
        if self.delete_panel.width() == 0:
            return
        
        anim1 = QtCore.QPropertyAnimation(self.delete_panel, b"minimumWidth")
        anim1.setDuration(200)
        anim1.setStartValue(self.delete_panel.width())
        anim1.setEndValue(0)
        anim1.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)
        
        anim2 = QtCore.QPropertyAnimation(self.delete_panel, b"maximumWidth")
        anim2.setDuration(200)
        anim2.setStartValue(self.delete_panel.width())
        anim2.setEndValue(0)
        anim2.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)
        
        anim1.start()
        anim2.start()

    def delete_chat_by_id(self, chat_id: int):
        """Удалить чат по ID"""
        # Подтверждение удаления
        reply = QtWidgets.QMessageBox.question(
            self, "Удаление чата",
            "Вы уверены, что хотите удалить этот чат?\nВсе сообщения будут удалены.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            # Если удаляем активный чат
            if chat_id == self.current_chat_id:
                # Создаём новый пустой чат
                new_chat_id = self.chat_manager.create_chat("Новый чат")
                self.chat_manager.set_active_chat(new_chat_id)
                self.current_chat_id = new_chat_id
                on_chat_switched_all_memories(new_chat_id)
            
            # Удаляем контекстную память чата ПЕРЕД удалением самого чата
            clear_chat_all_memories(chat_id)

            # Удаляем чат
            self.chat_manager.delete_chat(chat_id)
            
            # Обновляем список
            self.load_chats_list()
            self.load_current_chat()

    def delete_selected_chat(self):
        """Удалить выбранный чат (для кнопки в панели)"""
        if not self.chat_to_delete:
            return
        
        self.delete_chat_by_id(self.chat_to_delete)
        
        # Скрываем панель удаления
        self.hide_delete_panel()
        self.chat_to_delete = None

    def _cleanup_empty_chats_on_startup(self):
        """Удалить все старые чаты без пользовательских сообщений при запуске"""
        try:
            all_chats = self.chat_manager.get_all_chats()
            deleted_count = 0
            
            for chat in all_chats:
                chat_id = chat['id']
                # Получаем сообщения чата
                messages = self.chat_manager.get_chat_messages(chat_id, limit=100)
                
                # Проверяем есть ли хотя бы одно сообщение от пользователя
                has_user_messages = any(msg[0] == "user" for msg in messages)
                
                if not has_user_messages:
                    # Удаляем пустой чат и его контекстную память
                    print(f"[CLEANUP] Удаляю пустой чат ID={chat_id}, title='{chat['title']}'")
                    clear_chat_all_memories(chat_id)
                    self.chat_manager.delete_chat(chat_id)
                    deleted_count += 1
                else:
                    print(f"[CLEANUP] Сохраняю чат ID={chat_id} - есть сообщения пользователя")
            
            if deleted_count > 0:
                print(f"[CLEANUP] ✓ Удалено пустых чатов: {deleted_count}")
            else:
                print(f"[CLEANUP] ✓ Пустых чатов не найдено")
                
        except Exception as e:
            print(f"[CLEANUP] ✗ Ошибка при очистке: {e}")
            import traceback
            traceback.print_exc()
    
    def load_chats_list(self):
        """Загрузить список чатов с превью последнего сообщения."""
        self.chats_list.clear()
        chats = self.chat_manager.get_all_chats()

        for chat in chats:
            # Получаем последнее сообщение для превью
            preview = ""
            try:
                msgs = self.chat_manager.get_chat_messages(chat['id'], limit=3)
                # Берём последнее сообщение не от Системы
                for m in reversed(msgs):
                    role, text = m[0], m[1]
                    if role in ("user", "assistant") and text:
                        import re as _re
                        clean = _re.sub(r'<[^>]+>', '', text)   # убираем HTML
                        clean = _re.sub(r'\s+', ' ', clean).strip()
                        preview = clean[:55] + ("…" if len(clean) > 55 else "")
                        break
            except Exception:
                pass

            # Двухстрочный текст: заголовок + превью через 

            display = chat['title']
            if preview:
                display = chat['title'] + "\n" + preview

            item = QtWidgets.QListWidgetItem(display)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, chat['id'])
            # Фиксированная высота для двух строк
            item.setSizeHint(QtCore.QSize(0, 58 if preview else 42))
            self.chats_list.addItem(item)

            if chat['is_active']:
                self.chats_list.setCurrentItem(item)

    def _update_chat_preview(self, chat_id: int, new_text: str):
        """
        Точечно обновить превью одного чата в боковой панели.

        Не перезагружает весь список — просто меняет текст нужного QListWidgetItem.
        Вызывается после каждого нового сообщения (пользователя и ИИ).

        chat_id  — ID чата для обновления
        new_text — полный текст последнего сообщения (будет обрезан до 55 символов)
        """
        try:
            import re as _re
            clean = _re.sub(r'<[^>]+>', '', new_text or '')
            clean = _re.sub(r'\s+', ' ', clean).strip()
            preview = clean[:55] + ("…" if len(clean) > 55 else "")

            for i in range(self.chats_list.count()):
                item = self.chats_list.item(i)
                if item and item.data(QtCore.Qt.ItemDataRole.UserRole) == chat_id:
                    # Берём текущий заголовок (первая строка до \n)
                    current = item.text()
                    title = current.split("\n", 1)[0]
                    item.setText(title + ("\n" + preview if preview else ""))
                    item.setSizeHint(QtCore.QSize(0, 58 if preview else 42))
                    # Перерисовываем строку без полной перезагрузки списка
                    self.chats_list.update(self.chats_list.indexFromItem(item))
                    break
        except Exception as e:
            print(f"[CHAT_PREVIEW] ✗ Ошибка обновления превью: {e}")

    def load_current_chat(self):
        """Загрузить текущий активный чат (УЛУЧШЕНО: загрузка файлов)"""
        if not self.current_chat_id:
            return
        
        print(f"[LOAD_CURRENT] ════════════════════════════════════════")
        print(f"[LOAD_CURRENT] Загрузка чата ID={self.current_chat_id}")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: ОЧИСТКА ФАЙЛОВ ИЗ ПРЕДЫДУЩЕГО ЧАТА
        # ═══════════════════════════════════════════════════════════════
        if self.attached_files:
            print(f"[LOAD_CURRENT] 🗑️ Очищаем {len(self.attached_files)} старых файлов")
            self.attached_files = []
            self.update_file_chips()
        
        # ✅ КРИТИЧНО: Полностью очищаем все виджеты сообщений
        # Структура layout: [message1, message2, ..., stretch(1)]
        # Удаляем только виджеты сообщений, оставляем stretch в конце
        items_to_remove = []
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                # Удаляем все виджеты сообщений (они имеют атрибут speaker)
                if hasattr(widget, 'speaker'):
                    items_to_remove.append(widget)
        
        # Удаляем собранные виджеты
        for widget in items_to_remove:
            self.messages_layout.removeWidget(widget)
            widget.deleteLater()
        
        print(f"[LOAD_CURRENT] Удалено виджетов: {len(items_to_remove)}")
        
        # Загружаем сообщения текущего чата (оптимизировано: 30 вместо 50)
        messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=30)
        
        # Проверяем состояние кнопки "Очистить"
        self.clear_btn.setEnabled(True)
        self.clear_btn.setStyleSheet("")
        
        # Показываем приветствие если чат пустой
        if len(messages) == 0:
            welcome_msg = "Привет! Готов к работе."
            self.add_message_widget("Система", welcome_msg, add_controls=False)
            print(f"[LOAD_CURRENT] ✅ Загрузка завершена (пустой чат)")
            print(f"[LOAD_CURRENT] ════════════════════════════════════════")
            return
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: ЗАГРУЗКА ФАЙЛОВ ОТКЛЮЧЕНА
        # ═══════════════════════════════════════════════════════════════
        # ИСПРАВЛЕНИЕ: НЕ загружаем файлы в поле прикрепления
        # Файлы сохраняются только для контекста AI (через memory)
        # но НЕ отображаются пользователю как прикреплённые
        print(f"[LOAD_CURRENT] ℹ️ Загрузка файлов в UI отключена (файлы в памяти AI)")
        
        # Определяем какие сообщения показывать с анимацией (последние 2 для ускорения)
        total_messages = len(messages)
        
        # Загружаем существующие сообщения с файлами
        for idx, msg_data in enumerate(messages):
            role    = msg_data[0]
            content           = msg_data[1]
            files             = msg_data[2] if len(msg_data) > 2 else None
            sources           = msg_data[3] if len(msg_data) > 3 else []
            # speaker_name сохранён в БД — используем его, иначе текущий ИИ
            stored_speaker    = msg_data[5] if len(msg_data) > 5 else None
            stored_regen_hist = msg_data[6] if len(msg_data) > 6 else None
            stored_gen_files  = msg_data[7] if len(msg_data) > 7 else []
            
            if role == "user":
                speaker = "Вы"
            else:
                speaker = stored_speaker if stored_speaker else llama_handler.ASSISTANT_NAME
            if role not in ["user", "assistant"]:
                continue
            
            # Проверяем, входит ли сообщение в последние 2 (оптимизировано)
            is_recent = (total_messages - idx) <= 2
            
            # Создаём виджет с файлами и источниками
            message_widget = MessageWidget(
                speaker, content, add_controls=True,
                language=self.current_language,
                main_window=self,
                parent=self.messages_widget,
                thinking_time=0,
                attached_files=files,
                sources=sources or [],
                generated_files=stored_gen_files or [],
            )
            
            # Восстанавливаем историю перегенерации из БД
            if role == "assistant" and stored_regen_hist and len(stored_regen_hist) >= 1:
                try:
                    message_widget._regen_history = stored_regen_hist
                    message_widget._regen_idx = len(stored_regen_hist) - 1
                    # Инициализируем _regen_nav_group если его нет (старые виджеты)
                    if not hasattr(message_widget, '_regen_nav_group'):
                        message_widget._regen_nav_group = None
                    message_widget._regen_apply_entry(message_widget._regen_idx)
                    print(f"[LOAD_CHAT] ✓ Восстановлена история: {len(stored_regen_hist)} вариантов")
                except Exception as e:
                    print(f"[LOAD_CHAT] ⚠️ Ошибка восстановления истории: {e}")

            # Для старых сообщений сразу убираем анимацию — показываем мгновенно
            if not is_recent:
                # Останавливаем appear-группу и снимаем graphics effect целиком.
                # _SlideOpacityEffect (и старый QGraphicsOpacityEffect) больше не нужен —
                # виджет уже должен быть полностью видим без каких-либо переходов.
                try:
                    if hasattr(message_widget, '_appear_group'):
                        message_widget._appear_group.stop()
                    if hasattr(message_widget, 'fade_in_animation'):
                        message_widget.fade_in_animation.stop()
                    if hasattr(message_widget, 'pos_animation'):
                        message_widget.pos_animation.stop()
                    # Убираем эффект — виджет станет полностью непрозрачным
                    message_widget.setGraphicsEffect(None)
                    # Чистим ссылки
                    for _attr in ('_slide_eff', 'opacity_effect', '_appear_group',
                                  '_anim_opacity', '_anim_slide', 'fade_in_animation'):
                        if hasattr(message_widget, _attr):
                            delattr(message_widget, _attr)
                except Exception:
                    pass
            else:
                # Для последних 2 - анимация включена по умолчанию (оптимизировано)
                pass
            
            # Добавляем в layout (stretch уже удалён, добавляем в конец)
            self.messages_layout.addWidget(message_widget)
            
            # Запускаем анимацию для последних 2 сообщений (оптимизировано)
            if is_recent and hasattr(message_widget, '_start_appear_animation'):
                QtCore.QTimer.singleShot(60 + idx * 150, message_widget._start_appear_animation)
        
        # ═══════════════════════════════════════════════════════════════
        # АВТОМАТИЧЕСКИЙ СКРОЛЛ ВНИЗ ПОСЛЕ ЗАГРУЗКИ ЧАТА
        # ═══════════════════════════════════════════════════════════════
        # Полное обновление layout (invalidate гарантирует пересчёт ВСЕГО дерева)
        self.messages_layout.invalidate()
        self.messages_layout.activate()
        self.messages_widget.updateGeometry()
        # ✅ processEvents убран — используем delayed scroll через QTimer
        
        # Скроллим вниз с задержкой 350ms:
        # - последние 2 сообщения запускают анимацию в 60ms и 210ms
        # - 350ms гарантирует что layout успел пересчитать размеры ДО скролла
        def scroll_to_bottom_delayed():
            # Повторный invalidate + activate — layout ГАРАНТИРОВАННО завершён
            self.messages_layout.invalidate()
            self.messages_layout.activate()
            self.messages_widget.updateGeometry()
            # ✅ ИСПРАВЛЕНИЕ ДЁРГАНЬЯ: убрали processEvents() — он вызывал
            # принудительную синхронную перерисовку всего окна включая нижнюю панель
            scrollbar = self.scroll_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            # Обновляем видимость кнопки "вниз"
            if hasattr(self, 'scroll_to_bottom_btn'):
                self.update_scroll_button_visibility()
        
        QtCore.QTimer.singleShot(350, scroll_to_bottom_delayed)
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 3: УПРАВЛЕНИЕ ВИДИМОСТЬЮ КНОПОК РЕГЕНЕРАЦИИ И РЕДАКТИРОВАНИЯ
        # ═══════════════════════════════════════════════════════════════
        # Показываем кнопки только у последних сообщений
        def manage_regenerate_buttons():
            # Находим последнее сообщение ассистента
            last_assistant_widget = None
            # Находим последнее сообщение пользователя
            last_user_widget = None
            
            # Проходим в обратном порядке чтобы найти последние сообщения
            for i in range(self.messages_layout.count() - 1, -1, -1):
                item = self.messages_layout.itemAt(i)
                if item and item.widget() and hasattr(item.widget(), 'speaker'):
                    widget = item.widget()
                    
                    # Ищем последнее сообщение ассистента (не "Вы" и не "Система")
                    if last_assistant_widget is None and widget.speaker not in ["Вы", "Система"]:
                        last_assistant_widget = widget
                    
                    # Ищем последнее сообщение пользователя
                    if last_user_widget is None and widget.speaker == "Вы":
                        last_user_widget = widget
                    
                    # Если нашли оба - можно остановиться
                    if last_assistant_widget and last_user_widget:
                        break
            
            # Скрываем все кнопки регенерации у сообщений ассистента
            # Показываем только у последнего
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item and item.widget() and hasattr(item.widget(), 'speaker'):
                    widget = item.widget()
                    
                    # Управление кнопкой регенерации (у сообщений ассистента)
                    if widget.speaker not in ["Вы", "Система"]:
                        if hasattr(widget, 'regenerate_button') and widget.regenerate_button:
                            if widget == last_assistant_widget:
                                widget.regenerate_button.setVisible(True)
                            else:
                                widget.regenerate_button.setVisible(False)
                    
                    # Управление кнопкой редактирования (у сообщений пользователя)
                    if widget.speaker == "Вы":
                        if hasattr(widget, 'edit_button') and widget.edit_button:
                            if widget == last_user_widget:
                                widget.edit_button.setVisible(True)
                            else:
                                widget.edit_button.setVisible(False)
            
            print(f"[LOAD_CURRENT] ✓ Управление кнопками завершено")
        
        # Запускаем управление кнопками с небольшой задержкой после загрузки
        QtCore.QTimer.singleShot(400, manage_regenerate_buttons)

    # ─── Просмотрщики файлов (вызываются из attachment_manager через self) ───

    def _show_image_viewer(self, file_path: str):
        """Мини-просмотрщик изображений внутри приложения."""
        viewer = _ImageViewerDialog(file_path, parent=self)
        viewer.exec()

    def _show_text_viewer(self, file_path: str):
        """Мини-просмотрщик текстовых файлов внутри приложения."""
        viewer = _TextViewerDialog(file_path, parent=self)
        viewer.exec()

    def _preview_file(self, file_path: str):
        """Открывает предпросмотр файла в зависимости от типа."""
        if not os.path.exists(file_path):
            from PyQt6 import QtWidgets
            QtWidgets.QMessageBox.warning(
                self, "Файл не найден",
                f"Файл не найден:\n{file_path}\n\nВозможно, файл был перемещён.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            return
        if is_image_file(file_path):
            self._show_image_viewer(file_path)
        elif is_text_file(file_path):
            self._show_text_viewer(file_path)
        else:
            # Открываем в системном приложении
            import subprocess, sys
            try:
                if sys.platform == 'darwin':
                    subprocess.run(['open', file_path], check=True)
                elif sys.platform == 'win32':
                    os.startfile(file_path)
                else:
                    subprocess.run(['xdg-open', file_path], check=True)
            except Exception as e:
                from PyQt6 import QtWidgets
                QtWidgets.QMessageBox.warning(
                    self, "Ошибка", f"Не удалось открыть файл:\n{e}",
                    QtWidgets.QMessageBox.StandardButton.Ok
                )


    def create_new_chat(self):
        """Создать новый чат (УЛУЧШЕНО: с плавной анимацией кнопки)"""
        
        # ═══════════════════════════════════════════════════════════════
        # АНИМАЦИЯ КНОПКИ "+ Новый чат" (bounce эффект)
        # ═══════════════════════════════════════════════════════════════
        # Находим кнопку нового чата
        new_chat_btn = None
        for i in range(self.sidebar.layout().count()):
            widget = self.sidebar.layout().itemAt(i).widget()
            if widget and isinstance(widget, QtWidgets.QPushButton):
                if "Новый чат" in widget.text() or widget.text() == "+ Новый чат":
                    new_chat_btn = widget
                    break
        
        if new_chat_btn:
            # Создаём анимацию масштабирования
            if not hasattr(self, '_new_chat_btn_press_anim'):
                self._new_chat_btn_press_anim = QtCore.QPropertyAnimation(new_chat_btn, b"geometry")
            
            original_geo = new_chat_btn.geometry()
            center_x = original_geo.center().x()
            center_y = original_geo.center().y()
            
            # Уменьшаем до 0.92 scale для более тонкого эффекта
            scale_factor = 0.92
            new_width = int(original_geo.width() * scale_factor)
            new_height = int(original_geo.height() * scale_factor)
            pressed_geo = QtCore.QRect(
                center_x - new_width // 2,
                center_y - new_height // 2,
                new_width,
                new_height
            )
            
            # Быстрое нажатие
            self._new_chat_btn_press_anim.stop()
            self._new_chat_btn_press_anim.setDuration(100)
            self._new_chat_btn_press_anim.setStartValue(original_geo)
            self._new_chat_btn_press_anim.setEndValue(pressed_geo)
            self._new_chat_btn_press_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
            
            # После нажатия - возврат с bounce
            def on_new_chat_press_finished():
                if not hasattr(self, '_new_chat_btn_release_anim'):
                    self._new_chat_btn_release_anim = QtCore.QPropertyAnimation(new_chat_btn, b"geometry")
                
                self._new_chat_btn_release_anim.setDuration(350)
                self._new_chat_btn_release_anim.setStartValue(pressed_geo)
                self._new_chat_btn_release_anim.setEndValue(original_geo)
                # OutBack создаёт лёгкий spring bounce эффект
                self._new_chat_btn_release_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
                self._new_chat_btn_release_anim.start()
            
            try:
                self._new_chat_btn_press_anim.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._new_chat_btn_press_anim.finished.connect(on_new_chat_press_finished)
            self._new_chat_btn_press_anim.start()
            
            print("[NEW_CHAT] ✨ Запущена анимация кнопки нового чата")
        
        # ═══════════════════════════════════════════════════════════════
        # GUARD: не создаём новый чат если текущий уже пустой
        # ═══════════════════════════════════════════════════════════════
        if self.current_chat_id:
            messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=10)
            user_messages = [msg for msg in messages if msg[0] == "user"]
            
            if len(user_messages) == 0:
                # Уже в пустом чате — просто закрываем sidebar, новый не создаём
                print("[NEW_CHAT] Уже в пустом чате — создание нового заблокировано")
                if getattr(self, '_sidebar_open', False):
                    self.toggle_sidebar()
                return
        
        # Создаём новый чат
        chat_id = self.chat_manager.create_chat("Новый чат")
        self.chat_manager.set_active_chat(chat_id)
        self.current_chat_id = chat_id
        on_chat_switched_all_memories(chat_id)
        
        # Обновляем флаги стартового чата
        self.startup_chat_id = chat_id
        self.startup_chat_has_messages = False
        
        self.load_chats_list()
        
        # Принудительно скрываем кнопку "вниз" ДО загрузки чата
        if hasattr(self, 'scroll_to_bottom_btn'):
            btn = self.scroll_to_bottom_btn
            btn.fade_animation.stop()
            btn.opacity_effect.setOpacity(0.0)
            btn.hide()
            btn._is_visible_animated = False
        
        # Закрываем sidebar → после его закрытия делаем fade-переход в новый чат
        if getattr(self, '_sidebar_open', False):
            self.toggle_sidebar()
            # Дожидаемся конца анимации закрытия (240ms) и делаем fade-in
            QtCore.QTimer.singleShot(260, lambda: self._animate_chat_transition(self.load_current_chat))
        else:
            self._animate_chat_transition(self.load_current_chat)
        
        print(f"[NEW_CHAT] ✓ Создан новый чат ID={chat_id}")

    def _animate_chat_transition(self, callback):
        """
        Плавный переход между чатами: fade-out → callback → fade-in.
        callback — функция загрузки нового чата (load_current_chat).
        """
        if not hasattr(self, 'messages_widget'):
            callback()
            return

        # Fade-out
        eff_out = QtWidgets.QGraphicsOpacityEffect(self.messages_widget)
        self.messages_widget.setGraphicsEffect(eff_out)
        anim_out = QtCore.QPropertyAnimation(eff_out, b"opacity")
        anim_out.setDuration(120)
        anim_out.setStartValue(1.0)
        anim_out.setEndValue(0.0)
        anim_out.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)

        def _do_switch():
            try:
                callback()
            except Exception as e:
                print(f"[CHAT_TRANSITION] ошибка callback: {e}")
            # Fade-in
            eff_in = QtWidgets.QGraphicsOpacityEffect(self.messages_widget)
            self.messages_widget.setGraphicsEffect(eff_in)
            anim_in = QtCore.QPropertyAnimation(eff_in, b"opacity")
            anim_in.setDuration(200)
            anim_in.setStartValue(0.0)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
            def _cleanup():
                try:
                    self.messages_widget.setGraphicsEffect(None)
                except RuntimeError:
                    pass
            anim_in.finished.connect(_cleanup)
            self._chat_fade_in_anim = anim_in   # защита от GC
            anim_in.start()

        anim_out.finished.connect(_do_switch)
        self._chat_fade_out_anim = anim_out     # защита от GC
        anim_out.start()

    def switch_chat(self, item):
        """Переключить чат с полной остановкой генерации (УЛУЧШЕНО: очистка файлов)"""
        chat_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        
        print(f"[SWITCH_CHAT] ════════════════════════════════════════")
        print(f"[SWITCH_CHAT] Переключение с чата {self.current_chat_id} на {chat_id}")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: ПОЛНАЯ ОСТАНОВКА ГЕНЕРАЦИИ (КРИТИЧНО!)
        # ═══════════════════════════════════════════════════════════════
        if self.is_generating:
            print(f"[SWITCH_CHAT] ⚠️ Останавливаем активную генерацию перед переключением")
            
            # Останавливаем флаг генерации
            self.is_generating = False
            
            # Отменяем воркер
            if hasattr(self, 'current_worker'):
                self.current_worker = None
            
            # Останавливаем анимацию статуса
            if hasattr(self, 'stop_status_animation'):
                self.stop_status_animation()
            
            # Очищаем статус
            self.status_label.setText("")
            
            # Сбрасываем UI
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
            _set_send_icon(self.send_btn)
            
            print(f"[SWITCH_CHAT] ✓ Генерация остановлена")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: ОЧИСТКА ПРИКРЕПЛЁННЫХ ФАЙЛОВ ИЗ СТАРОГО ЧАТА
        # ═══════════════════════════════════════════════════════════════
        if self.attached_files:
            print(f"[SWITCH_CHAT] 🗑️ Очищаем {len(self.attached_files)} файлов из старого чата")
            self.attached_files = []
            self.update_file_chips()
        
        # ═══ ЛОГИКА ОЧИСТКИ ПУСТЫХ ЧАТОВ ═══
        # Если переключаемся с пустого чата - удаляем его
        if self.current_chat_id and chat_id != self.current_chat_id:
            messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=10)
            user_messages = [msg for msg in messages if msg[0] == "user"]
            
            # Если в текущем чате нет сообщений пользователя - удаляем его
            if len(user_messages) == 0:
                print(f"[SWITCH_CHAT] Удаляем пустой чат {self.current_chat_id} при переключении")
                clear_chat_all_memories(self.current_chat_id)
                try:
                    self.chat_manager.delete_chat(self.current_chat_id)
                except Exception as e:
                    print(f"[SWITCH_CHAT] Ошибка удаления пустого чата: {e}")
        
        # ✅ GUARD: Очищаем поле ввода при переключении
        try:
            self.input_field.clear()
        except Exception:
            pass
        
        self.chat_manager.set_active_chat(chat_id)
        self.current_chat_id = chat_id
        on_chat_switched_all_memories(chat_id)
        
        # Обновляем флаги стартового чата
        self.startup_chat_id = None
        self.startup_chat_has_messages = False
        
        self.load_chats_list()
        self._animate_chat_transition(self.load_current_chat)

        # ═══════════════════════════════════════════════════════════════
        # ═══════════════════════════════════════════════════════════════
        # ИСПРАВЛЕНИЕ: НЕ загружаем файлы в поле прикрепления
        # Файлы сохраняются только для контекста AI (через memory)
        print(f"[SWITCH_CHAT] ℹ️ Загрузка файлов в UI отключена")
        
        print(f"[SWITCH_CHAT] ✅ Переключение завершено")
        print(f"[SWITCH_CHAT] ════════════════════════════════════════")
        
        # Закрываем sidebar после переключения
        self.toggle_sidebar()
    def add_message_widget(self, speaker: str, text: str, add_controls: bool = False, thinking_time: float = 0, action_history: list = None, attached_files: list = None, sources: list = None, is_acknowledgment: bool = False, generated_files: list = None):
        """
        Добавить виджет сообщения в layout БЕЗ АВТОСКРОЛЛА.
        
        УМНОЕ ОБНОВЛЕНИЕ В ЗАВИСИМОСТИ ОТ ПОЗИЦИИ ПОЛЬЗОВАТЕЛЯ:
        ════════════════════════════════════════════════════════════
        
        ЛОГИКА:
        • Пользователь ВНИЗУ → Обновляем layout с периодической синхронизацией
        • Пользователь НЕ внизу (читает историю) → МИНИМАЛЬНОЕ обновление
        
        МИНИМАЛЬНОЕ ОБНОВЛЕНИЕ (когда пользователь читает историю):
        ✓ Добавляем виджет в layout (addWidget)
        ✓ Показываем виджет (show)
        ✓ НЕ обновляем viewport (чтобы не мешать чтению)
        ✓ НЕ вызываем processEvents (избегаем "застревания")
        ✓ Пузыри не мешают скроллу
        
        ПЕРИОДИЧЕСКАЯ СИНХРОНИЗАЦИЯ (когда пользователь внизу):
        ✓ Каждое 5-е сообщение → полное обновление
        ✓ Остальные → быстрое обновление
        ✓ Viewport обновляется корректно
        
        РЕЗУЛЬТАТ:
        • Когда читаешь историю → новые сообщения НЕ мешают
        • Когда внизу → всё обновляется нормально
        • БЕЗ автоскролла
        • БЕЗ "застревания" пузырей
        ════════════════════════════════════════════════════════════
        """
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: СОХРАНЯЕМ ТЕКУЩУЮ ПОЗИЦИЮ СКРОЛЛА
        # ═══════════════════════════════════════════════════════════════
        scrollbar = self.scroll_area.verticalScrollBar()
        old_value = scrollbar.value()
        old_max = scrollbar.maximum()
        was_at_bottom = (old_max == 0) or (old_value >= old_max - 10)
        
        # ═══════════════════════════════════════════════════════════════
        # ПОДСЧЁТ КОЛИЧЕСТВА СООБЩЕНИЙ
        # ═══════════════════════════════════════════════════════════════
        message_count = 0
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item and item.widget() and hasattr(item.widget(), 'speaker'):
                message_count += 1
        
        # ═══════════════════════════════════════════════════════════════
        # ОПРЕДЕЛЯЕМ РЕЖИМ ОБНОВЛЕНИЯ
        # ═══════════════════════════════════════════════════════════════
        FULL_UPDATE_INTERVAL = 5
        is_full_update = (message_count % FULL_UPDATE_INTERVAL == 0)
        
        # Создаём виджет
        message_widget = MessageWidget(
            speaker, text, add_controls,
            language=self.current_language,
            main_window=self,
            parent=self.messages_widget,
            thinking_time=thinking_time,
            action_history=action_history,
            attached_files=attached_files,
            sources=sources or [],
            is_acknowledgment=is_acknowledgment,
            generated_files=generated_files or [],
        )
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: ДОБАВЛЕНИЕ В LAYOUT
        # ═══════════════════════════════════════════════════════════════
        self.messages_layout.addWidget(message_widget)
        message_widget.show()

        # Применяем текущие настройки видимости к новому сообщению
        if add_controls:
            self._apply_element_visibility(
                getattr(self, '_ui_show_tts',       True),
                getattr(self, '_ui_show_regen',     True),
                getattr(self, '_ui_show_copy',      True),
                getattr(self, '_ui_show_user_copy', True),
                getattr(self, '_ui_show_user_edit', True),
            )

        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 3: ОБНОВЛЕНИЕ LAYOUT (ЗАВИСИТ ОТ ПОЗИЦИИ ПОЛЬЗОВАТЕЛЯ)
        # ═══════════════════════════════════════════════════════════════
        
        if not was_at_bottom:
            # ──────────────────────────────────────────────────────────
            # ПОЛЬЗОВАТЕЛЬ ЧИТАЕТ ИСТОРИЮ (НЕ внизу)
            # ──────────────────────────────────────────────────────────
            # МИНИМАЛЬНОЕ обновление - только добавили виджет
            # НЕ трогаем viewport чтобы не мешать чтению
            print(f"[ADD_MESSAGE] 📖 Минимальное обновление (пользователь читает историю)")
            
            # НЕ вызываем activate/update/processEvents
            # Виджет добавлен в layout, но viewport не обновляется
            # Когда пользователь вернётся вниз - всё обновится
            
        else:
            # ──────────────────────────────────────────────────────────
            # ПОЛЬЗОВАТЕЛЬ ВНИЗУ (видит новые сообщения)
            # ──────────────────────────────────────────────────────────
            # Периодическая синхронизация
            
            if is_full_update:
                print(f"[ADD_MESSAGE] 🔄 ПОЛНОЕ обновление (сообщение #{message_count + 1})")
                
                # ПОЛНОЕ обновление с синхронизацией
                self.messages_layout.invalidate()
                self.messages_layout.activate()
                self.messages_widget.updateGeometry()
                
                # ✅ ИСПРАВЛЕНИЕ ДЁРГАНЬЯ: используем update() вместо repaint() + processEvents()
                # repaint() + processEvents() вызывали перерисовку всего окна включая нижнюю панель
                self.scroll_area.viewport().update()
                
            else:
                print(f"[ADD_MESSAGE] ⚡ БЫСТРОЕ обновление (сообщение #{message_count + 1})")
                
                # БЫСТРОЕ обновление без processEvents
                self.messages_layout.activate()
                self.messages_widget.updateGeometry()
                self.scroll_area.viewport().update()
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 4: АВТОСКРОЛЛ ИЛИ ВОССТАНОВЛЕНИЕ ПОЗИЦИИ
        # ═══════════════════════════════════════════════════════════════
        _auto_scroll = getattr(self, "auto_scroll_enabled", False)
        if _auto_scroll:
            # Автоскролл включён — плавная анимация вниз.
            # Запускаем ПОСЛЕ завершения appear-анимации (380ms + запас),
            # чтобы не пересекаться с ней и не вызывать лаг layout-пересчёта.
            def _do_smooth_scroll():
                # НЕ вызываем activate/updateGeometry — layout уже актуален
                # после addWidget. Повторный вызов во время анимации = лаг.
                sb = self.scroll_area.verticalScrollBar()
                target = sb.maximum()
                current = sb.value()
                if target <= current:
                    return
                _scroll_anim = QtCore.QPropertyAnimation(sb, b"value", self)
                _scroll_anim.setDuration(260)
                _scroll_anim.setStartValue(current)
                _scroll_anim.setEndValue(target)
                _scroll_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                _scroll_anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
                # Скрываем кнопку вниз — мы уже едем вниз
                if hasattr(self, 'scroll_to_bottom_btn'):
                    self.scroll_to_bottom_btn.smooth_hide()
            # ПОРЯДОК: сначала скролл (20ms), потом анимация появления (после скролла).
            # Скролл длится 260ms → анимацию запускаем через 20+260+60=340ms.
            QtCore.QTimer.singleShot(20, _do_smooth_scroll)
        elif old_max > 0 and not was_at_bottom:
            # Автоскролл выключен — сохраняем позицию пользователя
            scrollbar.setValue(old_value)
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 5: ОБНОВЛЯЕМ КНОПКУ "ВНИЗ"
        # ═══════════════════════════════════════════════════════════════
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.update_scroll_button_visibility()
        
        # Анимация появления — запускаем ПОСЛЕ скролла.
        # Если автоскролл включён: ждём окончания скролла (260ms) + запас 80ms = 340ms.
        # Если автоскролл выключен: запускаем сразу через 20ms как раньше.
        if hasattr(message_widget, '_start_appear_animation'):
            _mw_ref = message_widget
            _appear_delay = 340 if getattr(self, "auto_scroll_enabled", False) else 20
            QtCore.QTimer.singleShot(_appear_delay, _mw_ref._start_appear_animation)
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 6: УПРАВЛЕНИЕ ВИДИМОСТЬЮ КНОПОК РЕГЕНЕРАЦИИ И РЕДАКТИРОВАНИЯ
        # ═══════════════════════════════════════════════════════════════
        # Показываем кнопку регенерации только у последнего сообщения ассистента
        # Показываем кнопку редактирования только у последнего сообщения пользователя
        if speaker != "Система":
            # Отложенное управление кнопками через 100ms (минимальная задержка)
            def manage_buttons():
                # РЕГЕНЕРАЦИЯ: Скрываем у всех ответов ИИ кроме последнего
                if speaker != "Вы":
                    for i in range(self.messages_layout.count()):
                        item = self.messages_layout.itemAt(i)
                        if item and item.widget() and hasattr(item.widget(), 'speaker'):
                            widget = item.widget()
                            # Проверяем что это сообщение ассистента
                            if widget.speaker != "Вы" and widget.speaker != "Система":
                                # Если это не текущий виджет - скрываем кнопку
                                if widget != message_widget and hasattr(widget, 'regenerate_button') and widget.regenerate_button:
                                    widget.regenerate_button.setVisible(False)
                                # Если это текущий виджет - показываем кнопку
                                elif widget == message_widget and hasattr(widget, 'regenerate_button') and widget.regenerate_button:
                                    widget.regenerate_button.setVisible(True)
                
                # РЕДАКТИРОВАНИЕ: Скрываем у всех сообщений пользователя кроме последнего
                else:  # speaker == "Вы"
                    for i in range(self.messages_layout.count()):
                        item = self.messages_layout.itemAt(i)
                        if item and item.widget() and hasattr(item.widget(), 'speaker'):
                            widget = item.widget()
                            # Проверяем что это сообщение пользователя
                            if widget.speaker == "Вы":
                                # Если это не текущий виджет - скрываем кнопку редактирования
                                if widget != message_widget and hasattr(widget, 'edit_button') and widget.edit_button:
                                    widget.edit_button.setVisible(False)
                                # Если это текущий виджет - показываем кнопку редактирования
                                elif widget == message_widget and hasattr(widget, 'edit_button') and widget.edit_button:
                                    widget.edit_button.setVisible(True)
                
                print(f"[ADD_MESSAGE] ✓ Управление кнопками завершено")
            
            # Запускаем управление кнопками отложенно
            QtCore.QTimer.singleShot(100, manage_buttons)
    
    def send_message(self):
        """Отправка сообщения пользователя
        
        ВАЖНО: Всегда берёт текст ТОЛЬКО из поля ввода (self.input_field.text())
        Никогда не использует старые значения или данные из других чатов
        """
        
        # Если идёт генерация - останавливаем и возвращаем текст в поле
        if self.is_generating:
            print(f"[SEND] ═══════════════════════════════════════════")
            print(f"[SEND] ОСТАНОВКА ГЕНЕРАЦИИ")
            
            self.is_generating = False
            
            # Помечаем текущий worker как отменённый
            if hasattr(self, 'current_worker') and self.current_worker:
                self.current_worker._cancelled = True
                print(f"[SEND] ✓ Worker помечен как отменённый")
            
            self.current_worker = None
            
            # Останавливаем анимацию статуса
            if hasattr(self, 'stop_status_animation'):
                self.stop_status_animation()
            
            # ── Удаляем последнее сообщение пользователя из БД и UI ──
            # Оно было сохранено при отправке, но ответа не последовало —
            # без удаления AI увидит его в истории и ответит на него повторно.
            #
            # ВАЖНО: при перегенерации (_is_regenerating=True) нового сообщения
            # пользователя в UI НЕТ — его не нужно удалять из UI.
            # Также не удаляем из БД, т.к. сообщение ассистента уже было там удалено.
            _was_regenerating = getattr(self, '_is_regenerating', False)
            self._is_regenerating = False  # сбрасываем флаг

            # ✅ ВОССТАНОВЛЕНИЕ: Сохраняем текст и файлы ПЕРЕД удалением виджета
            restored_text = ""
            restored_files = []
            
            if not _was_regenerating:
                # Обычная остановка: удаляем незавершённое сообщение пользователя из БД и UI
                try:
                    conn = sqlite3.connect("chats.db")
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT role, content FROM chat_messages
                        WHERE chat_id = ?
                        ORDER BY id DESC LIMIT 1
                    """, (self.current_chat_id,))
                    last = cur.fetchone()
                    if last and last[0] == "user":
                        restored_text = last[1] or ""
                        cur.execute("""
                            DELETE FROM chat_messages
                            WHERE chat_id = ? AND id = (
                                SELECT id FROM chat_messages
                                WHERE chat_id = ?
                                ORDER BY id DESC LIMIT 1
                            )
                        """, (self.current_chat_id, self.current_chat_id))
                        conn.commit()
                        print("[SEND] ✓ Незавершённое сообщение пользователя удалено из БД")

                        # ✅ FIX ДУБЛЕЙ: удаляем последнее user-сообщение из ВСЕХ
                        # memory_manager-ов, иначе при повторной отправке ИИ видит
                        # старое сообщение + новое и отвечает «двойным» контекстом.
                        # Используем прямой SQL — надёжно для любых memory-бэкендов.
                        _MEMORY_DBS = [
                            "context_memory.db",
                            "deepseek_memory.db",
                            "mistral_memory.db",
                            "qwen_memory.db",
                        ]
                        for _mdb in _MEMORY_DBS:
                            if not os.path.exists(_mdb):
                                continue
                            try:
                                _mc = sqlite3.connect(_mdb)
                                _mcur = _mc.cursor()
                                # Ищем таблицу с колонкой chat_id
                                _mcur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                                for (_tname,) in _mcur.fetchall():
                                    try:
                                        _mcur.execute(
                                            f"SELECT name FROM pragma_table_info('{_tname}') WHERE name='chat_id'"
                                        )
                                        if not _mcur.fetchone():
                                            continue
                                        # Удаляем последнюю запись с role='user' для этого chat_id
                                        _mcur.execute(f"""
                                            DELETE FROM {_tname}
                                            WHERE id = (
                                                SELECT id FROM {_tname}
                                                WHERE chat_id = ? AND role = 'user'
                                                ORDER BY id DESC LIMIT 1
                                            )
                                        """, (self.current_chat_id,))
                                        if _mcur.rowcount > 0:
                                            print(f"[SEND] ✓ Удалено user-сообщение из {_mdb}.{_tname}")
                                    except Exception:
                                        pass
                                _mc.commit()
                                _mc.close()
                            except Exception as _me:
                                print(f"[SEND] ⚠️ memory cleanup {_mdb}: {_me}")
                    conn.close()
                except Exception as e:
                    print(f"[SEND] ⚠️ Ошибка удаления сообщения из БД: {e}")

                # ✅ ВОССТАНОВЛЕНИЕ: Забираем прикреплённые файлы из последнего виджета ДО его удаления
                try:
                    for i in range(self.messages_layout.count() - 1, -1, -1):
                        item = self.messages_layout.itemAt(i)
                        if item and item.widget() and hasattr(item.widget(), 'speaker'):
                            w = item.widget()
                            if w.speaker == "Вы":
                                # Забираем файлы из виджета если они там есть
                                if hasattr(w, 'attached_files') and w.attached_files:
                                    restored_files = list(w.attached_files)
                                # ✅ Плавное удаление с анимацией slide-out + fade-out
                                def _do_remove(widget=w):
                                    try:
                                        self.messages_layout.removeWidget(widget)
                                        widget.deleteLater()
                                        print("[SEND] ✓ Виджет сообщения пользователя удалён из UI")
                                    except Exception as _e:
                                        print(f"[SEND] ⚠️ Ошибка удаления виджета: {_e}")
                                if hasattr(w, 'animate_remove'):
                                    w.animate_remove(_do_remove)
                                else:
                                    _do_remove()
                                break
                except Exception as e:
                    print(f"[SEND] ⚠️ Ошибка удаления виджета: {e}")
            else:
                # Остановка ПЕРЕГЕНЕРАЦИИ: нового сообщения пользователя в UI нет,
                # удалять ничего не нужно — пузырь ассистента уже затемнён, снимем dim выше.
                print("[SEND] ℹ️ Остановка перегенерации — удаление виджета пользователя пропущено")
            
            # Если из виджета файлы не получили — берём сохранённую копию
            if not restored_files and hasattr(self, '_last_sent_files') and self._last_sent_files:
                restored_files = list(self._last_sent_files)
            # Если текст из БД не получили — берём сохранённую копию
            if not restored_text and hasattr(self, '_last_sent_text') and self._last_sent_text:
                restored_text = self._last_sent_text

            # ✅ ВОССТАНОВЛЕНИЕ: Возвращаем текст в поле ввода
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
            _set_send_icon(self.send_btn)

            # ✅ Восстанавливаем яркость поля ввода и разблокируем mic_btn
            self._restore_input_after_generation()

            # ✅ Убираем все blur-оверлеи (перегенерация и обычный)
            if hasattr(self, '_regen_blur_overlay') and self._regen_blur_overlay.isVisible():
                try:
                    self._remove_regen_blur_effect()
                except Exception as _e:
                    print(f"[SEND] ⚠️ _remove_regen_blur_effect: {_e}")
                    try:
                        self._regen_blur_overlay.hide()
                    except Exception:
                        pass
            if hasattr(self, '_blur_overlay') and self._blur_overlay.isVisible():
                try:
                    self._blur_overlay.hide()
                    self._blur_overlay.clear()
                    print("[SEND] ✓ _blur_overlay скрыт")
                except Exception as _e:
                    print(f"[SEND] ⚠️ _blur_overlay hide: {_e}")
            
            if restored_text:
                self.input_field.setText(restored_text)
                self.input_field.setCursorPosition(len(restored_text))
                print(f"[SEND] ✓ Текст возвращён в поле ввода: '{restored_text[:40]}...'")
            
            # ✅ ВОССТАНОВЛЕНИЕ: Возвращаем прикреплённые файлы
            if restored_files:
                try:
                    self.attached_files = restored_files
                    self.update_file_chips()
                    print(f"[SEND] ✓ Восстановлено {len(restored_files)} прикреплённых файлов")
                except Exception as e:
                    print(f"[SEND] ⚠️ Не удалось восстановить файлы: {e}")
            
            # Очищаем статус сразу (без задержки)
            self.status_label.setText("")

            # ════════════════════════════════════════════════════════
            # ✅ КРИТИЧНО: если остановили ПЕРЕГЕНЕРАЦИЮ —
            # снимаем затемнение с пузыря и чистим target-виджет.
            # Без этого: пузырь навсегда остаётся тёмным, а следующий
            # ответ AI улетает в старый пузырь через _regen_target_widget.
            # ════════════════════════════════════════════════════════
            _regen_w = getattr(self, '_regen_target_widget', None)
            if _regen_w is not None:
                try:
                    _regen_w._set_regen_dim(False)
                    print("[SEND] ✓ Затемнение пузыря снято (перегенерация отменена)")
                except Exception as _dim_e:
                    print(f"[SEND] ⚠️ Не удалось снять dim: {_dim_e}")
                self._regen_target_widget = None
                print("[SEND] ✓ _regen_target_widget сброшен")

            print(f"[SEND] ✅ Генерация остановлена, текст и файлы возвращены")
            print(f"[SEND] ═══════════════════════════════════════════")
            return
        
        global CURRENT_LANGUAGE
        # ИСТОЧНИК ИСТИНЫ - текст из поля ввода
        user_text = self.input_field.text().strip()
        if not user_text:
            return
        
        print(f"[SEND] Отправка сообщения: {user_text[:50]}...")
        
        # Проверка орфографии убрана - нейросеть сама переспросит если не поймёт
        # ════════════════════════════════════════════════════════════════
        # ИСПРАВЛЕНИЕ №3: Проверка на короткие подтверждения
        # ════════════════════════════════════════════════════════════════
        is_acknowledgment, acknowledgment_response = is_short_acknowledgment(user_text)
        if is_acknowledgment:
            print(f"[SEND] Обнаружено короткое подтверждение: {user_text} → {acknowledgment_response}")
            
            # Добавляем сообщение пользователя
            self.input_field.clear()
            self.add_message_widget("Вы", user_text, add_controls=True)
            self.chat_manager.save_message(self.current_chat_id, "user", user_text)
            
            # Отвечаем немедленно без вызова AI
            self.add_message_widget(llama_handler.ASSISTANT_NAME, acknowledgment_response, add_controls=True, is_acknowledgment=True)
            self.chat_manager.save_message(self.current_chat_id, "assistant", acknowledgment_response, speaker_name=llama_handler.ASSISTANT_NAME)
            
            # Обновляем название чата если это первое сообщение
            try:
                messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=5)
                if messages and len(messages) == 2:
                    first_user_msg = messages[0][1] if len(messages[0]) > 1 and messages[0][0] == "user" else ""
                    if first_user_msg and isinstance(first_user_msg, str) and len(first_user_msg) > 0:
                        chat_title = self.chat_manager.generate_smart_title(first_user_msg)
                        self.chat_manager.update_chat_title(self.current_chat_id, chat_title)
                        self.load_chats_list()
            except Exception as e:
                print(f"[SEND] Ошибка обновления названия чата: {e}")
            
            return  # Завершаем метод, не вызывая AI
        # ════════════════════════════════════════════════════════════════



        should_forget = detect_forget_command(user_text)
        if should_forget:
            print("[SEND] Обнаружена команда забыть!")
            
            # Добавляем сообщение пользователя в чат
            self.input_field.clear()
            self.add_message_widget("Вы", user_text, add_controls=True)
            self.chat_manager.save_message(self.current_chat_id, "user", user_text)
            
            # Извлекаем цель забывания
            forget_info = extract_forget_target(user_text)
            
            if forget_info["forget_all"]:
                # ПОЛНАЯ ОЧИСТКА
                print("[SEND] Выполняю полную очистку памяти...")
                
                # Очищаем сообщения чата
                self.chat_manager.clear_chat_messages(self.current_chat_id)
                
                # Очищаем контекстную память всех менеджеров
                clear_chat_all_memories(self.current_chat_id)
                
                # Сбрасываем название на "Новый чат"
                self.chat_manager.update_chat_title(self.current_chat_id, "Новый чат")
                
                # Обновляем список чатов
                self.load_chats_list()
                
                # Ответ от имени AI (а не системы!)
                if self.current_language == "russian":
                    ai_response = "Хорошо, я забыл! 😊"
                else:
                    ai_response = "Okay, I've forgotten! 😊"
                
            else:
                # СЕЛЕКТИВНОЕ УДАЛЕНИЕ
                target = forget_info["target"]
                print(f"[SEND] Выполняю селективное удаление: '{target}'")
                
                try:
                    # Берём менеджер памяти текущей модели — DeepSeek/Mistral/LLaMA
                    context_mgr = get_memory_manager(llama_handler.CURRENT_AI_MODEL_KEY)
                    
                    # Выполняем селективное удаление
                    result = selective_forget_memory(
                        self.current_chat_id, 
                        target, 
                        context_mgr, 
                        self.chat_manager
                    )
                    
                    if result["success"]:
                        print(f"[SEND] ✓ {result['message']}")
                        
                        # Обновляем список чатов
                        self.load_chats_list()
                        
                        # Формируем ответ в зависимости от результата
                        if result["deleted_count"] > 0:
                            if self.current_language == "russian":
                                ai_response = f"✓ Готово! Я забыл информацию о '{target}'. {result['message']}"
                            else:
                                ai_response = f"✓ Done! I've forgotten information about '{target}'. {result['message']}"
                        else:
                            if self.current_language == "russian":
                                ai_response = f"Я не нашёл упоминаний '{target}' в нашей истории. Возможно, мы не обсуждали это."
                            else:
                                ai_response = f"I couldn't find any mentions of '{target}' in our history. Perhaps we didn't discuss this."
                    else:
                        if self.current_language == "russian":
                            ai_response = f"❌ Произошла ошибка при удалении: {result['message']}"
                        else:
                            ai_response = f"❌ An error occurred during deletion: {result['message']}"
                        
                except Exception as e:
                    print(f"[SEND] ✗ Ошибка селективного удаления: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    if self.current_language == "russian":
                        ai_response = f"❌ Не удалось забыть '{target}': {e}"
                    else:
                        ai_response = f"❌ Failed to forget '{target}': {e}"
            
            self.add_message_widget(llama_handler.ASSISTANT_NAME, ai_response, add_controls=False)
            self.chat_manager.save_message(self.current_chat_id, "assistant", ai_response, speaker_name=llama_handler.ASSISTANT_NAME)
            return

        language_switch = detect_language_switch(user_text)
        if language_switch and language_switch != CURRENT_LANGUAGE:
            CURRENT_LANGUAGE = language_switch
            self.current_language = language_switch

            if language_switch == "english":
                notification = "✓ Language switched to English"
            else:
                notification = "✓ Язык изменён на русский"

            self.add_message_widget("Система", notification, add_controls=False)

        self.current_user_message = user_text
        
        # ✅ ВОССТАНОВЛЕНИЕ ПРИ ОТМЕНЕ: сохраняем текст и файлы ДО очистки поля
        self._last_sent_text = user_text
        self._last_sent_files = list(self.attached_files) if self.attached_files else []
        
        # ═══════════════════════════════════════════════════════════
        # УМНАЯ АДАПТИВНАЯ СИСТЕМА ВЕБ-ПОИСКА
        # ═══════════════════════════════════════════════════════════
        
        # DeepSeek: веб-поиск полностью отключён
        if llama_handler.CURRENT_AI_MODEL_KEY == "deepseek":
            print("[SEND] ✗ Веб-поиск ОТКЛЮЧЁН для DeepSeek")
            actual_use_search = False
        # ═══════════════════════════════════════════════════════════
        # ВАЖНО: Если есть прикреплённые файлы - НЕ использовать веб-поиск!
        # ═══════════════════════════════════════════════════════════
        elif self.attached_files:
            print(f"[SEND] 📎 Обнаружены прикреплённые файлы ({len(self.attached_files)})")
            print("[SEND] ✗ Веб-поиск ОТКЛЮЧЁН (есть файлы для анализа)")
            actual_use_search = False
        else:
            # Получаем историю чата для контекстного анализа
            chat_history = self.chat_manager.get_chat_messages(self.current_chat_id, limit=5)
            
            # Анализируем намерение пользователя с учётом контекста
            intent_result = analyze_intent_for_search(user_text, forced_search=self.use_search, chat_history=chat_history)
            
            # ПРИОРИТЕТ: Принудительный поиск переопределяет всё
            if intent_result["forced"]:
                print("[SEND] 🔴 FORCED SEARCH MODE - поиск обязателен (пользователь нажал кнопку)")
                actual_use_search = True
            elif intent_result["requires_search"]:
                print(f"[SEND] ✓ Автоматический поиск активирован (уверенность: {intent_result['confidence']:.2f})")
                print(f"[SEND] Причина: {intent_result['reason']}")
                actual_use_search = True
                # НЕ сохраняем self.use_search = True - это должен делать только пользователь!
            else:
                print("[SEND] ✗ Поиск не требуется")
                actual_use_search = False  # Явно отключаем поиск
        
        # Адаптируем deep_thinking в зависимости от режима AI
        if self.ai_mode == AI_MODE_FAST:
            actual_deep_thinking = False
        elif self.ai_mode == AI_MODE_THINKING:
            actual_deep_thinking = True
        elif self.ai_mode == AI_MODE_PRO:
            actual_deep_thinking = True  # В режиме "Про" всегда используем углублённое мышление
        else:
            actual_deep_thinking = self.deep_thinking  # Fallback на старое значение
        
        print(f"[SEND] Режим AI: {self.ai_mode}")
        print(f"[SEND] Deep thinking: {actual_deep_thinking}")
        print(f"[SEND] Search enabled: {actual_use_search}")
        
        # Сохраняем текущие режимы для восстановления при редактировании
        self.last_message_deep_thinking = self.deep_thinking
        self.last_message_use_search = actual_use_search
        
        # ═══════════════════════════════════════════════════════════════════════════
        # СОХРАНЕНИЕ ПАРАМЕТРОВ ДЛЯ PIPELINE
        # ═══════════════════════════════════════════════════════════════════════════
        # Сохраняем параметры для использования в pipeline
        self.current_ai_mode = self.ai_mode
        self.current_use_search = actual_use_search
        self.current_deep_thinking = actual_deep_thinking
        
        # Проверяем режим редактирования
        # Проверяем режим редактирования
        if not self.is_editing:
            # Обычная отправка - добавляем сообщение
            self.input_field.clear()
            
            # Плавно удаляем системное приветствие если это первое сообщение
            if self.messages_layout.count() == 2:  # Только stretch + приветствие
                first_widget = self.messages_layout.itemAt(0).widget()
                if first_widget and hasattr(first_widget, 'speaker') and first_widget.speaker == "Система":
                    # Запускаем fade-out для приветствия
                    first_widget.fade_out_and_delete()
                    print("[SEND] Системное приветствие плавно удаляется")
            
            self.add_message_widget("Вы", user_text, add_controls=True,
                                     attached_files=list(self.attached_files) if self.attached_files else None)
            
            # Сохраняем сообщение с файлами в БД (полный путь, чтобы можно было открыть позже)
            files_to_save = list(self.attached_files) if self.attached_files else None
            self.chat_manager.save_message(self.current_chat_id, "user", user_text, files_to_save)
            # Обновляем превью в сайдбаре сразу после отправки сообщения пользователя
            self._update_chat_preview(self.current_chat_id, user_text)
            
            # Сохраняем поворот диалога в memory_manager (для истории ИИ)
            try:
                _current_model = llama_handler.CURRENT_AI_MODEL_KEY
                get_memory_manager(_current_model).save_message(self.current_chat_id, "user", user_text)
            except Exception as _me:
                print(f"[SEND] ⚠️ Ошибка сохранения user-сообщения в memory: {_me}")
            
            # Сохраняем список файлов в контекстную память (для AI)
            if self.attached_files:
                try:
                    _current_model = llama_handler.CURRENT_AI_MODEL_KEY
                    context_mgr = get_memory_manager(_current_model)
                    files_list = [os.path.basename(f) for f in self.attached_files]
                    files_info = f"📎 Файлы к сообщению '{user_text[:30]}...': {', '.join(files_list)}"
                    context_mgr.save_context_memory(self.current_chat_id, "message_files", files_info)
                    print(f"[SEND] ✓ Сохранена информация о {len(files_list)} файлах")
                except Exception as e:
                    print(f"[SEND] ⚠️ Ошибка сохранения информации о файлах: {e}")
            
            # ═══ ЛОГИКА СТАРТОВОГО ЧАТА ═══
            # Если это стартовый чат и первое сообщение - помечаем что он больше не пустой
            if hasattr(self, 'startup_chat_id') and self.current_chat_id == self.startup_chat_id:
                self.startup_chat_has_messages = True
                print(f"[STARTUP_CHAT] Стартовый чат {self.startup_chat_id} теперь содержит сообщения")
            
            # ═══════════════════════════════════════════════════════════════════════════
            # ЗАПУСК ПОЭТАПНОГО STATUS PIPELINE В НИЖНЕМ ЛЕВОМ УГЛУ
            # ═══════════════════════════════════════════════════════════════════════════
            # ЭТАП 1: Обработка запроса (немедленно)
            # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
            self.status_label.clear()
            self.status_label.setText("обрабатываю запрос…")
            print(f"[STATUS_PIPELINE] Этап 1: обрабатываю запрос…")
            
            # ЭТАП 2: Анализ (через 300ms)
            QtCore.QTimer.singleShot(300, lambda: self._status_pipeline_analyzing())
            
            print("[SEND] Новое сообщение добавлено")
        else:
            # Режим редактирования - НЕ добавляем сообщение, оно уже было удалено
            self.input_field.clear()
            self.add_message_widget("Вы", user_text, add_controls=True,
                                     attached_files=list(self.attached_files) if self.attached_files else None)
            
            # Сохраняем сообщение с файлами в БД (полный путь для открытия)
            files_to_save = list(self.attached_files) if self.attached_files else None
            self.chat_manager.save_message(self.current_chat_id, "user", user_text, files_to_save)
            # Обновляем превью (режим редактирования)
            self._update_chat_preview(self.current_chat_id, user_text)
            
            # Сохраняем поворот диалога в memory_manager (для истории ИИ)
            try:
                _current_model = llama_handler.CURRENT_AI_MODEL_KEY
                get_memory_manager(_current_model).save_message(self.current_chat_id, "user", user_text)
            except Exception as _me:
                print(f"[SEND] ⚠️ Ошибка сохранения user-сообщения в memory (edit): {_me}")
            
            # Сохраняем список файлов в контекстную память (для AI)
            if self.attached_files:
                try:
                    _current_model = llama_handler.CURRENT_AI_MODEL_KEY
                    context_mgr = get_memory_manager(_current_model)
                    files_list = [os.path.basename(f) for f in self.attached_files]
                    files_info = f"📎 Файлы к сообщению '{user_text[:30]}...': {', '.join(files_list)}"
                    context_mgr.save_context_memory(self.current_chat_id, "message_files", files_info)
                    print(f"[SEND] ✓ Сохранена информация о {len(files_list)} файлах (редактирование)")
                except Exception as e:
                    print(f"[SEND] ⚠️ Ошибка сохранения информации о файлах: {e}")
            
            # Запуск pipeline при регенерации
            # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
            self.status_label.clear()
            self.status_label.setText("обрабатываю запрос…")
            print(f"[STATUS_PIPELINE] Регенерация - Этап 1: обрабатываю запрос…")
            QtCore.QTimer.singleShot(300, lambda: self._status_pipeline_analyzing())
            
            # Сбрасываем флаг редактирования
            self.is_editing = False
            self.editing_message_text = ""
            print("[SEND] Отредактированное сообщение отправлено")

        self.input_field.setEnabled(False)
        _set_stop_icon(self.send_btn)
        self.send_btn.setEnabled(True)
        self.is_generating = True

        # ── Разносим анимации по времени чтобы Qt не задыхался от одновременных операций ──
        # Затемнение поля — сразу (не конкурирует с add_message_widget)
        self._dim_input_for_generation()
        # Анимация точек — через 60ms, после того как layout сообщения завершится
        QtCore.QTimer.singleShot(60, self.start_status_animation)
        
        # Запускаем таймер обдумывания
        self.thinking_start_time = time.time()

        # Запускаем воркер с ПРАВИЛЬНЫМИ флагами и режимом AI
        _locked_model_key = llama_handler.CURRENT_AI_MODEL_KEY
        print(f"[SEND] Модель зафиксирована: {_locked_model_key}")
        worker = AIWorker(user_text, self.current_language, actual_deep_thinking, actual_use_search, False, self.chat_manager, self.current_chat_id, self.attached_files, self.ai_mode, model_key_override=_locked_model_key)
        worker.signals.chunk.connect(self._on_stream_chunk)
        worker.signals.finished.connect(self.handle_response)
        self.current_worker = worker  # Сохраняем ссылку на текущего воркера
        self._current_request_id = worker.request_id  # Запоминаем ID запроса
        
        # ✅ ИСПРАВЛЕНИЕ: Сохраняем worker в список для предотвращения удаления signals
        self.active_workers.append(worker)
        # Очищаем список от завершённых workers (максимум 5)
        if len(self.active_workers) > 5:
            self.active_workers = self.active_workers[-5:]
        
        self.threadpool.start(worker)
        print(f"[SEND] Запущен воркер генерации (search={actual_use_search}, deep={actual_deep_thinking}, mode={self.ai_mode})")
        
        # Очищаем прикреплённые файлы после отправки
        if self.attached_files:
            print(f"[SEND] Файлы отправлены в модель: {', '.join([os.path.basename(f) for f in self.attached_files])}")
            self.clear_attached_file()  # Очищаем все файлы

    def _cleanup_regen_state(self, reason: str = ""):
        """Снимает затемнение с пузыря перегенерации и сбрасывает target-виджет.

        Вызывается из ВСЕХ точек где генерация прерывается или игнорируется,
        чтобы пузырь не оставался тёмным и следующий ответ не попал в него.
        """
        _w = getattr(self, '_regen_target_widget', None)
        if _w is not None:
            try:
                _w._set_regen_dim(False)
            except Exception:
                pass
            self._regen_target_widget = None
            print(f"[REGEN_CLEANUP] ✓ Состояние перегенерации сброшено{': ' + reason if reason else ''}")

    def handle_response(self, response: str, sources: list = None):
        """Обработка ответа AI с полной защитой от ошибок (УЛУЧШЕНО: проверка отмены)"""
        try:
            # ✅ GUARD 1: СТРОГАЯ проверка - игнорируем сообщения для другого чата
            # Это предотвращает появление "чужих" сообщений при переключении чатов
            if hasattr(self, 'current_worker'):
                # Если воркер был отменён (current_worker = None), игнорируем его ответ
                if self.current_worker is None:
                    print(f"[HANDLE_RESPONSE] ⚠️ Игнорируем ответ отменённого воркера (current_worker = None)")
                    self._cleanup_regen_state("воркер отменён (None)")
                    return
                
                # ✅ GUARD 1.5: Проверяем флаг отмены в worker
                if hasattr(self.current_worker, '_cancelled') and self.current_worker._cancelled:
                    print(f"[HANDLE_RESPONSE] ⚠️ Игнорируем ответ отменённого воркера (флаг _cancelled = True)")
                    self._cleanup_regen_state("воркер помечен _cancelled")
                    return
                # ✅ GUARD 1.6: Проверяем совпадение request_id (защита от "призраков")
                if hasattr(self, '_current_request_id') and hasattr(self.current_worker, 'request_id'):
                    if self.current_worker.request_id != self._current_request_id:
                        print(f"[HANDLE_RESPONSE] ⚠️ Игнорируем устаревший запрос (id несовпадение)")
                        self._cleanup_regen_state("устаревший request_id")
                        return
                
                # ✅ GUARD 2: Проверяем что воркер принадлежит текущему чату
                if hasattr(self.current_worker, 'chat_id') and self.current_worker.chat_id != self.current_chat_id:
                    print(f"[HANDLE_RESPONSE] ⚠️ Игнорируем ответ от другого чата (воркер chat_id={self.current_worker.chat_id}, текущий={self.current_chat_id})")
                    self._cleanup_regen_state("другой чат")
                    return
            
            # ВАЖНО: Сбрасываем флаг генерации
            self.is_generating = False

            # Вычисляем время обдумывания с защитой
            thinking_time_to_show = 0
            try:
                if hasattr(self, 'thinking_start_time') and self.thinking_start_time:
                    self.thinking_elapsed_time = time.time() - self.thinking_start_time
                    print(f"[THINKING] Время обдумывания: {self.thinking_elapsed_time:.2f}s")
                    # Передаём время если был режим "думающий", "про" или "поиск"
                    show_timer = (self.ai_mode in [AI_MODE_THINKING, AI_MODE_PRO]) or self.use_search
                    thinking_time_to_show = self.thinking_elapsed_time if show_timer else 0
                else:
                    self.thinking_elapsed_time = 0
            except Exception as e:
                print(f"[HANDLE_RESPONSE] Ошибка расчёта времени: {e}")
                self.thinking_elapsed_time = 0
            
            # ═══════════════════════════════════════════════════════════════════════════
            # ✅ УНИВЕРСАЛЬНЫЙ ФИЛЬТР ТЕХНИЧЕСКИХ ОШИБОК
            # ═══════════════════════════════════════════════════════════════════════════
            
            # Проверка 1: Пустой или None ответ
            if not response or response is None:
                print(f"[ERROR_FILTER] ✗ Получен пустой ответ (None или пустая строка)")
                # НЕ создаём сообщение, полностью игнорируем
                return
            
            # Проверка 2: Не строка
            if not isinstance(response, str):
                print(f"[ERROR_FILTER] ✗ Ответ не является строкой: {type(response)}")
                # НЕ создаём сообщение
                return
            
            # Проверка 3: Признаки технических ошибок (только явные системные ошибки Python)
            error_indicators = [
                "Traceback (most recent call last)",
                "object is not iterable",
            ]
            
            error_prefixes = [
                "[Ошибка]",
                "File \"",
            ]
            
            # Проверяем содержимое на технические ошибки
            response_lower = response.lower()
            has_error = False
            
            for indicator in error_indicators:
                if indicator in response or indicator.lower() in response_lower:
                    print(f"[ERROR_FILTER] ✗ Обнаружен индикатор ошибки: {indicator}")
                    has_error = True
                    break
            
            # Проверяем начало строки
            if not has_error:
                for prefix in error_prefixes:
                    if response.startswith(prefix):
                        print(f"[ERROR_FILTER] ✗ Ответ начинается с: {prefix}")
                        has_error = True
                        break
            
            # Если обнаружена техническая ошибка
            if has_error:
                print(f"[ERROR_FILTER] ✗ Техническая ошибка обнаружена, показываем нейтральное сообщение")
                print(f"[ERROR_FILTER] Оригинальный ответ (логируется): {response[:200]}...")
                
                # Заменяем на нейтральное сообщение
                if self.current_language == "russian":
                    response = "Не удалось обработать запрос. Попробуйте ещё раз."
                else:
                    response = "Failed to process request. Please try again."
            
            # ═══════════════════════════════════════════════════════════════════════════
            
            # Проверяем валидность ответа (дополнительная проверка)
            if not response:
                response = "[Ошибка] Пустой ответ от модели"
                print(f"[HANDLE_RESPONSE] ✗ Получен пустой ответ")
            elif not isinstance(response, str):
                response = str(response) if response else "[Ошибка] Некорректный ответ"
                print(f"[HANDLE_RESPONSE] ✗ Ответ не строка, конвертирован")
            
            # Формируем историю действий (для логики, без UI)
            action_history = []
            
            # Режим AI
            if self.ai_mode == AI_MODE_FAST:
                action_history.append("[✓] быстрый режим")
            elif self.ai_mode == AI_MODE_THINKING:
                action_history.append("[✓] думающий режим")
            elif self.ai_mode == AI_MODE_PRO:
                action_history.append("[✓] про режим")
            
            # Поиск
            if hasattr(self, 'last_message_use_search') and self.last_message_use_search:
                action_history.append("[✓] найдено в интернете")
            
            # Добавляем сообщение с защитой
            # Определяем имя модели которая реально ответила (для пузыря)
            try:
                _response_model_key = (
                    self.current_worker.model_key
                    if hasattr(self, 'current_worker') and self.current_worker
                       and hasattr(self.current_worker, 'model_key')
                    else llama_handler.CURRENT_AI_MODEL_KEY
                )
                _response_speaker = llama_handler.SUPPORTED_MODELS.get(
                    _response_model_key,
                    llama_handler.SUPPORTED_MODELS.get(llama_handler.CURRENT_AI_MODEL_KEY)
                )[1]
            except Exception:
                _response_speaker = llama_handler.ASSISTANT_NAME

            # ── Обновляем виджет или создаём новый ─────────────────────────────
            _regen_widget = getattr(self, '_regen_target_widget', None)
            self._last_regen_widget = _regen_widget  # для save_message ниже

            # ── Парсим сгенерированные файлы из ответа ─────────────────────
            # КРИТИЧНО: вызываем только если в ответе реально есть теги файлов.
            # parse_generated_files на каждом ответе → паттерн 5 (markdown code block)
            # ловит случайные совпадения в обычных объяснениях кода или текста,
            # и модель начинает "общаться через файлы" без всякого запроса.
            _has_file_tags = "[FILE:" in response or "<FILE " in response or "[ФАЙЛ:" in response
            if _has_file_tags:
                response, _gen_files = parse_generated_files(response)
            else:
                _gen_files = []
            if _gen_files:
                print(f"[FILE_GEN] ✓ Найдено файлов в ответе: {len(_gen_files)} → {[f['filename'] for f in _gen_files]}")

            if _regen_widget is not None:
                # Перегенерация: добавляем в историю существующего виджета
                try:
                    _regen_widget.add_regen_entry(
                        response,
                        thinking_time=thinking_time_to_show,
                        action_history=action_history,
                        sources=sources or [],
                        speaker=_response_speaker
                    )
                    # Обновляем/добавляем карточки файлов при перегенерации
                    if _gen_files:
                        _regen_widget._generated_files = _gen_files
                        if _regen_widget._generated_files_widget is not None:
                            try:
                                _regen_widget._generated_files_widget.setParent(None)
                                _regen_widget._generated_files_widget.deleteLater()
                            except Exception:
                                pass
                        try:
                            _new_gw = GeneratedFileWidget(_gen_files, main_window=self, parent=_regen_widget)
                            # Найти col_widget → col_layout (второй дочерний виджет)
                            _col_widget = None
                            for child in _regen_widget.children():
                                if isinstance(child, QtWidgets.QWidget):
                                    _col_widget = child
                                    break
                            if _col_widget and _col_widget.layout():
                                _col_widget.layout().addWidget(_new_gw, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
                            _regen_widget._generated_files_widget = _new_gw
                        except Exception as _ge:
                            print(f"[FILE_GEN] ⚠️ Ошибка обновления карточек при регенерации: {_ge}")
                    print("[HANDLE_RESPONSE] ✓ Ответ добавлен в историю перегенерации виджета")
                    # Авто-скролл после перегенерации:
                    # layout пересчитывает высоту асинхронно → ждём 120мс и скроллим.
                    # Двойной таймер: первый активирует layout, второй скроллит уже с верным maximum().
                    if getattr(self, "auto_scroll_enabled", False):
                        def _regen_scroll():
                            self.messages_layout.activate()
                            self.messages_widget.updateGeometry()
                            sb = self.scroll_area.verticalScrollBar()
                            def _do():
                                target = sb.maximum()
                                cur = sb.value()
                                if target <= cur:
                                    return
                                anim = QtCore.QPropertyAnimation(sb, b"value", self)
                                anim.setDuration(350)
                                anim.setStartValue(cur)
                                anim.setEndValue(target)
                                anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                                anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
                                if hasattr(self, 'scroll_to_bottom_btn'):
                                    self.scroll_to_bottom_btn.smooth_hide()
                            QtCore.QTimer.singleShot(80, _do)
                        QtCore.QTimer.singleShot(40, _regen_scroll)
                except Exception as e:
                    print(f"[HANDLE_RESPONSE] ✗ Ошибка add_regen_entry: {e}, создаём новый виджет")
                    try:
                        self.add_message_widget(_response_speaker, response, add_controls=True, thinking_time=thinking_time_to_show, action_history=action_history, sources=sources or [], generated_files=_gen_files)
                    except Exception as e2:
                        print(f"[HANDLE_RESPONSE] ✗ Критическая ошибка виджета: {e2}")
                finally:
                    self._regen_target_widget = None  # сбрасываем цель
            else:
                # Обычный ответ: завершаем стрим или создаём виджет
                # Останавливаем flush-таймер
                if hasattr(self, '_stream_flush_timer'):
                    self._stream_flush_timer.stop()

                _sw = getattr(self, '_stream_widget', None)
                _stream_was_active = getattr(self, '_stream_active', False)
                # Сбрасываем флаги стрима
                self._stream_active = False
                self._stream_widget = None
                self._stream_buf    = ""
                self._stream_raw    = ""
                # Дренируем оставшуюся очередь символов (если ответ короткий)
                _char_queue = getattr(self, '_char_queue', None)
                if _char_queue:
                    _char_queue.clear()
                self._displayed_text = ""

                if _stream_was_active and _sw is not None:
                    # ── Стрим завершён: финализируем виджет на месте ──────────────
                    try:
                        # 1. Сбрасываем зафиксированную высоту — теперь Qt сам определит нужный размер
                        if hasattr(_sw, 'message_container'):
                            _sw.message_container.setMinimumHeight(0)
                        # 2. Применяем markdown к финальному тексту
                        _sw.text = response
                        _formatted = format_text_with_markdown_and_math(response)
                        _sw.message_label.setText(
                            f"<b style='color:{_sw._speaker_color};'>{_sw.speaker}:</b><br>{_formatted}"
                        )
                        # 2. Показываем панель кнопок (она уже в layout, просто hidden)
                        if hasattr(_sw, 'controls_widget'):
                            _sw.controls_widget.setVisible(True)
                        if hasattr(_sw, 'copy_button') and _sw.copy_button:
                            _sw.copy_button.setVisible(True)
                        if hasattr(_sw, 'regenerate_button') and _sw.regenerate_button:
                            _sw.regenerate_button.setVisible(True)
                        # 3. Обновляем manage_buttons (скрываем кнопку regen у предыдущих)
                        def _manage():
                            try:
                                for i in range(self.messages_layout.count()):
                                    item = self.messages_layout.itemAt(i)
                                    if item and item.widget() and hasattr(item.widget(), 'speaker'):
                                        w = item.widget()
                                        if w.speaker not in ("Вы", "Система") and w != _sw:
                                            if hasattr(w, 'regenerate_button') and w.regenerate_button:
                                                w.regenerate_button.setVisible(False)
                            except Exception:
                                pass
                        QtCore.QTimer.singleShot(50, _manage)
                        print("[HANDLE_RESPONSE] ✓ Stream-виджет финализирован на месте")
                    except Exception as e:
                        print(f"[HANDLE_RESPONSE] ✗ Ошибка финализации стрима: {e}")
                        try:
                            self.add_message_widget(_response_speaker, response, add_controls=True, thinking_time=thinking_time_to_show, action_history=action_history, sources=sources or [], generated_files=_gen_files)
                        except Exception:
                            pass
                else:
                    # Стрима не было (поиск в интернете, перегенерация и т.п.)
                    try:
                        self.add_message_widget(_response_speaker, response, add_controls=True, thinking_time=thinking_time_to_show, action_history=action_history, sources=sources or [], generated_files=_gen_files)
                    except Exception as e:
                        print(f"[HANDLE_RESPONSE] ✗ Ошибка add_message_widget: {e}")
                        try:
                            self.add_message_widget(_response_speaker, response, add_controls=True, thinking_time=0, action_history=action_history, sources=sources or [], generated_files=_gen_files)
                        except Exception as e2:
                            print(f"[HANDLE_RESPONSE] ✗ Критическая ошибка виджета: {e2}")
            
            # Сохраняем в БД с защитой
            # При перегенерации — сразу передаём полную историю вариантов,
            # чтобы она была доступна при следующей загрузке чата.
            try:
                if hasattr(self, 'chat_manager') and hasattr(self, 'current_chat_id'):
                    _save_regen_hist = None
                    if _regen_widget is not None or getattr(self, '_last_regen_widget', None):
                        _target = _regen_widget if _regen_widget is not None else self._last_regen_widget
                        try:
                            _save_regen_hist = list(_target._regen_history)
                        except Exception:
                            pass
                    self.chat_manager.save_message(
                        self.current_chat_id, "assistant", response,
                        sources=sources or [],
                        speaker_name=_response_speaker,
                        regen_history=_save_regen_hist,
                        generated_files=_gen_files if _gen_files else None,
                    )
                    # Обновляем превью в сайдбаре сразу после получения ответа ИИ
                    self._update_chat_preview(self.current_chat_id, response)
                    if _save_regen_hist:
                        print(f"[HANDLE_RESPONSE] ✓ Сохранено с историей перегенерации ({len(_save_regen_hist)} вариантов)")
                    if _gen_files:
                        print(f"[HANDLE_RESPONSE] ✓ Сохранено {len(_gen_files)} файлов в БД")
                    # Сохраняем ответ ИИ в memory_manager (для истории контекста)
                    try:
                        _resp_model_key = (
                            self.current_worker.model_key
                            if hasattr(self, 'current_worker') and self.current_worker
                               and hasattr(self.current_worker, 'model_key')
                            else llama_handler.CURRENT_AI_MODEL_KEY
                        )
                        get_memory_manager(_resp_model_key).save_message(
                            self.current_chat_id, "assistant",
                            # Сохраняем ЧИСТЫЙ текст без [FILE:...] тегов.
                            # Если сохранить сырой ответ с тегами — модель видит их
                            # в истории и начинает генерировать файлы при каждом запросе.
                            response  # response уже очищен parse_generated_files выше
                        )
                    except Exception as _me:
                        print(f"[HANDLE_RESPONSE] ⚠️ Ошибка сохранения assistant в memory: {_me}")
                else:
                    print(f"[HANDLE_RESPONSE] ✗ Нет chat_manager или current_chat_id")
            except Exception as e:
                print(f"[HANDLE_RESPONSE] ✗ Ошибка сохранения в БД: {e}")
            
            # Сбрасываем таймер
            self.thinking_start_time = None
            
            # ═══════════════════════════════════════════════════════════════════════════
            # ОЧИСТКА СТАТУСА ПОСЛЕ ЗАВЕРШЕНИЯ
            # ═══════════════════════════════════════════════════════════════════════════
            # ✅ ИСПРАВЛЕНИЕ: Сбрасываем status_base_text чтобы не показывать "регенерация" постоянно
            if hasattr(self, 'status_base_text'):
                self.status_base_text = ""
            
            # Плавно очищаем статус через 500ms после получения ответа
            QtCore.QTimer.singleShot(500, lambda: self.status_label.setText(""))
            print(f"[STATUS_PIPELINE] Статус будет очищен через 500ms")
            
            # Автоматическое именование чата с защитой
            try:
                messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=5)
                if messages and len(messages) == 2:
                    first_user_msg = messages[0][1] if len(messages[0]) > 1 and messages[0][0] == "user" else ""
                    if first_user_msg and isinstance(first_user_msg, str) and len(first_user_msg) > 0:
                        chat_title = self.chat_manager.generate_smart_title(first_user_msg)
                        self.chat_manager.update_chat_title(self.current_chat_id, chat_title)
                        self.load_chats_list()
            except Exception as e:
                print(f"[HANDLE_RESPONSE] Ошибка автоименования: {e}")
            
        except Exception as e:
            print(f"[HANDLE_RESPONSE] ✗ Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # ВСЕГДА восстанавливаем UI
            try:
                self.is_generating = False  # Гарантированно сбрасываем флаг генерации
                self.send_btn.setEnabled(True)
                _set_send_icon(self.send_btn)
                self.input_field.setEnabled(True)
                self.input_field.setFocus()
                self.activateWindow()
                self.raise_()
                # Останавливаем анимацию точек
                if hasattr(self, 'stop_status_animation'):
                    self.stop_status_animation()
                # Плавно восстанавливаем яркость поля ввода и mic_btn
                self._restore_input_after_generation()
                if getattr(self, '_is_regenerating', False):
                    self._is_regenerating = False
            except Exception as e:
                print(f"[HANDLE_RESPONSE] Ошибка восстановления UI: {e}")


    def regenerate_last_response(self, force_model_key: str = None):
        """Перегенерировать последний ответ ассистента
        
        ЛОГИКА:
        1. Проверяем, идёт ли генерация - если да, отменяем и запускаем новую
        2. Находим последнее сообщение ассистента в UI
        3. Получаем последнее сообщение пользователя из БД
        4. Удаляем последний ответ ассистента (из UI и БД)
        5. Перезапускаем генерацию с последним запросом пользователя
        
        force_model_key — если передан, используется эта модель вместо текущей
        (для кнопки «Перегенерировать через другую модель»)
        """
        print(f"[REGENERATE] ▶ Начинаем регенерацию последнего ответа"
              + (f" (модель: {force_model_key})" if force_model_key else ""))
        
        # Если генерация идёт - останавливаем её
        if self.is_generating:
            self.is_generating = False
            if hasattr(self, 'current_worker'):
                self.current_worker = None
            print("[REGENERATE] Отменяем текущую генерацию для перезапуска")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: НАХОДИМ ПОСЛЕДНИЙ ВИДЖЕТ АССИСТЕНТА В UI
        # ═══════════════════════════════════════════════════════════════
        last_assistant_widget = None
        for i in range(self.messages_layout.count() - 1, -1, -1):
            item = self.messages_layout.itemAt(i)
            if item and item.widget() and hasattr(item.widget(), 'speaker'):
                widget = item.widget()
                if widget.speaker != "Вы" and widget.speaker != "Система":
                    last_assistant_widget = widget
                    print(f"[REGENERATE] Найден последний виджет ассистента на позиции {i}")
                    break
        
        if not last_assistant_widget:
            print("[REGENERATE] ✗ Не найдено сообщение ассистента для регенерации")
            return
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: ПОЛУЧАЕМ ПОСЛЕДНЕЕ СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ ИЗ БД
        # ═══════════════════════════════════════════════════════════════
        messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=50)
        
        last_user_msg = None
        for msg_data in reversed(messages):
            role, content = msg_data[0], msg_data[1]
            if role == "user":
                last_user_msg = content
                break
        
        if not last_user_msg:
            print("[REGENERATE] ✗ Нет сообщений пользователя в текущем чате")
            return
        
        print(f"[REGENERATE] Найдено последнее сообщение пользователя: {last_user_msg[:50]}...")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 3: СОХРАНЯЕМ ВИДЖЕТ ДЛЯ ДОБАВЛЕНИЯ В ИСТОРИЮ
        # (НЕ удаляем — новый ответ добавится через add_regen_entry)
        # ═══════════════════════════════════════════════════════════════
        self._regen_target_widget = last_assistant_widget
        # Затемняем пузырь пока идёт генерация нового варианта
        try:
            last_assistant_widget._set_regen_dim(True)
        except Exception:
            pass
        print("[REGENERATE] ✓ Виджет сохранён как цель для истории перегенерации")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 4: УДАЛЯЕМ ПОСЛЕДНЕЕ СООБЩЕНИЕ АССИСТЕНТА ИЗ БД
        # ═══════════════════════════════════════════════════════════════
        conn = sqlite3.connect("chats.db")
        cur = conn.cursor()
        
        # Проверяем, что последнее сообщение - от ассистента
        cur.execute("""
            SELECT role FROM chat_messages 
            WHERE chat_id = ? 
            ORDER BY id DESC LIMIT 1
        """, (self.current_chat_id,))
        
        last_role = cur.fetchone()
        if last_role and last_role[0] == "assistant":
            cur.execute("""
                DELETE FROM chat_messages 
                WHERE chat_id = ? AND id = (
                    SELECT id FROM chat_messages 
                    WHERE chat_id = ? 
                    ORDER BY id DESC LIMIT 1
                )
            """, (self.current_chat_id, self.current_chat_id))
            conn.commit()
            print("[REGENERATE] ✓ Сообщение ассистента удалено из БД")
        else:
            print("[REGENERATE] ⚠️ Последнее сообщение в БД не от ассистента")
        
        conn.close()

        # ── Удаляем последний assistant-ответ из memory_manager ────────────
        # КРИТИЧНО: chat_manager.save_message удаляет из chats.db, но
        # memory_manager (context_memory.db / deepseek_memory.db и т.д.)
        # при каждом ответе добавляет запись и НИКОГДА её не удаляет.
        # После нескольких перегенераций в памяти накапливаются:
        # ..., user, assistant_v1, assistant_v2, assistant_v3 ...
        # Модель видит два assistant подряд и начинает "разговаривать сама с собой".
        # Решение: удалять последний assistant-элемент из memory_manager здесь.
        try:
            _regen_mem_mgr = get_memory_manager(llama_handler.CURRENT_AI_MODEL_KEY)
            if hasattr(_regen_mem_mgr, 'delete_last_assistant_message'):
                _regen_mem_mgr.delete_last_assistant_message(self.current_chat_id)
            elif hasattr(_regen_mem_mgr, 'get_messages'):
                # Универсальный fallback через прямой SQL по имени таблицы
                import sqlite3 as _sq
                # Определяем файл БД по типу менеджера
                _db_map = {
                    'ContextMemoryManager':    'context_memory.db',
                    'DeepSeekMemoryManager':   'deepseek_memory.db',
                    'MistralMemoryManager':    'mistral_memory.db',
                    'QwenMemoryManager':       'qwen_memory.db',
                }
                _mgr_name = type(_regen_mem_mgr).__name__
                _db_file  = _db_map.get(_mgr_name)
                if _db_file and os.path.exists(_db_file):
                    _rc = _sq.connect(_db_file)
                    # Автоматически находим таблицу с колонками chat_id + role + id
                    _tbls = _rc.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                    _tbl = None
                    for (_t,) in _tbls:
                        _cols = {r[1] for r in _rc.execute(f"PRAGMA table_info({_t})")}
                        if {'id', 'chat_id', 'role', 'content'}.issubset(_cols):
                            # Берём таблицу с "messages" в имени если есть
                            if 'message' in _t.lower():
                                _tbl = _t
                                break
                    if _tbl:
                        _rc.execute(f"""
                            DELETE FROM {_tbl}
                            WHERE chat_id = ? AND role = 'assistant'
                              AND id = (
                                  SELECT id FROM {_tbl}
                                  WHERE chat_id = ? AND role = 'assistant'
                                  ORDER BY id DESC LIMIT 1
                              )
                        """, (self.current_chat_id, self.current_chat_id))
                        _rows = _rc.execute("SELECT changes()").fetchone()[0]
                        _rc.commit()
                        print(f"[REGENERATE] ✓ memory_manager ({_mgr_name}/{_tbl}): удалено {_rows} assistant-записей")
                    else:
                        print(f"[REGENERATE] ⚠️ Таблица messages не найдена в {_db_file}")
                    _rc.close()
                else:
                    print(f"[REGENERATE] ⚠️ Неизвестный/отсутствующий memory_manager: {_mgr_name}")
        except Exception as _rme:
            print(f"[REGENERATE] ⚠️ Ошибка очистки memory_manager: {_rme}")
        
        # Отправляем запрос заново
        self._is_regenerating = True  # флаг: идёт перегенерация (не обычный запрос)
        self.input_field.setEnabled(False)
        _set_stop_icon(self.send_btn)
        self.send_btn.setEnabled(True)
        self.is_generating = True
        # Плавно затемняем поле ввода и кнопку голоса
        self._dim_input_for_generation()
        
        # Адаптируем deep_thinking в зависимости от режима AI (как в send_message)
        if self.ai_mode == AI_MODE_FAST:
            actual_deep_thinking = False
        elif self.ai_mode == AI_MODE_THINKING:
            actual_deep_thinking = True
        elif self.ai_mode == AI_MODE_PRO:
            actual_deep_thinking = True
        else:
            actual_deep_thinking = self.deep_thinking
        
        # Устанавливаем статус перегенерации с учётом режима
        if self.ai_mode == AI_MODE_PRO:
            self.status_base_text = "⏳ Перегенерация (режим Про)"
        elif self.ai_mode == AI_MODE_THINKING:
            self.status_base_text = "⏳ Перегенерация (режим Думающий)"
        elif self.ai_mode == AI_MODE_FAST:
            self.status_base_text = "⏳ Перегенерация (быстрый режим)"
        else:
            self.status_base_text = "⏳ Перегенерирую сообщение"
        
        self.status_label.setText(self.status_base_text)
        self.start_status_animation()
        
        # Запускаем таймер обдумывания
        self.thinking_start_time = time.time()
        
        self.current_user_message = last_user_msg

        # Поиск при регенерации: приоритет — был ли поиск при оригинальном запросе
        if hasattr(self, 'last_message_use_search') and self.last_message_use_search:
            actual_use_search = True
        elif self.use_search:
            actual_use_search = True
        else:
            ir = analyze_intent_for_search(last_user_msg, forced_search=False)
            actual_use_search = ir["requires_search"]
        self.last_message_use_search = actual_use_search
        print(f"[REGENERATE] поиск={'вкл' if actual_use_search else 'выкл'}")

        # Если передана другая модель — обновляем статус соответственно
        if force_model_key and force_model_key != llama_handler.CURRENT_AI_MODEL_KEY:
            other_display = llama_handler.SUPPORTED_MODELS.get(
                force_model_key, ("", force_model_key))[1]
            self.status_base_text = f"⏳ Перегенерация через {other_display}"
            self.status_label.setText(self.status_base_text)

        worker = AIWorker(last_user_msg, self.current_language, actual_deep_thinking,
                         actual_use_search, False, self.chat_manager, self.current_chat_id,
                         None, self.ai_mode,
                         model_key_override=force_model_key)
        worker.signals.chunk.connect(self._on_stream_chunk)
        worker.signals.finished.connect(self.handle_response)
        self._current_request_id = worker.request_id
        self.current_worker = worker
        
        # ✅ ИСПРАВЛЕНИЕ: Сохраняем worker в список
        self.active_workers.append(worker)
        if len(self.active_workers) > 5:
            self.active_workers = self.active_workers[-5:]
        
        self.threadpool.start(worker)
        print(f"[REGENERATE] Запущена новая генерация (модель: {force_model_key or llama_handler.CURRENT_AI_MODEL_KEY}, "
              f"режим: {self.ai_mode}, deep_thinking: {actual_deep_thinking}, search: {self.use_search})")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # STATUS PIPELINE - ПОЭТАПНОЕ ОБНОВЛЕНИЕ СТАТУСА В НИЖНЕМ ЛЕВОМ УГЛУ
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _status_pipeline_analyzing(self):
        """ЭТАП 2: Анализ запроса"""
        if not self.is_generating:
            # Генерация уже остановлена, не продолжаем pipeline
            return
        
        # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
        self.status_label.clear()
        self.status_label.setText("анализирую…")
        print(f"[STATUS_PIPELINE] Этап 2: анализирую…")
        
        # Переходим к следующему этапу в зависимости от режима
        if self.current_deep_thinking or self.current_ai_mode in [AI_MODE_THINKING, AI_MODE_PRO]:
            # Если думающий или про режим - показываем этап "думаю"
            QtCore.QTimer.singleShot(400, lambda: self._status_pipeline_thinking())
        elif self.current_use_search or self.current_ai_mode == AI_MODE_PRO:
            # Если есть поиск или про режим - переходим к поиску
            QtCore.QTimer.singleShot(400, lambda: self._status_pipeline_searching())
        else:
            # Быстрый режим без поиска - сразу к формированию ответа
            QtCore.QTimer.singleShot(400, lambda: self._status_pipeline_generating())
    
    def _status_pipeline_thinking(self):
        """ЭТАП 3: Обдумывание (только для думающего/про режима)"""
        if not self.is_generating:
            return
        
        # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
        self.status_label.clear()
        self.status_label.setText("думаю…")
        print(f"[STATUS_PIPELINE] Этап 3: думаю…")
        
        # Переходим к поиску или генерации
        if self.current_use_search or self.current_ai_mode == AI_MODE_PRO:
            QtCore.QTimer.singleShot(600, lambda: self._status_pipeline_searching())
        else:
            QtCore.QTimer.singleShot(600, lambda: self._status_pipeline_generating())
    
    def _status_pipeline_searching(self):
        """ЭТАП 4: Поиск информации (если активирован поиск или про режим)"""
        if not self.is_generating:
            return
        
        # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
        self.status_label.clear()
        self.status_label.setText("ищу информацию…")
        print(f"[STATUS_PIPELINE] Этап 4: ищу информацию…")
        
        # Переходим к формированию ответа
        QtCore.QTimer.singleShot(800, lambda: self._status_pipeline_generating())
    
    def _status_pipeline_generating(self):
        """ЭТАП 5: Формирование ответа"""
        if not self.is_generating:
            return
        
        # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
        self.status_label.clear()
        self.status_label.setText("формирую ответ…")
        print(f"[STATUS_PIPELINE] Этап 5: формирую ответ…")
        
        # После завершения статус будет очищен в handle_response
    
    def edit_last_message(self, old_text=None):
        """Редактировать последнее сообщение пользователя
        
        ЛОГИКА:
        1. Получить последний user-запрос из текущего чата
        2. Вернуть текст в поле ввода
        3. Удалить последние 2 сообщения (user + assistant) + ActionIndicatorRow из UI и БД
        4. Установить флаг режима редактирования
        5. При отправке сообщение заменится, а не добавится
        """
        if self.is_generating:
            print("[EDIT] ✗ Генерация идёт, редактирование невозможно")
            return
        
        # Получаем последнее сообщение пользователя из ТЕКУЩЕГО чата
        messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=50)
        
        last_user_msg = None
        for msg_data in reversed(messages):
            role, content = msg_data[0], msg_data[1]
            if role == "user":
                last_user_msg = content
                break
        
        if not last_user_msg:
            print("[EDIT] ✗ Нет сообщений пользователя для редактирования")
            return
        
        print(f"[EDIT] Редактируем последний запрос: {last_user_msg[:50]}...")
        
        # Удаляем последние 2 виджета (user + assistant) из layout И из памяти Qt.
        # ВАЖНО: deleteLater() без removeWidget() не убирает виджет из layout немедленно —
        # count() не уменьшается, и следующий new message добавляется ПОСЛЕ "удалённого" виджета.
        # Правильный порядок: removeWidget() → deleteLater().
        removed_count = 0
        # Собираем виджеты которые нужно удалить (до -2 пропускаем stretch)
        to_remove = []
        total = self.messages_layout.count()
        # Итерируем с конца, пропуская последний spacer/stretch
        for i in range(total - 1, -1, -1):
            if removed_count >= 2:
                break
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                to_remove.append(w)
                removed_count += 1

        for w in to_remove:
            self.messages_layout.removeWidget(w)
            w.hide()
            w.deleteLater()

        self.messages_layout.invalidate()
        self.messages_layout.activate()

        print(f"[EDIT] ✓ Удалено виджетов: {removed_count}")
        
        # Удаляем последние 2 сообщения из БД текущего чата
        conn = sqlite3.connect("chats.db")
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM chat_messages 
            WHERE chat_id = ? AND id IN (
                SELECT id FROM chat_messages 
                WHERE chat_id = ? 
                ORDER BY id DESC LIMIT 2
            )
        """, (self.current_chat_id, self.current_chat_id))
        conn.commit()
        conn.close()
        print("[EDIT] ✓ Удалены последние 2 сообщения из БД")
        
        # УСТАНАВЛИВАЕМ РЕЖИМ РЕДАКТИРОВАНИЯ
        self.is_editing = True
        self.editing_message_text = last_user_msg
        
        # ВОССТАНАВЛИВАЕМ РЕЖИМЫ которые были при отправке сообщения
        if hasattr(self, 'last_message_deep_thinking') and hasattr(self, 'last_message_use_search'):
            self.deep_thinking = self.last_message_deep_thinking
            self.use_search = self.last_message_use_search
            # Обновляем виджеты-тогглы если они существуют в текущем UI
            if hasattr(self, 'think_toggle') and self.think_toggle is not None:
                self.think_toggle.setChecked(self.deep_thinking)
            if hasattr(self, 'search_toggle') and self.search_toggle is not None:
                self.search_toggle.setChecked(self.use_search)
            print(f"[EDIT] Восстановлены режимы: думать={self.deep_thinking}, поиск={self.use_search}")
        else:
            print(f"[EDIT] Текущие режимы: думать={self.deep_thinking}, поиск={self.use_search}")
        
        # ВОЗВРАЩАЕМ ТЕКСТ В ПОЛЕ ВВОДА И УСТАНАВЛИВАЕМ КУРСОР В КОНЕЦ
        self.input_field.setText(last_user_msg)
        self.input_field.setEnabled(True)
        self.input_field.setFocus()
        self.input_field.setCursorPosition(len(last_user_msg))
        print(f"[EDIT] ✓ Режим редактирования активирован")

    def clear_chat(self):
        """Очистка чата с кастомным окном подтверждения"""
        print("[CLEAR_CHAT] Метод вызван!")
        
        # Блокируем очистку если идёт генерация
        if self.is_generating:
            print("[CLEAR_CHAT] Генерация в процессе - очистка заблокирована")
            return
        
        # Проверяем, есть ли сообщения в чате (кроме системных)
        messages_count = 0
        for i in range(self.messages_layout.count() - 1):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'speaker') and widget.speaker != "Система":
                    messages_count += 1
        
        print(f"[CLEAR_CHAT] Найдено сообщений: {messages_count}")
        
        if messages_count == 0:
            print("[CLEAR_CHAT] Нет сообщений - выход")
            return
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Создаём МОДАЛЬНОЕ окно (работает на Mac)
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("")
        dialog.setModal(True)
        dialog.setFixedSize(420, 220)
        
        # Убираем рамку окна
        dialog.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Dialog)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        
        # Центрируем по ЭКРАНУ (не по родителю)
        screen_geo = QtWidgets.QApplication.primaryScreen().geometry()
        dialog.move(
            screen_geo.center().x() - 210,
            screen_geo.center().y() - 110
        )
        
        # Layout
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Стеклянный контейнер с адаптацией под тему
        frame = QtWidgets.QFrame()
        
        # КРИТИЧНО: Устанавливаем что фон НЕ должен рисоваться поверх дочерних элементов
        frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        
        if is_dark:
            # Тёмная тема - стеклянный фон БЕЗ дополнительных слоёв
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(30, 30, 35, 0.92);
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 20px;
                }
            """)
        else:
            # Светлая тема - стеклянный фон БЕЗ дополнительных слоёв
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(255, 255, 255, 0.90);
                    border: 1px solid rgba(255, 255, 255, 0.95);
                    border-radius: 20px;
                }
            """)
        
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(35, 35, 35, 35)
        frame_layout.setSpacing(28)
        
        # Текст - КРИТИЧНО: убираем любые стили которые могут создать слой
        label = QtWidgets.QLabel("Вы уверены, что хотите\nочистить чат?")
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setFont(_apple_font(16, weight=QtGui.QFont.Weight.Medium))
        
        # ИСПРАВЛЕНИЕ: Минимальный стиль только для цвета текста
        # НЕ используем padding, background и другие свойства которые создают слои
        if is_dark:
            label.setStyleSheet("QLabel { color: #e6e6e6; background-color: none; border: none; }")
        else:
            label.setStyleSheet("QLabel { color: #2d3748; background-color: none; border: none; }")
        
        label.setWordWrap(True)
        
        # КРИТИЧНО: Поднимаем label поверх всех слоёв
        label.raise_()
        
        frame_layout.addWidget(label)
        
        # Кнопки
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(15)
        
        no_btn = QtWidgets.QPushButton("НЕТ")
        no_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Bold))
        no_btn.setFixedHeight(54)
        no_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        if is_dark:
            no_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(60, 60, 70, 0.7);
                    color: #c0c0c0;
                    border: 1px solid rgba(80, 80, 90, 0.8);
                    border-radius: 13px;
                    padding: 8px 18px;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(70, 70, 80, 0.85);
                    border: 1px solid rgba(90, 90, 100, 0.9);
                }
            """)
        else:
            no_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(200, 200, 200, 0.6);
                    color: #4a5568;
                    border: 1px solid rgba(200, 200, 200, 0.75);
                    border-radius: 13px;
                    padding: 8px 18px;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(200, 200, 200, 0.8);
                }
            """)
        
        yes_btn = QtWidgets.QPushButton("ДА")
        yes_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Bold))
        yes_btn.setFixedHeight(54)
        yes_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        if is_dark:
            yes_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(220, 38, 38, 0.95);
                    color: #ffffff;
                    border: 1px solid rgba(220, 38, 38, 1.0);
                    border-radius: 13px;
                    padding: 8px 18px;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(185, 28, 28, 1.0);
                    border: 1px solid rgba(185, 28, 28, 1.0);
                }
            """)
        else:
            yes_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(239, 68, 68, 0.95);
                    color: white;
                    border: none;
                    border-radius: 13px;
                    padding: 8px 18px;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(220, 38, 38, 1.0);
                }
            """)
        
        buttons.addWidget(no_btn)
        buttons.addWidget(yes_btn)
        
        # КРИТИЧНО: Поднимаем кнопки поверх всех слоёв
        no_btn.raise_()
        yes_btn.raise_()
        
        frame_layout.addLayout(buttons)
        
        layout.addWidget(frame)
        
        # Обработчики с плавным закрытием
        def _close_dialog_animated(accept: bool):
            """Плавное закрытие: fade-out, затем закрытие"""
            # Отключаем кнопки чтобы не нажали дважды
            no_btn.setEnabled(False)
            yes_btn.setEnabled(False)

            _d_eff = QtWidgets.QGraphicsOpacityEffect(dialog)
            dialog.setGraphicsEffect(_d_eff)
            _d_eff.setOpacity(1.0)

            _d_op = QtCore.QPropertyAnimation(_d_eff, b"opacity")
            _d_op.setDuration(160)
            _d_op.setStartValue(1.0)
            _d_op.setEndValue(0.0)
            _d_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            def _finish():
                if accept:
                    dialog.accept()
                else:
                    dialog.reject()

            _d_op.finished.connect(_finish)
            _d_op.start()
            dialog._close_anims = [_d_op, _d_eff]

        no_btn.clicked.connect(lambda: _close_dialog_animated(False))
        yes_btn.clicked.connect(lambda: _close_dialog_animated(True))

        print("[CLEAR_CHAT] Показываю диалог...")

        # Плавное открытие: только fade-in (без geometry — избегаем сдвигов)
        _open_eff = QtWidgets.QGraphicsOpacityEffect(dialog)
        dialog.setGraphicsEffect(_open_eff)
        _open_eff.setOpacity(0.0)

        _open_op = QtCore.QPropertyAnimation(_open_eff, b"opacity")
        _open_op.setDuration(220)
        _open_op.setStartValue(0.0)
        _open_op.setEndValue(1.0)
        _open_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        def _on_open_done():
            try:
                dialog.setGraphicsEffect(None)
            except Exception:
                pass

        _open_op.finished.connect(_on_open_done)
        _open_op.start()
        dialog._open_anims = [_open_op, _open_eff]

        result = dialog.exec()
        
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            print("[CLEAR_CHAT] Пользователь подтвердил очистку")
            self.perform_clear_chat()
        else:
            print("[CLEAR_CHAT] Пользователь отменил очистку")
    
    def perform_clear_chat(self):
        """Очистка чата — каскадный slide-fade снизу вверх."""
        print("[PERFORM_CLEAR] Начинаем плавную очистку...")

        widgets = []
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if hasattr(w, 'speaker'):
                    widgets.append(w)

        print(f"[PERFORM_CLEAR] Виджетов для удаления: {len(widgets)}")

        if not widgets:
            self.finalize_clear()
            return

        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)

        # Каскад снизу вверх: интервал 55ms, анимация 650ms (пиксели)
        STAGGER = 55
        ANIM_DUR = 650
        for idx, widget in enumerate(reversed(widgets)):
            delay = idx * STAGGER
            QtCore.QTimer.singleShot(delay, lambda w=widget: self.pixel_dissolve_and_remove(w))

        total = (len(widgets) - 1) * STAGGER + ANIM_DUR + 200
        QtCore.QTimer.singleShot(total, self.finalize_clear)

    def pixel_dissolve_and_remove(self, widget):
        """
        Эффект рассыпания в пыль.

        Механика:
          1. grab() снимок виджета
          2. Виджет НЕ скрывается и НЕ удаляется — занимает место в layout
             Поверх него (в (0,0) виджета) показывается _PixelProxy
          3. Сам виджет скрывается через QGraphicsOpacityEffect → opacity=0
             (layout сохраняет его размер, места нет чёрных прямоугольников)
          4. _PixelProxy рисует снимок с эффектом рассыпания
          5. По завершении: прокси закрывается, виджет удаляется из layout
        """
        try:
            if not widget or not widget.isVisible():
                return

            # Снимок виджета до скрытия
            try:
                px = widget.grab()
            except Exception:
                px = None

            if not px or px.isNull():
                # Fallback: простой fade
                eff = QtWidgets.QGraphicsOpacityEffect(widget)
                widget.setGraphicsEffect(eff)
                a = QtCore.QPropertyAnimation(eff, b"opacity")
                a.setDuration(400)
                a.setStartValue(1.0); a.setEndValue(0.0)
                def _fb():
                    try:
                        widget.setGraphicsEffect(None)
                        self.messages_layout.removeWidget(widget)
                        widget.deleteLater()
                    except Exception:
                        pass
                a.finished.connect(_fb)
                a.start()
                widget._clear_fb = [eff, a]
                return

            # DPR: на Retina grab() даёт пиксмап в 2× физических пикселях
            # Работаем в логических пикселях (размер виджета),
            # а рисуем с масштабом 1/dpr чтобы снимок не был в 2 раза больше
            _dpr  = px.devicePixelRatio() if px.devicePixelRatio() > 0 else 1.0
            _ww   = widget.width()    # логический размер виджета
            _wh   = widget.height()

            # Блоки в логических пикселях
            import random as _rand
            _rng  = _rand.Random(99)
            BLOCK = 8
            _cols = (_ww + BLOCK - 1) // BLOCK
            _rows = (_wh + BLOCK - 1) // BLOCK
            _bd   = [
                (_rng.random(),
                 _rng.uniform(-16, 16),
                 _rng.uniform(6, 24))
                for _ in range(_cols * _rows)
            ]

            class _PixelProxy(QtWidgets.QWidget):
                """
                Рисует снимок виджета с эффектом рассыпания.
                Координаты блоков — логические пиксели.
                Снимок масштабируется через drawPixmap target-rect.
                """
                def __init__(self, pixmap, block_data, cols, rows, bsize,
                             ww, wh, dpr, parent_w):
                    super().__init__(parent_w)
                    self._px   = pixmap
                    self._bd   = block_data
                    self._cols = cols
                    self._rows = rows
                    self._bs   = bsize
                    self._ww   = ww     # логическая ширина
                    self._wh   = wh     # логическая высота
                    self._dpr  = dpr
                    self._progress = 0.0
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

                def setProgress(self, v):
                    self._progress = v
                    self.update()

                def getProgress(self):
                    return self._progress

                progress = QtCore.pyqtProperty(float, getProgress, setProgress)

                def paintEvent(self, event):
                    if not self._px:
                        return
                    p = QtGui.QPainter(self)
                    p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                    prog = self._progress
                    bs   = self._bs
                    dpr  = self._dpr
                    # физические пиксели снимка
                    phys_w = self._px.width()
                    phys_h = self._px.height()

                    if prog < 0.005:
                        # Рисуем снимок в логических размерах виджета
                        p.drawPixmap(
                            QtCore.QRect(0, 0, self._ww, self._wh),
                            self._px,
                            QtCore.QRect(0, 0, phys_w, phys_h)
                        )
                        p.end()
                        return

                    idx = 0
                    for row in range(self._rows):
                        for col in range(self._cols):
                            thresh, dx_max, dy_max = self._bd[idx]
                            idx += 1

                            # Логические координаты блока
                            bx = col * bs
                            by = row * bs
                            bw = min(bs, self._ww - bx)
                            bh = min(bs, self._wh - by)
                            if bw <= 0 or bh <= 0:
                                continue

                            # Физические координаты в снимке
                            sbx = int(bx * dpr)
                            sby = int(by * dpr)
                            sbw = int(bw * dpr)
                            sbh = int(bh * dpr)

                            t0    = thresh * 0.65
                            local = (prog - t0) / 0.35
                            local = max(0.0, min(1.0, local))

                            if local <= 0.0:
                                p.setOpacity(1.0)
                                p.drawPixmap(
                                    QtCore.QRect(bx, by, bw, bh),
                                    self._px,
                                    QtCore.QRect(sbx, sby, sbw, sbh)
                                )
                            elif local < 1.0:
                                ease  = local * local
                                ox    = int(dx_max * ease)
                                oy    = int(dy_max * ease)
                                alpha = max(0.0, 1.0 - ease * 1.4)
                                p.setOpacity(alpha)
                                p.drawPixmap(
                                    QtCore.QRect(bx + ox, by + oy, bw, bh),
                                    self._px,
                                    QtCore.QRect(sbx, sby, sbw, sbh)
                                )
                    p.end()

            _parent = widget.parent()
            proxy = _PixelProxy(px, _bd, _cols, _rows, BLOCK,
                                _ww, _wh, _dpr, _parent)
            proxy.setGeometry(widget.geometry())
            proxy.show()
            proxy.raise_()

            # Скрываем виджет сразу — прокси показывает его снимок
            # Используем setVisible(False) вместо opacity=0 чтобы не трогать дочерних
            # Но чтобы layout не схлопнулся — минимальная высота = текущая
            _saved_min_h = widget.minimumHeight()
            _saved_h     = widget.height()
            widget.setMinimumHeight(_saved_h)
            widget.setMaximumHeight(_saved_h)
            widget.setVisible(False)

            # Анимируем рассыпание
            anim = QtCore.QPropertyAnimation(proxy, b"progress")
            anim.setDuration(700)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QtCore.QEasingCurve.Type.Linear)

            def _cleanup():
                try:
                    proxy.close()
                except Exception:
                    pass
                try:
                    widget.setMinimumHeight(_saved_min_h)
                    widget.setMaximumHeight(16777215)
                    self.messages_layout.removeWidget(widget)
                    widget.deleteLater()
                except Exception:
                    pass

            anim.finished.connect(_cleanup)
            anim.start()
            widget._dissolve_refs = [proxy, anim, _parent]  # защита от GC

        except Exception as e:
            print(f"[PIXEL_DISSOLVE] Ошибка: {e}")
            try:
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
            except Exception:
                pass
    
    
    def finalize_clear(self):
        """Завершение очистки чата после анимации"""
        try:
            print("[FINALIZE] Очищаем БД и восстанавливаем UI...")
            
            # ✅ Удаляем все оставшиеся виджеты сообщений (на случай если анимация не завершилась)
            # Оставляем только stretch в конце
            items_to_remove = []
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    # Удаляем только виджеты с атрибутом speaker (сообщения)
                    if hasattr(widget, 'speaker'):
                        items_to_remove.append(widget)
            
            for widget in items_to_remove:
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
            
            print(f"[FINALIZE] Удалено оставшихся виджетов: {len(items_to_remove)}")
            
            # Очищаем БД сообщений И контекстную память чата
            self.chat_manager.clear_chat_messages(self.current_chat_id)
            clear_chat_all_memories(self.current_chat_id)
            self.chat_manager.update_chat_title(self.current_chat_id, "Новый чат")
            self.load_chats_list()
            
            # Добавляем системное сообщение (автоскролл произойдет автоматически)
            self.add_message_widget("Система", "Чат очищен", add_controls=False)
            
            # Восстанавливаем UI
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.input_field.setFocus()
            
            print("[FINALIZE] Готово!")
        except Exception as e:
            print(f"[FINALIZE] Ошибка: {e}")
            import traceback
            traceback.print_exc()
            # В случае ошибки - всё равно восстанавливаем UI
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
    
    def confirm_delete_all_models(self):
        """Показать диалог подтверждения и удалить ВСЕ модели ИИ с диска"""
        print("[DELETE_ALL_MODELS] Запрос подтверждения")

        is_dark = self.current_theme == "dark"

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("")
        dialog.setModal(True)
        dialog.setFixedSize(450, 230)
        dialog.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.Dialog |
            QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)

        screen_geo = QtWidgets.QApplication.primaryScreen().geometry()
        dialog.move(screen_geo.center().x() - 225, screen_geo.center().y() - 115)

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        frame = QtWidgets.QFrame()
        frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        if is_dark:
            frame.setStyleSheet("QFrame { background-color: rgba(30,30,35,0.97); border: 1px solid rgba(60,60,70,0.8); border-radius: 20px; }")
        else:
            frame.setStyleSheet("QFrame { background-color: rgba(255,255,255,0.97); border: 1px solid rgba(200,200,210,0.9); border-radius: 20px; }")

        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(30, 24, 30, 24)
        frame_layout.setSpacing(0)

        title = QtWidgets.QLabel("🤖 Удалить все модели ИИ?")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setFont(_apple_font(18, weight=QtGui.QFont.Weight.Bold))
        title.setStyleSheet(f"QLabel {{ color: {'#e89999' if is_dark else '#c85555'}; background-color: none; border: none; }}")
        frame_layout.addWidget(title)
        frame_layout.addSpacing(14)

        warning = QtWidgets.QLabel(
            "Все скачанные модели ИИ будут удалены с диска.\n"
            "Это действие невозможно отменить.\n"
            "Для работы потребуется повторная загрузка."
        )
        warning.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        warning.setFont(_apple_font(13, weight=QtGui.QFont.Weight.Normal))
        warning.setWordWrap(True)
        warning.setStyleSheet(f"QLabel {{ color: {'#b0b0b0' if is_dark else '#64748b'}; background-color: none; border: none; }}")
        frame_layout.addWidget(warning)
        frame_layout.addSpacing(18)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(15)

        no_btn = QtWidgets.QPushButton("Отмена")
        no_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Medium))
        no_btn.setMinimumHeight(48)
        no_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        if is_dark:
            no_btn.setStyleSheet("QPushButton { background: rgba(60,60,70,0.70); color: #e6e6e6; border: none; border-radius: 13px; padding: 8px 18px; } QPushButton:hover { background: rgba(70,70,80,0.85); }")
        else:
            no_btn.setStyleSheet("QPushButton { background: rgba(226,232,240,0.90); color: #334155; border: none; border-radius: 13px; padding: 8px 18px; } QPushButton:hover { background: rgba(203,213,225,1.0); }")

        yes_btn = QtWidgets.QPushButton("Удалить все модели")
        yes_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Bold))
        yes_btn.setMinimumHeight(48)
        yes_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        yes_btn.setStyleSheet("QPushButton { background: rgba(239,68,68,0.95); color: white; border: none; border-radius: 13px; padding: 8px 18px; } QPushButton:hover { background: rgba(220,38,38,1.0); }")

        buttons.addWidget(no_btn)
        buttons.addWidget(yes_btn)
        frame_layout.addLayout(buttons)
        layout.addWidget(frame)

        def _close_animated(accept: bool):
            no_btn.setEnabled(False)
            yes_btn.setEnabled(False)
            _eff = QtWidgets.QGraphicsOpacityEffect(dialog)
            dialog.setGraphicsEffect(_eff)
            _eff.setOpacity(1.0)
            _anim = QtCore.QPropertyAnimation(_eff, b"opacity")
            _anim.setDuration(160)
            _anim.setStartValue(1.0)
            _anim.setEndValue(0.0)
            _anim.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
            _anim.finished.connect(lambda: dialog.accept() if accept else dialog.reject())
            _anim.start()
            dialog._anims = [_anim, _eff]

        no_btn.clicked.connect(lambda: _close_animated(False))
        yes_btn.clicked.connect(lambda: _close_animated(True))

        # Fade-in открытие
        _open_eff = QtWidgets.QGraphicsOpacityEffect(dialog)
        dialog.setGraphicsEffect(_open_eff)
        _open_eff.setOpacity(0.0)
        _open_anim = QtCore.QPropertyAnimation(_open_eff, b"opacity")
        _open_anim.setDuration(220)
        _open_anim.setStartValue(0.0)
        _open_anim.setEndValue(1.0)
        _open_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        _open_anim.finished.connect(lambda: dialog.setGraphicsEffect(None) if dialog else None)
        _open_anim.start()
        dialog._open_anims = [_open_anim, _open_eff]

        dialog.raise_()
        dialog.activateWindow()
        result = dialog.exec()

        if result == QtWidgets.QDialog.DialogCode.Accepted:
            print("[DELETE_ALL_MODELS] Пользователь подтвердил — начинаем удаление")
            self._perform_delete_all_models()
        else:
            print("[DELETE_ALL_MODELS] Пользователь отменил")

    def _perform_delete_all_models(self):
        """Удаляет все модели из Ollama и с диска"""
        models_dir = get_ollama_models_dir()
        total_freed = 0
        errors = []

        prog = QtWidgets.QProgressDialog("Удаление моделей…", None, 0, 0, self)
        prog.setWindowTitle("Удаление всех моделей")
        prog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        if IS_WINDOWS:
            prog.setWindowFlags(QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.WindowTitleHint)
        prog.show()
        QtWidgets.QApplication.processEvents()

        for model_key, (ollama_name, display_name) in list(SUPPORTED_MODELS.items()):
            print(f"[DELETE_ALL_MODELS] Удаляем: {display_name} ({ollama_name})")
            prog.setLabelText(f"Удаление {display_name}…")
            QtWidgets.QApplication.processEvents()

            # ollama rm
            try:
                kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                if IS_WINDOWS:
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                subprocess.run(["ollama", "rm", ollama_name], timeout=60, **kwargs)
            except Exception as e:
                print(f"[DELETE_ALL_MODELS] ollama rm {ollama_name}: {e}")

            # физическое удаление файлов
            try:
                freed, deleted = delete_model_files_from_disk(ollama_name, models_dir)
                total_freed += freed
                print(f"[DELETE_ALL_MODELS] {display_name}: удалено {len(deleted)} файлов, {freed/1024**3:.2f} GB")
            except Exception as e:
                errors.append(f"{display_name}: {e}")
                print(f"[DELETE_ALL_MODELS] Ошибка при удалении {display_name}: {e}")

        prog.close()

        freed_str = f"{total_freed / 1024**3:.1f} GB" if total_freed > 0 else "неизвестно"

        if errors:
            QtWidgets.QMessageBox.warning(
                self, "Удаление завершено с ошибками",
                f"Большинство моделей удалено. Освобождено: {freed_str}\n\n"
                + "\n".join(errors),
                QtWidgets.QMessageBox.StandardButton.Ok
            )
        else:
            QtWidgets.QMessageBox.information(
                self, "✅ Модели удалены",
                f"Все модели ИИ успешно удалены с диска.\n\n"
                f"Освобождено места: {freed_str}\n\n"
                f"Для работы с ИИ откройте «Выбор модели» и скачайте нужную модель.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
        print(f"[DELETE_ALL_MODELS] ✓ Завершено. Освобождено: {freed_str}")

    def confirm_delete_all_chats(self):
        """Показать диалог подтверждения удаления ВСЕХ чатов"""
        print("[DELETE_ALL_CHATS] Запрос подтверждения удаления всех чатов")
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Создаём модальное окно
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("")
        dialog.setModal(True)
        dialog.setFixedSize(450, 210)
        
        # Убираем рамку окна и поднимаем поверх всего
        dialog.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.Dialog |
            QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        
        # Центрируем по экрану
        screen_geo = QtWidgets.QApplication.primaryScreen().geometry()
        dialog.move(
            screen_geo.center().x() - 225,
            screen_geo.center().y() - 110
        )
        
        # Layout без отступов — frame полностью заполняет диалог (нет прозрачных краёв)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Стеклянный контейнер
        frame = QtWidgets.QFrame()
        frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        
        if is_dark:
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(30, 30, 35, 0.97);
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 20px;
                }
            """)
        else:
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(255, 255, 255, 0.97);
                    border: 1px solid rgba(200, 200, 210, 0.9);
                    border-radius: 20px;
                }
            """)
        
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(30, 24, 30, 24)
        frame_layout.setSpacing(0)
        
        # Заголовок
        title = QtWidgets.QLabel("⚠️ Удалить все чаты?")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setFont(_apple_font(18, weight=QtGui.QFont.Weight.Bold))
        
        if is_dark:
            title.setStyleSheet("QLabel { color: #e89999; background-color: none; border: none; }")
        else:
            title.setStyleSheet("QLabel { color: #c85555; background-color: none; border: none; }")
        
        frame_layout.addWidget(title)
        frame_layout.addSpacing(14)
        
        # Текст предупреждения
        warning = QtWidgets.QLabel("Это действие невозможно отменить.\nВсе чаты будут удалены безвозвратно.")
        warning.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        warning.setFont(_apple_font(13, weight=QtGui.QFont.Weight.Normal))
        warning.setWordWrap(True)
        
        if is_dark:
            warning.setStyleSheet("QLabel { color: #b0b0b0; background-color: none; border: none; }")
        else:
            warning.setStyleSheet("QLabel { color: #64748b; background-color: none; border: none; }")
        
        frame_layout.addWidget(warning)
        frame_layout.addSpacing(14)
        
        # Кнопки
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(15)
        
        no_btn = QtWidgets.QPushButton("Отмена")
        no_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Medium))
        no_btn.setMinimumHeight(48)
        no_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        if is_dark:
            no_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(60, 60, 70, 0.70);
                    color: #e6e6e6;
                    border: none;
                    border-radius: 13px;
                    padding: 8px 18px;
                }
                QPushButton:hover {
                    background: rgba(70, 70, 80, 0.85);
                }
            """)
        else:
            no_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(226, 232, 240, 0.90);
                    color: #334155;
                    border: none;
                    border-radius: 13px;
                    padding: 8px 18px;
                }
                QPushButton:hover {
                    background: rgba(203, 213, 225, 1.0);
                }
            """)
        
        yes_btn = QtWidgets.QPushButton("Удалить все")
        yes_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Bold))
        yes_btn.setMinimumHeight(48)
        yes_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        yes_btn.setStyleSheet("""
            QPushButton {
                background: rgba(239, 68, 68, 0.95);
                color: white;
                border: none;
                border-radius: 13px;
                padding: 8px 18px;
                text-align: center;
            }
            QPushButton:hover {
                background: rgba(220, 38, 38, 1.0);
            }
        """)
        
        buttons.addWidget(no_btn)
        buttons.addWidget(yes_btn)
        
        no_btn.raise_()
        yes_btn.raise_()
        
        frame_layout.addLayout(buttons)
        layout.addWidget(frame)
        
        # Обработчики с плавным закрытием
        def _close_delete_animated(accept: bool):
            no_btn.setEnabled(False)
            yes_btn.setEnabled(False)

            _d_eff = QtWidgets.QGraphicsOpacityEffect(dialog)
            dialog.setGraphicsEffect(_d_eff)
            _d_eff.setOpacity(1.0)

            _d_op = QtCore.QPropertyAnimation(_d_eff, b"opacity")
            _d_op.setDuration(160)
            _d_op.setStartValue(1.0)
            _d_op.setEndValue(0.0)
            _d_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            def _finish():
                if accept:
                    dialog.accept()
                else:
                    dialog.reject()

            _d_op.finished.connect(_finish)
            _d_op.start()
            dialog._close_anims = [_d_op, _d_eff]

        no_btn.clicked.connect(lambda: _close_delete_animated(False))
        yes_btn.clicked.connect(lambda: _close_delete_animated(True))

        print("[DELETE_ALL_CHATS] Показываю диалог...")
        dialog.raise_()
        dialog.activateWindow()

        # Плавное открытие: только fade-in (без geometry — избегаем сдвигов)
        _open_eff = QtWidgets.QGraphicsOpacityEffect(dialog)
        dialog.setGraphicsEffect(_open_eff)
        _open_eff.setOpacity(0.0)

        _open_op = QtCore.QPropertyAnimation(_open_eff, b"opacity")
        _open_op.setDuration(220)
        _open_op.setStartValue(0.0)
        _open_op.setEndValue(1.0)
        _open_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        def _on_open_done():
            try:
                dialog.setGraphicsEffect(None)
            except Exception:
                pass

        _open_op.finished.connect(_on_open_done)
        _open_op.start()
        dialog._open_anims = [_open_op, _open_eff]

        result = dialog.exec()
        
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            print("[DELETE_ALL_CHATS] Пользователь подтвердил удаление всех чатов")
            self.perform_delete_all_chats()
        else:
            print("[DELETE_ALL_CHATS] Пользователь отменил удаление")
    
    def perform_delete_all_chats(self):
        """Удалить все чаты — очищает чат, обновляет сайдбар, показывает popup."""
        print("[DELETE_ALL_CHATS] ▶ Начинаю полное удаление...")

        def _run_delete():
            try:
                import sqlite3 as _sq, chat_manager as _cm
                from datetime import datetime as _dt

                # Считаем количество чатов ДО удаления
                _conn = _sq.connect(_cm.CHATS_DB)
                _chat_count = _conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
                _conn.close()

                clear_all_memories_global()

                # Очищаем БД и создаём новый чат
                conn = _sq.connect(_cm.CHATS_DB)
                cur  = conn.cursor()
                cur.execute("DELETE FROM chat_messages")
                cur.execute("DELETE FROM chats")
                now = _dt.utcnow().isoformat()
                cur.execute(
                    "INSERT INTO chats (title, created_at, updated_at, is_active) VALUES (?,?,?,?)",
                    ("Новый чат", now, now, 1)
                )
                new_chat_id = cur.lastrowid
                conn.commit()
                conn.close()

                self.current_chat_id = new_chat_id
                self.startup_chat_id = new_chat_id
                on_chat_switched_all_memories(new_chat_id)

                # Удаляем все виджеты сообщений
                to_remove = []
                for i in range(self.messages_layout.count()):
                    item = self.messages_layout.itemAt(i)
                    if item and item.widget() and hasattr(item.widget(), 'speaker'):
                        to_remove.append(item.widget())
                for ww in to_remove:
                    self.messages_layout.removeWidget(ww)
                    ww.deleteLater()

                # Обновляем сайдбар
                self.chats_list.clear()
                for chat in self.chat_manager.get_all_chats():
                    it = QtWidgets.QListWidgetItem(chat['title'])
                    it.setData(QtCore.Qt.ItemDataRole.UserRole, chat['id'])
                    self.chats_list.addItem(it)
                    if chat['is_active']:
                        self.chats_list.setCurrentItem(it)
                self.chats_list.repaint()

                # Приветствие в чате
                self.add_message_widget("Система", "Привет! Готов к работе.", add_controls=False)

                self.input_field.setEnabled(True)
                self.send_btn.setEnabled(True)

                QtCore.QTimer.singleShot(100, lambda: self.scroll_area.verticalScrollBar().setValue(
                    self.scroll_area.verticalScrollBar().maximum()
                ))

                # Показываем popup-окно с результатом
                QtCore.QTimer.singleShot(300, lambda: self._show_deleted_chats_popup(_chat_count))
                print(f"[DELETE_ALL_CHATS] ✓ Удалено чатов: {_chat_count}")

            except Exception as e:
                print(f"[DELETE_ALL_CHATS] ✗ Ошибка: {e}")
                import traceback; traceback.print_exc()
                self.input_field.setEnabled(True)
                self.send_btn.setEnabled(True)

        if self.content_stack.currentIndex() == 1:
            self.close_settings()
            QtCore.QTimer.singleShot(620, _run_delete)
        else:
            _run_delete()

    def _show_deleted_chats_popup(self, chat_count: int):
        """Красивое popup-окно с результатом удаления чатов. Исчезает через 4 сек."""
        is_dark  = self.current_theme == "dark"
        is_glass = getattr(self, "current_liquid_glass", True)

        if is_dark and is_glass:
            bg_frame = "rgba(30, 30, 38, 0.95)"; border = "rgba(60, 60, 90, 0.60)"
            tc = "#e8e8f8"; sc = "rgba(160, 160, 200, 0.80)"
        elif is_dark:
            bg_frame = "rgb(30, 30, 36)"; border = "rgba(60, 60, 70, 0.90)"
            tc = "#e8e8f8"; sc = "#9090aa"
        elif is_glass:
            bg_frame = "rgba(255, 255, 255, 0.92)"; border = "rgba(255, 255, 255, 0.95)"
            tc = "#1a1a3a"; sc = "rgba(80, 90, 140, 0.75)"
        else:
            bg_frame = "rgb(252, 252, 254)"; border = "rgba(210, 210, 218, 0.95)"
            tc = "#1a1a3a"; sc = "#6677aa"

        noun = "чат" if chat_count == 1 else "чата" if 2 <= chat_count <= 4 else "чатов"

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("")
        dialog.setModal(False)
        dialog.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.Dialog |
            QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        dialog.setFixedSize(360, 180)

        screen = QtWidgets.QApplication.primaryScreen().geometry()
        gp = self.mapToGlobal(QtCore.QPoint(0, 0))
        gw = self.geometry()
        dx = gp.x() + (gw.width()  - 360) // 2
        dy = gp.y() + (gw.height() - 180) // 2
        dialog.move(dx, dy)

        root = QtWidgets.QVBoxLayout(dialog)
        root.setContentsMargins(0, 0, 0, 0)

        frame = QtWidgets.QFrame()
        frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        frame.setStyleSheet(f"""
            QFrame {{
                background: {bg_frame};
                border: 1px solid {border};
                border-radius: 22px;
            }}
        """)
        root.addWidget(frame)

        fl = QtWidgets.QVBoxLayout(frame)
        fl.setContentsMargins(32, 28, 32, 28)
        fl.setSpacing(10)

        icon_lbl = QtWidgets.QLabel("✅")
        icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 36px; background: transparent; border: none;")
        fl.addWidget(icon_lbl)

        title_lbl = QtWidgets.QLabel(f"Удалено {chat_count} {noun}")
        title_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_lbl.setFont(_apple_font(18, weight=QtGui.QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {tc}; background: transparent; border: none;")
        fl.addWidget(title_lbl)

        sub_lbl = QtWidgets.QLabel("Все чаты успешно удалены")
        sub_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setFont(_apple_font(13))
        sub_lbl.setStyleSheet(f"color: {sc}; background: transparent; border: none;")
        fl.addWidget(sub_lbl)

        # Появление
        dialog.setWindowOpacity(0.0)
        dialog.show()
        _anim_in = QtCore.QPropertyAnimation(dialog, b"windowOpacity")
        _anim_in.setDuration(220)
        _anim_in.setStartValue(0.0)
        _anim_in.setEndValue(1.0)
        _anim_in.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        _anim_in.start()
        dialog._anim_in = _anim_in

        # Закрытие через 4 сек
        def _close_popup():
            _anim_out = QtCore.QPropertyAnimation(dialog, b"windowOpacity")
            _anim_out.setDuration(260)
            _anim_out.setStartValue(1.0)
            _anim_out.setEndValue(0.0)
            _anim_out.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
            _anim_out.finished.connect(dialog.close)
            dialog._anim_out = _anim_out
            _anim_out.start()

        QtCore.QTimer.singleShot(4000, _close_popup)
        self._deleted_popup = dialog  # защита от GC

    def _show_delete_all_toast(self, chat_count: int):
        """Toast-уведомление после удаления всех чатов."""
        is_dark  = self.current_theme == "dark"
        is_glass = getattr(self, "current_liquid_glass", True)

        if is_dark and is_glass:
            bg    = "rgba(28, 28, 38, 0.92)"
            bord  = "rgba(90, 90, 130, 0.50)"
            tc    = "#e0e0f0"
            subc  = "rgba(150,150,185,0.75)"
        elif is_dark:
            bg    = "rgb(26, 26, 34)"
            bord  = "rgba(65, 65, 90, 0.90)"
            tc    = "#e0e0f0"
            subc  = "#8888aa"
        elif is_glass:
            bg    = "rgba(255,255,255,0.82)"
            bord  = "rgba(255,255,255,0.90)"
            tc    = "#1a1a3a"
            subc  = "rgba(80,90,140,0.70)"
        else:
            bg    = "rgb(248,248,252)"
            bord  = "rgba(200,205,230,0.95)"
            tc    = "#1a1a3a"
            subc  = "#6677aa"

        noun = "чат" if chat_count == 1 else                "чата" if 2 <= chat_count <= 4 else "чатов"

        toast = QtWidgets.QWidget(self,
            QtCore.Qt.WindowType.Tool |
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint)
        toast.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        toast.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)

        tl = QtWidgets.QHBoxLayout(toast)
        tl.setContentsMargins(18, 12, 18, 12)
        tl.setSpacing(10)

        icon_lbl = QtWidgets.QLabel("✅")
        icon_lbl.setStyleSheet("background:transparent;border:none;font-size:20px;")
        tl.addWidget(icon_lbl)

        txt_col = QtWidgets.QVBoxLayout()
        txt_col.setSpacing(2)
        h_lbl = QtWidgets.QLabel("Все чаты удалены")
        h_lbl.setFont(_apple_font(13, weight=QtGui.QFont.Weight.Bold))
        h_lbl.setStyleSheet(f"background:transparent;border:none;color:{tc};")
        s_lbl = QtWidgets.QLabel(f"Удалено {chat_count} {noun}")
        s_lbl.setFont(_apple_font(11))
        s_lbl.setStyleSheet(f"background:transparent;border:none;color:{subc};")
        txt_col.addWidget(h_lbl)
        txt_col.addWidget(s_lbl)
        tl.addLayout(txt_col)

        toast.setStyleSheet(f"""
            QWidget {{
                background: {bg};
                border: 1px solid {bord};
                border-radius: 16px;
            }}
        """)

        toast.adjustSize()
        tw = toast.sizeHint().width() + 36
        th = toast.sizeHint().height() + 24
        toast.setFixedSize(max(tw, 220), max(th, 60))

        # Позиция: снизу по центру экрана (над полем ввода)
        gw = self.geometry()
        gp = self.mapToGlobal(QtCore.QPoint(0, 0))
        tx = gp.x() + (gw.width() - toast.width()) // 2
        ty = gp.y() + gw.height() - toast.height() - 90

        toast.move(tx, ty + 40)
        toast.show()
        toast.raise_()
        _apply_windows_rounded(toast, radius=16)

        # Slide-up + fade-in
        _eff = QtWidgets.QGraphicsOpacityEffect(toast)
        toast.setGraphicsEffect(_eff)
        _eff.setOpacity(0.0)
        _op_in = QtCore.QPropertyAnimation(_eff, b"opacity")
        _op_in.setDuration(260); _op_in.setStartValue(0.0); _op_in.setEndValue(1.0)
        _op_in.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        _pos_in = QtCore.QPropertyAnimation(toast, b"pos")
        _pos_in.setDuration(300)
        _pos_in.setStartValue(QtCore.QPoint(tx, ty + 40))
        _pos_in.setEndValue(QtCore.QPoint(tx, ty))
        _pos_in.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
        _grp_in = QtCore.QParallelAnimationGroup()
        _grp_in.addAnimation(_op_in); _grp_in.addAnimation(_pos_in)
        _grp_in.start()
        toast._grp_in = _grp_in

        def _fade_out():
            try:
                toast.setGraphicsEffect(None)
            except Exception:
                pass
            _eff2 = QtWidgets.QGraphicsOpacityEffect(toast)
            toast.setGraphicsEffect(_eff2)
            _eff2.setOpacity(1.0)
            _op_out = QtCore.QPropertyAnimation(_eff2, b"opacity")
            _op_out.setDuration(260); _op_out.setStartValue(1.0); _op_out.setEndValue(0.0)
            _op_out.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
            _pos_out = QtCore.QPropertyAnimation(toast, b"pos")
            _pos_out.setDuration(260)
            _pos_out.setStartValue(QtCore.QPoint(tx, ty))
            _pos_out.setEndValue(QtCore.QPoint(tx, ty - 20))
            _pos_out.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
            _grp_out = QtCore.QParallelAnimationGroup()
            _grp_out.addAnimation(_op_out); _grp_out.addAnimation(_pos_out)
            _grp_out.finished.connect(toast.close)
            _grp_out.start()
            toast._grp_out = _grp_out

        QtCore.QTimer.singleShot(3000, _fade_out)


    # ═══════════════════════════════════════════════════════════════
    # DRAG-AND-DROP: Обработка перетаскивания файлов
    # ═══════════════════════════════════════════════════════════════
    

def main():
    """Главная функция запуска с полной диагностикой и самовосстановлением."""

    # ── Шаг 1: базовая инициализация Qt (нужна раньше всего для диалогов) ──
    try:
        app = QtWidgets.QApplication(sys.argv)
    except Exception as e:
        print(f"[MAIN] ❌ Не удалось создать QApplication: {e}")
        sys.exit(1)

    # ── SIGINT: полностью игнорируем Ctrl+C / внешние сигналы ────────────
    # KeyboardInterrupt в Qt-коллбеках (paintEvent, eventFilter и т.д.)
    # нельзя поймать через try/except — Python бросает его при ВХОДЕ в функцию,
    # до первого байткода. Единственный надёжный способ — SIG_IGN на уровне ОС.
    # GUI-приложение всё равно закрывается через красную кнопку окна.
    import signal as _signal
    _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
    print("[MAIN] ✓ SIGINT отключён (GUI-приложение, используйте кнопку закрытия)")

    if IS_WINDOWS:
        app.setStyle("Fusion")
        # ── Apple-style рендеринг шрифтов на Windows ──────────────────────
        # QtGui уже импортирован глобально — НЕ импортируем повторно (UnboundLocalError)
        _win_font = next(
            (n for n in ["Segoe UI Variable", "Segoe UI"] if n in QtGui.QFontDatabase.families()),
            "Segoe UI"
        )
        _gf = QtGui.QFont(_win_font, 11)
        _gf.setHintingPreference(QtGui.QFont.HintingPreference.PreferNoHinting)
        try:
            _gf.setStyleStrategy(
                QtGui.QFont.StyleStrategy.PreferAntialias |
                QtGui.QFont.StyleStrategy.PreferQuality
            )
        except Exception:
            _gf.setStyleStrategy(QtGui.QFont.StyleStrategy.PreferAntialias)
        app.setFont(_gf)
        import os; os.environ.setdefault("QT_FONT_DPI", "96")
        print(f"[FONT] ✓ Apple-style: {_win_font}, субпиксельный рендеринг")

    # ── Шаг 1.5: запуск Ollama ────────────────────────────────────────────────
    # Ищем бинарник во ВСЕХ стандартных местах ОС и сразу запускаем в фоне.
    # Не блокируем главный поток — просто стартуем и идём дальше.
    # Если Ollama не найдена — диалог откроется после запуска главного окна.
    print("[MAIN] Проверка Ollama…")
    try:
        import threading as _thr0
        from ollama_manager import is_ollama_running, find_ollama_binary, launch_ollama

        if is_ollama_running():
            print("[MAIN] ✅ Ollama уже запущена")
        else:
            _binary = find_ollama_binary()
            if _binary:
                print(f"[MAIN] Найдена Ollama: {_binary} — запускаем в фоне")
                # launch_ollama запускает процесс (не блокирует), ждать не нужно
                _thr0.Thread(target=launch_ollama, args=(_binary,), daemon=True).start()
            else:
                print("[MAIN] Ollama не найдена в стандартных местах — диалог после окна")
    except Exception as _oe:
        print(f"[MAIN] ⚠️ ollama_manager: {_oe}")
    print("[MAIN] Запуск диагностики...")
    report = startup_checks(
        check_ollama   = False,  # Ollama управляется через ollama_manager
        check_dbs      = ["chats.db", "chat_memory.db", "deepseek_memory.db"],
        check_packages = True,
        check_space    = True,
        check_files    = True,
        check_settings = True,
        auto_fix       = True,
        qt_app         = app,
    )

    # ── Шаг 3: фатальные ошибки — показываем и выходим ────────────────────
    if report["fatal"]:
        error_msg = build_fatal_error_message(report)
        QtWidgets.QMessageBox.critical(
            None,
            "❌ Ошибка запуска",
            error_msg,
            QtWidgets.QMessageBox.StandardButton.Ok,
        )
        sys.exit(1)

    # ── Шаг 4: предупреждения — показываем и продолжаем ───────────────────
    if report["warnings"]:
        ollama_warns = [w for w in report["warnings"] if "ollama" in w.lower()]
        other_warns  = [w for w in report["warnings"] if "ollama" not in w.lower()]
        if other_warns:
            detail = "\n".join(other_warns)
            QtWidgets.QMessageBox.warning(
                None,
                "⚠️ Предупреждения при запуске",
                f"Приложение запущено с предупреждениями:\n\n{detail}\n\n"
                "Программа продолжит работу, но некоторые функции могут быть ограничены.",
                QtWidgets.QMessageBox.StandardButton.Ok,
            )

    # ── Шаг 5: инициализация БД приложения ────────────────────────────────
    try:
        print("[MAIN] Инициализация базы данных...")
        init_db()

        print("[MAIN] Запуск миграции ChatManager...")
        from chat_manager import ChatManager
        chat_mgr = ChatManager()
        print("[MAIN] ✓ База данных готова")
    except Exception as e:
        log_error("MAIN_DB_INIT", e)
        QtWidgets.QMessageBox.critical(
            None,
            "❌ Ошибка БД",
            f"Не удалось инициализировать базу данных:\n{e}\n\n"
            "Попробуйте удалить файлы .db и перезапустить программу.",
            QtWidgets.QMessageBox.StandardButton.Ok,
        )
        sys.exit(1)

    # ── Шаг 6: создаём главное окно ───────────────────────────────────────
    try:
        print("[MAIN] Создание иконки приложения...")
        app_icon = create_app_icon()

        # На macOS — устанавливаем через NSApp (PyObjC) для нативного Dock.
        # Это даёт правильный размер и корректные углы без масштабирования Qt.
        # Fallback: setWindowIcon для Windows/Linux или если PyObjC недоступен.
        if not _apply_macos_dock_icon(app_icon):
            app.setWindowIcon(QtGui.QIcon(app_icon))

        print("[MAIN] Создание главного окна...")
        window = MainWindow()
        window.show()

        # ── Цепочка запуска Ollama ────────────────────────────────────────────
        # Правильный Qt-паттерн: сигналы из фонового потока → слоты в главном.
        # QTimer.singleShot из фонового потока ненадёжен — функция может быть
        # собрана GC до срабатывания. Сигналы Qt гарантируют доставку.

        class _OllamaBridge(QtCore.QObject):
            """Мост: фоновый поток → главный поток через Qt-сигналы."""
            ollama_ready   = QtCore.pyqtSignal()   # Ollama запущена → проверить модели
            need_install   = QtCore.pyqtSignal()   # Ollama не найдена → диалог установки

        _bridge = _OllamaBridge()

        def _after_ollama_ready():
            """Ollama запущена (или не найдена — неважно). Проверяем модели."""
            print("[MAIN] → _check_first_launch()")
            window._check_first_launch()

        def _show_ollama_install_dialog():
            """Показывает диалог установки Ollama. Вызывается в главном потоке."""
            print("[MAIN] Открываем OllamaDownloadDialog...")
            try:
                from model_downloader import OllamaDownloadDialog
                dlg = OllamaDownloadDialog(window)
                accepted = dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted
                if accepted:
                    print("[MAIN] Пользователь принял установку — ищем бинарник...")
                    # После установки запускаем в фоне, потом проверяем модели
                    def _after_install():
                        try:
                            from ollama_manager import find_ollama_binary, launch_ollama, wait_for_ollama
                            binary = find_ollama_binary()
                            if binary:
                                launch_ollama(binary)
                                print("[MAIN] ✅ Ollama установлена и запущена")
                            else:
                                print("[MAIN] ⚠️ После установки бинарник не найден")
                        except Exception as _e:
                            print(f"[MAIN] ⚠️ _after_install: {_e}")
                        finally:
                            _bridge.ollama_ready.emit()
                    import threading as _thr2
                    _thr2.Thread(target=_after_install, daemon=True).start()
                else:
                    print("[MAIN] Пользователь отказался от установки Ollama")
                    # Не предлагаем модели — Ollama не установлена, смысла нет
            except Exception as _e:
                print(f"[MAIN] ⚠️ OllamaDownloadDialog: {_e}")

        # Подключаем сигналы к слотам (всё в главном потоке)
        _bridge.ollama_ready.connect(_after_ollama_ready)
        _bridge.need_install.connect(_show_ollama_install_dialog)

        def _ollama_startup_check():
            """
            Фоновый поток: проверяет/ищет/запускает Ollama.
            Общается с главным потоком ТОЛЬКО через сигналы _bridge.
            """
            try:
                from ollama_manager import is_ollama_running, find_ollama_binary, launch_ollama
                print("[MAIN] Проверяем Ollama...")

                if is_ollama_running():
                    print("[MAIN] ✅ Ollama уже запущена")
                    _bridge.ollama_ready.emit()
                    return

                binary = find_ollama_binary()
                if binary:
                    print(f"[MAIN] Бинарник найден: {binary} — запускаем")
                    launch_ollama(binary)
                    print("[MAIN] ✅ Ollama запущена в фоне")
                    _bridge.ollama_ready.emit()
                else:
                    print("[MAIN] ❌ Ollama не найдена — сигнал диалога установки")
                    _bridge.need_install.emit()

            except Exception as _e:
                print(f"[MAIN] ⚠️ _ollama_startup_check: {_e}")
                # При ошибке всё равно проверяем модели
                _bridge.ollama_ready.emit()

        import threading as _thr_ol
        _thr_ol.Thread(target=_ollama_startup_check, daemon=True).start()

        print("[MAIN] ✅ Запуск главного цикла...")
        sys.exit(app.exec())

    except Exception as e:
        log_error("MAIN_WINDOW", e)
        QtWidgets.QMessageBox.critical(
            None,
            "❌ Ошибка запуска",
            f"Не удалось создать главное окно:\n\n{e}\n\n"
            "Проверьте файл errors.log для подробностей.",
            QtWidgets.QMessageBox.StandardButton.Ok,
        )
        sys.exit(1)

if __name__ == "__main__":
    main()