import asyncio
import json
import os
import logging
from dotenv import load_dotenv

load_dotenv()
import html
import re
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, CopyTextButton
from aiohttp import web
import anousith_api
import vet_api
import hal_api
import tdffm_api

# Cấu hình
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Fatal Error: Không tìm thấy TELEGRAM_BOT_TOKEN. Vui lòng cấu hình biến môi trường hoặc file .env")
TRACKING_LIST_FILE = 'tracking_list.json'
TRACKING_TIME_FILE = 'tracking_time_state.json'
TRACKING_STATE_FILE = 'tracking_history_state.json'
TRACKING_PHONE_FILE = 'tracking_phone_state.json'

# --- QUẢN LÝ TRẠNG THÁI (UI STATE) ---
user_states = {}

def get_user_state(user_id):
    uid = str(user_id)
    if uid not in user_states:
        user_states[uid] = {'delete_mode': False, 'selected_tids': set()}
    return user_states[uid]


COMPLETED_KEYWORDS = [
    "đã đối soát",
    "package received successfully",
    "giao hàng hoàn tất",
    "delivered successfully",
    "đã giao hàng thành công",
]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- DATABASE UTILS ---
def load_json(filename, default=None):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return default if default is not None else []

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def is_completed(tid):
    state = load_json(TRACKING_STATE_FILE, {})
    if not isinstance(state, dict): return False
    last_status = state.get(tid, "")
    if not last_status: return False
    return any(kw in last_status.lower() for kw in COMPLETED_KEYWORDS)

def delete_from_state(tid):
    history_state = load_json(TRACKING_STATE_FILE, {})
    if isinstance(history_state, dict) and tid in history_state:
        del history_state[tid]
        save_json(TRACKING_STATE_FILE, history_state)

    time_state = load_json(TRACKING_TIME_FILE, {})
    if isinstance(time_state, dict) and tid in time_state:
        del time_state[tid]
        save_json(TRACKING_TIME_FILE, time_state)

    phone_state = load_json(TRACKING_PHONE_FILE, {})
    if isinstance(phone_state, dict) and tid in phone_state:
        del phone_state[tid]
        save_json(TRACKING_PHONE_FILE, phone_state)


# --- API UTILS ---
async def get_parcel_info(tracking_id):
    tid = tracking_id.strip()

    if tid.upper().startswith(("HAL", "PXE")):
        carrier = "hal"
    elif tid.endswith("-kh") or len(tid) == 16:
        carrier = "vet"
    else:
        carrier = "anousith"

    if carrier == "hal":
        result = await hal_api.track_parcel(tid)
        if result["success"]:
            result["data"]["carrier_name"] = "HAL Logistics"
            return result
    elif carrier == "vet":
        result = await vet_api.track_parcel(tid)
        if result["success"]:
            result["data"]["carrier_name"] = "VET Express"
            return result
        # Fallback thử Anousith nếu VET lỗi (hoặc tìm nhầm)
        result_alt = await anousith_api.track_parcel(tid)
        if result_alt["success"]:
            result_alt["data"]["carrier_name"] = "Anousith Express"
            return result_alt
    else:
        result = await anousith_api.track_parcel(tid)
        if result["success"]:
            result["data"]["carrier_name"] = "Anousith Express"
            return result
        # Fallback thử VET
        result_alt = await vet_api.track_parcel(tid)
        if result_alt["success"]:
            result_alt["data"]["carrier_name"] = "VET Express"
            return result_alt

    return result

