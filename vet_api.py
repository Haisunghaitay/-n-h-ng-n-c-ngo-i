import httpx
import re
import translation_utils

# VET App Internal API Configuration (Captured from App sniffing)
VET_API_BASE = "https://tomapicaps.utlog.net/vetAppApi/goods-transfer/find/{}"
VET_HEADERS = {
    "authorization": "bearer 9b7ea6cc-90f7-41e5-8556-ea60be1f2e2f",
    "user-agent": "Dart/3.11 (dart:io)",
    "content-type": "application/json",
    "accept-encoding": "gzip",
    "content-length": "0"
}

def extract_internal_id(tracking_id):
    """
    Transforms barcode (e.g. 2604184282859-kh) to internal ID (e.g. 184282859).
    Logic: Remove '-kh' suffix, ensure it starts with '2604', then take the digits after '2604'.
    """
    clean_id = tracking_id.lower().replace("-kh", "").strip()
    if clean_id.startswith("2604") and len(clean_id) > 4:
        return clean_id[4:]
    return clean_id

async def track_parcel(tracking_id):
    try:
        internal_id = extract_internal_id(tracking_id)
        url = VET_API_BASE.format(internal_id)
        
        async with httpx.AsyncClient(headers=VET_HEADERS, timeout=15.0) as client:
            # The app uses POST/find/{id} with no body
            res = await client.post(url)
            res.raise_for_status()
            data = res.json()
            
            if not data.get("header", {}).get("result") or not data.get("body", {}).get("data"):
                return {"success": False, "message": f"Không tìm thấy vận đơn VET {tracking_id}."}
            
            parcel = data["body"]["data"][0]
            
            # Map tracking history
            history = []
            move_list = parcel.get("goodsTransferMoveList", [])
            for move in move_list:
                msg_kh = move.get("msg", "")
                # Translate status message if possible
                status_translated = await translation_utils.translate_text(msg_kh)
                
                history.append({
                    "time": move.get("created", ""),
                    "location": "", 
                    "status": status_translated
                })
            
            # Format main fields
            origin_kh = parcel.get("destinationFromEn", "N/A")
            dest_kh = parcel.get("destinationToEn", "N/A")
            
            # Translate locations
            origin = await translation_utils.translate_text(origin_kh)
            destination = await translation_utils.translate_text(dest_kh)
            
            # Extraction of receiver info
            receiver_phone = parcel.get("receiverTelephone", "N/A")
            sender_phone = parcel.get("senderTelephone", "N/A")
            
            # COD logic (Check for price/cod keys if they exist in other responses)
            cod_val = parcel.get("price", 0) or parcel.get("cod", 0) or 0
            
            return {
                "success": True,
                "data": {
                    "tracking_id": tracking_id,
                    "status": history[0]["status"] if history else "N/A",
                    "status_raw": move_list[0].get("msg", "") if move_list else "N/A",
                    "receiver": f"SĐT: {receiver_phone}",
                    "phone": receiver_phone,
                    "sender_phone": sender_phone,
                    "origin": origin,
                    "origin_raw": origin_kh,
                    "destination": destination,
                    "destination_raw": dest_kh,
                    "cod": cod_val,
                    "history": history,
                    "carrier": "VET"
                }
            }

            
    except Exception as e:
        return {"success": False, "message": f"Lỗi thực thi (VET App API): {str(e)}"}

if __name__ == "__main__":
    import asyncio
    import json
    tid = "2604184282859-kh"
    result = asyncio.run(track_parcel(tid))
    print(json.dumps(result, indent=2, ensure_ascii=False))

async def fetch_user_parcels():
    url = "https://tomapicaps.utlog.net/vetAppApi/goods-transfer/list"
    headers = {
        "authorization": "bearer 9b7ea6cc-90f7-41e5-8556-ea60be1f2e2f",
        "user-agent": "Dart/3.11 (dart:io)",
        "content-type": "application/json",
        "accept-encoding": "gzip",
    }
    payload = {"destinationFromId":0,"destinationToId":0,"page":1,"rowsPerPage":100,"type":1,"status":0}
    
    try:
        async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
            res = await client.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            
            if not data.get("body", {}).get("status"):
                return {"success": False, "message": "Failed to fetch list from VET."}
            
            items = data["body"].get("data", [])
            results = []
            for item in items:
                # Reconstruct full tracking ID to match system format
                # Barcode logic (sometimes it uses standard format): 2604{id}-kh
                # The code field has something like 'PPDP-phnompenhtmey260400005', 
                # but our bot uses '2604{id}-kh' for VET tracking conventionally
                t_id = f"2604{item['id']}-kh"
                results.append({
                    "id": item["id"],
                    "code": item["code"],
                    "tracking_id": t_id,
                    "date": item.get("date"),
                    "receiverTelephone": item.get("receiverTelephone"),
                    "destinationToEn": item.get("destinationToEn"),
                })
            
            return {"success": True, "data": results}
    except Exception as e:
        return {"success": False, "message": f"Lỗi (VET List API): {str(e)}"}
