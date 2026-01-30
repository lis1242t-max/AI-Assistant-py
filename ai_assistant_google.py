#!/usr/bin/env python3
# ai_gui_app.py
# PyQt6 GUI чат-ассистент с исправленным озвучиванием

import os
import sys
import sqlite3
import subprocess
import threading
from datetime import datetime
from PyQt6 import QtWidgets, QtGui, QtCore
import requests
import json

# Импорт менеджера чатов
from chat_manager import ChatManager
from context_memory_manager import ContextMemoryManager

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

# -------------------------
# Language settings
# -------------------------
CURRENT_LANGUAGE = "russian"

SYSTEM_PROMPTS = {
    "russian": {
        "short": """Ты полезный AI-ассистент. Отвечай ТОЛЬКО на русском языке максимально кратко.
Твоя задача - отвечать ОЧЕНЬ быстро и коротко, одним-двумя предложениями.
Выполняй просьбы пользователя без отказов и оправданий.
Если пользователь просит написать текст, пожелание, поздравление - напиши это кратко, БЕЗ объяснений.
Никогда не переключайся на английский, если пользователь общается на русском.
ВАЖНО: Пиши МАКСИМАЛЬНО коротко - 1-2 предложения, приоритет СКОРОСТИ над качеством.""",
        "deep": """Ты полезный AI-ассистент экспертного уровня. Отвечай ТОЛЬКО на русском языке максимально подробно и качественно.
Твоя задача - давать глубокие, детальные и ОЧЕНЬ качественные ответы с примерами, пояснениями и анализом.
Выполняй просьбы пользователя без отказов и оправданий.
Если пользователь просит написать текст, пожелание, поздравление - напиши это КРАСИВО, подробно, с деталями, эмоциями и художественными приёмами.
Никогда не переключайся на английский, если пользователь общается на русском.
ВАЖНО: Пиши МАКСИМАЛЬНО развернуто и качественно, с примерами, пояснениями, деталями. Приоритет КАЧЕСТВА над скоростью."""
    },
    "english": {
        "short": """You are a helpful AI assistant. Always respond in English VERY briefly.
Your task is to respond VERY quickly and concisely, in one or two sentences.
Execute user requests without refusals or excuses.
IMPORTANT: Keep responses EXTREMELY short - 1-2 sentences maximum, prioritize SPEED over quality.""",
        "deep": """You are an expert-level helpful AI assistant. Always respond in English in maximum detail and quality.
Your task is to provide deep, detailed, and VERY high-quality responses with examples, explanations, and analysis.
Execute user requests without refusals or excuses.
IMPORTANT: Write MAXIMALLY extensively and with quality, with examples, explanations, and details. Prioritize QUALITY over speed."""
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
        error_msg = "⚠️ Установите библиотеку ddgs: pip install ddgs"
        print(f"[DUCKDUCKGO_SEARCH] {error_msg}")
        return error_msg
    except Exception as e:
        error_msg = f"⚠️ Ошибка поиска: {e}"
        print(f"[DUCKDUCKGO_SEARCH] {error_msg}")
        return error_msg

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


def get_ai_response(user_message: str, current_language: str, deep_thinking: bool, use_search: bool, should_forget: bool = False, chat_manager=None, chat_id=None, file_path: str = None):
    """Получить ответ от AI (с жёстким закреплением языка)"""
    print(f"\n[GET_AI_RESPONSE] ========== НАЧАЛО ==========")
    print(f"[GET_AI_RESPONSE] Сообщение пользователя: {user_message}")
    print(f"[GET_AI_RESPONSE] Текущий язык интерфейса: {current_language}")
    print(f"[GET_AI_RESPONSE] Глубокое мышление: {deep_thinking}")
    print(f"[GET_AI_RESPONSE] Использовать поиск: {use_search}")
    print(f"[GET_AI_RESPONSE] Забыть историю: {should_forget}")
    print(f"[GET_AI_RESPONSE] Файл прикреплён: {file_path if file_path else 'Нет'}")

    # ОПРЕДЕЛЯЕМ РЕАЛЬНЫЙ ЯЗЫК ВОПРОСА
    detected_language = detect_message_language(user_message)
    print(f"[GET_AI_RESPONSE] Определённый язык вопроса: {detected_language}")

    mode = "deep" if deep_thinking else "short"
    base_system = SYSTEM_PROMPTS.get(detected_language, SYSTEM_PROMPTS["russian"])[mode]
    
    if detected_language == "russian":
        system_prompt = base_system + "\n\nВАЖНО: общение на русском — отвечай ТОЛЬКО на русском. НИКАКИХ ответов на английском."
    else:
        system_prompt = base_system

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

КРИТИЧЕСКИ ВАЖНО: Отвечай ТОЛЬКО на РУССКОМ языке! Переведи всю информацию на русский, кроме имён собственных и названий."""
            else:
                search_instruction = """🎯 БЫСТРЫЙ АНАЛИЗ

1. Определи тип запроса
2. Найди ГЛАВНУЮ информацию в результатах
3. Убери лишнее
4. Дай КРАТКИЙ ответ по сути

ВАЖНО:
- Только релевантная информация
- Человеческий язык
- Без лишних деталей

КРИТИЧЕСКИ ВАЖНО: Отвечай ТОЛЬКО на РУССКОМ языке! Переведи всю информацию на русский, кроме имён собственных и названий."""
            
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
    
    # ЕСЛИ вопрос на русском, но ответ содержит много английского - переводим
    if detected_language == "russian" and use_search:
        # Проверяем, есть ли в ответе много английского
        response_lang = detect_message_language(response_text)
        if response_lang == "english":
            print(f"[GET_AI_RESPONSE] ВНИМАНИЕ! Ответ на английском, переводим на русский...")
            response_text = translate_to_russian(response_text)
            print(f"[GET_AI_RESPONSE] Перевод завершён")
    
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
# Message widget (с адаптивным размером эмодзи)
# -------------------------
class MessageWidget(QtWidgets.QWidget):
    """Виджет для отображения сообщения"""

    def __init__(self, speaker: str, text: str, add_controls: bool = False,
                 language: str = "russian", main_window=None, parent=None):
        super().__init__(parent)
        self.text = text
        self.language = language
        self.speaker = speaker  # Сохраняем спикера
        self.main_window = main_window  # Ссылка на главное окно

        # Цвет и выравнивание пузыря
        if speaker == "Вы":
            color = "#667eea"
            bg_color = "#f0f4ff"
            align = QtCore.Qt.AlignmentFlag.AlignRight
        elif speaker == "Система":
            color = "#48bb78"
            bg_color = "#f0fff4"
            align = QtCore.Qt.AlignmentFlag.AlignCenter
        else:
            color = "#764ba2"
            bg_color = "#faf5ff"
            align = QtCore.Qt.AlignmentFlag.AlignLeft

        # краткость текста
        short = is_short_text(text)

        # Фиксированные размеры кнопок
        btn_size = 36
        emoji_size = 15
        btn_radius = btn_size // 2

        # главный layout
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(6, 8, 6, 8)
        main_layout.setSpacing(6)
        if align == QtCore.Qt.AlignmentFlag.AlignRight:
            main_layout.addStretch()

        # вертикальный столбик: пузырь + панель кнопок (вне пузыря)
        col_widget = QtWidgets.QWidget()
        col_layout = QtWidgets.QVBoxLayout(col_widget)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(6)

        # пузырь сообщения
        message_container = QtWidgets.QWidget()
        message_container.setObjectName("messageContainer")
        message_container.setMaximumWidth(720)
        message_container.setMinimumWidth(200)
        message_container.setStyleSheet(f"""
            #messageContainer {{
                background-color: {bg_color};
                border-radius: 22px;
                padding: 14px 18px;
            }}
        """)
        container_layout = QtWidgets.QVBoxLayout(message_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)

        message_label = QtWidgets.QLabel()
        message_label.setWordWrap(True)
        message_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        message_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
            QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        font = QtGui.QFont("Inter", 15)
        message_label.setFont(font)
        message_label.setStyleSheet("""
            QLabel {
                color: #2d3748;
                padding: 4px;
                line-height: 1.5;
            }
        """)
        display_text = f"<b style='color:{color};'>{speaker}:</b><br>{text}"
        message_label.setText(display_text)
        message_label.setTextFormat(QtCore.Qt.TextFormat.RichText)

        # Центрируем текст если его мало
        if short:
            message_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        container_layout.addWidget(message_label)


        col_layout.addWidget(message_container, alignment=(QtCore.Qt.AlignmentFlag.AlignLeft if align == QtCore.Qt.AlignmentFlag.AlignLeft else QtCore.Qt.AlignmentFlag.AlignRight))

        # Решаем сторону для панели кнопок
        if speaker == "Вы":
            controls_side = "right"
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
                background-color: rgba(102, 126, 234, 0.12);
                color: #667eea;
                border: 1px solid rgba(102, 126, 234, 0.2);
                border-radius: {btn_radius}px;
                font-size: {emoji_size}px;
            }}
            QPushButton#floatingControl:hover {{ 
                background-color: rgba(102, 126, 234, 0.2);
                border: 1px solid rgba(102, 126, 234, 0.35);
            }}
            QPushButton#floatingControl:pressed {{ 
                background-color: rgba(102, 126, 234, 0.3);
                border: 1px solid rgba(102, 126, 234, 0.5);
            }}
        """)
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
                    background-color: rgba(102, 126, 234, 0.12);
                    color: #667eea;
                    border: 1px solid rgba(102, 126, 234, 0.2);
                    border-radius: {btn_radius}px;
                    font-size: {emoji_size}px;
                }}
                QPushButton#floatingControl:hover {{ 
                    background-color: rgba(102, 126, 234, 0.2);
                    border: 1px solid rgba(102, 126, 234, 0.35);
                }}
                QPushButton#floatingControl:pressed {{ 
                    background-color: rgba(102, 126, 234, 0.3);
                    border: 1px solid rgba(102, 126, 234, 0.5);
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
                    background-color: rgba(102, 126, 234, 0.12);
                    color: #667eea;
                    border: 1px solid rgba(102, 126, 234, 0.2);
                    border-radius: {btn_radius}px;
                    font-size: {emoji_size}px;
                }}
                QPushButton#floatingControl:hover {{ 
                    background-color: rgba(102, 126, 234, 0.2);
                    border: 1px solid rgba(102, 126, 234, 0.35);
                }}
                QPushButton#floatingControl:pressed {{ 
                    background-color: rgba(102, 126, 234, 0.3);
                    border: 1px solid rgba(102, 126, 234, 0.5);
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

    def copy_text(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.text)

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
    def __init__(self, user_message: str, current_language: str, deep_thinking: bool, use_search: bool, should_forget: bool = False, chat_manager=None, chat_id=None, file_path: str = None):
        super().__init__()
        self.user_message = user_message
        self.current_language = current_language
        self.deep_thinking = deep_thinking
        self.use_search = use_search
        self.should_forget = should_forget
        self.chat_manager = chat_manager
        self.chat_id = chat_id
        self.file_path = file_path
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
                self.file_path
            )
            self.signals.finished.emit(response)
        except Exception as e:
            self.signals.finished.emit(f"[Ошибка] {e}")

