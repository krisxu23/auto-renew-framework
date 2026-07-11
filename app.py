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
#  配置管理
# ============================================================

class Config:
    # 目标站点
    BASE_URL        = os.environ.get("BASE_URL", "")
    LOGIN_PATH      = os.environ.get("LOGIN_PATH", "").strip() or "/auth/login"
    DASHBOARD_PATH  = os.environ.get("DASHBOARD_PATH", "").strip() or "/"

    # 账号密码登录
    EMAIL    = os.environ.get("EMAIL", "")
    PASSWORD = os.environ.get("PASSWORD", "")

    # Cookie 登录（如果 COOKIE_NAME 为空，使用 IceHost 默认值）
    COOKIE_NAME   = os.environ.get("COOKIE_NAME", "").strip() or "remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d"
    COOKIE_VALUE  = os.environ.get("COOKIE_VALUE", "")
    COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", "").strip() or "dash.icehost.pl"

    # Discord OAuth 登录
    DISCORD_TOKEN        = os.environ.get("DISCORD_TOKEN", "")
    DISCORD_CLIENT_ID    = os.environ.get("DISCORD_CLIENT_ID", "")
    DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "")
    DISCORD_LOGIN_PATH   = os.environ.get("DISCORD_LOGIN_PATH", "/login/discord")

    # Cookie 自动更新到 GitHub Secrets
    GH_TOKEN      = os.environ.get("GH_TOKEN", "")
    GH_SECRET_NAME = os.environ.get("GH_SECRET_NAME", "COOKIE_VALUE")

    # Telegram 通知
    TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
    TG_CHAT_ID   = os.environ.get("TG_CHAT_ID", "")

    # 代理
    IS_PROXY     = os.environ.get("IS_PROXY", "false").lower() == "true"
    PROXY_SERVER = os.environ.get("PROXY_SERVER", "").strip() or "http://127.0.0.1:1080"
    NODE_LINK    = os.environ.get("NODE_LINK", "")

    # 浏览器
    HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

    # 通知显示
    PLATFORM_NAME  = os.environ.get("PLATFORM_NAME", "Unknown Platform")
    PLATFORM_FLAG  = os.environ.get("PLATFORM_FLAG", "🏳️")

    # Cookie 更新阈值（天）
    COOKIE_UPDATE_THRESHOLD_DAYS = int(os.environ.get("COOKIE_UPDATE_THRESHOLD_DAYS", "3"))

    @classmethod
    def validate(cls) -> bool:
        has_credential = False
        if cls.COOKIE_VALUE:
            has_credential = True
            log(f"✅ 配置了 Cookie 登录凭证 (Cookie名: {cls.COOKIE_NAME})")
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
#  代理配置（sing-box，支持 VMess / VLESS / SS / Trojan / 订阅链接）
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
    if ":" in rest:
        server, port = rest.split(":", 1)
        return {"v": "2", "ps": "trojan", "add": server, "port": port,
                "id": password, "type": "trojan"}
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
            outbounds.append({"type": "vless", "tag": tag,
                "server": node.get("add", ""), "server_port": int(node.get("port", 0)),
                "uuid": node.get("id", ""), "flow": node.get("flow", ""),
                "tls": {"enabled": node.get("security", "") == "tls",
                    "server_name": node.get("sni", ""),
                    "utls": {"enabled": True, "fingerprint": node.get("fp", "chrome")}}
                    if node.get("security", "") == "tls" or node.get("flow", "") else None,
                "transport": {}})
            if node.get("pbk"):
                outbounds[-1]["packet_encoding"] = "xudp"
                outbounds[-1]["tls"]["reality"] = {"enabled": True,
                    "public_key": node.get("pbk", ""), "short_id": node.get("sid", "")}
        elif ntype in ("shadowsocks", "ss"):
            outbounds.append({"type": "shadowsocks", "tag": tag,
                "server": node.get("add", ""), "server_port": int(node.get("port", 0)),
                "method": node.get("method", "aes-256-gcm"),
                "password": node.get("id", node.get("password", ""))})
        elif ntype == "trojan":
            outbounds.append({"type": "trojan", "tag": tag,
                "server": node.get("add", ""), "server_port": int(node.get("port", 0)),
                "password": node.get("id", node.get("password", "")),
                "tls": {"enabled": True, "server_name": node.get("add", "")}})
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

