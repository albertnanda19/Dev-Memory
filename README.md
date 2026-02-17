# Dev-Memory — Project Context

`dev-memory` adalah CLI tool berbasis Python (standard library only) untuk mengotomasi _daily standup / dev log_ dari aktivitas Git di beberapa repository. Tool ini menghasilkan output harian & bulanan dalam format JSON + Markdown (Bahasa Indonesia), opsional ditambah narasi AI, dan (opsional) mengirimkan hasil daily standup ke Discord.

Dokumen ini berisi gambaran lengkap cara kerja, fitur, struktur file, environment variables, alur eksekusi (cron + startup recovery), dan cara troubleshooting. Cocok untuk diberikan ke AI lain sebagai konteks proyek.

---

## 1) Tujuan Utama

- Mengumpulkan aktivitas development harian (commit + working tree) dari beberapa repo Git.
- Menyimpan data harian (JSON) dan ringkasan harian (Markdown) secara deterministik.
- Menghasilkan ringkasan bulanan dari kumpulan laporan harian.
- (Opsional) Menambahkan narasi AI di layer presentasi (tanpa mempengaruhi data JSON).
- Otomatis berjalan setiap hari via cron (06:00) + fallback saat laptop/device OFF.
- (Opsional) Mengirim Markdown daily standup ke Discord dengan retry + logging.

---

## 2) Gambaran Arsitektur (Layered)

Proyek ini menjaga pemisahan concern agar reliabel dan mudah diobservasi:

1.  **Data Aggregation Layer (pure data)**
    - Mengambil data dari Git dan membentuk model data.
    - Tidak ada AI.
    - Tidak ada logic presentasi.

2.  **Analyzer Layer (rule-based)**
    - Klasifikasi aktivitas secara deterministik (heuristic / rule-based).
    - Tidak ada AI.

3.  **Presentation Layer (Markdown generator)**
    - Mengubah data menjadi Markdown Bahasa Indonesia.
    - Boleh menambah narasi AI (opsional) tetapi tidak mengubah data JSON.

4.  **Execution / Scheduling Layer**
    - Cron job + startup recovery + idempotency.
    - Logging dan metrik durasi.

5.  **Notification Layer (Discord)**
    - Terpisah dari aggregator.
    - Jika error tidak boleh menggagalkan cron/job.

---

## 3) Struktur Folder & Output

### Output harian

- **Daily JSON**: `data/daily/YYYY-MM-DD.json`
- **Daily Markdown**: `data/daily/YYYY-MM-DD.md`

### Output bulanan

- **Monthly JSON**: `data/monthly/YYYY-MM.json`
- **Monthly Markdown**: `data/monthly/YYYY-MM.md`

### State & logs

- **Execution state**: `data/state.json`
  - contoh:
    - `{ "last_daily_execution": "2026-02-12" }`
- **Cron log per hari**: `logs/cron-YYYY-MM-DD.log`
- **Discord log**: `logs/discord.log`

---

## 4) Time Window (Cut-off 06:00) + Monday Rule

Collector menggunakan parameter waktu untuk `git log`:

`git log --since="YYYY-MM-DD HH:MM" --until="YYYY-MM-DD HH:MM"`

### Default (hari biasa)

Window harian:

- **Start**: 06:00 “hari sebelumnya”
- **End**: 05:59 “hari ini”

Contoh:

Jika hari ini `2026-02-13` (Jumat), collect:

- `2026-02-12 06:00 → 2026-02-13 05:59`

### Monday special rule

Jika hari ini **Senin**, collect:

- `Jumat 06:00 → Senin 05:59`

Tujuan:

- Aktivitas larut malam (00:00–05:59) masuk ke “hari sebelumnya”.
- Senin merangkum weekend (Jumat-Sabtu-Minggu sampai Senin pagi sebelum 06:00).

Label file output harian tetap menggunakan `YYYY-MM-DD` = “hari sebelumnya” (contoh: Senin menghasilkan label Minggu).

---

## 5) Data yang Dikumpulkan (Daily)

Collector membaca beberapa repo (paths di `config.py`) dan menghasilkan `DailyReport` (lihat `models.py`).

Ringkasan yang dikumpulkan per repo:

- **Committed summary**
  - `commits_count`
  - `files_changed`, `insertions`, `deletions`
  - `commit_messages`
  - `commit_details`:
    - `hash`, `message`, `files` (list path file yang berubah)

- **Working state**
  - `modified_files`, `untracked_files`
  - insertions/deletions dari:
    - `git diff --shortstat`
    - `git diff --cached --shortstat`

Analyzer (`analyzer.py`) menambahkan:

- `activity_type` (rule-based) per repo.

---

## 6) Markdown Daily (Bahasa Indonesia)

`summarizer.py` menghasilkan Markdown daily yang berisi:

- Judul laporan
- Ringkasan per repo
- Bullet deskriptif dari `commit_details` (deterministik, tidak mengarang)
- Section standup:
  - Hari ini
  - Hambatan

### AI Narrative (opsional)

Jika flag `--ai` dipakai, Markdown akan ditambah:

- `## Ringkasan Naratif AI`

AI hanya presentational layer; jika AI gagal, report tetap dibuat (fail-safe).

---

## 7) Monthly Aggregation

`monthly.py` membaca semua daily JSON dalam bulan tertentu (`YYYY-MM`) lalu membuat:

- monthly aggregated JSON
- monthly Markdown Bahasa Indonesia
- insight produktivitas rule-based

Monthly bisa dijalankan manual:

```bash
python3 main.py --monthly 2026-02
python3 main.py --monthly 2026-02 --ai
```