def format_parcel_msg(result):
    d = result["data"]
    carrier = d.get('carrier', '').upper()
    is_hal = carrier == 'HAL'
    is_vet = carrier == 'VET'
    is_anousith = carrier == 'ANOUSITH'

    res_text = (
        f"<b>[{d.get('carrier_name', 'Hãng')}]</b>\n"
        f"📦 <b>VẬN ĐƠN: {html.escape(str(d['tracking_id']))}</b>\n"
        f"🚩 Trạng thái: <b>{html.escape(str(d['status']))}</b>\n"
    )

    if is_vet and d.get('status_raw') and d.get('status_raw') != 'N/A':
        res_text += f"   <i>⤷ {html.escape(str(d['status_raw']))}</i>\n"

    if d.get('sender_phone') and d.get('sender_phone') != "N/A":
        res_text += f"👤 Người gửi: {html.escape(str(d['sender_phone']))}\n"

    phone = d.get('phone', 'N/A')
    if phone and phone != "N/A":
        if is_anousith:
            res_text += f"👤 Người nhận: {html.escape(str(d.get('receiver', 'N/A')))} ({html.escape(str(phone))})\n"
        else:
            res_text += f"👤 Người nhận: {html.escape(str(phone))}\n"
    elif d.get('receiver') and d.get('receiver') != "N/A":
        res_text += f"👤 Người nhận: {html.escape(str(d['receiver']))}\n"

    origin = d.get('origin', 'N/A')
    dest = d.get('destination', 'N/A')
    if (origin and origin != "N/A") or (dest and dest != "N/A"):
        res_text += f"📍 Lộ trình: {html.escape(str(origin))} ➡️ {html.escape(str(dest))}\n"
        if is_vet:
            origin_raw = d.get('origin_raw', '')
            dest_raw = d.get('destination_raw', '')
            if (origin_raw and origin_raw not in ['N/A', origin]) or (dest_raw and dest_raw not in ['N/A', dest]):
                res_text += f"   <i>⤷ {html.escape(str(origin_raw))} ➡️ {html.escape(str(dest_raw))}</i>\n"

    cod = d.get('cod', 0)
    if cod and cod > 0:
        currency = "USD" if is_vet else d.get('currency', 'KIP').upper()
        res_text += f"💰 Tiền COD/Phí: <b>{cod:,} {currency}</b>\n"

    res_text += (
        f"--------------------\n"
        f"🕒 Cập nhật cuối: {html.escape(d['history'][0]['time'] if d.get('history') else 'N/A')}"
    )
    return res_text


# --- CHỨC NĂNG KEYBOARD CHÍNH ---
def get_dashboard_content(user_id):
    """
    Tạo nội dung chữ và Inline Keyboard theo cấu trúc:
    - Text: Số thứ tự + Mã Vận Đơn dạng copy được (code).
    - Keyboard: Số thứ tự tương ứng + Trạng thái.
    """
    tracking_list = load_json(TRACKING_LIST_FILE, [])
    history_state = load_json(TRACKING_STATE_FILE, {})
    
    state = get_user_state(user_id)
    is_delete_mode = state['delete_mode']
    selected = state['selected_tids']

    def get_carrier(tid):
        tid_u = tid.upper()
        if tid_u.startswith(("HAL", "PXE")): return "🛡 HAL LOGISTICS"
        elif tid.endswith("-kh") or len(tid) == 16: return "🚚 VET EXPRESS"
        else: return "📦 ANOUSITH (TDFFM)"

    groups = {"🚚 VET EXPRESS": [], "📦 ANOUSITH (TDFFM)": [], "🛡 HAL LOGISTICS": []}
    for tid in tracking_list:
        groups[get_carrier(tid)].append(tid)

    # --- TẠO TEXT ---
    phone_state = load_json(TRACKING_PHONE_FILE, {})
    text_lines = [f"📋 <b>BẢNG ĐIỀU KHIỂN (Đang theo dõi: {len(tracking_list)} đơn)</b>\n"]
    
    def get_status_icon(text):
        t = text.lower()
        if any(k in t for k in ["thành công", "đã nhận", "hoàn thành", "xong"]): return "✅"
        if any(k in t for k in ["đang giao", "giao hàng", "xuất kho", "đi giao"]): return "🚚"
        if any(k in t for k in ["không nghe", "không nhấc", "thất bại", "lỗi", "không nâng"]): return "❌"
        if any(k in t for k in ["cuộc gọi", "gọi", "điện thoại"]): return "📞"
        if any(k in t for k in ["kho", "điểm", "bưu cục", "cơ quan", "chi nhánh", "đại lý", "hq"]): return "🏢"
        return "📦"

    if is_delete_mode:
        text_lines.append("🗑 <b>CHẾ ĐỘ XÓA</b>: Bấm vào nút 'Xóa' bên cạnh mã vận đơn để chọn.")
    else:
        for carrier, tids in groups.items():
            if not tids: continue
            text_lines.append(f"<b>{carrier}</b>")
            for tid in tids:
                phone = phone_state.get(tid, "")
                phone_text = f" | SĐT: <code>{html.escape(phone)}</code>" if phone and phone != "N/A" else ""
                status = history_state.get(tid, "Đang xử lý")
                icon = get_status_icon(status)
                status_short = status[:60] + "..." if len(status) > 60 else status
                text_lines.append(f"• <code>{html.escape(tid)}</code>{phone_text}\n  ↳ {icon} <i>{html.escape(status_short)}</i>")
            text_lines.append("") # Xuống dòng cho đẹp
    
    final_text = ""
    for line in text_lines:
        if len(final_text) + len(line) > 4000:
            final_text += "\n...(Danh sách quá dài đã bị cắt bớt)"
            break
        final_text += line + "\n"
    text = final_text.strip()

    # --- TẠO KEYBOARD ---
    keyboard = []
    
    for carrier, tids in groups.items():
        if not tids: continue
        
        if is_delete_mode:
            # Thêm vạch phân cách
            keyboard.append([InlineKeyboardButton(text=f"━━━ {carrier} ━━━", callback_data="ignore")])
            
            for tid in tids:
                btn_left = f"🗑 {tid}"
                btn_right = f"{'✅' if tid in selected else '⬜️'} Xóa"
                cb = f"toggle:{tid}"
                
                keyboard.append([
                    InlineKeyboardButton(text=btn_left, copy_text=CopyTextButton(text=tid)),
                    InlineKeyboardButton(text=btn_right, callback_data=cb)
                ])

    if is_delete_mode:
        keyboard.append([
            InlineKeyboardButton(text="Hủy", callback_data="cancel_delete"),
            InlineKeyboardButton(text=f"Xác nhận xóa ({len(selected)})", callback_data="confirm_delete")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(text="🗑 Xóa", callback_data="delete_mode"),
            InlineKeyboardButton(text="🛑 Xóa tất cả", callback_data="delete_all")
        ])

    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


