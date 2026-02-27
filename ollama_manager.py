"""
ollama_manager.py — управление процессом Ollama.

Ищет Ollama ВО ВСЕХ стандартных местах установки:
  Windows → реестр, AppData/Local/Programs/Ollama, Program Files, PATH
  macOS   → /usr/local/bin, /opt/homebrew/bin, Ollama.app, login-shell PATH
  Linux   → /usr/local/bin, /usr/bin, ~/.local/bin, snap, PATH

Порядок при старте:
  1. is_ollama_running()     — Ollama уже запущена? (системная или наша)
  2. find_ollama_binary()    — ищем во ВСЕХ стандартных местах
  3. launch_ollama(binary)   — запускаем скрыто (без окна), не ждём API
  4. Если бинарник не найден → OllamaDownloadDialog

Экспорт:
    is_ollama_running()         → bool
    find_ollama_binary()        → str | None
    launch_ollama(binary)       → bool
    stop_managed_ollama()       → None
    ensure_ollama_ready(parent) → bool  (вызывать из фонового потока)
"""

import os, sys, time, threading, subprocess, shutil

try:
    import requests as _req
except ImportError:
    _req = None

APP_DIR           = os.path.dirname(os.path.abspath(__file__))
OLLAMA_BIN_DIR    = os.path.join(APP_DIR, "bin")
OLLAMA_MODELS_DIR = os.path.join(APP_DIR, "ollama_models")

try:
    from llama_handler import OLLAMA_HOST  # type: ignore
except ImportError:
    OLLAMA_HOST = "http://localhost:11434"

IS_WINDOWS = sys.platform == "win32"
IS_MACOS   = sys.platform == "darwin"

_managed_proc = None   # Popen — только тот, что запустили МЫ


# ══════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА ДОСТУПНОСТИ
# ══════════════════════════════════════════════════════════════════════════

def is_ollama_running(timeout: float = 2.0) -> bool:
    """True если Ollama API уже отвечает на /api/tags."""
    if _req is None:
        return False
    try:
        return _req.get(f"{OLLAMA_HOST}/api/tags", timeout=timeout).status_code == 200
    except Exception:
        return False


def wait_for_ollama(max_sec: float = 25.0) -> bool:
    """Опрашивает API каждые 0.5 сек до max_sec. Только из фоновых потоков."""
    deadline = time.monotonic() + max_sec
    while time.monotonic() < deadline:
        if is_ollama_running(1.5):
            return True
        time.sleep(0.5)
    return False


# ══════════════════════════════════════════════════════════════════════════
# ПОИСК БИНАРНИКА — во ВСЕХ стандартных местах
# ══════════════════════════════════════════════════════════════════════════

