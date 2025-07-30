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
SELECT_VIDEO_STATE, ENTER_KEY_STATE, SCHEDULE_STOP_STATE, DELETE_VIDEO_STATE, UPLOAD_VIDEO_STATE = range(5) # Tambahkan UPLOAD_VIDEO_STATE

# Default config jika file tidak ditemukan atau error
DEFAULT_BOT_CONFIG = {
    "TELEGRAM_BOT_TOKEN": "GANTI_DENGAN_TOKEN_BOT_ANDA",
    "ALLOWED_CHAT_ID": 0,
    "STREAM_SCRIPT_PATH": "streamer.py", # Ini adalah relatif terhadap lokasi telegram_bot.py
    "PID_FILE": "stream_process.pid",
    "LOG_FILE": "ffmpeg_log.txt",
    "VIDEOS_DIR": "uploaded_videos" # Ini adalah relatif terhadap lokasi telegram_bot.py
}

DEFAULT_BOT_STATE = {
    "selected_video": None, # Path absolut dari video yang dipilih
    "is_stream_key_set": False, # Status apakah kunci streaming sudah diatur
    "scheduled_stop_job_name": None # Untuk melacak job yang dijadwalkan (di memory)
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
        # Pastikan semua kunci default ada di konfigurasi yang dimuat
        for key, default_value in DEFAULT_BOT_CONFIG.items():
            if key not in CONFIG:
                CONFIG[key] = default_value
        logger.info(f"Konfigurasi bot dimuat dari '{config_file_path}'.")

        # Validasi penting: token dan chat ID
        if CONFIG["TELEGRAM_BOT_TOKEN"] == DEFAULT_BOT_CONFIG["TELEGRAM_BOT_TOKEN"] or not CONFIG["TELEGRAM_BOT_TOKEN"]:
            logger.error("Token bot Telegram belum diatur di bot_config.json. Bot tidak akan berfungsi.")
            sys.exit(1)
        if CONFIG["ALLOWED_CHAT_ID"] == DEFAULT_BOT_CONFIG["ALLOWED_CHAT_ID"] or not CONFIG["ALLOWED_CHAT_ID"]:
            logger.error("Chat ID yang diizinkan belum diatur di bot_config.json. Bot tidak akan berfungsi.")
            sys.exit(1)

        # Ubah VIDEOS_DIR menjadi path absolut segera setelah dimuat
        # Ini akan menjadi YtubeLive/uploaded_videos
        CONFIG["VIDEOS_DIR"] = os.path.abspath(os.path.join(current_script_dir, CONFIG["VIDEOS_DIR"]))
        os.makedirs(CONFIG["VIDEOS_DIR"], exist_ok=True)
        logger.info(f"Memastikan direktori video '{CONFIG['VIDEOS_DIR']}' ada. Path absolut: {CONFIG['VIDEOS_DIR']}")

        # Ubah STREAM_SCRIPT_PATH menjadi path absolut
        CONFIG["STREAM_SCRIPT_PATH"] = os.path.abspath(os.path.join(current_script_dir, CONFIG["STREAM_SCRIPT_PATH"]))
        logger.info(f"Streamer script path: {CONFIG['STREAM_SCRIPT_PATH']}")

        # Ubah PID_FILE dan LOG_FILE juga menjadi absolut jika Anda ingin mereka di root folder
        # Jika Anda ingin mereka berada di direktori yang sama dengan telegram_bot.py
        CONFIG["PID_FILE"] = os.path.abspath(os.path.join(current_script_dir, CONFIG["PID_FILE"]))
        CONFIG["LOG_FILE"] = os.path.abspath(os.path.join(current_script_dir, CONFIG["LOG_FILE"]))
        logger.info(f"PID File: {CONFIG['PID_FILE']}, Log File: {CONFIG['LOG_FILE']}")


    except FileNotFoundError:
        logger.warning(f"File '{BOT_CONFIG_FILE}' tidak ditemukan. Membuat file konfigurasi bot default...")
        CONFIG = DEFAULT_BOT_CONFIG
        save_bot_config() # Simpan konfigurasi default baru
        logger.error(f"Harap edit '{BOT_CONFIG_FILE}' dengan token bot dan Chat ID Anda, lalu jalankan ulang bot.")
        sys.exit(1) # Keluar karena konfigurasi belum lengkap
    except json.JSONDecodeError:
        logger.error(f"Kesalahan format JSON di '{BOT_CONFIG_FILE}'. Menggunakan konfigurasi bot default.")
        CONFIG = DEFAULT_BOT_CONFIG
        logger.error(f"Harap perbaiki atau hapus '{BOT_CONFIG_FILE}' jika Anda ingin menggunakan konfigurasi baru.")
        sys.exit(1) # Keluar karena konfigurasi bermasalah

def save_bot_config():
    """Menyimpan konfigurasi bot saat ini ke bot_config.json."""
    try:
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        config_file_path = os.path.join(current_script_dir, BOT_CONFIG_FILE)
        
        # Buat salinan CONFIG agar tidak menyimpan path absolut kembali ke bot_config.json
        # Ini penting agar bot_config.json tetap portable dengan path relatif
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
        # Pastikan semua kunci default ada di status yang dimuat
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
        save_bot_state() # Simpan status default yang baru

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
    # Path ke config.json streamer relatif terhadap lokasi telegram_bot.py
    streamer_dir = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH']) # streamer_dir sudah absolut dari CONFIG["STREAM_SCRIPT_PATH"]
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
    if update.effective_chat.id != CONFIG['ALLOWED_CHAT_ID']:
        if update.callback_query:
            await update.callback_query.message.reply_text("Maaf, Anda tidak diizinkan menggunakan bot ini.")
        else:
            await update.message.reply_text("Maaf, Anda tidak diizinkan menggunakan bot ini.")
        logger.warning(f"Akses tidak sah dari Chat ID: {update.effective_chat.id} mencoba akses.")
        return False
    return True

def is_stream_running():
    """Mengecek apakah proses streaming sedang berjalan."""
    pid_file_path = CONFIG['PID_FILE'] # Ini sudah absolut dari load_bot_config
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
        # streamer_dir adalah direktori tempat streamer.py berada (sudah absolut dari CONFIG['STREAM_SCRIPT_PATH'])
        streamer_dir = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
        destination_path_for_streamer = os.path.join(streamer_dir, selected_video_filename)

        # Dapatkan ekstensi yang diizinkan dari config.json streamer untuk menghapus video lama
        streamer_config_path_abs = os.path.join(streamer_dir, "config.json")
        allowed_extensions = []
        try:
            with open(streamer_config_path_abs, 'r') as f:
                streamer_conf = json.load(f)
            allowed_extensions = [ext.lower() for ext in streamer_conf.get("VIDEO_EXTENSIONS", [])]
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Gagal membaca streamer config dari '{streamer_config_path_abs}'. Menggunakan ekstensi default untuk pembersihan: {e}")
            allowed_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']

        # Hapus video/symlink lama yang mungkin ada di direktori streamer.py yang akan digunakan
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

        # Buat symlink dari video yang dipilih ke direktori streamer.py
        if not os.path.exists(destination_path_for_streamer) or \
           not os.path.islink(destination_path_for_streamer) or \
           os.readlink(destination_path_for_streamer) != BOT_STATE["selected_video"]:
            
            if os.path.exists(destination_path_for_streamer):
                try:
                    os.unlink(destination_path_for_streamer)
                except OSError as ose:
                    if ose.errno == 21: # If it's a directory
                        pass # Ignore if it's a directory, as we only expect files/symlinks to files
                    else:
                        os.remove(destination_path_for_streamer)
                except Exception as ex:
                    logger.warning(f"Gagal membersihkan tujuan symlink {destination_path_for_streamer}: {ex}")

            os.symlink(BOT_STATE["selected_video"], destination_path_for_streamer)
            logger.info(f"Membuat symlink: {BOT_STATE['selected_video']} -> {destination_path_for_streamer}")
        else:
            logger.info(f"Symlink {destination_path_for_streamer} sudah ada dan menunjuk ke video yang benar.")


        # Jalankan script streamer.py
        process = subprocess.Popen([sys.executable, CONFIG['STREAM_SCRIPT_PATH']],
                                     cwd=streamer_dir, # Working directory untuk streamer.py
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
    """Mengirim menu utama bot dengan ikon."""
    # Menu ReplyKeyboardMarkup (untuk bagian bawah keyboard)
    reply_keyboard = [
        [KeyboardButton("🎬 Pilih Video"), KeyboardButton("⬆️ Unggah Video Baru")],
        [KeyboardButton("🔑 Atur Kunci Streaming"), KeyboardButton("🔴 Mulai Live"), KeyboardButton("⏹️ Hentikan Live")],
        [KeyboardButton("⏰ Jadwal Hentikan Live"), KeyboardButton("🗑️ Hapus Video")],
        [KeyboardButton("⚙️ Status & Konfigurasi"), KeyboardButton("📄 Lihat Log FFmpeg")],
        [KeyboardButton("◀️ Kembali")] # Tombol Kembali untuk menyingkirkan keyboard atau kembali ke menu utama
    ]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    # Inline Keyboard (opsional, jika Anda ingin tetap memiliki opsi ini di dalam pesan)
    inline_keyboard = [
        [InlineKeyboardButton("🎬 Pilih Video", callback_data="select_video_menu"),
         InlineKeyboardButton("⬆️ Unggah Video Baru", callback_data="upload_video")],
        [InlineKeyboardButton("🔑 Masukkan Kunci Streaming", callback_data="enter_stream_key")],
        [InlineKeyboardButton("🔴 Mulai Live", callback_data="start_live"),
         InlineKeyboardButton("⏹️ Hentikan Live", callback_data="stop_live")],
        [InlineKeyboardButton("⏰ Jadwal Hentikan Live", callback_data="schedule_stop_live"),
         InlineKeyboardButton("🗑️ Hapus Video", callback_data="delete_video_menu")],
        [InlineKeyboardButton("⚙️ Tampilkan Konfigurasi", callback_data="show_config"),
         InlineKeyboardButton("🟢 Cek Status Live", callback_data="check_status")],
        [InlineKeyboardButton("📄 Lihat Log FFmpeg", callback_data="view_ffmpeg_log")],
    ]
    inline_reply_markup = InlineKeyboardMarkup(inline_keyboard)

    if isinstance(update, Update):
        if update.message:
            # Kirim pesan dengan ReplyKeyboardMarkup sebagai menu utama
            await update.message.reply_text("Pilih aksi dari menu di bawah:", reply_markup=reply_markup)
            # Anda bisa juga mengirim InlineKeyboard secara terpisah jika diperlukan
            # await update.message.reply_text("Atau pilih aksi dari tombol di dalam pesan:", reply_markup=inline_reply_markup)
        elif update.callback_query:
            try:
                # Jika dari callback, edit pesan sebelumnya jika memungkinkan, tetapi kirim ReplyKeyboardMarkup baru
                # Perhatikan bahwa edit_reply_markup tidak didukung untuk ReplyKeyboardMarkup
                await update.callback_query.message.edit_text("Pilih aksi dari menu di bawah:", reply_markup=inline_reply_markup) # Tetap gunakan inline untuk edit pesan
                await context.bot.send_message(chat_id=update.effective_chat.id, text="Menu utama:", reply_markup=reply_markup) # Kirim menu Reply baru
            except Exception as e:
                logger.warning(f"Gagal mengedit pesan callback, mengirim pesan baru: {e}")
                await update.callback_query.message.reply_text("Pilih aksi dari menu di bawah:", reply_markup=reply_markup)
    else:
        # Fallback jika 'update' bukan objek Update (misal, dari JobQueue)
        await context.bot.send_message(chat_id=CONFIG['ALLOWED_CHAT_ID'], text="Pilih aksi:", reply_markup=reply_markup)


# --- Handler Perintah Telegram ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengirim menu utama saat perintah /start diterima."""
    if not await check_auth(update, context): return
    await send_main_menu(update, context)

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani callback dari tombol inline keyboard."""
    query = update.callback_query
    await query.answer() # Harus dipanggil untuk "menutup" notifikasi loading di Telegram

    action = query.data

    if action == "select_video_menu":
        await list_videos_for_selection(query.message, context)
    elif action == "upload_video":
        await query.message.reply_text("Silakan unggah file video Anda sekarang. Bot akan menyimpannya di folder 'uploaded_videos'.")
        return UPLOAD_VIDEO_STATE # Masuk ke state UPLOAD_VIDEO_STATE
    elif action == "enter_stream_key":
        await query.edit_message_text("Silakan kirim kunci streaming Anda. (Ini akan disimpan di keystream.txt)")
        return ENTER_KEY_STATE # Masuk ke state ENTER_KEY_STATE
    elif action == "start_live":
        await start_live_handler(query.message, context)
        # await send_main_menu(update, context) # Tidak perlu panggil lagi, karena sudah ditangani di `handle_text_messages`
    elif action == "stop_live":
        await stop_live_handler(query.message, context)
        # await send_main_menu(update, context)
    elif action == "schedule_stop_live":
        await query.edit_message_text("Untuk menjadwalkan penghentian, balas dengan durasi (misal: '30m' untuk 30 menit, '1h' untuk 1 jam, '2h30m' untuk 2 jam 30 menit) atau waktu spesifik (misal: '23:00').")
        return SCHEDULE_STOP_STATE # Masuk ke state SCHEDULE_STOP_STATE
    elif action == "delete_video_menu":
        await list_videos_for_deletion(query.message, context)
    elif action == "show_config":
        await show_config_handler(query.message, context)
        # await send_main_menu(update, context)
    elif action == "check_status":
        await check_status_handler(query.message, context)
        # await send_main_menu(update, context)
    elif action == "view_ffmpeg_log":
        await view_ffmpeg_log_handler(query.message, context)
        # await send_main_menu(update, context)
    else: # Menangani pemilihan video atau penghapusan video
        if action.startswith("select_video_"):
            video_name = action.replace("select_video_", "")
            # Path absolut video terpilih
            selected_path = os.path.join(CONFIG["VIDEOS_DIR"], video_name) 
            if os.path.exists(selected_path):
                BOT_STATE["selected_video"] = selected_path
                save_bot_state()
                await query.edit_message_text(f"Video '{video_name}' telah dipilih.\nSekarang Anda bisa memulai live.")
            else:
                await query.edit_message_text(f"Video '{video_name}' tidak ditemukan. Silakan pilih lagi.")
            await send_main_menu(update, context) # Kembali ke menu utama setelah pemilihan
        elif action.startswith("delete_video_"):
            video_name = action.replace("delete_video_", "")
            # Path absolut video yang akan dihapus
            video_path = os.path.join(CONFIG["VIDEOS_DIR"], video_name)
            if os.path.exists(video_path):
                try:
                    os.remove(video_path)
                    await query.edit_message_text(f"Video '{video_name}' berhasil dihapus.")
                    # Jika video yang dihapus adalah yang sedang dipilih, reset selected_video
                    if BOT_STATE["selected_video"] == video_path:
                        BOT_STATE["selected_video"] = None
                        save_bot_state()
                except Exception as e:
                    logger.error(f"Gagal menghapus video '{video_name}': {e}", exc_info=True)
                    await query.edit_message_text(f"Gagal menghapus video '{video_name}': {e}")
            else:
                await query.edit_message_text(f"Video '{video_name}' tidak ditemukan.")
            await send_main_menu(update, context) # Kembali ke menu utama setelah penghapusan
    
    # Jika tidak ada return ConversationHandler.END, asumsikan tetap di menu utama atau kembali ke sana
    if not (action.startswith("enter_stream_key") or action.startswith("schedule_stop_live") or action.startswith("upload_video")):
        await send_main_menu(update, context)

# --- Fitur Manajemen Video ---
async def handle_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menangani unggahan file video."""
    if not await check_auth(update, context): return ConversationHandler.END # Hentikan percakapan jika tidak berwenang

    logger.info(f"Menerima pesan. Tipe pesan efektif: {update.message.effective_attachment.mime_type if update.message.effective_attachment else 'No Attachment'}")

    if update.message.document:
        doc = update.message.document
        logger.info(f"Dokumen diterima: {doc.file_name} (MIME: {doc.mime_type}, Size: {doc.file_size} bytes)")

        file_extension = os.path.splitext(doc.file_name)[1].lower()
        
        # Path ke config.json streamer relatif terhadap lokasi telegram_bot.py
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
            
            # CONFIG["VIDEOS_DIR"] sudah absolut dari load_bot_config()
            videos_dir_abs = CONFIG["VIDEOS_DIR"] 
            os.makedirs(videos_dir_abs, exist_ok=True) # Pastikan direktori ada sebelum mengunduh

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

    await send_main_menu(update.message, context) # Mengirim menu utama setelah proses upload selesai
    return ConversationHandler.END # Akhiri conversation setelah upload

async def list_videos_for_selection(message, context: ContextTypes.DEFAULT_TYPE):
    # CONFIG["VIDEOS_DIR"] sudah absolut dari load_bot_config()
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
        await message.reply_text("Tidak ada video yang ditemukan di folder 'uploaded_videos'.")
        return

    keyboard = []
    for video in valid_video_files:
        current_video_abs_path = os.path.join(videos_dir_abs, video)
        is_selected = " ✅" if current_video_abs_path == BOT_STATE["selected_video"] else ""
        keyboard.append([InlineKeyboardButton(f"🎬 {video}{is_selected}", callback_data=f"select_video_{video}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text("Pilih video yang ingin di-stream:", reply_markup=reply_markup)

async def list_videos_for_deletion(message, context: ContextTypes.DEFAULT_TYPE):
    # CONFIG["VIDEOS_DIR"] sudah absolut dari load_bot_config()
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
        await message.reply_text("Tidak ada video yang ditemukan untuk dihapus di folder 'uploaded_videos'.")
        return

    keyboard = []
    for video in valid_video_files:
        keyboard.append([InlineKeyboardButton(f"🗑️ {video}", callback_data=f"delete_video_{video}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text("Pilih video yang ingin dihapus:", reply_markup=reply_markup)

# --- Conversation Handlers ---
async def enter_stream_key_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Ini bisa dipanggil dari CallbackQuery atau dari pesan teks langsung
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Silakan kirim kunci streaming Anda. (Ini akan disimpan di keystream.txt)")
    else: # Dipanggil dari pesan teks
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
    await update.message.reply_text("Aksi dibatalkan.")
    await send_main_menu(update.message, context)
    return ConversationHandler.END

# --- Live Stream Control ---
async def start_live_handler(message, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    streamer_dir = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH']) # Sudah absolut
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

    # Hapus video/symlink lama yang mungkin ada di direktori streamer.py yang akan digunakan
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

    # Buat symlink dari video yang dipilih ke direktori streamer.py
    try:
        if not os.path.exists(destination_path_for_streamer) or \
           not os.path.islink(destination_path_for_streamer) or \
           os.readlink(destination_path_for_streamer) != BOT_STATE["selected_video"]:
            
            if os.path.exists(destination_path_for_streamer):
                try:
                    os.unlink(destination_path_for_streamer)
                except OSError as ose:
                    if ose.errno == 21: # If it's a directory
                        pass # Ignore if it's a directory, as we only expect files/symlinks to files
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

async def stop_live_handler(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menghentikan streaming live."""
    running, pid = is_stream_running()
    if not running:
        await message.reply_text("Streaming tidak sedang berjalan.")
    else:
        # Batalkan jadwal stop jika ada
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
    """Fungsi callback untuk menghentikan live secara terjadwal."""
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
    """Menerima input jadwal dari pengguna."""
    if not await check_auth(update, context): return ConversationHandler.END

    input_text = update.message.text.strip().lower()

    # Batalkan jadwal sebelumnya jika ada
    if BOT_STATE["scheduled_stop_job_name"]:
        current_jobs = context.job_queue.get_jobs_by_name(BOT_STATE["scheduled_stop_job_name"])
        for job in current_jobs:
            job.schedule_removal()
        BOT_STATE["scheduled_stop_job_name"] = None
        save_bot_state()
        await update.message.reply_text("Jadwal sebelumnya dibatalkan.")

    delay_seconds = 0
    try:
        if 'm' in input_text or 'h' in input_text: # Durasi (contoh: 30m, 1h, 2h30m)
            total_minutes = 0
            if 'h' in input_text:
                parts = input_text.split('h')
                hours = int(parts[0])
                total_minutes += hours * 60
                input_text = parts[1] # Sisa setelah jam
            if 'm' in input_text:
                minutes = int(input_text.replace('m', ''))
                total_minutes += minutes
            
            if total_minutes <= 0:
                raise ValueError("Durasi harus positif.")
            
            delay_seconds = total_minutes * 60
            schedule_message = f"Live akan dihentikan secara otomatis dalam {total_minutes} menit."

        elif ':' in input_text: # Waktu spesifik (contoh: 23:00)
            now = datetime.now()
            hours, minutes = map(int, input_text.split(':'))
            scheduled_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            
            if scheduled_time < now:
                scheduled_time += timedelta(days=1) # Jika waktu sudah lewat, jadwalkan untuk besok

            delay_seconds = (scheduled_time - now).total_seconds()
            schedule_message = f"Live akan dihentikan secara otomatis pada {scheduled_time.strftime('%H:%M:%S')}."

        else:
            raise ValueError("Format waktu tidak valid.")

        if delay_seconds < 10: # Minimal 10 detik untuk jadwal
            await update.message.reply_text("Waktu penjadwalan terlalu singkat (minimal 10 detik).")
            return SCHEDULE_STOP_STATE # Tetap di state ini

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


# --- Tampilan Status & Konfigurasi ---
async def show_config_handler(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan konfigurasi bot dan streamer."""
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

    # Baca konfigurasi streamer
    streamer_dir_for_config = os.path.dirname(CONFIG['STREAM_SCRIPT_PATH'])
    streamer_config_path = os.path.join(streamer_dir_for_config, "config.json")
    try:
        with open(streamer_config_path, 'r') as f:
            streamer_conf = json.load(f)
        config_str += "\n--- KONFIGURASI STREAMER (config.json) ---\n"
        for key, value in streamer_conf.items():
            if key == "KEY_FILENAME": # Jangan tampilkan nama file kunci
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


async def check_status_handler(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengecek status streaming."""
    running, pid = is_stream_running()
    status_text = f"Streaming sedang berjalan dengan PID: `{pid}`" if running else "Streaming tidak sedang berjalan."
    
    status_text += f"\nVideo Terpilih: {os.path.basename(BOT_STATE['selected_video']) if BOT_STATE['selected_video'] else 'Belum dipilih'}"
    status_text += f"\nKunci Streaming Disetel: {'Ya ✅' if BOT_STATE['is_stream_key_set'] else 'Tidak ❌'}"
    
    # Cek jadwal
    if BOT_STATE["scheduled_stop_job_name"]:
        job_found = False
        current_jobs = context.job_queue.get_jobs_by_name(BOT_STATE["scheduled_stop_job_name"])
        if current_jobs:
            job = current_jobs[0]
            # Job is scheduled with TZ aware datetime, job.next_t is UTC timestamp
            # Convert job.next_t (timestamp) back to datetime object in its timezone for display
            tz = job.tzinfo if job.tzinfo else datetime.now().astimezone().tzinfo # Fallback to local timezone
            
            # Hitung waktu tersisa
            remaining_time_seconds = job.next_t - datetime.now(tz).timestamp()
            remaining_td = timedelta(seconds=max(0, int(remaining_time_seconds)))
            
            # Waktu scheduled dalam format yang dapat dibaca
            scheduled_dt_local = datetime.fromtimestamp(job.next_t, tz)
            
            status_text += f"\nDijadwalkan Berhenti: Dalam {remaining_td} (pada {scheduled_dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')})"
            job_found = True
        if not job_found: # Jika job_name ada tapi job_queue tidak menemukannya (misal bot restart)
            BOT_STATE["scheduled_stop_job_name"] = None
            save_bot_state()
            status_text += "\nAda jadwal yang dicatat sebelumnya, tetapi tidak aktif (mungkin bot baru di-restart)."
    else:
        status_text += "\nTidak ada jadwal penghentian live."


    await message.reply_text(status_text, parse_mode='MarkdownV2')


async def view_ffmpeg_log_handler(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengirim file log FFmpeg terbaru."""
    log_file_path = CONFIG['LOG_FILE'] # Ini sudah absolut
    
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, 'rb') as f:
                await message.reply_document(f, caption="Log FFmpeg terbaru:")
        except Exception as e:
            logger.error(f"Gagal membaca file log: {e}", exc_info=True)
            await message.reply_text(f"Gagal membaca file log: {e}")
    else:
        await message.reply_text("File log FFmpeg tidak ditemukan.")

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani pesan teks yang berasal dari ReplyKeyboardMarkup."""
    if not await check_auth(update, context): return ConversationHandler.END

    message_text = update.message.text

    if message_text == "🎬 Pilih Video":
        await list_videos_for_selection(update.message, context)
    elif message_text == "⬆️ Unggah Video Baru":
        await update.message.reply_text("Silakan unggah file video Anda sekarang. Bot akan menyimpannya di folder 'uploaded_videos'.")
        return UPLOAD_VIDEO_STATE # Masuk ke state UPLOAD_VIDEO_STATE untuk menunggu dokumen
    elif message_text == "🔑 Atur Kunci Streaming":
        await update.message.reply_text("Silakan kirim kunci streaming Anda. (Ini akan disimpan di keystream.txt)")
        return ENTER_KEY_STATE # Masuk ke state ENTER_KEY_STATE untuk menunggu kunci
    elif message_text == "🔴 Mulai Live":
        await start_live_handler(update.message, context)
    elif message_text == "⏹️ Hentikan Live":
        await stop_live_handler(update.message, context)
    elif message_text == "⏰ Jadwal Hentikan Live":
        await update.message.reply_text("Untuk menjadwalkan penghentian, balas dengan durasi (misal: '30m' untuk 30 menit, '1h' untuk 1 jam, '2h30m' untuk 2 jam 30 menit) atau waktu spesifik (misal: '23:00').")
        return SCHEDULE_STOP_STATE # Masuk ke state SCHEDULE_STOP_STATE
    elif message_text == "🗑️ Hapus Video":
        await list_videos_for_deletion(update.message, context)
    elif message_text == "⚙️ Status & Konfigurasi":
        await show_config_handler(update.message, context)
    elif message_text == "📄 Lihat Log FFmpeg":
        await view_ffmpeg_log_handler(update.message, context)
    elif message_text == "◀️ Kembali":
        await update.message.reply_text("Kembali ke menu utama.", reply_markup=ReplyKeyboardRemove()) # Menghilangkan keyboard
        await send_main_menu(update, context) # Mengirim kembali menu utama
    else:
        await update.message.reply_text("Maaf, perintah tersebut tidak dikenal.")
    
    # Kecuali jika masuk ke ConversationHandler, selalu kembali ke menu utama
    if context.bot_data.get('conversation_active_state') not in [ENTER_KEY_STATE, SCHEDULE_STOP_STATE, UPLOAD_VIDEO_STATE]:
        await send_main_menu(update, context)
    return ConversationHandler.END


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menanggapi perintah yang tidak dikenal atau pesan teks di luar conversation."""
    if not await check_auth(update, context): return
    await update.message.reply_text("Maaf, perintah tersebut tidak dikenal atau tidak ada dalam alur percakapan saat ini.")
    #await send_main_menu(update.message, context) # Hindari double menu

def main() -> None:
    """Menjalankan bot."""
    load_bot_config() # Muat konfigurasi bot di awal
    load_bot_state() # Muat status bot di awal

    application = Application.builder().token(CONFIG['TELEGRAM_BOT_TOKEN']).build()

    # Conversation Handler untuk Kunci Streaming
    key_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(enter_stream_key_start, pattern="^enter_stream_key$"),
            MessageHandler(filters.Regex("^🔑 Atur Kunci Streaming$"), enter_stream_key_start) # Tangani dari ReplyKeyboard
        ],
        states={
            ENTER_KEY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_stream_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation), MessageHandler(filters.Regex("^◀️ Kembali$"), cancel_conversation)],
        allow_reentry=True
    )
    application.add_handler(key_conv_handler)

    # Conversation Handler untuk Jadwal Hentikan Live
    schedule_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(schedule_stop_receive, pattern="^schedule_stop_live$"),
            MessageHandler(filters.Regex("^⏰ Jadwal Hentikan Live$"), schedule_stop_receive) # Tangani dari ReplyKeyboard
        ],
        states={
            SCHEDULE_STOP_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_stop_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation), MessageHandler(filters.Regex("^◀️ Kembali$"), cancel_conversation)],
        allow_reentry=True
    )
    application.add_handler(schedule_conv_handler)

    # Conversation Handler for Upload Video
    upload_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_video_upload, pattern="^upload_video$"),
            MessageHandler(filters.Regex("^⬆️ Unggah Video Baru$"), handle_video_upload) # Tangani dari ReplyKeyboard
        ],
        states={
            UPLOAD_VIDEO_STATE: [MessageHandler(filters.Document.ALL, handle_video_upload)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation), MessageHandler(filters.Regex("^◀️ Kembali$"), cancel_conversation)],
        allow_reentry=True
    )
    application.add_handler(upload_conv_handler)


    # Handler Perintah dan Callback Query Utama
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    # Handler untuk pesan teks dari ReplyKeyboardMarkup
    # Ini harus ditempatkan SETELAH ConversationHandlers lainnya
    # agar pesan yang dimaksudkan untuk ConversationHandler tidak ditangkap di sini.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
    # Handler untuk command yang tidak dikenal (pastikan ini di paling akhir)
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("Bot dimulai. Tekan Ctrl+C untuk menghentikan.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()