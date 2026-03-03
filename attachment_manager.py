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
═══════════════════════════════════════════════════════════════════
📄 ГЕНЕРАЦИЯ ФАЙЛОВ — СТРОГИЙ ФОРМАТ
═══════════════════════════════════════════════════════════════════

Когда пользователь просит создать, написать или сохранить файл —
ОБЯЗАТЕЛЬНО используй ТОЧНО этот формат:

[FILE:имя_файла.расширение]
содержимое файла здесь
[/FILE]

ЗАКРЫВАЮЩИЙ ТЕГ — ВСЕГДА [/FILE], а НЕ [FILE:имя_файла.расширение]!

❌ НЕПРАВИЛЬНО (закрыл тем же тегом):
[FILE:jokes.txt]
содержимое
[FILE:jokes.txt]

✅ ПРАВИЛЬНО (закрыл через [/FILE]):
[FILE:jokes.txt]
содержимое
[/FILE]

ПРИМЕР ПРАВИЛЬНОГО ОТВЕТА:
Вот файл с приколами:
[FILE:jokes.txt]
1. Почему программисты путают Хэллоуин и Рождество?
   Потому что Oct 31 == Dec 25.

2. Как называется кот программиста? try-catch.

3. Бесконечный цикл — это бесценно. Для всего остального есть break.
[/FILE]
Файл готов! Можешь скачать его кнопкой ниже.
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

    if name_match:
        suggested_name = name_match.group(1).lower()
    elif ext_match:
        ext = ext_match.group(1).lower()
        suggested_name = f"output.{ext}"
    else:
        suggested_name = "output.txt"

    if language == "russian":
        return (
            f"\n\n"
            f"⚠️ ОБЯЗАТЕЛЬНО СОЗДАЙ ФАЙЛ в точно таком формате:\n"
            f"[FILE:{suggested_name}]\n"
            f"содержимое файла\n"
            f"[/FILE]\n\n"
            f"❌ ЗАПРЕЩЕНО закрывать файл так: [FILE:{suggested_name}] — это неправильно!\n"
            f"✅ ТОЛЬКО ТАК закрывай файл: [/FILE]\n"
            f"Закрывающий тег всегда [/FILE] — без имени файла внутри!"
        )
    else:
        return (
            f"\n\n"
            f"⚠️ YOU MUST CREATE THE FILE in exactly this format:\n"
            f"[FILE:{suggested_name}]\n"
            f"file content here\n"
            f"[/FILE]\n\n"
            f"❌ WRONG closing tag: [FILE:{suggested_name}]\n"
            f"✅ CORRECT closing tag: [/FILE]\n"
            f"The closing tag is always [/FILE] — no filename inside!"
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

    # 5. Markdown code block с именем файла — ОТКЛЮЧЁН.
    # Слишком много ложных срабатываний: любой ```output.txt\n...\n```
    # в обычном объяснении кода парсился как файл.
    # Модель достаточно обучена использовать [FILE:...][/FILE] — паттерн 5 не нужен.
    #
    # (re.compile(
    #     r'```' + _FNAME + r'\n(.*?)\n```',
    #     re.DOTALL
    # ), 1, 2),

    # 6. Без новой строки — [FILE:name]content[/FILE]
    (re.compile(
        r'\[FILE:' + _FNAME + r'\](.*?)\[/FILE\]',
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

# ───────────────────────────────────────────────────────────────────────
# ATTACHMENT MIXIN
# Подключается через: class MainWindow(AttachmentMixin, QMainWindow)
# Ожидает у self: attached_files (list), file_chip_container (QWidget),
#                 current_theme (str), input_field (QWidget)
# ───────────────────────────────────────────────────────────────────────

import os as _os

_ATTACH_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_ATTACH_MAX_FILES = 5
_ATTACH_FILE_FILTER = (
    "Все поддерживаемые файлы ("
    "*.txt *.md *.py *.js *.ts *.html *.css *.json *.xml *.csv *.log "
    "*.yaml *.yml *.ini *.cfg *.toml *.sh *.bat *.c *.cpp *.h *.java "
    "*.rs *.go *.php *.rb *.swift *.kt *.sql *.env "
    "*.png *.jpg *.jpeg *.gif *.bmp *.webp"
    ");;"
    "Текстовые файлы (*.txt *.md *.py *.js *.json *.csv *.log);;"
    "Изображения (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;"
    "Все файлы (*.*)"
)


class AttachmentMixin:
    """Mixin с методами управления прикреплёнными файлами."""

    def attach_file(self):
        """Открывает диалог выбора файла и прикрепляет его."""
        if len(self.attached_files) >= _ATTACH_MAX_FILES:
            QtWidgets.QMessageBox.information(
                self, "Лимит файлов",
                f"Можно прикрепить не более {_ATTACH_MAX_FILES} файлов за раз.\n"
                "Открепите лишние файлы и попробуйте снова.",
            )
            return

        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Прикрепить файл", "", _ATTACH_FILE_FILTER,
        )
        if not paths:
            return

        for path in paths:
            if len(self.attached_files) >= _ATTACH_MAX_FILES:
                break
            if path not in self.attached_files:
                self.attached_files.append(path)
                print(f"[ATTACH] ✓ Прикреплён: {_os.path.basename(path)}")

        self.update_file_chips()

    def clear_attached_file(self):
        """Очищает все прикреплённые файлы и скрывает чипы."""
        count = len(self.attached_files)
        self.attached_files.clear()
        self.update_file_chips()
        print(f"[ATTACH] Откреплено файлов: {count}")

    def remove_attached_file(self, path: str):
        """Удаляет один файл по пути."""
        if path in self.attached_files:
            self.attached_files.remove(path)
            print(f"[ATTACH] Откреплён: {_os.path.basename(path)}")
        self.update_file_chips()

    def update_file_chips(self):
        """Перестраивает UI-чипы прикреплённых файлов над полем ввода."""
        container = self.file_chip_container

        # Удаляем старый layout
        old_layout = container.layout()
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            QtWidgets.QWidget().setLayout(old_layout)

        if not self.attached_files:
            container.hide()
            return

        is_dark = getattr(self, "current_theme", "light") == "dark"
        layout = QtWidgets.QGridLayout(container)
        layout.setContentsMargins(12, 6, 12, 4)
        layout.setSpacing(6)

        for idx, path in enumerate(self.attached_files):
            chip = self._make_file_chip(path, is_dark)
            row, col = divmod(idx, 3)
            layout.addWidget(chip, row, col, QtCore.Qt.AlignmentFlag.AlignLeft)

        container.show()

    def _make_file_chip(self, path: str, is_dark: bool) -> "QtWidgets.QFrame":
        """Создаёт один chip-виджет для файла."""
        filename = _os.path.basename(path)
        ext = _os.path.splitext(path)[1].lower()
        emoji = "🖼️" if ext in _ATTACH_IMAGE_EXT else "📄"
        display = filename if len(filename) <= 22 else filename[:19] + "…"

        if is_dark:
            chip_bg, chip_border, text_color = "rgba(102,126,234,0.20)", "rgba(102,126,234,0.40)", "#8fa3f5"
            btn_bg, btn_hover_bg, btn_hover_color = "rgba(102,126,234,0.25)", "rgba(239,68,68,0.30)", "#f87171"
        else:
            chip_bg, chip_border, text_color = "rgba(102,126,234,0.15)", "rgba(102,126,234,0.35)", "#667eea"
            btn_bg, btn_hover_bg, btn_hover_color = "rgba(102,126,234,0.20)", "rgba(239,68,68,0.25)", "#ef4444"

        chip = QtWidgets.QFrame()
        chip.setObjectName("fileChip")
        chip.setStyleSheet(f"""
            #fileChip {{
                background: {chip_bg};
                border: 1px solid {chip_border};
                border-radius: 14px;
                padding: 2px 6px;
            }}
        """)
        chip.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

        row = QtWidgets.QHBoxLayout(chip)
        row.setContentsMargins(8, 4, 4, 4)
        row.setSpacing(5)

        label = QtWidgets.QLabel(f"{emoji} {display}")
        label.setStyleSheet(f"color: {text_color}; background: transparent; border: none; font-size: 12px;")
        label.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        label.mousePressEvent = lambda _e, p=path: (
            self._preview_file(p) if hasattr(self, "_preview_file") else None
        )
        row.addWidget(label)

        remove_btn = QtWidgets.QPushButton("✕")
        remove_btn.setFixedSize(22, 22)
        remove_btn.setStyleSheet(f"""
            QPushButton {{
                background: {btn_bg}; color: {text_color};
                border: none; border-radius: 11px;
                font-size: 10px; font-weight: 700;
            }}
            QPushButton:hover {{ background: {btn_hover_bg}; color: {btn_hover_color}; }}
        """)
        remove_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        remove_btn.clicked.connect(lambda _c=False, p=path: self.remove_attached_file(p))
        row.addWidget(remove_btn)

        return chip