#!/usr/bin/env python3
# qwen_memory_manager.py
# ═══════════════════════════════════════════════════════════════════
# Отдельная контекстная память для Qwen 3.5.
# Полностью изолирована от памяти LLaMA / DeepSeek / Mistral.
# Своя БД: qwen_memory.db
#
# Архитектура идентична DeepSeek:
# - Нет WAL / синхронных режимов — обычный SQLite без -wal/-shm файлов
# - Изоляция по chat_id на уровне каждого SQL-запроса
# - on_chat_switch только логирует, не очищает
# - Все операции явно принимают chat_id как аргумент
# ═══════════════════════════════════════════════════════════════════

import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional

QWEN_MEMORY_DB = "qwen_memory.db"


class QwenMemoryManager:
    """
    Менеджер памяти для Qwen 3.5.
    Работает исключительно с qwen_memory.db.
    Не читает и не пишет в context_memory.db (LLaMA) или другие БД.

    Изоляция по chat_id обеспечивается на уровне каждого SQL-запроса.
    """

    def __init__(self):
        self._init_db()

    # ─── Инициализация БД ────────────────────────────────────────────

    def _init_db(self):
        conn = sqlite3.connect(QWEN_MEMORY_DB)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS qwen_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                entry_type  TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_qwen_chat
            ON qwen_memory(chat_id)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS qwen_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                role        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_qwen_msg_chat
            ON qwen_messages(chat_id)
        """)
        conn.commit()
        conn.close()
        print(f"[QWEN_MEMORY] ✓ БД инициализирована: {QWEN_MEMORY_DB}")

    # ─── Смена чата ──────────────────────────────────────────────────

    def on_chat_switch(self, new_chat_id: int):
        print(f"[QWEN_MEMORY] Переключение на чат {new_chat_id} (изоляция по chat_id активна)")

    def on_chat_cleared(self, chat_id: int):
        self.clear_context_memory(chat_id)
        print(f"[QWEN_MEMORY] Чат {chat_id} очищен — память сброшена.")

    # ─── Запись ──────────────────────────────────────────────────────

    def save_context_memory(self, chat_id: int, entry_type: str, content: str):
        conn = sqlite3.connect(QWEN_MEMORY_DB)
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO qwen_memory (chat_id, entry_type, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, entry_type, content, now)
        )
        conn.commit()
        conn.close()
        print(f"[QWEN_MEMORY] Сохранено: chat_id={chat_id}, type={entry_type}, len={len(content)}")

    def save_message(self, chat_id: int, role: str, content: str):
        conn = sqlite3.connect(QWEN_MEMORY_DB)
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO qwen_messages (chat_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, role, content, now)
        )
        conn.commit()
        conn.close()
        print(f"[QWEN_MEMORY] Сообщение: chat_id={chat_id}, role={role}, len={len(content)}")

    # ─── Чтение ──────────────────────────────────────────────────────

    def get_messages(self, chat_id: int, limit: int = 20) -> List[dict]:
        conn = sqlite3.connect(QWEN_MEMORY_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM qwen_messages "
            "WHERE chat_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        )
        rows = cur.fetchall()
        conn.close()
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    def get_context_memory(self, chat_id: int, limit: int = 12) -> List[Tuple]:
        conn = sqlite3.connect(QWEN_MEMORY_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT entry_type, content, created_at "
            "FROM qwen_memory "
            "WHERE chat_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        )
        rows = cur.fetchall()
        conn.close()
        return list(reversed(rows))

    # ─── Очистка одного чата ────────────────────────────────────────

    def clear_context_memory(self, chat_id: int):
        conn = sqlite3.connect(QWEN_MEMORY_DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM qwen_memory WHERE chat_id = ?", (chat_id,))
        meta_deleted = cur.rowcount
        cur.execute("DELETE FROM qwen_messages WHERE chat_id = ?", (chat_id,))
        msg_deleted = cur.rowcount
        conn.commit()
        conn.close()
        print(f"[QWEN_MEMORY] Очищено {meta_deleted} метазаписей и {msg_deleted} "
              f"сообщений для chat_id={chat_id}")

    def delete_chat_context(self, chat_id: int):
        """Псевдоним для совместимости с вызовами delete_chat."""
        self.clear_context_memory(chat_id)

    def clear_all(self, chat_id: Optional[int] = None):
        """Совместимость с интерфейсом MistralMemoryManager."""
        if chat_id is not None:
            self.clear_context_memory(chat_id)
        else:
            self.clear_all_context()

    # ─── Очистка всех чатов ─────────────────────────────────────────

    def clear_all_context(self):
        conn = sqlite3.connect(QWEN_MEMORY_DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM qwen_memory")
        cur.execute("DELETE FROM qwen_messages")
        try:
            cur.execute("DELETE FROM sqlite_sequence WHERE name='qwen_memory'")
            cur.execute("DELETE FROM sqlite_sequence WHERE name='qwen_messages'")
        except Exception:
            pass
        conn.commit()
        conn.close()
        print("[QWEN_MEMORY] Очищена ВСЯ память Qwen (метаданные + история диалогов)")