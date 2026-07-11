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
- app.py # 主程序（单文件，包含所有逻辑） 
- .github/workflows/renew.yml # GitHub Actions 工作流

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
