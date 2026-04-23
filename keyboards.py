import random
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ==========================================
# 1. СТАРЫЕ КЛАВИАТУРЫ (Reply и Базовые Inline)
# ==========================================
CAPTCHA_ITEMS = {"🚗": "🚗", "🎸": "🎸", "🍎": "🍎", "🐶": "🐶", "✈️": "✈️"}

def get_captcha_kb(target_emoji: str) -> ReplyKeyboardMarkup:
    items = list(CAPTCHA_ITEMS.values())
    random.shuffle(items)
    row = [KeyboardButton(text=i) for i in items]
    return ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True)

def get_main_kb(user_id: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎵 Быстрый трек (10💎)"), KeyboardButton(text="🎛 PRO-Студия (40💎)")],
        [KeyboardButton(text="🎙 AI-Кавер"), KeyboardButton(text="🎛 Мои треки")],
        [KeyboardButton(text="💎 Пополнить баланс"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🏆 Чарты")]
    ], resize_keyboard=True)

def get_payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить 100💎 (100 XTR)", callback_data="buy_100")],
        [InlineKeyboardButton(text="Купить 500💎 (450 XTR)", callback_data="buy_500")],
        [InlineKeyboardButton(text="Купить 1000💎 (800 XTR)", callback_data="buy_1000")]
    ])

def get_language_kb() -> ReplyKeyboardMarkup:
    """Расширенная клавиатура выбора языков"""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🇷🇺 Русский"), KeyboardButton(text="🇺🇸 Английский"), KeyboardButton(text="🇪🇸 Испанский")],
        [KeyboardButton(text="🇫🇷 Французский"), KeyboardButton(text="🇩🇪 Немецкий"), KeyboardButton(text="🇮🇹 Итальянский")],
        [KeyboardButton(text="🤖 На усмотрение ИИ"), KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)

def get_lyrics_mode_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🤖 Сгенерировать ИИ"), KeyboardButton(text="✍️ Напишу сам")],
        [KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)

def get_lyrics_confirm_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✅ Текст супер, дальше!")],
        [KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)

def get_confirm_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✅ Всё верно, создаём!")],
        [KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)

# ==========================================
# 2. НОВЫЕ INLINE-КЛАВИАТУРЫ (Сетка "Сонграйтера")
# ==========================================

MAIN_GENRES = [
    ("🎤 Поп", "genre_pop"), ("🎸 Рок", "genre_rock"),
    ("🎷 Джаз", "genre_jazz"), ("🎹 Блюз", "genre_blues"),
    ("🎧 Хип-хоп / Рэп", "genre_hiphop"), ("🎛 Электронная", "genre_electronic"),
    ("🎻 Классическая", "genre_classical"), ("🪩 R&B / Соул", "genre_rnb"),
    ("🌴 Регги", "genre_reggae"), ("🤠 Кантри", "genre_country"),
    ("⚡ Метал", "genre_metal"), ("🪗 Фолк / Этника", "genre_folk"),
    ("🌶 Латино", "genre_latino"), ("🛹 Панк", "genre_punk"),
    ("🕺 Фанк / Диско", "genre_funk"), ("🏕 Шансон", "genre_chanson")
]

