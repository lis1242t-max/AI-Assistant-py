"""
ai_core.py — Ядро AI: история, память, формирование системного промпта, вызов Ollama.

Содержит:
  - init_db, save_message, load_history, clear_messages
  - get_memory_manager, clear_chat_all_memories, clear_all_memories_global
  - on_chat_switched_all_memories
  - _is_conversational_message
  - get_ai_response  — главная функция генерации ответа
  - is_short_text

Использование:
    from ai_core import get_ai_response, get_memory_manager, is_short_text
"""
import os
import re
import sys
import json
import time
import sqlite3
import threading
import subprocess
import requests
from datetime import datetime
from typing import Any

# ── Добавляем папку ai_config в sys.path ─────────────────────────────────────
# qwen_config.py, mistral_config.py, deepseek_config.py лежат в ai_config/.
# Без этого import qwen_config падает с ImportError даже если файл существует.
_AC_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_AC_AI_CONFIG = os.path.join(_AC_APP_DIR, "ai_config")
if os.path.isdir(_AC_AI_CONFIG) and _AC_AI_CONFIG not in sys.path:
    sys.path.insert(1, _AC_AI_CONFIG)

# ── Внешние зависимости проекта ─────────────────────────────────────────────
import llama_handler
from llama_handler import (
    USE_OLLAMA, OLLAMA_HOST, OLLAMA_MODEL, SUPPORTED_MODELS,
    AI_MODE_FAST, AI_MODE_THINKING, AI_MODE_PRO,
    SYSTEM_PROMPTS, MODE_STRATEGY_RULES,
    get_current_ollama_model, get_current_display_name,
    call_ollama_chat, warm_up_model, unload_model, unload_all_models,
)

from chat_manager import ChatManager
from context_memory_manager import ContextMemoryManager

from ai_file_generator import (
    parse_generated_files,
    FILE_GENERATION_PROMPT,
    detect_file_request,
    build_file_injection,
)

try:
    from enhanced_subtext import (
        get_subtext_injection, get_subtext_reminder,
        subtext_track_message, SubtextManager as _SubtextManager,
    )
except ImportError:
    def get_subtext_injection(): return ""
    def get_subtext_reminder(): return ""
    def subtext_track_message(msg): pass
    class _SubtextManager:
        @staticmethod
        def load(): return {}

try:
    from deepseek_memory_manager import DeepSeekMemoryManager
    _DS_MEMORY = DeepSeekMemoryManager()
except ImportError:
    DeepSeekMemoryManager = None
    _DS_MEMORY = None

try:
    from qwen_memory_manager import QwenMemoryManager
    _QWEN_MEMORY = QwenMemoryManager()
except ImportError:
    QwenMemoryManager = None
    _QWEN_MEMORY = None

try:
    from mistral_config import (
        get_mistral_system_prompt, clean_mistral_response,
        MISTRAL_MODEL_NAME, MISTRAL_DISPLAY_NAME, MISTRAL_OLLAMA_PULL,
    )
except ImportError:
    def get_mistral_system_prompt(lang, mode): return ""
    def clean_mistral_response(t): return t
    MISTRAL_MODEL_NAME = "mistral-nemo:12b"
    MISTRAL_DISPLAY_NAME = "Mistral Nemo"
    MISTRAL_OLLAMA_PULL = "ollama pull mistral-nemo:12b"

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
except ImportError:
    def get_deepseek_system_prompt(language, mode): return ""
    def get_deepseek_math_prompt(mode): return ""
    def clean_deepseek_latex(text): return text
    def detect_user_correction(msg): return False
    def is_simple_arithmetic(msg): return False, ""
    def compute_simple_arithmetic(expr, language="russian"): return None
    def is_garbage_math_response(resp): return False
    def sanitize_deepseek_math(resp, q, language="russian"): return resp
    def sanitize_deepseek_file_response(resp): return resp
    DEEPSEEK_MODEL_NAME   = "deepseek-llm:7b-chat"
    DEEPSEEK_DISPLAY_NAME = "DeepSeek"
    DEEPSEEK_OLLAMA_PULL  = "ollama pull deepseek-llm:7b-chat"

try:
    from qwen_config import (
        get_qwen_system_prompt, clean_qwen_response,
        QWEN_MODEL_NAME, QWEN_DISPLAY_NAME, QWEN_OLLAMA_PULL,
    )
except ImportError:
    def get_qwen_system_prompt(lang, mode): return ""
    def clean_qwen_response(t): return t
    QWEN_MODEL_NAME = "qwen3:14b"
    QWEN_DISPLAY_NAME = "Qwen 3"
    QWEN_OLLAMA_PULL = "ollama pull qwen3:14b"

from error_handler import (
    check_database_health, safe_db_connect, log_error,
)

# ── Веб-поиск ───────────────────────────────────────────────────────────────
from web_search import (
    analyze_intent_for_search,
    deep_web_search,
    build_contextual_search_query,
    detect_question_parts,
    validate_answer,
    build_final_answer_prompt,
    is_short_acknowledgment,
    # Дополнительные функции используемые в get_ai_response
    detect_role_command,
    detect_message_language,
    detect_math_problem,
    translate_to_russian,
    remove_english_words_from_russian,
    summarize_sources,
    compress_search_results,
    version_search_pipeline,
    is_version_query,
    validate_versions_before_answer,
    MATH_PROMPTS,
)

# ── Константы ───────────────────────────────────────────────────────────────
DB_FILE = "chat_memory.db"
MAX_HISTORY_LOAD = 15
SHORT_TEXT_THRESHOLD = 80

_CTX_MEMORY = ContextMemoryManager()

# Запрещённые английские слова
FORBIDDEN_WORDS_DICT = {}
FORBIDDEN_WORDS_SET = set()
try:
    from forbidden_english_words import FORBIDDEN_WORDS_DICT as _fw
    FORBIDDEN_WORDS_DICT = _fw
    FORBIDDEN_WORDS_SET = set(FORBIDDEN_WORDS_DICT.keys())
except ImportError:
    pass

def init_db():
    """Инициализирует основную БД. При ошибке — чинит и пересоздаёт."""
    try:
        check_database_health(DB_FILE, required_tables=["messages"], auto_fix=True)
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

        # ── Одноразовая очистка старой БД без chat_id-изоляции ───────────────
        # chat_memory.db — устаревшая плоская таблица без разделения по чатам/моделям.
        # Данные из неё никогда не читаются (fallback отключён), но физически существуют
        # и могут вызывать утечку контекста если логика когда-то откатится.
        # Чистим один раз при старте и помечаем флагом чтобы не трогать при каждом запуске.
        cur.execute("SELECT COUNT(*) FROM messages")
        msg_count = cur.fetchone()[0]
        if msg_count > 0:
            cur.execute("DELETE FROM messages")
            try:
                cur.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
            except Exception:
                pass
            conn.commit()
            print(f"[DB] 🧹 Очищена старая chat_memory.db ({msg_count} строк) — данные перенесены в chat_manager")
        conn.close()
        print("[DB] ✅ chat_memory.db готова")
    except Exception as e:
        log_error("INIT_DB", e)
        # Последний шанс — создать пустую БД
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.close()
        except Exception:
            pass

def save_message(role: str, content: str):
    conn = safe_db_connect(DB_FILE)
    if conn is None:
        print("[DB] ⚠️ save_message: нет соединения с БД")
        return
    try:
        conn.execute(
            "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, datetime.utcnow().isoformat())
        )
        conn.commit()
    except Exception as e:
        log_error("SAVE_MSG", e)
    finally:
        conn.close()

def load_history(limit=MAX_HISTORY_LOAD):
    conn = safe_db_connect(DB_FILE)
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = cur.fetchall()
        return list(reversed(rows))
    except Exception as e:
        log_error("LOAD_HISTORY", e)
        return []
    finally:
        conn.close()

def clear_messages():
    conn = safe_db_connect(DB_FILE)
    if conn is None:
        return
    try:
        conn.execute("DELETE FROM messages")
        conn.commit()
    except Exception as e:
        log_error("CLEAR_MSG", e)
    finally:
        conn.close()

# -------------------------
# Model-call helpers
# -------------------------
# call_ollama_vision перенесена в vision_handler.py

# call_ollama_chat и warm_up_model перенесены в llama_handler.py
# Они импортируются выше через 'from llama_handler import ...'

def get_memory_manager(model_key: str):
    """
    Возвращает нужный менеджер памяти в зависимости от модели.
    DeepSeek  → DeepSeekMemoryManager  (deepseek_memory.db)
    Mistral   → MistralMemoryManager   (mistral_memory.db)
    LLaMA и все остальные → ContextMemoryManager (context_memory.db)
    """
    if model_key in ("deepseek", "deepseek-r1") and _DS_MEMORY is not None:
        return _DS_MEMORY
    if model_key == "mistral" and _MISTRAL_MEMORY is not None:
        return _MISTRAL_MEMORY
    if model_key == "qwen" and _QWEN_MEMORY is not None:
        return _QWEN_MEMORY
    # ✅ ИСПРАВЛЕНО: возвращаем singleton, а не новый объект каждый раз
    return _CTX_MEMORY


def clear_chat_all_memories(chat_id: int):
    """Очищает память конкретного чата во ВСЕХ трёх менеджерах (LLaMA + DeepSeek + Mistral)."""
    try:
        _CTX_MEMORY.delete_chat_context(chat_id)
        print(f"[MEMORY] LLaMA память чата {chat_id} удалена")
    except Exception as e:
        print(f"[MEMORY] LLaMA память: {e}")
    try:
        if _DS_MEMORY is not None:
            _DS_MEMORY.delete_chat_context(chat_id)
            print(f"[MEMORY] DeepSeek память чата {chat_id} удалена")
    except Exception as e:
        print(f"[MEMORY] DeepSeek память: {e}")
    try:
        if _MISTRAL_MEMORY is not None:
            # ИСПРАВЛЕНО: передаём chat_id, иначе очищается только chat_id=0
            _MISTRAL_MEMORY.clear_all(chat_id=chat_id)
            print(f"[MEMORY] Mistral память чата {chat_id} удалена")
    except Exception as e:
        print(f"[MEMORY] Mistral память: {e}")
    try:
        if _QWEN_MEMORY is not None:
            _QWEN_MEMORY.clear_all(chat_id=chat_id)
            print(f"[MEMORY] Qwen память чата {chat_id} удалена")
    except Exception as e:
        print(f"[MEMORY] Qwen память: {e}")


def clear_all_memories_global():
    """Полная очистка памяти ВСЕХ моделей для ВСЕХ чатов. Вызывать при удалении всех чатов."""
    try:
        _CTX_MEMORY.clear_all_context()
        print("[MEMORY] Вся память LLaMA очищена")
    except Exception as e:
        print(f"[MEMORY] LLaMA clear_all: {e}")
    try:
        if _DS_MEMORY is not None:
            _DS_MEMORY.clear_all_context()
            print("[MEMORY] Вся память DeepSeek очищена")
    except Exception as e:
        print(f"[MEMORY] DeepSeek clear_all: {e}")
    try:
        if _MISTRAL_MEMORY is not None:
            # ИСПРАВЛЕНО: clear_all_context() удаляет ВСЕ чаты,
            # а не только chat_id=0 как делал clear_all() без аргумента
            _MISTRAL_MEMORY.clear_all_context()
            print("[MEMORY] Вся память Mistral очищена")
    except Exception as e:
        print(f"[MEMORY] Mistral clear_all: {e}")
    try:
        if _QWEN_MEMORY is not None:
            _QWEN_MEMORY.clear_all_context()
            print("[MEMORY] Вся память Qwen очищена")
    except Exception as e:
        print(f"[MEMORY] Qwen clear_all: {e}")


def on_chat_switched_all_memories(new_chat_id: int):
    """Уведомляет все менеджеры памяти о смене чата."""
    if _DS_MEMORY is not None:
        _DS_MEMORY.on_chat_switch(new_chat_id)
    if _QWEN_MEMORY is not None:
        _QWEN_MEMORY.on_chat_switch(new_chat_id)


_CONVERSATIONAL_RE = re.compile(
    r"""^(?:
        # Благодарности RU
        спасибо[\w\s]{0,30}  | благодар[\w]{1,10}[\s\w]{0,20} |
        # Подтверждения RU
        ок[её]?й? | хорошо | понял[аи]? | понятно | ясно | отлично | супер |
        норм(?:ально)? | ладно | угу | ага | да | нет | конечно | договорились |
        всё\s+(?:ясно|понятно|окей|хорошо) | отлично[,!\s]* |
        # Приветствия RU
        привет[\w\s]{0,15} | здравствуй[\w\s]{0,15} | добрый\s+\w+ |
        # Восклицания RU
        круто[\s!]* | класс[\s!]* | прекрасно[\s!]* | замечательно[\s!]* |
        шикарно[\s!]* | бомба[\s!]* | огонь[\s!]* | красота[\s!]* |
        # Благодарности EN
        thanks?[\s\w]{0,25} | thank\s+you[\s\w]{0,25} | thx[\s!]* | ty[\s!]* |
        # Подтверждения EN
        ok(?:ay)? | got\s+it | i\s+see | understood | sure | yep | yup |
        cool[\s!]* | great[\s!]* | awesome[\s!]* | nice[\s!]* | perfect[\s!]* |
        sounds?\s+good | makes?\s+sense | alright | roger |
        # Приветствия EN
        hi[\s\w]{0,10} | hello[\s\w]{0,10} | hey[\s\w]{0,10}
    )[!?.,\s]*$""",
    re.VERBOSE | re.IGNORECASE | re.UNICODE,
)

