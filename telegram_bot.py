import logging
import os
import subprocess
import time
import json
import sys
import platform
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
    ConversationHandler, CallbackQueryHandler
)

# --- KONFIGURASI BOT ---
BOT_CONFIG_FILE = "bot_config.json"
BOT_STATE_FILE = "bot_state.json"
CONFIG = {} # Konfigurasi bot
BOT_STATE = {} # Status bot (persisten)

# States untuk ConversationHandler
SELECT_VIDEO_STATE, ENTER_KEY_STATE, SCHEDULE_STOP_STATE, DELETE_VIDEO_STATE, UPLOAD_VIDEO_STATE = range(5) 

# Default config jika file tidak ditemukan atau error
DEFAULT_BOT_CONFIG = {
    "TELEGRAM_BOT_TOKEN": "GANTI_DENGAN_TOKEN_BOT_ANDA",
    "ALLOWED_CHAT_ID": 0,
    "STREAM_SCRIPT_PATH": "streamer.py",
    "PID_FILE": "stream_process.pid",
    "LOG_FILE": "ffmpeg_log.txt",
    "VIDEOS_DIR": "uploaded_videos"
}

DEFAULT_BOT_STATE = {
    "selected_video": None,
    "is_stream_key_set": False,
    "scheduled_stop_job_name": None
}

# Aktifkan logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Fungsi untuk memuat/menyimpan konfigurasi dan status ---
def load_bot_config():
    """Memuat konfigurasi bot dari bot_config.json."""
    global CONFIG
    try:
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        config_file_path = os.path.join(current_script_dir, BOT_CONFIG_FILE)

        with open(config_file_path, 'r') as f:
            CONFIG = json.load(f)
        for key, default_value in DEFAULT_BOT_CONFIG.items():
            if key not in CONFIG:
                CONFIG[key] = default_value
        logger.info(f"Konfigurasi bot dimuat dari '{config_file_path}'.")

        if CONFIG["TELEGRAM_BOT_TOKEN"] == DEFAULT_BOT_CONFIG["TELEGRAM_BOT_TOKEN"] or not CONFIG["TELEGRAM_BOT_TOKEN"]:
            logger.error("Token bot Telegram belum diatur di bot_config.json. Bot tidak akan berfungsi.")
            sys.exit(1)
        if CONFIG["ALLOWED_CHAT_ID"] == DEFAULT_BOT_CONFIG["ALLOWED_CHAT_ID"] or not CONFIG["ALLOWED_CHAT_ID"]:
            logger.error("Chat ID yang diizinkan belum diatur di bot_config.json. Bot tidak akan berfungsi.")
            sys.exit(1)

        CONFIG["VIDEOS_DIR"] = os.path.abspath(os.path.join(current_script_dir, CONFIG["VIDEOS_DIR"]))
        os.makedirs(CONFIG["VIDEOS_DIR"], exist_ok=True)
        logger.info(f"Memastikan direktori video '{CONFIG['VIDEOS_DIR']}' ada. Path absolut: {CONFIG['VIDEOS_DIR']}")

        CONFIG["STREAM_SCRIPT_PATH"] = os.path.abspath(os.path.join(current_script_dir, CONFIG["STREAM_SCRIPT_PATH"]))
        logger.info(f"Streamer script path: {CONFIG['STREAM_SCRIPT_PATH']}")

        CONFIG["PID_FILE"] = os.path.abspath(os.path.join(current_script_dir, CONFIG["PID_FILE"]))
        CONFIG["LOG_FILE"] = os.path.abspath(os.path.join(current_script_dir, CONFIG["LOG_FILE"]))
        logger.info(f"PID File: {CONFIG['PID_FILE']}, Log File: {CONFIG['LOG_FILE']}")

    except FileNotFoundError:
        logger.warning(f"File '{BOT_CONFIG_FILE}' tidak ditemukan. Membuat file konfigurasi bot default...")
        CONFIG = DEFAULT_BOT_CONFIG
        save_bot_config()
        logger.error(f"Harap edit '{BOT_CONFIG_FILE}' dengan token bot dan Chat ID Anda, lalu jalankan ulang bot.")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"Kesalahan format JSON di '{BOT_CONFIG_FILE}'. Menggunakan konfigurasi bot default.")
        CONFIG = DEFAULT_BOT_CONFIG
        logger.error(f"Harap perbaiki atau hapus '{BOT_CONFIG_FILE}' jika Anda ingin menggunakan konfigurasi baru.")
        sys.exit(1)

def save_bot_config():
    """Menyimpan konfigurasi bot saat ini ke bot_config.json."""
    try:
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        config_file_path = os.path.join(current_script_dir, BOT_CONFIG_FILE)
        
        temp_config = CONFIG.copy()
        temp_config["VIDEOS_DIR"] = os.path.relpath(CONFIG["VIDEOS_DIR"], current_script_dir)
        temp_config["STREAM_SCRIPT_PATH"] = os.path.relpath(CONFIG["STREAM_SCRIPT_PATH"], current_script_dir)
        temp_config["PID_FILE"] = os.path.relpath(CONFIG["PID_FILE"], current_script_dir)
        temp_config["LOG_FILE"] = os.path.relpath(CONFIG["LOG_FILE"], current_script_dir)

        with open(config_file_path, 'w') as f:
            json.dump(temp_config, f, indent=4)
        logger.info(f"Konfigurasi bot disimpan ke '{config_file_path}'.")
    except IOError as e:
        logger.error(f"Gagal menyimpan konfigurasi bot ke '{config_file_path}': {e}")

