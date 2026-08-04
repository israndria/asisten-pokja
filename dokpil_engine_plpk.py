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
import re as _re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

import spse_browser
from config import SPSE_BASE_URL

BASE = SPSE_BASE_URL.rstrip("/")
HDRS = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://spse.inaproc.id",
    "Referer": BASE + "/admin/pegawai",
}


def _http_post_result(response, operation: str) -> dict:
    """Normalize POST result and reject login-page false-success."""
    status = getattr(response, "status_code", 0)
    redirect = str(getattr(response, "headers", {}).get("Location", "") or "")
    body = str(getattr(response, "text", "") or "")
    probe = f"{redirect}\n{body[:8000]}".lower()
    login_page = (
        "login" in redirect.lower()
        or bool(_re.search(r"<title[^>]*>[^<]*(login|masuk)", body, _re.I))
        or bool(_re.search(r"(?:name|id)=[\"'](?:username|j_username|password)[\"']", body, _re.I))
        or "j_spring_security_check" in probe
    )
    ok_status = status in (200, 302)
    return {
        "ok": bool(ok_status and not login_page),
        "status": status,
        "redirect": redirect,
        "body": body[:1500],
        **({"error": f"{operation}: sesi SPSE mengembalikan halaman login."} if login_page else {}),
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
    hidden_fields = {}
    checked_admin_ids = []
    checked_teknis_ids = []

    for inp in form.find_all("input"):
        n = inp.get("name", "")
        v = inp.get("value", "")
        if inp.get("type") == "hidden" and n and n != "authenticityToken":
            hidden_fields[n] = v
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
            if field == "ckm_id" and inp.has_attr("checked"):
                if prefix == "syaratAdmin":
                    checked_admin_ids.append(v)
                elif prefix == "syaratTeknis":
                    checked_teknis_ids.append(v)

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
        "ijin_rows":    ijin_items,       # index -> chk_id; row baru bisa tidak punya chk_id
        "hidden_fields": hidden_fields,   # hidden native form, termasuk number1 + checklist_* semua row
        # Backward compat (jangan dipakai utk submit yg butuh chk_id):
        "admin_ids":    [d.get("ckm_id", "") for d in admin_list],
        "teknis_ids":   [d.get("ckm_id", "") for d in teknis_list],
        "checked_admin_ids": checked_admin_ids,
        "checked_teknis_ids": checked_teknis_ids,
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

    # Parse pasangan chk_id + ckm_id per index per kategori
    admin_map  = {}
    syarat_map = {}
    harga_map  = {}
    disabled_ckm_ids = set()
    checked_ckm_ids = set()

    for inp in form.find_all("input"):
        name = inp.get("name", "")
        val  = inp.get("value", "") or ""
        m = _re.match(r"^(syaratAdmin|syarat|syaratHarga)\[(\d+)\]\.(chk_id|ckm_id)$", name)
        if not m:
            continue
        prefix, idx, field = m.group(1), int(m.group(2)), m.group(3)
        bucket = {"syaratAdmin": admin_map, "syarat": syarat_map, "syaratHarga": harga_map}[prefix]
        bucket.setdefault(idx, {"chk_id": "", "ckm_id": ""})[field] = val
        if field == "ckm_id" and inp.get("type") == "checkbox":
            if inp.has_attr("disabled"):
                disabled_ckm_ids.add(val)
            if inp.has_attr("checked"):
                checked_ckm_ids.add(val)

    if not csrf:
        raise RuntimeError("Form checklist tidak memiliki authenticityToken; sesi SPSE mungkin sudah kedaluwarsa.")

    def _ol(d):
        return [d[k] for k in sorted(d)]

    admin_items  = _ol(admin_map)
    syarat_items = _ol(syarat_map)
    harga_items  = _ol(harga_map)

    return {
        "csrf":         csrf,
        "cookie":       cookie,
        "admin_items":  admin_items,
        "syarat_items": syarat_items,
        "harga_items":  harga_items,
        "disabled_ckm_ids": disabled_ckm_ids,
        "checked_ckm_ids": checked_ckm_ids,
        # Backward compat:
        "admin_ids":    [d["ckm_id"] for d in admin_items],
        "syarat_ids":   [d["ckm_id"] for d in syarat_items],
        "harga_ids":    [d["ckm_id"] for d in harga_items],
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
                "yang mencantumkan bahwa Sertifikat Standar sedang menunggu verifikasi"
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


def update_ijin_sbu_via_http(
    kode_paket: str,
    ijin_idx: int,
    klas_baru: str,
    base_url: str = "",
    cookie: str = "",
) -> dict:
    """Update klasifikasi izin SBU dengan submit form LDK via HTTP langsung.

    Form dibaca ulang agar ``chk_id`` dan seluruh hidden/native fields tetap
    mengikuti state SPSE terbaru. Jalur ini sengaja tidak memakai browser/CDP.
    """
    from config import SPSE_BASE_URL

    base = (base_url or SPSE_BASE_URL).rstrip("/") + "/"
    cookie = cookie or spse_browser.get_spse_cookies()
    if not cookie:
        return {"ok": False, "error": "Cookie SPSE kosong."}

    url_form = f"{base}dokumennontender/{kode_paket}/ldk"
    headers = {**HDRS, "Cookie": cookie}
    rg = requests.get(url_form, headers=headers, timeout=20)
    if rg.status_code != 200:
        return {"ok": False, "status": rg.status_code, "error": "GET form LDK gagal."}

    soup = BeautifulSoup(rg.text, "html.parser")
    form = next(
        (f for f in soup.find_all("form") if "ldksubmitbaru" in (f.get("action") or "")),
        None,
    )
    if form is None:
        return {"ok": False, "error": "Form ldksubmitbaru tidak ditemukan."}

    payload = {}
    for field in form.find_all(["input", "textarea", "select"]):
        name = field.get("name")
        if not name:
            continue
        kind = (field.get("type") or "text").lower()
        if kind in {"submit", "button", "file", "reset"}:
            continue
        if kind in {"checkbox", "radio"} and not field.has_attr("checked"):
            continue
        if field.name == "select":
            option = field.find("option", selected=True) or field.find("option")
            value = option.get("value", "") if option else ""
        else:
            value = field.get("value", "")
        payload[name] = value

    csrf = form.find("input", {"name": "authenticityToken"})
    if csrf is None or not csrf.get("value", "").strip():
        return {"ok": False, "status": 200, "error": "CSRF form LDK kosong."}
    payload["authenticityToken"] = csrf.get("value", "").strip()
    payload[f"ijin[{ijin_idx}].chk_klasifikasi"] = klas_baru

    action = form.get("action") or f"dokumennontender/{kode_paket}/ldksubmitbaru"
    url_submit = urljoin(url_form, action)
    rp = requests.post(
        url_submit,
        data=payload,
        headers={
            **HDRS,
            "Cookie": cookie,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": url_form,
        },
        allow_redirects=False,
        timeout=30,
    )
    return _http_post_result(rp, "Update SBU")


def submit_ldk_pl(
    kode_paket: str,
    sbu_baru: str = "",
    sbu_lama: str = "",
    centang_admin_ckm_ids: list[str] | None = None,
    teknis_centang_ckm_ids: list[str] | None = None,
    izin_extra: list[dict] | None = None,
    kinerja_text: str = "",
    base_url: str = "",
) -> dict:
    """
    Submit form LDK PLPK dengan ID checklist dari form live SPSE.

    Struktur live PLPK konstruksi yang diverifikasi via CDP:
      - Admin: 401–404 (default inti), 410–411 (opsional)
      - Teknis: 437–441; pilihan UI paket ini 437/438/439
      - kinerja_text: tambah row resmi via struktur native ckm_id=996

    UPDATE ijin[1] klasifikasi:
      Jika sbu_lama="" dan ijin[1] sudah ada di SPSE (chk_id asli), form LDK
      dibaca ulang lalu dikirim ulang via HTTP langsung agar klasifikasi SBU
      mengikuti nilai terbaru.

    PENTING: Server butuh chk_id VALUE ASLI dari hidden input.
    Kalau chk_id="" → server abaikan centang (row dianggap baru/orphan).
    """
    from config import SPSE_BASE_URL
    _base = (base_url or SPSE_BASE_URL).rstrip("/") + "/"

    ctx = scrap_ldk_context(kode_paket)
    if not str(ctx.get("csrf") or "").strip():
        return {"ok": False, "status": 200, "error": "CSRF form LDK kosong."}
    # Mulai dari hidden fields native SPSE. Jangan hanya mengirim row yang dicentang:
    # server membutuhkan checklist_kualifikasi_* untuk seluruh row dan number1.
    payload = dict(ctx.get("hidden_fields", {}))
    payload["authenticityToken"] = ctx["csrf"]

    # ── IJIN USAHA ────────────────────────────────────────────────
    # Struktur izin PLPK berbeda dari JKK. Jangan mengirim label jasa
    # konsultansi ke paket pekerjaan konstruksi.
    izin_text = (
        "Memiliki izin berusaha di bidang Jasa Pekerjaan Konstruksi; "
        "a) Memiliki Nomor Induk Berusaha (NIB) dan Sertifikat Standar terverifikasi; "
        "b) Dalam hal Sertifikat Standar sebagaimana dimaksud pada huruf a) belum "
        "terverifikasi, peserta menyampaikan NIB, Sertifikat Standar belum terverifikasi "
        "dan tangkapan layar laman OSS yang mencantumkan bahwa Sertifikat Standar sedang "
        "menunggu verifikasi;"
    )
    sbu_text = sbu_baru or sbu_lama or ""
    izin_list = [
        {
            "jenis_izin": "Izin Usaha di bidang Jasa Pekerjaan Konstruksi",
            "klasifikasi": izin_text,
        },
        {
            "jenis_izin": "Sertifikat Badan Usaha SBU",
            "klasifikasi": sbu_text,
        },
    ]
    if izin_extra:
        izin_list.extend(izin_extra)

    ijin_rows = ctx.get("ijin_rows", {})
    # Simpan daftar ID asli untuk menentukan apakah baris SBU lama memang
    # sudah ada di SPSE. Tanpa assignment ini jalur SBU Custom baru meledak
    # setelah POST sukses dengan NameError, sehingga seluruh paket dilaporkan
    # gagal walaupun payload utama sudah terkirim.
    ijin_existing_ids = ctx.get("ijin_chk_ids", [])
    for i, ij in enumerate(izin_list):
        # Row existing punya hidden chk_id; row hasil tombol Tambah Izin tidak.
        if i in ijin_rows:
            payload[f"ijin[{i}].chk_id"] = ijin_rows[i]
        payload[f"ijin[{i}].chk_nama"] = ij["jenis_izin"]
        payload[f"ijin[{i}].chk_klasifikasi"] = ij["klasifikasi"]

    # ── SYARAT ADMINISTRASI ───────────────────────────────────────
    valid_admin = {str(x.get("ckm_id", "")) for x in ctx["admin_list"]}
    requested_admin = {str(x) for x in (centang_admin_ckm_ids or [])}
    if not requested_admin & valid_admin:
        centang_admin_ckm_ids = ctx.get("checked_admin_ids") or [
            str(x.get("ckm_id")) for x in ctx["admin_list"][:4]
        ]
    else:
        centang_admin_ckm_ids = [str(x) for x in requested_admin if str(x) in valid_admin]

    for i, item in enumerate(ctx["admin_list"]):
        chk_id = item.get("chk_id", "")
        ckm_id = str(item.get("ckm_id", ""))
        payload[f"syaratAdmin[{i}].chk_id"] = chk_id
        if ckm_id in centang_admin_ckm_ids:
            payload[f"syaratAdmin[{i}].ckm_id"] = ckm_id
            payload[f"checklist_kualifikasi_administrasi_ckm_id[{i}]"] = ckm_id

    # ── SYARAT TEKNIS ─────────────────────────────────────────────
    valid_teknis = {str(x.get("ckm_id", "")) for x in ctx["teknis_list"]}
    requested_teknis = {str(x) for x in (teknis_centang_ckm_ids or [])}
    if not requested_teknis & valid_teknis:
        teknis_centang_ckm_ids = ctx.get("checked_teknis_ids") or [
            str(x.get("ckm_id")) for x in ctx["teknis_list"][:2]
        ]
    else:
        teknis_centang_ckm_ids = [str(x) for x in requested_teknis if str(x) in valid_teknis]

    # Logika Kinerja (996): Cek apakah sudah ada di teknis_list
    kinerja_exists = False
    if kinerja_text:
        for item in ctx["teknis_list"]:
            if str(item.get("ckm_id", "")) == "996":
                kinerja_exists = True
                if "996" not in teknis_centang_ckm_ids:
                    teknis_centang_ckm_ids.append("996")
                break

    for i, item in enumerate(ctx["teknis_list"]):
        chk_id = item.get("chk_id", "")
        ckm_id = str(item.get("ckm_id", ""))
        payload[f"syaratTeknis[{i}].chk_id"] = chk_id
        if ckm_id in teknis_centang_ckm_ids:
            payload[f"syaratTeknis[{i}].ckm_id"] = ckm_id
            payload[f"checklist_kualifikasi_teknis_ckm_id[{i}]"] = ckm_id
            if ckm_id == "996" and kinerja_text:
                payload[f"syaratTeknis[{i}].chk_nama"] = kinerja_text

    # ── KINERJA PENYEDIA (custom row baru) ────────────────────────
    if kinerja_text and not kinerja_exists:
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

    result = _http_post_result(r, "Submit LDK")
    ok = result["ok"]
    result["ijin_update"] = None

    # ── UPDATE ijin[1] klasifikasi via HTTP langsung ─────────────────────────
    # Jika sbu_lama kosong DAN ijin[1] sudah ada di SPSE (chk_id asli ≠ ""),
    # Form dibaca ulang supaya chk_id/native fields berasal dari state terbaru.
    if ok and not sbu_lama and sbu_baru and len(ijin_existing_ids) >= 2:
        # Row 0 = izin usaha; row 1 = SBU.
        klas_target = izin_list[1].get("klasifikasi", "")
        try:
            http_result = update_ijin_sbu_via_http(
                kode_paket,
                1,
                klas_target,
                _base,
                cookie=ctx["cookie"],
            )
            result["ijin_update"] = http_result
        except Exception as e:
            result["ijin_update"] = f"HTTP error: {e}"

    return result


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
        csrf = csrf_inp.get("value", "").strip()
    if not csrf:
        return {"ok": False, "status": 200, "error": "CSRF form masa berlaku kosong."}

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
    return _http_post_result(rp, "Submit masa berlaku")


# ─────────────────────────────────────────────────────────────────────────────
# Submit Checklist Dokumen Penawaran
# ─────────────────────────────────────────────────────────────────────────────

def submit_checklist_pl(
    kode_paket: str,
    centang_admin_all: bool = True,
    centang_syarat_all: bool = True,
    centang_harga_all: bool = True,
    selected_ckm_ids: list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict:
    """
    Submit checklist dokumen penawaran.
    PLPK memakai lima dokumen penawaran konstruksi yang ditetapkan user:
      - Teknis: ckm_id 341 (peralatan), 342 (personel), 344 (RKK).
      - Harga: ckm_id 347 (daftar kuantitas/keluaran dan harga), 348
        (klarifikasi kewajaran harga di bawah 80% HPS).
    ID row/chk_id tetap selalu diambil dari form live.
    """
    ctx = scrap_checklist_context(kode_paket)
    payload = {"authenticityToken": ctx["csrf"]}
    disabled_ckm_ids = {str(value) for value in ctx.get("disabled_ckm_ids", set())}
    checked_ckm_ids = {str(value) for value in ctx.get("checked_ckm_ids", set())}

    default_selected_ids = {"341", "342", "344", "347", "348"}
    selected_ids = (
        {str(value) for value in selected_ckm_ids}
        if selected_ckm_ids is not None
        else default_selected_ids
    )
    selected_teknis_ids = selected_ids & {"341", "342", "344"}
    selected_harga_ids = selected_ids & {"347", "348"}

    for i, item in enumerate(ctx["admin_items"]):
        payload[f"syaratAdmin[{i}].chk_id"] = item["chk_id"]
        # Form native tetap mengirim ckm_id tersembunyi untuk baris admin
        # bawaan yang disabled (336/337). Tanpa ini SPSE menerima 302, tetapi
        # tidak menyimpan keseluruhan checklist.
        if item["ckm_id"] in disabled_ckm_ids or item["ckm_id"] in checked_ckm_ids:
            payload[f"syaratAdmin[{i}].ckm_id"] = item["ckm_id"]
    for i, item in enumerate(ctx["syarat_items"]):
        payload[f"syarat[{i}].chk_id"] = item["chk_id"]
        if (
            centang_syarat_all
            and item["ckm_id"] in selected_teknis_ids
            and (item["ckm_id"] not in disabled_ckm_ids or item["ckm_id"] in checked_ckm_ids)
        ):
            payload[f"syarat[{i}].ckm_id"] = item["ckm_id"]
    for i, item in enumerate(ctx["harga_items"]):
        payload[f"syaratHarga[{i}].chk_id"] = item["chk_id"]
        if (
            centang_harga_all
            and item["ckm_id"] in selected_harga_ids
            and (item["ckm_id"] not in disabled_ckm_ids or item["ckm_id"] in checked_ckm_ids)
        ):
            payload[f"syaratHarga[{i}].ckm_id"] = item["ckm_id"]

    # Native submit button ikut menjadi bagian FormData browser.
    payload["simpan"] = "simpan"

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
    result = _http_post_result(rp, "Submit checklist")
    if not result["ok"]:
        return result

    # HTTP 302 hanya berarti server menerima request/redirect. Baca ulang
    # checklist untuk memastikan ckm_id benar-benar tersimpan di SPSE.
    expected_ckm_ids = set()
    if centang_syarat_all:
        expected_ckm_ids.update(selected_teknis_ids)
    if centang_harga_all:
        expected_ckm_ids.update(selected_harga_ids)
    try:
        verified_ctx = scrap_checklist_context(kode_paket)
        verified_ckm_ids = {
            str(value) for value in verified_ctx.get("checked_ckm_ids", set())
        }
        missing_ckm_ids = expected_ckm_ids - verified_ckm_ids

        def _sort_ckm(values):
            return sorted(values, key=lambda value: (not str(value).isdigit(), int(value) if str(value).isdigit() else str(value)))

        result["verified_ckm_ids"] = _sort_ckm(expected_ckm_ids & verified_ckm_ids)
        result["missing_ckm_ids"] = _sort_ckm(missing_ckm_ids)
        if missing_ckm_ids:
            result["ok"] = False
            result["error"] = (
                "Submit checklist HTTP 302, tetapi SPSE belum menyimpan "
                f"ckm_id: {', '.join(result['missing_ckm_ids'])}."
            )
    except Exception as exc:
        result["ok"] = False
        result["verified_ckm_ids"] = []
        result["missing_ckm_ids"] = _sort_ckm(expected_ckm_ids)
        result["error"] = f"Submit checklist HTTP 302, verifikasi state SPSE gagal: {exc}"
    return result
