import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GIGACHAT_KEY = os.getenv("GIGACHAT_KEY", "")
PROXY_KEY = os.getenv("PROXY_KEY", "")
MUSIC_KEY = os.getenv("MUSIC_KEY", "")
EVOLINK_BASE_URL = os.getenv("EVOLINK_BASE_URL", "https://api.sunoaiapi.com")
REPLICATE_TOKEN = os.getenv("REPLICATE_TOKEN", "")
GOOGLE_SHEETS_URL = os.getenv("GOOGLE_SHEETS_URL", "")

ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

COST_QUICK = 10
COST_PRO = 40
COST_COVER = 15
MAX_FILE_SIZE = 10 * 1024 * 1024

DB_PATH = "database.sqlite"