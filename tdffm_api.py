import os, json, httpx, logging

SESSION_FILE = "tdffm_session.json"
BASE_URL = "https://tdffm.com/api/v1"

def load_session():
    try: return json.load(open(SESSION_FILE, 'r')) if os.path.exists(SESSION_FILE) else {}
    except: return {}

def save_session(session):
    with open(SESSION_FILE, 'w') as f: json.dump(session, f, indent=2)

async def _login_tdffm():
    """Tự động đăng nhập lấy token mới nếu refresh thất bại."""
    try:
        async with httpx.AsyncClient() as client:
            # TDFFM dùng payload "email" dù là username LAO162
            res = await client.post(f"{BASE_URL}/auth/login",
                json={"email": "LAO162", "password": "LAO162"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if res.status_code == 200:
                cookies = {c.name: c.value for c in client.cookies.jar}
                token = cookies.get("token")
                refresh = cookies.get("refreshToken")
                if token:
                    logging.info("[TDFFM] 🟢 Đã Đăng Nhập Tự Động thành công (Tài khoản: LAO162)")
                    return token, refresh
    except Exception as e:
        logging.error(f"[TDFFM] Lỗi Auto-Login: {e}")
    return None, None

async def _refresh_cookie(session):
    """Cố gắng tự refresh HTTPOnly cookie nếu có thể, trả về token mới hoặc token cũ"""
    refresh_val = session.get("refreshToken", "")
    for cookie_name in ["refreshToken", "Refresh", "refresh_token"]:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{BASE_URL}/auth/refresh", 
                    headers={"User-Agent": "Mozilla/5.0"}, cookies={cookie_name: refresh_val}, timeout=10)
                if res.status_code == 200:
                    new_token = res.json().get("token") or res.json().get("accessToken")
                    if new_token: return new_token
        except: pass
    return session.get("token", "")

async def fetch_orders(page=1, limit=50):
    """Lấy danh sách mã vận TĐFFM đang SHIPPING."""
    session = load_session()
    token = session.get("token", "")
    
    # 1. Thử dùng Playwright từ file auto_refresh_tdffm (nếu có sẵn)
    try:
        import auto_refresh_tdffm
        token = await auto_refresh_tdffm.auto_refresh_and_save() or token
    except Exception:
        pass

    # 2. Re-login nếu token trống hoặc cũ (Fallback toàn diện)
    async def try_auth(curr_token):
        if not curr_token:
            new_t, new_r = await _login_tdffm()
            if new_t:
                session["token"] = new_t
                session["refreshToken"] = new_r or session.get("refreshToken")
                save_session(session)
                return new_t
        return curr_token
        
    token = await try_auth(token)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{BASE_URL}/orders/list", json={"page": page, "limit": limit},
                headers={"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"})
            
            # Nếu 401 (hết hạn), Force Login Lại 1 Lần Nữa ngay lập tức:
            if resp.status_code in [401, 403]: 
                logging.info("[TDFFM] Token từ chối, kích hoạt Auto-Login khẩn cấp...")
                new_t, new_r = await _login_tdffm()
                if new_t:
                    session["token"], session["refreshToken"] = new_t, new_r
                    save_session(session)
                    # Gọi lại API lần 2 bằng token mới tinh
                    resp = await client.post(f"{BASE_URL}/orders/list", json={"page": page, "limit": limit},
                        headers={"Authorization": f"Bearer {new_t}", "User-Agent": "Mozilla/5.0"})
                if resp.status_code in [401, 403]: 
                    return {"success": False, "message": f"TDFFM HTTP {resp.status_code} - Auto-Login thất bại (Sai Pass hoặc Server chặn)."}
            
            if resp.status_code not in [200, 201]: return {"success": False, "message": f"TDFFM HTTP {resp.status_code}"}
            
            # Quét tìm mảng data
            data = resp.json()
            orders = data.get("data", {}).get("data") if isinstance(data.get("data"), dict) else data.get("data", [])
            orders = orders or data.get("orders") or data.get("body", {}).get("data", [])
            
            # Lọc trực tiếp mã 'SHIPPING'
            results = [
                {"tracking_id": str(i.get("shippingOrderCode")).strip(), "status": "Đang vận chuyển"}
                for i in (orders if isinstance(orders, list) else [])
                if isinstance(i, dict) and i.get("shippingOrderCode") and i.get("shippingOrderStatus", "").upper() == "SHIPPING"
            ]
            return {"success": True, "data": results}
    except Exception as e:
        return {"success": False, "message": f"Lỗi TDFFM: {e}"}