def load_bot_state():
    """Memuat status bot dari bot_state.json."""
    global BOT_STATE
    try:
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        state_file_path = os.path.join(current_script_dir, BOT_STATE_FILE)

        with open(state_file_path, 'r') as f:
            BOT_STATE = json.load(f)
        for key, default_value in DEFAULT_BOT_STATE.items():
            if key not in BOT_STATE:
                BOT_STATE[key] = default_value
        logger.info(f"Status bot dimuat dari '{state_file_path}'.")
    except FileNotFoundError:
        logger.warning(f"File '{BOT_STATE_FILE}' tidak ditemukan. Membuat status bot default...")
        BOT_STATE = DEFAULT_BOT_STATE
        save_bot_state()
    except json.JSONDecodeError:
        logger.error(f"Kesalahan format JSON di '{BOT_STATE_FILE}'. Menggunakan status bot default.")
        BOT_STATE = DEFAULT_BOT_STATE
        save_bot_state()

def save_bot_state():
    """Menyimpan status bot saat ini ke bot_state.json."""
    try:
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        state_file_path = os.path.join(current_script_dir, BOT_STATE_FILE)

        with open(state_file_path, 'w') as f:
            json.dump(BOT_STATE, f, indent=4)
        logger.info(f"Status bot disimpan ke '{state_file_path}'.")
    except IOError as e:
        logger.error(f"Gagal menyimpan status bot ke '{state_file_path}': {e}")

def get_stream_key_from_file():
    """Membaca kunci streaming dari file (menggunakan KEY_FILENAME dari config.json streamer)."""
    streamer_dir = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
    streamer_config_path = os.path.join(streamer_dir, "config.json")
    
    try:
        with open(streamer_config_path, 'r') as f:
            streamer_conf = json.load(f)
        key_filename = streamer_conf.get("KEY_FILENAME", "keystream.txt")
        key_file_path = os.path.join(streamer_dir, key_filename)

        with open(key_file_path, 'r') as f:
            key = f.read().strip()
            if key:
                BOT_STATE["is_stream_key_set"] = True
                save_bot_state()
            return key
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        logger.error(f"Gagal membaca kunci streaming dari file '{key_file_path}': {e}")
        BOT_STATE["is_stream_key_set"] = False
        save_bot_state()
        return None

def write_stream_key_to_file(key):
    """Menulis kunci streaming ke file."""
    streamer_dir = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
    streamer_config_path = os.path.join(streamer_dir, "config.json")
    try:
        with open(streamer_config_path, 'r') as f:
            streamer_conf = json.load(f)
        key_filename = streamer_conf.get("KEY_FILENAME", "keystream.txt")
        key_file_path = os.path.join(streamer_dir, key_filename)

        with open(key_file_path, 'w') as f:
            f.write(key.strip())
        BOT_STATE["is_stream_key_set"] = True
        save_bot_state()
        return True
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        logger.error(f"Gagal menulis kunci streaming ke file '{key_file_path}': {e}")
        return False

