# ═══════════════════════════════════════════════════════════════════════
# vision_handler.py — модуль для работы с LLaMA 3.2 Vision
#
# Содержит:
#   • Конфигурацию vision-модели
#   • call_ollama_vision()   — низкоуровневый вызов Ollama API с изображением
#   • build_vision_prompt()  — построение промпта по режиму и тексту запроса
#   • process_image_file()   — высокоуровневый обработчик: промпт → анализ → результат
#
# Используется из run.py:
#   from vision_handler import (
#       OLLAMA_VISION_MODEL,
#       call_ollama_vision,
#       process_image_file,
#   )
# ═══════════════════════════════════════════════════════════════════════

import os
import base64
import json
import traceback

import requests

# ── Конфигурация ────────────────────────────────────────────────────────
OLLAMA_VISION_MODEL: str = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision")
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

# Расширения файлов, которые считаются изображениями
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

# Режимы работы (дублируем из run.py, чтобы модуль был независимым)
_MODE_FAST     = "быстрый"
_MODE_THINKING = "думающий"
_MODE_PRO      = "про"


# ═══════════════════════════════════════════════════════════════════════
# Низкоуровневый вызов Ollama Vision API
# ═══════════════════════════════════════════════════════════════════════

def call_ollama_vision(image_path: str, prompt: str,
                       max_tokens: int = 800, timeout: int = 120,
                       temperature: float = 0.7) -> str:
    """
    Отправляет изображение и промпт в Ollama vision-модель,
    возвращает текстовый ответ.

    После успешного ответа автоматически выгружает модель из RAM
    (keep_alive=0), чтобы она не занимала память между запросами.

    Возвращает строку — либо ответ модели, либо сообщение об ошибке
    (начинающееся с «❌»).
    """
    r = None  # нужно для обработки JSONDecodeError в except
    try:
        # Нормализуем путь (убираем лишние ../  и пробелы)
        image_path = os.path.normpath(os.path.abspath(image_path))

        print("[VISION] ========== НАЧАЛО АНАЛИЗА ==========")
        print(f"[VISION] Изображение : {image_path}")
        print(f"[VISION] Модель      : {OLLAMA_VISION_MODEL}")
        print(f"[VISION] Промпт      : {prompt[:120]}...")
        print(f"[VISION] Max tokens  : {max_tokens}")

        # ── Проверка файла ──────────────────────────────────────────
        if not os.path.exists(image_path):
            return f"❌ Файл изображения не найден: {image_path}"
        if not os.path.isfile(image_path):
            return f"❌ Путь не является файлом: {image_path}"

        # ── Кодирование в base64 ────────────────────────────────────
        with open(image_path, "rb") as img_file:
            image_bytes = img_file.read()
        image_data = base64.b64encode(image_bytes).decode("utf-8")
        print(f"[VISION] Размер файла: {len(image_bytes) / 1024:.1f} KB")

        # ── Запрос к Ollama ─────────────────────────────────────────
        payload = {
            "model": OLLAMA_VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_data],
                }
            ],
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        url = f"{OLLAMA_HOST}/api/chat"
        print(f"[VISION] Отправка запроса → {url}")
        print(f"[VISION] Ожидание ответа (таймаут: {timeout}s)...")

        r = requests.post(url, headers={"Content-Type": "application/json"},
                          json=payload, timeout=timeout)

        print(f"[VISION] HTTP статус: {r.status_code}")

        if r.status_code != 200:
            print(f"[VISION] ❌ Ошибка HTTP: {r.text[:500]}")
            r.raise_for_status()

        j = r.json()

        # ── Разбор ответа ───────────────────────────────────────────
        if "message" in j and "content" in j["message"]:
            response = j["message"]["content"].strip()
            print(f"[VISION] ✅ Ответ получен (message.content), {len(response)} символов")
        elif "response" in j:
            response = j["response"].strip()
            print(f"[VISION] ✅ Ответ получен (response), {len(response)} символов")
        else:
            print(f"[VISION] ⚠️ Неожиданный формат: {json.dumps(j)[:500]}")
            return "[Ошибка] Неожиданный формат ответа от модели. Проверьте консоль."

        # ── Выгрузка модели из RAM ──────────────────────────────────
        # keep_alive=0 говорит Ollama немедленно освободить память.
        # Модель загружается только когда нужна — остальное время
        # не занимает RAM.
        try:
            requests.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": OLLAMA_VISION_MODEL, "keep_alive": 0},
                timeout=10,
            )
            print(f"[VISION] ✓ Модель {OLLAMA_VISION_MODEL} выгружена из RAM")
        except Exception as unload_err:
            print(f"[VISION] ⚠️ Не удалось выгрузить модель: {unload_err}")

        return response

    # ── Обработка ошибок ────────────────────────────────────────────
    except FileNotFoundError:
        msg = f"❌ Файл изображения не найден: {image_path}"
        print(f"[VISION] {msg}")
        return msg

    except requests.exceptions.Timeout:
        msg = (f"❌ Превышен таймаут ({timeout}s). "
               f"Модель {OLLAMA_VISION_MODEL} может быть не загружена.")
        print(f"[VISION] {msg}")
        return msg

    except requests.exceptions.ConnectionError:
        msg = (f"❌ Не удалось подключиться к Ollama на {OLLAMA_HOST}.\n"
               "Убедитесь что Ollama запущена: ollama serve")
        print(f"[VISION] {msg}")
        return msg

    except requests.exceptions.HTTPError as e:
        print(f"[VISION] ❌ HTTP ошибка: {e}")
        server_text = e.response.text if hasattr(e, "response") else ""
        print(f"[VISION] Ответ сервера: {server_text[:300]}")

        if "404" in str(e) or "not found" in str(e).lower():
            msg = (f"❌ Модель '{OLLAMA_VISION_MODEL}' не найдена.\n\n"
                   f"Установите командой:\n"
                   f"  ollama pull {OLLAMA_VISION_MODEL}\n\n"
                   f"Доступные vision-модели:\n"
                   f"  • llama3.2-vision (рекомендуется)\n"
                   f"  • llava\n"
                   f"  • bakllava\n\n"
                   f"Проверить установленные: ollama list")
        else:
            status = e.response.status_code if hasattr(e, "response") else "?"
            msg = f"❌ HTTP ошибка {status}: {server_text[:200]}"
        print(f"[VISION] {msg}")
        return msg

    except json.JSONDecodeError as e:
        raw = r.text[:500] if r is not None else "нет ответа"
        msg = f"❌ Ошибка парсинга JSON: {e}\nСырой ответ: {raw}"
        print(f"[VISION] {msg}")
        return msg

    except Exception as e:
        msg = f"❌ Неожиданная ошибка: {type(e).__name__}: {e}"
        print(f"[VISION] {msg}")
        traceback.print_exc()
        return msg

    finally:
        print("[VISION] ========== КОНЕЦ АНАЛИЗА ==========\n")


