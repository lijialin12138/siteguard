"""第一天用：验证华为云 MaaS 到底调不调得通。

用法（在项目根目录下）：
    python scripts/smoke_maas.py

看到模型回话，就说明 .env 配对了，可以继续往下做。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai  # noqa: E402
from app.config import MAAS_BASE_URL, MAAS_MODEL, maas_mode, maas_ready, mock_active  # noqa: E402


def main() -> int:
    print("=" * 58)
    print("  SiteGuard · 华为云 MaaS 连通性自检")
    print("=" * 58)
    print(f"  模型      : {MAAS_MODEL}")
    print(f"  接口地址  : {MAAS_BASE_URL}")
    print(f"  密钥      : {'已配置' if maas_ready() else '未配置'}")
    print(f"  运行模式  : {maas_mode()}" + ("（当前走内置模拟诊断）" if mock_active() else "（当前走真实大模型）"))
    print("-" * 58)

    if mock_active():
        print("\n[i] 当前是模拟模式，不调用真实模型，无需 API Key。")
        print("    想验证真实 MaaS 连通性，请先：")
        print("    1. 把 .env 里的 MAAS_API_KEY 填成真实密钥")
        print("    2. 把 MAAS_BASE_URL 换成控制台的真实地址（末尾只留到 /v1）")
        print("    3. 确认 MAAS_MODE 为 auto 或 off")
        print("\n[√] 现在就可以直接跑：uvicorn app.main:app --reload")
        print("    然后打开 http://127.0.0.1:8000/ 点「巡检」和「AI 诊断」")
        return 0

    if not maas_ready():
        print("\n[×] 还没配好。请检查：")
        print("    1. 项目根目录下有没有 .env 文件（从 .env.example 复制一份改名）")
        print("    2. MAAS_API_KEY 是否填了真实密钥")
        print("    3. MAAS_BASE_URL 是否已把『你的API地址』替换成控制台里的真实地址")
        print("    4. 地址末尾只保留到 /v1，不要带 /chat/completions")
        return 1

    import asyncio

    try:
        reply = asyncio.run(ai.ping())
    except Exception as exc:
        print(f"\n[×] 调用失败：{type(exc).__name__}: {exc}")
        print("\n常见原因：")
        print("    - 区域不对：MaaS 免费额度只在「西南-贵阳一」开放")
        print("    - 模型名不对：要和控制台『调用说明』里的模型 ID 完全一致")
        print("    - 还没在控制台『领取额度』或『开通预置服务』")
        return 1

    print(f"\n[√] 成功！模型回复：{reply}")
    print("\n接下来：uvicorn app.main:app --reload")
    print("然后打开 http://127.0.0.1:8000/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
