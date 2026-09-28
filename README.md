# Monev Attendance Bot (Telegram & GitHub Actions)

Bot personal (single-user) berbasis Python 3.11+ untuk otomatisasi presensi dan penyusunan laporan harian magang di portal **Monev MagangHub Kemnaker** (`monev.maganghub.kemnaker.go.id`).

Bot ini mendukung **dua mode operasional**:
1. 🚀 **Mode GitHub Actions (Serverless / Tanpa Server)**: Berjalan otomatis via GitHub Actions cron tanpa butuh VPS/laptop menyala terus.
2. 💻 **Mode Polling (Self-Hosted / VPS)**: Bot interaktif yang hidup terus dan merespons perintah Telegram secara instan.

---

## 🌟 Fitur Utama

- **Pencatatan Poin Kegiatan dari Chat:** Kirim `/poin <kegiatan>` dari Telegram saat jam pulang magang.
- **Penyusunan Laporan Cerdas (3 Bagian):**
  - **Ada poin:** Disusun menggunakan Groq AI (`llama-3.3-70b-versatile`) jika `GROQ_API_KEY` tersedia, atau generator lokal otomatis.
  - **Tanpa poin:** Memilih template secara acak dari template buatan pengguna (Prioritas: Nama Hari `Monday`..`Sunday` $\to$ `default` $\to$ bawaan).
  - **Penjaminan Panjang Karakter:** Setiap bagian (*Aktivitas*, *Pembelajaran*, *Kendala*) dijamin memiliki panjang $\ge 100$ karakter.
- **Jadwal Otomatis & Jaring Pengaman:**
  - Peringatan di `WARN_AFTER` (default 17:15 WIB) jika belum presensi.
  - Auto-submit di `SUBMIT_AFTER` (default 17:45 WIB) setelah verifikasi ulang ke portal Monev.
  - Dukungan `/tunda` untuk membatalkan pengiriman otomatis hari berjalan, dan `/lanjut` untuk mengaktifkannya kembali.
- **Dukungan Hari Libur (`OFF_DAYS`):** Tidak ada pengiriman di hari libur mingguan (default `Saturday,Sunday`) maupun hari libur nasional dari portal Monev.
- **Keamanan Ketat:**
  - Login raw HTTP 4-langkah SSO Kemnaker tanpa browser (tanpa Selenium/Playwright).
  - **Log Aman:** Log runner pada GitHub Actions tidak pernah mencetak password, token, email, chat ID, poin kegiatan, atau isi laporan ke publik.

---

## 🚀 Mode 1: GitHub Actions (Serverless / Tanpa Server)

Mode ini sangat direkomendasikan jika Anda tidak memiliki VPS atau tidak ingin membiarkan laptop menyala terus.

### 1. Buat Repositori GitHub
- Buat repositori baru di GitHub (Bisa **Private** atau **Public**).
- Unggah/push kode proyek `monev-bot` ke repositori Anda.

### 2. Atur GitHub Secrets
Buka **Settings** $\to$ **Secrets and variables** $\to$ **Actions** $\to$ **New repository secret**:

