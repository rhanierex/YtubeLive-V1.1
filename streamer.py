import os
import subprocess
import sys
import platform
import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# --- KONFIGURASI ---
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "STREAM_URL": "rtmp://a.rtmp.youtube.com/live2", # Diperbarui ke yang lebih standar
    "VIDEO_EXTENSIONS": [".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm"],
    "KEY_FILENAME": "keystream.txt",
    "RETRY_LIMIT": 5,
    "LOG_FILE": "ffmpeg_log.txt",
    "TIMEZONE": "Asia/Makassar",
    "FFMPEG_PRESET": "veryfast",
    "VIDEO_BITRATE_KBPS": 2500,
    "AUDIO_BITRATE_KBPS": 128
}
CONFIG = {}

def load_config():
    """Memuat konfigurasi dari config.json atau membuat file default jika tidak ada."""
    global CONFIG
    try:
        with open(CONFIG_FILE, 'r') as f:
            CONFIG = json.load(f)
        for key, default_value in DEFAULT_CONFIG.items():
            if key not in CONFIG:
                CONFIG[key] = default_value
        print(f"[INFO] Konfigurasi dimuat dari '{CONFIG_FILE}'.")
    except FileNotFoundError:
        print(f"[INFO] File '{CONFIG_FILE}' tidak ditemukan. Membuat file konfigurasi default...")
        CONFIG = DEFAULT_CONFIG
        save_config()
    except json.JSONDecodeError:
        print(f"[ERROR] Kesalahan format JSON di '{CONFIG_FILE}'. Menggunakan konfigurasi default.")
        CONFIG = DEFAULT_CONFIG
        print(f"       Harap periksa atau hapus '{CONFIG_FILE}' jika Anda ingin menggunakan konfigurasi baru.")

    if not CONFIG["STREAM_URL"].startswith("rtmp://"):
        print("[WARNING] STREAM_URL mungkin tidak valid. Pastikan dimulai dengan 'rtmp://'.")
    CONFIG["STREAM_URL"] = CONFIG["STREAM_URL"].strip('/')

