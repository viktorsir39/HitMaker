import os
import uuid
import json
import logging
import random
import httpx
import html
from aiogram import Router, Bot, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    LabeledPrice, PreCheckoutQuery, BufferedInputFile, 
    ReplyKeyboardRemove, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite

import config
import database as db
import keyboards as kb
import services as svc
from states import CaptchaFSM, CoverFSM, CreateSongFSM
from utils import check_rate_limit, get_user_lock, clean_user_input

router = Router()

AI_INSTS = ["analog synths", "heavy distorted guitars", "acoustic guitar, soft piano", "orchestral strings", "groovy bassline", "808 beats"]
MAX_LYRICS = 2500

# ==========================================
# 🛑 ОТМЕНА И ПОМОЩЬ
# ==========================================
@router.message(F.text.in_(["❌ Отмена", "/cancel", "Отмена"]))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=kb.get_main_kb(str(message.from_user.id)))

@router.callback_query(F.data == "cancel_creation")
async def cancel_creation_inline(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.delete()
    await call.message.answer("❌ Действие отменено.", reply_markup=kb.get_main_kb(str(call.from_user.id)))
    await call.answer()

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    if not check_rate_limit(str(message.from_user.id)): return
    text = ("🛠 **Справка по HitMaker Studio**\n\n"
            "🎵 **Быстрый трек** — Базовая генерация (10💎)\n"
            "🎛 **PRO-Студия** — Продвинутая ИИ генерация (40💎)\n"
            "🎙 **AI-Кавер** — Твой голос в любой песне (30💎)\n"
            "🎛 **Мои треки** — Управление медиатекой\n"
            "🏆 **Чарты** — Топ популярных песен\n"
            "💎 **Пополнить баланс** — Покупка алмазов\n"
            "❌ **/cancel** — Отмена текущего действия")
    await message.answer(text, parse_mode="Markdown")

# ==========================================
# 🚀 СТАРТ И КАПЧА
# ==========================================
@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    if not check_rate_limit(user_id): return
    
    referrer = message.text.split()[1][4:] if len(message.text.split()) > 1 and message.text.split()[1].startswith("ref_") else None
    user_data = await db.get_user(user_id)
    
    if not user_data:
        target = random.choice(list(kb.CAPTCHA_ITEMS.keys()))
        await state.update_data(captcha_target=kb.CAPTCHA_ITEMS[target], referrer=referrer)
        await message.answer(
            f"Привет 👋 Нажми на кнопку, где изображён(а) <b>{html.escape(target)}</b>?", 
            reply_markup=kb.get_captcha_kb(kb.CAPTCHA_ITEMS[target]), 
            parse_mode="HTML"
        )
        await state.set_state(CaptchaFSM.waiting_for_emoji)
    else:
        await message.answer("С возвращением в студию!", reply_markup=kb.get_main_kb(user_id))

@router.message(CaptchaFSM.waiting_for_emoji)
async def process_captcha(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not data: return
    
    if message.text == data.get("captcha_target"):
        await state.clear()
        user_id = str(message.from_user.id)
        await db.create_user(user_id, data.get("referrer"))
        svc.log_action_bg(user_id, "Новый пользователь", f"Реферал: {data.get('referrer')}", 0)
        await svc.update_stats_bg()
        
        welcome = "🎬 Добро пожаловать! Дарим тебе 50 алмазов на пробу! 🎁"
        main_kb = kb.get_main_kb(user_id)
        
        try:
            if os.path.exists("welcome.mp4"): 
                await message.answer_video(FSInputFile("welcome.mp4"), caption=welcome, reply_markup=main_kb)
            elif os.path.exists("welcome.jpg"): 
                await message.answer_photo(FSInputFile("welcome.jpg"), caption=welcome, reply_markup=main_kb)
            else: 
                await message.answer(welcome, reply_markup=main_kb)
        except Exception: 
            await message.answer(welcome, reply_markup=main_kb)
    else:
        target = random.choice(list(kb.CAPTCHA_ITEMS.keys()))
        await state.update_data(captcha_target=kb.CAPTCHA_ITEMS[target])
        await message.answer(
            f"❌ Ошибка! Нажми на <b>{html.escape(target)}</b>?", 
            reply_markup=kb.get_captcha_kb(kb.CAPTCHA_ITEMS[target]), 
            parse_mode="HTML"
        )

# ==========================================
# 👑 АДМИН ПАНЕЛЬ И ОПЛАТА
# ==========================================
@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != config.ADMIN_ID: return
    text = "👑 <b>ПАНЕЛЬ АДМИНА</b>\nСмотрите логи в Google Sheets."
    if config.GOOGLE_SHEETS_URL: 
        text += f'\n📊 <a href="{config.GOOGLE_SHEETS_URL.replace("/exec", "/edit")}">Таблица Логов</a>'
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

@router.message(Command("give"))
async def admin_give(message: types.Message):
    if message.from_user.id != config.ADMIN_ID: return
    args = message.text.split()
    if len(args) == 3:
        await db.update_credits(args[1], int(args[2]))
        svc.log_action_bg(str(config.ADMIN_ID), "Выдача кредитов", f"Кому: {args[1]}", int(args[2]))
        await message.answer(f"✅ Выдано {args[2]} алмазов.")

@router.message(F.text == "💎 Пополнить баланс")
async def buy_menu(message: types.Message):
    uid = str(message.from_user.id)
    if not check_rate_limit(uid): return
    u = await db.get_user(uid)
    await message.answer(f"💎 Баланс: {u['credits'] if u else 0}💎\nВыберите пакет:", reply_markup=kb.get_payment_kb())

@router.callback_query(F.data.startswith("buy_"))
async def process_payment(call: types.CallbackQuery, bot: Bot):
    if not check_rate_limit(str(call.from_user.id)): 
        return await call.answer("Не так часто!", show_alert=True)
    amt = int(call.data.split("_")[1])
    await bot.send_invoice(
        call.message.chat.id, 
        f"Пакет {amt}💎", 
        "Пополнение", 
        f"credits_{amt}", 
        "", 
        "XTR", 
        [LabeledPrice(label=f"{amt} алмазов", amount=amt)]
    )
    await call.answer()

@router.pre_checkout_query(lambda q: True)
async def pre_checkout(query: PreCheckoutQuery, bot: Bot): 
    await bot.answer_pre_checkout_query(query.id, ok=True)

@router.message(F.successful_payment)
async def pay_ok(message: types.Message):
    amt = int(message.successful_payment.invoice_payload.split("_")[1])
    uid = str(message.from_user.id)
    await db.update_credits(uid, amt)
    svc.log_action_bg(uid, "Покупка Stars", f"+{amt}💎", 0)
    await message.answer(f"✅ Успешно! {amt}💎 зачислены.")

# ==========================================
# 🎵 СОЗДАНИЕ ПЕСНИ (ВИЗУАЛ)
# ==========================================
@router.message(F.text.in_(["🎵 Быстрый трек (10💎)", "🎛 PRO-Студия (40💎)", "🎵 Создать песню"]))
async def song_start(message: types.Message, state: FSMContext):
    if not check_rate_limit(str(message.from_user.id)): return
    is_pro = "PRO" in message.text
    cost = config.COST_PRO if is_pro else config.COST_QUICK
    
    await state.clear()
    await state.update_data(genre="", vocals="", mood="", instruments="", is_pro=is_pro, cost=cost, ai_genre="", ai_vocal="", ai_inst="", original_idea="")
    mode_text = "🎛 <b>PRO-Режим активирован</b>" if is_pro else "🎵 <b>Базовый режим</b>"
    await message.answer(f"{mode_text}\n🌍 <b>Выбери язык для песни:</b>", reply_markup=kb.get_language_kb(), parse_mode="HTML")
    await state.set_state(CreateSongFSM.waiting_for_language)

@router.message(CreateSongFSM.waiting_for_language)
async def lang_set(message: types.Message, state: FSMContext):
    await state.update_data(language=clean_user_input(message.text))
    await message.answer("Как получить текст?", reply_markup=kb.get_lyrics_mode_kb())
    await state.set_state(CreateSongFSM.waiting_for_lyrics_mode)

@router.message(CreateSongFSM.waiting_for_lyrics_mode, F.text == "🤖 Сгенерировать ИИ")
async def lyrics_ai(message: types.Message, state: FSMContext):
    await message.answer("Введи тему, идею или референсы (на кого должно быть похоже) для песни:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(CreateSongFSM.waiting_for_keywords)

@router.message(CreateSongFSM.waiting_for_keywords)
async def lyrics_gen(message: types.Message, state: FSMContext):
    await message.answer("🔄 Генерирую текст (в PRO-режиме это занимает чуть дольше)...")
    d = await state.get_data()
    clean_idea = clean_user_input(message.text)
    
    await state.update_data(original_idea=clean_idea)
    
    lyr = await svc.ai_generate_lyrics(clean_idea, d.get("language", "🤖 На усмотрение ИИ"), d.get("is_pro", False))
    await state.update_data(lyrics=lyr)
    await message.answer(
        f"📝 Текст готов:\n\n{html.escape(lyr)}\n\nНапиши правки текстом или жми кнопку.", 
        reply_markup=kb.get_lyrics_confirm_kb(), 
        parse_mode="HTML"
    )
    await state.set_state(CreateSongFSM.waiting_for_lyrics_edit)

@router.message(CreateSongFSM.waiting_for_lyrics_edit)
async def lyrics_edit(message: types.Message, state: FSMContext):
    if message.text == "✅ Текст супер, дальше!":
        await message.answer("Напиши название трека или нажми /auto_title", reply_markup=ReplyKeyboardRemove())
        await state.set_state(CreateSongFSM.waiting_for_title)
    else:
        d = await state.get_data()
        await message.answer("🔄 Переписываю...")
        clean_req = clean_user_input(message.text)
        new_lyr = await svc.ai_edit_lyrics(d.get("lyrics", ""), clean_req, d.get("is_pro", False))
        await state.update_data(lyrics=new_lyr)
        await message.answer(f"📝 Новый текст:\n\n{html.escape(new_lyr)}", reply_markup=kb.get_lyrics_confirm_kb(), parse_mode="HTML")

@router.message(CreateSongFSM.waiting_for_lyrics_mode, F.text == "✍️ Напишу сам")
async def lyrics_manual(message: types.Message, state: FSMContext):
    await message.answer("Отправь текст. В конце напиши /done", reply_markup=ReplyKeyboardRemove())
    await state.set_state(CreateSongFSM.waiting_for_lyrics_text)

@router.message(CreateSongFSM.waiting_for_lyrics_text)
async def lyrics_collect(message: types.Message, state: FSMContext):
    if message.text == "/done":
        d = await state.get_data()
        lyr = d.get("temp_lyrics", "").strip()
        if not lyr: 
            return await message.answer("❌ Пусто!")
        await state.update_data(lyrics=lyr)
        await message.answer("Название или /auto_title")
        await state.set_state(CreateSongFSM.waiting_for_title)
    else:
        d = await state.get_data()
        clean_lyr = clean_user_input(message.text)
        await state.update_data(temp_lyrics=d.get("temp_lyrics", "") + clean_lyr + "\n")
        await message.answer("Добавлено. Ещё текст или /done")

@router.message(CreateSongFSM.waiting_for_title)
async def title_set(message: types.Message, state: FSMContext):
    d = await state.get_data()
    clean_msg = clean_user_input(message.text)
    title = await svc.ai_generate_title(d.get("lyrics", "")) if clean_msg == "/auto_title" else clean_msg
    await state.update_data(title=title)
    
    text = f"🎵 Название: **{title}**\n\n🎸 **Выбери жанр будущего хита:**"
    await message.answer(text, reply_markup=kb.get_genres_keyboard(), parse_mode="Markdown")
    await state.set_state(CreateSongFSM.waiting_for_genre)

@router.callback_query(CreateSongFSM.waiting_for_genre, F.data.startswith("genre_"))
async def genre_selected(call: types.CallbackQuery, state: FSMContext):
    genre_code = call.data
    
    if genre_code == "genre_custom":
        await call.message.delete()
        await call.message.answer("✍️ Напиши свой стиль (промпт) обычным текстом в чат:")
        return
        
    if genre_code == "genre_mix":
        await state.update_data(mix_genres=[])
        await call.message.edit_text(
            "🔀 **Смешивание стилей**\n\nВыбери **ПЕРВЫЙ** жанр из списка:", 
            reply_markup=kb.get_mix_keyboard(), 
            parse_mode="Markdown"
        )
        await call.answer()
        return

    sub_kb = kb.get_subgenres_keyboard(genre_code)
    await call.message.edit_text("🎶 Отличный выбор! Теперь уточни поджанр:", reply_markup=sub_kb)
    await call.answer()

@router.callback_query(CreateSongFSM.waiting_for_genre, F.data.startswith("mix_"))
async def process_mix(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    mix_genres = data.get("mix_genres", [])
    
    clean_name = call.data.replace("mix_", "")
    display_name = next((name for name, cb in kb.MAIN_GENRES if cb.endswith(clean_name)), clean_name)
    
    mix_genres.append(display_name)
    await state.update_data(mix_genres=mix_genres)
    
    if len(mix_genres) == 1:
        await call.message.edit_text(
            f"🔀 **Смешивание стилей**\n\nПервый жанр: **{mix_genres[0]}** ✅\nТеперь выбери **ВТОРОЙ** жанр:", 
            reply_markup=kb.get_mix_keyboard(), 
            parse_mode="Markdown"
        )
    else:
        combined_prompt = f"{mix_genres[0]} + {mix_genres[1]} fusion".strip()
        await state.update_data(genre=combined_prompt)
        
        await call.message.edit_text(
            f"🔥 Получился огненный микс: **{mix_genres[0]} + {mix_genres[1]}**!\n\n🎤 **Выбери тип вокала:**", 
            reply_markup=kb.get_vocals_inline_kb(), 
            parse_mode="Markdown"
        )
        await state.set_state(CreateSongFSM.waiting_for_vocals)
    
    await call.answer()

@router.message(CreateSongFSM.waiting_for_genre, F.text)
async def custom_genre_text(message: types.Message, state: FSMContext):
    await state.update_data(genre=clean_user_input(message.text))
    await message.answer("🎤 **Выбери тип вокала:**", reply_markup=kb.get_vocals_inline_kb(), parse_mode="Markdown")
    await state.set_state(CreateSongFSM.waiting_for_vocals)

@router.callback_query(CreateSongFSM.waiting_for_genre, F.data == "back_to_genres")
@router.callback_query(CreateSongFSM.waiting_for_vocals, F.data == "back_to_genres")
async def back_to_genres_menu(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(CreateSongFSM.waiting_for_genre)
    await call.message.edit_text("🎸 **Выбери жанр будущего хита:**", reply_markup=kb.get_genres_keyboard(), parse_mode="Markdown")
    await call.answer()

@router.callback_query(CreateSongFSM.waiting_for_genre, F.data.startswith("sub_") | F.data.startswith("final_"))
async def subgenre_selected(call: types.CallbackQuery, state: FSMContext):
    clean_genre = call.data.replace("sub_", "").replace("final_genre_", "").replace("_", " ")
    await state.update_data(genre=clean_genre) 
    
    await call.message.edit_text("🎤 **Выбери тип вокала:**", reply_markup=kb.get_vocals_inline_kb(), parse_mode="Markdown")
    await state.set_state(CreateSongFSM.waiting_for_vocals)
    await call.answer()

@router.callback_query(CreateSongFSM.waiting_for_vocals, F.data.startswith("vocal_"))
async def vocal_selected(call: types.CallbackQuery, state: FSMContext):
    if call.data == "vocal_skip":
        await state.update_data(vocals="")
    else:
        vocal_map = {
            "vocal_male": "Male vocal", "vocal_female": "Female vocal",
            "vocal_raspy": "Raspy vocal, rough voice", "vocal_smooth": "Smooth velvety vocal, soft delivery",
            "vocal_powerful": "Powerful belting vocal, emotional delivery", "vocal_whisper": "Whispering vocal, intimate delivery",
            "vocal_rap": "Rap flow", "vocal_growl": "Extreme vocal, growling",
            "vocal_opera": "Operatic vocal", "vocal_vocoder": "Vocoder, autotune",
            "vocal_duet": "Male and female duet vocals", "vocal_choir": "Epic choir",
            "vocal_instrumental": "Instrumental", "vocal_ai": "На усмотрение ИИ"
        }
        await state.update_data(vocals=vocal_map.get(call.data, ""))

    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer("🎭 **Выбери настроение и темп трека:**", reply_markup=kb.get_mood_tempo_inline_kb(), parse_mode="Markdown")
    await state.set_state(CreateSongFSM.waiting_for_mood)
    await call.answer()

@router.callback_query(CreateSongFSM.waiting_for_mood, F.data.startswith("mood_") | (F.data == "back_to_vocals"))
async def mood_selected(call: types.CallbackQuery, state: FSMContext):
    if call.data == "back_to_vocals":
        await call.message.edit_text("🎤 **Выбери тип вокала:**", reply_markup=kb.get_vocals_inline_kb(), parse_mode="Markdown")
        await state.set_state(CreateSongFSM.waiting_for_vocals)
        await call.answer()
        return

    if call.data == "mood_skip":
        await state.update_data(mood="")
    elif call.data == "mood_ai":
        await state.update_data(mood="SMART_AI_ANALYSIS")
    else:
        mood_map = {
            "mood_energetic": "Fast tempo, energetic, upbeat, driving rhythm",
            "mood_sad": "Slow tempo, melancholic, sad, emotional, deep",
            "mood_dance": "Danceable groove, upbeat, rhythmic",
            "mood_dark": "Dark mood, heavy, aggressive, intense",
            "mood_chill": "Chill, relaxing, slow tempo, lo-fi vibes",
            "mood_epic": "Epic, cinematic, massive scale, orchestral feel"
        }
        await state.update_data(mood=mood_map.get(call.data, ""))

    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer("🥁 **Выберите инструменты:**", reply_markup=kb.get_instruments_kb(), parse_mode="Markdown")
    await state.set_state(CreateSongFSM.waiting_for_instruments)
    await call.answer()

@router.callback_query(CreateSongFSM.waiting_for_instruments, F.data.startswith("inst_"))
async def inst_selected(call: types.CallbackQuery, state: FSMContext):
    d = await state.get_data()

    if call.data == "inst_generate":
        await call.message.edit_text("⏳ ИИ анализирует настройки и собирает промпт...", reply_markup=None)
        
        st = await svc.ai_compile_style(
            genre=d.get('genre', ''),
            vocals=d.get('vocals', ''),
            instruments=d.get('instruments', ''),
            mood=d.get('mood', ''),
            lyrics=d.get('lyrics', ''),
            is_pro=d.get('is_pro', False),
            original_idea=d.get('original_idea', '')
        )
        
        await state.update_data(style=st)
        
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer(
            f"✨ Промпт стиля готов:\n<code>{html.escape(st)}</code>\n\nМожешь написать правки обычным текстом в чат или жми ✅", 
            reply_markup=kb.get_confirm_kb(), 
            parse_mode="HTML"
        )
        
        await state.set_state(CreateSongFSM.waiting_for_style_confirm)
        await call.answer()
        return
        
    inst_map = {
        "inst_acoustic": "Acoustic guitar", "inst_electric": "Electric guitar, overdrive",
        "inst_piano": "Piano, keys", "inst_drums_bass": "Punchy drums, deep bassline",
        "inst_orchestra": "Orchestral strings, epic brass", "inst_folk": "Folk instruments",
        "inst_ai": "На усмотрение ИИ"
    }
    
    clean_msg = inst_map.get(call.data, "")
    
    if clean_msg == "На усмотрение ИИ":
        new_ai = random.choice(AI_INSTS)
        old_ai = d.get('ai_inst', '')
        curr = d.get('instruments', '')
        if old_ai and old_ai in curr: new_i = curr.replace(old_ai, new_ai)
        else: new_i = f"{curr}, {new_ai}".strip(", ") if curr else new_ai
        await state.update_data(instruments=new_i, ai_inst=new_ai)
    else:
        curr = d.get('instruments', '')
        new_i = f"{curr}, {clean_msg}".strip(", ") if curr else clean_msg
        await state.update_data(instruments=new_i, ai_inst="")
        
    try:
        await call.message.edit_text(
            f"✅ Инструменты добавлены:\n**{new_i}**\n\nВыбери еще или нажми 'Сгенерировать промпт!'", 
            reply_markup=kb.get_instruments_kb(), 
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await call.answer()

@router.message(CreateSongFSM.waiting_for_instruments, F.text)
async def custom_inst_text(message: types.Message, state: FSMContext):
    d = await state.get_data()
    curr = d.get('instruments', '')
    clean_msg = clean_user_input(message.text)
    new_i = f"{curr}, {clean_msg}".strip(", ") if curr else clean_msg
    await state.update_data(instruments=new_i, ai_inst="")
    await message.answer(f"✅ Твой инструмент добавлен:\n**{new_i}**\n\nМожешь выбрать еще из списка или сгенерировать промпт.", reply_markup=kb.get_instruments_kb(), parse_mode="Markdown")

# Финал генерации
@router.message(CreateSongFSM.waiting_for_style_confirm)
async def finalize_song(message: types.Message, state: FSMContext):
    if message.text != "✅ Всё верно, создаём!":
        d = await state.get_data()
        clean_req = clean_user_input(message.text)
        await message.answer("🔄 Переосмысляю звучание...", reply_markup=ReplyKeyboardRemove())
        new_style = await svc.ai_edit_style(d.get('style', ''), clean_req, d.get('is_pro', False))
        await state.update_data(style=new_style)
        return await message.answer(f"✨ Обновлённый промпт стиля:\n<code>{html.escape(new_style)}</code>\nМожешь снова исправить текстом или жми ✅", reply_markup=kb.get_confirm_kb(), parse_mode="HTML")
    
    d = await state.get_data()
    if not d or not d.get('title'): return 
        
    uid = str(message.from_user.id)
    lock = get_user_lock(uid)

    if lock.locked(): return await message.answer("⏳ Уже генерирую трек, подожди...")

    async with lock:
        await state.clear() 
        cost = d.get('cost', 10)
        is_pro = d.get('is_pro', False)
        lyrics = d.get('lyrics', '')[:MAX_LYRICS]
        
        if not await db.try_spend_credits(uid, cost):
            return await message.answer(f"🚫 Нужно {cost} алмазов!", reply_markup=kb.get_payment_kb())

        status = await message.answer(f"💎 Списано {cost}💎\n🎨 Рисую обложку...", reply_markup=ReplyKeyboardRemove())
        svc.log_action_bg(uid, "Генерация PRO" if is_pro else "Генерация База", d['title'], cost)
        
        p = await svc.ai_generate_cover_prompt(d['title'], d['style'], is_pro)
        img = await svc.generate_image(p)
        cid = None
        
        try:
            if img:
                c_msg = await message.answer_photo(BufferedInputFile(img, "cover.png"), caption=f"🖼 Обложка готова!\n🎧 Свожу музыку...")
                cid = c_msg.photo[-1].file_id
                await status.delete()
                status = await message.answer("🔄 Магия звука...")
            else: 
                await status.delete()
                status = await message.answer("🎧 Обложка не удалась (слишком строгий стиль), но музыку сводим...")
        except Exception:
            pass 

        # 🔥 ИСПРАВЛЕНИЕ: Evolink обновил API. Используем актуальные suno-v4 и suno-v5.
        model_version = "suno-v5" if is_pro else "suno-v4"
        
        try:
            url = await svc.generate_suno_music(lyrics, d['style'], "Инструментал" in d.get('vocals',''), d['title'], model_version)
            
            if not url: 
                await db.update_credits(uid, cost)
                await status.delete()
                await message.answer("❌ Ошибка генерации (Suno отклонила запрос). Алмазы возвращены.", reply_markup=kb.get_main_kb(uid))
                await state.clear()
                return

            if url.startswith("//"): url = "https:" + url
            elif not url.startswith("http"): url = "https://" + url

            async with httpx.AsyncClient(timeout=60.0) as c: 
                audio = (await svc.safe_request(lambda: c.get(url))).content
                
            msg_a = await message.answer_audio(BufferedInputFile(audio, f"{d['title']}.mp3"), title=d['title'], performer="HitMaker AI")
            
            await db.add_song(uid, d['title'], d['style'], msg_a.audio.file_id, cid)
            await svc.update_stats_bg()
            await status.delete()
            await message.answer(f"✅ Готово!", reply_markup=kb.get_main_kb(uid))
        except Exception as e:
            logging.error(f"Download audio error: {e}")
            await db.update_credits(uid, cost)
            await status.delete()
            await message.answer("❌ Ошибка загрузки готового трека. Алмазы возвращены.", reply_markup=kb.get_main_kb(uid))
            await state.clear()

# --- AI КАВЕР ---
@router.message(F.text == "🎙 AI-Кавер")
async def cov_start(message: types.Message, state: FSMContext):
    if not check_rate_limit(str(message.from_user.id)): return
    cancel_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
    await message.answer("🎤 Отправь голосовое (до 60 сек):", reply_markup=cancel_kb)
    await state.set_state(CoverFSM.waiting_for_voice)

@router.message(CoverFSM.waiting_for_voice, F.voice)
async def cov_voice(message: types.Message, bot: Bot, state: FSMContext):
    if message.voice.duration > 60: return await message.answer("⚠️ Не длиннее 60 сек.")
        
    path = f"voice_{uuid.uuid4().hex}.ogg"
    await bot.download_file((await bot.get_file(message.voice.file_id)).file_path, path)
    await state.update_data(voice_path=path)
    
    markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🎤 Из чартов")], [KeyboardButton(text="📎 Свой файл")], [KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
    await message.answer("Источник песни:", reply_markup=markup)
    await state.set_state(CoverFSM.waiting_for_song_choice)

@router.message(CoverFSM.waiting_for_song_choice, F.text == "🎤 Из чартов")
async def cov_charts(message: types.Message):
    songs = await db.get_global_charts(10)
    if not songs: return await message.answer("Чарты пусты.")
        
    b = InlineKeyboardBuilder()
    for s in songs: 
        b.button(text=f"{s['title']} (❤️{s['likes']})", callback_data=f"cover_song_{s['id']}")
    b.adjust(1)
    await message.answer("Выбери трек:", reply_markup=b.as_markup())

@router.message(CoverFSM.waiting_for_song_choice, F.text == "📎 Свой файл")
async def cov_file_prompt(message: types.Message, state: FSMContext):
    cancel_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
    await message.answer("Отправь MP3 (до 10МБ):", reply_markup=cancel_kb)
    await state.set_state(CoverFSM.waiting_for_external_audio)

@router.message(CoverFSM.waiting_for_external_audio, F.audio | F.document)
async def cov_file_handle(message: types.Message, bot: Bot, state: FSMContext):
    uid = str(message.from_user.id)
    lock = get_user_lock(uid)

    if lock.locked(): return await message.answer("⏳ Идёт генерация, подожди...")

    async with lock:
        d = await state.get_data()
        fs = message.audio.file_size if message.audio else message.document.file_size
        if fs and fs > config.MAX_FILE_SIZE: return await message.answer("❌ Больше 10 МБ!")
        
        vp, tp = d.get("voice_path", ""), f"target_{uuid.uuid4().hex}.mp3"
        await state.clear()

        if not await db.try_spend_credits(uid, config.COST_COVER): 
            return await message.answer("🚫 Нет алмазов!", reply_markup=kb.get_main_kb(uid))
        
        try:
            f_id = message.audio.file_id if message.audio else message.document.file_id
            await bot.download_file((await bot.get_file(f_id)).file_path, tp)
            await message.answer("🔄 Сведение 2-3 минуты...", reply_markup=ReplyKeyboardRemove())
            svc.log_action_bg(uid, "Кавер", "Свой файл", config.COST_COVER)
            
            url = await svc.make_ai_cover(vp, tp)
            if url:
                if url.startswith("//"): url = "https:" + url
                elif not url.startswith("http"): url = "https://" + url
                async with httpx.AsyncClient(timeout=60.0) as c: 
                    aud = (await svc.safe_request(lambda: c.get(url))).content
                await message.answer_audio(BufferedInputFile(aud, "Cover.mp3"), title="AI Cover", reply_markup=kb.get_main_kb(uid))
            else:
                await db.update_credits(uid, config.COST_COVER)
                await message.answer("❌ Ошибка.", reply_markup=kb.get_main_kb(uid))
        finally:
            for p in [vp, tp]:
                if p and os.path.exists(p): os.remove(p)

@router.callback_query(F.data.startswith("cover_song_"))
async def cov_call(call: types.CallbackQuery, bot: Bot, state: FSMContext):
    sid = int(call.data.split("_")[2])
    uid = str(call.from_user.id)
    lock = get_user_lock(uid)

    if lock.locked(): return await call.answer("⏳ Идёт генерация, подожди...", show_alert=True)

    async with lock:
        d = await state.get_data()
        if not d or not d.get("voice_path"): return await call.answer("Голос не найден. Начните заново.", show_alert=True)
            
        vp, tp = d.get("voice_path", ""), f"target_{uuid.uuid4().hex}.mp3"
        await state.clear()

        if not await db.try_spend_credits(uid, config.COST_COVER): return await call.answer("🚫 Нет алмазов!", show_alert=True)

        try:
            async with aiosqlite.connect(config.DB_PATH) as conn:
                cur = await conn.execute("SELECT audio_file_id, title FROM songs WHERE id=?", (sid,))
                r = await cur.fetchone()
            
            if not r: 
                await db.update_credits(uid, config.COST_COVER)
                return await call.answer("Не найдено")
                
            await bot.download_file((await bot.get_file(r[0])).file_path, tp)
            await call.message.edit_text("🔄 Сведение...")
            svc.log_action_bg(uid, "Кавер", f"Трек: {r[1]}", config.COST_COVER)
            
            url = await svc.make_ai_cover(vp, tp)
            if url:
                if url.startswith("//"): url = "https:" + url
                elif not url.startswith("http"): url = "https://" + url
                async with httpx.AsyncClient(timeout=60.0) as c: 
                    aud = (await svc.safe_request(lambda: c.get(url))).content
                await call.message.answer_audio(BufferedInputFile(aud, f"Cover_{r[1]}.mp3"), title=f"{r[1]} Cover", reply_markup=kb.get_main_kb(uid))
            else:
                await db.update_credits(uid, config.COST_COVER)
                await call.message.answer("❌ Ошибка.", reply_markup=kb.get_main_kb(uid))
        finally:
            for p in [vp, tp]:
                if p and os.path.exists(p): os.remove(p)
        await call.answer()

# --- МЕДИАТЕКА И ПРОЧЕЕ ---
@router.message(F.text == "🎛 Мои треки")
async def my_tracks(message: types.Message):
    if not check_rate_limit(str(message.from_user.id)): return
    s = await db.get_user_songs(str(message.from_user.id))
    if not s: return await message.answer("Нет треков!")
        
    b = InlineKeyboardBuilder()
    for x in s: b.button(text=f"🎵 {x['title']}", callback_data=f"sm_{x['id']}")
    b.adjust(1)
    await message.answer("🎛 <b>Медиатека</b>", reply_markup=b.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("sm_"))
async def track_menu(call: types.CallbackQuery):
    sid = int(call.data.split("_")[1])
    b = InlineKeyboardBuilder()
    b.button(text="▶️ Слушать", callback_data=f"listen_{sid}")
    b.button(text="🗑 Удалить", callback_data=f"del_{sid}")
    await call.message.edit_text("Действие:", reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("listen_"))
async def play_track(call: types.CallbackQuery, bot: Bot):
    sid = int(call.data.split("_")[1])
    async with aiosqlite.connect(config.DB_PATH) as conn:
        cur = await conn.execute("SELECT title, style, audio_file_id, cover_file_id, likes FROM songs WHERE id=?", (sid,))
        r = await cur.fetchone()
        
    if not r: return await call.answer("Не найдено")
        
    cap = f"🎵 <b>{html.escape(r[0])}</b>\nСтиль: {html.escape(r[1])}\n❤️ {r[4]}"
    if r[3]: await bot.send_photo(call.message.chat.id, r[3], caption=cap, parse_mode="HTML")
    else: await bot.send_message(call.message.chat.id, cap, parse_mode="HTML")
        
    await bot.send_audio(call.message.chat.id, r[2], title=r[0])
    await call.answer()

@router.callback_query(F.data.startswith("del_"))
async def del_track(call: types.CallbackQuery):
    sid = int(call.data.split("_")[1])
    async with aiosqlite.connect(config.DB_PATH) as conn:
        await conn.execute("DELETE FROM songs WHERE id=?", (sid,))
        await conn.commit()
    await svc.update_stats_bg()
    await call.message.edit_text("✅ Удалено.")

@router.message(F.text == "🏆 Чарты")
async def show_charts(message: types.Message):
    if not check_rate_limit(str(message.from_user.id)): return
    s = await db.get_global_charts()
    if not s: return await message.answer("Пусто!")
        
    text = "🏆 <b>ТОП-10</b>\n\n" + "\n".join([f"{i+1}. {html.escape(x['title'])} (❤️{x['likes']})" for i, x in enumerate(s)])
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "👤 Профиль")
async def show_profile(message: types.Message):
    uid = str(message.from_user.id)
    if not check_rate_limit(uid): return
    u = await db.get_user(uid)
    if not u: return
        
    songs = await db.get_user_songs(uid)
    text = f"👤 <b>Профиль</b>\n💎 Баланс: {u['credits']}\n🎵 Создано: {len(songs)}\n👥 Рефералы: {u['referrals']}"
    await message.answer(text, parse_mode="HTML")

@router.errors()
async def err_h(event: types.ErrorEvent):
    logging.error(f"Global Error: {event.exception}")
    return True