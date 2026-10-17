import asyncio
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from app import ai

def main() -> int:
    print("=" * 60)
    print(f"密钥状态 : {'已配置' if ai.maas_ready() else '未配置'}")
    #print(f"运行模式 : {ai.maas_mode()} + {'[当前走内置模拟诊断，无需真实MaaS密钥]' if ai.mock_active() else '[当前调用真实华为云MaaS大模型]'}")
    print("=" * 60)

    if ai.mock_active():
        print("\n[i] 当前为模拟模式，直接使用内置Mock返回，不访问MaaS接口。")
    else:
        if not ai.maas_ready():
            print("\n[x] MaaS密钥未配置！请检查根目录 .env 文件 MAAS_API_KEY。")
            return 1

    async def run_cases():
        # ========== 改动点：更新3个报告，对齐scanner输出结构 ==========
        report_all_ok = {
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
            "scanned_at": "2026-10-13 14:32:00"
        }
        report_broken_link = {
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
            "scanned_at": "2026-10-13 14:32:00"
        }
        report_ssl_expire_soon = {
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
            "scanned_at": "2026-10-13 14:32:00"
        }
        # =============================================================
        print("====用例0: 全部正常====")
        res1 = await ai.diagnose(report_all_ok)
        print(res1)
        print("\n====用例1: P1失效链接====")
        res2 = await ai.diagnose(report_broken_link)
        print(res2)
        print("\n====用例2: SSL证书3天内过期====")
        res3 = await ai.diagnose(report_ssl_expire_soon)
        print(res3)

    try:
        asyncio.run(run_cases())
    except Exception as exc:
        print(f"\n[x] 执行异常: {type(exc).__name__}: {exc}")
        return 1

    print("\n[v] 全部用例执行完毕。")
    return 0


if __name__ == "__main__":
    exit(main())

