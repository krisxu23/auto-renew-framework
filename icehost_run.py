import os
import json
import urllib.parse
import requests
from datetime import datetime, timedelta
import re
from seleniumbase import SB

SERVER_URL = os.getenv("ICEHOST_SERVER_URL")
ICEHOST_COOKIES = os.getenv("ICEHOST_COOKIES")

def send_tg_notification(message, photo_path=None):
    """发送结果和截图至 Telegram"""
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        print("未配置 TG 机器人变量，跳过发送 TG 推送。")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})
        print("TG 状态通知发送成功。")
    except Exception as e:
        print(f"发送 TG 消息异常: {e}")
    if photo_path and os.path.exists(photo_path):
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": chat_id, "caption": "IceHost 实时画面"}
                requests.post(url, data=data, files=files)
            print("TG 截图发送成功。")
        except Exception as e:
            print(f"发送 TG 截图异常: {e}")

def get_expiration_time(sb):
    """
    从页面提取到期时间字符串，返回 datetime 对象
    若未找到，返回 None
    """
    try:
        # 定位包含 "Expiration date:" 的段落
        expiration_elem = sb.find_element("//p[contains(., 'Expiration date:')]")
        text = expiration_elem.text.strip()
        # 提取日期时间部分，格式如 "2026-07-11 16:37:32"
        match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', text)
        if match:
            time_str = match.group(1)
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        else:
            return None
    except Exception as e:
        print(f"获取到期时间失败: {e}")
        return None

