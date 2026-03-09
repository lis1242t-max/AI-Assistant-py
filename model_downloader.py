"""
model_downloader.py — диалоги и утилиты для скачивания/удаления моделей Ollama.

Экспортирует:
    check_model_in_ollama(model_name) -> bool
    get_ollama_models_dir() -> str
    set_ollama_models_env_and_restart(new_models_dir) -> (bool, str)
    delete_model_files_from_disk(ollama_model_name, models_dir) -> (int, list)
    LlamaDownloadDialog(parent)
    DeepSeekDownloadDialog(parent)
    DeepSeekR1DownloadDialog(parent)
    MistralDownloadDialog(parent)
    QwenDownloadDialog(parent)
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
    from ai_config.deepseek_config import DEEPSEEK_MODEL_NAME, DEEPSEEK_OLLAMA_PULL
except ImportError:
    DEEPSEEK_MODEL_NAME = "deepseek-llm:7b-chat"
    DEEPSEEK_OLLAMA_PULL = "ollama pull deepseek-llm:7b-chat"

# ── Константы DeepSeek-R1 8B ─────────────────────────────────────────────
DEEPSEEK_R1_MODEL_NAME  = "deepseek-r1:8b"
DEEPSEEK_R1_OLLAMA_PULL = "ollama pull deepseek-r1:8b"

# ── Константы Mistral (берём из mistral_config или fallback) ─────────────
try:
    from ai_config.mistral_config import MISTRAL_MODEL_NAME, MISTRAL_OLLAMA_PULL
except ImportError:
    MISTRAL_MODEL_NAME = "mistral-nemo:12b"
    MISTRAL_OLLAMA_PULL = "ollama pull mistral-nemo:12b"

# ── Константы Qwen 3 ────────────────────────────────────────────────────
try:
    from ai_config.qwen_config import QWEN_MODEL_NAME, QWEN_OLLAMA_PULL
except ImportError:
    QWEN_MODEL_NAME  = "qwen3:14b"
    QWEN_OLLAMA_PULL = "ollama pull qwen3:14b"

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

        # Немодальное окно — пользователь работает пока идёт загрузка
        if IS_WINDOWS:
            self.setWindowFlags(
                QtCore.Qt.WindowType.Window |
                QtCore.Qt.WindowType.WindowTitleHint |
                QtCore.Qt.WindowType.WindowCloseButtonHint |
                QtCore.Qt.WindowType.WindowStaysOnTopHint
            )
        else:
            self.setWindowFlags(
                QtCore.Qt.WindowType.Window |
                QtCore.Qt.WindowType.FramelessWindowHint |
                QtCore.Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setModal(False)
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
            # stderr=STDOUT объединяет оба потока — нужно для HuggingFace моделей,
            # которые пишут прогресс в stderr. encoding+errors для безопасности.
            cmd = self.MODEL_CMD.split()
            kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, bufsize=1, encoding="utf-8", errors="replace")
            if IS_WINDOWS:
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            self._download_process = subprocess.Popen(cmd, **kwargs)

            _saw_progress   = False  # видели хоть один % — признак успешного начала
            _last_line      = ""     # последняя непустая строка вывода

            for line in self._download_process.stdout:
                if self._cancelled:
                    break
                line = line.strip()
                if not line:
                    continue
                _last_line = line
                pct_m = _re.search(r'(\d+)%', line)
                if pct_m:
                    _saw_progress = True
                    pct    = int(pct_m.group(1))
                    size_m = _re.search(r'([\d.]+)\s*GB/([\d.]+)\s*GB', line)
                    spd_m  = _re.search(r'([\d.]+)\s*(MB|KB)/s', line)
                    eta_m  = _re.search(r'(\d+m\d+s|\d+s)', line)
                    parts  = [f"{pct}%"]
                    if size_m: parts.append(f"({size_m.group(1)} / {size_m.group(2)} GB)")
                    if spd_m:  parts.append(f"— {spd_m.group(1)} {spd_m.group(2)}/s")
                    if eta_m:  parts.append(f"| осталось ~{eta_m.group(1)}")
                    self._set_status(pct, " ".join(parts))
                elif any(w in line.lower() for w in ("success", "done", "complete",
                                                       "writing manifest", "verifying sha256",
                                                       "pulling manifest", "already exists")):
                    _saw_progress = True
                    self._set_status(99, "✅ Финализация…")

            ret = self._download_process.wait()
            if self._cancelled:
                self.download_finished.emit(False, "Отменено пользователем")
            elif ret == 0:
                self.download_finished.emit(True, "Скачивание завершено!")
            else:
                # HuggingFace-модели в Ollama иногда возвращают код 1 даже при успехе.
                # Трёхступенчатая проверка:
                # 1. Вывод выглядит успешно (видели прогресс, нет слов "error")
                # 2. /api/tags — модель есть по полному имени
                # 3. /api/tags — модель есть по базовому имени (без тега и пути)
                _model_ok   = False
                _last_low   = _last_line.lower()
                _error_words = ("error", "failed", "cannot", "refused", "not found",
                                "не удал", "ошибка")

                # Проверка 1: по контексту вывода
                if _saw_progress and not any(w in _last_low for w in _error_words):
                    _model_ok = True

                # Проверка 2 и 3: через /api/tags
                if not _model_ok:
                    try:
                        _cmd_model = self.MODEL_CMD.replace("ollama pull ", "").strip()
                        _cmd_low   = _cmd_model.lower()
                        # Базовое имя: namespace/ModelName:tag → modelname
                        _base      = _re.sub(r'[-_]gguf.*$', '',
                                             _cmd_low.split("/")[-1].split(":")[0])
                        _tags = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=8).json()
                        _names = [m.get("name", "").lower()
                                  for m in _tags.get("models", [])]
                        _model_ok = any(
                            _cmd_low in n or n in _cmd_low or _base in n
                            for n in _names
                        )
                    except Exception:
                        pass

                if _model_ok:
                    self.download_finished.emit(True, "Скачивание завершено!")
                else:
                    err_detail = _last_line[:120] if _last_line else f"код {ret}"
                    self.download_finished.emit(False, f"Ошибка скачивания: {err_detail}")
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
        self.close()

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
            self.cancel_btn.clicked.connect(self.close)
            if hasattr(self, "start_btn"):
                self.start_btn.hide()
            QtWidgets.QMessageBox.information(
                self, "Готово",
                f"✅ {message}\n\nМожете начинать общение.",
                QtWidgets.QMessageBox.StandardButton.Ok,
            )
            self.close()
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
            self.cancel_btn.clicked.connect(self.close)


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
            self.cancel_btn.clicked.connect(self.close)
            if hasattr(self, "start_btn"):
                self.start_btn.hide()
            QtWidgets.QMessageBox.information(
                self, "Готово",
                f"✅ {message}\n\nМожете выбрать эту модель.",
                QtWidgets.QMessageBox.StandardButton.Ok,
            )
            self.close()
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
            self.cancel_btn.clicked.connect(self.close)


class DeepSeekR1DownloadDialog(_BaseDownloadDialog):
    """Диалог скачивания DeepSeek-R1 8B (модель с цепочкой рассуждений)."""
    MODEL_CMD   = DEEPSEEK_R1_OLLAMA_PULL
    MODEL_LABEL = "🧠  Скачивание DeepSeek-R1 8B"
    MODEL_SIZE  = "~4.9 GB"

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
            self.cancel_btn.clicked.connect(self.close)
            if hasattr(self, "start_btn"):
                self.start_btn.hide()
            QtWidgets.QMessageBox.information(
                self, "Готово",
                f"✅ {message}\n\nDeepSeek-R1 8B готов к использованию!",
                QtWidgets.QMessageBox.StandardButton.Ok,
            )
            self.close()
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
            self.cancel_btn.clicked.connect(self.close)


class MistralDownloadDialog(_BaseDownloadDialog):
    """Диалог скачивания Mistral Nemo 12B."""
    MODEL_CMD   = MISTRAL_OLLAMA_PULL
    MODEL_LABEL = "⚡  Скачивание Mistral Nemo 12B"
    MODEL_SIZE  = "~7.1 GB"

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
            self.cancel_btn.clicked.connect(self.close)
            if hasattr(self, "start_btn"):
                self.start_btn.hide()
            QtWidgets.QMessageBox.information(
                self, "Готово",
                f"✅ {message}\n\nMistral Nemo готов к использованию!",
                QtWidgets.QMessageBox.StandardButton.Ok,
            )
            self.close()
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
            self.cancel_btn.clicked.connect(self.close)

class QwenDownloadDialog(_BaseDownloadDialog):
    """Диалог скачивания Qwen 3 14B."""
    MODEL_CMD   = QWEN_OLLAMA_PULL
    MODEL_LABEL = "🌟  Скачивание Qwen"
    MODEL_SIZE  = "~9 GB"

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
            self.cancel_btn.clicked.connect(self.close)
            if hasattr(self, "start_btn"):
                self.start_btn.hide()
            QtWidgets.QMessageBox.information(
                self, "Готово",
                f"✅ {message}\n\nQwen 3 готов к использованию!",
                QtWidgets.QMessageBox.StandardButton.Ok,
            )
            self.close()
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
            self.cancel_btn.clicked.connect(self.close)


# ══════════════════════════════════════════════════════════════════════════
# ДИАЛОГ СКАЧИВАНИЯ САМОЙ ПРОГРАММЫ OLLAMA
# ══════════════════════════════════════════════════════════════════════════

class OllamaDownloadDialog(QtWidgets.QDialog):
    """
    Диалог скачивания и установки Ollama.

    Mac:     скачивает Ollama-darwin.zip → распаковывает → перемещает в /Applications
    Windows: скачивает OllamaSetup.exe   → запускает тихую установку (/SILENT)

    Без терминала — только чистый прогресс: %, скорость, статус.
    """

    _sig_progress = QtCore.pyqtSignal(int, str, str)   # pct, status, speed
    _sig_done     = QtCore.pyqtSignal(bool, str)        # success, message

    # URLs для скачивания
    _URL_MAC = "https://ollama.com/download/Ollama-darwin.zip"
    _URL_WIN = "https://ollama.com/download/OllamaSetup.exe"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Скачивание Ollama")
        self._cancelled = False

        self._is_dark = True
        if parent and hasattr(parent, "current_theme"):
            self._is_dark = parent.current_theme == "dark"

        IS_MAC = sys.platform == "darwin"
        if IS_WINDOWS or IS_MAC:
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
        self._sig_progress.connect(self._on_progress)
        self._sig_done.connect(self._on_done)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        d   = self._is_dark
        win = IS_WINDOWS

        if d:
            card_bg   = "rgb(22,22,32)"    if win else "rgba(22,22,32,0.98)"
            card_bdr  = "rgba(75,75,105,0.75)"
            title_col = "#e4e4f4"; desc_col = "#8888aa"; status_col = "#8899dd"
            pb_bg     = "rgba(40,40,60,0.85)"; pb_bdr = "rgba(70,70,100,0.55)"; pb_txt = "#d0d0f0"
            speed_col = "#aabbee"
        else:
            card_bg   = "rgb(248,248,255)" if win else "rgba(248,248,255,0.99)"
            card_bdr  = "rgba(200,205,235,0.90)"
            title_col = "#1a1a40"; desc_col = "#6677aa"; status_col = "#5566bb"
            pb_bg     = "rgba(225,228,248,0.90)"; pb_bdr = "rgba(180,190,225,0.70)"; pb_txt = "#2a2a60"
            speed_col = "#4455aa"

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4 if win else 14, 4 if win else 14,
                                4 if win else 14, 4 if win else 14)

        card = QtWidgets.QFrame()
        card.setObjectName("olDlCard")
        card.setStyleSheet(
            f"QFrame#olDlCard {{ background:{card_bg}; border:1px solid {card_bdr}; border-radius:20px; }}"
        )
        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(32, 28, 32, 28)
        cl.setSpacing(16)
        root.addWidget(card)

        # Заголовок
        title = QtWidgets.QLabel("🦙  Установка Ollama")
        title.setStyleSheet(
            f"color:{title_col};font-size:18px;font-weight:700;background:transparent;border:none;"
        )
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(title)

        # Описание
        desc_txt = (
            "Для работы ИИ-ассистента требуется Ollama. "
            "Нажмите «Скачать» — файл загрузится и установится автоматически."
        )
        self._desc_lbl = QtWidgets.QLabel(desc_txt)
        self._desc_lbl.setStyleSheet(f"color:{desc_col};font-size:12px;background:transparent;border:none;")
        self._desc_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._desc_lbl.setWordWrap(True)
        cl.addWidget(self._desc_lbl)

        # Прогресс-бар
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setStyleSheet(
            f"QProgressBar{{background:{pb_bg};border:1px solid {pb_bdr};"
            f"border-radius:9px;}}"
            f"QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #667eea,stop:1 #764ba2);border-radius:8px;}}"
        )
        cl.addWidget(self.progress_bar)

        # Строка: процент + скорость
        info_row = QtWidgets.QHBoxLayout()
        self._pct_lbl = QtWidgets.QLabel("0%")
        self._pct_lbl.setStyleSheet(f"color:{pb_txt};font-size:12px;font-weight:600;background:transparent;border:none;")
        self._speed_lbl = QtWidgets.QLabel("")
        self._speed_lbl.setStyleSheet(f"color:{speed_col};font-size:12px;background:transparent;border:none;")
        self._speed_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        info_row.addWidget(self._pct_lbl)
        info_row.addStretch()
        info_row.addWidget(self._speed_lbl)
        cl.addLayout(info_row)

        # Статус
        self.status_label = QtWidgets.QLabel("Нажмите «Скачать» для начала")
        self.status_label.setStyleSheet(
            f"color:{status_col};font-size:12px;background:transparent;border:none;"
        )
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        cl.addWidget(self.status_label)

        # Кнопки
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(10)

        self.start_btn = QtWidgets.QPushButton("⬇  Скачать Ollama")
        self.start_btn.setFixedHeight(42)
        self.start_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.start_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.start_btn.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #667eea,stop:1 #764ba2);color:#fff;border:none;"
            "border-radius:12px;font-size:14px;font-weight:700;}"
            "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #7b8ff5,stop:1 #8860b8);}"
            "QPushButton:disabled{background:rgba(100,100,140,0.45);color:#9999bb;}"
        )
        self.start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QtWidgets.QPushButton("✕  Пропустить")
        self.cancel_btn.setFixedHeight(42)
        self.cancel_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.cancel_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.cancel_btn.setStyleSheet(
            "QPushButton{background:rgba(180,55,55,0.65);color:#f0f0f8;"
            "border:1px solid rgba(200,75,75,0.5);border-radius:12px;"
            "font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:rgba(205,65,65,0.82);}"
        )
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_btn)
        cl.addLayout(btn_row)

        self.adjustSize()
        self.setMinimumWidth(480)

    # ── Запуск скачивания ─────────────────────────────────────────────────
    def _on_start(self):
        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳  Скачивание…")
        self.status_label.setText("Подключение к серверу…")
        self._cancelled = False
        threading.Thread(target=self._download_thread, daemon=True).start()

    # ── Поток скачивания ──────────────────────────────────────────────────
    def _download_thread(self):
        import time as _time
        import zipfile as _zip
        import shutil as _sh
        import tempfile as _tmp

        IS_MAC = sys.platform == "darwin"
        url    = self._URL_MAC if IS_MAC else self._URL_WIN

        tmp_dir  = _tmp.mkdtemp(prefix="ollama_dl_")
        filename = "Ollama-darwin.zip" if IS_MAC else "OllamaSetup.exe"
        dest     = os.path.join(tmp_dir, filename)

        try:
            # ── Скачивание ────────────────────────────────────────────────
            self._sig_progress.emit(0, "Подключение…", "")
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()

            total     = int(resp.headers.get("content-length", 0))
            received  = 0
            t0        = _time.monotonic()
            t_last    = t0

            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._cancelled:
                        self._sig_done.emit(False, "Отменено")
                        return
                    if chunk:
                        f.write(chunk)
                        received += len(chunk)

                        now   = _time.monotonic()
                        elapsed = max(now - t0, 0.001)
                        speed_bps = received / elapsed

                        # Скорость в читаемом виде
                        if speed_bps > 1_048_576:
                            speed_str = f"{speed_bps/1_048_576:.1f} МБ/с"
                        elif speed_bps > 1024:
                            speed_str = f"{speed_bps/1024:.0f} КБ/с"
                        else:
                            speed_str = f"{speed_bps:.0f} Б/с"

                        if total > 0:
                            pct = int(received * 90 / total)
                            mb_recv = received / 1_048_576
                            mb_total = total / 1_048_576
                            status = f"Скачивание… {mb_recv:.1f} / {mb_total:.1f} МБ"
                        else:
                            pct = min(45, int(received / 1_048_576))
                            mb_recv = received / 1_048_576
                            status = f"Скачивание… {mb_recv:.1f} МБ"

                        # Обновляем UI не чаще чем раз в 0.1 сек
                        if now - t_last >= 0.1:
                            t_last = now
                            self._sig_progress.emit(pct, status, speed_str)

            if self._cancelled:
                self._sig_done.emit(False, "Отменено")
                return

            # ── Установка ────────────────────────────────────────────────
            self._sig_progress.emit(91, "Установка…", "")

            if IS_MAC:
                self._install_mac(dest, tmp_dir)
            else:
                self._install_windows(dest)

        except requests.exceptions.ConnectionError:
            self._sig_done.emit(False, "Нет соединения с интернетом")
        except Exception as e:
            self._sig_done.emit(False, f"Ошибка: {e}")
        finally:
            try:
                import shutil as _sh2
                _sh2.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    def _install_mac(self, zip_path: str, tmp_dir: str):
        """
        Распаковывает zip, перемещает Ollama.app в /Applications,
        снимает карантин macOS и выставляет права на исполнение.

        Без этих шагов macOS блокирует запуск и Finder показывает ошибку.
        """
        import zipfile as _zip
        import shutil  as _sh

        # ── 1. Распаковка ────────────────────────────────────────────────
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        self._sig_progress.emit(91, "Распаковка архива…", "")
        with _zip.ZipFile(zip_path, "r") as zf:
            # Восстанавливаем права из zip-метаданных (важно для исполняемых файлов)
            for info in zf.infolist():
                zf.extract(info, extract_dir)
                extracted_path = os.path.join(extract_dir, info.filename)
                # Старший байт external_attr — unix permissions
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if unix_mode and os.path.isfile(extracted_path):
                    os.chmod(extracted_path, unix_mode)

        # ── 2. Ищем Ollama.app ───────────────────────────────────────────
        app_src = None
        for root_d, dirs, _ in os.walk(extract_dir):
            for d in dirs:
                if d == "Ollama.app":
                    app_src = os.path.join(root_d, d)
                    break
            if app_src:
                break

        if not app_src:
            self._sig_done.emit(False, "Ollama.app не найдена в архиве")
            return

        # ── 3. Перемещаем в /Applications ───────────────────────────────
        app_dst = "/Applications/Ollama.app"
        self._sig_progress.emit(94, "Установка в /Applications…", "")

        if os.path.exists(app_dst):
            _sh.rmtree(app_dst, ignore_errors=True)

        try:
            _sh.move(app_src, app_dst)
        except PermissionError:
            # Нет прав на /Applications → ~/Applications
            user_apps = os.path.expanduser("~/Applications")
            os.makedirs(user_apps, exist_ok=True)
            app_dst = os.path.join(user_apps, "Ollama.app")
            if os.path.exists(app_dst):
                _sh.rmtree(app_dst, ignore_errors=True)
            _sh.move(app_src, app_dst)

        # ── 4. Снимаем карантин macOS ────────────────────────────────────
        # Без этого шага macOS блокирует запуск: "приложение повреждено"
        # или Finder выдаёт ошибку. xattr -cr рекурсивно удаляет карантин.
        self._sig_progress.emit(96, "Снятие карантина macOS…", "")
        try:
            ret = subprocess.call(
                ["xattr", "-cr", app_dst],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if ret == 0:
                print(f"[INSTALL] ✅ Карантин снят: {app_dst}")
            else:
                print(f"[INSTALL] ⚠️ xattr вернул {ret} — продолжаем")
        except FileNotFoundError:
            print("[INSTALL] ⚠️ xattr не найден — пропускаем")
        except Exception as e:
            print(f"[INSTALL] ⚠️ xattr: {e}")

        # ── 5. Права на исполнение главного бинарника ────────────────────
        self._sig_progress.emit(97, "Настройка прав доступа…", "")
        for rel in (
            "Contents/MacOS/Ollama",
            "Contents/Resources/ollama",
            "Contents/MacOS/ollama",
        ):
            bin_path = os.path.join(app_dst, rel)
            if os.path.isfile(bin_path):
                try:
                    os.chmod(bin_path, 0o755)
                    print(f"[INSTALL] ✅ chmod 755: {bin_path}")
                except Exception as e:
                    print(f"[INSTALL] ⚠️ chmod: {e}")

        # ── 6. Регистрируем в Launch Services (чтобы Finder тоже видел) ──
        self._sig_progress.emit(99, "Регистрация приложения…", "")
        try:
            subprocess.call(
                ["/System/Library/Frameworks/CoreServices.framework"
                 "/Versions/A/Frameworks/LaunchServices.framework"
                 "/Versions/A/Support/lsregister",
                 "-f", app_dst],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            print("[INSTALL] ✅ lsregister выполнен")
        except Exception as e:
            print(f"[INSTALL] ⚠️ lsregister: {e}")

        self._sig_progress.emit(100, "✅ Готово!", "")
        self._sig_done.emit(True, app_dst)

    def _install_windows(self, exe_path: str):
        """Запускает OllamaSetup.exe с флагом тихой установки."""
        self._sig_progress.emit(93, "Запуск установщика…", "")
        try:
            ret = subprocess.call(
                [exe_path, "/SILENT", "/NORESTART"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if ret == 0:
                self._sig_progress.emit(100, "✅ Готово!", "")
                self._sig_done.emit(True, "")
            else:
                self._sig_done.emit(False, f"Установщик завершился с кодом {ret}")
        except Exception as e:
            self._sig_done.emit(False, f"Ошибка запуска установщика: {e}")

    # ── Обновление прогресса ─────────────────────────────────────────────
    @QtCore.pyqtSlot(int, str, str)
    def _on_progress(self, pct: int, status: str, speed: str):
        self.progress_bar.setValue(pct)
        self.status_label.setText(status)
        self._pct_lbl.setText(f"{pct}%")
        self._speed_lbl.setText(speed)

    # ── Финальный обработчик ─────────────────────────────────────────────
    @QtCore.pyqtSlot(bool, str)
    def _on_done(self, success: bool, message: str):
        if success:
            self.progress_bar.setValue(100)
            self._pct_lbl.setText("100%")
            self._speed_lbl.setText("")
            self.start_btn.hide()

            IS_MAC = sys.platform == "darwin"
            if IS_MAC:
                app_path = message  # путь куда установили
                self.status_label.setText("✅ Ollama установлена!")
                self._desc_lbl.setText(
                    f"Ollama установлена: {app_path}\n\n"
                    "Нажмите «Готово» — ассистент запустит её автоматически."
                )
            else:
                self.status_label.setText("✅ Ollama установлена!")

            self.cancel_btn.setText("✓  Готово")
            self.cancel_btn.setStyleSheet(
                "QPushButton{background:rgba(55,155,75,0.72);color:#f0f8f0;"
                "border:1px solid rgba(75,175,95,0.55);border-radius:12px;"
                "font-size:14px;font-weight:600;}"
                "QPushButton:hover{background:rgba(65,170,85,0.88);}"
            )
            try:
                self.cancel_btn.clicked.disconnect()
            except Exception:
                pass
            self.cancel_btn.clicked.connect(self.close)
        else:
            self.status_label.setText(f"❌ {message}")
            self.start_btn.setEnabled(True)
            self.start_btn.setText("⬇  Повторить")
            self._pct_lbl.setText("")
            self._speed_lbl.setText("")
            self.cancel_btn.setText("✕  Закрыть")
            try:
                self.cancel_btn.clicked.disconnect()
            except Exception:
                pass
            self.cancel_btn.clicked.connect(self.close)

    def _on_cancel(self):
        self._cancelled = True
        self.reject()