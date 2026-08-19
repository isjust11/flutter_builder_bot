import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, Application

from builder import start_build_thread

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_CHAT_IDS = [int(x) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.strip().lstrip("-").isdigit()]
channel_id_env = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
if channel_id_env.lstrip("-").isdigit():
    ALLOWED_CHAT_IDS.append(int(channel_id_env))

# Store user selections during the flow
# Dictionary format: { chat_id: { 'project': '...', 'env': '...', 'platform': '...', 'version': '...' } }
user_sessions = {}

# Parse .env để lấy động danh sách project
def load_projects():
    projects = {}
    for key, value in os.environ.items():
        if key.startswith("PROJECT_") and key.endswith("_PATH"):
            project_key = key[len("PROJECT_"):-len("_PATH")]
            
            branch_prefix = f"PROJECT_{project_key}_"
            
            # Tìm tất cả các branch liên quan đến project này
            branch_keys = [k for k in os.environ.keys() if k.startswith(branch_prefix) and k.endswith("_BRANCH")]
            
            # Sắp xếp các branch: đảm bảo SUPPER_BRANCH luôn nằm cuối danh sách (để được build)
            branch_keys.sort(key=lambda k: (1 if 'SUPPER' in k else 0, k))
            
            branches = []
            for k in branch_keys:
                val = os.environ[k]
                if '|' in val:
                    b_path, b_name = val.split('|', 1)
                    branches.append({"path": b_path.strip(), "name": b_name.strip()})
                else:
                    branches.append({"path": None, "name": val.strip()})
            
            projects[project_key] = {
                "path": value,
                "branches": branches
            }
    return projects

PROJECTS = load_projects()

def load_flutter_versions():
    versions = {"Mặc định": "flutter"}
    for key, val in os.environ.items():
        if key.startswith("FLUTTER_") and key.endswith("_PATH"):
            version_name = key.replace("FLUTTER_", "").replace("_PATH", "").replace("_", ".")
            versions[version_name] = val
    return versions

FLUTTER_VERSIONS = load_flutter_versions()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Bạn không có quyền truy cập bot này.")
        return
    await update.message.reply_text("👋 Chào mừng bạn đến với Flutter Builder Bot! Gõ /build để bắt đầu.")

async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.message.message_thread_id else "None"
    await update.message.reply_text(f"🆔 Chat ID: `{chat_id}`\n💬 Topic/Thread ID: `{thread_id}`", parse_mode="Markdown")

async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        logging.warning(f"Từ chối lệnh /build từ chat_id chưa được cấp phép: {chat_id}")
        return
        
    # BƯỚC 1: Chọn Project
    keyboard = []
    for proj_name in PROJECTS.keys():
        keyboard.append([InlineKeyboardButton(proj_name, callback_data=f"proj|{proj_name}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    channel_id_str = os.getenv("TELEGRAM_CHANNEL_ID")
    if channel_id_str and channel_id_str.lstrip("-").isdigit():
        channel_id = int(channel_id_str)
        user_sessions[channel_id] = {}
        try:
            await context.bot.send_message(
                chat_id=channel_id,
                text=f"👤 **{update.effective_user.full_name}** yêu cầu build.\nVui lòng chọn Project:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            if chat_id != channel_id:
                await update.message.reply_text("✅ Đã gửi menu chọn project vào channel.")
        except Exception as e:
            logging.error(f"Cannot send to channel: {e}")
            user_sessions[chat_id] = {}
            await update.message.reply_text("Vui lòng chọn Project:", reply_markup=reply_markup)
    else:
        user_sessions[chat_id] = {}
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

        # Hàm callback gửi tin nhắn kết quả cuối cùng
        def send_final_result(text, file_path=None):
            try:
                import requests
                
                def _send(target_chat_id, target_text):
                    if file_path and os.path.exists(file_path):
                        url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
                        with open(file_path, 'rb') as f:
                            requests.post(url, data={"chat_id": target_chat_id, "caption": target_text, "parse_mode": "Markdown"}, files={"document": f})
                    else:
                        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                        requests.post(url, json={"chat_id": target_chat_id, "text": target_text, "parse_mode": "Markdown"})

                # Gửi cho chat hiện tại (nơi bấm menu)
                _send(chat_id, text)
                
                # Gửi vào channel nếu chưa trùng
                channel_id_str = os.getenv("TELEGRAM_CHANNEL_ID")
                if channel_id_str and str(chat_id) != channel_id_str:
                    channel_text = f"👤 **Yêu cầu bởi:** {update.effective_user.full_name}\n{text}"
                    _send(channel_id_str, channel_text)
                    
            except Exception as e:
                logging.error(f"Cannot send final result: {e}")

        # Lấy BUILD_CMD
        build_cmd_template = os.getenv("BUILD_CMD")

        # Khởi chạy luồng build
        start_build_thread(
            proj_config["path"],
            proj_config["branches"],
            session["env"],
            session["platform"],
            flutter_bin,
            appbox_cli,
            send_status,
            send_final_result,
            build_cmd_template
        )

async def on_startup(app: Application):
    channel_id_str = os.getenv("TELEGRAM_CHANNEL_ID")
    if channel_id_str and channel_id_str.lstrip("-").isdigit():
        channel_id = int(channel_id_str)
        user_sessions[channel_id] = {}
        
        keyboard = []
        for proj_name in PROJECTS.keys():
            keyboard.append([InlineKeyboardButton(proj_name, callback_data=f"proj|{proj_name}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await app.bot.send_message(
                chat_id=channel_id,
                text="🚀 **Bot đã khởi động!**\nVui lòng chọn Project để build:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            logging.info("Đã gửi menu chọn project vào channel khi khởi động.")
        except Exception as e:
            logging.error(f"Cannot send startup menu to channel: {e}")

if __name__ == '__main__':
    if not TOKEN:
        print("LỖI: Chưa cấu hình TELEGRAM_TOKEN trong file .env")
        exit(1)
        
    app = ApplicationBuilder().token(TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("getid", getid_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🚀 Flutter Builder Bot đang chạy...")
    app.run_polling()