Monthly juga bisa otomatis dijalankan oleh `run_daily.py` pada “first weekday” awal bulan.

---

## 8) Cara Pakai (CLI)

Entry point: `main.py`

### Generate daily

```bash
python3 main.py
python3 main.py --ai
```

### Generate daily + AI + kirim ke Discord

Command ini akan:

- Generate daily JSON dan daily Markdown seperti `python3 main.py --ai`
- Menambahkan section `## Ringkasan Naratif AI` (jika AI tersedia)
- Mengirim hasil daily standup ke Discord channel (dengan retry + rate limit handling)

```bash
python3 main.py --daily-ai-discord
```

Kebutuhan `.env` (minimal untuk Discord):

- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID`

Opsional untuk mention/ping:

- `DISCORD_USER_ID`

Kebutuhan `.env` untuk AI (opsional):

- `GEMINI_API_KEY`
- `GEMINI_MODEL`

Debugging:

- Log Discord: `logs/discord.log`
- Log proses utama: `logs/cron-YYYY-MM-DD.log`

### Generate monthly

```bash
python3 main.py --monthly YYYY-MM
python3 main.py --monthly YYYY-MM --ai
```

### Install/remove cron

```bash
python3 main.py --install-cron
python3 main.py --remove-cron
```

### Install/remove startup hook (Linux autostart)

```bash
python3 main.py --install-startup
python3 main.py --remove-startup
```

---

## 9) Cron + Startup Recovery (Missed Execution)

### Masalah

Cron tidak berjalan jika device OFF / sleep / hibernate.

### Solusi

1.  **Cron tetap trigger utama**
    - schedule: `0 6 * * 1-5 run_daily.py`

2.  **Startup recovery sebagai fallback**
    - Linux autostart file:
      - `~/.config/autostart/dev-memory.desktop`
    - menjalankan `run_on_startup.py` saat login

3.  **State tracking** untuk mencegah duplicate
    - `data/state.json`

### Idempotency (run_daily.py)

Sebelum generate:

- hitung `report_date` (logical report date)
- jika state menunjukkan sudah executed untuk tanggal itu → exit
- jika file `data/daily/<report_date>.json` sudah ada → exit (dan sinkronkan state)

Setelah daily sukses:

- update `data/state.json`

### run_on_startup.py

- Jika startup terjadi **setelah 06:00** dan report untuk `report_date` belum dibuat → jalankan `run_daily.py`.
- Jika recovery gagal → state tidak di-update.

---

## 10) Logging & Observability

### Logger utama (cron log per hari)

`logger.py` menulis ke:

- `logs/cron-YYYY-MM-DD.log`

Format:

- `[timestamp] [level] [module] message`

`run_daily.py` mencatat:

- start/end
- Python version + working directory
- time window
- durasi daily/monthly/total
- status Discord delivery

### Logger Discord (terpisah)

`discord/discord_client.py` menulis detail ke:

- `logs/discord.log`

Yang dicatat:

- HTTP status code
- latency (ms)
- retry count
- rate limit (429 + retry_after)
- error body preview

---

## 11) Discord Notification Layer

Tujuan: kirim daily standup ke Discord channel tanpa mengganggu cron.

Modul:

- `discord/discord_client.py`
  - HTTP client via `urllib`
  - retry 1x (default) + delay 5 detik
  - rate-limit aware (429 → tunggu `retry_after` → retry 1x)
  - support message biasa atau attachment `.md` (multipart)
  - mendukung mention user via `DISCORD_USER_ID`
  - menggunakan `allowed_mentions` supaya mention benar-benar ping
  - membaca env dari OS dan fallback ke file `.env`

- `discord/send_report.py`
  - validasi markdown exists & non-empty
  - jika konten markdown > 1800 chars → kirim attachment
  - jika <= 1800 chars → kirim message dengan code block
  - follow-up message setelah sukses:
    - `✅ Daily Standup berhasil dibuat dan dikirim pada {timestamp}`

Integrasi:

- `run_daily.py` memanggil `send_daily_standup()` setelah daily sukses dibuat.
- Jika Discord gagal → log warning/error, proses tetap sukses.

---

## 12) Environment Variables (.env)

`.env` berada di project root. Credentials tidak di-hardcode.

### AI

- `GEMINI_API_KEY` (opsional)
- `GEMINI_MODEL` (opsional)
- atau generic:
  - `LLM_API_URL`
  - `LLM_API_KEY`
  - `LLM_MODEL`

### Discord

- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID`
- `DISCORD_USER_ID` (optional, untuk mention/ping)

---

## 13) Quick Troubleshooting

### Daily report tidak terbentuk

- Cek `logs/cron-YYYY-MM-DD.log`
- Pastikan repo paths valid dan repo adalah git repo.

### Cron tidak jalan

- Device OFF/sleep: mengandalkan startup recovery (`run_on_startup.py`).
- Cek crontab: `crontab -l | grep dev-memory`

### Discord tidak terkirim

- Cek `logs/discord.log`
- Kemungkinan:
  - `401` token salah
  - `403` permission bot kurang (Send Messages / Attach Files)
  - `404` channel id salah atau bot tidak bisa akses
  - `429` rate limit (harusnya auto retry)

### AI error

- AI failure tidak memblok data.
- Report tetap dibuat.

---

## 14) Testing

Test suite menggunakan `unittest`.

Run:

```bash
python3 -m unittest -q
```

Test coverage mencakup:

- date range logic (06:00 + Monday rule)
- run_daily behavior
- scheduler idempotency
- Discord delivery (mock): missing token, retry, rate limit, empty file
