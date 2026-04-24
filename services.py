import asyncio
import httpx
import base64
import logging
import os
import random
import urllib.parse
from typing import Optional
from gigachat import GigaChat

from config import (
    GIGACHAT_KEY, PROXY_KEY, MUSIC_KEY, EVOLINK_BASE_URL, 
    REPLICATE_TOKEN, GOOGLE_SHEETS_URL
)

_evo_base = str(EVOLINK_BASE_URL).strip() if EVOLINK_BASE_URL else "https://api.evolink.ai"
if not _evo_base.startswith("http"):
    _evo_base = "https://" + _evo_base

giga = GigaChat(credentials=GIGACHAT_KEY, verify_ssl_certs=False) if GIGACHAT_KEY else None

GENERATION_LIMIT = 2
generation_semaphore = asyncio.Semaphore(GENERATION_LIMIT)

# 🌐 ГЛОБАЛЬНЫЙ HTTP-КЛИЕНТ
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(60.0, connect=10.0),
    limits=httpx.Limits(max_connections=20)
)

def sanitize_text(text: str, max_len=4000) -> str:
    if not text: return "Empty result"
    return text.strip()[:max_len]

async def safe_request(func, retries=3, delay=2):
    for i in range(retries):
        try: return await func()
        except Exception as e:
            if i == retries - 1:
                logging.error(f"API request failed: {e}")
                raise
            await asyncio.sleep(delay)

# --- АНАЛИТИКА ---
async def send_to_google_sheets(payload: dict):
    if not GOOGLE_SHEETS_URL: return
    try: await safe_request(lambda: http_client.post(GOOGLE_SHEETS_URL, json=payload, timeout=5.0))
    except Exception as e: logging.error(f"Google Sheets Error: {e}")

def log_action_bg(user_id: str, action: str, details: str = "", cost: int = 0):
    short_details = (details[:200] + '...') if len(details) > 200 else details
    payload = {"type": "log", "user_id": user_id, "action": action, "details": short_details, "cost": cost}
    asyncio.create_task(send_to_google_sheets(payload))

async def update_stats_bg():
    if not GOOGLE_SHEETS_URL: return
    try:
        import database as db 
        async with db.db_instance._lock:
            if not db.db_instance._conn: await db.db_instance.connect()
            uc = await (await db.db_instance._conn.execute("SELECT COUNT(*) FROM users")).fetchone()
            sc = await (await db.db_instance._conn.execute("SELECT COUNT(*) FROM songs")).fetchone()
        payload = {"type": "stats", "users_count": uc[0] if uc else 0, "songs_count": sc[0] if sc else 0}
        asyncio.create_task(send_to_google_sheets(payload))
    except Exception as e: logging.error(f"Stats Error: {e}")

# --- МОЩНЫЙ ИИ ДЛЯ PRO ---
async def call_pro_llm(prompt: str, system_prompt: str = "") -> str:
    if not PROXY_KEY: return "ERROR_PROXY_KEY_MISSING"
    headers = {"Authorization": f"Bearer {PROXY_KEY}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": "gpt-4o", 
        "messages": messages,
        "max_tokens": 1500,
        "temperature": 0.7
    }
    try:
        resp = await safe_request(lambda: http_client.post("https://api.proxyapi.ru/openai/v1/chat/completions", json=payload, headers=headers))
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        return f"ERROR_PRO_MODEL_HTTP_{resp.status_code}"
    except Exception: return "ERROR_CONNECTION"

# --- ГЕНЕРАЦИЯ ТЕКСТА (С ЖЁСТКИМ АНАЛИЗОМ АРТИСТОВ) ---
async def ai_generate_lyrics(idea: str, language: str, is_pro: bool = False) -> str:
    lang_prompt = f"Язык песни: {language}." if language != "🤖 На усмотрение ИИ" else "Выбери язык сам."
    
    if is_pro:
        sys = (
            "Ты — платиновый хитмейкер. Твоя задача — написать текст песни.\n"
            "🚨 КРИТИЧЕСКОЕ ПРАВИЛО: Пользователь будет называть имена певцов (например, Майкл Джексон, Анжелика Варум). ОН ПРОСИТ ИХ МУЗЫКАЛЬНЫЙ СТИЛЬ, А НЕ ПЕСНЮ О НИХ!\n"
            "Тебе КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать эти имена в тексте. Героями песни не могут быть реальные артисты. Песня должна быть о чувствах, мыслях или сюжете.\n"
            "Структура: [Intro], [Verse 1], [Chorus], [Bridge], [Outro].\n"
            "Ударения: В русских словах ставь ЗАГЛАВНУЮ букву на ударную гласную (зАмок / замОк).\n"
            "Выведи только текст."
        )
        res = await call_pro_llm(f"Тема и референсы: '{idea}'. {lang_prompt}", sys)
        if not res.startswith("ERROR"):
            return sanitize_text(res, max_len=2500).replace("```", "").strip()
            
    if not giga: return "⚠️ ИИ недоступен."
    try:
        sys_basic = (
            "Ты профессиональный поэт-песенник. Напиши текст песни. "
            "🚨 ВАЖНО: Если в запросе есть имена (Майкл Джексон и т.д.), это указание на музыкальный стиль! "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать эти имена в тексте песни. Песня должна быть без упоминания реальных артистов. "
            "Выведи ТОЛЬКО текст."
        )
        res = await safe_request(lambda: giga.achat(f"{sys_basic} Запрос пользователя: {idea}. {lang_prompt}"))
        return sanitize_text(res.choices[0].message.content, max_len=2500).replace("```", "").strip()
    except Exception: return "⚠️ Ошибка генерации."

