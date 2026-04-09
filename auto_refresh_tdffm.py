"""
auto_refresh_tdffm.py — Quản lý token TDFFM.

Lý do không thể tự refresh qua API:
- TDFFM dùng NestJS Passport JWT với sessionId validation.
- refreshToken chỉ hợp lệ khi cùng sessionId với accessToken.
- Server set httpOnly cookie — không đọc được từ bên ngoài.

=> Giải pháp: Cảnh báo sớm khi token sắp hết hạn, và hỗ trợ
   cập nhật token thủ công (paste headers từ browser).
"""

import asyncio
import base64
import json
import os
import logging

SESSION_FILE = "tdffm_session.json"

def get_token_info(token: str) -> dict:
    """Decode JWT payload để lấy thông tin token."""
    try:
        payload = json.loads(base64.b64decode(token.split(".")[1] + "=="))
        return payload
    except Exception:
        return {}

def get_remaining_hours(token: str) -> float:
    """Trả về số giờ còn lại trước khi token hết hạn. Âm = đã hết hạn."""
    import datetime
    info = get_token_info(token)
    exp = info.get("exp", 0)
    remaining = exp - datetime.datetime.now().timestamp()
    return remaining / 3600

async def auto_refresh_and_save() -> str:
    """
    Kiểm tra token TDFFM.
    - Còn hạn > 1 tiếng: trả về token hiện tại, không làm gì.
    - Còn hạn < 1 tiếng hoặc đã hết: log cảnh báo, trả về token cũ để bot vẫn chạy.
    """
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE) as f:
            session = json.load(f)
    else:
        logging.error("[TDFFM] Không tìm thấy tdffm_session.json")
        return ""

    token = session.get("token", "")
    if not token:
        return ""

    remaining_h = get_remaining_hours(token)

    if remaining_h > 2:
        logging.info(f"[TDFFM] Token còn hạn {remaining_h:.1f} giờ.")
        return token
    elif remaining_h > 0:
        logging.warning(
            f"[TDFFM] ⚠️  Token sắp hết hạn trong {remaining_h*60:.0f} phút! "
            "Vào TDFFM bằng Chrome → F12 → Network → copy cookie 'token' → cập nhật tdffm_session.json"
        )
        return token
    else:
        logging.error(
            f"[TDFFM] ❌ Token đã hết hạn {abs(remaining_h):.1f} giờ trước! "
            "Vào TDFFM bằng Chrome → F12 → Network → copy cookie 'token' → cập nhật tdffm_session.json"
        )
        return token  # Vẫn trả về token cũ, bot sẽ nhận 401 khi gọi API


def update_token_from_cookie_string(cookie_string: str) -> bool:
    """
    Cập nhật token từ chuỗi cookie header (dán từ DevTools).
    Ví dụ: 'lang=vn; token=eyJ...; refreshToken=eyJ...'
    """
    new_token = None
    new_refresh = None

    for part in cookie_string.split(";"):
        part = part.strip()
        if part.startswith("token="):
            new_token = part[6:].strip()
        elif part.startswith("refreshToken="):
            new_refresh = part[13:].strip()

    if not new_token:
        logging.error("[TDFFM] Không tìm thấy 'token=' trong cookie string")
        return False

    session = {}
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE) as f:
            session = json.load(f)

    session["token"] = new_token
    if new_refresh:
        session["refreshToken"] = new_refresh

    with open(SESSION_FILE, "w") as f:
        json.dump(session, f, indent=2)

    info = get_token_info(new_token)
    import datetime
    exp = info.get("exp", 0)
    exp_str = datetime.datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M") if exp else "N/A"
    logging.info(f"[TDFFM] ✅ Token đã cập nhật! Hết hạn: {exp_str}")
    return True


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        # Chế độ: python3 auto_refresh_tdffm.py "lang=vn; token=eyJ...; refreshToken=eyJ..."
        cookie_str = sys.argv[1]
        if update_token_from_cookie_string(cookie_str):
            print("✅ Cập nhật token thành công!")
        else:
            print("❌ Không cập nhật được token.")
    else:
        # Chế độ kiểm tra
        result = asyncio.run(auto_refresh_and_save())
        if result:
            h = get_remaining_hours(result)
            print(f"Token còn hạn: {h:.1f} giờ")
        else:
            print("❌ Không có token hợp lệ.")


import asyncio
import json
import os
import logging

SESSION_FILE = "tdffm_session.json"

