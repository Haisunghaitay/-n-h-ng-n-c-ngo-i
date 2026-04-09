import json
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from deep_translator import GoogleTranslator

CACHE_FILE = 'translation_cache.json'
_executor = ThreadPoolExecutor(max_workers=5)

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_cache(cache_data):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[CACHE ERROR] Cannot save: {e}")

_cache = load_cache()

STATUS_PREFIX_MAP = {
    "Received at Agency": "🏢 Nhận tại đại lý",
    "Received at": "🏢 Nhận tại",
    "Arrival": "🚛 Đã đến",
    "Shipping from": "➡️ Đang vận chuyển từ",
    "Posting at": "📦 Đã gửi tại",
    "Delivered": "✅ Đã giao hàng",
    "ຮັບພັດສະດຸແລ້ວ": "🏢 Đã nhận bưu phẩm",
    "ພັດສະດຸຮອດປາຍທາງແລ້ວ": "🚚 Bưu phẩm đã đến đích",
    "ສໍາເລັດການຮັບຝາກ": "✅ Giao hàng thành công",
    "ຈັດສົ່ງສໍາເລັດ": "✅ Giao hàng hoàn tất"
}

async def translate_text(text, source='auto', target='vi'):
    """Dịch văn bản sang tiếng Việt với cơ chế Cache."""
    if not text or not text.strip():
        return text
    
    # Kiểm tra trong bộ nhớ đệm
    cache_key = f"{source}_{target}_{text}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    try:
        loop = asyncio.get_event_loop()
        # Chạy đồng bộ trong executor để không block vòng lặp async
        translated = await loop.run_in_executor(
            _executor,
            lambda: GoogleTranslator(source=source, target=target).translate(text)
        )
        
        if translated and translated.strip():
            _cache[cache_key] = translated
            save_cache(_cache)
            return translated
            
    except Exception as e:
        print(f"[TRANS ERROR] Lỗi dịch thuật: {e}")
        
    return text

async def translate_vet_status(status_str):
    """
    Dịch trạng thái VET thông minh.
    Ưu tiên map prefix trước, sau đó dịch phần còn lại.
    """
    if not status_str:
        return status_str
        
    res = status_str.strip()
    
    # 1. Thử map prefix Anh-Việt trước để giữ văn phong chuẩn
    matched_prefix = None
    vn_prefix = ""
    for en, vn in STATUS_PREFIX_MAP.items():
        if res.startswith(en):
            matched_prefix = en
            vn_prefix = vn
            break
            
    if matched_prefix:
        # Tách phần Khmer/địa danh phía sau
        remaining = res[len(matched_prefix):].strip()
        if remaining:
            # Dịch phần còn lại
            translated_rem = await translate_text(remaining)
            return f"{vn_prefix} {translated_rem}"
        else:
            return vn_prefix

            
    # 2. Nếu không khớp prefix nào, dịch toàn bộ
    if not any(ord(c) > 127 for c in res):
        return res
        
    translated = await translate_text(res)
    if translated.lower() != res.lower():
        return translated
    
    return res


if __name__ == "__main__":
    # Test
    async def test():
        txt = "Received at Agency ផ្សារដើមអំពិល (កណ្ដាល)KD"
        res = await translate_vet_status(txt)
        print(f"GỐC: {txt}")
        print(f"DỊCH: {res}")
        
    asyncio.run(test())