async def ai_edit_lyrics(old_lyrics: str, edit_request: str, is_pro: bool = False) -> str:
    if is_pro:
        res = await call_pro_llm(f"Текст:\n{old_lyrics}\n\nПравки: {edit_request}", "Ты музыкальный редактор. Сохрани структуру тегов Suno. Выведи только обновлённый текст, без символов ```.")
        if not res.startswith("ERROR"):
            return sanitize_text(res, max_len=2500).replace("```", "").strip()
            
    if not giga: return old_lyrics
    try:
        res = await safe_request(lambda: giga.achat(f"Текст:\n{old_lyrics}\nПравки: {edit_request}. Без символов ```."))
        return sanitize_text(res.choices[0].message.content, max_len=2500).replace("```", "").strip()
    except Exception: return old_lyrics

async def ai_generate_title(lyrics: str) -> str:
    if not giga: return "Мой хит"
    try:
        prompt = f"Придумай название для песни (1-3 слова). ВЫВЕДИ ТОЛЬКО НАЗВАНИЕ. Без кавычек, без пояснений, без символов # или *. Текст:\n{lyrics[:500]}"
        res = await safe_request(lambda: giga.achat(prompt))
        title = sanitize_text(res.choices[0].message.content)
        title = title.replace('*', '').replace('#', '').replace('"', '').split('\n')[0].strip()
        return title[:75]
    except Exception: return "Мой хит"

# --- ГЕНЕРАЦИЯ СТИЛЯ (УМНЫЙ АНАЛИЗ ТЕКСТА И РЕФЕРЕНСОВ) ---
async def ai_compile_style(genre: str, vocals: str, instruments: str, mood: str, lyrics: str, is_pro: bool = False, original_idea: str = "") -> str:
    user_prompt = (
        f"Изначальная задумка пользователя (референсы): {original_idea}\n"
        f"Жанр: {genre}\nВокал: {vocals}\nНастроение/Темп: {mood}\nИнструменты: {instruments}\n\n"
        f"Текст песни:\n{lyrics[:800]}"
    )

    if is_pro:
        sys = (
            "Ты гениальный AI-саунд-продюсер. Скомпилируй идеальный Style Prompt для Suno v5.5.\n"
            "ФОРМУЛА: [vocal texture], [core genre], [lead instruments], [mood], [BPM], [production quality].\n\n"
            "🧠 УМНЫЙ АНАЛИЗ:\n"
            "1. Если параметр 'SMART_AI_ANALYSIS' — прочитай текст и подбери параметр сам.\n"
            "2. Если в 'Изначальной задумке' есть имена артистов — переведи их фирменное звучание в правильные жанровые теги (например, 'Michael Jackson' -> '80s pop, funk, rhythmic, smooth male vocal'). Сами имена артистов писать ЗАПРЕЩЕНО (Suno их блокирует)!\n\n"
            "ПРАВИЛА: ТОЛЬКО английский язык. Строго до 115 символов. Без квадратных скобок."
        )
        res = await call_pro_llm(user_prompt, sys)
        if not res.startswith("ERROR"):
            return sanitize_text(res, max_len=115).strip("[]")
            
    if not giga: return "pop, emotional"
    try:
        sys_giga = "Translate and compile to Suno AI tags (english, comma separated). Extract vibe from artist names if present, but DO NOT use real artist names. Output ONLY tags under 110 chars."
        res = await safe_request(lambda: giga.achat(f"{sys_giga}\n\n{user_prompt}"))
        return sanitize_text(res.choices[0].message.content, max_len=115).strip("[]")
    except Exception: return "pop, emotional"