# --- TELEGRAM HANDLERS CHÍNH ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Chào mừng bạn đến với <b>Tracking Bot Control Panel</b>!\n\n"
        "Các lệnh hỗ trợ:\n"
        "📋 <code>/list</code> - Tự động đồng bộ và mở Bảng điều khiển quản lý đơn hàng.\n"
        "🔍 <code>/track [mã_vận_đơn]</code> - Xem chi tiết quá trình vận chuyển của 1 đơn.\n\n"
        "<i>Mọi thao tác quản lý/xoá sẽ được tích hợp ngay trên Bảng điều khiển.</i>",
        parse_mode="HTML"
    )

@dp.message(Command("list"))
async def cmd_list(message: Message):
    msg_wait = await message.answer("🔄 Đang đồng bộ và chuẩn bị dữ liệu bảng điều khiển...")

    tracking_list = load_json(TRACKING_LIST_FILE, [])

    # 1. Đồng bộ VET
    vet_added = 0
    vet_skipped = 0
    vet_res = await vet_api.fetch_user_parcels()
    if vet_res["success"] and vet_res.get("data"):
        for p in vet_res["data"]:
            tid = p["tracking_id"]
            if tid in tracking_list: continue
            if is_completed(tid):
                vet_skipped += 1
                continue
            tracking_list.append(tid)
            vet_added += 1

    # 2. Đồng bộ TDFFM 
    tdffm_added = 0
    tdffm_skipped = 0
    tdffm_error = ""
    tdffm_res = await tdffm_api.fetch_orders()
    if tdffm_res["success"] and tdffm_res.get("data"):
        for p in tdffm_res["data"]:
            tid = p["tracking_id"]
            if tid in tracking_list: continue
            if is_completed(tid):
                tdffm_skipped += 1
                continue
            tracking_list.append(tid)
            tdffm_added += 1
    elif not tdffm_res["success"]:
        tdffm_error = f"\n⚠️ <b>Lỗi đồng bộ TDFFM</b>: {tdffm_res.get('message', 'Không rõ')}"

    if vet_added > 0 or tdffm_added > 0:
        save_json(TRACKING_LIST_FILE, tracking_list)

    skip_note = ""
    if vet_skipped + tdffm_skipped > 0:
        skip_note = f"\n⏭ Bỏ qua <b>{vet_skipped + tdffm_skipped}</b> đơn đã hoàn thành."

    res_text = (
        f"✅ <b>Đã gom đơn thành công</b>\n\n"
        f"📦 Từ VET App: thêm mới <b>{vet_added}</b> đơn.\n"
        f"🌐 Từ TDFFM: thêm mới <b>{tdffm_added}</b> đơn."
        f"{skip_note}{tdffm_error}\n\n"
    )
    
    await msg_wait.edit_text(res_text + "⏳ <i>Đang cào dữ liệu trạng thái mới nhất cho các đơn...</i>", parse_mode="HTML")

    # 3. Quét trạng thái hiện tại cho TOÀN BỘ danh sách đang theo dõi để hiển thị chữ liền
    history_state = load_json(TRACKING_STATE_FILE, {})
    phone_state = load_json(TRACKING_PHONE_FILE, {})
    
    sem = asyncio.Semaphore(5) # Tránh quá tải request
    async def fetch_and_cache(tid):
        async with sem:
            try:
                res = await get_parcel_info(tid)
                if res["success"]:
                    data = res["data"]
                    if data.get("history"):
                        status = data["history"][0].get("status_raw") or data["history"][0].get("status", "")
                        if status:
                            history_state[tid] = status
                    
                    phone = str(data.get("phone", "")).strip()
                    if phone and phone != "N/A" and phone != "None":
                        phone_state[tid] = phone
            except Exception as e:
                logging.error(f"Lỗi quét {tid}: {e}")

    # Chạy quét song song tất cả vận đơn
    await asyncio.gather(*(fetch_and_cache(tid) for tid in tracking_list))
    save_json(TRACKING_STATE_FILE, history_state)
    save_json(TRACKING_PHONE_FILE, phone_state)

    user_state = get_user_state(message.from_user.id)
    user_state['delete_mode'] = False
    user_state['selected_tids'].clear()

    text, markup = get_dashboard_content(message.from_user.id)
    await msg_wait.edit_text(text, reply_markup=markup, parse_mode="HTML")