def _is_conversational_message(text: str) -> bool:
    """
    Возвращает True если сообщение — чисто социальное/разговорное:
    благодарность, подтверждение, приветствие, восклицание.
    Для таких сообщений НЕ нужно вшивать file_analysis в системный промпт —
    это главная причина галлюцинаций о содержимом файлов.
    """
    stripped = text.strip()
    # Длинные сообщения (>80 символов) скорее всего содержат реальный вопрос
    if len(stripped) > 80:
        return False
    # Если есть вопросительный знак внутри — скорее всего вопрос
    if '?' in stripped[:-1]:
        return False
    return bool(_CONVERSATIONAL_RE.match(stripped))


# Sentinel — отличает отменённый стрим от реально пустого ответа
_STREAM_CANCELLED = "[Ollama cancelled]"

def _ollama_stream(payload: dict, timeout: int, on_chunk, cancelled_flag) -> str:
    """
    Выполняет стриминговый запрос к Ollama /api/chat.
    Вызывает on_chunk(text) для каждого токена.
    Возвращает полный собранный текст.
    При отмене пользователем возвращает _STREAM_CANCELLED (не пустую строку!).
    """
    import json as _json
    payload = dict(payload)
    payload["stream"] = True
    full = []
    was_cancelled = False
    try:
        with requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json=payload,
            stream=True,
            timeout=(30, None),
        ) as r:
            if r.status_code != 200:
                return f"[Ollama error] HTTP {r.status_code}"
            for raw_line in r.iter_lines():
                if callable(cancelled_flag) and cancelled_flag():
                    was_cancelled = True
                    break
                if not raw_line:
                    continue
                try:
                    obj = _json.loads(raw_line)
                except Exception:
                    continue
                token = obj.get("message", {}).get("content", "")
                if token:
                    full.append(token)
                    if on_chunk:
                        try:
                            on_chunk(token)
                        except Exception:
                            pass
                if obj.get("done", False):
                    break
    except requests.exceptions.Timeout:
        return "[Ollama timeout]"
    except requests.exceptions.ConnectionError:
        return "[Ollama connection error]"
    if was_cancelled:
        return _STREAM_CANCELLED
    return "".join(full)


