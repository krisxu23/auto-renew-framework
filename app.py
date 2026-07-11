import os
import re
import sys
import json
import time
import base64
import random
import subprocess
import urllib.parse
from datetime import datetime

import requests
from seleniumbase import SB


# ============================================================
#  工具函数
# ============================================================

def log(message: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def mask_email(email: str) -> str:
    if '@' in email:
        name, domain = email.split('@', 1)
        if len(name) > 4:
            return f"{name[:2]}****{name[-2:]}@{domain}"
        return f"{name}@{domain}"
    return email[:2] + '****'


def beijing_time_str() -> str:
    local_time = time.gmtime(time.time() + 8 * 3600)
    return time.strftime("%Y-%m-%d %H:%M:%S", local_time)


# ============================================================
#  配置管理（IceHost 专用默认值，使用 .strip() or 模式防止空 Secret 覆盖）
# ============================================================

class Config:
    # 目标站点（IceHost 默认）
    BASE_URL        = os.environ.get("BASE_URL", "").strip() or "https://dash.icehost.pl"
    LOGIN_PATH      = os.environ.get("LOGIN_PATH", "").strip() or "/login"
    DASHBOARD_PATH  = os.environ.get("DASHBOARD_PATH", "").strip() or "/"

    # 账号密码登录
    EMAIL    = os.environ.get("EMAIL", "").strip()
    PASSWORD = os.environ.get("PASSWORD", "").strip()

    # Cookie 登录（IceHost Laravel remember_web_ 持久登录 Cookie）
    COOKIE_NAME   = os.environ.get("COOKIE_NAME", "").strip() or "remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d"
    COOKIE_VALUE  = os.environ.get("COOKIE_VALUE", "").strip()
    COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", "").strip() or "dash.icehost.pl"

    # Discord OAuth 登录
    DISCORD_TOKEN        = os.environ.get("DISCORD_TOKEN", "").strip()
    DISCORD_CLIENT_ID    = os.environ.get("DISCORD_CLIENT_ID", "").strip()
    DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "").strip()
    DISCORD_LOGIN_PATH   = os.environ.get("DISCORD_LOGIN_PATH", "").strip() or "/login/discord"

    # Cookie 自动更新到 GitHub Secrets
    GH_TOKEN       = os.environ.get("GH_TOKEN", "").strip()
    GH_SECRET_NAME = os.environ.get("GH_SECRET_NAME", "").strip() or "COOKIE_VALUE"

    # Telegram 通知
    TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
    TG_CHAT_ID   = os.environ.get("TG_CHAT_ID", "").strip()

    # 代理
    IS_PROXY     = os.environ.get("IS_PROXY", "false").lower() == "true"
    PROXY_SERVER = os.environ.get("PROXY_SERVER", "").strip() or "http://127.0.0.1:1080"
    NODE_LINK    = os.environ.get("NODE_LINK", "").strip()

    # 浏览器
    HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

    # 通知显示
    PLATFORM_NAME  = os.environ.get("PLATFORM_NAME", "").strip() or "IceHost"
    PLATFORM_FLAG  = os.environ.get("PLATFORM_FLAG", "").strip() or "🧊"

    # Cookie 更新阈值（天）
    COOKIE_UPDATE_THRESHOLD_DAYS = int(os.environ.get("COOKIE_UPDATE_THRESHOLD_DAYS", "3"))

    @classmethod
    def validate(cls) -> bool:
        has_credential = False
        if cls.COOKIE_VALUE:
            has_credential = True
            log("✅ 配置了 Cookie 登录凭证")
        if cls.EMAIL and cls.PASSWORD:
            has_credential = True
            log("✅ 配置了账号密码登录凭证")
        if cls.DISCORD_TOKEN and cls.DISCORD_CLIENT_ID:
            has_credential = True
            log("✅ 配置了 Discord OAuth 登录凭证")
        if not has_credential:
            log("❌ 未配置任何登录凭证（Cookie / 账号密码 / Discord Token）")
            return False
        if not cls.BASE_URL:
            log("❌ 未配置 BASE_URL")
            return False
        return True

    @classmethod
    def login_url(cls) -> str:
        return f"{cls.BASE_URL}{cls.LOGIN_PATH}"

    @classmethod
    def dashboard_url(cls) -> str:
        return f"{cls.BASE_URL}{cls.DASHBOARD_PATH}"


# ============================================================
#  浏览器工具
# ============================================================

def get_current_ip() -> str:
    proxies = {"http": Config.PROXY_SERVER, "https": Config.PROXY_SERVER} if Config.IS_PROXY else None
    try:
        resp = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
        if resp.status_code == 200:
            return resp.text.strip()
        return "获取失败"
    except Exception as e:
        log(f"❌ 获取出口IP失败: {e}")
        return "获取失败"


def js_fill_input(sb, selector: str, text: str):
    safe_text = text.replace('\\', '\\\\').replace('"', '\\"')
    sb.execute_script(f"""
    (function(){{
        var el = document.querySelector('{selector}');
        if (!el) return;
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        if (nativeInputValueSetter) {{
            nativeInputValueSetter.call(el, "{safe_text}");
        }} else {{
            el.value = "{safe_text}";
        }}
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()
    """)


def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", cls],
                               capture_output=True, text=True, timeout=3)
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(["xdotool", "windowactivate", "--sync", wids[0]],
                               timeout=3, stderr=subprocess.DEVNULL)
                time.sleep(0.2)
                return
        except Exception:
            pass
    try:
        subprocess.run(["xdotool", "getactivewindow", "windowactivate"],
                       timeout=3, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def xdotool_click(x: int, y: int):
    _activate_window()
    try:
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)],
                       timeout=3, stderr=subprocess.DEVNULL)
        time.sleep(0.15)
        subprocess.run(["xdotool", "click", "1"], timeout=2, stderr=subprocess.DEVNULL)
    except Exception:
        os.system(f"xdotool mousemove {x} {y} click 1 2>/dev/null")


_WININFO_JS = """
(function(){
    return {
        sx: window.screenX || 0,
        sy: window.screenY || 0,
        oh: window.outerHeight,
        ih: window.innerHeight
    };
})()
"""


def screen_to_abs(sb, cx: int, cy: int) -> tuple:
    try:
        wi = sb.execute_script(_WININFO_JS)
    except Exception:
        wi = {"sx": 0, "sy": 0, "oh": 800, "ih": 768}
    bar = wi["oh"] - wi["ih"]
    ax = cx + wi["sx"]
    ay = cy + wi["sy"] + bar
    return ax, ay


# ============================================================
#  代理配置（sing-box，支持 VMess / VLESS / SS / Trojan / Hysteria2 / 订阅链接）
# ============================================================

SINGBOX_BIN   = os.path.join(os.getcwd(), "sing-box")
SINGBOX_CONFIG = os.path.join(os.getcwd(), "sing-box-config.json")
SINGBOX_LOG   = os.path.join(os.getcwd(), "sing-box.log")


def _decode_base64(s: str) -> str:
    s = s.strip()
    padding = 4 - len(s) % 4
    if padding != 4:
        s += '=' * padding
    try:
        return base64.urlsafe_b64decode(s).decode('utf-8', errors='ignore')
    except Exception:
        try:
            return base64.b64decode(s).decode('utf-8', errors='ignore')
        except Exception:
            return ""


def _parse_vmess(link: str) -> dict:
    raw = link.replace("vmess://", "").strip()
    decoded = _decode_base64(raw)
    if not decoded:
        return {}
    try:
        return json.loads(decoded)
    except Exception:
        return {}


def _parse_ss(link: str) -> dict:
    link = link.replace("ss://", "").strip()
    if "@" in link:
        method_info, server_info = link.split("@", 1)
    else:
        decoded = _decode_base64(link)
        if "@" not in decoded:
            return {}
        method_info, server_info = decoded.split("@", 1)
    method = _decode_base64(method_info) if "%" not in method_info else urllib.parse.unquote(method_info)
    if not method:
        method = method_info
    if ":" in server_info:
        srv_port = server_info.split("#")[0]
        if ":" in srv_port:
            server, port = srv_port.split(":", 1)
            return {"v": "2", "ps": "shadowsocks", "add": server, "port": port,
                    "method": method, "id": "", "type": "ss"}
    return {}


