"""
tts_engine.py — Движок озвучки текста для чат-приложения.

Возможности:
  - Автоопределение языка каждого сегмента текста (русский / другой)
  - Озвучка смешанного текста: каждый сегмент своим голосом
  - Нормализация текста: числа → слова, markdown → чистый текст,
    формулы → читаемая речь
  - Поддержка macOS (say), Linux (espeak-ng), Windows (pyttsx3/SAPI)
  - Стоп в любой момент

Использование:
    from tts_engine import TTSEngine
    engine = TTSEngine()
    engine.speak(text, on_done=lambda: ...)
    engine.stop()
"""

import re
import sys
import threading
import subprocess
from typing import Callable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Числа → слова (Russian)
# ─────────────────────────────────────────────────────────────────────────────

_ONES_M  = ['', 'один', 'два', 'три', 'четыре', 'пять',
             'шесть', 'семь', 'восемь', 'девять']
_ONES_F  = ['', 'одна', 'две', 'три', 'четыре', 'пять',
             'шесть', 'семь', 'восемь', 'девять']
_TEENS   = ['десять', 'одиннадцать', 'двенадцать', 'тринадцать',
             'четырнадцать', 'пятнадцать', 'шестнадцать', 'семнадцать',
             'восемнадцать', 'девятнадцать']
_TENS    = ['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят',
            'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто']
_HUNDREDS = ['', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот',
              'шестьсот', 'семьсот', 'восемьсот', 'девятьсот']
_DIGIT_RU = {'0':'ноль','1':'один','2':'два','3':'три','4':'четыре',
              '5':'пять','6':'шесть','7':'семь','8':'восемь','9':'девять'}


def _chunk3(n: int, feminine: bool = False) -> str:
    res = []
    h = n // 100
    if h:
        res.append(_HUNDREDS[h])
    t = (n % 100) // 10
    o = n % 10
    if t == 1:
        res.append(_TEENS[o])
    else:
        if t:
            res.append(_TENS[t])
        if o:
            res.append((_ONES_F if feminine else _ONES_M)[o])
    return ' '.join(res)


def int_to_ru(n: int) -> str:
    if n == 0:
        return 'ноль'
    if n < 0:
        return 'минус ' + int_to_ru(-n)
    parts = []
    millions = n // 1_000_000
    if millions:
        w = _chunk3(millions)
        o, t = millions % 10, (millions % 100) // 10
        s = 'миллион' if (t != 1 and o == 1) else \
            'миллиона' if (t != 1 and o in (2, 3, 4)) else 'миллионов'
        parts.append(f"{w} {s}")
        n %= 1_000_000
    thousands = n // 1000
    if thousands:
        w = _chunk3(thousands, feminine=True)
        o, t = thousands % 10, (thousands % 100) // 10
        s = 'тысяча' if (t != 1 and o == 1) else \
            'тысячи' if (t != 1 and o in (2, 3, 4)) else 'тысяч'
        parts.append(f"{w} {s}")
        n %= 1000
    if n:
        parts.append(_chunk3(n))
    return ' '.join(p for p in parts if p).strip()


def num_to_ru(s: str) -> str:
    s = s.replace(',', '.')
    try:
        if '.' in s:
            ip, fp = s.split('.', 1)
            iw = int_to_ru(int(ip))
            fw = ' '.join(_DIGIT_RU.get(c, c) for c in fp)
            return f"{iw} целых {fw}"
        return int_to_ru(int(s))
    except Exception:
        return s


# ─────────────────────────────────────────────────────────────────────────────
# Нормализация текста перед озвучкой
# ─────────────────────────────────────────────────────────────────────────────

_LATEX_RU = [
    (r'\\frac\{([^}]+)\}\{([^}]+)\}', r'\1 делить на \2'),
    (r'\\sqrt\{([^}]+)\}',             r'квадратный корень из \1'),
    (r'\\sum(?:_[^\s]+)?',             'сумма'),
    (r'\\int',                          'интеграл'),
    (r'\\infty',                        'бесконечность'),
    (r'\\cdot|\\times',                 ' умножить на '),
    (r'\\div',                          ' делить на '),
    (r'\\leq',                          ' меньше или равно '),
    (r'\\geq',                          ' больше или равно '),
    (r'\\neq',                          ' не равно '),
    (r'\\approx',                       ' примерно '),
    (r'\\pi',                           'пи'),
    (r'\\alpha',                        'альфа'),
    (r'\\beta',                         'бета'),
    (r'\\gamma',                        'гамма'),
    (r'\\delta',                        'дельта'),
    (r'\\sigma',                        'сигма'),
    (r'\\theta',                        'тета'),
    (r'\\lambda',                       'лямбда'),
    (r'\\mu',                           'мю'),
    (r'\^2',                            ' в квадрате'),
    (r'\^3',                            ' в кубе'),
    (r'\^(\w+)',                        r' в степени \1'),
    (r'_(\w+)',                         r' нижний индекс \1'),
    (r'[{}\\]',                         ' '),
]

