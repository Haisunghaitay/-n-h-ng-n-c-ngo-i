# QUY TẮC NGHIỆP VỤ VẬN HÀNH ĐƠN HÀNG LÀO

1. **Khóa An Toàn Tin Nhắn WhatsApp:**
   - Tuyệt đối CHỈ gửi tin nhắn WhatsApp khi đơn hàng có trạng thái `READY_FOR_PICKUP` (Đã đến chi nhánh đích).
   - Với các đơn đang vận chuyển hoặc mới tạo, nút WhatsApp bắt buộc phải bị khóa (`🔒 Chưa đến đích`).

2. **Quy Chuẩn Tin Nhắn:**
   - 100% Thuần tiếng Việt, lịch sự, ngắn gọn, tôn trọng khách hàng.
   - Luôn kèm theo link Google Maps dẫn trực tiếp đến vị trí bưu cục đích nhận hàng (`maps.app.goo.gl` hoặc toạ độ GPS).
   - Tuyệt đối KHÔNG sử dụng câu văn mẫu thừa: *"Anh/chị vui lòng để ý điện thoại để nhận hàng giúp em nhé. Em xin cảm ơn ạ!"*.

3. **Cơ Chế Tra Cứu:**
   - Đơn Anousith Express (mã số 13 ký tự bắt đầu bằng `826`): Tra cứu qua GraphQL API Anousith.
   - Đơn HAL Logistics (mã bắt đầu bằng `PXE` hoặc `HAL`): Tra cứu qua REST API HAL Logistics.
