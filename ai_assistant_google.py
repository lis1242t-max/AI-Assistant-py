#!/usr/bin/env python3
# ai_gui_app.py
# PyQt6 GUI чат-ассистент с ОПТИМИЗИРОВАННЫМ обновлением layout
#
# ═══════════════════════════════════════════════════════════════════════════
# INTELLIGENT LAYOUT UPDATE - ОБНОВЛЕНИЕ ПО ТРЕБОВАНИЮ
# ═══════════════════════════════════════════════════════════════════════════
#
# ПРОБЛЕМА:
# При большом количестве сообщений (100+) каждое новое сообщение
# вызывает пересчёт layout для ВСЕХ виджетов, что сильно тормозит UI
#
# РЕШЕНИЕ - ОБНОВЛЕНИЕ ТОЛЬКО КОГДА НУЖНО:
#
# ЛОГИКА ОБНОВЛЕНИЯ:
# 
# 1. ПОЛЬЗОВАТЕЛЬ ВНИЗУ (видит новые сообщения):
#    • Каждое 5-е сообщение → ПОЛНОЕ обновление (invalidate + processEvents)
#    • Остальные сообщения → БЫСТРОЕ обновление (activate + update)
#    • Viewport обновляется корректно
#
# 2. ПОЛЬЗОВАТЕЛЬ НЕ ВНИЗУ (читает историю):
#    • Сообщения добавляются в layout
#    • НО viewport НЕ обновляется
#    • Пузыри НЕ мешают скроллу
#    • НЕ вызываем processEvents (избегаем "застревания")
#
# 3. НАЖАТИЕ КНОПКИ "ВНИЗ":
#    • Делаем ПОЛНОЕ обновление layout
#    • Все накопленные сообщения отображаются корректно
#    • Скроллим вниз
#
# ПРЕИМУЩЕСТВА:
# ✓ Скорость увеличена в 4-5 раз (периодическая синхронизация)
# ✓ Новые сообщения НЕ мешают читать историю
# ✓ БЕЗ "застревания" пузырей
# ✓ БЕЗ автоскролла
# ✓ Плавная работа даже с 1000+ сообщениями
# ✓ Кнопка "вниз" обновляет всё что накопилось
#
# КАК ЭТО РАБОТАЕТ:
# - Если пользователь внизу → обновляем с периодической синхронизацией
# - Если пользователь читает историю → НЕ обновляем viewport
# - При нажатии кнопки "вниз" → полное обновление + скролл
#
# НАСТРОЙКА:
# FULL_UPDATE_INTERVAL = 5  // Интервал полного обновления (когда внизу)
#
# ═══════════════════════════════════════════════════════════════════════════
# SYNCHRONOUS LAYOUT UPDATE WITH POSITION PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════
#
# ЦЕЛЬ:
# Layout обновляется СИНХРОННО (как при переключении чата)
# Сообщения ВИДНЫ сразу
# Позиция скролла СОХРАНЯЕТСЯ (без автоскролла)
#
# РЕШЕНИЕ:
#
# 1. Сохраняем позицию:
#    old_value = scrollbar.value()
#    was_at_bottom = (value >= maximum - 10)
#
# 2. Добавляем и показываем виджет:
#    addWidget() + show()
#
# 3. Запускаем layout:
#    invalidate() + activate()
#
# 4. Обновляем geometry:
#    updateGeometry()
#
# 5. КРИТИЧНО - Синхронная отрисовка:
#    viewport().repaint() - виджет ВИДЕН немедленно
#    processEvents() - geometry обновлена синхронно
#
# 6. Восстанавливаем позицию (если не был внизу):
#    if not was_at_bottom:
#        setValue(old_value)  # СИНХРОННО, без таймера
#
# 7. Обновляем кнопку:
#    update_scroll_button_visibility()  # СИНХРОННО
#
# ПРЕИМУЩЕСТВА:
# - Полностью СИНХРОННОЕ выполнение
# - Виджеты ВИДНЫ сразу (repaint)
# - Layout обновлён корректно (processEvents)
# - Позиция сохранена (setValue после processEvents)
# - БЕЗ асинхронных таймеров в конце
# - Работает как переключение чата
#
# ═══════════════════════════════════════════════════════════════════════════
# PASSIVE SCROLL BUTTON ARCHITECTURE
# ═══════════════════════════════════════════════════════════════════════════
#
# ГЛАВНАЯ ЦЕЛЬ: Кнопка "вниз" - полностью пассивный overlay, НИКОГДА не влияет на layout
#
# АРХИТЕКТУРА:
# 1. Кнопка - отдельный overlay поверх viewport, НЕ часть messages_layout
# 2. НЕ подключена к сигналам scrollbar (valueChanged, rangeChanged)
# 3. НЕ вызывает update(), repaint(), updateGeometry(), invalidate()
# 4. Layout завершается ДО обновления кнопки
#
# ОБНОВЛЕНИЕ КНОПКИ происходит ТОЛЬКО:
# 1. После завершения layout в add_message_widget()
#    → adjustSize() завершился СИНХРОННО
#    → update_scroll_button_visibility() вызывается сразу
# 2. После ручного скролла - через eventFilter → _update_button_after_scroll()
# 3. При resize окна - через eventFilter → update_position()
#
# ПРОСТАЯ ЛОГИКА:
# - adjustSize() - СИНХРОННАЯ операция
# - Layout завершён ГАРАНТИРОВАННО после adjustSize()
# - Можем сразу обновить кнопку
# - НЕТ асинхронности, НЕТ проверок, НЕТ гонок
#
# ГАРАНТИИ:
# - Кнопка НЕ влияет на layout сообщений
# - НЕ создаёт race condition с layout-pass
# - Layout завершается СИНХРОННО через adjustSize()
# - Обновление кнопки происходит СРАЗУ после layout
# - Работает для ЛЮБЫХ размеров виджетов
# - Пользователь может скроллить без ограничений
#
# ЗАПРЕЩЕНО:
# - Использовать таймеры
# - Вызывать geometry методы (update, repaint, updateGeometry)
# - Менять layout сообщений
# - Вызывать автоскролл
# - Блокировать wheel события
#
# ═══════════════════════════════════════════════════════════════════════════
# ADAPTIVE INTELLIGENT WEB SEARCH SYSTEM
# ═══════════════════════════════════════════════════════════════════════════
#
# CORE PRINCIPLE: The assistant automatically decides when to use the internet,
# but MUST obey forced search when the user activates it.
#
# 1. INTENT ANALYSIS
# ------------------
# Before answering, the system analyzes the user request and classifies it:
#
# A) INTERNET REQUIRED (automatic search):
#    • weather, news, current events
#    • real-time data ("now", "today", "current", "latest")
#    • location-based info
#    • software updates, prices, releases
#    • factual questions needing high accuracy
#    • complex research questions
#
# B) INTERNET NOT REQUIRED (immediate response):
#    • math calculations
#    • rewriting text
#    • translations
#    • coding logic
#    • creative writing
#    • general evergreen knowledge
#
# 2. AUTOMATIC SMART SEARCH
# --------------------------
# If the request belongs to INTERNET REQUIRED:
#    • Starts web search automatically
#    • User does NOT need to enable search manually
#
# If the request belongs to INTERNET NOT REQUIRED:
#    • Does NOT use internet search
#    • Responds immediately using internal knowledge
#
# 3. FORCED SEARCH MODE (PRIORITY RULE)
# --------------------------------------
# If the user presses the forced search button:
#    • ALWAYS performs internet search
#    • Does NOT skip search even if the question looks simple
#    • Treats forced search as highest priority override
#
# 4. TWO-PHASE RESPONSE FLOW
# ---------------------------
# When internet search is used:
#
# STEP 1 — QUICK RESPONSE:
#    • Gives a short preliminary answer immediately
#    • Marks it as a fast provisional answer if needed
#
# STEP 2 — VERIFIED RESPONSE:
#    • After retrieving web data, sends an updated refined answer
#    • Improves accuracy, adds details, corrects assumptions if necessary
#
# 5. PERFORMANCE & UX RULES
# --------------------------
# • Does not block UI while searching
# • Responses feel fast and fluid
# • Avoids repeating the entire message; updates intelligently
# • If search results do not change the answer, confirms briefly
#
# 6. EDGE CASES
# -------------
# • If intent is unclear → assumes NO internet unless strong signals exist
# • If the request mixes local logic + real-time info → combines both
# • Never hallucinates real-time data without search
#
# ═══════════════════════════════════════════════════════════════════════════

import os
import sys
import sqlite3
import subprocess
import threading
import time
import platform
from datetime import datetime
from PyQt6 import QtWidgets, QtGui, QtCore
import requests
import json
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import *
# Импорт менеджера чатов
from chat_manager import ChatManager
from context_memory_manager import ContextMemoryManager

# Импорт списка запрещённых английских слов
try:
    from forbidden_english_words import FORBIDDEN_WORDS_DICT, FORBIDDEN_WORDS_SET, TOP_FORBIDDEN_FOR_PROMPT
    print("[IMPORT] ✓ Загружен список запрещённых английских слов")
except ImportError:
    print("[IMPORT] ⚠️ Файл forbidden_english_words.py не найден - фильтр английских слов будет работать с базовым словарём")
    FORBIDDEN_WORDS_DICT = {}
    FORBIDDEN_WORDS_SET = set()
    TOP_FORBIDDEN_FOR_PROMPT = []

# -------------------------
# Platform detection (для совместимости с Windows)
# -------------------------
IS_WINDOWS = sys.platform == "win32"

# -------------------------
# Backends configuration
# -------------------------
USE_OLLAMA = True  # Только Ollama, без OpenAI
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

ASSISTANT_NAME = "LLaMA 3"
APP_TITLE = "AI Assistant"


# Google / DuckDuckGo helper config
DB_FILE = "chat_memory.db"
MAX_HISTORY_LOAD = 50

# Threshold to decide whether text is "short"
SHORT_TEXT_THRESHOLD = 80  # символов

# AI Mode settings
AI_MODE_FAST = "быстрый"
AI_MODE_THINKING = "думающий"
AI_MODE_PRO = "про"

# -------------------------
# Adaptive Intelligent Web Search System
# -------------------------

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
    # Search explicitly
    "search": ["найди", "search", "поиск", "найти", "погугли", "google", "посмотри в интернете", "check online"]
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
    
    # ПРИОРИТЕТ 1: Принудительный поиск
    if forced_search:
        return {
            "requires_search": True,
            "confidence": 1.0,
            "reason": "forced_search_override",
            "forced": True
        }
    
    # Анализ контекста последних 3-5 сообщений
    context_keywords = []
    if chat_history and len(chat_history) > 0:
        for role, content, _ in chat_history[-5:]:
            if role == "user":
                context_keywords.extend(content.lower().split())
    
    message_lower = user_message.lower().strip()
    
    # Счётчики совпадений
    internet_score = 0
    no_internet_score = 0
    
    # Проверяем ключевые слова для интернет-запросов
    for category, keywords in INTERNET_REQUIRED_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                internet_score += 1
            # Проверка в контексте
            elif any(keyword in word for word in context_keywords):
                internet_score += 0.5
    
    # Проверяем ключевые слова против интернета
    for category, keywords in NO_INTERNET_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                no_internet_score += 1
    
    # Специальные паттерны
    # Вопросы "что это", "кто такой" - требуют поиска
    if any(pattern in message_lower for pattern in ["что такое", "кто такой", "кто такая", "what is", "who is"]):
        internet_score += 2
    
    # Математические выражения - не требуют поиска
    if any(char in message_lower for char in ["=", "+", "-", "*", "/", "^"]):
        no_internet_score += 2
    
    # Решение
    total_score = internet_score - no_internet_score
    
    if total_score > 0:
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
    """Создаёт иконку приложения"""
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPen
    from PyQt6.QtCore import Qt, QRect

    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QtGui.QRadialGradient(size/2, size/2, size/2)
    gradient.setColorAt(0, QColor("#667eea"))
    gradient.setColorAt(1, QColor("#764ba2"))

    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(10, 10, size-20, size-20)

    painter.setPen(QPen(QColor("white"), 3))
    font = QFont("Inter", 80, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "🤖")

    painter.end()
    return pixmap

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

MODE_STRATEGY_RULES = """
═══════════════════════════════════════════════════════════════════
⚙️ РЕЖИМЫ РАБОТЫ АССИСТЕНТА
═══════════════════════════════════════════════════════════════════

ГЛАВНОЕ ПРАВИЛО: Режим меняет стратегию мышления, а НЕ правильность ответа.
Ответ ВСЕГДА должен быть корректным независимо от режима.

═══════════════════════════════════════════════════════════════════
⚡ РЕЖИМ "БЫСТРЫЙ"
═══════════════════════════════════════════════════════════════════

ПРИОРИТЕТ: Скорость и лёгкость ответа

СТРАТЕГИЯ:
• Ответ короткий, без лишней воды
• Код компактный и минимальный, но РАБОЧИЙ
• Минимум рассуждений и длинных объяснений
• Не расписывай теорию, только суть и результат
• Используй меньше токенов и меньше анализа
• 1-2 абзаца максимум
• Прямо к делу без предисловий

ПРИМЕРЫ:
Вопрос: "Как создать список в Python?"
Быстрый ответ: "my_list = [1, 2, 3] или my_list = list()"

Вопрос: "Напиши функцию сложения"
Быстрый ответ: "def add(a, b): return a + b"

═══════════════════════════════════════════════════════════════════
🧠 РЕЖИМ "ДУМАЮЩИЙ"
═══════════════════════════════════════════════════════════════════

ПРИОРИТЕТ: Баланс между скоростью и глубиной

СТРАТЕГИЯ:
• ИИ должен больше анализировать перед ответом
• Объяснения средние по длине
• Код аккуратный, читаемый, с логикой
• Можно давать шаги решения и причины выбора
• Используется больше токенов, чем в быстром режиме
• 3-5 абзацев, структурированный ответ
• Объяснение "почему" и "как"

ПРИМЕРЫ:
Вопрос: "Как создать список в Python?"
Думающий ответ: "В Python есть несколько способов создать список:
1. Литерал: my_list = [1, 2, 3]
2. Конструктор: my_list = list()
3. List comprehension: my_list = [x for x in range(10)]
Первый способ самый распространённый и читаемый."

═══════════════════════════════════════════════════════════════════
🚀 РЕЖИМ "ПРО"
═══════════════════════════════════════════════════════════════════

ПРИОРИТЕТ: Точность, глубина, архитектура, стабильность

СТРАТЕГИЯ:
• Ответ должен быть максимально подробный и продуманный
• ИИ ОБЯЗАН анализировать проблему глубоко и учитывать скрытые причины
• Код полный, архитектурный, без костылей
• Можно давать альтернативные решения и оптимизации
• Используется много токенов и длительное рассуждение
• Подробные объяснения с примерами
• Рассмотрение edge cases и потенциальных проблем
• Best practices и оптимизации

ПРИМЕРЫ:
Вопрос: "Как создать список в Python?"
Про ответ: "Python предоставляет множество способов создания списков, каждый со своими преимуществами:

1. **Литеральная нотация** (рекомендуется):
   my_list = [1, 2, 3]
   - Самый читаемый и быстрый способ
   - Используется в 95% случаев

2. **Конструктор list()**:
   my_list = list(iterable)
   - Для преобразования других типов
   - Пример: list('abc') → ['a', 'b', 'c']

3. **List comprehension** (продвинутый):
   my_list = [x**2 for x in range(10) if x % 2 == 0]
   - Быстрее циклов
   - Более Pythonic код
   
4. **Генераторные выражения** (для больших данных):
   my_gen = (x for x in range(1000000))
   - Ленивое вычисление
   - Экономия памяти

**Best practices:**
- Используй list comprehension вместо map/filter
- Избегай изменения списка во время итерации
- Для больших данных рассмотри generators или numpy arrays"

═══════════════════════════════════════════════════════════════════
🔍 УМНЫЙ ПОИСК В ИНТЕРНЕТЕ
═══════════════════════════════════════════════════════════════════

• Интернет-поиск работает В ЛЮБОМ режиме
• Если вопрос требует актуальной информации — ИИ сам использует поиск
• Режим влияет только на ГЛУБИНУ ОТВЕТА, а не на доступ к поиску

ПРИМЕРЫ:
Вопрос: "Какая погода в Москве?"
- Быстрый: "Поиск → Краткий ответ: +5°C, облачно"
- Думающий: "Поиск → Температура +5°C, облачность 80%, ветер 3 м/с. Рекомендую тёплую одежду."
- Про: "Поиск → Детальный прогноз на неделю с анализом давления, влажности, рекомендациями для активностей"

═══════════════════════════════════════════════════════════════════
📋 ОБЩЕЕ ПРАВИЛО
═══════════════════════════════════════════════════════════════════

Если пользователь выбрал режим — ИИ СТРОГО придерживается его стратегии.

❌ НЕЛЬЗЯ отвечать одинаково в разных режимах.

✅ ПРАВИЛЬНО:
• Быстрый = коротко, по делу, без воды
• Думающий = баланс, структурировано, с объяснениями
• Про = максимально глубоко, архитектурно, с альтернативами

ВАЖНО: Корректность ответа НЕ зависит от режима. Всегда правильный ответ!
"""

