"""
web_search.py — Модуль веб-поиска и анализа источников.

Содержит:
  - INTERNET_REQUIRED_KEYWORDS / NO_INTERNET_KEYWORDS
  - analyze_intent_for_search, analyze_query_type
  - google_search, deep_web_search, fallback_web_search, fetch_page_content
  - rank_and_select_sources, source_quality_score
  - version_search_pipeline (vp_*)
  - summarize_sources, compress_search_results
  - validate_answer, build_final_answer_prompt
  - build_contextual_search_query
  - _conversational_response, is_short_acknowledgment

Использование в run.py / ai_core.py:
    from web_search import (analyze_intent_for_search, google_search,
                            deep_web_search, summarize_sources, ...)
"""
import os
import sys
import re

# ── Добавляем папку ai_config в sys.path ─────────────────────────────────────
_WS_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_WS_AI_CONFIG = os.path.join(_WS_APP_DIR, "ai_config")
if os.path.isdir(_WS_AI_CONFIG) and _WS_AI_CONFIG not in sys.path:
    sys.path.insert(1, _WS_AI_CONFIG)
import json
import time
import random as _random
import datetime as _dt_vp
import re as _re
import re as _re_vp
import requests
from datetime import datetime
from typing import Any

# Константы — импортируются из llama_handler при использовании в run.py.
# При импорте web_search напрямую эти значения нужно передать извне или
# они читаются лениво через llama_handler.
try:
    import llama_handler
    from llama_handler import (
        OLLAMA_HOST, get_current_ollama_model, SUPPORTED_MODELS,
    )
except ImportError:
    OLLAMA_HOST = "http://localhost:11434"
    SUPPORTED_MODELS = {}
    def get_current_ollama_model(): return "llama3"

try:
    from qwen_config import QWEN_MODEL_NAME
except ImportError:
    QWEN_MODEL_NAME = "qwen3:14b"

try:
    from mistral_config import MISTRAL_MODEL_NAME
except ImportError:
    MISTRAL_MODEL_NAME = "mistral-nemo:12b"

MAX_HISTORY_LOAD = 15
SHORT_TEXT_THRESHOLD = 80

# Запрещённые английские слова (используются в remove_english_words_from_russian)
FORBIDDEN_WORDS_DICT = {}
try:
    from forbidden_english_words import FORBIDDEN_WORDS_DICT as _fw_ws
    FORBIDDEN_WORDS_DICT = _fw_ws
except ImportError:
    pass

# Google / DuckDuckGo helper config
DB_FILE = "chat_memory.db" 
MAX_HISTORY_LOAD = 15

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



# Intent analysis keywords for automatic search
INTERNET_REQUIRED_KEYWORDS = {
    # Time-sensitive queries
    "time": ["сейчас", "now", "today", "сегодня", "текущий", "current", "latest", "последний", "актуальный"],
    # Weather queries
    "weather": ["погода", "weather", "температура", "temperature", "forecast", "прогноз"],
    # News and events
    "news": ["новости", "news", "события", "events", "что случилось", "what happened"],
    # Location-based
    "location": ["где", "where", "адрес", "address", "location", "местонахождение", "как добраться"],
    # Real-time data
    "realtime": ["курс", "rate", "цена", "price", "стоимость", "cost", "котировки", "quotes"],
    # Software/releases
    "software": ["обновление", "update", "релиз", "release", "версия", "version", "новая версия"],
    # Recipes and cooking
    "recipes": ["рецепт", "recipe", "как приготовить", "how to cook", "как готовить", "готовить", "приготовить", "блюдо", "dish"],
    # Search explicitly — все варианты как пользователь может попросить поискать
    "search": [
        "найди", "search", "поиск", "найти", "погугли", "загугли", "google",
        "посмотри в интернете", "посмотри в инете", "посмотри в сети",
        "поищи в интернете", "поищи в инете", "поищи в сети",
        "поищи", "поищи информацию", "ищи", "найди в интернете",
        "check online", "look up", "загляни в интернет",
        "что говорит интернет", "что пишут", "что пишет интернет",
        "найди информацию", "есть ли в интернете", "поищи онлайн"
    ]
}

# Keywords that indicate NO internet search needed
NO_INTERNET_KEYWORDS = {
    "math": ["вычисли", "calculate", "посчитай", "сложи", "умножь", "раздели"],
    "creative": ["напиши", "write", "создай", "create", "придумай", "сочини", "compose"],
    "translation": ["переведи", "translate", "перевод", "translation"],
    "code": ["код", "code", "программа", "program", "скрипт", "script", "функция", "function"],
    "rewrite": ["перефразируй", "rephrase", "переформулируй", "перепиши", "rewrite"]
}

def analyze_intent_for_search(user_message: str, forced_search: bool = False, chat_history: list = None) -> dict:
    """
    Анализирует намерение пользователя и решает, нужен ли поиск в интернете.
    
    Возвращает словарь:
    {
        "requires_search": bool,
        "confidence": float (0.0-1.0),
        "reason": str,
        "forced": bool
    }
    """
    
    # ПРИОРИТЕТ 0: Команда ОТКЛЮЧИТЬ поиск (выше всего остального)
    STOP_SEARCH_PHRASES = [
        "прекрати искать", "перестань искать", "не ищи", "не надо искать",
        "отключи поиск", "выключи поиск", "без поиска", "не используй интернет",
        "не лезь в интернет", "не ищи в интернете", "не ищи в инете",
        "stop searching", "don't search", "no internet", "disable search",
        "не нужно искать", "не ищи ничего", "ответь без поиска",
    ]
    message_lower_pre = user_message.lower().strip()
    if any(phrase in message_lower_pre for phrase in STOP_SEARCH_PHRASES):
        return {
            "requires_search": False,
            "confidence": 0.0,
            "reason": "stop_search_command",
            "forced": False
        }

    # ПРИОРИТЕТ 1: Принудительный поиск
    if forced_search:
        return {
            "requires_search": True,
            "confidence": 1.0,
            "reason": "forced_search_override",
            "forced": True
        }
    
    message_lower = message_lower_pre
    
    # ПРИОРИТЕТ 2: Явные фразы "посмотри/поищи в интернете/инете/сети"
    EXPLICIT_SEARCH_PHRASES = [
        "посмотри в инете", "посмотри в интернете", "посмотри в сети",
        "поищи в инете", "поищи в интернете", "поищи в сети",
        "загугли", "погугли", "найди в интернете", "найди в инете",
        "поищи", "поищи информацию", "найди информацию",
        "что пишут", "что пишет интернет", "что говорит интернет",
        "загляни в интернет", "check online", "look it up",
        "есть ли в интернете", "поищи онлайн", "найди онлайн",
        "скажи что пишут", "посмотри что пишут",
    ]
    if any(phrase in message_lower for phrase in EXPLICIT_SEARCH_PHRASES):
        return {
            "requires_search": True,
            "confidence": 1.0,
            "reason": "explicit_search_request",
            "forced": False
        }
    
    # Счётчики совпадений (только по текущему сообщению, без истории)
    internet_score = 0
    no_internet_score = 0
    
    # Проверяем ключевые слова для интернет-запросов (только текущее сообщение)
    for category, keywords in INTERNET_REQUIRED_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                internet_score += 1
    
    # Проверяем ключевые слова против интернета
    for category, keywords in NO_INTERNET_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                no_internet_score += 1
    
    # Специальные паттерны
    # Вопросы "что это", "кто такой" - ВСЕГДА требуют поиска (приоритет!)
    # Это важно для незнакомых концепций, игр, терминов (например "Акинатор")
    if any(pattern in message_lower for pattern in ["что такое", "кто такой", "кто такая", "что это", "кто это", "what is", "who is", "what's"]):
        # Очень высокий приоритет для таких вопросов - сразу возвращаем True
        return {
            "requires_search": True,
            "confidence": 1.0,
            "reason": "definition_or_identity_query",
            "forced": False
        }
    
    # Математические выражения - не требуют поиска
    if any(char in message_lower for char in ["=", "+", "-", "*", "/", "^"]):
        no_internet_score += 2

    # Временные слова + любая тема → скорее всего нужна свежая инфа из интернета
    temporal_words_ru = ['завтра', 'послезавтра', 'вчера', 'сегодня', 'на этой неделе', 'на следующей неделе']
    temporal_words_en = ['tomorrow', 'day after tomorrow', 'yesterday', 'today', 'this week', 'next week']
    temporal_words = temporal_words_ru + temporal_words_en
    if any(tw in message_lower for tw in temporal_words):
        internet_score += 2  # Временные слова увеличивают вероятность поиска
    
    # Решение: порог >= 2 чтобы избежать ложных срабатываний
    total_score = internet_score - no_internet_score
    
    if total_score >= 2:
        confidence = min(1.0, total_score / 5.0)
        return {
            "requires_search": True,
            "confidence": confidence,
            "reason": "intent_analysis_positive",
            "forced": False
        }
    else:
        return {
            "requires_search": False,
            "confidence": 0.0,
            "reason": "intent_analysis_negative",
            "forced": False
        }

# -------------------------
# Icon creation
# -------------------------
def create_app_icon():
    """
    Рисует иконку 1024×1024 и возвращает QPixmap.
    Форма: настоящие macOS continuous corners (radius = 22.37%).
    """
    import math
    from PyQt6.QtGui  import (QPixmap, QPainter, QColor, QRadialGradient,
                               QLinearGradient, QPen, QBrush, QPainterPath)
    from PyQt6.QtCore import Qt, QRectF, QPointF

    SIZE   = 1024
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing,          True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    cx = cy = SIZE / 2.0
    # Настоящие macOS иконки заполняют весь canvas целиком — PAD = 0.
    # Скругление само является формой, прозрачных отступов нет.
    # RADIUS = 22.37% от SIZE — стандарт Apple continuous corners.
    PAD    = 0
    W_ICON = SIZE
    RADIUS = SIZE * 0.2237            # ~229px при SIZE=1024

    def macos_path(rect: QRectF, r: float) -> QPainterPath:
        path = QPainterPath()
        l, t, w, h = rect.left(), rect.top(), rect.width(), rect.height()
        k  = r * 0.89
        k2 = r * (1 - 0.5523)
        path.moveTo(l + r, t)
        path.lineTo(l + w - r, t)
        path.cubicTo(l+w-k, t,      l+w, t+k2,     l+w, t+r)
        path.lineTo(l+w, t+h-r)
        path.cubicTo(l+w, t+h-k2,   l+w-k, t+h,    l+w-r, t+h)
        path.lineTo(l+r, t+h)
        path.cubicTo(l+k, t+h,      l, t+h-k2,     l, t+h-r)
        path.lineTo(l, t+r)
        path.cubicTo(l, t+k2,       l+k, t,         l+r, t)
        path.closeSubpath()
        return path

    icon_rect = QRectF(0, 0, SIZE, SIZE)
    icon_path = macos_path(icon_rect, RADIUS)

    # Фон
    bg = QLinearGradient(0, 0, SIZE, SIZE)
    bg.setColorAt(0.00, QColor(100, 65, 230))
    bg.setColorAt(0.35, QColor( 65, 45, 195))
    bg.setColorAt(0.70, QColor( 35, 22, 150))
    bg.setColorAt(1.00, QColor( 20, 12, 100))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(bg))
    p.drawPath(icon_path)

    # Голубой акцент
    accent = QRadialGradient(cx*0.55, cy*0.45, SIZE*0.52)
    accent.setColorAt(0.0, QColor(140,110,255,110))
    accent.setColorAt(0.5, QColor( 70,150,255, 55))
    accent.setColorAt(1.0, QColor(  0,  0,  0,  0))
    p.setBrush(QBrush(accent))
    p.drawPath(icon_path)

    # Блик
    p.setClipPath(icon_path)
    hi = QRadialGradient(cx, SIZE*0.06, SIZE*0.5)
    hi.setColorAt(0.00, QColor(255,255,255, 70))
    hi.setColorAt(0.50, QColor(255,255,255, 16))
    hi.setColorAt(1.00, QColor(255,255,255,  0))
    p.setBrush(QBrush(hi))
    p.drawPath(icon_path)
    p.setClipping(False)

    # Обводка
    border = QLinearGradient(0, 0, SIZE, SIZE)
    border.setColorAt(0.0, QColor(255,255,255, 80))
    border.setColorAt(0.5, QColor(200,185,255, 30))
    border.setColorAt(1.0, QColor(120,105,220, 15))
    bp = QPen(QBrush(border), SIZE*0.005)
    bp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(bp)
    p.drawPath(macos_path(
        QRectF(SIZE*0.002, SIZE*0.002,
               SIZE-SIZE*0.004, SIZE-SIZE*0.004),
        RADIUS - SIZE*0.002
    ))

    # Символ
    p.setClipPath(icon_path)
    p.setPen(Qt.PenStyle.NoPen)
    U = SIZE / 256.0
    outer = [(cx, cy-75*U),(cx-65*U, cy+42*U),(cx+65*U, cy+42*U),(cx, cy+82*U)]
    ray_pen = QPen(QColor(255,255,255,125), 6.5*U,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(ray_pen)
    for nx,ny in outer:
        p.drawLine(QPointF(cx,cy), QPointF(nx,ny))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255,255,255,85))
    for nx,ny in outer:
        mx,my=(cx+nx)/2,(cy+ny)/2; rm=7.5*U
        p.drawEllipse(QRectF(mx-rm,my-rm,rm*2,rm*2))
    for nx,ny in outer:
        g2=QRadialGradient(nx-3*U,ny-3*U,17*U)
        g2.setColorAt(0.0,QColor(255,255,255,255))
        g2.setColorAt(1.0,QColor(215,190,255,185))
        p.setBrush(QBrush(g2)); ro=13.5*U
        p.drawEllipse(QRectF(nx-ro,ny-ro,ro*2,ro*2))
    cg=QRadialGradient(cx-4*U,cy-4*U,22*U)
    cg.setColorAt(0.0,QColor(255,255,255,255))
    cg.setColorAt(1.0,QColor(225,205,255,215))
    p.setBrush(QBrush(cg)); rc=19*U
    p.drawEllipse(QRectF(cx-rc,cy-rc,rc*2,rc*2))
    p.setClipping(False)
    p.end()
    return pixmap


