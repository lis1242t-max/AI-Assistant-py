# enhanced_subtext.py
# ══════════════════════════════════════════════════════════════════════════════
# УЛУЧШЕННЫЙ ПОДТЕКСТ — персональные предпочтения общения с ИИ
#
# Данные хранятся ТОЛЬКО локально в user_subtext.json.
# Ничего никуда не отправляется — программа полностью локальная.
# ══════════════════════════════════════════════════════════════════════════════

import os
import json
from PyQt6 import QtWidgets, QtGui, QtCore

SUBTEXT_FILE = "user_subtext.json"

SUBTEXT_README = (
    "✨ Улучшенный подтекст\n\n"
    "Эта функция запоминает, как вы предпочитаете общаться с ИИ:\n"
    "• Стиль речи (с шутками, неформально, с матами и т.д.)\n"
    "• Предпочтительный язык общения\n"
    "• Тональность ответов\n\n"
    "Режим «Авто» — программа сама анализирует ваши сообщения\n"
    "и постепенно подстраивает стиль ИИ под вас.\n\n"
    "Предпочтения применяются ко всем моделям и чатам сразу.\n\n"
    "🔒 Приватность:\n"
    "Все данные хранятся ТОЛЬКО на вашем компьютере в файле\n"
    "user_subtext.json. Никуда не отправляются."
)

# ══════════════════════════════════════════════════════════════════════════════
#  SubtextManager
# ══════════════════════════════════════════════════════════════════════════════

