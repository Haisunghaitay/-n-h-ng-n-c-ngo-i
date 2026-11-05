# -*- coding: utf-8 -*-
"""
hal_api.py - BỘ TRA CỨU VẬN ĐƠN HAL LOGISTICS (LÀO)
Kết nối trực tiếp API HAL Logistics: https://hal.hal-logistics.la/api/v1/orders/tracking/{tracking_id}?lang=la
Không phụ thuộc vào thư viện ngoài, trả về dữ liệu chuẩn hóa phục vụ Dashboard.
"""

import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

HAL_URL_TEMPLATE = "https://hal.hal-logistics.la/api/v1/orders/tracking/{}?lang=la"
HEADERS = {
    "Referer": "https://hal-logistics.la/",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Từ điển chuẩn hóa trạng thái HAL Logistics
HAL_STATUS_TRANSLATION = {
    "ຮັບພັດສະດຸແລ້ວ": "Bưu cục gửi đã nhận kiện",
    "ພັດສະດຸຮອດ": "Đã đến trạm / kho luân chuyển",
    "ກໍາລັງຈັດສົ່ງໄປ": "Đang vận chuyển luân chuyển",
    "ກຳລັງຂົນສົ່ງ": "Đang trên đường vận chuyển",
    "ຈັດສົ່ງສຳເລັດ": "Giao hàng thành công",
    "ສຳເລັດການຮັບຝາກ": "Giao hàng thành công",
    "ສົ່ງຄືນແລ້ວ": "Đã chuyển hoàn",
    "ລໍຖ້າລູກຄ້າມາຮັບ": "Đã đến bưu cục đích",
}

def translate_hal_message(msg: str) -> str:
    """Dịch thông điệp sự kiện của HAL sang tiếng Việt dễ hiểu."""
    if not msg:
        return ""
    m = msg.strip()
    if "ສຳເລັດການຮັບຝາກ" in m or "ຈັດສົ່ງສຳເລັດ" in m:
        return "Giao hàng thành công (Khách đã nhận kiện)"
    if "ສົ່ງຄືນ" in m or "ຕີກັບ" in m:
        return "Sự cố giao hàng / Đang chuyển hoàn"
    if "ກໍາລັງຈັດສົ່ງໄປ" in m or "ກຳລັງຂົນສົ່ງ" in m:
        return "Đang trên đường vận chuyển luân chuyển"
    if "ຮັບພັດສະດຸແລ້ວ" in m:
        return "Bưu cục gửi đã nhận kiện hàng"
    if "ພັດສະດຸຮອດ" in m:
        return "Kiện hàng đã đến trạm khai thác"
    return m

def track_parcel_hal(tracking_id: str) -> Dict[str, Any]:
    """
    Tra cứu mã vận đơn HAL Logistics qua API chính thức.
    Trả về Dict chuẩn hóa.
    """
    tid = str(tracking_id).strip().upper()
    url = HAL_URL_TEMPLATE.format(tid)
    req = urllib.request.Request(url, headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status == 404:
                return {"success": False, "message": f"Không tìm thấy vận đơn HAL {tid}"}
            
            data = json.loads(resp.read().decode("utf-8"))
            info = data.get("shipment_info", {})
            events = data.get("tracking_events", [])

            if not info:
                return {"success": False, "message": f"Dữ liệu vận đơn {tid} trống"}

            raw_status = info.get("status", "")
            dest_branch = info.get("destination_branch", "")
            from_branch = info.get("from_branch", "")
            dest_tel = info.get("destination_branch_tel", "")
            receiver_phone = info.get("receiver_phone_number", "")
            receiver_name = info.get("receiver_name", "")

            # Chuẩn hóa trạng thái
            canonical_code = "IN_TRANSIT"
            status_label = "Đang vận chuyển luân chuyển"

            if raw_status in ["ຈັດສົ່ງສຳເລັດ", "ສຳເລັດການຮັບຝາກ"] or info.get("delivery_date"):
                canonical_code = "DELIVERED"
                status_label = "Giao hàng thành công"
            elif info.get("has_been_returned"):
                canonical_code = "EXCEPTION"
                status_label = "Đơn hàng đã chuyển hoàn"
            else:
                # Kiểm tra xem sự kiện cuối có phải đã tới bưu cục đích chưa
                if events:
                    last_event = events[-1]
                    last_place = str(last_event.get("place", ""))
                    last_msg = str(last_event.get("message", ""))
                    delivery_state = last_event.get("delivery_state", 0)

                    if dest_branch and (dest_branch in last_place or last_place in dest_branch) and "ຮອດ" in last_msg:
                        canonical_code = "READY_FOR_PICKUP"
                        status_label = f"Đã đến chi nhánh đích ({dest_branch})"
                    elif delivery_state == 6:
                        canonical_code = "DELIVERED"
                        status_label = "Giao hàng thành công"

            # Chuẩn hóa timeline
            history = []
            for ev in events:
                place = ev.get("place", "")
                msg = ev.get("message", "")
                msg_vn = translate_hal_message(msg)
                history.append({
                    "date": ev.get("date", ""),
                    "place": place,
                    "message_raw": msg,
                    "message_vn": msg_vn,
                    "delivery_state": ev.get("delivery_state", 0),
                    "delivery_state_name": ev.get("delivery_state_name", "")
                })

            return {
                "success": True,
                "carrier": "hal",
                "carrier_name": "HAL Logistics",
                "tracking_id": tid,
                "canonical_code": canonical_code,
                "status_label": status_label,
                "raw_status": raw_status,
                "destination_branch": dest_branch,
                "from_branch": from_branch,
                "branch_phone": dest_tel,
                "receiver_name": receiver_name,
                "receiver_phone": receiver_phone,
                "pickup_date": info.get("pickup_date"),
                "delivery_date": info.get("delivery_date"),
                "cod_amount": info.get("total_rental_price", 0),
                "history": history
            }

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"success": False, "message": f"Mã vận đơn HAL {tid} chưa xuất hiện trên hệ thống."}
        return {"success": False, "message": f"Lỗi máy chủ HAL (HTTP {e.code})"}
    except Exception as e:
        return {"success": False, "message": f"Lỗi kết nối HAL: {str(e)}"}

if __name__ == "__main__":
    import sys
    test_code = sys.argv[1] if len(sys.argv) > 1 else "PXE46905477845"
    res = track_parcel_hal(test_code)
    print(json.dumps(res, indent=2, ensure_ascii=False))
