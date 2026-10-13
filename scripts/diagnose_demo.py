import asyncio
import sys
from pathlib import Path
# 把项目根目录加入python搜索路径
sys.path.append(str(Path(__file__).parent.parent))

from app import ai

async def main():
    report_all_ok = {
        "description": "",
        "h1_count": 1,
        "images_total": 4,
        "images_without_alt": 0,
        "broken_links": [],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [
        ],
        "error": None,
        "scanned_at": "2026-10-13 14:32:00"
    }

    report_broken_link = {
        "description": "",
        "h1_count": 1,
        "images_total": 4,
        "images_without_alt": 0,
        "broken_links": ["https://demo.test/404"],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [
            {"level": "P1", "category": "broken_link", "message": "存在P1级别失效链接"}
        ],
        "error": None,
        "scanned_at": "2026-10-13 14:32:00"
    }

    report_ssl_expire_soon = {
        "description": "",
        "h1_count": 1,
        "images_total": 4,
        "images_without_alt": 0,
        "broken_links": [],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [
            {"level": "P1", "category": "ssl", "message": "SSL证书仅剩 3 天到期"}
        ],
        "error": None,
        "scanned_at": "2026-10-13 14:32:00"
    }

    print("====用例0: 全部正常====")
    res1 = await ai.diagnose(report_all_ok)
    print(res1)

    print("\n====用例1: P1失效链接====")
    res2 = await ai.diagnose(report_broken_link)
    print(res2)

    print("\n====用例2: SSL证书3天内过期====")
    res3 = await ai.diagnose(report_ssl_expire_soon)
    print(res3)

if __name__ == "__main__":
    asyncio.run(main())
