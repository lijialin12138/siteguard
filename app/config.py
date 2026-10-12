"""集中读取配置。所有可调参数都在这里，业务代码不要直接读 os.environ。"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# 加载项目根目录下的 .env（不存在也不会报错，方便第一次先跑起来）
load_dotenv(BASE_DIR / ".env")


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _get_int(key: str, default: int) -> int:
    raw = _get(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    raw = _get(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ---------- 华为云 MaaS ----------
MAAS_BASE_URL = _get("MAAS_BASE_URL", "https://你的API地址/v1")
MAAS_API_KEY = _get("MAAS_API_KEY")
MAAS_MODEL = _get("MAAS_MODEL", "DeepSeek-V3")

# ---------- 存储 ----------
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "siteguard.db"

# ---------- 巡检 ----------
SCAN_INTERVAL_MINUTES = _get_int("SCAN_INTERVAL_MINUTES", 30)
REQUEST_TIMEOUT = _get_float("REQUEST_TIMEOUT", 10.0)
MAX_LINKS_PER_PAGE = _get_int("MAX_LINKS_PER_PAGE", 50)
MAX_CONCURRENCY = _get_int("MAX_CONCURRENCY", 10)

# ---------- 状态 ----------


def maas_ready() -> bool:
    """MaaS 是否已经配置好。没配好时接口会给出明确提示，而不是抛一个看不懂的异常。"""
    return bool(MAAS_API_KEY) and "你的API地址" not in MAAS_BASE_URL
