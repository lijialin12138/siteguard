"""第一天用：验证华为云 MaaS 到底调不调得通。

用法（在项目根目录下）：
    python scripts/smoke_maas.py

看到模型回话，就说明 .env 配对了，可以继续往下做。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai  # noqa: E402
from app.config import (  # noqa: E402
    MAAS_API_KEY,
    MAAS_BASE_URL,
    MAAS_MODEL,
    maas_mode,
    maas_ready,
    mock_active,
)


def main() -> int:
    print("=" * 58)
    print("  SiteGuard · 华为云 MaaS 连通性自检")
    print("=" * 58)
    key = MAAS_API_KEY.strip()
    shown = f"{key[:4]}...{key[-4:]}（共 {len(key)} 位）" if key else "未配置"
    print(f"  模型      : {MAAS_MODEL}")
    print(f"  接口地址  : {MAAS_BASE_URL}")
    print(f"  密钥      : {shown}")
    print(f"  运行模式  : {maas_mode()}" + ("（当前走内置模拟诊断）" if mock_active() else "（当前走真实大模型）"))
    if key:
        print("  比对提示  : 上面的密钥指纹，应与 MaaS 控制台『API Key 管理』列表里")
        print("              这把 Key 显示的前四位 / 后四位一致；不一致就是贴错了。")
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
        text = f"{type(exc).__name__}: {exc}"
        print(f"\n[×] 调用失败：{text}\n")
        if "81003" in text:
            print("  [81003] 鉴权信息解析失败 —— 说明这颗 API Key 不被认可。按顺序排查：")
            print("    1) 这把 Key 是不是在「西南-贵阳一」控制台里、通过")
            print("       『管理与统计 > API Key 管理』创建的？（Key 是区域级的，跨区域一定失败）")
            print("    2) 刚创建的 Key 需要几分钟才生效，等 3~5 分钟再跑一次。")
            print("    3) 确认贴进 .env 的是弹窗里那串『密钥』本身，")
            print("       而不是 Key 的『标签』或『描述』（那两个是给自己看的名字）。")
            print("    4) 仍失败：在贵阳一把旧的删掉、新建一把，创建后立刻整串复制过来。")
        elif "81004" in text:
            print("  [81004] 尚未开通该预置服务。去 MaaS 控制台 > 在线推理 > 预置服务，")
            print(f"    把 {MAAS_MODEL} 点『开通服务』（免费开通、按量计费、不开不收费）。")
        elif "81006" in text:
            print("  [81006] 资源被冻结 —— 检查账号是否欠费或状态异常。")
        elif "81015" in text:
            print("  [81015] 被 API Key 的 IP / 模型白名单拦下 —— 去『API Key 管理』")
            print("    把这把 Key 的『权限范围』改成『全部』，或把模型加进白名单。")
        else:
            print("  常见原因：")
            print("    - 模型名要与控制台『调用说明』里的 model 值完全一致（全小写）")
            print("    - 接口地址末尾只到 /v1（本项目用 OpenAI SDK，会自动补 /chat/completions）")
            print("    - 网络不通 / 代理拦截 / DNS 异常")
        return 1

    print(f"\n[√] 成功！模型回复：{reply}")
    print("\n接下来：uvicorn app.main:app --reload")
    print("然后打开 http://127.0.0.1:8000/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