# --- Fungsi Helper Bot ---
async def check_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memeriksa apakah chat ID diizinkan."""
    chat_id_to_check = update.effective_chat.id
    if chat_id_to_check != CONFIG['ALLOWED_CHAT_ID']:
        if update.callback_query:
            await update.callback_query.message.reply_text("Maaf, Anda tidak diizinkan menggunakan bot ini.")
        elif update.message:
            await update.message.reply_text("Maaf, Anda tidak diizinkan menggunakan bot ini.")
        logger.warning(f"Akses tidak sah dari Chat ID: {chat_id_to_check} mencoba akses.")
        return False
    return True

def is_stream_running():
    """Mengecek apakah proses streaming sedang berjalan."""
    pid_file_path = CONFIG['PID_FILE']
    if os.path.exists(pid_file_path):
        with open(pid_file_path, 'r') as f:
            pid_str = f.read().strip()
        try:
            pid = int(pid_str)
            if platform.system() == "Windows":
                return True, pid
            else:
                os.kill(pid, 0)
                return True, pid
        except (ProcessLookupError, ValueError):
            logger.warning(f"PID {pid_str} tidak valid atau proses tidak ditemukan. Menghapus '{pid_file_path}'.")
            os.remove(pid_file_path)
            return False, None
        except Exception as e:
            logger.error(f"Error saat mengecek PID: {e}")
            return False, None
    return False, None

def start_stream_process():
    """Memulai proses streaming."""
    running, _ = is_stream_running()
    if running:
        logger.info("Mencoba memulai stream, tetapi sudah ada yang berjalan.")
        return False

    if not BOT_STATE["selected_video"]:
        logger.error("Tidak ada video yang dipilih untuk streaming.")
        return False

    if not BOT_STATE["is_stream_key_set"]:
        logger.error("Kunci streaming belum diatur.")
        return False

    if not os.path.exists(BOT_STATE["selected_video"]):
        logger.error(f"Video yang dipilih '{os.path.basename(BOT_STATE['selected_video'])}' tidak ditemukan. Path: {BOT_STATE['selected_video']}")
        return False

    try:
        selected_video_filename = os.path.basename(BOT_STATE["selected_video"])
        streamer_dir = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
        destination_path_for_streamer = os.path.join(streamer_dir, selected_video_filename)

        streamer_config_path_abs = os.path.join(streamer_dir, "config.json")
        allowed_extensions = []
        try:
            with open(streamer_config_path_abs, 'r') as f:
                streamer_conf = json.load(f)
            allowed_extensions = [ext.lower() for ext in streamer_conf.get("VIDEO_EXTENSIONS", [])]
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Gagal membaca streamer config dari '{streamer_config_path_abs}'. Menggunakan ekstensi default untuk pembersihan: {e}")
            allowed_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']

        for f in os.listdir(streamer_dir):
            file_ext = os.path.splitext(f)[1].lower()
            if file_ext in allowed_extensions and f != selected_video_filename:
                try:
                    full_path_to_remove = os.path.join(streamer_dir, f)
                    if os.path.islink(full_path_to_remove):
                        os.unlink(full_path_to_remove)
                        logger.info(f"Menghapus symlink lama di direktori streamer: {full_path_to_remove}")
                    elif os.path.isfile(full_path_to_remove):
                        os.remove(full_path_to_remove)
                        logger.info(f"Menghapus video fisik lama di direktori streamer: {full_path_to_remove}")
                except Exception as ex:
                    logger.warning(f"Gagal menghapus video/symlink lama {f}: {ex}")

        if not os.path.exists(destination_path_for_streamer) or \
           not os.path.islink(destination_path_for_streamer) or \
           (os.path.islink(destination_path_for_streamer) and os.readlink(destination_path_for_streamer) != BOT_STATE["selected_video"]):
            
            if os.path.exists(destination_path_for_streamer):
                try:
                    os.unlink(destination_path_for_streamer)
                except OSError as ose:
                    if ose.errno == 21:
                        pass 
                    else:
                        os.remove(destination_path_for_streamer)
                except Exception as ex:
                    logger.warning(f"Gagal membersihkan tujuan symlink {destination_path_for_streamer}: {ex}")

            os.symlink(BOT_STATE["selected_video"], destination_path_for_streamer)
            logger.info(f"Membuat symlink: {BOT_STATE['selected_video']} -> {destination_path_for_streamer}")
        else:
            logger.info(f"Symlink {destination_path_for_streamer} sudah ada dan menunjuk ke video yang benar.")

        process = subprocess.Popen([sys.executable, CONFIG['STREAM_SCRIPT_PATH']],
                                     cwd=streamer_dir,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT,
                                     text=True,
                                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if platform.system() == "Windows" else 0)

        with open(CONFIG['PID_FILE'], 'w') as f:
            f.write(str(process.pid))
        logger.info(f"Proses streaming dimulai dengan PID: {process.pid}")
        return True
    except Exception as e:
        logger.error(f"Gagal memulai proses streaming: {e}", exc_info=True)
        return False

def stop_stream_process(pid):
    """Menghentikan proses streaming."""
    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=True, capture_output=True)
        else:
            os.kill(pid, 15)

        time.sleep(2)
        if os.path.exists(CONFIG['PID_FILE']):
            os.remove(CONFIG['PID_FILE'])
        logger.info(f"Proses streaming (PID: {pid}) dihentikan.")
        return True
    except Exception as e:
        logger.error(f"Gagal menghentikan proses streaming (PID: {pid}): {e}", exc_info=True)
        return False

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mengirim menu utama bot hanya dengan ReplyKeyboardMarkup."""
    reply_keyboard = [
        [KeyboardButton("🎬 Pilih Video"), KeyboardButton("⬆️ Unggah Video Baru")],
        [KeyboardButton("🔑 Atur Kunci Streaming"), KeyboardButton("🔴 Mulai Live"), KeyboardButton("⏹️ Hentikan Live")],
        [KeyboardButton("⏰ Jadwal Hentikan Live"), KeyboardButton("🗑️ Hapus Video")],
        [KeyboardButton("⚙️ Status & Konfigurasi"), KeyboardButton("🟢 Cek Status Live"), KeyboardButton("📄 Lihat Log FFmpeg")],
        [KeyboardButton("◀️ Kembali")] 
    ]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    target_message = None
    if update.message:
        target_message = update.message
    elif update.callback_query:
        target_message = update.callback_query.message
    else: 
        await context.bot.send_message(chat_id=CONFIG['ALLOWED_CHAT_ID'], text="Pilih aksi:", reply_markup=reply_markup)
        return

    await target_message.reply_text("Pilih aksi:", reply_markup=reply_markup)


