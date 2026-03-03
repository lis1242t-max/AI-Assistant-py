#!/usr/bin/env python3
# ai_file_generator.py
# ═══════════════════════════════════════════════════════════════════════
# Генерация файлов ИИ: обнаружение запроса, инъекция инструкции,
# парсинг ответа, хранение и визуализация.
# ═══════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import re
import json
from typing import List, Dict, Tuple

from PyQt6 import QtWidgets, QtCore, QtGui


# ───────────────────────────────────────────────────────────────────────
# ИКОНКИ ПО РАСШИРЕНИЮ
# ───────────────────────────────────────────────────────────────────────
_EXT_ICONS: dict[str, str] = {
    ".json":  "🔷",
    ".txt":   "📄",
    ".md":    "📝",
    ".csv":   "📊",
    ".xml":   "📋",
    ".yaml":  "⚙️",
    ".yml":   "⚙️",
    ".html":  "🌐",
    ".css":   "🎨",
    ".js":    "⚡",
    ".py":    "🐍",
    ".sql":   "🗄️",
    ".sh":    "🖥️",
    ".bat":   "🖥️",
    ".log":   "📃",
    ".toml":  "⚙️",
    ".ini":   "⚙️",
    ".cfg":   "⚙️",
}


# ───────────────────────────────────────────────────────────────────────
# СИСТЕМНЫЙ ПРОМПТ
# ───────────────────────────────────────────────────────────────────────
FILE_GENERATION_PROMPT = """
Для создания файла используй формат (теги НЕ переводить на русский!):
Текст ответа.
[FILE:имя.расширение]
содержимое файла здесь
[/FILE]
Важно: пиши [FILE:...] и [/FILE] только латиницей. Не писать [ФАЙЛ:] или [/ФАЙЛ].
"""


# ───────────────────────────────────────────────────────────────────────
# ОПРЕДЕЛЕНИЕ ЗАПРОСА НА СОЗДАНИЕ ФАЙЛА
# ───────────────────────────────────────────────────────────────────────

_FILE_REQUEST_PATTERNS = [
    r'создай\s+файл', r'создать\s+файл', r'сделай\s+файл', r'сгенерируй\s+файл',
    r'запиши\s+в\s+файл', r'сохрани\s+в\s+файл', r'запиши\s+файл',
    r'файл\s+с\s+', r'сохрани\s+как\s+файл',
    r'напиши\s+файл', r'создай.{0,20}\.txt', r'создай.{0,20}\.json',
    r'создай.{0,20}\.csv', r'создай.{0,20}\.md', r'создай.{0,20}\.xml',
    r'сгенерируй.{0,20}\.txt', r'сделай.{0,20}\.txt',
    r'хочу\s+(получить|скачать|сохранить)\s+файл',
    r'дай\s+мне\s+файл', r'выгрузи\s+(в|как)\s+файл',
    r'create\s+a?\s*file', r'make\s+a?\s*file', r'generate\s+a?\s*file',
    r'save\s+(as|to)\s+file', r'write\s+to\s+file', r'write\s+a?\s*file',
    r'create.{0,20}\.txt', r'create.{0,20}\.json', r'make.{0,20}\.txt',
    r'output\s+(as|to)\s+file',
]

_FILE_REQUEST_RE = re.compile('|'.join(_FILE_REQUEST_PATTERNS), re.IGNORECASE)
_EXT_RE = re.compile(
    r'\b(txt|json|csv|md|xml|yaml|yml|html|py|log|sql|ini|cfg|toml)\b', re.IGNORECASE
)
_ACTION_RE = re.compile(
    r'\b(создай|сделай|напиши|запиши|сохрани|сгенерируй|выгрузи|'
    r'create|make|write|save|generate|output|export)\b',
    re.IGNORECASE
)


def detect_file_request(text: str) -> bool:
    """Возвращает True если пользователь просит создать/сохранить файл."""
    if _FILE_REQUEST_RE.search(text):
        return True
    if _ACTION_RE.search(text) and _EXT_RE.search(text):
        return True
    return False