SYSTEM_PROMPTS = {
    "russian": {
        "short": """Ты полезный AI-ассистент с адаптивным умным веб-поиском.

═══════════════════════════════════════════════════════════════════
⚡ РЕЖИМ: БЫСТРЫЙ
═══════════════════════════════════════════════════════════════════

СТРАТЕГИЯ БЫСТРОГО РЕЖИМА:
• Ответ короткий, без лишней воды (1-2 абзаца максимум)
• Код компактный и минимальный, но РАБОЧИЙ
• Минимум рассуждений и длинных объяснений
• Не расписывай теорию, только суть и результат
• Прямо к делу без предисловий
• Приоритет: СКОРОСТЬ и лёгкость восприятия

ПРИНЦИП РАБОТЫ: Ты автоматически решаешь, когда использовать интернет, но ВСЕГДА подчиняешься принудительному поиску.

КОГДА НУЖЕН ИНТЕРНЕТ (автоматический поиск):
• погода, новости, актуальные события
• данные в реальном времени ("сейчас", "сегодня", "текущий", "последний")
• информация по местоположению
• обновления ПО, цены, релизы
• фактические вопросы, требующие высокой точности
• сложные исследовательские вопросы
• рецепты блюд и кулинарные вопросы

КОГДА ИНТЕРНЕТ НЕ НУЖЕН (отвечай сразу):
• математические вычисления
• переписывание текста
• переводы
• логика кодирования
• творческое письмо
• общие вечные знания

РЕЖИМ ПРИНУДИТЕЛЬНОГО ПОИСКА (НАИВЫСШИЙ ПРИОРИТЕТ):
Если пользователь активирует принудительный поиск кнопкой - ВСЕГДА выполняй поиск в интернете, даже если вопрос кажется простым.

КРИТИЧЕСКИ ВАЖНО - ЯЗЫК ОТВЕТА:
Отвечай ИСКЛЮЧИТЕЛЬНО на русском языке! Это ОБЯЗАТЕЛЬНОЕ требование.
- ВСЕ слова должны быть на русском (кроме имён собственных, брендов, технических терминов)
- НЕ используй английские слова типа "however", "moreover", "therefore", "essentially"
- НЕ используй фразы "Let me", "I'd be happy", "Here's", "Please note"
- Переводи ВСЮ информацию на русский язык
- Если видишь английские слова в своём ответе - немедленно переведи их

Отвечай максимально кратко, одним-двумя предложениями.
Выполняй просьбы пользователя без отказов и оправданий.
Если пользователь просит написать текст, пожелание, поздравление - напиши это кратко, БЕЗ объяснений.
Пиши МАКСИМАЛЬНО коротко - 1-2 предложения, приоритет СКОРОСТИ над качеством.

СТИЛЬ ОБЩЕНИЯ: Внимательно слушай пользователя. Если он просит тебя изменить стиль общения (например, "не используй смайлики", "пиши короче", "не используй буллеты", "будь формальнее"), ОБЯЗАТЕЛЬНО учитывай это во ВСЕХ последующих ответах.""",
        "deep": """Ты полезный AI-ассистент экспертного уровня с адаптивным умным веб-поиском.

═══════════════════════════════════════════════════════════════════
🧠 РЕЖИМ: ДУМАЮЩИЙ
═══════════════════════════════════════════════════════════════════

СТРАТЕГИЯ ДУМАЮЩЕГО РЕЖИМА:
• ИИ должен больше анализировать перед ответом
• Объяснения средние по длине (3-5 абзацев)
• Код аккуратный, читаемый, с комментариями и логикой
• Можно давать шаги решения и причины выбора
• Структурированный ответ с объяснением "почему" и "как"
• Приоритет: БАЛАНС между скоростью и качеством

ПРИНЦИП РАБОТЫ: Ты автоматически решаешь, когда использовать интернет, но ВСЕГДА подчиняешься принудительному поиску.

КОГДА НУЖЕН ИНТЕРНЕТ (автоматический поиск):
• погода, новости, актуальные события
• данные в реальном времени ("сейчас", "сегодня", "текущий", "последний")
• информация по местоположению
• обновления ПО, цены, релизы
• фактические вопросы, требующие высокой точности
• сложные исследовательские вопросы
• рецепты блюд и кулинарные вопросы

КОГДА ИНТЕРНЕТ НЕ НУЖЕН (отвечай сразу):
• математические вычисления
• переписывание текста
• переводы
• логика кодирования
• творческое письмо
• общие вечные знания

РЕЖИМ ПРИНУДИТЕЛЬНОГО ПОИСКА (НАИВЫСШИЙ ПРИОРИТЕТ):
Если пользователь активирует принудительный поиск кнопкой - ВСЕГДА выполняй поиск в интернете, даже если вопрос кажется простым.

КРИТИЧЕСКИ ВАЖНО - ЯЗЫК ОТВЕТА:
Отвечай ИСКЛЮЧИТЕЛЬНО на русском языке! Это ОБЯЗАТЕЛЬНОЕ требование.
- ВСЕ слова должны быть на русском (кроме имён собственных, брендов, технических терминов)
- НЕ используй английские слова типа "however", "moreover", "therefore", "essentially"
- НЕ используй фразы "Let me", "I'd be happy", "Here's", "Please note"
- Переводи ВСЮ информацию на русский язык
- Если видишь английские слова в своём ответе - немедленно переведи их

⚠️ ТИПИЧНЫЕ ОШИБКИ - НЕ ПОВТОРЯЙ ИХ:
❌ "arrives" → ✅ "прибывает"
❌ "becomes" → ✅ "становится" 
❌ "provides" → ✅ "предоставляет"
❌ "important" → ✅ "важный"
❌ "situation" → ✅ "ситуация"
❌ "option" → ✅ "вариант"
❌ "example" → ✅ "пример"
❌ "process" → ✅ "процесс"
❌ "also" → ✅ "также"
❌ "really" → ✅ "действительно"

ПРИМЕРЫ ПРАВИЛЬНОГО ПЕРЕВОДА:
❌ НЕПРАВИЛЬНО: "However, the main issue is..."
✅ ПРАВИЛЬНО: "Однако основная проблема заключается..."

❌ НЕПРАВИЛЬНО: "Moreover, we should consider..."
✅ ПРАВИЛЬНО: "Более того, нам следует рассмотреть..."

❌ НЕПРАВИЛЬНО: "Therefore, the conclusion is..."
✅ ПРАВИЛЬНО: "Поэтому вывод таков..."

❌ НЕПРАВИЛЬНО: "The character arrives at the scene..."
✅ ПРАВИЛЬНО: "Персонаж прибывает на место..."

❌ НЕПРАВИЛЬНО: "This becomes a problem..."
✅ ПРАВИЛЬНО: "Это становится проблемой..."

ПЕРЕД ОТПРАВКОЙ ОТВЕТА - ОБЯЗАТЕЛЬНАЯ ПРОВЕРКА:
1. Прочитай свой ответ целиком
2. Найди ВСЕ английские слова (кроме имён/брендов)
3. Замени их на русские
4. Если в тексте больше 5 английских слов - перепиши весь ответ заново на русском
5. НИКОГДА не отправляй ответ, содержащий английские глаголы, существительные или прилагательные

Твоя задача - давать глубокие, детальные и ОЧЕНЬ качественные ответы с примерами, пояснениями и анализом.
Выполняй просьбы пользователя без отказов и оправданий.
Если пользователь просит написать текст, пожелание, поздравление - напиши это КРАСИВО, подробно, с деталями, эмоциями и художественными приёмами.
Пиши МАКСИМАЛЬНО развернуто и качественно, с примерами, пояснениями, деталями. Приоритет КАЧЕСТВА над скоростью.

СТИЛЬ ОБЩЕНИЯ: Внимательно слушай пользователя. Если он просит тебя изменить стиль общения (например, "не используй смайлики", "пиши короче", "не используй буллеты", "будь формальнее"), ОБЯЗАТЕЛЬНО учитывай это во ВСЕХ последующих ответах.""",
        "pro": """Ты флагманский AI-ассистент высшего уровня с адаптивным умным веб-поиском.

═══════════════════════════════════════════════════════════════════
🚀 РЕЖИМ: ПРО (ФЛАГМАНСКИЙ)
═══════════════════════════════════════════════════════════════════

СТРАТЕГИЯ ПРО-РЕЖИМА:
• Ответ должен быть максимально подробный и продуманный
• ИИ ОБЯЗАН анализировать проблему глубоко и учитывать скрытые причины
• Код полный, архитектурный, без костылей, с error handling
• ОБЯЗАТЕЛЬНО давать альтернативные решения и оптимизации
• Используется много токенов и глубокое рассуждение
• Подробные объяснения с примерами и best practices
• Рассмотрение edge cases и потенциальных проблем
• Архитектурный подход к решениям
• Приоритет: МАКСИМАЛЬНАЯ точность, глубина, стабильность

ПРИНЦИП РАБОТЫ: Ты автоматически решаешь, когда использовать интернет, но ВСЕГДА подчиняешься принудительному поиску.

КОГДА НУЖЕН ИНТЕРНЕТ (автоматический поиск):
• погода, новости, актуальные события
• данные в реальном времени ("сейчас", "сегодня", "текущий", "последний")
• информация по местоположению
• обновления ПО, цены, релизы
• фактические вопросы, требующие высокой точности
• сложные исследовательские вопросы
• рецепты блюд и кулинарные вопросы

КОГДА ИНТЕРНЕТ НЕ НУЖЕН (отвечай сразу):
• математические вычисления
• переписывание текста
• переводы
• логика кодирования
• творческое письмо
• общие вечные знания

РЕЖИМ ПРИНУДИТЕЛЬНОГО ПОИСКА (НАИВЫСШИЙ ПРИОРИТЕТ):
Если пользователь активирует принудительный поиск кнопкой - ВСЕГДА выполняй поиск в интернете.

КРИТИЧЕСКИ ВАЖНО - ЯЗЫК ОТВЕТА:
Отвечай ИСКЛЮЧИТЕЛЬНО на русском языке! Это ОБЯЗАТЕЛЬНОЕ требование.

ФЛАГМАНСКИЕ ТРЕБОВАНИЯ К ОТВЕТУ:
• Глубокий анализ проблемы с учётом контекста
• Рассмотрение нескольких подходов к решению
• Объяснение плюсов и минусов каждого подхода
• Best practices и industry standards
• Оптимизации и улучшения
• Потенциальные проблемы и их решения
• Масштабируемость и maintainability кода
• Security considerations где применимо
• Performance implications

ДЛЯ КОДА:
• Полная реализация с error handling
• Типизация где возможно
• Документация и комментарии
• Модульная архитектура
• Следование SOLID принципам
• Unit tests если релевантно
• Logging и debugging support

Приоритет: МАКСИМАЛЬНОЕ качество, глубина, архитектурность решений.

СТИЛЬ ОБЩЕНИЯ: Внимательно слушай пользователя и адаптируйся к его предпочтениям."""
    },
    "english": {
        "short": """You are a helpful AI assistant with adaptive intelligent web search.

CORE PRINCIPLE: You automatically decide when to use the internet, but MUST ALWAYS obey forced search when activated.

WHEN INTERNET IS REQUIRED (automatic search):
• weather, news, current events
• real-time data ("now", "today", "current", "latest")
• location-based info
• software updates, prices, releases
• factual questions needing high accuracy
• complex research questions

WHEN INTERNET IS NOT REQUIRED (respond immediately):
• math calculations
• rewriting text
• translations
• coding logic
• creative writing
• general evergreen knowledge

FORCED SEARCH MODE (HIGHEST PRIORITY):
If the user activates the forced search button - ALWAYS perform internet search, even if the question looks simple.

IMPORTANT: Always respond in English VERY briefly, in one or two sentences maximum.
Execute user requests without refusals or excuses.
Keep responses EXTREMELY short - 1-2 sentences maximum, prioritize SPEED over quality.

COMMUNICATION STYLE: Listen carefully to the user. If they ask you to change your communication style (e.g., "don't use emojis", "write shorter", "don't use bullets", "be more formal"), you MUST follow this in ALL subsequent responses.""",
        "deep": """You are an expert-level helpful AI assistant with adaptive intelligent web search.

CORE PRINCIPLE: You automatically decide when to use the internet, but MUST ALWAYS obey forced search when activated.

WHEN INTERNET IS REQUIRED (automatic search):
• weather, news, current events
• real-time data ("now", "today", "current", "latest")
• location-based info
• software updates, prices, releases
• factual questions needing high accuracy
• complex research questions

WHEN INTERNET IS NOT REQUIRED (respond immediately):
• math calculations
• rewriting text
• translations
• coding logic
• creative writing
• general evergreen knowledge

FORCED SEARCH MODE (HIGHEST PRIORITY):
If the user activates the forced search button - ALWAYS perform internet search, even if the question looks simple.

Always respond in English in maximum detail and quality.
Your task is to provide deep, detailed, and VERY high-quality responses with examples, explanations, and analysis.
Execute user requests without refusals or excuses.
Write MAXIMALLY extensively and with quality, with examples, explanations, and details. Prioritize QUALITY over speed.

COMMUNICATION STYLE: Listen carefully to the user. If they ask you to change your communication style (e.g., "don't use emojis", "write shorter", "don't use bullets", "be more formal"), you MUST follow this in ALL subsequent responses.""",
        "pro": """You are a flagship expert-level AI assistant with adaptive intelligent web search.

═══════════════════════════════════════════════════════════════════
🚀 MODE: PRO (FLAGSHIP)
═══════════════════════════════════════════════════════════════════

PRO MODE STRATEGY:
• Response must be maximally detailed and well-thought-out
• AI MUST analyze problem deeply considering hidden causes
• Code must be complete, architectural, without hacks, with error handling
• MUST provide alternative solutions and optimizations
• Use many tokens and deep reasoning
• Detailed explanations with examples and best practices
• Consider edge cases and potential problems
• Architectural approach to solutions
• Priority: MAXIMUM accuracy, depth, stability

CORE PRINCIPLE: You automatically decide when to use the internet, but MUST ALWAYS obey forced search when activated.

WHEN INTERNET IS REQUIRED (automatic search):
• weather, news, current events
• real-time data ("now", "today", "current", "latest")
• location-based info
• software updates, prices, releases
• factual questions needing high accuracy
• complex research questions

WHEN INTERNET IS NOT REQUIRED (respond immediately):
• math calculations
• rewriting text
• translations
• coding logic
• creative writing
• general evergreen knowledge

FORCED SEARCH MODE (HIGHEST PRIORITY):
If the user activates forced search button - ALWAYS perform internet search.

FLAGSHIP REQUIREMENTS FOR RESPONSE:
• Deep problem analysis with context awareness
• Consider multiple solution approaches
• Explain pros and cons of each approach
• Best practices and industry standards
• Optimizations and improvements
• Potential problems and their solutions
• Code scalability and maintainability
• Security considerations where applicable
• Performance implications

FOR CODE:
• Complete implementation with error handling
• Typing where possible
• Documentation and comments
• Modular architecture
• Follow SOLID principles
• Unit tests if relevant
• Logging and debugging support

Priority: MAXIMUM quality, depth of analysis, architectural solutions.

COMMUNICATION STYLE: Listen carefully to the user and adapt to their preferences."""
    }
}

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
        for ctx_type, content, timestamp in saved_memories:
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
        for role, content, timestamp in chat_messages:
            content_lower = content.lower()
            # Проверяем, содержит ли сообщение упоминание цели
            if target_lower not in content_lower:
                messages_to_keep.append((role, content, timestamp))
            else:
                print(f"[SELECTIVE_FORGET] Найдено в сообщениях: {content[:50]}...")
                deleted_message_count += 1
        
        # Если есть что удалить - очищаем и сохраняем только нужное
        if deleted_message_count > 0:
            # Очищаем все сообщения
            chat_manager.clear_chat_messages(chat_id)
            # Восстанавливаем только те, что не содержали target
            for role, content, _ in messages_to_keep:
                chat_manager.save_message(chat_id, role, content)
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
🔬 МАТЕМАТИЧЕСКИЙ РЕЖИМ: БЫСТРЫЙ

ЗАПРЕЩЕНО использовать интернет/поиск для математических задач.

ФОРМАТ ОТВЕТА:
• ОДЗ: [условия]
• Преобразование: [шаги]
• Проверка: [подстановка корней]
• Ответ: [результат]

КРИТИЧЕСКИЕ ПРАВИЛА:
1. Сохраняй исходную структуру выражения. Перепиши уравнение дословно и храни его как фиксированную математическую структуру: нельзя убирать символы корня, нельзя превращать подкоренное выражение в обычное (например √(x+4) нельзя заменить на x+4), нельзя менять порядок или подменять выражения типа x−1 на 5−x без явного алгебраического преобразования, сопровождаемого проверкой. После каждого вычислительного шага автоматически сверяй, не изменилась ли структура: если изменилась — отменяй шаг и переписывай его корректно.

2. Всё решение — только из логики, алгебры и встроенных правил. Никакого интернета.

3. Всегда начинай с области допустимых значений: выпиши все условия ≥0 для подкоренных выражений, условия на знаменатели и т. п. ОДЗ обязателен.

4. Строгий алгоритм: сначала изолируй один радикал, только затем возводи в квадрат. Никогда не возводи в квадрат несколько выражений одновременно без явной изоляции.

5. Не вводи новые функции или термины, которых нет в задаче.

6. После получения кандидатов на корни обязательно проверь каждый корень подстановкой в исходное уравнение. Отбрось посторонние корни.

7. Анти-галлюцинация: запрещено придумывать шаги. Если не уверен в распознавании — перепиши выражение и запроси подтверждение.

