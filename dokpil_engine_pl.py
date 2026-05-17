"""
dokpil_engine_pl.py — Setup Paket PL (non-tender).

Endpoint setup paket PL (semua pakai kode_paket, BUKAN id_nontender):
  - LDK (persyaratan kualifikasi): POST /dokumennontender/{kode}/ldksubmitbaru
  - Masa Berlaku Penawaran      : POST /dokumennontender/{kode}/masaberlakupenawaransubmit
  - Checklist Dokumen Penawaran : POST /dokumennontender/{kode}/checklistsubmit

JKK PL: TIDAK ada syarat kinerja penyedia bawaan (khusus tender PK).

Upload Dokpil PDF: lihat upload_dokpil_pl.py.
Upload BA Reviu DPP: lihat upload_ba_reviu_pl.py.
KAK/Kontrak/Uraian/Lainnya: tugas PPK (bukan PP), tidak di-handle di sini.
"""
import requests
from bs4 import BeautifulSoup

import spse_browser
from config import SPSE_BASE_URL

BASE = SPSE_BASE_URL.rstrip("/")
HDRS = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://spse.inaproc.id",
    "Referer": BASE + "/admin/pegawai",
}


# ─────────────────────────────────────────────────────────────────────────────
# Helper: ambil form context (CSRF + ckm_id list)
# ─────────────────────────────────────────────────────────────────────────────

def scrap_ldk_context(kode_paket: str) -> dict:
    """
    GET /dokumennontender/{kode}/ldk — scrap CSRF + (chk_id, ckm_id) per syarat.

    Penting: server SPSE butuh `chk_id` VALUE ASLI dari hidden input (BUKAN kosong).
    Kalau chk_id="" → server treat sebagai row baru dan ABAIKAN centang (sehingga
    syarat bawaan tidak tercentang). Plus butuh hidden ijin[N].chk_id juga.
    """
    import re as _re
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        raise RuntimeError("Cookie SPSE kosong.")

    url = f"{BASE}/dokumennontender/{kode_paket}/ldk"
    r = requests.get(url, headers={**HDRS, "Cookie": cookie}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"GET /ldk fail: HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")
    form = None
    for f in soup.find_all("form"):
        if "ldksubmitbaru" in (f.get("action") or ""):
            form = f
            break
    if not form:
        raise RuntimeError("Form ldksubmitbaru tidak ditemukan.")

    csrf_inp = form.find("input", {"name": "authenticityToken"})
    csrf = csrf_inp["value"] if csrf_inp else None

    # Parse hidden chk_id + ckm_id per index berdasar nama field
    # Pattern: syaratAdmin[N].chk_id | syaratAdmin[N].ckm_id | ijin[N].chk_id
    admin_items  = {}  # idx -> {"chk_id": "...", "ckm_id": "..."}
    teknis_items = {}
    ijin_items   = {}  # idx -> chk_id (untuk override ijin existing)

    for inp in form.find_all("input"):
        n = inp.get("name", "")
        v = inp.get("value", "")
        m = _re.match(r"^(syaratAdmin|syaratTeknis|ijin)\[(\d+)\]\.(chk_id|ckm_id)$", n)
        if not m:
            continue
        prefix, idx, field = m.group(1), int(m.group(2)), m.group(3)
        bucket = {"syaratAdmin": admin_items,
                  "syaratTeknis": teknis_items,
                  "ijin": ijin_items}[prefix]
        if prefix == "ijin":
            if field == "chk_id":
                ijin_items[idx] = v
        else:
            bucket.setdefault(idx, {})[field] = v

    # Convert ke list ordered by idx
    def _ordered(items: dict) -> list:
        return [items[k] for k in sorted(items.keys())]

    admin_list  = _ordered(admin_items)   # [{chk_id, ckm_id}, ...]
    teknis_list = _ordered(teknis_items)
    ijin_chk_ids = _ordered(ijin_items)    # [chk_id, ...]

    return {
        "csrf":         csrf,
        "cookie":       cookie,
        "admin_list":   admin_list,       # list of dict {chk_id, ckm_id}
        "teknis_list":  teknis_list,
        "ijin_chk_ids": ijin_chk_ids,     # list of chk_id existing (untuk override)
        # Backward compat (jangan dipakai utk submit yg butuh chk_id):
        "admin_ids":    [d.get("ckm_id", "") for d in admin_list],
        "teknis_ids":   [d.get("ckm_id", "") for d in teknis_list],
        "url_submit":   f"{BASE}/dokumennontender/{kode_paket}/ldksubmitbaru",
        "url_form":     url,
    }


