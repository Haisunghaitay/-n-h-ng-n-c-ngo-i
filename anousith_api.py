import json
import httpx
import translation_utils

GRAPHQL_URL = "https://pro.api.anousith.express/graphql"

HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://app.anousith.express/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*"
}

QUERY_ITEMS_V2 = """
query ItemsV2($where: ItemV2WhereInput, $limit: Int, $orderBy: OrderByItem) {
  itemsV2(where: $where, limit: $limit, orderBy: $orderBy) {
    total
    data {
      _id
      trackingId
      itemName
      itemStatus
      receiverName
      receiverPhone
      itemValueKIP
      isSummary
      originBranchId {
        branch_name
      }
      destBranchId {
        branch_name
      }
      originProvinceId {
        provinceName
      }
      destProvinceId {
        provinceName
      }
    }
  }
}
"""

QUERY_SCAN_ITEMS = """
query ScanItems($orderBy: OrderByInput, $where: ScanItemWhereInput, $limit: Int) {
  scanItems(orderBy: $orderBy, where: $where, limit: $limit) {
    data {
      _id
      branch {
        branch_name
      }
      center {
        centerName
      }
      createdAt
      scanStatus
    }
  }
}
"""

STATUS_MAP = {
    "COMPLETED": "✅ Đã giao hàng thành công",
    "SCAN_IN": "📥 Đã nhập kho",
    "SCAN_OUT": "📤 Đã xuất kho",
    "PENDING": "⏳ Đang chờ xử lý",
    "PICKUP": "📦 Đã lấy hàng",
    "DELIVERING": "🚚 Đang giao hàng",
    "DEST_BRANCH_RECEIVED_FORWARD": "📍 Chi nhánh đích đã nhận hàng",
    "ORIGIN_BRANCH_RECEIVED": "🏠 Chi nhánh gốc đã nhận hàng",
    "FORWARDED": "➡️ Đang chuyển tiếp",
    "RETURNED": "🔄 Đã hoàn trả",
    "CANCELED": "❌ Đã hủy"
}

def translate_status(status_code):
    return STATUS_MAP.get(status_code, status_code)

async def track_parcel(tracking_id):
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0) as client:
            # 1. Fetch Item Details
            # Use searchMultiple instead of trackingId as discovered from browser
            variables_item = {
                "where": {
                    "searchMultiple": tracking_id,
                    "isDeleted": 0
                },
                "limit": 5,
                "orderBy": "originReceiveDate_DESC"
            }
            payload_item = {
                "operationName": "ItemsV2",
                "query": QUERY_ITEMS_V2,
                "variables": variables_item
            }
            res_item = await client.post(GRAPHQL_URL, json=payload_item)
            res_item.raise_for_status()
            json_item = res_item.json()
            
            if "errors" in json_item:
                return {"success": False, "message": f"API Error (ItemsV2): {json_item['errors'][0].get('message')}"}
            
            item_data = json_item.get("data", {}).get("itemsV2", {}).get("data", []) if json_item.get("data") else []
            
            if not item_data:
                return {"success": False, "message": f"Không tìm thấy vận đơn {tracking_id}."}
            
            parcel = item_data[0]
            
            # Translate location and receiver names if they contain non-ascii
            receiver_name = parcel.get("receiverName", "N/A")
            origin = (parcel.get("originProvinceId") or {}).get("provinceName") or (parcel.get("originBranchId") or {}).get("branch_name") or "N/A"
            destination = (parcel.get("destProvinceId") or {}).get("provinceName") or (parcel.get("destBranchId") or {}).get("branch_name") or "N/A"
            
            # Translate them
            origin_vn = await translation_utils.translate_vet_status(origin)
            dest_vn = await translation_utils.translate_vet_status(destination)
            
            # Reconcile status
            is_summary = parcel.get("isSummary") == 1
            raw_status = parcel.get("itemStatus")
            
            if raw_status == "COMPLETED":
                if is_summary:
                    status_vn = "✅ Giao hàng hoàn tất (Đã đối soát)"
                else:
                    status_vn = "🚚 Giao hàng hoàn tất (Chưa đối soát)"
            else:
                status_vn = translate_status(raw_status)
            
            # 2. Fetch Scan History
            variables_scan = {
                "where": {
                    "trackingId": tracking_id
                },
                "orderBy": "createdAt_DESC",
                "limit": 50
            }
            payload_scan = {
                "operationName": "ScanItems",
                "query": QUERY_SCAN_ITEMS,
                "variables": variables_scan
            }
            res_scan = await client.post(GRAPHQL_URL, json=payload_scan)
            res_scan.raise_for_status()
            json_scan = res_scan.json()
            
            if "errors" in json_scan:
                 return {"success": False, "message": f"API Error (ScanItems): {json_scan['errors'][0].get('message')}"}
            
            scan_data = []
            if json_scan.get("data") and json_scan["data"].get("scanItems"):
                scan_data = json_scan["data"]["scanItems"].get("data", [])
            
            # 3. Format result
            history = []
            for scan in scan_data:
                if not scan: continue
                loc_raw = (scan.get("branch") or {}).get("branch_name") or (scan.get("center") or {}).get("centerName") or "N/A"
                loc = await translation_utils.translate_vet_status(loc_raw)
                status_code = scan.get("scanStatus") or "Unknown"
                status = translate_status(status_code)
                time = scan.get("createdAt", "")
                history.append({
                    "time": time,
                    "location": loc,
                    "status": status
                })
            
            # Sort history by time
            history.sort(key=lambda x: x["time"], reverse=True)

            return {
                "success": True,
                "data": {
                    "tracking_id": parcel.get("trackingId"),
                    "status": status_vn,
                    "status_raw": raw_status,
                    "receiver": receiver_name,
                    "phone": parcel.get("receiverPhone"),
                    "origin": origin_vn,
                    "origin_raw": origin,
                    "destination": dest_vn,
                    "destination_raw": destination,
                    "cod": parcel.get("itemValueKIP"),
                    "history": history
                }
            }

            
    except Exception as e:
        return {"success": False, "message": f"Lỗi thực thi: {str(e)}"}

if __name__ == "__main__":
    import asyncio
    tid = "8260917179024"
    result = asyncio.run(track_parcel(tid))
    print(json.dumps(result, indent=2, ensure_ascii=False))
