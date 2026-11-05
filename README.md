# Plugin: Theo Dõi Vận Đơn Lào (Anousith & HAL Logistics)

Plugin chuyên dụng cho thị trường thương mại điện tử và xuất khẩu hàng hóa sang **Lào**.

## Tính Năng Cốt Lõi
1. **Đồng bộ tự động từ Thái Dương Fulfillment (TDFFM - LAO162)**: Tự động gia hạn Access Token qua Refresh Token chống đăng xuất tài khoản.
2. **Tra cứu thời gian thực 2 hãng vận chuyển**:
   - **Anousith Express**: Tra cứu GraphQL `itemsV2` + `scanItems` (mã số `826...`).
   - **HAL Logistics**: Tra cứu REST API v1 chính thức (mã `PXE...`).
3. **Mạng lưới bưu cục thông minh**: So khớp tên trạm với 3.965 bưu cục trên Google Sheet để lấy vị trí Google Maps chuẩn (`maps.app.goo.gl`).
4. **Khóa an toàn WhatsApp**: Chỉ cho phép sinh link và gửi tin nhắn WhatsApp khi đơn hàng **ĐÃ ĐẾN CHI NHÁNH ĐÍCH**. Tin nhắn 100% thuần tiếng Việt, loại bỏ văn mẫu dặn dò thừa.
5. **Dashboard Trực Quan**: Bảng điều khiển HTML/JS hiện đại với đầy đủ thẻ số liệu, bộ lọc thông minh và cửa sổ xem hành trình quét trạm.
