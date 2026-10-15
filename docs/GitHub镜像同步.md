# GitHub 镜像同步（Gitee + GitHub 双平台）

> **用途**：老师要求「参加 ICT 比赛的同学注册好 Gitee 和 GitHub 账号，做好代码托管和开源准备」。
> 本项目主仓在 **Gitee**，GitHub 作为**镜像/开源展示**。本文档说明如何一条命令同时推两个平台，以及校园网下 GitHub 必须用 SSH 的原因与配置。
>
> 面向阅读对象：队长（A）已完成配置，队友（B 小甘 / C 小格）照此在自己机器上配一遍。

---

## 一、为什么要用 SSH（重要背景）

GitHub 的 **HTTPS（`github.com:443`）在本机所在网络被封锁**（无论是校园网还是热点，实测 TCP 都连不上，浏览器也打不开 github.com）。

但 **SSH 通道（`github.com:22`）是通的**。所以本项目**不走 HTTPS，全程走 SSH**。

实测对照（2026-10-15）：

| 目标 | 结果 |
|---|---|
| `gitee.com` | HTTP 200 ✅ |
| `github.com:443`（HTTPS） | TCP 不通 ❌ |
| `github.com:22`（SSH） | TCP 通 + 握手成功 ✅ |
| `ssh.github.com:443` | TCP 通 + 握手成功 ✅ |
| `api.github.com` | HTTP 200 ✅ |

**结论**：GitHub 网页（:443）打不开时，SSH 仍能推代码。

---

## 二、SSH 密钥配置（必须做）

### 1. 生成密钥（注意中文用户名路径）

机器是 Windows 中文用户名时，SSH 默认去 `C:\Users\<中文>\.ssh` 写文件会报路径乱码。
**密钥务必放在纯英文路径**，例如 `C:\ssh_github\`。

```bash
mkdir C:\ssh_github
ssh-keygen -t ed25519 -f C:\ssh_github\id_ed25519 -N "" -C "你的名字"
```

- `-N ""`：不设密码（CI/命令行更方便；若要更高安全可设密码）
- 生成后有两个文件：`id_ed25519`（私钥，保密）和 `id_ed25519.pub`（公钥，可公开）

### 2. 把公钥贴到 GitHub

GitHub 网页（:443）打不开时，用**能打开 github.com 的网络**（家用 WiFi / 不同运营商手机热点 / GitHub 手机 App）操作：

> GitHub → 右上角头像 → **Settings → SSH and GPG keys → New SSH key**
> Title 随便（如 `siteguard-deploy`），Key 里粘贴 `id_ed25519.pub` 的全部内容 → **Add SSH key**

### 3. 让 git 用这把密钥（绕开中文路径坑）

在本仓库目录内执行（写进**本仓库**配置，不污染全局）：

```bash
cd siteguard
git config core.sshCommand "ssh -i C:/ssh_github/id_ed25519 -o UserKnownHostsFile=C:/ssh_github/known_hosts -o StrictHostKeyChecking=accept-new"
```

---

## 三、远程仓库配置

主仓 `origin` 指向 Gitee；另设 `github` 远程指向 GitHub（SSH 地址）：

```bash
# origin 已是 Gitee（fetch/push 默认指向它），无需改
# 新增 github 远程（SSH 地址，注意换成自己的用户名）
git remote add github git@github.com:你的GitHub用户名/siteguard.git
```

---

## 四、一键双推（推荐）

让 `git push origin main` 一次同时推 Gitee + GitHub：

```bash
git remote set-url --add --push origin https://gitee.com/lijialin12138/siteguard.git
git remote set-url --add --push origin git@github.com:lijialin12138/siteguard.git
```

配置后 `git remote -v | grep origin` 应看到：

```
origin  https://gitee.com/lijialin12138/siteguard.git (fetch)
origin  https://gitee.com/lijialin12138/siteguard.git (push)
origin  git@github.com:lijialin12138/siteguard.git  (push)
```

> ⚠️ **常见坑**：只跑 `git remote set-url --add --push origin <github>` 一条，
> 会**覆盖**掉 Gitee 的 push（origin 变成只推 GitHub、不再推 Gitee）。
> 必须**两条 pushurl 都显式加**（Gitee + GitHub），如上所示。

---

## 五、日常用法

```bash
# 平时正常提交
git add <文件>
git commit -m "feat: xxx"

# 一条命令：同时推 Gitee 和 GitHub
git push origin main
```

验证双推是否成功：看输出应有**两行** `To https://gitee...` 与 `To github.com...`。

---

## 六、安全铁律（红线，违反即安全事故）

1. **绝不提交 `.env`**：真实 MaaS API Key 在里面。`.gitignore` 已排除 `.env`，只把占位符 `.env.example` 进仓库。
2. 公钥（`id_ed25519.pub`）可以公开贴 GitHub；**私钥（`id_ed25519`）永远不进仓库、不进群**。
3. 推之前想确认没带密钥：`git ls-files | grep -iE "^\.env"` 应只显示 `.env.example`。
4. 首次推 GitHub 时，若远端有一个 GitHub 自动生成的「Initial commit」（建仓勾了 License 导致），用
   `git push -u github main --force` 用本地历史覆盖即可（远端那个初始提交本地已有等价内容，无损失）。
