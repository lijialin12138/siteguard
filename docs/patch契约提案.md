# 修复补丁（patch）数据契约提案 · D5

> 目的：D5 要做「自动修复闭环」（拉分项）。核心是 AI 给出的 `patch` 从「一段泛泛的建议」
> 升级成「按问题类别、可直接落地的多段补丁」。这会改到**三人共用的诊断结果结构**，
> 所以先把契约定死，再各自动手，避免中途字段对不上导致三方一起崩。
>
> 提出人：霖（后端） · 涉及：小甘（ai.py 产出）、霖（后端接口）、小格（前端消费）

---

## 一、为什么要改

- 现状：诊断结果里 `patch` 是**单个字符串**，一次诊断只给一段补丁，且不分问题类别。
- D5 目标：一个站点常同时有几类问题（SSL 临期 + 死链 + 慢），应当**每类问题各给一段可直接用的补丁**，
  前端才能做到「逐条复制、逐条修复、修完复扫验证」。
- 风险：`patch` 是「存储 / AI / 前端」三处共用的字段，**改它之前三条线必须同步**（团队铁律）。

---

## 二、新契约（以此为准）

在诊断结果 JSON 里，**新增** `patches` 数组字段；**保留** 旧的 `patch` 字符串字段。

```jsonc
{
  "summary": "……",
  "severity": "P1",
  "root_causes": [ { "issue": "……", "reason": "……" } ],
  "actions": [ { "priority": 1, "action": "……", "how": "……" } ],

  // ✅ 新字段：结构化补丁列表，按问题类别各一段
  "patches": [
    {
      "category": "ssl",             // 必填，取值见「五、category 取值」
      "title": "证书续期并配置自动续期", // 必填，一句话说明这段补丁在干什么
      "language": "bash",            // 选填，代码高亮用：bash / nginx / html / json / ""
      "code": "sudo certbot renew …"  // 必填，可直接复制落地的补丁正文
    }
  ],

  // ⚠️ 旧字段：保留做兜底兼容（MOCK 和历史数据仍是它）
  "patch": "……"
}
```

**硬规则：**
1. `patches` 每个元素的 `category` / `title` / `code` **都必须有**（`code` 不能为空串，否则这一段没意义）。
2. `language` 可为空串，前端按空串当纯文本处理。
3. `patches` 可以为 `[]`（本次无代码级修复），此时视为「无补丁」，前端显示「本次无需代码修改」。
4. 顺序：`patches` 按 `severity` 从高到低排（最严重的排最前）。

---

## 三、兼容策略（过渡期，别一刀切）

| 场景 | `patches` | `patch` | 前端表现 |
|---|---|---|---|
| 新模型输出 | 有内容 | 也保留（可填第一段的 `code`） | 用 `patches` 渲染多段 |
| 旧数据 / MOCK | 无（缺字段） | 有内容 | 回退用 `patch` 渲染单段 |

> 后端已经把这层兼容做好了（见「四」），**前端不需要自己判断新旧**。

---

## 四、三方职责（各改各的文件，不重叠）

| 角色 | 文件 | 要做的事 |
|---|---|---|
| **小甘** | `app/ai.py` | ① `SYSTEM_PROMPT` 增加 `patches` 输出要求；② `_mock_diagnose` 之类的 MOCK 同步产出 `patches`；③ **更新自己文件里的 `write_daily_report`**（当前读 `diagnosis.get("patch")`），让它优先渲染 `patches` 里的多段。**不要动 main.py / service.py**。 |
| **霖** | `app/main.py`、`app/service.py` | ① 新增 `GET /api/scans/{scan_id}/patch` 接口；② `service.extract_patches()` 统一新旧结构。**已提供，见「六」**。 |
| **小格** | `app/static/index.html` | 修复闭环前端**只调 `/api/scans/{scan_id}/patch`**，读返回的 `patches` 数组渲染多段 + 每条一键复制。**不要直接读 `/diagnose` 的原始 result**。 |

> 关键点：**前端与模型输出之间隔了霖的 `/patch` 接口**。这样小甘以后怎么调模型侧结构，
> 只要改 `extract_patches` 一处或小甘同步，就不会牵动前端。

---

## 五、category 取值（必须与 scanner 对齐，不要自造）

