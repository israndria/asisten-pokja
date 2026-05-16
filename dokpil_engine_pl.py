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
    """GET /dokumennontender/{kode}/ldk — scrap authenticityToken + ckm_id."""
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

    admin_ids = []
    teknis_ids = []
    for inp in form.find_all("input", type="hidden"):
        n = inp.get("name", "")
        v = inp.get("value", "")
        if n.startswith("checklist_kualifikasi_administrasi_ckm_id"):
            admin_ids.append(v)
        elif n.startswith("checklist_kualifikasi_teknis_ckm_id"):
            teknis_ids.append(v)

    return {
        "csrf":       csrf,
        "cookie":     cookie,
        "admin_ids":  admin_ids,
        "teknis_ids": teknis_ids,
        "url_submit": f"{BASE}/dokumennontender/{kode_paket}/ldksubmitbaru",
        "url_form":   url,
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
    centang_teknis_all: bool = True,
    izin_extra: list[dict] | None = None,
) -> dict:
    """
    Submit form LDK PL (JKK).

    JKK PL ckm_id (verified 2026-05-16 latihan):
      - Admin a-e: 251, 70, 72, 73, 74
      - Teknis a-f: 77, 268, 78, 79, 80, 81
    TIDAK ada syarat kinerja penyedia di JKK PL (khusus tender PK/Konstruksi).
    """
    ctx = scrap_ldk_context(kode_paket)
    payload = {"authenticityToken": ctx["csrf"]}

    # Izin Usaha — 2 baris default JKK
    izin_list = build_izin_usaha_jkk(sbu_baru, sbu_lama)
    if izin_extra:
        izin_list.extend(izin_extra)

    for i, ij in enumerate(izin_list):
        payload[f"ijin[{i}].chk_id"] = ""
        payload[f"ijin[{i}].chk_nama"] = ij["jenis_izin"]
        payload[f"ijin[{i}].chk_klasifikasi"] = ij["klasifikasi"]

    # Syarat Administrasi (default centang semua)
    if centang_admin_all:
        for i, cid in enumerate(ctx["admin_ids"]):
            payload[f"syaratAdmin[{i}].chk_id"] = ""
            payload[f"syaratAdmin[{i}].ckm_id"] = cid
            payload[f"checklist_kualifikasi_administrasi_ckm_id[{i}]"] = cid

    # Syarat Teknis (default centang semua a-f kualifikasi teknis JKK)
    if centang_teknis_all:
        for i, cid in enumerate(ctx["teknis_ids"]):
            payload[f"syaratTeknis[{i}].chk_id"] = ""
            payload[f"syaratTeknis[{i}].ckm_id"] = cid
            payload[f"checklist_kualifikasi_teknis_ckm_id[{i}]"] = cid

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
