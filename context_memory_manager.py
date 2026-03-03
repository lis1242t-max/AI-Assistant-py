#!/usr/bin/env python3
# context_memory_manager.py
# Управление контекстной памятью для всех чатов
#
# ИСПРАВЛЕНО: добавлена защита от дублирования записей одного типа,
# добавлен clear_all_context со сбросом автоинкремента,
# все запросы явно фильтруют по chat_id.

import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional

CONTEXT_DB = "context_memory.db"


class ContextMemoryManager:
    """Менеджер контекстной памяти — работа с контекстом для всех чатов.
    
    Изоляция: каждая запись привязана к chat_id.
    Запросы между чатами невозможны — WHERE chat_id=? стоит везде.
    """

    def __init__(self):
        self.init_db()

    # ── Инициализация ─────────────────────────────────────────────────────────

    def init_db(self):
        """Инициализация базы данных контекстной памяти."""
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS context_memory (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id      INTEGER NOT NULL,
            context_type TEXT    NOT NULL,
            content      TEXT    NOT NULL,
            created_at   TEXT    NOT NULL
        )
        """)

        # Составной индекс — быстрый поиск по чату и типу
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_type
        ON context_memory(chat_id, context_type)
        """)

        # Таблица истории диалога (повороты user/assistant)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS context_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER NOT NULL,
            role        TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        )
        """)
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ctx_msg_chat
        ON context_messages(chat_id)
        """)

        conn.commit()
        conn.close()

    # ── Запись ───────────────────────────────────────────────────────────────

    def save_context_memory(self, chat_id: int, context_type: str, content: str):
        """
        Сохранить запись в контекстную память чата.
        Записи разных context_type накапливаются (не перезаписываются).
        Изоляция: chat_id всегда сохраняется в БД и фильтрует все запросы.
        """
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute("""
        INSERT INTO context_memory (chat_id, context_type, content, created_at)
        VALUES (?, ?, ?, ?)
        """, (chat_id, context_type, content, now))
        conn.commit()
        conn.close()
        print(f"[CONTEXT_MEMORY] Сохранено: chat_id={chat_id}, "
              f"type={context_type}, длина={len(content)}")

    def upsert_context_memory(self, chat_id: int, context_type: str, content: str):
        """
        Обновить запись если существует, иначе создать.
        Используй вместо save_context_memory когда запись должна быть одна
        (например, профиль пользователя, текущий файл).
        """
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()

        cur.execute("""
        SELECT id FROM context_memory
        WHERE chat_id = ? AND context_type = ?
        ORDER BY id DESC LIMIT 1
        """, (chat_id, context_type))
        row = cur.fetchone()

        if row:
            cur.execute("""
            UPDATE context_memory SET content = ?, created_at = ?
            WHERE id = ?
            """, (content, now, row[0]))
        else:
            cur.execute("""
            INSERT INTO context_memory (chat_id, context_type, content, created_at)
            VALUES (?, ?, ?, ?)
            """, (chat_id, context_type, content, now))

        conn.commit()
        conn.close()
        print(f"[CONTEXT_MEMORY] Upsert: chat_id={chat_id}, type={context_type}")

    # ── Чтение ───────────────────────────────────────────────────────────────

    def get_context_memory(self, chat_id: int, limit: int = 10) -> List[Tuple]:
        """
        Получить контекстную память чата.
        Возвращает список (context_type, content, created_at) от старых к новым.
        Строго только для данного chat_id.
        """
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        cur.execute("""
        SELECT context_type, content, created_at
        FROM context_memory
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT ?
        """, (chat_id, limit))
        rows = cur.fetchall()
        conn.close()
        return list(reversed(rows))

    def get_context_by_type(self, chat_id: int, context_type: str,
                            limit: int = 5) -> List[Tuple]:
        """
        Получить записи конкретного типа для данного чата.
        Удобно для выборки только file_analysis или только user_memory.
        """
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        cur.execute("""
        SELECT context_type, content, created_at
        FROM context_memory
        WHERE chat_id = ? AND context_type = ?
        ORDER BY id DESC
        LIMIT ?
        """, (chat_id, context_type, limit))
        rows = cur.fetchall()
        conn.close()
        return list(reversed(rows))

    def get_all_context(self, limit: int = 100) -> List[Tuple]:
        """
        Получить весь контекст (для всех чатов) — только для отладки/UI.
        Не использовать при формировании промпта для ИИ.
        """
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        cur.execute("""
        SELECT chat_id, context_type, content, created_at
        FROM context_memory
        ORDER BY id DESC
        LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return list(reversed(rows))

    # ── Диалоговая история (user/assistant повороты) ─────────────────────────

    def save_message(self, chat_id: int, role: str, content: str):
        """
        Сохранить один поворот диалога в context_messages.
        role: "user" | "assistant"
        Вызывать ПОСЛЕ каждого сообщения пользователя и ПОСЛЕ каждого ответа ИИ.
        Изоляция: запись привязана к chat_id — кросс-чат утечка исключена.
        """
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO context_messages (chat_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, role, content, now)
        )
        conn.commit()
        conn.close()
        print(f"[CONTEXT_MEMORY] Сообщение: chat_id={chat_id}, role={role}, len={len(content)}")

    def get_messages(self, chat_id: int, limit: int = 20) -> List[dict]:
        """
        Получить историю диалога в формате [{"role": ..., "content": ...}, ...].
        Готов для прямой передачи в Ollama API как поле 'messages'.
        Только для данного chat_id — кросс-чат утечка исключена.
        """
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM context_messages "
            "WHERE chat_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        )
        rows = cur.fetchall()
        conn.close()
        # Разворачиваем: получены от новых к старым, нужно от старых к новым
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    # ── Очистка ──────────────────────────────────────────────────────────────

    def clear_context_memory(self, chat_id: int):
        """Очистить контекстную память и историю диалога конкретного чата."""
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM context_memory WHERE chat_id = ?", (chat_id,))
        deleted = cur.rowcount
        cur.execute("DELETE FROM context_messages WHERE chat_id = ?", (chat_id,))
        msg_deleted = cur.rowcount
        conn.commit()
        conn.close()
        print(f"[CONTEXT_MEMORY] Очищено {deleted} записей памяти и {msg_deleted} "
              f"сообщений для chat_id={chat_id}")

    def delete_chat_context(self, chat_id: int):
        """Удалить всю контекстную память чата (при удалении чата)."""
        self.clear_context_memory(chat_id)

    def clear_all_context(self):
        """Очистить контекстную память и историю диалогов ВСЕХ чатов."""
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM context_memory")
        cur.execute("DELETE FROM context_messages")
        try:
            cur.execute("DELETE FROM sqlite_sequence WHERE name='context_memory'")
            cur.execute("DELETE FROM sqlite_sequence WHERE name='context_messages'")
        except Exception:
            pass
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        print(f"[CONTEXT_MEMORY] ✓ Очищена ВСЯ контекстная память и история диалогов ({deleted} записей)")