"""
mistral_memory_manager.py — Изолированная память подтекста для Mistral Nemo.

Хранится в отдельной БД: mistral_memory.db
Не смешивается с context_memory.db (LLaMA) и deepseek_memory.db (DeepSeek).

Интерфейс полностью совместим с ContextMemoryManager из context_memory_manager.py:
    mm = MistralMemoryManager()
    mm.add_memory(text)
    memories = mm.get_relevant_memories(query, limit=5)
    mm.clear_all()
    mm.get_all_memories()
    mm.delete_memory(memory_id)
"""

import sqlite3
import os
import re
from datetime import datetime
from typing import List, Dict, Optional

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
    """

    def __init__(self, db_path: str = MISTRAL_MEMORY_DB):
        self.db_path = db_path
        self._init_db()

    # ── Инициализация ─────────────────────────────────────────────────────────
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS mistral_memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT    NOT NULL,
            keywords    TEXT,
            importance  REAL    DEFAULT 1.0,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            access_count INTEGER DEFAULT 0
        )
        """)
        # Индекс для быстрого поиска по ключевым словам
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_mistral_keywords ON mistral_memories(keywords)
        """)
        conn.commit()
        conn.close()
        print(f"[MISTRAL_MEMORY] ✓ БД инициализирована: {self.db_path}")

    # ── CRUD ─────────────────────────────────────────────────────────────────
    def add_memory(self, content: str, importance: float = 1.0) -> int:
        """
        Добавить новое воспоминание.
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
        INSERT INTO mistral_memories (content, keywords, importance, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """, (content, keywords, importance, now, now))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()

        print(f"[MISTRAL_MEMORY] ✓ Добавлено воспоминание #{row_id}: {content[:60]}…")
        return row_id

    def get_relevant_memories(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Получить воспоминания, релевантные запросу.
        Поиск по совпадению ключевых слов + важность.
        """
        if not query.strip():
            return self._get_recent_memories(limit)

        query_kw = set(self._extract_keywords(query).lower().split(","))
        query_kw = {k.strip() for k in query_kw if k.strip()}

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT id, content, keywords, importance, created_at, access_count
        FROM mistral_memories
        ORDER BY importance DESC, created_at DESC
        LIMIT 100
        """)
        rows = cur.fetchall()
        conn.close()

        scored = []
        for row in rows:
            _id, content, kw_str, importance, created_at, access_count = row
            mem_kw = set(kw_str.lower().split(",")) if kw_str else set()
            mem_kw = {k.strip() for k in mem_kw if k.strip()}

            # Пересечение ключевых слов
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
                "id":          _id,
                "content":     content,
                "score":       score,
                "importance":  importance,
                "created_at":  created_at,
                "access_count": access_count,
            })

        # Сортируем по score, берём top-limit
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

    def get_all_memories(self) -> List[Dict]:
        """Вернуть все воспоминания для отображения в UI."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT id, content, importance, created_at, access_count
        FROM mistral_memories
        ORDER BY created_at DESC
        """)
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "id":          r[0],
                "content":     r[1],
                "importance":  r[2],
                "created_at":  r[3],
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

    def clear_all(self):
        """Очистить всю память Mistral."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM mistral_memories")
        conn.commit()
        conn.close()
        print("[MISTRAL_MEMORY] 🧹 Память очищена")

    def count(self) -> int:
        """Количество воспоминаний."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM mistral_memories")
        n = cur.fetchone()[0]
        conn.close()
        return n

    # ── Вспомогательные ──────────────────────────────────────────────────────
    def _get_recent_memories(self, limit: int) -> List[Dict]:
        """Вернуть последние N воспоминаний (если нет запроса)."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT id, content, importance, created_at, access_count
        FROM mistral_memories
        ORDER BY created_at DESC
        LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "id":          r[0],
                "content":     r[1],
                "score":       r[2],
                "importance":  r[2],
                "created_at":  r[3],
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
        # Уникальные, сохраняя порядок
        seen = set()
        unique = []
        for w in kw:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        return ",".join(unique[:max_keywords])

    # ── Контекстная строка для промпта ───────────────────────────────────────
    def build_memory_context(self, query: str, limit: int = 5) -> str:
        """
        Возвращает готовый блок текста для вставки в системный промпт Mistral.
        Если воспоминаний нет — возвращает пустую строку.
        """
        memories = self.get_relevant_memories(query, limit=limit)
        if not memories:
            return ""

        lines = ["═══════════════════════════════════════",
                 "📝 ПАМЯТЬ (факты из предыдущих разговоров):",
                 "═══════════════════════════════════════"]
        for i, m in enumerate(memories, 1):
            lines.append(f"{i}. {m['content']}")
        lines.append("═══════════════════════════════════════")
        lines.append("Используй эти факты при ответе, если они релевантны.")
        return "\n".join(lines)

    def save_context_memory(self, chat_id, key: str, value: str):
        """
        Алиас для совместимости с ContextMemoryManager.
        Позволяет использовать MistralMemoryManager там, где ожидается
        ContextMemoryManager (вызовы context_mgr.save_context_memory(...)).
        chat_id игнорируется — Mistral хранит глобальную память без привязки к чату.
        """
        combined = f"[{key}] {value}"
        self.add_memory(combined)

    def get_context_memory(self, chat_id, limit: int = 20) -> list:
        """
        Алиас для совместимости с ContextMemoryManager.
        Возвращает список кортежей (key, value) — как ContextMemoryManager.
        chat_id игнорируется (память глобальная, без привязки к чату).

        Разбирает записи вида "[key] value" обратно в (key, value).
        Незнакомые записи возвращаются как ("user_memory", content).
        """
        rows = self._get_recent_memories(limit)
        result = []
        for row in rows:
            c = row.get("content", "")
            m = re.match(r'^\[([^\]]+)\]\s*(.*)', c, re.DOTALL)
            if m:
                result.append((m.group(1), m.group(2)))
            else:
                result.append(("user_memory", c))
        return result