def build_file_injection(user_text: str, language: str = "russian") -> str:
    """
    Вшивает жёсткую инструкцию прямо в сообщение пользователя.
    Явно показывает НЕПРАВИЛЬНЫЙ и ПРАВИЛЬНЫЙ форматы, потому что
    модели часто используют [FILE:name] как закрывающий тег вместо [/FILE].
    """
    if not detect_file_request(user_text):
        return ""

    # Угадываем имя файла из запроса
    name_match = re.search(
        r'\b([\w\-_]+\.(txt|json|csv|md|xml|yaml|yml|html|py|log|sql|ini|cfg|toml))\b',
        user_text, re.IGNORECASE
    )
    ext_match = _EXT_RE.search(user_text)

    # Ищем имя файла без расширения в разных формулировках.
    # ВАЖНО: пользователи часто путают латинскую "c" и кириллическую "с",
    # поэтому паттерн "[сc]\s+именем" ловит оба варианта.
    bare_name_match = re.search(
        r'(?:'
        r'название\s+файла|имя\s+файла|назови\s+файл|назвать\s+файл'
        r'|файл\s+будет\s+называться|назови\s+его|называемый'
        r'|[сc]\s+именем|файл\s+[сc]\s+названием'   # лат. c / кир. с
        r'|file\s+name(?:\s+(?:will\s+be|is|be))?|file\s+named|file\s+called'
        r'|filename|named|called'
        r')\s*(?:будет\s+|как\s+|:\s*|=\s*|\s+)([\w\-]+)',
        user_text, re.IGNORECASE
    )

    if name_match:
        suggested_name = name_match.group(1).lower()
    elif bare_name_match:
        bare = bare_name_match.group(1).strip().lower()
        # Добавляем расширение из запроса или .txt по умолчанию
        if ext_match:
            suggested_name = f"{bare}.{ext_match.group(1).lower()}"
        else:
            suggested_name = f"{bare}.txt"
    elif ext_match:
        ext = ext_match.group(1).lower()
        suggested_name = f"output.{ext}"
    else:
        suggested_name = "output.txt"

    if language == "russian":
        return (
            f"\n\nСоздай файл СТРОГО в этом формате — без пропусков и без сокращений:\n"
            f"Вот файл!\n"
            f"[FILE:{suggested_name}]\n"
            f"<здесь ПОЛНОЕ содержимое файла — все пункты, весь текст, ничего не пропускать>\n"
            f"[/FILE]\n"
            f"КРИТИЧНО: тег [FILE:{suggested_name}] — на отдельной строке. "
            f"Всё содержимое — между тегами. Закрывающий тег [/FILE] — на отдельной строке в конце. "
            f"Без [/FILE] файл НЕ будет создан! Теги писать ТОЛЬКО латиницей. "
            f"НЕ сокращать содержимое — включить ВСЁ что просил пользователь."
        )
    else:
        return (
            f"\n\nCreate the file STRICTLY in this format — include ALL content, nothing omitted:\n"
            f"Here's your file!\n"
            f"[FILE:{suggested_name}]\n"
            f"<full file content here — every item, every line, nothing skipped>\n"
            f"[/FILE]\n"
            f"CRITICAL: [FILE:{suggested_name}] on its own line. All content between tags. "
            f"[/FILE] on its own line at the end. Tags in Latin only. Do NOT abbreviate."
        )


# ───────────────────────────────────────────────────────────────────────
# ПАРСИНГ ТЕГОВ ИЗ ОТВЕТА
# ───────────────────────────────────────────────────────────────────────
# Поддерживаем ВСЕ варианты которые модели могут сгенерировать:
#
#   Паттерн 1 — правильный:
#     [FILE:name.ext]\ncontent\n[/FILE]
#
#   Паттерн 2 — модель закрыла тем же тегом (самая частая ошибка!):
#     [FILE:name.ext]\ncontent\n[FILE:name.ext]
#     или [FILE:name.ext] content [FILE:name.ext]
#
#   Паттерн 3 — с двоеточием после открывающего тега:
#     [FILE:name.ext]: content [/FILE]
#
#   Паттерн 4 — XML-стиль:
#     <FILE name="name.ext">content</FILE>
#
#   Паттерн 5 — markdown code block с именем:
#     ```name.ext\ncontent\n```

