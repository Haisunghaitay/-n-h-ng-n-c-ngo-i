# -*- coding: utf-8 -*-
"""
HỆ THỐNG ĐẶT LỊCH CHẠY TỰ ĐỘNG THEO DÕI VẬN ĐƠN LÀO (2 LẦN/NGÀY)
Khung giờ thực thi:
- 09:00 Sáng: Quét đơn mới phát sinh và cập nhật trạng thái thực tế từ Anousith & HAL.
- 14:00 Chiều: Quét đơn cập nhật hành trình buổi chiều từ Anousith & HAL.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "lao_tracking_sync.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)

def run_sync_job():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Bắt đầu phiên đồng bộ tự động vận đơn Lào...")
    logging.info("Bắt đầu phiên đồng bộ tự động vận đơn Lào.")
    try:
        import tdffm_anousith_tracking_sync
        tdffm_anousith_tracking_sync.sync_orders_data()
        logging.info("Hoàn tất phiên đồng bộ thành công.")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Đồng bộ thành công!")
    except Exception as e:
        logging.error(f"Lỗi đồng bộ: {e}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Lỗi: {e}")

def main():
    print("==================================================================")
    print("🕒 TRÌNH TỰ ĐỘNG ĐỒNG BỘ VẬN ĐƠN LÀO (LỊCH 2 LẦN / NGÀY: 09:00 & 18:00)")
    print("==================================================================")
    
    # Chạy thử nghiệm ngay một lần đầu tiên khi khởi động
    run_sync_job()

    last_ran_date_hour = ""

    while True:
        now = datetime.now()
        current_time_key = now.strftime("%Y-%m-%d_%H")
        
        # Kiểm tra nếu rơi vào đúng khung giờ 09:00 hoặc 14:00 và chưa chạy trong giờ này
        if now.hour in [9, 14] and current_time_key != last_ran_date_hour:
            last_ran_date_hour = current_time_key
            run_sync_job()
            
        time.sleep(60) # Kiểm tra mỗi phút một lần

if __name__ == "__main__":
    # Nếu truyền cờ --once thì chỉ chạy 1 lần và thoát
    if "--once" in sys.argv:
        run_sync_job()
    else:
        main()

