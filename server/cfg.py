
import os
from dotenv import load_dotenv

# load .env file (once, at import time)
load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_KEY", "")
TG_SESSION_NAME = os.getenv("TG_SESSION_NAME", "unknown")
TG_API_ID = int(os.getenv("TG_API_ID", 0))
TG_API_HASH = os.getenv("TG_API_HASH", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")
ADMIN_PW = os.getenv("ADMIN_PW", "admin123")

MAX_EXCEPTIONS_FOR_AI_SIGNAL_EXTRACTION = 3

PRODUCTION = False