def save_config():
    """Menyimpan konfigurasi saat ini ke config.json."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(CONFIG, f, indent=4)
        print(f"[INFO] Konfigurasi disimpan ke '{CONFIG_FILE}'.")
    except IOError as e:
        print(f"[ERROR] Gagal menyimpan konfigurasi ke '{CONFIG_FILE}': {e}")

def main():
    clear_screen()
    load_config()

    video_file = find_video_file(silent=True)

    if not video_file:
        print("[ERROR] Video tidak ditemukan di folder ini. Pastikan ada satu file video didalam folder.")
        # Tidak memanggil pause_and_exit() karena ini adalah subprocess
        return # Keluar dari main()

    video_name = os.path.splitext(os.path.basename(video_file))[0]
    if platform.system() == "Windows":
        os.system(f"title Streaming: {video_name}")

    print("=========================================")
    print(f"   ALIEF KRESNA UTAMA")
    print(f"   YOUTUBE STREAMER: [{video_name}]")
    print("=========================================")

    print_waktu_lokal()
    print(f"1. Video ditemukan: {video_file}\n")

    if not check_ffmpeg_installed():
        return # Keluar dari main()

    print(f"2. Membaca Kunci Streaming dari file '{CONFIG['KEY_FILENAME']}'...")
    stream_key = read_stream_key()
    if not stream_key:
        return # Keluar dari main()

    destination_url = f"{CONFIG['STREAM_URL']}/{stream_key}"

    video_codec, audio_codec = get_media_info(video_file)

    if video_codec == 'h264' and audio_codec == 'aac':
        print("3. Mode: COPY STREAM (tanpa re-encode) ✅\n")
        command = [
            'ffmpeg', '-re', '-stream_loop', '-1', '-i', video_file,
            '-c:v', 'copy', '-c:a', 'copy',
            '-f', 'flv', destination_url
        ]
    else:
        print(f"3. Mode: RE-ENCODE (video: {video_codec if video_codec else 'Tidak Ditemukan'}, audio: {audio_codec if audio_codec else 'Tidak Ditemukan'}) ⚠️")
        print("   FFmpeg akan melakukan re-encode ke H.264 (video) dan AAC (audio).")
        print(f"   Preset: {CONFIG['FFMPEG_PRESET']}, Video Bitrate: {CONFIG['VIDEO_BITRATE_KBPS']}kbps, Audio Bitrate: {CONFIG['AUDIO_BITRATE_KBPS']}kbps\n")
        command = [
            'ffmpeg', '-re', '-stream_loop', '-1', '-i', video_file,
            '-c:v', 'libx264', '-preset', CONFIG['FFMPEG_PRESET'],
            '-b:v', f"{CONFIG['VIDEO_BITRATE_KBPS']}k",
            '-maxrate', f"{CONFIG['VIDEO_BITRATE_KBPS']}k",
            '-bufsize', f"{CONFIG['VIDEO_BITRATE_KBPS'] * 2}k",
            '-g', '120', '-keyint_min', '120',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', f"{CONFIG['AUDIO_BITRATE_KBPS']}k",
            '-f', 'flv', destination_url
        ]

    print("-----------------------------------------")
    print("   SIARAN AKAN SEGERA DIMULAI...")
    print(f"   > Tujuan: {destination_url}")
    print("   > Tekan CTRL+C di jendela ini untuk menghentikan siaran.")
    print(f"   > Output FFmpeg akan dicatat di '{CONFIG['LOG_FILE']}'.")
    print("-----------------------------------------")

    retry_count = 0
    while retry_count < CONFIG['RETRY_LIMIT']:
        try:
            with open(CONFIG['LOG_FILE'], "a", encoding="utf-8") as log_file: # Ubah "w" ke "a" untuk append
                log_file.write(f"\n--- Memulai Siaran ({datetime.now(ZoneInfo(CONFIG['TIMEZONE'])).strftime('%Y-%m-%d %H:%M:%S')}) ---\n")
                process = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)
                process.wait()

            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, command)
            break
        except subprocess.CalledProcessError as e:
            retry_count += 1
            print(f"\n[ WARNING ] FFmpeg gagal dijalankan (percobaan {retry_count}/{CONFIG['RETRY_LIMIT']}). Kode keluar: {e.returncode}")
            print(f"            Lihat '{CONFIG['LOG_FILE']}' untuk detail lebih lanjut.")
            if retry_count >= CONFIG['RETRY_LIMIT']:
                print("\n[ FATAL ] Gagal setelah beberapa kali percobaan. Proses dibatalkan.")
                break
        except KeyboardInterrupt:
            print(f"\n\n[ INFO ] Siaran [{video_name}] dihentikan oleh pengguna.")
            if 'process' in locals() and process.poll() is None:
                process.terminate()
            break
        except Exception as e:
            print(f"\n[ ERROR ] Terjadi kesalahan tak terduga: {e}")
            break

    print(f"\nProses [{video_name}] selesai.")
    # Hapus atau beri komentar baris ini:
    # pause_and_exit(message="Tekan Enter untuk menutup jendela ini...")

# --- Helper Functions (Sama seperti sebelumnya) ---

def clear_screen():
    command = 'cls' if platform.system() == "Windows" else 'clear'
    os.system(command)

def pause_and_exit(message="Tekan Enter untuk keluar..."):
    # Fungsi ini tidak akan terpanggil lagi oleh main()
    # Tapi tetap ada jika ada bagian lain yang membutuhkannya
    print()
    if platform.system() == "Windows":
        os.system(f'cmd /c "echo {message} & pause > nul"')
    else:
        input(message)
    sys.exit(1)

def find_video_file(silent=False):
    if not silent:
        print("1. Mencari file video di folder ini...")
    video_files = [f for f in os.listdir('.') if f.lower().endswith(tuple(CONFIG["VIDEO_EXTENSIONS"]))]
    if not video_files:
        if not silent: print("\n[ ERROR ] Tidak ada file video yang ditemukan di folder ini.")
        return None
    if len(video_files) > 1:
        if not silent: print(f"\n[ ERROR ] Ditemukan lebih dari satu file video. Hanya satu yang diizinkan: {', '.join(video_files)}")
        return None
    return video_files[0]

def read_stream_key():
    try:
        with open(CONFIG['KEY_FILENAME'], 'r') as f:
            stream_key = f.read().strip()
        if not stream_key:
            print(f"\n[ ERROR ] File '{CONFIG['KEY_FILENAME']}' ditemukan, tetapi isinya kosong. Harap masukkan kunci streaming Anda.")
            return None
        print(f"   -> Kunci ditemukan: ...{stream_key[-4:]}\n")
        return stream_key
    except FileNotFoundError:
        print(f"\n[ ERROR ] File kunci streaming '{CONFIG['KEY_FILENAME']}' tidak ditemukan.")
        print("          Harap buat file teks dengan nama tersebut dan letakkan kunci streaming Anda di dalamnya.")
        return None
    except Exception as e:
        print(f"\n[ ERROR ] Gagal membaca kunci streaming dari '{CONFIG['KEY_FILENAME']}': {e}")
        return None

def check_ffmpeg_installed():
    print("*. Memeriksa instalasi FFmpeg...")
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        subprocess.run(['ffprobe', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("   -> FFmpeg dan FFprobe terdeteksi.\n")
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("\n[ FATAL ERROR ] FFmpeg atau FFprobe tidak ditemukan di PATH sistem Anda.")
        print("                Harap instal FFmpeg (termasuk FFprobe) dan pastikan itu ditambahkan ke variabel lingkungan PATH Anda.")
        print("                Unduh dari: https://ffmpeg.org/download.html")
        return False
    except Exception as e:
        print(f"\n[ FATAL ERROR ] Terjadi kesalahan saat memeriksa FFmpeg/FFprobe: {e}")
        return False

def get_media_info(filepath):
    video_codec = None
    audio_codec = None
    try:
        result_video = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', filepath],
            capture_output=True, text=True, check=False
        )
        if result_video.returncode == 0:
            video_codec = result_video.stdout.strip()
        else:
            print(f"[WARNING] Tidak dapat mendeteksi codec video: {result_video.stderr.strip()}")

        result_audio = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', filepath],
            capture_output=True, text=True, check=False
        )
        if result_audio.returncode == 0:
            audio_codec = result_audio.stdout.strip()
        else:
            print(f"[WARNING] Tidak dapat mendeteksi codec audio: {result_audio.stderr.strip()}")

        return video_codec, audio_codec
    except FileNotFoundError:
        print("[ERROR] FFprobe tidak ditemukan. Tidak dapat memeriksa codec video/audio.")
        return None, None
    except Exception as e:
        print(f"[ERROR] Gagal mendapatkan info media: {e}")
        return None, None

def print_waktu_lokal():
    hari_indo = {
        'Monday': 'Senin', 'Tuesday': 'Selasa', 'Wednesday': 'Rabu',
        'Thursday': 'Kamis', 'Friday': 'Jumat', 'Saturday': 'Sabtu', 'Sunday': 'Minggu'
    }
    bulan_indo = {
        'January': 'Januari', 'February': 'Februari', 'March': 'Maret',
        'April': 'April', 'May': 'Mei', 'June': 'Juni', 'July': 'Juli',
        'August': 'Agustus', 'September': 'September', 'October': 'Oktober',
        'November': 'November', 'December': 'Desember'
    }

    try:
        zona_waktu = ZoneInfo(CONFIG['TIMEZONE'])
    except ZoneInfoNotFoundError:
        print(f"[ERROR] Zona waktu '{CONFIG['TIMEZONE']}' tidak valid. Menggunakan zona waktu lokal sistem.")
        zona_waktu = datetime.now().astimezone().tzinfo

    waktu_sekarang = datetime.now(zona_waktu)
    nama_hari = hari_indo.get(waktu_sekarang.strftime("%A"), waktu_sekarang.strftime("%A"))
    nama_bulan = bulan_indo.get(waktu_sekarang.strftime("%B"), waktu_sekarang.strftime("%B"))

    waktu_str = (f"{nama_hari}, {waktu_sekarang.day} {nama_bulan} {waktu_sekarang.year} | "
                 f"Pukul {waktu_sekarang.strftime('%H:%M:%S')} {waktu_sekarang.tzname() if waktu_sekarang.tzname() else CONFIG['TIMEZONE']}")
    print(f"Waktu Saat Ini: {waktu_str}\n")

if __name__ == "__main__":
    main()