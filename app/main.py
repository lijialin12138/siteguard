"""FastAPI 入口。

启动：uvicorn app.main:app --reload
接口文档：http://127.0.0.1:8000/docs
控制台：http://127.0.0.1:8000/
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, scheduler, service
from .config import API_TOKEN, MAAS_MODEL, maas_mode, maas_ready, mock_active
from .db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("siteguard")

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ---------------------------- API 鉴权 ----------------------------
# 仅对 /api/* 生效；本地未设 API_TOKEN 时全部放行（不挡联调）。
# 部署前在 .env 设 API_TOKEN 后，所有 /api 接口强制校验
#   Authorization: Bearer <API_TOKEN>
# 否则返回 401，防止站点被任意删除、MaaS 额度被外人烧。
async def require_token(request: Request) -> None:
    expected = API_TOKEN
    if not expected:
        return  # 本地放行
    if not request.url.path.startswith("/api/"):
        return  # 页面 / 文档 / 静态资源不拦截
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少或格式错误的 Authorization 头")
    if auth[len("Bearer "):].strip() != expected:
        raise HTTPException(status_code=401, detail="token 无效")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    scheduler.start_scheduler()
    logger.info("SiteGuard 启动完成")
    yield
    scheduler.shutdown_scheduler()


app = FastAPI(
    title="SiteGuard · AI 自动化企业网站维护助手",
    description="自动巡检企业网站，用 AI 定位问题根因并给出修复方案。",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(require_token)],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------- 请求模型 ----------------------------

class SiteIn(BaseModel):
    name: str = Field("", description="站点名称，可留空")
    url: str = Field(..., description="站点地址，可省略协议头", examples=["www.example.com"])


# ---------------------------- 基础 ----------------------------

@app.get("/", include_in_schema=False)
async def console():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["基础"])
async def health():
    return {"status": "ok", "service": "siteguard", "version": app.version}


@app.get("/api/status", tags=["基础"])
async def status():
    return {
        "maas_configured": maas_ready(),
        "maas_model": MAAS_MODEL,
        "ai_mode": maas_mode(),
        "mock_active": mock_active(),
        "scheduler": scheduler.job_info(),
    }


@app.post("/api/status/maas-ping", tags=["基础"])
async def maas_ping():
    """连通性自检：确认华为云 MaaS 是否真的调得通。"""
    try:
        reply = await ai.ping()
    except RuntimeError:
        raise HTTPException(400, "MaaS 尚未配置，请检查项目根目录下的 .env 文件")
    except Exception as exc:
        raise HTTPException(502, f"调用 MaaS 失败：{type(exc).__name__}: {exc}")
    return {
        "ok": True,
        "model": "内置模拟诊断" if mock_active() else MAAS_MODEL,
        "mock": mock_active(),
        "reply": reply,
    }


# ---------------------------- 站点 ----------------------------

@app.get("/api/sites", tags=["站点"])
async def api_list_sites():
    return service.list_sites()


@app.post("/api/sites", tags=["站点"], status_code=201)
async def api_add_site(payload: SiteIn):
    try:
        return service.add_site(payload.name, payload.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(409, "该站点已存在")
        raise HTTPException(500, str(exc))


@app.delete("/api/sites/{site_id}", tags=["站点"])
async def api_delete_site(site_id: int):
    if not service.delete_site(site_id):
        raise HTTPException(404, "站点不存在")
    return {"deleted": site_id}


@app.get("/api/overview", tags=["站点"])
async def api_overview():
    """Dashboard 首页数据：每个站点最近一次巡检结果。"""
    return service.latest_scan_per_site()


# ---------------------------- 巡检 ----------------------------

@app.post("/api/sites/{site_id}/scan", tags=["巡检"])
async def api_scan_site(site_id: int, deep: bool = True):
    """手动巡检单个站点。deep=false 时跳过死链扫描，速度快很多。"""
    try:
        result = await service.run_scan_for_site(site_id, deep=deep)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {
        "scan_id": result["scan_id"],
        "site": result["site"],
        "report": result["report"],
    }


@app.post("/api/scan/all", tags=["巡检"])
async def api_scan_all(deep: bool = True):
    """立即巡检全部站点。"""
    results = await service.run_scan_all(deep=deep)
    return {
        "count": len(results),
        "scans": [
            {"site_id": r["site"]["id"], "scan_id": r.get("scan_id"), "error": r.get("error")}
            for r in results
        ],
    }


@app.get("/api/scans", tags=["巡检"])
async def api_list_scans(site_id: int | None = None, limit: int = 50):
    return service.list_scans(site_id=site_id, limit=limit)


@app.get("/api/scans/{scan_id}", tags=["巡检"])
async def api_get_scan(scan_id: int):
    scan = service.get_scan(scan_id)
    if not scan:
        raise HTTPException(404, "巡检记录不存在")
    return scan


# ---------------------------- AI 诊断 ----------------------------

@app.post("/api/scans/{scan_id}/diagnose", tags=["AI 诊断"])
async def api_diagnose(scan_id: int):
    """对某次巡检结果做 AI 诊断，给出根因与修复建议。"""
    try:
        return await service.diagnose_scan(scan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except RuntimeError:
        raise HTTPException(400, "MaaS 尚未配置，请检查项目根目录下的 .env 文件")
    except Exception as exc:
        raise HTTPException(502, f"AI 诊断失败：{type(exc).__name__}: {exc}")


@app.get("/api/scans/{scan_id}/report", tags=["AI 诊断"])
async def api_daily_report(scan_id: int):
    """生成一份可直接发给团队的每日运维简报（Markdown）。"""
    scan = service.get_scan(scan_id)
    if not scan:
        raise HTTPException(404, "巡检记录不存在")
    diagnosis = service.get_latest_diagnosis(scan_id)
    if not diagnosis:
        raise HTTPException(400, "请先调用 /diagnose 生成 AI 诊断结论")
    try:
        markdown = await ai.write_daily_report(scan.get("report") or {}, diagnosis["result"])
    except RuntimeError:
        raise HTTPException(400, "MaaS 尚未配置，请检查项目根目录下的 .env 文件")
    return {"scan_id": scan_id, "markdown": markdown}