def _parse_trojan(link: str) -> dict:
    link = link.replace("trojan://", "").strip()
    if "@" not in link:
        return {}
    password, rest = link.split("@", 1)
    rest = rest.split("#")[0]
    params = {}
    if "?" in rest:
        addr_part, query_part = rest.split("?", 1)
        params = dict(urllib.parse.parse_qsl(query_part))
    else:
        addr_part = rest
    if ":" in addr_part:
        server, port = addr_part.split(":", 1)
        result = {"v": "2", "ps": "trojan", "add": server, "port": port,
                "id": password, "type": "trojan"}
        if params.get("sni"):
            result["sni"] = params.get("sni")
        return result
    return {}


def _parse_vless(link: str) -> dict:
    link = link.replace("vless://", "").strip()
    if "@" not in link:
        return {}
    uuid, rest = link.split("@", 1)
    rest = rest.split("#")[0]
    params = {}
    if "?" in rest:
        addr_part, query_part = rest.split("?", 1)
        params = dict(urllib.parse.parse_qsl(query_part))
    else:
        addr_part = rest
    if ":" in addr_part:
        server, port = addr_part.split(":", 1)
        return {"v": "2", "ps": "vless", "add": server, "port": port, "id": uuid,
                "type": "vless", "encryption": params.get("encryption", "none"),
                "security": params.get("security", ""), "sni": params.get("sni", ""),
                "flow": params.get("flow", ""), "fp": params.get("fp", ""),
                "pbk": params.get("pbk", ""), "sid": params.get("sid", ""),
                "spx": params.get("spx", "")}
    return {}


def _parse_hysteria2(link: str) -> dict:
    """解析 hysteria2:// 或 hy2:// 链接"""
    raw = link
    if raw.startswith("hysteria2://"):
        raw = raw[len("hysteria2://"):]
    elif raw.startswith("hy2://"):
        raw = raw[len("hy2://"):]
    else:
        return {}
    raw = raw.strip()
    if "@" not in raw:
        return {}
    password, rest = raw.split("@", 1)
    rest = rest.split("#")[0]
    params = {}
    if "?" in rest:
        addr_part, query_part = rest.split("?", 1)
        params = dict(urllib.parse.parse_qsl(query_part))
    else:
        addr_part = rest
    if ":" in addr_part:
        server, port = addr_part.split(":", 1)
        return {"v": "2", "ps": "hysteria2", "add": server, "port": port,
                "id": password, "type": "hysteria2",
                "security": params.get("security", "tls"),
                "sni": params.get("sni", ""),
                "insecure": params.get("insecure", "0")}
    return {}


def _parse_single_link(link: str) -> dict:
    link = link.strip()
    if link.startswith("vmess://"):
        return _parse_vmess(link)
    elif link.startswith("ss://"):
        return _parse_ss(link)
    elif link.startswith("trojan://"):
        return _parse_trojan(link)
    elif link.startswith("vless://"):
        return _parse_vless(link)
    elif link.startswith("hysteria2://") or link.startswith("hy2://"):
        return _parse_hysteria2(link)
    return {}


def _parse_subscription(url: str) -> list:
    proxies = {"http": Config.PROXY_SERVER, "https": Config.PROXY_SERVER} if Config.IS_PROXY else None
    try:
        resp = requests.get(url, proxies=proxies, timeout=30)
        if resp.status_code != 200:
            return []
        content = resp.text.strip()
        if content.startswith("http") or content.startswith("vmess://") or content.startswith("ss://"):
            lines = content.split("\n")
        else:
            decoded = _decode_base64(content)
            lines = decoded.split("\n") if decoded else []
        return [l.strip() for l in lines if l.strip()]
    except Exception as e:
        log(f"❌ 订阅拉取失败: {e}")
        return []


def parse_node_link(link: str) -> list:
    link = link.strip()
    if not link:
        return []
    nodes = []
    if link.startswith("http://") or link.startswith("https://"):
        log("📡 检测到订阅链接，正在拉取节点...")
        links = _parse_subscription(link)
        for l in links:
            n = _parse_single_link(l)
            if n:
                nodes.append(n)
    else:
        for l in link.split("\n"):
            l = l.strip()
            if l:
                n = _parse_single_link(l)
                if n:
                    nodes.append(n)
    return nodes


def _build_singbox_outbounds(nodes: list) -> list:
    outbounds = []
    for idx, node in enumerate(nodes):
        ntype = node.get("type", "")
        tag = f"proxy-{idx}"
        if ntype == "vmess":
            outbounds.append({"type": "vmess", "tag": tag,
                "server": node.get("add", ""), "server_port": int(node.get("port", 0)),
                "uuid": node.get("id", ""), "security": node.get("scy", "auto"),
                "alter_id": int(node.get("aid", 0)), "transport": {}})
            net = node.get("net", "tcp")
            if net == "ws":
                outbounds[-1]["transport"] = {"type": "ws", "path": node.get("path", "/"),
                    "headers": {"Host": node.get("host", "")}}
            elif net == "grpc":
                outbounds[-1]["transport"] = {"type": "grpc", "service_name": node.get("path", "")}
        elif ntype == "vless":
            tls_obj = None
            if node.get("security", "") == "tls" or node.get("flow", ""):
                tls_obj = {"enabled": True,
                           "server_name": node.get("sni", "") or node.get("add", ""),
                           "utls": {"enabled": True, "fingerprint": node.get("fp", "chrome")}}
                if node.get("pbk"):
                    tls_obj["reality"] = {"enabled": True,
                        "public_key": node.get("pbk", ""), "short_id": node.get("sid", "")}
            outbounds.append({"type": "vless", "tag": tag,
                "server": node.get("add", ""), "server_port": int(node.get("port", 0)),
                "uuid": node.get("id", ""), "flow": node.get("flow", ""),
                "tls": tls_obj,
                "transport": {}})
            if node.get("pbk"):
                outbounds[-1]["packet_encoding"] = "xudp"
        elif ntype in ("shadowsocks", "ss"):
            outbounds.append({"type": "shadowsocks", "tag": tag,
                "server": node.get("add", ""), "server_port": int(node.get("port", 0)),
                "method": node.get("method", "aes-256-gcm"),
                "password": node.get("id", node.get("password", ""))})
        elif ntype == "trojan":
            outbounds.append({"type": "trojan", "tag": tag,
                "server": node.get("add", ""), "server_port": int(node.get("port", 0)),
                "password": node.get("id", node.get("password", "")),
                "tls": {"enabled": True, "server_name": node.get("sni", "") or node.get("add", "")}})
        elif ntype == "hysteria2":
            tls_config = {"enabled": True}
            if node.get("sni"):
                tls_config["server_name"] = node.get("sni")
            if str(node.get("insecure", "0")) in ("1", "true"):
                tls_config["insecure"] = True
            outbounds.append({"type": "hysteria2", "tag": tag,
                "server": node.get("add", ""), "server_port": int(node.get("port", 0)),
                "password": node.get("id", ""),
                "tls": tls_config})
    return [o for o in outbounds if o.get("server") and o.get("server_port")]