_FNAME = r'([\w\-_.() ]+\.(?:txt|json|csv|md|xml|yaml|yml|html|css|js|py|sql|sh|bat|log|toml|ini|cfg))'

_FILE_PATTERNS: list[tuple[re.Pattern, int, int]] = [
    # (pattern, group_for_name, group_for_content)

    # 1. Правильный формат: [FILE:name] ... [/FILE]
    (re.compile(
        r'\[📄?FILE:' + _FNAME + r'\][:\s]*\n(.*?)\n?\s*\[/FILE\]',
        re.DOTALL | re.IGNORECASE
    ), 1, 2),

    # 2. Модель закрыла тем же тегом: [FILE:name] ... [FILE:name]
    (re.compile(
        r'\[FILE:' + _FNAME + r'\][:\s]*\n(.*?)\n?\s*\[FILE:[\w\-_.() ]+\]',
        re.DOTALL | re.IGNORECASE
    ), 1, 2),

    # 3. Без [/FILE] — контент в одну строку после двоеточия:
    #    [FILE:name.ext]: всё содержимое тут
    (re.compile(
        r'\[FILE:' + _FNAME + r'\]:\s*(.+?)(?:\n\n|\Z)',
        re.DOTALL | re.IGNORECASE
    ), 1, 2),

    # 4. XML-стиль: <FILE name="name.ext">
    (re.compile(
        r'<FILE\s+name=["\']?' + _FNAME + r'["\']?>[:\s]*\n?(.*?)\n?\s*</FILE>',
        re.DOTALL | re.IGNORECASE
    ), 1, 2),

    # 5. Markdown code block с именем файла:
    #    ```jokes.txt\ncontent\n```
    (re.compile(
        r'```' + _FNAME + r'\n(.*?)\n```',
        re.DOTALL
    ), 1, 2),

    # 6. Без новой строки — [FILE:name]content[/FILE]
    (re.compile(
        r'\[FILE:' + _FNAME + r'\](.*?)\[/FILE\]',
        re.DOTALL | re.IGNORECASE
    ), 1, 2),

    # 7. Без закрывающего тега — [FILE:name] или [FILE:name]\n content до конца/следующего блока
    #    Самый частый случай когда модель пишет тег но забывает [/FILE]
    (re.compile(
        r'\[FILE:' + _FNAME + r'\]\s*\n(.*?)(?=\[FILE:|\[/FILE\]|\Z)',
        re.DOTALL | re.IGNORECASE
    ), 1, 2),

    # 8. Инлайн без закрывающего тега: [FILE:name] content (всё до конца или до \n\n)
    (re.compile(
        r'\[FILE:' + _FNAME + r'\]\s+(.+?)(?:\[/FILE\]|\n\n|\Z)',
        re.DOTALL | re.IGNORECASE
    ), 1, 2),
]


def parse_generated_files(text: str) -> Tuple[str, List[Dict]]:
    """
    Вырезает теги файлов из ответа ИИ.
    Обрабатывает правильные форматы И типичные ошибки моделей.
    Возвращает: (clean_text, files)
    files — список {"filename": str, "content": str, "ext": str}
    """
    # Нормализуем русские теги → английские ДО парсинга.
    # DeepSeek 7b иногда переводит [FILE:name] → [ФАЙЛ:name], [/FILE] → [/ФАЙЛ].
    text = re.sub(r'\[ФАЙЛ:', '[FILE:', text, flags=re.IGNORECASE)
    text = re.sub(r'\[/ФАЙЛ\]', '[/FILE]', text, flags=re.IGNORECASE)

    files: List[Dict] = []
    matched_spans: List[Tuple[int, int]] = []

    for pattern, name_grp, content_grp in _FILE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            # Не обрабатываем уже поглощённые spans
            if any(s <= start < e for s, e in matched_spans):
                continue

            raw_name = match.group(name_grp).strip()
            content  = match.group(content_grp).strip()

            # Убираем возможный ": " в начале содержимого
            content = re.sub(r'^:\s*', '', content).strip()

            filename = os.path.basename(raw_name)
            if not filename:
                filename = "file.txt"
            ext = os.path.splitext(filename)[1].lower()
            if not ext:
                ext = ".txt"
                filename += ext

            if content:  # Не добавляем пустые файлы
                files.append({"filename": filename, "content": content, "ext": ext})
                matched_spans.append((start, end))
                print(f"[FILE_GEN] ✓ Поймал файл '{filename}' ({len(content)} символов) паттерном #{_FILE_PATTERNS.index((pattern, name_grp, content_grp)) + 1}")

    # Убираем все теги из текста
    clean = text
    for pattern, _, _ in _FILE_PATTERNS:
        clean = pattern.sub("", clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean).strip()

    return clean, files


