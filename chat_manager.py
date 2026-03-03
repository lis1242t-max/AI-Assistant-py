#!/usr/bin/env python3
# chat_manager.py
# Управление чатами

import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple

CHATS_DB = "chats.db"

class ChatManager:
    """Менеджер чатов - работа с несколькими чатами"""
    
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных чатов"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        # Таблица чатов
        cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            created_at TEXT,
            updated_at TEXT,
            is_active INTEGER DEFAULT 0
        )
        """)
        
        # Таблица сообщений
        cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT,
            FOREIGN KEY (chat_id) REFERENCES chats(id)
        )
        """)
        
        # ── Миграции (добавляем колонки если их нет) ─────────────────
        _migrations = [
            ("attached_files",  "TEXT"),
            ("sources",         "TEXT"),
            ("speaker_name",    "TEXT"),
            ("regen_history",   "TEXT"),
            ("generated_files", "TEXT"),   # ← список файлов сгенерированных ИИ
        ]

        for col_name, col_type in _migrations:
            try:
                cur.execute(f"ALTER TABLE chat_messages ADD COLUMN {col_name} {col_type}")
                print(f"[DB_MIGRATION] ✓ Добавлена колонка {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print(f"[DB_MIGRATION] ℹ️ Колонка {col_name} уже существует")
                else:
                    print(f"[DB_MIGRATION] ⚠️ Ошибка миграции {col_name}: {e}")

        conn.commit()
        
        # Если нет чатов - создаём первый
        cur.execute("SELECT COUNT(*) FROM chats")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO chats (title, created_at, updated_at, is_active) VALUES (?, ?, ?, ?)",
                       ("Новый чат", datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), 1))
            conn.commit()
        
        conn.close()
    
    def create_chat(self, title: str = "Новый чат") -> int:
        """Создать новый чат"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        now = datetime.utcnow().isoformat()
        cur.execute("INSERT INTO chats (title, created_at, updated_at, is_active) VALUES (?, ?, ?, ?)",
                   (title, now, now, 0))
        chat_id = cur.lastrowid
        
        conn.commit()
        conn.close()
        
        return chat_id
    
    def get_all_chats(self) -> List[Dict]:
        """Получить список всех чатов"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("SELECT id, title, created_at, updated_at, is_active FROM chats ORDER BY updated_at DESC")
        rows = cur.fetchall()
        
        conn.close()
        
        chats = []
        for row in rows:
            chats.append({
                'id': row[0],
                'title': row[1],
                'created_at': row[2],
                'updated_at': row[3],
                'is_active': row[4] == 1
            })
        
        return chats
    
    def get_active_chat_id(self) -> Optional[int]:
        """Получить ID активного чата"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("SELECT id FROM chats WHERE is_active = 1 LIMIT 1")
        row = cur.fetchone()
        
        conn.close()
        
        return row[0] if row else None
    
    def set_active_chat(self, chat_id: int):
        """Установить активный чат"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        # Снять активность со всех
        cur.execute("UPDATE chats SET is_active = 0")
        
        # Установить активность на выбранный
        cur.execute("UPDATE chats SET is_active = 1 WHERE id = ?", (chat_id,))
        
        conn.commit()
        conn.close()
    
    def save_message(self,
                     chat_id: int,
                     role: str,
                     content: str,
                     attached_files: list = None,
                     sources: list = None,
                     speaker_name: str = None,
                     regen_history: list = None,
                     generated_files: list = None):
        """
        Сохранить сообщение в чат.

        generated_files — список dict {"filename":str,"content":str,"ext":str},
                          сгенерированных ИИ файлов для этого сообщения.
        """
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        now = datetime.utcnow().isoformat()
        
        files_json   = json.dumps(attached_files)  if attached_files  else None
        sources_json = json.dumps(sources)          if sources         else None
        regen_json   = json.dumps(regen_history)    if regen_history   else None
        gfiles_json  = json.dumps(generated_files)  if generated_files else None
        
        cur.execute("""
            INSERT INTO chat_messages
                (chat_id, role, content, attached_files, sources, created_at,
                 speaker_name, regen_history, generated_files)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (chat_id, role, content, files_json, sources_json, now,
              speaker_name, regen_json, gfiles_json))
        
        # Обновить время последнего обновления чата
        cur.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
        
        conn.commit()
        conn.close()
    
    def get_chat_messages(self, chat_id: int, limit: int = 50) -> List[Tuple]:
        """
        Получить сообщения чата.

        Возвращает список кортежей:
            (role, content, attached_files, sources, created_at,
             speaker_name, regen_history, generated_files)
        """
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("""
        SELECT role, content, attached_files, sources, created_at,
               speaker_name, regen_history, generated_files
        FROM chat_messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT ?
        """, (chat_id, limit))
        
        rows = cur.fetchall()
        conn.close()
        
        result = []
        for row in reversed(rows):
            (role, content, files_json, sources_json,
             created_at, speaker_name, regen_json, gfiles_json) = row

            files        = json.loads(files_json)   if files_json   else None
            sources      = json.loads(sources_json) if sources_json else []
            sources      = [tuple(s) for s in sources] if sources else []
            regen_history = json.loads(regen_json)  if regen_json   else None
            gen_files    = json.loads(gfiles_json)  if gfiles_json  else []

            result.append((role, content, files, sources, created_at,
                           speaker_name, regen_history, gen_files))
        
        return result
    
    def clear_chat_messages(self, chat_id: int):
        """Очистить сообщения чата"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
        
        conn.commit()
        conn.close()
    
    def get_last_assistant_message_id(self, chat_id: int) -> Optional[int]:
        """Вернуть DB id последнего сообщения ассистента в чате."""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        cur.execute("""SELECT id FROM chat_messages WHERE chat_id = ? AND role = 'assistant'
                       ORDER BY id DESC LIMIT 1""", (chat_id,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None

    def update_regen_history(self, chat_id: int, message_id: int, regen_history: list):
        """Обновить историю перегенерации у конкретного сообщения."""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        cur.execute("UPDATE chat_messages SET regen_history = ? WHERE id = ? AND chat_id = ?",
                    (json.dumps(regen_history), message_id, chat_id))
        conn.commit()
        conn.close()

    # ── Умная генерация заголовка ────────────────────────────────────────────
    @staticmethod
    def generate_smart_title(user_message: str) -> str:
        """
        Генерирует осмысленное название чата из первого сообщения пользователя.
        Социальные фразы (привет, спасибо, ок…) → тематический заголовок.
        Запросы определяются по ключевым словам.
        Длинные сообщения обрезаются аккуратно по слову.
        """
        import re as _re

        msg     = user_message.strip()
        msg_low = msg.lower().rstrip("!?.,;: ")

        # 1. Социальные фразы → тематический заголовок
        _SOCIAL = [
            (r"^(привет|здравствуй|добрый\s+\w+|хай|хей|йоу|ку|хелло)", "Новый разговор"),
            (r"^(hi|hello|hey|yo|sup)\b",                                  "New conversation"),
            (r"^(спасибо|благодар|спс)\b",                                 "Разговор"),
            (r"^(thanks|thank\s+you|thx)\b",                              "Conversation"),
            (r"^(ок|окей|хорошо|понял|ясно|угу|ага|да|нет|норм|ладно)\b", "Разговор"),
            (r"^(ok|okay|sure|got\s+it|yes|no|yep|yup|roger)\b",          "Conversation"),
            (r"^(круто|отлично|супер|класс|бомба|огонь|шикарно|прекрасно)", "Разговор"),
            (r"^(cool|great|awesome|nice|perfect|wow)\b",                  "Conversation"),
        ]
        for pat, ttl in _SOCIAL:
            if _re.match(pat, msg_low, _re.IGNORECASE):
                return ttl

        # 2. Тематические ключевые слова
        _TOPICS = [
            (r"создай\s+файл|сгенерируй\s+файл|сделай\s+файл",                  "Создание файла"),
            (r"create\s+(a\s+)?file|make\s+(a\s+)?file",                       "Creating a file"),
            (r"(напиши|создай|сделай)\s+(код|скрипт|программу|функцию|класс)",    "Написание кода"),
            (r"(write|create|make)\s+(code|script|program|function|class)",       "Writing code"),
            (r"переведи|перевод",                                                   "Перевод"),
            (r"translat(e|ion)",                                                    "Translation"),
            (r"объясни|расскажи\s+о\b|что\s+такое",                             "Объяснение темы"),
            (r"explain|tell\s+me\s+about|what\s+is\b",                         "Explanation"),
            (r"помоги|помощь|как\s+(мне\s+|можно\s+)?",                         "Вопрос и помощь"),
            (r"help\s+(me\s+)?(with\s+)?|how\s+(do|can)\b",                   "Help & question"),
            (r"список|перечисли|примеры|топ\b",                                   "Список / подборка"),
            (r"\blist\b|enumerate|examples?\b|\btop\b",                       "List / examples"),
            (r"напиши\s+(письмо|текст|пост|статью|эссе|резюме|описание)",         "Написание текста"),
            (r"write\s+(a\s+)?(letter|text|post|article|essay|resume|description)", "Writing text"),
            (r"посчитай|вычисли|реши\b|сколько\s+будет",                         "Математика"),
            (r"\b(calculate|compute|solve)\b|how\s+much\b",                    "Math"),
            (r"\b(найди|поищи|погугли)\b",                                       "Поиск информации"),
            (r"\b(find|search|look\s+up|google)\b",                             "Search"),
        ]
        for pat, ttl in _TOPICS:
            if _re.search(pat, msg_low, _re.IGNORECASE):
                return ttl

        # 3. Обрезка — берём суть до первой точки/переноса
        clean = _re.sub(r"^[\s\-\u2013\u2014\u2022*#]+", "", msg)
        first = _re.split(r"[.\n]", clean)[0].strip()
        if 6 <= len(first) <= 50:
            return first[:50]
        if len(clean) <= 42:
            return clean
        cut = clean[:42]
        sp  = cut.rfind(" ")
        return (cut[:sp] if sp > 20 else cut) + "\u2026"

    def update_chat_title(self, chat_id: int, title: str):
        """Обновить название чата"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
                   (title, datetime.utcnow().isoformat(), chat_id))
        
        conn.commit()
        conn.close()
    
    def delete_chat(self, chat_id: int):
        """Удалить чат полностью (чат и все его сообщения)"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
        cur.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        
        conn.commit()
        conn.close()
    
    def delete_all_chats(self) -> int:
        """
        Удалить ВСЕ чаты и их сообщения, создать новый пустой чат.
        Возвращает ID нового чата.
        """
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM chat_messages")
        cur.execute("DELETE FROM chats")
        
        now = datetime.utcnow().isoformat()
        cur.execute("INSERT INTO chats (title, created_at, updated_at, is_active) VALUES (?, ?, ?, ?)",
                   ("Новый чат", now, now, 1))
        new_chat_id = cur.lastrowid
        
        conn.commit()
        conn.close()
        
        return new_chat_id