def _get_shell_path_candidates() -> list:
    """
    На Mac GUI-приложения стартуют с урезанным PATH (без /usr/local/bin и т.д.).
    Запрашиваем настоящий PATH через login-шелл пользователя.
    """
    results = []
    if not IS_MACOS:
        return results

    shell = os.environ.get("SHELL", "/bin/zsh")
    try:
        # which ollama через login-шелл — самый надёжный способ
        out = subprocess.check_output(
            [shell, "-l", "-c", "which ollama 2>/dev/null || command -v ollama 2>/dev/null"],
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if out:
            results.append(out)
    except Exception as e:
        print(f"[OLLAMA_MGR] shell which: {e}")

    try:
        # Все директории из PATH login-шелла
        path_out = subprocess.check_output(
            [shell, "-l", "-c", "echo $PATH"],
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        for d in path_out.split(":"):
            p = os.path.join(d.strip(), "ollama")
            results.append(p)
    except Exception as e:
        print(f"[OLLAMA_MGR] shell PATH: {e}")

    return results


def _candidate_paths() -> list:
    """
    Возвращает упорядоченный список путей для поиска бинарника Ollama.
    Дублей нет (seen-set).
    """
    seen = set()
    candidates = []

    def add(p):
        if p and p not in seen:
            seen.add(p)
            candidates.append(p)

    # ── 1. Папка проекта (bin/) ──────────────────────────────────────────
    name = "ollama.exe" if IS_WINDOWS else "ollama"
    add(os.path.join(OLLAMA_BIN_DIR, name))

    # ── 2. Платформо-специфичные пути ───────────────────────────────────
    if IS_WINDOWS:
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            add(os.path.join(local_app, "Programs", "Ollama", "ollama.exe"))
            add(os.path.join(local_app, "Ollama", "ollama.exe"))

        for pf in [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]:
            if pf:
                add(os.path.join(pf, "Ollama", "ollama.exe"))

        user = os.environ.get("USERPROFILE", "")
        if user:
            add(os.path.join(user, "AppData", "Local", "Programs", "Ollama", "ollama.exe"))

        # Реестр Windows — самый надёжный способ найти путь установки
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for subkey in (
                    r"SOFTWARE\Ollama",
                    r"SOFTWARE\WOW6432Node\Ollama",
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Ollama",
                ):
                    try:
                        with winreg.OpenKey(root, subkey) as k:
                            for val_name in ("InstallLocation", "DisplayIcon", "UninstallString"):
                                try:
                                    v, _ = winreg.QueryValueEx(k, val_name)
                                    v = v.strip().strip('"')
                                    if v.lower().endswith(".exe"):
                                        add(v)
                                    else:
                                        add(os.path.join(v, "ollama.exe"))
                                except OSError:
                                    pass
                    except OSError:
                        pass
        except ImportError:
            pass

    elif IS_MACOS:
        # CLI — наиболее вероятные места (brew, install-script)
        add("/usr/local/bin/ollama")
        add("/opt/homebrew/bin/ollama")        # Apple Silicon homebrew
        add("/opt/local/bin/ollama")            # MacPorts
        add("/usr/bin/ollama")
        add(os.path.expanduser("~/.local/bin/ollama"))
        add(os.path.expanduser("~/bin/ollama"))

        # Ollama.app bundle (GUI установщик)
        for app_root in (
            "/Applications/Ollama.app",
            os.path.expanduser("~/Applications/Ollama.app"),
        ):
            # Resources/ollama — CLI внутри бандла (новые версии)
            add(os.path.join(app_root, "Contents", "Resources", "ollama"))
            # MacOS/ollama — исполняемый файл бандла (тоже работает с serve)
            add(os.path.join(app_root, "Contents", "MacOS", "ollama"))

        # GUI-приложения на Mac стартуют с урезанным PATH.
        # Получаем настоящий PATH через login-шелл → надёжное обнаружение.
        for p in _get_shell_path_candidates():
            add(p)

    else:  # Linux
        add("/usr/local/bin/ollama")
        add("/usr/bin/ollama")
        add(os.path.expanduser("~/.local/bin/ollama"))
        add(os.path.expanduser("~/bin/ollama"))
        add("/snap/bin/ollama")

    # ── 3. Системный PATH текущего процесса (последний шанс) ────────────
    sys_bin = shutil.which("ollama")
    if sys_bin:
        add(sys_bin)

    return candidates


def find_ollama_binary() -> "str | None":
    """Ищет бинарник Ollama во всех стандартных местах."""
    paths = _candidate_paths()

    for path in paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            print(f"[OLLAMA_MGR] ✅ Найден: {path}")
            return path

    print("[OLLAMA_MGR] ❌ Ollama не найдена ни в одном стандартном месте")
    print("[OLLAMA_MGR]    Проверены пути:")
    for p in paths:
        exists = "✓ ФАЙЛ ЕСТЬ, но не исполняемый" if os.path.isfile(p) else "✗"
        print(f"             {exists} {p}")
    return None


# ══════════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════════

def _close_ollama_gui_macos() -> None:
    """
    Принудительно завершает GUI-процесс Ollama.app на Mac
    (иконка в меню-баре), оставляя `ollama serve` живым в фоне.
    Вызывать только ПОСЛЕ того как API ответил.
    """
    try:
        # Мягкое закрытие через AppleScript
        subprocess.run(
            ["osascript", "-e", 'tell application "Ollama" to quit'],
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("[OLLAMA_MGR] ✅ Ollama.app (GUI) закрыта через osascript")
    except Exception as e:
        print(f"[OLLAMA_MGR] ⚠️ osascript quit: {e}")
        # Fallback: pkill по имени процесса
        try:
            subprocess.run(
                ["pkill", "-x", "Ollama"],
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[OLLAMA_MGR] ✅ Ollama.app закрыта через pkill")
        except Exception as e2:
            print(f"[OLLAMA_MGR] ⚠️ pkill: {e2}")


def launch_ollama(binary: str) -> bool:
    """
    Запускает Ollama в фоне:
      macOS   → open -a Ollama (запускает сервер через .app),
                затем ждёт API и закрывает GUI-часть (иконку меню-бара).
                ollama serve продолжает работать в фоне.
      Windows → ollama serve с CREATE_NO_WINDOW (без окна изначально).
      Linux   → ollama serve в новом сеансе.
    """
    global _managed_proc

    os.makedirs(OLLAMA_MODELS_DIR, exist_ok=True)

    # ── macOS: запускаем через .app, потом закрываем GUI ───────────────────
    if IS_MACOS:
        app_found = False
        for app in ("/Applications/Ollama.app", os.path.expanduser("~/Applications/Ollama.app")):
            if os.path.isdir(app):
                app_found = True
                break

        if app_found:
            try:
                subprocess.Popen(
                    ["open", "-a", "Ollama"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                print("[OLLAMA_MGR] ✅ Ollama.app запущена через 'open -a Ollama'")

                # Ждём пока API поднимется (до 30 сек)
                print("[OLLAMA_MGR] ⏳ Ждём API от Ollama.app...")
                if wait_for_ollama(30):
                    print("[OLLAMA_MGR] ✅ API готов — закрываем GUI (иконку меню-бара)")
                    _close_ollama_gui_macos()
                else:
                    print("[OLLAMA_MGR] ⚠️ API не ответил за 30 сек — GUI оставляем как есть")
                return True
            except Exception as e:
                print(f"[OLLAMA_MGR] ⚠️ open -a Ollama: {e}")

        # Fallback: CLI бинарник напрямую
        print("[OLLAMA_MGR] Ollama.app не найдена — запускаем через CLI напрямую")

    # ── Windows / Linux / Mac-fallback: ollama serve ────────────────────────
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = OLLAMA_MODELS_DIR

    # На Mac подставляем полный PATH из login-шелла
    if IS_MACOS:
        try:
            shell = os.environ.get("SHELL", "/bin/zsh")
            shell_path = subprocess.check_output(
                [shell, "-l", "-c", "echo $PATH"],
                timeout=5, stderr=subprocess.DEVNULL,
            ).decode().strip()
            if shell_path:
                env["PATH"] = shell_path
        except Exception:
            pass

    kw: dict = {
        "env":    env,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }

    if IS_WINDOWS:
        # Скрытое окно — пользователь ничего не видит
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        kw["start_new_session"] = True

    try:
        proc = subprocess.Popen([binary, "serve"], **kw)
        _managed_proc = proc
        print(f"[OLLAMA_MGR] ✅ ollama serve запущен (PID={proc.pid})")
        return True
    except Exception as e:
        print(f"[OLLAMA_MGR] ❌ Не удалось запустить: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════
# ОСТАНОВКА
# ══════════════════════════════════════════════════════════════════════════

def stop_managed_ollama() -> None:
    """
    Завершает ТОЛЬКО тот процесс, что запустили МЫ.
    Системную Ollama не трогает.
    Вызывать из closeEvent перед os._exit().
    """
    global _managed_proc
    if _managed_proc is None:
        return
    proc, _managed_proc = _managed_proc, None
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("[OLLAMA_MGR] ✅ Ollama остановлена")
    except Exception as e:
        print(f"[OLLAMA_MGR] ⚠️ stop: {e}")


# ══════════════════════════════════════════════════════════════════════════
# ГЛАВНАЯ ТОЧКА — вызывать из ФОНОВОГО потока
# ══════════════════════════════════════════════════════════════════════════

def ensure_ollama_ready(parent_qt=None) -> bool:
    """
    Проверяет, запущена ли Ollama. Если нет — ищет бинарник и запускает.
    Диалог установки НЕ показывает — этим занимается run.py в главном потоке.
    Возвращает True если Ollama запущена или успешно стартовала.
    Возвращает False если бинарник не найден (нужна установка).
    """
    print(f"[OLLAMA_MGR] >>> ensure_ollama_ready() platform={sys.platform}")

    if is_ollama_running():
        print("[OLLAMA_MGR] ✅ Ollama уже запущена")
        return True

    binary = find_ollama_binary()
    if not binary:
        print("[OLLAMA_MGR] ❌ Бинарник не найден — требуется установка")
        return False

    launched = launch_ollama(binary)
    if launched:
        print("[OLLAMA_MGR] ✅ Ollama запущена в фоне")
    else:
        print("[OLLAMA_MGR] ❌ Не удалось запустить")
    return launched