def get_ai_response(user_message: str, current_language: str, deep_thinking: bool, use_search: bool, should_forget: bool = False, chat_manager=None, chat_id=None, file_paths: list = None, ai_mode: str = AI_MODE_FAST, model_key: str = None, on_chunk=None, cancelled_flag=None):
    """Получить ответ от AI (с жёстким закреплением языка)"""
    # Авто-анализ стиля пользователя (если включён улучшенный подтекст)
    subtext_track_message(user_message)

    # Фиксируем модель ОДИН РАЗ — используем переданный ключ или читаем глобал
    # Это предотвращает любую гонку потоков с llama_handler.CURRENT_AI_MODEL_KEY
    _mk = model_key if model_key is not None else llama_handler.CURRENT_AI_MODEL_KEY
    print(f"\n[GET_AI_RESPONSE] ========== НАЧАЛО ==========")
    print(f"[GET_AI_RESPONSE] Сообщение пользователя: {user_message}")
    print(f"[GET_AI_RESPONSE] Текущий язык интерфейса: {current_language}")
    print(f"[GET_AI_RESPONSE] Глубокое мышление: {deep_thinking}")
    print(f"[GET_AI_RESPONSE] Использовать поиск: {use_search}")
    print(f"[GET_AI_RESPONSE] Забыть историю: {should_forget}")
    print(f"[GET_AI_RESPONSE] Файлов прикреплено: {len(file_paths) if file_paths else 0}")

    # НОРМАЛИЗАЦИЯ МАТЕМАТИЧЕСКИХ СИМВОЛОВ
    # Заменяем специальные символы на стандартные ASCII
    # Сохраняем оригинал для сравнения с историей (история хранит raw-текст)
    _user_message_raw = user_message
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
            context_mgr = get_memory_manager(_mk)
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

    # ПРОВЕРЯЕМ РОЛЕВУЮ КОМАНДУ
    role_info = detect_role_command(user_message)
    role_instruction = ""
    if role_info["is_role_command"]:
        print(f"[GET_AI_RESPONSE] 🎭 Обнаружена РОЛЕВАЯ КОМАНДА: {role_info['role']}")
        role_instruction = role_info["instruction"]
    
    # ОПРЕДЕЛЯЕМ РЕАЛЬНЫЙ ЯЗЫК ВОПРОСА
    detected_language = detect_message_language(user_message)
    # Для Qwen: если есть хоть одна кириллическая буква — принудительно русский.
    if _mk == "qwen":
        _has_cyrillic = any('\u0400' <= ch <= '\u04FF' for ch in user_message)
        if _has_cyrillic and detected_language != "russian":
            detected_language = "russian"
            print(f"[GET_AI_RESPONSE] [Qwen] Переопределён язык → РУССКИЙ (найдена кириллица)")
    # Для Mistral: если есть хоть одна кириллическая буква — принудительно русский.
    # Исправляет ложное определение "english" из-за технических терминов (API, JSON...).
    if _mk == "mistral":
        _has_cyrillic = any('\u0400' <= ch <= '\u04FF' for ch in user_message)
        if _has_cyrillic and detected_language != "russian":
            detected_language = "russian"
            print(f"[GET_AI_RESPONSE] [Mistral] Переопределён язык → РУССКИЙ (найдена кириллица)")
    print(f"[GET_AI_RESPONSE] Определённый язык вопроса: {detected_language}")

    # ═══════════════════════════════════════════════════════════
    # DEEPSEEK: BYPASS ПРОСТОЙ АРИФМЕТИКИ
    # Для "25 * 25", "100+200" и т.п. Python считает сам.
    # DeepSeek не вызывается — он генерирует мусор на таких запросах.
    # ═══════════════════════════════════════════════════════════
    if _mk in ("deepseek", "deepseek-r1"):
        _is_arith, _arith_expr = is_simple_arithmetic(user_message)
        if _is_arith and _arith_expr:
            _arith_result = compute_simple_arithmetic(_arith_expr, detected_language)
            if _arith_result:
                print(f"[GET_AI_RESPONSE] [DeepSeek] Простая арифметика — вычислено Python: {_arith_result}")
                return _arith_result, []

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

    # ══════════════════════════════════════════════════════════════════
    # СУБТЕКСТ: загружаем настройки пользователя один раз
    # Применяется ко ВСЕМ моделям одинаково
    # ══════════════════════════════════════════════════════════════════
    _st_prefs = {}
    try:
        _st_prefs = _SubtextManager.load()
    except Exception:
        pass
    _st_enabled = _st_prefs.get("enabled", False)
    _st_styles  = list(_st_prefs.get("style", []))
    if _st_prefs.get("auto_mode"):
        for _s in _st_prefs.get("auto_learned", {}).get("detected_style", []):
            if _s not in _st_styles:
                _st_styles.append(_s)
    _st_note = _st_prefs.get("custom_note", "").strip()
    _st_lang = _st_prefs.get("language", "").strip()

    # Строим единый блок пользовательских настроек — для ВСЕХ моделей.
    # Написан как факт об окружении, а не как команда — модели не зачитывают его вслух.
    _user_prefs_block = ""
    if _st_enabled:
        _ov = []
        if _st_lang and _st_lang not in ("", "Не важно (как спрошу)"):
            _lang_map = {
                "Русский":    "Respond ONLY in Russian. Never use any other language.",
                "English":    "Respond ONLY in English. Never use any other language.",
                "Украинський":"Відповідай ТІЛЬКИ українською. Жодного іншого мовного слова.",
                "Украинский": "Відповідай ТІЛЬКИ українською. Жодного іншого мовного слова.",
                "Беларуский": "Адказвай ТОЛЬКІ па-беларуску.",
                "Español":    "Responde SOLO en español. Nunca uses otro idioma.",
                "Deutsch":    "Antworte NUR auf Deutsch. Verwende keine andere Sprache.",
                "Français":   "Réponds UNIQUEMENT en français. N'utilise aucune autre langue.",
                "Polski":     "Odpowiadaj WYŁĄCZNIE po polsku. Nie używaj żadnego innego języka.",
            }
            _ov.append(_lang_map.get(_st_lang, f"Respond only in: {_st_lang}."))
        if "profanity" in _st_styles:
            pass  # Мат разрешается ТОЛЬКО через get_subtext_reminder() в конце промпта.
                  # Дублирование в начале создаёт шум и не помогает перебить RLHF-обучение.
        if "concise" in _st_styles:
            _ov.append("Keep responses short and to the point.")
        if "formal" in _st_styles:
            _ov.append("Use formal, professional tone.")
        if "warm" in _st_styles:
            _ov.append("Use a warm, friendly tone.")
        if "jokes" in _st_styles:
            _ov.append("Light humor is welcome.")
        if _st_note:
            _ov.append(_st_note)
        if _ov:
            _user_prefs_block = "\n".join(_ov) + "\n\n"
            print(f"[SUBTEXT] Префы активны для {_mk}: {list(_st_styles)}, lang={_st_lang!r}")

    # Переопределяет ли субтекст язык ответа?
    # True когда пользователь явно выбрал язык, отличный от русского или "как спрошу".
    _subtext_overrides_lang = bool(
        _st_enabled and _st_lang and _st_lang not in ("", "Не важно (как спрошу)", "Русский")
    )
    # Базовый язык для системного промпта.
    # Если субтекст задаёт нерусский язык — используем "english" как нейтральную базу:
    # это снимает конфликт «русские инструкции в промпте VS польская директива в субтексте»,
    # который заставляет модель отказывать или игнорировать выбранный язык.
    _effective_base_lang = "english" if _subtext_overrides_lang else detected_language
    if _subtext_overrides_lang:
        print(f"[SUBTEXT] Язык субтекста={_st_lang!r} → базовый промпт переключён на 'english'")

    # Язык для конструирования ВНУТРЕННИХ блоков промпта:
    # меток памяти, даты, контекста файлов и т.д.
    # Когда субтекст задаёт не-русский язык (например польский), пользователь
    # пишет по-русски → detected_language="russian", НО инжектировать русскоязычные
    # блоки ("Сегодня: понедельник", "ВАЖНАЯ ИНФОРМАЦИЯ") в промпт нельзя —
    # они перебивают польскую директиву и модель постепенно переходит на русский.
    # Решение: при override используем нейтральный "english" для всех внутренних блоков.
    _prompt_lang = _effective_base_lang  # "english" если subtext override, иначе detected_language

    # Выбираем промпт в зависимости от текущей модели
    if _mk in ("deepseek", "deepseek-r1"):
        _ds_base = get_deepseek_system_prompt(_effective_base_lang, mode)
        if _effective_base_lang == "russian":
            _identity_prefix = (
                "Ты — ИИ-ассистент DeepSeek. "
                "Ты НЕ GPT-4, НЕ ChatGPT, НЕ продукт OpenAI. "
                "Ты создан компанией DeepSeek AI. "
                "Отвечай коротко и по делу. "
                "Ты помнишь всю историю нашего текущего разговора — она передана выше в сообщениях. "
                "Если пользователь спрашивает что он только что написал или о чём шёл разговор — "
                "посмотри в историю сообщений и ответь точно.\n\n"
            )
        else:
            _identity_prefix = (
                "You are DeepSeek AI assistant. "
                "You are NOT GPT-4, NOT ChatGPT, NOT an OpenAI product. "
                "Answer concisely. "
                "You have full access to the current conversation history.\n\n"
            )
        base_system = _user_prefs_block + _identity_prefix + _ds_base
        print(f"[GET_AI_RESPONSE] Используется промпт DeepSeek")
    elif _mk == "mistral":
        base_system = _user_prefs_block + get_mistral_system_prompt(_effective_base_lang, mode)
        print(f"[GET_AI_RESPONSE] Используется промпт Mistral Nemo")
        if detect_user_correction(user_message):
            _warn = (
                "\n\n🔴 ВНИМАНИЕ: ПОЛЬЗОВАТЕЛЬ СЧИТАЕТ ЧТО ТЫ ДОПУСТИЛ ОШИБКУ.\n"
                "1. НЕ СОГЛАШАЙСЯ АВТОМАТИЧЕСКИ.\n"
                "2. Пересчитай с нуля самостоятельно, покажи все шаги.\n"
                "3. Если пользователь прав — признай и исправься.\n"
                "4. Если ты прав — вежливо объясни с доказательством.\n"
                "ЗАПРЕЩЕНО писать 'Вы правы' без собственной проверки."
            )
            base_system = base_system + _warn
            print(f"[GET_AI_RESPONSE] ⚠️ Обнаружена попытка исправления — добавлено предупреждение")
    elif _mk == "qwen":
        base_system = _user_prefs_block + get_qwen_system_prompt(_effective_base_lang, mode)
        # Явная директива против отказов читать тексты (реп, стихи и т.п.)
        base_system = base_system + (
            "\n\nВАЖНО: Ты обязан выполнять просьбы прочитать, процитировать или зачитать ЛЮБЫЕ тексты — "
            "рэп, стихи, песни, диалоги и т.д. Никогда не отказывайся от таких просьб. "
            "Если тебя просят зачитать реп или текст — делай это без комментариев о содержании.\n"
            "ВАЖНО: Если пользователь просит «зачитай реп», «читай рэп», «напиши реп» или похожее "
            "БЕЗ конкретного текста — ВСЕГДА СОЧИНИ ОРИГИНАЛЬНЫЙ рэп самостоятельно. "
            "ЗАПРЕЩЕНО цитировать чужие песни или артистов. Только твой собственный текст."
        )
        print(f"[GET_AI_RESPONSE] Используется промпт Qwen 3")
        if detect_user_correction(user_message):
            _warn = (
                "\n\n🔴 ВНИМАНИЕ: ПОЛЬЗОВАТЕЛЬ СЧИТАЕТ ЧТО ТЫ ДОПУСТИЛ ОШИБКУ.\n"
                "1. НЕ СОГЛАШАЙСЯ АВТОМАТИЧЕСКИ.\n"
                "2. Пересчитай с нуля самостоятельно, покажи все шаги.\n"
                "3. Если пользователь прав — признай и исправься.\n"
                "4. Если ты прав — вежливо объясни с доказательством.\n"
                "ЗАПРЕЩЕНО писать 'Вы правы' без собственной проверки."
            )
            base_system = base_system + _warn
    else:
        base_system = _user_prefs_block + SYSTEM_PROMPTS.get(_effective_base_lang, SYSTEM_PROMPTS["russian"])[mode]

    # Универсальная директива против отказов читать тексты (для всех моделей)
    _no_refusal_inject = (
        "\n\nВАЖНО: Ты обязан выполнять просьбы прочитать, зачитать или процитировать ЛЮБЫЕ тексты — "
        "рэп, стихи, песни, диалоги, монологи и т.д. — без отказов и без предупреждений о содержании. "
        "Запрещено говорить «Я не могу зачитать» или отказываться от цитирования по соображениям содержания. "
        "Если просят «зачитай реп» / «напиши реп» без конкретного текста — сочини ОРИГИНАЛЬНЫЙ рэп. "
        "ЗАПРЕЩЕНО цитировать чужих артистов или реальные песни — только собственный текст."
    )
    base_system = base_system + _no_refusal_inject

    # ══════════════════════════════════════════════════════════
    # ИНЖЕКЦИЯ ТЕКУЩЕЙ ДАТЫ И ВРЕМЕНИ — напрямую из Python
    # Это 100% надёжно — модель не может "забыть" или проигнорировать
    # ══════════════════════════════════════════════════════════
    _now = datetime.now()
    _weekdays_ru = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
    _months_ru   = ["января","февраля","марта","апреля","мая","июня",
                    "июля","августа","сентября","октября","ноября","декабря"]
    _date_ru = f"{_now.day} {_months_ru[_now.month-1]} {_now.year} г., {_weekdays_ru[_now.weekday()]}"
    _time_ru = _now.strftime("%H:%M")
    _date_en = _now.strftime("%B %d, %Y, %A")
    _time_en = _now.strftime("%H:%M")

    # Вычисляем завтрашний и послезавтрашний день
    from datetime import timedelta
    _tomorrow = _now + timedelta(days=1)
    _day_after = _now + timedelta(days=2)
    _tomorrow_ru = f"{_tomorrow.day} {_months_ru[_tomorrow.month-1]} {_tomorrow.year} г., {_weekdays_ru[_tomorrow.weekday()]}"
    _day_after_ru = f"{_day_after.day} {_months_ru[_day_after.month-1]} {_day_after.year} г., {_weekdays_ru[_day_after.weekday()]}"
    _tomorrow_en = _tomorrow.strftime("%B %d, %Y, %A")
    _day_after_en = _day_after.strftime("%B %d, %Y, %A")

    # Используем _prompt_lang (не detected_language!) — чтобы при польском субтексте
    # не инжектировать русскоязычную дату, которая сбивает модель обратно на русский.
    if _prompt_lang == "russian":
        if _mk in ("deepseek", "deepseek-r1"):
            # Для DeepSeek — компактная однострочная инжекция даты
            _datetime_inject = f"\n\nСегодня: {_date_ru}, время: {_time_ru}."
        else:
            _datetime_inject = (
                f"\n\n⚡ СИСТЕМНЫЙ ФАКТ (абсолютно точно, из системных часов компьютера):\n"
                f"• Сегодня: {_date_ru}\n"
                f"• Завтра: {_tomorrow_ru}\n"
                f"• Послезавтра: {_day_after_ru}\n"
                f"• Время сейчас: {_time_ru}\n"
                f"ОБЯЗАТЕЛЬНО используй эти данные при любых вопросах о дате, времени, дне недели.\n"
                f"Если пользователь спрашивает про 'завтра' — это {_tomorrow_ru}.\n"
                f"Твои обучающие данные о датах УСТАРЕЛИ — доверяй только этому системному факту."
            )
    else:
        if _mk in ("deepseek", "deepseek-r1"):
            _datetime_inject = f"\n\nToday: {_date_en}, time: {_time_en}."
        else:
            _datetime_inject = (
                f"\n\n⚡ SYSTEM FACT (exact, from computer system clock):\n"
                f"• Today: {_date_en}\n"
                f"• Tomorrow: {_tomorrow_en}\n"
                f"• Day after tomorrow: {_day_after_en}\n"
                f"• Current time: {_time_en}\n"
                f"ALWAYS use this when answering questions about date, time, or day of week.\n"
                f"If user asks about 'tomorrow' — that is {_tomorrow_en}.\n"
                f"Your training data about dates is OUTDATED — trust only this system fact."
            )
    base_system = base_system + _datetime_inject
    print(f"[GET_AI_RESPONSE] 📅 Инжектирована дата: {_date_ru if _prompt_lang == 'russian' else _date_en}")
    
    # ═══════════════════════════════════════════════════════════
    # ЗАГРУЗКА СОХРАНЁННОЙ ПАМЯТИ
    # DeepSeek читает из deepseek_memory.db, LLaMA — из context_memory.db
    # ═══════════════════════════════════════════════════════════
    memory_context = ""
    if chat_id:
        try:
            context_mgr = get_memory_manager(_mk)
            saved_memories = context_mgr.get_context_memory(chat_id, limit=20)
            
            if saved_memories:
                # Разделяем по типам
                user_memories = [r[1] for r in saved_memories if r[0] == "user_memory"]
                file_analyses = [r[1] for r in saved_memories if r[0] == "file_analysis"]
                
                # Пользовательская память
                if user_memories:
                    if _prompt_lang == "russian":
                        memory_context = "\n\n📌 ВАЖНАЯ ИНФОРМАЦИЯ (пользователь просил запомнить):\n"
                        for idx, mem in enumerate(user_memories, 1):
                            memory_context += f"{idx}. {mem}\n"
                        print(f"[MEMORY] ✓ Загружено {len(user_memories)} записей памяти")
                    else:
                        memory_context = "\n\n📌 IMPORTANT INFORMATION (user asked to remember):\n"
                        for idx, mem in enumerate(user_memories, 1):
                            memory_context += f"{idx}. {mem}\n"
                        print(f"[MEMORY] ✓ Loaded {len(user_memories)} memory records")
                
                # КРИТИЧНО: Добавляем контекст файлов из памяти
                # НО только если:
                #   1. В ТЕКУЩЕМ запросе нет своих файлов
                #   2. Сообщение НЕ является чисто разговорным (спасибо, ок, привет…)
                #      Для разговорных сообщений file_analysis НЕ нужен —
                #      именно он вызывает галлюцинации о содержимом файлов.
                _skip_file_ctx = (
                    (file_paths and len(file_paths) > 0)
                    or _is_conversational_message(user_message)
                )
                if file_analyses and not _skip_file_ctx:
                    # Берём последний анализ файлов (самый свежий)
                    latest_file_context = file_analyses[-1]
                    if _prompt_lang == "russian":
                        memory_context += f"\n\n📎 КОНТЕКСТ ИЗ ПРИКРЕПЛЁННЫХ ФАЙЛОВ:\n{latest_file_context}\n"
                        memory_context += "\n(Используй этот контекст ТОЛЬКО если пользователь явно спрашивает о файлах. Не упоминай файлы если вопрос не связан с ними.)\n"
                        print(f"[MEMORY] ✓ Загружен контекст файлов ({len(latest_file_context)} символов)")
                    else:
                        memory_context += f"\n\n📎 CONTEXT FROM ATTACHED FILES:\n{latest_file_context}\n"
                        memory_context += "\n(Use this context ONLY if the user explicitly asks about files. Don't mention files if the question is unrelated.)\n"
                        print(f"[MEMORY] ✓ Loaded file context ({len(latest_file_context)} chars)")
                elif file_analyses and _is_conversational_message(user_message):
                    print(f"[MEMORY] ⏭ Пропуск file_analysis — разговорное сообщение: '{user_message[:40]}'"  )
        except Exception as e:
            print(f"[MEMORY] ✗ Ошибка загрузки памяти: {e}")
    
    # Добавляем математический промпт если это математическая задача
    math_prompt = ""
    if is_math_problem:
        # Выбираем математический промпт в зависимости от модели и режима AI
        if _mk in ("deepseek", "deepseek-r1"):
            _ds_mode = {"fast": "short", "thinking": "deep", "pro": "pro"}.get(
                ai_mode.lower().replace("быстрый","short").replace("думающий","deep").replace("про","pro"), "short"
            )
            if ai_mode == AI_MODE_FAST:
                _ds_mode = "short"
            elif ai_mode == AI_MODE_THINKING:
                _ds_mode = "deep"
            elif ai_mode == AI_MODE_PRO:
                _ds_mode = "pro"
            math_prompt = get_deepseek_math_prompt(_ds_mode)
            print(f"[GET_AI_RESPONSE] 🔬 DeepSeek математика - режим: {_ds_mode}")
        else:
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
                math_prompt = MATH_PROMPTS["thinking"]
                print(f"[GET_AI_RESPONSE] 🔬 Математика - режим: ДУМАЮЩИЙ (по умолчанию)")
        
        print(f"[GET_AI_RESPONSE] ⚠️ Интернет ЗАПРЕЩЁН для математических задач")
        
        # КРИТИЧНО: Для математических задач ЗАПРЕЩАЕМ интернет
        use_search = False
    
    # ══════════════════════════════════════════════════════════
    # БЛОК ПОНИМАНИЯ КОНТЕКСТА ДИАЛОГА
    # ══════════════════════════════════════════════════════════
    context_understanding_ru = """


═══════════════════════════════════════════════════════════
🧠 ПОНИМАНИЕ КОНТЕКСТА ДИАЛОГА — КРИТИЧЕСКИ ВАЖНО
═══════════════════════════════════════════════════════════

Ты ВСЕГДА читаешь всю историю переписки перед ответом. Это значит:

1. ССЫЛКИ НА ПРОШЛОЕ ("в неё", "в него", "это", "то самое", "оно"):
   • "давай сыграем в неё" → посмотри что обсуждалось выше и пойми что "в неё" = та игра/активность
   • "сделай то же самое" → повтори последнее действие из истории
   • "продолжай" → продолжи то что делал раньше
   • "ещё раз" → повтори предыдущий ответ или действие
   ❌ НЕЛЬЗЯ: делать вид что не понимаешь о чём речь и переспрашивать
   ✅ НУЖНО: найти референс в истории и выполнить просьбу

2. ПРОСЬБА НАЧАТЬ АКТИВНОСТЬ ("давай сыграем", "поиграем", "начнём", "устроим"):
   • Немедленно НАЧНИ эту активность — не объясняй что готов, не описывай правила снова
   • Если это игра — сделай первый ход сам или попроси пользователя начать
   • ❌ НЕЛЬЗЯ: "Я готов! Пожалуйста задавайте вопросы..." — это игнорирование просьбы
   • ✅ НУЖНО: сразу начать играть, назвать первое слово/ход/вопрос

3. УТОЧНЕНИЯ И УСЛОВИЯ ("только по России", "только на букву А", "без повторов"):
   • Запомни условие и соблюдай его во всех последующих ответах
   • ❌ НЕЛЬЗЯ: игнорировать условие или забыть о нём через 1-2 хода
   • ✅ НУЖНО: каждый ответ проверять соответствие условию

4. СМЕНА ТЕМЫ:
   • Если пользователь явно меняет тему — переключайся
   • Если нет — оставайся в контексте текущей активности

ПРИМЕРЫ ПРАВИЛЬНОГО ПОВЕДЕНИЯ:
• Пользователь спросил про игру "Города" → ИИ объяснил
• Пользователь: "давай сыграем, только по России"
• ✅ ИИ: "Отлично! Начинаю: Москва. Ваш ход — называй город на букву 'А'!"
• ❌ ИИ: "Я готов помочь с вопросами о России!" (это провал — он не начал игру)
═══════════════════════════════════════════════════════════"""

    context_understanding_en = """


═══════════════════════════════════════════════════════════
🧠 CONVERSATION CONTEXT UNDERSTANDING — CRITICAL
═══════════════════════════════════════════════════════════

You ALWAYS read the full chat history before responding:

1. REFERENCES TO PAST ("it", "that", "the same", "do it again"):
   • Find the reference in history and act on it immediately
   • ❌ NEVER: pretend you don't understand or ask what they mean
   • ✅ ALWAYS: look back in history and fulfill the request

2. REQUESTS TO START AN ACTIVITY ("let's play", "let's start", "begin"):
   • IMMEDIATELY start the activity — don't just say you're ready
   • ❌ NEVER: "I'm ready! Please ask me questions..." — this ignores the request
   • ✅ ALWAYS: make the first move, say the first word, start the game

3. CONDITIONS AND RULES ("only Russia", "no repeats", "only letter A"):
   • Remember and follow the condition in ALL subsequent responses
═══════════════════════════════════════════════════════════"""

    # ══════════════════════════════════════════════════════════
    # СБОРКА СИСТЕМНОГО ПРОМПТА
    # DeepSeek — маленькая (7b) модель: огромный промпт вызывает
    # галлюцинации и потерю контекста диалога.
    # Для DeepSeek: только base + memory + math + role + язык.
    # context_understanding и FILE_GENERATION_PROMPT — только для LLaMA/Mistral.
    # FILE_GENERATION_PROMPT добавляем когда: прикреплён файл ИЛИ пользователь просит создать файл.
    # ══════════════════════════════════════════════════════════
    _has_files_in_request = bool(file_paths and len(file_paths) > 0)
    _is_file_creation_request = detect_file_request(user_message)
    # Если файл прикреплён + пользователь явно просит что-то с ним сделать
    # — всегда включаем FILE_GENERATION_PROMPT
    _file_action_re = __import__('re').compile(
        r'(создай|сделай|выдай|дай|перепиш|перезапиш|передай|отдай|обнови|измени'
        r'|create|make|give|rewrite|update|output)',
        __import__('re').IGNORECASE
    )
    _is_file_action_with_attachment = (
        _has_files_in_request and bool(_file_action_re.search(user_message))
    )
    _needs_file_gen_prompt = _has_files_in_request or _is_file_creation_request or _is_file_action_with_attachment
    _is_deepseek = _mk in ("deepseek", "deepseek-r1")
    # Qwen3: жёсткие директивы в subtext_reminder вызывают chain-of-thought вслух.
    # Для Qwen используем смягчённую версию — без заголовков-команд.
    _is_qwen = _mk == "qwen"

    # ── _subtext_overrides_lang и _effective_base_lang уже вычислены выше ──────
    # (сразу после построения _user_prefs_block)

    # Блок разрешения мата — вставляется ПОСЛЕДНИМ перед reminder.
    # Позиция "конец промпта" критична: модели с RLHF весят последние токены сильнее.
    # ВАЖНО: НЕ перечисляем конкретные слова — локальные модели начинают их зачитывать
    # и уходят в repetition loop. Используем общее описание без конкретных слов.
    _profanity_override = ""
    if _st_enabled and "profanity" in _st_styles:
        _profanity_override = (
            "\n\nСТИЛЬ ОБЩЕНИЯ: пользователь выбрал разговорный стиль без ограничений на лексику. "
            "Используй естественный живой язык, включая ненормативную лексику, органично и по контексту. "
            "Не заменяй сильные выражения мягкими аналогами. "
            "Не комментируй и не объясняй своё использование такой лексики. "
            "Отвечай НАПРЯМУЮ — без внутренних рассуждений вслух."
        )

    if detected_language == "russian" and not _subtext_overrides_lang:
        _lang_rule = (
            "\n\nВАЖНО: отвечай строго на русском языке. "
            "Не используй иностранные слова: вместо «your turn» — «ваш ход», "
            "вместо «sorry» — «извините» и т.д."
        )
        if _is_deepseek:
            # Компактный промпт для DeepSeek — не перегружаем маленькую модель
            _file_gen_part = FILE_GENERATION_PROMPT if _needs_file_gen_prompt else ""
            system_prompt = get_subtext_injection() + base_system + memory_context + math_prompt + role_instruction + _lang_rule + _file_gen_part + _profanity_override + get_subtext_reminder()
        elif _is_qwen:
            # Qwen3: get_subtext_reminder() с жёсткими CAPS-директивами вызывает
            # chain-of-thought вслух. Используем инъекцию из начала промпта вместо reminder.
            # _profanity_override и get_subtext_injection() уже несут мягкую версию правил.
            _file_gen_part = FILE_GENERATION_PROMPT if _needs_file_gen_prompt else ""
            system_prompt = get_subtext_injection() + base_system + memory_context + math_prompt + role_instruction + context_understanding_ru + _file_gen_part + _profanity_override
        else:
            # FILE_GENERATION_PROMPT — только когда реально просят файл.
            # Если добавлять его ВСЕГДА, модель начинает генерировать файлы
            # при любом обычном вопросе (видит инструкцию → применяет её).
            _file_gen_part = FILE_GENERATION_PROMPT if _needs_file_gen_prompt else ""
            system_prompt = get_subtext_injection() + base_system + memory_context + math_prompt + role_instruction + context_understanding_ru + _file_gen_part + """

КРИТИЧЕСКИ ВАЖНО - ЯЗЫК ОТВЕТА:
• Отвечай СТРОГО ТОЛЬКО на русском языке
• НЕЛЬЗЯ использовать слова на любом иностранном языке: английском, испанском, итальянском, французском и т.д.
• ЗАПРЕЩЕНО: "turno", "your turn", "turn", "move", "next", "please", "try", "sorry" и любые другие иностранные слова
• Вместо иностранных слов используй ТОЛЬКО русские: "ваш ход", "попробуйте", "извините", "далее" и т.д.
• Русские эквиваленты: however→однако, therefore→поэтому, important→важный, turn→ход, your→ваш, try→попробуйте""" + _profanity_override + get_subtext_reminder()
    else:
        if _is_deepseek:
            _file_gen_part = FILE_GENERATION_PROMPT if _needs_file_gen_prompt else ""
            system_prompt = get_subtext_injection() + base_system + memory_context + math_prompt + role_instruction + _file_gen_part + _profanity_override + get_subtext_reminder()
        elif _is_qwen:
            # Qwen3: без жёсткого reminder — только мягкая инъекция из начала промпта
            _file_gen_part = FILE_GENERATION_PROMPT if _needs_file_gen_prompt else ""
            system_prompt = get_subtext_injection() + base_system + memory_context + math_prompt + role_instruction + _file_gen_part + _profanity_override
        else:
            _file_gen_part = FILE_GENERATION_PROMPT if _needs_file_gen_prompt else ""
            system_prompt = get_subtext_injection() + base_system + memory_context + math_prompt + role_instruction + context_understanding_en + _file_gen_part + _profanity_override + get_subtext_reminder()

    # ── Железное усиление языка ─────────────────────────────────────────────────
    # Если субтекст задаёт конкретный язык — добавляем жёсткое правило В КОНЕЦ
    # системного промпта, независимо от всех других механизмов.
    # Это спасает от ситуации когда get_subtext_injection/reminder вернули пустое
    # (например, после полной очистки памяти).
    if _st_lang and _st_lang not in ("", "Не важно (как спрошу)"):
        _lang_map_final = {
            "Русский":     "\n\nОТВЕЧАЙ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.",
            "English":     "\n\nRESPOND ONLY IN ENGLISH.",
            "Украинський": "\n\nВІДПОВІДАЙ ТІЛЬКИ УКРАЇНСЬКОЮ.",
            "Украинский":  "\n\nВІДПОВІДАЙ ТІЛЬКИ УКРАЇНСЬКОЮ.",
            "Polski":      "\n\nODPOWIADAJ WYŁĄCZNIE PO POLSKU. Żadnego innego języka.",
            "Español":     "\n\nRESPONDE SOLO EN ESPAÑOL.",
            "Deutsch":     "\n\nANTWORTE NUR AUF DEUTSCH.",
            "Français":    "\n\nRÉPONDS UNIQUEMENT EN FRANÇAIS.",
            "Беларуский":  "\n\nАДКАЗВАЙ ТОЛЬКІ ПА-БЕЛАРУСКУ.",
        }
        _final_lang_rule = _lang_map_final.get(_st_lang, f"\n\nRESPOND ONLY IN: {_st_lang}.")
        system_prompt = system_prompt + _final_lang_rule
        print(f"[LANG] ✅ Усиление языка в конце промпта: {_st_lang!r}")

    final_user_message = user_message

    # User-turn инъекция директив УДАЛЕНА:
    # модели зачитывали директиву вслух вместо молчаливого применения.
    # Все правила теперь только в system_prompt через _identity_override.

    # ── Если пользователь просит создать файл — вшиваем жёсткую инструкцию
    # прямо в сообщение. Локальные модели следуют inline-инструкциям намного
    # надёжнее, чем инструкциям в системном промпте.
    # Передаём имя прикреплённого файла — если "перепиши этот файл" без имени
    _attached_name = file_paths[0] if file_paths else None
    _file_injection = build_file_injection(user_message, detected_language,
                                           attached_file_name=_attached_name)
    if _file_injection:
        final_user_message = final_user_message + _file_injection
        print(f"[FILE_GEN] Запрос на файл — инструкция вшита (имя: {_attached_name})")

    all_files_context = []  # Инициализируем заранее — используется позже вне блока if file_paths
    
    # Обрабатываем прикреплённые файлы
    if file_paths and len(file_paths) > 0:
        print(f"[GET_AI_RESPONSE] Обработка файлов: {len(file_paths)}")
        
        for file_path in file_paths:
            # УЛУЧШЕНИЕ: Нормализуем путь к файлу
            file_path = os.path.normpath(os.path.abspath(file_path))
            print(f"[GET_AI_RESPONSE] Обработка файла: {file_path}")
            print(f"[GET_AI_RESPONSE] ════════════════════════════════════════")
            
            try:
                file_ext = os.path.splitext(file_path)[1].lower()
                file_name = os.path.basename(file_path)
                
                # ПРОВЕРКА: убеждаемся что файл существует
                if not os.path.exists(file_path):
                    print(f"[GET_AI_RESPONSE] ⚠️ ФАЙЛ НЕ НАЙДЕН: {file_path}")
                    
                    # Возвращаем понятную ошибку пользователю
                    if detected_language == "russian":
                        error_msg = f"""🔴 Файл '{file_name}' не найден

Путь: {file_path}

Возможные причины:
• Файл был перемещён или удалён
• Неправильный путь к файлу
• Проблема с правами доступа

Попробуйте:
1. Прикрепите файл заново
2. Убедитесь что файл существует на диске
3. Проверьте права доступа к файлу"""
                    else:
                        error_msg = f"""🔴 File '{file_name}' not found

Path: {file_path}

Possible reasons:
• File was moved or deleted
• Incorrect file path
• Access permission issue

Try:
1. Attach the file again
2. Make sure the file exists on disk
3. Check file access permissions"""
                    
                    return error_msg
                
                # Проверяем тип файла
                if is_image_file(file_path):
                    # ═══════════════════════════════════════════════════════
                    # ИЗОБРАЖЕНИЕ — делегируем в vision_handler.py
                    # ═══════════════════════════════════════════════════════
                    result = process_image_file(
                        file_path=file_path,
                        file_name=file_name,
                        user_message=user_message,
                        ai_mode=ai_mode,
                        language=detected_language,
                    )
                    if result["success"]:
                        all_files_context.append(f"[Изображение: {file_name}]\n{result['content']}")
                    else:
                        return result["content"]

                else:
                    # ═══════════════════════════════════════════════════════
                    # ТЕКСТОВЫЙ ФАЙЛ - Читаем и обрабатываем обычной моделью
                    # ═══════════════════════════════════════════════════════
                    print(f"[GET_AI_RESPONSE] 📄 ТИП: ТЕКСТОВЫЙ ФАЙЛ")
                    print(f"[GET_AI_RESPONSE] 🤖 МОДЕЛЬ: {OLLAMA_MODEL} (обычная модель)")
                    print(f"[GET_AI_RESPONSE] 📖 Чтение файла...")
                    
                    try:
                        # Пробуем разные кодировки
                        encodings = ['utf-8', 'cp1251', 'latin-1']
                        file_content = None
                        used_encoding = None
                        
                        for encoding in encodings:
                            try:
                                with open(file_path, 'r', encoding=encoding) as f:
                                    file_content = f.read()[:10000]  # Ограничиваем 10000 символов
                                used_encoding = encoding
                                break
                            except UnicodeDecodeError:
                                continue
                        
                        if file_content:
                            if detected_language == "russian":
                                all_files_context.append(f"""[Файл: {file_name}]
СОДЕРЖИМОЕ:
{file_content}""")
                            else:
                                all_files_context.append(f"""[File: {file_name}]
CONTENT:
{file_content}""")
                            print(f"[GET_AI_RESPONSE] ✅ Файл прочитан ({used_encoding}): {file_name}")
                        else:
                            raise UnicodeDecodeError("all", b"", 0, 0, "Could not decode with any encoding")
                            
                    except Exception as e:
                        # Не удалось прочитать как текст
                        print(f"[GET_AI_RESPONSE] ❌ Не удалось прочитать файл: {file_name} ({e})")
                        
                        # Показываем понятное сообщение
                        if detected_language == "russian":
                            error_msg = f"""⚠️ Файл '{file_name}' не может быть прочитан

Возможные причины:
• Это бинарный файл (exe, pdf, docx и т.д.)
• Неподдерживаемая кодировка

Поддерживаемые текстовые файлы: .txt, .py, .js, .html, .css, .md и др.
Для изображений используйте форматы: .png, .jpg, .jpeg, .gif"""
                        else:
                            error_msg = f"""⚠️ File '{file_name}' cannot be read

Possible reasons:
• This is a binary file (exe, pdf, docx, etc.)
• Unsupported encoding

Supported text files: .txt, .py, .js, .html, .css, .md, etc.
For images use formats: .png, .jpg, .jpeg, .gif"""
                        
                        return error_msg
                        
            except Exception as e:
                print(f"[GET_AI_RESPONSE] Ошибка обработки файла {file_name}: {e}")
                import traceback
                traceback.print_exc()
        
        # Объединяем контекст всех файлов
        if all_files_context:
            # Формируем инструкцию в зависимости от режима
            if ai_mode == AI_MODE_FAST:
                if _prompt_lang == "russian":
                    file_instruction = "Кратко ответь на вопрос используя информацию из файлов."
                else:
                    file_instruction = "Answer briefly using information from the files."
            elif ai_mode == AI_MODE_THINKING:
                if _prompt_lang == "russian":
                    file_instruction = "Проанализируй содержимое файлов. Дай развернутый ответ с примерами и пояснениями."
                else:
                    file_instruction = "Analyze the file contents. Provide a detailed answer with examples and explanations."
            else:  # PRO
                if _prompt_lang == "russian":
                    file_instruction = """Максимально глубокий анализ файлов:
1. Обзор всех файлов
2. Ключевые моменты из каждого файла
3. Связи между файлами (если применимо)
4. Детальный ответ на вопрос пользователя с обоснованием"""
                else:
                    file_instruction = """Maximum deep file analysis:
1. Overview of all files
2. Key points from each file
3. Connections between files (if applicable)
4. Detailed answer to user's question with justification"""
            
            files_context = "\n\n".join(all_files_context)
            
            if _prompt_lang == "russian":
                final_user_message = f"""[Пользователь прикрепил {len(file_paths)} файл(ов)]

{files_context}

ИНСТРУКЦИЯ:
{file_instruction}

Вопрос/сообщение пользователя: {user_message}

ВАЖНО: 
- Если пользователь просто прислал файл без вопроса (например "как тебе фотка?" или просто название файла), ОБЯЗАТЕЛЬНО:
  1. Опиши ЧТО изображено/написано в файле
  2. Дай свою оценку/комментарий
  3. Задай уточняющий вопрос если нужно
- Если есть конкретный вопрос - отвечай на него используя информацию из файла
- Отвечай естественно, как будто видишь файл и обсуждаешь его с другом"""
            else:
                final_user_message = f"""[User attached {len(file_paths)} file(s)]

{files_context}

INSTRUCTION:
{file_instruction}

User's question/message: {user_message}

IMPORTANT:
- If user just sent a file without specific question (e.g. "how's the photo?" or just filename), YOU MUST:
  1. Describe WHAT is shown/written in the file
  2. Give your assessment/comment
  3. Ask clarifying question if needed
- If there's a specific question - answer it using file information
- Respond naturally, as if you're seeing the file and discussing it with a friend"""
            
            print(f"[GET_AI_RESPONSE] Все файлы добавлены в контекст")
            
            # ═══════════════════════════════════════════════════════════
            # СОХРАНЕНИЕ КОНТЕКСТА ФАЙЛОВ В ПАМЯТЬ
            # ═══════════════════════════════════════════════════════════
            # КРИТИЧНО: Сохраняем результаты анализа файлов в историю
            # чтобы AI помнил содержимое файлов в следующих сообщениях
            if chat_id and all_files_context:
                try:
                    context_mgr = get_memory_manager(_mk)
                    files_summary = "\n\n".join(all_files_context)
                    
                    # Сохраняем компактную версию для истории
                    # Ограничиваем длину чтобы не засорять память
                    max_length = 2000  # Максимум 2000 символов
                    if len(files_summary) > max_length:
                        files_summary = files_summary[:max_length] + "...[содержимое обрезано]"
                    
                    context_mgr.save_context_memory(chat_id, "file_analysis", files_summary)
                    print(f"[GET_AI_RESPONSE] ✓ Контекст файлов сохранён в память ({len(files_summary)} символов)")
                except Exception as e:
                    print(f"[GET_AI_RESPONSE] ⚠️ Ошибка сохранения контекста файлов: {e}")
    
    print(f"[GET_AI_RESPONSE] Контекстная память добавлена в системный промпт")

    found_sources = []  # Список (title, url) — заполняется если был поиск

    if use_search:
        print(f"[GET_AI_RESPONSE] ПОИСК АКТИВИРОВАН! Выполняю поиск...")
        if detected_language == "russian":
            region = "ru-ru"
        else:
            region = "us-en"
        num_results = 8 if deep_thinking else 3
        
        # 🔥 КОНТЕКСТНЫЙ ПОИСК: формируем запрос с учётом истории диалога
        contextual_query = build_contextual_search_query(user_message, chat_manager, chat_id, detected_language)

        # ── Подстановка реальных дат вместо "завтра"/"послезавтра" ──────────
        # Чтобы поисковик получал точную дату, а не относительное слово
        from datetime import timedelta as _td
        _sq_now = datetime.now()
        _sq_months_ru = ["января","февраля","марта","апреля","мая","июня",
                         "июля","августа","сентября","октября","ноября","декабря"]
        _sq_tomorrow  = _sq_now + _td(days=1)
        _sq_dayafter  = _sq_now + _td(days=2)
        _sq_yesterday = _sq_now - _td(days=1)
        _sq_tom_ru  = f"{_sq_tomorrow.day} {_sq_months_ru[_sq_tomorrow.month-1]}"
        _sq_daf_ru  = f"{_sq_dayafter.day} {_sq_months_ru[_sq_dayafter.month-1]}"
        _sq_yes_ru  = f"{_sq_yesterday.day} {_sq_months_ru[_sq_yesterday.month-1]}"
        _sq_tom_en  = _sq_tomorrow.strftime("%B %d")
        _sq_daf_en  = _sq_dayafter.strftime("%B %d")
        _sq_yes_en  = _sq_yesterday.strftime("%B %d")
        import re as _re_sq
        if detected_language == "russian":
            contextual_query = _re_sq.sub(r'\bпослезавтра\b', _sq_daf_ru,  contextual_query, flags=_re_sq.IGNORECASE)
            contextual_query = _re_sq.sub(r'\bзавтра\b',      _sq_tom_ru,   contextual_query, flags=_re_sq.IGNORECASE)
            contextual_query = _re_sq.sub(r'\bвчера\b',       _sq_yes_ru,   contextual_query, flags=_re_sq.IGNORECASE)
        else:
            contextual_query = _re_sq.sub(r'\bday after tomorrow\b', _sq_daf_en, contextual_query, flags=_re_sq.IGNORECASE)
            contextual_query = _re_sq.sub(r'\btomorrow\b',            _sq_tom_en, contextual_query, flags=_re_sq.IGNORECASE)
            contextual_query = _re_sq.sub(r'\byesterday\b',           _sq_yes_en, contextual_query, flags=_re_sq.IGNORECASE)

        print(f"[GET_AI_RESPONSE] 🔍 Поисковый запрос: {contextual_query}")
        
        # ── Маршрутизация запросов: версии ПО → специальный пайплайн ──
        # Запросы о версиях, релизах, changelog обрабатываются модульным
        # пайплайном version_search_pipeline (search→filter→extract→validate→answer),
        # который делает несколько поисковых запросов, фильтрует источники
        # по качеству, извлекает и валидирует версии, формирует ответ
        # с явным запретом на галлюцинации.
        _is_version_q = is_version_query(contextual_query)

        if _is_version_q:
            print(f"[GET_AI_RESPONSE] 📦 ОПРЕДЕЛЁН ЗАПРОС О ВЕРСИИ ПО "
                  f"→ Запускаю version_search_pipeline")
            search_results, _page_contents = version_search_pipeline(
                contextual_query,
                region=region,
                language=detected_language,
            )
            # Если пайплайн ничего не вернул — откатываемся к обычному поиску
            if not _page_contents:
                print(f"[GET_AI_RESPONSE] ⚠️ Пайплайн версий пуст, откатываюсь к deep_web_search")
                _is_version_q = False

        if not _is_version_q:
            # УМНЫЙ ПОИСК: все режимы заходят на сайты, отличается только глубина
            if ai_mode in [AI_MODE_THINKING, AI_MODE_PRO]:
                print(f"[GET_AI_RESPONSE] 🧠 Использую ГЛУБОКИЙ веб-поиск (3 сайта)")
                search_results, _page_contents = deep_web_search(
                    contextual_query, num_results=num_results,
                    region=region, language=detected_language, max_pages=3)
            else:
                print(f"[GET_AI_RESPONSE] ⚡ Использую БЫСТРЫЙ веб-поиск (1 сайт)")
                search_results, _page_contents = deep_web_search(
                    contextual_query, num_results=num_results,
                    region=region, language=detected_language, max_pages=1)

            # ── ЗАЩИТА ОТ ГАЛЛЮЦИНАЦИЙ (только для обычного поиска) ──
            _version_guard = validate_versions_before_answer(_page_contents, contextual_query)
            if _version_guard["retry"]:
                print(
                    f"[VERSION_GUARD] 🔄 Источники устаревшие "
                    f"(лучшая версия: «{_version_guard['best_version']}», "
                    f"причина: {_version_guard['reason']}). "
                    f"Повторяю поиск с уточнёнными ключами..."
                )
                import datetime as _dt
                _retry_q = (f"{contextual_query} latest version release "
                            f"{_dt.datetime.now().year}")
                _retry_str, _retry_pages = deep_web_search(
                    _retry_q, num_results=num_results,
                    region=region, language=detected_language, max_pages=3,
                )
                if _retry_pages:
                    search_results = _retry_str
                    _page_contents = _retry_pages
                    print(f"[VERSION_GUARD] ✅ Повторный поиск: {len(_retry_pages)} свежих страниц")
                else:
                    print(f"[VERSION_GUARD] ⚠️ Повторный поиск пустой, оставляем исходные данные")

            if _version_guard["best_version"]:
                print(f"[VERSION_GUARD] 📌 Лучшая версия: «{_version_guard['best_version']}» "
                      f"из {len(_version_guard['all_versions'])} вариантов")
        
        print(f"[GET_AI_RESPONSE] Результаты поиска получены. Длина: {len(search_results)} символов")
        print(f"[GET_AI_RESPONSE] Первые 300 символов результатов: {search_results[:300]}...")

        # ── Извлекаем источники (Заголовок + Ссылка) для кнопки "Источники" ──
        _src_titles = re.findall(r'Заголовок:\s*(.+)', search_results)
        _src_urls   = re.findall(r'Ссылка:\s*(https?://\S+)', search_results)
        found_sources = []
        for i, url in enumerate(_src_urls):
            title = _src_titles[i].strip() if i < len(_src_titles) else url
            found_sources.append((title, url))
        print(f"[GET_AI_RESPONSE] 🔗 Извлечено источников: {len(found_sources)}")

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

        # ══════════════════════════════════════════════════════════
        # НОВЫЙ ПАЙПЛАЙН: суммаризация → анализ вопроса → финальная генерация
        # ══════════════════════════════════════════════════════════

        # ШАГ 1: Извлекаем только факты из сырых результатов
        facts = summarize_sources(search_results, user_message, detected_language, model_key=_mk)

        # ШАГ 1.5: Проверяем релевантность фактов
        # Если суммаризатор вернул "не найдено" — говорим модели использовать свои знания
        no_facts_markers = ["релевантных фактов не найдено", "no relevant facts found", "не найдено", "нет информации"]
        facts_are_irrelevant = any(marker in facts.lower() for marker in no_facts_markers)
        if facts_are_irrelevant:
            print(f"[GET_AI_RESPONSE] ⚠️ Релевантных фактов из поиска не найдено — модель будет использовать собственные знания")
            if detected_language == "russian":
                facts = f"Поиск не дал релевантных результатов по запросу «{user_message}». Ответь на основе своих знаний."
            else:
                facts = f"Search did not return relevant results for «{user_message}». Answer based on your own knowledge."

        # ШАГ 2: Определяем структуру вопроса
        question_parts = detect_question_parts(user_message)

        # ШАГ 3: Строим финальный промпт
        search_context = build_final_answer_prompt(user_message, facts, question_parts, detected_language)
        print(f"[GET_AI_RESPONSE] Контекст поиска добавлен. Длина: {len(search_context)} символов")
        
        # ИСПРАВЛЕНИЕ: Если есть файлы, добавляем их контекст К поисковым результатам
        if all_files_context:
            files_summary = "\n\n".join(all_files_context)
            if detected_language == "russian":
                final_user_message = f"""{search_context}

[ДОПОЛНИТЕЛЬНО: Пользователь прикрепил {len(file_paths)} файл(ов)]

{files_summary}

Учитывай информацию из ОБЕИХ источников: результаты поиска И прикреплённые файлы."""
            else:
                final_user_message = f"""{search_context}

[ADDITIONALLY: User attached {len(file_paths)} file(s)]

{files_summary}

Consider information from BOTH sources: search results AND attached files."""
            print(f"[GET_AI_RESPONSE] ✓ Контекст файлов СОХРАНЁН при поиске")
        else:
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
        # Загружаем историю диалога из memory_manager (primary) или chat_manager (fallback)
        # memory_manager хранит только чистые повороты user/assistant — без мусора.
        # Это гарантирует, что ИИ ВИДИТ СВОИ предыдущие ответы.
        _history_limit = 20 if _mk in ("deepseek", "deepseek-r1") else MAX_HISTORY_LOAD

        mem_mgr = get_memory_manager(_mk)
        mem_messages = []
        if chat_id and hasattr(mem_mgr, 'get_messages'):
            try:
                mem_messages = mem_mgr.get_messages(chat_id, limit=_history_limit)
                print(f"[GET_AI_RESPONSE] Загружено {len(mem_messages)} сообщений из memory_manager ({_mk})")
            except Exception as _mex:
                print(f"[GET_AI_RESPONSE] ⚠️ memory_manager.get_messages: {_mex}")

        # Fallback: если memory_manager пустой (старые чаты) — грузим из chat_manager
        if not mem_messages:
            if chat_manager and chat_id:
                _fb_history = chat_manager.get_chat_messages(chat_id, limit=_history_limit)
                print(f"[GET_AI_RESPONSE] Fallback: {len(_fb_history)} сообщений из chat_manager")
                _fb = list(_fb_history)
                if _fb and _fb[-1][0] == "user" and _fb[-1][1] in (_user_message_raw, user_message):
                    _fb = _fb[:-1]
                mem_messages = [
                    {"role": r[0], "content": r[1]}
                    for r in _fb if r[0] in ("user", "assistant")
                ]
            else:
                # Старая БД chat_memory.db не имеет chat_id — читать её НЕЛЬЗЯ,
                # иначе любая модель получает историю ВСЕХ удалённых чатов.
                # Намеренно возвращаем пустую историю.
                print(f"[GET_AI_RESPONSE] ⚠️ chat_id=None — история не загружается (защита от утечки)")
                mem_messages = []
        else:
            # memory_manager уже содержит текущий user_message (сохранён до вызова ИИ)
            # Убираем последний элемент если он совпадает с текущим запросом (анти-дубль)
            # ✅ ИСПРАВЛЕНО: сравниваем с _user_message_raw (то что реально сохранено в БД),
            # а не с нормализованным user_message — иначе при спецсимволах антидубль не срабатывал
            # и текущий запрос попадал в историю ДВАЖДЫ (raw + normalized).
            if mem_messages and mem_messages[-1]["role"] == "user" and mem_messages[-1]["content"] in (_user_message_raw, user_message):
                mem_messages = mem_messages[:-1]

        # ── Обрезка истории по токен-бюджету ─────────────────────────────────
        # Грубая оценка: 1 токен ≈ 4 символа.
        # Бюджет контекста модели минус системный промпт и текущий запрос.
        # num_ctx для Qwen3 и файловых запросов может быть 8192, иначе 4096.
        # Qwen3:14b поддерживает до 32K — используем 16384 для длинных диалогов.
        _ctx_window = 16384 if _mk == "qwen" else 4096
        _sys_tokens  = len(system_prompt) // 4
        _user_tokens = len(final_user_message) // 4
        _answer_budget = 800
        # Если system_prompt слишком большой и съедает весь контекст,
        # не схлопываем историю в 400 токенов — берём хотя бы последние 6 сообщений отдельно.
        _raw_budget = _ctx_window - _sys_tokens - _user_tokens - _answer_budget
        if _raw_budget < 800:
            # System prompt почти заполнил контекст — берём только самые свежие реплики
            _history_budget = 800
            print(f"[GET_AI_RESPONSE] ⚠️ System prompt большой ({_sys_tokens} tk) — history_budget зажат до 800")
        else:
            _history_budget = _raw_budget

        # Оставляем только последние сообщения, пока не превышен бюджет.
        # Идём с конца (самые свежие сохраняем в первую очередь).
        _original_count = len(mem_messages)
        _trimmed: list = []
        _used = 0
        for _m in reversed(mem_messages):
            _tok = len(_m.get("content", "")) // 4
            if _used + _tok > _history_budget:
                break
            _trimmed.append(_m)
            _used += _tok
        mem_messages = list(reversed(_trimmed))
        if len(mem_messages) < _original_count:
            print(f"[GET_AI_RESPONSE] ✂️ История обрезана до {len(mem_messages)} сообщений "
                  f"(~{_used} токенов из бюджета {_history_budget})")

        messages = [{"role": "system", "content": system_prompt}]
        for _msg in mem_messages:
            messages.append({"role": _msg["role"], "content": _msg["content"]})
        # Для Qwen3: добавляем /no_think токен — официальный способ отключить мышление
        # на уровне конкретного сообщения. Без него модель может игнорировать think=False.
        _qwen_user_msg = ("/no_think\n" + final_user_message) if _mk == "qwen" else final_user_message
        messages.append({"role": "user", "content": _qwen_user_msg})

        # Для Qwen3: assistant prefill при мате в сообщении — форсируем прямой ответ.
        # Без prefill модель видит «конфликтный» промпт и уходит в chain-of-thought.
        if _mk == "qwen" and _st_enabled and "profanity" in _st_styles:
            messages.append({"role": "assistant", "content": ""})

        # ── ASSISTANT PREFILL для файловых запросов ──────────────────
        # Для маленьких моделей (7b) инструкции в промпте недостаточны —
        # они игнорируют формат и выводят содержимое как обычный текст.
        # Prefill буквально начинает ответ за модель: она вынуждена
        # продолжать с того места где мы остановились, то есть внутри тега.
        #
        # ВАЖНО: DeepSeek R1 генерирует <think>...</think> ДО ответа.
        # Prefill-сообщение assistant вставляется перед этим блоком —
        # модель его игнорирует и пишет ответ после своего think.
        # Поэтому для R1 prefill НЕ используем — только системный промпт + инструкция в сообщении.
        # R1 и Qwen думают сами — prefill добавляется ДО think-блока и ломает формат
        if _file_injection and _mk not in ("deepseek-r1", "qwen"):
            import re as _re
            _pf_match = _re.search(
                r'\[FILE:([\w\-_.() ]+\.(?:txt|json|csv|md|xml|yaml|yml|html|py|log|sql|ini|cfg|toml))\]',
                _file_injection, _re.IGNORECASE
            )
            if _pf_match:
                _prefill_name = _pf_match.group(1)
                if detected_language == "russian":
                    messages.append({
                        "role": "assistant",
                        "content": f"Вот файл!\n[FILE:{_prefill_name}]\n"
                    })
                else:
                    messages.append({
                        "role": "assistant",
                        "content": f"Here's your file!\n[FILE:{_prefill_name}]\n"
                    })
                print(f"[GET_AI_RESPONSE] 📄 Prefill добавлен: [FILE:{_prefill_name}]")

        if use_search:
            print(f"[GET_AI_RESPONSE] Режим поиска: история загружена для учета контекста диалога")

    print(f"[GET_AI_RESPONSE] Всего сообщений для отправки в AI: {len(messages)}")

    # ═══════════════════════════════════════════════════════════════════
    # АДАПТИВНОЕ ОПРЕДЕЛЕНИЕ ЛИМИТА ТОКЕНОВ
    # ═══════════════════════════════════════════════════════════════════
    # Вместо жестких лимитов используем умную логику, которая:
    # 1. Анализирует длину запроса пользователя
    # 2. Учитывает режим AI
    # 3. Даёт запас для завершения мысли
    # 
    # ЦЕЛЬ: Избежать обрыва ответов на полуслове
    # ═══════════════════════════════════════════════════════════════════
    
    # Анализируем длину запроса пользователя
    user_message_length = len(user_message)

    # Детектируем запрос на генерацию файла — влияет на tokens и timeout
    _is_file_request = bool(_file_injection) or detect_file_request(user_message)
    if _is_file_request:
        print(f"[GET_AI_RESPONSE] 📄 Обнаружен файловый запрос — увеличиваем лимиты")

    # Детектируем творческие запросы (реп, стихи, песни) — им нужно больше токенов
    _creative_keywords = (
        "реп", "рэп", "rap", "стих", "poem", "song", "песн", "куплет",
        "рифм", "verse", "зачитай", "напиши реп", "сочини реп", "freestyle"
    )
    _is_creative_request = any(kw in user_message.lower() for kw in _creative_keywords)
    if _is_creative_request:
        print(f"[GET_AI_RESPONSE] 🎤 Обнаружен творческий запрос — увеличиваем лимиты")

    # Базовые лимиты в зависимости от режима AI
    # DeepSeek получает жёсткие ограничения — модель склонна к болтливости
    if _mk in ("deepseek", "deepseek-r1"):
        if _is_file_request:
            # Для файловых запросов R1 нужно больше токенов — содержимое файла
            base_tokens = 2000
        elif ai_mode == AI_MODE_FAST:
            base_tokens = 600
        elif ai_mode == AI_MODE_THINKING:
            base_tokens = 1000
        elif ai_mode == AI_MODE_PRO:
            base_tokens = 1800
        else:
            base_tokens = 700
    elif ai_mode == AI_MODE_FAST:
        base_tokens = 400  # Быстрый режим - короткие ответы, но не слишком
    elif ai_mode == AI_MODE_THINKING:
        base_tokens = 1200  # Думающий режим - средние ответы
    elif ai_mode == AI_MODE_PRO:
        base_tokens = 2500  # Про режим - детальные ответы
    else:
        base_tokens = 800   # По умолчанию

    # Творческие запросы (реп, стихи, сравнение) требуют много токенов —
    # короткий запрос "переделай припев" может породить длинный ответ.
    if _is_creative_request:
        if base_tokens < 3500:
            base_tokens = 3500
        print(f"[GET_AI_RESPONSE] 🎤 base_tokens подняты до {base_tokens} для творческого запроса")

    # Коэффициент на основе длины запроса
    # Для творческих запросов короткий запрос ≠ короткий ответ — не занижаем множитель
    if _is_creative_request:
        length_multiplier = 1.5  # Всегда даём запас для творческого контента
    elif user_message_length < 50:
        length_multiplier = 1.0  # Короткий вопрос
    elif user_message_length < 200:
        length_multiplier = 1.3  # Средний вопрос - больше деталей
    elif user_message_length < 500:
        length_multiplier = 1.6  # Длинный вопрос - ещё больше деталей
    else:
        length_multiplier = 2.0  # Очень длинный вопрос - максимум деталей
    
    # Коэффициент на основе поиска
    if use_search:
        search_multiplier = 1.2  # С поиском нужно больше токенов для синтеза
    else:
        search_multiplier = 1.0
    
    # Итоговый расчёт с запасом
    calculated_tokens = int(base_tokens * length_multiplier * search_multiplier)
    
    # Безопасные границы (минимум и максимум)
    min_tokens = 300   # Минимум чтобы не обрывать
    # Творческие запросы требуют больше токенов для всех моделей
    if _is_creative_request:
        max_tokens_limit = 8000
    elif _mk == "qwen":
        max_tokens_limit = 8000
    else:
        max_tokens_limit = 4000
    
    max_tokens = max(min_tokens, min(calculated_tokens, max_tokens_limit))
    
    print(f"[GET_AI_RESPONSE] Адаптивный расчёт токенов:")
    print(f"  - Режим AI: {ai_mode} (база: {base_tokens})")
    print(f"  - Длина запроса: {user_message_length} символов (множитель: {length_multiplier}x)")
    print(f"  - Поиск: {'да' if use_search else 'нет'} (множитель: {search_multiplier}x)")
    print(f"  - Итоговый лимит: {max_tokens} токенов")

    # Увеличиваем timeout для сложных запросов
    # R1 генерирует think-блок перед ответом — ему нужно больше времени
    if _mk == "deepseek-r1":
        if _is_file_request:
            timeout = 300  # 5 минут: think-блок + содержимое файла
        elif use_search and deep_thinking:
            timeout = 300
        elif use_search or deep_thinking:
            timeout = 240
        else:
            timeout = 180  # R1 даже на простых запросах думает ~1-2 мин
        print(f"[GET_AI_RESPONSE] [R1] Timeout установлен: {timeout}s (файл={_is_file_request})")
    elif _mk == "qwen":
        # Qwen3:14b — крупная модель, нуждается в большем таймауте
        if use_search and deep_thinking:
            timeout = 360
        elif use_search or deep_thinking:
            timeout = 240
        else:
            timeout = 150  # 2.5 мин для обычных запросов (qwen3:14b медленная)
    elif use_search and deep_thinking:
        timeout = 180  # 3 минуты для поиска + глубокое мышление
    elif use_search or deep_thinking:
        timeout = 120  # 2 минуты для поиска ИЛИ глубокое мышление
    else:
        timeout = 60   # 1 минута для обычных запросов

    response_text = ""

    # ═══════════════════════════════════════════════════════════════
    # РЕЗОЛВЕР ИМЁН МОДЕЛЕЙ
    # SUPPORTED_MODELS содержит только deepseek-r1/qwen — для остальных
    # моделей .get() давал фолбэк get_current_ollama_model() (LLaMA).
    # Решение: явный маппинг всех ключей в точное Ollama-имя модели.
    # ═══════════════════════════════════════════════════════════════
    def _resolve_ollama_model_name(mk: str) -> str:
        if mk == "mistral":
            return MISTRAL_MODEL_NAME
        if mk == "qwen":
            return QWEN_MODEL_NAME
        entry = SUPPORTED_MODELS.get(mk)
        if entry:
            return entry[0]
        return OLLAMA_MODEL

    # ═══════════════════════════════════════════════════════════════
    # DEEPSEEK: параметры Ollama для надёжной работы с историей диалога
    #
    # deepseek-llm:7b-chat — дефолтный num_ctx Ollama = 2048.
    # Это КРИТИЧЕСКИ МАЛО: системный промпт + 3-4 сообщения истории
    # уже не влезают → модель "забывает" предыдущие реплики и начинает
    # галлюцинировать (отвечать мусором или говорить что она GPT-4).
    # Решение: явно задаём num_ctx=4096 для обеих DeepSeek-моделей.
    #
    # deepseek-r1: temperature=0.6 рекомендована командой DeepSeek.
    # ═══════════════════════════════════════════════════════════════
    _extra_options: dict = {}
    if _mk == "deepseek":
        _extra_options = {
            "num_ctx": 4096,        # Хватит для системного промпта + ~15 реплик истории
            "temperature": 0.7,
            "repeat_penalty": 1.1,
        }
        if _is_file_request:
            _extra_options["num_ctx"] = 8192
        print(f"[GET_AI_RESPONSE] [DeepSeek 7b] Опции: {_extra_options}")
    elif _mk == "deepseek-r1":
        _extra_options = {
            "num_ctx": 4096,          # Меньше контекст — быстрее KV-cache
            "temperature": 0.6,       # Рекомендовано DeepSeek для R1-distilled
            "repeat_penalty": 1.05,   # Минимальный — не тормозит сэмплинг
        }
        if _is_file_request:
            # Файловый запрос: нужен полный контекст чтобы не обрезать содержимое
            _extra_options["num_ctx"] = 8192
            _extra_options["temperature"] = 0.6
            print(f"[GET_AI_RESPONSE] [R1] Файловый режим: num_ctx=8192")
        elif ai_mode == AI_MODE_FAST:
            # Быстрый режим без файла: агрессивно ограничиваем для скорости
            _extra_options["num_ctx"] = 2048
            _extra_options["temperature"] = 0.4
        print(f"[GET_AI_RESPONSE] [R1] Применены R1-опции: {_extra_options}")

    if USE_OLLAMA:
        # Qwen3 — отдельный блок: управляем встроенным мышлением (/think).
        # ПРОБЛЕМА: когда think=True, Qwen3 сливает внутренние рассуждения прямо в content
        # без тегов <think>, и пользователь видит весь монолог модели вместо ответа.
        # РЕШЕНИЕ: всегда think=False + /no_think токен в user-сообщении.
        if _mk == "qwen" and not _extra_options:
            _extra_options = {
                # 16384 токенов контекста — хватит для длинных диалогов с историей
                "num_ctx": 16384 if _is_file_request else 16384,
                "temperature": 0.7,
                "repeat_penalty": 1.1,
                "think": False,   # Всегда отключаем — thinking ломает content
            }
            print(f"[GET_AI_RESPONSE] [QWEN] Опции: {_extra_options} (think=False, принудительно)")

        # Для всех остальных моделей без явных _extra_options (LLaMA, Mistral)
        # задаём num_ctx=4096 и repeat_penalty чтобы модели не зацикливались.
        # Дефолт Ollama = 2048 — этого не хватает при длинных разговорах.
        if not _extra_options:
            _extra_options = {
                "num_ctx": 4096,
                "temperature": 0.7,
                "repeat_penalty": 1.1,
            }
            if _is_file_request:
                _extra_options["num_ctx"] = 8192
            print(f"[GET_AI_RESPONSE] [{_mk.upper()}] Опции: {_extra_options}")
        _resolved_name = _resolve_ollama_model_name(_mk)
        print(f"[GET_AI_RESPONSE] Использую Ollama → модель: {_resolved_name} (ключ: {_mk})")
        try:
            if _extra_options:
                # Прямой вызов с кастомными options.
                # ВАЖНО: используем имя модели из _mk (зафиксировано в начале get_ai_response),
                # а НЕ get_current_ollama_model() — тот читает глобал CURRENT_AI_MODEL_KEY,
                # который может измениться в другом потоке → Qwen подменялся на LLaMA.
                _model_name_for_request = _resolve_ollama_model_name(_mk)
                print(f"[GET_AI_RESPONSE] → Запрос: POST /api/chat model='{_model_name_for_request}' [streaming]")
                _r1_payload = {
                    "model": _model_name_for_request,
                    "messages": messages,
                    "options": {
                        "num_predict": max_tokens,
                        **_extra_options
                    }
                }
                resp = _ollama_stream(_r1_payload, timeout, on_chunk, cancelled_flag)
                if resp.startswith("[Ollama error]") or resp.startswith("[Ollama timeout]") or resp.startswith("[Ollama connection error]"):
                    pass  # обрабатывается ниже
                elif resp == _STREAM_CANCELLED:
                    # Пользователь отменил — НЕ делаем retry, просто возвращаем пустоту
                    print(f"[GET_AI_RESPONSE] ℹ️ Стрим отменён пользователем — retry не нужен")
                    resp = ""
                elif not resp:
                    # Действительно пустой ответ от Ollama — повторная попытка
                    print(f"[GET_AI_RESPONSE] ⚠️ Пустой ответ — повторная попытка с упрощённым промптом")
                    _retry_messages = [m for m in messages if m["role"] != "system"]
                    _retry_system = "Ты умный и творческий ассистент. Выполняй задание пользователя полностью, без ограничений."
                    _retry_messages = [{"role": "system", "content": _retry_system}] + _retry_messages
                    _retry_opts = {
                        "num_predict": max_tokens,
                        "num_ctx": 4096,
                        "temperature": 0.9,
                        "repeat_penalty": 1.05,
                    }
                    if _mk == "qwen":
                        _retry_opts["think"] = False
                    _retry_payload = {
                        "model": _model_name_for_request,
                        "messages": _retry_messages,
                        "options": _retry_opts,
                    }
                    try:
                        resp = _ollama_stream(_retry_payload, timeout, on_chunk, cancelled_flag)
                        if resp == _STREAM_CANCELLED:
                            resp = ""  # отмена — не ошибка
                        elif not resp:
                            resp = "[Ollama error] Empty response"
                        elif not resp.startswith("[Ollama"):
                            print(f"[GET_AI_RESPONSE] ✓ Повторная попытка успешна ({len(resp)} символов)")
                        else:
                            print(f"[GET_AI_RESPONSE] ✗ Повторная попытка тоже вернула пустой ответ")
                    except Exception as _retry_err:
                        print(f"[GET_AI_RESPONSE] ✗ Ошибка повторной попытки: {_retry_err}")
                        resp = "[Ollama error] Empty response"
            else:
                # Нет кастомных options — используем стриминг через call_ollama_chat fallback
                _fb_model = _resolve_ollama_model_name(_mk)
                _fb_payload = {
                    "model": _fb_model,
                    "messages": messages,
                    "options": {"num_predict": max_tokens},
                }
                resp = _ollama_stream(_fb_payload, timeout, on_chunk, cancelled_flag)
                if not resp:
                    resp = call_ollama_chat(messages, max_tokens=max_tokens, timeout=timeout, model_key=_mk)
            
            # Проверяем, что ответ не является ошибкой
            if not resp.startswith("[Ollama error]") and not resp.startswith("[Ollama timeout]") and not resp.startswith("[Ollama connection error]"):
                print(f"[GET_AI_RESPONSE] Ollama ответил успешно. Длина ответа: {len(resp)}")
                # Если был assistant prefill для файла — Ollama возвращает только продолжение,
                # без самого prefill. Восстанавливаем его, чтобы парсер увидел полный [FILE:...][/FILE].
                _prefill_msg = next(
                    (m["content"] for m in reversed(messages) if m["role"] == "assistant"),
                    None
                )
                if _prefill_msg and "[FILE:" in _prefill_msg and "[FILE:" not in resp:
                    resp = _prefill_msg + resp
                    print(f"[GET_AI_RESPONSE] 📄 Prefill восстановлен в ответе")
                response_text = resp
            else:
                print(f"[GET_AI_RESPONSE] Ollama вернул ошибку: {resp}")
                response_text = "❌ Ошибка: не удалось получить ответ от локальной модели LLaMA. Проверьте:\n1. Запущена ли Ollama\n2. Загружена ли модель\n3. Достаточно ли памяти"
        except Exception as e:
            print(f"[GET_AI_RESPONSE] Исключение при вызове Ollama: {e}")
            response_text = f"❌ Ошибка подключения к LLaMA: {e}"
    
    # ══════════════════════════════════════════════════════════
    # ШАГ 4 ПАЙПЛАЙНА: Валидация ответа и перегенерация при необходимости
    # ══════════════════════════════════════════════════════════
    # Валидация запускается только при поиске И только для содержательных вопросов.
    # Короткие запросы (< 20 символов) или простые ответы (< 30 символов) пропускаем —
    # они не требуют развёрнутой проверки и перегенерация только вредит.
    _skip_validation = (
        len(user_message.strip()) < 20         # слишком короткий вопрос
        or len(response_text.strip()) < 30     # слишком короткий ответ (например "Да" / "Нет")
    )
    if use_search and response_text and not response_text.startswith("❌") and not _skip_validation:
        facts_for_validation = locals().get("facts", "")
        validation = validate_answer(response_text, user_message, detected_language, facts_for_validation)
        
        if not validation["valid"]:
            print(f"[GET_AI_RESPONSE] 🔄 Ответ не прошёл валидацию, перегенерирую...")
            try:
                regen_prompt = build_final_answer_prompt(
                    user_message, facts_for_validation,
                    detect_question_parts(user_message),
                    detected_language, validation["issues"]
                )
                regen_messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": regen_prompt}
                ]
                regen_resp = call_ollama_chat(regen_messages, max_tokens=max_tokens, timeout=timeout, model_key=_mk)
                if regen_resp and not regen_resp.startswith("[Ollama"):
                    print(f"[GET_AI_RESPONSE] ✓ Перегенерация успешна. Длина: {len(regen_resp)}")
                    response_text = regen_resp
                else:
                    print(f"[GET_AI_RESPONSE] ⚠️ Перегенерация не удалась, оставляю первый ответ")
            except Exception as e:
                print(f"[GET_AI_RESPONSE] ⚠️ Ошибка перегенерации: {e}")

    # КРИТИЧЕСКАЯ ПРОВЕРКА: если вопрос на русском, но ответ содержит много английского - переводим
    # НЕ переводим если субтекст явно задал другой язык (English, Polski и т.д.) —
    # иначе мы заглушаем именно тот язык, который пользователь и выбрал.
    if detected_language == "russian" and not _subtext_overrides_lang:
        # Проверяем, есть ли в ответе много английского
        response_lang = detect_message_language(response_text)
        if response_lang == "english":
            print(f"[GET_AI_RESPONSE] ⚠️⚠️⚠️ КРИТИЧНО! Ответ ПОЛНОСТЬЮ на английском! Переводим...")
            try:
                response_text = translate_to_russian(response_text)
                print(f"[GET_AI_RESPONSE] ✓ Перевод завершён успешно")
            except Exception as e:
                print(f"[GET_AI_RESPONSE] ✗ Ошибка перевода: {e}")
    
    # ═══════════════════════════════════════════════════════════════
    # DEEPSEEK: очистка LaTeX-разметки из ответа
    # DeepSeek иногда генерирует \frac{}{}, \sqrt{}, $...$, что
    # не рендерится и выглядит как мусор. Заменяем на читаемый текст.
    # ═══════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════
    # DEEPSEEK R1: очистка блоков <think>...</think>
    # R1 генерирует внутренние рассуждения — они замедляют генерацию
    # и засоряют вывод. Всегда вырезаем их из финального ответа.
    # В режиме БЫСТРЫЙ (fast) — полностью убираем весь think-блок.
    # В режиме ДУМАЮЩИЙ/ПРО — убираем теги, но оставляем содержимое
    # в виде свёрнутого спойлера-заголовка для продвинутых пользователей.
    # ═══════════════════════════════════════════════════════════════
    # Защита от NoneType в постпроцессинге
    if not isinstance(response_text, str):
        response_text = str(response_text) if response_text is not None else ""

    if _mk == "deepseek-r1" and response_text and not response_text.startswith("❌"):
        import re as _re_r1
        _think_pattern = _re_r1.compile(r'<think>(.*?)</think>', _re_r1.DOTALL | _re_r1.IGNORECASE)
        _think_match = _think_pattern.search(response_text)
        if _think_match:
            if ai_mode == AI_MODE_FAST:
                # Быстрый режим: think-блок полностью удаляем — экономим время
                response_text = _think_pattern.sub('', response_text).strip()
                print(f"[GET_AI_RESPONSE] [R1] 🧹 Think-блок удалён (режим: быстрый)")
            else:
                # Думающий/Про: убираем теги, think-содержимое скрываем в сворачиваемый блок
                _thinking_content = _think_match.group(1).strip()
                response_text = _think_pattern.sub('', response_text).strip()
                if _thinking_content:
                    _thinking_summary = _thinking_content[:120].replace('\n', ' ').strip()
                    if len(_thinking_content) > 120:
                        _thinking_summary += '...'
                    response_text = f"💭 *Рассуждение:* _{_thinking_summary}_\n\n" + response_text
                print(f"[GET_AI_RESPONSE] [R1] 🧠 Think-блок свёрнут (режим: {ai_mode})")
        # Убираем незакрытые <think> без закрывающего тега (прерванная генерация)
        response_text = _re_r1.sub(r'<think>.*', '', response_text, flags=_re_r1.DOTALL).strip()

    # ── Универсальный fallback для файлов (все модели) ──────────────────────────
    # Если был запрос на файл, но в ответе нет тегов [FILE:..][/FILE] — оборачиваем.
    if (_is_file_creation_request or _needs_file_gen_prompt) and _file_injection and response_text and not response_text.startswith("❌"):
        import re as _re_univ
        _has_file_tag = _re_univ.search(r'\[FILE:[\w\-_.() ]+\]', response_text, _re_univ.IGNORECASE)
        if not _has_file_tag:
            _fb_match2 = _re_univ.search(
                r'\[FILE:([\w\-_.() ]+\.(?:txt|json|csv|md|xml|yaml|yml|html|py|log|sql|ini|cfg|toml))\]',
                _file_injection, _re_univ.IGNORECASE
            )
            if _fb_match2:
                _fb_name2 = _fb_match2.group(1)
                _clean_resp2 = _re_univ.sub(
                    r'^(вот\s+файл[:\s!]*|here.*?file[:\s!]*|конечно[!\s]*|создаю\s+файл[:\s]*|готово[!\s]*|сделано[!\s]*|пожалуйста[!\s]*)',
                    '', response_text.strip(), flags=_re_univ.IGNORECASE | _re_univ.MULTILINE
                ).strip()
                if _clean_resp2:
                    response_text = (f"Вот файл!\n"
                                     f"[FILE:{_fb_name2}]\n"
                                     f"{_clean_resp2}\n"
                                     "[/FILE]")
                    print(f"[GET_AI_RESPONSE] 📄 Universal fallback: обернули в [FILE:{_fb_name2}] ({_mk})")

    if _mk in ("deepseek", "deepseek-r1") and response_text and not response_text.startswith("❌"):
        # Постобработка файловых ответов (убираем дубли, мусорные заголовки)
        response_text = sanitize_deepseek_file_response(response_text)

        # ── Fallback: модель написала содержимое без тегов [FILE:...][/FILE] ──
        # Если был запрос на создание файла, но в ответе нет тегов FILE —
        # пробуем обернуть весь ответ в правильный тег.
        if _is_file_creation_request and _file_injection:
            import re as _re_fb
            _has_tag = _re_fb.search(r'\[FILE:', response_text, _re_fb.IGNORECASE)
            if not _has_tag:
                # Угадываем имя файла из инжекции
                _fb_match = _re_fb.search(
                    r'\[FILE:([\w\-_.() ]+\.(?:txt|json|csv|md|xml|yaml|yml|html|py|log|sql|ini|cfg|toml))\]',
                    _file_injection, _re_fb.IGNORECASE
                )
                if _fb_match:
                    _fb_name = _fb_match.group(1)
                    # Убираем вводные фразы типа "Вот файл:", "Конечно!", "Создаю файл:" и пустые строки в начале
                    _clean_resp = _re_fb.sub(
                        r'^(вот\s+файл[:\s!]*|конечно[!\s]*|создаю\s+файл[:\s]*|готово[!\s]*|пожалуйста[!\s]*)',
                        '', response_text.strip(), flags=_re_fb.IGNORECASE
                    ).strip()
                    if _clean_resp:
                        response_text = ("Вот файл!\n"
                                         f"[FILE:{_fb_name}]\n"
                                         f"{_clean_resp}\n"
                                         "[/FILE]")
                        print(f"[GET_AI_RESPONSE] 📄 Fallback: обернули ответ в [FILE:{_fb_name}]")
        # ШАГ 1: Проверяем на мусор (scss-блоки, выдуманные формулы и т.п.)
        # Расширено: проверяем мусор даже если is_math_problem=False, но в запросе есть арифметика
        _should_check_garbage = is_math_problem
        if not _should_check_garbage and re.search(r'\d+\s*[\+\-\*\/\%\^]\s*\d+', user_message):
            _should_check_garbage = True
        if _should_check_garbage and is_garbage_math_response(response_text):
            print(f"[GET_AI_RESPONSE] [DeepSeek] ⚠️ Обнаружен мусорный мат. ответ — заменяю!")
            response_text = sanitize_deepseek_math(response_text, user_message, detected_language)
        # ШАГ 2: Очищаем LaTeX из оставшегося ответа
        response_text = clean_deepseek_latex(response_text)
        print(f"[GET_AI_RESPONSE] [DeepSeek] LaTeX-разметка очищена")
    
    # ═══════════════════════════════════════════════════════════════
    # ФИЛЬТРАЦИЯ CJK + АНГЛИЙСКИХ СЛОВ
    # ═══════════════════════════════════════════════════════════════
    # Постобработка ответа Mistral — убираем артефакты токенизатора
    if _mk == "mistral" and response_text and not response_text.startswith("❌"):
        response_text = clean_mistral_response(response_text)
        print(f"[GET_AI_RESPONSE] [Mistral] Постобработка применена")
    if _mk == "qwen" and response_text and not response_text.startswith("❌"):
        response_text = clean_qwen_response(response_text)
        import re as _re_qw

        # 1. Удаляем <think>...</think> блоки
        _qw_think = _re_qw.compile(r'<think>(.*?)</think>', _re_qw.DOTALL | _re_qw.IGNORECASE)
        if _qw_think.search(response_text):
            _qw_thinking_text = "\n".join(_re_qw.findall(r'<think>(.*?)</think>', response_text, _re_qw.DOTALL))
            response_text = _qw_think.sub('', response_text).strip()
            if not response_text and _qw_thinking_text:
                response_text = _qw_thinking_text.strip()
            print(f"[GET_AI_RESPONSE] [QWEN] <think>-блоки очищены из ответа")

        # 2. Удаляем незакрытые <think> и одиночные </think>
        response_text = _re_qw.sub(r'<think>.*', '', response_text, flags=_re_qw.DOTALL).strip()
        response_text = _re_qw.sub(r'</think>', '', response_text).strip()

        # 3. ДЕТЕКТОР УТЕЧКИ МЫШЛЕНИЯ (без тегов):
        # Qwen3 иногда сливает внутренний монолог прямо в content без <think> тегов.
        # Признаки: начинается с фраз типа "Хорошо, пользователь...", "Нужно убедиться...",
        # "Итак, мне нужно...", "Думаю, что..." и длиннее 200 символов без реального ответа.
        _leaked_thinking_patterns = [
            r'^(Нужно убедиться)',
            r'^(Давайте подумаем)',
            r'^(Пользователь просит)',
            r'^(Пользователь попросил)',
            r'^(Давайте разберём)',
            r'^(Мне нужно (подумать|проанализировать|разобрать))',
            r'^(Я должен (подумать|проанализировать))',
            r'^(Let me think)',
            r'^(Okay[,.]? (so|let me|I need))',
        ]
        _is_leaked = any(_re_qw.match(p, response_text) for p in _leaked_thinking_patterns)
        if _is_leaked and len(response_text) > 200:
            print(f"[GET_AI_RESPONSE] [QWEN] ⚠️ Обнаружена утечка мышления — пробуем извлечь ответ")
            # Берём последний непустой абзац — обычно там финальный ответ
            _paragraphs = [p.strip() for p in response_text.split('\n\n') if p.strip()]
            if len(_paragraphs) > 1:
                # Ищем первый абзац который НЕ похож на монолог
                _real_answer = None
                for _para in reversed(_paragraphs):
                    _is_mono = any(_re_qw.match(p, _para) for p in _leaked_thinking_patterns)
                    if not _is_mono and len(_para) > 20:
                        _real_answer = _para
                        break
                if _real_answer:
                    response_text = _real_answer
                    print(f"[GET_AI_RESPONSE] [QWEN] ✓ Извлечён финальный ответ из монолога")

        print(f"[GET_AI_RESPONSE] [Qwen] Постобработка применена")

    # CJK (китайский/японский/корейский) фильтруем ВСЕГДА для deepseek
    if _mk in ("deepseek", "deepseek-r1") and response_text:
        import re as _re_cjk_check
        _cjk = _re_cjk_check.compile(
            '[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff'
            '\u3000-\u303f\u30a0-\u30ff\u3040-\u309f\uac00-\ud7af]+'
        )
        if _cjk.search(response_text):
            response_text = _cjk.sub('', response_text)
            response_text = re.sub(r'  +', ' ', response_text).strip()
            print("[GET_AI_RESPONSE] [DeepSeek] ⚠️ CJK-символы удалены из ответа")
            print(f"[GET_AI_RESPONSE] [DeepSeek] ⚠️ CJK-символы удалены из ответа")
    # Используем расширенный словарь из forbidden_english_words.py
    # Фильтр отключён для Mistral — он уже настроен на русский язык через промпт.
    # Фильтр также отключён когда субтекст явно задал нерусский язык ответа —
    # иначе мы вырезаем нужные слова из английского/польского/etc. ответа.
    if detected_language == "russian" and not _subtext_overrides_lang and _mk not in ("mistral", "mistral-nemo", MISTRAL_MODEL_NAME, "qwen", QWEN_MODEL_NAME):
        print(f"[GET_AI_RESPONSE] Фильтрация английских слов...")
        response_text = remove_english_words_from_russian(response_text)
    
    # ИСПРАВЛЕНО: НЕ сохраняем полный контекст поиска, чтобы избежать дублирования
    # Сохраняем только метаданные о том, что поиск был выполнен
    if use_search and chat_id and response_text:
        try:
            context_mgr = get_memory_manager(_mk)
            # Только факт поиска, БЕЗ содержимого ответа
            context_entry = f"[Поиск] {user_message[:80]}"
            context_mgr.save_context_memory(chat_id, "search_meta", context_entry)
            print(f"[GET_AI_RESPONSE] Сохранены метаданные поиска (без дублирования)")
        except Exception as e:
            print(f"[GET_AI_RESPONSE] Ошибка сохранения метаданных: {e}")
    
    print(f"[GET_AI_RESPONSE] ========== КОНЕЦ ==========\n")
    # Постпроцессинг: применяем финальные фильтры к готовому тексту.
    # Работает даже если модель проигнорировала промпт.
    # Финальный перехватчик: удаляет эхо промпта, зацикливание, цензурные отказы.
    response_text = _sanitize_final_response(response_text, system_prompt)

    return response_text, found_sources