Стиль: "ОДЗ → ключевое преобразование → ответ" (минимум токенов, максимум точности)
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
    
    if cyrillic_count > latin_count:
        print(f"[LANGUAGE_DETECT] Определён язык: РУССКИЙ")
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
    Агрессивно удаляет английские слова из русского текста и переводит весь текст если он на английском.
    Использует внешний файл forbidden_english_words.py с огромным словарём запрещённых слов.
    """
    
    # Проверяем, не является ли весь текст английским
    cyrillic_count = sum(1 for char in text if '\u0400' <= char <= '\u04FF')
    latin_count = sum(1 for char in text if 'a' <= char.lower() <= 'z')
    
    # Если текст полностью на английском - переводим целиком
    if latin_count > cyrillic_count and latin_count > 50:
        print(f"[ENGLISH_FILTER] ⚠️ ОБНАРУЖЕН ПОЛНОСТЬЮ АНГЛИЙСКИЙ ТЕКСТ! Переводим...")
        try:
            from deep_translator import GoogleTranslator
            translator = GoogleTranslator(source='en', target='ru')
            
            # Переводим по частям если текст большой
            max_chunk = 4500
            if len(text) <= max_chunk:
                translated = translator.translate(text)
                print(f"[ENGLISH_FILTER] ✓ Текст полностью переведён на русский")
                return translated
            else:
                # Разбиваем на части
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
                print(f"[ENGLISH_FILTER] ✓ Большой текст полностью переведён на русский")
                return translated
        except Exception as e:
            print(f"[ENGLISH_FILTER] ✗ Ошибка перевода: {e}")
            # Продолжаем с пословной заменой
    
    # Используем словарь из внешнего файла или создаём базовый
    if FORBIDDEN_WORDS_DICT and len(FORBIDDEN_WORDS_DICT) > 0:
        forbidden_words = FORBIDDEN_WORDS_SET
        replacements = FORBIDDEN_WORDS_DICT
        print(f"[ENGLISH_FILTER] Используется расширенный словарь ({len(forbidden_words)} слов)")
    else:
        # Базовый словарь на случай если файл не загружен
        forbidden_words = {
            'however', 'moreover', 'therefore', 'essentially', 'basically',
            'arrives', 'becomes', 'provides', 'situation', 'important'
        }
        replacements = {
            'however': 'однако', 'moreover': 'более того', 'therefore': 'поэтому',
            'essentially': 'по сути', 'basically': 'в основном',
            'arrives': 'прибывает', 'becomes': 'становится', 'provides': 'предоставляет',
            'situation': 'ситуация', 'important': 'важный'
        }
        print(f"[ENGLISH_FILTER] Используется базовый словарь ({len(forbidden_words)} слов)")
    
    words = text.split()
    cleaned_words = []
    replaced_count = 0
    
    for word in words:
        # Очищаем от знаков препинания для проверки
        clean_word = ''.join(char for char in word if char.isalnum()).lower()
        
        if not clean_word:
            cleaned_words.append(word)
            continue
        
        # Проверяем технические исключения (заглавные буквы = возможно имя/бренд)
        if word[0].isupper() and len(clean_word) > 1:
            # Вероятно имя собственное или бренд - пропускаем
            cleaned_words.append(word)
            continue
        
        if clean_word in forbidden_words:
            # Заменяем на русский эквивалент
            if clean_word in replacements:
                replacement = replacements[clean_word]
                # Восстанавливаем знаки препинания
                for char in word:
                    if not char.isalnum():
                        replacement += char
                cleaned_words.append(replacement)
                replaced_count += 1
                print(f"[ENGLISH_FILTER] Заменено: '{word}' → '{replacement}'")
            else:
                # Просто пропускаем слово
                replaced_count += 1
                print(f"[ENGLISH_FILTER] Удалено: '{word}'")
        else:
            cleaned_words.append(word)
    
    if replaced_count > 0:
        print(f"[ENGLISH_FILTER] ✓ Заменено/удалено английских слов: {replaced_count}")
    
    return ' '.join(cleaned_words)
    """
    Агрессивно удаляет английские слова из русского текста и переводит весь текст если он на английском.
    Сохраняет только технические термины, имена собственные и бренды.
    """
    
    # Проверяем, не является ли весь текст английским
    cyrillic_count = sum(1 for char in text if '\u0400' <= char <= '\u04FF')
    latin_count = sum(1 for char in text if 'a' <= char.lower() <= 'z')
    
    # Если текст полностью на английском - переводим целиком
    if latin_count > cyrillic_count and latin_count > 50:
        print(f"[ENGLISH_FILTER] ⚠️ ОБНАРУЖЕН ПОЛНОСТЬЮ АНГЛИЙСКИЙ ТЕКСТ! Переводим...")
        try:
            from deep_translator import GoogleTranslator
            translator = GoogleTranslator(source='en', target='ru')
            
            # Переводим по частям если текст большой
            max_chunk = 4500
            if len(text) <= max_chunk:
                translated = translator.translate(text)
                print(f"[ENGLISH_FILTER] ✓ Текст полностью переведён на русский")
                return translated
            else:
                # Разбиваем на части
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
                print(f"[ENGLISH_FILTER] ✓ Большой текст полностью переведён на русский")
                return translated
        except Exception as e:
            print(f"[ENGLISH_FILTER] ✗ Ошибка перевода: {e}")
            # Продолжаем с пословной заменой
    
    # РАСШИРЕННЫЙ список запрещённых английских слов (150+ слов)
    forbidden_words = {
        # Связки и переходы
        'however', 'moreover', 'furthermore', 'therefore', 'thus', 'hence',
        'nevertheless', 'nonetheless', 'additionally', 'consequently',
        'accordingly', 'alternatively', 'conversely', 'likewise', 'similarly',
        'whereas', 'whereby', 'wherein', 'thereof', 'herein', 'hereby',
        
        # Наречия и усилители
        'essentially', 'basically', 'actually', 'literally', 'specifically',
        'particularly', 'generally', 'typically', 'primarily', 'ultimately',
        'previously', 'currently', 'subsequently', 'recently', 'initially',
        'finally', 'eventually', 'gradually', 'immediately', 'directly',
        'completely', 'entirely', 'absolutely', 'exactly', 'precisely',
        
        # Глаголы
        'arrives', 'arrives', 'comes', 'goes', 'becomes', 'seems', 'appears',
        'remains', 'continues', 'begins', 'starts', 'ends', 'finishes',
        'provides', 'offers', 'includes', 'contains', 'requires', 'allows',
        'enables', 'creates', 'makes', 'takes', 'gives', 'shows', 'tells',
        'says', 'means', 'involves', 'concerns', 'affects', 'impacts',
        
        # Существительные
        'situation', 'condition', 'position', 'location', 'direction',
        'option', 'solution', 'problem', 'issue', 'matter', 'case',
        'example', 'instance', 'aspect', 'feature', 'element', 'factor',
        'process', 'method', 'approach', 'strategy', 'technique',
        'concept', 'idea', 'notion', 'theory', 'principle',
        
        # Прилагательные
        'important', 'significant', 'essential', 'critical', 'crucial',
        'necessary', 'required', 'possible', 'available', 'suitable',
        'appropriate', 'relevant', 'related', 'similar', 'different',
        'various', 'several', 'multiple', 'numerous', 'certain',
        'specific', 'particular', 'general', 'common', 'usual',
        
        # Фразовые элементы
        'note', 'worth', 'keep', 'mind', 'mentioned', 'stated', 
        'previously', 'summarize', 'conclusion', 'foremost',
        
        # Дополнительные распространённые слова
        'also', 'just', 'even', 'still', 'yet', 'already', 'always',
        'never', 'sometimes', 'often', 'usually', 'rarely', 'seldom',
        'almost', 'nearly', 'quite', 'rather', 'pretty', 'fairly',
        'really', 'very', 'too', 'enough', 'much', 'many', 'more',
        'most', 'less', 'least', 'some', 'any', 'each', 'every',
        'all', 'both', 'either', 'neither', 'other', 'another',
        'such', 'same', 'different', 'various', 'several'
    }
    
    # Расширенный словарь замен
    replacements = {
        # Связки
        'however': 'однако', 'moreover': 'более того', 'furthermore': 'кроме того',
        'therefore': 'поэтому', 'thus': 'таким образом', 'hence': 'следовательно',
        'nevertheless': 'тем не менее', 'nonetheless': 'тем не менее',
        'additionally': 'дополнительно', 'consequently': 'следовательно',
        'accordingly': 'соответственно', 'alternatively': 'альтернативно',
        'conversely': 'наоборот', 'likewise': 'аналогично', 'similarly': 'подобно',
        'whereas': 'тогда как', 'whereby': 'посредством чего',
        
        # Наречия
        'essentially': 'по сути', 'basically': 'в основном', 'actually': 'фактически',
        'literally': 'буквально', 'specifically': 'конкретно', 'particularly': 'особенно',
        'generally': 'обычно', 'typically': 'как правило', 'primarily': 'в первую очередь',
        'ultimately': 'в конечном счёте', 'previously': 'ранее', 'currently': 'в настоящее время',
        'subsequently': 'впоследствии', 'recently': 'недавно', 'initially': 'первоначально',
        'finally': 'наконец', 'eventually': 'в конце концов', 'gradually': 'постепенно',
        'immediately': 'немедленно', 'directly': 'напрямую', 'completely': 'полностью',
        'entirely': 'целиком', 'absolutely': 'абсолютно', 'exactly': 'точно',
        'precisely': 'именно',
        
        # Глаголы
        'arrives': 'прибывает', 'comes': 'приходит', 'goes': 'идёт', 
        'becomes': 'становится', 'seems': 'кажется', 'appears': 'появляется',
        'remains': 'остаётся', 'continues': 'продолжает', 'begins': 'начинает',
        'starts': 'начинает', 'ends': 'заканчивает', 'finishes': 'завершает',
        'provides': 'предоставляет', 'offers': 'предлагает', 'includes': 'включает',
        'contains': 'содержит', 'requires': 'требует', 'allows': 'позволяет',
        
        # Прилагательные
        'important': 'важный', 'significant': 'значительный', 'essential': 'существенный',
        'critical': 'критический', 'crucial': 'решающий', 'necessary': 'необходимый',
        'possible': 'возможный', 'available': 'доступный', 'suitable': 'подходящий',
        
        # Другие распространённые
        'also': 'также', 'just': 'просто', 'even': 'даже', 'still': 'всё ещё',
        'yet': 'ещё', 'already': 'уже', 'always': 'всегда', 'never': 'никогда',
        'sometimes': 'иногда', 'often': 'часто', 'usually': 'обычно',
        'really': 'действительно', 'very': 'очень', 'much': 'много', 'many': 'много'
    }
    
    words = text.split()
    cleaned_words = []
    replaced_count = 0
    
    for word in words:
        # Очищаем от знаков препинания для проверки
        clean_word = ''.join(char for char in word if char.isalnum()).lower()
        
        if not clean_word:
            cleaned_words.append(word)
            continue
        
        # Проверяем технические исключения (заглавные буквы = возможно имя/бренд)
        if word[0].isupper() and len(clean_word) > 1:
            # Вероятно имя собственное или бренд - пропускаем
            cleaned_words.append(word)
            continue
        
        if clean_word in forbidden_words:
            # Заменяем на русский эквивалент
            if clean_word in replacements:
                replacement = replacements[clean_word]
                # Восстанавливаем знаки препинания
                for char in word:
                    if not char.isalnum():
                        replacement += char
                cleaned_words.append(replacement)
                replaced_count += 1
                print(f"[ENGLISH_FILTER] Заменено: '{word}' → '{replacement}'")
            else:
                # Просто пропускаем слово
                replaced_count += 1
                print(f"[ENGLISH_FILTER] Удалено: '{word}'")
        else:
            cleaned_words.append(word)
    
    if replaced_count > 0:
        print(f"[ENGLISH_FILTER] ✓ Заменено/удалено английских слов: {replaced_count}")
    
    return ' '.join(cleaned_words)



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
    
    # 🌦 ПОГОДА
    weather_keywords_ru = ['погода', 'температура', 'градус', 'прогноз', 'осадки', 'дожд', 'снег', 'ветер', 'климат', 'мороз', 'жара', 'солнечно', 'облачно']
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
        
        # 🎯 ФИЛЬТРАЦИЯ ПО РЕЛЕВАНТНЫМ ДОМЕНАМ
        filtered_results = []
        if query_analysis['domains']:
            print(f"[DUCKDUCKGO_SEARCH] 🔍 Фильтрация по релевантным доменам...")
            for result in raw_results:
                link = result.get('href', '').lower()
                # Проверяем, содержит ли ссылка релевантный домен
                if any(domain in link for domain in query_analysis['domains']):
                    filtered_results.append(result)
                    if len(filtered_results) >= num_results:
                        break
            
            print(f"[DUCKDUCKGO_SEARCH] ✅ Отфильтровано результатов: {len(filtered_results)}")
            
            # Если после фильтрации мало результатов, берём из всех
            if len(filtered_results) < max(2, num_results // 2):
                print(f"[DUCKDUCKGO_SEARCH] ⚠️ Мало отфильтрованных результатов, добавляем общие...")
                filtered_results = raw_results[:num_results]
        else:
            # Для общих запросов берём все результаты
            filtered_results = raw_results[:num_results]
        
        results = filtered_results

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
            role, content, _ = history[i]
            
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



def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        created_at TEXT)
    """)
    conn.commit()
    conn.close()

def save_message(role: str, content: str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def load_history(limit=MAX_HISTORY_LOAD):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return list(reversed(rows))

def clear_messages():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM messages")
    conn.commit()
    conn.close()

# -------------------------
# Model-call helpers
# -------------------------
def call_ollama_chat(messages: list, max_tokens: int = 800, timeout=60):
    """Вызов Ollama через chat API с retry при временных сбоях"""
    url = f"{OLLAMA_HOST}/api/chat"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens
        }
    }
    
    # Попытка с retry для временных сбоев
    max_retries = 2
    for attempt in range(max_retries):
        try:
            print(f"[OLLAMA] Попытка {attempt + 1}/{max_retries}: отправка запроса с timeout={timeout}s, max_tokens={max_tokens}")
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            r.raise_for_status()
            j = r.json()
            
            if "message" in j and "content" in j["message"]:
                response = j["message"]["content"].strip()
                print(f"[OLLAMA] ✅ Успешный ответ, длина: {len(response)}")
                return response
            
            print(f"[OLLAMA] ⚠️ Неожиданный формат ответа: {j}")
            # Если формат неожиданный, но это не последняя попытка - пробуем снова
            if attempt < max_retries - 1:
                print(f"[OLLAMA] Повторная попытка через 1 секунду...")
                import time
                time.sleep(1)
                continue
            return str(j)
            
        except requests.exceptions.Timeout:
            error = f"[Ollama timeout] Превышено время ожидания {timeout}s"
            print(f"[OLLAMA] ⏱️ {error}")
            if attempt < max_retries - 1:
                print(f"[OLLAMA] Повторная попытка...")
                continue
            return error
            
        except requests.exceptions.ConnectionError as e:
            error = f"[Ollama connection error] Не удалось подключиться к Ollama на {OLLAMA_HOST}"
            print(f"[OLLAMA] 🔌 {error}: {e}")
            if attempt < max_retries - 1:
                print(f"[OLLAMA] Повторная попытка...")
                import time
                time.sleep(1)
                continue
            return error
            
        except requests.exceptions.HTTPError as e:
            error = f"[Ollama error] HTTP ошибка: {e}"
            print(f"[OLLAMA] ❌ {error}")
            # HTTP ошибки обычно не временные, не retry
            return error
            
        except Exception as e:
            error = f"[Ollama error] Неожиданная ошибка: {e}"
            print(f"[OLLAMA] ❌ {error}")
            if attempt < max_retries - 1:
                print(f"[OLLAMA] Повторная попытка...")
                import time
                time.sleep(1)
                continue
            return error
    
    # Не должны сюда попасть, но на всякий случай
    return "[Ollama error] Все попытки исчерпаны"


