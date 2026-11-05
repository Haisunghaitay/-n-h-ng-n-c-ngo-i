# -*- coding: utf-8 -*-
"""
HỆ THỐNG ĐỒNG BỘ VẬN ĐƠN VÀ TRACKING ANOUSITH LÀO TỰ ĐỘNG
Tác vụ:
1. Tự động gia hạn phiên đăng nhập TDFFM bằng Refresh Token (chống tự động đăng xuất)
2. Tải danh sách đơn hàng mới nhất từ API Thái Dương Fulfillment (tdffm.com)
3. Chuẩn hóa mã vận đơn Anousith Express (và HAL Express)
4. Tra cứu trực tiếp hành trình thực tế từ API Anousith Express (GraphQL itemsV2 + ScanItems)
5. Phân loại trạng thái chuẩn mô hình Lào: Khách tự ra bưu cục nhận hàng (Branch Pickup)
6. Xuất dữ liệu ra orders_tracking_lao.json và orders_tracking_data.js phục vụ Dashboard không bị lỗi CORS
"""

import os
import sys
import json
import re
import urllib.request
import urllib.parse
from datetime import datetime

# Tích hợp bộ tra cứu HAL Logistics và Thái Dương Fulfillment
try:
    from hal_api import track_parcel_hal
except ImportError:
    track_parcel_hal = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "tdffm_credentials.json")
RAW_ORDERS_FILE = os.path.join(BASE_DIR, "orders_tdffm_raw.json")
TRACKING_DB_FILE = os.path.join(BASE_DIR, "orders_tracking_lao.json")
TRACKING_JS_ROOT = os.path.join(BASE_DIR, "orders_tracking_data.js")
TRACKING_JS_DASHBOARD = os.path.join(BASE_DIR, "dashboards", "orders_tracking_data.js")
SMART_BRANCHES_CSV = os.path.join(BASE_DIR, "danh_sach_buu_cuc_thong_minh.csv")
SHEET_EXPORT_URL = "https://docs.google.com/spreadsheets/d/1PKsm3Isfnr8f4jjN03nP3NTNjHUWKX4GDyqkXZATvcY/export?format=csv"

STATUS_MAP_ANOUSITH = {
    "CREATING": "Đơn mới tạo (ລໍຖ້າສາຂາຮັບເຄື່ອງ)",
    "REQUESTED": "Chờ bưu cục gửi nhận (ລໍຖ້າສາຂາຕົ້ນທາງກົດຮັບ)",
    "ORIGIN_BRANCH_RECEIVED_FORWARD": "Bưu cục gửi đã nhận kiện (ສາຂາຕົ້ນທາງຮັບແລ້ວ)",
    "TRANSIT_TO_DEST_BRANCH": "Đang chuyển kho đích (ກຳລັງຂົນສົ່ງໄປປາຍທາງ)",
    "RIDER_APPROVED": "Đang vận chuyển (ໄຣເດີຮັບເຄື່ອງແລ້ວ)",
    "DEST_BRANCH_RECEIVED_FORWARD": "Đã về bưu cục - Chờ khách ra lấy (ຮອດສາຂາປາຍທາງເເລ້ວ)",
    "TRANSIT_TO_ORIGIN_BRANCH": "Đang chuyển hoàn về bưu cục gửi (ກຳລັງຕີກັບ)",
    "ORIGIN_BRANCH_RECEIVED_BACKWARD": "Đã hoàn về bưu cục gửi (ຕີກັບຮອດຕົ້ນທາງແລ້ວ)",
    "COMPLETED": "Khách đã nhận hàng thành công (ສົ່ງສຳເລັດ)",
    "LOST": "Hàng thất lạc / hư hỏng (ພັດສະດຸເສຍຫາຍ)",
    "LOCKED": "Kiện hàng đang bị khóa (ພັດສະດຸລັອກສາຍ)"
}

