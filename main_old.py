import os
import json
import asyncio
import httpx
import base64
import logging
import random
import uuid
import time
from datetime import datetime
from typing import Optional, List, Dict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    WebAppInfo,
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    LabeledPrice, 
    PreCheckoutQuery, 
    BufferedInputFile, 
    ReplyKeyboardRemove, 
    FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from gigachat import GigaChat
from dotenv import load_dotenv
import aiosqlite

# ==========================================
# ⚙️ КОНФИГУРАЦИЯ И КЛЮЧИ (v3.2 - Мобильный UX)
# ==========================================
load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GIGACHAT_KEY = os.getenv("GIGACHAT_KEY")
PROXY_KEY = os.getenv("PROXY_KEY")
MUSIC_KEY = os.getenv("MUSIC_KEY")
EVOLINK_BASE_URL = os.getenv("EVOLINK_BASE_URL", "https://api.evolink.ai")
WEBAPP_URL = os.getenv("WEBAPP_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
REPLICATE_TOKEN = os.getenv("REPLICATE_API_TOKEN")

COST_SONG = 20
COST_COVER = 30
DB_PATH = "users.db"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit

# ==========================================
# 🛡 ПРОСТОЙ АНТИ-СПАМ (Rate Limit)
# ==========================================
USER_COOLDOWN = {}

def check_rate_limit(user_id: str, cooldown_seconds: int = 3) -> bool:
    now = time.time()
    last_action = USER_COOLDOWN.get(user_id, 0)
    if now - last_action < cooldown_seconds:
        return False
    USER_COOLDOWN[user_id] = now
    return True

# ==========================================
# 🧹 ОЧИСТКА ВРЕМЕННЫХ ФАЙЛОВ
# ==========================================
def cleanup_temp_files():
    """Удаляет забытые временные аудиофайлы при старте бота"""
    try:
        count = 0
        for f in os.listdir():
            if (f.startswith("voice_") or f.startswith("target_")) and (f.endswith(".ogg") or f.endswith(".mp3")):
                os.remove(f)
                count += 1
        if count > 0:
            logging.info(f"🧹 Очищено {count} старых временных файлов.")
    except Exception as e:
        logging.error(f"Ошибка при очистке файлов: {e}")

# ==========================================
# 🚀 ИНИЦИАЛИЗАЦИЯ БОТА И ИИ
# ==========================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

if GIGACHAT_KEY:
    giga = GigaChat(
        credentials=GIGACHAT_KEY, 
        verify_ssl_certs=False
    )
else:
    giga = None

# ==========================================
# 🗄 БАЗА ДАННЫХ (БЕЗОПАСНЫЕ ТРАНЗАКЦИИ)
# ==========================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                credits INTEGER DEFAULT 50,
                referrals INTEGER DEFAULT 0,
                earned INTEGER DEFAULT 0,
                referrer_id TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                title TEXT,
                style TEXT,
                audio_file_id TEXT,
                cover_file_id TEXT,
                likes INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS song_likes (
                user_id TEXT,
                song_id INTEGER,
                PRIMARY KEY (user_id, song_id)
            )
        """)
        
        await db.execute("CREATE INDEX IF NOT EXISTS idx_songs_user ON songs(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_songs_likes ON songs(likes DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id)")
        
        await db.commit()

async def get_user(user_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        sql = "SELECT credits, referrals, earned, referrer_id FROM users WHERE user_id = ?"
        async with db.execute(sql, (user_id,)) as cur:
            row = await cur.fetchone()
            
            if not row:
                return None
                
            return {
                "credits": row[0], 
                "referrals": row[1], 
                "earned": row[2], 
                "referrer_id": row[3]
            }

async def create_user(user_id: str, referrer_id: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        sql_insert = """
            INSERT INTO users (user_id, credits, referrals, earned, referrer_id) 
            VALUES (?, 50, 0, 0, ?)
        """
        await db.execute(sql_insert, (user_id, referrer_id))
        
        if referrer_id:
            sql_update = """
                UPDATE users 
                SET credits = credits + 10, 
                    referrals = referrals + 1, 
                    earned = earned + 10 
                WHERE user_id = ?
            """
            await db.execute(sql_update, (referrer_id,))
            
        await db.commit()

async def update_credits(user_id: str, delta: int):
    async with aiosqlite.connect(DB_PATH) as db:
        sql = "UPDATE users SET credits = credits + ? WHERE user_id = ?"
        await db.execute(sql, (delta, user_id))
        await db.commit()

async def try_spend_credits(user_id: str, amount: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        sql = """
            UPDATE users 
            SET credits = credits - ? 
            WHERE user_id = ? AND credits >= ?
        """
        cursor = await db.execute(sql, (amount, user_id, amount))
        await db.commit()
        
        if cursor.rowcount > 0:
            return True
        else:
            return False

async def add_song(user_id: str, title: str, style: str, audio_file_id: str, cover_file_id: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        sql = """
            INSERT INTO songs (user_id, title, style, audio_file_id, cover_file_id) 
            VALUES (?, ?, ?, ?, ?)
        """
        cursor = await db.execute(sql, (user_id, title, style, audio_file_id, cover_file_id))
        await db.commit()
        return cursor.lastrowid

async def get_user_songs(user_id: str) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        sql = """
            SELECT id, title, style, audio_file_id, cover_file_id, likes 
            FROM songs 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        """
        async with db.execute(sql, (user_id,)) as cur:
            rows = await cur.fetchall()
            
            results = []
            for r in rows:
                results.append({
                    "id": r[0], 
                    "title": r[1], 
                    "style": r[2], 
                    "audio_file_id": r[3], 
                    "cover_file_id": r[4], 
                    "likes": r[5]
                })
            return results

async def get_global_charts(limit: int = 10) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        sql = """
            SELECT id, user_id, title, style, audio_file_id, cover_file_id, likes 
            FROM songs 
            ORDER BY likes DESC 
            LIMIT ?
        """
        async with db.execute(sql, (limit,)) as cur:
            rows = await cur.fetchall()
            
            results = []
            for r in rows:
                results.append({
                    "id": r[0], 
                    "user_id": r[1], 
                    "title": r[2], 
                    "style": r[3], 
                    "audio_file_id": r[4], 
                    "cover_file_id": r[5], 
                    "likes": r[6]
                })
            return results

async def toggle_like(user_id: str, song_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        check_sql = "SELECT 1 FROM song_likes WHERE user_id = ? AND song_id = ?"
        exists = await (await db.execute(check_sql, (user_id, song_id))).fetchone()
        
        if exists:
            await db.execute("DELETE FROM song_likes WHERE user_id = ? AND song_id = ?", (user_id, song_id))
            await db.execute("UPDATE songs SET likes = CASE WHEN likes > 0 THEN likes - 1 ELSE 0 END WHERE id = ?", (song_id,))
            await db.commit()
            return False
        else:
            await db.execute("INSERT INTO song_likes (user_id, song_id) VALUES (?, ?)", (user_id, song_id))
            await db.execute("UPDATE songs SET likes = likes + 1 WHERE id = ?", (song_id,))
            await db.commit()
            return True

# ==========================================
# 🤖 AI ФУНКЦИИ (СБЕР / SUNO / DALL-E / REPLICATE)
# ==========================================
async def ai_generate_lyrics(idea: str, language: str) -> str:
    if not giga: 
        return "⚠️ ИИ недоступен."
        
    try: 
        if language != "🤖 На усмотрение ИИ":
            lang_prompt = f"Песня должна быть строго на этом языке: {language}."
        else:
            lang_prompt = "Выбери язык сам в зависимости от контекста идеи."
            
        prompt = (
            f"Напиши текст песни (2 куплета и припев). "
            f"Тема: {idea}. "
            f"{lang_prompt} "
            f"Выведи ТОЛЬКО текст песни, без лишних вступлений."
        )
        
        response = await giga.achat(prompt)
        return response.choices[0].message.content
        
    except Exception as e: 
        logging.error(f"Giga error: {e}")
        return "⚠️ Ошибка генерации текста."

async def ai_edit_lyrics(old_lyrics: str, edit_request: str) -> str:
    if not giga: 
        return "⚠️ ИИ недоступен."
        
    try: 
        prompt = (
            f"Вот текущий текст песни:\n{old_lyrics}\n\n"
            f"Внеси следующие изменения: {edit_request}\n"
            f"Выведи ТОЛЬКО обновленный текст песни."
        )
        
        response = await giga.achat(prompt)
        return response.choices[0].message.content
        
    except Exception as e: 
        logging.error(f"Giga edit error: {e}")
        return "⚠️ Ошибка редактирования текста."

async def ai_generate_title(lyrics: str) -> str:
    if not giga:
        return "Мой хит"
        
    try: 
        prompt = (
            f"Придумай крутое коммерческое название для этой песни (1-3 слова). "
            f"Выведи только ОДНО название:\n{lyrics}"
        )
        
        response = await giga.achat(prompt)
        raw_title = response.choices[0].message.content.strip().strip('"')
        
        safe_title = raw_title.split('\n')[0][:75].strip()
        
        if safe_title:
            return safe_title
        else:
            return "Мой хит"
            
    except Exception as e: 
        logging.error(f"Giga title error: {e}")
        return "Мой хит"

async def ai_generate_cover_prompt(title: str, style: str) -> str:
    if not giga:
        return f"Album cover for song '{title}'"
        
    try: 
        prompt = (
            f"Create a short DALL-E 3 prompt for a music album cover titled '{title}' "
            f"in the musical style of {style}. Highly artistic. Output ONLY the english prompt."
        )
        
        response = await giga.achat(prompt)
        return response.choices[0].message.content.strip()
        
    except Exception as e: 
        logging.error(f"Giga cover prompt error: {e}")
        return f"Digital art album cover for '{title}'"

async def ai_compile_style(genre: str, vocals: str, instruments: str) -> str:
    if not giga:
        return "pop, emotional"
        
    try: 
        prompt = (
            f"Translate and compile these into Suno AI tags (english, comma separated).\n"
            f"Genre: {genre}\n"
            f"Vocals: {vocals}\n"
            f"Instruments: {instruments}\n"
            f"Keep it under 100 characters. DO NOT use real artist names. "
            f"ONLY output the comma-separated tags."
        )
        
        response = await giga.achat(prompt)
        return response.choices[0].message.content.strip()[:115]
        
    except Exception as e: 
        logging.error(f"Compile style error: {e}")
        return "pop, emotional"

async def generate_suno_music(lyrics: str, style: str, is_instrumental: bool, title: str) -> Optional[str]:
    if not MUSIC_KEY:
        logging.error("MUSIC_KEY missing")
        return None
        
    headers = {
        "Authorization": f"Bearer {MUSIC_KEY}", 
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "suno-v5-beta", 
        "prompt": lyrics, 
        "style": style, 
        "title": title, 
        "make_instrumental": is_instrumental, 
        "custom_mode": True
    }
    
    logging.info(f"🎵 Suno request payload: {payload}")
    
    async with httpx.AsyncClient(timeout=360.0) as client:
        try:
            resp = await client.post(f"{EVOLINK_BASE_URL}/v1/audios/generations", json=payload, headers=headers)
            
            if resp.status_code != 200: 
                logging.error(f"Suno API Error: {resp.text}")
                return None
                
            task_id = resp.json().get("id")
            
            if not task_id:
                return None
                
            for _ in range(80):
                await asyncio.sleep(6)
                
                poll_resp = await client.get(f"{EVOLINK_BASE_URL}/v1/tasks/{task_id}", headers=headers)
                data = poll_resp.json()
                status = data.get("status")
                
                if status == "completed": 
                    audio_url = (
                        data.get("audio_url") or 
                        (data.get("result_data") and data["result_data"][0].get("audio_url")) or
                        (data.get("output") and data["output"][0].get("audio_url"))
                    )
                    return audio_url
                    
                if status in ("failed", "error"): 
                    logging.error(f"Suno generation failed: {data}")
                    return None
                    
            return None
            
        except Exception as e: 
            logging.error(f"Suno critical error: {e}")
            return None

async def generate_image(prompt: str) -> Optional[bytes]:
    if not PROXY_KEY:
        return None
        
    headers = {
        "Authorization": f"Bearer {PROXY_KEY}", 
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "dall-e-3", 
        "prompt": prompt, 
        "n": 1, 
        "size": "1024x1024", 
        "response_format": "b64_json"
    }
    
    async with httpx.AsyncClient(timeout=150.0) as client:
        try: 
            resp = await client.post("https://api.proxyapi.ru/openai/v1/images/generations", json=payload, headers=headers)
            
            if resp.status_code == 200:
                b64_string = resp.json()["data"][0]["b64_json"]
                return base64.b64decode(b64_string)
                
            return None
            
        except Exception as e: 
            logging.error(f"DALL-E image error: {e}")
            return None

async def make_ai_cover(voice_path: str, song_path: str) -> Optional[str]:
    if not REPLICATE_TOKEN: 
        return None
        
    try:
        with open(voice_path, "rb") as f: 
            voice_data = f.read()
            voice_b64 = base64.b64encode(voice_data).decode('utf-8')
            voice_uri = f"data:audio/ogg;base64,{voice_b64}"
            
        with open(song_path, "rb") as f: 
            song_data = f.read()
            song_b64 = base64.b64encode(song_data).decode('utf-8')
            song_uri = f"data:audio/mpeg;base64,{song_b64}"
            
        headers = {
            "Authorization": f"Bearer {REPLICATE_TOKEN}", 
            "Content-Type": "application/json"
        }
        
        payload = {
            "version": "0a9c7c558af4c8f20ea30a1eb9ce6ab1f8eb9e124f0c1d1a9b9a6b1897d19760", 
            "input": {
                "song_input": song_uri, 
                "rvc_model": "custom", 
                "custom_voice": voice_uri, 
                "pitch_change": "no-change", 
                "keep_background": True
            }
        }
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            req = await client.post("https://api.replicate.com/v1/predictions", json=payload, headers=headers)
            
            if req.status_code != 201: 
                return None
                
            task_url = req.json()["urls"]["get"]
            
            for _ in range(60):
                await asyncio.sleep(5)
                
                poll_req = await client.get(task_url, headers=headers)
                data = poll_req.json()
                
                if data["status"] == "succeeded": 
                    return data["output"]
                    
                elif data["status"] in ["failed", "canceled"]: 
                    return None
                    
            return None 
            
    except Exception as e: 
        logging.error(f"Replicate AI Cover error: {e}")
        return None

# ==========================================
# 🍪 КАПЧА: ЗАЩИТА ОТ БОТОВ
# ==========================================
CAPTCHA_ITEMS = {
    "клубника": "🍓",
    "яблоко": "🍎",
    "виноград": "🍇",
    "пицца": "🍕",
    "печенье": "🍪",
    "морковь": "🥕",
    "банан": "🍌",
    "бургер": "🍔",
    "арбуз": "🍉",
    "лимон": "🍋",
    "апельсин": "🍊",
    "вишня": "🍒"
}

def get_captcha_kb(correct_emoji: str) -> ReplyKeyboardMarkup:
    choices = random.sample(list(CAPTCHA_ITEMS.values()), 8)
    
    if correct_emoji not in choices: 
        choices[0] = correct_emoji
        random.shuffle(choices)
        
    keyboard = [
        [
            KeyboardButton(text=choices[0]), 
            KeyboardButton(text=choices[1]), 
            KeyboardButton(text=choices[2]), 
            KeyboardButton(text=choices[3])
        ],
        [
            KeyboardButton(text=choices[4]), 
            KeyboardButton(text=choices[5]), 
            KeyboardButton(text=choices[6]), 
            KeyboardButton(text=choices[7])
        ]
    ]
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard, 
        resize_keyboard=True, 
        one_time_keyboard=True
    )

# ==========================================
# 🗂 МАШИНА СОСТОЯНИЙ (FSM)
# ==========================================
class CaptchaFSM(StatesGroup): 
    waiting_for_emoji = State()

class CoverFSM(StatesGroup): 
    waiting_for_voice = State()
    waiting_for_song_choice = State()
    waiting_for_external_audio = State()

class CreateSongFSM(StatesGroup):
    waiting_for_language = State()
    waiting_for_lyrics_mode = State()
    waiting_for_keywords = State()
    waiting_for_lyrics_edit = State()
    waiting_for_lyrics_text = State()
    waiting_for_title = State()
    waiting_for_genre = State()
    waiting_for_vocals = State()
    waiting_for_instruments = State()
    waiting_for_style_confirm = State()

# ==========================================
# 🎛 КЛАВИАТУРЫ ИНТЕРФЕЙСА (ОПТИМИЗИРОВАНЫ ДЛЯ МОБИЛЬНЫХ)
# ==========================================
def get_main_kb(user_id: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="🎵 Создать песню"), 
            KeyboardButton(text="🎙 AI-Кавер")
        ], 
        [
            KeyboardButton(text="🎛 Мои треки"), 
            KeyboardButton(text="🏆 Чарты")
        ], 
        [
            KeyboardButton(text="👤 Профиль"), 
            KeyboardButton(text="💎 Пополнить баланс")
        ]
    ]
    
    if WEBAPP_URL: 
        keyboard.insert(2, [
            KeyboardButton(text="🚀 Открыть Студию", web_app=WebAppInfo(url=WEBAPP_URL))
        ])
        
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_payment_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    builder.button(text="💿 Пакет 'Старт' (100💎) — 100⭐️", callback_data="buy_100")
    builder.button(text="💎 Пакет 'Хитмейкер' (500💎) — 500⭐️", callback_data="buy_500")
    builder.button(text="👑 Пакет 'Продюсер' (1000💎) — 1000⭐️", callback_data="buy_1000")
    
    builder.adjust(1)
    return builder.as_markup()

# ИСПРАВЛЕНИЕ: Кнопки навигации перенесены наверх
def get_language_kb() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="🤖 На усмотрение ИИ"), 
            KeyboardButton(text="❌ Отмена")
        ],
        [
            KeyboardButton(text="🇷🇺 Русский"), 
            KeyboardButton(text="🇬🇧 Английский")
        ],
        [
            KeyboardButton(text="🇪🇸 Испанский"), 
            KeyboardButton(text="🇯🇵 Японский")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ИСПРАВЛЕНИЕ: Кнопки навигации перенесены наверх
def get_lyrics_mode_kb() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="🤖 Сгенерировать ИИ"), 
            KeyboardButton(text="❌ Отмена")
        ], 
        [
            KeyboardButton(text="✍️ Напишу сам")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ИСПРАВЛЕНИЕ: Кнопки навигации перенесены наверх
def get_lyrics_confirm_kb() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="✅ Текст супер, дальше!"),
            KeyboardButton(text="❌ Отмена")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ИСПРАВЛЕНИЕ: Кнопки навигации перенесены наверх, чтобы не перекрывались Android-меню
def get_genre_kb() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="✅ Далее (к вокалу)"), 
            KeyboardButton(text="❌ Отмена")
        ],
        [
            KeyboardButton(text="🤖 Доверить ИИ")
        ], 
        [
            KeyboardButton(text="🎸 Рок"), 
            KeyboardButton(text="🎧 Поп"), 
            KeyboardButton(text="🎤 Хип-хоп")
        ], 
        [
            KeyboardButton(text="🎹 Синтвейв"), 
            KeyboardButton(text="🎻 Классика"), 
            KeyboardButton(text="🌍 Этника")
        ], 
        [
            KeyboardButton(text="🎷 Джаз"), 
            KeyboardButton(text="🪩 R&B"), 
            KeyboardButton(text="🎸 Метал")
        ], 
        [
            KeyboardButton(text="🎶 Фонк (Phonk)"), 
            KeyboardButton(text="🎛 EDM")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ИСПРАВЛЕНИЕ: Кнопки навигации перенесены наверх
def get_vocals_kb() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="✅ Далее (к инструментам)"), 
            KeyboardButton(text="❌ Отмена")
        ],
        [
            KeyboardButton(text="🤖 На усмотрение ИИ"), 
            KeyboardButton(text="🎹 Инструментал")
        ],
        [
            KeyboardButton(text="👩 Женский"), 
            KeyboardButton(text="👨 Мужской"), 
            KeyboardButton(text="👩‍❤️‍👨 Дуэт (М+Ж)")
        ], 
        [
            KeyboardButton(text="🗣 Хор"), 
            KeyboardButton(text="👶 Детский хор"), 
            KeyboardButton(text="🎤 Бэк-вокал")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ИСПРАВЛЕНИЕ: Кнопки навигации перенесены наверх
def get_instruments_kb() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="✅ Сгенерировать промпт!"), 
            KeyboardButton(text="❌ Отмена")
        ],
        [
            KeyboardButton(text="🤖 На усмотрение ИИ")
        ], 
        [
            KeyboardButton(text="🎸 Акустика"), 
            KeyboardButton(text="⚡ Электрогитара")
        ], 
        [
            KeyboardButton(text="🎹 Пианино"), 
            KeyboardButton(text="🥁 Ударные и бас")
        ], 
        [
            KeyboardButton(text="🎻 Оркестр"), 
            KeyboardButton(text="🪗 Баян / Народные")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ИСПРАВЛЕНИЕ: Кнопки навигации перенесены наверх
def get_confirm_kb() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="✅ Всё верно, создаём!"),
            KeyboardButton(text="❌ Отмена")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ==========================================
# 🛑 ГЛОБАЛЬНАЯ ОТМЕНА И ПОМОЩЬ
# ==========================================
@dp.message(F.text.in_(["❌ Отмена", "/cancel", "Отмена", "отмена"]))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    
    user_id = str(message.from_user.id)
    main_kb = get_main_kb(user_id)
    
    await message.answer(
        "❌ Действие отменено. Вы вернулись в главное меню.", 
        reply_markup=main_kb
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if not check_rate_limit(str(message.from_user.id)): return
    text = (
        "🛠 **Справка по HitMaker Studio**\n\n"
        "🎵 **Создать песню** — Генерация с нуля (20💎)\n"
        "🎙 **AI-Кавер** — Твой голос в любой песне (30💎)\n"
        "🎛 **Мои треки** — Управление медиатекой\n"
        "🏆 **Чарты** — Топ популярных песен\n"
        "💎 **Пополнить баланс** — Покупка алмазов (Stars)\n"
        "❌ **/cancel** — Отмена текущего действия"
    )
    await message.answer(text, parse_mode="Markdown")

# ==========================================
# 🚀 СТАРТ И КАПЧА
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    user_id = str(message.from_user.id)
    if not check_rate_limit(user_id): return
    
    referrer = None
    args = message.text.split()
    
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer = args[1][4:]
        
    user_data = await get_user(user_id)
    
    if not user_data:
        target_name = random.choice(list(CAPTCHA_ITEMS.keys()))
        
        await state.update_data(
            captcha_target=CAPTCHA_ITEMS[target_name], 
            referrer=referrer
        )
        await state.set_state(CaptchaFSM.waiting_for_emoji)
        
        text = f"Привет 👋\nДля начала нужно убедиться, что ты не бот 🤖\nНажми на кнопку где изображен(а) **{target_name}**?"
        captcha_kb = get_captcha_kb(CAPTCHA_ITEMS[target_name])
        
        await message.answer(text, reply_markup=captcha_kb, parse_mode="Markdown")
    else:
        main_kb = get_main_kb(user_id)
        await message.answer("С возвращением в студию!", reply_markup=main_kb, parse_mode="Markdown")

@dp.message(CaptchaFSM.waiting_for_emoji)
async def process_captcha(message: types.Message, state: FSMContext):
    data = await state.get_data()
    captcha_target = data.get("captcha_target")
    
    if message.text == captcha_target:
        await state.clear()
        user_id = str(message.from_user.id)
        referrer = data.get("referrer")
        
        await create_user(user_id, referrer)
        
        welcome_text = "🎬 Добро пожаловать в **HitMaker Studio**!\nДарим тебе 50 алмазов на пробу — создавай хиты! 🎁"
        main_kb = get_main_kb(user_id)
        
        try:
            if os.path.exists("welcome.mp4"): 
                video_file = FSInputFile("welcome.mp4")
                await message.answer_video(
                    video_file, 
                    caption=welcome_text, 
                    reply_markup=main_kb, 
                    parse_mode="Markdown"
                )
            elif os.path.exists("welcome.jpg"): 
                photo_file = FSInputFile("welcome.jpg")
                await message.answer_photo(
                    photo_file, 
                    caption=welcome_text, 
                    reply_markup=main_kb, 
                    parse_mode="Markdown"
                )
            else: 
                await message.answer(
                    welcome_text, 
                    reply_markup=main_kb, 
                    parse_mode="Markdown"
                )
        except Exception as e: 
            logging.error(f"Media sending error: {e}")
            await message.answer(
                welcome_text, 
                reply_markup=main_kb, 
                parse_mode="Markdown"
            )
    else:
        target_name = random.choice(list(CAPTCHA_ITEMS.keys()))
        await state.update_data(captcha_target=CAPTCHA_ITEMS[target_name])
        
        text = f"❌ Ошибка! Нажми на кнопку где изображен(а) **{target_name}**?"
        captcha_kb = get_captcha_kb(CAPTCHA_ITEMS[target_name])
        
        await message.answer(text, reply_markup=captcha_kb, parse_mode="Markdown")

# ==========================================
# 👑 АДМИН ПАНЕЛЬ
# ==========================================
@dp.message(Command("give"))
async def admin_give_credits(message: types.Message):
    if message.from_user.id != ADMIN_ID: 
        return
        
    args = message.text.split()
    
    if len(args) != 3: 
        await message.answer("Использование: /give <user_id> <amount>")
        return
        
    target_user = args[1]
    
    try:
        amount = int(args[2])
    except ValueError:
        await message.answer("Сумма должна быть числом.")
        return
        
    await update_credits(target_user, amount)
    await message.answer(f"✅ Успешно выдано {amount} алмазов пользователю {target_user}.")

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: 
        return

    async with aiosqlite.connect(DB_PATH) as db:
        users_count_cur = await db.execute("SELECT COUNT(*) FROM users")
        users_count_row = await users_count_cur.fetchone()
        users_count = users_count_row[0] if users_count_row else 0
        
        songs_count_cur = await db.execute("SELECT COUNT(*) FROM songs")
        songs_count_row = await songs_count_cur.fetchone()
        songs_count = songs_count_row[0] if songs_count_row else 0

    text = (
        "👑 **ПАНЕЛЬ УПРАВЛЕНИЯ СТУДИЕЙ**\n"
        "〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
        f"👥 Всего пользователей: **{users_count}**\n"
        f"🎵 Сгенерировано треков: **{songs_count}**\n\n"
        "🔗 **ДОСТУПЫ И БАЛАНСЫ СЕРВИСОВ:**\n"
        "*(Никогда не храни пароли в коде!)*\n\n"
        "🎶 **Suno (Evolink)**\n"
        "Логин: `Укажи_свой_email_здесь`\n"
        "➡️ [Проверить баланс Evolink](https://evolink.ai/dashboard)\n\n"
        "🎨 **DALL-E 3 (ProxyAPI)**\n"
        "Логин: `Укажи_свой_email_здесь`\n"
        "➡️ [Проверить баланс ProxyAPI](https://proxyapi.ru/lk/balance)\n\n"
        "🎙 **Replicate (AI-Каверы)**\n"
        "Логин: `Твой_GitHub_или_Email`\n"
        "➡️ [Проверить биллинг Replicate](https://replicate.com/account/billing)\n\n"
        "🧠 **GigaChat (Сбер)**\n"
        "Логин: `Сбер ID`\n"
        "➡️ [Кабинет разработчика](https://developers.sber.ru/studio/workspace)\n"
    )
    
    await message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)

# ==========================================
# 💰 ОПЛАТА
# ==========================================
@dp.message(F.text == "💎 Пополнить баланс")
async def buy_credits_menu(message: types.Message):
    user_id = str(message.from_user.id)
    if not check_rate_limit(user_id): return
    
    user_data = await get_user(user_id)
    credits_amt = user_data['credits'] if user_data else 0
    
    text = (
        f"💎 **Твой баланс:** {credits_amt} алмазов.\n\n"
        f"✨ Пополни баланс, чтобы создавать больше хитов! Выбери пакет ниже ⬇️"
    )
    
    await message.answer(text, reply_markup=get_payment_kb(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("buy_"))
async def process_payment(callback: types.CallbackQuery):
    if not check_rate_limit(str(callback.from_user.id)): 
        await callback.answer("Слишком часто нажимаете!", show_alert=True)
        return
        
    data_parts = callback.data.split("_")
    amount = int(data_parts[1])
    
    chat_id = callback.message.chat.id
    
    await bot.send_invoice(
        chat_id=chat_id, 
        title=f"Пакет {amount} алмазов", 
        description=f"Пополнение баланса на {amount} кредитов", 
        payload=f"credits_{amount}", 
        provider_token="", 
        currency="XTR", 
        prices=[LabeledPrice(label=f"{amount} алмазов", amount=amount)]
    )
    
    await callback.answer()

@dp.pre_checkout_query(lambda query: True)
async def pre_checkout(query: PreCheckoutQuery): 
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    payload_parts = payload.split("_")
    amount = int(payload_parts[1])
    
    user_id = str(message.from_user.id)
    await update_credits(user_id, amount)
    
    text = f"✅ Успешно! {amount} алмазов зачислены на ваш баланс."
    await message.answer(text)

# ==========================================
# 🎵 СОЗДАНИЕ ПЕСНИ (С МУЛЬТИ-ВЫБОРОМ)
# ==========================================
@dp.message(F.text == "🎵 Создать песню")
async def create_song_start(message: types.Message, state: FSMContext):
    if not check_rate_limit(str(message.from_user.id)): return
    
    await state.clear()
    await state.update_data(genre="", vocals="", instruments="")
    
    text = "🌍 **Выбери язык для песни:**"
    await message.answer(text, reply_markup=get_language_kb(), parse_mode="Markdown")
    
    await state.set_state(CreateSongFSM.waiting_for_language)

@dp.message(CreateSongFSM.waiting_for_language)
async def language_handler(message: types.Message, state: FSMContext):
    await state.update_data(language=message.text)
    
    text = "Как ты хочешь получить текст песни?"
    await message.answer(text, reply_markup=get_lyrics_mode_kb())
    
    await state.set_state(CreateSongFSM.waiting_for_lyrics_mode)

@dp.message(CreateSongFSM.waiting_for_lyrics_mode, F.text == "🤖 Сгенерировать ИИ")
async def lyrics_ai(message: types.Message, state: FSMContext):
    cancel_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")]
        ], 
        resize_keyboard=True
    )
    
    text = "Введите тему или идею для песни:"
    await message.answer(text, reply_markup=cancel_kb)
    
    await state.set_state(CreateSongFSM.waiting_for_keywords)

@dp.message(CreateSongFSM.waiting_for_keywords)
async def lyrics_ai_generate(message: types.Message, state: FSMContext):
    await message.answer("🔄 Генерирую текст...")
    
    data = await state.get_data()
    lang = data.get("language", "🤖 На усмотрение ИИ")
    
    idea = message.text
    lyrics = await ai_generate_lyrics(idea, lang)
    
    await state.update_data(lyrics=lyrics)
    
    text = (
        f"📝 Вот что получилось:\n\n{lyrics}\n\n"
        f"Если хочешь изменить текст, напиши свои пожелания. Если всё супер — жми кнопку."
    )
    
    await message.answer(text, reply_markup=get_lyrics_confirm_kb())
    await state.set_state(CreateSongFSM.waiting_for_lyrics_edit)

@dp.message(CreateSongFSM.waiting_for_lyrics_edit)
async def process_lyrics_edit(message: types.Message, state: FSMContext):
    if message.text == "✅ Текст супер, дальше!":
        title_kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="/auto_title")], 
                [KeyboardButton(text="❌ Отмена")]
            ], 
            resize_keyboard=True
        )
        
        text = "Отлично! Напиши название трека или нажми /auto_title"
        await message.answer(text, reply_markup=title_kb)
        
        await state.set_state(CreateSongFSM.waiting_for_title)
    else:
        data = await state.get_data()
        old_lyrics = data.get("lyrics", "")
        
        await message.answer("🔄 Переписываю текст с учётом твоих правок...")
        
        new_lyrics = await ai_edit_lyrics(old_lyrics, message.text)
        await state.update_data(lyrics=new_lyrics)
        
        text = (
            f"📝 Новый вариант:\n\n{new_lyrics}\n\n"
            f"Напиши новые правки или жми кнопку, если нравится."
        )
        
        await message.answer(text, reply_markup=get_lyrics_confirm_kb())

@dp.message(CreateSongFSM.waiting_for_lyrics_mode, F.text == "✍️ Напишу сам")
async def lyrics_manual(message: types.Message, state: FSMContext):
    done_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/done")], 
            [KeyboardButton(text="❌ Отмена")]
        ], 
        resize_keyboard=True
    )
    
    text = "Отправь текст песни. Когда закончишь, напиши /done"
    await message.answer(text, reply_markup=done_kb)
    
    await state.set_state(CreateSongFSM.waiting_for_lyrics_text)

@dp.message(CreateSongFSM.waiting_for_lyrics_text)
async def lyrics_collect(message: types.Message, state: FSMContext):
    if message.text == "/done":
        data = await state.get_data()
        lyrics = data.get("temp_lyrics", "").strip()
        
        if not lyrics: 
            await message.answer("❌ Ты не отправил текст!")
            return
            
        await state.update_data(lyrics=lyrics)
        
        title_kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="/auto_title")], 
                [KeyboardButton(text="❌ Отмена")]
            ], 
            resize_keyboard=True
        )
        
        text = "Напишите название трека или нажмите /auto_title"
        await message.answer(text, reply_markup=title_kb)
        
        await state.set_state(CreateSongFSM.waiting_for_title)
    else:
        data = await state.get_data()
        current_temp = data.get("temp_lyrics", "")
        
        new_temp = current_temp + message.text + "\n"
        await state.update_data(temp_lyrics=new_temp)
        
        text = "Текст добавлен. Продолжайте отправлять или нажмите /done"
        await message.answer(text)

@dp.message(CreateSongFSM.waiting_for_title)
async def title_handler(message: types.Message, state: FSMContext):
    if message.text == "/auto_title":
        data = await state.get_data()
        lyrics = data.get("lyrics", "")
        title = await ai_generate_title(lyrics)
    else:
        title = message.text
        
    await state.update_data(title=title)
    
    text = (
        f"🎵 Название: {title}\n\n"
        f"🎸 **Выберите жанр:**\n*(Ты можешь нажимать на кнопки несколько раз, чтобы смешать жанры!)*"
    )
    
    await message.answer(text, reply_markup=get_genre_kb(), parse_mode="Markdown")
    await state.set_state(CreateSongFSM.waiting_for_genre)

@dp.message(CreateSongFSM.waiting_for_genre)
async def genre_handler(message: types.Message, state: FSMContext):
    if message.text == "✅ Далее (к вокалу)":
        text = "🎤 **Выберите вокал:**\n*(Также можно выбрать несколько вариантов)*"
        await message.answer(text, reply_markup=get_vocals_kb(), parse_mode="Markdown")
        await state.set_state(CreateSongFSM.waiting_for_vocals)
        return
        
    data = await state.get_data()
    current_genre = data.get("genre", "")
    addition = message.text.replace("🤖 Доверить ИИ", "На усмотрение ИИ")
    
    if current_genre:
        new_genre = f"{current_genre}, {addition}"
    else:
        new_genre = addition
        
    await state.update_data(genre=new_genre)
    
    text = f"✅ Добавлено. Итоговые жанры: **{new_genre}**\n*Выбери еще жанр или нажми «Далее»*"
    await message.answer(text, reply_markup=get_genre_kb(), parse_mode="Markdown")

@dp.message(CreateSongFSM.waiting_for_vocals)
async def vocals_handler(message: types.Message, state: FSMContext):
    if message.text == "✅ Далее (к инструментам)":
        text = "🥁 **Выберите инструменты:**\n*(Собери свой оркестр!)*"
        await message.answer(text, reply_markup=get_instruments_kb(), parse_mode="Markdown")
        await state.set_state(CreateSongFSM.waiting_for_instruments)
        return
        
    data = await state.get_data()
    current_vocals = data.get("vocals", "")
    addition = message.text.replace("🤖 На усмотрение ИИ", "На усмотрение ИИ")
    
    if current_vocals:
        new_vocals = f"{current_vocals}, {addition}"
    else:
        new_vocals = addition
        
    await state.update_data(vocals=new_vocals)
    
    text = f"✅ Добавлено. Итоговый вокал: **{new_vocals}**\n*Выбери еще или нажми «Далее»*"
    await message.answer(text, reply_markup=get_vocals_kb(), parse_mode="Markdown")

@dp.message(CreateSongFSM.waiting_for_instruments)
async def instruments_handler(message: types.Message, state: FSMContext):
    if message.text == "✅ Сгенерировать промпт!":
        data = await state.get_data()
        
        await message.answer("⏳ Компилирую промпт для нейросети...", reply_markup=ReplyKeyboardRemove())
        
        genre = data.get('genre', 'pop')
        vocals = data.get('vocals', 'mixed')
        instruments = data.get('instruments', 'any')
        
        style = await ai_compile_style(genre, vocals, instruments)
        await state.update_data(style=style)
        
        text = (
            f"✨ **Итоговый промпт стиля для нейросети:**\n`{style}`\n\n"
            f"Ты можешь прямо сейчас **написать свой вариант текста** в чат, чтобы исправить этот промпт.\n\n"
            f"Если промпт идеален — жми ✅"
        )
        
        await message.answer(text, reply_markup=get_confirm_kb(), parse_mode="Markdown")
        await state.set_state(CreateSongFSM.waiting_for_style_confirm)
        return

    data = await state.get_data()
    current_inst = data.get("instruments", "")
    addition = message.text.replace("🤖 На усмотрение ИИ", "На усмотрение ИИ")
    
    if current_inst:
        new_inst = f"{current_inst}, {addition}"
    else:
        new_inst = addition
        
    await state.update_data(instruments=new_inst)
    
    text = f"✅ Добавлено. Инструменты: **{new_inst}**\n*Выбери еще или нажми «Сгенерировать промпт»*"
    await message.answer(text, reply_markup=get_instruments_kb(), parse_mode="Markdown")

@dp.message(CreateSongFSM.waiting_for_style_confirm)
async def finalize_song(message: types.Message, state: FSMContext):
    if message.text != "✅ Всё верно, создаём!":
        await state.update_data(style=message.text)
        
        text = f"Стиль обновлён на:\n`{message.text}`\nНажмите ✅ для генерации."
        await message.answer(text, reply_markup=get_confirm_kb(), parse_mode="Markdown")
        return
        
    user_id = str(message.from_user.id)
    data = await state.get_data()
    
    if not await try_spend_credits(user_id, COST_SONG):
        await message.answer(f"🚫 Недостаточно алмазов (нужно {COST_SONG}).", reply_markup=get_payment_kb())
        await state.clear()
        return

    text_charge = f"💎 Списано {COST_SONG} алмазов.\n🎨 Рисуем сочную обложку для трека..."
    status_msg = await message.answer(text_charge, reply_markup=ReplyKeyboardRemove())
    
    title = data.get('title', 'Song')
    style = data.get('style', 'pop')
    lyrics = data.get('lyrics', '')
    
    prompt = await ai_generate_cover_prompt(title, style)
    img_bytes = await generate_image(prompt)
    cover_file_id = None
    
    if img_bytes:
        img_file = BufferedInputFile(img_bytes, filename="cover.png")
        caption_text = f"🖼 Обложка для «{title}»!\n\n🎧 Теперь сводим музыку. Это займёт 2-5 минут..."
        
        cover_msg = await message.answer_photo(img_file, caption=caption_text)
        cover_file_id = cover_msg.photo[-1].file_id
        
        await status_msg.delete()
        status_msg = await message.answer("🔄 Магия звука в процессе...")
    else: 
        await status_msg.edit_text("🎧 Обложка не удалась, но мы уже сводим музыку... (до 5 минут)")

    vocals_data = data.get('vocals', '')
    is_instrumental = "Инструментал" in vocals_data
    
    audio_url = await generate_suno_music(lyrics, style, is_instrumental, title)
    
    if not audio_url: 
        await status_msg.edit_text("❌ Ошибка генерации музыки. Алмазы возвращены.")
        await update_credits(user_id, COST_SONG)
        await state.clear()
        return

    async with httpx.AsyncClient() as client: 
        audio_response = await client.get(audio_url)
        audio_data = audio_response.content
        
    audio_file = BufferedInputFile(audio_data, filename=f"{title}.mp3")
    audio_message = await message.answer_audio(
        audio_file, 
        title=title, 
        performer="HitMaker AI"
    )
    
    await add_song(user_id, title, style, audio_message.audio.file_id, cover_file_id)
    await status_msg.delete()
    
    main_kb = get_main_kb(user_id)
    success_text = f"✅ Песня **{title}** готова и добавлена в Мои треки."
    await message.answer(success_text, reply_markup=main_kb, parse_mode="Markdown")
    
    await state.clear()

# ==========================================
# 🎙 AI-КАВЕР (С ОЧИСТКОЙ И ЛИМИТАМИ ФАЙЛОВ)
# ==========================================
@dp.message(F.text == "🎙 AI-Кавер")
async def cover_start(message: types.Message, state: FSMContext):
    if not check_rate_limit(str(message.from_user.id)): return
    
    cancel_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")]
        ], 
        resize_keyboard=True
    )
    
    text = (
        "🎤 Отправь **голосовое сообщение** (до 60 секунд).\n"
        "Я скопирую твой тембр и наложу его на любую песню."
    )
    await message.answer(text, reply_markup=cancel_kb, parse_mode="Markdown")
    
    await state.set_state(CoverFSM.waiting_for_voice)

@dp.message(CoverFSM.waiting_for_voice, F.voice)
async def cover_voice_received(message: types.Message, bot: Bot, state: FSMContext):
    if message.voice.duration > 60: 
        await message.answer("⚠️ Голосовое сообщение не длиннее 60 секунд.")
        return
        
    unique_id = uuid.uuid4().hex
    voice_path = f"voice_{unique_id}.ogg"
    
    voice_file = await bot.get_file(message.voice.file_id)
    await bot.download_file(voice_file.file_path, voice_path)
    
    await state.update_data(voice_path=voice_path)
    
    source_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎤 Из чартов")], 
            [KeyboardButton(text="📎 Загрузить свой аудиофайл")], 
            [KeyboardButton(text="❌ Отмена")]
        ], 
        resize_keyboard=True
    )
    
    await message.answer("Выберите источник песни для кавера:", reply_markup=source_kb)
    await state.set_state(CoverFSM.waiting_for_song_choice)

@dp.message(CoverFSM.waiting_for_song_choice, F.text == "🎤 Из чартов")
async def cover_from_charts(message: types.Message):
    top_songs = await get_global_charts(10)
    
    if not top_songs: 
        await message.answer("Чарты пусты. Попробуйте загрузить свой файл.")
        return
        
    builder = InlineKeyboardBuilder()
    
    for song in top_songs: 
        title = song['title']
        likes = song['likes']
        song_id = song['id']
        
        button_text = f"{title} (❤️{likes})"
        callback = f"cover_song_{song_id}"
        
        builder.button(text=button_text, callback_data=callback)
        
    builder.adjust(1)
    await message.answer("Выберите песню:", reply_markup=builder.as_markup())

@dp.message(CoverFSM.waiting_for_song_choice, F.text == "📎 Загрузить свой аудиофайл")
async def cover_upload_audio(message: types.Message, state: FSMContext):
    cancel_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")]
        ], 
        resize_keyboard=True
    )
    
    text = "Отправьте аудиофайл (MP3, WAV, OGG) для создания кавера (до 10 МБ):"
    await message.answer(text, reply_markup=cancel_kb)
    
    await state.set_state(CoverFSM.waiting_for_external_audio)

@dp.message(CoverFSM.waiting_for_external_audio, F.audio | F.document)
async def cover_external_audio(message: types.Message, bot: Bot, state: FSMContext):
    user_id = str(message.from_user.id)
    data = await state.get_data()
    
    file_size = message.audio.file_size if message.audio else message.document.file_size
    if file_size and file_size > MAX_FILE_SIZE:
        await message.answer("❌ Ошибка: Файл слишком большой. Максимальный размер 10 МБ.")
        return
    
    voice_path = data.get("voice_path", "")
    unique_id = uuid.uuid4().hex
    target_path = f"target_{unique_id}.mp3"
    
    if not await try_spend_credits(user_id, COST_COVER):
        await message.answer(f"🚫 Недостаточно алмазов!", reply_markup=get_payment_kb())
        await state.clear()
        return
        
    try:
        if message.audio:
            file_id = message.audio.file_id
        else:
            file_id = message.document.file_id
            
        target_file = await bot.get_file(file_id)
        
        await bot.download_file(target_file.file_path, target_path)
        
        text_charge = f"🔄 **Списано {COST_COVER} алмазов. Сведение 2-3 минуты...**"
        await message.answer(text_charge, parse_mode="Markdown")
        
        cover_url = await make_ai_cover(voice_path, target_path)
        
        if cover_url:
            async with httpx.AsyncClient() as client: 
                cover_response = await client.get(cover_url)
                audio_data = cover_response.content
                
            cover_file = BufferedInputFile(audio_data, filename="Cover.mp3")
            
            main_kb = get_main_kb(user_id)
            await message.answer_audio(
                cover_file, 
                title="AI Cover", 
                performer="HitMaker AI", 
                caption="🎙 **Ваш AI-Кавер готов!**", 
                parse_mode="Markdown", 
                reply_markup=main_kb
            )
        else: 
            main_kb = get_main_kb(user_id)
            await message.answer("❌ Ошибка при создании кавера. Алмазы возвращены.", reply_markup=main_kb)
            await update_credits(user_id, COST_COVER)
            
    finally:
        for path in [voice_path, target_path]:
            if path and os.path.exists(path):
                try: 
                    os.remove(path)
                except OSError as e: 
                    logging.error(f"Error removing temp file {path}: {e}")
                    
        await state.clear()

@dp.callback_query(F.data.startswith("cover_song_"))
async def cover_callback_song(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    callback_parts = callback.data.split("_")
    song_id = int(callback_parts[2])
    user_id = str(callback.from_user.id)
    
    data = await state.get_data()
    voice_path = data.get("voice_path", "")
    
    unique_id = uuid.uuid4().hex
    target_path = f"target_{unique_id}.mp3"
    
    if not await try_spend_credits(user_id, COST_COVER): 
        await callback.message.answer("🚫 Недостаточно алмазов!")
        await state.clear()
        await callback.answer()
        return
        
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            sql = "SELECT audio_file_id, title FROM songs WHERE id = ?"
            cur = await db.execute(sql, (song_id,))
            row = await cur.fetchone()
            
            if not row: 
                await update_credits(user_id, COST_COVER)
                await callback.answer("Песня не найдена")
                return
                
        audio_file_id = row[0]
        title = row[1]
        
        target_file = await bot.get_file(audio_file_id)
        await bot.download_file(target_file.file_path, target_path)
        
        text_charge = f"🔄 **Списано {COST_COVER} алмазов. Сведение...**"
        await callback.message.edit_text(text_charge, parse_mode="Markdown")
        
        cover_url = await make_ai_cover(voice_path, target_path)
        
        main_kb = get_main_kb(user_id)
        
        if cover_url:
            async with httpx.AsyncClient() as client: 
                cover_response = await client.get(cover_url)
                audio_data = cover_response.content
                
            cover_file = BufferedInputFile(audio_data, filename=f"Cover_{title}.mp3")
            
            await callback.message.answer_audio(
                cover_file, 
                title=f"{title} (AI Cover)", 
                performer="HitMaker AI", 
                caption="🎙 **Твой AI-Кавер готов!**", 
                parse_mode="Markdown", 
                reply_markup=main_kb
            )
        else: 
            await callback.message.answer("❌ Ошибка. Алмазы возвращены.", reply_markup=main_kb)
            await update_credits(user_id, COST_COVER)
            
    finally:
        for path in [voice_path, target_path]:
            if path and os.path.exists(path):
                try: 
                    os.remove(path)
                except OSError as e: 
                    logging.error(f"Error removing temp file {path}: {e}")
                    
        await state.clear()
        await callback.answer()

# ==========================================
# 🎛 ПЛЕЕР И УПРАВЛЕНИЕ МЕДИАТЕКОЙ
# ==========================================
@dp.message(F.text == "🎛 Мои треки")
async def tracks_menu(message: types.Message):
    if not check_rate_limit(str(message.from_user.id)): return
    
    user_id = str(message.from_user.id)
    songs = await get_user_songs(user_id)
    
    if not songs: 
        await message.answer("У тебя пока нет треков. Создай свой первый хит!")
        return
        
    builder = InlineKeyboardBuilder()
    
    for song in songs: 
        title = song['title']
        song_id = song['id']
        builder.button(text=f"🎵 {title}", callback_data=f"song_menu_{song_id}")
        
    builder.adjust(1)
    
    text = "🎛 **Твоя медиатека**\nВыбери трек для прослушивания:"
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("song_menu_"))
async def song_action_menu(callback: types.CallbackQuery):
    callback_parts = callback.data.split("_")
    song_id = int(callback_parts[2])
    
    builder = InlineKeyboardBuilder()
    
    builder.button(text="▶️ Слушать", callback_data=f"listen_{song_id}")
    builder.button(text="🗑 Удалить", callback_data=f"del_{song_id}")
    
    await callback.message.edit_text("Выбери действие для трека:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("listen_"))
async def listen_song(callback: types.CallbackQuery, bot: Bot):
    callback_parts = callback.data.split("_")
    song_id = int(callback_parts[1])
    
    async with aiosqlite.connect(DB_PATH) as db:
        sql = "SELECT title, style, audio_file_id, cover_file_id, likes FROM songs WHERE id = ?"
        cur = await db.execute(sql, (song_id,))
        row = await cur.fetchone()
        
    if not row: 
        await callback.answer("Трек не найден!")
        return
        
    title = row[0]
    style = row[1]
    audio_id = row[2]
    cover_id = row[3]
    likes = row[4]
    
    caption = f"🎵 **{title}**\nСтиль: {style}\n❤️ {likes} лайков"
    
    chat_id = callback.message.chat.id
    
    if cover_id: 
        await bot.send_photo(chat_id, cover_id, caption=caption, parse_mode="Markdown")
    else: 
        await bot.send_message(chat_id, caption, parse_mode="Markdown")
        
    await bot.send_audio(chat_id, audio_id, title=title)
    await callback.answer()

@dp.callback_query(F.data.startswith("del_"))
async def delete_song(callback: types.CallbackQuery):
    callback_parts = callback.data.split("_")
    song_id = int(callback_parts[1])
    
    async with aiosqlite.connect(DB_PATH) as db: 
        sql = "DELETE FROM songs WHERE id = ?"
        await db.execute(sql, (song_id,))
        await db.commit()
        
    await callback.message.edit_text("✅ Трек удалён из библиотеки.")

# ==========================================
# 📊 ЧАРТЫ И ПРОФИЛЬ
# ==========================================
@dp.message(F.text == "🏆 Чарты")
async def charts(message: types.Message):
    if not check_rate_limit(str(message.from_user.id)): return
    
    songs = await get_global_charts(limit=10)
    
    if not songs: 
        await message.answer("Чарты пока пусты. Будь первым!")
        return
        
    text = "🏆 **Топ треков**\n\n"
    
    for index, song in enumerate(songs, start=1):
        title = song['title']
        likes = song['likes']
        text += f"{index}. {title} — ❤️ {likes}\n"
        
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "👤 Профиль")
async def profile(message: types.Message):
    if not check_rate_limit(str(message.from_user.id)): return
    
    user_id = str(message.from_user.id)
    user = await get_user(user_id)
    
    if not user: 
        return
        
    songs = await get_user_songs(user_id)
    
    credits_amt = user['credits']
    referrals = user['referrals']
    earned = user['earned']
    songs_count = len(songs)
    
    text = (
        f"👤 **Твой профиль**\n"
        f"💎 Баланс: {credits_amt} алмазов\n"
        f"🎵 Создано песен: {songs_count}\n"
        f"👥 Приглашено друзей: {referrals}\n"
        f"💰 Заработано рефералами: {earned} алмазов"
    )
    
    await message.answer(text, parse_mode="Markdown")

# ==========================================
# 🌐 ОБРАБОТКА ДАННЫХ WEB-APP
# ==========================================
@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    try: 
        data = json.loads(message.web_app_data.data)
    except json.JSONDecodeError: 
        return
        
    action = data.get("action")
    user_id = str(message.from_user.id)
    
    if action == "buy_credits":
        chat_id = message.chat.id
        await bot.send_invoice(
            chat_id=chat_id, 
            title="Пополнение баланса", 
            description="100 алмазов", 
            payload="credits_100", 
            provider_token="", 
            currency="XTR", 
            prices=[LabeledPrice(label="100 алмазов", amount=100)]
        )
    elif action == "like_song":
        song_id = data.get("song_id")
        if song_id: 
            await toggle_like(user_id, song_id)

# ==========================================
# 🚨 ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК
# ==========================================
@dp.errors()
async def errors_handler(update: types.Update, exception: Exception):
    logging.error(f"Unhandled error: {type(exception).__name__}: {exception}")
    return True

# ==========================================
# 🚀 ЗАПУСК БОТА
# ==========================================
async def main():
    cleanup_temp_files()
    await init_db()
    logging.info("Бот запущен. Версия 3.2 (Удобный Мобильный UX) активна!")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())