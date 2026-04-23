from aiogram.fsm.state import State, StatesGroup

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
    from aiogram.fsm.state import State, StatesGroup

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
    waiting_for_mood = State() # <--- НАШ НОВЫЙ ШАГ (Настроение)
    waiting_for_instruments = State()
    waiting_for_style_confirm = State()