SUBGENRES_DICT = {
    "genre_pop": [("🕺 Дэнс-поп", "sub_pop_dance"), ("🎹 Синти-поп", "sub_pop_synth"), ("🎸 Поп-рок", "sub_pop_rock"), ("✨ Инди-поп", "sub_pop_indie"), ("🌟 K-pop", "sub_pop_kpop"), ("🪩 Ретро 80-х", "sub_pop_retro"), ("⚡ Электро-поп", "sub_pop_electro"), ("🎸 Акустический поп", "sub_pop_acoustic")],
    "genre_rock": [("🎸 Хард-рок", "sub_rock_hard"), ("🤘 Альт-рок", "sub_rock_alt"), ("✨ Инди-рок", "sub_rock_indie"), ("👑 Классик-рок", "sub_rock_classic"), ("🖤 Гранж", "sub_rock_grunge"), ("🌌 Пост-рок", "sub_rock_post"), ("🛹 Поп-панк", "sub_rock_poppunk"), ("🌀 Психоделика", "sub_rock_psych")],
    "genre_jazz": [("🎺 Свинг", "sub_jazz_swing"), ("🎷 Бибоп", "sub_jazz_bebop"), ("☕ Кул-джаз", "sub_jazz_cool"), ("🥂 Смус-джаз", "sub_jazz_smooth"), ("🎸 Джаз-фьюжн", "sub_jazz_fusion"), ("🌑 Дарк-джаз", "sub_jazz_dark"), ("🌴 Босса-нова", "sub_jazz_bossa"), ("🧪 Эйсид-джаз", "sub_jazz_acid")],
    "genre_blues": [("🔥 Классика", "sub_blues_classic"), ("🎵 Блюз-рок", "sub_blues_rock"), ("✨ Дельта-блюз", "sub_blues_delta"), ("⚡ Электро-блюз", "sub_blues_electric"), ("⭐ Кантри-блюз", "sub_blues_country"), ("🐊 Свамп-блюз", "sub_blues_swamp"), ("🎶 Модерн-блюз", "sub_blues_modern"), ("🎧 Соул-блюз", "sub_blues_soul")],
    "genre_hiphop": [("📼 Олдскул", "sub_hiphop_oldschool"), ("🔥 Трэп", "sub_hiphop_trap"), ("🔪 Дрилл", "sub_hiphop_drill"), ("☕ Lo-fi Hip-Hop", "sub_hiphop_lofi"), ("☁️ Клауд-рэп", "sub_hiphop_cloud"), ("🤘 Альт-рэп", "sub_hiphop_alt"), ("🗣 Мамбл-рэп", "sub_hiphop_mumble"), ("🌴 G-Funk", "sub_hiphop_gfunk")],
    "genre_electronic": [("🏠 Хаус", "sub_elec_house"), ("⚙️ Техно", "sub_elec_techno"), ("🌌 Транс", "sub_elec_trance"), ("🔊 Дабстеп", "sub_elec_dubstep"), ("🥁 Drum & Bass", "sub_elec_dnb"), ("🌃 Синтвейв", "sub_elec_synthwave"), ("☁️ Эмбиент", "sub_elec_ambient"), ("☕ Чиллаут", "sub_elec_chillout")],
    "genre_classical": [("🎻 Барокко", "sub_class_baroque"), ("🌹 Романтизм", "sub_class_romantic"), ("🎺 Симфония", "sub_class_symphonic"), ("🎹 Камерная", "sub_class_chamber"), ("🏛 Неоклассика", "sub_class_neo"), ("🎭 Опера", "sub_class_opera"), ("🎼 Соло фортепиано", "sub_class_piano"), ("🎬 Кинематографичная", "sub_class_epic")],
    "genre_rnb": [("📀 Классик R&B", "sub_rnb_classic"), ("📱 Модерн R&B", "sub_rnb_modern"), ("✨ Нео-соул", "sub_rnb_neosoul"), ("⛪ Госпел", "sub_rnb_gospel"), ("☕ Смус-соул", "sub_rnb_smooth"), ("🤘 Альтернативный R&B", "sub_rnb_alt"), ("🕺 Фанк-соул", "sub_rnb_funk"), ("🎸 Блюз-соул", "sub_rnb_bluessoul")],
    "genre_reggae": [("🌴 Рутс-регги", "sub_reggae_roots"), ("🔥 Дансхолл", "sub_reggae_dancehall"), ("🎛 Даб", "sub_reggae_dub"), ("🎺 Ска", "sub_reggae_ska"), ("💃 Реггетон", "sub_reggae_reggaeton"), ("🎤 Раггамаффин", "sub_reggae_ragga")],
    "genre_country": [("🤠 Традиционное", "sub_country_trad"), ("🎸 Кантри-поп", "sub_country_pop"), ("🤘 Кантри-рок", "sub_country_rock"), ("🪕 Блюграсс", "sub_country_bluegrass"), ("🍻 Хонки-тонк", "sub_country_honky"), ("🏍 Аутло-кантри", "sub_country_outlaw")],
    "genre_metal": [("🤘 Хеви-метал", "sub_metal_heavy"), ("⚡ Трэш-метал", "sub_metal_thrash"), ("💀 Дэт-метал", "sub_metal_death"), ("🌑 Блэк-метал", "sub_metal_black"), ("🎻 Симфоник-метал", "sub_metal_symphonic"), ("⚔️ Пауэр-метал", "sub_metal_power"), ("🧢 Ню-метал", "sub_metal_nu"), ("🪗 Фолк-метал", "sub_metal_folk")],
    "genre_folk": [("🎸 Инди-фолк", "sub_folk_indie"), ("🍀 Кельтский фолк", "sub_folk_celtic"), ("🌾 Славянский фолк", "sub_folk_slavic"), ("🏔 Скандинавская", "sub_folk_nordic"), ("⚡ Фолк-рок", "sub_folk_rock"), ("🌑 Дарк-фолк", "sub_folk_dark")],
    "genre_latino": [("💃 Сальса", "sub_latino_salsa"), ("🌹 Бачата", "sub_latino_bachata"), ("🕺 Меренге", "sub_latino_merengue"), ("🔥 Реггетон", "sub_latino_reggaeton"), ("🌴 Босса-нова", "sub_latino_bossa"), ("🎸 Латин-поп", "sub_latino_pop")],
    "genre_punk": [("⚡ Панк-рок", "sub_punk_rock"), ("🛹 Поп-панк", "sub_punk_pop"), ("😤 Хардкор", "sub_punk_hardcore"), ("🌑 Пост-панк", "sub_punk_post"), ("🤘 Скейт-панк", "sub_punk_skate"), ("🦇 Хоррор-панк", "sub_punk_horror")],
    "genre_funk": [("🕺 Классический фанк", "sub_funk_classic"), ("🪩 Диско 70-х", "sub_funk_disco"), ("🌴 G-Funk", "sub_funk_gfunk"), ("🎹 Синти-фанк", "sub_funk_synth"), ("✨ Ню-диско", "sub_funk_nudisco"), ("🎸 Фанк-рок", "sub_funk_rock")],
    "genre_chanson": [("🏙 Городской романс", "sub_chanson_urban"), ("⛺ Авторская (бард)", "sub_chanson_bard"), ("🇫🇷 Французский", "sub_chanson_french"), ("🎤 Эстрадный шансон", "sub_chanson_pop"), ("🚬 Блатной", "sub_chanson_blatnoy"), ("🌹 Лирический", "sub_chanson_lyrical")]
}

