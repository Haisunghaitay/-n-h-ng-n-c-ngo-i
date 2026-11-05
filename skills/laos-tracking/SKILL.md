---
name: laos-tracking
description: Quản lý, đồng bộ và tra cứu hành trình vận đơn thị trường Lào qua Anousith Express và HAL Logistics.
---

# Kỹ Năng: Theo Dõi Vận Đơn Lào (Anousith & HAL Logistics)

Sử dụng kỹ năng này khi:
- Người dùng yêu cầu đồng bộ vận đơn Lào từ kho Thái Dương (tdffm.com - LAO162).
- Cần tra cứu hành trình thời gian thực của đơn hàng Anousith Express hoặc HAL Logistics.
- Cần lấy link định vị Google Maps của chi nhánh bưu cục tại Lào.
- Cần tạo tin nhắn WhatsApp gửi thông báo cho khách hàng khi đơn đã về đến trạm đích.
- Quản lý và kiểm tra dữ liệu hiển thị trên Dashboard Theo Dõi Vận Đơn Lào.

## Hướng Dẫn Thực Thi
1. **Đồng bộ dữ liệu:** Chạy lệnh `python3 scripts/tdffm_anousith_tracking_sync.py` để kéo đơn và quét hành trình.
2. **Khởi động Dashboard:** Chạy lệnh `Chay_Dashboard_Van_Don_Lao.command` hoặc mở trình duyệt tại `http://localhost:8080/dashboard_theo_doi_van_don_lao.html`.
3. **Quy định gửi tin nhắn:** Chỉ kích hoạt tin nhắn WhatsApp khi trạng thái là `READY_FOR_PICKUP`.