class SubtextManager:

    _DEFAULTS = {
        "enabled":     False,
        "auto_mode":   False,
        "language":    "",
        "style":       [],
        "custom_note": "",
        "auto_learned": {
            "detected_style": [],
            "message_count":  0,
        },
        "created_at": "",
        "updated_at": "",
    }

    @staticmethod
    def load() -> dict:
        try:
            if os.path.exists(SUBTEXT_FILE):
                with open(SUBTEXT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                merged = dict(SubtextManager._DEFAULTS)
                merged.update(data)
                if not isinstance(merged.get("auto_learned"), dict):
                    merged["auto_learned"] = dict(SubtextManager._DEFAULTS["auto_learned"])
                return merged
        except Exception as e:
            print(f"[SUBTEXT] load error: {e}")
        return dict(SubtextManager._DEFAULTS)

    @staticmethod
    def save(prefs: dict) -> bool:
        try:
            from datetime import datetime
            now = datetime.now().isoformat(timespec="seconds")
            if not prefs.get("created_at"):
                prefs["created_at"] = now
            prefs["updated_at"] = now
            with open(SUBTEXT_FILE, "w", encoding="utf-8") as f:
                json.dump(prefs, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[SUBTEXT] save error: {e}")
            return False

    @staticmethod
    def has_preferences() -> bool:
        prefs = SubtextManager.load()
        return bool(
            prefs.get("language") or prefs.get("style") or
            prefs.get("custom_note") or prefs.get("auto_mode")
        )

    @staticmethod
    def is_enabled() -> bool:
        return SubtextManager.load().get("enabled", False)

    @staticmethod
    def set_enabled(value: bool):
        prefs = SubtextManager.load()
        prefs["enabled"] = value
        SubtextManager.save(prefs)

    @staticmethod
    def reset():
        prefs = SubtextManager.load()
        prefs.update({
            "language": "", "style": [], "custom_note": "",
            "auto_mode": False,
            "auto_learned": {"detected_style": [], "message_count": 0},
        })
        SubtextManager.save(prefs)

    # ── Формирование инъекции ─────────────────────────────────────────────────

    @staticmethod
    def build_system_injection() -> str:
        """
        Возвращает строку для добавления В НАЧАЛО system_prompt.
        Написана как мягкая стилевая установка — НЕ «приоритет», НЕ «ВАЖНО».
        Это предотвращает галлюцинации и конфликты с основным промптом.
        """
        prefs = SubtextManager.load()
        if not prefs.get("enabled"):
            return ""

        parts = []

        lang = prefs.get("language", "").strip()
        if lang and lang != "Не важно (как спрошу)":
            lang_directives = {
                "Русский":    "Отвечай ТОЛЬКО на русском языке. Никакого другого языка в ответах.",
                "English":    "Reply ONLY in English. No other language in responses.",
                "Украинский": "Відповідай ТІЛЬКИ українською мовою.",
                "Беларуский": "Адказвай ТОЛЬКІ па-беларуску.",
                "Español":    "Responde SOLO en español.",
                "Deutsch":    "Antworte NUR auf Deutsch.",
                "Français":   "Réponds UNIQUEMENT en français.",
                "Polski":     "Odpowiadaj WYŁĄCZNIE po polsku. Żadnych innych języków.",
            }
            parts.append(lang_directives.get(lang, f"Отвечай ТОЛЬКО на языке: {lang}."))

        styles = list(prefs.get("style", []))
        if prefs.get("auto_mode"):
            for s in prefs.get("auto_learned", {}).get("detected_style", []):
                if s not in styles:
                    styles.append(s)

        style_map = {
            "jokes":    "Уместно добавляй юмор.",
            # profanity намеренно убрана из мягкой инъекции:
            # мягкое упоминание в начале промпта не перебивает RLHF-обучение модели.
            # Жёсткое разрешение мата даётся ТОЛЬКО через get_subtext_reminder() в конце.
            "formal":  "Официально-деловой тон.",
            "warm":    "Тёплый, дружелюбный стиль.",
            "concise": "Отвечай коротко и по делу.",
        }
        for s in styles:
            if s in style_map:
                parts.append(style_map[s])

        note = prefs.get("custom_note", "").strip()
        if note:
            parts.append(note)

        if not parts:
            return ""

        # Без заголовков-команд — они провоцируют модель зачитывать их вслух.
        return "\n".join(parts) + "\n\n"

    # ── Авто-анализ стиля ─────────────────────────────────────────────────────

    @staticmethod
    def analyze_and_update(user_message: str):
        """
        Лёгкий эвристический анализ сообщения пользователя.
        Вызывается из run.py через subtext_track_message().
        Не делает запросов к ИИ — работает мгновенно.
        """
        prefs = SubtextManager.load()
        if not prefs.get("enabled") or not prefs.get("auto_mode"):
            return

        auto    = prefs.setdefault("auto_learned", {"detected_style": [], "message_count": 0})
        count   = auto.get("message_count", 0) + 1
        auto["message_count"] = count
        detected = set(auto.get("detected_style", []))
        text = user_message.lower()

        _mats = [
            "блять","блин","блядь","бля","хуй","хуя","пизд",
            "ёбан","ёб","еблан","сука","пиздец","нахуй","нахрен",
            "fuck","shit","damn","wtf","ass","crap",
        ]
        if any(m in text for m in _mats):
            detected.add("profanity")

        _humor = ["хаха","хехе","ахах","lol","lmao","kek","😂","🤣",")))","хи-хи"]
        if any(m in text for m in _humor):
            detected.add("jokes")

        if count > 5 and len(user_message.strip()) < 35:
            detected.add("concise")

        _formal = ["уважаемый","прошу","благодарю","настоящим","в связи с","сообщаю"]
        if any(m in text for m in _formal):
            detected.add("formal")
            detected.discard("warm")
            detected.discard("profanity")

        auto["detected_style"] = list(detected)
        prefs["auto_learned"]  = auto
        SubtextManager.save(prefs)


# ══════════════════════════════════════════════════════════════════════════════
#  UI helpers
# ══════════════════════════════════════════════════════════════════════════════

def _apple_font_local(size: int, weight=None):
    font = QtGui.QFont()
    try:
        db       = QtGui.QFontDatabase()
        families = set(db.families())
        chosen   = next(
            (n for n in ("SF Pro Display", "SF Pro Text", "Helvetica Neue", "Segoe UI", "Arial")
             if n in families), "Arial"
        )
        font.setFamily(chosen)
    except Exception:
        font.setFamily("Arial")
    font.setPointSize(size)
    if weight is not None:
        font.setWeight(weight)
    return font


class _ToggleSwitchLocal(QtWidgets.QAbstractButton):
    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._thumb = 0.0
        self.setCheckable(True)
        self.setFixedSize(56, 30)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._anim = QtCore.QPropertyAnimation(self, b"_thumb_pos", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._start_anim)
        if checked:
            self._thumb = 1.0
            self.setChecked(True)

    def _get_thumb(self): return self._thumb
    def _set_thumb(self, v):
        self._thumb = v; self.update()
    _thumb_pos = QtCore.pyqtProperty(float, _get_thumb, _set_thumb)

    def _start_anim(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._thumb)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2
        t = self._thumb
        r_c = int(200 + (33  - 200) * t)
        g_c = int(200 + (150 - 200) * t)
        b_c = int(204 + (243 - 204) * t)
        p.setBrush(QtGui.QBrush(QtGui.QColor(r_c, g_c, b_c)))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, r, r)
        margin = 3
        diam   = h - margin * 2
        travel = w - diam - margin * 2
        tx     = margin + self._thumb * travel
        p.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
        p.drawEllipse(QtCore.QRectF(tx, margin, diam, diam))
        p.end()

    def sizeHint(self): return QtCore.QSize(56, 30)


# ══════════════════════════════════════════════════════════════════════════════
#  Диалог редактирования предпочтений
# ══════════════════════════════════════════════════════════════════════════════

class SubtextEditDialog(QtWidgets.QDialog):

    def __init__(self, parent=None, reset_mode: bool = False):
        super().__init__(parent)
        self.reset_mode = reset_mode
        self.setWindowTitle("Улучшенный подтекст — предпочтения")
        self.setMinimumWidth(440)
        self.setModal(True)

        self._prefs = SubtextManager.load()
        if reset_mode:
            self._prefs.update({
                "language": "", "style": [], "custom_note": "", "auto_mode": False
            })
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 20)

        title = QtWidgets.QLabel(
            "Начать заново" if self.reset_mode else "Настройка предпочтений"
        )
        title.setFont(_apple_font_local(18, QtGui.QFont.Weight.Bold))
        layout.addWidget(title)

        # ── Авто-режим ────────────────────────────────────────────────────────
        auto_box = QtWidgets.QGroupBox()
        auto_box.setStyleSheet(
            "QGroupBox { border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px; }"
        )
        auto_h = QtWidgets.QHBoxLayout(auto_box)
        auto_h.setContentsMargins(8, 6, 8, 6)
        self.auto_toggle = _ToggleSwitchLocal(checked=self._prefs.get("auto_mode", False))
        auto_h.addWidget(self.auto_toggle)
        col = QtWidgets.QVBoxLayout()
        t = QtWidgets.QLabel("🤖 Авто-анализ стиля")
        t.setFont(_apple_font_local(13, QtGui.QFont.Weight.Medium))
        d = QtWidgets.QLabel("Программа сама учится по вашим сообщениям.\nРучные настройки ниже дополняют авто.")
        d.setFont(_apple_font_local(11))
        d.setStyleSheet("color: #64748b;")
        col.addWidget(t); col.addWidget(d)
        auto_h.addLayout(col); auto_h.addStretch()
        layout.addWidget(auto_box)

        sep = QtWidgets.QLabel("— или задать вручную —")
        sep.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        sep.setFont(_apple_font_local(11))
        sep.setStyleSheet("color: #94a3b8;")
        layout.addWidget(sep)

        # ── Язык ──────────────────────────────────────────────────────────────
        layout.addWidget(_lbl("Предпочтительный язык:"))
        self.lang_combo = QtWidgets.QComboBox()
        self.lang_combo.addItems([
            "Не важно (как спрошу)", "Русский", "English",
            "Украинский", "Беларуский", "Español", "Deutsch", "Français", "Polski",
        ])
        idx = self.lang_combo.findText(self._prefs.get("language", ""))
        if idx >= 0: self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.setFont(_apple_font_local(13))
        layout.addWidget(self.lang_combo)

        # ── Стиль ─────────────────────────────────────────────────────────────
        layout.addWidget(_lbl("Стиль общения (можно несколько):"))
        saved = set(self._prefs.get("style", []))
        self._checks = {}
        col2 = QtWidgets.QVBoxLayout()
        col2.setSpacing(5)
        for key, label in [
            ("jokes",     "😄 С шутками и юмором"),
            ("profanity", "🤬 Без цензуры (с матами)"),
            ("formal",    "👔 Официально-деловой"),
            ("warm",      "🤝 Тепло и дружелюбно"),
            ("concise",   "⚡ Кратко и по делу"),
        ]:
            cb = QtWidgets.QCheckBox(label)
            cb.setFont(_apple_font_local(13))
            cb.setChecked(key in saved)
            self._checks[key] = cb
            col2.addWidget(cb)
        layout.addLayout(col2)

        # ── Заметка ───────────────────────────────────────────────────────────
        layout.addWidget(_lbl("Дополнительные пожелания (необязательно):"))
        self.note_edit = QtWidgets.QPlainTextEdit()
        self.note_edit.setPlaceholderText(
            "Например: «Объясняй как ребёнку», «Всегда давай пример кода»…"
        )
        self.note_edit.setFont(_apple_font_local(13))
        self.note_edit.setFixedHeight(65)
        self.note_edit.setPlainText(self._prefs.get("custom_note", ""))
        layout.addWidget(self.note_edit)

        # ── Кнопки ────────────────────────────────────────────────────────────
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        cancel = QtWidgets.QPushButton("Отмена")
        cancel.setFont(_apple_font_local(13))
        cancel.setMinimumHeight(40)
        cancel.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        cancel.clicked.connect(self.reject)
        save = QtWidgets.QPushButton("💾 Сохранить")
        save.setFont(_apple_font_local(13, QtGui.QFont.Weight.Medium))
        save.setMinimumHeight(40)
        save.setDefault(True)
        save.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        save.setStyleSheet(
            "QPushButton{background:#2196a5;color:white;border-radius:8px;border:none;}"
            "QPushButton:hover{background:#1a7a8a;}"
        )
        save.clicked.connect(self._on_save)
        row.addWidget(cancel); row.addWidget(save)
        layout.addLayout(row)

    def _on_save(self):
        prefs = SubtextManager.load()
        prefs["auto_mode"]   = self.auto_toggle.isChecked()
        prefs["language"]    = self.lang_combo.currentText()
        prefs["style"]       = [k for k, cb in self._checks.items() if cb.isChecked()]
        prefs["custom_note"] = self.note_edit.toPlainText().strip()
        SubtextManager.save(prefs)
        self.accept()