def scrap_checklist_context(kode_paket: str) -> dict:
    """GET /dokumennontender/{kode}/checklist — scrap CSRF + ckm_id checklist dokumen penawaran."""
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        raise RuntimeError("Cookie SPSE kosong.")

    url = f"{BASE}/dokumennontender/{kode_paket}/checklist"
    r = requests.get(url, headers={**HDRS, "Cookie": cookie}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"GET /checklist fail: HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form")
    if not form:
        raise RuntimeError("Form checklist tidak ditemukan.")

    csrf_inp = form.find("input", {"name": "authenticityToken"})
    csrf = csrf_inp["value"] if csrf_inp else None

    # Kumpulkan ckm_id per kategori (admin, syarat=teknis, harga)
    cats = {"admin": [], "syarat": [], "harga": []}
    for cb in form.find_all("input", {"type": "checkbox"}):
        name = cb.get("name", "")
        val = cb.get("value", "")
        if name.startswith("syaratAdmin[") and name.endswith(".ckm_id"):
            cats["admin"].append(val)
        elif name.startswith("syarat[") and name.endswith(".ckm_id"):
            cats["syarat"].append(val)
        elif name.startswith("syaratHarga[") and name.endswith(".ckm_id"):
            cats["harga"].append(val)

    return {
        "csrf":       csrf,
        "cookie":     cookie,
        "admin_ids":  cats["admin"],
        "syarat_ids": cats["syarat"],
        "harga_ids":  cats["harga"],
        "url_submit": f"{BASE}/dokumennontender/{kode_paket}/checklistsubmit",
        "url_form":   url,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Submit LDK (Persyaratan Kualifikasi) — JKK PL
# ─────────────────────────────────────────────────────────────────────────────

def build_izin_usaha_jkk(sbu_baru: str, sbu_lama: str) -> list[dict]:
    """
    2 baris izin usaha standar JKK:
    1. Izin Usaha di bidang Jasa Konsultansi Konstruksi (NIB + Sertifikat Standar KBLI 2017)
    2. Sertifikat Badan Usaha SBU (kualifikasi usaha kecil + SBU baru/lama)

    sbu_baru : "Subklasifikasi RK003 (KBLI 2020) Jasa Rekayasa..."
    sbu_lama : "Subklasifikasi Jasa Desain... (KBLI 2017) RE104"
    """
    if sbu_baru and sbu_lama:
        sbu_kl = f"a) {sbu_baru} atau; b) {sbu_lama}."
    elif sbu_baru:
        sbu_kl = f"{sbu_baru}."
    else:
        sbu_kl = f"{sbu_lama}."

    return [
        {
            "jenis_izin": "Izin Usaha di bidang Jasa Konsultansi Konstruksi",
            "klasifikasi": (
                "Memiliki perizinan berusaha di bidang Jasa Konsultansi Konstruksi. "
                "a) Memiliki Nomor Induk Berusaha (NIB) dan Sertifikat Standar terverifikasi "
                "(untuk Badan Usaha yang memiliki SBU KBLI 2020); "
                "b) Dalam hal Sertifikat Standar sebagaimana dimaksud pada huruf a) belum terverifikasi, "
                "peserta menyampaikan NIB, Sertifikat Standar belum terverifikasi dan tangkapan layar laman OSS "
                "yang mencantumkan bahwa Sertifikat Standar sedang menunggu verifikasi; atau "
                "c) Memiliki Nomor Induk Berusaha (NIB) dan SBU yang masih berlaku "
                "(untuk Badan Usaha yang memiliki SBU KBLI 2017)"
            ),
        },
        {
            "jenis_izin": "Sertifikat Badan Usaha SBU",
            "klasifikasi": (
                "Memiliki Sertifikat Badan Usaha (SBU) Jasa Konsultansi Konstruksi dengan "
                "Kualifikasi Usaha Kecil, serta disyaratkan: " + sbu_kl
            ),
        },
    ]


def submit_ldk_pl(
    kode_paket: str,
    sbu_baru: str = "",
    sbu_lama: str = "",
    centang_admin_all: bool = True,
    teknis_centang_indices: list[int] | None = None,
    izin_extra: list[dict] | None = None,
    kinerja_text: str = "",
) -> dict:
    """
    Submit form LDK PL (JKK).

    JKK PL ckm_id BAWAAN (verified 2026-05-17 PROD):
      - Admin idx 0-4: 251, 70, 72, 73, 74 (Pakta, KSWP, Tempat Usaha, Hukum, Pernyataan)
      - Teknis idx 0-5: 77, 268, 78, 79, 80, 81 (Pengalaman, <3thn, SDM-Manaj, SDM-Ahli, SDM-Teknis, Peralatan)

    DEFAULT BARU (per user 2026-05-17 E2E test):
      - centang_admin_all=True → semua admin tercentang (NPWP/Akta/Pakta auto by sistem)
      - teknis_centang_indices=[0, 1] → HANYA centang Pengalaman + Dispensasi <3thn
        SDM Manajerial/Ahli/Teknis/Peralatan (78/79/80/81) JANGAN dicentang.
      - kinerja_text → tambah custom row "Penilaian Kinerja Penyedia" ckm_id=996

    PENTING: Server butuh `chk_id` VALUE ASLI dari hidden input.
    Kalau dikirim chk_id="" → server abaikan centang (row dianggap baru/orphan).
    """
    ctx = scrap_ldk_context(kode_paket)
    payload = {"authenticityToken": ctx["csrf"]}

    # ── IJIN USAHA ────────────────────────────────────────────────
    # Override 2 ijin existing (chk_id asli) + tambah jika user kasih izin_extra
    izin_list = build_izin_usaha_jkk(sbu_baru, sbu_lama)
    if izin_extra:
        izin_list.extend(izin_extra)

    ijin_existing_ids = ctx.get("ijin_chk_ids", [])
    for i, ij in enumerate(izin_list):
        # Pakai chk_id existing jika ada, else kosong (row baru)
        payload[f"ijin[{i}].chk_id"] = ijin_existing_ids[i] if i < len(ijin_existing_ids) else ""
        payload[f"ijin[{i}].chk_nama"] = ij["jenis_izin"]
        payload[f"ijin[{i}].chk_klasifikasi"] = ij["klasifikasi"]

    # ── SYARAT ADMINISTRASI ───────────────────────────────────────
    # Kirim SEMUA hidden chk_id (wajib agar form lengkap)
    # Centang ckm_id HANYA jika centang_admin_all=True
    for i, item in enumerate(ctx["admin_list"]):
        chk_id = item.get("chk_id", "")
        ckm_id = item.get("ckm_id", "")
        payload[f"syaratAdmin[{i}].chk_id"] = chk_id
        if centang_admin_all:
            payload[f"syaratAdmin[{i}].ckm_id"] = ckm_id
            payload[f"checklist_kualifikasi_administrasi_ckm_id[{i}]"] = ckm_id

    # ── SYARAT TEKNIS ─────────────────────────────────────────────
    # Default centang HANYA idx 0 (77 Pengalaman) + idx 1 (268 Dispensasi <3thn).
    # idx 2-5 (SDM Manajerial/Ahli/Teknis/Peralatan) JANGAN dicentang per user.
    if teknis_centang_indices is None:
        teknis_centang_indices = [0, 1]

    for i, item in enumerate(ctx["teknis_list"]):
        chk_id = item.get("chk_id", "")
        ckm_id = item.get("ckm_id", "")
        payload[f"syaratTeknis[{i}].chk_id"] = chk_id
        if i in teknis_centang_indices:
            payload[f"syaratTeknis[{i}].ckm_id"] = ckm_id
            payload[f"checklist_kualifikasi_teknis_ckm_id[{i}]"] = ckm_id

    # ── KINERJA PENYEDIA (custom row baru) ────────────────────────
    if kinerja_text:
        n = len(ctx["teknis_list"])  # index lanjut setelah bawaan
        payload[f"syaratTeknis[{n}].chk_id"] = ""
        payload[f"syaratTeknis[{n}].ckm_id"] = "996"
        payload[f"checklist_kualifikasi_teknis_ckm_id[{n}]"] = "996"
        payload[f"syaratTeknis[{n}].chk_nama"] = kinerja_text

    r = requests.post(
        ctx["url_submit"],
        data=payload,
        headers={
            **HDRS,
            "Cookie": ctx["cookie"],
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": ctx["url_form"],
        },
        allow_redirects=False,
        timeout=30,
    )

    return {
        "ok":       r.status_code in (200, 302),
        "status":   r.status_code,
        "body":     (r.text or "")[:1500],
        "redirect": r.headers.get("Location", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Submit Masa Berlaku Penawaran
# ─────────────────────────────────────────────────────────────────────────────

def submit_masa_berlaku_pl(kode_paket: str, hari: int = 30) -> dict:
    """POST /dokumennontender/{kode}/masaberlakupenawaransubmit dengan field `masaberlaku`."""
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        raise RuntimeError("Cookie SPSE kosong.")

    url_form = f"{BASE}/dokumennontender/{kode_paket}/masaberlakupenawaran"
    r = requests.get(url_form, headers={**HDRS, "Cookie": cookie}, timeout=15)
    if r.status_code != 200:
        return {"ok": False, "status": r.status_code, "error": "GET form fail"}

    soup = BeautifulSoup(r.text, "html.parser")
    csrf = ""
    csrf_inp = soup.find("input", {"name": "authenticityToken"})
    if csrf_inp:
        csrf = csrf_inp.get("value", "")

    payload = {"authenticityToken": csrf, "masaberlaku": str(hari)}
    rp = requests.post(
        f"{BASE}/dokumennontender/{kode_paket}/masaberlakupenawaransubmit",
        data=payload,
        headers={
            **HDRS, "Cookie": cookie,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": url_form,
        },
        allow_redirects=False, timeout=30,
    )
    return {
        "ok":       rp.status_code in (200, 302),
        "status":   rp.status_code,
        "redirect": rp.headers.get("Location", ""),
        "body":     (rp.text or "")[:1000],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Submit Checklist Dokumen Penawaran
# ─────────────────────────────────────────────────────────────────────────────

def submit_checklist_pl(
    kode_paket: str,
    centang_admin_all: bool = True,
    centang_syarat_all: bool = True,
    centang_harga_all: bool = True,
) -> dict:
    """
    Submit checklist dokumen penawaran.
    JKK ckm_id (verified):
      - Admin: 16 (Masa Berlaku), 18 (Surat Penawaran)
      - Syarat (teknis): 39 (Metodologi), 40 (Pengalaman Perush), 41 (Kualif TA)
      - Harga: 19 (DKH), 31 (AHS), 127 (Remunerasi)
    Default: centang semua.
    """
    ctx = scrap_checklist_context(kode_paket)
    payload = {"authenticityToken": ctx["csrf"]}

    if centang_admin_all:
        for i, cid in enumerate(ctx["admin_ids"]):
            payload[f"syaratAdmin[{i}].chk_id"] = ""
            payload[f"syaratAdmin[{i}].ckm_id"] = cid
    if centang_syarat_all:
        for i, cid in enumerate(ctx["syarat_ids"]):
            payload[f"syarat[{i}].chk_id"] = ""
            payload[f"syarat[{i}].ckm_id"] = cid
    if centang_harga_all:
        for i, cid in enumerate(ctx["harga_ids"]):
            payload[f"syaratHarga[{i}].chk_id"] = ""
            payload[f"syaratHarga[{i}].ckm_id"] = cid

    rp = requests.post(
        ctx["url_submit"],
        data=payload,
        headers={
            **HDRS, "Cookie": ctx["cookie"],
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": ctx["url_form"],
        },
        allow_redirects=False, timeout=30,
    )
    return {
        "ok":       rp.status_code in (200, 302),
        "status":   rp.status_code,
        "redirect": rp.headers.get("Location", ""),
        "body":     (rp.text or "")[:1000],
    }