def start_singbox() -> bool:
    if not Config.NODE_LINK:
        log("ℹ️  未配置 NODE_LINK，跳过代理启动")
        return False
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
    try:
        subprocess.run(["pkill", "-f", "sing-box"], stderr=subprocess.DEVNULL)
        time.sleep(1)
        log("🧹 sing-box 已停止")
    except Exception:
        pass

# ============================================================
#  Cloudflare 验证（6 种策略逐一尝试）
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
    var iframes = document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        var src = iframes[i].src || '';
        if (src.includes('cloudflare') || src.includes('turnstile') || src.includes('challenges')) {
            var r = iframes[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2)};
        }
    }
    var inp = document.querySelector('input[name="cf-turnstile-response"]');
    if (inp) {
        var p = inp.parentElement;
        for (var j = 0; j < 5; j++) {
            if (!p) break;
            var r = p.getBoundingClientRect();
            if (r.width > 100 && r.height > 30)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2)};
            p = p.parentElement;
        }
    }
    return null;
})()
"""

_JS_CLICK_ALL = """
(function(){
    var iframes = document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        if (iframes[i].src && iframes[i].src.includes('challenges.cloudflare.com')) {
            iframes[i].click();
            iframes[i].dispatchEvent(new MouseEvent('click', {bubbles:true}));
        }
    }
    var labels = document.querySelectorAll('label');
    for (var j = 0; j < labels.length; j++) {
        var txt = (labels[j].textContent || '').toLowerCase();
        if (txt.includes('robot') || txt.includes('captcha') || txt.includes('verify'))
            labels[j].click();
    }
    var cbs = document.querySelectorAll('input[type="checkbox"]');
    for (var k = 0; k < cbs.length; k++) {
        if (!cbs[k].disabled) {
            cbs[k].click();
            cbs[k].dispatchEvent(new MouseEvent('click', {bubbles:true}));
        }
    }
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
    try:
        src = (sb.get_page_source() or "").lower()
        return any(x in src for x in _CF_INDICATORS)
    except Exception:
        return False

def is_turnstile_solved(sb) -> bool:
    try:
        result = sb.execute_script("""
        (function(){
            var i = document.querySelector('input[name="cf-turnstile-response"]');
            return !!(i && i.value && i.value.length > 20);
        })()
        """)
        return bool(result)
    except Exception:
        return False

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
    log("🔍 策略3: xdotool 物理点击 Turnstile 复选框...")
    try:
        sb.execute_script(_EXPAND_JS)
    except Exception:
        pass
    time.sleep(0.5)
    for attempt in range(max_attempts):
        if is_turnstile_solved(sb):
            log(f"✅ 通过（第 {attempt + 1} 次）")
            return True
        try:
            coords = sb.execute_script(_COORDS_JS)
        except Exception:
            coords = None
        if coords:
            ax, ay = screen_to_abs(sb, coords["cx"], coords["cy"])
            log(f"🖱️  点击 Turnstile ({ax}, {ay}) 第{attempt+1}次")
            xdotool_click(ax, ay)
        else:
            log("⚠️ 无法定位 Turnstile 坐标")
        for _ in range(8):
            time.sleep(0.5)
            if is_turnstile_solved(sb):
                log(f"✅ 通过（第 {attempt + 1} 次）")
                return True
    log("❌ xdotool 策略失败")
    return False

def _cf_seleniumbase_click(sb, max_attempts: int = 5) -> bool:
    log("🔍 策略4: SeleniumBase 原生点击 iframe...")
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
    log("🔍 策略5: JS 遍历点击所有可疑元素...")
    for attempt in range(max_attempts):
        if is_turnstile_solved(sb):
            log(f"✅ 通过（第 {attempt + 1} 次）")
            return True
        try:
            sb.execute_script(_JS_CLICK_ALL)
        except Exception:
            pass
        for _ in range(6):
            time.sleep(1)
            if is_turnstile_solved(sb):
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
    """多策略逐一尝试通过 Cloudflare 验证"""
    if not is_cloudflare_present(sb):
        log("✅ 未检测到 Cloudflare 验证")
        return True
    log("🔒 检测到 Cloudflare 验证，开始多策略尝试...")
    strategies = [
        ("静默等待",            _cf_wait_silent),
        ("uc_gui_click_captcha", _cf_uc_gui_captcha),
        ("xdotool物理点击",     _cf_xdotool_click),
        ("SeleniumBase点击",    _cf_seleniumbase_click),
        ("JS遍历点击",          _cf_js_click_all),
        ("随机鼠标移动",         _cf_random_mouse),
    ]
    for name, func in strategies:
        log(f"\n▶️  尝试策略: {name}")
        try:
            if func(sb):
                log(f"\n🎉 策略 [{name}] 成功通过！")
                return True
        except Exception as e:
            log(f"⚠️ 策略 [{name}] 异常: {e}")
        time.sleep(1)
    log("\n❌ 所有策略均未能通过 Cloudflare 验证")
    return False

# ============================================================
#  登录模块（Cookie / 账号密码 / Discord OAuth + Cookie 持久化）
# ============================================================

LOGIN_METHOD_COOKIE   = "Cookie"
LOGIN_METHOD_PASSWORD = "账号密码"
LOGIN_METHOD_DISCORD  = "Discord OAuth"

_current_login_method = LOGIN_METHOD_COOKIE
STATE_RE = re.compile(r"[?&]state=([^&]+)")

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
    log(f"🍪 尝试 Cookie 登录 (Cookie名: {Config.COOKIE_NAME})...")
    try:
        # 先打开站点，让浏览器建立域名上下文
        sb.open(Config.BASE_URL)
        sb.wait_for_ready_state_complete()
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

        # 刷新页面，让 Cookie 生效
        sb.refresh()
        sb.wait_for_ready_state_complete()
        time.sleep(3)

        # 处理 Cloudflare
        if is_cloudflare_present(sb):
            log("🔒 遇到 Cloudflare，尝试通过...")
            if not solve_cloudflare(sb):
                log("❌ Cookie 登录时 Cloudflare 验证失败")
                return False
            time.sleep(2)

        # 检查当前 URL
        current_url = sb.get_current_url()
        log(f"📝 当前URL: {current_url}")

        # 等待可能的重定向
        for _ in range(10):
            url_lower = sb.get_current_url().lower()
            if "login" not in url_lower and Config.LOGIN_PATH not in sb.get_current_url():
                break
            time.sleep(1)

        current_url = sb.get_current_url()
        url_lower = current_url.lower()

        # 检查页面是否有登录表单（双重验证）
        has_login_form = False
        try:
            has_login_form = sb.execute_script("""
                return !!(document.querySelector('input[name="email"]') ||
                          document.querySelector('input[name="username"]') ||
                          document.querySelector('input[name="password"]') ||
                          document.querySelector('input[type="password"]'));
            """)
        except Exception:
            pass

        if "login" not in url_lower and Config.LOGIN_PATH not in current_url and not has_login_form:
            _current_login_method = LOGIN_METHOD_COOKIE
            log("✅ Cookie 登录成功")
            return True

        log(f"❌ Cookie 登录失败，仍在登录页")
        sb.save_screenshot("cookie_login_fail.png")
        return False
    except Exception as e:
        log(f"❌ Cookie 登录异常: {e}")
        return False

def login_by_password(sb) -> bool:
    global _current_login_method
    if not Config.EMAIL or not Config.PASSWORD:
        log("ℹ️  未配置账号密码，跳过密码登录")
        return False
    log("🔑 尝试账号密码登录...")
    try:
        log(f"🌐 打开登录页: {Config.login_url()}")
        sb.uc_open_with_reconnect(Config.login_url(), reconnect_time=5)
        time.sleep(3)

        # 处理 Cloudflare
        if is_cloudflare_present(sb):
            log("🔒 遇到 Cloudflare，尝试通过...")
            if not solve_cloudflare(sb):
                log("❌ 登录页 Cloudflare 验证失败")
                return False
            time.sleep(2)

        # 等待登录表单出现（支持多种字段名）
        input_selector = None
        for sel in ['input[name="username"]', 'input[name="email"]', 'input[name="Email"]',
                     'input[type="email"]', 'input[type="text"]']:
            try:
                sb.wait_for_element(sel, timeout=10)
                input_selector = sel
                log(f"✅ 找到用户名输入框: {sel}")
                break
            except Exception:
                continue

        if not input_selector:
            log("❌ 页面未加载出登录表单")
            sb.save_screenshot("login_load_fail.png")
            return False

        # 关闭 cookie 弹窗等
        try:
            for btn in sb.find_elements("button"):
                txt = (btn.text or "").lower()
                if "accept" in txt or "agree" in txt or "zgadzam" in txt or "akceptuj" in txt:
                    btn.click()
                    time.sleep(0.5)
                    break
        except Exception:
            pass

        # 填写用户名/邮箱
        log(f"📧 填写用户名: {Config.EMAIL}")
        js_fill_input(sb, input_selector, Config.EMAIL)
        time.sleep(0.3)

        # 填写密码
        log("🔑 填写密码...")
        js_fill_input(sb, 'input[name="password"]', Config.PASSWORD)
        time.sleep(1)

        # 提交前再次检查 Cloudflare
        if is_cloudflare_present(sb):
            solve_cloudflare(sb)
            time.sleep(1)

        # 点击提交按钮（支持多种按钮文本）
        log("🖱️  提交登录表单...")
        submitted = False

        # 方式1：JS 点击所有可能的提交按钮
        try:
            submitted = sb.execute_script("""
                (function(){
                    var btns = document.querySelectorAll('button[type="submit"], button');
                    for (var i = 0; i < btns.length; i++) {
                        var txt = (btns[i].textContent || '').toLowerCase();
                        if (txt.includes('zaloguj') || txt.includes('login') || txt.includes('sign in') ||
                            txt.includes('log in') || txt.includes('submit') || txt.includes('zaloguj się')) {
                            btns[i].click();
                            return true;
                        }
                    }
                    return false;
                })()
            """)
        except Exception:
            pass

        # 方式2：回车提交
        if not submitted:
            try:
                sb.press_keys('input[name="password"]', '\n')
                submitted = True
            except Exception:
                pass

        # 方式3：点击 submit 按钮
        if not submitted:
            try:
                sb.click('button[type="submit"]')
                submitted = True
            except Exception:
                pass

        log("⏳ 等待登录跳转...")
        for _ in range(20):
            time.sleep(1)
            cur_url = sb.get_current_url().split('?')[0].lower()
            if "login" not in cur_url and Config.LOGIN_PATH not in cur_url:
                break

        cur_url = sb.get_current_url().lower()
        if "login" in cur_url:
            log("❌ 登录失败，仍在登录页")
            sb.save_screenshot("login_failed.png")
            return False

        _current_login_method = LOGIN_METHOD_PASSWORD
        log(f"✅ 账号密码登录成功！")
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
#  Telegram 通知
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
    if login_method and login_method != "Cookie":
        lines.append(f"🔐 登录方式: {login_method}")
    if expiry_date:
        lines.append(f"📅 到期时间: {expiry_date}")
    if extra:
        lines.append(extra)
    if error:
        lines.append(f"⚠️  错误信息: {error}")
    lines.append(f"⏱️  执行时间: {beijing_time_str()}")
    return "\n".join(lines)

def notify_login_success(login_method: str = ""):
    send_telegram_message(build_notification("✅ 登录成功", login_method=login_method))

def notify_login_failure(error: str = "未知错误"):
    send_telegram_message(build_notification("❌ 登录失败", error=error))

def notify_renew_success(extra: str = "", expiry_date: str = ""):
    send_telegram_message(build_notification("✅ 续期成功", extra=extra, expiry_date=expiry_date))

def notify_renew_failure(error: str = "未知错误", extra: str = ""):
    send_telegram_message(build_notification("❌ 续期失败", extra=extra, error=error))

def notify_not_time(extra: str = "", expiry_date: str = ""):
    send_telegram_message(build_notification("⏳ 未到续期时间", extra=extra, expiry_date=expiry_date))

# ============================================================
#  IceHost 续期动作
# ============================================================

def _parse_expiry_date(date_str: str):
    """解析到期时间字符串，返回 datetime 对象"""
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def _find_server_cards(sb) -> list:
    """通过 JS 查找页面上所有服务器卡片"""
    js = """
    (function(){
        var cards = document.querySelectorAll('[draggable="true"]');
        var results = [];
        cards.forEach(function(card, idx){
            var nameEl = card.querySelector('p');
            var dateEl = card.querySelector('.sc-1ibsw91-1, [class*="cUvpcr"]');
            var name = nameEl ? nameEl.textContent.trim() : '';
            var expiry = dateEl ? dateEl.textContent.trim() : '';
            var renewBtn = null;
            var btns = card.querySelectorAll('button');
            btns.forEach(function(b){
                var txt = (b.textContent || '').toLowerCase();
                if (txt.includes('przedłuż') || txt.includes('extend') || txt.includes('renew') || txt.includes('verlängern')) {
                    renewBtn = b;
                }
            });
            var suspended = false;
            var spans = card.querySelectorAll('span');
            spans.forEach(function(s){
                var txt = (s.textContent || '').toLowerCase();
                if (txt.includes('zawieszony') || txt.includes('suspended')) {
                    suspended = true;
                }
            });
            if (name) {
                results.push({idx: idx, name: name, expiry: expiry, hasRenewBtn: !!renewBtn, suspended: suspended});
            }
        });
        return results;
    })()
    """
    try:
        return sb.execute_script(js) or []
    except Exception as e:
        log(f"❌ 查找服务器卡片失败: {e}")
        return []

def _click_renew_button(sb, card_index: int) -> bool:
    """点击指定卡片的续期按钮"""
    js = f"""
    (function(){{
        var cards = document.querySelectorAll('[draggable="true"]');
        var card = cards[{card_index}];
        if (!card) return false;
        var btns = card.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {{
            var txt = (btns[i].textContent || '').toLowerCase();
            if (txt.includes('przedłuż') || txt.includes('extend') || txt.includes('renew') || txt.includes('verlängern')) {{
                btns[i].click();
                return true;
            }}
        }}
        return false;
    }})()
    """
    try:
        return sb.execute_script(js)
    except Exception as e:
        log(f"❌ 点击续期按钮失败: {e}")
        return False

def _click_confirm_button(sb, timeout: int = 10) -> bool:
    """在弹出的确认窗口中点击确认按钮（波兰语/英语/德语）"""
    start = time.time()
    while time.time() - start < timeout:
        js = """
        (function(){
            var btns = document.querySelectorAll('button, [role="button"], .sc-1qu1gou-2');
            for (var i = btns.length - 1; i >= 0; i--) {
                var txt = (btns[i].textContent || '').toLowerCase().trim();
                if (txt.includes('tak, przedłuż serwer') ||
                    txt.includes('yes, extend server') ||
                    txt.includes('ja, verlängern') ||
                    txt.includes('tak, przedłuż') ||
                    txt.includes('yes, extend') ||
                    (txt === 'przedłuż') ||
                    (txt === 'extend')) {
                    btns[i].click();
                    return true;
                }
            }
            return false;
        })()
        """
        try:
            if sb.execute_script(js):
                log("✅ 已点击确认续期按钮")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    log("❌ 未找到确认按钮")
    return False

def _navigate_to_servers(sb) -> bool:
    """导航到服务器列表页面"""
    log("🌐 导航到服务器列表页面...")

    # 方式1：点击侧边栏 Server/Serwery 链接
    js_click_sidebar = """
    (function(){
        var links = document.querySelectorAll('a.sidebar-link, a[href="/"], nav a, aside a');
        for (var i = 0; i < links.length; i++) {
            var txt = (links[i].textContent || '').toLowerCase().trim();
            if (txt.includes('serwer') || txt.includes('server') || txt.includes('serwery') ||
                txt.includes('servers') || txt.includes('moje')) {
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

    # 方式2：直接访问 BASE_URL 根路径
    log("⚠️  侧边栏点击失败，尝试直接访问根路径...")
    try:
        sb.open(Config.BASE_URL)
        sb.wait_for_ready_state_complete()
        time.sleep(3)
        return True
    except Exception as e:
        log(f"❌ 导航失败: {e}")
        return False

def do_renew(sb) -> tuple:
    """
    IceHost 服务器续期逻辑
    返回: (status, extra_info, expiry_date)
        status: "SUCCESS" | "NOT_TIME" | "FAIL"
    """
    log("\n" + "#" * 25)
    log("  开始执行 IceHost 续期动作")
    log("#" * 25)

    # 步骤1：导航到服务器页面
    if not _navigate_to_servers(sb):
        return "FAIL", "无法导航到服务器页面", ""

    # 处理可能的 Cloudflare 验证
    if is_cloudflare_present(sb):
        log("🔒 服务器页面遇到 Cloudflare...")
        if not solve_cloudflare(sb):
            return "FAIL", "Cloudflare 验证未通过", ""
        time.sleep(2)

    # 步骤2：查找所有服务器卡片
    time.sleep(2)
    cards = _find_server_cards(sb)
    if not cards:
        log("❌ 未找到任何服务器卡片")
        sb.save_screenshot("no_servers.png")
        return "FAIL", "未找到服务器卡片", ""

    log(f"📋 找到 {len(cards)} 个服务器:")
    for c in cards:
        status_str = "（已暂停）" if c.get("suspended") else ""
        log(f"  [{c['idx']}] {c['name']} | 到期: {c['expiry']} | 续期按钮: {'有' if c.get('hasRenewBtn') else '无'} {status_str}")

    # 步骤3：遍历每个服务器，直接续期
    renewed_count = 0
    skipped_count = 0
    failed_count = 0
    latest_expiry = ""
    results = []

    for card in cards:
        server_name = card["name"]
        expiry_str = card["expiry"]
        card_idx = card["idx"]

        if card.get("suspended"):
            log(f"\n⚠️  [{server_name}] 服务器已暂停，跳过")
            results.append(f"⚠️  {server_name}: 已暂停")
            skipped_count += 1
            continue

        log(f"\n📅 [{server_name}] 当前到期时间: {expiry_str}")
        old_expiry = expiry_str

        # 直接点击续期按钮，不判断到期时间
        log(f"🔄 [{server_name}] 开始续期...")

        if not _click_renew_button(sb, card_idx):
            log(f"❌ [{server_name}] 未找到续期按钮")
            results.append(f"❌ {server_name}: 未找到续期按钮")
            failed_count += 1
            continue

        log("⏳ 等待确认弹窗...")
        time.sleep(2)

        # 步骤4：点击确认按钮
        if not _click_confirm_button(sb, timeout=10):
            log(f"❌ [{server_name}] 未找到确认按钮")
            results.append(f"❌ {server_name}: 确认按钮未找到")
            sb.save_screenshot(f"confirm_fail_{card_idx}.png")
            failed_count += 1
            continue

        # 步骤5：等待续期完成
        log("⏳ 等待续期处理...")
        time.sleep(5)

        # 处理可能的 Cloudflare
        if is_cloudflare_present(sb):
            solve_cloudflare(sb)
            time.sleep(2)

        # 步骤6：刷新页面，重新读取到期时间
        log("🔄 刷新页面验证续期结果...")
        sb.refresh()
        sb.wait_for_ready_state_complete()
        time.sleep(3)

        if is_cloudflare_present(sb):
            solve_cloudflare(sb)
            time.sleep(2)

        # 重新查找服务器卡片
        new_cards = _find_server_cards(sb)
        new_expiry_str = ""
        for nc in new_cards:
            if nc["name"] == server_name:
                new_expiry_str = nc["expiry"]
                break

        if not new_expiry_str:
            log(f"⚠️  [{server_name}] 刷新后未找到服务器，尝试重新导航...")
            _navigate_to_servers(sb)
            time.sleep(3)
            new_cards = _find_server_cards(sb)
            for nc in new_cards:
                if nc["name"] == server_name:
                    new_expiry_str = nc["expiry"]
                    break

        if new_expiry_str and new_expiry_str != old_expiry:
            new_dt = _parse_expiry_date(new_expiry_str)
            new_days = (new_dt - datetime.now()).total_seconds() / 86400 if new_dt else 0
            log(f"✅ [{server_name}] 续期成功！")
            log(f"   旧到期: {old_expiry}")
            log(f"   新到期: {new_expiry_str}（剩余 {new_days:.1f} 天）")
            results.append(f"✅ {server_name}: {old_expiry} → {new_expiry_str}")
            renewed_count += 1
            if not latest_expiry or new_expiry_str > latest_expiry:
                latest_expiry = new_expiry_str
        else:
            log(f"⚠️  [{server_name}] 到期时间未变化，续期可能失败")
            results.append(f"⚠️  {server_name}: 到期时间未变化（{old_expiry}）")
            failed_count += 1
            if not latest_expiry or expiry_str > latest_expiry:
                latest_expiry = expiry_str

    # 步骤7：汇总结果
    log("\n" + "=" * 40)
    log("  续期汇总")
    log("=" * 40)
    log(f"  总计: {len(cards)} | 成功: {renewed_count} | 跳过: {skipped_count} | 失败: {failed_count}")
    for r in results:
        log(f"  {r}")

    extra_info = "\n".join(results)
    if failed_count > 0 and renewed_count == 0:
        return "FAIL", extra_info, latest_expiry
    elif renewed_count > 0:
        return "SUCCESS", extra_info, latest_expiry
    else:
        return "NOT_TIME", extra_info, latest_expiry

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
            if not do_login(sb):
                notify_login_failure("所有登录方式均失败")
                sys.exit(1)

            login_method = get_login_method()
            log(f"✅ 登录成功，方式: {login_method}")
            notify_login_success(login_method=login_method)

            status, extra_info, expiry_date = do_renew(sb)

            if status == "SUCCESS":
                log("🎉 续期成功！")
                notify_renew_success(extra=extra_info, expiry_date=expiry_date)
            elif status == "NOT_TIME":
                log("⏳ 未到续期时间")
                notify_not_time(extra=extra_info, expiry_date=expiry_date)
            else:
                log("❌ 续期失败")
                notify_renew_failure(error=extra_info)

            if Config.GH_TOKEN and Config.COOKIE_NAME:
                log("\n🔄 检查并更新 Cookie...")
                save_cookie_to_github(sb)

            log("\n🏁 脚本执行完毕")
            sys.exit(0 if status != "FAIL" else 1)

    except KeyboardInterrupt:
        log("\n⚠️  用户中断")
        sys.exit(130)
    except Exception as e:
        log(f"\n❌ 未捕获的异常: {e}")
        import traceback
        traceback.print_exc()
        try:
            notify_renew_failure(error=f"未捕获异常: {e}")
        except Exception:
            pass
        sys.exit(1)
    finally:
        if proxy_started:
            stop_singbox()
        cleanup()

if __name__ == "__main__":
    main()