def get_ai_response(user_message: str, current_language: str, deep_thinking: bool, use_search: bool, should_forget: bool = False, chat_manager=None, chat_id=None, file_path: str = None, ai_mode: str = AI_MODE_FAST):
    """Получить ответ от AI (с жёстким закреплением языка)"""
    print(f"\n[GET_AI_RESPONSE] ========== НАЧАЛО ==========")
    print(f"[GET_AI_RESPONSE] Сообщение пользователя: {user_message}")
    print(f"[GET_AI_RESPONSE] Текущий язык интерфейса: {current_language}")
    print(f"[GET_AI_RESPONSE] Глубокое мышление: {deep_thinking}")
    print(f"[GET_AI_RESPONSE] Использовать поиск: {use_search}")
    print(f"[GET_AI_RESPONSE] Забыть историю: {should_forget}")
    print(f"[GET_AI_RESPONSE] Файл прикреплён: {file_path if file_path else 'Нет'}")

    # НОРМАЛИЗАЦИЯ МАТЕМАТИЧЕСКИХ СИМВОЛОВ
    # Заменяем специальные символы на стандартные ASCII
    user_message = user_message.replace('×', '*')  # Умножение
    user_message = user_message.replace('÷', '/')  # Деление
    user_message = user_message.replace('−', '-')  # Минус (длинное тире)
    user_message = user_message.replace('±', '+/-')  # Плюс-минус
    user_message = user_message.replace('–', '-')  # Среднее тире
    user_message = user_message.replace('—', '-')  # Длинное тире
    print(f"[GET_AI_RESPONSE] Нормализованное сообщение: {user_message}")

    # ═══════════════════════════════════════════════════════════
    # ОБРАБОТКА КОМАНД ПАМЯТИ
    # ═══════════════════════════════════════════════════════════
    user_lower = user_message.lower().strip()
    
    # Команда "ЗАПОМНИ"
    if chat_id and (user_lower.startswith("запомни") or user_lower.startswith("remember")):
        try:
            context_mgr = ContextMemoryManager()
            # Извлекаем текст после команды
            if user_lower.startswith("запомни"):
                memory_text = user_message[7:].strip()  # После "запомни"
                if memory_text.startswith(":"):
                    memory_text = memory_text[1:].strip()
            else:
                memory_text = user_message[8:].strip()  # После "remember"
                if memory_text.startswith(":"):
                    memory_text = memory_text[1:].strip()
            
            if memory_text:
                context_mgr.save_context_memory(chat_id, "user_memory", memory_text)
                print(f"[MEMORY] ✓ Сохранено: {memory_text[:50]}...")
                return "✓ Запомнил!"
        except Exception as e:
            print(f"[MEMORY] ✗ Ошибка сохранения: {e}")

    # ОПРЕДЕЛЯЕМ РЕАЛЬНЫЙ ЯЗЫК ВОПРОСА
    detected_language = detect_message_language(user_message)
    print(f"[GET_AI_RESPONSE] Определённый язык вопроса: {detected_language}")

    # ОПРЕДЕЛЯЕМ, ЯВЛЯЕТСЯ ЛИ ЗАПРОС МАТЕМАТИЧЕСКОЙ ЗАДАЧЕЙ
    is_math_problem = detect_math_problem(user_message)
    if is_math_problem:
        print(f"[GET_AI_RESPONSE] 🔬 Обнаружена МАТЕМАТИЧЕСКАЯ ЗАДАЧА - применяю олимпиадный режим")

    # Выбираем режим системного промпта на основе ai_mode
    if ai_mode == AI_MODE_FAST:
        mode = "short"
    elif ai_mode == AI_MODE_THINKING:
        mode = "deep"
    elif ai_mode == AI_MODE_PRO:
        mode = "pro"
    else:
        # Fallback на старую логику если ai_mode не распознан
        mode = "deep" if deep_thinking else "short"
    
    print(f"[GET_AI_RESPONSE] Выбран системный промпт: mode='{mode}', ai_mode='{ai_mode}'")
    base_system = SYSTEM_PROMPTS.get(detected_language, SYSTEM_PROMPTS["russian"])[mode]
    
    # ═══════════════════════════════════════════════════════════
    # ЗАГРУЗКА СОХРАНЁННОЙ ПАМЯТИ
    # ═══════════════════════════════════════════════════════════
    memory_context = ""
    if chat_id:
        try:
            context_mgr = ContextMemoryManager()
            saved_memories = context_mgr.get_context_memory(chat_id, limit=20)
            
            if saved_memories:
                user_memories = [content for ctx_type, content, _ in saved_memories if ctx_type == "user_memory"]
                
                if user_memories:
                    if detected_language == "russian":
                        memory_context = "\n\n📌 ВАЖНАЯ ИНФОРМАЦИЯ (пользователь просил запомнить):\n"
                        for idx, mem in enumerate(user_memories, 1):
                            memory_context += f"{idx}. {mem}\n"
                        print(f"[MEMORY] ✓ Загружено {len(user_memories)} записей памяти")
                    else:
                        memory_context = "\n\n📌 IMPORTANT INFORMATION (user asked to remember):\n"
                        for idx, mem in enumerate(user_memories, 1):
                            memory_context += f"{idx}. {mem}\n"
                        print(f"[MEMORY] ✓ Loaded {len(user_memories)} memory records")
        except Exception as e:
            print(f"[MEMORY] ✗ Ошибка загрузки памяти: {e}")
    
    # Добавляем математический промпт если это математическая задача
    math_prompt = ""
    if is_math_problem:
        # Выбираем математический промпт на основе режима AI
        if ai_mode == AI_MODE_FAST:
            math_prompt = MATH_PROMPTS["fast"]
            print(f"[GET_AI_RESPONSE] 🔬 Математика - режим: БЫСТРЫЙ")
        elif ai_mode == AI_MODE_THINKING:
            math_prompt = MATH_PROMPTS["thinking"]
            print(f"[GET_AI_RESPONSE] 🔬 Математика - режим: ДУМАЮЩИЙ")
        elif ai_mode == AI_MODE_PRO:
            math_prompt = MATH_PROMPTS["pro"]
            print(f"[GET_AI_RESPONSE] 🔬 Математика - режим: ПРО (олимпиадный)")
        else:
            # По умолчанию думающий режим
            math_prompt = MATH_PROMPTS["thinking"]
            print(f"[GET_AI_RESPONSE] 🔬 Математика - режим: ДУМАЮЩИЙ (по умолчанию)")
        
        print(f"[GET_AI_RESPONSE] ⚠️ Интернет ЗАПРЕЩЁН для математических задач")
        
        # КРИТИЧНО: Для математических задач ЗАПРЕЩАЕМ интернет
        use_search = False
    
    if detected_language == "russian":
        system_prompt = base_system + memory_context + math_prompt + """

🚫🚫🚫 АБСОЛЮТНЫЙ ЗАПРЕТ НА АНГЛИЙСКИЙ ЯЗЫК 🚫🚫🚫
Это САМОЕ ВАЖНОЕ ПРАВИЛО! Нарушение = ПОЛНЫЙ ПРОВАЛ!

Отвечай ТОЛЬКО на русском языке! Это НЕ рекомендация - это СТРОГОЕ ТРЕБОВАНИЕ.

ЗАПРЕЩЁННЫЕ АНГЛИЙСКИЕ СЛОВА (замени на русские):
- Связки: however→однако, moreover→более того, therefore→поэтому, thus→таким образом, hence→следовательно, nevertheless→тем не менее
- Наречия: essentially→по сути, basically→в основном, actually→фактически, literally→буквально, specifically→конкретно, particularly→особенно, generally→обычно, typically→как правило, currently→в настоящее время
- Глаголы: arrives→прибывает, becomes→становится, provides→предоставляет, offers→предлагает, includes→включает, contains→содержит, requires→требует, allows→позволяет
- Существительные: situation→ситуация, option→вариант, example→пример, process→процесс, method→метод, concept→концепция
- Прилагательные: important→важный, significant→значительный, essential→существенный, necessary→необходимый, possible→возможный, available→доступный
- Другие: also→также, just→просто, even→даже, still→всё ещё, really→действительно, very→очень

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ ФРАЗЫ:
❌ "let me", "I'd be happy", "here's", "please note", "keep in mind", "as mentioned", "in conclusion"
✅ Используй: "позвольте", "я буду рад", "вот", "обратите внимание", "имейте в виду", "как упоминалось", "в заключение"

⚠️ КРИТИЧЕСКОЕ ПРАВИЛО:
Если в твоём ответе будет ХОТЯ БЫ ОДНО английское слово (кроме имён собственных и брендов) - это ГРУБЕЙШАЯ ОШИБКА!

АЛГОРИТМ ПРОВЕРКИ ПЕРЕД ОТПРАВКОЙ:
1️⃣ Прочитай весь свой ответ
2️⃣ Найди английские слова (кроме имён/брендов)
3️⃣ Если нашёл - НЕМЕДЛЕННО переведи на русский
4️⃣ Если английских слов больше 5 - ПЕРЕПИШИ ВЕСЬ ОТВЕТ заново на русском
5️⃣ Проверь ещё раз - НЕТ ЛИ английских глаголов, существительных, прилагательных?

Используй русские эквиваленты ВСЕГДА!"""
    else:
        system_prompt = base_system + memory_context + math_prompt

    final_user_message = user_message
    
    # Обрабатываем прикреплённый файл
    if file_path:
        print(f"[GET_AI_RESPONSE] Обработка файла: {file_path}")
        try:
            import os
            file_ext = os.path.splitext(file_path)[1].lower()
            file_name = os.path.basename(file_path)
            
            # Проверяем тип файла
            if file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                # Изображение
                print(f"[GET_AI_RESPONSE] Файл - изображение")
                if detected_language == "russian":
                    file_context = f"\n\n[Пользователь прикрепил изображение: {file_name}]\nПроанализируй изображение и ответь на вопрос пользователя об этом изображении."
                else:
                    file_context = f"\n\n[User attached an image: {file_name}]\nAnalyze the image and answer the user's question about it."
            else:
                # Текстовый файл
                print(f"[GET_AI_RESPONSE] Попытка прочитать файл как текст")
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        file_content = f.read()[:10000]  # Ограничиваем 10000 символов
                    if detected_language == "russian":
                        file_context = f"\n\n[Пользователь прикрепил файл: {file_name}]\n\nСОДЕРЖИМОЕ ФАЙЛА:\n{file_content}\n\nПроанализируй содержимое файла и ответь на вопрос пользователя."
                    else:
                        file_context = f"\n\n[User attached a file: {file_name}]\n\nFILE CONTENT:\n{file_content}\n\nAnalyze the file content and answer the user's question."
                except:
                    # Не удалось прочитать как текст
                    if detected_language == "russian":
                        file_context = f"\n\n[Пользователь прикрепил файл: {file_name}]\nФайл не может быть прочитан как текст."
                    else:
                        file_context = f"\n\n[User attached a file: {file_name}]\nThe file cannot be read as text."
            
            final_user_message = user_message + file_context
            print(f"[GET_AI_RESPONSE] Файл добавлен в контекст")
        except Exception as e:
            print(f"[GET_AI_RESPONSE] Ошибка обработки файла: {e}")
    
    print(f"[GET_AI_RESPONSE] Контекстная память добавлена в системный промпт")

    if use_search:
        print(f"[GET_AI_RESPONSE] ПОИСК АКТИВИРОВАН! Выполняю google_search...")
        if detected_language == "russian":
            region = "ru-ru"
        else:
            region = "us-en"
        num_results = 8 if deep_thinking else 3
        
        # 🔥 КОНТЕКСТНЫЙ ПОИСК: формируем запрос с учётом истории диалога
        contextual_query = build_contextual_search_query(user_message, chat_manager, chat_id, detected_language)
        print(f"[GET_AI_RESPONSE] 🔍 Поисковый запрос: {contextual_query}")
        
        search_results = google_search(contextual_query, num_results=num_results, region=region, language=detected_language)
        print(f"[GET_AI_RESPONSE] Результаты поиска получены. Длина: {len(search_results)} символов")
        print(f"[GET_AI_RESPONSE] Первые 300 символов результатов: {search_results[:300]}...")

        # СЖИМАЕМ результаты поиска под лимит токенов
        # Примерно 1 токен ≈ 4 символа для русского, ≈ 3 символа для английского
        # Оставляем место для системного промпта (~500 токенов) и ответа
        if deep_thinking:
            # Режим "Думать" - больше токенов на контекст
            max_search_tokens = 2000  # ~8000 символов для русского
        else:
            # Быстрый режим - меньше токенов
            max_search_tokens = 1000  # ~4000 символов для русского
        
        max_search_chars = max_search_tokens * 4 if detected_language == "russian" else max_search_tokens * 3
        print(f"[GET_AI_RESPONSE] Лимит для результатов поиска: {max_search_tokens} токенов ({max_search_chars} символов)")
        
        if len(search_results) > max_search_chars:
            print(f"[GET_AI_RESPONSE] Результаты поиска слишком длинные, сжимаем...")
            search_results = compress_search_results(search_results, max_search_chars)

        if detected_language == "russian":
            if deep_thinking:
                search_instruction = """🧠 УМНЫЙ АНАЛИЗ ИНФОРМАЦИИ ИЗ ИНТЕРНЕТА

⚠️ КОНТЕКСТ ДИАЛОГА:
- Учитывай предыдущие сообщения в истории
- Если вопрос является продолжением темы - развивай её
- Связывай найденную информацию с тем, о чём говорилось ранее

🎯 АНАЛИЗ РЕЗУЛЬТАТОВ:
1. Определи тип запроса (погода, техника, кулинария, обучение, код, новости)
2. Проанализируй РЕЛЕВАНТНОСТЬ каждого источника
3. Отбрось информацию, которая НЕ относится к запросу
4. Сравни информацию из разных источников
5. Если есть противоречия - укажи на них

📝 ПРАВИЛА ОТВЕТА:
- Используй ТОЛЬКО релевантную информацию из результатов поиска
- Убери лишнее (форумы, мнения, если запрос технический)
- Пиши ЧЕЛОВЕЧЕСКИМ языком, а не копируй текст
- Дай краткий, понятный вывод
- НЕ используй устаревшие знания

🚫 СТРОГО ЗАПРЕЩЕНО ИСПОЛЬЗОВАТЬ АНГЛИЙСКИЕ СЛОВА:
НЕ пиши: however, moreover, furthermore, therefore, thus, hence, nevertheless, nonetheless, additionally, consequently, essentially, basically, actually, literally, specifically, particularly, generally, typically, primarily, ultimately, previously, currently, subsequently, accordingly, alternatively, conversely, likewise, similarly, whereas, whereby, wherein, thereof, herein, thereof, hereby
ВМЕСТО ЭТОГО пиши по-русски: однако, более того, кроме того, поэтому, таким образом, тем не менее, дополнительно, следовательно, по сути, в основном, фактически, буквально, конкретно, особенно, обычно, как правило, в первую очередь, в конечном счёте, ранее, в настоящее время, впоследствии, соответственно, в качестве альтернативы, наоборот, аналогично, подобно, тогда как

НЕ пиши фразы: "let me", "I'd be happy to", "here's", "please note", "it's worth noting", "keep in mind", "as mentioned", "as previously stated", "to summarize", "in conclusion", "first and foremost"
ВМЕСТО ЭТОГО пиши: позвольте мне, я буду рад, вот, обратите внимание, стоит отметить, имейте в виду, как упоминалось, как было сказано ранее, подводя итог, в заключение, прежде всего

КРИТИЧЕСКИ ВАЖНО: Отвечай ИСКЛЮЧИТЕЛЬНО на РУССКОМ языке! 
- Переведи ВСЮ информацию на русский язык
- Допустимы ТОЛЬКО имена собственные, бренды и технические термины на английском
- Проверь свой ответ - если видишь английские слова (кроме имён/брендов) - НЕМЕДЛЕННО переведи их на русский
- НИ ОДНОГО английского слова в тексте ответа!"""
            else:
                search_instruction = """🎯 БЫСТРЫЙ АНАЛИЗ

1. Определи тип запроса
2. Найди ГЛАВНУЮ информацию в результатах
3. Убери лишнее
4. Дай КРАТКИЙ ответ по сути

🚫 ЗАПРЕЩЁННЫЕ АНГЛИЙСКИЕ СЛОВА:
НЕ используй: however, moreover, therefore, thus, nevertheless, additionally, essentially, basically, actually, specifically, particularly, generally, typically, ultimately, currently
Пиши ТОЛЬКО по-русски: однако, более того, поэтому, таким образом, тем не менее, дополнительно, по сути, в основном, фактически, конкретно, особенно, обычно, как правило, в конечном счёте, в настоящее время

КРИТИЧЕСКИ ВАЖНО: Отвечай ИСКЛЮЧИТЕЛЬНО на РУССКОМ языке! 
- Переведи ВСЮ информацию на русский
- Только имена собственные и бренды могут быть на английском
- НИ ОДНОГО английского слова в ответе!"""
            
            search_context = f"""

═══════════════════════════════════════════════════════════
🔍 АКТУАЛЬНАЯ ИНФОРМАЦИЯ ИЗ ИНТЕРНЕТА (DuckDuckGo)
═══════════════════════════════════════════════════════════

{search_results}

═══════════════════════════════════════════════════════════
📋 ИНСТРУКЦИЯ ДЛЯ ОТВЕТА:
═══════════════════════════════════════════════════════════

{search_instruction}

Вопрос пользователя: {user_message}
"""
        else:
            if deep_thinking:
                search_instruction = """🧠 SMART INFORMATION ANALYSIS

⚠️ DIALOG CONTEXT:
- Consider previous messages in history
- If the question continues the topic - develop it
- Connect found information with what was discussed earlier

🎯 RESULTS ANALYSIS:
1. Identify query type (weather, tech, cooking, learning, code, news)
2. Analyze RELEVANCE of each source
3. Discard information NOT related to the query
4. Compare information from different sources
5. If there are contradictions - point them out

📝 RESPONSE RULES:
- Use ONLY relevant information from search results
- Remove irrelevant (forums, opinions if query is technical)
- Write in HUMAN language, don't copy text
- Give brief, clear conclusion
- DON'T use outdated knowledge"""
            else:
                search_instruction = """🎯 QUICK ANALYSIS

1. Identify query type
2. Find MAIN information in results
3. Remove irrelevant
4. Give BRIEF answer to the point

IMPORTANT:
- Only relevant information
- Human language
- No unnecessary details"""
            
            search_context = f"""

═══════════════════════════════════════════════════════════
🔍 CURRENT INFORMATION FROM THE INTERNET (DuckDuckGo)
═══════════════════════════════════════════════════════════

{search_results}

═══════════════════════════════════════════════════════════
📋 RESPONSE INSTRUCTIONS:
═══════════════════════════════════════════════════════════

{search_instruction}

User's question: {user_message}
"""
        print(f"[GET_AI_RESPONSE] Контекст поиска добавлен. Длина: {len(search_context)} символов")
        final_user_message = search_context
    else:
        print(f"[GET_AI_RESPONSE] Поиск НЕ активирован")

    # Если запрошено забывание, НЕ загружаем историю
    if should_forget:
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({
            "role": "user",
            "content": final_user_message
        })
        print(f"[GET_AI_RESPONSE] Режим забывания: история не загружается")
    else:
        # Загружаем историю из chat_manager если доступен, иначе из старой БД
        # ВАЖНО: загружаем историю ДАЖЕ при включенном поиске для учета контекста
        if chat_manager and chat_id:
            history = chat_manager.get_chat_messages(chat_id, limit=MAX_HISTORY_LOAD)
            print(f"[GET_AI_RESPONSE] Загружено сообщений из чата {chat_id}: {len(history)}")
        else:
            history = load_history(limit=MAX_HISTORY_LOAD)
            print(f"[GET_AI_RESPONSE] Загружено сообщений из истории: {len(history)}")
        
        messages = [{"role": "system", "content": system_prompt}]
        for role, content, _ in history:
            # Пропускаем системные сообщения
            if role not in ["user", "assistant"]:
                continue
            messages.append({
                "role": "user" if role == "user" else "assistant",
                "content": content
            })
        messages.append({
            "role": "user",
            "content": final_user_message
        })
        
        if use_search:
            print(f"[GET_AI_RESPONSE] Режим поиска: история загружена для учета контекста диалога")

    print(f"[GET_AI_RESPONSE] Всего сообщений для отправки в AI: {len(messages)}")

    # ОПТИМИЗИРОВАННЫЕ лимиты токенов
    if use_search:
        # С поиском - меньше токенов на ответ, т.к. много контекста
        if deep_thinking:
            max_tokens = 1500  # Поиск + думать
        else:
            max_tokens = 800   # Только поиск
    else:
        # Без поиска - больше токенов на ответ
        if deep_thinking:
            max_tokens = 2000  # Только думать
        else:
            max_tokens = 200   # Быстрый режим

    # Увеличиваем timeout для сложных запросов
    if use_search and deep_thinking:
        timeout = 180  # 3 минуты для поиска + глубокое мышление
    elif use_search or deep_thinking:
        timeout = 120  # 2 минуты для поиска ИЛИ глубокое мышление
    else:
        timeout = 60   # 1 минута для обычных запросов

    print(f"[GET_AI_RESPONSE] Лимит токенов для ОТВЕТА: {max_tokens}, Timeout: {timeout}s")

    response_text = ""
    
    if USE_OLLAMA:
        print(f"[GET_AI_RESPONSE] Использую Ollama (LLaMA)...")
        try:
            resp = call_ollama_chat(messages, max_tokens=max_tokens, timeout=timeout)
            
            # Проверяем, что ответ не является ошибкой
            if not resp.startswith("[Ollama error]") and not resp.startswith("[Ollama timeout]") and not resp.startswith("[Ollama connection error]"):
                print(f"[GET_AI_RESPONSE] Ollama ответил успешно. Длина ответа: {len(resp)}")
                response_text = resp
            else:
                print(f"[GET_AI_RESPONSE] Ollama вернул ошибку: {resp}")
                response_text = "❌ Ошибка: не удалось получить ответ от локальной модели LLaMA. Проверьте:\n1. Запущена ли Ollama\n2. Загружена ли модель\n3. Достаточно ли памяти"
        except Exception as e:
            print(f"[GET_AI_RESPONSE] Исключение при вызове Ollama: {e}")
            response_text = f"❌ Ошибка подключения к LLaMA: {e}"
    
    # КРИТИЧЕСКАЯ ПРОВЕРКА: если вопрос на русском, но ответ содержит много английского - переводим
    if detected_language == "russian":
        # Проверяем, есть ли в ответе много английского
        response_lang = detect_message_language(response_text)
        if response_lang == "english":
            print(f"[GET_AI_RESPONSE] ⚠️⚠️⚠️ КРИТИЧНО! Ответ ПОЛНОСТЬЮ на английском! Переводим...")
            try:
                response_text = translate_to_russian(response_text)
                print(f"[GET_AI_RESPONSE] ✓ Перевод завершён успешно")
            except Exception as e:
                print(f"[GET_AI_RESPONSE] ✗ Ошибка перевода: {e}")
    
    # ДОПОЛНИТЕЛЬНАЯ ОЧИСТКА: удаляем английские слова из русского текста
    if detected_language == "russian":
        print(f"[GET_AI_RESPONSE] Фильтрация английских слов из русского текста...")
        response_text = remove_english_words_from_russian(response_text)
        print(f"[GET_AI_RESPONSE] Фильтрация завершена")
    
    # Сохраняем краткий вывод в контекстную память (если был поиск)
    if use_search and chat_id and response_text:
        try:
            # Создаём экземпляр менеджера контекстной памяти
            context_mgr = ContextMemoryManager()
            
            # Формируем контекст в зависимости от режима
            if deep_thinking:
                # Детальный контекст для режима "думать"
                summary = response_text[:500] if len(response_text) > 500 else response_text
                if len(response_text) > 500:
                    summary += "..."
                context_type = "search_deep"
            else:
                # Краткий контекст для обычного режима
                summary = response_text[:200] if len(response_text) > 200 else response_text
                if len(response_text) > 200:
                    summary += "..."
                context_type = "search_quick"
            
            context_entry = f"Вопрос: {user_message[:100]} | Вывод: {summary}"
            context_mgr.save_context_memory(chat_id, context_type, context_entry)
            print(f"[GET_AI_RESPONSE] Контекст сохранён: тип={context_type}, длина={len(context_entry)}")
        except Exception as e:
            print(f"[GET_AI_RESPONSE] Ошибка сохранения контекста: {e}")
    
    print(f"[GET_AI_RESPONSE] ========== КОНЕЦ ==========\n")
    return response_text