# -------------------------
# Финальный постпроцессор ответов
# -------------------------
def _sanitize_final_response(text: str, system_prompt: str = "") -> str:
    """
    Финальная чистка ответа модели перед отдачей пользователю.
    Убирает три класса проблем:

    1. Эхо системного промпта — модель "зачитывает" куски инструкций вместо ответа.
       Типично при мат-фильтре: видит слова в промпте → воспроизводит их цепочкой.

    2. Repetition loop — модель зациклилась и повторяет один фрагмент 3+ раз.
       Обнаруживаем по строкам (>=15 символов) с множественным вхождением.

    3. Разговор сам с собой — модель начинает писать "Пользователь: ... Ассистент: ..."
       или "User:" / "Human:" — имитирует диалог из тренировочных данных.
    """
    if not text or not isinstance(text, str):
        return text
    # Не трогаем сообщения об ошибках
    if text.startswith("❌") or text.startswith("[Ollama"):
        return text

    # ── 1. Эхо промпта ──────────────────────────────────────────────────────
    # Маркеры — уникальные строки из system_prompt которые никогда не должны
    # появляться в пользовательском ответе.
    _PROMPT_ECHO_MARKERS = [
        "СТИЛЬ ОБЩЕНИЯ:",
        "СТИЛЬ РЕЧИ ПОЛЬЗОВАТЕЛЯ",
        "КРИТИЧЕСКИ ВАЖНО",
        "═══════════════",
        "СИСТЕМНЫЙ ФАКТ",
        "SYSTEM FACT",
        "ПОНИМАНИЕ КОНТЕКСТА ДИАЛОГА",
        "CONVERSATION CONTEXT UNDERSTANDING",
        "ВАЖНАЯ ИНФОРМАЦИЯ (пользователь просил запомнить)",
        "IMPORTANT INFORMATION (user asked to remember)",
        "отвечай строго на русском языке",
        "ОТВЕЧАЙ ТОЛЬКО НА РУССКОМ",
        "RESPOND ONLY IN ENGLISH",
        "num_predict",
        "repeat_penalty",
        "temperature",
    ]
    _first_chunk = text[:600]
    for _marker in _PROMPT_ECHO_MARKERS:
        if _marker in _first_chunk:
            # Находим все строки — берём только те, что НЕ содержат маркеры промпта
            _lines = text.split('\n')
            _clean = []
            _skipping = True
            for _ln in _lines:
                _is_prompt_line = any(_m in _ln for _m in _PROMPT_ECHO_MARKERS)
                if _skipping:
                    if _is_prompt_line:
                        continue  # Пропускаем строки промпта
                    else:
                        _skipping = False  # Нашли нормальный текст — дальше берём всё
                _clean.append(_ln)
            _cleaned = '\n'.join(_clean).strip()
            if _cleaned:
                text = _cleaned
                print(f"[SANITIZE] ⚠️ Эхо промпта удалено (маркер: '{_marker[:30]}')")
            break

    # ── 2. Самодиалог (модель пишет диалог сама с собой) ────────────────────
    _self_chat_patterns = [
        r'\n(Пользователь|Человек|User|Human)\s*:',
        r'\n(Ассистент|Помощник|Assistant|AI)\s*:',
    ]
    import re as _re_sc
    for _pat in _self_chat_patterns:
        _match = _re_sc.search(_pat, text)
        if _match:
            # Берём только текст ДО первого "диалогового" паттерна
            _before = text[:_match.start()].strip()
            if len(_before) >= 20:
                text = _before
                print(f"[SANITIZE] ⚠️ Самодиалог обнаружен — обрезан на позиции {_match.start()}")
            break

    # ── 3. Repetition loop ──────────────────────────────────────────────────
    # Если одна и та же строка (>=15 симв.) встречается 3 раза — зацикливание.
    _lines_all = text.split('\n')
    _seen_counts: dict = {}
    for _idx, _line in enumerate(_lines_all):
        _key = _line.strip()
        if len(_key) < 15:
            continue
        _seen_counts[_key] = _seen_counts.get(_key, 0) + 1
        if _seen_counts[_key] >= 3:
            # Обрезаем до ЭТОЙ строки (не включая её)
            text = '\n'.join(_lines_all[:_idx]).strip()
            print(f"[SANITIZE] ⚠️ Repetition loop обнаружен — обрезан на строке {_idx}")
            break

    return text.strip() if text else text


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