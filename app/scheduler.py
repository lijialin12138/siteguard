"""定时巡检调度。

用 APScheduler 的 AsyncIOScheduler，直接跑在 FastAPI 的事件循环里，
不需要额外装 Redis / Celery —— 一周内出原型，别给自己加复杂度。
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import service
from .config import SCAN_INTERVAL_MINUTES

logger = logging.getLogger("siteguard.scheduler")

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

JOB_ID = "scan_all_sites"


async def _job() -> None:
    logger.info("定时巡检开始")
    results = await service.run_scan_all(deep=True)
    logger.info("定时巡检结束，共处理 %d 个站点", len(results))


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(minutes=SCAN_INTERVAL_MINUTES),
        id=JOB_ID,
        name="全站巡检",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("调度器已启动，每 %d 分钟巡检一次", SCAN_INTERVAL_MINUTES)


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def job_info() -> dict:
    job = scheduler.get_job(JOB_ID)
    return {
        "running": scheduler.running,
        "interval_minutes": SCAN_INTERVAL_MINUTES,
        "next_run_time": str(job.next_run_time) if job else None,
    }


async def trigger_now() -> list[dict]:
    """手动立即跑一轮（不等待下一次定时）。"""
    return await service.run_scan_all(deep=True)