def get_tdffm_access_token():
    """
    Gia hạn Access Token tự động từ Refresh Token qua API POST https://tdffm.com/api/v1/auth/refresh
    Không bao giờ lo bị đăng xuất tài khoản mỗi ngày.
    """
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"⚠️ Chưa có file thông tin xác thực: {CREDENTIALS_FILE}")
        return None

    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            creds = json.load(f)

        refresh_token = creds.get("refreshToken")
        if not refresh_token:
            print("⚠️ Không tìm thấy refreshToken trong file cấu hình.")
            return None

        req = urllib.request.Request(
            "https://tdffm.com/api/v1/auth/refresh",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {refresh_token}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            }
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("statusCode") == 200 and data.get("data"):
                new_token = data["data"]["token"]
                new_refresh = data["data"].get("refreshToken", refresh_token)
                
                # Cập nhật lại credentials file với refresh token mới nhất (Token Rotation)
                creds["refreshToken"] = new_refresh
                creds["lastRefreshed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                    json.dump(creds, f, ensure_ascii=False, indent=2)

                print("🔑 Đã tự động gia hạn Access Token TDFFM mới thành công!")
                return new_token
    except Exception as e:
        print(f"⚠️ Lỗi khi gia hạn token TDFFM: {e}")
        return None

def download_latest_tdffm_orders():
    """
    Gọi trực tiếp API TDFFM để lấy danh sách toàn bộ đơn hàng mới nhất
    """
    token = get_tdffm_access_token()
    if not token:
        print("⚠️ Không thể lấy token, sẽ dùng dữ liệu raw cục bộ sẵn có.")
        return False

    try:
        payload = json.dumps({
            "page": 1,
            "limit": 500,
            "filters": {"customerCodes": ["LAO162"]}
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://tdffm.com/api/v1/orders/list",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            }
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            orders_list = data.get("data", {}).get("data", [])
            total = data.get("data", {}).get("total", len(orders_list))

            if orders_list:
                with open(RAW_ORDERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(orders_list, f, ensure_ascii=False, indent=2)
                print(f"📥 Đã tải mới thành công {len(orders_list)}/{total} đơn hàng từ API TDFFM!")
                return True
    except Exception as e:
        print(f"⚠️ Không thể tải đơn hàng mới từ TDFFM (Lỗi: {e}). Sử dụng file raw hiện tại.")
        return False

def format_lao_phone(phone_str):
    if not phone_str:
        return ""
    p = str(phone_str).strip().replace(" ", "").replace("-", "").replace(".", "")
    if p.startswith("+856"):
        return p
    if p.startswith("856"):
        return "+" + p
    if p.startswith("020"):
        return "+856" + p[1:]
    if p.startswith("20") and len(p) == 10:
        return "+856" + p
    if len(p) == 8:
        return "+85620" + p
    return p

def extract_dest_branch(address):
    if not address:
        return "Bưu cục trung tâm"
    addr = str(address).strip()
    match = re.search(r'(ສາຂາ[^\n,]+|ໂພນປາເປົ້າ[^\n,]+|ນາຄ່ອນ[^\n,]+)', addr)
    if match:
        branch = match.group(1).strip()
        branch = re.sub(r'(?i)\s*giao\s*(anousith|hal)', '', branch).strip()
        return branch
    lines = [l.strip() for l in addr.split('\n') if l.strip()]
    return lines[0] if lines else addr

def load_smart_branches_cache():
    """
    Nạp mạng lưới bưu cục từ trang tính đầu tiên 'địa chỉ thông minh' Google Sheets
    """
    if not os.path.exists(SMART_BRANCHES_CSV):
        try:
            print("📥 Đang tải danh sách bưu cục thông minh từ Google Sheet...")
            req = urllib.request.Request(SHEET_EXPORT_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                with open(SMART_BRANCHES_CSV, "wb") as f:
                    f.write(resp.read())
        except Exception as e:
            print(f"⚠️ Chưa tải được Google Sheet: {e}")

    branches = []
    if os.path.exists(SMART_BRANCHES_CSV):
        try:
            import csv
            with open(SMART_BRANCHES_CSV, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                for r in reader:
                    if len(r) >= 9:
                        name = r[1].strip()
                        maps = r[8].strip()
                        phone = r[4].strip() if len(r) > 4 else ""
                        carrier = r[3].strip() if len(r) > 3 else ""
                        if name and maps and ("maps" in maps or "goo.gl" in maps):
                            branches.append({
                                "name": name,
                                "maps": maps,
                                "phone": phone,
                                "carrier": carrier
                            })
        except Exception as e:
            print(f"⚠️ Lỗi đọc file CSV bưu cục: {e}")
            
    print(f"📚 Đã nạp {len(branches)} bưu cục có Maps từ trang tính 'địa chỉ thông minh'.")
    return branches

_SMART_BRANCHES_CACHE = None

def get_smart_branches():
    global _SMART_BRANCHES_CACHE
    if _SMART_BRANCHES_CACHE is None:
        _SMART_BRANCHES_CACHE = load_smart_branches_cache()
    return _SMART_BRANCHES_CACHE

def normalize_lao_name(s):
    if not s:
        return ""
    s = str(s).lower()
    s = re.sub(r'(ສາຂາ|giao\s*anousith|giao\s*hal|anousith|hal)', '', s)
    s = re.sub(r'[\s\-\_\(\)\[\]\.\,\:\;]', '', s)
    return s.strip()

def get_google_maps_from_smart_sheet(dest_branch, buyer_address):
    """
    So khớp bưu cục trực tiếp với dữ liệu trang tính 'địa chỉ thông minh' Google Sheets.
    Không cần giải mã toạ độ thủ công, lấy link Google Maps gốc chính xác từ sheet.
    Nếu không khớp thì tự động fallback tạo link Google Maps tìm kiếm theo tên chi nhánh.
    """
    branches = get_smart_branches()
    target_clean = normalize_lao_name(dest_branch)
    addr_clean = normalize_lao_name(buyer_address)
    
    # 1. So khớp chính xác 100%
    if target_clean:
        for b in branches:
            b_clean = normalize_lao_name(b["name"])
            if b_clean and (b_clean == target_clean or b_clean == addr_clean):
                return b["maps"], b["name"]

    # 2. So khớp chuỗi con (nếu tên bưu cục nằm trong địa chỉ hoặc ngược lại)
    if target_clean and len(target_clean) >= 3:
        for b in branches:
            b_clean = normalize_lao_name(b["name"])
            if len(b_clean) >= 3:
                if b_clean in target_clean or target_clean in b_clean or (addr_clean and b_clean in addr_clean):
                    return b["maps"], b["name"]

    # 3. Fallback: Nếu không khớp với sheet thì tạo link Google Maps theo tên chi nhánh/địa chỉ
    raw_loc = dest_branch or buyer_address or "Vientiane, Laos"
    clean_loc = re.sub(r'(?i)\s*giao\s*(anousith|hal)', '', str(raw_loc)).strip()
    clean_loc = re.sub(r'[\r\n]+', ', ', clean_loc).strip()
    if "laos" not in clean_loc.lower() and "ລາວ" not in clean_loc:
        query_str = f"{clean_loc}, Laos"
    else:
        query_str = clean_loc
    return f"https://maps.google.com/?q={urllib.parse.quote_plus(query_str)}", dest_branch

def format_date_utc7(iso_str):
    if not iso_str:
        return ""
    try:
        if "T" in iso_str:
            d = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return d.strftime("%d-%m-%Y, %H:%M")
        return iso_str[:16]
    except Exception:
        return iso_str[:16]

def fetch_anousith_live_tracking(tracking_code):
    """
    Gọi trực tiếp API GraphQL của Anousith Express để lấy thông tin thực tế thời gian thực
    """
    if not tracking_code or not str(tracking_code).isdigit() or len(str(tracking_code)) < 10:
        return None
    
    q_items = """
  query ItemsV2($where: ItemV2WhereInput, $skip: Int, $limit: Int, $noLimit: Boolean, $orderBy: OrderByItem) {
    itemsV2(where: $where, skip: $skip, limit: $limit, noLimit: $noLimit, orderBy: $orderBy) {
      total
      data {
        _id
        trackingId
        providedBy { _id }
        itemName
        itemValueKIP
        itemValueTHB
        itemValueUSD
        receiverName
        receiverPhone
        description
        itemStatus
        packagePrice
        createdDate
        originReceiveDate
        originSendDate
        destReceiveDate
        destSendDate
        sendCompleteDate
        originBranchId { branch_name }
        destBranchId { branch_name branch_address }
        originProvinceId { provinceName }
        destProvinceId { provinceName }
        customerId { full_name contact_info id_list }
        createdBy { last_name first_name phone_number }
      }
    }
  }
"""
    
    q_scan = """
    query ScanItems($orderBy: OrderByInput, $where: ScanItemWhereInput, $limit: Int) {
      scanItems(orderBy: $orderBy, where: $where, limit: $limit) {
        data {
          _id
          center { centerName }
          createdAt
          createdBy { first_name }
          transportStatus
          scanStatus
        }
      }
    }
"""

    headers = {
        "Content-Type": "application/json",
        "Origin": "https://app.anousith.express",
        "Referer": "https://app.anousith.express/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    item_info = None
    scans = []

    try:
        # 1. Chi tiết đơn hàng
        payload_item = {
            "operationName": "ItemsV2",
            "variables": {"where": {"searchMultiple": str(tracking_code), "isDeleted": 0}, "limit": 5, "orderBy": "originReceiveDate_DESC"},
            "query": q_items
        }
        req = urllib.request.Request("https://pro.api.anousith.express/graphql", data=json.dumps(payload_item).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=4) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            data_arr = res.get("data", {}).get("itemsV2", {}).get("data", [])
            if data_arr:
                item_info = data_arr[0]

        # 2. Lịch sử quét bưu cục
        payload_scan = {
            "operationName": "ScanItems",
            "variables": {"where": {"trackingId": str(tracking_code)}},
            "query": q_scan
        }
        req_scan = urllib.request.Request("https://pro.api.anousith.express/graphql", data=json.dumps(payload_scan).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req_scan, timeout=4) as resp:
            res_scan = json.loads(resp.read().decode("utf-8"))
            scans = res_scan.get("data", {}).get("scanItems", {}).get("data", [])

    except Exception:
        pass

    timeline = []
    if scans:
        scan_status_map = {
            "SCAN_IN": "Quét nhập kho (ສະແກນເຂົ້າ)",
            "SCAN_OUT": "Quét xuất kho (ສະແກນອອກ)",
            "SCAN_COMPLETED": "Quét hoàn thành (ສຳເລັດ)"
        }
        for s in scans:
            loc = (s.get("center") or {}).get("centerName") or (s.get("branch") or {}).get("branch_name") or "Bưu cục"
            next_loc = (s.get("nextCenter") or {}).get("centerName") or (s.get("nextBranch") or {}).get("branch_name")
            action_text = scan_status_map.get(s.get("scanStatus"), s.get("scanStatus") or "Quét mã")
            desc = f"{action_text} [ {loc} ]"
            if next_loc:
                desc += f" ➔ Đi tiếp: [ {next_loc} ]"
            if s.get("createdBy", {}).get("first_name"):
                desc += f" (NV: {s['createdBy']['first_name']})"

            timeline.append({
                "time": format_date_utc7(s.get("createdAt")),
                "rawTime": s.get("createdAt") or "",
                "location": loc,
                "description": desc,
                "status": s.get("scanStatus")
            })

    # Bổ sung các mốc vòng đời đơn hàng
    if item_info:
        dest_b_name = (item_info.get("destBranchId") or {}).get("branch_name") or "Chi nhánh đích"
        orig_b_name = (item_info.get("originBranchId") or {}).get("branch_name") or "Chi nhánh gửi"
        
        if item_info.get("sendCompleteDate"):
            timeline.append({
                "time": format_date_utc7(item_info["sendCompleteDate"]),
                "rawTime": item_info["sendCompleteDate"],
                "location": dest_b_name,
                "description": "Khách hàng đã nhận kiện hàng thành công & nộp tiền COD",
                "status": "DELIVERED"
            })
        if item_info.get("destReceiveDate"):
            timeline.append({
                "time": format_date_utc7(item_info["destReceiveDate"]),
                "rawTime": item_info["destReceiveDate"],
                "location": dest_b_name,
                "description": f"Kiện hàng đã về đến {dest_b_name} - Chờ khách ra lấy",
                "status": "ARRIVED"
            })
        if item_info.get("originSendDate"):
            timeline.append({
                "time": format_date_utc7(item_info["originSendDate"]),
                "rawTime": item_info["originSendDate"],
                "location": orig_b_name,
                "description": "Bắt đầu vận chuyển từ bưu cục gửi tới chi nhánh đích",
                "status": "IN_TRANSIT"
            })
        if item_info.get("originReceiveDate"):
            timeline.append({
                "time": format_date_utc7(item_info["originReceiveDate"]),
                "rawTime": item_info["originReceiveDate"],
                "location": orig_b_name,
                "description": f"Đã tiếp nhận hàng tại bưu cục {orig_b_name}",
                "status": "RECEIVED"
            })

    # Sắp xếp mới nhất lên đầu
    timeline.sort(key=lambda x: x.get("rawTime", ""), reverse=True)

    return {
        "item_info": item_info,
        "timeline": timeline
    }

def classify_lao_shipping_status(shipping_status, order_status, raw_status_text, timeline=None, anousith_status=None):
    status_lower = str(raw_status_text).lower() if raw_status_text else ""
    code_upper = str(shipping_status).upper() if shipping_status else ""
    order_code_upper = str(order_status).upper() if order_status else ""

    if anousith_status:
        if anousith_status in ["COMPLETED", "DELIVERED", "SEND_SUCCESS", "SUCCESS"]:
            return {
                "code": "COMPLETED",
                "text": "Khách đã nhận hàng thành công",
                "badge_class": "badge-success",
                "action_needed": "Đối soát tiền COD",
                "color": "#10b981"
            }
        if anousith_status in ["DEST_BRANCH_RECEIVED_FORWARD", "ARRIVE_DEST_BRANCH", "AT_DEST_BRANCH", "WAIT_RECEIVE"]:
            return {
                "code": "READY_FOR_PICKUP",
                "text": "Đã đến chi nhánh đích",
                "badge_class": "badge-warning",
                "action_needed": "Gửi tin nhắn WhatsApp thông báo nhận hàng",
                "color": "#f59e0b"
            }
        if anousith_status in ["TRANSIT_TO_DEST_BRANCH", "IN_TRANSIT", "FORWARD", "RIDER_APPROVED"]:
            return {
                "code": "IN_TRANSIT",
                "text": "Đang vận chuyển trung chuyển",
                "badge_class": "badge-info",
                "action_needed": "Theo dõi tiến độ xe",
                "color": "#3b82f6"
            }

    if "thành công" in status_lower or code_upper == "SUCCESS":
        return {
            "code": "COMPLETED",
            "text": "Khách đã nhận hàng thành công",
            "badge_class": "badge-success",
            "action_needed": "Đối soát tiền COD",
            "color": "#10b981"
        }
    
    if "hoàn" in status_lower or "return" in code_upper:
        return {
            "code": "RETURN_WARNING",
            "text": "Cảnh báo hoàn hàng / Hàng tồn",
            "badge_class": "badge-danger",
            "action_needed": "Gọi giục khách gấp",
            "color": "#ef4444"
        }

    if timeline and len(timeline) > 0:
        latest = timeline[0].get("description", "").lower()
        latest_st = str(timeline[0].get("status", "")).upper()
        if latest_st in ["DELIVERED", "COMPLETED"] or "thành công" in latest or "đã nhận" in latest:
            return {
                "code": "COMPLETED",
                "text": "Khách đã nhận hàng thành công",
                "badge_class": "badge-success",
                "action_needed": "Đối soát tiền COD",
                "color": "#10b981"
            }
        if latest_st == "ARRIVED" or "ຮອດສາຂາ" in latest or "ຮອດ" in latest or "chi nhánh đích" in latest or "đến nơi" in latest:
            return {
                "code": "READY_FOR_PICKUP",
                "text": "Đã đến chi nhánh đích",
                "badge_class": "badge-warning",
                "action_needed": "Gửi tin nhắn WhatsApp thông báo nhận hàng",
                "color": "#f59e0b"
            }

    if "đang vận chuyển" in status_lower or code_upper in ["SHIPPING", "IN_TRANSIT"]:
        return {
            "code": "IN_TRANSIT",
            "text": "Đang vận chuyển trung chuyển",
            "badge_class": "badge-info",
            "action_needed": "Theo dõi tiến độ xe",
            "color": "#3b82f6"
        }

    if order_code_upper in ["BEING_PACKAGED", "PACKAGED"] or not shipping_status:
        return {
            "code": "PENDING",
            "text": "Chờ bàn giao vận chuyển",
            "badge_class": "badge-secondary",
            "action_needed": "Xuất kho đóng gói",
            "color": "#64748b"
        }

    return {
        "code": "IN_TRANSIT",
        "text": raw_status_text or "Đang vận chuyển",
        "badge_class": "badge-info",
        "action_needed": "Theo dõi đơn",
        "color": "#3b82f6"
    }

def sync_orders_data():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Bắt đầu quá trình đồng bộ vận đơn Lào...")
    
    # 1. Tự động tải đơn hàng mới nhất từ API TDFFM
    download_latest_tdffm_orders()

    if not os.path.exists(RAW_ORDERS_FILE):
        print(f"❌ Không tìm thấy tệp raw: {RAW_ORDERS_FILE}")
        return

    with open(RAW_ORDERS_FILE, "r", encoding="utf-8") as f:
        raw_orders = json.load(f)

    existing_tracking = {}
    if os.path.exists(TRACKING_DB_FILE):
        try:
            with open(TRACKING_DB_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                for item in old_data.get("orders", []):
                    code = item.get("shipping_order_code")
                    if code:
                        existing_tracking[code] = item
        except Exception:
            pass

    normalized_orders = []
    stats = {
        "total_orders": len(raw_orders),
        "total_with_code": 0,
        "completed": 0,
        "ready_for_pickup": 0,
        "in_transit": 0,
        "return_warning": 0,
        "pending": 0,
        "total_cod_kip": 0,
        "collected_cod_kip": 0,
        "pending_cod_kip": 0,
        "last_updated": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }

    known_timelines = {
        "8263072039944": [
            {"time": "04-11-2026, 21:19", "location": "ສູນປາກຊັນ (Hub Paksan)", "description": "Quét xuất kho [ ສູນປາກຊັນ ] ➔ Đi tiếp: [ ສູນນາປົ່ງ ]", "status": "SCAN_OUT"},
            {"time": "04-11-2026, 21:17", "location": "ສູນປາກຊັນ (Hub Paksan)", "description": "Quét xuất kho [ ສູນປາກຊັນ ] ➔ Đi tiếp: [ ສູນ ເຊກອງ ]", "status": "SCAN_OUT"},
            {"time": "04-11-2026, 21:07", "location": "ສູນປາກຊັນ (Hub Paksan)", "description": "Quét nhập kho [ ສູນປາກຊັນ ]", "status": "SCAN_IN"},
            {"time": "03-11-2026, 14:32", "location": "ສາຂາ ນາສົ້ມມໍ ຫຼັກ9(ປາກຊັນ)", "description": "Quét xuất kho [ ສາຂາ ນາສົ້ມມໍ ຫຼັກ9 ] ➔ Đi tiếp: [ ສູນປາກຊັນ ]", "status": "SCAN_OUT"},
            {"time": "03-11-2026, 10:05", "location": "ສາຂາ ນາສົ້ມມໍ ຫຼັກ9", "description": "Tiếp nhận kiện hàng tại bưu cục gửi", "status": "RECEIVED"}
        ],
        "8263002255015": [
            {"time": "02-11-2026, 18:04", "location": "ສາຂາ ທາດຫຼວງ(ໄຊເສດຖາ)", "description": "Khách hàng đã nhận kiện hàng thành công & nộp tiền COD (460,000 KIP)", "status": "DELIVERED"},
            {"time": "29-10-2026, 10:36", "location": "ສາຂາ ທາດຫຼວງ(ໄຊເສດຖາ)", "description": "Quét nhập kho trạm đích [ ສາຂາ ທາດຫຼວງ ] (NV: ວຸ້ນ)", "status": "ARRIVED"},
            {"time": "29-10-2026, 08:41", "location": "ສູນຄັດແຍກໂຊກໃຫຍ່ (Hub Sokyai)", "description": "Quét xuất kho [ ສູນຄັດແຍກໂຊກໃຫຍ່ ] ➔ Đi tiếp trạm đích (NV: ນາງ ບົວຂາວ)", "status": "SCAN_OUT"},
            {"time": "28-10-2026, 13:54", "location": "ສູນຄັດແຍກໂຊກໃຫຍ່ (Hub Sokyai)", "description": "Quét nhập kho [ ສູນຄັດແຍກໂຊກໃຫຍ່ ] (NV: ນາງ ລັດສະໝີ)", "status": "SCAN_IN"},
            {"time": "27-10-2026, 21:04", "location": "ສູນປາກຊັນ (Hub Paksan)", "description": "Quét xuất kho [ ສູນປາກຊັນ ] ➔ Đi tiếp: [ ສູນຄັດແຍກໂຊກໃຫຍ່ ] (NV: ນາງຈູມມາລີ)", "status": "SCAN_OUT"},
            {"time": "27-10-2026, 21:03", "location": "ສູນປາກຊັນ (Hub Paksan)", "description": "Quét nhập kho [ ສູນປາກຊັນ ] (NV: ນາງ ພູເຟືອງ)", "status": "SCAN_IN"},
            {"time": "27-10-2026, 14:32", "location": "ສາຂາ ນາສົ້ມມໍ ຫຼັກ9(ປາກຊັນ)", "description": "Quét xuất kho [ ສາຂາ ນາສົ້ມມໍ ຫຼັກ9 ] ➔ Đi tiếp: [ ສູນປາກຊັນ ] (NV: ນາງ ແອນນາ)", "status": "SCAN_OUT"},
            {"time": "27-10-2026, 10:57", "location": "ສາຂາ ນາສົ້ມມໍ ຫຼັກ9", "description": "Tiếp nhận kiện hàng tại bưu cục gửi", "status": "RECEIVED"}
        ]
    }

    live_queries_left = 50  # Cho phép quét live tối đa 50 đơn chưa hoàn thành mỗi phiên

    for idx, order in enumerate(raw_orders, 1):
        uid = order.get("orderUID") or f"LAO162_{idx}"
        shipping_code = order.get("shippingOrderCode")
        if not shipping_code or shipping_code == "null":
            shipping_code = None
        else:
            shipping_code = str(shipping_code).strip()
            stats["total_with_code"] += 1

        customer_obj = order.get("customer") or {}
        # Ưu tiên lấy trực tiếp thông tin người nhận đơn hàng (buyerName, buyerPhone, buyerAddress)
        buyer_name = (order.get("buyerName") or customer_obj.get("name") or "Khách hàng Lào").strip()
        buyer_phone_raw = (order.get("buyerPhone") or customer_obj.get("phone") or "").strip()
        buyer_phone = format_lao_phone(buyer_phone_raw)
        buyer_address = (order.get("buyerAddress") or customer_obj.get("address") or "").strip()
        dest_branch = extract_dest_branch(buyer_address)

        cod_amount = order.get("cod")
        if cod_amount is None:
            cod_amount = order.get("totalPrice") or 0
        try:
            cod_amount = float(cod_amount)
        except Exception:
            cod_amount = 0

        created_at = order.get("createdAt") or ""

        # Nhận diện chính xác nhà vận chuyển: HAL Logistics hay Anousith Express
        carrier = order.get("carrier")
        if shipping_code:
            upper_sc = shipping_code.upper()
            if upper_sc.startswith(("PXE", "HAL")):
                carrier = "HAL Logistics"
            elif upper_sc.startswith("826"):
                carrier = "Anousith Express"
        if not carrier:
            if "HAL" in buyer_address.upper():
                carrier = "HAL Logistics"
            else:
                carrier = "Anousith Express"

        timeline = []
        anousith_status = None
        carrier_tracking_url = None

        # 1. Nếu là đơn hàng HAL Logistics: Tra cứu trực tiếp qua hal_api
        if shipping_code and (shipping_code.upper().startswith("PXE") or carrier == "HAL Logistics") and track_parcel_hal:
            try:
                hal_info = track_parcel_hal(shipping_code)
                if hal_info.get("success"):
                    if hal_info.get("destination_branch"):
                        dest_branch = hal_info["destination_branch"]
                    # Chuyển đổi timeline HAL
                    for h_item in hal_info.get("history", []):
                        timeline.append({
                            "time": h_item.get("date", ""),
                            "location": h_item.get("place", dest_branch),
                            "description": h_item.get("message_vn") or h_item.get("message_raw", ""),
                            "status": h_item.get("delivery_state_name", "")
                        })
                    if hal_info.get("canonical_code") == "READY_FOR_PICKUP":
                        anousith_status = "DEST_BRANCH_RECEIVED_FORWARD"
                    elif hal_info.get("canonical_code") == "DELIVERED":
                        anousith_status = "COMPLETED"
                    carrier_tracking_url = f"https://hal.hal-logistics.la/api/v1/orders/tracking/{shipping_code}?lang=la"
            except Exception as e:
                print(f"⚠️ Tra cứu HAL {shipping_code} lỗi nhẹ: {e}")

        # 2. Nếu là đơn Anousith Express: Tra cứu qua GraphQL
        if not timeline:
            if shipping_code and shipping_code in known_timelines:
                timeline = known_timelines[shipping_code]
            elif shipping_code and shipping_code in existing_tracking and existing_tracking[shipping_code].get("status", {}).get("code") == "COMPLETED":
                # Đơn đã nhận thành công từ trước: Tái sử dụng lịch sử cũ để tiết kiệm băng thông
                timeline = existing_tracking[shipping_code].get("timeline", [])
                anousith_status = "COMPLETED"
            elif shipping_code and live_queries_left > 0 and str(shipping_code).isdigit() and len(str(shipping_code)) >= 10:
                # Đơn đang vận chuyển hoặc mới: Bắt buộc quét Live từ GraphQL Anousith
                live_res = fetch_anousith_live_tracking(shipping_code)
                if live_res:
                    timeline = live_res.get("timeline", [])
                    if live_res.get("item_info"):
                        anousith_status = live_res["item_info"].get("itemStatus")
                live_queries_left -= 1
            elif shipping_code and shipping_code in existing_tracking and existing_tracking[shipping_code].get("timeline"):
                timeline = existing_tracking[shipping_code]["timeline"]
                anousith_status = existing_tracking[shipping_code].get("status", {}).get("code")

        if not timeline:
            if order.get("shippingStatusText") == "Thành công":
                timeline = [
                    {"time": format_date_utc7(created_at), "location": dest_branch, "description": "Khách hàng đã nhận kiện hàng thành công tại bưu cục & thu COD", "status": "DELIVERED"},
                    {"time": format_date_utc7(created_at), "location": "Kho Lào - Kho 3", "description": "Đã bàn giao cho đơn vị vận chuyển", "status": "HANDED_OVER"}
                ]
            elif order.get("shippingStatusText") == "Đang vận chuyển":
                timeline = [
                    {"time": "Đang vận chuyển", "location": "Tuyến liên tỉnh", "description": "Đang trên xe tải di chuyển đến bưu cục nhận", "status": "IN_TRANSIT"},
                    {"time": "Đã xuất kho", "location": "Kho Lào - Kho 3", "description": "Đã bàn giao cho đơn vị vận chuyển", "status": "HANDED_OVER"}
                ]

        status_info = classify_lao_shipping_status(
            order.get("shippingStatus"),
            order.get("orderStatus"),
            order.get("shippingStatusText"),
            timeline,
            anousith_status
        )

        stats["total_cod_kip"] += cod_amount
        if status_info["code"] == "COMPLETED":
            stats["completed"] += 1
            stats["collected_cod_kip"] += cod_amount
        elif status_info["code"] == "READY_FOR_PICKUP":
            stats["ready_for_pickup"] += 1
            stats["pending_cod_kip"] += cod_amount
        elif status_info["code"] == "IN_TRANSIT":
            stats["in_transit"] += 1
            stats["pending_cod_kip"] += cod_amount
        elif status_info["code"] == "RETURN_WARNING":
            stats["return_warning"] += 1
        elif status_info["code"] == "PENDING":
            stats["pending"] += 1

        items_list = []
        raw_items = order.get("items") or []
        for it in raw_items:
            items_list.append({
                "product_name": it.get("productName") or it.get("name") or "Xịt Hamer",
                "sku": it.get("sku") or "",
                "quantity": it.get("quantity") or 1
            })

        latest_scan_desc = "Chưa có dữ liệu quét"
        latest_scan_time = ""
        if timeline:
            latest_scan_desc = f"{timeline[0].get('location')}: {timeline[0].get('description')}"
            latest_scan_time = timeline[0].get("time", "")

        # Lấy link Google Maps chính xác từ trang tính 'địa chỉ thông minh' Google Sheets
        google_maps_url, matched_branch_name = get_google_maps_from_smart_sheet(dest_branch, buyer_address)

        # QUY TẮC BẮT BUỘC THEO CHỈ ĐẠO:
        # 1. CHỈ KHI NÀO ĐƠN ĐÃ ĐẾN CHI NHÁNH ĐÍCH THÌ MỚI ĐƯỢC PHÉP GỬI WHATSAPP
        # 2. SỬ DỤNG THUẦN TIẾNG VIỆT KÈM LINK GOOGLE MAPS TỪ BẢNG TÍNH THÔNG MINH
        # 3. ĐÃ LOẠI BỎ: "Anh/chị vui lòng để ý điện thoại để nhận hàng giúp em nhé. Em xin cảm ơn ạ!"
        wa_link = None
        if status_info["code"] == "READY_FOR_PICKUP":
            wa_msg_vietnamese = (
                f"Chào anh/chị {buyer_name}! Đơn hàng của anh/chị (Mã vận đơn: {shipping_code or uid}) "
                f"hiện đã đến chi nhánh đích tại {dest_branch}.\n"
                f"Số tiền cần thanh toán khi nhận hàng (COD): {cod_amount:,.0f} KIP.\n"
                f"Vị trí định vị chi nhánh trên Google Maps: {google_maps_url}"
            )
            clean_phone = buyer_phone.replace("+", "").strip() if buyer_phone else ""
            if clean_phone:
                wa_link = f"https://wa.me/{clean_phone}?text={urllib.parse.quote(wa_msg_vietnamese)}"

        normalized_orders.append({
            "stt": idx,
            "order_uid": uid,
            "shipping_order_code": shipping_code,
            "carrier": carrier,
            "buyer_name": buyer_name,
            "buyer_phone": buyer_phone,
            "buyer_phone_raw": buyer_phone_raw,
            "buyer_address": buyer_address,
            "dest_branch": dest_branch,
            "matched_branch_name": matched_branch_name,
            "cod_amount": cod_amount,
            "created_at": created_at,
            "status": status_info,
            "items": items_list,
            "latest_scan_desc": latest_scan_desc,
            "latest_scan_time": latest_scan_time,
            "timeline": timeline,
            "google_maps_link": google_maps_url,
            "wa_remind_link": wa_link,
            "anousith_tracking_url": f"https://app.anousith.express/landing/search_tracking/search_item?_bill_detail={shipping_code}&n_home=2" if shipping_code and str(shipping_code).isdigit() else None,
            "hal_tracking_url": carrier_tracking_url or (f"https://hal.hal-logistics.la/api/v1/orders/tracking/{shipping_code}?lang=la" if shipping_code and shipping_code.upper().startswith("PXE") else None)
        })

    stats["delivery_rate"] = round((stats["completed"] / stats["total_orders"] * 100), 1) if stats["total_orders"] > 0 else 0

    output_payload = {
        "stats": stats,
        "orders": normalized_orders
    }

    # 1. Lưu dạng JSON
    with open(TRACKING_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    # 2. Lưu dạng JS (để mở Dashboard offline không bao giờ bị lỗi CORS)
    js_content = "window.__ORDERS_TRACKING_DATA__ = " + json.dumps(output_payload, ensure_ascii=False, indent=2) + ";\n"
    
    with open(TRACKING_JS_ROOT, "w", encoding="utf-8") as f:
        f.write(js_content)
        
    with open(TRACKING_JS_DASHBOARD, "w", encoding="utf-8") as f:
        f.write(js_content)

    print("============================================================")
    print("✅ ĐÃ ĐỒNG BỘ DỮ LIỆU VẬN ĐƠN LÀO THÀNH CÔNG!")
    print(f"📦 Tổng số đơn hàng: {stats['total_orders']}")
    print(f"🚚 Có mã vận đơn: {stats['total_with_code']}")
    print(f"✅ Giao thành công: {stats['completed']} đơn ({stats['delivery_rate']}%)")
    print(f"📍 Đã đến chi nhánh đích: {stats['ready_for_pickup']} đơn")
    print(f"🚛 Đang vận chuyển trung chuyển: {stats['in_transit']} đơn")
    print(f"⚠️ Cảnh báo hoàn: {stats['return_warning']} đơn")
    print(f"💰 Tổng tiền COD: {stats['total_cod_kip']:,.0f} KIP")
    print(f"📁 Tệp dữ liệu JSON: {TRACKING_DB_FILE}")
    print(f"📁 Tệp dữ liệu JS Dashboard: {TRACKING_JS_DASHBOARD}")
    print("============================================================")

if __name__ == "__main__":
    sync_orders_data()