# --- Handler Perintah Telegram ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengirim menu utama saat perintah /start diterima."""
    if not await check_auth(update, context): return
    await send_main_menu(update, context)

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menangani callback dari tombol inline keyboard (digunakan dalam convo saja)."""
    query = update.callback_query
    await query.answer()

    action = query.data
    
    if action == "main_menu":
        await send_main_menu(update, context)
        return ConversationHandler.END

    if action.startswith("select_video_"):
        video_name = action.replace("select_video_", "")
        selected_path = os.path.join(CONFIG["VIDEOS_DIR"], video_name) 
        if os.path.exists(selected_path):
            BOT_STATE["selected_video"] = selected_path
            save_bot_state()
            await query.edit_message_text(f"Video '{video_name}' telah dipilih.\nSekarang Anda bisa memulai live.")
        else:
            await query.edit_message_text(f"Video '{video_name}' tidak ditemukan. Silakan pilih lagi.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    elif action.startswith("delete_video_"):
        video_name = action.replace("delete_video_", "")
        video_path = os.path.join(CONFIG["VIDEOS_DIR"], video_name)
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
                await query.edit_message_text(f"Video '{video_name}' berhasil dihapus.")
                if BOT_STATE["selected_video"] == video_path:
                    BOT_STATE["selected_video"] = None
                    save_bot_state()
            except Exception as e:
                logger.error(f"Gagal menghapus video '{video_name}': {e}", exc_info=True)
                await query.edit_message_text(f"Gagal menghapus video '{video_name}': {e}")
        else:
            await query.edit_message_text(f"Video '{video_name}' tidak ditemukan.")
        await send_main_menu(update, context)
        return ConversationHandler.END

    logger.warning(f"Callback tidak ditangani di button_callback_handler: {action}")
    await send_main_menu(update, context)
    return ConversationHandler.END

# --- Fitur Manajemen Video ---
async def handle_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menangani unggahan file video."""
    if not await check_auth(update, context): 
        await send_main_menu(update.message, context) 
        return ConversationHandler.END

    if update.message.document:
        doc = update.message.document
        logger.info(f"Dokumen diterima: {doc.file_name} (MIME: {doc.mime_type}, Size: {doc.file_size} bytes)")

        file_extension = os.path.splitext(doc.file_name)[1].lower()
        
        streamer_dir_for_config_path = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
        streamer_config_path = os.path.join(streamer_dir_for_config_path, "config.json")
        allowed_extensions = []
        try:
            with open(streamer_config_path, 'r') as f:
                streamer_conf = json.load(f)
            allowed_extensions = [ext.lower() for ext in streamer_conf.get("VIDEO_EXTENSIONS", [])]
            logger.info(f"Ekstensi video yang diizinkan dari streamer config: {allowed_extensions}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Gagal membaca streamer config dari '{streamer_config_path}'. Menggunakan ekstensi default untuk upload: {e}", exc_info=True)
            allowed_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']

        if file_extension in allowed_extensions:
            file_id = doc.file_id
            logger.info(f"File extension {file_extension} diizinkan. Mengambil file dengan file_id: {file_id}")
            new_file = await context.bot.get_file(file_id)
            
            videos_dir_abs = CONFIG["VIDEOS_DIR"] 
            os.makedirs(videos_dir_abs, exist_ok=True)

            target_path = os.path.join(videos_dir_abs, doc.file_name)
            base_name, ext = os.path.splitext(doc.file_name)
            counter = 1
            while os.path.exists(target_path):
                target_path = os.path.join(videos_dir_abs, f"{base_name}_{counter}{ext}")
                counter += 1
            
            logger.info(f"Akan mengunduh file ke: {target_path}")
            try:
                await new_file.download_to_drive(target_path)
                logger.info(f"File berhasil diunduh ke {target_path}")
                await update.message.reply_text(f"Video '{os.path.basename(target_path)}' berhasil diunggah dan disimpan.")
            except Exception as e:
                logger.error(f"Gagal mengunduh video ke '{target_path}': {e}", exc_info=True)
                await update.message.reply_text(f"Gagal mengunggah video: {e}\nPeriksa log bot untuk detail.")
        else:
            logger.warning(f"File extension {file_extension} tidak diizinkan untuk upload video.")
            await update.message.reply_text(f"Format file '{file_extension}' tidak didukung sebagai video. Ekstensi yang didukung: {', '.join(allowed_extensions)}")
    else:
        logger.warning("Menerima pesan yang bukan dokumen atau bukan video yang valid.")
        await update.message.reply_text("Silakan unggah file video yang valid (misal: .mp4, .mkv).")
        return UPLOAD_VIDEO_STATE

    await send_main_menu(update.message, context)
    return ConversationHandler.END

