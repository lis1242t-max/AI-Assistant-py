"""
mistral_memory_manager.py — Изолированная память подтекста для Mistral Nemo.

Хранится в отдельной БД: mistral_memory.db
Не смешивается с context_memory.db (LLaMA) и deepseek_memory.db (DeepSeek).

ИСПРАВЛЕНО: добавлена полная изоляция по chat_id — воспоминания одного чата
никогда не попадают в другой чат.

Интерфейс полностью совместим с ContextMemoryManager из context_memory_manager.py:
    mm = MistralMemoryManager()
    mm.add_memory(chat_id, text)
    memories = mm.get_relevant_memories(chat_id, query, limit=5)
    mm.clear_all(chat_id)
    mm.get_all_memories(chat_id)
    mm.delete_memory(memory_id)
    mm.save_context_memory(chat_id, key, value)   # совместимость
    mm.get_context_memory(chat_id, limit)          # совместимость
"""

import sqlite3
import os
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# Абсолютный путь — БД всегда рядом с этим файлом,
# независимо от рабочей директории при запуске.
MISTRAL_MEMORY_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mistral_memory.db"
)


class MistralMemoryManager:
    """
    Менеджер памяти подтекста для Mistral Nemo.
    Изолированная БД — не влияет на LLaMA и DeepSeek.
    Каждое воспоминание привязано к chat_id — кросс-чат утечка невозможна.
    """

    def __init__(self, db_path: str = MISTRAL_MEMORY_DB):
        self.db_path = db_path
        self._init_db()

    # ── Инициализация ─────────────────────────────────────────────────────────

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Таблица с колонкой chat_id для полной изоляции чатов
        cur.execute("""
        CREATE TABLE IF NOT EXISTS mistral_memories (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id      INTEGER NOT NULL DEFAULT 0,
            content      TEXT    NOT NULL,
            keywords     TEXT,
            importance   REAL    DEFAULT 1.0,
            created_at   TEXT    NOT NULL,
            updated_at   TEXT    NOT NULL,
            access_count INTEGER DEFAULT 0
        )
        """)

        # Миграция старых записей без chat_id (если БД уже существовала)
        # Добавляем колонку chat_id если её ещё нет (для совместимости со старой схемой)
        # ВАЖНО: миграция должна быть ДО создания индекса по chat_id
        try:
            cur.execute("ALTER TABLE mistral_memories ADD COLUMN chat_id INTEGER NOT NULL DEFAULT 0")
            print("[MISTRAL_MEMORY] ✓ Миграция: добавлена колонка chat_id (старые записи → chat_id=0)")
        except sqlite3.OperationalError:
            pass  # Колонка уже есть — всё нормально

        # Составной индекс: chat_id + keywords — быстрый поиск внутри чата
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_mistral_chat_keywords
        ON mistral_memories(chat_id, keywords)
        """)

        # Таблица истории диалога (повороты user/assistant)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS mistral_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER NOT NULL,
            role        TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        )
        """)
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_mistral_msg_chat
        ON mistral_messages(chat_id)
        """)

        conn.commit()
        conn.close()
        print(f"[MISTRAL_MEMORY] ✓ БД инициализирована: {self.db_path}")

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add_memory(self, content: str, importance: float = 1.0,
                   chat_id: int = 0) -> int:
        """
        Добавить новое воспоминание, привязанное к chat_id.
        Возвращает id вставленной записи.
        """
        content = content.strip()
        if not content:
            return -1

        keywords = self._extract_keywords(content)
        now = datetime.utcnow().isoformat()

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO mistral_memories
            (chat_id, content, keywords, importance, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, content, keywords, importance, now, now))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()

        print(f"[MISTRAL_MEMORY] ✓ Добавлено #{row_id} (chat_id={chat_id}): {content[:60]}…")
        return row_id

    def get_relevant_memories(self, query: str, limit: int = 5,
                              chat_id: int = 0) -> List[Dict]:
        """
        Получить воспоминания, релевантные запросу, ТОЛЬКО для данного chat_id.
        Поиск по совпадению ключевых слов + важность.
        """
        if not query.strip():
            return self._get_recent_memories(limit, chat_id)

        query_kw = set(self._extract_keywords(query).lower().split(","))
        query_kw = {k.strip() for k in query_kw if k.strip()}

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        # Выбираем только записи этого чата
        cur.execute("""
        SELECT id, content, keywords, importance, created_at, access_count
        FROM mistral_memories
        WHERE chat_id = ?
        ORDER BY importance DESC, created_at DESC
        LIMIT 100
        """, (chat_id,))
        rows = cur.fetchall()
        conn.close()

        scored = []
        for row in rows:
            _id, content, kw_str, importance, created_at, access_count = row
            mem_kw = set(kw_str.lower().split(",")) if kw_str else set()
            mem_kw = {k.strip() for k in mem_kw if k.strip()}

            intersection = query_kw & mem_kw
            if not intersection:
                # Мягкий поиск: есть ли слова из запроса в тексте
                content_lower = content.lower()
                soft_score = sum(1 for w in query_kw if w and w in content_lower)
                if soft_score == 0:
                    continue
                score = soft_score * 0.5
            else:
                score = len(intersection) * importance

            scored.append({
                "id":           _id,
                "content":      content,
                "score":        score,
                "importance":   importance,
                "created_at":   created_at,
                "access_count": access_count,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[:limit]

        # Помечаем использованные (increment access_count)
        if top:
            ids = [m["id"] for m in top]
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                f"UPDATE mistral_memories SET access_count = access_count + 1 "
                f"WHERE id IN ({','.join('?' for _ in ids)})",
                ids
            )
            conn.commit()
            conn.close()

        return top

    def get_all_memories(self, chat_id: int = 0) -> List[Dict]:
        """Вернуть все воспоминания данного chat_id для отображения в UI."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT id, content, importance, created_at, access_count
        FROM mistral_memories
        WHERE chat_id = ?
        ORDER BY created_at DESC
        """, (chat_id,))
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "id":           r[0],
                "content":      r[1],
                "importance":   r[2],
                "created_at":   r[3],
                "access_count": r[4],
            }
            for r in rows
        ]

    def delete_memory(self, memory_id: int):
        """Удалить воспоминание по id."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM mistral_memories WHERE id = ?", (memory_id,))
        conn.commit()
        conn.close()
        print(f"[MISTRAL_MEMORY] 🗑 Удалено воспоминание #{memory_id}")

    # ── Диалоговая история (user/assistant повороты) ─────────────────────────

    def save_message(self, chat_id: int, role: str, content: str):
        """
        Сохранить один поворот диалога в mistral_messages.
        role: "user" | "assistant"
        Вызывать ПОСЛЕ каждого сообщения пользователя и ПОСЛЕ каждого ответа Mistral.
        Изоляция: запись привязана к chat_id — кросс-чат утечка исключена.
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO mistral_messages (chat_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, role, content, now)
        )
        conn.commit()
        conn.close()
        print(f"[MISTRAL_MEMORY] Сообщение: chat_id={chat_id}, role={role}, len={len(content)}")

    def get_messages(self, chat_id: int, limit: int = 20) -> List[Dict]:
        """
        Получить историю диалога в формате [{"role": ..., "content": ...}, ...].
        Готов для прямой передачи в Ollama API как поле 'messages'.
        Только для данного chat_id — кросс-чат утечка исключена.
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM mistral_messages "
            "WHERE chat_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        )
        rows = cur.fetchall()
        conn.close()
        # Разворачиваем: получены от новых к старым, нужно от старых к новым
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    def clear_all(self, chat_id: int = 0):
        """Очистить всю память и историю диалога Mistral для данного chat_id."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM mistral_memories WHERE chat_id = ?", (chat_id,))
        deleted = cur.rowcount
        cur.execute("DELETE FROM mistral_messages WHERE chat_id = ?", (chat_id,))
        msg_deleted = cur.rowcount
        conn.commit()
        conn.close()
        print(f"[MISTRAL_MEMORY] 🧹 Память очищена (chat_id={chat_id}, "
              f"удалено {deleted} воспоминаний и {msg_deleted} сообщений)")

    def clear_all_context(self):
        """Очистить ВСЮ память и историю диалогов Mistral — все чаты."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM mistral_memories")
        cur.execute("DELETE FROM mistral_messages")
        try:
            cur.execute("DELETE FROM sqlite_sequence WHERE name='mistral_memories'")
            cur.execute("DELETE FROM sqlite_sequence WHERE name='mistral_messages'")
        except Exception:
            pass
        conn.commit()
        conn.close()
        print("[MISTRAL_MEMORY] 🧹 ВСЯ память и история диалогов очищены (все чаты)")

    def count(self, chat_id: int = 0) -> int:
        """Количество воспоминаний для данного chat_id."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM mistral_memories WHERE chat_id = ?", (chat_id,))
        n = cur.fetchone()[0]
        conn.close()
        return n

    # ── Вспомогательные ──────────────────────────────────────────────────────

    def _get_recent_memories(self, limit: int, chat_id: int = 0) -> List[Dict]:
        """Вернуть последние N воспоминаний данного чата (если нет запроса)."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT id, content, importance, created_at, access_count
        FROM mistral_memories
        WHERE chat_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """, (chat_id, limit))
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "id":           r[0],
                "content":      r[1],
                "score":        r[2],
                "importance":   r[2],
                "created_at":   r[3],
                "access_count": r[4],
            }
            for r in rows
        ]

    @staticmethod
    def _extract_keywords(text: str, max_keywords: int = 20) -> str:
        """
        Извлекает ключевые слова из текста для индексирования.
        Убирает стоп-слова, берёт слова длиннее 3 символов.
        """
        STOP_WORDS = {
            "это", "как", "что", "для", "или", "при", "нет", "все", "так",
            "его", "её", "их", "они", "мне", "мне", "тот", "был", "уже",
            "на", "в", "с", "и", "а", "но", "же", "бы", "by", "to", "is",
            "the", "a", "an", "of", "in", "for", "and", "or", "not", "it",
            "this", "that", "was", "with", "are", "be", "as", "at", "do",
        }
        words = re.findall(r'[a-zA-Zа-яА-ЯёЁ]{4,}', text.lower())
        kw = [w for w in words if w not in STOP_WORDS]
        seen = set()
        unique = []
        for w in kw:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        return ",".join(unique[:max_keywords])

    # ── Контекстная строка для промпта ───────────────────────────────────────

    def build_memory_context(self, query: str, limit: int = 5,
                             chat_id: int = 0) -> str:
        """
        Возвращает готовый блок текста для вставки в системный промпт Mistral.
        Если воспоминаний нет — возвращает пустую строку.
        Работает только в рамках данного chat_id.
        """
        memories = self.get_relevant_memories(query, limit=limit, chat_id=chat_id)
        if not memories:
            return ""

        lines = [
            "═══════════════════════════════════════",
            "📝 ПАМЯТЬ (факты из предыдущих разговоров):",
            "═══════════════════════════════════════",
        ]
        for i, m in enumerate(memories, 1):
            lines.append(f"{i}. {m['content']}")
        lines.append("═══════════════════════════════════════")
        lines.append("Используй эти факты при ответе, если они релевантны.")
        return "\n".join(lines)

    # ── Алиасы совместимости с ContextMemoryManager ──────────────────────────

    def save_context_memory(self, chat_id: int, key: str, value: str):
        """
        Совместимость с ContextMemoryManager.
        chat_id теперь ИСПОЛЬЗУЕТСЯ — память изолирована по чату.
        """
        combined = f"[{key}] {value}"
        self.add_memory(combined, chat_id=chat_id)

    def get_context_memory(self, chat_id: int, limit: int = 20) -> List[Tuple]:
        """
        Совместимость с ContextMemoryManager.
        Возвращает список кортежей (key, value) — только для данного chat_id.
        Разбирает записи вида "[key] value" обратно в (key, value).
        """
        rows = self._get_recent_memories(limit, chat_id=chat_id)
        result = []
        for row in rows:
            c = row.get("content", "")
            m = re.match(r'^\[([^\]]+)\]\s*(.*)', c, re.DOTALL)
            if m:
                result.append((m.group(1), m.group(2)))
            else:
                result.append(("user_memory", c))
        return result

    def delete_chat_context(self, chat_id: int):
        """Удалить всю память Mistral для конкретного чата (при удалении чата)."""
        self.clear_all(chat_id=chat_id)
        print(f"[MISTRAL_MEMORY] 🗑 Чат {chat_id} — память удалена")

    def on_chat_switch(self, new_chat_id: int):
        """
        Совместимость с DeepSeekMemoryManager.
        У Mistral нет состояния между чатами — просто логируем.
        Изоляция обеспечивается через chat_id в каждом запросе.
        """
        print(f"[MISTRAL_MEMORY] Переключение на чат {new_chat_id} (изоляция по chat_id активна)")