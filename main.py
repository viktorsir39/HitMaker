import asyncio
import logging
import time
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from handlers import router
from services import http_client
from utils import USER_COOLDOWN
import database as db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

# Фоновая задача: очистка старых Rate Limit записей (Фаза 2 плана)
async def cleanup_cooldowns():
    while True:
        await asyncio.sleep(3600)  # Проверяем раз в час
        now = time.time()
        # Удаляем записи старше 10 минут (600 секунд)
        to_del = [uid for uid, t in USER_COOLDOWN.items() if now - t > 600]
        for uid in to_del:
            del USER_COOLDOWN[uid]
        if to_del:
            logging.info(f"🧹 Очищено {len(to_del)} старых записей Rate Limit.")

async def main():
    # Проверка обязательных ключей (Фаза 2 плана)
    required_keys = ["BOT_TOKEN", "GIGACHAT_KEY", "PROXY_KEY", "MUSIC_KEY"]
    for key in required_keys:
        if not getattr(config, key, None):
            logging.critical(f"❌ Отсутствует обязательная переменная окружения: {key}")
            return

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Инициализация единого подключения к БД
    await db.db_instance.connect()
    
    # Запуск фоновой очистки памяти
    asyncio.create_task(cleanup_cooldowns())

    logging.info("🚀 HitMaker AI Online! (Production v4.0: Singleton & Global HTTP)")
    
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        # Корректное закрытие соединений при выключении бота
        await db.db_instance.close()
        await http_client.aclose()
        logging.info("🛑 Бот остановлен. Все соединения закрыты.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот выключен вручную.")