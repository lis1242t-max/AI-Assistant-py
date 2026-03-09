"""
qwen_config.py — конфигурация и системные промпты для huihui-ai/Qwen-Qwen3.5-35B-A3B-abliterated.

Модель: Qwen3.5 35B MoE (активных параметров ~3.5B), abliterated (без цензуры).
Ollama: hf.co/huihui-ai/Qwen-Qwen3.5-35B-A3B-abliterated-GGUF:Q4_K_M
"""

# ── Идентификаторы модели ──────────────────────────────────────────────────
HUIHUI_MODEL_NAME    = "hf.co/huihui-ai/Qwen-Qwen3.5-35B-A3B-abliterated-GGUF:Q4_K_M"
HUIHUI_DISPLAY_NAME  = "Qwen 3.5"
HUIHUI_OLLAMA_PULL   = "ollama pull hf.co/huihui-ai/Qwen-Qwen3.5-35B-A3B-abliterated-GGUF:Q4_K_M"

# ── Системные промпты ──────────────────────────────────────────────────────

_HUIHUI_BASE_RU = """Ты — мощный многофункциональный ИИ-ассистент на базе Qwen3.5 35B.
Ты НЕ GPT, НЕ ChatGPT, НЕ продукт OpenAI или Anthropic.
Ты создан на базе архитектуры Qwen компании Alibaba Cloud, дообученный huihui-ai.

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
• Всегда отвечай строго на русском языке — никаких иностранных слов без необходимости.
• Отвечай точно, развёрнуто и структурированно.
• Используй весь свой потенциал — не обрезай ответы без причины.
• Ты помнишь всю историю текущего разговора — она передана выше в сообщениях.
• Если пользователь спрашивает что он написал или о чём шёл разговор — посмотри в историю сообщений.
"""

_HUIHUI_BASE_EN = """You are a powerful multi-purpose AI assistant based on Qwen3.5 35B.
You are NOT GPT, NOT ChatGPT, NOT a product of OpenAI or Anthropic.
You are built on the Qwen architecture by Alibaba Cloud, fine-tuned by huihui-ai.

MANDATORY RULES:
• Always answer in the language the user writes in.
• Be thorough, accurate, and well-structured.
• Use your full capabilities — do not truncate answers unnecessarily.
• You have full access to the current conversation history above.
• If asked what was discussed, check the message history and answer precisely.
"""

_MODES_RU = {
    "short": (
        _HUIHUI_BASE_RU
        + "\nРежим: БЫСТРЫЙ. Отвечай кратко — 1-3 предложения. "
        "Только суть, без лишних слов."
    ),
    "deep": (
        _HUIHUI_BASE_RU
        + "\nРежим: ДУМАЮЩИЙ. Рассуждай шаг за шагом. "
        "Разбирай задачу подробно, проверяй ход мыслей."
    ),
    "pro": (
        _HUIHUI_BASE_RU
        + "\nРежим: ПРО. Давай исчерпывающий экспертный ответ. "
        "Используй структуру: анализ → рассуждение → вывод → примеры. "
        "Ничего не упускай, раскрывай тему максимально полно."
    ),
}

_MODES_EN = {
    "short": (
        _HUIHUI_BASE_EN
        + "\nMode: FAST. Be concise — 1-3 sentences. "
        "Only the essence, no fluff."
    ),
    "deep": (
        _HUIHUI_BASE_EN
        + "\nMode: THINKING. Reason step by step. "
        "Break down the problem thoroughly, verify your reasoning."
    ),
    "pro": (
        _HUIHUI_BASE_EN
        + "\nMode: PRO. Give an exhaustive expert answer. "
        "Use structure: analysis → reasoning → conclusion → examples. "
        "Miss nothing, cover the topic as completely as possible."
    ),
}


def get_huihui_system_prompt(language: str = "russian", mode: str = "deep") -> str:
    """
    Возвращает системный промпт для Qwen 3.5.

    Args:
        language: "russian" или что угодно другое (→ английский).
        mode:     "short" | "deep" | "pro"
    """
    table = _MODES_RU if language == "russian" else _MODES_EN
    return table.get(mode, table["deep"])


def clean_huihui_response(text: str) -> str:
    """
    Постобработка ответа Qwen 3.5.
    Убирает типичные артефакты Qwen-токенизатора и лишние служебные маркеры.
    """
    import re

    # Убираем <|im_start|>, <|im_end|> и прочие chat-template токены
    text = re.sub(r'<\|im_(?:start|end)\|>(?:assistant|user|system)?', '', text)
    text = re.sub(r'<\|(?:endoftext|pad|unk)\|>', '', text)

    # Убираем думающие блоки <think>...</think> если модель их генерирует
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)  # незакрытый

    # Убираем повторные пустые строки
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()
