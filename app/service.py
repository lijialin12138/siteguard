"""业务编排层。

把「巡检 → 落库」这条链路抽出来，让 API 手动触发和定时任务共用同一份逻辑，
避免两处各写一遍导致行为不一致。
"""

import json
import logging
from typing import Any

from . import scanner
from .db import get_conn, now, rows_to_dicts

logger = logging.getLogger("siteguard.service")


# ---------------------------- 站点管理 ----------------------------

def add_site(name: str, url: str) -> dict:
    url = scanner.normalize_url(url)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sites (name, url, enabled, created_at) VALUES (?, ?, 1, ?)",
            (name.strip() or url, url, now()),
        )
        site_id = cur.lastrowid
    return get_site(site_id)  # type: ignore[return-value]


def list_sites() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM sites ORDER BY id").fetchall()
    return rows_to_dicts(rows)


def get_site(site_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    return dict(row) if row else None


def delete_site(site_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))
    return cur.rowcount > 0


# ---------------------------- 巡检与落库 ----------------------------

def save_scan(site_id: int, report: dict) -> int:
    """把一份体检报告和它的 issues 写进数据库，返回 scan_id。"""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO scans (
                site_id, status_code, response_ms, is_ok, ssl_days_left,
                title, broken_links, error, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                site_id,
                report.get("status_code"),
                report.get("response_ms"),
                1 if report.get("ok") else 0,
                report.get("ssl_days_left"),
                report.get("title"),
                len(report.get("broken_links") or []),
                report.get("error"),
                json.dumps(report, ensure_ascii=False),
                now(),
            ),
        )
        scan_id = cur.lastrowid
        for issue in report.get("issues") or []:
            conn.execute(
                "INSERT INTO issues (scan_id, level, category, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (scan_id, issue.get("level", "P3"), issue.get("category", "other"), issue.get("message", ""), now()),
            )
    return scan_id  # type: ignore[return-value]


async def run_scan_for_site(site_id: int, deep: bool = True) -> dict:
    """巡检单个站点并落库。返回 {site, report, scan_id}。"""
    site = get_site(site_id)
    if not site:
        raise ValueError(f"站点不存在: id={site_id}")

    report = await scanner.scan_site(site["url"], deep=deep)
    scan_id = save_scan(site_id, report)
    logger.info(
        "巡检完成 site=%s scan_id=%s ok=%s issues=%d",
        site["url"], scan_id, report.get("ok"), len(report.get("issues") or []),
    )
    return {"site": site, "report": report, "scan_id": scan_id}


async def run_scan_all(deep: bool = True) -> list[dict]:
    """巡检所有启用的站点。定时任务调用的就是它。"""
    results: list[dict[str, Any]] = []
    for site in list_sites():
        if not site.get("enabled"):
            continue
        try:
            results.append(await run_scan_for_site(site["id"], deep=deep))
        except Exception as exc:  # 单个站点失败不影响其他站点
            logger.warning("巡检失败 site_id=%s: %s", site["id"], exc)
            results.append({"site": site, "error": str(exc)})
    return results


# ---------------------------- 查询 ----------------------------

def list_scans(site_id: int | None = None, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        if site_id:
            rows = conn.execute(
                "SELECT * FROM scans WHERE site_id = ? ORDER BY id DESC LIMIT ?",
                (site_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return rows_to_dicts(rows)


def get_scan(scan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        if not row:
            return None
        scan = dict(row)
        issues = conn.execute(
            "SELECT * FROM issues WHERE scan_id = ? ORDER BY id", (scan_id,)
        ).fetchall()
    scan["issues"] = rows_to_dicts(issues)
    if scan.get("raw_json"):
        scan["report"] = json.loads(scan["raw_json"])
    scan.pop("raw_json", None)
    return scan


def latest_scan_per_site() -> list[dict]:
    """每个站点最近一次巡检结果 —— 给 Dashboard 用。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.id AS site_id, s.name, s.url,
                   sc.id AS scan_id, sc.status_code, sc.response_ms, sc.is_ok,
                   sc.ssl_days_left, sc.broken_links, sc.created_at
            FROM sites s
            LEFT JOIN scans sc ON sc.id = (
                SELECT id FROM scans WHERE site_id = s.id ORDER BY id DESC LIMIT 1
            )
            ORDER BY s.id
            """
        ).fetchall()
    return rows_to_dicts(rows)


def issue_levels(scan_id: int) -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT level, COUNT(*) AS c FROM issues WHERE scan_id = ? GROUP BY level",
            (scan_id,),
        ).fetchall()
    return {r["level"]: r["c"] for r in rows}


# ---------------------------- AI 诊断 ----------------------------

def save_diagnosis(scan_id: int, result: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO diagnoses (scan_id, model, result_json, created_at) VALUES (?, ?, ?, ?)",
            (
                scan_id,
                (result.get("_meta") or {}).get("model"),
                json.dumps(result, ensure_ascii=False),
                now(),
            ),
        )
        diagnosis_id = cur.lastrowid
    return diagnosis_id  # type: ignore[return-value]


def get_latest_diagnosis(scan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM diagnoses WHERE scan_id = ? ORDER BY id DESC LIMIT 1",
            (scan_id,),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["result"] = json.loads(data.pop("result_json"))
    return data


async def diagnose_scan(scan_id: int) -> dict:
    """对某次巡检结果做 AI 诊断，并把结论存下来。"""
    from . import ai  # 延迟导入，避免没配 MaaS 时启动就报错

    scan = get_scan(scan_id)
    if not scan:
        raise ValueError(f"巡检记录不存在: id={scan_id}")
    report = scan.get("report") or {}
    result = await ai.diagnose(report)
    diagnosis_id = save_diagnosis(scan_id, result)
    return {"scan_id": scan_id, "diagnosis_id": diagnosis_id, "result": result}
