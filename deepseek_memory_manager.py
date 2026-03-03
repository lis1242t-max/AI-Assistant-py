#!/usr/bin/env python3
# deepseek_memory_manager.py
# ═══════════════════════════════════════════════════════════════════
# Отдельная контекстная память для DeepSeek.
# Полностью изолирована от памяти LLaMA (context_memory.db).
# Своя БД: deepseek_memory.db
#
# ИСПРАВЛЕНО: убрана хрупкая логика _current_chat_id внутри save_context_memory.
# Раньше: если синглтон "забывал" предыдущий chat_id (рестарт, баг),
#          on_chat_switch не срабатывал → память чужого чата просачивалась.
# Теперь: все DB-операции явно фильтруют по chat_id переданному аргументом.
#          on_chat_switch — только явный вызов из run.py, не авто-триггер.
# ═══════════════════════════════════════════════════════════════════

import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional

DEEPSEEK_MEMORY_DB = "deepseek_memory.db"


class DeepSeekMemoryManager:
    """
    Менеджер памяти для DeepSeek.
    Работает исключительно с deepseek_memory.db.
    Не читает и не пишет в context_memory.db (LLaMA).

    Изоляция по chat_id обеспечивается на уровне каждого SQL-запроса,
    а не через хрупкое состояние _current_chat_id.
    """

    def __init__(self):
        self._init_db()

    # ─── Инициализация БД ────────────────────────────────────────────

    def _init_db(self):
        """Создаёт таблицы в deepseek_memory.db если их ещё нет."""
        conn = sqlite3.connect(DEEPSEEK_MEMORY_DB)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deepseek_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                entry_type  TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ds_chat
            ON deepseek_memory(chat_id)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deepseek_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                role        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ds_msg_chat
            ON deepseek_messages(chat_id)
        """)
        conn.commit()
        conn.close()
        print(f"[DS_MEMORY] ✓ БД инициализирована: {DEEPSEEK_MEMORY_DB}")

    # ─── Смена / очистка чата ───────────────────────────────────────

    def on_chat_switch(self, new_chat_id: int):
        """
        Вызывать явно из run.py при переключении на другой чат.
        Ничего не удаляет — только логирует.
        Изоляция памяти обеспечивается через chat_id в каждом запросе,
        а не через очистку при переключении.
        """
        print(f"[DS_MEMORY] Переключение на чат {new_chat_id} (изоляция по chat_id активна)")

    def on_chat_cleared(self, chat_id: int):
        """
        Вызывать когда пользователь нажал «Очистить чат» или «Новый чат».
        Сбрасывает память DeepSeek для этого чата.
        """
        self.clear_context_memory(chat_id)
        print(f"[DS_MEMORY] Чат {chat_id} очищен — память сброшена.")

    # ─── Запись ──────────────────────────────────────────────────────

    def save_context_memory(self, chat_id: int, entry_type: str, content: str):
        """
        Сохранить запись в память DeepSeek для данного chat_id.
        entry_type: "user_memory" | "file_analysis" | "search_meta" | "message_files"

        Изоляция: запись всегда привязана к переданному chat_id.
        Никаких побочных эффектов (очисток, переключений) не происходит.
        """
        conn = sqlite3.connect(DEEPSEEK_MEMORY_DB)
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO deepseek_memory (chat_id, entry_type, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, entry_type, content, now)
        )
        conn.commit()
        conn.close()
        print(f"[DS_MEMORY] Сохранено: chat_id={chat_id}, type={entry_type}, len={len(content)}")

    # ─── Диалоговая история (user/assistant повороты) ────────────────

    def save_message(self, chat_id: int, role: str, content: str):
        """
        Сохранить один поворот диалога.
        role: "user" | "assistant"
        Вызывать ПОСЛЕ каждого сообщения пользователя и ПОСЛЕ каждого ответа DeepSeek.
        """
        conn = sqlite3.connect(DEEPSEEK_MEMORY_DB)
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO deepseek_messages (chat_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, role, content, now)
        )
        conn.commit()
        conn.close()
        print(f"[DS_MEMORY] Сообщение: chat_id={chat_id}, role={role}, len={len(content)}")

    def get_messages(self, chat_id: int, limit: int = 20) -> List[dict]:
        """
        Получить историю диалога в формате [{"role": ..., "content": ...}, ...].
        Готов для прямой передачи в Ollama API как поле 'messages'.
        Только для данного chat_id — кросс-чат утечка исключена.
        """
        conn = sqlite3.connect(DEEPSEEK_MEMORY_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM deepseek_messages "
            "WHERE chat_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        )
        rows = cur.fetchall()
        conn.close()
        # Разворачиваем: получены от новых к старым, нужно от старых к новым
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    # ─── Чтение ──────────────────────────────────────────────────────

    def get_context_memory(self, chat_id: int, limit: int = 12) -> List[Tuple]:
        """
        Получить контекстную память чата DeepSeek.
        Возвращает список (entry_type, content, created_at) от старых к новым.
        Только для данного chat_id.
        """
        conn = sqlite3.connect(DEEPSEEK_MEMORY_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT entry_type, content, created_at "
            "FROM deepseek_memory "
            "WHERE chat_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        )
        rows = cur.fetchall()
        conn.close()
        return list(reversed(rows))

    # ─── Очистка одного чата ────────────────────────────────────────

    def clear_context_memory(self, chat_id: int):
        """Очистить память DeepSeek для конкретного чата (обе таблицы)."""
        conn = sqlite3.connect(DEEPSEEK_MEMORY_DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM deepseek_memory WHERE chat_id = ?", (chat_id,))
        meta_deleted = cur.rowcount
        cur.execute("DELETE FROM deepseek_messages WHERE chat_id = ?", (chat_id,))
        msg_deleted = cur.rowcount
        conn.commit()
        conn.close()
        print(f"[DS_MEMORY] Очищено {meta_deleted} метазаписей и {msg_deleted} "
              f"сообщений для chat_id={chat_id}")

    def delete_chat_context(self, chat_id: int):
        """Псевдоним clear_context_memory — для совместимости с вызовами delete_chat."""
        self.clear_context_memory(chat_id)

    # ─── Очистка всех чатов ─────────────────────────────────────────

    def clear_all_context(self):
        """Очистить память DeepSeek для ВСЕХ чатов (при 'Удалить все чаты')."""
        conn = sqlite3.connect(DEEPSEEK_MEMORY_DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM deepseek_memory")
        cur.execute("DELETE FROM deepseek_messages")
        try:
            cur.execute("DELETE FROM sqlite_sequence WHERE name='deepseek_memory'")
            cur.execute("DELETE FROM sqlite_sequence WHERE name='deepseek_messages'")
        except Exception:
            pass
        conn.commit()
        conn.close()
        print("[DS_MEMORY] Очищена ВСЯ память DeepSeek (метаданные + история диалогов)")