| Nama Secret | Isi / Keterangan |
|---|---|
| `MONEV_EMAIL` | Email akun Kemnaker / MagangHub Anda |
| `MONEV_PASSWORD` | Password akun Kemnaker Anda |
| `TELEGRAM_BOT_TOKEN` | Token bot dari [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | ID Telegram Anda (dapatkan via [@userinfobot](https://t.me/userinfobot)) |
| `GROQ_API_KEY` | *(Opsional)* API Key dari Groq untuk penyusunan laporan berbasis AI |
| `TEMPLATES_JSON` | *(Opsional)* Isi JSON template laporan Anda (format sama dengan `templates.json.example`) |

### 3. Atur Repository Variables (Opsional)
Buka tab **Variables** pada menu yang sama jika ingin mengubah pengaturan default:
- `WARN_AFTER`: Waktu kirim peringatan sore WIB (default: `17:15`)
- `SUBMIT_AFTER`: Waktu eksekusi auto-submit WIB (default: `17:45`)
- `OFF_DAYS`: Hari libur mingguan (default: `Saturday,Sunday`)
- `AUTO_SUBMIT`: Status auto-submit (default: `true`)
- `DRY_RUN`: Simulasi tanpa POST submit (default: `false`)

### 4. Bersihkan Webhook & Matikan Polling Lama
Pastikan tidak ada proses polling lain (misal script di laptop) yang berjalan dengan token bot yang sama.
Pastikan juga webhook Telegram dinonaktifkan dengan membuka URL berikut di browser Anda:
```
https://api.telegram.org/bot<TOKEN_BOT_ANDA>/deleteWebhook
```

### 5. Uji Coba Manual (Workflow Dispatch)
1. Buka tab **Actions** di repositori GitHub Anda.
2. Pilih workflow **Monev Attendance Runner**.
3. Klik **Run workflow**:
   - Pilih mode **`check`**: Untuk menguji login SSO Kemnaker dari runner GitHub dan memeriksa status presensi hari ini.
   - Pilih mode **`preview`**: Untuk melihat draf laporan yang akan di-generate hari ini.
   - Pilih centang **`dry_run`**: Untuk simulasi alur submit lengkap tanpa benar-benar mengirim data ke Monev.
   - Pilih mode **`submit`**: Untuk mengirim laporan presensi langsung ke Monev saat itu juga (bisa digunakan via aplikasi GitHub di HP jika jadwal terlambat).

---

## 💻 Mode 2: Polling (Self-Hosted / VPS)

Jika Anda ingin bot merespons perintah Telegram secara real-time dan hidup di VPS/laptop:

1. Salin `.env.example` ke `.env` dan isi variabelnya:
   ```bash
   TELEGRAM_BOT_TOKEN=...
   ENCRYPTION_KEY=...    # Dapatkan via: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. Jalankan bot:
   ```bash
   python bot.py
   ```
3. Di Telegram, gunakan `/daftar` untuk mendaftarkan akun Monev Anda secara interaktif.

---

## 📱 Daftar Perintah Telegram

| Perintah | Fungsi |
|---|---|
| `/poin <teks>` | Menambahkan satu butir kegiatan harian |
| `/preview` | Melihat draf laporan 3 bagian hari ini |
| `/status` | Melihat status presensi, hari libur, dan rencana auto-submit |
| `/submit` | Mengirim laporan presensi sekarang |
| `/tunda` | Membatalkan auto-submit khusus untuk hari ini |
| `/lanjut` | Mengaktifkan kembali auto-submit jika sebelumnya ditunda |

> **Catatan untuk Mode GitHub Actions:** Pesan dan poin disimpan dalam antrean pesan Telegram (`getUpdates` tanpa offset). Perintah Anda akan dibaca dan dieksekusi pada saat jadwal GitHub Actions berjalan berikutnya.

---

## 🧪 Menjalankan Unit Test

Proyek dilengkapi dengan 32 unit test otomatis (pytest) yang mencakup logika keputusan waktu, seleksi template, alur HTTP mock, filter pesan inbox, dan verifikasi keamanan log:

```bash
pytest -v
```

---

## ⚠️ Batasan & Tips

1. **Jadwal GitHub Actions Bersifat Best-Effort:** Jadwal cron di GitHub Actions gratis terkadang bisa mengalami delay beberapa menit. Karena itu, workflow dijadwalkan berjalan berulang kali di rentang 16:50–19:00 WIB untuk memastikan tugas terselesaikan.
2. **IP Datacenter:** IP runner GitHub Actions berada di luar negeri. Selalu uji koneksi pertama kali dengan mode `check` untuk memastikan akun Anda tidak diblokir oleh sistem Kemnaker.
3. **Keepalive Otomatis:** Workflow sudah dilengkapi langkah otomatis untuk menjaga repositori tetap aktif sehingga cron schedule tidak dinonaktifkan oleh GitHub setelah 60 hari.
