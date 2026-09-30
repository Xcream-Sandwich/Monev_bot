# Monev Attendance Bot — Mode Vercel

Bot presensi Monev MagangHub yang di-deploy sebagai Vercel Serverless Functions dengan Telegram Webhook (real-time) dan Vercel Cron untuk peringatan/auto-submit.

> **Versi sebelumnya** (GitHub Actions + polling) masih tersedia di root direktori. Panduan ini khusus untuk mode Vercel.

---

## Prasyarat

- Akun [Vercel](https://vercel.com) (plan Hobby cukup)
- Database [Vercel KV](https://vercel.com/docs/storage/vercel-kv) (Upstash Redis, tier gratis cukup untuk single-user)
- Bot Telegram (buat lewat [@BotFather](https://t.me/BotFather))
- Python 3.11+ (untuk pengembangan dan tes lokal)
- Vercel CLI: `npm i -g vercel`

---

## Struktur Proyek (Mode Vercel)

```
monev-bot/
  api/
    telegram.py          # Webhook handler (real-time command processing)
    cron/
      warn.py            # Cron: peringatan sebelum auto-submit
      submit.py          # Cron: auto-submit jika belum absen
      evening.py         # Cron: pengingat malam hari
  lib/
    config.py            # Baca env vars Vercel
    crypto.py            # Enkripsi Fernet
    kv_store.py          # Wrapper REST Upstash Redis
    monev_auth.py        # Login 4-langkah raw HTTP ke SSO Kemnaker
    monev_api.py         # Cek status & submit presensi
    report.py            # Susun laporan dari poin/template
    telegram_utils.py    # Kirim pesan via Telegram Bot API
  tests/
    test_kv_store.py
    test_telegram_handler.py
    test_report_vercel.py
  vercel.json
  requirements-vercel.txt
  README-vercel.md       # Dokumen ini
```

---

## Setup: Vercel KV

1. Buka [Vercel Dashboard](https://vercel.com/dashboard) → pilih project → **Storage**.
2. Klik **Create Database** → pilih **KV (Redis)**.
3. Ikuti wizard, beri nama database (contoh: `monev-kv`).
4. Setelah dibuat, klik **Connect to Project**.
5. Vercel otomatis mengisi env vars `KV_REST_API_URL` dan `KV_REST_API_TOKEN` di project settings.

> **Kapasitas plan Hobby:** Cek [dokumentasi Upstash/Vercel](https://vercel.com/docs/storage/vercel-kv/limits) untuk batas terkini (bisa berubah). Untuk single-user dengan TTL otomatis, tier gratis biasanya cukup.

---

## Setup: Environment Variables

Buka **Vercel Dashboard → Project → Settings → Environment Variables**, tambahkan:

| Variable | Keterangan |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token bot dari @BotFather |
| `TELEGRAM_CHAT_ID` | ID Telegram Anda (cari lewat @userinfobot) |
| `TELEGRAM_WEBHOOK_SECRET` | String acak (min. 32 karakter), dicocokkan dengan header webhook Telegram |
| `CRON_SECRET` | String acak lain; Vercel kirim ini otomatis ke endpoint cron resmi |
| `ENCRYPTION_KEY` | Kunci Fernet (generate dengan `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")` |
| `GROQ_API_KEY` | *(Opsional)* API key Groq untuk laporan berbasis AI |
| `KV_REST_API_URL` | Otomatis terisi saat KV dihubungkan ke project |
| `KV_REST_API_TOKEN` | Otomatis terisi saat KV dihubungkan ke project |
| `WARN_AFTER` | Jam peringatan WIB (default: `16:00`) |
| `SUBMIT_AFTER` | Jam auto-submit WIB (default: `17:00`) |
| `OFF_DAYS` | Hari libur mingguan (default: `Saturday,Sunday`) |
| `AUTO_SUBMIT` | `true` atau `false` (default: `true`) |
| `TEMPLATES_JSON` | *(Opsional)* Isi templates.json sebagai string JSON |

> **Keamanan:** Jangan pernah commit nilai env var ke repository. Gunakan Vercel Dashboard atau CLI untuk mengaturnya.

---

## Deploy

```bash
# Login ke Vercel
vercel login

# Deploy (dari root direktori proyek)
vercel --prod
```

Catat URL project Anda (contoh: `https://monev-bot-abc123.vercel.app`).

---

## Setup Webhook Telegram

> ⚠️ **Lakukan ini SEKALI setelah deploy.** Jangan dijalankan dari kode aplikasi.

**Langkah 1:** Matikan semua mode polling lama (bot lokal, GitHub Actions polling) dan hapus webhook lama:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/deleteWebhook"
```

**Langkah 2:** Daftarkan webhook baru:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<project>.vercel.app/api/telegram" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

Ganti `<TELEGRAM_BOT_TOKEN>`, `<project>`, dan `<TELEGRAM_WEBHOOK_SECRET>` dengan nilai aktual.

**Verifikasi webhook:**
```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

> ⚠️ **Penting:** Dua mode tidak boleh aktif bersamaan dengan token yang sama. Pastikan bot polling lama sudah dimatikan sebelum `setWebhook`.

---

## Perintah Telegram

| Perintah | Fungsi |
|---|---|
| `/start` | Tampilkan daftar perintah |
| `/daftar` | Daftarkan akun Monev (2 langkah: email → password) |
| `/batal` | Batalkan proses pendaftaran |
| `/cek` | Cek status presensi hari ini |
| `/poin <teks>` | Tambah poin aktivitas hari ini |
| `/lihatpoin` | Lihat semua poin yang sudah ditambahkan |
| `/preview` | Pratinjau laporan yang akan dikirim |
| `/submit` | Kirim laporan sekarang |
| `/auto on\|off` | Aktifkan/nonaktifkan auto-submit |
| `/tunda` | Tunda auto-submit hari ini (submit manual via /submit) |

---

## Jadwal Cron (vercel.json)

| Endpoint | Jadwal UTC | Waktu WIB | Fungsi |
|---|---|---|---|
| `/api/cron/warn` | `0 9 * * 1-5` | 16:00 WIB | Peringatan sebelum auto-submit |
| `/api/cron/submit` | `0 10 * * 1-5` | 17:00 WIB | Auto-submit jika belum absen |
| `/api/cron/evening` | `0 12 * * 1-5` | 19:00 WIB | Pengingat malam hari |

> **Catatan penting:** Presisi jadwal Cron Vercel plan Hobby **tidak dijamin ke menit** — bisa meleset beberapa menit, mirip GitHub Actions. Ini bukan bug, ini batasan platform. Jika presisi penting, gunakan trigger manual (lihat bawah).

> **Batasan plan Hobby:** Jumlah eksekusi cron per bulan dan durasi maksimum function bisa berubah. Selalu cek [dokumentasi Vercel terbaru](https://vercel.com/docs/cron-jobs/manage-cron-jobs) sebelum setup.

---

## Trigger Manual (Cadangan)

Jika jadwal cron meleset atau perlu dijalankan manual:

```bash
# Trigger warn cron manual
curl -H "Authorization: Bearer <CRON_SECRET>" \
  "https://<project>.vercel.app/api/cron/warn"

# Trigger submit cron manual
curl -H "Authorization: Bearer <CRON_SECRET>" \
  "https://<project>.vercel.app/api/cron/submit"

# Trigger evening cron manual
curl -H "Authorization: Bearer <CRON_SECRET>" \
  "https://<project>.vercel.app/api/cron/evening"
```

---

## Cara Uji Manual Setelah Deploy

### 1. Uji Webhook Secret
```bash
# Harus mengembalikan 403 Forbidden
curl -X POST "https://<project>.vercel.app/api/telegram" \
  -H "Content-Type: application/json" \
  -d '{"message": {"text": "/start"}}'

# Harus mengembalikan 200 (dengan secret yang benar)
curl -X POST "https://<project>.vercel.app/api/telegram" \
  -H "X-Telegram-Bot-Api-Secret-Token: <TELEGRAM_WEBHOOK_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{"message": {"from": {"id": <TELEGRAM_CHAT_ID>}, "chat": {"id": <TELEGRAM_CHAT_ID>}, "message_id": 1, "text": "/start"}}'
```

### 2. Uji Koneksi ke Monev (WAJIB sebelum aktifkan cron)

> ⚠️ **Login dan submit ke Monev asli tidak bisa diuji otomatis.** Harus diuji manual setelah deploy.

**Langkah pengujian:**
1. Kirim `/daftar` ke bot via Telegram → masukkan email dan password Monev.
2. Kirim `/cek` → verifikasi bot bisa membaca status dari Monev.
3. Jalankan warn cron manual sekali:
   ```bash
   curl -H "Authorization: Bearer <CRON_SECRET>" "https://<project>.vercel.app/api/cron/warn"
   ```
4. Cek apakah notifikasi masuk ke Telegram dan tidak ada error di Vercel Logs.

> **Catatan:** IP Vercel **mungkin** berbeda reputasinya dibanding IP Azure (GitHub Actions) di mata Cloudflare, tapi **ini tidak dijamin** bisa melewati blokir. Wajib diuji sebelum mengandalkan bot ini untuk presensi harian.

### 3. Uji Cron Secret
```bash
# Harus mengembalikan 401
curl -H "Authorization: Bearer WRONG_SECRET" \
  "https://<project>.vercel.app/api/cron/submit"
```

---

## Tes Lokal

```bash
# Install dependencies (lokal)
pip install -r requirements-vercel.txt

# Jalankan semua tes
pytest tests/test_kv_store.py tests/test_telegram_handler.py tests/test_report_vercel.py -v
```

Semua tes berjalan tanpa koneksi ke Vercel, Monev, atau Telegram.

---

## Keamanan

- **Webhook secret wajib:** Tanpa cek `secret_token`, siapa pun bisa mengirim payload palsu ke `/api/telegram`.
- **Cron secret wajib:** Endpoint cron publik by default (serverless). Tanpa `CRON_SECRET`, siapa pun bisa trigger submit.
- **Whitelist sender:** Bot hanya merespons pesan dari `TELEGRAM_CHAT_ID`. Pengirim lain diabaikan sepenuhnya.
- **Enkripsi at-rest:** Password dan token dienkripsi Fernet sebelum disimpan ke KV.
- **Tidak ada data sensitif di log:** Password, token, cookie, dan isi laporan tidak pernah dicetak ke Vercel Logs.
- **Hapus pesan password:** Pesan Telegram yang berisi password otomatis dihapus (`deleteMessage`) setelah diproses.

---

## Batasan yang Harus Diketahui

1. **Login/submit ke Monev asli tidak bisa diuji otomatis** — harus diuji manual setelah deploy.
2. **IP Vercel bisa saja diblokir Cloudflare** — ini bukan jaminan solusi, hanya alternatif yang layak dicoba.
3. **Presisi cron plan Hobby tidak dijamin ke menit** — sediakan trigger manual sebagai cadangan.
4. **Batas invocation/bulan plan Hobby bisa berubah** — cek dokumentasi Vercel saat setup.
5. **Timeout function Vercel** — login 4-langkah + submit harus selesai dalam `maxDuration` yang dikonfigurasi (default 30 detik untuk cron). Kalau mendekati limit, pertimbangkan upgrade plan.
6. **Serverless stateless** — tidak ada disk persisten. Semua state ada di KV. Jika KV down, bot tidak berfungsi sampai KV kembali normal.
