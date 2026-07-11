# Auto Renew Framework

一个综合优化的自动续期框架，集成了多种登录方式、Cloudflare 多策略验证、sing-box 全格式代理支持、Cookie 自动持久化和 Telegram 通知。

## ✨ 功能特性

- 🔐 **三种登录方式**：Cookie 登录 / 账号密码登录 / Discord OAuth 登录，自动降级尝试
- 🛡️ **Cloudflare 六脉神剑**：6 种验证策略逐一尝试，大大提高通过率
- 🌐 **全格式代理支持**：基于 sing-box，支持 VMess / VLESS / Shadowsocks / Trojan / 订阅链接
- 🍪 **Cookie 自动维护**：登录后自动将新 Cookie 更新到 GitHub Secrets，实现自我循环
- 📩 **Telegram 通知**：登录/续期结果实时推送
- 🧹 **自动清理**：进程、临时文件、截图自动清理
- ⏰ **定时执行**：基于 GitHub Actions，支持 cron 定时 + 手动触发
- 🔌 **插件式续期**：只需在 `do_renew()` 中添加平台逻辑，其余全部复用

## 📁 项目结构
. ├── app.py # 主程序（单文件，包含所有逻辑） └── .github/ └── workflows/ └── renew.yml # GitHub Actions 工作流


Plain Text


## 🚀 快速开始

### 1. Fork / 新建仓库

将 `app.py` 和 `.github/workflows/renew.yml` 放入你的仓库。

### 2. 配置 Secrets

在仓库的 **Settings → Secrets and variables → Actions → New repository secret** 中添加以下变量：

#### 🔧 基础配置（必填）

| Secret 名称 | 说明 | 示例 |
|------------|------|------|
| `BASE_URL` | 目标站点根 URL | `https://dash.example.com` |
| `PLATFORM_NAME` | 平台名称（通知用） | `ExampleCloud` |
| `PLATFORM_FLAG` | 平台 emoji 图标（通知用） | `🇫🇷` |

#### 🔑 登录凭证（至少配置一种）

| Secret 名称 | 说明 |
|------------|------|
| `COOKIE_VALUE` | 登录 Cookie 值（首选登录方式） |
| `COOKIE_NAME` | Cookie 名称，默认 `session_token` |
| `COOKIE_DOMAIN` | Cookie 作用域，默认自动从 BASE_URL 提取 |
| `EMAIL` | 登录邮箱（账号密码登录） |
| `PASSWORD` | 登录密码（账号密码登录） |
| `DISCORD_TOKEN` | Discord Token（Discord OAuth 登录） |
| `DISCORD_CLIENT_ID` | Discord OAuth Client ID |
| `DISCORD_REDIRECT_URI` | Discord OAuth 回调地址 |
| `DISCORD_LOGIN_PATH` | 站点 Discord 登录路径，默认 `/login/discord` |

#### 🍪 Cookie 自动更新

| Secret 名称 | 说明 |
|------------|------|
| `GH_TOKEN` | GitHub Personal Access Token，用于自动更新 Cookie |
| `GH_SECRET_NAME` | 要更新的 Secret 名称，默认 `COOKIE_VALUE` |

> 💡 GH_TOKEN 需要有 repo 权限，用于更新仓库 Secrets

#### 📩 Telegram 通知（可选）

| Secret 名称 | 说明 |
|------------|------|
| `TG_BOT_TOKEN` | Telegram Bot Token |
| `TG_CHAT_ID` | Telegram Chat ID |

#### 🌐 代理配置（可选）

| Secret 名称 | 说明 |
|------------|------|
| `NODE_LINK` | 节点链接或订阅链接（支持 VMess/VLESS/SS/Trojan） |

#### 🛠️ 高级配置（可选，有默认值）

| Secret 名称 | 默认值 | 说明 |
|------------|--------|------|
| `LOGIN_PATH` | `/auth/login` | 登录页路径 |
| `DASHBOARD_PATH` | `/dashboard` | Dashboard 路径 |
| `HEADLESS` | `false` | 是否无头模式运行 |
| `COOKIE_UPDATE_THRESHOLD_DAYS` | `3` | Cookie 剩余多少天时自动更新 |

### 3. 添加续期逻辑

打开 `app.py`，找到 `do_renew()` 函数（约 1087 行），在 TODO 处添加具体平台的续期代码。

函数返回值约定：

