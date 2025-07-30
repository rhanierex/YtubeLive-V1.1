#!/bin/bash

# Navigasi ke direktori proyek Anda
# GUNAKAN PATH ABSOLUT YANG ANDA DAPATKAN DARI 'pwd' DI SINI!
cd /root/YtubeLive # Contoh: cd /root/YtubeLive

# Aktifkan virtual environment
source venv/bin/activate

# Jalankan script bot Python
python telegram_bot.py

# Deaktivasi virtual environment (opsional)
deactivate
