"""D5 验收：同一份报告分别走内置 mock 诊断与真实华为云 MaaS，对比 patch 质量。

用法（项目根目录，MAAS_MODE=off 时 real 走真模型）：
    python scripts/real_vs_mock_compare.py

输出：每个用例打印 MOCK / REAL 两段 JSON，便于人工对比与写脱敏样例。
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from app import ai  # noqa: E402

# 与 diagnose_demo.py 对齐的三套样例报告（url 均为 demo.test，无真实 PII）
REPORTS = {
    "用例0_全部正常": {
        "url": "https://demo.test",
        "final_url": "https://demo.test",
        "status_code": 200,
        "response_ms": 220,
        "ssl_days_left": 60,
        "description": "",
        "h1_count": 1,
        "images_total": 4,
        "images_without_alt": 0,
        "broken_links": [],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [],
        "error": None,
        "scanned_at": "2026-10-13 14:32:00",
    },
    "用例1_P1失效链接": {
        "url": "https://demo.test",
        "final_url": "https://demo.test",
        "status_code": 200,
        "response_ms": 250,
        "ssl_days_left": 60,
        "description": "",
        "h1_count": 1,
        "images_total": 4,
        "images_without_alt": 0,
        "broken_links": [{"url": "https://demo.test/404"}],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [{"level": "P1", "category": "broken_link", "message": "存在P1级别失效链接"}],
        "error": None,
        "scanned_at": "2026-10-13 14:32:00",
    },
    "用例2_SSL证书3天内过期": {
        "url": "https://demo.test",
        "final_url": "https://demo.test",
        "status_code": 200,
        "response_ms": 240,
        "ssl_days_left": 3,
        "description": "",
        "h1_count": 1,
        "images_total": 4,
        "images_without_alt": 0,
        "broken_links": [],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [{"level": "P1", "category": "ssl", "message": "SSL证书仅剩 3 天到期"}],
        "error": None,
        "scanned_at": "2026-10-13 14:32:00",
    },
}

# scanner.build_issues 认可的 11 个 category（用于校验真模型输出是否越界）
VALID_CATEGORIES = {
    "availability", "server_error", "client_error", "redirect", "performance",
    "ssl", "broken_link", "link_server_error", "link_unverified", "seo",
    "accessibility",
}


def _check(real: dict) -> dict:
    problems = []
    patches = real.get("patches") or []
    cats = [p.get("category") for p in patches]
    for c in cats:
        if c not in VALID_CATEGORIES:
            problems.append(f"category 越界: {c}")
    for p in patches:
        if not (p.get("code") or "").strip():
            problems.append(f"code 为空: {p.get('category')}")
        if p.get("category") == "link_unverified" and "删除" in (p.get("code") or ""):
            problems.append("link_unverified 含删除命令（违反铁律）")
    return {"patch_count": len(patches), "categories": cats, "problems": problems}


async def main() -> int:
    if ai.mock_active():
        print("[!] 当前 MAAS_MODE=on/mock，real 不会调真模型。请设 MAAS_MODE=off 再跑。")
        return 1
    if not ai.maas_ready():
        print("[x] MaaS 未配置。")
        return 1

    out = {}
    for name, rep in REPORTS.items():
        mock = ai._mock_diagnose(rep)
        real = await ai.diagnose(rep)
        chk = _check(real)
        out[name] = {"mock": mock, "real": real, "check": chk}
        print("=" * 60)
        print(f"{name}  |  REAL patches={chk['patch_count']} cats={chk['categories']} "
              f"问题={chk['problems'] or '无'}")
        print("-" * 60)
        print("--- MOCK ---")
        print(json.dumps(mock, ensure_ascii=False, indent=2))
        print("--- REAL ---")
        print(json.dumps(real, ensure_ascii=False, indent=2))

    # 干净落盘（UTF-8），供写脱敏样例文档使用
    Path(__file__).with_name("compare_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n[v] 已写入 compare_result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
