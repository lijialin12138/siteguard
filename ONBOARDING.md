# SiteGuard · 团队上手与分工

本文件用于团队内部协作：**新成员从零到能改代码的完整路径**，以及各自的负责范围。

如果你刚拿到仓库地址，从「一、上手三件套」开始，一步一步照做即可。

---

## 一、上手三件套

每人都要做，约 1 小时。做完这三件，你就具备独立改代码的条件了。

### 1. 注册 Huawei Cloud 账号

- 网址 `huaweicloud.com`
- **必须用真实姓名**。队伍报名是队长建队、成员在线确认，**报名后不得更换队员**，填错了很麻烦。
- 不需要自己开通模型服务 —— 全队共用队长那一份 API Key。

### 2. 把项目跑起来

```bash
git clone https://gitee.com/lijialin12138/siteguard.git
cd siteguard
python -m venv .venv
```

Windows（PowerShell）：

```powershell
.\.venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt
```

macOS / Linux：

```bash
.venv/bin/python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt
```

> **镜像参数是必须的，不是可选项。** 直连 `pypi.org` 会超时；清华源近期会限流返回空包列表。
> 报 `No matching distribution found` 时，八成不是包不存在，而是源连不上。

然后配置并启动：

```powershell
copy .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

打开 <http://127.0.0.1:8000/>，加一个站点（**填真实站点，不要用 example.com**），点「巡检」，再点「AI 诊断」。

**通关标准**：看到一张带 P0–P3 分级 + 根因分析 + 处置建议的诊断卡。

顶部会有一个黄色徽标写着「**AI：模拟模式**」，**这是正常的** —— 真实模型 Key 还没到位，
当前用内置诊断逻辑跑通整条链路。等 Key 到位后把 `.env` 里的 `MAAS_MODE` 改成 `off` 即可切换。

### 3. 打通提交流程

**每人每天至少一次 commit。** 提交历史是开发过程的证据，也能证明代码确实是你们自己写的。

```bash
git config --global user.name "你的名字"
git config --global user.email "你的Gitee邮箱"
```

邮箱**必须和 Gitee 账号一致**，否则提交不归属你的账号。

一个完整的提交循环：

```bash
git pull                # 先拉，避免冲突
git add -A
git commit -m "feat: 你做了什么"
git push
```

> push 要密码时填**私人令牌**（Gitee → 设置 → 安全设置 → 私人令牌 → 生成新令牌，勾 `projects`），
> **不是登录密码** —— Gitee 已不支持用登录密码做 HTTPS 认证。

---

## 二、分工

| 角色 | 负责范围 | 主要文件 |
|---|---|---|
| **A** · 后端与巡检 | 巡检引擎、数据层、接口编排 | `app/scanner.py` `app/db.py` `app/service.py` `app/main.py` |
| **B** · AI 与提示词 | 诊断提示词、模型联调、修复闭环 | `app/ai.py` |
| **C** · 前端与交付 | 控制台、可视化、部署、演示材料 | `app/static/index.html` |

分工的原则是 **一个人一套文件**，互不重叠，避免改同一个文件时打架。

**当前进度**：角色 A 的巡检引擎与存储层已完成；角色 B 的模型通道已打通但尚未接入真实模型；
角色 C 的控制台是基础版，只有数字没有明细。

---

## 三、Day 1 任务

### 角色 C · 控制台问题明细

**目标**：让控制台从「只有数字」变成「能看到具体问题」。

**现状**：每个站点只显示「问题数 5」，但看不到这 5 条分别是什么。

**要做的**：

1. 站点卡片增加一个展开按钮（或整卡可点）
2. 点击后调 `GET /api/scans/{scan_id}` —— `scan_id` 从 `/api/overview` 的返回里拿
3. 返回结构里 `report.issues` 是问题清单，每条含 `level`（P0–P3）、`category`、`message`
4. 原地展开成列表，等级用带颜色的徽章区分，分类和消息照实显示
5. 顺手打磨三种状态：**空态**（还没加站点）、**加载态**（巡检进行中）、**错误态**（接口失败）

**约束**：只改 `app/static/index.html`。不要引入构建工具、不要装 npm 依赖，
图表库用 CDN 引入即可 —— 这个项目刻意保持「零构建」，一个人一天能改完。

**交付**：一张展开后的截图 + 一次 commit。

---

### 角色 B · 诊断知识库与调优标尺

**目标**：把 AI 诊断这一层的判断逻辑读懂、写下来，并给它建一个可复用的调优标尺。

**任务 1**：整理 `docs/diagnosis-kb.md`

读 `app/ai.py`，把其中 `_MOCK_KNOWLEDGE`（问题类别 → 根因 → 处置动作 → 操作步骤 → 修复片段）
和 `SYSTEM_PROMPT`（要求模型输出的结构）整理成一份对照表，每个问题类别一行。

这份文档将来**直接用于答辩** —— 评委一定会问「你们的 AI 到底在做什么判断」，
有这份表你就能当场答上来。

**任务 2**：写 `scripts/diagnose_demo.py`

一个不依赖 Web 服务的诊断演示脚本：构造 3 份体检报告喂给 `app.ai.diagnose()`，打印结果。

- ① 全部正常（无任何问题）
- ② 有 P1 失效链接
- ③ SSL 证书 3 天内过期

参考 `scripts/smoke_maas.py` 的写法（它已经处理好了 `sys.path` 和配置加载）。
造数据时注意：报告字段要与 `scanner.py` 里 `scan_site()` 的返回结构一致。

**这是后续调提示词的标尺** —— 改一版提示词就跑一次，对比输出有没有变好。

**任务 3**：提示词改进提案

基于上面两步的发现，在 `docs/diagnosis-kb.md` 末尾加一节「提示词改进提案」，
给出 3 条具体建议，每条写清 **现状 → 问题 → 改法**。不要写「建议更详细」这种空话。

**约束**：不要修改 `app/ai.py` 里已有的逻辑 —— 这一轮只做「读懂 + 记录 + 建工具」。

**交付**：`docs/diagnosis-kb.md` + `scripts/diagnose_demo.py` + 一次 commit。

**后续**：真实模型 Key 到位后，由你主责模型联调与提示词调优。

---

## 四、三条铁律

**1. `.env` 绝对不能提交。**
里面有 API Key。泄露不只是扣分，是别人拿你们的额度去跑、扣你们的钱。
`.gitignore` 已经排除了它，**不要手动删掉那条规则**。

**2. 不要连点「巡检」按钮。**
高频请求会触发对方站点的 WAF 限流，链接会返回 403/429 —— 那看着像故障，其实是误报。
间隔几分钟测一次。

> 这条不是小事：巡检类工具最典型的翻车方式，就是把「对方限流」误报成「网站有故障」。
> 一份让客户去修本来没坏的链接的报告，等于没有价值。

**3. API Key 不要贴到公开群或公共文档里。**
私聊发，或者用带密码的共享方式。

---

## 五、卡住了怎么办

把**完整报错原文**发出来 —— 终端里的红字、浏览器的提示，截图或复制都行。

只发一句「跑不起来」没法排查。**报错原文是定位问题的一半。**

常见报错的对照处理见 `README.md` 的「常见问题」一节。

---

## 六、关键时间点

| 事项 | 时间 |
|---|---|
| 报名截止 | 2026-11-30 |
| 初赛提交材料 | 2026-12 |
| 中国总决赛 | 2027-03 |

作品必须开源，且**未采用赛题要求 Huawei 技术的队伍没有参赛资格**。