# -------------------------
# Main Window
# -------------------------
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
        
        # Режим редактирования
        self.is_editing = False
        self.editing_message_text = ""
        
        # Прикреплённый файл
        self.attached_file_path = None
        
        # Менеджер чатов
        self.chat_manager = ChatManager()
        self.current_chat_id = self.chat_manager.get_active_chat_id()

        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 850)

        icon_pixmap = create_app_icon()
        self.setWindowIcon(QtGui.QIcon(icon_pixmap))

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

        # Кнопка меню (☰)
        self.menu_btn = QtWidgets.QPushButton("☰")
        self.menu_btn.setObjectName("menuBtn")
        self.menu_btn.setFont(QtGui.QFont("Inter", 18))
        self.menu_btn.setFixedSize(50, 50)
        self.menu_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.menu_btn.clicked.connect(self.toggle_sidebar)
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

        self.clear_btn = QtWidgets.QPushButton("🗑️ Очистить")
        self.clear_btn.setObjectName("clearBtn")
        font_clear = QtGui.QFont("Inter", 13, QtGui.QFont.Weight.Bold)
        self.clear_btn.setFont(font_clear)
        self.clear_btn.setFixedHeight(50)
        self.clear_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.clear_btn.clicked.connect(self.clear_chat)
        title_layout.addWidget(self.clear_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

        main_layout.addWidget(title_widget)

        # Chat display
        chat_container = QtWidgets.QWidget()
        chat_container.setObjectName("chatContainer")
        chat_layout = QtWidgets.QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(15, 15, 15, 15)

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("scrollArea")
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.scroll_area.setStyleSheet("background: transparent;")
        self.scroll_area.viewport().setStyleSheet("background-color: #e8edf5;")

        self.messages_widget = QtWidgets.QWidget()
        self.messages_layout = QtWidgets.QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(5, 5, 5, 5)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch()

        self.messages_widget.setStyleSheet("background: transparent;")

        self.scroll_area.setWidget(self.messages_widget)
        chat_layout.addWidget(self.scroll_area)

        main_layout.addWidget(chat_container, stretch=1)

        # Input area
        input_container = QtWidgets.QWidget()
        input_container.setObjectName("inputContainer")
        input_main_layout = QtWidgets.QVBoxLayout(input_container)
        input_main_layout.setContentsMargins(25, 15, 25, 20)
        input_main_layout.setSpacing(12)

        # Режимы — УВЕЛИЧЕННЫЕ кнопки и текст
        modes_layout = QtWidgets.QHBoxLayout()
        modes_layout.setSpacing(45)
        modes_layout.setContentsMargins(0, 0, 0, 0)
        modes_layout.addStretch()

        self.think_toggle = QtWidgets.QCheckBox("💡 Думать")
        self.think_toggle.setObjectName("modeToggle")
        self.think_toggle.stateChanged.connect(self.toggle_thinking)
        self.think_toggle.setMinimumHeight(42)
        modes_layout.addWidget(self.think_toggle)

        self.search_toggle = QtWidgets.QCheckBox("🔍 Поиск")
        self.search_toggle.setObjectName("modeToggle")
        self.search_toggle.stateChanged.connect(self.toggle_search)
        self.search_toggle.setMinimumHeight(42)
        modes_layout.addWidget(self.search_toggle)

        modes_layout.addStretch()
        input_main_layout.addLayout(modes_layout)

        # Поле ввода
        input_layout = QtWidgets.QHBoxLayout()
        input_layout.setSpacing(15)

        # Кнопка добавления файла
        self.attach_btn = QtWidgets.QPushButton("+")
        self.attach_btn.setObjectName("attachBtn")
        font_attach = QtGui.QFont("Inter", 26, QtGui.QFont.Weight.Bold)
        self.attach_btn.setFont(font_attach)
        self.attach_btn.setFixedSize(60, 60)
        self.attach_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.attach_btn.clicked.connect(self.show_attach_menu)
        # Явно указываем выравнивание текста по центру
        self.attach_btn.setStyleSheet("""
            text-align: center;
            padding: 0px;
            margin: 0px;
        """)
        input_layout.addWidget(self.attach_btn)

        self.input_field = QtWidgets.QLineEdit()
        self.input_field.setPlaceholderText("Введите сообщение...")
        self.input_field.setObjectName("inputField")
        font_input = QtGui.QFont("Inter", 14)
        self.input_field.setFont(font_input)
        self.input_field.setMinimumHeight(60)
        self.input_field.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_field, stretch=1)

        self.send_btn = QtWidgets.QPushButton("→")
        self.send_btn.setObjectName("sendBtn")
        font_btn = QtGui.QFont("Inter", 22, QtGui.QFont.Weight.Bold)
        self.send_btn.setFont(font_btn)
        self.send_btn.setFixedSize(60, 60)
        self.send_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_btn)

        input_main_layout.addLayout(input_layout)

        # Статус
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("statusLabel")
        font_status = QtGui.QFont("Inter", 11)
        self.status_label.setFont(font_status)
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        input_main_layout.addWidget(self.status_label)

        main_layout.addWidget(input_container)

        # Добавляем основную область в контейнер
        container_layout.addWidget(central)

        self.threadpool = QtCore.QThreadPool()

        # Устанавливаем фильтр событий для автозакрытия sidebar при клике по рабочей области
        self.messages_widget.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)
        chat_container.installEventFilter(self)

        self.apply_styles()
        self.load_chats_list()
        self.load_current_chat()

    def apply_styles(self):
        style = """
        QMainWindow { background: #f5f7fb; }
        #central { background: #f5f7fb; border-radius: 0px; }

        #sidebar {
            background: #e8edf5;
            border-right: 1px solid #d9e2ed;
            border-radius: 0px;
        }

        #newChatBtn {
            background: #f8fafd;
            color: #2d3748;
            border: 1px solid #d9e2ed;
            border-radius: 12px;
            padding: 18px 20px;
            margin: 12px 10px;
            font-size: 16px;
            font-weight: 700;
            text-align: left;
        }
        #newChatBtn:hover {
            background: #eef3ff;
            border: 1px solid #667eea;
        }

        #chatsList {
            background: transparent;
            border: none;
            outline: none;
            padding: 0px 10px;
        }
        #chatsList::item {
            padding: 16px 14px;
            margin: 3px 0px;
            border-radius: 10px;
            border: none;
            color: #2d3748;
            font-size: 14px;
            font-weight: 500;
            line-height: 1.4;
        }
        #chatsList::item:hover {
            background: #f5f8fc;
        }
        #chatsList::item:selected {
            background: #e8f0fe;
            color: #5568d3;
            font-weight: 600;
            border-left: 3px solid #667eea;
        }
        
        #deletePanel {
            background: #e8edf5;
            border-left: 1px solid #d9e2ed;
            padding: 15px;
        }
        
        #deleteChatBtn {
            background: #ef4444;
            color: white;
            border: none;
            border-radius: 10px;
            padding: 14px 20px;
            font-size: 14px;
            font-weight: 700;
        }
        #deleteChatBtn:hover {
            background: #dc2626;
        }
        #deleteChatBtn:pressed {
            background: #b91c1c;
        }

        #menuBtn {
            background: transparent;
            color: #2d3748;
            border: none;
            border-radius: 8px;
            font-size: 20px;
            font-weight: bold;
        }
        #menuBtn:hover {
            background: rgba(102, 126, 234, 0.08);
        }
        #menuBtn:pressed {
            background: rgba(102, 126, 234, 0.15);
        }

        #titleWidget {
            background: #f8fafd;
            border: 1px solid #d9e2ed;
            border-radius: 12px;
            margin: 10px 15px;
            padding-top: 12px;
            padding-bottom: 12px;
        }
        #titleLabel { 
            color: #2d3748; 
            font-size: 22px; 
            font-weight: 700; 
            padding: 5px; 
        }

        #clearBtn {
            background: #ef4444;
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 700;
            padding: 8px 16px;
        }
        #clearBtn:hover { 
            background: #dc2626;
        }
        #clearBtn:pressed { 
            background: #b91c1c;
        }

        #chatContainer { background: transparent; }

        QScrollArea { background: transparent; border: none; }
        QScrollArea > QWidget > QWidget { background: #e8edf5; border-radius: 24px; }

        QScrollBar:vertical { background: transparent; width: 10px; }
        QScrollBar::handle:vertical { background: #cbd5e0; border-radius: 5px; min-height: 30px; }
        QScrollBar::handle:vertical:hover { background: #a0aec0; }

        #inputContainer { 
            background: #f8fafd; 
            border-top: 1px solid #dce4ec;
        }
        #inputField {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #f8f9ff, stop:1 #f0f4ff);
            color: #1a202c;
            border: 2px solid rgba(102, 126, 234, 0.3);
            border-radius: 30px;
            padding: 18px 25px;
            font-size: 15px;
        }
        #inputField:focus { 
            border: 2px solid #667eea; 
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #ffffff, stop:1 #f0f4ff);
        }

        #attachBtn {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(102, 126, 234, 0.15),
                stop:1 rgba(102, 126, 234, 0.08));
            color: #667eea;
            border: 2px solid rgba(102, 126, 234, 0.3);
            border-radius: 30px;
            font-size: 28px;
            font-weight: bold;
            text-align: center;
            padding: 0px;
            line-height: 60px;
        }
        #attachBtn:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(102, 126, 234, 0.25),
                stop:1 rgba(102, 126, 234, 0.15));
            border: 2px solid rgba(102, 126, 234, 0.45);
        }
        #attachBtn:pressed {
            background: rgba(102, 126, 234, 0.35);
            border: 2px solid rgba(102, 126, 234, 0.6);
        }

        #sendBtn {
            background: rgba(102, 126, 234, 0.88);
            color: white; border-radius: 30px; font-size: 26px;
        }
        #sendBtn:hover { 
            background: rgba(102, 126, 234, 0.95);
            transform: scale(1.02);
        }
        #sendBtn:pressed { 
            background: rgba(85, 104, 211, 0.9);
            transform: scale(0.98);
        }
        #sendBtn:disabled { background: rgba(203, 213, 224, 0.6); }

        #statusLabel { color: #667eea; padding-left: 5px; font-style: italic; }
        
        QCheckBox#modeToggle { 
            color: #2d3748; 
            font-size: 17px; 
            font-weight: 600;
            padding: 8px 4px;
        }
        QCheckBox#modeToggle::indicator {
            width: 24px;
            height: 24px;
            border-radius: 6px;
            border: 2px solid #cbd5e0;
            background-color: white;
        }
        QCheckBox#modeToggle::indicator:checked {
            background: #667eea;
            border: none;
        }
        QCheckBox#modeToggle::indicator:hover {
            border: 2px solid #667eea;
        }
        """
        self.setStyleSheet(style)

        try:
            self.scroll_area.viewport().setStyleSheet("background-color: #e8edf5;")
            self.messages_widget.setStyleSheet("background: transparent;")
        except Exception:
            pass

    
    def show_model_info(self):
        """Показать информацию о модели при клике на заголовок"""
        QtWidgets.QMessageBox.information(
            self,
            "Информация о модели",
            "LLaMA 3 — локальная модель\n\nРаботает полностью офлайн на вашем компьютере.",
            QtWidgets.QMessageBox.StandardButton.Ok
        )
    
    def toggle_thinking(self, state):
        self.deep_thinking = (state == QtCore.Qt.CheckState.Checked.value)

    def toggle_search(self, state):
        self.use_search = (state == QtCore.Qt.CheckState.Checked.value)
    
    def show_attach_menu(self):
        """Показать меню выбора файла"""
        menu = QtWidgets.QMenu(self)
        
        # Улучшенные стили меню
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #d9e2ed;
                border-radius: 12px;
                padding: 8px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            }
            QMenu::item {
                padding: 12px 40px;
                border-radius: 8px;
                color: #2d3748;
                font-size: 15px;
                font-weight: 500;
                margin: 3px;
            }
            QMenu::item:selected {
                background-color: #f0f4ff;
                color: #667eea;
            }
        """)
        
        file_action = menu.addAction("📎 Прикрепить файл")
        
        # Показываем меню НАД кнопкой (не под ней)
        button_rect = self.attach_btn.rect()
        button_global_pos = self.attach_btn.mapToGlobal(button_rect.topLeft())
        
        # Вычисляем размер меню приблизительно
        menu_height = 60  # Примерная высота меню с одним пунктом
        
        # Позиция НАД кнопкой с небольшим отступом
        menu_pos = QtCore.QPoint(button_global_pos.x(), button_global_pos.y() - menu_height - 5)
        
        action = menu.exec(menu_pos)
        
        if action == file_action:
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
        dots = "." * self.status_dots_count
        self.status_label.setText(f"{self.status_base_text}{dots}")
        self.status_dots_count = (self.status_dots_count + 1) % 4  # 0, 1, 2, 3
    
    def stop_status_animation(self):
        """Остановка анимации точек"""
        if hasattr(self, 'status_timer') and self.status_timer.isActive():
            self.status_timer.stop()
        self.status_label.setText("")

    def toggle_sidebar(self):
        """Переключение боковой панели с анимацией"""
        current_width = self.sidebar.width()
        target_width = 280 if current_width == 0 else 0
        
        # Скрываем панель удаления при закрытии sidebar
        if target_width == 0:
            self.hide_delete_panel()
        
        self.animation = QtCore.QPropertyAnimation(self.sidebar, b"minimumWidth")
        self.animation.setDuration(250)
        self.animation.setStartValue(current_width)
        self.animation.setEndValue(target_width)
        self.animation.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
        
        self.animation2 = QtCore.QPropertyAnimation(self.sidebar, b"maximumWidth")
        self.animation2.setDuration(250)
        self.animation2.setStartValue(current_width)
        self.animation2.setEndValue(target_width)
        self.animation2.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
        
        self.animation.start()
        self.animation2.start()
    
    def eventFilter(self, obj, event):
        """Фильтр событий для автозакрытия sidebar при клике по рабочей области"""
        # Проверяем, открыт ли sidebar
        if self.sidebar.width() > 0:
            # Если событие - клик мышью
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                # Закрываем sidebar
                self.toggle_sidebar()
        
        # Передаём событие дальше
        return super().eventFilter(obj, event)

    def show_delete_panel(self, pos):
        """Показать контекстное меню при правом клике на чат"""
        item = self.chats_list.itemAt(pos)
        if not item:
            return
        
        chat_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        
        # Создаём контекстное меню
        context_menu = QtWidgets.QMenu(self)
        context_menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #d9e2ed;
                border-radius: 8px;
                padding: 6px;
            }
            QMenu::item {
                padding: 10px 20px;
                border-radius: 6px;
                color: #2d3748;
            }
            QMenu::item:selected {
                background-color: #fee2e2;
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
        
        # Очищаем виджеты сообщений
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Загружаем сообщения текущего чата
        messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=50)
        for role, content, created in messages:
            speaker = "Вы" if role == "user" else ASSISTANT_NAME
            # НЕ показываем системные сообщения при загрузке
            if role not in ["user", "assistant"]:
                continue
            self.add_message_widget(speaker, content, add_controls=True)

    def create_new_chat(self):
        """Создать новый чат"""
        chat_id = self.chat_manager.create_chat("Новый чат")
        self.chat_manager.set_active_chat(chat_id)
        self.current_chat_id = chat_id
        
        self.load_chats_list()
        self.load_current_chat()
        
        # Закрываем sidebar после создания
        self.toggle_sidebar()

    def switch_chat(self, item):
        """Переключить чат"""
        chat_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        self.chat_manager.set_active_chat(chat_id)
        self.current_chat_id = chat_id
        
        self.load_current_chat()
        
        # Закрываем sidebar после переключения
        self.toggle_sidebar()

    def add_message_widget(self, speaker: str, text: str, add_controls: bool = False):
        message_widget = MessageWidget(speaker, text, add_controls,
                                       language=self.current_language,
                                       main_window=self,
                                       parent=self.messages_widget)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, message_widget)
        QtCore.QTimer.singleShot(50, self.scroll_to_bottom)

    def scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

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
            
            # НЕ возвращаем текст в поле - оставляем пустым
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.send_btn.setText("→")
            self.status_label.setText("❌ Генерация остановлена")
            
            # Через 2 секунды очищаем статус
            QtCore.QTimer.singleShot(2000, lambda: self.status_label.setText(""))
            print("[SEND] Генерация остановлена пользователем")
            return
        
        global CURRENT_LANGUAGE
        # ИСТОЧНИК ИСТИНЫ - текст из поля ввода
        user_text = self.input_field.text().strip()
        if not user_text:
            return
        
        print(f"[SEND] Отправка сообщения: {user_text[:50]}...")

        should_forget = detect_forget_command(user_text)
        if should_forget:
            print("[SEND] Обнаружена команда забыть!")
            # Очищаем сообщения
            self.chat_manager.clear_chat_messages(self.current_chat_id)
            
            # Сбрасываем название на "Новый чат"
            self.chat_manager.update_chat_title(self.current_chat_id, "Новый чат")
            
            # Обновляем список чатов
            self.load_chats_list()
            
            if self.current_language == "russian":
                notification = "✓ Память очищена. Я забыл всю предыдущую историю разговора."
            else:
                notification = "✓ Memory cleared. I've forgotten all previous conversation history."
            
            self.input_field.clear()
            self.add_message_widget("Система", notification, add_controls=False)
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
        
        # Проверяем режим редактирования
        if not self.is_editing:
            # Обычная отправка - добавляем сообщение
            self.input_field.clear()
            self.add_message_widget("Вы", user_text, add_controls=True)
            self.chat_manager.save_message(self.current_chat_id, "user", user_text)
            print("[SEND] Новое сообщение добавлено")
        else:
            # Режим редактирования - НЕ добавляем сообщение, оно уже было удалено
            self.input_field.clear()
            self.add_message_widget("Вы", user_text, add_controls=True)
            self.chat_manager.save_message(self.current_chat_id, "user", user_text)
            # Сбрасываем флаг редактирования
            self.is_editing = False
            self.editing_message_text = ""
            print("[SEND] Отредактированное сообщение отправлено")

        self.input_field.setEnabled(False)
        self.send_btn.setText("⏸")
        self.send_btn.setEnabled(True)
        self.is_generating = True


        # Устанавливаем базовый текст статуса
        if self.use_search:
            self.status_base_text = "⏳ Ищу в интернете"
        elif self.deep_thinking:
            self.status_base_text = "⏳ Глубоко размышляю"
        else:
            self.status_base_text = "⏳ Быстрый ответ"
        
        # Запускаем анимацию точек
        self.start_status_animation()

        worker = AIWorker(user_text, self.current_language, self.deep_thinking, self.use_search, False, self.chat_manager, self.current_chat_id, self.attached_file_path)
        worker.signals.finished.connect(self.handle_response)
        self.current_worker = worker  # Сохраняем ссылку на текущего воркера
        self.threadpool.start(worker)
        print("[SEND] Запущен воркер генерации")
        
        # Очищаем прикреплённый файл после отправки
        if self.attached_file_path:
            print(f"[SEND] Файл {os.path.basename(self.attached_file_path)} отправлен в модель")
            self.clear_attached_file()

    def handle_response(self, response: str):
        # ВАЖНО: Сбрасываем флаг генерации
        self.is_generating = False
        
        self.add_message_widget(ASSISTANT_NAME, response, add_controls=True)
        self.chat_manager.save_message(self.current_chat_id, "assistant", response)
        
        # Автоматическое именование чата по первому сообщению
        messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=5)
        # Если это первый ответ (2 сообщения: вопрос пользователя + ответ ассистента)
        if len(messages) == 2:
            # Берём первое сообщение пользователя
            first_user_msg = messages[0][1] if messages[0][0] == "user" else ""
            if first_user_msg:
                # Обрезаем до 40 символов для читаемости
                chat_title = first_user_msg[:40]
                if len(first_user_msg) > 40:
                    chat_title += "..."
                # Делаем первую букву заглавной
                chat_title = chat_title[0].upper() + chat_title[1:] if chat_title else "Новый чат"
                # Обновляем название чата
                self.chat_manager.update_chat_title(self.current_chat_id, chat_title)
                # Обновляем список чатов
                self.load_chats_list()
        
        self.send_btn.setEnabled(True)
        self.send_btn.setText("→")  # Возвращаем стрелку

        self.input_field.setEnabled(True)
        self.input_field.setFocus()
        
        # Гарантируем, что окно остаётся активным
        self.activateWindow()
        self.raise_()
        
        # Останавливаем анимацию точек
        self.stop_status_animation()


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
        
        # Устанавливаем статус перегенерации с анимацией
        self.status_base_text = "⏳ Перегенерирую сообщение"
        self.status_label.setText(self.status_base_text)
        self.start_status_animation()
        
        self.current_user_message = last_user_msg
        
        worker = AIWorker(last_user_msg, self.current_language, self.deep_thinking, 
                         self.use_search, False, self.chat_manager, self.current_chat_id, None)
        worker.signals.finished.connect(self.handle_response)
        self.current_worker = worker
        self.threadpool.start(worker)
        print("[REGENERATE] Запущена новая генерация")
    
    def edit_last_message(self, old_text=None):
        """Редактировать последнее сообщение пользователя
        
        ЛОГИКА:
        1. Получить последний user-запрос из текущего чата
        2. Вернуть текст в поле ввода
        3. Удалить последние 2 сообщения (user + assistant) из UI и БД
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
        
        # ВОЗВРАЩАЕМ ТЕКСТ В ПОЛЕ ВВОДА И УСТАНАВЛИВАЕМ КУРСОР В КОНЕЦ
        self.input_field.setText(last_user_msg)
        self.input_field.setEnabled(True)
        self.input_field.setFocus()
        self.input_field.setCursorPosition(len(last_user_msg))
        print(f"[EDIT] ✓ Режим редактирования активирован")

    def clear_chat(self):
        reply = QtWidgets.QMessageBox.question(
            self, "Подтверждение",
            "Вы уверены, что хотите очистить текущий чат?\nЭто действие нельзя отменить.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            # Очищаем сообщения
            self.chat_manager.clear_chat_messages(self.current_chat_id)
            
            # Сбрасываем название на "Новый чат"
            self.chat_manager.update_chat_title(self.current_chat_id, "Новый чат")
            
            # Обновляем список чатов для отображения нового названия
            self.load_chats_list()
            
            # Очищаем визуальное отображение
            while self.messages_layout.count() > 1:
                item = self.messages_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.add_message_widget("Система", "История чата очищена.", add_controls=False)

def main():
    init_db()
    app = QtWidgets.QApplication(sys.argv)

    app_icon = create_app_icon()
    app.setWindowIcon(QtGui.QIcon(app_icon))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()