"""
model_downloader.py — диалоги и утилиты для скачивания/удаления моделей Ollama.

Экспортирует:
    check_model_in_ollama(model_name) -> bool
    get_ollama_models_dir() -> str
    set_ollama_models_env_and_restart(new_models_dir) -> (bool, str)
    delete_model_files_from_disk(ollama_model_name, models_dir) -> (int, list)
    LlamaDownloadDialog(parent)
    DeepSeekDownloadDialog(parent)
"""

import os
import sys
import json
import subprocess
import threading

import requests
from PyQt6 import QtWidgets, QtGui, QtCore

# ── Платформа ────────────────────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"

# ── Константы DeepSeek (берём из deepseek_config или fallback) ───────────
try:
    from deepseek_config import DEEPSEEK_MODEL_NAME, DEEPSEEK_OLLAMA_PULL
except ImportError:
    DEEPSEEK_MODEL_NAME = "deepseek-llm:7b-chat"
    DEEPSEEK_OLLAMA_PULL = "ollama pull deepseek-llm:7b-chat"

# ── OLLAMA_HOST (берём из llama_handler или fallback) ───────────────────
try:
    from llama_handler import OLLAMA_HOST
except ImportError:
    OLLAMA_HOST = "http://localhost:11434"


# ══════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ══════════════════════════════════════════════════════════════════════════

def check_model_in_ollama(model_name: str) -> bool:
    """Проверяет, установлена ли модель в Ollama локально."""
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if resp.status_code == 200:
            for m in resp.json().get("models", []):
                name = m.get("name", "")
                if name == model_name or name.startswith(model_name.split(":")[0] + ":"):
                    return True
        return False
    except Exception:
        return False


def get_ollama_models_dir() -> str:
    r"""
    Возвращает реальный путь к папке с файлами моделей Ollama.
    Порядок: OLLAMA_MODELS env → путь по умолчанию для ОС.
    (~/.ollama/models  или  %USERPROFILE%\.ollama\models)
    """
    env_val = os.environ.get("OLLAMA_MODELS", "").strip()
    if env_val and os.path.isdir(env_val):
        return env_val
    if IS_WINDOWS:
        base = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        return os.path.join(base, ".ollama", "models")
    return os.path.join(os.path.expanduser("~"), ".ollama", "models")