@dp.message(Command("track"))
async def cmd_track(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("👉 Vui lòng nhập mã vận đơn.\nVD: <code>/track 123456</code>", parse_mode="HTML")
    
    tid = args[1].strip()
    msg_wait = await message.answer(f"⏳ Đang tra cứu chi tiết lộ trình cho {html.escape(tid)}...")
    
    result = await get_parcel_info(tid)
    if not result["success"]:
        return await msg_wait.edit_text(f"❌ Không tìm thấy thông tin: {html.escape(result.get('message', 'Lỗi không xác định'))}")
        
    await msg_wait.edit_text(format_parcel_msg(result), parse_mode="HTML")


# --- CALLBACK BẢNG CHUYỂN HƯỚNG INTERACTIVE ---

@dp.callback_query(F.data == "ignore")
async def cb_ignore(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data == "delete_mode")
async def cb_delete_mode(callback: CallbackQuery):
    state = get_user_state(callback.from_user.id)
    state['delete_mode'] = True
    state['selected_tids'].clear()
    text, markup = get_dashboard_content(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "cancel_delete")
async def cb_cancel_delete(callback: CallbackQuery):
    state = get_user_state(callback.from_user.id)
    state['delete_mode'] = False
    state['selected_tids'].clear()
    
    text, markup = get_dashboard_content(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(callback: CallbackQuery):
    tid = callback.data.split(":")[1]
    state = get_user_state(callback.from_user.id)
    if tid in state['selected_tids']:
        state['selected_tids'].remove(tid)
    else:
        state['selected_tids'].add(tid)
        
    text, markup = get_dashboard_content(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "confirm_delete")
async def cb_confirm_delete(callback: CallbackQuery):
    state = get_user_state(callback.from_user.id)
    selected = state['selected_tids']
    if not selected:
        return await callback.answer("Bạn chưa chọn đơn nào!", show_alert=True)
        
    tracking_list = load_json(TRACKING_LIST_FILE, [])
    for tid in selected:
        if tid in tracking_list:
            tracking_list.remove(tid)
            delete_from_state(tid)
            
    save_json(TRACKING_LIST_FILE, tracking_list)
    count = len(selected)
    
    state['delete_mode'] = False
    state['selected_tids'].clear()
    
    text, markup = get_dashboard_content(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "delete_all")
async def cb_delete_all(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Hủy", callback_data="cancel_delete"),
         InlineKeyboardButton(text="⚠️ Xác nhận XÓA TẤT CẢ", callback_data="confirm_delete_all")]
    ])
    await callback.message.edit_text(
        "🛑 <b>CẢNH BÁO</b>\nBạn sắp xóa toàn bộ danh sách đơn hàng đang theo dõi. Bạn có chắc chắn không?",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "confirm_delete_all")
