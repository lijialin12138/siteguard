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

# ---------- 大模型运行模式 ----------
# auto：配了真实 Key 就走真实模型；没配则自动降级为内置模拟诊断（默认，适合边开发边等 Key）
# on  ：强制使用内置模拟诊断，绝不发出网络请求（断网、录屏、演示时用）
# off ：强制走真实模型，没配好就直接报错（正式提交 / 录演示视频时建议锁死这个）
_MODE_ALIAS = {
    "mock": "on", "true": "on", "yes": "on", "1": "on",
    "real": "off", "false": "off", "no": "off", "0": "off",
}
_raw_mode = _get("MAAS_MODE", "auto").lower()
MAAS_MODE = _MODE_ALIAS.get(_raw_mode, _raw_mode)
if MAAS_MODE not in ("auto", "on", "off"):
    MAAS_MODE = "auto"


# ---------- 状态 ----------

def maas_ready() -> bool:
    """MaaS 是否已经配置好。没配好时接口会给出明确提示，而不是抛一个看不懂的异常。"""
    return bool(MAAS_API_KEY) and "你的API地址" not in MAAS_BASE_URL


def maas_mode() -> str:
    """当前运行模式：auto / on / off。"""
    return MAAS_MODE


def mock_active() -> bool:
    """当前这一次调用是否走内置模拟诊断。

    auto 模式下只要还没配好 Key 就自动走模拟，这样 Day1 拿不到 Key 也不会卡住开发。
    """
    if MAAS_MODE == "on":
        return True
    if MAAS_MODE == "off":
        return False
    return not maas_ready()