# ═══════════════════════════════════════════════════════════════════════
# Построение промпта
# ═══════════════════════════════════════════════════════════════════════

# Ключевые слова для определения типа запроса
_KW_TEXT = [
    "текст", "text", "надпись", "надписи", "прочитай", "read",
    "перепиши", "transcribe", "распознай", "ocr",
    "что написано", "что написанно", "what does it say", "what's written",
]
_KW_MATH = [
    "реши", "solve", "посчитай", "calculate", "вычисли", "найди",
    "ответ", "answer", "задача", "task", "задание", "math",
    "уравнение", "equation", "докажи", "prove", "упрости", "simplify",
    "пример", "сколько", "how many", "how much", "find",
]
_KW_DESCRIBE = [
    "опиши", "describe", "что на фото", "что на изображении",
    "what is", "what's in", "что это", "analyse", "анализ",
]


def is_math_request(user_message: str) -> bool:
    """Возвращает True если запрос пользователя — математический."""
    msg = user_message.lower()
    return any(kw in msg for kw in _KW_MATH)


def build_vision_prompt(file_name: str, user_message: str,
                        ai_mode: str, language: str) -> str:
    """
    Строит промпт для vision-модели с учётом намерения пользователя.

    Приоритеты:
      1. Чтение текста (OCR)  → дословная транскрипция
      2. Математика / задача  → двухэтапный промпт: сначала читаем, потом решаем
      3. Конкретный вопрос    → вопрос передаётся напрямую
      4. Описание/анализ      → промпт по режиму (fast / thinking / pro)
    """
    msg = user_message.lower().strip()
    _ru = (language == "russian")
    lang_hint = "Отвечай на русском языке." if _ru else "Answer in English."

    # ── 1. OCR: читаем текст ─────────────────────────────────────────
    if any(kw in msg for kw in _KW_TEXT):
        if _ru:
            return (
                f"Внимательно изучи изображение '{file_name}' и выпиши "
                f"ВЕСЬ видимый текст дословно, включая цифры, формулы, условия задач. "
                f"Ничего не пропускай и не интерпретируй — только то, что написано. "
                f"{lang_hint}"
            )
        return (
            f"Carefully examine the image '{file_name}' and transcribe "
            f"ALL visible text verbatim, including numbers, formulas, problem statements. "
            f"Do not skip or interpret anything — only what is written. "
            f"{lang_hint}"
        )

    # ── 2. Математика / задача ───────────────────────────────────────
    if any(kw in msg for kw in _KW_MATH):
        if _ru:
            return (
                f"Ты смотришь на изображение '{file_name}' с математической задачей или примером.\n\n"
                f"ШАГ 1 — ПРОЧИТАЙ ЗАДАЧУ:\n"
                f"Внимательно прочитай и перепиши ДОСЛОВНО всё условие, все числа, "
                f"все символы и формулы точно так, как написано на изображении. "
                f"Не додумывай и не меняй числа — переписывай только то, что видишь.\n\n"
                f"ШАГ 2 — РЕШИ:\n"
                f"Используя ТОЛЬКО то, что ты прочитал на шаге 1, реши задачу пошагово. "
                f"Покажи все промежуточные вычисления. Дай чёткий ответ.\n\n"
                f"ВАЖНО: если что-то плохо видно — напиши об этом явно, не угадывай.\n"
                f"{lang_hint}"
            )
        return (
            f"You are looking at image '{file_name}' containing a math problem or expression.\n\n"
            f"STEP 1 — READ THE PROBLEM:\n"
            f"Carefully read and transcribe VERBATIM all conditions, numbers, symbols "
            f"and formulas exactly as written in the image. Do not guess or alter numbers — "
            f"copy only what you see.\n\n"
            f"STEP 2 — SOLVE:\n"
            f"Using ONLY what you read in step 1, solve the problem step by step. "
            f"Show all intermediate calculations. Give a clear final answer.\n\n"
            f"IMPORTANT: if anything is unclear or hard to read, state that explicitly — do not guess.\n"
            f"{lang_hint}"
        )

    # ── 3. Конкретный вопрос пользователя ───────────────────────────
    user_message_stripped = user_message.strip()
    if user_message_stripped and not any(kw in msg for kw in _KW_DESCRIBE):
        return (
            f"{user_message_stripped}\n\n"
            f"(Это вопрос об изображении '{file_name}'.) {lang_hint}"
        )

    # ── 4. Описание по режиму (по умолчанию) ────────────────────────
    if ai_mode == _MODE_FAST:
        if _ru:
            return f"Кратко опиши что на изображении '{file_name}'. {lang_hint}"
        return f"Briefly describe what's in the image '{file_name}'. {lang_hint}"

    if ai_mode == _MODE_THINKING:
        if _ru:
            return (
                f"Подробно проанализируй изображение '{file_name}'. "
                f"Опиши все важные детали, объекты, текст (если есть), цвета, композицию. "
                f"{lang_hint}"
            )
        return (
            f"Analyze the image '{file_name}' in detail. "
            f"Describe all important details, objects, text (if any), colors, composition. "
            f"{lang_hint}"
        )

    # PRO
    if _ru:
        return (
            f"Максимально детальный анализ изображения '{file_name}':\n"
            f"1. Основной объект/сцена\n"
            f"2. Все видимые объекты и их расположение\n"
            f"3. Текст на изображении (если есть) — перепиши дословно\n"
            f"4. Цветовая схема и освещение\n"
            f"5. Контекст и возможное назначение\n"
            f"6. Любые необычные или важные детали\n"
            f"{lang_hint}"
        )
    return (
        f"Maximum detailed analysis of image '{file_name}':\n"
        f"1. Main object/scene\n"
        f"2. All visible objects and their location\n"
        f"3. Text in the image (if any) — transcribe verbatim\n"
        f"4. Color scheme and lighting\n"
        f"5. Context and possible purpose\n"
        f"6. Any unusual or important details\n"
        f"{lang_hint}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Высокоуровневый обработчик изображения
# ═══════════════════════════════════════════════════════════════════════

def process_image_file(file_path: str, file_name: str,
                       user_message: str, ai_mode: str,
                       language: str) -> dict:
    """
    Полный цикл обработки изображения: строит промпт → вызывает vision API
    → возвращает результат.

    Returns:
        dict: {"success": bool, "content": str}
    """
    print(f"[VISION] 🖼️  Обработка изображения: {file_name}")
    print(f"[VISION] 🤖  Модель: {OLLAMA_VISION_MODEL}")

    # Для математики: больше токенов + низкая температура (меньше галлюцинаций)
    _is_math = is_math_request(user_message)
    if _is_math:
        max_tokens  = 2000
        temperature = 0.1   # детерминированный режим для точных вычислений
        print("[VISION] 🔢  Режим: математическая задача (temperature=0.1)")
    elif ai_mode == _MODE_PRO:
        max_tokens  = 1500
        temperature = 0.5
    else:
        max_tokens  = 800
        temperature = 0.7

    vision_prompt = build_vision_prompt(file_name, user_message, ai_mode, language)
    print(f"[VISION] 📝  Промпт: {vision_prompt[:200]}...")

    vision_response = call_ollama_vision(
        file_path, vision_prompt,
        max_tokens=max_tokens,
        timeout=180 if _is_math else 120,
        temperature=temperature,
    )

    # Определяем, ошибка это или нет
    _error_markers = ("❌", "[Ошибка", "[VISION", "не найден", "not found",
                      "connection", "timeout")
    is_error = any(m in vision_response for m in _error_markers)

    if not is_error:
        print(f"[VISION] ✅ Анализ успешен для '{file_name}'")
        return {"success": True, "content": vision_response}

    print(f"[VISION] ❌ Ошибка анализа '{file_name}': {vision_response[:200]}")
    if language == "russian":
        error_msg = (
            f"🔴 Не удалось обработать изображение '{file_name}'\n\n"
            f"{vision_response}\n\n"
            f"Возможные решения:\n"
            f"1. Убедитесь что Ollama запущена: ollama serve\n"
            f"2. Проверьте что модель установлена: ollama pull {OLLAMA_VISION_MODEL}\n"
            f"3. Попробуйте прикрепить файл снова"
        )
    else:
        error_msg = (
            f"🔴 Failed to process image '{file_name}'\n\n"
            f"{vision_response}\n\n"
            f"Possible solutions:\n"
            f"1. Make sure Ollama is running: ollama serve\n"
            f"2. Check that model is installed: ollama pull {OLLAMA_VISION_MODEL}\n"
            f"3. Try attaching the file again"
        )
    return {"success": False, "content": error_msg}



def is_image_file(file_path: str) -> bool:
    """Возвращает True если расширение файла является изображением."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in IMAGE_EXTENSIONS