def get_genres_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for name, callback in MAIN_GENRES:
        builder.button(text=name, callback_data=callback)
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔀 Смешать 2 стиля", callback_data="genre_mix"))
    builder.row(InlineKeyboardButton(text="🪄 Свой стиль (промпт)", callback_data="genre_custom"))
    builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel_creation"))
    return builder.as_markup()

def get_mix_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for name, callback in MAIN_GENRES:
        mix_callback = callback.replace("genre_", "mix_")
        builder.button(text=name, callback_data=mix_callback)
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад к жанрам", callback_data="back_to_genres"))
    return builder.as_markup()

def get_subgenres_keyboard(genre_callback: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    subgenres = SUBGENRES_DICT.get(genre_callback, [])
    if subgenres:
        for name, callback in subgenres:
            builder.button(text=name, callback_data=callback)
        builder.adjust(2)
    else:
        builder.button(text="✅ Выбрать этот жанр", callback_data=f"final_{genre_callback}")
        builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад к жанрам", callback_data="back_to_genres"))
    return builder.as_markup()

def get_vocals_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    vocals = [
        ("👨 Мужской", "vocal_male"), ("👩 Женский", "vocal_female"),
        ("🗣 Хриплый / Рок", "vocal_raspy"), ("🎙 Мягкий / Смус", "vocal_smooth"),
        ("🚀 Мощный (Belting)", "vocal_powerful"), ("🤫 Шёпот / ASMR", "vocal_whisper"),
        ("🎤 Рэп-читка", "vocal_rap"), ("👹 Экстрим / Гроул", "vocal_growl"),
        ("🎭 Оперный", "vocal_opera"), ("🤖 Автотюн / Вокодер", "vocal_vocoder"),
        ("👩‍❤️‍👨 Дуэт (М+Ж)", "vocal_duet"), ("⛪ Эпичный хор", "vocal_choir"),
        ("🎹 Инструментал", "vocal_instrumental"), ("🤖 На усмотрение ИИ", "vocal_ai")
    ]
    for name, callback in vocals:
        builder.button(text=name, callback_data=callback)
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="✅ Пропустить", callback_data="vocal_skip"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад к жанрам", callback_data="back_to_genres"))
    return builder.as_markup()

def get_mood_tempo_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    moods = [
        ("🔥 Энергично / Качает", "mood_energetic"), ("🌧 Грустно / Медленно", "mood_sad"),
        ("🕺 Танцевальный грув", "mood_dance"), ("🌑 Мрачно / Тяжело", "mood_dark"),
        ("☕ Чилл / Расслабленно", "mood_chill"), ("🌌 Эпично / Масштабно", "mood_epic")
    ]
    for name, callback in moods:
        builder.button(text=name, callback_data=callback)
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🤖 Умный ИИ (Анализ текста)", callback_data="mood_ai"))
    builder.row(InlineKeyboardButton(text="✅ Пропустить", callback_data="mood_skip"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад к вокалу", callback_data="back_to_vocals"))
    return builder.as_markup()

def get_instruments_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    instruments = [
        ("🎸 Акустика", "inst_acoustic"), ("⚡ Электрогитара", "inst_electric"),
        ("🎹 Пианино", "inst_piano"), ("🥁 Ударные и бас", "inst_drums_bass"),
        ("🎻 Оркестр", "inst_orchestra"), ("🪗 Баян / Народные", "inst_folk")
    ]
    for name, callback in instruments:
        builder.button(text=name, callback_data=callback)
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🤖 На усмотрение ИИ", callback_data="inst_ai"))
    builder.row(InlineKeyboardButton(text="✅ Сгенерировать промпт!", callback_data="inst_generate"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад к настроению", callback_data="back_to_mood"))
    return builder.as_markup()