async def ai_edit_style(old_style: str, edit_request: str, is_pro: bool = False) -> str:
    if is_pro:
        sys = "Ты саунд-продюсер. Переработай промпт (английский, макс 115 симв). Без имён артистов. Выведи только новые теги без квадратных скобок."
        prompt = f"Текущий промпт: [{old_style}]. Пожелания пользователя: '{edit_request}'. Перепиши."
        res = await call_pro_llm(prompt, sys)
        if not res.startswith("ERROR"):
            return sanitize_text(res, max_len=115).strip("[]")
            
    if not giga: return sanitize_text(edit_request)
    try:
        res = await safe_request(lambda: giga.achat(f"Translate to Suno tags. Request: {edit_request}. Output ONLY tags."))
        return sanitize_text(res.choices[0].message.content, max_len=115).strip("[]")
    except Exception: return sanitize_text(edit_request)

# --- ОБЛОЖКИ И МУЗЫКА ---
async def ai_generate_cover_prompt(title: str, style: str, is_pro: bool = False) -> str:
    # Возвращаем красивый промпт, описывающий стиль, для бесплатного генератора
    safe_prompts = [
        f"A beautiful aesthetic album cover for {style} music, vibrant colors, cinematic lighting, masterpiece",
        f"A creative and moody album cover art, {style} vibe, highly detailed, 8k resolution",
        f"Abstract visual representation of {style} music, cool shapes, neon glow, music album art",
        f"A cinematic and dramatic cover art for a {style} song, atmospheric, high quality"
    ]
    return random.choice(safe_prompts)

async def generate_suno_music(lyrics: str, style: str, is_instrumental: bool, title: str, model_version: str) -> Optional[str]:
    if not MUSIC_KEY: return None
    headers = {"Authorization": f"Bearer {MUSIC_KEY}", "Content-Type": "application/json"}
    
    # Жёстко обрезаем название песни до 75 символов
    safe_title = title[:75] if title else "My Song"
    
    payload = {
        "model": model_version, 
        "prompt": lyrics, 
        "style": style, 
        "title": safe_title, 
        "make_instrumental": is_instrumental, 
        "custom_mode": True
    }
    
    async with generation_semaphore:
        try:
            resp = await safe_request(lambda: http_client.post(f"{_evo_base}/v1/audios/generations", json=payload, headers=headers, timeout=120.0))
            if resp.status_code != 200: 
                logging.error(f"❌ Suno API Error: {resp.text}")
                return None
            task_id = resp.json().get("id")
            if not task_id: return None
            
            for _ in range(80):
                await asyncio.sleep(6)
                data = (await safe_request(lambda: http_client.get(f"{_evo_base}/v1/tasks/{task_id}", headers=headers, timeout=30.0))).json()
                if data.get("status") == "completed": 
                    return data.get("audio_url") or (data.get("result_data") and data["result_data"][0].get("audio_url")) or (data.get("output") and data["output"][0].get("audio_url"))
                if data.get("status") in ("failed", "error"): return None
            return None
        except Exception as e: 
            logging.error(f"Generation Exception: {e}")
            return None

async def generate_image(prompt: str) -> Optional[bytes]:
    # 🔥 ИСПОЛЬЗУЕМ БЕСПЛАТНЫЙ СЕРВИС POLLINATIONS.AI
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    
    async with generation_semaphore:
        try:
            # Делаем простой GET-запрос: сервис сразу отдаёт картинку
            resp = await safe_request(lambda: http_client.get(url, timeout=60.0))
            if resp.status_code == 200:
                return resp.content
            else:
                logging.error(f"Free image generation failed with status {resp.status_code}")
                return None
        except Exception as e: 
            logging.error(f"Free image generation error: {e}")
            return None

# --- AI КАВЕР ---
async def make_ai_cover(voice_path: str, song_path: str) -> Optional[str]:
    if not REPLICATE_TOKEN: return None
    try:
        with open(voice_path, "rb") as f: voice_uri = f"data:audio/ogg;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        with open(song_path, "rb") as f: song_uri = f"data:audio/mpeg;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        headers = {"Authorization": f"Bearer {REPLICATE_TOKEN}", "Content-Type": "application/json"}
        payload = {
            "version": "0a9c7c558af4c8f20ea30a1eb9ce6ab1f8eb9e124f0c1d1a9b9a6b1897d19760", 
            "input": {"song_input": song_uri, "rvc_model": "custom", "custom_voice": voice_uri, "pitch_change": "no-change", "keep_background": True}
        }
        async with generation_semaphore:
            req = await safe_request(lambda: http_client.post("https://api.replicate.com/v1/predictions", json=payload, headers=headers, timeout=150.0))
            if req.status_code != 201: return None
            task_url = req.json()["urls"]["get"]
            for _ in range(60):
                await asyncio.sleep(5)
                data = (await safe_request(lambda: http_client.get(task_url, headers=headers, timeout=30.0))).json()
                if data["status"] == "succeeded": return data["output"]
                elif data["status"] in ["failed", "canceled"]: return None
            return None 
    except Exception as e: 
        logging.error(f"Replicate AI Cover error: {e}")
        return None