后端 `scanner.build_issues()` 产出的问题类别就这 11 个，`patches[].category` 必须取其中之一：

| category | 含义 | 典型补丁形态 |
|---|---|---|
| `availability` | 站点无响应 | bash（进程/网络排查） |
| `server_error` | 5xx | bash（捞错误日志） |
| `client_error` | 4xx | nginx（补 301 / 改权限） |
| `redirect` | 多余跳转 | nginx（合并跳转） |
| `performance` | 响应慢 | nginx（gzip + 缓存） |
| `ssl` | 证书临期/过期 | bash（certbot 续期） |
| `broken_link` | 404/410 死链 | bash / html |
| `link_server_error` | 链接 5xx（可能瞬时） | bash（复测命令） |
| `link_unverified` | 无法验证（403/429/超时） | bash（复核命令） |
| `seo` | 缺 title/description/H1 | html |
| `accessibility` | 图片缺 alt | html |

> 注意：`link_unverified` 这一类的补丁**只能是「复核/人工确认」类**，绝不能给「删除链接」——
> 403/429 不等于死链，误删会烧掉客户的真实链接（控误报铁律）。

---

## 六、霖已提供的接口

```
GET /api/scans/{scan_id}/patch
```

- 前置：该 scan 已经跑过 `/api/scans/{scan_id}/diagnose`（否则返回 400，提示先诊断）。
- 返回：

```jsonc
{
  "scan_id": 12,
  "site_id": 3,
  "diagnosis_id": 7,
  "model": "deepseek-v4-flash",
  "severity": "P1",
  "summary": "……",
  "patches": [ { "category": "ssl", "title": "…", "language": "bash", "code": "…" } ],
  "patch": "……"   // 兼容字段
}
```

- 特点：**无论模型给的是新 `patches` 还是旧 `patch`，这里返回的 `patches` 一定是可以直接遍历的列表**（空则 `[]`）。

前端示例（小格）：

```js
const { patches } = await fetch(`/api/scans/${scanId}/patch`).then(r => r.json());
if (!patches.length) { /* 显示：本次无需代码修改 */ }
for (const p of patches) {
  // 渲染 p.title / p.language / p.code，并给 p.code 一个「一键复制」按钮
}
```

---

## 七、小甘要动的点（ai.py）

1. `SYSTEM_PROMPT` 的输出结构里，把 `patch` 一节改成明确要求 `patches` 数组（字段见「二」），
   并强调：**只能针对报告里真实存在的问题类别给补丁，禁止编造不存在的问题/配置**。
2. MOCK 分支（`_mock_diagnose`）同步产出 `patches`——你现有的 `_MOCK_KNOWLEDGE` 里
   每个类别已经带了 patch 片段，直接组装成 `patches` 列表即可（顺便把 MOCK 的 `patch` 也保留，做兜底）。
3. 你自己文件里的 `write_daily_report`（当前读 `diagnosis.get("patch")`）改成：
   **优先遍历 `diagnosis.get("patches")` 分段渲染，为空再回退 `diagnosis.get("patch")`**。
4. **补丁仍必须用码道 CodeArts 生成/校对并留痕**（D5 任务书要求，答辩「用了华为技术」的证据链）。

---

## 八、验收标准（D5 收尾自查）

- [ ] 真实模型跑一次，`/api/scans/{id}/patch` 返回的 `patches` 至少 1 段，且 `code` 非空、`category` 在 11 类之内。
- [ ] MOCK 模式下同样返回合法 `patches`（没配 Key 也能演示闭环）。
- [ ] 前端「一键复制」复制出来的就是 `code` 原文，粘贴到服务器能用（无多余转义/换行丢失）。
- [ ] 复扫前后对比：应用补丁 → 复扫 → 对应 issue 消失或等级下降（这条闭环跑通）。
- [ ] `docs/` 里留一份真实模型的脱敏样例（含 `patches`），作答辩证据。

---

## 九、时间线

- **今天**：霖冻结本契约，`/patch` 接口就位；文档同步小甘、小格。
- **D5 执行**：小甘按「七」改 `ai.py`；小格按「六」接接口；霖做真模型端到端验证。
- **契约冻结后**：任何一方要再改 `patches` 字段，**先在群里说一声**，三方同步再动。
