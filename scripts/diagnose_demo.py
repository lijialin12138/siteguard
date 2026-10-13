import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai


async def main():
    report_all_ok = {
        "url": "https://demo-normal.test",
        "final_url": "https://demo-normal.test",
        "ok": True,
        "status_code": 200,
        "response_ms": 210,
        "ssl_days_left": 90,
        "title": "正常演示站点",
        "description": "站点运行一切正常",
        "h1_count": 1,
        "images_total": 6,
        "images_without_alt": 0,
        "broken_links": [],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [],
        "error": None,
        "scanned_at": "2026-10-13 14:30:00"
    }

    report_broken_link = {
        "url": "https://demo-broken.test",
        "final_url": "https://demo-broken.test",
        "ok": True,
        "status_code": 200,
        "response_ms": 240,
        "ssl_days_left": 70,
        "title": "存在死链的站点",
        "description": "",
        "h1_count": 1,
        "images_total": 5,
        "images_without_alt": 1,
        "broken_links": [{"url": "https://demo-broken.test/old-page", "status": 404}],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [
            {
                "level": "P1",
                "category": "broken_link",
                "message": "发现1个失效链接（HTTP 404/410，资源确实不存在），例如 https://demo-broken.test/old-page"
            }
        ],
        "error": None,
        "scanned_at": "2026-10-13 14:31:00"
    }

    report_ssl_expire_soon = {
        "url": "https://demo-ssl.test",
        "final_url": "https://demo-ssl.test",
        "ok": True,
        "status_code": 200,
        "response_ms": 195,
        "ssl_days_left": 3,
        "title": "证书即将过期站点",
        "description": "",
        "h1_count": 1,
        "images_total": 4,
        "images_without_alt": 0,
        "broken_links": [],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [
            {
                "level": "P1",
                "category": "ssl",
                "message": "SSL 证书仅剩 3 天到期"
            }
        ],
        "error": None,
        "scanned_at": "2026-10-13 14:32:00"
    }

    print("=====用例①：全部正常=====")
    res1 = await ai.diagnose(report_all_ok)
    print(res1)

    print("\n=====用例②：P1失效链接=====")
    res2 = await ai.diagnose(report_broken_link)
    print(res2)

    print("\n=====用例③：SSL证书3天内过期=====")
    res3 = await ai.diagnose(report_ssl_expire_soon)
    print(res3)


if __name__ == "__main__":
    asyncio.run(main())