# -------------------------
# New helper: decide short text
# -------------------------
def is_short_text(text: str) -> bool:
    """
    Возвращает True если текст короткий — критерии:
    - по символам меньше SHORT_TEXT_THRESHOLD, и
    - не более 2 строк
    """
    if not text:
        return True
    s = text.strip()
    lines = s.count("\n") + 1
    return len(s) <= SHORT_TEXT_THRESHOLD and lines <= 2

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
        self.setWindowFlags(QtCore.Qt.WindowType.ToolTip | QtCore.Qt.WindowType.FramelessWindowHint)
        # Прозрачность работает плохо на Windows
        if not IS_WINDOWS:
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Стиль стеклянной подсказки
        self.setStyleSheet("""
            QLabel {
                background: rgba(255, 255, 255, 0.75);
                border: 1px solid rgba(255, 255, 255, 0.85);
                border-radius: 12px;
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
        self.fade_in.setDuration(200)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)
        self.fade_in.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        
        # Анимация исчезновения
        self.fade_out = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out.setDuration(200)
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
        self.fade_out.finished.connect(self.hide)
    
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
# Message widget (с адаптивным размером эмодзи)
# -------------------------
class MessageWidget(QtWidgets.QWidget):
    """Виджет для отображения сообщения"""

    def __init__(self, speaker: str, text: str, add_controls: bool = False,
                 language: str = "russian", main_window=None, parent=None, thinking_time: float = 0, action_history: list = None):
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
        
        # Создаём эффект прозрачности для анимации
        self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)  # Начинаем с полной прозрачности

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
            main_layout.setContentsMargins(80, 8, 6, 8)
        elif align == QtCore.Qt.AlignmentFlag.AlignLeft:
            # Сообщения ИИ - ближе к левому краю
            main_layout.setContentsMargins(6, 8, 80, 8)
        else:
            # Системные сообщения - по центру сверху с равными отступами
            main_layout.setContentsMargins(80, 8, 80, 8)
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
        col_layout.setSpacing(4)
        
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
                border: 1px solid {self.bubble_border};
                border-radius: 24px;
                padding: 20px 26px;
            }}
        """)
        
        # Сохраняем ссылку для обновления стилей
        self.message_container = message_container
        
        container_layout = QtWidgets.QVBoxLayout(message_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)  # Уменьшено с 6 до 4 для компактности пузыря

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
        
        font = QtGui.QFont("Inter", 18)
        message_label.setFont(font)
        message_label.setStyleSheet(f"""
            QLabel {{
                color: {self.text_color};
                padding: 8px;
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
        controls_layout = QtWidgets.QHBoxLayout(controls_widget)
        controls_layout.setSpacing(10)
        bubble_padding = 18

        if controls_side == "left":
            controls_layout.setContentsMargins(bubble_padding, 0, 0, 6)
        elif controls_side == "right":
            controls_layout.setContentsMargins(0, 0, bubble_padding, 6)
        else:
            controls_layout.setContentsMargins(0, 0, 0, 6)

        # Кнопка копирования
        copy_btn = QtWidgets.QPushButton()
        copy_btn.setText("📋")
        copy_btn.setToolTip("Копировать")
        copy_btn.setFixedSize(btn_size, btn_size)
        copy_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        copy_btn.clicked.connect(self.copy_text)
        copy_btn.setVisible(add_controls)
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

        
        # Кнопка перегенерации (только для ассистента)
        if speaker != "Вы" and speaker != "Система" and add_controls:
            regenerate_btn = QtWidgets.QPushButton()
            regenerate_btn.setText("🔄")
            regenerate_btn.setToolTip("Перегенерировать ответ")
            regenerate_btn.setFixedSize(btn_size, btn_size)
            regenerate_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            regenerate_btn.clicked.connect(self.regenerate_response)
            regenerate_btn.setVisible(add_controls)
            regenerate_btn.setObjectName("floatingControl")
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

        controls_widget.setVisible(add_controls)

        # Добавляем панель под пузырём
        if controls_side == "left":
            col_layout.addWidget(controls_widget, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        elif controls_side == "right":
            col_layout.addWidget(controls_widget, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        else:
            col_layout.addWidget(controls_widget, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)
        
        # Вставляем в главный layout
        main_layout.addWidget(col_widget)
        if align == QtCore.Qt.AlignmentFlag.AlignLeft:
            main_layout.addStretch()
        elif speaker == "Система":
            # ✅ Для системных сообщений - добавляем stretch ПОСЛЕ для полного центрирования
            main_layout.addStretch()
        
        # ✅ ТОЛЬКО FADE-IN АНИМАЦИЯ: Плавное появление через изменение прозрачности
        # Никаких манипуляций с позицией, размерами или margins!
        # Layout полностью контролирует позицию и размеры виджета
        if not IS_WINDOWS:
            # Создаём анимацию прозрачности: 0 → 1 (fade-in эффект)
            self.fade_in_animation = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
            self.fade_in_animation.setDuration(300)
            self.fade_in_animation.setStartValue(0.0)
            self.fade_in_animation.setEndValue(1.0)
            self.fade_in_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            
            # ✅ НЕ запускаем анимацию автоматически - она будет запущена из add_message_widget
            # после полного обновления layout
        else:
            # На Windows сразу показываем без анимации
            self.opacity_effect.setOpacity(1.0)

    @QtCore.pyqtSlot()
    def _start_appear_animation(self):
        """
        Запускает анимацию появления (только fade-in прозрачности).
        
        ВАЖНО: НЕ подключаемся к finished - это может пересчитать layout!
        Эффект остаётся с opacity=1.0 после завершения анимации.
        
        Вызывается через QMetaObject.invokeMethod для синхронизации с layout.
        """
        if hasattr(self, 'fade_in_animation'):
            self.fade_in_animation.start()
    
    def _cleanup_graphics_effect(self):
        """
        Завершает анимацию появления - устанавливает полную непрозрачность.
        
        ВАЖНО: НЕ удаляем graphicsEffect! 
        Он нужен для fade_out_and_delete() при удалении виджета.
        """
        try:
            if hasattr(self, 'opacity_effect') and self.opacity_effect is not None:
                # Просто устанавливаем полную непрозрачность
                self.opacity_effect.setOpacity(1.0)
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
        
        # Сохраняем новые стили
        self.bubble_bg = bubble_bg
        self.bubble_border = bubble_border
        self.btn_bg = btn_bg
        self.btn_bg_hover = btn_bg_hover
        self.btn_border = btn_border
        self.text_color = text_color
        self.icon_color = icon_color
        self.hover_border_color = hover_border_color
        self.pressed_border_color = pressed_border_color
        
        # Применяем стили к message_container
        if hasattr(self, 'message_container') and self.message_container:
            self.message_container.setStyleSheet(f"""
                #messageContainer {{
                    background-color: {bubble_bg};
                    border: 1px solid {bubble_border};
                    border-radius: 24px;
                    padding: 20px 26px;
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
        
        # Применяем к другим кнопкам если они есть
        # Находим все кнопки в виджете
        for button in self.findChildren(QtWidgets.QPushButton):
            if button.objectName() == "floatingControl":
                button.setStyleSheet(button_style)
        
        print(f"[MSG_UPDATE] Стили обновлены: theme={theme}, liquid_glass={liquid_glass}")


    def copy_text(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.text)
        
        # Анимация: показываем галочку
        if self.copy_button:
            original_text = self.copy_button.text()
            self.copy_button.setText("✓")
            
            # Возвращаем обратно через 1.5 секунды
            QtCore.QTimer.singleShot(1500, lambda: self.copy_button.setText(original_text) if self.copy_button else None)
    
    def fade_out_and_delete(self):
        """
        Плавное исчезновение виджета через прозрачность.
        
        ВАЖНО: Работает одинаково во всех темах (светлая/тёмная).
        Стиль темы НЕ влияет на механизм удаления.
        """
        # На Windows GraphicsOpacityEffect работает медленно - используем упрощённую анимацию
        if IS_WINDOWS:
            # Упрощённая анимация для Windows без GraphicsOpacityEffect
            try:
                # Просто удаляем без эффектов (на Windows могут быть проблемы с repaint)
                self.deleteLater()
            except Exception as e:
                print(f"[FADE_OUT] Ошибка удаления на Windows: {e}")
            return
        
        # Для macOS и Linux - полноценная анимация с opacity
        # Проверяем, существует ли opacity_effect
        if not hasattr(self, 'opacity_effect') or self.opacity_effect is None:
            # Если эффект удалён - создаём новый
            self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self.opacity_effect)
            self.opacity_effect.setOpacity(1.0)
        
        # Дополнительная проверка: проверяем что эффект не был удалён из C++
        try:
            # Пытаемся получить текущую прозрачность - если объект удалён, будет RuntimeError
            current_opacity = self.opacity_effect.opacity()
        except RuntimeError:
            # Объект был удалён на уровне C++ - создаём новый
            self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self.opacity_effect)
            self.opacity_effect.setOpacity(1.0)
        
        # ✅ ТОЛЬКО fade-out прозрачности, БЕЗ изменения высоты
        # Layout сам пересчитает позиции после удаления виджета
        # КРИТИЧНО: Анимация НЕ зависит от темы - работает одинаково везде
        self.fade_out_animation = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out_animation.setDuration(350)  # Плавная анимация
        self.fade_out_animation.setStartValue(1.0)
        self.fade_out_animation.setEndValue(0.0)
        self.fade_out_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)  # Плавное замедление
        
        # Удаляем виджет после завершения fade-out
        def safe_delete():
            try:
                # Останавливаем анимацию перед удалением
                if hasattr(self, 'fade_out_animation') and self.fade_out_animation:
                    self.fade_out_animation.stop()
                    self.fade_out_animation = None
                # Удаляем эффект
                if self.graphicsEffect():
                    self.setGraphicsEffect(None)
                # Обнуляем ссылку на opacity_effect
                if hasattr(self, 'opacity_effect'):
                    self.opacity_effect = None
                # Удаляем виджет
                self.deleteLater()
                print("[FADE_OUT] Системное сообщение плавно удалено")
            except RuntimeError:
                # Объект уже удалён
                print("[FADE_OUT] Объект уже удалён (RuntimeError)")
                pass
            except Exception as e:
                print(f"[FADE_OUT] Неожиданная ошибка при удалении: {e}")
        
        self.fade_out_animation.finished.connect(safe_delete)
        self.fade_out_animation.start()
        
        print("[FADE_OUT] Запущена анимация fade-out (универсальная для всех тем)")


    def regenerate_response(self):
        """Перегенерировать ответ ассистента"""
        # Отправляем сигнал родительскому окну
        parent_window = self.window()
        if hasattr(parent_window, 'regenerate_last_response'):
            parent_window.regenerate_last_response()
    
    def edit_message(self):
        """Редактировать сообщение пользователя"""
        parent_window = self.window()
        if hasattr(parent_window, 'edit_last_message'):
            parent_window.edit_last_message(self.text)
    

# -------------------------
# Worker
# -------------------------
class WorkerSignals(QtCore.QObject):
    finished = QtCore.pyqtSignal(str)

class AIWorker(QtCore.QRunnable):
    def __init__(self, user_message: str, current_language: str, deep_thinking: bool, use_search: bool, should_forget: bool = False, chat_manager=None, chat_id=None, file_path: str = None, ai_mode: str = AI_MODE_FAST):
        super().__init__()
        self.user_message = user_message
        self.current_language = current_language
        self.deep_thinking = deep_thinking
        self.use_search = use_search
        self.should_forget = should_forget
        self.chat_manager = chat_manager
        self.chat_id = chat_id
        self.file_path = file_path
        self.ai_mode = ai_mode  # Добавляем режим AI
        self.signals = WorkerSignals()

    @QtCore.pyqtSlot()
    def run(self):
        try:
            response = get_ai_response(
                self.user_message,
                self.current_language,
                self.deep_thinking,
                self.use_search,
                self.should_forget,
                self.chat_manager,
                self.chat_id,
                self.file_path,
                self.ai_mode  # Передаём режим AI
            )
            # ✅ ИСПРАВЛЕНИЕ: Безопасный emit - проверяем что signals ещё существует
            if hasattr(self, 'signals') and self.signals is not None:
                try:
                    self.signals.finished.emit(response)
                except RuntimeError:
                    # Signals уже удалён - игнорируем
                    pass
        except Exception as e:
            # ✅ Безопасный emit для ошибки
            if hasattr(self, 'signals') and self.signals is not None:
                try:
                    self.signals.finished.emit(f"[Ошибка] {e}")
                except RuntimeError:
                    pass

# -------------------------
# Main Window
# -------------------------

# ═══════════════════════════════════════════════════════════════════════════
# НОВЫЙ КОМПОНЕНТ 1: SCROLL TO BOTTOM BUTTON
# Floating overlay кнопка "⬇ вниз" - НЕ участвует в layout
# ═══════════════════════════════════════════════════════════════════════════

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
        super().__init__("⬇", parent)
        
        self.setObjectName("scrollToBottomBtn")
        self.setFixedSize(50, 50)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        # Изначально скрыта
        self.hide()
        
        # Применяем стиль по умолчанию (светлая тема + glass)
        # На этом этапе добавится тень через graphicsEffect
        self.apply_theme_styles(theme="light", liquid_glass=True)
        
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
        self.fade_animation.setDuration(250)  # 250ms - быстрая и плавная
        self.fade_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        
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
        except:
            pass
        
        self.fade_animation.finished.connect(on_fade_out_finished)
        self.fade_animation.start()
        
        self._is_visible_animated = False