def generate_singbox_config(nodes: list) -> str:
    outbounds = _build_singbox_outbounds(nodes)
    if not outbounds:
        return ""
    config = {
        "log": {"level": "warn", "output": SINGBOX_LOG},
        "inbounds": [
            {"type": "http", "tag": "http-in", "listen": "127.0.0.1", "listen_port": 1080},
            {"type": "socks", "tag": "socks-in", "listen": "127.0.0.1", "listen_port": 1081},
        ],
        "outbounds": outbounds + [{"type": "direct", "tag": "direct"}, {"type": "block", "tag": "block"}],
        "route": {"rules": [], "final": outbounds[0]["tag"] if outbounds else "direct"},
    }
    with open(SINGBOX_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return SINGBOX_CONFIG


def download_singbox() -> bool:
    if os.path.exists(SINGBOX_BIN) and os.access(SINGBOX_BIN, os.X_OK):
        log("✅ sing-box 已存在")
        return True
    log("⬇️  正在下载 sing-box...")
    arch = subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip()
    arch_suffix = "linux-arm64" if arch == "aarch64" else "linux-amd64"
    url = f"https://github.com/SagerNet/sing-box/releases/latest/download/sing-box-{arch_suffix}.tar.gz"
    try:
        subprocess.run(["wget", "-q", "-O", "/tmp/sing-box.tar.gz", url], timeout=120)
        subprocess.run(["tar", "xzf", "/tmp/sing-box.tar.gz", "-C", "/tmp/"], check=True)
        extracted_dir = None
        for d in os.listdir("/tmp"):
            if d.startswith("sing-box-") and os.path.isdir(f"/tmp/{d}"):
                extracted_dir = f"/tmp/{d}"
                break
        if extracted_dir and os.path.exists(f"{extracted_dir}/sing-box"):
            subprocess.run(["cp", f"{extracted_dir}/sing-box", SINGBOX_BIN])
            os.chmod(SINGBOX_BIN, 0o755)
            log("✅ sing-box 下载完成")
            return True
        return False
    except Exception as e:
        log(f"❌ sing-box 下载失败: {e}")
        return False


def _is_singbox_running() -> bool:
    """检测 sing-box 是否已经在运行（可能由 workflow 脚本启动）"""
    try:
        result = subprocess.run(["pgrep", "-f", "sing-box"], capture_output=True, timeout=3)
        return result.returncode == 0
    except Exception:
        return False


def start_singbox() -> bool:
    # 如果 sing-box 已经在运行（由 workflow 脚本启动），直接使用
    if _is_singbox_running():
        log("✅ 检测到 sing-box 已在运行（由 workflow 脚本启动），直接使用")
        return True

    if not Config.NODE_LINK:
        log("ℹ️  未配置 NODE_LINK，跳过代理启动")
        return False

    # sing-box 未运行，尝试自己启动
    nodes = parse_node_link(Config.NODE_LINK)
    if not nodes:
        log("❌ 未能解析出有效节点")
        return False
    log(f"✅ 解析到 {len(nodes)} 个节点")
    if not download_singbox():
        return False
    config_path = generate_singbox_config(nodes)
    if not config_path:
        log("❌ 生成 sing-box 配置失败")
        return False
    log("🚀 启动 sing-box...")
    try:
        subprocess.Popen([SINGBOX_BIN, "run", "-c", SINGBOX_CONFIG],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        log("✅ sing-box 已启动 (http=1080, socks=1081)")
        return True
    except Exception as e:
        log(f"❌ sing-box 启动失败: {e}")
        return False


def stop_singbox():
    # 如果 sing-box 由 workflow 脚本启动，不要停止它（让 workflow 清理步骤处理）
    # 这里只停止由本脚本启动的 sing-box
    try:
        subprocess.run(["pkill", "-f", "sing-box"], stderr=subprocess.DEVNULL)
        time.sleep(1)
        log("🧹 sing-box 已停止")
    except Exception:
        pass


# ============================================================
#  Cloudflare 验证（多策略逐一尝试）
# ============================================================

_CF_INDICATORS = [
    "verify you are human", "确认您是真人", "troubleshoot",
    "just a moment", "cf-turnstile", "challenges.cloudflare.com",
]
_TURNSTILE_IFRAME_SEL = 'iframe[src*="challenges.cloudflare.com"]'

_EXPAND_JS = """
(function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (!ts) return 'no-turnstile';
    var el = ts;
    for (var i = 0; i < 20; i++) {
        el = el.parentElement;
        if (!el) break;
        var s = window.getComputedStyle(el);
        if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
            el.style.overflow = 'visible';
        el.style.minWidth = 'max-content';
    }
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && f.src.includes('challenges.cloudflare.com')) {
            f.style.width = '300px'; f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible'; f.style.opacity = '1';
        }
    });
    return 'done';
})()
"""

_COORDS_JS = """
(function(){
    // 优先定位 Turnstile widget 的复选框 label.dxeA5（IceHost 的 Turnstile 直接嵌入主页面）
    var label = document.querySelector('label.dxeA5') || document.querySelector('label:has(input[type="checkbox"])');
    if (label) {
        var r = label.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            // 点击复选框左侧的可视化区域（span.hHMFo6）
            return {cx: Math.round(r.x + 15), cy: Math.round(r.y + r.height / 2)};
        }
    }
    // 备用1: span.hHMFo6（复选框可视化元素）
    var visual = document.querySelector('span.hHMFo6');
    if (visual) {
        var r2 = visual.getBoundingClientRect();
        if (r2.width > 0) return {cx: Math.round(r2.x + r2.width/2), cy: Math.round(r2.y + r2.height/2)};
    }
    // 备用2: iframe（某些场景下 Turnstile 仍在 iframe 内）
    var iframes = document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        var src = iframes[i].src || '';
        if (src.includes('cloudflare') || src.includes('turnstile') || src.includes('challenges')) {
            var r3 = iframes[i].getBoundingClientRect();
            if (r3.width > 0 && r3.height > 0)
                return {cx: Math.round(r3.x + 30), cy: Math.round(r3.y + r3.height / 2)};
        }
    }
    // 备用3: cf-turnstile-response 输入框的父容器
    var inp = document.querySelector('input[name="cf-turnstile-response"]');
    if (inp) {
        var p = inp.parentElement;
        for (var j = 0; j < 5; j++) {
            if (!p) break;
            var r4 = p.getBoundingClientRect();
            if (r4.width > 100 && r4.height > 30)
                return {cx: Math.round(r4.x + 30), cy: Math.round(r4.y + r4.height / 2)};
            p = p.parentElement;
        }
    }
    return null;
})()
"""

_JS_CLICK_ALL = """
(function(){
    // 1. 优先点击 Turnstile 复选框 label.dxeA5（IceHost 直接嵌入主页面场景）
    var label = document.querySelector('label.dxeA5');
    if (label) {
        label.click();
        label.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        // 同时点击内部 checkbox 和可视化 span
        var cb = label.querySelector('input[type="checkbox"]');
        if (cb) { cb.click(); cb.dispatchEvent(new MouseEvent('click', {bubbles:true})); }
        var sp = label.querySelector('span.hHMFo6');
        if (sp) { sp.click(); sp.dispatchEvent(new MouseEvent('click', {bubbles:true})); }
        return 'label.dxeA5';
    }
    // 2. 点击 span.hHMFo6（复选框可视化元素）
    var visual = document.querySelector('span.hHMFo6');
    if (visual) {
        visual.click();
        visual.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        return 'span.hHMFo6';
    }
    // 3. 点击 iframe（传统 iframe 嵌入场景）
    var iframes = document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        if (iframes[i].src && iframes[i].src.includes('challenges.cloudflare.com')) {
            iframes[i].click();
            iframes[i].dispatchEvent(new MouseEvent('click', {bubbles:true}));
        }
    }
    // 4. 点击其他可疑 label
    var labels = document.querySelectorAll('label');
    for (var j = 0; j < labels.length; j++) {
        var txt = (labels[j].textContent || '').toLowerCase();
        if (txt.includes('robot') || txt.includes('captcha') || txt.includes('verify') || txt.includes('验证'))
            labels[j].click();
    }
    // 5. 点击所有未禁用的 checkbox
    var cbs = document.querySelectorAll('input[type="checkbox"]');
    for (var k = 0; k < cbs.length; k++) {
        if (!cbs[k].disabled) {
            cbs[k].click();
            cbs[k].dispatchEvent(new MouseEvent('click', {bubbles:true}));
        }
    }
    return 'done';
})()
"""

_MOUSE_MOVE_JS = """
(function(){
    var evt = new MouseEvent('mousemove', {
        clientX: Math.random() * window.innerWidth,
        clientY: Math.random() * window.innerHeight,
        bubbles: true
    });
    document.dispatchEvent(evt);
})()
"""


def is_cloudflare_present(sb) -> bool:
    """检测 Cloudflare/Turnstile 是否存在"""
    try:
        # 优先使用 Turnstile widget 自身的元素检测（更精准）
        result = sb.execute_script("""
        (function(){
            // IceHost 的 Turnstile 直接嵌入主页面，检测关键元素
            if (document.querySelector('label.dxeA5')) return true;
            if (document.querySelector('span.hHMFo6')) return true;
            if (document.querySelector('span.YFbSK8')) return true;  // "请验证您是真人"
            if (document.getElementById('KwOf6')) return true;        // "正在验证…"
            if (document.getElementById('OiYF0')) return true;        // "成功！"
            if (document.getElementById('iKdh9')) return true;         // "验证失败"
            // 传统 iframe 嵌入场景
            if (document.querySelector('iframe[src*="challenges.cloudflare.com"]')) return true;
            if (document.querySelector('iframe[src*="turnstile"]')) return true;
            // cf-turnstile-response 隐藏输入框
            if (document.querySelector('input[name="cf-turnstile-response"]')) return true;
            return false;
        })()
        """)
        if result:
            return True
        # 备用：页面源码关键词检测
        src = (sb.get_page_source() or "").lower()
        return any(x in src for x in _CF_INDICATORS)
    except Exception:
        return False


def is_turnstile_solved(sb) -> bool:
    """检测 Turnstile 是否已通过验证（使用 widget 自身状态元素，更精准）"""
    try:
        result = sb.execute_script("""
        (function(){
            // 1. 最权威：成功状态容器 #UtClV5 可见（display 不是 none）
            var successBox = document.getElementById('UtClV5');
            if (successBox) {
                var s = window.getComputedStyle(successBox);
                if (s.display !== 'none' && s.visibility !== 'hidden') return true;
            }
            // 2. 成功文字 #OiYF0 可见
            var successText = document.getElementById('OiYF0');
            if (successText) {
                var s2 = window.getComputedStyle(successText);
                if (s2.display !== 'none' && successText.textContent.includes('成功')) return true;
            }
            // 3. cf-turnstile-response 已有值
            var i = document.querySelector('input[name="cf-turnstile-response"]');
            if (i && i.value && i.value.length > 20) return true;
            return false;
        })()
        """)
        return bool(result)
    except Exception:
        return False


def get_turnstile_status(sb) -> str:
    """获取 Turnstile 当前状态：waiting / verifying / success / failed / expired / unknown"""
    try:
        result = sb.execute_script("""
        (function(){
            function isVisible(el) {
                if (!el) return false;
                var s = window.getComputedStyle(el);
                return s.display !== 'none' && s.visibility !== 'hidden';
            }
            // 成功
            if (isVisible(document.getElementById('UtClV5'))) return 'success';
            // 失败
            if (isVisible(document.getElementById('quFo1'))) return 'failed';
            // 过期
            if (isVisible(document.getElementById('pxku5')) || isVisible(document.getElementById('PZKC2'))) return 'expired';
            // 验证中
            if (isVisible(document.getElementById('PwDu3'))) return 'verifying';
            // 等待点击（初始状态：请验证您是真人）
            if (isVisible(document.getElementById('KYRAp1'))) return 'waiting';
            // 检测到 label.dxeA5 但状态容器都不可见
            if (document.querySelector('label.dxeA5')) return 'waiting';
            return 'unknown';
        })()
        """)
        return result or 'unknown'
    except Exception:
        return 'unknown'


def _cf_wait_silent(sb, timeout: int = 30) -> bool:
    log("🔍 策略1: 静默等待 Cloudflare 自动通过...")
    start = time.time()
    while time.time() - start < timeout:
        if not is_cloudflare_present(sb) or is_turnstile_solved(sb):
            log("✅ 静默通过")
            return True
        time.sleep(1)
    log("⚠️ 静默等待超时")
    return False


def _cf_uc_gui_captcha(sb, max_attempts: int = 3) -> bool:
    log("🔍 策略2: SeleniumBase uc_gui_click_captcha...")
    for attempt in range(max_attempts):
        if is_turnstile_solved(sb) or not is_cloudflare_present(sb):
            log(f"✅ 通过（第 {attempt + 1} 次）")
            return True
        try:
            sb.uc_gui_click_captcha()
            time.sleep(random.uniform(3, 6))
        except Exception as e:
            log(f"⚠️ uc_gui_click_captcha 出错: {e}")
            time.sleep(2)
    log("❌ uc_gui_click_captcha 策略失败")
    return False


def _cf_xdotool_click(sb, max_attempts: int = 6) -> bool:
    log("🔍 备用策略1: xdotool 物理点击 Turnstile 复选框...")
    try:
        sb.execute_script(_EXPAND_JS)
    except Exception:
        pass
    time.sleep(0.5)
    for attempt in range(max_attempts):
        status = get_turnstile_status(sb)
        if status == 'success' or is_turnstile_solved(sb):
            log(f"✅ 通过（第 {attempt + 1} 次）状态: {status}")
            return True
        try:
            coords = sb.execute_script(_COORDS_JS)
        except Exception:
            coords = None
        if coords:
            ax, ay = screen_to_abs(sb, coords["cx"], coords["cy"])
            log(f"🖱️  点击 Turnstile ({ax}, {ay}) 第{attempt+1}次 (状态: {status})")
            xdotool_click(ax, ay)
        else:
            log(f"⚠️ 无法定位 Turnstile 坐标 (状态: {status})")
        for _ in range(8):
            time.sleep(0.5)
            status = get_turnstile_status(sb)
            if status == 'success' or is_turnstile_solved(sb):
                log(f"✅ 通过（第 {attempt + 1} 次）状态: {status}")
                return True
    log("❌ xdotool 策略失败")
    return False


def _cf_seleniumbase_click(sb, max_attempts: int = 5) -> bool:
    log("🔍 备用策略: SeleniumBase 原生点击 iframe...")
    for attempt in range(max_attempts):
        if is_turnstile_solved(sb):
            log(f"✅ 通过（第 {attempt + 1} 次）")
            return True
        try:
            iframes = sb.find_elements(_TURNSTILE_IFRAME_SEL)
            for iframe in iframes:
                try:
                    iframe.click()
                    log("🖱️  SeleniumBase 点击 iframe")
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(2)
    log("❌ SeleniumBase 点击策略失败")
    return False


def _cf_js_click_all(sb, max_attempts: int = 3) -> bool:
    log("🔍 备用策略2: JS 遍历点击所有可疑元素...")
    for attempt in range(max_attempts):
        status = get_turnstile_status(sb)
        if status == 'success' or is_turnstile_solved(sb):
            log(f"✅ 通过（第 {attempt + 1} 次）")
            return True
        try:
            result = sb.execute_script(_JS_CLICK_ALL)
            log(f"   JS 点击返回: {result}")
        except Exception as e:
            log(f"   JS 点击异常: {e}")
        for _ in range(6):
            time.sleep(1)
            status = get_turnstile_status(sb)
            if status == 'success' or is_turnstile_solved(sb):
                log(f"✅ 通过（第 {attempt + 1} 次）")
                return True
    log("❌ JS 点击策略失败")
    return False


def _cf_random_mouse(sb, duration: int = 10) -> bool:
    log("🔍 策略6: 随机鼠标移动模拟真人行为...")
    start = time.time()
    while time.time() - start < duration:
        if is_turnstile_solved(sb) or not is_cloudflare_present(sb):
            log("✅ 随机移动中通过验证")
            return True
        try:
            sb.execute_script(_MOUSE_MOVE_JS)
        except Exception:
            pass
        time.sleep(0.3)
    log("❌ 随机移动策略失败")
    return False


def solve_cloudflare(sb) -> bool:
    """
    通过 Cloudflare 验证
    主策略: uc_open_with_reconnect + uc_gui_click_captcha（SeleniumBase 推荐方式）
    备用策略: xdotool / JS点击 / 随机鼠标
    """
    if not is_cloudflare_present(sb):
        log("✅ 未检测到 Cloudflare 验证")
        return True

    status = get_turnstile_status(sb)
    log(f"🔒 检测到 Cloudflare 验证（当前状态: {status}），开始尝试通过...")

    # ===== 主策略: uc_open_with_reconnect + uc_gui_click_captcha =====
    # uc_open_with_reconnect 会在打开页面后断开驱动连接（避免 CDP 被检测），
    # 等待 reconnect_time 秒后重新连接 —— 这是 SeleniumBase 通过 Cloudflare 的关键
    for attempt in range(4):
        reconnect_time = 4 + attempt * 2  # 递增: 4, 6, 8, 10 秒
        log(f"\n▶️  主策略第 {attempt+1}/4 次 (reconnect={reconnect_time}s)")
        try:
            # 获取当前 URL，用 uc_open_with_reconnect 重新打开
            current_url = sb.get_current_url()
            sb.uc_open_with_reconnect(current_url, reconnect_time=reconnect_time)
            time.sleep(2)

            # 重连后检查状态
            status = get_turnstile_status(sb)
            log(f"   重连后状态: {status}")
            if status == 'success' or is_turnstile_solved(sb):
                log(f"✅ 重连后 Turnstile 已自动通过（第 {attempt+1} 次）")
                return True
            if not is_cloudflare_present(sb):
                log(f"✅ 重连后 Cloudflare 已自动通过（第 {attempt+1} 次）")
                return True

            # 状态为 waiting（等待点击）时，激活窗口并点击
            if status in ('waiting', 'unknown', 'verifying'):
                # 激活浏览器窗口（uc_gui_click_captcha 需要窗口在前台）
                _activate_window()
                time.sleep(0.5)

                log(f"🖱️  调用 uc_gui_click_captcha()（第 {attempt+1} 次）")
                sb.uc_gui_click_captcha()
                time.sleep(random.uniform(4, 7))

                # 检查状态变化
                new_status = get_turnstile_status(sb)
                log(f"   点击后状态: {new_status}")
                if new_status == 'success' or is_turnstile_solved(sb):
                    log(f"✅ 点击后 Turnstile 已通过（第 {attempt+1} 次）")
                    return True
                if new_status == 'verifying':
                    log("   正在验证中，继续等待...")
                    for _ in range(10):
                        time.sleep(1)
                        if get_turnstile_status(sb) == 'success' or is_turnstile_solved(sb):
                            log(f"✅ 验证中转为成功（第 {attempt+1} 次）")
                            return True
        except Exception as e:
            log(f"⚠️ 主策略第 {attempt+1} 次异常: {e}")
        time.sleep(2)

    log("⚠️ 主策略未能通过，尝试备用策略...")

    # ===== 备用策略 1: xdotool 物理点击 =====
    if _cf_xdotool_click(sb):
        log("🎉 备用策略 [xdotool物理点击] 成功通过！")
        return True

    # ===== 备用策略 2: JS 遍历点击 =====
    if _cf_js_click_all(sb):
        log("🎉 备用策略 [JS遍历点击] 成功通过！")
        return True

    # ===== 备用策略 3: 随机鼠标移动 =====
    if _cf_random_mouse(sb):
        log("🎉 备用策略 [随机鼠标移动] 成功通过！")
        return True

    log("❌ 所有策略均未能通过 Cloudflare 验证")
    return False


# ============================================================
#  登录模块（Cookie / 账号密码 / Discord OAuth + Cookie 持久化）
# ============================================================

LOGIN_METHOD_COOKIE   = "Cookie"
LOGIN_METHOD_PASSWORD = "账号密码"
LOGIN_METHOD_DISCORD  = "Discord OAuth"

_current_login_method = LOGIN_METHOD_COOKIE
STATE_RE = re.compile(r"[?&]state=([^&]+)")

# IceHost 登录表单用户名输入框的多种可能选择器
_USERNAME_SELECTORS = [
    'input[name="username"]',
    'input[name="email"]',
    'input[name="Email"]',
    'input[type="email"]',
    'input[type="text"]',
]


def get_login_method() -> str:
    return _current_login_method


def get_cookie_value(sb, name: str):
    try:
        for c in sb.get_cookies():
            if c.get('name') == name:
                value = c.get('value')
                expiry_ts = c.get('expiry')
                expiry_dt = datetime.fromtimestamp(expiry_ts) if expiry_ts else None
                return value, expiry_dt
    except Exception:
        pass
    return None, None


def should_update_cookie(new_value, old_value, expiry_dt) -> bool:
    if new_value is None:
        return False
    if new_value != old_value:
        return True
    if expiry_dt:
        remaining = (expiry_dt - datetime.now()).total_seconds()
        if remaining < Config.COOKIE_UPDATE_THRESHOLD_DAYS * 24 * 3600:
            return True
    return False


def update_github_secret(secret_name: str, new_value: str) -> bool:
    if not new_value:
        log(f"⚠️  跳过更新 {secret_name}：新值为空")
        return False
    masked = new_value[:4] + "..." + new_value[-4:] if len(new_value) > 8 else "***"
    log(f"🔄 更新 GitHub Secret: {secret_name} (新值: {masked})")
    try:
        env = os.environ.copy()
        if Config.GH_TOKEN:
            env["GH_TOKEN"] = Config.GH_TOKEN
        proc = subprocess.run(["gh", "secret", "set", secret_name, "--body", new_value],
                              capture_output=True, text=True, timeout=30, check=False, env=env)
        if proc.returncode == 0:
            log(f"✅ {secret_name} 更新成功")
            return True
        log(f"❌ 更新失败: {proc.stderr.strip()}")
        return False
    except Exception as e:
        log(f"❌ 异常: {e}")
        return False


def save_cookie_to_github(sb) -> bool:
    if not Config.GH_TOKEN or not Config.GH_SECRET_NAME:
        log("ℹ️  未配置 GH_TOKEN 或 GH_SECRET_NAME，跳过自动更新 Cookie")
        return False
    new_value, expiry_dt = get_cookie_value(sb, Config.COOKIE_NAME)
    if should_update_cookie(new_value, Config.COOKIE_VALUE, expiry_dt):
        return update_github_secret(Config.GH_SECRET_NAME, new_value)
    log("✅ Cookie 无需更新")
    return True


def login_by_cookie(sb) -> bool:
    global _current_login_method
    if not Config.COOKIE_VALUE:
        log("ℹ️  未配置 Cookie，跳过 Cookie 登录")
        return False
    log("🍪 尝试 Cookie 登录...")
    try:
        # 使用 uc_open_with_reconnect 打开站点（UC 模式，更好地处理 Cloudflare）
        # uc_open_with_reconnect 会断开驱动连接避免被 Cloudflare 检测
        sb.uc_open_with_reconnect(Config.BASE_URL, reconnect_time=4)
        time.sleep(2)

        # 如果首次打开就遇到 Cloudflare，先解决
        if is_cloudflare_present(sb):
            log("🔒 首次打开遇到 Cloudflare，尝试通过...")
            if not solve_cloudflare(sb):
                log("❌ 首次打开时 Cloudflare 验证失败")
                return False
            time.sleep(2)

        # 设置 Cookie（带完整属性）
        cookie_domain = Config.COOKIE_DOMAIN or urllib.parse.urlparse(Config.BASE_URL).hostname
        sb.add_cookie({
            "name": Config.COOKIE_NAME,
            "value": Config.COOKIE_VALUE,
            "domain": cookie_domain,
            "path": "/",
            "secure": True,
            "httpOnly": True,
        })
        log(f"✅ Cookie 已设置: {Config.COOKIE_NAME} (domain={cookie_domain})")

        # 使用 uc_open_with_reconnect 重新加载页面让 Cookie 生效
        # 不要用 sb.refresh() —— uc_open_with_reconnect 才能正确处理 Cloudflare
        sb.uc_open_with_reconnect(Config.BASE_URL, reconnect_time=4)
        time.sleep(3)

        # 处理 Cookie 生效后可能出现的 Cloudflare
        if is_cloudflare_present(sb):
            log("🔒 Cookie 设置后遇到 Cloudflare，尝试通过...")
            if not solve_cloudflare(sb):
                log("❌ Cookie 登录时 Cloudflare 验证失败")
                return False
            time.sleep(2)

        # 检查是否仍在登录页
        current_url = sb.get_current_url()
        log(f"📝 当前URL: {current_url}")

        # 等待可能的 Laravel remember_web 重定向
        for _ in range(10):
            url_lower = sb.get_current_url().lower()
            if "login" not in url_lower and Config.LOGIN_PATH not in sb.get_current_url():
                break
            time.sleep(1)

        current_url = sb.get_current_url()
        url_lower = current_url.lower()

        # 检查是否成功（URL 不含 login 且页面没有登录表单）
        has_login_form = False
        try:
            has_login_form = sb.execute_script("""
                return !!(document.querySelector('input[name="username"]') ||
                          document.querySelector('input[name="email"]') ||
                          document.querySelector('input[name="password"]') ||
                          document.querySelector('input[type="password"]'));
            """)
        except Exception:
            pass

        if "login" not in url_lower and Config.LOGIN_PATH not in current_url and not has_login_form:
            _current_login_method = LOGIN_METHOD_COOKIE
            log("✅ Cookie 登录成功")
            return True

        log(f"❌ Cookie 登录失败，仍在登录页: {current_url}")
        sb.save_screenshot("cookie_login_fail.png")
        return False
    except Exception as e:
        log(f"❌ Cookie 登录异常: {e}")
        return False


def _find_username_input(sb) -> str:
    """在登录页查找用户名输入框，返回命中的选择器；找不到返回空串"""
    for sel in _USERNAME_SELECTORS:
        try:
            sb.wait_for_element_present(sel, timeout=3)
            log(f"✅ 找到用户名输入框: {sel}")
            return sel
        except Exception:
            continue
    return ""


def login_by_password(sb) -> bool:
    global _current_login_method
    if not Config.EMAIL or not Config.PASSWORD:
        log("ℹ️  未配置账号密码，跳过密码登录")
        return False
    log("🔑 尝试账号密码登录...")
    try:
        log(f"🌐 打开登录页: {Config.login_url()}")
        sb.uc_open_with_reconnect(Config.login_url(), reconnect_time=6)
        time.sleep(3)
        if is_cloudflare_present(sb):
            log("🔒 遇到 Cloudflare，尝试通过...")
            if not solve_cloudflare(sb):
                log("❌ 登录页 Cloudflare 验证失败")
                return False
            time.sleep(2)

        # 多选择器查找用户名输入框（IceHost 用 input[name="username"]）
        username_sel = _find_username_input(sb)
        if not username_sel:
            log("❌ 页面未加载出登录表单（未找到用户名输入框）")
            sb.save_screenshot("login_load_fail.png")
            return False

        # 处理可能的 Cookie 横幅
        try:
            for btn in sb.find_elements("button"):
                if "Accept" in (btn.text or ""):
                    btn.click()
                    time.sleep(0.5)
                    break
        except Exception:
            pass

        log("📧 填写用户名/邮箱...")
        js_fill_input(sb, username_sel, Config.EMAIL)
        time.sleep(0.3)
        log("🔑 填写密码...")
        js_fill_input(sb, 'input[name="password"]', Config.PASSWORD)
        time.sleep(1)

        # 提交前再次检查 Cloudflare
        if is_cloudflare_present(sb):
            solve_cloudflare(sb)
            time.sleep(1)

        log("🖱️  提交登录表单...")
        try:
            sb.press_keys('input[name="password"]', '\n')
        except Exception:
            try:
                sb.click('button[type="submit"]')
            except Exception:
                pass

        log("⏳ 等待登录跳转...")
        for _ in range(20):
            time.sleep(1)
            cur_url = sb.get_current_url().split('?')[0].lower()
            if Config.LOGIN_PATH not in cur_url and "login" not in cur_url:
                break

        cur_url = sb.get_current_url().lower()
        if "login" in cur_url:
            log("❌ 登录失败，仍在登录页")
            sb.save_screenshot("login_failed.png")
            return False
        _current_login_method = LOGIN_METHOD_PASSWORD
        log(f"✅ 账号密码登录成功！(URL: {sb.get_current_url()})")
        return True
    except Exception as e:
        log(f"❌ 密码登录异常: {e}")
        sb.save_screenshot("login_error.png")
        return False


def _capture_discord_state(sb) -> str:
    log("🔎 获取 Discord OAuth state...")
    discord_login_url = f"{Config.BASE_URL}{Config.DISCORD_LOGIN_PATH}"
    sb.uc_open_with_reconnect(discord_login_url, reconnect_time=4)
    time.sleep(2)
    url = sb.get_current_url()
    if "discord.com" not in url:
        log(f"⚠️  未跳转到 Discord，当前 URL：{url}")
        return ""
    m = STATE_RE.search(url)
    if not m:
        log(f"❌ 未能解析出 state，当前 URL：{url}")
        return ""
    state = urllib.parse.unquote(m.group(1))
    log(f"✅ 已捕获 state")
    return state


def _discord_authorize(state: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": Config.DISCORD_CLIENT_ID, "response_type": "code",
        "redirect_uri": Config.DISCORD_REDIRECT_URI, "scope": "identify email guilds",
        "state": state,
    })
    authorize_url = f"https://discord.com/api/v9/oauth2/authorize?{query}"
    dc_token = Config.DISCORD_TOKEN
    if "," in dc_token:
        dc_token = dc_token.split(",", 1)[-1].strip()
    headers = {
        "accept": "*/*", "authorization": dc_token, "content-type": "application/json",
        "origin": "https://discord.com",
        "referer": f"https://discord.com/oauth2/authorize?{query}",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "x-discord-locale": "zh-CN",
    }
    body = json.dumps({
        "permissions": "0", "authorize": True, "integration_type": 0,
        "location_context": {"guild_id": "10000", "channel_id": "10000", "channel_type": 10000},
    })
    proxies = {"http": Config.PROXY_SERVER, "https": Config.PROXY_SERVER} if Config.IS_PROXY else None
    try:
        resp = requests.post(authorize_url, headers=headers, data=body, proxies=proxies, timeout=20)
        if resp.status_code != 200:
            log(f"❌ Discord OAuth2 授权失败: HTTP {resp.status_code}")
            return ""
        location = resp.json().get("location", "")
        if not location:
            log("❌ 授权响应中未找到 location")
            return ""
        log(f"✅ 拿到回调 URL")
        return location
    except Exception as e:
        log(f"❌ Discord OAuth2 异常: {e}")
        return ""


def login_by_discord(sb) -> bool:
    global _current_login_method
    if not Config.DISCORD_TOKEN or not Config.DISCORD_CLIENT_ID:
        log("ℹ️  未配置 Discord Token 或 Client ID，跳过 Discord 登录")
        return False
    log("\n🔑 通过 Discord Token 登录...")
    state = _capture_discord_state(sb)
    if not state:
        sb.save_screenshot("login_no_state.png")
        return False
    location = _discord_authorize(state)
    if not location:
        return False
    log("↩️  携带授权码打开回调链接...")
    sb.uc_open_with_reconnect(location, reconnect_time=4)
    time.sleep(3)
    url = sb.get_current_url()
    if "/error/banned" in url:
        log("🚫 账号已被封禁")
        sb.save_screenshot("login_banned.png")
        return False
    base_host = urllib.parse.urlparse(Config.BASE_URL).hostname
    if base_host not in url:
        log(f"❌ 回调后未跳转至目标站点")
        sb.save_screenshot("login_no_redirect.png")
        return False
    for _ in range(30):
        url = sb.get_current_url()
        path = urllib.parse.urlparse(url).path
        if base_host in url and path != Config.LOGIN_PATH and not path.startswith(Config.DISCORD_LOGIN_PATH):
            log(f"✅ Discord OAuth 登录成功！")
            _current_login_method = LOGIN_METHOD_DISCORD
            return True
        time.sleep(0.5)
    log("❌ 登录超时")
    sb.save_screenshot("login_timeout.png")
    return False


def do_login(sb) -> bool:
    log("\n" + "#" * 25)
    log("  开始自动登录")
    log("#" * 25)
    for name, method in [("Cookie 登录", login_by_cookie),
                         ("账号密码登录", login_by_password),
                         ("Discord OAuth 登录", login_by_discord)]:
        log(f"\n▶️  尝试: {name}")
        try:
            if method(sb):
                log(f"\n🎉 [{name}] 成功！")
                return True
        except Exception as e:
            log(f"⚠️  [{name}] 异常: {e}")
        time.sleep(1)
    log("\n❌ 所有登录方式均失败")
    return False


# ============================================================
#  Telegram 通知（单一最终通知）
# ============================================================

def send_telegram_message(text: str) -> bool:
    if not Config.TG_BOT_TOKEN or not Config.TG_CHAT_ID:
        log("ℹ️  Telegram 未配置，跳过通知")
        return False
    url = f"https://api.telegram.org/bot{Config.TG_BOT_TOKEN}/sendMessage"
    proxies = {"http": Config.PROXY_SERVER, "https": Config.PROXY_SERVER} if Config.IS_PROXY else None
    try:
        r = requests.post(url, json={"chat_id": Config.TG_CHAT_ID, "text": text}, timeout=10, proxies=proxies)
        if r.status_code == 200:
            log("📩 Telegram 通知发送成功！")
            return True
        log(f"⚠️  Telegram 发送失败: {r.text}")
        return False
    except Exception as e:
        log(f"⚠️  Telegram 发送异常: {e}")
        return False


def build_notification(status: str, extra: str = "", error: str = "",
                       expiry_date: str = "", login_method: str = "") -> str:
    masked_email = mask_email(Config.EMAIL) if Config.EMAIL else "未填写"
    lines = [f"{Config.PLATFORM_FLAG} {Config.PLATFORM_NAME} 续期通知", "", f"{status}",
             f"👤 登录账户: {masked_email}"]
    if login_method:
        lines.append(f"🔐 登录方式: {login_method}")
    if expiry_date:
        lines.append(f"📅 到期时间: {expiry_date}")
    if extra:
        lines.append(extra)
    if error:
        lines.append(f"⚠️  错误信息: {error}")
    lines.append(f"⏱️  执行时间: {beijing_time_str()}")
    return "\n".join(lines)


def notify_final(status: str, login_method: str = "", extra: str = "",
                 error: str = "", expiry_date: str = ""):
    """单一最终通知：只在脚本结束时发送一次总结通知"""
    send_telegram_message(build_notification(status, extra=extra, error=error,
                                             expiry_date=expiry_date, login_method=login_method))


# ============================================================
#  续期动作（IceHost 专用）
# ============================================================

def _parse_expiry_date(date_str: str):
    """解析到期时间字符串，返回 datetime 对象"""
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _is_ip_blocked(sb) -> bool:
    """检测 IceHost IP 封锁（页面标题包含 Block）"""
    try:
        title = sb.execute_script("return document.title || '';") or ""
        if "block" in title.lower():
            log(f"🚫 检测到 IP 被封锁（页面标题: {title}）")
            return True
    except Exception:
        pass
    return False


def _find_renew_buttons(sb) -> list:
    """
    全页搜索续期按钮（通过 span / button 文本匹配）
    匹配文本: Przedłuż serwer / Extend Server / Przedłuż / Extend
    返回: [{text, ...}]
    """
    js = """
    (function(){
        var results = [];
        var matchTexts = ['przedłuż serwer', 'extend server', 'przedłuż', 'extend'];
        var seen = {};
        // 1. 搜索所有 span（IceHost 按钮文本常在 span 里）
        var spans = document.querySelectorAll('span');
        for (var i = 0; i < spans.length; i++) {
            var txt = (spans[i].textContent || '').toLowerCase().trim();
            for (var j = 0; j < matchTexts.length; j++) {
                if (txt === matchTexts[j] || (txt.length < 40 && txt.includes(matchTexts[j]))) {
                    var key = txt;
                    if (!seen[key]) {
                        seen[key] = true;
                        results.push({text: spans[i].textContent.trim(), type: 'span'});
                    }
                    break;
                }
            }
        }
        // 2. 搜索所有 button / a / [role=button]
        var btns = document.querySelectorAll('button, a, [role="button"]');
        for (var k = 0; k < btns.length; k++) {
            var btxt = (btns[k].textContent || '').toLowerCase().trim();
            for (var m = 0; m < matchTexts.length; m++) {
                if (btxt === matchTexts[m] || (btxt.length < 40 && btxt.includes(matchTexts[m]))) {
                    var bkey = btxt;
                    if (!seen[bkey]) {
                        seen[bkey] = true;
                        results.push({text: btns[k].textContent.trim(), type: 'button'});
                    }
                    break;
                }
            }
        }
        return results;
    })()
    """
    try:
        return sb.execute_script(js) or []
    except Exception as e:
        log(f"❌ 查找续期按钮失败: {e}")
        return []


def _click_button_by_text(sb, texts: list, timeout: int = 10) -> bool:
    """
    通过文本匹配点击按钮（倒序遍历，优先点击后出现的按钮，通常是确认弹窗）
    texts: 文本列表（不区分大小写），命中其一即点击
    """
    start = time.time()
    js_texts = json.dumps([t.lower() for t in texts])
    js = f"""
    (function(){{
        var texts = {js_texts};
        var btns = document.querySelectorAll('button, a, [role="button"], span');
        for (var i = btns.length - 1; i >= 0; i--) {{
            var txt = (btns[i].textContent || '').toLowerCase().trim();
            for (var j = 0; j < texts.length; j++) {{
                if (txt === texts[j] || (txt.length < 60 && txt.includes(texts[j]))) {{
                    var el = btns[i];
                    var clickTarget = el.closest('button, a, [role="button"]') || el;
                    clickTarget.click();
                    return clickTarget.textContent.trim();
                }}
            }}
        }}
        return false;
    }})()
    """
    while time.time() - start < timeout:
        try:
            result = sb.execute_script(js)
            if result:
                log(f"🖱️  已点击按钮: {result}")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# 续期按钮文本（波兰语 / 英语）
_RENEW_BUTTON_TEXTS = ["Przedłuż serwer", "Extend Server", "Przedłuż", "Extend"]
# 确认按钮文本（波兰语 / 英语）
_CONFIRM_BUTTON_TEXTS = [
    "Tak, przedłuż serwer", "Yes, extend server",
    "Tak, przedłuż", "Yes, extend",
]


def _navigate_to_servers(sb) -> bool:
    """导航到服务器列表页面"""
    log("🌐 导航到服务器列表页面...")

    # 方式1：点击侧边栏 Server/Serwery 链接
    js_click_sidebar = """
    (function(){
        var links = document.querySelectorAll('a, [role="link"]');
        for (var i = 0; i < links.length; i++) {
            var txt = (links[i].textContent || '').toLowerCase().trim();
            if (txt.includes('serwer') || txt.includes('server') ||
                txt.includes('serwery') || txt.includes('servers') || txt.includes('moje')) {
                links[i].click();
                return true;
            }
        }
        return false;
    })()
    """
    try:
        if sb.execute_script(js_click_sidebar):
            log("✅ 已点击侧边栏服务器链接")
            time.sleep(3)
            sb.wait_for_ready_state_complete()
            return True
    except Exception:
        pass

    # 方式2：直接访问 BASE_URL 根路径（IceHost 登录后默认就是服务器列表）
    # 使用 uc_open_with_reconnect 避免 Cloudflare 检测
    log("⚠️  侧边栏点击失败，尝试直接访问根路径...")
    try:
        sb.uc_open_with_reconnect(Config.BASE_URL, reconnect_time=4)
        time.sleep(3)
        return True
    except Exception as e:
        log(f"❌ 导航失败: {e}")
        return False


def do_renew(sb) -> tuple:
    """
    IceHost 服务器续期逻辑
    返回: (status, extra_info, expiry_date)
        status: "SUCCESS" | "FAIL"
    """
    log("\n" + "#" * 25)
    log("  开始执行 IceHost 续期动作")
    log("#" * 25)

    # 步骤1：导航到服务器页面
    if not _navigate_to_servers(sb):
        return "FAIL", "无法导航到服务器页面", ""

    # IP 封锁检测（IceHost 封锁 GitHub Actions IP 时页面标题为 "IceHost - Block"）
    if _is_ip_blocked(sb):
        return "FAIL", "IP 被 IceHost 封锁，请配置代理节点（NODE_LINK）后重试", ""

    # 处理可能的 Cloudflare 验证
    if is_cloudflare_present(sb):
        log("🔒 服务器页面遇到 Cloudflare...")
        if not solve_cloudflare(sb):
            return "FAIL", "Cloudflare 验证未通过", ""
        time.sleep(2)
        # 再次检测 IP 封锁
        if _is_ip_blocked(sb):
            return "FAIL", "IP 被 IceHost 封锁，请配置代理节点（NODE_LINK）后重试", ""

    # 步骤2：查找续期按钮（5 次重试，第 3 次刷新页面）
    renew_buttons = []
    for attempt in range(5):
        attempt_num = attempt + 1
        log(f"\n🔍 第 {attempt_num} 次查找续期按钮...")

        # 第 3 次重试时刷新页面
        if attempt_num == 3:
            log("🔄 刷新页面后重试...")
            sb.refresh()
            sb.wait_for_ready_state_complete()
            time.sleep(3)
            if _is_ip_blocked(sb):
                return "FAIL", "IP 被 IceHost 封锁，请配置代理节点（NODE_LINK）后重试", ""
            if is_cloudflare_present(sb):
                solve_cloudflare(sb)
                time.sleep(2)

        renew_buttons = _find_renew_buttons(sb)
        if renew_buttons:
            log(f"✅ 找到 {len(renew_buttons)} 个续期按钮")
            for rb in renew_buttons:
                log(f"  - [{rb.get('type', '')}] {rb.get('text', '')}")
            break

        log(f"⚠️  第 {attempt_num} 次未找到续期按钮")
        # 打印页面标题便于诊断
        try:
            title = sb.execute_script("return document.title || '';")
            log(f"   页面标题: {title}")
        except Exception:
            pass
        if attempt_num < 5:
            time.sleep(3)

    if not renew_buttons:
        log("❌ 5 次重试后仍未找到续期按钮")
        sb.save_screenshot("no_renew_buttons.png")
        if _is_ip_blocked(sb):
            return "FAIL", "IP 被 IceHost 封锁，请配置代理节点（NODE_LINK）后重试", ""
        return "FAIL", "未找到续期按钮（可能页面结构变化或无服务器）", ""

    # 步骤3：逐个点击续期按钮并确认
    renewed_count = 0
    failed_count = 0
    results = []
    total = len(renew_buttons)

    for i, rb in enumerate(renew_buttons):
        btn_text = rb.get("text", "")
        log(f"\n🔄 [{i+1}/{total}] 点击续期按钮: {btn_text}")

        # 点击续期按钮
        if not _click_button_by_text(sb, _RENEW_BUTTON_TEXTS, timeout=5):
            log(f"❌ [{i+1}] 点击续期按钮失败")
            results.append(f"❌ 按钮 {i+1}: 点击失败")
            failed_count += 1
            continue

        log("⏳ 等待确认弹窗...")
        time.sleep(2)

        # 点击确认按钮
        if not _click_button_by_text(sb, _CONFIRM_BUTTON_TEXTS, timeout=10):
            log(f"❌ [{i+1}] 未找到确认按钮")
            results.append(f"❌ 按钮 {i+1}: 确认按钮未找到")
            sb.save_screenshot(f"confirm_fail_{i+1}.png")
            failed_count += 1
            continue

        log("✅ 已点击确认")
        time.sleep(5)

        # 处理可能的 Cloudflare
        if is_cloudflare_present(sb):
            solve_cloudflare(sb)
            time.sleep(2)

        renewed_count += 1
        results.append(f"✅ 按钮 {i+1}: {btn_text} 已续期")

    # 汇总
    log("\n" + "=" * 40)
    log("  续期汇总")
    log("=" * 40)
    log(f"  续期按钮总数: {total} | 成功: {renewed_count} | 失败: {failed_count}")
    for r in results:
        log(f"  {r}")

    extra_info = "\n".join(results)
    if renewed_count > 0:
        return "SUCCESS", extra_info, ""
    return "FAIL", extra_info, ""


# ============================================================
#  清理模块
# ============================================================

def cleanup():
    log("\n🧹 开始清理进程和临时文件...")
    for proc in ["sing-box", "chromedriver", "chrome", "Xvfb", "xvfb-run"]:
        try:
            subprocess.run(["pkill", "-f", proc], stderr=subprocess.DEVNULL)
        except Exception:
            pass
    for f in ["sing-box", "sing-box-config.json", "sing-box.log"]:
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception:
            pass
    try:
        for f in os.listdir("."):
            if f.endswith(".png"):
                os.remove(f)
    except Exception:
        pass
    log("✅ 清理完成\n")


# ============================================================
#  主流程
# ============================================================

def main():
    print("\n" + "#" * 40)
    print(f"  {Config.PLATFORM_FLAG} {Config.PLATFORM_NAME} 自动续期框架")
    print("#" * 40 + "\n")

    if not Config.validate():
        log("❌ 配置校验失败，请检查环境变量")
        notify_final("❌ 配置校验失败", error="未配置任何登录凭证或 BASE_URL")
        sys.exit(1)

    proxy_started = False

    try:
        if Config.IS_PROXY:
            log(f"🔗 代理模式已启用: {Config.PROXY_SERVER}")
            proxy_started = start_singbox()
            if not proxy_started and Config.NODE_LINK:
                log("⚠️  代理启动失败，将尝试直连")
        else:
            log("🌐 直连模式（未使用代理）")

        try:
            ip = get_current_ip()
            log(f"🎯 当前出口IP: {ip}")
        except Exception as e:
            log(f"⚠️  获取出口 IP 失败: {e}")

        sb_kwargs = {"uc": True, "headless": Config.HEADLESS}
        if Config.IS_PROXY and proxy_started:
            sb_kwargs["proxy"] = Config.PROXY_SERVER

        log(f"🚀 启动浏览器 (headless={Config.HEADLESS})...")

        with SB(**sb_kwargs) as sb:
            # 登录
            if not do_login(sb):
                log("❌ 所有登录方式均失败")
                notify_final("❌ 登录失败", error="所有登录方式（Cookie/账号密码/Discord）均失败")
                sys.exit(1)

            login_method = get_login_method()
            log(f"✅ 登录成功，方式: {login_method}")

            # 执行续期
            status, extra_info, expiry_date = do_renew(sb)

            # 单一最终通知
            if status == "SUCCESS":
                log("🎉 续期成功！")
                notify_final("✅ 续期成功", login_method=login_method,
                             extra=extra_info, expiry_date=expiry_date)
            else:
                log("❌ 续期失败")
                notify_final("❌ 续期失败", login_method=login_method,
                             extra=extra_info, error="详见下方明细")

            # 检查并更新 Cookie 到 GitHub Secrets
            if Config.GH_TOKEN and Config.COOKIE_NAME:
                log("\n🔄 检查并更新 Cookie...")
                save_cookie_to_github(sb)

            log("\n🏁 脚本执行完毕")
            sys.exit(0 if status != "FAIL" else 1)

    except KeyboardInterrupt:
        log("\n⚠️  用户中断")
        notify_final("⚠️ 用户中断", error="用户手动中断执行")
        sys.exit(130)
    except Exception as e:
        log(f"\n❌ 未捕获的异常: {e}")
        import traceback
        traceback.print_exc()
        try:
            notify_final("❌ 脚本异常", error=f"未捕获异常: {e}")
        except Exception:
            pass
        sys.exit(1)
    finally:
        if proxy_started:
            stop_singbox()
        cleanup()


if __name__ == "__main__":
    main()
