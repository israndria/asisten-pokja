# Asisten Pokja

A full-stack Streamlit automation app for Indonesian government procurement working groups (*Kelompok Kerja / Pokja*). Automates the entire procurement lifecycle on SPSE (Sistem Pengadaan Secara Elektronik) — from drafting packages to uploading final procurement documents.

Built for procurement officers operating under Indonesian law (Perpres 16/2018 jo. 12/2021 jo. 46/2025). Every step that used to require manual clicks on the government portal can now be done in bulk with one button.

## What It Does

Two complete procurement workflows, each fully automated end-to-end:

### Tender (Lelang)

| Tab | Feature |
|---|---|
| 0 — Draft Paket | Import DPA budget data, create tender package drafts |
| 1 — Undangan DPP | Bulk-send invitation messages to pre-qualified vendors |
| 2 — Jadwal | Auto-create tender schedule on SPSE portal |
| 3 — Setup Paket | Create local folder structure + link Word/Excel templates |
| 4 — Penjelasan | Automate aanwijzing (pre-bid meeting) Q&A |
| 5 — Cetak BA | Upload and print 5 official procurement minutes (*Berita Acara*) |
| 6 — Kualifikasi | Bulk-download vendor qualification documents |
| 7 — Penawaran | Extract encrypted bid files (Apendo) + parse technical documents |

### Pengadaan Langsung / PL (Direct Procurement)

| Tab | Feature |
|---|---|
| 0 — Import DPA | Import budget allocation data |
| 1 — Draft Paket PL | Create direct procurement package drafts with auto vendor matching |
| 2 — Undangan | Send vendor invitations via SPSE |
| 3 — Jadwal | Auto-create PL schedule (5-stage) on SPSE |
| 4 — Setup Paket | Folder creation + template relinking |
| 5 — Kualifikasi | Download + parse vendor qualification PDFs (SBU, personnel, equipment) |
| 6 — Evaluasi | Bulk admin/technical/qualification evaluation with auto KSWP check + SIKaP confirmation |
| 7 — Verifikasi | Send verification requests to vendors |
| 8 — Upload BA | Auto-generate and upload official procurement minutes to SPSE |

## Key Technical Features

- **Chrome CDP integration** — drives an already-logged-in Chrome session via DevTools Protocol; no credential storage needed
- **COM automation** — reads/writes Excel workbooks and merges Word templates directly via `win32com`
- **Supabase backend** — stores package data, vendor identities, SBU classifications, and evaluation results
- **PDF parsing** — extracts vendor qualification data (SBU certificates, personnel CVs, equipment lists) from uploaded PDFs using `pdfplumber`
- **Bulk operations** — all tabs support selecting multiple packages and running actions in batch
- **Live vendor monitoring** — tracks registered vendors in real-time during tender registration period via CDP
- **Google Calendar sync** — procurement schedules synced automatically

## Architecture

```
Chrome (logged-in SPSE session)
  ↕ CDP port 9222
Playwright / requests + cookies
  ↕
app.py (Streamlit UI)
  ├── *_engine.py       # business logic per feature
  ├── *_parser.py       # PDF/HTML data extraction
  ├── input_ba_engine.py # COM writer → Excel "0. Input BA"
  ├── merge_engine.py   # COM driver → Word mail merge → PDF
  └── Supabase          # persistent storage
```

## Requirements

- Windows only (COM automation requires Excel + Word)
- Python 3.10+
- Google Chrome with active SPSE login session
- Microsoft Excel + Word installed
- Supabase project (for data storage)

```bash
pip install streamlit playwright pdfplumber supabase openpyxl python-docx requests pypdf
playwright install chromium
```

## Running

```bash
streamlit run app.py
# Runs on http://localhost:8502
```

Requires Chrome open and logged in to your SPSE instance before launching.

## Context

Indonesia processes **IDR 800+ trillion (~$50B USD)** in government procurement annually. Each package — whether a full tender or direct procurement — requires 10–20 manual steps on the SPSE portal, plus generating multiple legally-mandated documents. Procurement officers across hundreds of agencies do all of this by hand.

This tool automates that entire workflow, handling everything from the first vendor invitation to the final uploaded procurement minutes — turning a multi-day process into hours.

## License

MIT
