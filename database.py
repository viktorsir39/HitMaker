import aiosqlite
import asyncio
import logging
from config import DB_PATH

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None
        self._lock = asyncio.Lock()

    async def connect(self):
        if not self._conn:
            self._conn = await aiosqlite.connect(self.db_path)
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self.create_tables()
            logging.info("✅ Успешное подключение к БД (Синглтон)")

    async def execute(self, sql, params=None):
        if not self._conn:
            await self.connect()
        async with self._lock:
            return await self._conn.execute(sql, params or [])

    async def commit(self):
        if not self._conn:
            await self.connect()
        async with self._lock:
            await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None
            logging.info("🔌 Соединение с БД закрыто")

    async def create_tables(self):
        await self._conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                credits INTEGER DEFAULT 0,
                referrer TEXT,
                referrals INTEGER DEFAULT 0
            )
        ''')
        await self._conn.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                title TEXT,
                style TEXT,
                audio_file_id TEXT,
                cover_file_id TEXT,
                likes INTEGER DEFAULT 0
            )
        ''')
        await self._conn.commit()

# Глобальный экземпляр
db_instance = Database(DB_PATH)

# Обертки для совместимости со старым кодом FSM
async def get_user(user_id: str):
    cur = await db_instance.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = await cur.fetchone()
    if row: return {"id": row[0], "credits": row[1], "referrer": row[2], "referrals": row[3]}
    return None

async def create_user(user_id: str, referrer: str = None):
    await db_instance.execute("INSERT OR IGNORE INTO users (id, credits, referrer) VALUES (?, ?, ?)", (user_id, 0, referrer))
    if referrer:
        await db_instance.execute("UPDATE users SET referrals = referrals + 1 WHERE id=?", (referrer,))
    await db_instance.commit()

async def update_credits(user_id: str, amount: int):
    await db_instance.execute("UPDATE users SET credits = credits + ? WHERE id=?", (amount, user_id))
    await db_instance.commit()

async def try_spend_credits(user_id: str, amount: int) -> bool:
    if not db_instance._conn: await db_instance.connect()
    async with db_instance._lock:
        cur = await db_instance._conn.execute("SELECT credits FROM users WHERE id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0] >= amount:
            await db_instance._conn.execute("UPDATE users SET credits = credits - ? WHERE id=?", (amount, user_id))
            await db_instance._conn.commit()
            return True
        return False

async def add_song(user_id: str, title: str, style: str, audio_file_id: str, cover_file_id: str = None):
    await db_instance.execute("INSERT INTO songs (user_id, title, style, audio_file_id, cover_file_id) VALUES (?, ?, ?, ?, ?)",
                              (user_id, title, style, audio_file_id, cover_file_id))
    await db_instance.commit()

async def get_user_songs(user_id: str):
    cur = await db_instance.execute("SELECT * FROM songs WHERE user_id=? ORDER BY id DESC", (user_id,))
    rows = await cur.fetchall()
    return [{"id": r[0], "title": r[2], "style": r[3], "audio_file_id": r[4], "cover_file_id": r[5], "likes": r[6]} for r in rows]

async def get_global_charts(limit: int = 10):
    cur = await db_instance.execute("SELECT * FROM songs ORDER BY likes DESC LIMIT ?", (limit,))
    rows = await cur.fetchall()
    return [{"id": r[0], "title": r[2], "style": r[3], "likes": r[6]} for r in rows]