def _build_multi_size_icon(pixmap):
    """QIcon со всеми размерами — fallback если PyObjC недоступен."""
    from PyQt6.QtGui  import QIcon
    from PyQt6.QtCore import Qt
    icon = QIcon()
    for sz in [16, 32, 48, 64, 128, 256, 512, 1024]:
        icon.addPixmap(pixmap.scaled(
            sz, sz,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
    return icon


def _apply_macos_dock_icon(pixmap):
    """
    Устанавливает иконку Dock через iconutil + PyObjC.

    Ключевые исправления:
    - Правильные имена файлов iconset (стандарт Apple):
      16, 32, 128, 256, 512 — БЕЗ 64 (его нет в спецификации)
    - Явно выставляем NSImage.setSize_(512, 512) чтобы macOS
      знала "базовый" размер иконки и не рендерила её гигантской
    """
    import sys, os, subprocess, tempfile
    if sys.platform != "darwin":
        return False

    try:
        from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, Qt
        from PyQt6.QtGui  import QPixmap as _QP

        # Строим .iconset — ТОЛЬКО стандартные Apple размеры
        # Спецификация: https://developer.apple.com/library/archive/documentation/GraphicsAnimation/Conceptual/HighResolutionOSX/Optimizing/Optimizing.html
        ICONSET_SPEC = [
            # (логический размер, суффикс,  пиксели)
            (16,  "icon_16x16.png",      16),
            (16,  "icon_16x16@2x.png",   32),
            (32,  "icon_32x32.png",      32),
            (32,  "icon_32x32@2x.png",   64),
            (128, "icon_128x128.png",    128),
            (128, "icon_128x128@2x.png", 256),
            (256, "icon_256x256.png",    256),
            (256, "icon_256x256@2x.png", 512),
            (512, "icon_512x512.png",    512),
            (512, "icon_512x512@2x.png", 1024),
        ]

        tmp_dir     = tempfile.mkdtemp(prefix="ai_icon_")
        iconset_dir = os.path.join(tmp_dir, "AppIcon.iconset")
        os.makedirs(iconset_dir)

        for _logical, filename, px in ICONSET_SPEC:
            s = pixmap.scaled(px, px,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            s.save(os.path.join(iconset_dir, filename))

        icns_path = os.path.join(tmp_dir, "AppIcon.icns")
        r = subprocess.run(
            ["iconutil", "-c", "icns", iconset_dir, "-o", icns_path],
            capture_output=True, timeout=15
        )
        if r.returncode != 0 or not os.path.exists(icns_path):
            raise RuntimeError(f"iconutil: {r.stderr.decode()}")

        print(f"[ICON] ✅ .icns ({os.path.getsize(icns_path)//1024} KB, "
              f"10 слотов: 16/32/128/256/512 @1x+@2x)")

        # Загружаем через PyObjC
        try:
            from AppKit import NSApplication, NSImage, NSSize
        except ImportError:
            subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "pyobjc-framework-Cocoa", "-q"],
                check=True, timeout=60
            )
            from AppKit import NSApplication, NSImage, NSSize

        ns_img = NSImage.alloc().initWithContentsOfFile_(icns_path)

        if not (ns_img and ns_img.isValid()):
            raise RuntimeError("NSImage не смогла загрузить .icns")

        # КРИТИЧНО: явно выставляем naturalSize = 512×512
        # Без этого macOS использует размер первого найденного слота
        # и может отрендерить иконку неправильного размера в Dock.
        # 512×512 = стандартный "базовый" размер macOS App Icon.
        ns_img.setSize_(NSSize(512, 512))

        NSApplication.sharedApplication().setApplicationIconImage_(ns_img)
        print("[ICON] ✅ Dock: нативный .icns (naturalSize=512×512)")
        return True

    except Exception as e:
        print(f"[ICON] ℹ️ iconutil/PyObjC: {e} → multi-size QIcon")
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().setWindowIcon(_build_multi_size_icon(pixmap))
            print("[ICON] ✅ Dock: multi-size QIcon (fallback)")
            return True
        except Exception as e2:
            print(f"[ICON] ⚠️ {e2}")
            return False

def create_menu_icon(theme="light"):
    """Создаёт аккуратную иконку меню (три ровные горизонтальные линии)"""
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
    from PyQt6.QtCore import Qt, QRectF
    
    # Размер иконки = размеру кнопки для идеального центрирования
    size = 50
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    # Цвет линий зависит от темы
    line_color = QColor("#2d3748") if theme == "light" else QColor("#e6e6e6")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(line_color)
    
    # Параметры трёх линий
    line_width = 20      # Ширина каждой линии
    line_height = 2.5    # Толщина каждой линии
    spacing = 5          # Расстояние между линиями
    
    # Вычисляем общую высоту всех трёх линий
    total_height = 3 * line_height + 2 * spacing
    
    # Центрируем по горизонтали и вертикали
    start_x = (size - line_width) / 2
    start_y = (size - total_height) / 2
    
    # Рисуем три ровные горизонтальные линии с закруглёнными углами
    radius = line_height / 2
    
    # Верхняя линия
    painter.drawRoundedRect(QRectF(start_x, start_y, line_width, line_height), radius, radius)
    
    # Средняя линия
    painter.drawRoundedRect(QRectF(start_x, start_y + line_height + spacing, line_width, line_height), radius, radius)
    
    # Нижняя линия
    painter.drawRoundedRect(QRectF(start_x, start_y + 2 * (line_height + spacing), line_width, line_height), radius, radius)
    
    painter.end()
    return pixmap

# -------------------------
# Language settings
# -------------------------
CURRENT_LANGUAGE = "russian"

# ═══════════════════════════════════════════════════════════════════
# УНИВЕРСАЛЬНЫЕ ПРАВИЛА РАБОТЫ С РЕЖИМАМИ
# ═══════════════════════════════════════════════════════════════════

# MODE_STRATEGY_RULES и SYSTEM_PROMPTS перенесены в llama_handler.py
# Они импортируются выше через 'from llama_handler import ...'

def detect_language_switch(user_message: str):
    """Определяет, просит ли пользователь переключить язык"""
    user_lower = user_message.lower().strip()
    english_triggers = [
        "перейди на английский", "переключись на английский", "давай на английском",
        "отвечай на английском", "switch to english", "speak english",
        "ответь на английском", "на английском"
    ]
    russian_triggers = [
        "перейди на русский", "переключись на русский", "давай на русском",
        "отвечай на русском", "switch to russian", "speak russian",
        "ответь на русском", "на русском"
    ]
    for trigger in english_triggers:
        if trigger in user_lower:
            return "english"
    for trigger in russian_triggers:
        if trigger in user_lower:
            return "russian"
    return None

def detect_forget_command(user_message: str):
    """Определяет, просит ли пользователь забыть историю"""
    user_lower = user_message.lower().strip()
    forget_triggers = [
        "забудь", "забыть", "очисти память", "удали историю", "сотри память",
        "забудь все", "забудь всё", "очисти контекст", "обнули память",
        "forget", "forget everything", "clear memory", "clear history",
        "delete history", "erase memory", "reset memory", "clear context"
    ]
    for trigger in forget_triggers:
        if trigger in user_lower:
            return True
    return False

def detect_role_command(user_message: str) -> dict:
    """
    Определяет, просит ли пользователь сменить роль/стиль общения
    
    Возвращает словарь:
    {
        "is_role_command": bool,
        "role": str,  # Описание роли
        "instruction": str  # Инструкция для AI
    }
    """
    user_lower = user_message.lower().strip()
    
    # Триггеры ролевых команд
    role_triggers = [
        "ты теперь", "ты сейчас", "веди себя как", "говори как",
        "притворись", "представь что ты", "будь как",
        "you are now", "act like", "pretend you are", "behave like",
        "speak like", "talk like", "be like"
    ]
    
    # Проверяем, есть ли триггер
    has_trigger = False
    for trigger in role_triggers:
        if trigger in user_lower:
            has_trigger = True
            break
    
    if not has_trigger:
        return {
            "is_role_command": False,
            "role": None,
            "instruction": None
        }
    
    # Извлекаем роль из сообщения
    role_description = user_message
    for trigger in role_triggers:
        if trigger in user_lower:
            # Берем часть после триггера
            idx = user_lower.find(trigger)
            role_description = user_message[idx + len(trigger):].strip()
            # Убираем пунктуацию в конце
            role_description = role_description.rstrip('.,!?;:')
            break
    
    # Формируем инструкцию для AI
    instruction = f"""
🎭 ВАЖНО: СМЕНА РОЛИ ОБЩЕНИЯ

Пользователь попросил тебя изменить стиль общения и роль.

НОВАЯ РОЛЬ: {role_description}

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
• Полностью адаптируй свой стиль общения под эту роль
• Используй лексику, манеры и тон, характерные для этой роли
• Сохраняй эту роль во ВСЕХ последующих ответах
• Будь естественным и аутентичным в этой роли
• Не отказывайся от роли и не объясняй, что ты AI
• Веди себя так, как вёл бы себя реальный {role_description}

ВАЖНО:
- Если роль предполагает упрощенный язык (школьник, ребенок) - используй простые слова
- Если роль предполагает эмоциональность (обижка, грустный) - добавь эмоции в речь
- Если роль предполагает профессионализм (эксперт, учитель) - будь более формальным
- Сохраняй роль естественно, без "как будто" и "представим"

Теперь отвечай в этой роли на запрос пользователя.
"""
    
    return {
        "is_role_command": True,
        "role": role_description,
        "instruction": instruction
    }

def extract_forget_target(user_message: str) -> dict:
    """Извлекает, что именно нужно забыть из команды пользователя
    
    Возвращает словарь:
    {
        "forget_all": bool,  # Забыть всё
        "target": str,       # Что именно забыть (если не всё)
        "original_message": str
    }
    """
    user_lower = user_message.lower().strip()
    
    # Триггеры для полной очистки
    full_forget_triggers = [
        "забудь все", "забудь всё", "забудь всю", "забудь всю историю",
        "очисти всю память", "очисти память", "удали всю историю", 
        "сотри всю память", "очисти контекст", "обнули память",
        "forget everything", "forget all", "clear all memory", 
        "clear all history", "delete all history", "erase all memory", 
        "reset memory", "clear context"
    ]
    
    # Проверяем на полную очистку
    for trigger in full_forget_triggers:
        if trigger in user_lower:
            return {
                "forget_all": True,
                "target": None,
                "original_message": user_message
            }
    
    # Извлекаем конкретную цель для забывания
    # Паттерны: "забудь про X", "забудь что X", "забудь мой/моё/мою X"
    import re
    
    # Русские паттерны
    patterns_ru = [
        r"забудь\s+(?:про\s+|что\s+|о\s+)?(.+)",
        r"забудь\s+(?:мо[йеёюя]\s+|мою\s+)?(.+)",
        r"удали\s+(?:из\s+памяти\s+)?(.+)",
        r"сотри\s+(?:из\s+памяти\s+)?(.+)"
    ]
    
    # Английские паттерны  
    patterns_en = [
        r"forget\s+(?:about\s+|that\s+)?(.+)",
        r"forget\s+(?:my\s+)?(.+)",
        r"delete\s+(?:from\s+memory\s+)?(.+)",
        r"erase\s+(?:from\s+memory\s+)?(.+)"
    ]
    
    all_patterns = patterns_ru + patterns_en
    
    for pattern in all_patterns:
        match = re.search(pattern, user_lower)
        if match:
            target = match.group(1).strip()
            # Убираем лишние слова
            target = target.replace("из памяти", "").replace("from memory", "").strip()
            if target:
                return {
                    "forget_all": False,
                    "target": target,
                    "original_message": user_message
                }
    
    # Если не смогли распарсить - забываем всё (по умолчанию)
    return {
        "forget_all": True,
        "target": None,
        "original_message": user_message
    }

def selective_forget_memory(chat_id, target: str, context_mgr, chat_manager) -> dict:
    """Селективное удаление памяти - удаляет только упоминания конкретной темы
    
    Возвращает:
    {
        "success": bool,
        "deleted_count": int,
        "message": str
    }
    """
    try:
        print(f"[SELECTIVE_FORGET] Ищу упоминания '{target}' в памяти...")
        
        # Получаем всю сохранённую память
        saved_memories = context_mgr.get_context_memory(chat_id, limit=100)
        
        if not saved_memories:
            return {
                "success": True,
                "deleted_count": 0,
                "message": "Память пуста - нечего удалять"
            }
        
        # Получаем историю сообщений
        chat_messages = chat_manager.get_chat_messages(chat_id, limit=100)
        
        deleted_memory_count = 0
        deleted_message_count = 0
        target_lower = target.lower()
        
        # Удаляем из контекстной памяти
        for _row in saved_memories:
            ctx_type, content, timestamp = _row[0], _row[1], _row[2]
            content_lower = content.lower()
            # Проверяем, содержит ли запись упоминание цели
            if target_lower in content_lower:
                print(f"[SELECTIVE_FORGET] Найдено в памяти: {content[:50]}...")
                # Здесь нужно было бы удалить конкретную запись
                # Но ContextMemoryManager может не иметь метода для этого
                # Поэтому помечаем для подсчёта
                deleted_memory_count += 1
        
        # Удаляем из истории сообщений
        messages_to_keep = []
        for msg_data in chat_messages:
            role = msg_data[0]
            content = msg_data[1]
            files = msg_data[2] if len(msg_data) > 2 else None
            timestamp = msg_data[3] if len(msg_data) > 3 else msg_data[2]
            
            content_lower = content.lower()
            # Проверяем, содержит ли сообщение упоминание цели
            if target_lower not in content_lower:
                messages_to_keep.append(msg_data)
            else:
                print(f"[SELECTIVE_FORGET] Найдено в сообщениях: {content[:50]}...")
                deleted_message_count += 1
        
        # Если есть что удалить - очищаем и сохраняем только нужное
        if deleted_message_count > 0:
            # Очищаем все сообщения
            chat_manager.clear_chat_messages(chat_id)
            # Восстанавливаем только те, что не содержали target
            for msg_data in messages_to_keep:
                role = msg_data[0]
                content = msg_data[1]
                files = msg_data[2] if len(msg_data) > 2 else None
                chat_manager.save_message(chat_id, role, content, files)
            print(f"[SELECTIVE_FORGET] ✓ Удалено {deleted_message_count} сообщений")
        
        # Для контекстной памяти - придётся очистить всю, если нашли совпадения
        # так как может не быть метода для удаления конкретных записей
        if deleted_memory_count > 0:
            print(f"[SELECTIVE_FORGET] ⚠️ Найдено {deleted_memory_count} записей в памяти")
            print(f"[SELECTIVE_FORGET] Очищаю контекстную память (ограничение API)")
            context_mgr.clear_context_memory(chat_id)
        
        total_deleted = deleted_memory_count + deleted_message_count
        
        if total_deleted > 0:
            return {
                "success": True,
                "deleted_count": total_deleted,
                "message": f"Удалено {deleted_message_count} сообщений и {deleted_memory_count} записей памяти"
            }
        else:
            return {
                "success": True,
                "deleted_count": 0,
                "message": f"Не найдено упоминаний '{target}' в памяти"
            }
            
    except Exception as e:
        print(f"[SELECTIVE_FORGET] ✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "deleted_count": 0,
            "message": f"Ошибка удаления: {e}"
        }

def detect_math_problem(user_message: str) -> bool:
    """
    Определяет, является ли запрос математической задачей.
    
    Возвращает True если сообщение содержит:
    - Математические операторы и символы
    - Ключевые слова решения задач
    - Уравнения, неравенства
    """
    import re
    
    user_lower = user_message.lower().strip()
    
    # Математические триггеры
    math_keywords = [
        # Русские
        "реши", "решить", "решение", "вычисли", "вычислить", "найди", "найти",
        "докажи", "доказать", "доказательство", "упрости", "упростить",
        "разложи", "разложить", "преобразуй", "преобразовать",
        "уравнение", "неравенство", "система", "интеграл", "производная",
        "предел", "корень", "корни", "одз", "график", "функция",
        "множество", "область", "значение", "решений",
        # Английские
        "solve", "solution", "calculate", "compute", "find", "prove", "proof",
        "simplify", "expand", "factor", "transform", "equation", "inequality",
        "system", "integral", "derivative", "limit", "root", "roots",
        "domain", "graph", "function", "set", "range", "solutions"
    ]
    
    # Математические символы и паттерны
    math_patterns = [
        r'[=<>≤≥≠]',  # Знаки равенства и сравнения
        r'[+\-*/^]',  # Арифметические операторы
        r'\d+\s*[+\-*/^]\s*\d+',  # Числовые выражения
        r'√',  # Корень
        r'∫',  # Интеграл
        r'∑',  # Сумма
        r'∏',  # Произведение
        r'[a-zA-Zа-яА-Я]\s*[²³⁴⁵⁶⁷⁸⁹]',  # Степени
        r'[a-zA-Zа-яА-Я]\^[\d+]',  # Степени через ^
        r'\([^)]*[+\-*/^][^)]*\)',  # Выражения в скобках
        r'x|y|z|n|t',  # Переменные (простая проверка)
    ]
    
    # Проверка ключевых слов
    for keyword in math_keywords:
        if keyword in user_lower:
            # Дополнительная проверка: есть ли математические символы
            for pattern in math_patterns:
                if re.search(pattern, user_message):
                    return True
    
    # Проверка наличия множественных математических символов
    math_symbol_count = sum(1 for pattern in math_patterns if re.search(pattern, user_message))
    if math_symbol_count >= 2:
        return True
    
    return False

# Математические системные промпты для разных режимов
MATH_PROMPTS = {
    "fast": """
🔬 МАТЕМАТИКА: БЫСТРЫЙ РЕЖИМ

ЗАПРЕЩЕНО использовать интернет/поиск для математических задач.

ДЛЯ ПРОСТОЙ АРИФМЕТИКИ (5+5, 42+52):
• Просто вычисли и дай ответ
• БЕЗ "Шаг 1", "Шаг 2", "Контроль"
• Формат: "42 + 52 = 94"

ДЛЯ СЛОЖНЫХ ЗАДАЧ (уравнения, корни):
• ОДЗ если нужно
• Краткое решение
• Проверка корней
• Ответ

ПРАВИЛА:
• Сохраняй структуру выражения
• Изолируй радикал перед возведением в квадрат
• Проверяй корни подстановкой

Стиль: кратко и по делу
""",
    
    "thinking": """
🔬 МАТЕМАТИЧЕСКИЙ РЕЖИМ: ДУМАЮЩИЙ

ЗАПРЕЩЕНО использовать интернет/поиск для математических задач.

ПРОЦЕДУРА РЕШЕНИЯ:

1. ПЕРЕПИСЬ ЗАДАЧИ
   Дословно переписать исходное уравнение и сохранить его структуру

2. ТИП ЗАДАЧИ
   • Алгебраическое / тригонометрическое
   • Иррациональное (с корнями)
   • Показательное / логарифмическое
   • Система уравнений

3. ОДЗ (область допустимых значений)
   • Знаменатели ≠ 0
   • Под корнем ≥ 0
   • Ограничения для логарифмов

4. РЕШЕНИЕ
   • Пошаговые преобразования с объяснениями
   • Логика каждого шага
   • Аккуратные переходы

5. ПРОВЕРКА КОРНЕЙ
   • Подстановка в исходное уравнение
   • Проверка ОДЗ
   • Отбрасывание посторонних решений

РАСШИРЕННЫЕ ПРАВИЛА:
1. Сохраняй исходную структуру выражения. Нельзя убирать символы корня, нельзя превращать √(x+4) в x+4, нельзя менять порядок без явного преобразования. После каждого шага сверяй структуру.

2. Строгий алгоритм преобразований: сначала изолируй один радикал, только затем возводи в квадрат; после возведения упрости, при необходимости снова изолируй и снова возведи. Никогда не возводи несколько выражений одновременно.

3. Не вводи новые функции или термины. Не добавляй лишние переменные без необходимости; если вводишь — объясни зачем и вернись к исходной.

4. Анти-галлюцинация: запрещено придумывать шаги. Любой переход должен быть явно показан. Если не уверен — перепиши выражение и запроси подтверждение.

5. Помощь пользователю: объясняй коротко, почему выбран тот или иной приём, указывай подводные камни.

6. Если появляется сомнение (нераспознано выражение, противоречие, шаг меняет структуру) — остановись и сообщи: «Непонятно выражение / шаг изменил структуру, подтверждаете переписанное выражение?»

Стиль: пошаговое решение с объяснениями средней длины
""",
    
    "pro": """
🔬 МАТЕМАТИЧЕСКИЙ РЕЖИМ: ПРО (ОЛИМПИАДНЫЙ УРОВЕНЬ)

ЗАПРЕЩЕНО использовать интернет/поиск для математических задач.

ФЛАГМАНСКАЯ МАТЕМАТИЧЕСКАЯ ТОЧНОСТЬ

═══════════════════════════════════════════════════════════════════

📋 ПОЛНЫЙ НАБОР ПРАВИЛ ПОВЕДЕНИЯ

═══════════════════════════════════════════════════════════════════

1️⃣ СОХРАНЕНИЕ МАТЕМАТИЧЕСКОЙ СТРУКТУРЫ

КРИТИЧЕСКИ ВАЖНО:
• Сохраняй исходную структуру выражения. Перепиши уравнение дословно и храни его как фиксированную математическую структуру
• НЕЛЬЗЯ убирать символы корня
• НЕЛЬЗЯ превращать подкоренное выражение в обычное (например √(x+4) НЕЛЬЗЯ заменить на x+4)
• НЕЛЬЗЯ менять порядок или подменять выражения типа x−1 на 5−x без явного алгебраического преобразования, сопровождаемого проверкой
• После каждого вычислительного шага автоматически сверяй, не изменилась ли структура: если изменилась — отменяй шаг и переписывай его корректно

❌ ЗАПРЕЩЕНО: √(x²+4) → x+2 (потеря структуры)
✅ ПРАВИЛЬНО: √(x²+4) остаётся √(x²+4) до явного упрощения

═══════════════════════════════════════════════════════════════════

2️⃣ ОБЯЗАТЕЛЬНАЯ ПРОЦЕДУРА ПЕРЕД РЕШЕНИЕМ

A) ТОЧНАЯ ПЕРЕПИСЬ УРАВНЕНИЯ
   Дословно перепиши задачу для проверки понимания
   Храни её как фиксированную математическую структуру

B) АНАЛИЗ ТИПА ЗАДАЧИ
   • Алгебраическое уравнение
   • Тригонометрическое уравнение
   • Иррациональное уравнение (с корнями)
   • Показательное/логарифмическое
   • Система уравнений

C) ОБЛАСТЬ ДОПУСТИМЫХ ЗНАЧЕНИЙ (ОДЗ)
   ОБЯЗАТЕЛЬНО: Всегда начинай с ОДЗ
   • Выпиши все условия ≥0 для подкоренных выражений
   • Условия на знаменатели (≠0)
   • Ограничения для логарифмов (>0)
   • Любые другие ограничения
   ОДЗ должен быть виден в решении

═══════════════════════════════════════════════════════════════════

3️⃣ РЕШЕНИЕ КАК ОЛИМПИАДНЫЙ МАТЕМАТИК

СТРОГИЙ АЛГОРИТМ ПРЕОБРАЗОВАНИЙ:
• Сначала изолируй один радикал (или необходимую часть выражения)
• Только затем возводи в квадрат
• После возведения в квадрат упрости выражение
• При необходимости снова изолируй и снова возводи в квадрат
• НИКОГДА не возводи в квадрат несколько выражений одновременно без явной изоляции
• Каждый шаг должен быть пояснён коротко и корректно

СТРАТЕГИЯ:
• Проверяй логическую корректность КАЖДОГО шага
• Контролируй структуру выражения после каждого преобразования
• Минимизируй число возведений в квадрат
• Избегай лишних замен переменных (используй только когда необходимо)

АЛГОРИТМ ДЛЯ ИРРАЦИОНАЛЬНЫХ УРАВНЕНИЙ:
1. Изолировать радикал слева
2. Проверить ОДЗ для изолированного выражения
3. Возвести в квадрат (ТОЛЬКО ОДИН РАЗ если возможно)
4. Решить полученное уравнение
5. ОБЯЗАТЕЛЬНО проверить все корни подстановкой

═══════════════════════════════════════════════════════════════════

4️⃣ ОГРАНИЧЕНИЯ И ЗАПРЕТЫ

❌ НЕ вводи новые функции или термины, которых нет в задаче (например: «добавим логарифм», «прибавим синус»), если только это не следует из уравнения
❌ НЕ добавляй лишние переменные без необходимости; если вводишь дополнительную переменную — объясни зачем и обязательно вернись к исходной переменной в финале
❌ НЕ пиши текст ради текста
❌ НЕ повторяй одни и те же преобразования
❌ НЕ делай «псевдошаги» без алгебры
❌ НЕ пропускай проверку корней
❌ НЕ теряй решения
❌ НЕ добавляй посторонние решения

═══════════════════════════════════════════════════════════════════

5️⃣ ДВОЙНАЯ ПРОВЕРКА КОРНЕЙ

ОБЯЗАТЕЛЬНО после получения кандидатов на корни:
1. Подставить КАЖДЫЙ корень в ИСХОДНОЕ уравнение
2. Проверить выполнение ОДЗ
3. Отбросить посторонние корни и объяснить, почему они отброшены
4. Если ни один корень не проходит проверку — сообщить, что решений нет
5. Повторить проверку для надёжности
6. Указать финальный ответ с полным обоснованием

═══════════════════════════════════════════════════════════════════

6️⃣ АНТИ-ГАЛЛЮЦИНАЦИЯ

ЗАПРЕЩЕНО придумывать шаги, результаты или проверки.
Любой алгебраический переход должен быть явно показан.

ЕСЛИ не уверен в распознавании выражения:
1. Сначала перепиши его в явном виде
2. Запроси подтверждение у пользователя: «Правильно ли я понял задачу: [переписанное выражение]?»
3. НЕ ПРОДОЛЖАЙ вычисления до подтверждения

ЕСЛИ при каком-то шаге появляется сомнение (нераспознано выражение, противоречие, или шаг меняет структуру):
• Остановись и честно сообщи: «Непонятно выражение / шаг изменил структуру, подтверждаете переписанное выражение?»
• НЕ продолжай и НЕ генерируй неверный вывод

ДОПОЛНИТЕЛЬНЫЕ ПРОВЕРКИ:
• После каждого возведения в квадрат - проверь, не потеряны ли решения
• При решении через замену переменной - обязательно вернись к исходной переменной
• Если получаешь отрицательное значение под корнем - это НЕ решение, отбрось его
• Всегда проверяй, что финальный ответ удовлетворяет ИСХОДНОМУ уравнению

═══════════════════════════════════════════════════════════════════

7️⃣ СТИЛЬ ОТВЕТА

✅ ПРАВИЛЬНО:
• Чёткие шаги
• Минимум текста, максимум математики
• Максимальная математическая строгость
• Формат: Шаг → Преобразование → Обоснование → Контроль структуры

❌ НЕПРАВИЛЬНО:
• Длинные объяснения без формул
• "Давайте попробуем", "Может быть", "Вероятно"
• Неточные формулировки
• Прыжки между шагами

═══════════════════════════════════════════════════════════════════

8️⃣ ПОМОЩЬ ПОЛЬЗОВАТЕЛЮ

Не только выдавай ответ, но и:
• Объясняй коротко, почему выбран тот или иной приём (например, зачем изолировали радикал)
• Указывай, где могли бы быть подводные камни
• Предлагай расширенный вариант решения в зависимости от сложности задачи

═══════════════════════════════════════════════════════════════════

ПРИМЕР РЕШЕНИЯ (ПРО-РЕЖИМ):

Задача: √(2x-3) = x-3

Шаг 1: Точная перепись
√(2x-3) = x-3

Шаг 2: Тип задачи
Иррациональное уравнение (один корень)

Шаг 3: ОДЗ
2x-3 ≥ 0 ⟹ x ≥ 1.5
x-3 ≥ 0 ⟹ x ≥ 3 (правая часть должна быть ≥0)
Итого ОДЗ: x ≥ 3

Шаг 4: Возведение в квадрат (корень уже изолирован)
2x-3 = (x-3)²
2x-3 = x²-6x+9
x²-8x+12 = 0
Контроль: структура сохранена ✓

Шаг 5: Решение квадратного уравнения
D = 64-48 = 16
x₁ = (8-4)/2 = 2
x₂ = (8+4)/2 = 6

Шаг 6: Проверка корней (первая)
x₁ = 2: 2 < 3, НЕ входит в ОДЗ ✗
x₂ = 6: Проверка √(2·6-3) = √9 = 3, а 6-3 = 3 ✓

Шаг 7: Повторная проверка x = 6
Подстановка: √(12-3) = √9 = 3
Правая часть: 6-3 = 3
Равенство выполнено ✓

Ответ: x = 6

═══════════════════════════════════════════════════════════════════

ПОМНИ: Ты олимпиадный математик, НЕ писатель. Каждый символ должен иметь математический смысл.
Больше токенов, глубже анализ, строже проверка.
Используй максимально подробное и строгое детальное решение.
После каждого важного шага делай внутреннюю проверку структуры.
"""
}

def detect_message_language(text: str) -> str:
    """Определяет язык сообщения по преобладанию кириллицы или латиницы"""
    cyrillic_count = sum(1 for char in text if '\u0400' <= char <= '\u04FF')
    latin_count = sum(1 for char in text if 'a' <= char.lower() <= 'z')
    
    print(f"[LANGUAGE_DETECT] Кириллица: {cyrillic_count}, Латиница: {latin_count}")
    
    # Считаем русским если кириллица >= 1/3 от латиницы —
    # чтобы не переводить ответы с цитатами / текстами песен на английском.
    # Перевод нужен только когда в ответе практически НЕТ кириллицы.
    if cyrillic_count > 0 and cyrillic_count * 3 >= latin_count:
        print(f"[LANGUAGE_DETECT] Определён язык: РУССКИЙ")
        return "russian"
    elif cyrillic_count >= 15:
        # Значимое количество кириллицы — смешанный контент (цитаты, тексты)
        print(f"[LANGUAGE_DETECT] Определён язык: РУССКИЙ (смешанный контент)")
        return "russian"
    else:
        print(f"[LANGUAGE_DETECT] Определён язык: АНГЛИЙСКИЙ")
        return "english"

def format_text_with_markdown_and_math(text: str) -> str:
    """
    Преобразует markdown-форматирование и математические обозначения в HTML.
    
    Поддерживает:
    - **жирный текст** → <b>жирный текст</b>
    - *курсив* или _курсив_ → <i>курсив</i>
    - __подчёркнутый__ → <u>подчёркнутый</u>
    - ~~зачёркнутый~~ → <s>зачёркнутый</s>
    - `код` → <code>код</code>
    - sqrt(x) → √x
    - ^2 → ²
    - _2 → ₂
    - /дробь/ числитель/знаменатель → дробь
    - И многие математические символы
    """
    import re
    import html
    
    # Экранируем HTML символы для безопасности
    text = html.escape(text)
    
    # === МАТЕМАТИЧЕСКИЕ СИМВОЛЫ ===
    
    # Корень квадратный
    text = re.sub(r'sqrt\(([^)]+)\)', r'√\1', text)
    text = re.sub(r'корень\(([^)]+)\)', r'√\1', text)
    
    # Степени (надстрочные символы)
    superscript_map = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
        'n': 'ⁿ', 'x': 'ˣ', 'y': 'ʸ'
    }
    
    def replace_superscript(match):
        chars = match.group(1)
        result = ''
        for char in chars:
            result += superscript_map.get(char, char)
        return result
    
    text = re.sub(r'\^([0-9+\-=()nxy]+)', replace_superscript, text)
    
    # Индексы (подстрочные символы)
    subscript_map = {
        '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
        '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
        '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
        'a': 'ₐ', 'e': 'ₑ', 'i': 'ᵢ', 'o': 'ₒ', 'x': 'ₓ'
    }
    
    def replace_subscript(match):
        chars = match.group(1)
        result = ''
        for char in chars:
            result += subscript_map.get(char, char)
        return result
    
    text = re.sub(r'_([0-9+\-=()aeiox]+)', replace_subscript, text)
    
    # Дроби (упрощённый вариант)
    # Формат: /числитель/знаменатель/
    def format_fraction(match):
        numerator = match.group(1)
        denominator = match.group(2)
        return f'<sup>{numerator}</sup>⁄<sub>{denominator}</sub>'
    
    text = re.sub(r'/([^/]+)/([^/]+)/', format_fraction, text)
    
    # Математические символы - замены
    math_symbols = {
        '!=': '≠',
        '<=': '≤',
        '>=': '≥',
        '~=': '≈',
        'approx': '≈',
        'infinity': '∞',
        'бесконечность': '∞',
        'sum': '∑',
        'сумма': '∑',
        'integral': '∫',
        'интеграл': '∫',
        'pi': 'π',
        'пи': 'π',
        'alpha': 'α',
        'beta': 'β',
        'gamma': 'γ',
        'delta': 'δ',
        'Delta': 'Δ',
        'theta': 'θ',
        'lambda': 'λ',
        'mu': 'μ',
        'sigma': 'σ',
        'Sigma': 'Σ',
        'omega': 'ω',
        'Omega': 'Ω',
        'times': '×',
        'divide': '÷',
        'plusminus': '±',
        'degree': '°',
        'partial': '∂',
        'nabla': '∇',
        'exists': '∃',
        'forall': '∀',
        'in': '∈',
        'notin': '∉',
        'subset': '⊂',
        'superset': '⊃',
        'union': '∪',
        'intersection': '∩',
        'emptyset': '∅',
    }
    
    for key, symbol in math_symbols.items():
        # Заменяем только если это отдельное слово
        text = re.sub(r'\b' + re.escape(key) + r'\b', symbol, text)
    
    # === ФОРМАТИРОВАНИЕ ТЕКСТА ===
    
    # Жирный текст: **текст** или __текст__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    
    # Курсив: *текст* или _текст_ (но не числа как _2)
    # Избегаем замены подстрочных индексов
    text = re.sub(r'(?<![a-zA-Zа-яА-Я0-9])\*([^*\n]+?)\*(?![a-zA-Zа-яА-Я0-9])', r'<i>\1</i>', text)
    text = re.sub(r'(?<![a-zA-Zа-яА-Я0-9])_([^_\n0-9]+?)_(?![a-zA-Zа-яА-Я0-9])', r'<i>\1</i>', text)
    
    # Зачёркнутый: ~~текст~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    
    # Подчёркнутый: <u>текст</u> (уже HTML, но на всякий случай)
    # Добавляем поддержку через двойное подчеркивание для удобства
    
    # Код (моноширинный): `код`
    text = re.sub(r'`([^`]+)`', r'<code style="background: rgba(0,0,0,0.1); padding: 2px 6px; border-radius: 4px; font-family: monospace;">\1</code>', text)
    
    # Убираем экранирование для уже обработанных HTML тегов
    text = text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
    text = text.replace('&lt;i&gt;', '<i>').replace('&lt;/i&gt;', '</i>')
    text = text.replace('&lt;u&gt;', '<u>').replace('&lt;/u&gt;', '</u>')
    text = text.replace('&lt;s&gt;', '<s>').replace('&lt;/s&gt;', '</s>')
    
    return text