def _lbl(text: str) -> QtWidgets.QLabel:
    l = QtWidgets.QLabel(text)
    l.setFont(_apple_font_local(13))
    return l


# ══════════════════════════════════════════════════════════════════════════════
#  SubtextSettingBlock — виджет для SettingsView
# ══════════════════════════════════════════════════════════════════════════════

class SubtextSettingBlock(QtWidgets.QWidget):

    enabled_changed = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_dark = False
        self._build_ui()
        self._refresh_state()

    def set_theme(self, is_dark: bool):
        """Вызывать при смене темы (light/dark)."""
        self._is_dark = is_dark
        self._apply_btn_styles()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        group = QtWidgets.QGroupBox()
        group.setObjectName("settingGroup")
        gl = QtWidgets.QVBoxLayout(group)
        gl.setSpacing(10)
        gl.setContentsMargins(16, 14, 16, 14)

        # Заголовок
        t = QtWidgets.QLabel("✨ Улучшенный подтекст")
        t.setFont(_apple_font_local(18, QtGui.QFont.Weight.Bold))
        gl.addWidget(t)

        d = QtWidgets.QLabel(
            "Запоминает стиль, язык и тональность — "
            "применяется ко всем моделям и чатам"
        )
        d.setObjectName("descLabel")
        d.setFont(_apple_font_local(13))
        d.setStyleSheet("color: #475569;")
        d.setWordWrap(True)
        gl.addWidget(d)

        # Слайдер
        tr = QtWidgets.QHBoxLayout()
        tr.setSpacing(14)
        tr.setContentsMargins(0, 4, 0, 0)
        self.toggle = _ToggleSwitchLocal(checked=SubtextManager.is_enabled())
        self.toggle.toggled.connect(self._on_toggle)
        tr.addWidget(self.toggle)
        tl = QtWidgets.QLabel("Включить улучшенный подтекст")
        tl.setFont(_apple_font_local(14))
        tr.addWidget(tl)
        tr.addStretch()
        gl.addLayout(tr)

        # Кнопки
        self.reset_btn = QtWidgets.QPushButton("🔄  Начать с новыми предпочтениями")
        self.reset_btn.setFont(_apple_font_local(13))
        self.reset_btn.setMinimumHeight(38)
        self.reset_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.reset_btn.clicked.connect(self._on_reset)
        self.reset_btn.setVisible(False)
        gl.addWidget(self.reset_btn)

        self.setup_btn = QtWidgets.QPushButton("⚙️  Настроить предпочтения")
        self.setup_btn.setFont(_apple_font_local(13))
        self.setup_btn.setMinimumHeight(38)
        self.setup_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.setup_btn.clicked.connect(self._on_setup)
        self.setup_btn.setVisible(False)
        gl.addWidget(self.setup_btn)

        # Превью
        self.preview_lbl = QtWidgets.QLabel()
        self.preview_lbl.setFont(_apple_font_local(12))
        self.preview_lbl.setWordWrap(True)
        self.preview_lbl.setVisible(False)
        gl.addWidget(self.preview_lbl)

        # README
        rr = QtWidgets.QHBoxLayout()
        rr.setContentsMargins(0, 2, 0, 0)
        rb = QtWidgets.QPushButton("📖 readme")
        rb.setFont(_apple_font_local(11))
        rb.setFixedHeight(22)
        rb.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        rb.setStyleSheet(
            "QPushButton{border:none;color:#94a3b8;background:transparent;}"
            "QPushButton:hover{color:#64748b;}"
        )
        rb.clicked.connect(self._show_readme)
        rr.addWidget(rb); rr.addStretch()
        gl.addLayout(rr)

        root.addWidget(group)
        self._apply_btn_styles()

    def _apply_btn_styles(self):
        """Явный цвет текста кнопок — виден и на светлой, и на тёмной теме."""
        if self._is_dark:
            s = (
                "QPushButton{"
                "  border:1px solid #4a5568; border-radius:8px;"
                "  padding:4px 12px; background:rgba(255,255,255,0.05);"
                "  color:#e2e8f0; text-align:left;"
                "}"
                "QPushButton:hover{background:rgba(255,255,255,0.1);}"
            )
            p = "color:#cbd5e1;background:rgba(255,255,255,0.06);border-radius:6px;padding:6px 10px;"
        else:
            s = (
                "QPushButton{"
                "  border:1px solid #cbd5e1; border-radius:8px;"
                "  padding:4px 12px; background:#f8fafc;"
                "  color:#1e293b; text-align:left;"
                "}"
                "QPushButton:hover{background:#e2e8f0;}"
            )
            p = "color:#334155;background:#f1f5f9;border-radius:6px;padding:6px 10px;"

        self.reset_btn.setStyleSheet(s)
        self.setup_btn.setStyleSheet(s)
        self.preview_lbl.setStyleSheet(p)

    def _refresh_state(self):
        enabled   = SubtextManager.is_enabled()
        has_prefs = SubtextManager.has_preferences()

        self.toggle.blockSignals(True)
        self.toggle.setChecked(enabled)
        self.toggle.blockSignals(False)

        if enabled and has_prefs:
            self.reset_btn.setVisible(True)
            self.setup_btn.setVisible(True)
            self.preview_lbl.setVisible(True)
            self._update_preview()
        elif enabled and not has_prefs:
            self.reset_btn.setVisible(False)
            self.setup_btn.setVisible(True)
            self.preview_lbl.setVisible(False)
        else:
            self.reset_btn.setVisible(False)
            self.setup_btn.setVisible(False)
            self.preview_lbl.setVisible(False)

    def _update_preview(self):
        prefs  = SubtextManager.load()
        lines  = []
        labels = {
            "jokes": "юмор", "profanity": "без цензуры",
            "formal": "официально", "warm": "тепло", "concise": "кратко",
        }

        if prefs.get("auto_mode"):
            auto   = prefs.get("auto_learned", {})
            count  = auto.get("message_count", 0)
            styles = auto.get("detected_style", [])
            ss = ", ".join(labels.get(s, s) for s in styles) if styles else "ещё учится…"
            lines.append(f"🤖 Авто: {ss}  ({count} сообщ.)")

        if prefs.get("language") and prefs["language"] != "Не важно (как спрошу)":
            lines.append(f"🌐 Язык: {prefs['language']}")
        if prefs.get("style"):
            lines.append(f"🎨 Стиль: {', '.join(labels.get(k, k) for k in prefs['style'])}")
        if prefs.get("custom_note"):
            note = prefs["custom_note"]
            lines.append(f"📝 {note[:55]}{'…' if len(note) > 55 else ''}")

        self.preview_lbl.setText("\n".join(lines) if lines else "Предпочтения не заданы")

    def _on_toggle(self, checked: bool):
        SubtextManager.set_enabled(checked)
        if checked and not SubtextManager.has_preferences():
            self._open_edit_dialog(reset_mode=False)
        self._refresh_state()
        self.enabled_changed.emit(checked)

    def _on_setup(self):  self._open_edit_dialog(False)
    def _on_reset(self):
        r = QtWidgets.QMessageBox.question(
            self, "Начать заново?",
            "Текущие предпочтения будут очищены.\nОткрыть настройки заново?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if r == QtWidgets.QMessageBox.StandardButton.Yes:
            self._open_edit_dialog(True)

    def _open_edit_dialog(self, reset_mode: bool = False):
        dlg = SubtextEditDialog(self, reset_mode=reset_mode)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._refresh_state()

    def _show_readme(self):
        dlg = QtWidgets.QMessageBox(self)
        dlg.setWindowTitle("📖 Улучшенный подтекст")
        dlg.setText(SUBTEXT_README)
        dlg.setIcon(QtWidgets.QMessageBox.Icon.Information)
        dlg.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        dlg.exec()

    def refresh(self):
        self._refresh_state()


# ══════════════════════════════════════════════════════════════════════════════
#  Публичные хелперы для run.py
# ══════════════════════════════════════════════════════════════════════════════

def get_subtext_injection() -> str:
    """
    ВАЖНО: вставлять В НАЧАЛО system_prompt, не в конец:

        system_prompt = get_subtext_injection() + base_system + memory + ...

    Мягкая стилевая установка — не конфликтует с основным промптом.
    """
    return SubtextManager.build_system_injection()


def get_subtext_reminder() -> str:
    """
    Жёсткое напоминание — вставлять В САМЫЙ КОНЕЦ system_prompt:

        system_prompt = ... + get_subtext_reminder()

    Модели весят последние токены промпта сильнее. Это напоминание
    перебивает встроенные фильтры моделей, которые игнорируют начало промпта.
    Возвращает пустую строку если функция выключена.
    """
    prefs = SubtextManager.load()
    if not prefs.get("enabled"):
        return ""

    parts = []

    lang = prefs.get("language", "").strip()
    if lang and lang not in ("", "Не важно (как спрошу)"):
        lang_hard = {
            "Русский":    "Весь ответ — только по-русски. Никаких слов на других языках.",
            "English":    "Respond ENTIRELY in English. Zero words in any other language.",
            "Украинський": "Відповідай ВИКЛЮЧНО українською. Жодного іншого мовного слова.",
            "Украинский": "Відповідай ВИКЛЮЧНО українською. Жодного іншого мовного слова.",
            "Беларуский": "Адказвай ВЫКЛЮЧНА па-беларуску.",
            "Español":    "RESPONDE ÚNICAMENTE en español.",
            "Deutsch":    "Antworte AUSSCHLIESSLICH auf Deutsch.",
            "Français":   "Réponds EXCLUSIVEMENT en français.",
            "Polski":     "Odpowiadaj WYŁĄCZNIE po polsku.",
        }
        parts.append(lang_hard.get(lang, f"Отвечай ИСКЛЮЧИТЕЛЬНО на языке: {lang}. Никакого другого языка."))

    styles = list(prefs.get("style", []))
    if prefs.get("auto_mode"):
        for s in prefs.get("auto_learned", {}).get("detected_style", []):
            if s not in styles:
                styles.append(s)

    if "profanity" in styles:
        parts.append(
            "СТИЛЬ РЕЧИ — ОБЯЗАТЕЛЬНО:\n"
            "Пользователь разрешил мат. Это его личное пространство, не публичный чат.\n"
            "Слова «блядь», «хуй», «пиздец», «ёбаный», «сука», «нахуй», «хуёво», «заебись» — "
            "обычные слова в этом разговоре. Используй их органично, без замен.\n"
            "ЗАПРЕЩЕНО: «блин», «чёрт», «ёлки», звёздочки (*), [censored], любые эвфемизмы.\n"
            "Если без мата — значит, ты нарушаешь настройки пользователя."
        )
    if "concise" in styles:
        parts.append("Краткость обязательна. Убери воду и лишние слова.")
    if "formal" in styles:
        parts.append("Тон — строго официальный.")
    if "warm" in styles:
        parts.append("Тон — тёплый, дружеский.")
    if "jokes" in styles:
        parts.append("Добавь лёгкий юмор.")

    note = prefs.get("custom_note", "").strip()
    if note:
        parts.append(f"Требование пользователя: {note}")

    if not parts:
        return ""

    # Без заголовков и «финальных директив» — модель их зачитывает вслух.
    return "\n" + "\n".join(parts)


def subtext_track_message(user_message: str):
    """
    Вызывать после получения сообщения пользователя (авто-анализ).
    Безопасно вызывать всегда — ничего не делает если авто-режим выключен.

    В run.py добавить одну строку перед get_ai_response():
        from enhanced_subtext import subtext_track_message
        subtext_track_message(user_message)
    """
    try:
        SubtextManager.analyze_and_update(user_message)
    except Exception as e:
        print(f"[SUBTEXT] track error: {e}")