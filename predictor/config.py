"""环境变量配置"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# OpenAI（通过 Vercel 代理）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openai-proxy-plum.vercel.app/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 数据库路径（优先读环境变量，容器部署时指向挂载目录）
DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).resolve().parent.parent / "predictor.db")))

# 预测配置
COINS = ["BTCUSDT", "ETHUSDT"]
TIMEFRAMES = ["1h", "4h"]
# 最低推送置信度（1-5）
MIN_CONFIDENCE = 1