def run():
    if not SERVER_URL:
        print("错误: 缺少 ICEHOST_SERVER_URL 环境变量")
        return

    with SB(uc=True, xvfb=True) as sb:
        print(f"正在访问 IceHost 面板: {SERVER_URL}")
        sb.uc_open_with_reconnect(SERVER_URL, reconnect_time=8)
        sb.sleep(5)

        # 注入 Cookies
        if ICEHOST_COOKIES:
            try:
                raw_data = json.loads(ICEHOST_COOKIES)
                cookies_to_add = []
                if isinstance(raw_data, list):
                    cookies_to_add = raw_data
                elif isinstance(raw_data, dict):
                    cookies_to_add = raw_data.get("cookies", [])
                for c in cookies_to_add:
                    decoded_value = urllib.parse.unquote(c["value"])
                    cookie_dict = {
                        "name": c["name"],
                        "value": decoded_value,
                        "domain": c["domain"],
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True)
                    }
                    if "sameSite" in c:
                        ss = str(c["sameSite"]).lower()
                        if ss in ["lax", "strict", "none"]:
                            cookie_dict["sameSite"] = ss.capitalize()
                    sb.add_cookie(cookie_dict)
                print("Cookie 成功注入！")
                sb.refresh()
                sb.sleep(5)
            except json.JSONDecodeError as e:
                print(f"❌ Cookie JSON 解析失败: {e}")
                # 继续尝试，但可能无法登录
            except Exception as e:
                print(f"注入 Cookie 发生异常: {e}")

        # 过盾
        sb.save_screenshot("icehost_debug_before_captcha.png")
        try:
            print("正在检测并点击 Cloudflare 验证码...")
            sb.uc_gui_click_captcha()
            sb.sleep(10)
            sb.save_screenshot("icehost_debug_after_captcha.png")
        except Exception as e:
            print(f"验证码处理: {e}")

        # 检查是否在登录页
        current_url = sb.get_current_url()
        if "login" in current_url or sb.is_element_visible("input[type='email']"):
            msg = "❌ <b>IceHost 登录失效！</b>\n请检查 Cookie 或重新提取。"
            print(msg)
            send_tg_notification(msg, "icehost_debug_after_captcha.png")
            return

        print(f"当前页面 URL: {current_url}")

        # 双语限制关键词（包含波兰语和英语）
        keywords = [
            "Nie możesz przedłużyć", "niedawno to zrobiłeś", "kolejne 6 godziny",
            "You can't extend", "you have recently done", "next 6 hours"
        ]
        # 先检查页面是否已有限制提示
        page_source = sb.get_page_source()
        if any(kw in page_source for kw in keywords):
            print("检测到限制提示，未到续期时间，退出。")
            return

        # 获取当前到期时间（点击前）
        old_time = get_expiration_time(sb)
        if old_time:
            print(f"当前到期时间: {old_time}")

        # 精确定位续期按钮（使用 span 文本匹配）
        # 注意：该 span 的文本为 "Add 6 hours validity"（可能有前后空格）
        renew_btn_selector = "//span[normalize-space()='Add 6 hours validity']"
        # 备用：如果波兰语界面，可使用 "Dodaj 6 godzin ważności"
        renew_btn_selector_pl = "//span[normalize-space()='Dodaj 6 godzin ważności']"

        try:
            # 先尝试英语按钮
            if sb.is_element_visible(renew_btn_selector):
                btn_selector = renew_btn_selector
            elif sb.is_element_visible(renew_btn_selector_pl):
                btn_selector = renew_btn_selector_pl
            else:
                raise Exception("未找到续期按钮（英语或波兰语）")

            print("等待续期按钮可点击...")
            sb.wait_for_element_visible(btn_selector, timeout=20)
            # 滚动到元素可视区域
            sb.execute_script("arguments[0].scrollIntoView({block: 'center'});", sb.find_element(btn_selector))
            sb.sleep(1)

            # 使用 JavaScript 点击，更可靠
            print("正在点击续期按钮...")
            sb.js_click(btn_selector)

            # 点击后等待 3 秒让提示或更新出现
            sb.sleep(3)
            sb.save_screenshot("icehost_debug_after_click.png")

            # 检查点击后是否出现限制提示
            current_source = sb.get_page_source()
            if any(kw in current_source for kw in keywords):
                print("点击后出现限制提示，续期未成功，退出。")
                return

            # 刷新页面，确认续期是否生效
            print("刷新页面以获取最新到期时间...")
            sb.refresh()
            sb.sleep(5)
            sb.save_screenshot("icehost_debug_final.png")

            # 获取新的到期时间
            new_time = get_expiration_time(sb)
            if new_time:
                print(f"续期后的到期时间: {new_time}")
                if old_time and new_time > old_time:
                    # 判断时间差是否接近 6 小时（允许一定误差）
                    delta = (new_time - old_time).total_seconds() / 3600
                    if delta >= 5.5:  # 大约增加 6 小时
                        msg = "⚡ <b>IceHost 服务器续期成功！</b>\n有效期已延长 6 小时。"
                        print(msg)
                        send_tg_notification(msg, "icehost_debug_final.png")
                    else:
                        msg = "⚠️ <b>IceHost 续期似乎未完全成功</b>\n时间仅增加 {:.1f} 小时，请手动检查。".format(delta)
                        print(msg)
                        send_tg_notification(msg, "icehost_debug_final.png")
                else:
                    # 如果获取不到旧时间，但页面没有限制提示，视为可能成功（保守）
                    msg = "ℹ️ <b>IceHost 续期指令已发送</b>\n请检查截图确认时间是否增加。"
                    print(msg)
                    send_tg_notification(msg, "icehost_debug_final.png")
            else:
                # 无法获取到期时间，但无限制提示，可能成功
                msg = "ℹ️ <b>IceHost 续期指令已发送</b>\n（无法读取到期时间，请截图确认）"
                print(msg)
                send_tg_notification(msg, "icehost_debug_final.png")

        except Exception as e:
            print(f"续期操作失败: {e}")
            # 如果是因为按钮未找到，也发送通知以便调试
            msg = f"❌ <b>IceHost 续期失败</b>\n错误: {str(e)[:200]}"
            send_tg_notification(msg, "icehost_debug_after_click.png")

if __name__ == "__main__":
    run()