_SYM_RU = {
    '=': ' равно ', '+': ' плюс ', '−': ' минус ', '—': ', ', '–': ', ',
    '×': ' умножить на ', '÷': ' делить на ',
    '≈': ' примерно равно ', '≠': ' не равно ',
    '≤': ' меньше или равно ', '≥': ' больше или равно ',
    '→': ' стрелка ', '⇒': ' следует из ', '←': ' стрелка влево ',
    '∑': ' сумма ', '∫': ' интеграл ', '∂': ' дэ ',
    '∈': ' принадлежит ', '∉': ' не принадлежит ',
    '∩': ' пересечение ', '∪': ' объединение ',
    '∞': ' бесконечность ', '°': ' градусов ',
    '№': ' номер ', '©': '', '®': '', '™': '',
    '>=': ' больше или равно ', '<=': ' меньше или равно ',
    '!=': ' не равно ', '==': ' равно ', '=>': ' следует ',
    '->': ' стрелка ', '<-': ' стрелка влево ',
    '±': ' плюс-минус ',
}

_ABBR_LETTERS = {
    'A':'эй','B':'би','C':'си','D':'ди','E':'и','F':'эф',
    'G':'джи','H':'эйч','I':'ай','J':'джей','K':'кей',
    'L':'эл','M':'эм','N':'эн','O':'о','P':'пи',
    'Q':'кью','R':'ар','S':'эс','T':'ти','U':'ю',
    'V':'ви','W':'дабл-ю','X':'экс','Y':'вай','Z':'зи',
}

# Известные аббревиатуры, которые НЕ нужно читать по буквам
_KNOWN_ABBR_RU = {
    'AI': 'ИИ', 'API': 'апи', 'URL': 'урл', 'HTML': 'хтмл',
    'CSS': 'сэсэс', 'SQL': 'эскюэл', 'GPU': 'джипию', 'CPU': 'цэпию',
    'OS': 'ОС', 'RAM': 'рам', 'ROM': 'ром', 'USB': 'юэсби',
    'PDF': 'пдф', 'JSON': 'джейсон', 'XML': 'иксэмэл',
    'HTTP': 'эйчтитипи', 'HTTPS': 'эйчтитипиэс',
    'FPS': 'эфписэс', 'PC': 'пц', 'VPN': 'впн',
    'OK': 'окей', 'IT': 'айти', 'UI': 'юай', 'UX': 'юикс',
}

_FRAC_DENOM_RU = {
    2: 'вторых', 3: 'третьих', 4: 'четвёртых', 5: 'пятых',
    6: 'шестых', 7: 'седьмых', 8: 'восьмых', 9: 'девятых',
    10: 'десятых', 100: 'сотых', 1000: 'тысячных',
}


def _latex_to_words_ru(m: re.Match) -> str:
    expr = m.group(1) if m.lastindex else m.group(0)
    for pat, repl in _LATEX_RU:
        if callable(repl):
            expr = re.sub(pat, repl, expr)
        else:
            expr = re.sub(pat, repl, expr)
    return ' ' + expr.strip() + ' '