```python
def do_renew(sb) -> tuple: # 返回: (status, extra_info, expiry_date) # status: "SUCCESS" | 续期成功 # "NOT_TIME" | 未到续期时间 # "FAIL" | 续期失败 # extra_info: 附加说明文本（显示在通知中） # expiry_date: 到期日期字符串（显示在通知中） return "SUCCESS", "延长 7 天", "2026-07-18"


Plain Text


可用工具函数：

```python
处理 Cloudflare 验证
solve_cloudflare(sb)

JS 方式填写表单
js_fill_input(sb, 'input[name="email"]', "your@email.com")

获取出口 IP
get_current_ip()


Plain Text


### 4. 测试运行

在 **Actions** 页面找到 workflow，点击 **Run workflow** 手动触发一次，观察日志确认是否正常。

## 🔐 登录方式优先级

脚本按以下顺序尝试登录，前一种失败自动降级到下一种：

1. **Cookie 登录**（首选，最快最稳）
2. **账号密码登录**（次选，通用）
3. **Discord OAuth 登录**（备用，针对支持 Discord 登录的站点）

登录成功后，如果配置了 `GH_TOKEN`，会自动将新 Cookie 写回 GitHub Secrets，实现 Cookie 的自我维护。

## 🛡️ Cloudflare 验证策略

当检测到 Cloudflare 验证时，按以下顺序逐一尝试，成功即停止：

| 策略 | 说明 |
|------|------|
| 1. 静默等待 | 等待 5 秒盾自动通过 |
| 2. uc_gui_click_captcha | SeleniumBase 内置验证码点击 |
| 3. xdotool 物理点击 | 计算绝对坐标，模拟真人鼠标点击 |
| 4. SeleniumBase 点击 | 原生方式点击 iframe |
| 5. JS 遍历点击 | 注入 JS 点击所有 checkbox/label/iframe |
| 6. 随机鼠标移动 | 模拟真人鼠标轨迹 |

## 🌐 代理支持

基于 sing-box，支持以下节点格式：

- ✅ VMess（支持 WS/gRPC 传输）
- ✅ VLESS（支持 TLS / Reality / XTLS）
- ✅ Shadowsocks
- ✅ Trojan
- ✅ 订阅链接（base64 编码）

使用方式：在 Secrets 中配置 `NODE_LINK`，填入节点链接或订阅链接即可。

HTTP 代理端口：`1080`  
SOCKS5 代理端口：`1081`

## 📅 定时设置

修改 `.github/workflows/renew.yml` 中的 cron 表达式：

```yaml
on: schedule: - cron: '0 2 * * *' # 每天 UTC 02:00 = 北京时间 10:00


Plain Text


> ⚠️ GitHub Actions 的 cron 使用 UTC 时间，北京时间 = UTC + 8

## 🖥️ 本地运行

### 环境要求

- Python 3.10+
- Chrome / Chromium 浏览器
- xvfb（Linux 无头运行需要）

### 安装依赖

```bash
pip install seleniumbase requests 'requests[socks]' seleniumbase install chromedriver


Plain Text


### Linux 系统依赖

```bash
sudo apt-get install -y xvfb x11-utils xdotool scrot fonts-noto-cjk


Plain Text


### 运行脚本

```bash
设置环境变量（示例）
export BASE_URL="https://dash.example.com" export COOKIE_VALUE="your_cookie_here" export EMAIL="your@email.com" export PASSWORD="your_password" export PLATFORM_NAME="ExampleCloud" export PLATFORM_FLAG="☁️"

有图形界面直接运行
python3 app.py

无图形界面用 xvfb
xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" python3 app.py


Plain Text


## 🔧 常见问题

### Q: Cloudflare 验证一直通不过怎么办？

A: 可以尝试：
1. 使用代理换个 IP 段
2. 增加 Cookie 登录，减少触发验证的概率
3. 检查是否开了 HEADLESS 模式，有头模式通过率更高

### Q: Cookie 多久会过期？

A: 不同平台不一样。开启 `GH_TOKEN` 自动更新后，Cookie 快过期时会自动刷新。

### Q: 可以同时配置多个节点吗？

A: 可以。`NODE_LINK` 支持换行填入多个节点链接，也支持订阅链接（自动拉取所有节点）。脚本默认使用第一个节点。

### Q: 如何添加新的登录方式？

A: 在登录模块区域添加一个 `login_by_xxx(sb)` 函数，然后在 `do_login()` 的 methods 列表中加入即可。

## 📄 License

MIT