def remove_english_words_from_russian(text: str) -> str:
    """
    Удаляет лишние латинские слова из русского текста.
    ЗАЩИЩАЕТ: блоки кода, инлайн-код, технические ответы.
    """
    import re as _re_eng

    # ── 0. Удаляем CJK-символы ─────────────────────────────────────────
    # Только 4-значные \u эскейпы — они всегда корректны в Python regex
    _cjk_re = _re_eng.compile(
        '[\u4e00-\u9fff'
        '\u3400-\u4dbf'
        '\uf900-\ufaff'
        '\u3000-\u303f'
        '\u30a0-\u30ff'
        '\u3040-\u309f'
        '\uac00-\ud7af]+'
    )
    if _cjk_re.search(text):
        text = _cjk_re.sub('', text)
        text = _re_eng.sub(r'  +', ' ', text).strip()
        print("[CJK_FILTER] \u26a0\ufe0f Удалены CJK-символы из ответа")

    # ── 1. Если в тексте есть код — не трогаем ─────────────────────────
    code_keywords = [
        'def ', 'class ', 'import ', 'from ', 'return ', 'FastAPI', 'app =',
        'function ', 'const ', 'let ', 'var ', '#!/', 'SELECT ', 'INSERT ',
        '=> {', '() =>', '.get(', '.post(', '.put(', '.delete(',
        '@app.', '@router.', 'async def', 'await ',
    ]
    has_code_block   = '```' in text
    has_code_content = any(kw in text for kw in code_keywords)

    if has_code_block or has_code_content:
        print("[ENGLISH_FILTER] \u2139\ufe0f Обнаружен код — фильтрация отключена")
        return text

    # ── 2. Считаем кириллицу vs латиницу ───────────────────────────────
    cyrillic_count = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin_count    = sum(1 for c in text if 'a' <= c.lower() <= 'z')

    # Мало кириллицы — технический текст, не трогаем
    if cyrillic_count < 10:
        print("[ENGLISH_FILTER] \u2139\ufe0f Мало кириллицы — пропускаем фильтрацию")
        return text

    # Полностью латинский длинный текст — пробуем перевести
    if latin_count > cyrillic_count and latin_count > 50:
        print("[ENGLISH_FILTER] \u26a0\ufe0f ОБНАРУЖЕН ПОЛНОСТЬЮ АНГЛИЙСКИЙ ТЕКСТ! Переводим...")
        try:
            from deep_translator import GoogleTranslator
            translator = GoogleTranslator(source='en', target='ru')
            max_chunk = 4500
            if len(text) <= max_chunk:
                translated = translator.translate(text)
                print("[ENGLISH_FILTER] \u2713 Текст полностью переведён на русский")
                return translated
            else:
                sentences = text.split('. ')
                translated_parts = []
                current_chunk = ""
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) < max_chunk:
                        current_chunk += sentence + ". "
                    else:
                        if current_chunk:
                            translated_parts.append(translator.translate(current_chunk))
                        current_chunk = sentence + ". "
                if current_chunk:
                    translated_parts.append(translator.translate(current_chunk))
                translated = " ".join(translated_parts)
                print("[ENGLISH_FILTER] \u2713 Большой текст полностью переведён на русский")
                return translated
        except Exception as e:
            print(f"[ENGLISH_FILTER] \u2717 Ошибка перевода: {e}")

    # ── 3. Пословная фильтрация запрещённых латинских слов ──────────────
    if FORBIDDEN_WORDS_DICT and len(FORBIDDEN_WORDS_DICT) > 0:
        replacements = FORBIDDEN_WORDS_DICT
        print(f"[ENGLISH_FILTER] Используется расширенный словарь ({len(replacements)} слов)")
    else:
        replacements = {
            'however': 'однако', 'moreover': 'более того', 'therefore': 'поэтому',
            'essentially': 'по сути', 'basically': 'в основном',
        }
        print(f"[ENGLISH_FILTER] Используется базовый словарь ({len(replacements)} слов)")

    ALLOWED_LATIN = {
        'ai', 'ok', 'api', 'url', 'http', 'https', 'html', 'css', 'js',
        'python', 'java', 'sql', 'gpu', 'cpu', 'ram', 'rom', 'usb', 'hdmi',
        'pdf', 'jpg', 'png', 'gif', 'mp3', 'mp4', 'wifi', 'lan', 'vpn',
        'google', 'apple', 'microsoft', 'samsung', 'huawei', 'xiaomi', 'sony',
        'intel', 'amd', 'nvidia', 'linux', 'windows', 'macos', 'android', 'ios',
        'youtube', 'telegram', 'instagram', 'facebook', 'twitter', 'whatsapp',
        'ollama', 'llama', 'gpt', 'claude', 'openai',
    }

    words = text.split()
    cleaned_words = []
    replaced_count = 0

    for word in words:
        clean_word = ''.join(c for c in word if c.isalnum()).lower()

        if not clean_word:
            cleaned_words.append(word)
            continue

        has_cyrillic = any('\u0400' <= c <= '\u04FF' for c in clean_word)
        has_latin    = any('a' <= c <= 'z' for c in clean_word)

        if not has_latin:
            cleaned_words.append(word)
            continue

        if has_cyrillic and has_latin:
            cleaned_words.append(word)
            continue

        if clean_word in ALLOWED_LATIN:
            cleaned_words.append(word)
            continue

        if clean_word in replacements:
            suffix = ''.join(c for c in word if not c.isalnum())
            cleaned_words.append(replacements[clean_word] + suffix)
            replaced_count += 1
            print(f"[ENGLISH_FILTER] Заменено: '{word}' → '{replacements[clean_word]}'")
        else:
            # ── Защита единиц измерения: +25°C, -10°F, 100km, 500ml и т.п. ──
            # clean_word типа "25c", "100km", "5f" содержит цифры → оставляем
            if any(c.isdigit() for c in clean_word):
                cleaned_words.append(word)
            else:
                # Неизвестное латинское слово — оставляем, не удаляем.
                # Удаление незнакомых слов ломает технические термины, имена,
                # аббревиатуры которых нет в словаре.
                replaced_count += 1
                print(f"[ENGLISH_FILTER] Неизвестное слово оставлено: '{word}'")
                cleaned_words.append(word)

    if replaced_count > 0:
        print(f"[ENGLISH_FILTER] \u2713 Заменено/удалено: {replaced_count}")

    result = ' '.join(cleaned_words)
    result = re.sub(r'  +', ' ', result).strip()
    return result


def check_spelling_and_suggest(text: str, language: str = "russian") -> dict:
    """
    Проверяет орфографию в тексте и предлагает исправления.
    Возвращает словарь с информацией об ошибках и предложениями.
    
    Returns:
    {
        "has_errors": bool,
        "original": str,
        "suggested": str,
        "corrections": list of tuples (wrong_word, suggested_word)
    }
    """
    try:
        from spellchecker import SpellChecker
        
        if language == "russian":
            spell = SpellChecker(language='ru')
        else:
            spell = SpellChecker(language='en')
        
        words = text.split()
        corrections = []
        corrected_words = []
        
        for word in words:
            # Очищаем слово от знаков препинания для проверки
            clean_word = ''.join(char for char in word if char.isalnum())
            
            if not clean_word:
                corrected_words.append(word)
                continue
            
            # Проверяем орфографию
            if clean_word.lower() in spell:
                corrected_words.append(word)
            else:
                # Слово с ошибкой - ищем исправление
                correction = spell.correction(clean_word.lower())
                if correction and correction != clean_word.lower():
                    # Сохраняем регистр оригинала
                    if clean_word[0].isupper():
                        correction = correction.capitalize()
                    
                    # Восстанавливаем знаки препинания
                    corrected_word = word.replace(clean_word, correction)
                    corrected_words.append(corrected_word)
                    corrections.append((clean_word, correction))
                    print(f"[SPELL_CHECK] Найдена ошибка: '{clean_word}' -> '{correction}'")
                else:
                    corrected_words.append(word)
        
        suggested_text = ' '.join(corrected_words)
        
        return {
            "has_errors": len(corrections) > 0,
            "original": text,
            "suggested": suggested_text,
            "corrections": corrections
        }
        
    except ImportError:
        print("[SPELL_CHECK] pyspellchecker не установлен. Установите: pip install pyspellchecker")
        return {
            "has_errors": False,
            "original": text,
            "suggested": text,
            "corrections": []
        }
    except Exception as e:
        print(f"[SPELL_CHECK] Ошибка проверки орфографии: {e}")
        return {
            "has_errors": False,
            "original": text,
            "suggested": text,
            "corrections": []
        }


# -------------------------
# DuckDuckGo Search helper (named google_search for compatibility)
# -------------------------
def translate_to_russian(text: str) -> str:
    """Переводит текст с английского на русский, сохраняя имена и названия"""
    try:
        print(f"[TRANSLATOR] Начинаю перевод текста...")
        print(f"[TRANSLATOR] Длина текста: {len(text)} символов")
        
        # Используем простой API для перевода
        from deep_translator import GoogleTranslator
        
        translator = GoogleTranslator(source='en', target='ru')
        
        # Переводим по частям, если текст большой
        max_chunk = 4500
        if len(text) <= max_chunk:
            translated = translator.translate(text)
        else:
            # Разбиваем на части по предложениям
            sentences = text.split('. ')
            translated_parts = []
            current_chunk = ""
            
            for sentence in sentences:
                if len(current_chunk) + len(sentence) < max_chunk:
                    current_chunk += sentence + ". "
                else:
                    if current_chunk:
                        translated_parts.append(translator.translate(current_chunk))
                    current_chunk = sentence + ". "
            
            if current_chunk:
                translated_parts.append(translator.translate(current_chunk))
            
            translated = " ".join(translated_parts)
        
        print(f"[TRANSLATOR] Перевод завершён успешно")
        return translated
        
    except ImportError:
        print("[TRANSLATOR] deep-translator не установлен. Установите: pip install deep-translator")
        return text
    except Exception as e:
        print(f"[TRANSLATOR] Ошибка перевода: {e}")
        return text

def analyze_query_type(query: str, language: str) -> dict:
    """
    Анализирует тип запроса и определяет категорию + релевантные источники
    
    Возвращает:
    {
        'category': str,  # Категория запроса
        'domains': list,  # Релевантные домены (пустой = все)
        'keywords': list  # Ключевые слова для улучшения поиска
    }
    """
    query_lower = query.lower()

    # 🕐 ДАТА И ВРЕМЯ (приоритет выше погоды)
    datetime_keywords_ru = ['какое число', 'какой день', 'какое сегодня', 'сегодня число',
                            'текущая дата', 'текущее время', 'который час', 'сколько время',
                            'какой год', 'какой месяц', 'какое время', 'дата сегодня', 'день недели']
    datetime_keywords_en = ['what date', 'what day', 'what time', 'current date', 'current time',
                            'today date', "today's date", 'what year', 'what month', 'day of week']
    if language == "russian":
        if any(kw in query_lower for kw in datetime_keywords_ru):
            return {'category': '🕐 Дата и время',
                    'domains': ['time.is', 'timeanddate.com', 'yandex.ru'],
                    'keywords': ['текущая дата', 'сегодня']}
    else:
        if any(kw in query_lower for kw in datetime_keywords_en):
            return {'category': '🕐 Date & Time',
                    'domains': ['time.is', 'timeanddate.com'],
                    'keywords': ['current date', 'today']}

    # 🌦 ПОГОДА
    weather_keywords_ru = ['погода', 'температура', 'градус', 'прогноз', 'осадки', 'дожд', 'снег', 'ветер', 'климат', 'мороз', 'жара', 'солнечно', 'облачно', 'утром', 'днем', 'днём', 'вечером', 'ночью']
    weather_keywords_en = ['weather', 'temperature', 'forecast', 'rain', 'snow', 'wind', 'climate', 'sunny', 'cloudy']
    
    if language == "russian":
        if any(kw in query_lower for kw in weather_keywords_ru):
            return {
                'category': '🌦 Погода',
                'domains': ['weather', 'meteo', 'gismeteo', 'погода', 'yandex.ru/pogoda'],
                'keywords': ['прогноз погоды', 'температура', 'метеосервис']
            }
    else:
        if any(kw in query_lower for kw in weather_keywords_en):
            return {
                'category': '🌦 Weather',
                'domains': ['weather.com', 'accuweather', 'weatherapi', 'meteo'],
                'keywords': ['weather forecast', 'temperature']
            }
    
    # 📱 ТЕХНИКА / ГАДЖЕТЫ
    tech_keywords_ru = ['телефон', 'смартфон', 'компьютер', 'ноутбук', 'планшет', 'айфон', 'iphone', 'samsung', 'характеристик', 'сравни', 'лучше', 'процессор', 'память', 'экран', 'камера', 'батарея', 'гаджет']
    tech_keywords_en = ['phone', 'smartphone', 'computer', 'laptop', 'tablet', 'iphone', 'samsung', 'specs', 'compare', 'better', 'processor', 'memory', 'screen', 'camera', 'battery', 'gadget']
    
    if language == "russian":
        if any(kw in query_lower for kw in tech_keywords_ru):
            return {
                'category': '📱 Техника',
                'domains': ['ixbt', 'overclockers', 'dns-shop', 'citilink', 'mobile-review', 'tech', 'gadget'],
                'keywords': ['обзор', 'характеристики', 'тест', 'сравнение']
            }
    else:
        if any(kw in query_lower for kw in tech_keywords_en):
            return {
                'category': '📱 Tech',
                'domains': ['gsmarena', 'techradar', 'cnet', 'anandtech', 'tomshardware', 'tech', 'review'],
                'keywords': ['review', 'specs', 'comparison', 'test']
            }
    
    # 🍳 КУЛИНАРИЯ
    cooking_keywords_ru = ['рецепт', 'приготов', 'готов', 'блюдо', 'ингредиент', 'выпека', 'варить', 'жарить', 'запека', 'кухня', 'салат', 'суп', 'десерт', 'торт']
    cooking_keywords_en = ['recipe', 'cook', 'dish', 'ingredient', 'bake', 'fry', 'roast', 'kitchen', 'salad', 'soup', 'dessert', 'cake']
    
    if language == "russian":
        if any(kw in query_lower for kw in cooking_keywords_ru):
            return {
                'category': '🍳 Кулинария',
                'domains': ['russianfood', 'edimdoma', 'povar', 'gastronom', 'recipe', 'рецепт'],
                'keywords': ['рецепт с фото', 'как приготовить', 'пошаговый рецепт']
            }
    else:
        if any(kw in query_lower for kw in cooking_keywords_en):
            return {
                'category': '🍳 Cooking',
                'domains': ['allrecipes', 'foodnetwork', 'epicurious', 'recipe', 'cooking'],
                'keywords': ['recipe with photos', 'how to cook', 'step by step']
            }
    
    # 🧠 ОБУЧЕНИЕ / ОБЪЯСНЕНИЕ
    learning_keywords_ru = ['что такое', 'как работает', 'объясни', 'расскажи', 'чем отличается', 'зачем', 'почему', 'определение', 'значение']
    learning_keywords_en = ['what is', 'how does', 'explain', 'tell me', 'difference', 'why', 'definition', 'meaning']
    
    if language == "russian":
        if any(kw in query_lower for kw in learning_keywords_ru):
            return {
                'category': '🧠 Обучение',
                'domains': ['wikipedia', 'wiki', 'habr', 'образование', 'учебный'],
                'keywords': ['определение', 'объяснение', 'что это']
            }
    else:
        if any(kw in query_lower for kw in learning_keywords_en):
            return {
                'category': '🧠 Learning',
                'domains': ['wikipedia', 'wiki', 'education', 'tutorial'],
                'keywords': ['definition', 'explanation', 'what is']
            }
    
    # ⚙ ПРОГРАММИРОВАНИЕ
    programming_keywords = ['код', 'программ', 'python', 'javascript', 'java', 'c++', 'html', 'css', 'api', 'функция', 'метод', 'класс', 'error', 'bug', 'github', 'stackoverflow', 'code', 'script']
    
    if any(kw in query_lower for kw in programming_keywords):
        return {
            'category': '⚙ Программирование',
            'domains': ['stackoverflow', 'github', 'habr', 'docs', 'documentation', 'developer'],
            'keywords': ['documentation', 'example', 'tutorial', 'code']
        }
    
    # 📰 НОВОСТИ / СОБЫТИЯ
    news_keywords_ru = ['новост', 'событ', 'сегодня', 'вчера', 'произошло', 'случилось']
    news_keywords_en = ['news', 'event', 'today', 'yesterday', 'happened', 'occurred']
    
    if language == "russian":
        if any(kw in query_lower for kw in news_keywords_ru):
            return {
                'category': '📰 Новости',
                'domains': ['news', 'новости', 'lenta', 'tass', 'ria', 'rbc'],
                'keywords': ['новости', 'событие', 'последние новости']
            }
    else:
        if any(kw in query_lower for kw in news_keywords_en):
            return {
                'category': '📰 News',
                'domains': ['news', 'bbc', 'cnn', 'reuters', 'nytimes'],
                'keywords': ['latest news', 'breaking news', 'event']
            }
    
    # ❓ ОБЩИЙ ВОПРОС (по умолчанию)
    return {
        'category': '❓ Общий вопрос',
        'domains': [],  # Поиск везде
        'keywords': []
    }


# ═══════════════════════════════════════════════════════════════════
# УМНАЯ СИСТЕМА ОЦЕНКИ И ФИЛЬТРАЦИИ РЕЗУЛЬТАТОВ ПОИСКА
# ═══════════════════════════════════════════════════════════════════

# Домены с высоким доверием
# ═══════════════════════════════════════════════════════════════════
# WHITELIST / BLACKLIST доменов для оценки качества источников
# ═══════════════════════════════════════════════════════════════════

# Устаревший список — сохранён для обратной совместимости с score_result()
TRUSTED_DOMAINS = [
    'wikipedia.org', 'github.com', 'stackoverflow.com', 'habr.com',
    'python.org', 'developer.mozilla.org', 'docs.microsoft.com',
    'tass.ru', 'ria.ru', 'rbc.ru', 'lenta.ru', 'bbc.com', 'reuters.com',
    'ixbt.com', 'gsmarena.com', 'techradar.com', 'cnet.com',
    'weather.com', 'gismeteo.ru', 'timeanddate.com'
]

