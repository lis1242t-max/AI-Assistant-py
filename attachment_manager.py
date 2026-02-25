"""
attachment_manager.py — Менеджер прикрепления файлов.

macOS особенности:
  - Скриншоты из Finder: file:// URL → hasUrls()
  - Скриншоты drag из превью уведомления: raw QImage → hasImage()
  - Оба случая обрабатываются

Возможности:
  - Drag & Drop файлов и скриншотов macOS
  - Ctrl+V вставка файлов и изображений из буфера
  - Анимированный drop-overlay при перетаскивании
  - Выбор файла через диалог
"""

import os
import tempfile
import shutil
from datetime import datetime
from PyQt6 import QtWidgets, QtGui, QtCore

try:
    from vision_handler import is_image_file
except ImportError:
    def is_image_file(path):
        return os.path.splitext(path)[1].lower() in {
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"
        }

# Расширения текстовых файлов для предпросмотра
_TEXT_EXTENSIONS_AM = {
    '.txt', '.md', '.py', '.js', '.ts', '.html', '.css', '.json', '.xml',
    '.csv', '.log', '.yaml', '.yml', '.ini', '.cfg', '.toml', '.sh',
    '.bat', '.c', '.cpp', '.h', '.java', '.rs', '.go', '.php', '.rb',
    '.swift', '.kt', '.sql', '.env', '.gitignore',
}

def is_text_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _TEXT_EXTENSIONS_AM

MAX_ATTACHED_FILES = 5


