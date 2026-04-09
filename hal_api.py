import httpx
import translation_utils

HAL_URL_TEMPLATE = "https://hal.hal-logistics.la/api/v1/orders/tracking/{}?lang=la"
HEADERS = {
    "Referer": "https://hal-logistics.la/",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

async def track_parcel(tracking_id):
    try:
        url = HAL_URL_TEMPLATE.format(tracking_id)
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                return {"success": False, "message": f"Không tìm thấy vận đơn HAL {tracking_id}."}
            resp.raise_for_status()
            data = resp.json()
            
            info = data.get("shipment_info", {})
            events = data.get("tracking_events", [])
            
            if not info:
                return {"success": False, "message": f"Dữ liệu vận đơn {tracking_id} trống."}
            
            # Translate current status
            raw_status = info.get("status", "N/A")
            status_vn = await translation_utils.translate_vet_status(raw_status)
            
            # Trả về giá trị gốc cho địa danh (không dịch)
            origin_raw = info.get("from_branch", "N/A")
            dest_raw = info.get("destination_branch", "N/A")
            
            history = []
            for ev in events:
                msg_raw = ev.get("message", "")
                place_raw = ev.get("place", "")
                
                # Trình bày lịch sử: Dịch trạng thái nhưng giữ nguyên địa danh gốc
                msg_vn = await translation_utils.translate_vet_status(msg_raw)
                
                history.append({
                    "time": ev.get("date", "N/A"),
                    "location": place_raw,
                    "status": msg_vn
                })
            
            return {
                "success": True,
                "data": {
                    "tracking_id": tracking_id,
                    "status": status_vn,
                    "status_raw": raw_status,
                    "receiver": info.get("receiver_phone_number", "N/A"),
                    "phone": info.get("receiver_phone_number", "N/A"),
                    "origin": origin_raw,
                    "origin_raw": origin_raw,
                    "destination": dest_raw,
                    "destination_raw": dest_raw,
                    "cod": info.get("total_rental_price", 0),
                    "currency": info.get("freight_currency", "lak"),
                    "history": history,
                    "carrier": "HAL"
                }
            }

    except Exception as e:
        return {"success": False, "message": f"Lỗi thực thi (HAL): {str(e)}"}

if __name__ == "__main__":
    import asyncio
    import json
    import sys
    tid = sys.argv[1] if len(sys.argv) > 1 else "PXE92460983905"
    res = asyncio.run(track_parcel(tid))
    print(json.dumps(res, indent=2, ensure_ascii=False))
