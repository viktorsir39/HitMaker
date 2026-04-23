import time
import asyncio

# Словарь для хранения времени последнего запроса (используется и тут, и в main.py для очистки)
USER_COOLDOWN = {}
RATE_LIMIT_SECONDS = 2

def check_rate_limit(user_id: str) -> bool:
    """Проверяет, не слишком ли часто пользователь отправляет запросы."""
    now = time.time()
    if user_id in USER_COOLDOWN and now - USER_COOLDOWN[user_id] < RATE_LIMIT_SECONDS:
        return False
    USER_COOLDOWN[user_id] = now
    return True

# Словарь для блокировок (чтобы юзер не запустил 2 генерации трека одновременно)
_user_locks = {}

def get_user_lock(user_id: str) -> asyncio.Lock:
    """Возвращает асинхронную блокировку для конкретного пользователя."""
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]

def clean_user_input(text: str, max_len: int = 1500) -> str:
    """Очищает и обрезает текст от пользователя (защита от переполнения БД)."""
    if not text:
        return ""
    return text.strip()[:max_len]