# ───────────────────────────────────────────────────────────────────────
# ВИДЖЕТ КАРТОЧКИ ФАЙЛА
# ───────────────────────────────────────────────────────────────────────

class GeneratedFileWidget(QtWidgets.QWidget):
    """Карточки сгенерированных файлов под пузырём ИИ."""

    def __init__(self, files: List[Dict], main_window=None, parent=None):
        super().__init__(parent)
        self._files = files
        self._main_window = main_window
        self._card_widgets: List[QtWidgets.QFrame] = []   # для горячего обновления
        self._dl_buttons:   List[QtWidgets.QPushButton] = []
        self._name_labels:  List[QtWidgets.QLabel] = []
        self._sz_labels:    List[QtWidgets.QLabel] = []

        # Тема из main_window — всегда актуальна
        theme       = getattr(main_window, "current_theme",        "light") if main_window else "light"
        liquid_glass = getattr(main_window, "current_liquid_glass", True)   if main_window else True
        self._theme       = theme
        self._liquid_glass = liquid_glass

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(18, 2, 0, 4)
        outer.setSpacing(6)
        for fdata in files:
            card, dl_btn, name_lbl, sz_lbl = self._make_card(fdata, theme, liquid_glass)
            outer.addWidget(card, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
            self._card_widgets.append(card)
            self._dl_buttons.append(dl_btn)
            self._name_labels.append(name_lbl)
            self._sz_labels.append(sz_lbl)

    # ── Цветовая схема ────────────────────────────────────────────────
    @staticmethod
    def _colors(theme: str, liquid_glass: bool) -> dict:
        if theme == "dark":
            if liquid_glass:
                return dict(
                    card_bg="rgba(40,40,55,0.78)", card_border="rgba(75,75,100,0.65)",
                    text="#d0d0e8", sub="#8a8aaa", btn_bg="rgba(55,55,75,0.65)",
                    btn_hover="rgba(70,70,95,0.80)", btn_border="rgba(90,90,120,0.55)",
                    accent="#7b93f0", sep="rgba(90,90,120,0.35)"
                )
            else:
                return dict(
                    card_bg="rgb(36,36,48)", card_border="rgba(62,62,85,0.9)",
                    text="#d0d0e8", sub="#7a7a9a", btn_bg="rgb(44,44,60)",
                    btn_hover="rgb(56,56,75)", btn_border="rgba(75,75,100,0.9)",
                    accent="#7b93f0", sep="rgba(75,75,100,0.4)"
                )
        else:
            if liquid_glass:
                return dict(
                    card_bg="rgba(255,255,255,0.52)", card_border="rgba(175,185,230,0.62)",
                    text="#1a202c", sub="#5a6aaa", btn_bg="rgba(255,255,255,0.60)",
                    btn_hover="rgba(230,237,255,0.85)", btn_border="rgba(175,185,230,0.56)",
                    accent="#5a6aaa", sep="rgba(175,185,230,0.4)"
                )
            else:
                return dict(
                    card_bg="rgb(238,241,254)", card_border="rgba(195,205,232,0.92)",
                    text="#1a1a2e", sub="#5a6aaa", btn_bg="rgb(228,233,252)",
                    btn_hover="rgb(212,220,248)", btn_border="rgba(195,205,232,0.92)",
                    accent="#5a6aaa", sep="rgba(195,205,232,0.5)"
                )

    # ── Построить карточку ────────────────────────────────────────────
    def _make_card(self, fdata: dict, theme: str, liquid_glass: bool):
        filename = fdata.get("filename", "file.txt")
        content  = fdata.get("content", "")
        ext      = fdata.get("ext", ".txt")
        icon_str = _EXT_ICONS.get(ext, "📄")
        sz       = len(content.encode("utf-8"))
        size_str = f"{sz / 1024:.1f} КБ" if sz >= 1024 else f"{sz} Б"
        c        = self._colors(theme, liquid_glass)

        # ── Единая карточка ──────────────────────────────────────────
        card = QtWidgets.QFrame()
        card.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                           QtWidgets.QSizePolicy.Policy.Fixed)
        card.setStyleSheet(
            f"QFrame#fileCard {{ background: {c['card_bg']}; "
            f"border: 1.5px solid {c['card_border']}; border-radius: 14px; }}"
        )
        card.setObjectName("fileCard")

        col = QtWidgets.QVBoxLayout(card)
        col.setContentsMargins(12, 10, 14, 10)
        col.setSpacing(7)

        # Строка: иконка + имя + размер
        top_row = QtWidgets.QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(9)

        icon_lbl = QtWidgets.QLabel(icon_str)
        icon_lbl.setFixedSize(28, 28)
        icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none; font-size: 18px;")
        top_row.addWidget(icon_lbl)

        info_col = QtWidgets.QVBoxLayout()
        info_col.setSpacing(1)
        info_col.setContentsMargins(0, 0, 0, 0)

        disp = filename if len(filename) <= 28 else filename[:25] + "…"
        name_lbl = QtWidgets.QLabel(disp)
        name_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"color: {c['text']}; font-size: 13px; font-weight: 600;"
        )
        sz_lbl = QtWidgets.QLabel(size_str)
        sz_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"color: {c['sub']}; font-size: 11px;"
        )
        info_col.addWidget(name_lbl)
        info_col.addWidget(sz_lbl)
        top_row.addLayout(info_col)
        col.addLayout(top_row)

        # Разделитель
        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {c['sep']}; border: none;")
        col.addWidget(sep)

        # Кнопка скачать — внутри карточки, слева
        dl_btn = QtWidgets.QPushButton("⬇  Скачать")
        dl_btn.setFixedHeight(26)
        dl_btn.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                             QtWidgets.QSizePolicy.Policy.Fixed)
        dl_btn.setStyleSheet(
            f"QPushButton {{ background: {c['btn_bg']}; color: {c['accent']}; "
            f"border: 1px solid {c['btn_border']}; border-radius: 7px; "
            f"font-size: 12px; padding: 0px 12px; }}"
            f"QPushButton:hover {{ background: {c['btn_hover']}; }}"
        )
        dl_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        dl_btn.clicked.connect(lambda _, f=filename, ct=content: self._download(f, ct))
        col.addWidget(dl_btn, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)

        # Клик по карточке (кроме кнопки) — превью
        card.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        card.mousePressEvent = lambda event, f=filename, ct=content, e=ext: self._preview(f, ct, e)

        return card, dl_btn, name_lbl, sz_lbl

    # ── Горячее обновление темы ────────────────────────────────────────
    def update_theme(self, theme: str, liquid_glass: bool):
        """Обновляет цвета всех карточек без пересоздания виджетов."""
        self._theme       = theme
        self._liquid_glass = liquid_glass
        c = self._colors(theme, liquid_glass)

        card_style = (
            f"QFrame#fileCard {{ background: {c['card_bg']}; "
            f"border: 1.5px solid {c['card_border']}; border-radius: 14px; }}"
        )
        dl_style = (
            f"QPushButton {{ background: {c['btn_bg']}; color: {c['accent']}; "
            f"border: 1px solid {c['btn_border']}; border-radius: 7px; "
            f"font-size: 12px; padding: 0px 12px; }}"
            f"QPushButton:hover {{ background: {c['btn_hover']}; }}"
        )
        name_style = (
            f"background: transparent; border: none; "
            f"color: {c['text']}; font-size: 13px; font-weight: 600;"
        )
        sz_style = (
            f"background: transparent; border: none; "
            f"color: {c['sub']}; font-size: 11px;"
        )
        sep_style = f"background: {c['sep']}; border: none;"

        for card in self._card_widgets:
            try:
                card.setStyleSheet(card_style)
                # Разделитель внутри карточки
                for child in card.findChildren(QtWidgets.QFrame):
                    child.setStyleSheet(sep_style)
            except RuntimeError:
                pass

        for btn in self._dl_buttons:
            try:
                btn.setStyleSheet(dl_style)
            except RuntimeError:
                pass

        for lbl in self._name_labels:
            try:
                lbl.setStyleSheet(name_style)
            except RuntimeError:
                pass

        for lbl in self._sz_labels:
            try:
                lbl.setStyleSheet(sz_style)
            except RuntimeError:
                pass

    def _preview(self, filename, content, ext):
        dlg = _FilePreviewDialog(filename, content, ext, theme=self._theme, parent=self)
        dlg.exec()

    def _download(self, filename, content):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Сохранить файл", filename, "Все файлы (*.*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Ошибка сохранения", f"Не удалось сохранить:\n{e}")


class _FilePreviewDialog(QtWidgets.QDialog):
    def __init__(self, filename, content, ext, theme="light", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"📄  {filename}")
        self.resize(700, 480)
        self.setModal(True)

        is_dark   = (theme == "dark")
        bg        = "#1a1a26" if is_dark else "#f5f7fc"
        editor_bg = "#13131d" if is_dark else "#ffffff"
        text_c    = "#d0d0e8" if is_dark else "#1a202c"
        border_c  = "#363650" if is_dark else "#cdd3ea"
        btn_bg    = "#28283c" if is_dark else "#eceffe"
        btn_hover = "#383852" if is_dark else "#dce0f8"
        accent    = "#7b93f0" if is_dark else "#5a6aaa"

        self.setStyleSheet(
            f"QDialog {{ background: {bg}; border: 1.5px solid {border_c}; border-radius: 16px; }}"
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        hdr = QtWidgets.QHBoxLayout()
        ico = _EXT_ICONS.get(ext, "📄")
        lbl = QtWidgets.QLabel(f"{ico}  {filename}")
        lbl.setStyleSheet(
            f"color: {text_c}; font-size: 14px; font-weight: 700; background: transparent; border: none;"
        )
        hdr.addWidget(lbl)
        hdr.addStretch()
        sz = len(content.encode("utf-8"))
        sz_lbl = QtWidgets.QLabel(f"{sz / 1024:.1f} КБ" if sz >= 1024 else f"{sz} Б")
        sz_lbl.setStyleSheet(
            f"color: {accent}; font-size: 11px; background: transparent; border: none;"
        )
        hdr.addWidget(sz_lbl)
        layout.addLayout(hdr)

        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {border_c};")
        layout.addWidget(sep)

        editor = QtWidgets.QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(content)
        editor.setFont(QtGui.QFont("Courier New", 12))
        editor.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {editor_bg}; color: {text_c}; "
            f"border: 1.5px solid {border_c}; border-radius: 10px; padding: 10px; "
            f"selection-background-color: {accent}; }}"
        )
        layout.addWidget(editor)

        _bs = (f"QPushButton {{ background: {btn_bg}; color: {accent}; border: 1px solid {border_c}; "
               f"border-radius: 9px; padding: 6px 16px; font-size: 13px; }}"
               f"QPushButton:hover {{ background: {btn_hover}; }}")
        _cs = (f"QPushButton {{ background: {accent}; color: white; border: none; "
               f"border-radius: 9px; padding: 6px 18px; font-size: 13px; font-weight: 600; }}"
               f"QPushButton:hover {{ background: {accent}cc; }}")

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        copy_btn  = QtWidgets.QPushButton("📋  Копировать"); copy_btn.setStyleSheet(_bs)
        save_btn  = QtWidgets.QPushButton("⬇  Скачать");    save_btn.setStyleSheet(_bs)
        close_btn = QtWidgets.QPushButton("Закрыть");        close_btn.setStyleSheet(_cs)
        for b in (copy_btn, save_btn, close_btn):
            b.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        copy_btn.clicked.connect(lambda: (
            QtWidgets.QApplication.clipboard().setText(content),
            copy_btn.setText("✓  Скопировано"),
        ))
        save_btn.clicked.connect(lambda: self._save(filename, content))
        close_btn.clicked.connect(self.accept)

    def _save(self, filename, content):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Сохранить файл", filename, "Все файлы (*.*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить:\n{e}")