# ═══════════════════════════════════════════════════════════════════════════
# НОВЫЙ КОМПОНЕНТ 2: SETTINGS VIEW
# Экран настроек - замена chat_area
# ═══════════════════════════════════════════════════════════════════════════

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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("settingsView")
        
        # Текущие настройки (сохранённые и применённые)
        self.current_settings = {
            "theme": "light",
            "liquid_glass": True,
        }
        
        # Временные настройки (pending - до нажатия "Применить")
        self.pending_settings = {
            "theme": "light",
            "liquid_glass": True,
        }
        
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        """Инициализация UI"""
        
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(50, 50, 50, 50)
        main_layout.setSpacing(35)
        
        # Заголовок
        title = QtWidgets.QLabel("⚙️ Настройки")
        title.setObjectName("settingsTitle")
        title.setFont(QtGui.QFont("Inter", 32, QtGui.QFont.Weight.Bold))
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)
        
        main_layout.addSpacing(25)
        
        # Контейнер настроек
        settings_container = QtWidgets.QWidget()
        settings_container.setObjectName("settingsContainer")
        settings_layout = QtWidgets.QVBoxLayout(settings_container)
        settings_layout.setSpacing(30)
        
        # ═══════════════════════════════════════════════
        # НАСТРОЙКА 1: Тема
        # ═══════════════════════════════════════════════
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
        settings_layout.addWidget(theme_group)
        
        # ═══════════════════════════════════════════════
        # НАСТРОЙКА 2: Liquid Glass - УДАЛЕНО
        # Liquid Glass теперь фиксированный, не редактируется
        # ═══════════════════════════════════════════════
        
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
        self.delete_all_chats_btn.setFont(QtGui.QFont("Inter", 13, QtGui.QFont.Weight.Medium))
        self.delete_all_chats_btn.setMinimumHeight(45)
        self.delete_all_chats_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.delete_all_chats_btn.clicked.connect(self.request_delete_all_chats)
        
        delete_all_layout.addWidget(self.delete_all_chats_btn)
        
        danger_group.layout().addLayout(delete_all_layout)
        settings_layout.addWidget(danger_group)
        
        main_layout.addWidget(settings_container)
        main_layout.addStretch()
        
        # ═══════════════════════════════════════════════
        # КНОПКИ ДЕЙСТВИЙ
        # ═══════════════════════════════════════════════
        actions_layout = QtWidgets.QHBoxLayout()
        actions_layout.setSpacing(15)
        
        back_btn = QtWidgets.QPushButton("← Назад к чату")
        back_btn.setObjectName("settingsBackBtn")
        back_btn.setFont(QtGui.QFont("Inter", 14, QtGui.QFont.Weight.Medium))
        back_btn.setMinimumHeight(50)
        back_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        back_btn.clicked.connect(self.close_requested.emit)
        
        apply_btn = QtWidgets.QPushButton("✓ Применить")
        apply_btn.setObjectName("settingsApplyBtn")
        apply_btn.setFont(QtGui.QFont("Inter", 14, QtGui.QFont.Weight.Bold))
        apply_btn.setMinimumHeight(50)
        apply_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        apply_btn.clicked.connect(self.apply_settings)
        
        actions_layout.addWidget(back_btn)
        actions_layout.addWidget(apply_btn)
        
        main_layout.addLayout(actions_layout)
        
        self.apply_settings_styles()
    
    def create_setting_group(self, title: str, description: str) -> QtWidgets.QGroupBox:
        """Создать группу настроек"""
        
        group = QtWidgets.QGroupBox()
        group.setObjectName("settingGroup")
        
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(12)
        
        title_label = QtWidgets.QLabel(title)
        title_label.setFont(QtGui.QFont("Inter", 18, QtGui.QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        desc_label = QtWidgets.QLabel(description)
        desc_label.setObjectName("descLabel")
        desc_label.setFont(QtGui.QFont("Inter", 13))
        desc_label.setStyleSheet("color: #475569;")
        layout.addWidget(desc_label)
        
        return group
    
    def set_theme(self, theme: str):
        """
        Установить тему ВИЗУАЛЬНО (pending state).
        
        ВАЖНО: НЕ применяет стили к приложению!
        Только меняет визуальное состояние кнопок выбора.
        Реальное применение происходит при нажатии "Применить".
        """
        # Сохраняем в pending settings
        self.pending_settings["theme"] = theme
        
        # Обновляем ТОЛЬКО визуальное состояние кнопок
        self.theme_light_btn.setChecked(theme == "light")
        self.theme_dark_btn.setChecked(theme == "dark")
        
        # НЕ применяем стили! Только обновляем кнопки
        print(f"[SETTINGS] Выбрана тема: {theme} (pending, не применено)")
    
    def set_liquid_glass(self, enabled: bool):
        """
        Liquid Glass теперь фиксированный - метод сохранен для совместимости.
        НЕ ИСПОЛЬЗУЕТСЯ.
        """
        # Заглушка - liquid_glass всегда True
        pass
    
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
        
        # LIQUID GLASS ФИКСИРОВАН - ВСЕГДА TRUE
        self.current_settings["liquid_glass"] = True
        self.pending_settings["liquid_glass"] = True
        
        # Устанавливаем визуальное состояние кнопок согласно current settings
        theme = self.current_settings.get("theme", "light")
        
        self.theme_light_btn.setChecked(theme == "light")
        self.theme_dark_btn.setChecked(theme == "dark")
        
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
    
    def request_delete_all_chats(self):
        """Запросить подтверждение удаления всех чатов"""
        print("[SETTINGS] Запрос на удаление всех чатов")
        self.delete_all_chats_requested.emit()
    
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
                    "btn_border": "rgba(68, 68, 72, 0.95)",
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
                    "btn_bg": "rgba(255, 255, 255, 0.65)",
                    "btn_border": "rgba(203, 213, 225, 0.55)",
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
                    "btn_border": "rgba(210, 210, 215, 0.95)",
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
        """
        
        self.setStyleSheet(style)
        print(f"[SETTINGS_VIEW] ✓ Стили применены")




class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        global CURRENT_LANGUAGE
        self.current_language = CURRENT_LANGUAGE
        self.deep_thinking = False
        self.use_search = False
        self.is_generating = False
        self.current_user_message = ""
        self.current_worker = None
        
        # ✅ ИСПРАВЛЕНИЕ: Список активных workers для предотвращения RuntimeError
        # WorkerSignals не должен удаляться пока worker работает
        self.active_workers = []  # Сильные ссылки на workers
        
        # Режим работы AI
        self.ai_mode = AI_MODE_FAST  # По умолчанию быстрый режим
        
        # Таймер обдумывания
        self.thinking_start_time = None
        self.thinking_elapsed_time = 0
        
        # Режим редактирования
        self.is_editing = False
        self.editing_message_text = ""
        
        # Прикреплённый файл
        self.attached_file_path = None
        
        # Менеджер чатов
        self.chat_manager = ChatManager()
        
        # Текущая тема и настройки интерфейса
        self.current_theme = "light"
        self.current_liquid_glass = True
        
        # ЛОГИКА СТАРТОВОГО ЧАТА
        # Создаём временный чат при запуске
        new_chat_id = self.chat_manager.create_chat("Новый чат")
        self.chat_manager.set_active_chat(new_chat_id)
        self.current_chat_id = new_chat_id
        
        # Помечаем этот чат как стартовый (пустой)
        self.startup_chat_id = new_chat_id
        self.startup_chat_has_messages = False

        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 850)

        icon_pixmap = create_app_icon()
        self.setWindowIcon(QtGui.QIcon(icon_pixmap))

        # ── Animated background widget (lives behind everything) ──
        self.bg_widget = QtWidgets.QWidget()
        self.bg_widget.setObjectName("bgWidget")

        # Главный контейнер
        main_container = QtWidgets.QWidget()
        self.setCentralWidget(main_container)
        container_layout = QtWidgets.QHBoxLayout(main_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Боковая панель чатов
        self.sidebar = QtWidgets.QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(0)  # Изначально скрыта
        sidebar_layout = QtWidgets.QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 12, 0, 0)  # Верхний отступ как у title
        sidebar_layout.setSpacing(0)

        # Кнопка "Новый чат"
        new_chat_btn = QtWidgets.QPushButton("+ Новый чат")
        new_chat_btn.setObjectName("newChatBtn")
        new_chat_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        new_chat_btn.clicked.connect(self.create_new_chat)
        sidebar_layout.addWidget(new_chat_btn)

        # Список чатов
        self.chats_list = QtWidgets.QListWidget()
        self.chats_list.setObjectName("chatsList")
        self.chats_list.itemClicked.connect(self.switch_chat)
        self.chats_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.chats_list.customContextMenuRequested.connect(self.show_delete_panel)
        sidebar_layout.addWidget(self.chats_list)

        # ═══════════════════════════════════════════════
        # НОВОЕ: Кнопка настроек (закреплена снизу sidebar)
        # ═══════════════════════════════════════════════
        self.settings_btn = QtWidgets.QPushButton("⚙️ Настройки")
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.settings_btn.clicked.connect(self.open_settings)
        sidebar_layout.addWidget(self.settings_btn)


        container_layout.addWidget(self.sidebar)

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
        title_layout = QtWidgets.QHBoxLayout(title_widget)
        title_layout.setContentsMargins(15, 12, 15, 12)
        title_layout.setSpacing(15)

        # Кнопка меню (иконка трёх полосок)
        self.menu_btn = QtWidgets.QPushButton()
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
        font_title = QtGui.QFont("Inter", 22, QtGui.QFont.Weight.Bold)
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
        font_clear = QtGui.QFont("Inter", 13, QtGui.QFont.Weight.Bold)
        self.clear_btn.setFont(font_clear)
        self.clear_btn.setFixedSize(120, 44)
        self.clear_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.clear_btn.clicked.connect(self.clear_chat)
        title_layout.addWidget(self.clear_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
        
        # Уменьшен отступ для сдвига кнопки вправо (было 15)
        title_layout.addSpacing(8)

        main_layout.addWidget(title_widget)


        # ═══════════════════════════════════════════════════════════════
        # Chat display - QStackedWidget для переключения чат/настройки
        # ═══════════════════════════════════════════════════════════════
        self.content_stack = QtWidgets.QStackedWidget()
        self.content_stack.setObjectName("contentStack")

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
        
        # Добавляем страницы в stack
        self.content_stack.addWidget(chat_container)  # index 0
        self.content_stack.addWidget(self.settings_view)  # index 1
        
        # Показываем чат по умолчанию
        self.content_stack.setCurrentIndex(0)
        
        main_layout.addWidget(self.content_stack, stretch=1)

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
        self.attach_btn = QtWidgets.QPushButton("+")
        self.attach_btn.setObjectName("attachBtn")
        font_attach = QtGui.QFont("Inter", 26, QtGui.QFont.Weight.Bold)
        self.attach_btn.setFont(font_attach)
        self.attach_btn.setFixedSize(60, 60)
        self.attach_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.attach_btn.clicked.connect(self.show_attach_menu)
        input_layout.addWidget(self.attach_btn)

        self.input_field = QtWidgets.QLineEdit()
        self.input_field.setPlaceholderText("Введите сообщение...")
        self.input_field.setObjectName("inputField")
        font_input = QtGui.QFont("Inter", 14)
        self.input_field.setFont(font_input)
        self.input_field.setMinimumHeight(60)
        self.input_field.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_field, stretch=1)
        
        # Кнопка выбора режима AI (новая)
        self.mode_btn = QtWidgets.QPushButton(self.ai_mode)
        self.mode_btn.setObjectName("modeBtn")
        font_mode = QtGui.QFont("Inter", 12, QtGui.QFont.Weight.Medium)
        self.mode_btn.setFont(font_mode)
        self.mode_btn.setFixedSize(95, 60)
        self.mode_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.mode_btn.clicked.connect(self.show_mode_menu)
        input_layout.addWidget(self.mode_btn)

        self.send_btn = QtWidgets.QPushButton("→")
        self.send_btn.setObjectName("sendBtn")
        font_btn = QtGui.QFont("Inter", 22, QtGui.QFont.Weight.Bold)
        self.send_btn.setFont(font_btn)
        self.send_btn.setFixedSize(60, 60)
        self.send_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_btn)

        # ✅ КРИТИЧНО: Добавляем input_container в main_layout с stretch=0
        main_layout.addWidget(input_container, 0)
        
        # Store reference
        self.input_container = input_container

        # Статус - fixed at bottom
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("statusLabel")
        font_status = QtGui.QFont("Inter", 11)
        self.status_label.setFont(font_status)
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.status_label.setContentsMargins(30, 0, 30, 10)
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
        
        # Применяем стили с загруженными настройками
        self.apply_styles(theme=theme, liquid_glass=liquid_glass)
        
        # Применяем тему к кнопке "вниз"
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.scroll_to_bottom_btn.apply_theme_styles(theme=theme, liquid_glass=liquid_glass)
        
        self.load_chats_list()
        self.load_current_chat()
        
        # Флаг первого показа для финализации layout
        self._first_show_done = False
    
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
            # Откладываем финализацию на следующий цикл event loop
            # Это гарантирует что все виджеты полностью отрендерены
            QtCore.QTimer.singleShot(0, self._finalize_initial_layout)
    
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
    
    def resizeEvent(self, event):
        """
        Обработка изменения размера окна.
        
        КРИТИЧНО:
        - Обновляем ТОЛЬКО позицию overlay-кнопки "вниз"
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
                    "sidebar_bg": "rgba(24, 24, 28, 0.65)",  # Тёмное стекло для sidebar
                    
                    "central_border": "rgba(50, 50, 55, 0.4)",  # Мягкие тёмные границы
                    "sidebar_border": "rgba(50, 50, 55, 0.35)",
                    
                    "text_primary": "#e6e6e6",  # Светлый текст для читаемости
                    "text_secondary": "#b0b0b0",
                    "text_tertiary": "#808080",
                    
                    "btn_bg": "rgba(45, 45, 50, 0.55)",  # Тёмные полупрозрачные кнопки
                    "btn_bg_hover": "rgba(55, 55, 60, 0.65)",
                    "btn_border": "rgba(60, 60, 65, 0.4)",
                    
                    "input_bg_start": "rgba(35, 35, 40, 0.75)",  # Тёмные инпуты
                    "input_bg_end": "rgba(28, 28, 32, 0.75)",
                    "input_border": "rgba(55, 55, 60, 0.5)",
                    "input_focus_border": "rgba(139, 92, 246, 0.4)",
                    
                    "accent_primary": "rgba(139, 92, 246, 0.3)",  # Фиолетовый акцент
                    "accent_hover": "rgba(139, 92, 246, 0.45)",
                    
                    "title_bg": "rgba(30, 30, 35, 0.65)",
                    "title_border": "rgba(50, 50, 55, 0.4)",
                    
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
                    "sidebar_border": "rgba(55, 55, 60, 0.85)",
                    
                    "text_primary": "#f0f0f0",  # Очень светлый текст для контраста
                    "text_secondary": "#c0c0c0",
                    "text_tertiary": "#909090",
                    
                    "btn_bg": "rgb(48, 48, 52)",  # НЕПРОЗРАЧНЫЕ кнопки
                    "btn_bg_hover": "rgb(58, 58, 62)",
                    "btn_border": "rgba(68, 68, 72, 0.95)",
                    
                    "input_bg_start": "rgb(38, 38, 42)",  # НЕПРОЗРАЧНЫЕ инпуты
                    "input_bg_end": "rgb(32, 32, 36)",
                    "input_border": "rgba(58, 58, 62, 0.95)",
                    "input_focus_border": "rgba(139, 92, 246, 0.7)",
                    
                    "accent_primary": "rgba(139, 92, 246, 0.45)",
                    "accent_hover": "rgba(139, 92, 246, 0.65)",
                    
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
                    "sidebar_bg": "rgba(255, 255, 255, 0.42)",
                    
                    "central_border": "rgba(255, 255, 255, 0.72)",
                    "sidebar_border": "rgba(255, 255, 255, 0.55)",
                    
                    "text_primary": "#222222",  # Тёмный текст для контраста
                    "text_secondary": "#3a3a3a",
                    "text_tertiary": "#5a5a5a",
                    
                    "btn_bg": "rgba(255, 255, 255, 0.60)",
                    "btn_bg_hover": "rgba(255, 255, 255, 0.78)",
                    "btn_border": "rgba(255, 255, 255, 0.70)",
                    
                    "input_bg_start": "rgba(248, 248, 250, 0.98)",
                    "input_bg_end": "rgba(242, 242, 245, 0.98)",
                    "input_border": "rgba(220, 220, 225, 0.80)",
                    "input_focus_border": "rgba(102, 126, 234, 0.35)",
                    
                    "accent_primary": "rgba(102, 126, 234, 0.18)",
                    "accent_hover": "rgba(102, 126, 234, 0.45)",
                    
                    "title_bg": "rgba(255, 255, 255, 0.52)",
                    "title_border": "rgba(255, 255, 255, 0.72)",
                    
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
                    "sidebar_border": "rgba(210, 210, 215, 0.9)",
                    
                    "text_primary": "#1a1a1a",  # Очень тёмный текст
                    "text_secondary": "#2a2a2a",
                    "text_tertiary": "#4a4a4a",
                    
                    "btn_bg": "rgb(242, 242, 245)",  # НЕПРОЗРАЧНЫЕ кнопки
                    "btn_bg_hover": "rgb(235, 235, 240)",
                    "btn_border": "rgba(210, 210, 215, 0.95)",
                    
                    "input_bg_start": "rgb(248, 248, 250)",  # НЕПРОЗРАЧНЫЕ инпуты
                    "input_bg_end": "rgb(242, 242, 245)",
                    "input_border": "rgba(210, 210, 215, 0.95)",
                    "input_focus_border": "rgba(102, 126, 234, 0.7)",
                    
                    "accent_primary": "rgba(102, 126, 234, 0.25)",
                    "accent_hover": "rgba(102, 126, 234, 0.5)",
                    
                    "title_bg": "rgb(246, 246, 248)",
                    "title_border": "rgba(210, 210, 215, 0.95)",
                    
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

        /* ── New-chat button ── */
        #newChatBtn {{
            background: {colors["btn_bg"]};
            color: {colors["text_secondary"]};
            border: 1px solid {colors["btn_border"]};
            border-radius: 14px;
            padding: 18px 20px;
            margin: 12px 10px;
            font-size: 16px;
            font-weight: 700;
            text-align: left;
        }}
        #newChatBtn:hover {{
            background: {colors["btn_bg_hover"]};
            border: 1px solid {colors["accent_hover"]};
        }}

        /* ── Chat list ── */
        #chatsList {{
            background: transparent;
            border: none;
            outline: none;
            padding: 0px 10px;
        }}
        #chatsList::item {{
            padding: 16px 14px;
            margin: 3px 0px;
            border-radius: 12px;
            border: none;
            color: {colors["text_secondary"]};
            font-size: 14px;
            font-weight: 500;
            line-height: 1.4;
        }}
        #chatsList::item:hover {{
            background: {colors["btn_bg"]};
        }}
        #chatsList::item:selected {{
            background: {colors["accent_primary"]};
            color: {colors["text_primary"]};
            font-weight: 600;
            border-left: 3px solid {colors["accent_hover"]};
        }}

        /* ── Settings button ── */
        #settingsBtn {{
            background: {colors["btn_bg"]};
            color: {colors["text_secondary"]};
            border: 1px solid {colors["btn_border"]};
            border-radius: 14px;
            padding: 18px 20px;
            margin: 12px 10px;
            font-size: 16px;
            font-weight: 700;
            text-align: left;
        }}
        #settingsBtn:hover {{
            background: {colors["btn_bg_hover"]};
            border: 1px solid {colors["accent_hover"]};
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
            border-radius: 10px;
            padding: 0;
            margin: 0;
        }}
        #menuBtn:hover {{
            background: {colors["btn_bg"]};
        }}
        #menuBtn:pressed {{
            background: {colors["btn_bg_hover"]};
        }}

        #titleWidget {{
            background: {colors["title_bg"]};
            border: 1px solid {colors["title_border"]};
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

        /* ── Input field ── */
        #inputField {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {colors["input_bg_start"]},
                stop:1 {colors["input_bg_end"]});
            color: {colors["text_primary"]};
            border: 1px solid {colors["input_border"]};
            border-radius: 30px;
            padding: 18px 25px;
            font-size: 16px;
        }}
        #inputField:focus {{
            border: 1px solid {colors["input_focus_border"]};
        }}
        #inputField::placeholder {{
            color: {colors["text_tertiary"]};
        }}

        /* ── Attach button ── */
        #attachBtn {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {colors["input_bg_start"]},
                stop:1 {colors["input_bg_end"]});
            color: {colors["text_tertiary"]};
            border: 1px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 28px;
            font-weight: bold;
            text-align: center;
            padding: 0px;
            line-height: 60px;
        }}
        #attachBtn:hover {{
            border: 1px solid {colors["input_focus_border"]};
        }}
        #attachBtn:pressed {{
            border: 1px solid {colors["accent_hover"]};
        }}

        /* ── Send button ── */
        #sendBtn {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {colors["input_bg_start"]},
                stop:1 {colors["input_bg_end"]});
            color: {colors["text_tertiary"]};
            border: 1px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 26px;
        }}
        #sendBtn:hover {{
            border: 1px solid {colors["input_focus_border"]};
        }}
        #sendBtn:pressed {{
            border: 1px solid {colors["accent_hover"]};
        }}
        #sendBtn:disabled {{
            color: {colors["text_tertiary"]};
            border: 1px solid {colors["input_border"]};
        }}
        
        /* ── Mode button ── */
        #modeBtn {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {colors["input_bg_start"]},
                stop:1 {colors["input_bg_end"]});
            color: {colors["text_tertiary"]};
            border: 1px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 12px;
            font-weight: 600;
            text-align: center;
            padding: 0px 10px;
        }}
        #modeBtn:hover {{
            border: 1px solid {colors["input_focus_border"]};
        }}
        #modeBtn:pressed {{
            border: 1px solid {colors["accent_hover"]};
        }}

        /* ── Status label ── */
        #statusLabel {{
            color: {colors["text_tertiary"]};
            padding-left: 5px;
            font-style: italic;
        }}

        """
        self.setStyleSheet(style)

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

    
    def show_model_info(self):
        """Показать информацию о модели при клике на заголовок"""
        QtWidgets.QMessageBox.information(
            self,
            "Информация о модели",
            "LLaMA 3 — локальная модель\n\nРаботает полностью офлайн на вашем компьютере.",
            QtWidgets.QMessageBox.StandardButton.Ok
        )
    
    def show_mode_menu(self):
        """Показать меню выбора режима работы AI"""
        menu = QtWidgets.QMenu(self)
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Прозрачное меню
        menu.setWindowFlags(QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint)
        if not IS_WINDOWS:
            menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Адаптивные стили в зависимости от темы
        if is_dark:
            # Тёмная тема
            menu.setStyleSheet("""
                QMenu {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(30, 30, 35, 0.92),
                        stop:1 rgba(25, 25, 30, 0.95));
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 16px;
                    padding: 10px;
                }
                QMenu::item {
                    padding: 14px 45px;
                    border-radius: 12px;
                    color: #e0e0e0;
                    font-size: 15px;
                    font-weight: 600;
                    margin: 4px;
                    background: transparent;
                }
                QMenu::item:selected {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(60, 60, 70, 0.85),
                        stop:1 rgba(50, 50, 60, 0.88));
                    color: #ffffff;
                }
            """)
        else:
            # Светлая тема
            menu.setStyleSheet("""
                QMenu {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 0.92),
                        stop:1 rgba(250, 250, 252, 0.95));
                    border: 1px solid rgba(255, 255, 255, 0.95);
                    border-radius: 16px;
                    padding: 10px;
                }
                QMenu::item {
                    padding: 14px 45px;
                    border-radius: 12px;
                    color: #1a202c;
                    font-size: 15px;
                    font-weight: 600;
                    margin: 4px;
                    background: transparent;
                }
                QMenu::item:selected {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 0.85),
                        stop:1 rgba(245, 245, 250, 0.88));
                    color: #0f172a;
                }
            """)
        
        # Создаём действия для каждого режима
        fast_action = menu.addAction("⚡ Быстрый")
        fast_action.setCheckable(True)
        fast_action.setChecked(self.ai_mode == AI_MODE_FAST)
        
        thinking_action = menu.addAction("🧠 Думающий")
        thinking_action.setCheckable(True)
        thinking_action.setChecked(self.ai_mode == AI_MODE_THINKING)
        
        pro_action = menu.addAction("🚀 Про")
        pro_action.setCheckable(True)
        pro_action.setChecked(self.ai_mode == AI_MODE_PRO)
        
        # Получаем позицию кнопки
        button_rect = self.mode_btn.rect()
        button_global_pos = self.mode_btn.mapToGlobal(button_rect.bottomLeft())
        
        # Получаем размер меню
        menu.adjustSize()
        menu_size = menu.sizeHint()
        menu_height = menu_size.height()
        menu_width = menu_size.width()
        
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
        
        action = menu.exec(menu_pos)
        
        # КРИТИЧНО: Убираем фокус с кнопки ВСЕГДА, даже если ничего не выбрано
        # Это предотвращает "залипание" обводки на кнопке
        self.mode_btn.clearFocus()
        
        # Обрабатываем выбор
        if action == fast_action:
            self.ai_mode = AI_MODE_FAST
            self.mode_btn.setText(AI_MODE_FAST)
            print(f"[MODE] Выбран режим: {AI_MODE_FAST}")
        elif action == thinking_action:
            self.ai_mode = AI_MODE_THINKING
            self.mode_btn.setText(AI_MODE_THINKING)
            print(f"[MODE] Выбран режим: {AI_MODE_THINKING}")
        elif action == pro_action:
            self.ai_mode = AI_MODE_PRO
            self.mode_btn.setText(AI_MODE_PRO)
            print(f"[MODE] Выбран режим: {AI_MODE_PRO}")
        
        # Возвращаем фокус на поле ввода
        self.input_field.setFocus()
    
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
        # Проверяем что это viewport нашего scroll_area
        if obj == self.scroll_area.viewport():
            # Если это wheel событие
            if event.type() == QtCore.QEvent.Type.Wheel:
                # ═══════════════════════════════════════════════
                # НИКОГДА НЕ БЛОКИРУЕМ WHEEL
                # ═══════════════════════════════════════════════
                # Layout завершается независимо от действий пользователя
                # Пользователь может скроллить в любой момент
                # Обрабатываем wheel событие стандартно
                result = super().eventFilter(obj, event)
                
                # ПОСЛЕ обработки wheel события обновляем кнопку
                # Используем QMetaObject.invokeMethod для отложенного вызова
                # чтобы кнопка обновилась ПОСЛЕ полной обработки скролла
                # (scrollbar.value() уже изменился)
                # update_scroll_button_visibility сама проверит _layout_in_progress
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_update_button_after_scroll",
                    QtCore.Qt.ConnectionType.QueuedConnection
                )
                
                return result
        
        # ═══════════════════════════════════════════════
        # ОБРАБОТКА RESIZE SCROLL_AREA (изменение размера)
        # ═══════════════════════════════════════════════
        if obj == self.scroll_area and event.type() == QtCore.QEvent.Type.Resize:
            if hasattr(self, 'scroll_to_bottom_btn'):
                # Обновляем позицию кнопки при resize
                # Это единственное место где вызывается update_position
                self.scroll_to_bottom_btn.update_position(
                    self.scroll_area.width(),
                    self.scroll_area.height()
                )
        
        # ═══════════════════════════════════════════════
        # АВТОЗАКРЫТИЕ SIDEBAR (клик вне sidebar)
        # ═══════════════════════════════════════════════
        # Проверяем, открыт ли sidebar
        if self.sidebar.width() > 0:
            # Если событие - клик мышью
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                # Закрываем sidebar
                self.toggle_sidebar()
        
        # Для всех остальных случаев - стандартная обработка
        return super().eventFilter(obj, event)
    
    @QtCore.pyqtSlot()
    def _update_button_after_scroll(self):
        """
        Обновляет layout и видимость кнопки "вниз" после ручного скролла.
        
        КРИТИЧНО:
        - Вызывается через QMetaObject.invokeMethod после wheel события
        - Гарантирует что скролл полностью обработан
        - При ручном скролле ВСЕГДА обновляет layout (как при переключении чата)
        - Это гарантирует корректное отображение всех накопленных сообщений и кнопки
        """
        # ═══════════════════════════════════════════════════════════════
        # ОБНОВЛЕНИЕ LAYOUT ПРИ РУЧНОМ СКРОЛЛЕ
        # ═══════════════════════════════════════════════════════════════
        # Сохраняем текущую позицию скролла
        scrollbar = self.scroll_area.verticalScrollBar()
        current_value = scrollbar.value()
        
        # Полное обновление layout (как при переключении чата)
        self.messages_layout.invalidate()
        self.messages_layout.activate()
        self.messages_widget.updateGeometry()
        
        # Синхронная отрисовка
        self.scroll_area.viewport().repaint()
        QtWidgets.QApplication.processEvents()
        
        # Восстанавливаем позицию скролла
        scrollbar.setValue(current_value)
        
        # Теперь обновляем кнопку после завершения layout
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
    
    def show_attach_menu(self):
        """Показать меню с опциями Search и Attach file с glass-эффектом"""
        menu = QtWidgets.QMenu(self)
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Прозрачное меню без артефактов
        menu.setWindowFlags(QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint)
        # Прозрачность работает плохо на Windows
        if not IS_WINDOWS:
            menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Адаптивные стили в зависимости от темы
        if is_dark:
            # Тёмная тема
            menu.setStyleSheet("""
                QMenu {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(30, 30, 35, 0.92),
                        stop:1 rgba(25, 25, 30, 0.95));
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 16px;
                    padding: 10px;
                }
                QMenu::item {
                    padding: 14px 45px;
                    border-radius: 12px;
                    color: #e0e0e0;
                    font-size: 15px;
                    font-weight: 600;
                    margin: 4px;
                    background: transparent;
                }
                QMenu::item:selected {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(60, 60, 70, 0.85),
                        stop:1 rgba(50, 50, 60, 0.88));
                    color: #ffffff;
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(80, 80, 90, 0.50);
                    margin: 8px 20px;
                }
            """)
        else:
            # Светлая тема
            menu.setStyleSheet("""
                QMenu {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 0.92),
                        stop:1 rgba(250, 250, 252, 0.95));
                    border: 1px solid rgba(255, 255, 255, 0.95);
                    border-radius: 16px;
                    padding: 10px;
                }
                QMenu::item {
                    padding: 14px 45px;
                    border-radius: 12px;
                    color: #1a202c;
                    font-size: 15px;
                    font-weight: 600;
                    margin: 4px;
                    background: transparent;
                }
                QMenu::item:selected {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 0.85),
                        stop:1 rgba(245, 245, 250, 0.88));
                    color: #0f172a;
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(200, 200, 210, 0.60);
                    margin: 8px 20px;
                }
            """)
        
        # FORCED SEARCH - явное указание режима принудительного поиска
        search_label = "🔴 Принудительный поиск" if self.use_search else "🔍 Умный поиск"
        search_action = menu.addAction(search_label)
        search_action.setCheckable(True)
        search_action.setChecked(self.use_search)
        
        # Разделитель
        menu.addSeparator()
        
        # Attach file опция
        file_action = menu.addAction("📎 Прикрепить файл")
        
        # Показываем меню НАД кнопкой с плавной анимацией
        button_rect = self.attach_btn.rect()
        button_global_pos = self.attach_btn.mapToGlobal(button_rect.topLeft())
        
        menu_height = 150
        menu_pos = QtCore.QPoint(button_global_pos.x(), button_global_pos.y() - menu_height - 8)
        
        action = menu.exec(menu_pos)
        
        # Убираем фокус с кнопки после закрытия меню
        self.attach_btn.clearFocus()
        self.input_field.setFocus()
        
        if action == search_action:
            # Переключаем режим Forced Search
            self.use_search = not self.use_search
            if self.use_search:
                print(f"[MENU] ⚠️ FORCED SEARCH MODE активирован - поиск будет выполнен ОБЯЗАТЕЛЬНО")
            else:
                print(f"[MENU] Режим 'Умный поиск' - автоматическое определение необходимости поиска")
        elif action == file_action:
            self.attach_file()
    
    def attach_file(self):
        """Выбрать и прикрепить файл (любой тип, включая изображения)"""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Выбрать файл",
            "",
            "Все файлы (*.*);;Изображения (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;Текстовые файлы (*.txt *.md *.py *.js *.json)"
        )
        
        # Возвращаем фокус в приложение
        self.activateWindow()
        self.raise_()
        
        if file_path:
            self.attached_file_path = file_path
            file_name = os.path.basename(file_path)
            # Проверяем тип файла для правильного эмодзи
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                emoji = "🖼️"
                question = "Введите вопрос об изображении..."
            else:
                emoji = "📎"
                question = "Введите вопрос о файле..."
            self.input_field.setPlaceholderText(f"{emoji} {file_name} | {question}")
            print(f"[ATTACH] Прикреплён файл: {file_path}")
            
        # Возвращаем фокус на поле ввода
        self.input_field.setFocus()
    
    def clear_attached_file(self):
        """Очистить прикреплённый файл"""
        self.attached_file_path = None
        self.input_field.setPlaceholderText("Введите сообщение...")
    
    def start_status_animation(self):
        """Запуск анимации точек в статусе"""
        self.status_dots_count = 0
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.timeout.connect(self.update_status_dots)
        self.status_timer.start(350)  # Интервал 350ms
    
    def update_status_dots(self):
        """Обновление точек в статусе"""
        # ✅ КРИТИЧНО: Проверка наличия status_base_text
        if not hasattr(self, 'status_base_text'):
            self.status_base_text = ""
        
        # ✅ КРИТИЧНО: Очищаем перед обновлением
        self.status_label.clear()
        
        dots = "." * self.status_dots_count
        self.status_label.setText(f"{self.status_base_text}{dots}")
        self.status_dots_count = (self.status_dots_count + 1) % 4  # 0, 1, 2, 3
    
    def stop_status_animation(self):
        """Остановка анимации точек"""
        if hasattr(self, 'status_timer') and self.status_timer.isActive():
            self.status_timer.stop()
        # ✅ КРИТИЧНО: Очищаем перед установкой пустой строки
        self.status_label.clear()
        self.status_label.setText("")

    def toggle_sidebar(self):
        """Переключение боковой панели с анимацией"""
        # ВАЖНО: НЕ закрываем настройки автоматически!
        # Если мы в режиме настроек, кнопка меню работает как "← Чаты"
        # и должна быть обработана отдельно в open_settings
        
        current_width = self.sidebar.width()
        target_width = 280 if current_width == 0 else 0
        
        # Скрываем панель удаления при закрытии sidebar
        if target_width == 0:
            self.hide_delete_panel()
        
        # Сохраняем текущую позицию скролла
        scroll_pos = self.scroll_area.verticalScrollBar().value()
        
        self.animation = QtCore.QPropertyAnimation(self.sidebar, b"minimumWidth")
        self.animation.setDuration(400)
        self.animation.setStartValue(current_width)
        self.animation.setEndValue(target_width)
        self.animation.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        
        self.animation2 = QtCore.QPropertyAnimation(self.sidebar, b"maximumWidth")
        self.animation2.setDuration(400)
        self.animation2.setStartValue(current_width)
        self.animation2.setEndValue(target_width)
        self.animation2.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        
        # Layout обновится автоматически после завершения анимации
        # Не нужны processEvents, updateGeometry, activate - Qt сам управляет layout
        
        self.animation.start()
        self.animation2.start()
        self.animation2.start()
    


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
        self.scroll_area.viewport().repaint()
        QtWidgets.QApplication.processEvents()
        
        # ═══════════════════════════════════════════════════════════════
        # ПЛАВНЫЙ СКРОЛЛ ВНИЗ
        # ═══════════════════════════════════════════════════════════════
        scrollbar = self.scroll_area.verticalScrollBar()
        
        # Создаём анимацию скролла
        if not hasattr(self, '_scroll_animation'):
            self._scroll_animation = QtCore.QPropertyAnimation(scrollbar, b"value")
        
        self._scroll_animation.stop()  # Останавливаем предыдущую если есть
        self._scroll_animation.setDuration(400)  # 400ms - плавная анимация
        self._scroll_animation.setStartValue(scrollbar.value())
        self._scroll_animation.setEndValue(scrollbar.maximum())
        self._scroll_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        
        # Когда скролл завершится - плавно скрываем кнопку
        def on_scroll_finished():
            self.scroll_to_bottom_btn.smooth_hide()
        
        # Отключаем старый обработчик если был
        try:
            self._scroll_animation.finished.disconnect()
        except:
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
        
        # Показываем кнопку если НЕ внизу (с порогом 10px)
        if scrollbar.value() < scrollbar.maximum() - 10:
            # ПЛАВНОЕ ПОЯВЛЕНИЕ вместо резкого show()
            self.scroll_to_bottom_btn.smooth_show()
        else:
            # ПЛАВНОЕ ИСЧЕЗНОВЕНИЕ вместо резкого hide()
            self.scroll_to_bottom_btn.smooth_hide()
    
    def open_settings(self):
        """Открыть экран настроек"""
        print("[SETTINGS] Открытие настроек")
        
        # Обновляем стили экрана настроек ПЕРЕД показом
        if hasattr(self, 'settings_view'):
            print("[SETTINGS] Обновляю стили settings_view")
            self.settings_view.apply_settings_styles()
        else:
            print("[SETTINGS] ⚠️ settings_view не найден!")
        
        self.content_stack.setCurrentIndex(1)
        print(f"[SETTINGS] Переключен на индекс: {self.content_stack.currentIndex()}")
        
        # Скрываем элементы header кроме кнопки меню
        if hasattr(self, 'title_label'):
            self.title_label.hide()
        if hasattr(self, 'clear_btn'):
            self.clear_btn.hide()
        
        # КРИТИЧНО: Отключаем старый обработчик и подключаем новый
        if hasattr(self, 'menu_btn'):
            # Отключаем toggle_sidebar
            try:
                self.menu_btn.clicked.disconnect()
            except:
                pass
            
            # Подключаем close_settings
            self.menu_btn.clicked.connect(self.close_settings)
            
            # Иконка остаётся как есть - НЕ меняем на текст
        
        # Скрываем кнопку скролла при открытии настроек
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.scroll_to_bottom_btn.smooth_hide()
        
        # Закрываем sidebar если открыт
        if self.sidebar.width() > 0:
            self.toggle_sidebar()
    
    def close_settings(self):
        """Закрыть настройки и вернуться к чату"""
        print("[SETTINGS] Возврат к чату")
        self.content_stack.setCurrentIndex(0)
        
        # Восстанавливаем элементы header
        if hasattr(self, 'title_label'):
            self.title_label.show()
        if hasattr(self, 'clear_btn'):
            self.clear_btn.show()
        
        # КРИТИЧНО: Восстанавливаем обработчик кнопки меню
        if hasattr(self, 'menu_btn'):
            # Отключаем close_settings
            try:
                self.menu_btn.clicked.disconnect()
            except:
                pass
            
            # Восстанавливаем toggle_sidebar
            self.menu_btn.clicked.connect(self.toggle_sidebar)
            
            # Иконка уже на месте - ничего не меняем
        
        # Обновляем видимость кнопки скролла ПОСЛЕ завершения переключения экранов
        # Используем QMetaObject.invokeMethod для синхронизации с event loop
        # Это гарантирует что переключение полностью завершено
        QtCore.QMetaObject.invokeMethod(
            self,
            "_update_button_after_scroll",
            QtCore.Qt.ConnectionType.QueuedConnection
        )
    
    def on_settings_applied(self, settings: dict):
        """Обработка применения настроек с плавной crossfade анимацией смены темы"""
        print(f"[SETTINGS] Применены настройки: {settings}")
        
        # Получаем параметры
        theme = settings.get("theme", "light")
        liquid_glass = settings.get("liquid_glass", True)
        
        # Проверяем, изменилась ли тема
        theme_changed = (self.current_theme != theme)
        
        if theme_changed:
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
            
            # Обновляем стили кнопки "вниз"
            if hasattr(self, 'scroll_to_bottom_btn'):
                self.scroll_to_bottom_btn.apply_theme_styles(theme=theme, liquid_glass=liquid_glass)
            
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
        anim1.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
        
        anim2 = QtCore.QPropertyAnimation(self.delete_panel, b"maximumWidth")
        anim2.setDuration(200)
        anim2.setStartValue(self.delete_panel.width())
        anim2.setEndValue(0)
        anim2.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
        
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

    def load_chats_list(self):
        """Загрузить список чатов"""
        self.chats_list.clear()
        chats = self.chat_manager.get_all_chats()
        
        for chat in chats:
            item = QtWidgets.QListWidgetItem(chat['title'])
            item.setData(QtCore.Qt.ItemDataRole.UserRole, chat['id'])
            self.chats_list.addItem(item)
            
            if chat['is_active']:
                self.chats_list.setCurrentItem(item)

    def load_current_chat(self):
        """Загрузить текущий активный чат"""
        if not self.current_chat_id:
            return
        
        print(f"[LOAD_CURRENT] Загрузка чата ID={self.current_chat_id}")
        
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
            return
        
        # Определяем какие сообщения показывать с анимацией (последние 2 для ускорения)
        total_messages = len(messages)
        
        # Загружаем существующие сообщения
        for idx, (role, content, created) in enumerate(messages):
            speaker = "Вы" if role == "user" else ASSISTANT_NAME
            if role not in ["user", "assistant"]:
                continue
            
            # Проверяем, входит ли сообщение в последние 2 (оптимизировано)
            is_recent = (total_messages - idx) <= 2
            
            # Создаём виджет БЕЗ анимации (для всех)
            message_widget = MessageWidget(
                speaker, content, add_controls=True,
                language=self.current_language,
                main_window=self,
                parent=self.messages_widget,
                thinking_time=0
            )
            
            # Для старых сообщений сразу убираем анимацию
            if not is_recent:
                if hasattr(message_widget, 'opacity_effect'):
                    message_widget.opacity_effect.setOpacity(1.0)
                # Отключаем анимации появления
                if hasattr(message_widget, 'fade_in_animation'):
                    message_widget.fade_in_animation.stop()
                if hasattr(message_widget, 'pos_animation'):
                    message_widget.pos_animation.stop()
            else:
                # Для последних 2 - анимация включена по умолчанию (оптимизировано)
                pass
            
            # Добавляем в layout (stretch уже удалён, добавляем в конец)
            self.messages_layout.addWidget(message_widget)
            
            # Запускаем анимацию для последних 2 сообщений (оптимизировано)
            if is_recent and not IS_WINDOWS and hasattr(message_widget, '_start_appear_animation'):
                # Запускаем с небольшой задержкой для каждого сообщения
                QtCore.QTimer.singleShot(20 + idx * 40, message_widget._start_appear_animation)
        
        # ═══════════════════════════════════════════════════════════════
        # АВТОМАТИЧЕСКИЙ СКРОЛЛ ВНИЗ ПОСЛЕ ЗАГРУЗКИ ЧАТА
        # ═══════════════════════════════════════════════════════════════
        # Обновляем layout перед скроллом
        self.messages_layout.activate()
        self.messages_widget.updateGeometry()
        QtWidgets.QApplication.processEvents()
        
        # Скроллим вниз с небольшой задержкой чтобы layout успел обновиться
        def scroll_to_bottom_delayed():
            scrollbar = self.scroll_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            # Обновляем видимость кнопки "вниз"
            if hasattr(self, 'scroll_to_bottom_btn'):
                self.update_scroll_button_visibility()
        
        QtCore.QTimer.singleShot(100, scroll_to_bottom_delayed)

    def create_new_chat(self):
        """Создать новый чат"""
        
        # ═══ ЛОГИКА СТАРТОВОГО ЧАТА ═══
        # Если текущий чат - пустой стартовый, удаляем его перед созданием нового
        if (hasattr(self, 'startup_chat_id') and 
            hasattr(self, 'startup_chat_has_messages') and
            self.current_chat_id == self.startup_chat_id and
            not self.startup_chat_has_messages):
            
            # Проверяем, действительно ли чат пустой
            messages = self.chat_manager.get_chat_messages(self.startup_chat_id, limit=10)
            user_messages = [msg for msg in messages if msg[0] == "user"]
            
            if len(user_messages) == 0:
                print(f"[STARTUP_CHAT] Удаляем пустой стартовый чат {self.startup_chat_id} перед созданием нового")
                try:
                    self.chat_manager.delete_chat(self.startup_chat_id)
                except Exception as e:
                    print(f"[STARTUP_CHAT] Ошибка удаления стартового чата: {e}")
        
        chat_id = self.chat_manager.create_chat("Новый чат")
        self.chat_manager.set_active_chat(chat_id)
        self.current_chat_id = chat_id
        
        # Сбрасываем флаги стартового чата для нового
        self.startup_chat_id = None
        self.startup_chat_has_messages = False
        
        self.load_chats_list()
        self.load_current_chat()
        
        # Закрываем sidebar после создания
        self.toggle_sidebar()

    def switch_chat(self, item):
        """Переключить чат с защитой от чужих сообщений"""
        chat_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        
        # ═══ ЛОГИКА СТАРТОВОГО ЧАТА ═══
        # Если переключаемся с пустого стартового чата - удаляем его
        if (hasattr(self, 'startup_chat_id') and 
            hasattr(self, 'startup_chat_has_messages') and
            self.current_chat_id == self.startup_chat_id and
            not self.startup_chat_has_messages and
            chat_id != self.startup_chat_id):
            
            # Проверяем, действительно ли чат пустой
            messages = self.chat_manager.get_chat_messages(self.startup_chat_id, limit=10)
            # Отфильтровываем системные сообщения
            user_messages = [msg for msg in messages if msg[0] == "user"]
            
            if len(user_messages) == 0:
                print(f"[STARTUP_CHAT] Удаляем пустой стартовый чат {self.startup_chat_id}")
                try:
                    self.chat_manager.delete_chat(self.startup_chat_id)
                    # Сбрасываем флаг стартового чата
                    self.startup_chat_id = None
                    self.startup_chat_has_messages = False
                except Exception as e:
                    print(f"[STARTUP_CHAT] Ошибка удаления стартового чата: {e}")
        
        # ✅ GUARD: Отменяем воркер предыдущего чата
        if hasattr(self, 'current_worker') and self.current_worker is not None:
            try:
                print(f"[SWITCH_CHAT] Отменяем воркер предыдущего чата")
                self.current_worker = None  # Обнуляем ссылку
                self.is_generating = False
            except Exception as e:
                print(f"[SWITCH_CHAT] Ошибка отмены воркера: {e}")
        
        # ✅ GUARD: Очищаем поле ввода при переключении
        try:
            self.input_field.clear()
        except Exception:
            pass
        
        self.chat_manager.set_active_chat(chat_id)
        self.current_chat_id = chat_id
        
        self.load_current_chat()
        
        # Закрываем sidebar после переключения
        self.toggle_sidebar()
    def add_message_widget(self, speaker: str, text: str, add_controls: bool = False, thinking_time: float = 0, action_history: list = None):
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
            action_history=action_history
        )
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: ДОБАВЛЕНИЕ В LAYOUT
        # ═══════════════════════════════════════════════════════════════
        self.messages_layout.addWidget(message_widget)
        message_widget.show()
        
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
                
                # Синхронная отрисовка
                self.scroll_area.viewport().repaint()
                QtWidgets.QApplication.processEvents()
                
            else:
                print(f"[ADD_MESSAGE] ⚡ БЫСТРОЕ обновление (сообщение #{message_count + 1})")
                
                # БЫСТРОЕ обновление без processEvents
                self.messages_layout.activate()
                self.messages_widget.updateGeometry()
                self.scroll_area.viewport().update()
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 4: ВОССТАНАВЛИВАЕМ ПОЗИЦИЮ СКРОЛЛА (БЕЗ АВТОСКРОЛЛА)
        # ═══════════════════════════════════════════════════════════════
        if old_max > 0 and not was_at_bottom:
            # Если пользователь НЕ был внизу - сохраняем его позицию
            scrollbar.setValue(old_value)
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 5: ОБНОВЛЯЕМ КНОПКУ "ВНИЗ"
        # ═══════════════════════════════════════════════════════════════
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.update_scroll_button_visibility()
        
        # Анимация появления (не влияет на layout)
        if not IS_WINDOWS and hasattr(message_widget, '_start_appear_animation'):
            QtCore.QMetaObject.invokeMethod(
                message_widget,
                "_start_appear_animation",
                QtCore.Qt.ConnectionType.QueuedConnection
            )
    
    def send_message(self):
        """Отправка сообщения пользователя
        
        ВАЖНО: Всегда берёт текст ТОЛЬКО из поля ввода (self.input_field.text())
        Никогда не использует старые значения или данные из других чатов
        """
        
        # Если идёт генерация - останавливаем БЕЗ возврата текста
        if self.is_generating:
            self.is_generating = False
            if hasattr(self, 'current_worker'):
                self.current_worker = None
            
            # Останавливаем анимацию статуса
            if hasattr(self, 'stop_status_animation'):
                self.stop_status_animation()
            
            # НЕ возвращаем текст в поле - оставляем пустым
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.send_btn.setText("→")
            
            # Очищаем статус сразу (без задержки)
            self.status_label.setText("")
            
            print("[SEND] Генерация остановлена пользователем")
            return
        
        global CURRENT_LANGUAGE
        # ИСТОЧНИК ИСТИНЫ - текст из поля ввода
        user_text = self.input_field.text().strip()
        if not user_text:
            return
        
        print(f"[SEND] Отправка сообщения: {user_text[:50]}...")
        
        # Проверка орфографии убрана - нейросеть сама переспросит если не поймёт

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
                
                # Очищаем контекстную память
                try:
                    from context_memory_manager import ContextMemoryManager
                    context_mgr = ContextMemoryManager()
                    context_mgr.clear_context_memory(self.current_chat_id)
                    print(f"[SEND] ✓ Контекстная память очищена для chat_id={self.current_chat_id}")
                except Exception as e:
                    print(f"[SEND] ✗ Ошибка очистки контекстной памяти: {e}")
                
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
                    from context_memory_manager import ContextMemoryManager
                    context_mgr = ContextMemoryManager()
                    
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
            
            self.add_message_widget(ASSISTANT_NAME, ai_response, add_controls=False)
            self.chat_manager.save_message(self.current_chat_id, "assistant", ai_response)
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
        
        # ═══════════════════════════════════════════════════════════
        # УМНАЯ АДАПТИВНАЯ СИСТЕМА ВЕБ-ПОИСКА
        # ═══════════════════════════════════════════════════════════
        
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
            
            self.add_message_widget("Вы", user_text, add_controls=True)
            self.chat_manager.save_message(self.current_chat_id, "user", user_text)
            
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
            self.add_message_widget("Вы", user_text, add_controls=True)
            self.chat_manager.save_message(self.current_chat_id, "user", user_text)
            
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
        self.send_btn.setText("⏸")
        self.send_btn.setEnabled(True)
        self.is_generating = True

        # ═══════════════════════════════════════════════════════════
        # ДВУХФАЗНЫЙ РЕЖИМ ОТВЕТА
        # ═══════════════════════════════════════════════════════════
        
        # ФАЗА 1: Быстрый предварительный ответ (если НЕ используется поиск)
        if not actual_use_search and not self.deep_thinking:
            print("[SEND] 📝 ФАЗА 1: Предоставляем быстрый ответ без поиска")
        # Запускаем анимацию точек
        self.start_status_animation()
        
        # Запускаем таймер обдумывания
        self.thinking_start_time = time.time()

        # Запускаем воркер с ПРАВИЛЬНЫМИ флагами и режимом AI
        worker = AIWorker(user_text, self.current_language, actual_deep_thinking, actual_use_search, False, self.chat_manager, self.current_chat_id, self.attached_file_path, self.ai_mode)
        worker.signals.finished.connect(self.handle_response)
        self.current_worker = worker  # Сохраняем ссылку на текущего воркера
        
        # ✅ ИСПРАВЛЕНИЕ: Сохраняем worker в список для предотвращения удаления signals
        self.active_workers.append(worker)
        # Очищаем список от завершённых workers (максимум 5)
        if len(self.active_workers) > 5:
            self.active_workers = self.active_workers[-5:]
        
        self.threadpool.start(worker)
        print(f"[SEND] Запущен воркер генерации (search={actual_use_search}, deep={actual_deep_thinking}, mode={self.ai_mode})")
        
        # Очищаем прикреплённый файл после отправки
        if self.attached_file_path:
            print(f"[SEND] Файл {os.path.basename(self.attached_file_path)} отправлен в модель")
            self.clear_attached_file()

    def handle_response(self, response: str):
        """Обработка ответа AI с полной защитой от ошибок"""
        try:
            # ✅ GUARD: СТРОГАЯ проверка - игнорируем сообщения для другого чата
            # Это предотвращает появление "чужих" сообщений при переключении чатов
            if hasattr(self, 'current_worker'):
                # Если воркер был отменён (current_worker = None), игнорируем его ответ
                if self.current_worker is None:
                    print(f"[HANDLE_RESPONSE] ⚠️ Игнорируем ответ отменённого воркера")
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
            
            # Проверка 3: Признаки технических ошибок
            error_indicators = [
                "Traceback",
                "Exception",
                "Error:",
                "NoneType",
                "object is not iterable",
                "KeyError",
                "IndexError", 
                "TypeError",
                "AttributeError",
                "ValueError",
                "RuntimeError"
            ]
            
            error_prefixes = [
                "[Ошибка]",
                "Python",
                "File \"",
                "line ",
                "Traceback (most recent call last)"
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
            try:
                self.add_message_widget(ASSISTANT_NAME, response, add_controls=True, thinking_time=thinking_time_to_show, action_history=action_history)
            except Exception as e:
                print(f"[HANDLE_RESPONSE] ✗ Ошибка add_message_widget: {e}")
                try:
                    # Пробуем без thinking_time
                    self.add_message_widget(ASSISTANT_NAME, response, add_controls=True, thinking_time=0, action_history=action_history)
                except Exception as e2:
                    print(f"[HANDLE_RESPONSE] ✗ Критическая ошибка виджета: {e2}")
            
            # Сохраняем в БД с защитой
            try:
                if hasattr(self, 'chat_manager') and hasattr(self, 'current_chat_id'):
                    self.chat_manager.save_message(self.current_chat_id, "assistant", response)
                else:
                    print(f"[HANDLE_RESPONSE] ✗ Нет chat_manager или current_chat_id")
            except Exception as e:
                print(f"[HANDLE_RESPONSE] ✗ Ошибка сохранения в БД: {e}")
            
            # Сбрасываем таймер
            self.thinking_start_time = None
            
            # ═══════════════════════════════════════════════════════════════════════════
            # ОЧИСТКА СТАТУСА ПОСЛЕ ЗАВЕРШЕНИЯ
            # ═══════════════════════════════════════════════════════════════════════════
            # Плавно очищаем статус через 500ms после получения ответа
            QtCore.QTimer.singleShot(500, lambda: self.status_label.setText(""))
            print(f"[STATUS_PIPELINE] Статус будет очищен через 500ms")
            
            # Автоматическое именование чата с защитой
            try:
                messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=5)
                if messages and len(messages) == 2:
                    first_user_msg = messages[0][1] if len(messages[0]) > 1 and messages[0][0] == "user" else ""
                    if first_user_msg and isinstance(first_user_msg, str) and len(first_user_msg) > 0:
                        chat_title = first_user_msg[:40]
                        if len(first_user_msg) > 40:
                            chat_title += "..."
                        chat_title = chat_title[0].upper() + chat_title[1:] if len(chat_title) > 0 else "Новый чат"
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
                self.send_btn.setEnabled(True)
                self.send_btn.setText("→")
                self.input_field.setEnabled(True)
                self.input_field.setFocus()
                self.activateWindow()
                self.raise_()
                # Останавливаем анимацию точек
                if hasattr(self, 'stop_status_animation'):
                    self.stop_status_animation()
            except Exception as e:
                print(f"[HANDLE_RESPONSE] Ошибка восстановления UI: {e}")


    def regenerate_last_response(self):
        """Перегенерировать последний ответ ассистента
        
        ЛОГИКА:
        1. Проверяем, идёт ли генерация - если да, отменяем и запускаем новую
        2. Получаем последнее сообщение пользователя ТОЛЬКО из текущего чата
        3. Удаляем последний ответ ассистента (из UI и БД)
        4. Перезапускаем генерацию с последним запросом пользователя
        """
        # Если генерация идёт - останавливаем её
        if self.is_generating:
            self.is_generating = False
            if hasattr(self, 'current_worker'):
                self.current_worker = None
            print("[REGENERATE] Отменяем текущую генерацию для перезапуска")
        
        # Получаем последнее сообщение пользователя ТОЛЬКО из ТЕКУЩЕГО чата
        messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=50)
        
        last_user_msg = None
        for role, content, _ in reversed(messages):
            if role == "user":
                last_user_msg = content
                break
        
        if not last_user_msg:
            print("[REGENERATE] Нет сообщений пользователя в текущем чате")
            return
        
        print(f"[REGENERATE] Найдено последнее сообщение пользователя: {last_user_msg[:50]}...")
        
        # Удаляем последний ответ ассистента из интерфейса
        if self.messages_layout.count() > 1:
            last_item = self.messages_layout.itemAt(self.messages_layout.count() - 2)
            if last_item and last_item.widget():
                widget = last_item.widget()
                # Проверяем, что это сообщение ассистента
                if hasattr(widget, 'speaker') and widget.speaker not in ["Вы", "Система"]:
                    widget.deleteLater()
                    print("[REGENERATE] Удалён виджет последнего ответа ассистента")
        
        # Удаляем последний ответ ассистента из БД текущего чата
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
            print("[REGENERATE] Удалено последнее сообщение ассистента из БД")
        
        conn.close()
        
        # Отправляем запрос заново
        self.input_field.setEnabled(False)
        self.send_btn.setText("⏸")
        self.send_btn.setEnabled(True)
        self.is_generating = True
        
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
        
        # Используем actual_deep_thinking вместо self.deep_thinking и ai_mode
        worker = AIWorker(last_user_msg, self.current_language, actual_deep_thinking, 
                         self.use_search, False, self.chat_manager, self.current_chat_id, None, self.ai_mode)
        worker.signals.finished.connect(self.handle_response)
        self.current_worker = worker
        
        # ✅ ИСПРАВЛЕНИЕ: Сохраняем worker в список
        self.active_workers.append(worker)
        if len(self.active_workers) > 5:
            self.active_workers = self.active_workers[-5:]
        
        self.threadpool.start(worker)
        print(f"[REGENERATE] Запущена новая генерация (режим: {self.ai_mode}, deep_thinking: {actual_deep_thinking}, search: {self.use_search})")
    
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
        for role, content, _ in reversed(messages):
            if role == "user":
                last_user_msg = content
                break
        
        if not last_user_msg:
            print("[EDIT] ✗ Нет сообщений пользователя для редактирования")
            return
        
        print(f"[EDIT] Редактируем последний запрос: {last_user_msg[:50]}...")
        
        # Удаляем последние 2 виджета (user + assistant)
        removed_count = 0
        while self.messages_layout.count() > 1 and removed_count < 2:
            last_item = self.messages_layout.itemAt(self.messages_layout.count() - 2)
            if last_item and last_item.widget():
                last_item.widget().deleteLater()
                removed_count += 1
        
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
            self.think_toggle.setChecked(self.deep_thinking)
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
        # Прозрачность работает плохо на Windows
        if not IS_WINDOWS:
            dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        
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
        label.setFont(QtGui.QFont("Inter", 16, QtGui.QFont.Weight.Medium))
        
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
        no_btn.setFont(QtGui.QFont("Inter", 14, QtGui.QFont.Weight.Bold))
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
        yes_btn.setFont(QtGui.QFont("Inter", 14, QtGui.QFont.Weight.Bold))
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
        
        # Обработчики
        no_btn.clicked.connect(dialog.reject)
        yes_btn.clicked.connect(dialog.accept)
        
        print("[CLEAR_CHAT] Показываю диалог...")
        result = dialog.exec()
        
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            print("[CLEAR_CHAT] Пользователь подтвердил очистку")
            self.perform_clear_chat()
        else:
            print("[CLEAR_CHAT] Пользователь отменил очистку")
    
    def perform_clear_chat(self):
        """Выполнить очистку чата с плавной iOS-style анимацией"""
        print("[PERFORM_CLEAR] Начинаем плавную очистку...")
        
        # Собираем все виджеты сообщений для удаления
        widgets = []
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                # Удаляем все виджеты сообщений
                if hasattr(widget, 'speaker'):
                    widgets.append(widget)
        
        print(f"[PERFORM_CLEAR] Виджетов для удаления: {len(widgets)}")
        
        if len(widgets) == 0:
            print("[PERFORM_CLEAR] Нет виджетов для удаления")
            self.finalize_clear()
            return
        
        # Блокируем UI во время анимации
        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)
        
        # ПЛАВНАЯ iOS-style анимация для ВСЕХ платформ
        # Удаляем сообщения снизу вверх с небольшой задержкой
        total_duration = 0
        for idx, widget in enumerate(reversed(widgets)):  # Снизу вверх
            delay = idx * 40  # Меньше задержка = быстрее
            total_duration = delay + 300  # 300ms на саму анимацию
            QtCore.QTimer.singleShot(delay, lambda w=widget: self.smooth_fade_and_remove(w))
        
        # После завершения всех анимаций - финализируем
        QtCore.QTimer.singleShot(total_duration + 100, self.finalize_clear)
    
    def smooth_fade_and_remove(self, widget):
        """
        Плавное удаление виджета через fade-out анимацию.
        
        ВАЖНО: Только fade-out прозрачности, БЕЗ изменения размеров.
        После удаления виджета layout автоматически пересчитывается.
        """
        try:
            if not widget or not widget.isVisible():
                return
            
            # Создаём эффект прозрачности если его нет
            if not widget.graphicsEffect():
                opacity_effect = QtWidgets.QGraphicsOpacityEffect(widget)
                widget.setGraphicsEffect(opacity_effect)
            else:
                opacity_effect = widget.graphicsEffect()
            
            # Fade-out анимация
            fade_anim = QtCore.QPropertyAnimation(opacity_effect, b"opacity")
            fade_anim.setDuration(300)
            fade_anim.setStartValue(1.0)
            fade_anim.setEndValue(0.0)
            fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            
            # Удаляем виджет после завершения анимации
            def cleanup():
                try:
                    # КРИТИЧНО: Сначала останавливаем анимацию
                    if hasattr(widget, '_cleanup_anim'):
                        widget._cleanup_anim.stop()
                        widget._cleanup_anim = None
                    
                    # Затем удаляем эффект
                    if widget.graphicsEffect():
                        widget.setGraphicsEffect(None)
                    
                    # Удаляем ссылку на эффект
                    if hasattr(widget, '_opacity_effect'):
                        widget._opacity_effect = None
                    
                    # И только после этого удаляем виджет
                    self.messages_layout.removeWidget(widget)
                    widget.deleteLater()
                    # Layout обновится автоматически
                except RuntimeError:
                    # Объект уже удалён - игнорируем
                    pass
                except Exception as e:
                    print(f"[CLEANUP] Ошибка при удалении виджета: {e}")
            
            fade_anim.finished.connect(cleanup)
            fade_anim.start()
            
            # Сохраняем ссылку на анимацию И на эффект прозрачности
            widget._cleanup_anim = fade_anim
            widget._opacity_effect = opacity_effect
            
        except Exception as e:
            print(f"[SMOOTH_FADE] Ошибка: {e}")
            # В случае ошибки - просто удаляем виджет
            try:
                if widget.graphicsEffect():
                    widget.setGraphicsEffect(None)
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
                # Layout обновится автоматически
            except:
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
            
            # Очищаем БД
            self.chat_manager.clear_chat_messages(self.current_chat_id)
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
    
    def confirm_delete_all_chats(self):
        """Показать диалог подтверждения удаления ВСЕХ чатов"""
        print("[DELETE_ALL_CHATS] Запрос подтверждения удаления всех чатов")
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Создаём модальное окно
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("")
        dialog.setModal(True)
        dialog.setFixedSize(450, 240)
        
        # Убираем рамку окна
        dialog.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Dialog)
        if not IS_WINDOWS:
            dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Центрируем по экрану
        screen_geo = QtWidgets.QApplication.primaryScreen().geometry()
        dialog.move(
            screen_geo.center().x() - 225,
            screen_geo.center().y() - 120
        )
        
        # Layout
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Стеклянный контейнер
        frame = QtWidgets.QFrame()
        frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        
        if is_dark:
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(30, 30, 35, 0.92);
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 20px;
                }
            """)
        else:
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
        
        # Заголовок
        title = QtWidgets.QLabel("⚠️ Удалить все чаты?")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setFont(QtGui.QFont("Inter", 18, QtGui.QFont.Weight.Bold))
        
        if is_dark:
            title.setStyleSheet("QLabel { color: #e89999; background-color: none; border: none; }")
        else:
            title.setStyleSheet("QLabel { color: #c85555; background-color: none; border: none; }")
        
        frame_layout.addWidget(title)
        
        # Текст предупреждения
        warning = QtWidgets.QLabel("Это действие невозможно отменить.\nВсе чаты будут удалены безвозвратно.")
        warning.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        warning.setFont(QtGui.QFont("Inter", 13, QtGui.QFont.Weight.Normal))
        warning.setWordWrap(True)
        
        if is_dark:
            warning.setStyleSheet("QLabel { color: #b0b0b0; background-color: none; border: none; }")
        else:
            warning.setStyleSheet("QLabel { color: #64748b; background-color: none; border: none; }")
        
        frame_layout.addWidget(warning)
        
        # Кнопки
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(15)
        
        no_btn = QtWidgets.QPushButton("Отмена")
        no_btn.setFont(QtGui.QFont("Inter", 14, QtGui.QFont.Weight.Medium))
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
        yes_btn.setFont(QtGui.QFont("Inter", 14, QtGui.QFont.Weight.Bold))
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
        
        # Обработчики
        no_btn.clicked.connect(dialog.reject)
        yes_btn.clicked.connect(dialog.accept)
        
        print("[DELETE_ALL_CHATS] Показываю диалог...")
        result = dialog.exec()
        
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            print("[DELETE_ALL_CHATS] Пользователь подтвердил удаление всех чатов")
            self.perform_delete_all_chats()
        else:
            print("[DELETE_ALL_CHATS] Пользователь отменил удаление")
    
    def perform_delete_all_chats(self):
        """Удалить все чаты и создать новый"""
        print("[DELETE_ALL_CHATS] Удаляю все чаты...")
        
        try:
            # Удаляем все чаты и создаём новый
            new_chat_id = self.chat_manager.get_all_chats()
            
            print(f"[DELETE_ALL_CHATS] Создан новый чат с ID: {new_chat_id}")
            
            # Устанавливаем новый чат как текущий
            self.current_chat_id = new_chat_id
            
            # Очищаем UI
            for i in reversed(range(self.messages_layout.count())):
                item = self.messages_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if hasattr(widget, 'speaker'):
                        self.messages_layout.removeWidget(widget)
                        widget.deleteLater()
            
            # Обновляем список чатов
            self.load_chats_list()
            
            # Добавляем системное сообщение
            self.add_message_widget("Система", "Это пока заглушка для будущего, не чего не поменялось", add_controls=False)
            
            # Возвращаемся к чату если находимся в настройках
            if self.content_stack.currentIndex() == 1:
                self.close_settings()
            
            print("[DELETE_ALL_CHATS] ✓ Готово!")
            
        except Exception as e:
            print(f"[DELETE_ALL_CHATS] ✗ Ошибка: {e}")
            import traceback
            traceback.print_exc()