class AttachmentMixin:
    """Миксин для MainWindow — вся логика прикрепления файлов."""

    # ═══════════════════════════════════════════════════════════════
    # ПРИКРЕПЛЕНИЕ ФАЙЛОВ
    # ═══════════════════════════════════════════════════════════════

    def attach_file(self):
        """Выбрать и прикрепить файл через диалог."""
        if len(self.attached_files) >= MAX_ATTACHED_FILES:
            return

        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Выбрать файл", "",
            "Все файлы (*.*);;Изображения (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;"
            "Текстовые файлы (*.txt *.md *.py *.js *.json)"
        )
        self.activateWindow()
        self.raise_()
        if file_path:
            self._add_file(file_path, source="[ATTACH]")
        self.input_field.setFocus()

    def paste_from_clipboard(self):
        """Вставка файлов и изображений через Ctrl+V."""
        clipboard = QtWidgets.QApplication.clipboard()
        mime = clipboard.mimeData()

        if mime.hasUrls():
            added = 0
            for url in mime.urls():
                if url.isLocalFile():
                    fp = url.toLocalFile()
                    if os.path.isfile(fp):
                        if len(self.attached_files) >= MAX_ATTACHED_FILES:
                            self._warn_limit()
                            break
                        self._add_file(fp, source="[PASTE]")
                        added += 1
            if added:
                return

        if mime.hasImage():
            image = clipboard.image()
            if not image.isNull():
                if len(self.attached_files) >= MAX_ATTACHED_FILES:
                    self._warn_limit()
                    return
                tmp_path = self._save_image_to_temp(image, prefix="paste")
                if tmp_path:
                    self._add_file(tmp_path, source="[PASTE]")
                return

        if mime.hasText():
            self.input_field.paste()

    def _add_file(self, file_path: str, source: str = "[ATTACH]"):
        """Добавить файл в список и обновить UI."""
        if len(self.attached_files) >= MAX_ATTACHED_FILES:
            self._warn_limit()
            return

        resolved = self.copy_file_to_chat_dir(file_path, self.current_chat_id)

        if resolved and os.path.exists(resolved):
            if resolved not in self.attached_files:
                self.attached_files.append(resolved)
                print(f"{source} ✅ {os.path.basename(resolved)}")
            else:
                print(f"{source} ⚠️ Уже прикреплён: {os.path.basename(resolved)}")
        else:
            print(f"{source} ✗ Файл не найден: {file_path}")
            QtWidgets.QMessageBox.warning(
                self, "Ошибка прикрепления",
                f"Не удалось прикрепить:\n{os.path.basename(file_path)}",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
        self.update_file_chips()

    def _save_image_to_temp(self, image, prefix: str = "image") -> str:
        """Сохраняет QImage во временный PNG."""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            tmp_path = os.path.join(tempfile.gettempdir(), f"{prefix}_{ts}.png")
            if image.save(tmp_path, "PNG"):
                print(f"[IMG] 🖼️ Сохранено: {tmp_path}")
                return tmp_path
            return None
        except Exception as e:
            print(f"[IMG] ❌ {e}")
            return None

    def _warn_limit(self):
        QtWidgets.QMessageBox.warning(
            self, "Лимит файлов",
            "Можно прикрепить максимум 5 файлов.",
            QtWidgets.QMessageBox.StandardButton.Ok
        )

    def clear_attached_file(self, file_path=None):
        if file_path is None:
            self.attached_files = []
        elif file_path in self.attached_files:
            self.attached_files.remove(file_path)
        self.update_file_chips()
        self.input_field.setFocus()

    # ═══════════════════════════════════════════════════════════════
    # УПРАВЛЕНИЕ ФАЙЛАМИ ЧАТОВ
    # ═══════════════════════════════════════════════════════════════

    def copy_file_to_chat_dir(self, source_path: str, chat_id: int) -> str:
        try:
            source_path = os.path.normpath(os.path.abspath(source_path))
            return source_path if os.path.exists(source_path) else None
        except Exception as e:
            print(f"[CHAT_FILES] ✗ {e}")
            return None

    def load_chat_files(self, chat_id: int) -> list:
        try:
            chat_dir = os.path.normpath(
                os.path.join(os.path.abspath(self.chat_files_dir), f"chat_{chat_id}")
            )
            if not os.path.exists(chat_dir):
                return []
            return [
                os.path.normpath(os.path.join(chat_dir, fn))
                for fn in os.listdir(chat_dir)
                if os.path.isfile(os.path.join(chat_dir, fn))
            ]
        except Exception as e:
            print(f"[LOAD_CHAT_FILES] ✗ {e}")
            return []

    def clear_chat_files(self, chat_id: int) -> bool:
        try:
            d = os.path.join(self.chat_files_dir, f"chat_{chat_id}")
            if os.path.exists(d):
                shutil.rmtree(d)
            return True
        except Exception as e:
            print(f"[CHAT_FILES] ✗ {e}")
            return False

    def clear_all_chat_files(self) -> bool:
        try:
            if os.path.exists(self.chat_files_dir):
                for item in os.listdir(self.chat_files_dir):
                    p = os.path.join(self.chat_files_dir, item)
                    if os.path.isdir(p):
                        shutil.rmtree(p)
            return True
        except Exception as e:
            print(f"[CHAT_FILES] ✗ {e}")
            return False

    # ═══════════════════════════════════════════════════════════════
    # UI — ФАЙЛОВЫЕ ЧИПЫ
    # ═══════════════════════════════════════════════════════════════

    def update_file_chips(self):
        if not hasattr(self, 'file_chip_container'):
            return

        layout = self.file_chip_container.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QtWidgets.QWidget().setLayout(layout)

        if not self.attached_files:
            self.file_chip_container.hide()
            self.input_field.setPlaceholderText("Введите сообщение...")
            return

        self.file_chip_container.show()
        self.input_field.setPlaceholderText("Введите вопрос...")
        is_dark = getattr(self, 'current_theme', 'light') == 'dark'

        grid_layout = QtWidgets.QGridLayout(self.file_chip_container)
        grid_layout.setContentsMargins(25, 4, 25, 4)
        grid_layout.setSpacing(8)

        row, col = 0, 0
        MAX_CHIPS_PER_ROW = 3

        for file_path in self.attached_files:
            file_name = os.path.basename(file_path)
            emoji = "🖼️" if is_image_file(file_path) else ("📄" if is_text_file(file_path) else "📎")

            chip = QtWidgets.QWidget()
            chip.setObjectName("fileChip")
            chip.setStyleSheet("""
                #fileChip { background: rgba(102,126,234,0.20);
                            border: 1px solid rgba(102,126,234,0.40);
                            border-radius: 14px; padding: 2px 6px; }
            """ if is_dark else """
                #fileChip { background: rgba(102,126,234,0.15);
                            border: 1px solid rgba(102,126,234,0.35);
                            border-radius: 14px; padding: 2px 6px; }
            """)

            cl = QtWidgets.QHBoxLayout(chip)
            cl.setContentsMargins(10, 4, 6, 4)
            cl.setSpacing(6)

            dn = file_name if len(file_name) <= 20 else file_name[:17] + "…"
            lbl = QtWidgets.QLabel(f"{emoji} {dn}")
            lbl.setFont(QtGui.QFont("Inter", 11))
            lbl.setStyleSheet(
                "color:#8fa3f5;background:transparent;border:none;" if is_dark
                else "color:#667eea;background:transparent;border:none;"
            )
            cl.addWidget(lbl)

            rb = QtWidgets.QPushButton("✕")
            rb.setFixedSize(22, 22)
            rb.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            rb.setFont(QtGui.QFont("Inter", 10, QtGui.QFont.Weight.Bold))
            rb.setStyleSheet("""
                QPushButton { background:rgba(102,126,234,0.25); color:#8fa3f5;
                              border:none; border-radius:11px; }
                QPushButton:hover { background:rgba(239,68,68,0.30); color:#f87171; }
            """ if is_dark else """
                QPushButton { background:rgba(102,126,234,0.20); color:#667eea;
                              border:none; border-radius:11px; }
                QPushButton:hover { background:rgba(239,68,68,0.25); color:#ef4444; }
            """)
            rb.clicked.connect(lambda checked, p=file_path: self.clear_attached_file(p))
            cl.addWidget(rb)

            # Клик по чипу (не по кнопке удаления) — открывает предпросмотр
            _fp = file_path
            chip.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            chip.mousePressEvent = lambda event, p=_fp: (
                self._preview_file(p)
                if event.button() == QtCore.Qt.MouseButton.LeftButton else None
            )
            lbl.mousePressEvent = lambda event, p=_fp: (
                self._preview_file(p)
                if event.button() == QtCore.Qt.MouseButton.LeftButton else None
            )

            grid_layout.addWidget(chip, row, col)
            col += 1
            if col >= MAX_CHIPS_PER_ROW:
                col = 0
                row += 1

    # ═══════════════════════════════════════════════════════════════
    # DROP OVERLAY
    # ═══════════════════════════════════════════════════════════════

    def _show_drop_overlay(self):
        if not hasattr(self, '_drop_overlay') or self._drop_overlay is None:
            self._drop_overlay = _DropOverlay(self)
        self._drop_overlay.resize(self.size())
        self._drop_overlay.show_animated()
        self._drop_overlay.raise_()

    def _hide_drop_overlay(self):
        if hasattr(self, '_drop_overlay') and self._drop_overlay is not None:
            self._drop_overlay.hide_animated()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_drop_overlay') and self._drop_overlay is not None:
            self._drop_overlay.resize(self.size())

    # ═══════════════════════════════════════════════════════════════
    # КЛАВИАТУРА — CTRL+V
    # ═══════════════════════════════════════════════════════════════

    def keyPressEvent(self, event):
        is_ctrl_v = (
            event.modifiers() == QtCore.Qt.KeyboardModifier.ControlModifier
            and event.key() == QtCore.Qt.Key.Key_V
        )
        if is_ctrl_v:
            mime = QtWidgets.QApplication.clipboard().mimeData()
            if mime.hasUrls() or mime.hasImage():
                self.paste_from_clipboard()
                event.accept()
                return
        super().keyPressEvent(event)

    # ═══════════════════════════════════════════════════════════════
    # DRAG-AND-DROP
    # ═══════════════════════════════════════════════════════════════

    def dragEnterEvent(self, event):
        mime = event.mimeData()

        # Случай 1: файлы как URL (Finder, Explorer, стандартный drag)
        # На macOS скриншоты из Finder ВСЕГДА идут как file:// URL
        if mime.hasUrls():
            urls = mime.urls()
            # Проверяем что есть хотя бы один непустой file:// URL
            has_real_file = any(
                (url.isLocalFile() or url.scheme() == "file") and url.toLocalFile()
                for url in urls
            )
            if has_real_file:
                event.acceptProposedAction()
                self._show_drop_overlay()
                return
            # URL есть, но все пустые — macOS скриншот, проверим hasImage() ниже

        # Случай 2: raw image data (drag скриншота из превью/уведомления macOS)
        if mime.hasImage():
            event.acceptProposedAction()
            self._show_drop_overlay()
            return

        event.ignore()

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._hide_drop_overlay()

    def dropEvent(self, event):
        self._hide_drop_overlay()
        mime = event.mimeData()

        # ── Случай 1: URL-файлы ───────────────────────────────────────────
        # ВАЖНО: macOS при drag скриншота иногда добавляет hasUrls()=True,
        # но сами URL пустые (""). В этом случае надо падать на hasImage().
        if mime.hasUrls():
            import urllib.parse
            urls = mime.urls()
            real_files = []
            for url in urls:
                file_path = url.toLocalFile()
                if not file_path:
                    raw = url.toString()
                    if raw.startswith("file://"):
                        file_path = urllib.parse.unquote(raw[7:])
                if file_path and os.path.exists(file_path):
                    real_files.append(file_path)
                elif file_path:
                    print(f"[DRAG-DROP] ✗ Файл не существует: {file_path}")
                # url пустой — молча пропускаем, перейдём к hasImage() ниже

            if real_files:
                # Есть настоящие файлы — обрабатываем
                for file_path in real_files:
                    if len(self.attached_files) >= MAX_ATTACHED_FILES:
                        self._warn_limit()
                        break
                    self._add_file(file_path, source="[DRAG-DROP]")
                print(f"[DRAG-DROP] ✅ Прикреплено: {len(real_files)}")
                event.acceptProposedAction()
                return
            # real_files пустой — все URL оказались пустыми (macOS скриншот)
            # Падаем дальше на hasImage()

        # ── Случай 2: Raw image (macOS drag скриншота) ────────────────────
        # Сюда попадаем при:
        #   - hasImage()=True и hasUrls()=False
        #   - hasImage()=True и hasUrls()=True, но все URL пустые
        if mime.hasImage():
            image = mime.imageData()
            if image and not image.isNull():
                if len(self.attached_files) >= MAX_ATTACHED_FILES:
                    self._warn_limit()
                    event.ignore()
                    return
                tmp_path = self._save_image_to_temp(image, prefix="screenshot")
                if tmp_path:
                    self._add_file(tmp_path, source="[DRAG-IMG]")
                    print("[DRAG-DROP] ✅ Скриншот macOS прикреплён")
                    event.acceptProposedAction()
                    return

        event.ignore()


# ═══════════════════════════════════════════════════════════════════════════
# DROP OVERLAY WIDGET
# ═══════════════════════════════════════════════════════════════════════════

class _DropOverlay(QtWidgets.QWidget):
    """
    Анимированный полупрозрачный оверлей при drag-and-drop.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._opacity = 0.0
        self._target = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def show_animated(self):
        self._target = 1.0
        if not self._timer.isActive():
            self._timer.start(12)
        super().show()
        self.raise_()

    def hide_animated(self):
        self._target = 0.0
        if not self._timer.isActive():
            self._timer.start(12)

    def _tick(self):
        diff = self._target - self._opacity
        self._opacity += diff * 0.25
        if abs(diff) < 0.01:
            self._opacity = self._target
            self._timer.stop()
            if self._opacity <= 0.0:
                super().hide()
        self.update()

    def paintEvent(self, event):
        try:
            painter = QtGui.QPainter(self)
            if not painter.isActive():
                return
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

            t = self._opacity

            # Фон — тёмное стекло
            painter.fillRect(self.rect(), QtGui.QColor(10, 12, 28, int(t * 210)))

            if t < 0.15:
                painter.end()
                return

            w, h = self.width(), self.height()
            cx, cy = w // 2, h // 2

            # Пунктирная рамка
            margin = 32
            r = QtCore.QRectF(margin, margin, w - margin * 2, h - margin * 2)
            pen = QtGui.QPen(QtGui.QColor(102, 126, 234, int(t * 220)), 2.5,
                             QtCore.Qt.PenStyle.DashLine)
            pen.setDashPattern([10, 7])
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor(102, 126, 234, int(t * 20)))
            painter.drawRoundedRect(r, 28, 28)

            # ── Иконка файла ─────────────────────────────────────────────
            s = 80           # размер иконки
            ix = cx - s // 2
            iy = cy - s // 2 - 44
            fold = 20
            icon_c = QtGui.QColor(102, 126, 234, int(t * 255))

            painter.setPen(QtGui.QPen(icon_c, 2.2))
            painter.setBrush(QtGui.QColor(102, 126, 234, int(t * 28)))

            body = QtGui.QPolygonF([
                QtCore.QPointF(ix,          iy + fold),
                QtCore.QPointF(ix,          iy + s),
                QtCore.QPointF(ix + s,      iy + s),
                QtCore.QPointF(ix + s,      iy),
                QtCore.QPointF(ix + fold,   iy),
            ])
            painter.drawPolygon(body)

            fold_path = QtGui.QPainterPath()
            fold_path.moveTo(ix, iy + fold)
            fold_path.lineTo(ix + fold, iy + fold)
            fold_path.lineTo(ix + fold, iy)
            painter.setBrush(QtGui.QColor(102, 126, 234, int(t * 60)))
            painter.drawPath(fold_path)

            # "+" по центру иконки
            painter.setPen(QtGui.QPen(icon_c, 3.5, QtCore.Qt.PenStyle.SolidLine))
            pcx = ix + s // 2
            pcy = iy + s // 2 + 6
            pl = 16
            painter.drawLine(int(pcx - pl), int(pcy), int(pcx + pl), int(pcy))
            painter.drawLine(int(pcx), int(pcy - pl), int(pcx), int(pcy + pl))

            # ── Тексты ───────────────────────────────────────────────────
            painter.setPen(QtGui.QPen(QtGui.QColor(225, 230, 255, int(t * 255))))
            f1 = QtGui.QFont("Inter", 24, QtGui.QFont.Weight.Bold)
            painter.setFont(f1)
            painter.drawText(
                QtCore.QRectF(0, cy + 54, w, 38),
                QtCore.Qt.AlignmentFlag.AlignHCenter,
                "Перетащите файлы сюда"
            )

            painter.setPen(QtGui.QPen(QtGui.QColor(150, 160, 210, int(t * 200))))
            f2 = QtGui.QFont("Inter", 14)
            painter.setFont(f2)
            painter.drawText(
                QtCore.QRectF(0, cy + 98, w, 28),
                QtCore.Qt.AlignmentFlag.AlignHCenter,
                "Изображения, документы, любые файлы"
            )

            painter.end()
        except Exception:
            pass