async def cb_confirm_delete_all(callback: CallbackQuery):
    tracking_list = load_json(TRACKING_LIST_FILE, [])
    for tid in tracking_list:
        delete_from_state(tid)
    save_json(TRACKING_LIST_FILE, [])
    
    state = get_user_state(callback.from_user.id)
    state['delete_mode'] = False
    state['selected_tids'].clear()
    
    await callback.message.edit_text("✅ Đã dọn sạch toàn bộ danh sách theo dõi. Nhấn /sync_all để lấy đơn mới.", parse_mode="HTML")

@dp.callback_query(F.data.startswith("view:"))
async def cb_view(callback: CallbackQuery):
    tid = callback.data.split(":")[1]
    
    # Hiển thị Loading pop-up nhỏ
    await callback.answer(f"Đang tải {tid} thật nhanh...", show_alert=False)
    
    result = await get_parcel_info(tid)
    if not result["success"]:
        res_text = f"❌ Không tra cứu được <code>{html.escape(tid)}</code>: {html.escape(result['message'])}"
    else:
        res_text = format_parcel_msg(result)
        
        # Tiện thể Update Cache State luôn 
        data = result["data"]
        history = data.get("history", [])
        if history:
            history_state = load_json(TRACKING_STATE_FILE, {})
            current_status = history[0].get("status_raw") or history[0].get("status", "")
            if history_state.get(tid) != current_status:
                history_state[tid] = current_status
                save_json(TRACKING_STATE_FILE, history_state)
                
        phone = str(data.get("phone", "")).strip()
        if phone and phone != "N/A" and phone != "None":
            phone_state = load_json(TRACKING_PHONE_FILE, {})
            if phone_state.get(tid) != phone:
                phone_state[tid] = phone
                save_json(TRACKING_PHONE_FILE, phone_state)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Quay lại danh sách", callback_data="back_to_list")]
    ])
    await callback.message.edit_text(res_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "back_to_list")
async def cb_back_to_list(callback: CallbackQuery):
    tracking_list = load_json(TRACKING_LIST_FILE, [])
    state = get_user_state(callback.from_user.id)
    state['delete_mode'] = False
    state['selected_tids'].clear()
    
    text, markup = get_dashboard_content(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

# --- START ROUTINE ---

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"[SYSTEM] Web Server giả lập đang mở rào cổng {port} để tương thích với dịch vụ Render!")

async def main():
    admin_id_file = 'admin_id.txt'
    admin_id = None
    if os.path.exists(admin_id_file):
        with open(admin_id_file, 'r') as f:
            admin_id = f.read().strip()

    @dp.message()
    async def global_handler(message: Message):
        nonlocal admin_id
        if not admin_id:
            admin_id = str(message.from_user.id)
            with open(admin_id_file, 'w') as f:
                f.write(admin_id)
            print(f"[INFO] Đã thiết lập Admin ID: {admin_id}")

    # Chạy Web Server song song 
    await start_web_server()

    print("[SYSTEM] UI Bot đang khởi chạy. Đã áp dụng giao diện Control Panel Interactive.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