async def fetch_token_from_browser():
    """Mở browser headless, inject refreshToken cookie, lấy token mới từ TDFFM."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logging.error("[AutoRefresh] Chưa cài Playwright. Chạy: pip install playwright && playwright install chromium")
        return None

    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE) as f:
            session = json.load(f)
    else:
        logging.error("[AutoRefresh] Không tìm thấy tdffm_session.json")
        return None

    refresh_token = session.get("refreshToken", "")
    old_token     = session.get("token", "")
    if not refresh_token:
        logging.error("[AutoRefresh] Không có refreshToken")
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        # Inject cả 2 cookies như browser thật
        await context.add_cookies([
            {"name": "refreshToken", "value": refresh_token, "domain": "tdffm.com",
             "path": "/", "httpOnly": True,  "secure": True, "sameSite": "Lax"},
            {"name": "token",        "value": old_token,     "domain": "tdffm.com",
             "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax"},
            {"name": "lang",         "value": "vn",          "domain": "tdffm.com",
             "path": "/", "httpOnly": False, "secure": False, "sameSite": "Lax"},
        ])

        page = await context.new_page()
        new_token = None

        # Bắt tất cả responses trả về JSON có chứa token
        async def handle_response(response):
            nonlocal new_token
            if new_token:
                return
            url = response.url
            if "tdffm.com/api" not in url:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                data = await response.json()
                # Tìm token trong response (nhiều dạng key khác nhau)
                tok = (data.get("token") or data.get("accessToken")
                       or data.get("access_token")
                       or (data.get("data") or {}).get("token")
                       or (data.get("data") or {}).get("accessToken"))
                if tok and tok != old_token:
                    new_token = tok
                    logging.info(f"[AutoRefresh] ✅ Token mới từ response: {url}")
            except Exception:
                pass

        page.on("response", handle_response)

        logging.info("[AutoRefresh] Đang load https://tdffm.com/orders/list ...")
        try:
            await page.goto("https://tdffm.com/orders/list",
                            wait_until="networkidle", timeout=25000)
        except Exception as e:
            logging.warning(f"[AutoRefresh] Timeout/lỗi load: {e}")

        # Nếu bắt được từ response
        if new_token:
            await browser.close()
            return new_token

        # Đọc cookies sau khi trang load
        cookies = await context.cookies("https://tdffm.com")
        for c in cookies:
            if c["name"] == "token" and c["value"] != old_token:
                new_token = c["value"]
                logging.info("[AutoRefresh] ✅ Token mới từ cookie sau khi load!")
                break

        if not new_token:
            # Thử trigger refresh bằng JS trong browser (credentials: 'include' mang cookie httpOnly)
            logging.info("[AutoRefresh] Thử JS fetch /api/v1/auth/refresh...")
            try:
                js_result = await page.evaluate("""
                    async () => {
                        try {
                            const res = await fetch('/api/v1/auth/refresh', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                credentials: 'include'
                            });
                            const text = await res.text();
                            return {status: res.status, body: text.substring(0, 500)};
                        } catch(e) {
                            return {error: e.toString()};
                        }
                    }
                """)
                logging.info(f"[AutoRefresh] JS fetch result: {js_result}")
                import json as _json
                body = js_result.get("body", "")
                if body:
                    try:
                        data = _json.loads(body)
                        tok = (data.get("token") or data.get("accessToken")
                               or data.get("access_token")
                               or (data.get("data") or {}).get("token"))
                        if tok and tok != old_token:
                            new_token = tok
                            logging.info("[AutoRefresh] ✅ Token mới từ JS fetch!")
                    except Exception:
                        pass
            except Exception as e:
                logging.warning(f"[AutoRefresh] JS trigger lỗi: {e}")

        if not new_token:
            all_cookies = await context.cookies("https://tdffm.com")
            logging.info(f"[AutoRefresh] Cookies: {[c['name'] for c in all_cookies]}")

        await browser.close()
        return new_token



async def auto_refresh_and_save():
    """Kiểm tra token, nếu sắp hết hạn thì tự động refresh."""
    import base64, datetime

    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE) as f:
            session = json.load(f)
    else:
        session = {}

    token = session.get("token", "")
    needs_refresh = True

    if token:
        try:
            parts = token.split(".")
            payload = json.loads(base64.b64decode(parts[1] + "=="))
            exp = payload.get("exp", 0)
            remaining = exp - datetime.datetime.now().timestamp()
            if remaining > 3600:  # Còn hơn 1 tiếng → không cần refresh
                logging.info(f"[AutoRefresh] Token còn hạn {remaining/3600:.1f} giờ, bỏ qua.")
                needs_refresh = False
            else:
                logging.info(f"[AutoRefresh] Token sắp hết hạn ({remaining/60:.0f} phút), bắt đầu refresh...")
        except Exception:
            pass

    if not needs_refresh:
        return session.get("token")

    new_token = await fetch_token_from_browser()
    if new_token:
        session["token"] = new_token
        with open(SESSION_FILE, "w") as f:
            json.dump(session, f, indent=2)
        logging.info("[AutoRefresh] ✅ Đã lưu token mới vào tdffm_session.json")
        return new_token
    else:
        logging.warning("[AutoRefresh] ⚠️  Không lấy được token mới, dùng token cũ.")
        return session.get("token")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(auto_refresh_and_save())
    if result:
        print(f"Token hiện tại (60 ký tự đầu): {result[:60]}...")
    else:
        print("❌ Không lấy được token.")
