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
    
    def save_message(self, chat_id: int, role: str, content: str):
        """Сохранить сообщение в чат"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        now = datetime.utcnow().isoformat()
        
        cur.execute("INSERT INTO chat_messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                   (chat_id, role, content, now))
        
        # Обновить время последнего обновления чата
        cur.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
        
        conn.commit()
        conn.close()
    
    def get_chat_messages(self, chat_id: int, limit: int = 50) -> List[Tuple]:
        """Получить сообщения чата"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("""
        SELECT role, content, created_at 
        FROM chat_messages 
        WHERE chat_id = ? 
        ORDER BY id DESC 
        LIMIT ?
        """, (chat_id, limit))
        
        rows = cur.fetchall()
        conn.close()
        
        return list(reversed(rows))
    
    def clear_chat_messages(self, chat_id: int):
        """Очистить сообщения чата"""
        conn = sqlite3.connect(CHATS_DB)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
        
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