def normalize_text(text: str, lang: str = 'ru') -> str:
    """
    Нормализует текст для TTS.
    lang: 'ru' или 'en'
    """
    is_ru = (lang == 'ru')

    # 1. HTML-теги
    text = re.sub(r'<[^>]+>', ' ', text)

    # 2. Блоки кода
    text = re.sub(r'```[\s\S]*?```',
                  ' блок кода. ' if is_ru else ' code block. ', text)
    text = re.sub(r'`[^`\n]+`',
                  ' код ' if is_ru else ' code ', text)

    # 3. Markdown-разметка
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}([^_\n]+)_{1,2}', r'\1', text)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-•*>]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)

    # 4. URL
    text = re.sub(r'https?://\S+', ' ссылка ' if is_ru else ' link ', text)
    text = re.sub(r'www\.\S+',     ' ссылка ' if is_ru else ' link ', text)

    # 5. LaTeX / формулы
    text = re.sub(r'\$\$([^$]+)\$\$', _latex_to_words_ru, text)
    text = re.sub(r'\$([^$\n]+)\$',   _latex_to_words_ru, text)

    # 6. Inline-математика
    text = re.sub(r'sqrt\(([^)]+)\)',
                  lambda m: f"квадратный корень из {m.group(1)}" if is_ru
                  else f"square root of {m.group(1)}", text)
    text = re.sub(r'\blog\b\s*\(([^)]+)\)',
                  lambda m: f"логарифм {m.group(1)}" if is_ru
                  else f"log of {m.group(1)}", text)
    text = re.sub(r'\bpi\b', 'пи' if is_ru else 'pi', text, flags=re.IGNORECASE)

    # Степени x^2
    text = re.sub(r'(\w+)\^2',
                  lambda m: f"{m.group(1)} в квадрате" if is_ru
                  else f"{m.group(1)} squared", text)
    text = re.sub(r'(\w+)\^3',
                  lambda m: f"{m.group(1)} в кубе" if is_ru
                  else f"{m.group(1)} cubed", text)
    text = re.sub(r'(\w+)\^(\w+)',
                  lambda m: f"{m.group(1)} в степени {m.group(2)}" if is_ru
                  else f"{m.group(1)} to the power {m.group(2)}", text)

    # 7. Операторы сравнения (до числовой замены!)
    for sym, word in _SYM_RU_OPS.items():
        text = text.replace(sym, word)

    # 8. Числа (только для русского, чтобы не ломать английское произношение)
    if is_ru:
        # Дроби типа 1/2
        def _frac(m):
            num, den = int(m.group(1)), int(m.group(2))
            return f"{int_to_ru(num)} {_FRAC_DENOM_RU.get(den, f'{den}-я часть')}"
        text = re.sub(r'\b(\d+)/(\d+)\b', _frac, text)

        # Проценты
        text = re.sub(r'(\d+(?:[.,]\d+)?)\s*%',
                      lambda m: f"{num_to_ru(m.group(1))} процентов", text)
        # ± число
        text = re.sub(r'±\s*(\d+)',
                      lambda m: f"плюс-минус {num_to_ru(m.group(1))}", text)
        # Размеры файлов
        text = re.sub(r'(\d+(?:[.,]\d+)?)\s*(мб|гб|тб|кб)',
                      lambda m: f"{num_to_ru(m.group(1))} {m.group(2)}", text,
                      flags=re.IGNORECASE)
        # Все числа
        text = re.sub(r'\b(\d+(?:[.,]\d+)?)\b',
                      lambda m: num_to_ru(m.group(1)), text)

    # 9. Спец-символы
    for sym, word in _SYM_RU.items():
        text = text.replace(sym, word)

    # 10. Аббревиатуры (заглавные латинские слова в русском тексте)
    if is_ru:
        def _abbr(m):
            w = m.group(0)
            if w in _KNOWN_ABBR_RU:
                return _KNOWN_ABBR_RU[w]
            if re.match(r'^[A-Z]{2,8}$', w):
                return ' '.join(_ABBR_LETTERS.get(c, c) for c in w)
            return w
        text = re.sub(r'\b[A-Z]{2,8}\b', _abbr, text)

    # 11. Убираем мусорные символы
    text = re.sub(r'[|\\~@#^&*_{}[\]<>]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    # Нормализуем пунктуацию
    text = re.sub(r'([.!?,;:]){2,}', r'\1', text)
    text = re.sub(r'\s+([.!?,;:])', r'\1', text)

    return text


# Операторы (применяются до символьной карты, чтобы >=  не распалось на > и =)
_SYM_RU_OPS = {
    '>=': ' больше или равно ',
    '<=': ' меньше или равно ',
    '!=': ' не равно ',
    '==': ' равно ',
    '=>': ' следует ',
    '->': ' стрелка ',
    '<-': ' стрелка влево ',
}
_SYM_RU = _SYM_RU  # уже определён выше


# ─────────────────────────────────────────────────────────────────────────────
# Сегментация текста по языку
# ─────────────────────────────────────────────────────────────────────────────

def _detect_lang(chunk: str) -> str:
    """Определяет язык куска текста по доле символов."""
    cyr = len(re.findall(r'[а-яёА-ЯЁ]', chunk))
    lat = len(re.findall(r'[a-zA-Z]', chunk))
    if cyr == 0 and lat == 0:
        return 'ru'  # только цифры/пунктуация — читаем как текущий контекст
    return 'ru' if cyr >= lat else 'en'


def split_by_language(text: str) -> list:
    """
    Разбивает текст на сегменты [(lang, text), ...].
    Мелкие сегменты (< 4 символов) склеиваются с соседним.
    """
    # Убираем лишние пробелы
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []

    segments = []
    # Разбиваем по предложениям и словам, сохраняя язык каждого
    # Токенизируем: слово + разделитель
    tokens = re.findall(r'\S+|\s+', text)

    current_lang = _detect_lang(text[:200])  # начальный язык по первым 200 символам
    current_buf = []

    for token in tokens:
        stripped = token.strip()
        if not stripped:
            current_buf.append(token)
            continue
        tok_lang = _detect_lang(stripped)
        # Числа и пунктуация — оставляем в текущем сегменте
        if not re.search(r'[а-яёА-ЯЁa-zA-Z]', stripped):
            current_buf.append(token)
            continue
        if tok_lang != current_lang:
            buf_text = ''.join(current_buf).strip()
            if buf_text:
                segments.append((current_lang, buf_text))
            current_lang = tok_lang
            current_buf = [token]
        else:
            current_buf.append(token)

    buf_text = ''.join(current_buf).strip()
    if buf_text:
        segments.append((current_lang, buf_text))

    # Склеиваем слишком короткие сегменты с соседним
    merged = []
    for lang, seg in segments:
        if merged and len(seg) < 8:
            prev_lang, prev_seg = merged[-1]
            merged[-1] = (prev_lang, prev_seg + ' ' + seg)
        else:
            merged.append((lang, seg))

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Голоса
# ─────────────────────────────────────────────────────────────────────────────

# macOS: приоритетные голоса по языку
_MACOS_VOICES_RU = ['Milena', 'Katya', 'Yuri', 'Siri Milena']
_MACOS_VOICES_EN = ['Samantha', 'Alex', 'Daniel', 'Karen']


def _macos_find_voice(preferred: list) -> Optional[str]:
    """Возвращает первый доступный голос из списка предпочтений."""
    try:
        result = subprocess.run(
            ['say', '-v', '?'], capture_output=True, text=True, timeout=5
        )
        available = result.stdout.lower()
        for v in preferred:
            if v.lower() in available:
                return v
    except Exception:
        pass
    return None


def _pyttsx3_find_voice(engine, lang: str):
    """Выбирает голос pyttsx3 для нужного языка."""
    try:
        voices = engine.getProperty('voices') or []
        ru_keys = ('ru', 'russian', 'milena', 'irina', 'tatiana', 'anna', 'александра')
        en_keys = ('en_us', 'en_gb', 'english', 'samantha', 'david', 'zira')
        keys = ru_keys if lang == 'ru' else en_keys
        for v in voices:
            combined = ((v.id or '') + ' ' + (v.name or '')).lower()
            if any(k in combined for k in keys):
                return v.id
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Основной класс
# ─────────────────────────────────────────────────────────────────────────────

class TTSEngine:
    """
    Управляет озвучкой текста. Потокобезопасен.
    Использует наилучший доступный движок для платформы.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._procs: list = []          # subprocess.Popen объекты
        self._pyttsx3_engine = None
        self._thread: Optional[threading.Thread] = None
        self._cancelled = False

    # ── Public API ────────────────────────────────────────────────────────────

    def speak(self, raw_text: str, on_done: Callable = None):
        """
        Запускает озвучку в фоновом потоке.
        raw_text — оригинальный текст (HTML + markdown).
        on_done — callback в фоновом потоке по завершении/остановке.
        """
        self.stop()
        with self._lock:
            self._cancelled = False
            self._active = True

        t = threading.Thread(
            target=self._worker,
            args=(raw_text, on_done),
            daemon=True,
        )
        self._thread = t
        t.start()

    def stop(self):
        """Немедленно останавливает озвучку."""
        with self._lock:
            self._cancelled = True
            self._active = False
        self._kill_procs()
        self._stop_pyttsx3()

    def is_active(self) -> bool:
        return self._active

    # ── Internal ──────────────────────────────────────────────────────────────

    def _worker(self, raw_text: str, on_done: Callable):
        try:
            # Определяем доминирующий язык текста
            clean = re.sub(r'<[^>]+>', '', raw_text)
            dominant_lang = _detect_lang(clean)

            # Нормализуем весь текст под доминирующий язык
            normalized = normalize_text(raw_text, dominant_lang)

            # Сегментируем по языку для смешанных текстов
            segments = split_by_language(normalized)
            if not segments:
                return

            print(f"[TTS] Запуск. Язык: {dominant_lang}. "
                  f"Сегментов: {len(segments)}. "
                  f"Текст (preview): {normalized[:80]}...")

            for lang, seg in segments:
                if self._cancelled:
                    break
                if not seg.strip():
                    continue
                self._speak_segment(seg, lang)

        except Exception as e:
            print(f"[TTS] Ошибка воспроизведения: {e}")
        finally:
            with self._lock:
                self._active = False
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

    def _speak_segment(self, text: str, lang: str):
        """Озвучивает один языковой сегмент."""
        if self._cancelled:
            return

        platform = sys.platform

        # ── macOS: say (самый надёжный для русского) ──────────────────────
        if platform == 'darwin':
            self._speak_macos(text, lang)
            return

        # ── Linux: espeak-ng ───────────────────────────────────────────────
        if platform.startswith('linux'):
            self._speak_espeak(text, lang)
            return

        # ── Windows: pyttsx3 / SAPI ────────────────────────────────────────
        self._speak_pyttsx3(text, lang)

    def _speak_macos(self, text: str, lang: str):
        if self._cancelled:
            return
        preferred = _MACOS_VOICES_RU if lang == 'ru' else _MACOS_VOICES_EN
        voice = _macos_find_voice(preferred)
        cmd = ['say', '-r', '165']
        if voice:
            cmd += ['-v', voice]
        cmd.append(text)
        self._run_proc(cmd)

    def _speak_espeak(self, text: str, lang: str):
        if self._cancelled:
            return
        # espeak-ng лучше espeak — пробуем оба
        for exe in ('espeak-ng', 'espeak'):
            try:
                lang_code = 'ru' if lang == 'ru' else 'en'
                cmd = [exe, '-l', lang_code, '-s', '155', '-a', '180',
                       '-g', '5', '--punct', text]
                self._run_proc(cmd)
                return
            except FileNotFoundError:
                continue
        print("[TTS] espeak/espeak-ng не найден")

    def _speak_pyttsx3(self, text: str, lang: str):
        if self._cancelled:
            return
        try:
            import pyttsx3
            # pyttsx3 нельзя использовать из разных потоков — создаём заново
            engine = pyttsx3.init()
            engine.setProperty('rate', 160)
            voice_id = _pyttsx3_find_voice(engine, lang)
            if voice_id:
                engine.setProperty('voice', voice_id)
                print(f"[TTS] pyttsx3 голос: {voice_id}")
            else:
                print(f"[TTS] pyttsx3: голос для '{lang}' не найден, используется дефолтный")

            with self._lock:
                self._pyttsx3_engine = engine

            if not self._cancelled:
                engine.say(text)
                engine.runAndWait()

            with self._lock:
                self._pyttsx3_engine = None
            engine.stop()

        except Exception as e:
            print(f"[TTS] pyttsx3 ошибка: {e}")
            # Fallback: попробуем espeak
            self._speak_espeak(text, lang)

    def _run_proc(self, cmd: list):
        """Запускает subprocess и ждёт завершения или отмены."""
        if self._cancelled:
            return
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._procs.append(proc)
            proc.wait()
            with self._lock:
                if proc in self._procs:
                    self._procs.remove(proc)
        except FileNotFoundError:
            print(f"[TTS] Команда не найдена: {cmd[0]}")
        except Exception as e:
            print(f"[TTS] Subprocess ошибка: {e}")

    def _kill_procs(self):
        with self._lock:
            procs = list(self._procs)
            self._procs.clear()
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass

    def _stop_pyttsx3(self):
        with self._lock:
            engine = self._pyttsx3_engine
            self._pyttsx3_engine = None
        if engine:
            try:
                engine.stop()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Синглтон — один движок на всё приложение
# ─────────────────────────────────────────────────────────────────────────────

_global_engine: Optional[TTSEngine] = None


def get_engine() -> TTSEngine:
    global _global_engine
    if _global_engine is None:
        _global_engine = TTSEngine()
    return _global_engine