# ── Whitelist: доверенные домены с рейтингом (чем выше — тем лучше) ──
# Tier 1 (+40): официальная документация, репозитории, первоисточники
# Tier 2 (+25): крупные авторитетные IT-СМИ и форумы
# Tier 3 (+15): известные технические ресурсы и энциклопедии
SOURCE_WHITELIST: dict = {
    # ── Официальная документация и репозитории ──────────────────────
    "github.com":               40,
    "gitlab.com":               35,
    "docs.python.org":          40,
    "python.org":               40,
    "pypi.org":                 35,
    "docs.microsoft.com":       40,
    "learn.microsoft.com":      40,
    "developer.mozilla.org":    40,
    "developer.apple.com":      40,
    "developer.android.com":    40,
    "developer.chrome.com":     40,
    "docs.oracle.com":          40,
    "docs.docker.com":          40,
    "kubernetes.io":            40,
    "golang.org":               40,
    "rust-lang.org":            40,
    "nodejs.org":               40,
    "reactjs.org":              38,
    "vuejs.org":                38,
    "angular.io":               38,
    "djangoproject.com":        38,
    "flask.palletsprojects.com":38,
    "pytorch.org":              38,
    "tensorflow.org":           38,
    "arxiv.org":                38,
    "openai.com":               35,
    "anthropic.com":            35,
    "huggingface.co":           35,
    "linux.die.net":            35,
    "kernel.org":               38,
    "gnu.org":                  35,
    "postgresql.org":           38,
    "mysql.com":                38,
    "redis.io":                 38,
    "mongodb.com":              35,
    # ── Авторитетные IT-СМИ и форумы ────────────────────────────────
    "stackoverflow.com":        38,
    "superuser.com":            30,
    "serverfault.com":          30,
    "askubuntu.com":            30,
    "unix.stackexchange.com":   30,
    "security.stackexchange.com":30,
    "habr.com":                 30,
    "techradar.com":            25,
    "arstechnica.com":          28,
    "wired.com":                25,
    "theverge.com":             25,
    "engadget.com":             22,
    "zdnet.com":                25,
    "tomshardware.com":         25,
    "anandtech.com":            28,
    "ixbt.com":                 25,
    "3dnews.ru":                22,
    "4pda.ru":                  18,
    "cnews.ru":                 20,
    "vc.ru":                    18,
    "tproger.ru":               20,
    "overclockers.ru":          18,
    # ── Энциклопедии и справочники ───────────────────────────────────
    "wikipedia.org":            25,
    "wikimedia.org":            20,
    "britannica.com":           25,
    "cnet.com":                 22,
    "pcmag.com":                22,
    "gsmarena.com":             25,
    "phonearena.com":           20,
    # ── Надёжные новостные агентства ─────────────────────────────────
    "bbc.com":                  25,
    "bbc.co.uk":                25,
    "reuters.com":              28,
    "bloomberg.com":            28,
    "tass.ru":                  22,
    "ria.ru":                   20,
    "rbc.ru":                   22,
    "kommersant.ru":            22,
    "interfax.ru":              22,
}

# ── Blacklist: агрегаторы, SEO-помойки, ненадёжные сайты ────────────
# Значение — штраф, вычитаемый из итогового скора
SOURCE_BLACKLIST: dict = {
    # Контент-фермы и агрегаторы
    "buzzfeed.com":         -60,
    "listverse.com":        -50,
    "brightside.me":        -50,
    "boredpanda.com":       -50,
    "lifehack.org":         -40,
    "viral":                -40,
    # SEO-дорвеи и маркетинговые сайты
    "seoaudit":             -50,
    "seopult":              -50,
    "rankmath.com":         -40,
    "top10":                -30,
    "topten":               -30,
    "bestof":               -25,
    "compare99":            -40,
    "capterra.com":         -15,
    "g2.com":               -15,
    "getapp.com":           -20,
    "softwaresuggest.com":  -30,
    # Жёлтая пресса и ненадёжные источники
    "dailymail.co.uk":      -40,
    "thesun.co.uk":         -40,
    "infowars.com":         -80,
    "naturalnews.com":      -80,
    # Отзывники и агрегаторы мнений
    "trustpilot.com":       -20,
    "sitejabber.com":       -25,
}

# Слова-маркеры запросов на актуальность
FRESHNESS_KEYWORDS_RU = [
    'последний', 'последняя', 'последнее', 'последние',
    'сейчас', 'текущий', 'текущая', 'актуальный', 'актуально',
    'свежий', 'новый', 'новая', 'новое', 'сегодня', 'недавно',
    'только что', '2024', '2025', '2026'
]
FRESHNESS_KEYWORDS_EN = [
    'latest', 'current', 'now', 'today', 'recent', 'new',
    'updated', 'fresh', 'modern', '2024', '2025', '2026'
]


def needs_freshness_check(query: str) -> bool:
    """Определяет, нужна ли проверка актуальности для запроса."""
    q = query.lower()
    return any(kw in q for kw in FRESHNESS_KEYWORDS_RU + FRESHNESS_KEYWORDS_EN)


def extract_year_from_text(text: str) -> int:
    """Извлекает наиболее свежий год из текста. Возвращает 0 если не найдено."""
    import re
    years = re.findall(r'\b(20[12][0-9])\b', text)
    if years:
        return max(int(y) for y in years)
    return 0


def score_result(result: dict, query: str, freshness_needed: bool = False) -> float:
    """
    Оценивает релевантность результата поиска по нескольким критериям.
    Возвращает float — чем выше, тем лучше.
    
    Критерии:
    - Совпадение ключевых слов запроса в заголовке/описании
    - Домен сайта (трастовые домены получают бонус)
    - Наличие актуальных дат (если запрос требует свежести)
    - Длина описания (короткие описания — меньше информации)
    """
    import re
    
    title = result.get('title', '').lower()
    body = result.get('body', '').lower()
    link = result.get('href', '').lower()
    full_text = title + ' ' + body
    
    score = 0.0
    
    # ── 1. Совпадение ключевых слов ──
    # Очищаем запрос от стоп-слов
    stop_words = {'и', 'в', 'на', 'с', 'по', 'для', 'что', 'как', 'где',
                  'the', 'a', 'an', 'of', 'in', 'for', 'to', 'is', 'how'}
    keywords = [w for w in re.split(r'[\s,?!.]+', query.lower()) 
                if len(w) > 2 and w not in stop_words]
    
    keyword_hits = sum(1 for kw in keywords if kw in full_text)
    if keywords:
        keyword_ratio = keyword_hits / len(keywords)
        score += keyword_ratio * 40  # Макс 40 баллов за ключевые слова
    
    # Бонус за совпадение ключевых слов в заголовке (более ценно)
    title_hits = sum(1 for kw in keywords if kw in title)
    score += title_hits * 5  # +5 за каждое слово в заголовке
    
    # ── 2. Трастовость домена ──
    domain_bonus = sum(10 for trusted in TRUSTED_DOMAINS if trusted in link)
    score += min(domain_bonus, 15)  # Макс 15 баллов за домен
    
    # ── 3. Длина описания (больше текста = больше информации) ──
    body_length = len(result.get('body', ''))
    if body_length > 200:
        score += 10
    elif body_length > 100:
        score += 5
    elif body_length < 30:
        score -= 10  # Штраф за слишком короткое описание
    
    # ── 4. Проверка актуальности ──
    if freshness_needed:
        import datetime
        current_year = datetime.datetime.now().year
        year_in_text = extract_year_from_text(full_text + link)
        
        if year_in_text == current_year:
            score += 20  # Текущий год — отличный бонус
        elif year_in_text == current_year - 1:
            score += 10  # Прошлый год — небольшой бонус
        elif year_in_text > 0 and year_in_text < current_year - 2:
            score -= 20  # Старые страницы — штраф при freshness-запросе
    
    # ── 5. Штраф за нерелевантный контент ──
    # Если ни одного ключевого слова не совпало — штраф
    if keyword_hits == 0 and keywords:
        score -= 15
    
    return score


def filter_and_rank_results(results: list, query: str, min_score: float = -10.0) -> list:
    """
    Фильтрует и сортирует результаты поиска по скору релевантности.
    Отбрасывает явно нерелевантные страницы.
    """
    freshness = needs_freshness_check(query)
    
    scored = []
    for r in results:
        s = score_result(r, query, freshness)
        scored.append((s, r))
        print(f"[SMART_SEARCH] Скор {s:.1f} | {r.get('title', '')[:50]}")
    
    # Сортируем по убыванию скора
    scored.sort(key=lambda x: x[0], reverse=True)
    
    # Отбрасываем слишком нерелевантные
    filtered = [(s, r) for s, r in scored if s >= min_score]
    
    print(f"[SMART_SEARCH] Из {len(results)} результатов осталось {len(filtered)} после фильтрации")
    return [r for _, r in filtered]


def detect_contradiction_or_staleness(page_contents: list, query: str) -> bool:
    """
    Проверяет, противоречат ли страницы друг другу или содержат устаревшие данные.
    Если да — нужен повторный поиск.
    """
    import re, datetime
    
    if not page_contents:
        return False
    
    # Проверка 1: Устаревшие данные при freshness-запросе
    if needs_freshness_check(query):
        current_year = datetime.datetime.now().year
        old_count = 0
        for page in page_contents:
            text = page.get('content', '')
            year = extract_year_from_text(text)
            if year > 0 and year < current_year - 1:
                old_count += 1
        
        # Если больше половины страниц с устаревшими данными
        if old_count > len(page_contents) / 2:
            print(f"[SMART_SEARCH] ⚠️ Обнаружены устаревшие данные в {old_count}/{len(page_contents)} страницах")
            return True
    
    # Проверка 2: Противоречивые версии (например разные версии ПО)
    # Ищем числа вида X.Y.Z (версии) или X.Y (версии/годы)
    version_pattern = re.compile(r'\b(\d+\.\d+(?:\.\d+)?)\b')
    all_versions = []
    for page in page_contents:
        text = page.get('content', '')
        versions = version_pattern.findall(text)
        all_versions.extend(versions)
    
    if all_versions:
        unique_versions = set(all_versions)
        # Если слишком много разных версий — возможно противоречие
        if len(unique_versions) > 5 and needs_freshness_check(query):
            print(f"[SMART_SEARCH] ⚠️ Противоречивые версии: {list(unique_versions)[:5]}")
            return True
    
    return False


# ═══════════════════════════════════════════════════════════════════
# ФИЛЬТР РЕЛЕВАНТНОСТИ СТРАНИЦ (is_relevant_page + score_page_content)
# Применяется ПЕРЕД передачей текста страницы модели.
# ═══════════════════════════════════════════════════════════════════

# Тематические ключевые слова — платформы и ОС
TOPIC_PLATFORM_KEYWORDS = [
    # Мобильные
    'ios', 'android', 'iphone', 'ipad', 'samsung', 'pixel', 'huawei',
    # ПК / ОС
    'windows', 'macos', 'linux', 'ubuntu', 'debian', 'fedora',
    # Браузеры
    'chrome', 'firefox', 'safari', 'edge', 'opera',
    # Облако/сервисы
    'google', 'apple', 'microsoft', 'amazon', 'yandex',
]

# Маркеры конкретных фактов: версии, даты, номера
import re as _re
_FACT_PATTERNS = [
    _re.compile(r'\b\d+\.\d+(?:\.\d+)*\b'),          # версии: 17.4.1, 3.12
    _re.compile(r'\b(19|20)\d{2}\b'),                    # годы: 2023, 2025
    _re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b'), # даты: 12.05.2024
    _re.compile(r'\b(?:january|february|march|april|may|june|july|august|'
                r'september|october|november|december|'
                r'январ|феврал|март|апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)'
                r'\w*\b', _re.IGNORECASE),
    _re.compile(r'\bv?\d+(?:\.\d+){1,3}\b'),           # v1.2.3
    _re.compile(r'\b(?:обновлен|released|вышел|launch|update|релиз)\w*\b', _re.IGNORECASE),
]


def score_page_content(query: str, page_text: str) -> dict:
    """
    Оценивает релевантность текста страницы по трём критериям.
    
    Возвращает словарь:
    {
        "total_score":      float,   # суммарный балл (0-100)
        "keyword_score":    float,   # совпадение ключевых слов (0-40)
        "topic_score":      float,   # упоминание тем/платформ  (0-30)
        "facts_score":      float,   # наличие дат/версий/фактов (0-30)
        "keyword_hits":     int,
        "topic_hits":       list,
        "facts_count":      int,
    }
    """
    stop_words = {
        "и", "в", "на", "с", "по", "для", "что", "как", "где", "это",
        "the", "a", "an", "of", "in", "for", "to", "is", "are", "was",
    }

    # --- Ключевые слова запроса ---
    raw_keywords = _re.split(r"[\s,?!.;:]+", query.lower())
    keywords = [w for w in raw_keywords if len(w) > 2 and w not in stop_words]

    page_lower = page_text.lower()

    keyword_hits = sum(1 for kw in keywords if kw in page_lower)
    if keywords:
        keyword_ratio = keyword_hits / len(keywords)
    else:
        keyword_ratio = 1.0
    keyword_score = round(keyword_ratio * 40, 2)   # макс 40

    # --- Тематика / платформы ---
    # Проверяем запрос И страницу: если тема есть в запросе, ищем её на странице
    query_has_platform = [p for p in TOPIC_PLATFORM_KEYWORDS if p in query.lower()]
    topic_hits = []
    if query_has_platform:
        # Запрос специфичен — ищем только эти платформы
        topic_hits = [p for p in query_has_platform if p in page_lower]
        topic_score = min(len(topic_hits) / max(len(query_has_platform), 1), 1.0) * 30
    else:
        # Запрос общий — любая платформа/тема добавляет балл
        topic_hits = [p for p in TOPIC_PLATFORM_KEYWORDS if p in page_lower]
        topic_score = min(len(topic_hits) * 5, 30)   # +5 за каждую, макс 30
    topic_score = round(topic_score, 2)

    # --- Конкретные факты (версии, даты, названия) ---
    facts_count = 0
    for pattern in _FACT_PATTERNS:
        matches = pattern.findall(page_lower)
        facts_count += len(matches)
    # Нелинейный скор: первые 3 факта дают больше всего очков
    if facts_count == 0:
        facts_score = 0.0
    elif facts_count <= 3:
        facts_score = facts_count * 7.0        # 7/14/21
    elif facts_count <= 10:
        facts_score = 21 + (facts_count - 3) * 1.0  # до 28
    else:
        facts_score = 30.0                     # насыщение
    facts_score = round(min(facts_score, 30), 2)

    total_score = keyword_score + topic_score + facts_score

    return {
        "total_score":   round(total_score, 2),
        "keyword_score": keyword_score,
        "topic_score":   topic_score,
        "facts_score":   facts_score,
        "keyword_hits":  keyword_hits,
        "topic_hits":    topic_hits,
        "facts_count":   facts_count,
    }


def is_relevant_page(query: str, page_text: str, url: str = "",
                     min_total: float = 20.0,
                     min_keyword_ratio: float = 0.20) -> tuple:
    """
    Строгий фильтр релевантности страницы перед передачей текста модели.

    Проверяет 5 условий (все обязательны):
    1. Длина текста        — минимум 200 символов.
    2. URL-фильтр          — отклоняет соцсети, магазины, рекламу, трекеры.
    3. Ключевые слова      — ≥ min_keyword_ratio ключевых слов запроса в тексте.
    4. Тематика            — если запрос содержит платформу (iOS / Android /
                             Windows…), она должна присутствовать на странице.
    5. Суммарный балл      — score_page_content() ≥ min_total.

    Аргументы:
        query:             запрос пользователя
        page_text:         текстовое содержимое страницы
        url:               URL страницы (для URL-фильтра; можно передать "")
        min_total:         порог суммарного балла (по умолч. 20)
        min_keyword_ratio: доля ключевых слов, которая должна совпасть (0.20)

    Возвращает (bool, dict_with_scores, str_reason).
    """
    # ── Проверка 1: минимальная длина текста ────────────────────────
    if not page_text or len(page_text) < 200:
        return False, {}, f"Текст слишком короткий ({len(page_text or '')} символов, нужно ≥200)"

    # ── Проверка 2: URL-фильтр (соцсети, магазины, реклама) ─────────
    # Домены, которые гарантированно не содержат релевантного контента
    _URL_BLOCKLIST = (
        # Социальные сети
        "facebook.com", "fb.com", "instagram.com", "twitter.com", "x.com",
        "tiktok.com", "vk.com", "ok.ru", "pinterest.com", "tumblr.com",
        "linkedin.com", "snapchat.com", "telegram.org", "t.me",
        # Видеохостинги (текста нет)
        "youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "rutube.ru",
        # Интернет-магазины
        "amazon.com", "amazon.co.uk", "ebay.com", "aliexpress.com",
        "ozon.ru", "wildberries.ru", "avito.ru", "market.yandex.ru",
        "etsy.com", "walmart.com", "bestbuy.com", "newegg.com",
        # Маркетплейсы приложений
        "play.google.com", "apps.apple.com", "microsoft.com/store",
        # Рекламные и трекинговые сети
        "doubleclick.net", "googlesyndication.com", "googletagmanager.com",
        "analytics.google.com", "yandex.ru/adv", "ads.google.com",
        # Агрегаторы цен и отзывов без контента
        "pricespy.com", "price.ru", "hotline.ua", "rozetka.ua",
        # Паблики / форумы без факто-ориентированного контента
        "reddit.com", "quora.com",          # мнения ≠ факты (можно снять)
        "yahoo.com/answers",
    )
    url_lower = (url or "").lower()
    if url_lower:
        for blocked in _URL_BLOCKLIST:
            if blocked in url_lower:
                return (False, {},
                        f"Заблокированный домен: {blocked}")

    # ── Считаем скоры через score_page_content() ────────────────────
    scores = score_page_content(query, page_text)

    stop_words = {
        "и", "в", "на", "с", "по", "для", "что", "как", "где", "это",
        "the", "a", "an", "of", "in", "for", "to", "is", "are", "was",
    }
    raw_keywords = _re.split(r"[\s,?!.;:]+", query.lower())
    keywords = [w for w in raw_keywords if len(w) > 2 and w not in stop_words]

    # ── Проверка 3: ключевые слова ───────────────────────────────────
    if keywords:
        actual_ratio = scores["keyword_hits"] / len(keywords)
        if actual_ratio < min_keyword_ratio:
            return (False, scores,
                    f"Мало ключевых слов запроса: "
                    f"{scores['keyword_hits']}/{len(keywords)} "
                    f"({actual_ratio:.0%} < {min_keyword_ratio:.0%})")

    # ── Проверка 4: тематика (платформа в запросе → нужна на странице) ─
    query_platforms = [p for p in TOPIC_PLATFORM_KEYWORDS if p in query.lower()]
    if query_platforms and not scores["topic_hits"]:
        return (False, scores,
                f"Запрос о платформах {query_platforms}, "
                f"но они отсутствуют на странице")

    # ── Проверка 5: суммарный балл ───────────────────────────────────
    if scores["total_score"] < min_total:
        return (False, scores,
                f"Низкий суммарный балл: "
                f"{scores['total_score']:.1f} < {min_total}")

    return True, scores, "OK"