async def list_videos_for_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_to_reply = update.message if update.message else update.callback_query.message

    videos_dir_abs = CONFIG["VIDEOS_DIR"] 
    video_files = [f for f in os.listdir(videos_dir_abs) if os.path.isfile(os.path.join(videos_dir_abs, f))]
    
    streamer_dir_for_config_path = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
    streamer_config_path = os.path.join(streamer_dir_for_config_path, "config.json")
    allowed_extensions = []
    try:
        with open(streamer_config_path, 'r') as f:
            streamer_conf = json.load(f)
        allowed_extensions = [ext.lower() for ext in streamer_conf.get("VIDEO_EXTENSIONS", [])]
    except (FileNotFoundError, json.JSONDecodeError):
        logger.error(f"Gagal membaca streamer config dari '{streamer_config_path}'. Menggunakan ekstensi default.")
        allowed_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']

    valid_video_files = [f for f in video_files if os.path.splitext(f)[1].lower() in allowed_extensions]

    if not valid_video_files:
        await message_to_reply.reply_text("Tidak ada video yang ditemukan di folder 'uploaded_videos'.")
        await send_main_menu(update, context)
        return ConversationHandler.END

    keyboard = []
    for video in valid_video_files:
        current_video_abs_path = os.path.join(videos_dir_abs, video)
        is_selected = " ✅" if current_video_abs_path == BOT_STATE["selected_video"] else ""
        keyboard.append([InlineKeyboardButton(f"🎬 {video}{is_selected}", callback_data=f"select_video_{video}")])
    keyboard.append([InlineKeyboardButton("◀️ Kembali ke Menu Utama", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await message_to_reply.reply_text("Pilih video yang ingin di-stream:", reply_markup=reply_markup)
    return SELECT_VIDEO_STATE

async def list_videos_for_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_to_reply = update.message if update.message else update.callback_query.message

    videos_dir_abs = CONFIG["VIDEOS_DIR"] 
    video_files = [f for f in os.listdir(videos_dir_abs) if os.path.isfile(os.path.join(videos_dir_abs, f))]
    
    streamer_dir_for_config_path = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
    streamer_config_path = os.path.join(streamer_dir_for_config_path, "config.json")
    allowed_extensions = []
    try:
        with open(streamer_config_path, 'r') as f:
            streamer_conf = json.load(f)
        allowed_extensions = [ext.lower() for ext in streamer_conf.get("VIDEO_EXTENSIONS", [])]
    except (FileNotFoundError, json.JSONDecodeError):
        logger.error(f"Gagal membaca streamer config dari '{streamer_config_path}'. Menggunakan ekstensi default.")
        allowed_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']

    valid_video_files = [f for f in video_files if os.path.splitext(f)[1].lower() in allowed_extensions]

    if not valid_video_files:
        await message_to_reply.reply_text("Tidak ada video yang ditemukan untuk dihapus di folder 'uploaded_videos'.")
        await send_main_menu(update, context)
        return ConversationHandler.END

    keyboard = []
    for video in valid_video_files:
        keyboard.append([InlineKeyboardButton(f"🗑️ {video}", callback_data=f"delete_video_{video}")])
    keyboard.append([InlineKeyboardButton("◀️ Kembali ke Menu Utama", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await message_to_reply.reply_text("Pilih video yang ingin dihapus:", reply_markup=reply_markup)
    return DELETE_VIDEO_STATE


# --- Conversation Handlers ---
async def enter_stream_key_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Silakan kirim kunci streaming Anda. (Ini akan disimpan di keystream.txt)")
    elif update.message:
        await update.message.reply_text("Silakan kirim kunci streaming Anda. (Ini akan disimpan di keystream.txt)")
    return ENTER_KEY_STATE

async def receive_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_auth(update, context): return ConversationHandler.END

    stream_key = update.message.text.strip()
    if not stream_key:
        await update.message.reply_text("Kunci streaming tidak boleh kosong. Silakan coba lagi.")
        return ENTER_KEY_STATE
    
    if write_stream_key_to_file(stream_key):
        await update.message.reply_text("Kunci streaming berhasil disimpan!")
        BOT_STATE["is_stream_key_set"] = True
        save_bot_state()
    else:
        await update.message.reply_text("Gagal menyimpan kunci streaming. Periksa log bot.")

    await send_main_menu(update.message, context)
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("Aksi dibatalkan.", reply_markup=ReplyKeyboardRemove())
        await send_main_menu(update.message, context)
    elif update.callback_query:
        await update.callback_query.message.reply_text("Aksi dibatalkan.")
        await send_main_menu(update.callback_query.message, context)
    return ConversationHandler.END

# --- Live Stream Control (Updated to accept 'update' object directly) ---
async def start_live_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message if update.message else update.callback_query.message
    if not await check_auth(update, context): return

    running, _ = is_stream_running()
    if running:
        await message.reply_text("Streaming sudah berjalan.")
        return

    if not BOT_STATE["selected_video"]:
        await message.reply_text("Anda belum memilih video. Silakan pilih video terlebih dahulu dari menu 'Pilih Video'.")
        return
    
    if not BOT_STATE["is_stream_key_set"]:
        await message.reply_text("Kunci streaming belum diatur. Silakan masukkan kunci streaming terlebih dahulu dari menu 'Atur Kunci Streaming'.")
        return

    if not os.path.exists(BOT_STATE["selected_video"]):
        await message.reply_text(f"Video yang dipilih '{os.path.basename(BOT_STATE['selected_video'])}' tidak ditemukan. Silakan pilih video lain.")
        BOT_STATE["selected_video"] = None
        save_bot_state()
        return

    await message.reply_text("Memulai streaming, mohon tunggu...")

    streamer_dir = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
    streamer_config_path = os.path.join(streamer_dir, "config.json")
    
    allowed_extensions = []
    try:
        with open(streamer_config_path, 'r') as f:
            streamer_conf = json.load(f)
        allowed_extensions = [ext.lower() for ext in streamer_conf.get("VIDEO_EXTENSIONS", [])]
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Gagal membaca streamer config dari '{streamer_config_path}'. Menggunakan ekstensi default untuk pembersihan: {e}")
        allowed_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']

    selected_video_filename = os.path.basename(BOT_STATE["selected_video"])
    destination_path_for_streamer = os.path.join(streamer_dir, selected_video_filename)

    for f in os.listdir(streamer_dir):
        file_ext = os.path.splitext(f)[1].lower()
        if file_ext in allowed_extensions and f != selected_video_filename:
            try:
                full_path_to_remove = os.path.join(streamer_dir, f)
                if os.path.islink(full_path_to_remove):
                    os.unlink(full_path_to_remove)
                    logger.info(f"Menghapus symlink lama di direktori streamer: {full_path_to_remove}")
                elif os.path.isfile(full_path_to_remove):
                    os.remove(full_path_to_remove)
                    logger.info(f"Menghapus video fisik lama di direktori streamer: {full_path_to_remove}")
            except Exception as ex:
                logger.warning(f"Gagal menghapus video/symlink lama {f}: {ex}")

    try:
        if not os.path.exists(destination_path_for_streamer) or \
           not os.path.islink(destination_path_for_streamer) or \
           (os.path.islink(destination_path_for_streamer) and os.readlink(destination_path_for_streamer) != BOT_STATE["selected_video"]):
            
            if os.path.exists(destination_path_for_streamer):
                try:
                    os.unlink(destination_path_for_streamer)
                except OSError as ose:
                    if ose.errno == 21:
                        pass 
                    else:
                        os.remove(destination_path_for_streamer)
                except Exception as ex:
                    logger.warning(f"Gagal membersihkan tujuan symlink {destination_path_for_streamer}: {ex}")

            os.symlink(BOT_STATE["selected_video"], destination_path_for_streamer)
            logger.info(f"Membuat symlink: {BOT_STATE['selected_video']} -> {destination_path_for_streamer}")
        else:
            logger.info(f"Symlink {destination_path_for_streamer} sudah ada dan menunjuk ke video yang benar.")

    except Exception as e:
        logger.error(f"Gagal menyiapkan video untuk streamer (symlink/copy): {e}", exc_info=True)
        await message.reply_text(f"Gagal menyiapkan video untuk streamer (symlink/copy): {e}\nCoba secara manual menempatkan video yang dipilih di folder yang sama dengan streamer.py.")
        return

    if start_stream_process():
        await message.reply_text("Streaming berhasil dimulai! Cek log FFmpeg untuk detail.")
    else:
        await message.reply_text("Gagal memulai streaming. Periksa log bot.")

async def stop_live_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message if update.message else update.callback_query.message
    if not await check_auth(update, context): return

    running, pid = is_stream_running()
    if not running:
        await message.reply_text("Streaming tidak sedang berjalan.")
    else:
        if BOT_STATE["scheduled_stop_job_name"]:
            current_jobs = context.job_queue.get_jobs_by_name(BOT_STATE["scheduled_stop_job_name"])
            for job in current_jobs:
                job.schedule_removal()
            BOT_STATE["scheduled_stop_job_name"] = None
            save_bot_state()
            await message.reply_text("Jadwal penghentian live telah dibatalkan.")

        await message.reply_text(f"Menghentikan streaming (PID: {pid}), mohon tunggu...")
        if stop_stream_process(pid):
            await message.reply_text("Streaming berhasil dihentikan.")
        else:
            await message.reply_text("Gagal menghentikan streaming. Periksa log bot.")

async def scheduled_stop_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    await context.bot.send_message(chat_id=chat_id, text=f"Waktu yang dijadwalkan telah tiba. Menghentikan live...")
    running, pid = is_stream_running()
    if running:
        if stop_stream_process(pid):
            await context.bot.send_message(chat_id=chat_id, text="Streaming berhasil dihentikan secara terjadwal.")
        else:
            await context.bot.send_message(chat_id=chat_id, text="Gagal menghentikan streaming secara terjadwal. Periksa log bot.")
    else:
        await context.bot.send_message(chat_id=chat_id, text="Streaming tidak aktif saat waktu penghentian terjadwal tiba.")
    
    BOT_STATE["scheduled_stop_job_name"] = None
    save_bot_state()


async def schedule_stop_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_auth(update, context): return ConversationHandler.END

    input_text = update.message.text.strip().lower()

    if BOT_STATE["scheduled_stop_job_name"]:
        current_jobs = context.job_queue.get_jobs_by_name(BOT_STATE["scheduled_stop_job_name"])
        for job in current_jobs:
            job.schedule_removal()
        BOT_STATE["scheduled_stop_job_name"] = None
        save_bot_state()
        await update.message.reply_text("Jadwal sebelumnya dibatalkan.")

    delay_seconds = 0
    try:
        if 'm' in input_text or 'h' in input_text:
            total_minutes = 0
            if 'h' in input_text:
                parts = input_text.split('h')
                if not parts[0].isdigit():
                    raise ValueError("Format jam tidak valid.")
                hours = int(parts[0])
                total_minutes += hours * 60
                input_text = parts[1]
            if 'm' in input_text:
                minutes_str = input_text.replace('m', '')
                if minutes_str and not minutes_str.isdigit():
                    raise ValueError("Format menit tidak valid.")
                minutes = int(minutes_str) if minutes_str else 0
                total_minutes += minutes
            
            if total_minutes <= 0:
                raise ValueError("Durasi harus positif.")
            
            delay_seconds = total_minutes * 60
            schedule_message = f"Live akan dihentikan secara otomatis dalam {total_minutes} menit."

        elif ':' in input_text:
            now = datetime.now()
            time_parts = input_text.split(':')
            if len(time_parts) != 2 or not all(part.isdigit() for part in time_parts):
                 raise ValueError("Format waktu HH:MM tidak valid.")
            
            hours, minutes = map(int, time_parts)
            
            if not (0 <= hours <= 23 and 0 <= minutes <= 59):
                raise ValueError("Jam atau menit di luar rentang valid (0-23, 0-59).")

            scheduled_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            
            if scheduled_time < now:
                scheduled_time += timedelta(days=1)

            delay_seconds = (scheduled_time - now).total_seconds()
            schedule_message = f"Live akan dihentikan secara otomatis pada {scheduled_time.strftime('%H:%M:%S')}."

        else:
            raise ValueError("Format waktu tidak valid. Gunakan '30m', '1h', '2h30m' atau 'HH:MM'.")

        if delay_seconds < 10:
            await update.message.reply_text("Waktu penjadwalan terlalu singkat (minimal 10 detik).")
            return SCHEDULE_STOP_STATE

        job_name = f"scheduled_stop_live_{update.message.chat_id}_{int(time.time())}"
        context.job_queue.run_once(scheduled_stop_callback, delay_seconds, chat_id=update.message.chat_id, name=job_name)
        
        BOT_STATE["scheduled_stop_job_name"] = job_name
        save_bot_state()
        await update.message.reply_text(schedule_message)

    except ValueError as e:
        await update.message.reply_text(f"Format waktu tidak valid: {e}. Silakan coba lagi.")
        return SCHEDULE_STOP_STATE
    except Exception as e:
        logger.error(f"Gagal menjadwalkan penghentian: {e}", exc_info=True)
        await update.message.reply_text("Terjadi kesalahan saat menjadwalkan. Periksa log bot.")

    await send_main_menu(update.message, context)
    return ConversationHandler.END


# --- Tampilan Status & Konfigurasi (Updated to accept 'update' object directly) ---
async def show_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message if update.message else update.callback_query.message
    if not await check_auth(update, context): return

    config_str = "--- KONFIGURASI BOT (bot_config.json) ---\n"
    for key, value in CONFIG.items():
        if key == "TELEGRAM_BOT_TOKEN":
            config_str += f"{key}: {'*' * 5} (Disembunyikan)\n"
        else:
            config_str += f"{key}: {value}\n"

    config_str += "\n--- STATUS BOT (bot_state.json) ---\n"
    config_str += f"Video Terpilih: {os.path.basename(BOT_STATE['selected_video']) if BOT_STATE['selected_video'] else 'Belum dipilih'}\n"
    config_str += f"Kunci Streaming Disetel: {'Ya ✅' if BOT_STATE['is_stream_key_set'] else 'Tidak ❌'}\n"
    
    running, pid = is_stream_running()
    config_str += f"Status Streaming: {'Berjalan (PID: ' + str(pid) + ')' if running else 'Tidak Berjalan'}\n"

    streamer_dir_for_config = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
    streamer_config_path = os.path.join(streamer_dir_for_config, "config.json")
    try:
        with open(streamer_config_path, 'r') as f:
            streamer_conf = json.load(f)
        config_str += "\n--- KONFIGURASI STREAMER (config.json) ---\n"
        for key, value in streamer_conf.items():
            if key == "KEY_FILENAME":
                continue
            config_str += f"{key}: {value}\n"
    except FileNotFoundError:
        config_str += "\n[WARNING] config.json streamer tidak ditemukan."
    except json.JSONDecodeError:
        config_str += "\n[WARNING] Format config.json streamer salah."
    except Exception as e:
        logger.error(f"Gagal membaca config.json streamer: {e}", exc_info=True)
        config_str += f"\n[ERROR] Gagal membaca config.json streamer: {e}"

    await message.reply_text(f"```json\n{config_str}\n```", parse_mode='MarkdownV2')


async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message if update.message else update.callback_query.message
    if not await check_auth(update, context): return

    running, pid = is_stream_running()
    status_text = f"Streaming sedang berjalan dengan PID: `{pid}`" if running else "Streaming tidak sedang berjalan."
    
    status_text += f"\nVideo Terpilih: {os.path.basename(BOT_STATE['selected_video']) if BOT_STATE['selected_video'] else 'Belum dipilih'}"
    status_text += f"\nKunci Streaming Disetel: {'Ya ✅' if BOT_STATE['is_stream_key_set'] else 'Tidak ❌'}"
    
    if BOT_STATE["scheduled_stop_job_name"]:
        job_found = False
        current_jobs = context.job_queue.get_jobs_by_name(BOT_STATE["scheduled_stop_job_name"])
        if current_jobs:
            job = current_jobs[0]
            tz_info = job.tzinfo if job.tzinfo else datetime.now().astimezone().tzinfo 
            
            remaining_time_seconds = job.next_t - datetime.now(tz_info).timestamp()
            remaining_td = timedelta(seconds=max(0, int(remaining_time_seconds)))
            
            scheduled_dt_local = datetime.fromtimestamp(job.next_t, tz_info)
            
            status_text += f"\nDijadwalkan Berhenti: Dalam {remaining_td} (pada {scheduled_dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')})"
            job_found = True
        if not job_found: 
            BOT_STATE["scheduled_stop_job_name"] = None
            save_bot_state()
            status_text += "\nAda jadwal yang dicatat sebelumnya, tetapi tidak aktif (mungkin bot baru di-restart)."
    else:
        status_text += "\nTidak ada jadwal penghentian live."

    await message.reply_text(status_text, parse_mode='MarkdownV2')


async def view_ffmpeg_log_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message if update.message else update.callback_query.message
    if not await check_auth(update, context): return

    log_file_path = CONFIG['LOG_FILE']
    
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, 'rb') as f:
                await message.reply_document(f, caption="Log FFmpeg terbaru:")
        except Exception as e:
            logger.error(f"Gagal membaca file log: {e}", exc_info=True)
            await message.reply_text(f"Gagal membaca file log: {e}")
    else:
        await message.reply_text("File log FFmpeg tidak ditemukan.")

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menangani pesan teks yang berasal dari ReplyKeyboardMarkup."""
    if not await check_auth(update, context): return ConversationHandler.END

    message_text = update.message.text

    # Logika untuk memulai ConversationHandler
    if message_text == "🎬 Pilih Video":
        # Panggil fungsi entry point ConversationHandler yang akan mengembalikan state
        return await list_videos_for_selection(update, context) 
    elif message_text == "⬆️ Unggah Video Baru":
        await update.message.reply_text("Silakan unggah file video Anda sekarang. Bot akan menyimpannya di folder 'uploaded_videos'.")
        return UPLOAD_VIDEO_STATE
    elif message_text == "🔑 Atur Kunci Streaming":
        await update.message.reply_text("Silakan kirim kunci streaming Anda. (Ini akan disimpan di keystream.txt)")
        return ENTER_KEY_STATE
    elif message_text == "⏰ Jadwal Hentikan Live":
        await update.message.reply_text("Untuk menjadwalkan penghentian, balas dengan durasi (misal: '30m' untuk 30 menit, '1h' untuk 1 jam, '2h30m' untuk 2 jam 30 menit) atau waktu spesifik (misal: '23:00').")
        return SCHEDULE_STOP_STATE
    elif message_text == "🗑️ Hapus Video":
        return await list_videos_for_deletion(update, context) 
    
    # Logika untuk aksi langsung (non-ConversationHandler)
    elif message_text == "🔴 Mulai Live":
        await start_live_handler(update, context)
        await send_main_menu(update, context) 
    elif message_text == "⏹️ Hentikan Live":
        await stop_live_handler(update, context)
        await send_main_menu(update, context)
    elif message_text == "⚙️ Status & Konfigurasi":
        await show_config_handler(update, context)
        await send_main_menu(update, context)
    elif message_text == "🟢 Cek Status Live":
        await check_status_handler(update, context)
        await send_main_menu(update, context)
    elif message_text == "📄 Lihat Log FFmpeg":
        await view_ffmpeg_log_handler(update, context)
        await send_main_menu(update, context)
    elif message_text == "◀️ Kembali":
        await update.message.reply_text("Kembali ke menu utama.", reply_markup=ReplyKeyboardRemove())
        await send_main_menu(update, context)
    else:
        # Jika tidak ada tombol ReplyKeyboard yang cocok, ini bisa jadi input teks bebas.
        # Jika bukan bagian dari ConversationHandler yang aktif, maka ini adalah "unknown".
        # Ini penting agar ConversationHandler yang sedang menunggu input teks tidak terganggu.
        return ConversationHandler.END # Biarkan sistem ConversationHandler menangani, atau fallback ke unknown
                                     # Jika ConversationHandler tidak aktif, maka pesan akan jatuh ke unknown handler.


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menanggapi perintah yang tidak dikenal atau pesan teks di luar conversation."""
    if not await check_auth(update, context): return
    await update.message.reply_text("Maaf, perintah tersebut tidak dikenal atau tidak ada dalam alur percakapan saat ini.")
    await send_main_menu(update.message, context)

def main() -> None:
    """Menjalankan bot."""
    load_bot_config()
    load_bot_state()

    application = Application.builder().token(CONFIG['TELEGRAM_BOT_TOKEN']).build()

    common_fallbacks = [
        CommandHandler("cancel", cancel_conversation), 
        MessageHandler(filters.Regex("^◀️ Kembali$"), cancel_conversation),
        CallbackQueryHandler(cancel_conversation, pattern="^main_menu$") 
    ]

    # Conversation Handlers (HARUS diletakkan sebelum MessageHandler umum)
    # Ini akan menangkap input teks saat berada dalam state ConversationHandler.

    key_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(enter_stream_key_start, pattern="^enter_stream_key_inline$"), 
            # Entry point for ReplyKeyboard handled by handle_text_messages
        ],
        states={
            ENTER_KEY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_stream_key)],
        },
        fallbacks=common_fallbacks,
        allow_reentry=True
    )
    application.add_handler(key_conv_handler)

    schedule_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(schedule_stop_receive, pattern="^schedule_stop_live_inline$"),
            # Entry point for ReplyKeyboard handled by handle_text_messages
        ],
        states={
            SCHEDULE_STOP_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_stop_receive)],
        },
        fallbacks=common_fallbacks,
        allow_reentry=True
    )
    application.add_handler(schedule_conv_handler)

    upload_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_video_upload, pattern="^upload_video_inline$"),
            # Entry point for ReplyKeyboard handled by handle_text_messages
        ],
        states={
            UPLOAD_VIDEO_STATE: [MessageHandler(filters.Document.ALL, handle_video_upload)],
        },
        fallbacks=common_fallbacks,
        allow_reentry=True
    )
    application.add_handler(upload_conv_handler)

    select_video_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(list_videos_for_selection, pattern="^select_video_menu$"),
            # Entry point for ReplyKeyboard handled by handle_text_messages
        ],
        states={
            SELECT_VIDEO_STATE: [CallbackQueryHandler(button_callback_handler, pattern="^select_video_.*$")],
        },
        fallbacks=common_fallbacks,
        allow_reentry=True
    )
    application.add_handler(select_video_conv_handler)

    delete_video_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(list_videos_for_deletion, pattern="^delete_video_menu_inline$"),
            # Entry point for ReplyKeyboard handled by handle_text_messages
        ],
        states={
            DELETE_VIDEO_STATE: [CallbackQueryHandler(button_callback_handler, pattern="^delete_video_.*$")],
        },
        fallbacks=common_fallbacks,
        allow_reentry=True
    )
    application.add_handler(delete_video_conv_handler)

    # Handler Perintah Telegram Umum
    application.add_handler(CommandHandler("start", start_command))
    
    # MessageHandler untuk tombol ReplyKeyboard.
    # Ini harus ditempatkan setelah semua ConversationHandler,
    # tetapi sebelum MessageHandler yang lebih umum seperti 'unknown'.
    # Penting: filter.TEXT & ~filters.COMMAND akan menangkap ini.
    # Fungsi `handle_text_messages` akan mengembalikan ConversationHandler.END jika ia MULAImengirim ke conversation handler,
    # atau akan melakukan aksi dan mengirim menu utama kembali.
    # Jika ConversationHandler sudah aktif, `handle_text_messages` ini TIDAK akan dipanggil.
    # ConversationHandler akan mengambil prioritas.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & 
                                        (filters.Regex("🎬 Pilih Video") |
                                         filters.Regex("⬆️ Unggah Video Baru") |
                                         filters.Regex("🔑 Atur Kunci Streaming") |
                                         filters.Regex("⏰ Jadwal Hentikan Live") |
                                         filters.Regex("🗑️ Hapus Video") |
                                         filters.Regex("🔴 Mulai Live") |
                                         filters.Regex("⏹️ Hentikan Live") |
                                         filters.Regex("⚙️ Status & Konfigurasi") |
                                         filters.Regex("🟢 Cek Status Live") |
                                         filters.Regex("📄 Lihat Log FFmpeg") |
                                         filters.Regex("◀️ Kembali")), 
                                        handle_text_messages))


    # Ini menangani sisa CallbackQueryHandler yang masih ada (misalnya dari list video yang ditampilkan oleh InlineKeyboard)
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    # Handler untuk command yang tidak dikenal (pastikan ini di paling akhir)
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    
    # Catch-all untuk pesan teks yang tidak ditangani oleh handler lain
    # Ini adalah fallback jika MessageHandler di atas tidak cocok DAN tidak ada ConversationHandler aktif.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    logger.info("Bot dimulai. Tekan Ctrl+C untuk menghentikan.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
