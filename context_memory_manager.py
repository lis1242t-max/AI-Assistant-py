#!/usr/bin/env python3
# context_memory_manager.py
# Управление контекстной памятью для всех чатов

import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple

CONTEXT_DB = "context_memory.db"

class ContextMemoryManager:
    """Менеджер контекстной памяти - работа с контекстом для всех чатов"""
    
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных контекстной памяти"""
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        
        # Таблица контекстной памяти
        cur.execute("""
        CREATE TABLE IF NOT EXISTS context_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            context_type TEXT,
            content TEXT,
            created_at TEXT
        )
        """)
        
        # Индекс для быстрого поиска по chat_id
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_id 
        ON context_memory(chat_id)
        """)
        
        conn.commit()
        conn.close()
    
    def save_context_memory(self, chat_id: int, context_type: str, content: str):
        """Сохранить запись в контекстную память чата"""
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        
        now = datetime.utcnow().isoformat()
        
        cur.execute("""
        INSERT INTO context_memory (chat_id, context_type, content, created_at) 
        VALUES (?, ?, ?, ?)
        """, (chat_id, context_type, content, now))
        
        conn.commit()
        conn.close()
        print(f"[CONTEXT_MEMORY] Сохранено: chat_id={chat_id}, type={context_type}, длина={len(content)}")
    
    def get_context_memory(self, chat_id: int, limit: int = 10) -> List[Tuple]:
        """Получить контекстную память чата"""
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
    
    def clear_context_memory(self, chat_id: int):
        """Очистить контекстную память чата"""
        conn = sqlite3.connect(CONTEXT_DB)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM context_memory WHERE chat_id = ?", (chat_id,))
        
        deleted_count = cur.rowcount
        conn.commit()
        conn.close()
        print(f"[CONTEXT_MEMORY] Очищено записей: {deleted_count} для chat_id={chat_id}")
    
    def get_all_context(self, limit: int = 100) -> List[Tuple]:
        """Получить весь контекст (для всех чатов)"""
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
    
    def delete_chat_context(self, chat_id: int):
        """Удалить всю контекстную память чата (при удалении чата)"""
        self.clear_context_memory(chat_id)