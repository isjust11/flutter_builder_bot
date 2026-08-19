import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

from builder import start_build_thread

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_CHAT_IDS = [int(x) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.strip().isdigit()]

# Store user selections during the flow
# Dictionary format: { chat_id: { 'project': '...', 'env': '...', 'platform': '...', 'version': '...' } }
user_sessions = {}

# Mock data mapping to .env
# Trong thực tế, bạn sẽ parse .env để lấy động danh sách này
PROJECTS = {
    "Chợ Tốt": {
        "path": os.getenv("PROJECT_CHOTOT_PATH", "D:\\develop\\projects\\chotot"),
        "branch": os.getenv("PROJECT_CHOTOT_BRANCH", "main")
    },
    "Other App": {
        "path": os.getenv("PROJECT_OTHER_PATH", "D:\\develop\\projects\\other"),
        "branch": os.getenv("PROJECT_OTHER_BRANCH", "dev")
    }
}

FLUTTER_VERSIONS = {
    "3.24.0": os.getenv("FLUTTER_3_24_PATH", "flutter"),
    "3.19.0": os.getenv("FLUTTER_3_19_PATH", "flutter")
}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Bạn không có quyền truy cập bot này.")
        return
    await update.message.reply_text("👋 Chào mừng bạn đến với Flutter Builder Bot! Gõ /build để bắt đầu.")

async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        return
        
    user_sessions[chat_id] = {}
    
    # BƯỚC 1: Chọn Project
    keyboard = []
    for proj_name in PROJECTS.keys():
        keyboard.append([InlineKeyboardButton(proj_name, callback_data=f"proj|{proj_name}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Vui lòng chọn Project:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {}
        
    data = query.data
    
    # 1. Xử lý Chọn Project
    if data.startswith("proj|"):
        proj_name = data.split("|")[1]
        user_sessions[chat_id]["project"] = proj_name
        
        # BƯỚC 2: Chọn Môi Trường
        keyboard = [
            [InlineKeyboardButton("Dev", callback_data="env|dev")],
            [InlineKeyboardButton("Staging", callback_data="env|staging")],
            [InlineKeyboardButton("Product", callback_data="env|product")]
        ]
        await query.edit_message_text(text=f"Project: **{proj_name}**\n\nTiếp tục chọn Môi trường (Flavor):", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    # 2. Xử lý Chọn Môi trường
    elif data.startswith("env|"):
        env_name = data.split("|")[1]
        user_sessions[chat_id]["env"] = env_name
        
        # BƯỚC 3: Chọn Platform
        keyboard = [
            [InlineKeyboardButton("Android APK", callback_data="plat|apk")],
            [InlineKeyboardButton("Android AppBundle", callback_data="plat|appbundle")],
            [InlineKeyboardButton("iOS IPA", callback_data="plat|ipa")]
        ]
        await query.edit_message_text(text=f"Project: **{user_sessions[chat_id]['project']}** | Env: **{env_name}**\n\nTiếp tục chọn Nền tảng:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    # 3. Xử lý Chọn Platform
    elif data.startswith("plat|"):
        plat_name = data.split("|")[1]
        user_sessions[chat_id]["platform"] = plat_name
        
        # BƯỚC 4: Chọn Flutter Version
        keyboard = []
        for ver in FLUTTER_VERSIONS.keys():
            keyboard.append([InlineKeyboardButton(f"Flutter {ver}", callback_data=f"ver|{ver}")])
            
        await query.edit_message_text(text=f"Project: **{user_sessions[chat_id]['project']}** | Env: **{user_sessions[chat_id]['env']}** | Plat: **{plat_name}**\n\nChọn phiên bản Flutter:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    # 4. Xử lý Chọn Version -> START THREAD BUILD
    elif data.startswith("ver|"):
        ver_name = data.split("|")[1]
        user_sessions[chat_id]["version"] = ver_name
        
        session = user_sessions[chat_id]
        await query.edit_message_text(
            text=f"✅ Đã nhận lệnh build:\n- Project: {session['project']}\n- Env: {session['env']}\n- Plat: {session['platform']}\n- Version: {session['version']}\n\nĐang đẩy vào hàng đợi...", 
            parse_mode="Markdown"
        )
        
        # Chuẩn bị dữ liệu cho builder
        proj_config = PROJECTS[session["project"]]
        flutter_bin = FLUTTER_VERSIONS[session["version"]]
        appbox_cli = os.getenv("APPBOX_CLI_PATH", "appbox")
        
        # Hàm callback gửi tin nhắn về Telegram
        def send_status(text):
            # Lưu ý: Gửi đồng bộ trong thread có thể hơi phức tạp với async.
            # python-telegram-bot v20 cho phép dùng application.bot
            try:
                # Do hàm này chạy ngoài event loop, cần gửi thông qua sync nếu có thể, hoặc đơn giản nhất là call_api_requests
                # Ở đây dùng hàm send_message đồng bộ bằng requests cho dễ nếu application context không rảnh, 
                # Tuy nhiên PTB v20 khuyên dùng run_coroutine_threadsafe.
                # Để tối giản, ta có thể dùng trực tiếp `requests` API
                import requests
                url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
            except Exception as e:
                logging.error(f"Cannot send status: {e}")

        # Khởi chạy luồng build
        start_build_thread(
            proj_config["path"],
            proj_config["branch"],
            session["env"],
            session["platform"],
            flutter_bin,
            appbox_cli,
            send_status
        )

if __name__ == '__main__':
    if not TOKEN:
        print("LỖI: Chưa cấu hình TELEGRAM_TOKEN trong file .env")
        exit(1)
        
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🚀 Flutter Builder Bot đang chạy...")
    app.run_polling()