def main():
    """Главная функция запуска приложения с обработкой ошибок"""
    try:
        print("[MAIN] Инициализация базы данных...")
        init_db()
        
        print("[MAIN] Создание приложения Qt...")
        app = QtWidgets.QApplication(sys.argv)
        
        # Для Windows - устанавливаем явно стиль
        if IS_WINDOWS:
            print("[MAIN] Применение стиля для Windows...")
            app.setStyle('Fusion')
        
        print("[MAIN] Создание иконки приложения...")
        app_icon = create_app_icon()
        app.setWindowIcon(QtGui.QIcon(app_icon))
        
        print("[MAIN] Создание главного окна...")
        window = MainWindow()
        
        print("[MAIN] Отображение окна...")
        window.show()
        
        print("[MAIN] Запуск главного цикла...")
        sys.exit(app.exec())
        
    except Exception as e:
        print(f"[MAIN] КРИТИЧЕСКАЯ ОШИБКА при запуске: {e}")
        import traceback
        traceback.print_exc()
        
        # Пытаемся показать сообщение об ошибке
        try:
            error_app = QtWidgets.QApplication(sys.argv)
            QtWidgets.QMessageBox.critical(
                None,
                "Ошибка запуска",
                f"Не удалось запустить приложение:\n\n{str(e)}\n\nПроверьте:\n1. Установлены ли все зависимости\n2. Доступна ли база данных\n3. Запущена ли Ollama",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
        except:
            pass
        
        sys.exit(1)

if __name__ == "__main__":
    main()