def set_ollama_models_env_and_restart(new_models_dir: str) -> tuple:
    """
    Устанавливает OLLAMA_MODELS и перезапускает сервер Ollama.
    Возвращает (success: bool, error_msg: str).
    """
    import time as _time

    popen_kw = {}
    if IS_WINDOWS:
        popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        if IS_WINDOWS:
            subprocess.run(
                ["setx", "OLLAMA_MODELS", new_models_dir],
                timeout=10, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_kw
            )
            subprocess.run(
                ["net", "stop", "Ollama"],
                timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_kw
            )
            _time.sleep(2)
            subprocess.run(
                ["net", "start", "Ollama"],
                timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_kw
            )
        else:
            # macOS / Linux — убиваем и перезапускаем
            subprocess.run(
                ["pkill", "-f", "ollama serve"],
                timeout=10, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            subprocess.run(
                ["pkill", "-f", "Ollama.app"],
                timeout=5, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            _time.sleep(1)
            # macOS launchd
            try:
                subprocess.run(
                    ["launchctl", "setenv", "OLLAMA_MODELS", new_models_dir],
                    timeout=5, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
            except Exception:
                pass
            # Устанавливаем в текущей сессии
            os.environ["OLLAMA_MODELS"] = new_models_dir
            # Запускаем ollama serve в фоне
            env = os.environ.copy()
            env["OLLAMA_MODELS"] = new_models_dir
            subprocess.Popen(
                ["ollama", "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Ждём готовности сервера
        _time.sleep(3)
        for _ in range(10):
            try:
                resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
                if resp.status_code == 200:
                    return True, ""
            except Exception:
                pass
            _time.sleep(1)

        return True, ""   # Возможно запустился, но API ещё не ответил
    except Exception as e:
        return False, str(e)


def delete_model_files_from_disk(ollama_model_name: str, models_dir: str) -> tuple:
    """
    Физически удаляет файлы модели с диска.

    Структура Ollama:
        models/manifests/registry.ollama.ai/library/<model>/<tag>
        models/blobs/sha256-<hash>

    Возвращает (bytes_freed: int, deleted_files: list).
    """
    import shutil as _shutil

    deleted_files = []
    bytes_freed   = 0

    model_base = ollama_model_name.split(":")[0]
    model_tag  = ollama_model_name.split(":")[1] if ":" in ollama_model_name else "latest"

    manifest_root = os.path.join(
        models_dir, "manifests", "registry.ollama.ai", "library"
    )
    manifest_path = os.path.join(manifest_root, model_base, model_tag)
    if not os.path.isfile(manifest_path):
        manifest_path = os.path.join(manifest_root, model_base, "latest")

    blobs_to_delete = set()

    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            for layer in manifest_data.get("layers", []):
                digest = layer.get("digest", "")
                if digest:
                    blobs_to_delete.add(digest.replace(":", "-"))
            cfg_digest = manifest_data.get("config", {}).get("digest", "")
            if cfg_digest:
                blobs_to_delete.add(cfg_digest.replace(":", "-"))
        except Exception as e:
            print(f"[DELETE_FILES] Ошибка чтения manifest: {e}")

        # Удаляем папку манифеста
        try:
            model_manifest_dir = os.path.join(manifest_root, model_base)
            sz = sum(
                os.path.getsize(os.path.join(r, fn))
                for r, _, files in os.walk(model_manifest_dir)
                for fn in files
            )
            _shutil.rmtree(model_manifest_dir, ignore_errors=True)
            bytes_freed += sz
            deleted_files.append(model_manifest_dir)
        except Exception as e:
            print(f"[DELETE_FILES] Ошибка удаления manifest dir: {e}")

    # Удаляем blob-файлы
    blobs_dir = os.path.join(models_dir, "blobs")
    if os.path.isdir(blobs_dir):
        for blob_ref in blobs_to_delete:
            blob_path = os.path.join(blobs_dir, blob_ref)
            if os.path.isfile(blob_path):
                try:
                    sz = os.path.getsize(blob_path)
                    os.remove(blob_path)
                    bytes_freed += sz
                    deleted_files.append(blob_path)
                except Exception as e:
                    print(f"[DELETE_FILES] Ошибка удаления blob {blob_path}: {e}")

    return bytes_freed, deleted_files


# ══════════════════════════════════════════════════════════════════════════
# БАЗОВЫЙ ДИАЛОГ СКАЧИВАНИЯ
# ══════════════════════════════════════════════════════════════════════════

class _BaseDownloadDialog(QtWidgets.QDialog):
    """
    Общая основа для диалогов скачивания моделей.
    Подклассы переопределяют MODEL_CMD, MODEL_LABEL, MODEL_SIZE.
    """

    download_finished = QtCore.pyqtSignal(bool, str)

    MODEL_CMD   = ""
    MODEL_LABEL = "⬇  Скачивание модели"
    MODEL_SIZE  = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Скачивание модели")
        self._download_process = None
        self._cancelled = False
        self._models_dir = ""

        self._is_dark = True
        if parent and hasattr(parent, "current_theme"):
            self._is_dark = parent.current_theme == "dark"

        if IS_WINDOWS:
            self.setWindowFlags(
                QtCore.Qt.WindowType.Dialog |
                QtCore.Qt.WindowType.WindowTitleHint |
                QtCore.Qt.WindowType.WindowCloseButtonHint
            )
        else:
            self.setWindowFlags(
                QtCore.Qt.WindowType.Dialog |
                QtCore.Qt.WindowType.FramelessWindowHint
            )
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)

        self._build_ui()
        self.download_finished.connect(self._on_download_finished)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        d = self._is_dark
        win = IS_WINDOWS

        if d:
            card_bg   = "rgb(22,22,32)"    if win else "rgba(22,22,32,0.98)"
            card_bdr  = "rgba(75,75,105,0.75)"
            title_col = "#e4e4f4"; desc_col = "#8888aa"; status_col = "#8899dd"
            pb_bg     = "rgba(40,40,60,0.85)"; pb_bdr = "rgba(70,70,100,0.55)"; pb_txt = "#d0d0f0"
            dir_bg    = "rgb(30,30,45)"    if win else "rgba(30,30,45,0.80)"
            dir_bdr   = "rgba(70,70,100,0.55)"; dir_col = "#aaaacc"
            br_bg     = "rgba(60,60,95,0.80)"; br_hv = "rgba(80,80,120,0.95)"; br_col = "#ccccee"
        else:
            card_bg   = "rgb(248,248,255)" if win else "rgba(248,248,255,0.99)"
            card_bdr  = "rgba(200,205,235,0.90)"
            title_col = "#1a1a40"; desc_col = "#6677aa"; status_col = "#5566bb"
            pb_bg     = "rgba(225,228,248,0.90)"; pb_bdr = "rgba(180,190,225,0.70)"; pb_txt = "#2a2a60"
            dir_bg    = "rgb(235,238,252)" if win else "rgba(235,238,252,0.90)"
            dir_bdr   = "rgba(180,190,225,0.70)"; dir_col = "#4455aa"
            br_bg     = "rgba(102,126,234,0.12)"; br_hv = "rgba(102,126,234,0.25)"; br_col = "#3344aa"

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4 if win else 14, 4 if win else 14,
                                4 if win else 14, 4 if win else 14)

        card = QtWidgets.QFrame()
        card.setObjectName("dlCard")
        card.setStyleSheet(
            f"QFrame#dlCard {{ background:{card_bg}; border:1px solid {card_bdr}; border-radius:20px; }}"
        )
        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(26, 22, 26, 22)
        cl.setSpacing(12)
        root.addWidget(card)

        # Заголовок
        title = QtWidgets.QLabel(self.MODEL_LABEL)
        title.setStyleSheet(
            f"color:{title_col};font-size:17px;font-weight:700;background:transparent;border:none;"
        )
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(title)

        # Описание
        desc_text = f"Размер модели: {self.MODEL_SIZE}\n" if self.MODEL_SIZE else ""
        desc_text += "Выберите папку и нажмите «Начать скачивание»."
        desc = QtWidgets.QLabel(desc_text)
        desc.setStyleSheet(f"color:{desc_col};font-size:12px;background:transparent;border:none;")
        desc.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        cl.addWidget(desc)

        # Выбор папки
        dir_row = QtWidgets.QHBoxLayout()
        dir_row.setSpacing(6)
        ico = QtWidgets.QLabel("💾")
        ico.setStyleSheet("background:transparent;border:none;font-size:14px;")
        ico.setFixedWidth(20)
        dir_row.addWidget(ico)

        self.dir_label = QtWidgets.QLabel("Папка по умолчанию (Ollama)")
        self.dir_label.setStyleSheet(
            f"color:{dir_col};font-size:11px;background:{dir_bg};"
            f"border:1px solid {dir_bdr};border-radius:7px;padding:4px 8px;"
        )
        dir_row.addWidget(self.dir_label, stretch=1)

        browse_btn = QtWidgets.QPushButton("📂 Выбрать")
        browse_btn.setFixedHeight(30)
        browse_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        browse_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        browse_btn.setStyleSheet(
            f"QPushButton{{background:{br_bg};color:{br_col};border:1px solid {dir_bdr};"
            f"border-radius:7px;font-size:11px;font-weight:600;padding:0 10px;}}"
            f"QPushButton:hover{{background:{br_hv};}}"
        )
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        cl.addLayout(dir_row)

        hint = QtWidgets.QLabel("Выберите диск/папку с достаточным свободным местом")
        hint.setStyleSheet(f"color:{desc_col};font-size:10px;background:transparent;border:none;")
        hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(hint)

        # Прогресс-бар
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(22)
        self.progress_bar.setStyleSheet(
            f"QProgressBar{{background:{pb_bg};border:1px solid {pb_bdr};"
            f"border-radius:8px;color:{pb_txt};font-size:11px;text-align:center;}}"
            f"QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #667eea,stop:1 #764ba2);border-radius:7px;}}"
        )
        cl.addWidget(self.progress_bar)

        # Статус
        self.status_label = QtWidgets.QLabel("Нажмите «Начать» для скачивания")
        self.status_label.setStyleSheet(
            f"color:{status_col};font-size:12px;background:transparent;border:none;"
        )
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        cl.addWidget(self.status_label)

        # Кнопки
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(10)

        self.start_btn = QtWidgets.QPushButton("⬇  Начать скачивание")
        self.start_btn.setFixedHeight(40)
        self.start_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.start_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.start_btn.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #667eea,stop:1 #764ba2);color:#fff;border:none;"
            "border-radius:11px;font-size:13px;font-weight:700;}"
            "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #7b8ff5,stop:1 #8860b8);}"
            "QPushButton:disabled{background:rgba(100,100,140,0.45);color:#9999bb;}"
        )
        self.start_btn.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QtWidgets.QPushButton("✕  Пропустить")
        self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.cancel_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.cancel_btn.setStyleSheet(
            "QPushButton{background:rgba(180,55,55,0.65);color:#f0f0f8;"
            "border:1px solid rgba(200,75,75,0.5);border-radius:11px;"
            "font-size:13px;font-weight:600;}"
            "QPushButton:hover{background:rgba(205,65,65,0.82);}"
        )
        self.cancel_btn.clicked.connect(self._cancel_download)
        btn_row.addWidget(self.cancel_btn)
        cl.addLayout(btn_row)

        self.adjustSize()
        self.setMinimumWidth(520)

    # ── Выбор папки ───────────────────────────────────────────────────────
    def _browse_dir(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Выберите папку для хранения моделей", "",
            QtWidgets.QFileDialog.Option.ShowDirsOnly
        )
        if not folder:
            return
        self._models_dir = folder
        display = folder if len(folder) <= 42 else "…" + folder[-40:]
        self.dir_label.setText(display)
        self.dir_label.setToolTip(folder)
        # Проверяем свободное место
        try:
            import shutil
            free_gb = shutil.disk_usage(folder).free / (1024 ** 3)
            needed_gb = 6.0
            if free_gb < needed_gb:
                QtWidgets.QMessageBox.warning(
                    self, "Мало места",
                    f"⚠️ На выбранном диске только {free_gb:.1f} GB свободно.\n\n"
                    f"Рекомендуется минимум {needed_gb:.0f} GB.\n"
                    "Выберите другой диск или освободите место."
                )
            else:
                self.status_label.setText(
                    f"✅ Свободно: {free_gb:.1f} GB — достаточно для скачивания"
                )
        except Exception:
            pass

    # ── Запуск ────────────────────────────────────────────────────────────
    def _on_start_clicked(self):
        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳  Скачивание…")
        self.status_label.setText("Инициализация…")
        self._cancelled = False
        self._thread = threading.Thread(target=self._download_thread, daemon=True)
        self._thread.start()

    # Совместимость — вызывается снаружи если нужно запустить без кнопки
    def start_download(self):
        self._on_start_clicked()

    # ── Поток скачивания ──────────────────────────────────────────────────
    def _download_thread(self):
        try:
            import re as _re

            # Шаг 1: если выбрана нестандартная папка — перезапускаем сервер
            if self._models_dir:
                self._set_status(0, "🔄 Настройка папки — перезапуск Ollama…")
                ok, err = set_ollama_models_env_and_restart(self._models_dir)
                if not ok:
                    self.download_finished.emit(False, f"Не удалось настроить папку: {err}")
                    return
                self._set_status(0, "✅ Папка настроена. Начинаем скачивание…")

            # Шаг 2: ollama pull
            cmd = self.MODEL_CMD.split()
            kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, bufsize=1)
            if IS_WINDOWS:
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            self._download_process = subprocess.Popen(cmd, **kwargs)

            for line in self._download_process.stdout:
                if self._cancelled:
                    break
                line = line.strip()
                if not line:
                    continue
                pct_m = _re.search(r'(\d+)%', line)
                if pct_m:
                    pct     = int(pct_m.group(1))
                    size_m  = _re.search(r'([\d.]+)\s*GB/([\d.]+)\s*GB', line)
                    spd_m   = _re.search(r'([\d.]+)\s*(MB|KB)/s', line)
                    eta_m   = _re.search(r'(\d+m\d+s|\d+s)', line)
                    parts   = [f"{pct}%"]
                    if size_m: parts.append(f"({size_m.group(1)} / {size_m.group(2)} GB)")
                    if spd_m:  parts.append(f"— {spd_m.group(1)} {spd_m.group(2)}/s")
                    if eta_m:  parts.append(f"| осталось ~{eta_m.group(1)}")
                    self._set_status(pct, " ".join(parts))
                elif any(w in line.lower() for w in ("success", "done", "complete")):
                    self._set_status(100, "✅ Готово!")

            ret = self._download_process.wait()
            if self._cancelled:
                self.download_finished.emit(False, "Отменено пользователем")
            elif ret == 0:
                self.download_finished.emit(True, "Скачивание завершено!")
            else:
                self.download_finished.emit(False, f"Ошибка скачивания (код {ret})")
        except FileNotFoundError:
            self.download_finished.emit(
                False, "Ollama не найдена. Убедитесь что Ollama установлена и запущена."
            )
        except Exception as e:
            self.download_finished.emit(False, f"Ошибка: {e}")

    def _set_status(self, pct: int, text: str):
        QtCore.QMetaObject.invokeMethod(
            self, "_update_progress",
            QtCore.Qt.ConnectionType.QueuedConnection,
            QtCore.Q_ARG(int, pct),
            QtCore.Q_ARG(str, text),
        )

    @QtCore.pyqtSlot(int, str)
    def _update_progress(self, value: int, status: str):
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def _cancel_download(self):
        self._cancelled = True
        if self._download_process:
            try:
                self._download_process.terminate()
            except Exception:
                pass
        self.reject()

    @QtCore.pyqtSlot(bool, str)
    def _on_download_finished(self, success: bool, message: str):
        if success:
            self.progress_bar.setValue(100)
            self.status_label.setText("✅ Скачивание завершено!")
            self.cancel_btn.setText("✓  Готово")
            self.cancel_btn.setStyleSheet(
                "QPushButton{background:rgba(55,155,75,0.72);color:#f0f8f0;"
                "border:1px solid rgba(75,175,95,0.55);border-radius:11px;"
                "font-size:13px;font-weight:600;}"
                "QPushButton:hover{background:rgba(65,170,85,0.88);}"
            )
            try:
                self.cancel_btn.clicked.disconnect()
            except Exception:
                pass
            self.cancel_btn.clicked.connect(self.accept)
            if hasattr(self, "start_btn"):
                self.start_btn.hide()
            QtWidgets.QMessageBox.information(
                self, "Готово",
                f"✅ {message}\n\nМожете начинать общение.",
                QtWidgets.QMessageBox.StandardButton.Ok,
            )
            self.accept()
        else:
            self.status_label.setText(f"❌ {message}")
            if hasattr(self, "start_btn"):
                self.start_btn.setEnabled(True)
                self.start_btn.setText("⬇  Повторить")
            self.cancel_btn.setText("✕  Закрыть")
            try:
                self.cancel_btn.clicked.disconnect()
            except Exception:
                pass
            self.cancel_btn.clicked.connect(self.reject)


# ══════════════════════════════════════════════════════════════════════════
# КОНКРЕТНЫЕ ДИАЛОГИ
# ══════════════════════════════════════════════════════════════════════════

class LlamaDownloadDialog(_BaseDownloadDialog):
    """Диалог скачивания LLaMA 3."""
    MODEL_CMD   = "ollama pull llama3"
    MODEL_LABEL = "🦙  Скачивание LLaMA 3"
    MODEL_SIZE  = "~4.7 GB"


class DeepSeekDownloadDialog(_BaseDownloadDialog):
    """Диалог скачивания DeepSeek."""
    MODEL_CMD   = DEEPSEEK_OLLAMA_PULL
    MODEL_LABEL = "🧠  Скачивание DeepSeek"
    MODEL_SIZE  = "~4.1 GB"

    @QtCore.pyqtSlot(bool, str)
    def _on_download_finished(self, success: bool, message: str):
        # Переопределяем финальное сообщение
        if success:
            self.progress_bar.setValue(100)
            self.status_label.setText("✅ Скачивание завершено!")
            self.cancel_btn.setText("✓  Готово")
            self.cancel_btn.setStyleSheet(
                "QPushButton{background:rgba(55,155,75,0.72);color:#f0f8f0;"
                "border:1px solid rgba(75,175,95,0.55);border-radius:11px;"
                "font-size:13px;font-weight:600;}"
                "QPushButton:hover{background:rgba(65,170,85,0.88);}"
            )
            try:
                self.cancel_btn.clicked.disconnect()
            except Exception:
                pass
            self.cancel_btn.clicked.connect(self.accept)
            if hasattr(self, "start_btn"):
                self.start_btn.hide()
            QtWidgets.QMessageBox.information(
                self, "Готово",
                f"✅ {message}\n\nМожете выбрать эту модель.",
                QtWidgets.QMessageBox.StandardButton.Ok,
            )
            self.accept()
        else:
            self.status_label.setText(f"❌ {message}")
            if hasattr(self, "start_btn"):
                self.start_btn.setEnabled(True)
                self.start_btn.setText("⬇  Повторить")
            self.cancel_btn.setText("✕  Закрыть")
            try:
                self.cancel_btn.clicked.disconnect()
            except Exception:
                pass
            self.cancel_btn.clicked.connect(self.reject)
