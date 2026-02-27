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
        
        # МИГРАЦИЯ: Добавляем колонку attached_files если её нет
        try:
            cur.execute("ALTER TABLE chat_messages ADD COLUMN attached_files TEXT")
            print("[DB_MIGRATION] ✓ Добавлена колонка attached_files")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("[DB_MIGRATION] ℹ️ Колонка attached_files уже существует")
            else:
                print(f"[DB_MIGRATION] ⚠️ Ошибка миграции: {e}")

        # МИГРАЦИЯ: Добавляем колонку sources если её нет
        try:
            cur.execute("ALTER TABLE chat_messages ADD COLUMN sources TEXT")
            print("[DB_MIGRATION] ✓ Добавлена колонка sources")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("[DB_MIGRATION] ℹ️ Колонка sources уже существует")
            else:
                print(f"[DB_MIGRATION] ⚠️ Ошибка миграции sources: {e}")

        # МИГРАЦИЯ: Добавляем колонку speaker_name если её нет
        try:
            cur.execute("ALTER TABLE chat_messages ADD COLUMN speaker_name TEXT")
            print("[DB_MIGRATION] ✓ Добавлена колонка speaker_name")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("[DB_MIGRATION] ℹ️ Колонка speaker_name уже существует")
            else:
                print(f"[DB_MIGRATION] ⚠️ Ошибка миграции speaker_name: {e}")

        # МИГРАЦИЯ: История перегенерации
        try:
            cur.execute("ALTER TABLE chat_messages ADD COLUMN regen_history TEXT")
            print("[DB_MIGRATION] ✓ Добавлена колонка regen_history")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("[DB_MIGRATION] ℹ️ Колонка regen_history уже существует")
            else:
                print(f"[DB_MIGRATION] ⚠️ Ошибка миграции regen_history: {e}")
        
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
    
    def save_message(self, chat_id: int, role: str, content: str, attached_files: list = None, sources: list = None, speaker_name: str = None, regen_history: list = None):
        """Сохранить сообщение в чат с прикреплёнными файлами, источниками, именем ИИ и историей перегенерации"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        now = datetime.utcnow().isoformat()
        
        # Сериализуем список файлов в JSON
        files_json = json.dumps(attached_files) if attached_files else None
        # Сериализуем источники [(title, url), ...] в JSON
        sources_json = json.dumps(sources) if sources else None
        # История перегенерации
        regen_json = json.dumps(regen_history) if regen_history else None
        
        cur.execute("INSERT INTO chat_messages (chat_id, role, content, attached_files, sources, created_at, speaker_name, regen_history) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (chat_id, role, content, files_json, sources_json, now, speaker_name, regen_json))
        
        # Обновить время последнего обновления чата
        cur.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
        
        conn.commit()
        conn.close()
    
    def get_chat_messages(self, chat_id: int, limit: int = 50) -> List[Tuple]:
        """Получить сообщения чата с прикреплёнными файлами"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("""
        SELECT role, content, attached_files, sources, created_at, speaker_name, regen_history
        FROM chat_messages 
        WHERE chat_id = ? 
        ORDER BY id DESC 
        LIMIT ?
        """, (chat_id, limit))
        
        rows = cur.fetchall()
        conn.close()
        
        # Десериализуем файлы, источники и историю перегенерации из JSON
        result = []
        for row in reversed(rows):
            role, content, files_json, sources_json, created_at, speaker_name, regen_json = row
            files = json.loads(files_json) if files_json else None
            sources = json.loads(sources_json) if sources_json else []
            sources = [tuple(s) for s in sources] if sources else []
            regen_history = json.loads(regen_json) if regen_json else None
            result.append((role, content, files, sources, created_at, speaker_name, regen_history))
        
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
        """Обновить историю перегенерации у конкретного сообщения (вызывается после каждой регенерации)."""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        cur.execute("UPDATE chat_messages SET regen_history = ? WHERE id = ? AND chat_id = ?",
                    (json.dumps(regen_history), message_id, chat_id))
        conn.commit()
        conn.close()

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
        
        # Удаляем все сообщения чата
        cur.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
        
        # Удаляем сам чат
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
        
        # Удаляем все сообщения
        cur.execute("DELETE FROM chat_messages")
        
        # Удаляем все чаты
        cur.execute("DELETE FROM chats")
        
        # Создаём новый чат
        now = datetime.utcnow().isoformat()
        cur.execute("INSERT INTO chats (title, created_at, updated_at, is_active) VALUES (?, ?, ?, ?)",
                   ("Новый чат", now, now, 1))
        new_chat_id = cur.lastrowid
        
        conn.commit()
        conn.close()
        
        return new_chat_id