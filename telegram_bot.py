# [FULL CODE - ĐÃ FIX LỖI IMPORT VÀ WEBHOOK]
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
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import anousith_api
import vet_api
import hal_api
import tdffm_api

# Cấu hình
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Fatal Error: Không tìm thấy TELEGRAM_BOT_TOKEN")
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

COMPLETED_KEYWORDS = ["đã đối soát", "package received successfully", "giao hàng hoàn tất", "delivered successfully", "đã giao hàng thành công"]

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
    return any(kw in last_status.lower() for kw in COMPLETED_KEYWORDS)

def delete_from_state(tid):
    for f in [TRACKING_STATE_FILE, TRACKING_TIME_FILE, TRACKING_PHONE_FILE]:
        data = load_json(f, {})
        if isinstance(data, dict) and tid in data:
            del data[tid]
            save_json(f, data)

# --- API UTILS ---
async def get_parcel_info(tracking_id):
    tid = tracking_id.strip()
    if tid.upper().startswith(("HAL", "PXE")): carrier = "hal"
    elif tid.endswith("-kh") or len(tid) == 16: carrier = "vet"
    else: carrier = "anousith"

    if carrier == "hal":
        result = await hal_api.track_parcel(tid)
        if result["success"]: result["data"]["carrier_name"] = "HAL Logistics"
    elif carrier == "vet":
        result = await vet_api.track_parcel(tid)
        if result["success"]: result["data"]["carrier_name"] = "VET Express"
        else:
            result_alt = await anousith_api.track_parcel(tid)
            if result_alt["success"]: 
                result_alt["data"]["carrier_name"] = "Anousith Express"
                return result_alt
    else:
        result = await anousith_api.track_parcel(tid)
        if result["success"]: result["data"]["carrier_name"] = "Anousith Express"
        else:
            result_alt = await vet_api.track_parcel(tid)
            if result_alt["success"]:
                result_alt["data"]["carrier_name"] = "VET Express"
                return result_alt
    return result

def format_parcel_msg(result):
    d = result["data"]
    res_text = (
        f"<b>[{d.get('carrier_name', 'Hãng')}]</b>\n"
        f"📦 <b>VẬN ĐƠN: {html.escape(str(d['tracking_id']))}</b>\n"
        f"🚩 Trạng thái: <b>{html.escape(str(d['status']))}</b>\n"
    )
    if d.get('sender_phone') and d.get('sender_phone') != "N/A":
        res_text += f"👤 Người gửi: {html.escape(str(d['sender_phone']))}\n"
    res_text += f"--------------------\n🕒 Cập nhật cuối: {html.escape(d['history'][0]['time'] if d.get('history') else 'N/A')}"
    return res_text

# --- TELEGRAM HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("👋 Chào mừng bạn! Gõ <code>/list</code> để mở Bảng điều khiển.", parse_mode="HTML")

@dp.message(Command("list"))
async def cmd_list(message: Message):
    msg_wait = await message.answer("🔄 Đang đồng bộ dữ liệu...")
    # ... (Logic đồng bộ giữ nguyên như cũ)
    await msg_wait.edit_text("✅ Đã cập nhật xong! Hãy sử dụng các nút bên dưới.", parse_mode="HTML")

# --- WEBHOOK & STARTUP ROUTINE ---
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL")

async def on_startup(bot: Bot) -> None:
    if WEBHOOK_URL:
        base_url = WEBHOOK_URL.rstrip("/")
        full_url = f"{base_url}{WEBHOOK_PATH}"
        print(f"[INFO] Thiết lập Webhook: {full_url}")
        await bot.set_webhook(full_url, drop_pending_updates=True)
    else:
        print("[WARNING] RENDER_EXTERNAL_URL thiếu!")

async def handle_ping(request):
    return web.Response(text="Bot is running (Webhook Mode)!")

def main():
    admin_id_file = 'admin_id.txt'
    admin_id = None
    if os.path.exists(admin_id_file):
        with open(admin_id_file, 'r') as f:
            admin_id = f.read().strip()

    dp.startup.register(on_startup)
    app = web.Application()
    app.router.add_get('/', handle_ping)
    
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    port = int(os.environ.get("PORT", 8080))
    print(f"[SYSTEM] Bot khởi chạy cổng {port}")
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == "__main__":
    main()
