# -*- coding: utf-8 -*-
"""
tdffm_api.py - BỘ KẾT NỐI VÀ ĐỒNG BỘ DỮ LIỆU THÁI DƯƠNG FULFILLMENT (TDFFM)
API: https://tdffm.com/api/v1
Tự động làm mới phiên làm việc qua Refresh Token, bảo vệ phiên đăng nhập lâu dài.
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, Any, Optional, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "tdffm_credentials.json")
SESSION_FILE = os.path.join(BASE_DIR, "tdffm_session.json")
BASE_URL = "https://tdffm.com/api/v1"

def load_credentials() -> Dict[str, Any]:
    """Tải thông tin phiên đăng nhập từ file credentials hoặc session."""
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_credentials(data: Dict[str, Any]):
    """Lưu lại credentials mới nhất."""
    try:
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Không thể lưu credentials: {e}")

def refresh_tdffm_access_token() -> Optional[str]:
    """
    Gia hạn Access Token tự động từ Refresh Token qua API POST https://tdffm.com/api/v1/auth/refresh
    Không bao giờ lo bị đăng xuất tài khoản mỗi ngày.
    """
    creds = load_credentials()
    refresh_token = creds.get("refreshToken")
    if not refresh_token:
        print("⚠️ Chưa có refreshToken trong tdffm_credentials.json")
        return None

    url = f"{BASE_URL}/auth/refresh"
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"refreshToken={refresh_token}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        req = urllib.request.Request(url, data=b"{}", headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            new_token = res_data.get("token") or res_data.get("accessToken")
            if new_token:
                creds["lastRefreshed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_credentials(creds)
                return new_token
    except urllib.error.HTTPError as e:
        print(f"⚠️ Lỗi HTTP khi gia hạn Token TDFFM: {e.code}")
    except Exception as e:
        print(f"⚠️ Lỗi kết nối khi gia hạn Token TDFFM: {e}")
    return None

def fetch_orders_from_tdffm(page: int = 1, limit: int = 200, access_token: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Lấy danh sách đơn hàng xuất kho từ TDFFM API.
    """
    token = access_token or refresh_tdffm_access_token()
    if not token:
        # Nếu không có token trực tiếp, dùng file orders_tdffm_raw.json làm nguồn dự phòng offline
        raw_cache = os.path.join(BASE_DIR, "orders_tdffm_raw.json")
        if os.path.exists(raw_cache):
            try:
                with open(raw_cache, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    url = f"{BASE_URL}/orders/list"
    payload = json.dumps({"page": page, "limit": limit}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            orders = data.get("data", {}).get("data") if isinstance(data.get("data"), dict) else data.get("data", [])
            orders = orders or data.get("orders") or []
            return orders
    except Exception as e:
        print(f"⚠️ Lỗi khi tải danh sách đơn TDFFM: {e}")
        return []

if __name__ == "__main__":
    orders = fetch_orders_from_tdffm(limit=10)
    print(f"Lấy được {len(orders)} đơn hàng.")