def refine_search_query(original_query: str, attempt: int = 1) -> str:
    """
    Генерирует уточнённый поисковый запрос для повторного поиска.
    attempt=1 → добавляем год; attempt=2 → более конкретная формулировка.
    """
    import datetime
    year = datetime.datetime.now().year

    if attempt == 1:
        # Добавляем текущий год для более актуальных результатов
        return f"{original_query} {year}"
    else:
        # Упрощаем запрос до ключевых слов + добавляем "официальный" / "обзор"
        stop_words = {
            "и", "в", "на", "с", "по", "для", "что", "как", "где",
            "the", "a", "an", "of", "in", "for", "to",
        }
        raw = _re.split(r"[\s,?!.;:]+", original_query.lower())
        keywords = [w for w in raw if len(w) > 3 and w not in stop_words]
        core = " ".join(keywords[:5])
        suffix = "официально обзор" if any(c in original_query for c in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя") else "official review"
        return f"{core} {suffix} {year}"


def google_search(query: str, num_results: int = 5, region: str = "wt-wt", language: str = "russian"):
    """Поиск через DuckDuckGo API (ddgs) с умной фильтрацией по типу запроса"""
    print(f"[DUCKDUCKGO_SEARCH] Запуск поиска...")
    print(f"[DUCKDUCKGO_SEARCH] Запрос: {query}")
    print(f"[DUCKDUCKGO_SEARCH] Регион: {region}")
    print(f"[DUCKDUCKGO_SEARCH] Количество результатов: {num_results}")
    
    # 🔍 АНАЛИЗ ТИПА ЗАПРОСА
    query_analysis = analyze_query_type(query, language)
    print(f"[DUCKDUCKGO_SEARCH] 📊 Категория запроса: {query_analysis['category']}")
    print(f"[DUCKDUCKGO_SEARCH] 🎯 Релевантные домены: {query_analysis['domains']}")
    
    # Улучшаем запрос ключевыми словами если они есть
    enhanced_query = query
    if query_analysis['keywords']:
        enhanced_query = f"{query} {' '.join(query_analysis['keywords'][:2])}"
        print(f"[DUCKDUCKGO_SEARCH] ✨ Улучшенный запрос: {enhanced_query}")

    try:
        # ddgs is optional dependency: pip install ddgs
        from ddgs import DDGS

        print(f"[DUCKDUCKGO_SEARCH] Отправка запроса...")
        with DDGS() as ddgs:
            # Получаем больше результатов для фильтрации
            raw_results = list(ddgs.text(enhanced_query, region=region, max_results=num_results * 3))

        print(f"[DUCKDUCKGO_SEARCH] Получено сырых результатов: {len(raw_results)}")
        
        # 🎯 ШАГ 1: ДОМЕННАЯ ФИЛЬТРАЦИЯ (по категории запроса)
        domain_filtered = []
        if query_analysis['domains']:
            for result in raw_results:
                link = result.get('href', '').lower()
                if any(domain in link for domain in query_analysis['domains']):
                    domain_filtered.append(result)
            
            # Если мало доменных результатов — добавляем из всех
            if len(domain_filtered) < max(2, num_results // 2):
                domain_filtered = raw_results
        else:
            domain_filtered = raw_results
        
        # 🎯 ШАГ 2: УМНЫЙ СКОРИНГ И РАНЖИРОВАНИЕ
        print(f"[DUCKDUCKGO_SEARCH] 📊 Запускаю скоринг {len(domain_filtered)} результатов...")
        ranked_results = filter_and_rank_results(domain_filtered, query)
        
        # Берём топ N результатов
        results = ranked_results[:num_results]
        
        # Если после фильтрации совсем мало — берём из всех сырых
        if len(results) < 2:
            print(f"[DUCKDUCKGO_SEARCH] ⚠️ Мало результатов после скоринга, берём всё...")
            results = raw_results[:num_results]
        
        print(f"[DUCKDUCKGO_SEARCH] ✅ Итого результатов после ранжирования: {len(results)}")

        if not results:
            print(f"[DUCKDUCKGO_SEARCH] Нет результатов поиска")
            return "Ничего не найдено по вашему запросу."

        search_results = []
        for i, result in enumerate(results, 1):
            title = result.get('title', 'Без заголовка')
            body = result.get('body', 'Нет описания')
            link = result.get('href', '')
            search_results.append(f"[Результат {i}]\nЗаголовок: {title}\nОписание: {body}\nСсылка: {link}")
            print(f"[DUCKDUCKGO_SEARCH] Результат {i}: {title[:50]}...")

        final_results = "\n\n".join(search_results)
        print(f"[DUCKDUCKGO_SEARCH] Поиск завершён успешно. Длина результатов: {len(final_results)} символов")
        print(f"[DUCKDUCKGO_SEARCH] 📊 Итоговая статистика: категория={query_analysis['category']}, результатов={len(results)}")
        return final_results

    except ImportError:
        # FALLBACK: Используем простой веб-скрейпинг DuckDuckGo HTML
        print(f"[DUCKDUCKGO_SEARCH] ⚠️ Библиотека ddgs не установлена, используем fallback...")
        try:
            return fallback_web_search(enhanced_query, num_results, language)
        except Exception as fallback_error:
            error_msg = f"⚠️ Установите библиотеку ddgs: pip install ddgs\nОшибка fallback: {fallback_error}"
            print(f"[DUCKDUCKGO_SEARCH] {error_msg}")
            return error_msg
    except Exception as e:
        error_msg = f"⚠️ Ошибка поиска: {e}"
        print(f"[DUCKDUCKGO_SEARCH] {error_msg}")
        return error_msg

def fetch_page_content(url: str, max_chars: int = 5000) -> str:
    """
    Загружает и извлекает текстовое содержимое веб-страницы
    
    Args:
        url: URL страницы для загрузки
        max_chars: Максимальное количество символов для возврата
    
    Returns:
        Текстовое содержимое страницы или сообщение об ошибке
    """
    try:
        print(f"[FETCH_PAGE] Загрузка страницы: {url[:50]}...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Используем BeautifulSoup для извлечения текста
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Удаляем скрипты и стили
            for script in soup(['script', 'style', 'nav', 'header', 'footer']):
                script.decompose()
            
            # Извлекаем текст
            text = soup.get_text(separator=' ', strip=True)
            
            # Очищаем от множественных пробелов
            import re
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Ограничиваем размер
            if len(text) > max_chars:
                text = text[:max_chars] + "..."
            
            print(f"[FETCH_PAGE] ✓ Загружено {len(text)} символов")
            return text
            
        except ImportError:
            # Если BeautifulSoup не установлен, используем простую регулярку
            import re
            # Удаляем HTML теги
            text = re.sub(r'<[^>]+>', '', response.text)
            # Очищаем от множественных пробелов
            text = re.sub(r'\s+', ' ', text).strip()
            # Ограничиваем размер
            if len(text) > max_chars:
                text = text[:max_chars] + "..."
            print(f"[FETCH_PAGE] ✓ Загружено {len(text)} символов (без BS4)")
            return text
            
    except Exception as e:
        print(f"[FETCH_PAGE] ✗ Ошибка загрузки {url}: {e}")
        return f"[Ошибка загрузки страницы: {str(e)[:100]}]"

# ═══════════════════════════════════════════════════════════════════
# ПРОВЕРКА СВЕЖЕСТИ И ФАКТОВ ПЕРЕД ГЕНЕРАЦИЕЙ ОТВЕТА
# ═══════════════════════════════════════════════════════════════════

def extract_year(text: str) -> int:
    """
    Извлекает наиболее свежий год из текста страницы или метаданных.
    Ищет как явные годы (2023), так и даты в заголовках HTTP/HTML.

    Возвращает год (int) или 0 если не найдено.
    """
    import re, datetime

    # 1. Ищем год в формате мета-тега или HTTP-заголовка:
    #    <meta ... content="2024-05-12" ...>  или  Last-Modified: 2024
    meta_match = re.search(
        r'(?:content|datetime|date|published|modified|last.modified)["\s:=]+(\d{4})',
        text, re.IGNORECASE
    )
    if meta_match:
        y = int(meta_match.group(1))
        current = datetime.datetime.now().year
        if 2000 <= y <= current:
            return y

    # 2. Ищем даты в тексте: «15 мая 2024», «May 15, 2024», «2024-05-15»
    date_patterns = [
        r'\b(20[12]\d)[.\-/]\d{1,2}[.\-/]\d{1,2}\b',   # 2024-05-15
        r'\b\d{1,2}[.\-/]\d{1,2}[.\-/](20[12]\d)\b',   # 15.05.2024
        r'\b(?:january|february|march|april|may|june|july|august|'
        r'september|october|november|december|'
        r'январ\w*|феврал\w*|март\w*|апрел\w*|май|июн\w*|июл\w*|'
        r'август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)'
        r'\s+\d{1,2}[,\s]+(20[12]\d)\b',                # May 15, 2024
        r'\b\d{1,2}\s+(?:january|february|march|april|may|june|july|august|'
        r'september|october|november|december|'
        r'январ\w*|феврал\w*|март\w*|апрел\w*|май|июн\w*|июл\w*|'
        r'август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)'
        r'\s+(20[12]\d)\b',                              # 15 мая 2024
    ]
    years_found = []
    for pat in date_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            # Группа с годом — последняя захватывающая группа
            for g in reversed(m.groups()):
                if g and re.fullmatch(r'20[12]\d', g):
                    years_found.append(int(g))
                    break

    # 3. Запасной вариант — любое четырёхзначное число 2010-текущий год
    fallback = re.findall(r'\b(20[12]\d)\b', text)
    years_found.extend(int(y) for y in fallback)

    if years_found:
        current_year = datetime.datetime.now().year
        valid = [y for y in years_found if 2000 <= y <= current_year]
        if valid:
            return max(valid)

    return 0


def has_facts(text: str) -> bool:
    """
    Проверяет, содержит ли текст конкретные факты:
    версии ПО, даты, числовые данные, названия функций/релизов.

    Возвращает True если найдено ≥ 2 различных фактических паттернов.
    """
    import re

    fact_patterns = [
        re.compile(r'\b\d+\.\d+(?:\.\d+)*\b'),              # версии: 3.12, 17.4.1
        re.compile(r'\bv?\d+(?:\.\d+){1,3}\b'),             # v1.2.3
        re.compile(r'\b(19|20)\d{2}\b'),                     # годы: 2023
        re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b'),  # даты: 12.05.2024
        re.compile(                                           # месяцы
            r'\b(?:january|february|march|april|may|june|july|august|'
            r'september|october|november|december|'
            r'январ|феврал|март|апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)'
            r'\w*\b', re.IGNORECASE
        ),
        re.compile(                                           # ключевые слова релизов
            r'\b(?:released?|вышел|вышла|обновлен\w*|запущен\w*|launch\w*|'
            r'релиз|update|changelog|новая\s+версия|new\s+version)\b',
            re.IGNORECASE
        ),
        re.compile(r'\b\d+\s*(?:мб|гб|mb|gb|мс|ms|fps|rpm|ghz|ггц|кб|kb)\b',
                   re.IGNORECASE),                           # технические числа
    ]

    hits = 0
    for pattern in fact_patterns:
        if pattern.search(text):
            hits += 1
        if hits >= 2:
            return True

    return False


# ═══════════════════════════════════════════════════════════════════
# ПАЙПЛАЙН КАЧЕСТВА: свежесть, факты, версии, защита от галлюцинаций
# ═══════════════════════════════════════════════════════════════════

# Ключевые слова, означающие «нужна актуальная информация»
_FRESHNESS_TRIGGER_WORDS = [
    # Русские
    "последняя", "последний", "последнее", "последние",
    "сейчас", "актуальная", "актуальный", "актуальное", "актуальные",
    "свежая", "свежий", "свежее", "свежие",
    "текущая", "текущий", "текущее", "текущие",
    "новая версия", "новый релиз", "вышла", "вышел", "вышло",
    # Английские
    "latest", "current", "newest", "recent", "now",
    "latest version", "current version", "new release",
]


def is_fresh_page(text: str, query: str) -> tuple:
    """
    Проверяет, является ли страница достаточно свежей для данного запроса.

    Логика:
    - Если запрос содержит слова актуальности (latest, последняя и т.д.),
      страница должна содержать год >= current_year - 1.
    - Если год не найден вообще → страница считается свежей (неизвестно).
    - Если запрос не требует актуальности → всегда True.

    Возвращает (is_ok: bool, found_year: int, reason: str).
    """
    import datetime

    query_lower = query.lower()
    needs_fresh = any(kw in query_lower for kw in _FRESHNESS_TRIGGER_WORDS)

    if not needs_fresh:
        return True, 0, "freshness_not_required"

    current_year = datetime.datetime.now().year
    found_year = extract_year(text)

    if found_year == 0:
        # Год не найден → не отклоняем (нет доказательства устарелости)
        return True, 0, "year_not_found"

    threshold = current_year - 1
    if found_year >= threshold:
        return True, found_year, f"fresh ({found_year} >= {threshold})"

    return False, found_year, f"stale: {found_year} < {threshold}"


def has_real_facts(text: str) -> tuple:
    """
    Проверяет, содержит ли текст конкретные факты перед передачей модели.

    Проверяет наличие:
    1. Версий ПО (X.Y, X.Y.Z, vX.Y)
    2. Дат (числовых или словесных)
    3. Ключевых слов релизов / функций
    4. Технических чисел с единицами измерения

    Требуется минимум 2 разных типа фактов.

    Возвращает (has_facts: bool, facts_found: list[str], count: int).
    """
    import re

    checks = [
        ("version_dotted",  re.compile(r'\b\d+\.\d+(?:\.\d+)*\b')),
        ("version_v_prefix", re.compile(r'\bv\d+(?:\.\d+){1,3}\b', re.IGNORECASE)),
        ("year_4digit",     re.compile(r'\b(19|20)\d{2}\b')),
        ("date_numeric",    re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b')),
        ("month_word",      re.compile(
            r'\b(?:january|february|march|april|may|june|july|august|'
            r'september|october|november|december|'
            r'январ|феврал|март|апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)'
            r'\w*\b', re.IGNORECASE)),
        ("release_keyword", re.compile(
            r'\b(?:released?|вышел|вышла|обновлен\w*|запущен\w*|launch\w*|'
            r'релиз|changelog|новая\s+версия|new\s+version|feature|функция)\b',
            re.IGNORECASE)),
        ("tech_measurement", re.compile(
            r'\b\d+\s*(?:мб|гб|тб|mb|gb|tb|мс|ms|fps|rpm|ghz|ггц|кб|kb|px|dp)\b',
            re.IGNORECASE)),
    ]

    found_types = []
    for name, pattern in checks:
        if pattern.search(text):
            found_types.append(name)

    ok = len(found_types) >= 2
    return ok, found_types, len(found_types)


def filter_pages(pages: list, query: str, max_age_years: int = 1) -> list:
    """
    Главный фильтр качества страниц перед передачей текста модели.

    Применяет 4 последовательных проверки:
    1) is_relevant_page(query, text, url) — URL-блокировка соцсетей/магазинов/рекламы,
       ключевые слова, тематика платформы, суммарный балл.
       Страницы, не прошедшие этот фильтр, НЕ передаются модели.
    2) is_fresh_page — отклоняет устаревшие страницы при freshness-запросах.
    3) has_real_facts — отклоняет страницы без конкретных фактов (версии, даты…).

    Аргументы:
        pages:         список dict с ключами 'content', 'url'
        query:         исходный запрос пользователя
        max_age_years: порог устарелости (по умолч. 1 год)

    Возвращает отфильтрованный список страниц.
    Страницы, не прошедшие любой из фильтров, гарантированно исключаются.
    """
    accepted = []

    for page in pages:
        text = page.get('content', '')
        url  = page.get('url', '')
        label = url[:70] or '<без url>'

        # ── Проверка 1: релевантность + URL-блокировка ────────────
        rel_ok, rel_scores, rel_reason = is_relevant_page(query, text, url)
        if not rel_ok:
            print(f"[FILTER_PAGES] ❌ Нерелевантна ({rel_reason}): {label}")
            continue

        # ── Проверка 2: свежесть ──────────────────────────────────
        fresh_ok, found_year, fresh_reason = is_fresh_page(text, query)
        if not fresh_ok:
            print(f"[FILTER_PAGES] ❌ Устаревшая ({found_year}): {label}")
            continue

        # ── Проверка 3: наличие фактов ────────────────────────────
        facts_ok, fact_types, fact_count = has_real_facts(text)
        if not facts_ok:
            print(f"[FILTER_PAGES] ❌ Мало фактов ({fact_count}/2): {label}")
            continue

        print(
            f"[FILTER_PAGES] ✅ Принята | "
            f"score={rel_scores.get('total_score', 0):.0f} "
            f"year={found_year or '?'} "
            f"facts={fact_count}: {url[:65]}"
        )
        accepted.append(page)

    print(f"[FILTER_PAGES] Итого: {len(accepted)}/{len(pages)} страниц прошли все фильтры")
    return accepted


def retry_search_if_needed(
    page_contents: list,
    query: str,
    num_results: int = 5,
    region: str = "wt-wt",
    language: str = "russian",
    max_pages: int = 3,
    max_attempts: int = 2,
    min_good_sources: int = 2,
) -> list:
    """
    Если отфильтрованных источников меньше min_good_sources,
    автоматически повторяет поиск с уточнёнными запросами.

    При повторном поиске к запросу добавляются:
    «latest version», «release», текущий год — чтобы получить свежие страницы.

    Возвращает дополненный список страниц.
    """
    import re, datetime

    if len(page_contents) >= min_good_sources:
        return page_contents

    current_year = datetime.datetime.now().year
    existing_urls = {p['url'] for p in page_contents}

    for attempt in range(1, max_attempts + 1):
        if len(page_contents) >= min_good_sources:
            break

        # Уточняем запрос: добавляем свежесть-маркеры
        if attempt == 1:
            retry_query = f"{query} latest version release {current_year}"
        else:
            # Второй вариант: упрощаем запрос до ключевых слов + год
            stop = {'и','в','на','с','по','для','что','как','где',
                    'the','a','an','of','in','for','to'}
            words = [w for w in re.split(r'[\s,?!.;:]+', query.lower())
                     if len(w) > 3 and w not in stop]
            retry_query = f"{' '.join(words[:5])} release changelog {current_year}"

        print(f"[RETRY_SEARCH] 🔎 Попытка {attempt}/{max_attempts}: «{retry_query}»")

        retry_results = google_search(retry_query, num_results, region, language)
        if "Ничего не найдено" in retry_results or "Ошибка" in retry_results:
            print(f"[RETRY_SEARCH] ⚠️ Поиск пустой на попытке {attempt}")
            continue

        urls = re.findall(r'Ссылка: (https?://[^\s]+)', retry_results)

        for url in urls[:max_pages]:
            if url in existing_urls:
                continue
            page_text = fetch_page_content(url, max_chars=3000)
            if not page_text or "[Ошибка" in page_text:
                continue

            candidate = {"url": url, "content": page_text}
            filtered = filter_pages([candidate], query)
            if filtered:
                page_contents.append(filtered[0])
                existing_urls.add(url)
                print(f"[RETRY_SEARCH] ✅ Добавлена: {url[:70]}")

    status = "достаточно" if len(page_contents) >= min_good_sources else "недостаточно"
    print(
        f"[RETRY_SEARCH] Итого источников: {len(page_contents)} "
        f"(нужно {min_good_sources}) — {status}"
    )
    return page_contents


# ─────────────────────────────────────────────────────────────────────
# ЗАЩИТА ОТ ГАЛЛЮЦИНАЦИЙ: извлечение и валидация версий из источников
# ─────────────────────────────────────────────────────────────────────

def extract_versions_from_sources(page_contents: list) -> list:
    """
    Извлекает все версии ПО (формат X.Y или X.Y.Z) из отфильтрованных страниц.

    Возвращает список строк версий, отсортированных от новейшей к старейшей.
    Пример: ['17.4.1', '17.4', '16.0.3']
    """
    import re
    from functools import cmp_to_key

    version_pattern = re.compile(r'\b(\d{1,3}\.\d{1,3}(?:\.\d{1,4})?(?:\.\d{1,4})?)\b')
    all_versions = set()

    for page in page_contents:
        text = page.get('content', '')
        matches = version_pattern.findall(text)
        for v in matches:
            parts = v.split('.')
            # Отсеиваем явные годы (20xx.x) и IP-подобные (192.168...)
            if len(parts) >= 2:
                major = int(parts[0])
                if 2010 <= major <= 2040:
                    continue  # это год, не версия
                if major > 255:
                    continue  # слишком большое число
            all_versions.add(v)

    def version_key(v: str):
        """Сравнивает версии как кортежи чисел."""
        try:
            return tuple(int(x) for x in v.split('.'))
        except ValueError:
            return (0,)

    sorted_versions = sorted(all_versions, key=version_key, reverse=True)
    return sorted_versions


def validate_versions_before_answer(
    page_contents: list,
    query: str,
    max_version_age_years: int = 3,
) -> dict:
    """
    Проверяет версии из источников перед генерацией ответа.
    Защищает от галлюцинаций: модель не получит данные,
    если все версии слишком старые или противоречивы.

    Логика:
    - Извлекает все версии из page_contents.
    - Выбирает самую новую версию.
    - Если версия слишком старая (год публикации < current-max_version_age_years)
      И запрос требует актуальности → рекомендует повторный поиск.
    - Если версий совсем нет → нейтральный статус (не блокируем генерацию).

    Возвращает dict:
    {
        "ok": bool,          # True = можно генерировать ответ
        "retry": bool,       # True = нужен повторный поиск
        "best_version": str, # Лучшая найденная версия или ""
        "all_versions": list,
        "reason": str,
    }
    """
    import datetime

    versions = extract_versions_from_sources(page_contents)

    # Нет версий вообще — не блокируем (возможно, запрос не про версии)
    if not versions:
        return {
            "ok": True, "retry": False,
            "best_version": "", "all_versions": [],
            "reason": "no_versions_found"
        }

    best_version = versions[0]

    # Определяем, требует ли запрос актуальности
    query_lower = query.lower()
    needs_fresh = any(kw in query_lower for kw in _FRESHNESS_TRIGGER_WORDS)

    if not needs_fresh:
        return {
            "ok": True, "retry": False,
            "best_version": best_version, "all_versions": versions,
            "reason": "freshness_not_required"
        }

    # Проверяем свежесть через год публикации страниц
    current_year = datetime.datetime.now().year
    threshold_year = current_year - max_version_age_years

    # Собираем годы публикации всех страниц
    page_years = []
    for page in page_contents:
        y = extract_year(page.get('content', ''))
        if y > 0:
            page_years.append(y)

    if page_years:
        newest_page_year = max(page_years)
        if newest_page_year < threshold_year:
            print(
                f"[VERSION_GUARD] ⚠️ Все страницы устаревшие "
                f"(новейший год={newest_page_year}, порог={threshold_year}). "
                f"Версия «{best_version}» может быть неактуальной."
            )
            return {
                "ok": False, "retry": True,
                "best_version": best_version, "all_versions": versions,
                "reason": (
                    f"stale_sources: newest page year {newest_page_year} "
                    f"< threshold {threshold_year}"
                )
            }

    print(
        f"[VERSION_GUARD] ✅ Версия «{best_version}» из {len(versions)} найденных. "
        f"Все источники актуальны."
    )
    return {
        "ok": True, "retry": False,
        "best_version": best_version, "all_versions": versions,
        "reason": "version_validated"
    }


# ═══════════════════════════════════════════════════════════════════
# СИСТЕМА ОЦЕНКИ КАЧЕСТВА ИСТОЧНИКОВ
# ═══════════════════════════════════════════════════════════════════

def source_quality_score(url: str, text: str, query: str = "") -> dict:
    """
    Оценивает качество источника по 6 критериям и возвращает итоговый балл.

    Критерии (максимум 100 баллов):
    1. Домен — whitelist / blacklist / нейтральный  (−80 … +40)
    2. Техническое содержание — код, команды, API    (0 … +20)
    3. Длина текста по теме                          (0 … +15)
    4. Наличие дат и фактов                          (0 … +15)
    5. Совпадение темы страницы с запросом           (0 … +20)
    6. Признаки авторства и структурности            (0 … +10)

    Аргументы:
        url:   URL источника
        text:  текстовое содержимое страницы
        query: запрос пользователя (для пункта 5)

    Возвращает dict:
    {
        "total":        float,   # итоговый балл
        "domain_score": float,   # балл за домен
        "tech_score":   float,   # техническое содержание
        "length_score": float,   # длина текста
        "facts_score":  float,   # факты и даты
        "topic_score":  float,   # совпадение темы
        "author_score": float,   # авторство / структура
        "tier":         str,     # "whitelist" / "blacklist" / "neutral"
        "domain":       str,     # извлечённый домен
    }
    """
    import re, datetime

    url_lower = url.lower()
    text_lower = text.lower() if text else ""

    # ── 1. Домен: whitelist / blacklist ─────────────────────────────
    domain_score = 0.0
    tier = "neutral"
    matched_domain = ""

    # Извлекаем основной домен из URL
    domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url_lower)
    raw_domain = domain_match.group(1) if domain_match else url_lower[:60]

    # Проверяем whitelist (от наиболее специфичного к общему)
    for wl_domain, wl_bonus in sorted(SOURCE_WHITELIST.items(),
                                       key=lambda x: len(x[0]), reverse=True):
        if wl_domain in raw_domain:
            domain_score = float(wl_bonus)
            tier = "whitelist"
            matched_domain = wl_domain
            break

    # Проверяем blacklist (штраф суммируется, если нет бонуса whitelist)
    if tier != "whitelist":
        for bl_pattern, bl_penalty in SOURCE_BLACKLIST.items():
            if bl_pattern in raw_domain or bl_pattern in url_lower:
                domain_score += float(bl_penalty)
                tier = "blacklist"
                matched_domain = bl_pattern
                break

    # Ограничиваем диапазон
    domain_score = max(-80.0, min(40.0, domain_score))

    # ── 2. Техническое содержание ────────────────────────────────────
    tech_patterns = [
        r'```',                          # блоки кода
        r'def \w+\(',                  # функции Python
        r'function\s+\w+\s*\(',        # JavaScript функции
        r'class \w+',                  # классы
        r'import \w+',                 # импорты
        r'\$ \w+',                       # shell-команды
        r'--\w+',                        # CLI флаги
        r'api',                      # упоминание API
        r'https?://[^\s]{10,}',          # реальные URL в тексте
        r'(?:curl|wget|npm|pip|apt|brew|docker|kubectl)',
        r'\d+\.\d+\.\d+',           # версии X.Y.Z
        r'<\w+[^>]*>',                   # HTML/XML теги (в сыром тексте)
    ]
    tech_hits = sum(1 for p in tech_patterns if re.search(p, text[:5000]))
    tech_score = min(20.0, tech_hits * 2.5)

    # ── 3. Длина текста ──────────────────────────────────────────────
    text_len = len(text)
    if text_len >= 3000:
        length_score = 15.0
    elif text_len >= 1500:
        length_score = 10.0
    elif text_len >= 600:
        length_score = 5.0
    elif text_len < 200:
        length_score = -5.0   # штраф за слишком мало текста
    else:
        length_score = 0.0

    # ── 4. Факты: версии, даты, числа ───────────────────────────────
    fact_patterns_list = [
        re.compile(r'\d+\.\d+(?:\.\d+)*'),              # версии
        re.compile(r'(19|20)\d{2}'),                     # годы
        re.compile(r'\d{1,2}[./]\d{1,2}[./]\d{2,4}'),  # даты
        re.compile(r'(?:january|february|march|april|may|june|july|august|'
                   r'september|october|november|december|январ|феврал|март|'
                   r'апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*',
                   re.IGNORECASE),
        re.compile(r'(?:released?|вышел|вышла|релиз|changelog|'
                   r'обновлен\w*|запущен\w*)', re.IGNORECASE),
        re.compile(r'\d+\s*(?:мб|гб|mb|gb|мс|ms|fps|ghz|ггц|px)',
                   re.IGNORECASE),
    ]
    fact_types_found = sum(1 for fp in fact_patterns_list if fp.search(text_lower))
    facts_score = min(15.0, fact_types_found * 3.0)

    # ── 5. Совпадение темы с запросом ───────────────────────────────
    topic_score = 0.0
    if query:
        stop = {'и','в','на','с','по','для','что','как','где','это',
                'the','a','an','of','in','for','to','is','are','was'}
        kws = [w for w in re.split(r'[\s,?!.;:]+', query.lower())
               if len(w) > 2 and w not in stop]
        if kws:
            hits = sum(1 for kw in kws if kw in text_lower)
            ratio = hits / len(kws)
            topic_score = round(min(20.0, ratio * 20.0), 2)

            # Бонус если ключевые слова встречаются в первых 500 символах
            head = text_lower[:500]
            head_hits = sum(1 for kw in kws if kw in head)
            topic_score = min(20.0, topic_score + head_hits * 1.5)

    # ── 6. Авторство и структура ─────────────────────────────────────
    author_score = 0.0
    author_markers = [
        r'(?:by|автор|author|written by|опубликовано|published)',
        r'(?:updated|обновлено|дата публикации|date)',
        r'(?:editor|редактор|contributor)',
        r'<h[1-3]',         # структурные заголовки в сыром HTML
        r'#{1,3} \w',       # markdown-заголовки
    ]
    author_hits = sum(1 for p in author_markers
                      if re.search(p, text[:3000], re.IGNORECASE))
    author_score = min(10.0, author_hits * 3.0)

    # ── Итог ─────────────────────────────────────────────────────────
    total = domain_score + tech_score + length_score + facts_score + topic_score + author_score

    return {
        "total":        round(total, 2),
        "domain_score": domain_score,
        "tech_score":   round(tech_score, 2),
        "length_score": length_score,
        "facts_score":  round(facts_score, 2),
        "topic_score":  round(topic_score, 2),
        "author_score": round(author_score, 2),
        "tier":         tier,
        "domain":       matched_domain or raw_domain[:40],
    }


def rank_and_select_sources(
    page_contents: list,
    query: str,
    top_n: int = 3,
    min_quality_score: float = 20.0,
    min_sources: int = 2,
) -> tuple:
    """
    Оценивает качество каждого источника, сортирует по баллу и выбирает лучшие.

    Если после фильтрации остаётся меньше min_sources качественных источников,
    возвращает флаг needs_retry=True — сигнал для повторного поиска.

    Аргументы:
        page_contents:      список dict{'url', 'content', ...}
        query:              запрос пользователя
        top_n:              максимальное число источников в ответе (2–3)
        min_quality_score:  минимальный балл для «качественного» источника
        min_sources:        минимум качественных источников перед retry

    Возвращает (ranked_pages: list, needs_retry: bool):
        ranked_pages  — отсортированный список страниц с добавленным ключом
                        'quality_score' (только ≥ min_quality_score)
        needs_retry   — True если нужен повторный поиск
    """
    if not page_contents:
        return [], True

    scored = []
    for page in page_contents:
        url   = page.get("url", "")
        text  = page.get("content", "")
        scores = source_quality_score(url, text, query)
        page_with_score = dict(page)
        page_with_score["quality_score"]  = scores["total"]
        page_with_score["quality_detail"] = scores
        scored.append(page_with_score)

        tier_icon = "✅" if scores["tier"] == "whitelist" else (
                    "❌" if scores["tier"] == "blacklist" else "⚪")
        print(
            f"[SOURCE_QUALITY] {tier_icon} {scores['total']:6.1f}pts "
            f"| domain={scores['domain_score']:+.0f} "
            f"tech={scores['tech_score']:.0f} "
            f"facts={scores['facts_score']:.0f} "
            f"topic={scores['topic_score']:.0f} "
            f"| {url[:65]}"
        )

    # Сортируем от лучшего к худшему
    scored.sort(key=lambda p: p["quality_score"], reverse=True)

    # Отбираем только источники выше порога качества
    quality_pages = [p for p in scored if p["quality_score"] >= min_quality_score]

    needs_retry = len(quality_pages) < min_sources

    if needs_retry:
        print(
            f"[SOURCE_QUALITY] ⚠️ Качественных источников: {len(quality_pages)} "
            f"(нужно ≥{min_sources}, порог ≥{min_quality_score}пт). "
            f"Нужен повторный поиск."
        )
        # Возвращаем всё что есть — retry обработает caller
        best = scored[:top_n]
    else:
        best = quality_pages[:top_n]
        print(
            f"[SOURCE_QUALITY] ✅ Выбрано {len(best)} из {len(scored)} источников "
            f"(топ {top_n}, порог {min_quality_score}пт)"
        )

    return best, needs_retry




# ═══════════════════════════════════════════════════════════════════════════
# МОДУЛЬНЫЙ ПАЙПЛАЙН ОПРЕДЕЛЕНИЯ АКТУАЛЬНОЙ ВЕРСИИ ПО / ПРОШИВКИ / СИСТЕМЫ
# Архитектура: search → filter → extract → validate → answer
#
# Универсален для любого ПО: iOS, Android, Python, Firefox, Windows и т.д.
# Активируется автоматически при запросах вида:
#   «последняя версия X», «что нового в X», «latest version X», «X changelog»
# ═══════════════════════════════════════════════════════════════════════════

# ── Ключевые слова, однозначно указывающие на запрос о версии ───────────
_VERSION_INTENT_KEYWORDS = [
    # Русские
    "последняя версия", "актуальная версия", "текущая версия",
    "новая версия", "что нового", "что нового в", "изменения в",
    "обновление до", "вышла версия", "релиз", "changelog",
    "release notes", "список изменений", "что изменилось",
    # Английские
    "latest version", "current version", "newest version",
    "what's new", "what is new", "release notes", "changelog",
    "new features", "latest release", "current release",
    "latest update", "version history",
]

# ── Шаблоны поисковых запросов ───────────────────────────────────────────
_VERSION_QUERY_TEMPLATES = [
    "latest version {name}",
    "{name} latest release",
    "{name} release notes",
    "{name} changelog",
    "current {name} version",
    "{name} github releases",
    "{name} новая версия",
    "последняя версия {name}",
]

# ── Приоритет доменов: url-подстрока → бонус/штраф ──────────────────────
# Высокий приоритет: официальные источники, release-страницы, тех-СМИ
_DOMAIN_HIGH: dict = {
    # Страницы релизов (путь содержит releases/changelog)
    "/releases":            +90,
    "/changelog":           +85,
    "/release-notes":       +85,
    "/releasenotes":        +80,
    "/whats-new":           +75,
    "/downloads":           +60,
    # Официальные домены
    "github.com":           +70,
    "gitlab.com":           +65,
    "developer.apple.com":  +85,
    "developer.android.com":+85,
    "developer.chrome.com": +80,
    "docs.python.org":      +85,
    "python.org":           +75,
    "nodejs.org":           +75,
    "rust-lang.org":        +75,
    "golang.org":           +75,
    "kernel.org":           +80,
    "docs.microsoft.com":   +75,
    "learn.microsoft.com":  +70,
    "developer.mozilla.org":+80,
    "huggingface.co":       +65,
    "pytorch.org":          +70,
    "tensorflow.org":       +70,
    # Крупные тех-СМИ с датами
    "techradar.com":        +40,
    "arstechnica.com":      +45,
    "theverge.com":         +35,
    "zdnet.com":            +35,
    "9to5mac.com":          +40,
    "macrumors.com":        +40,
    "androidauthority.com": +40,
    "xda-developers.com":   +35,
    "theregister.com":      +40,
    "habr.com":             +40,
    "ixbt.com":             +35,
    "3dnews.ru":            +30,
    "cnews.ru":             +30,
}

# Низкий приоритет: форумы, агрегаторы, магазины, блоги без дат
_DOMAIN_LOW: dict = {
    "reddit.com":           -25,
    "quora.com":            -30,
    "yahoo.com":            -25,
    "answers.":             -30,
    "forum.":               -25,
    "forums.":              -25,
    "community.":           -20,
    "discussion.":          -20,
    "amazon.com":           -50,
    "ebay.com":             -50,
    "aliexpress.com":       -60,
    "play.google.com":      -40,
    "apps.apple.com":       -40,
    "facebook.com":         -60,
    "instagram.com":        -60,
    "twitter.com":          -35,
    "x.com":                -35,
    "youtube.com":          -40,
    "buzzfeed.com":         -60,
    "pinterest.com":        -60,
    "medium.com":           -10,  # небольшой штраф — может быть полезен
}

# ── Паттерны извлечения версий ───────────────────────────────────────────
import re as _re_vp
import datetime as _dt_vp

_VER_PATS = [
    # Явная метка: Version 17.4.1 / v3.12 / Ver. 3.12
    _re_vp.compile(
        r'(?:version|ver\.?|v)\s*(\d{1,3}\.\d{1,3}(?:\.\d{1,4})?(?:\.\d{1,4})?)',
        _re_vp.IGNORECASE),
    # В скобках: (3.12.1)
    _re_vp.compile(r'\((\d{1,3}\.\d{1,3}(?:\.\d{1,4})?)\)'),
    # Bare X.Y.Z
    _re_vp.compile(r'\b(\d{1,3}\.\d{1,3}(?:\.\d{1,4})?(?:\.\d{1,4})?)\b'),
]

_BETA_PAT   = _re_vp.compile(r'\b(?:beta|b\d+|preview|rc\d*|alpha|dev|nightly)\b',
                               _re_vp.IGNORECASE)
_STABLE_PAT = _re_vp.compile(r'\b(?:stable|release|final|lts|ga|general.availability)\b',
                               _re_vp.IGNORECASE)

# ── Паттерны дат ─────────────────────────────────────────────────────────
_DATE_PATS = [
    _re_vp.compile(r'(202\d)[.\-/](\d{2})[.\-/](\d{2})'),                  # 2024-05-13
    _re_vp.compile(r'(\d{1,2})[.\-/ ](\d{1,2})[.\-/ ](202\d)'),           # 13.05.2024
    _re_vp.compile(
        r'(?:january|february|march|april|may|june|july|august|september|'
        r'october|november|december|январ\w*|феврал\w*|март\w*|апрел\w*|'
        r'май|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)'
        r'\s+\d{1,2}[,\s]+?(202\d)', _re_vp.IGNORECASE),                   # May 13, 2024
    _re_vp.compile(r'\b(202\d)\b'),                                         # запасной: год
]

# Changelog-триггеры
_CHANGELOG_TRIGGER = _re_vp.compile(
    r"(?:what.?s new|changelog|release notes|изменения|что нового|новое в|"
    r"новшества|обновления|улучшения)\b",
    _re_vp.IGNORECASE)

_CHANGELOG_LINE = _re_vp.compile(r'(?:^|[-•*·▪])\s*(.{20,150}?)(?:\n|$)',
                                   _re_vp.MULTILINE)


# ───────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ───────────────────────────────────────────────────────────────────────────

def is_version_query(query: str) -> bool:
    """
    Определяет, является ли запрос запросом о версии ПО.
    Использует два уровня проверки:
    1. Точные фразы (multi-word) — высокая точность.
    2. Одиночные слова-маркеры — ловят «latest X», «X release», «X changelog».
    """
    import re as _re_iq
    q = query.lower()

    # Уровень 1: точные фразы
    if any(kw in q for kw in _VERSION_INTENT_KEYWORDS):
        return True

    # Уровень 2: одиночные маркеры версий
    _SINGLE_MARKERS = [
        r"\blatest\b", r"\bchangelog\b", r"\brelease\b",
        r"\brelease\s+notes\b", r"\bdownload\b",
        r"\bрелиз\b", r"\bверсия\b", r"\bchangelog\b",
        r"\bv\d+\.\d+\b",            # vX.Y в запросе
        r"\d+\.\d+\.\d+\b",         # X.Y.Z в запросе
        r"\bwhat.?s new\b",
    ]
    return any(_re_iq.search(p, q) for p in _SINGLE_MARKERS)


def _vp_domain_score(url: str) -> int:
    """Вычисляет приоритетный балл URL на основе домена и пути."""
    u = url.lower()
    score = 0
    for pattern, pts in _DOMAIN_HIGH.items():
        if pattern in u:
            score = max(score, pts)
    for pattern, pts in _DOMAIN_LOW.items():
        if pattern in u:
            score += pts
    return score


def _vp_parse_ver(v: str) -> tuple:
    """Конвертирует строку версии в сортируемый кортеж."""
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def _vp_classify(version: str, context: str) -> str:
    """Определяет тип релиза: stable / beta / rc / alpha."""
    combined = (version + " " + context[:300]).lower()
    if _BETA_PAT.search(combined):
        if "rc" in combined:
            return "rc"
        if "alpha" in combined:
            return "alpha"
        return "beta"
    return "stable"


def _vp_extract_date(text: str) -> str:
    """Извлекает первую читаемую дату из текста страницы."""
    for pat in _DATE_PATS:
        m = pat.search(text)
        if m:
            return m.group(0)[:30].strip()
    return ""


def _vp_extract_software_name(query: str) -> str:
    """
    Извлекает название ПО из запроса.
    «последняя версия Python 3» → «Python 3»
    «что нового в iOS 18» → «iOS 18»
    «latest Firefox release» → «Firefox»
    """
    q = query.strip()
    strip_pats = [
        r'\b(?:последняя|последний|актуальная|актуальный|новая|новый)\s+'
        r'(?:версия|релиз|обновление|release|version)?\s*',
        r'\b(?:что нового в|changelog|release notes|изменения в|список изменений в)\s*',
        r'\b(?:latest|current|newest|recent)\s+(?:version|release|update)?\s*',
        r'\b(?:version|release|update)\s+of\s+',
        r'\b(?:версия|релиз|обновление)\s+',
    ]
    result = q
    for pat in strip_pats:
        result = _re_vp.sub(pat, '', result, flags=_re_vp.IGNORECASE).strip()
    words = result.split()
    # берём до 3 слов — название обычно короткое
    return " ".join(words[:3]) if words else q[:40]


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 1 — SEARCH: несколько поисковых запросов
# ───────────────────────────────────────────────────────────────────────────

def vp_search(
    sw_name: str,
    region: str = "wt-wt",
    language: str = "russian",
    num_per_query: int = 5,
) -> list:
    """
    Выполняет 5 поисковых запросов по шаблонам и собирает уникальные URL.

    Аргументы:
        sw_name:       название ПО (например «Python», «iOS 18», «Firefox»)
        region:        регион поиска
        language:      язык
        num_per_query: результатов за запрос

    Возвращает список уникальных URL (минимум 5–8 источников).
    """
    print(f"[VP:SEARCH] 🔍 Мульти-поиск для «{sw_name}»")
    seen: set = set()
    all_urls: list = []

    for tmpl in _VERSION_QUERY_TEMPLATES[:6]:          # берём 6 из 8 шаблонов
        q = tmpl.format(name=sw_name)
        print(f"[VP:SEARCH]   → {q}")
        try:
            raw = google_search(q, num_results=num_per_query,
                                region=region, language=language)
            for url in _re_vp.findall(r'Ссылка: (https?://[^\s]+)', raw):
                if url not in seen:
                    seen.add(url)
                    all_urls.append(url)
        except Exception as exc:
            print(f"[VP:SEARCH]   ⚠️ Ошибка запроса: {exc}")

    print(f"[VP:SEARCH] ✅ Уникальных URL: {len(all_urls)}")
    return all_urls


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 2 — FILTER: приоритизация, загрузка, фильтр релевантности
# ───────────────────────────────────────────────────────────────────────────

def vp_filter(
    urls: list,
    query: str,
    max_load: int = 8,
) -> list:
    """
    Сортирует URL по приоритету домена, загружает страницы,
    фильтрует нерелевантные через is_relevant_page.

    Повышает приоритет: официальные сайты, /releases, /changelog, GitHub,
    крупные тех-СМИ с датами.
    Понижает приоритет: форумы, агрегаторы, магазины, соцсети.

    Страницы без дат или с текстом < 200 символов отклоняются.

    Аргументы:
        urls:     список URL из vp_search
        query:    исходный запрос (для is_relevant_page)
        max_load: максимум страниц для загрузки

    Возвращает список dict{'url','content','priority','rel_score'}.
    """
    # Сортируем по приоритету
    ranked = sorted([(u, _vp_domain_score(u)) for u in urls],
                    key=lambda x: x[1], reverse=True)
    print(f"[VP:FILTER] Загрузка страниц (топ по приоритету)...")
    pages = []

    for url, priority in ranked:
        if len(pages) >= max_load:
            break

        print(f"[VP:FILTER]  {priority:+4d}  {url[:70]}")
        try:
            text = fetch_page_content(url, max_chars=4000)
        except Exception as exc:
            print(f"[VP:FILTER]   ⚠️ Ошибка загрузки: {exc}")
            continue

        if not text or "[Ошибка" in text or len(text) < 200:
            print(f"[VP:FILTER]   ❌ Слишком короткий или ошибка ({len(text or '')} символов)")
            continue

        # Фильтр релевантности (URL-блокировка + ключевые слова + тема)
        ok, scores, reason = is_relevant_page(query, text, url=url)
        if not ok:
            print(f"[VP:FILTER]   ❌ Нерелевантна: {reason}")
            continue

        pages.append({
            "url":       url,
            "content":   text,
            "priority":  priority,
            "rel_score": scores.get("total_score", 0),
        })
        print(f"[VP:FILTER]   ✅ Принята | rel={scores.get('total_score',0):.0f}")

    print(f"[VP:FILTER] Итого страниц: {len(pages)}")
    return pages


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 3 — EXTRACT: версии, даты, changelog
# ───────────────────────────────────────────────────────────────────────────

def vp_extract(pages: list) -> dict:
    """
    Извлекает из текстов всех страниц:
    - все версии с типом (stable/beta/rc/alpha) и источниками
    - даты публикации каждой страницы
    - фрагменты changelog / release notes

    Аргументы:
        pages: список dict из vp_filter

    Возвращает dict:
    {
        "versions":   [{"version", "type", "date", "sources", "source_count", "priority_sum"}, ...],
        "changelogs": {url: [строка, ...]},
        "dates":      {url: str},
    }
    """
    ver_map: dict = {}
    changelogs: dict = {}
    dates: dict = {}

    for page in pages:
        url      = page["url"]
        text     = page["content"]
        priority = page.get("priority", 0)

        # Дата страницы
        page_date = _vp_extract_date(text)
        dates[url] = page_date

        # ── Извлекаем версии ─────────────────────────────────────────
        found_in_page: set = set()
        for vpat in _VER_PATS:
            for m in vpat.finditer(text):
                v = m.group(1)
                parts = v.split(".")
                if len(parts) < 2:
                    continue
                try:
                    major = int(parts[0])
                except ValueError:
                    continue
                # Фильтр: не IP, не год, не слишком большие числа
                if major < 0 or major > 999:
                    continue
                if 2000 <= major <= 2040:
                    continue   # это год
                if v in found_in_page:
                    continue
                found_in_page.add(v)

                # Контекст для определения типа релиза
                ctx = text[max(0, m.start()-100): m.end()+100]
                rtype = _vp_classify(v, ctx)

                if v not in ver_map:
                    ver_map[v] = {
                        "version":      v,
                        "type":         rtype,
                        "date":         page_date,
                        "sources":      [url],
                        "source_count": 1,
                        "priority_sum": priority,
                    }
                else:
                    info = ver_map[v]
                    if url not in info["sources"]:
                        info["sources"].append(url)
                        info["source_count"] += 1
                        info["priority_sum"] += priority
                    # Уточняем тип
                    if rtype in ("rc", "beta", "alpha") and info["type"] == "stable":
                        info["type"] = rtype
                    if page_date and not info["date"]:
                        info["date"] = page_date

        # ── Changelog-фрагменты ──────────────────────────────────────
        trigger = _CHANGELOG_TRIGGER.search(text)
        if trigger:
            block = text[trigger.end(): trigger.end() + 2500]
            lines = [m.group(1).strip()
                     for m in _CHANGELOG_LINE.finditer(block)
                     if len(m.group(1).strip()) > 20]
            if lines:
                changelogs[url] = lines[:10]

    return {
        "versions":   list(ver_map.values()),
        "changelogs": changelogs,
        "dates":      dates,
    }


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 4 — VALIDATE: консенсус версий, уровень доверия
# ───────────────────────────────────────────────────────────────────────────

def vp_validate(extracted: dict, max_age_months: int = 18) -> dict:
    """
    Проверяет актуальность версий и выбирает консенсусную.

    Логика:
    - Сортирует версии по номеру (от новейшей к старейшей).
    - Stable-версия с подтверждением ≥ 2 источников — выбирается как лучшая.
    - Pre-release (beta/rc/alpha) выбирается если новее stable.
    - Уровень доверия: high (≥3 источника), medium (≥2), low (<2).
    - Если top-3 версии из разных мажорных веток — генерируется предупреждение.

    Аргументы:
        extracted:      dict из vp_extract()
        max_age_months: порог устаревания источников (пока информационный)

    Возвращает dict:
    {
        "stable":        dict | None,   # лучшая стабильная версия
        "pre_release":   dict | None,   # лучшая бета/RC (если новее stable)
        "all_stable":    list,          # все stable, отсортированные
        "changelogs":    dict,
        "confidence":    "high"|"medium"|"low",
        "warning":       str,           # "" если нет предупреждений
    }
    """
    versions  = extracted.get("versions", [])
    changelogs = extracted.get("changelogs", {})

    if not versions:
        return {
            "stable":       None,
            "pre_release":  None,
            "all_stable":   [],
            "changelogs":   changelogs,
            "confidence":   "low",
            "warning":      "Не удалось извлечь версии из источников.",
        }

    # Сортируем всё по номеру версии
    all_sorted = sorted(versions, key=lambda v: _vp_parse_ver(v["version"]),
                        reverse=True)

    stable_vers  = [v for v in all_sorted if v["type"] == "stable"]
    pre_rel_vers = [v for v in all_sorted if v["type"] in ("beta", "rc", "alpha")]

    # ── Лучшая stable-версия ────────────────────────────────────────
    # Предпочитаем подтверждённую ≥2 источниками
    confirmed = [v for v in stable_vers if v["source_count"] >= 2]
    best_stable = confirmed[0] if confirmed else (stable_vers[0] if stable_vers else None)

    # ── Лучшая pre-release ─────────────────────────────────────────
    best_pre = None
    if pre_rel_vers:
        candidate = pre_rel_vers[0]
        if best_stable is None or (
            _vp_parse_ver(candidate["version"]) > _vp_parse_ver(best_stable["version"])
        ):
            best_pre = candidate

    # ── Доверие ──────────────────────────────────────────────────────
    if best_stable and best_stable["source_count"] >= 3:
        confidence = "high"
    elif best_stable and best_stable["source_count"] >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    # ── Предупреждение о разбросе версий ────────────────────────────
    warning = ""
    top3 = [v["version"] for v in stable_vers[:3]]
    if len(top3) >= 2:
        try:
            tuples = [_vp_parse_ver(v) for v in top3]
            if tuples[0][0] != tuples[-1][0]:
                warning = (
                    f"Найдены версии из разных мажорных веток: {', '.join(top3)}. "
                    f"Рекомендую уточнить на официальном сайте разработчика."
                )
        except Exception:
            pass

    return {
        "stable":       best_stable,
        "pre_release":  best_pre,
        "all_stable":   stable_vers[:8],
        "changelogs":   changelogs,
        "confidence":   confidence,
        "warning":      warning,
    }


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 5 — ANSWER: форматирование результата для промпта
# ───────────────────────────────────────────────────────────────────────────

def vp_answer(
    validated: dict,
    pages: list,
    sw_name: str,
    detected_language: str = "russian",
) -> str:
    """
    Формирует строку-контекст для передачи в промпт AI.

    Содержит:
    - последнюю стабильную версию + дату + источники
    - последнюю бета/RC (если есть)
    - список изменений из changelog-блоков
    - все использованные источники
    - предупреждение об уровне доверия
    - явные правила для AI (не придумывать, не обобщать без источника)

    Аргументы:
        validated:         dict из vp_validate()
        pages:             список страниц из vp_filter()
        sw_name:           название ПО
        detected_language: "russian" или иное (→ английский)
    """
    is_ru   = detected_language == "russian"
    SEP     = "═" * 56
    lines   = []

    stable    = validated.get("stable")
    pre_rel   = validated.get("pre_release")
    confidence = validated.get("confidence", "low")
    warning   = validated.get("warning", "")
    changelogs = validated.get("changelogs", {})

    conf_label = {"high": "🟢 ВЫСОКИЙ", "medium": "🟡 СРЕДНИЙ",
                  "low":  "🔴 НИЗКИЙ"}.get(confidence, confidence)

    if is_ru:
        lines += [SEP,
                  f"📦 ДАННЫЕ О ВЕРСИИ: {sw_name.upper()}",
                  f"Достоверность: {conf_label}",
                  SEP]
    else:
        lines += [SEP,
                  f"📦 VERSION DATA: {sw_name.upper()}",
                  f"Confidence: {conf_label}",
                  SEP]

    # ── Stable ───────────────────────────────────────────────────────
    if stable:
        ver  = stable["version"]
        date = stable.get("date") or ("неизвестна" if is_ru else "unknown")
        cnt  = stable.get("source_count", 1)
        srcs = stable.get("sources", [])[:3]
        if is_ru:
            lines += ["",
                      f"✅ ПОСЛЕДНЯЯ СТАБИЛЬНАЯ ВЕРСИЯ: {ver}",
                      f"   Дата выхода: {date}",
                      f"   Подтверждена в {cnt} источнике(ах):"]
        else:
            lines += ["",
                      f"✅ LATEST STABLE VERSION: {ver}",
                      f"   Release date: {date}",
                      f"   Confirmed in {cnt} source(s):"]
        for s in srcs:
            lines.append(f"      • {s[:70]}")
    else:
        lines.append("\n⚠️ " + ("Стабильная версия не определена." if is_ru
                                 else "Stable version not determined."))

    # ── Pre-release ──────────────────────────────────────────────────
    if pre_rel:
        ver   = pre_rel["version"]
        rtype = pre_rel.get("type", "beta").upper()
        date  = pre_rel.get("date") or ("неизвестна" if is_ru else "unknown")
        cnt   = pre_rel.get("source_count", 1)
        if is_ru:
            lines += ["",
                      f"🧪 ПОСЛЕДНЯЯ {rtype}-ВЕРСИЯ: {ver}",
                      f"   Дата: {date} | Источников: {cnt}"]
        else:
            lines += ["",
                      f"🧪 LATEST {rtype}: {ver}",
                      f"   Date: {date} | Sources: {cnt}"]

    # ── Все найденные stable-версии ─────────────────────────────────
    all_stable = validated.get("all_stable", [])
    if len(all_stable) > 1:
        ver_list = ", ".join(v["version"] for v in all_stable[:5])
        if is_ru:
            lines.append(f"\n   Все найденные стабильные версии: {ver_list}")
        else:
            lines.append(f"\n   All found stable versions: {ver_list}")

    # ── Changelog ───────────────────────────────────────────────────
    if changelogs:
        # Берём лог из источника с наивысшим приоритетом
        best_url = max(changelogs, key=lambda u: _vp_domain_score(u))
        cl_lines = changelogs[best_url][:8]
        label = "📋 ИЗМЕНЕНИЯ (из источника):" if is_ru else "📋 CHANGES (from source):"
        lines.append(f"\n{label}")
        lines.append(f"   Источник: {best_url[:70]}")
        for cl in cl_lines:
            lines.append(f"   • {cl}")
    else:
        lines.append("\n" + ("📋 Блок изменений не найден в загруженных источниках."
                              if is_ru else "📋 No changelog block found in loaded sources."))

    # ── Источники ────────────────────────────────────────────────────
    used = [p["url"] for p in pages[:6]]
    lines.append("\n" + ("🔗 ИСПОЛЬЗОВАННЫЕ ИСТОЧНИКИ:" if is_ru else "🔗 SOURCES USED:"))
    for i, u in enumerate(used, 1):
        prio = _vp_domain_score(u)
        tier = ("✅" if prio >= 50 else "⚪" if prio >= 0 else "⚠️")
        lines.append(f"   {i}. {tier} {u[:80]}")

    # ── Предупреждения ───────────────────────────────────────────────
    if warning:
        lines.append(f"\n⚠️  {warning}")

    if confidence == "low":
        low_msg = (
            "⚠️  ВНИМАНИЕ: Низкая достоверность — версия подтверждена менее чем 2 независимыми "
            "источниками. Настоятельно рекомендую проверить на официальном сайте."
            if is_ru else
            "⚠️  WARNING: Low confidence — version confirmed by fewer than 2 independent sources. "
            "Please verify on the official website."
        )
        lines.append(f"\n{low_msg}")

    # ── Правила для AI (запрет галлюцинаций) ────────────────────────
    if is_ru:
        lines += [
            "",
            SEP,
            "🚫 ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ДЛЯ AI:",
            "   • Используй ТОЛЬКО данные из блока выше — ничего сверх этого",
            "   • НЕ придумывай список изменений и новые функции",
            "   • НЕ пиши «улучшена стабильность» или другие общие фразы без источника",
            "   • Если данных нет — прямо скажи об этом пользователю",
            "   • Если достоверность LOW или MEDIUM — обязательно предупреди пользователя",
            "   • Всегда указывай источники в ответе",
            SEP,
        ]
    else:
        lines += [
            "",
            SEP,
            "🚫 MANDATORY AI RULES:",
            "   • Use ONLY the data from the block above — nothing beyond it",
            "   • Do NOT invent change lists or new features",
            "   • Do NOT write vague phrases like 'improved stability' without a source",
            "   • If data is missing — tell the user directly",
            "   • If confidence is LOW or MEDIUM — always warn the user",
            "   • Always cite sources in your answer",
            SEP,
        ]

    return "\n".join(lines)


# ───────────────────────────────────────────────────────────────────────────
# ОРКЕСТРАТОР — version_search_pipeline
# ───────────────────────────────────────────────────────────────────────────

def version_search_pipeline(
    user_query: str,
    region: str = "wt-wt",
    language: str = "russian",
) -> tuple:
    """
    Полный модульный пайплайн для определения актуальной версии ПО.

    Архитектура: search → filter → extract → validate → answer

    Шаги:
    1. vp_search    — 6 поисковых запросов по шаблонам, 5–8 источников
    2. vp_filter    — приоритизация по домену, загрузка, фильтр релевантности
    3. vp_extract   — извлечение версий, дат, changelog из всех страниц
    4. vp_validate  — консенсус версий, уровень доверия, предупреждения
    5. vp_answer    — форматированный блок с запретом галлюцинаций

    Аргументы:
        user_query: исходный запрос пользователя
        region:     регион поиска
        language:   язык результатов

    Возвращает КОРТЕЖ (result_str: str, page_contents: list):
        result_str    — форматированный блок данных для передачи в промпт
        page_contents — список загруженных страниц dict{'url','content',...}
    """
    print(f"[VP:PIPELINE] ════ СТАРТ ПАЙПЛАЙНА ВЕРСИЙ ════")
    print(f"[VP:PIPELINE] Запрос: {user_query}")

    # ── Определяем название ПО ───────────────────────────────────────
    sw_name = _vp_extract_software_name(user_query)
    print(f"[VP:PIPELINE] 📦 Название ПО: «{sw_name}»")

    # ── 1. SEARCH ────────────────────────────────────────────────────
    urls = vp_search(sw_name, region=region, language=language, num_per_query=5)
    if not urls:
        msg = "⚠️ Поиск не вернул результатов." if language == "russian" \
              else "⚠️ Search returned no results."
        return msg, []

    # ── 2. FILTER ────────────────────────────────────────────────────
    pages = vp_filter(urls, query=user_query, max_load=8)
    if not pages:
        msg = ("⚠️ Подходящих источников не найдено после фильтрации." if language == "russian"
               else "⚠️ No suitable sources found after filtering.")
        return msg, []

    # ── 3. EXTRACT ───────────────────────────────────────────────────
    extracted = vp_extract(pages)
    n_versions = len(extracted["versions"])
    print(f"[VP:PIPELINE] 🔢 Извлечено версий: {n_versions} | "
          f"с changelog: {len(extracted['changelogs'])}")

    # Если не нашли ни одной версии — откатываемся к обычному поиску
    if n_versions == 0:
        print(f"[VP:PIPELINE] ⚠️ Версии не найдены, передаём страницы как есть")
        fallback_str = "\n\n".join(
            f"[Источник {i+1}]\nURL: {p['url']}\n{p['content'][:1500]}"
            for i, p in enumerate(pages[:4])
        )
        return fallback_str, pages

    # ── 4. VALIDATE ──────────────────────────────────────────────────
    validated = vp_validate(extracted, max_age_months=18)
    stable = validated["stable"]
    if stable:
        print(f"[VP:PIPELINE] ✅ Stable: {stable['version']} "
              f"(источников: {stable['source_count']}, "
              f"доверие: {validated['confidence']})")
    else:
        print(f"[VP:PIPELINE] ⚠️ Стабильная версия не определена")

    # ── 5. ANSWER ────────────────────────────────────────────────────
    result_str = vp_answer(validated, pages, sw_name, language)
    print(f"[VP:PIPELINE] ✓ Завершён. Страниц: {len(pages)}, "
          f"символов в контексте: {len(result_str)}")

    return result_str, pages

def deep_web_search(
    query: str,
    num_results: int = 5,
    region: str = "wt-wt",
    language: str = "russian",
    max_pages: int = 3,
) -> tuple:
    """
    Глубокий веб-поиск с полным пайплайном качества.

    Пайплайн:
    1. Первичный поиск (DuckDuckGo)
    2. Загрузка страниц + фильтр релевантности (is_relevant_page)
    3. Фильтр свежести + наличия фактов (filter_pages)
    4. Оценка качества источников (source_quality_score)
       → сортировка, выбор топ-3 лучших
       → если качественных < 2: автоматический повторный поиск
    5. Финальный retry_search_if_needed если всё ещё мало источников

    Возвращает КОРТЕЖ (result_str: str, page_contents: list):
      - result_str    — текстовый блок для передачи в промпт
      - page_contents — список dict с добавленным 'quality_score'
    """
    print(f"[DEEP_SEARCH] ═══ ЗАПУСК ГЛУБОКОГО ВЕБ-ПОИСКА ═══")
    print(f"[DEEP_SEARCH] Запрос: {query}")

    # ── ШАГ 1: Первичный поиск ──────────────────────────────────────
    search_results = google_search(query, num_results, region, language)

    if "Ничего не найдено" in search_results or "Ошибка" in search_results:
        return search_results, []

    import re
    urls = re.findall(r'Ссылка: (https?://[^\s]+)', search_results)

    if not urls:
        print(f"[DEEP_SEARCH] ⚠️ URL не найдены в результатах")
        return search_results, []

    print(f"[DEEP_SEARCH] Найдено {len(urls)} URL для анализа")

    # ── ШАГ 2: Загрузка + фильтр релевантности ──────────────────────
    effective_max = min(max(max_pages, 5), len(urls))  # берём чуть больше для отбора
    raw_pages = []

    for i, url in enumerate(urls[:effective_max], 1):
        print(f"[DEEP_SEARCH] Загрузка страницы {i}/{effective_max}...")
        page_text = fetch_page_content(url, max_chars=3000)

        if page_text and "[Ошибка" not in page_text:
            is_ok, scores, reason = is_relevant_page(query, page_text, url=url)
            if is_ok:
                raw_pages.append({
                    "url": url,
                    "content": page_text,
                    "relevance_score": scores.get("total_score", 0),
                })
                print(f"[DEEP_SEARCH] ✅ Страница {i} релевантна "
                      f"(total={scores.get('total_score',0):.0f})")
            else:
                print(f"[DEEP_SEARCH] ❌ Страница {i} ОТКЛОНЕНА: {reason}")
        else:
            print(f"[DEEP_SEARCH] ⚠️ Страница {i}: ошибка загрузки")

    # ── ШАГ 3: Свежесть + факты ─────────────────────────────────────
    fresh_pages = filter_pages(raw_pages, query)

    # ── ШАГ 4: Оценка качества + сортировка + retry ─────────────────
    print(f"[DEEP_SEARCH] 🔍 Оцениваю качество {len(fresh_pages)} источников...")
    quality_pages, needs_quality_retry = rank_and_select_sources(
        fresh_pages, query, top_n=3, min_quality_score=20.0, min_sources=2
    )

    if needs_quality_retry:
        print(f"[DEEP_SEARCH] 🔄 Недостаточно качественных источников, "
              f"запускаю повторный поиск...")
        quality_pages = retry_search_if_needed(
            quality_pages,
            query,
            num_results=num_results,
            region=region,
            language=language,
            max_pages=max_pages,
            min_good_sources=2,
        )
        # После retry — снова оцениваем и сортируем
        if quality_pages:
            quality_pages, _ = rank_and_select_sources(
                quality_pages, query, top_n=3, min_quality_score=5.0
            )

    page_contents = quality_pages

    if not page_contents:
        print(f"[DEEP_SEARCH] ⚠️ Подходящих страниц нет, возвращаю базовые результаты")
        return search_results, []

    # ── ШАГ 5: Формируем текстовый блок для промпта ─────────────────
    enhanced_results = search_results + "\n\n" + "═" * 60 + "\n"
    enhanced_results += "📄 СОДЕРЖИМОЕ ПРОАНАЛИЗИРОВАННЫХ СТРАНИЦ:\n"
    enhanced_results += "═" * 60 + "\n\n"

    for i, page in enumerate(page_contents, 1):
        q_score = page.get("quality_score", 0)
        tier    = page.get("quality_detail", {}).get("tier", "")
        enhanced_results += f"[Источник {i} | качество: {q_score:.0f}пт | {tier}]\n"
        enhanced_results += f"URL: {page['url']}\n"
        enhanced_results += f"Текст: {page['content']}\n\n"
        enhanced_results += "-" * 60 + "\n\n"

    print(f"[DEEP_SEARCH] ✓ Завершён. "
          f"Лучших источников: {len(page_contents)}, "
          f"объём: {len(enhanced_results)} символов")

    return enhanced_results, page_contents

def fallback_web_search(query: str, num_results: int = 5, language: str = "russian") -> str:
    """Fallback веб-поиск через DuckDuckGo HTML без внешних библиотек"""
    print(f"[FALLBACK_SEARCH] Запуск fallback поиска для: {query}")
    
    try:
        import urllib.parse
        import re
        from html import unescape
        
        # Формируем URL для DuckDuckGo
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        
        # Настраиваем заголовки чтобы выглядеть как браузер
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7' if language == "russian" else 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        print(f"[FALLBACK_SEARCH] Отправка запроса к DuckDuckGo...")
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        html_content = response.text
        print(f"[FALLBACK_SEARCH] Получен HTML, длина: {len(html_content)} символов")
        
        # Парсим результаты с помощью регулярных выражений
        # DuckDuckGo HTML использует структуру: <div class="result">
        
        # Ищем заголовки результатов
        title_pattern = r'<a[^>]*class="result__a"[^>]*>([^<]+)</a>'
        titles = re.findall(title_pattern, html_content)
        
        # Ищем описания
        snippet_pattern = r'<a[^>]*class="result__snippet"[^>]*>([^<]+)</a>'
        snippets = re.findall(snippet_pattern, html_content)
        
        # Ищем ссылки
        url_pattern = r'<a[^>]*class="result__url"[^>]*href="([^"]+)"'
        urls = re.findall(url_pattern, html_content)
        
        # Если стандартный паттерн не сработал, пробуем альтернативный
        if not titles:
            print(f"[FALLBACK_SEARCH] Стандартный паттерн не сработал, пробуем альтернативный...")
            # Альтернативный паттерн для нового формата DuckDuckGo
            title_pattern = r'class="result__title"[^>]*><a[^>]*>(.+?)</a>'
            titles = re.findall(title_pattern, html_content, re.DOTALL)
            
            snippet_pattern = r'class="result__snippet">(.+?)</div>'
            snippets = re.findall(snippet_pattern, html_content, re.DOTALL)
        
        print(f"[FALLBACK_SEARCH] Найдено: заголовков={len(titles)}, описаний={len(snippets)}, ссылок={len(urls)}")
        
        if not titles and not snippets:
            print(f"[FALLBACK_SEARCH] Не удалось распарсить результаты. Возможно, изменился формат DuckDuckGo.")
            return "⚠️ Не удалось получить результаты поиска. Попробуйте установить библиотеку: pip install ddgs"
        
        # Объединяем результаты
        search_results = []
        for i in range(min(num_results, len(titles))):
            title = unescape(re.sub(r'<[^>]+>', '', titles[i])).strip() if i < len(titles) else "Без заголовка"
            snippet = unescape(re.sub(r'<[^>]+>', '', snippets[i])).strip() if i < len(snippets) else "Нет описания"
            url = urls[i] if i < len(urls) else ""
            
            # Декодируем URL если он закодирован
            if url.startswith('//duckduckgo.com/l/?'):
                # Извлекаем реальный URL из redirect
                url_match = re.search(r'uddg=([^&]+)', url)
                if url_match:
                    url = urllib.parse.unquote(url_match.group(1))
            
            search_results.append(
                f"[Результат {i+1}]\n"
                f"Заголовок: {title}\n"
                f"Описание: {snippet}\n"
                f"Ссылка: {url}"
            )
            print(f"[FALLBACK_SEARCH] Результат {i+1}: {title[:50]}...")
        
        if not search_results:
            return "⚠️ Результаты поиска пусты. Попробуйте переформулировать запрос."
        
        final_results = "\n\n".join(search_results)
        print(f"[FALLBACK_SEARCH] ✓ Fallback поиск завершён. Найдено {len(search_results)} результатов")
        return final_results
        
    except requests.Timeout:
        return "⚠️ Превышено время ожидания ответа от поисковика. Попробуйте снова."
    except requests.RequestException as e:
        return f"⚠️ Ошибка сетевого подключения: {e}"
    except Exception as e:
        print(f"[FALLBACK_SEARCH] ✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return f"⚠️ Ошибка fallback поиска: {e}"

# -------------------------
# TTS с pyttsx3
# -------------------------
def compress_search_results(search_results: str, max_length: int) -> str:
    """Сжимает результаты поиска до нужной длины, сохраняя самое важное"""
    print(f"[COMPRESS] Начальная длина: {len(search_results)} символов")
    print(f"[COMPRESS] Целевая длина: {max_length} символов")
    
    if len(search_results) <= max_length:
        print(f"[COMPRESS] Сжатие не требуется")
        return search_results
    
    # Разбиваем на отдельные результаты
    results = search_results.split('[Результат ')
    if len(results) <= 1:
        # Если не удалось разбить, просто обрезаем
        print(f"[COMPRESS] Простое обрезание до {max_length} символов")
        return search_results[:max_length] + "..."
    
    # Первый элемент - пустой, убираем
    results = results[1:]
    
    # Вычисляем, сколько символов на каждый результат
    chars_per_result = max_length // len(results)
    print(f"[COMPRESS] Результатов: {len(results)}, символов на результат: {chars_per_result}")
    
    compressed_results = []
    for i, result in enumerate(results, 1):
        # Восстанавливаем структуру
        result = '[Результат ' + result
        
        # Извлекаем основные части
        lines = result.split('\n')
        title_line = ""
        description_line = ""
        link_line = ""
        
        for line in lines:
            if line.startswith('Заголовок:'):
                title_line = line
            elif line.startswith('Описание:'):
                description_line = line
            elif line.startswith('Ссылка:'):
                link_line = line
        
        # Сжимаем описание, если нужно
        if description_line:
            desc_prefix = "Описание: "
            desc_text = description_line[len(desc_prefix):]
            
            # Оставляем место для заголовка и ссылки (примерно 200 символов)
            available_for_desc = chars_per_result - 200
            if available_for_desc < 100:
                available_for_desc = 100
            
            if len(desc_text) > available_for_desc:
                desc_text = desc_text[:available_for_desc] + "..."
                description_line = desc_prefix + desc_text
        
        # Собираем сжатый результат
        compressed = f"[Результат {i}]\n{title_line}\n{description_line}\n{link_line}"
        compressed_results.append(compressed)
    
    final_result = "\n\n".join(compressed_results)
    print(f"[COMPRESS] Итоговая длина: {len(final_result)} символов")
    
    return final_result


# ═══════════════════════════════════════════════════════════════════
# ПАЙПЛАЙН ОБРАБОТКИ ОТВЕТА ПОСЛЕ ПОИСКА
# ═══════════════════════════════════════════════════════════════════

def summarize_sources(raw_search_results: str, query: str, detected_language: str = "russian", model_key: str = None) -> str:
    """
    Вызывает Ollama для извлечения только фактов из сырого содержимого страниц.
    Модели передаётся только сжатый список фактов, а не длинный текст страниц.
    model_key — явный ключ модели; если None, берётся текущий глобал.
    """
    print(f"[SUMMARIZE] Начинаю извлечение фактов из результатов поиска...")

    # Если результаты небольшие — не тратим время на промежуточный вызов
    if len(raw_search_results) < 1500:
        print(f"[SUMMARIZE] Результаты небольшие ({len(raw_search_results)} символов), пропускаем суммаризацию")
        return raw_search_results

    if detected_language == "russian":
        summarize_prompt = f"""Ты — строгий фильтр фактов. Вот содержимое веб-страниц по запросу: "{query}"

{raw_search_results}

ЗАДАЧА: Извлеки ТОЛЬКО факты, которые НАПРЯМУЮ отвечают на запрос "{query}".

СТРОГИЕ ПРАВИЛА:
- ❌ ИГНОРИРУЙ результаты, которые не относятся к теме запроса (реклама, случайные страницы, не по теме)
- ❌ НЕ включай факты о посторонних вещах, даже если они есть в источниках
- ✅ Включай ТОЛЬКО факты, прямо отвечающие на запрос
- Каждый факт — отдельная строка, начинающаяся с "• "
- Максимум 10 фактов
- НЕ копируй целые абзацы — только суть
- НЕ добавляй своих рассуждений
- Если ни один результат не относится к теме — напиши: "Релевантных фактов не найдено"

Отвечай на русском языке."""
    else:
        summarize_prompt = f"""You are a strict fact filter. Here is web page content for query: "{query}"

{raw_search_results}

TASK: Extract ONLY facts that DIRECTLY answer the query "{query}".

STRICT RULES:
- ❌ IGNORE results not related to the query topic (ads, random pages, off-topic)
- ❌ Do NOT include facts about unrelated things, even if they appear in sources
- ✅ Include ONLY facts that directly answer the query
- Each fact on a new line starting with "• "
- Maximum 10 facts
- Do NOT copy full paragraphs — only the core info
- Do NOT add your own reasoning
- If no results are relevant — write: "No relevant facts found"

Answer in English."""

    try:
        # Используем глобальный резолвер из get_ai_response недоступен здесь,
        # поэтому дублируем логику: mistral/qwen — явно, остальные — SUPPORTED_MODELS
        if model_key == "mistral":
            _summ_model = MISTRAL_MODEL_NAME
        elif model_key == "qwen":
            _summ_model = QWEN_MODEL_NAME
        elif model_key and model_key in SUPPORTED_MODELS:
            _summ_model = SUPPORTED_MODELS[model_key][0]
        else:
            _summ_model = get_current_ollama_model()
        payload = {
            "model": _summ_model,
            "messages": [{"role": "user", "content": summarize_prompt}],
            "stream": False,
            "options": {"num_predict": 600, "temperature": 0.1}
        }
        response = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=45)
        if response.status_code == 200:
            data = response.json()
            facts = data.get("message", {}).get("content", "").strip()
            if facts and len(facts) > 50:
                print(f"[SUMMARIZE] ✓ Факты извлечены. Длина: {len(facts)} символов")
                return facts
    except Exception as e:
        print(f"[SUMMARIZE] ⚠️ Ошибка при суммаризации: {e}")

    # Если что-то пошло не так — возвращаем оригинал
    print(f"[SUMMARIZE] Возвращаю оригинальные результаты")
    return raw_search_results


def detect_question_parts(query: str) -> dict:
    """
    Определяет структуру вопроса пользователя:
    - есть ли запрос на версию/номер
    - есть ли запрос на изменения/что нового
    - есть ли запрос на объяснение/как работает
    - сколько отдельных вопросов/пунктов
    """
    q = query.lower()

    has_version = any(kw in q for kw in [
        "версия", "version", "v.", "релиз", "release", "обновление", "update",
        "какая версия", "последняя версия", "новая версия", "вышла"
    ])

    has_changes = any(kw in q for kw in [
        "что изменилось", "что нового", "что добавили", "что нового в",
        "изменения", "нововведения", "changelog", "changes", "what's new",
        "что поменялось", "отличия", "отличается", "новые функции", "улучшения"
    ])

    # ВАЖНО: не используем одиночное "как" — оно входит в любое предложение
    # ("как дела", "как называется", "как погода" и т.д.) → ложные срабатывания.
    # Только конкретные фразы, явно запрашивающие развёрнутое объяснение.
    has_explanation = any(kw in q for kw in [
        "как работает", "как устроен", "как происходит", "как это работает",
        "как используется", "как настроить", "как установить", "как сделать",
        "почему", "зачем", "объясни", "расскажи подробно",
        "what is", "how does", "how to", "how do", "explain", "why",
        "что это такое", "что такое", "что из себя представляет",
        "в чём разница", "в чем разница", "чем отличается",
    ])

    # Подсчёт пунктов: вопросительные знаки, союзы "и ещё", нумерация
    question_marks = q.count("?")
    has_multiple = (
        question_marks > 1
        or any(kw in q for kw in ["и ещё", "и также", "а также", "плюс", "и ещё", "кроме того", "во-первых", "и как"])
        or (has_version and has_changes)
        or (has_version and has_explanation)
        or (has_changes and has_explanation)
    )

    parts_count = sum([has_version, has_changes, has_explanation])
    if question_marks > 1:
        parts_count = max(parts_count, question_marks)

    result = {
        "has_version": has_version,
        "has_changes": has_changes,
        "has_explanation": has_explanation,
        "has_multiple": has_multiple,
        "parts_count": parts_count
    }
    print(f"[DETECT_PARTS] Анализ вопроса: {result}")
    return result


def detect_language_of_text(text: str) -> str:
    """Определяет язык текста по характерным символам."""
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    if cyrillic > latin:
        return "russian"
    return "english"


def validate_answer(answer: str, query: str, detected_language: str, facts: str = "") -> dict:
    """
    Проверяет качество ответа:
    - язык совпадает с языком пользователя
    - нет вставок на другом языке (более 20% слов другого языка)
    - все части вопроса раскрыты
    - нет явной копипасты из источников (длинные совпадения >80 символов)

    Возвращает: {"valid": bool, "issues": list[str]}
    """
    issues = []
    answer_lower = answer.lower()

    # 1. Проверка языка
    answer_lang = detect_language_of_text(answer)
    if answer_lang != detected_language:
        issues.append(f"wrong_language: ответ на {answer_lang}, ожидается {detected_language}")

    # 2. Проверка смешивания языков
    if detected_language == "russian":
        # Считаем процент латинских слов (исключаем URL и технические термины)
        words = answer.split()
        latin_words = [w for w in words if all('a' <= c.lower() <= 'z' for c in w if c.isalpha()) and len(w) > 3 and 'http' not in w]
        if len(words) > 10 and len(latin_words) / len(words) > 0.25:
            issues.append(f"language_mixing: {len(latin_words)}/{len(words)} слов латинские")

    # 3. Проверка полноты по частям вопроса
    parts = detect_question_parts(query)
    if parts["has_version"] and not any(kw in answer_lower for kw in ["версия", "version", "v.", "релиз", "release", "вышла", "обновлен"]):
        issues.append("missing_version: не упомянута версия/релиз")
    if parts["has_changes"] and not any(kw in answer_lower for kw in ["изменил", "добавил", "нов", "улучшил", "исправил", "change", "new", "update", "feature"]):
        issues.append("missing_changes: не описаны изменения")
    # Порог длины: считаем ответ слишком коротким только если:
    # 1. Вопрос сам по себе длинный (> 40 символов) — значит, ждём развёрнутый ответ
    # 2. Ответ короче 150 символов
    # Короткие вопросы ("почему небо синее?") могут получать короткие ответы.
    if parts["has_explanation"] and len(query) > 40 and len(answer) < 150:
        issues.append("missing_explanation: объяснение слишком короткое")

    # 4. Проверка копипасты из источников (если переданы факты)
    if facts:
        # Ищем длинные строки (>80 символов), которые есть и в ответе, и в фактах
        sentences = [s.strip() for s in facts.replace('\n', '. ').split('.') if len(s.strip()) > 80]
        for sentence in sentences[:20]:
            # Нормализуем для сравнения
            s_norm = ' '.join(sentence.lower().split())
            a_norm = ' '.join(answer.lower().split())
            if s_norm in a_norm:
                issues.append(f"copy_paste: найдена копипаста из источников")
                break

    valid = len(issues) == 0
    result = {"valid": valid, "issues": issues}
    if not valid:
        print(f"[VALIDATE] ⚠️ Проверка не пройдена: {issues}")
    else:
        print(f"[VALIDATE] ✓ Ответ прошёл проверку")
    return result


def build_final_answer_prompt(user_message: str, facts: str, question_parts: dict, detected_language: str, issues: list = None) -> str:
    """
    Строит финальный промпт для генерации ответа с учётом структуры вопроса.
    Используется при первой генерации и при перегенерации после провала валидации.
    """
    # Инструкции по структуре ответа
    structure_hints = []
    if question_parts["has_version"]:
        if detected_language == "russian":
            structure_hints.append("• Начни с текущей версии/релиза")
        else:
            structure_hints.append("• Start with the current version/release")

    if question_parts["has_changes"]:
        if detected_language == "russian":
            structure_hints.append("• Перечисли изменения списком (каждое изменение — новая строка с «–»)")
        else:
            structure_hints.append("• List changes as bullet points (each change on new line with '–')")

    if question_parts["has_explanation"]:
        if detected_language == "russian":
            structure_hints.append("• Объясни кратко своими словами, не цитируя источники")
        else:
            structure_hints.append("• Briefly explain in your own words, no direct quotes from sources")

    if question_parts["has_multiple"]:
        if detected_language == "russian":
            structure_hints.append("• Ответь на ВСЕ части вопроса последовательно")
        else:
            structure_hints.append("• Answer ALL parts of the question in order")

    structure_block = "\n".join(structure_hints) if structure_hints else ""

    # Блок с исправлениями (при перегенерации)
    fix_block = ""
    if issues:
        if detected_language == "russian":
            fix_block = f"\n\nПРЕДЫДУЩИЙ ОТВЕТ БЫЛ ПЛОХИМ. Проблемы:\n" + "\n".join(f"- {i}" for i in issues) + "\nИСПРАВЬ все эти проблемы в новом ответе.\n"
        else:
            fix_block = f"\n\nPREVIOUS ANSWER WAS REJECTED. Issues:\n" + "\n".join(f"- {i}" for i in issues) + "\nFIX all these issues in the new answer.\n"

    if detected_language == "russian":
        prompt = f"""Ты помогаешь пользователю ответить на вопрос. У тебя есть список фактов из интернета.

ФАКТЫ ИЗ ИСТОЧНИКОВ:
{facts}

ВОПРОС ПОЛЬЗОВАТЕЛЯ:
{user_message}

ТРЕБОВАНИЯ К ОТВЕТУ:
{structure_block}
• Используй ТОЛЬКО факты, которые НАПРЯМУЮ относятся к вопросу пользователя
• ❌ ИГНОРИРУЙ любые факты не по теме (про другие фильмы, города, организации и т.д.)
• Если фактов по теме мало — честно скажи что информации недостаточно, не додумывай
• Пиши связный текст своими словами, не как кусок статьи
• НЕ копируй фразы из источников — перефразируй
• Отвечай ИСКЛЮЧИТЕЛЬНО на русском языке, без английских вставок
• 🚫 НЕ вставляй URL-адреса в текст{fix_block}

Ответ:"""
    else:
        prompt = f"""You are helping the user answer a question. You have a list of facts from the internet.

FACTS FROM SOURCES:
{facts}

USER QUESTION:
{user_message}

ANSWER REQUIREMENTS:
{structure_block}
• Write coherent text, like a normal answer — not a fragment of an article
• Use ONLY facts from the list above, don't invent anything
• Do NOT copy phrases from sources — rephrase in your own words
• Answer EXCLUSIVELY in English, no Russian inserts
• 🚫 Do NOT insert URLs in the text{fix_block}

Answer:"""

    return prompt


def build_contextual_search_query(user_message: str, chat_manager, chat_id: int, detected_language: str) -> str:
    """
    Формирует контекстный поисковый запрос на основе истории диалога.
    
    Логика:
    1. Определяет, является ли вопрос уточняющим (короткий или с ключевыми словами)
    2. Если уточняющий - добавляет контекст из предыдущих сообщений
    3. Если самостоятельный - возвращает как есть
    """
    print(f"[CONTEXTUAL_SEARCH] Анализирую вопрос...")
    print(f"[CONTEXTUAL_SEARCH] Вопрос: {user_message}")
    
    # Получаем последние сообщения для контекста
    if chat_manager and chat_id:
        history = chat_manager.get_chat_messages(chat_id, limit=10)
    else:
        # Fallback на старую БД
        import sqlite3
        conn = sqlite3.connect("chat_memory.db")
        cur = conn.cursor()
        cur.execute("SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT 10")
        history = list(reversed(cur.fetchall()))
        conn.close()
    
    if not history or len(history) < 2:
        print(f"[CONTEXTUAL_SEARCH] История короткая, используем исходный запрос")
        return user_message
    
    # Ключевые слова уточняющих вопросов
    clarifying_keywords_ru = [
        'а почему', 'а как', 'а где', 'а когда', 'а что', 'а кто', 'а после', 'а завтра', 'а вчера', 'а сегодня',
        'почему', 'как именно', 'что именно', 'когда именно', 'где именно',
        'расскажи', 'подробнее', 'ещё', 'еще', 'тоже', 'также', 'дальше',
        'его', 'её', 'их', 'этого', 'этой', 'этим', 'этот', 'эта', 'это',
        'тогда', 'потом', 'после этого', 'что дальше',
        'завтра', 'вчера', 'сегодня', 'послезавтра'  # ВАЖНО: добавлены временные слова
    ]
    
    clarifying_keywords_en = [
        'and why', 'and how', 'and where', 'and when', 'and what', 'and who',
        'why', 'how exactly', 'what exactly', 'when exactly', 'where exactly',
        'tell me', 'more', 'also', 'too', 'then', 'after', 'next',
        'it', 'its', 'their', 'this', 'that', 'those', 'these',
        'tomorrow', 'yesterday', 'today'  # Temporal words
    ]
    
    keywords = clarifying_keywords_ru if detected_language == "russian" else clarifying_keywords_en
    
    user_lower = user_message.lower().strip()
    
    # Проверка 1: Содержит ли вопрос ключевые слова уточнения
    has_clarifying_words = any(keyword in user_lower for keyword in keywords)
    
    # Проверка 2: ОЧЕНЬ короткий вопрос (менее 6 слов) - скорее всего уточнение
    is_very_short = len(user_message.split()) < 6
    
    # Проверка 3: Начинается с вопросительного слова без контекста
    starts_with_question = any(user_lower.startswith(q) for q in ['почему', 'как', 'где', 'когда', 'зачем', 'why', 'how', 'where', 'when'])
    
    # Проверка 4: Начинается с "а " - ВСЕГДА уточнение
    starts_with_a = user_lower.startswith('а ') or user_lower.startswith('and ')
    
    # Проверка 5: Только временные слова (завтра, вчера, сегодня)
    is_temporal_only = user_lower in ['завтра', 'вчера', 'сегодня', 'послезавтра', 'tomorrow', 'yesterday', 'today']
    
    # РАСШИРЕННАЯ ЛОГИКА: считаем уточняющим если:
    # - есть ключевые слова ИЛИ
    # - очень короткий вопрос ИЛИ
    # - начинается с "а " ИЛИ
    # - только временное слово
    is_clarifying = has_clarifying_words or is_very_short or starts_with_a or is_temporal_only
    
    if is_clarifying:
        print(f"[CONTEXTUAL_SEARCH] ✅ Обнаружен УТОЧНЯЮЩИЙ вопрос")
        print(f"[CONTEXTUAL_SEARCH]    - Ключевые слова: {has_clarifying_words}")
        print(f"[CONTEXTUAL_SEARCH]    - Очень короткий (<6 слов): {is_very_short}")
        print(f"[CONTEXTUAL_SEARCH]    - Начинается с 'а': {starts_with_a}")
        print(f"[CONTEXTUAL_SEARCH]    - Только временное слово: {is_temporal_only}")
        
        # Извлекаем последний вопрос пользователя для контекста
        context_parts = []
        
        for i in range(len(history) - 1, -1, -1):
            row = history[i]
            role, content = row[0], row[1]
            
            # Берём последний вопрос пользователя (не текущий)
            if role == "user" and content != user_message:
                context_parts.insert(0, content)
                print(f"[CONTEXTUAL_SEARCH]    Найден предыдущий вопрос: {content[:50]}...")
                break
        
        if context_parts:
            # Формируем расширенный запрос
            main_context = context_parts[0]
            
            # УМНАЯ ОБРАБОТКА УТОЧНЯЮЩИХ ВОПРОСОВ
            user_lower = user_message.lower().strip()
            
            # Если вопрос начинается с "а в/а на" - это изменение места
            # Пример: "погода в Питере" + "а в Мытищах" → "погода в Мытищах"
            if detected_language == "russian":
                # Проверяем паттерны изменения места
                location_change_patterns = [
                    ('а в ', 'в '),
                    ('а на ', 'на '),
                    ('а для ', 'для ')
                ]
                
                for pattern, replacement in location_change_patterns:
                    if user_lower.startswith(pattern):
                        # Извлекаем новое место
                        new_location_part = user_message[len(pattern):]
                        
                        # Заменяем старое место на новое в исходном запросе
                        # Ищем паттерны типа "в [город]", "на [место]"
                        import re
                        # Заменяем первое вхождение предлога + место
                        for prep in ['в ', 'на ', 'для ']:
                            pattern_to_replace = prep + r'\S+'
                            if re.search(pattern_to_replace, main_context.lower()):
                                contextual_query = re.sub(
                                    pattern_to_replace,
                                    replacement + new_location_part,
                                    main_context,
                                    count=1,
                                    flags=re.IGNORECASE
                                )
                                print(f"[CONTEXTUAL_SEARCH] 🔄 Заменено место: '{main_context}' → '{contextual_query}'")
                                return contextual_query
                        
                        # Если не нашли паттерн, добавляем новое место в конец основного запроса
                        contextual_query = main_context.replace(main_context.split()[-1], new_location_part)
                        print(f"[CONTEXTUAL_SEARCH] 🔄 Изменено место (fallback): '{contextual_query}'")
                        return contextual_query
            
            else:
                # Для английского
                location_change_patterns = [
                    ('and in ', 'in '),
                    ('and at ', 'at '),
                    ('and for ', 'for ')
                ]
                
                for pattern, replacement in location_change_patterns:
                    if user_lower.startswith(pattern):
                        new_location_part = user_message[len(pattern):]
                        
                        import re
                        for prep in ['in ', 'at ', 'for ']:
                            pattern_to_replace = prep + r'\S+'
                            if re.search(pattern_to_replace, main_context.lower()):
                                contextual_query = re.sub(
                                    pattern_to_replace,
                                    replacement + new_location_part,
                                    main_context,
                                    count=1,
                                    flags=re.IGNORECASE
                                )
                                print(f"[CONTEXTUAL_SEARCH] 🔄 Replaced location: '{main_context}' → '{contextual_query}'")
                                return contextual_query
                        
                        contextual_query = main_context.replace(main_context.split()[-1], new_location_part)
                        print(f"[CONTEXTUAL_SEARCH] 🔄 Changed location (fallback): '{contextual_query}'")
                        return contextual_query
            
            # Стандартное поведение для других типов уточнений
            # Комбинируем: "основная тема" + "уточняющий вопрос"
            contextual_query = f"{main_context} {user_message}"
            
            print(f"[CONTEXTUAL_SEARCH] ✅ Расширенный запрос: {contextual_query[:100]}...")
            return contextual_query
        else:
            print(f"[CONTEXTUAL_SEARCH] ⚠️  Не найден предыдущий контекст, используем исходный запрос")
            return user_message
    else:
        print(f"[CONTEXTUAL_SEARCH] ℹ️  Самостоятельный вопрос, контекст не требуется")
        return user_message

# Озвучка полностью удалена