#!/usr/bin/env python3
# deepseek_memory_manager.py
# ═══════════════════════════════════════════════════════════════════
# Отдельная контекстная память для DeepSeek.
# Полностью изолирована от памяти LLaMA (context_memory.db).
# Своя БД: deepseek_memory.db
# ═══════════════════════════════════════════════════════════════════

import sqlite3
from datetime import datetime
from typing import List, Tuple

# Отдельная БД — не пересекается с LLaMA (context_memory.db)
DEEPSEEK_MEMORY_DB = "deepseek_memory.db"


class DeepSeekMemoryManager:
    """
    Менеджер памяти для DeepSeek.
    Работает исключительно с deepseek_memory.db.
    Не читает и не пишет в context_memory.db (LLaMA).
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
        conn.commit()
        conn.close()

    # ─── Запись ──────────────────────────────────────────────────────

    def save_context_memory(self, chat_id: int, entry_type: str, content: str):
        """
        Сохранить запись в память DeepSeek.
        entry_type: "user_memory" | "file_analysis" | "search_meta" | "message_files"
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

    # ─── Чтение ──────────────────────────────────────────────────────

    def get_context_memory(self, chat_id: int, limit: int = 12) -> List[Tuple]:
        """
        Получить контекстную память чата DeepSeek.
        Возвращает список (entry_type, content, created_at) от старых к новым.
        Лимит по умолчанию 12 — DeepSeek не нужна длинная история.
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
        """Очистить память DeepSeek для конкретного чата."""
        conn = sqlite3.connect(DEEPSEEK_MEMORY_DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM deepseek_memory WHERE chat_id = ?", (chat_id,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        print(f"[DS_MEMORY] Очищено {deleted} записей для chat_id={chat_id}")

    def delete_chat_context(self, chat_id: int):
        """Псевдоним clear_context_memory — для совместимости с вызовами delete_chat."""
        self.clear_context_memory(chat_id)

    # ─── Очистка всех чатов ─────────────────────────────────────────

    def clear_all_context(self):
        """Очистить память DeepSeek для ВСЕХ чатов (при 'Удалить все чаты')."""
        conn = sqlite3.connect(DEEPSEEK_MEMORY_DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM deepseek_memory")
        try:
            cur.execute("DELETE FROM sqlite_sequence WHERE name='deepseek_memory'")
        except Exception:
            pass
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        print(f"[DS_MEMORY] Очищена ВСЯ память DeepSeek ({deleted} записей)")
