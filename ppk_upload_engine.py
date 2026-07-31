"""
ppk_upload_engine.py — Engine upload dokumen persiapan pengadaan untuk role PPK ke SPSE.
"""

import json
import re
import urllib.request
import requests
from bs4 import BeautifulSoup
import spse_browser
from config import SPSE_BASE_URL

BASE_URL = SPSE_BASE_URL.rstrip("/")
_LPSE = BASE_URL.rstrip("/").rsplit("/", 1)[-1]  # "tapinkab"


_cdp_eval_lock = __import__("threading").Lock()
_CDP_PORT = 9222


def _cdp_eval(js: str, timeout: int = 30) -> tuple[bool, object, str]:
    """
    Jalankan JS di tab SPSE via pure WebSocket CDP (tanpa Playwright connect_over_cdp).
    Cari tab SPSE dari /json endpoint, connect langsung ke tab WS, eval JS.
    Return (ok, result_value, error_msg).
    """
    import asyncio, json as _json

    async def _run_ws():
        import websockets
        # Ambil daftar tab dari CDP HTTP
        import urllib.request as _ur
        try:
            tabs = _json.loads(_ur.urlopen(f"http://localhost:{_CDP_PORT}/json", timeout=3).read())
        except Exception as e:
            raise RuntimeError(f"CDP HTTP tidak aktif: {e}")

        page_tabs = [t for t in tabs if t.get("type") == "page"]
        if not page_tabs:
            raise RuntimeError("Tidak ada tab page di CDP")

        # Pilih tab SPSE paketnontender, fallback tab SPSE lain
        tab = next(
            (t for t in page_tabs if "paketnontender" in t.get("url", "") and "spse.inaproc.id" in t.get("url", "")),
            next((t for t in page_tabs if "spse.inaproc.id" in t.get("url", "")), page_tabs[0])
        )
        ws_url = tab.get("webSocketDebuggerUrl", "")
        if not ws_url:
            raise RuntimeError(f"Tab tidak punya webSocketDebuggerUrl: {tab.get('url')}")

        async with websockets.connect(ws_url, open_timeout=5) as ws:
            cmd = _json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
                "expression": js, "returnByValue": True, "awaitPromise": True
            }})
            await ws.send(cmd)
            while True:
                msg = _json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                if msg.get("id") == 1:
                    break
        res = msg.get("result", {})
        exc = res.get("exceptionDetails")
        if exc:
            raise RuntimeError(exc.get("text", "JS exception"))
        return res.get("result", {}).get("value")

    with _cdp_eval_lock:
        try:
            import threading
            result_holder = [None, None]  # [value, exception]
            def _in_thread():
                loop = asyncio.ProactorEventLoop()  # Windows: wajib Proactor untuk WS
                asyncio.set_event_loop(loop)
                try:
                    result_holder[0] = loop.run_until_complete(_run_ws())
                except Exception as e:
                    result_holder[1] = e
                finally:
                    loop.close()
            t = threading.Thread(target=_in_thread, daemon=True)
            t.start()
            t.join(timeout=timeout + 5)
            if t.is_alive():
                return False, None, "CDP eval timeout"
            if result_holder[1]:
                raise result_holder[1]
            return True, result_holder[0], ""
        except Exception as e:
            return False, None, str(e)

_SUBMIT_ENDPOINTS = {
    "kak":     "spekPpkSubmit",
    "kontrak": "uploadSskkSubmit",
    "uraian":  "uploadUraianSubmit",
    "lainnya": "lainnyaPpkSubmit",
}

_DELETE_ENDPOINTS = {
    "kak":     "hapusspekppk",
    "kontrak": "hapussskkattachment",
    "uraian":  "hapusuraianattachment",
    "lainnya": "hapuslainnyappk",
}

def _headers(referer: str = "") -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer or BASE_URL,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }

def get_cookies_from_browser() -> str:
    """Ambil cookie SPSE via spse_browser"""
    return spse_browser.get_spse_cookies()



def fetch_paket_ppk() -> list[dict]:
    """
    Ambil daftar paket non-tender PPK via CDP WebSocket.
    Cookie HttpOnly tidak bisa diakses Python — fetch dari dalam browser.
    """
    import time as _time
    ts = int(_time.time() * 1000)
    js = f"""
    (async () => {{
        const r = await fetch('/{_LPSE}/dt/paketppknontender?draw=1&start=0&length=200&_={ts}',
                              {{credentials:'include'}});
        if (!r.ok) return [];
        const j = await r.json();
        return (j.data || []).map(row => ({{
            kode_paket: String(row[0]),
            nama_paket: String(row[1]),
            status:     String(row[2]),
        }}));
    }})()
    """
    ok, val, err = _cdp_eval(js, timeout=20)
    if not ok:
        return []
    rows = val or []
    # Tab PPK hanya menampilkan paket aktif berstatus Draft.
    return [p for p in rows if str(p.get("status", "")).strip().lower() == "draft"]

def fetch_detail_paket(kode_paket: str) -> dict:
    """
    Scrape detail paket PPK dari edit?step=1 dan step=2.
    Return dict berisi: kode_rup, mak, nilai_pagu, nilai_hps, tahun_anggaran,
    sumber_dana, lokasi, jenis_kontrak, nama_ppk, instansi, satker.
    """
    cookie_str = get_cookies_from_browser()
    if not cookie_str:
        return {}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Cookie": cookie_str,
        "Referer": f"{BASE_URL}/paketnontender/{kode_paket}/edit?step=1",
    }
    result: dict = {}

    # ── Step 1 ────────────────────────────────────────────────────────────────
    try:
        r1 = requests.get(f"{BASE_URL}/paketnontender/{kode_paket}/edit?step=1", headers=headers, timeout=15)
        soup1 = BeautifulSoup(r1.text, "html.parser")

        # Tabel RUP (kolom: kode_rup, nama_paket_rup, sumber_dana)
        for tbl in soup1.find_all("table"):
            rows = tbl.find_all("tr")
            for tr in rows:
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cells) >= 2 and re.match(r"^\d{8,}$", cells[0]):
                    result["kode_rup"] = cells[0]
                    break

        # Tabel Anggaran (kolom: tahun, sumber_dana, kode_rekening, nilai_pagu, nama_ppk)
        tbl_rows_all = []
        for tbl in soup1.find_all("table"):
            for tr in tbl.find_all("tr"):
                cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
                tbl_rows_all.append(cells)

        for cells in tbl_rows_all:
            if len(cells) >= 3 and re.match(r"^\d{4}$", cells[0]):  # tahun anggaran
                result["tahun_anggaran"] = cells[0]
                if len(cells) > 1: result["sumber_dana"] = cells[1]
                if len(cells) > 2: result["mak"] = cells[2].rstrip(".")
                if len(cells) > 3:
                    # "Rp. 44.950.000,00" → hapus titik ribuan, ambil sebelum koma
                    raw = cells[3].replace("Rp.", "").replace("Rp", "").strip()
                    raw = raw.replace(".", "").split(",")[0]
                    if raw.isdigit(): result["nilai_pagu"] = int(raw)
                if len(cells) > 4: result["nama_ppk"] = cells[4]
                break

        # K/L/PD (Instansi) & Satker
        for label in soup1.find_all(["label", "th", "td"]):
            txt = label.get_text(strip=True)
            if "K/L/PD" in txt or "Instansi" in txt:
                sib = label.find_next_sibling()
                if sib: result["instansi"] = sib.get_text(strip=True)
            if "Satuan Kerja" in txt:
                sib = label.find_next_sibling()
                if sib: result["satker"] = sib.get_text(strip=True)

        # Lokasi: input textlokasi
        inp_lok = soup1.find("input", {"id": "textlokasi"})
        if inp_lok:
            result["lokasi"] = inp_lok.get("value", "")
        sel_kab = soup1.find("select", {"id": "kabupaten"})
        if sel_kab:
            sel_opt = sel_kab.find("option", {"selected": True})
            if sel_opt:
                kab_txt = sel_opt.get_text(strip=True)
                lok = result.get("lokasi", "")
                result["lokasi"] = f"{kab_txt}, {lok}".strip(", ") if lok else kab_txt

    except Exception as e:
        result["_error_step1"] = str(e)

    # ── Step 2: nilai HPS + jenis kontrak ─────────────────────────────────────
    try:
        r2 = requests.get(f"{BASE_URL}/paketnontender/{kode_paket}/edit?step=2", headers=headers, timeout=15)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        # Nilai HPS dari tabel row "Nilai HPS"
        for tr in soup2.find_all("tr"):
            cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
            if cells and "Nilai HPS" in cells[0] and len(cells) > 1:
                raw = cells[1].replace("Rp.", "").replace("Rp", "").strip()
                raw = raw.split()[0].replace(".", "").split(",")[0]
                if raw.isdigit(): result["nilai_hps"] = int(raw)
                break

        # Jenis kontrak
        sel_k = soup2.find("select", {"name": "kontrak_pembayaran"})
        if sel_k:
            opt = sel_k.find("option", {"selected": True})
            if opt: result["jenis_kontrak"] = opt.get_text(strip=True)

    except Exception as e:
        result["_error_step2"] = str(e)

    return result


def upload_dokumen(
    kode_paket: str,
    jenis: str,
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
    cookies: dict = None,
    log_fn=None
) -> dict:
    """
    Upload dokumen PPK via CDP page.evaluate (5 langkah).
    Cookie PPK ber-flag HttpOnly — seluruh flow dijalankan dari dalam browser.
    File bytes dikirim sebagai base64, di-decode di browser lalu di-upload.
    """
    import base64

    def _log(msg):
        if log_fn:
            log_fn(msg)

    sub_endpoint = _SUBMIT_ENDPOINTS.get(jenis)
    if not sub_endpoint:
        return {"ok": False, "error": f"Jenis '{jenis}' tidak dikenal."}

    _log(f"Langkah 1-5: Upload via browser (CDP)...")
    b64 = base64.b64encode(file_bytes).decode()

    js = f"""
    (async () => {{
        const lpse = "{_LPSE}";
        const kode = "{kode_paket}";
        const mime = "{mime_type}";
        const fname = "{file_name}";
        const subEndpoint = "{sub_endpoint}";
        const b64 = "{b64}";

        const binaryStr = atob(b64);
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);

        await fetch('/' + lpse + '/otorisasiDataPaketPlUpload?id=' + kode, {{credentials:'include'}});

        const formData = new FormData();
        formData.append('input[uploadSignedUrlReq][0][contentType]', mime);
        formData.append('input[uploadSignedUrlReq][0][identifier]', '');
        formData.append('input[uploadSignedUrlReq][0][fileName]', fname);
        formData.append('input[uploadSignedUrlReq][0][isPublic]', 'false');
        formData.append('isArchieve', 'true');

        const r2 = await fetch('/' + lpse + '/paketnontender/' + kode + '/getSignedUrl', {{
            method: 'POST', credentials: 'include', body: formData
        }});
        if (!r2.ok) return {{ok: false, error: 'getSignedUrl HTTP ' + r2.status}};
        const res2 = await r2.json();
        const fileId = res2?.result?.data?.fileId;
        const signedUrl = res2?.result?.data?.signedUrl;
        const path = res2?.result?.data?.path || res2?.path;
        if (!fileId || !signedUrl || !path) return {{ok: false, error: 'getSignedUrl data tidak lengkap: ' + JSON.stringify(res2)}};

        const r3 = await fetch(signedUrl, {{
            method: 'PUT', headers: {{'Content-Type': mime}}, body: bytes
        }});
        if (!r3.ok) return {{ok: false, error: 'PUT storage HTTP ' + r3.status}};

        for (let i = 0; i < 5; i++) {{
            const fd4 = new FormData();
            fd4.append('input', fileId);
            const r4 = await fetch('/' + lpse + '/uploadCheckStatus', {{
                method: 'POST', credentials: 'include', body: fd4
            }});
            let d4 = null;
            try {{ d4 = await r4.json(); }} catch(e) {{ break; }}  // parse error = lanjut
            if (!d4 || d4?.errors === null) break;  // null errors = sukses
            if (d4?.errors) return {{ok: false, error: 'checkStatus error: ' + JSON.stringify(d4.errors)}};
            const st = d4?.data?.status;
            if (!st || st === 'UPLOAD_SUCCESS') break;
            if (st === 'UPLOAD_FAILED') return {{ok: false, error: 'Upload dinyatakan gagal server'}};
            await new Promise(r => setTimeout(r, 300));
        }}

        const fd5 = new FormData();
        fd5.append('id', kode);
        fd5.append('path', path);
        fd5.append('fileId', fileId);
        const r5 = await fetch('/' + lpse + '/dokumennontender/' + kode + '/' + subEndpoint, {{
            method: 'POST', credentials: 'include', body: fd5
        }});
        if (!r5.ok) return {{ok: false, error: 'submit HTTP ' + r5.status}};
        let res5 = null;
        try {{ res5 = await r5.clone().json(); }} catch(e) {{}}
        const versi = res5?.files?.[0]?.versi ?? null;
        return {{ok: true, path, fileId, versi}};
    }})()
    """
    ok, result, err = _cdp_eval(js, timeout=120)
    if not ok:
        return {"ok": False, "error": err}
    if result and result.get("ok"):
        _log(f"✅ {file_name} berhasil diupload")
    else:
        _log(f"❌ {file_name} gagal: {result.get('error') if result else err}")
    return result or {"ok": False, "error": err}

def upload_nota_dinas(kode_paket: str, file_bytes: bytes, file_name: str, mime_type: str, log_fn=None) -> dict:
    """
    Upload Nota Dinas via GCS flow + submit ke uploadAttachment step=1.
    """
    import base64

    def _log(msg):
        if log_fn: log_fn(msg)

    _log(f"Langkah 1-5: Upload ND via browser (CDP)...")
    b64 = base64.b64encode(file_bytes).decode()

    js = f"""
    (async () => {{
        const lpse = "{_LPSE}";
        const kode = "{kode_paket}";
        const mime = "{mime_type}";
        const fname = "{file_name}";
        const b64 = "{b64}";

        const binaryStr = atob(b64);
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);

        await fetch('/' + lpse + '/otorisasiDataPaketPlUpload?id=' + kode, {{credentials:'include'}});

        const formData = new FormData();
        formData.append('input[uploadSignedUrlReq][0][contentType]', mime);
        formData.append('input[uploadSignedUrlReq][0][identifier]', '');
        formData.append('input[uploadSignedUrlReq][0][fileName]', fname);
        formData.append('input[uploadSignedUrlReq][0][isPublic]', 'false');
        formData.append('isArchieve', 'true');

        const r2 = await fetch('/' + lpse + '/paketnontender/' + kode + '/getSignedUrl', {{
            method: 'POST', credentials: 'include', body: formData
        }});
        if (!r2.ok) return {{ok: false, error: 'getSignedUrl HTTP ' + r2.status}};
        const res2 = await r2.json();
        const fileId = res2?.result?.data?.fileId;
        const signedUrl = res2?.result?.data?.signedUrl;
        const path = res2?.result?.data?.path || res2?.path;
        if (!fileId || !signedUrl || !path) return {{ok: false, error: 'getSignedUrl data tidak lengkap: ' + JSON.stringify(res2)}};

        const r3 = await fetch(signedUrl, {{
            method: 'PUT', headers: {{'Content-Type': mime}}, body: bytes
        }});
        if (!r3.ok) return {{ok: false, error: 'PUT storage HTTP ' + r3.status}};

        for (let i = 0; i < 5; i++) {{
            const fd4 = new FormData();
            fd4.append('input', fileId);
            const r4 = await fetch('/' + lpse + '/uploadCheckStatus', {{
                method: 'POST', credentials: 'include', body: fd4
            }});
            let d4 = null;
            try {{ d4 = await r4.json(); }} catch(e) {{ break; }}
            if (!d4 || d4?.errors === null) break;
            if (d4?.errors) return {{ok: false, error: 'checkStatus error: ' + JSON.stringify(d4.errors)}};
            const st = d4?.data?.status;
            if (!st || st === 'UPLOAD_SUCCESS') break;
            if (st === 'UPLOAD_FAILED') return {{ok: false, error: 'Upload dinyatakan gagal server'}};
            await new Promise(r => setTimeout(r, 300));
        }}

        const fd5 = new FormData();
        fd5.append('id', kode);
        fd5.append('step', '1');
        fd5.append('path', path);
        fd5.append('fileId', fileId);
        const r5 = await fetch('/' + lpse + '/paketnontender/' + kode + '/uploadAttachment', {{
            method: 'POST', credentials: 'include', body: fd5
        }});
        if (!r5.ok) return {{ok: false, error: 'submit HTTP ' + r5.status}};

        return {{ok: true, path, fileId}};
    }})()
    """
    ok, result, err = _cdp_eval(js, timeout=120)
    if not ok:
        return {"ok": False, "error": err}
    if result and result.get("ok"):
        _log(f"✅ {file_name} berhasil diupload")
    else:
        _log(f"❌ {file_name} gagal: {result.get('error') if result else err}")
    return result or {"ok": False, "error": err}

def pilih_pp(kode_paket: str, pp_id: str = "74177", log_fn=None) -> bool:
    """
    Step 3 SPSE: pilih PP via /pilihpp -> submit_pp.
    Ambil token dari halaman /pilihpp, POST ke /submit_pp dengan field ppId (bukan pp_id).
    """
    js = f"""
    (async () => {{
        const tokenResp = await fetch('/{_LPSE}/paketnontender/{kode_paket}/pilihpp', {{credentials:'include'}});
        const html = await tokenResp.text();
        const tokenMatch = html.match(/authenticityToken[^>]*value="([^"]+)"/);
        const token = tokenMatch ? tokenMatch[1] : '';
        const fd = new FormData();
        fd.append('authenticityToken', token);
        fd.append('ppId', '{pp_id}');
        const r = await fetch('/{_LPSE}/paketnontender/{kode_paket}/submit_pp', {{
            method: 'POST', credentials: 'include', body: fd
        }});
        return {{status: r.status, ok: r.ok, url: r.url}};
    }})()
    """
    ok, val, _ = _cdp_eval(js, timeout=20)
    if not ok or not val:
        return False
    return val.get("ok") is True or val.get("status") in (200, 302)


def kirim_email_pp(kode_paket: str, path: str, file_id: str, log_fn=None) -> bool:
    """
    Kirim email pemberitahuan ke PP_ISRANDRIA (pp_id=74177) setelah ND terupload.
    Wajib panggil pilih_pp() dulu sebelum fungsi ini.
    """
    js = f"""
    (async () => {{
        const fd = new FormData();
        fd.append('id', '{kode_paket}');
        fd.append('pp_id', '74177');
        fd.append('path', '{path}');
        fd.append('fileId', '{file_id}');
        const r = await fetch('/{_LPSE}/paketnontender/{kode_paket}/submitrekirimpesanpp?pp_id=74177', {{
            method: 'POST', credentials: 'include', body: fd, redirect: 'manual'
        }});
        return {{status: r.status}};
    }})()
    """
    ok, val, _ = _cdp_eval(js, timeout=20)
    if not ok or not val: return False
    st = val.get("status")
    return st in (0, 200, 302)


def simpan_dan_membuat_paket(kode_paket: str, log_fn=None) -> dict:
    """Submit final step 3 SPSE setelah PP, Nota Dinas, dan email siap.

    Token diambil ulang dari halaman step 3 agar tidak memakai token lama
    setelah rangkaian upload/email sebelumnya.
    """
    import json as _json

    def _log(msg):
        if log_fn:
            log_fn(msg)

    kode_js = _json.dumps(str(kode_paket))
    js = f"""
    (async () => {{
        const lpse = {_json.dumps(_LPSE)};
        const kode = {kode_js};
        const editUrl = '/' + lpse + '/paketnontender/' + kode + '/edit?step=3';
        const submitPath = '/' + lpse + '/paketnontender/' + kode + '/simpanpartthree';
        const pageResp = await fetch(editUrl, {{credentials: 'include', cache: 'no-store'}});
        if (!pageResp.ok) return {{ok: false, error: 'Gagal membaca step 3 HTTP ' + pageResp.status}};

        const html = await pageResp.text();
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const form = doc.querySelector('#formTambahPaket');
        if (!form) return {{ok: false, error: 'Form #formTambahPaket tidak ditemukan pada step 3'}};

        const fd = new FormData(form);
        fd.set('step', fd.get('step') || '3');
        fd.set('flow', fd.get('flow') || '1');
        fd.set('simpan', 'simpan');
        const response = await fetch(submitPath, {{
            method: 'POST', credentials: 'include', body: fd, redirect: 'follow'
        }});
        const responseText = await response.text();
        const finalUrl = response.url || '';
        const followed = !finalUrl.includes('/simpanpartthree');
        const success = response.ok && followed;
        return {{
            ok: success,
            status: response.status,
            finalUrl,
            error: success ? '' : ('Submit final tidak terkonfirmasi (HTTP ' + response.status + ', URL ' + finalUrl + ')'),
            preview: responseText.slice(0, 300)
        }};
    }})()
    """
    ok, val, err = _cdp_eval(js, timeout=30)
    if not ok or not val:
        _log(f"❌ Simpan dan Membuat Paket gagal: {err or 'respons kosong'}")
        return {"ok": False, "error": err or "Respons kosong dari submit final"}
    if val.get("ok"):
        _log("✅ Simpan dan Membuat Paket berhasil")
    else:
        _log(f"❌ Simpan dan Membuat Paket gagal: {val.get('error', 'respons tidak terkonfirmasi')}")
    return val

_LIST_ENDPOINTS = {
    "kak":     "spekppk",
    "kontrak": "uploadsskk",
    "uraian":  "uploaduraian",
    "lainnya": "lainnyappk",
    "nd":      "notadinasppk",
}

def list_semua_dokumen(kode_paket: str) -> dict[str, list[dict]]:
    """
    Ambil dokumen semua jenis via cdp_eval + fetch() + DOMParser.
    Tidak membuka tab baru — fetch dari tab SPSE yang sudah aktif.
    """
    import json as _json
    endpoints = {k: v for k, v in _LIST_ENDPOINTS.items() if k != "nd"}
    lpse = _LPSE
    js = f"""
(async () => {{
  const lpse = {_json.dumps(lpse)};
  const kode = {_json.dumps(kode_paket)};
  const endpoints = {_json.dumps(endpoints)};
  const results = {{}};
  await Promise.all(Object.entries(endpoints).map(async ([jenis, ep]) => {{
    try {{
      const r = await fetch('/' + lpse + '/dokumennontender/' + kode + '/' + ep, {{credentials: 'include'}});
      const html = await r.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const rows = doc.querySelectorAll('#files tbody tr');
      const docs = [];
      rows.forEach(tr => {{
        const a = tr.querySelector('td a');
        const rem = tr.querySelector('.removeDok');
        const versi = rem ? parseInt(rem.getAttribute('versi') || '0') : 0;
        if (a && a.textContent.trim()) {{
          docs.push({{nama_file: a.textContent.trim(), url_dl: a.href || '', versi: versi}});
        }}
      }});
      results[jenis] = docs;
    }} catch(e) {{ results[jenis] = []; }}
  }}));
  return results;
}})()
"""
    ok, val, _ = _cdp_eval(js, timeout=20)
    return val if ok and isinstance(val, dict) else {}


def list_bulk_semua_paket(kode_list: list[str]) -> dict[str, dict[str, list[dict]]]:
    """
    Ambil dokumen semua jenis untuk N paket via cdp_eval + fetch() paralel.
    Tidak membuka tab baru — semua fetch dari tab SPSE yang sudah aktif.
    """
    import json as _json
    endpoints = {k: v for k, v in _LIST_ENDPOINTS.items() if k != "nd"}
    lpse = _LPSE
    js = f"""
(async () => {{
  const lpse = {_json.dumps(lpse)};
  const kode_list = {_json.dumps(kode_list)};
  const endpoints = {_json.dumps(endpoints)};
  const out = {{}};
  await Promise.all(kode_list.map(async kode => {{
    out[kode] = {{}};
    await Promise.all(Object.entries(endpoints).map(async ([jenis, ep]) => {{
      try {{
        const r = await fetch('/' + lpse + '/dokumennontender/' + kode + '/' + ep, {{credentials: 'include'}});
        const html = await r.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const rows = doc.querySelectorAll('#files tbody tr');
        const docs = [];
        rows.forEach(tr => {{
          const a = tr.querySelector('td a');
          const rem = tr.querySelector('.removeDok');
          const versi = rem ? parseInt(rem.getAttribute('versi') || '0') : 0;
          if (a && a.textContent.trim()) {{
            docs.push({{nama_file: a.textContent.trim(), url_dl: a.href || '', versi: versi}});
          }}
        }});
        out[kode][jenis] = docs;
      }} catch(e) {{ out[kode][jenis] = []; }}
    }}));
  }}));
  return out;
}})()
"""
    ok, val, _ = _cdp_eval(js, timeout=30)
    return val if ok and isinstance(val, dict) else {}


def list_dokumen(kode_paket: str, jenis: str, cookies: dict = None) -> list[dict]:
    """
    Ambil daftar dokumen terunggah via Playwright goto (tabel diisi JS, bukan SSR).
    Navigate ke endpoint, tunggu #files tbody terisi, parse .removeDok.
    """
    endpoint = _LIST_ENDPOINTS.get(jenis)
    if not endpoint:
        return []

    url = f"https://spse.inaproc.id/{_LPSE}/dokumennontender/{kode_paket}/{endpoint}"
    import subprocess, sys, json as _json, tempfile, os

    script = f"""
import sys, json
from playwright.sync_api import sync_playwright

url = {_json.dumps(url)}
with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://localhost:9222")
    ctx = browser.contexts[0]
    # Buka halaman baru agar tidak ganggu tab user
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        # Tunggu jQuery populate #files tbody (via uploadFlow successData)
        # Max 8 detik; kalau tidak ada row, kembalikan []
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('#files tbody tr td').length > 0",
                timeout=8000
            )
        except Exception:
            pass  # timeout = tidak ada file
        result = page.evaluate('''() => {{
            const rows = document.querySelectorAll("#files tbody tr");
            const out = [];
            rows.forEach(tr => {{
                const a = tr.querySelector("td a");
                const rem = tr.querySelector(".removeDok");
                const versi = rem ? parseInt(rem.getAttribute("versi") || "0") : 0;
                if (a && a.textContent.trim()) {{
                    out.push({{
                        nama_file: a.textContent.trim(),
                        url_dl: a.href || "",
                        versi: versi,
                    }});
                }}
            }});
            return out;
        }}''')
        print(json.dumps({{"ok": True, "value": result}}))
    except Exception as e:
        print(json.dumps({{"ok": False, "error": str(e)}}))
    finally:
        page.close()
"""
    fd, path = tempfile.mkstemp(suffix="_list_dok.py", prefix="pokja_")
    os.write(fd, script.encode())
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, path],
            capture_output=True, timeout=30
        )
        stdout = proc.stdout.decode(errors="replace").strip()
        if stdout:
            resp = json.loads(stdout)
            if resp.get("ok"):
                return resp.get("value") or []
        return []
    except Exception:
        return []
    finally:
        os.unlink(path)


def hapus_dokumen(kode_paket: str, jenis: str, versi: int, cookies: dict = None) -> bool:
    """
    Hapus dokumen via CDP (cookie HttpOnly).
    """
    del_endpoint = _DELETE_ENDPOINTS.get(jenis)
    if not del_endpoint:
        return False

    js = f"""
    (async () => {{
        const fd = new FormData();
        fd.append('versi', '{versi}');
        const r = await fetch('/{_LPSE}/dokumennontender/{kode_paket}/{del_endpoint}',
                              {{method:'POST', credentials:'include', body:fd}});
        return r.ok || r.status === 302;
    }})()
    """
    ok, val, _ = _cdp_eval(js, timeout=15)
    return bool(ok and val)


def hapus_semua_dokumen(kode_paket: str, versi_map: dict = None) -> dict:
    """
    Hapus semua dokumen (kak/kontrak/uraian/lainnya).
    versi_map: {jenis: [versi, ...]} dari session_state (lebih cepat).
    Kalau tidak ada, fallback ke list_dokumen (Playwright goto).
    Return {"dihapus": N, "gagal": N}.
    """
    jenis_list = [k for k in _LIST_ENDPOINTS if k != "nd"]

    # Kumpulkan semua (jenis, versi) yang perlu dihapus
    to_delete = []
    if versi_map:
        for jenis, versis in versi_map.items():
            for v in versis:
                to_delete.append({"jenis": jenis, "versi": v})
    else:
        for jenis in jenis_list:
            docs = list_dokumen(kode_paket, jenis)
            for doc in docs:
                if doc.get("versi") is not None:
                    to_delete.append({"jenis": jenis, "versi": doc["versi"]})

    if not to_delete:
        return {"dihapus": 0, "gagal": 0}

    # Hapus semua dalam 1 CDP call (paralel di browser)
    import json as _json
    del_ep = _DELETE_ENDPOINTS
    lpse   = _LPSE

    js = f"""
    (async () => {{
        const lpse = "{lpse}";
        const kode = "{kode_paket}";
        const toDelete = {_json.dumps(to_delete)};
        const deleteEp = {_json.dumps(del_ep)};
        let dihapus = 0, gagal = 0;
        await Promise.all(toDelete.map(async ({{jenis, versi}}) => {{
            const ep = deleteEp[jenis];
            if (!ep) {{ gagal++; return; }}
            const fd = new FormData();
            fd.append('versi', String(versi));
            const r = await fetch(`/${{lpse}}/dokumennontender/${{kode}}/${{ep}}`,
                                  {{method:'POST', credentials:'include', body:fd}});
            if (r.ok || r.status === 302) dihapus++;
            else gagal++;
        }}));
        return {{dihapus, gagal}};
    }})()
    """
    ok, val, err = _cdp_eval(js, timeout=30)
    if not ok or not val:
        return {"dihapus": 0, "gagal": len(to_delete)}
    return val


PPK_PL_BASE = r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Dinas Perdagangan\1 PERENCANAAN PENGADAAN\Dokumen Upload PPK PL"


def folder_number(folder_name: str) -> int | None:
    """Ambil nomor urut dari prefix folder PPK, mis. ``9. Nama`` → 9."""
    m = re.match(r"^\s*(\d+)\s*\.\s*", str(folder_name or ""))
    return int(m.group(1)) if m else None


def next_folder_number(subfolders: list[str] | None = None) -> int:
    """Nomor paket berikutnya berdasarkan folder fisik PPK, bukan jumlah API."""
    folders = subfolders if subfolders is not None else list_subfolder_ppk()
    return max((folder_number(f) or 0 for f in folders), default=0) + 1

FILE_PREFIX_MAP = {
    "1.":  "kak",      # KAK / Spesifikasi Teknis
    "9.":  "kak",      # List Personil (masuk KAK)
    "2.":  "uraian",   # Uraian Singkat
    "3.":  "kontrak",  # SPPBJ (masuk Rancangan Kontrak)
    "4.":  "kontrak",  # SPMK (masuk Rancangan Kontrak)
    "5.":  "kontrak",  # Rancangan Kontrak (SPK)
    "6.":  "kontrak",  # SUK (masuk Rancangan Kontrak)
    "8.":  "nd",       # Nota Dinas PPK
    "11.": "lainnya",  # Diskresi / Informasi Lainnya
    # 7. HPS, 10. Survey — tidak diupload
}

def scan_folder(folder_path: str, pdf_only: bool = False) -> list[dict]:
    """
    Scan folder → return list file yang akan diupload.
    [{"path": str, "nama": str, "jenis": str, "mime": str}]
    Skip file yang prefixnya tidak ada di FILE_PREFIX_MAP.
    """
    import os, mimetypes
    hasil = []
    if not os.path.isdir(folder_path):
        return []
    for fname in sorted(os.listdir(folder_path)):
        fpath = os.path.join(folder_path, fname)
        if not os.path.isfile(fpath):
            continue
        if pdf_only and os.path.splitext(fname)[1].lower() != ".pdf":
            continue
        jenis = None
        for prefix, j in FILE_PREFIX_MAP.items():
            if fname.startswith(prefix + " ") or fname == prefix.rstrip(".") + ".pdf":
                jenis = j
                break
        if not jenis:
            continue
        mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        hasil.append({"path": fpath, "nama": fname, "jenis": jenis, "mime": mime})
    return hasil


def list_subfolder_ppk() -> list[str]:
    """
    List subfolder di PPK_PL_BASE yang bukan _* atau .*
    Return sorted list nama folder.
    """
    import os
    if not os.path.isdir(PPK_PL_BASE):
        return []
    return sorted([
        d for d in os.listdir(PPK_PL_BASE)
        if os.path.isdir(os.path.join(PPK_PL_BASE, d))
        and not d.startswith('_') and not d.startswith('.')
    ])


def auto_match_folder(nama_paket_spse: str, subfolder_list: list[str]) -> str | None:
    """
    Fuzzy match nama paket SPSE ke subfolder PPK PL.
    Return nama subfolder yang paling cocok, atau None.
    """
    import re
    from difflib import SequenceMatcher

    STRIP_PREFIXES = [
        'Belanja Jasa Konsultansi Perencanaan Arsitektur-Jasa Arsitektur Lainnya ',
        'Belanja Jasa Konsultansi Perencanaan Arsitektur-Jasa Arsitektur ',
        'Belanja Jasa Konsultansi Perencanaan Rekayasa-Jasa Desain Rekayasa untuk Konstruksi ',
        'Belanja Jasa Konsultansi Perencanaan ',
        'Belanja Jasa Konsultansi ',
        'Belanja Jasa ',
    ]

    def _strip(nama):
        for pfx in STRIP_PREFIXES:
            if nama.startswith(pfx):
                return nama[len(pfx):]
        return nama

    def _strip_num(folder):
        return re.sub(r'^\d+\.\s*', '', folder)

    def _folder_num(folder):
        m = re.match(r'^(\d+)\.', folder)
        return int(m.group(1)) if m else 0

    target = _strip(nama_paket_spse).lower().strip()
    best, best_score, best_num = None, 0.0, -1
    for folder in subfolder_list:
        candidate = _strip_num(folder).lower().strip()
        # substring → score 1.0, tapi tetap bandingkan semua (jangan early return)
        if target in candidate or candidate in target:
            score = 1.0
        else:
            score = SequenceMatcher(None, target, candidate).ratio()
        fnum = _folder_num(folder)
        # ambil score tertinggi; tie-break: nomor folder terbesar (versi terbaru)
        if score > best_score or (score == best_score and fnum > best_num):
            best_score = score
            best = folder
            best_num = fnum
    return best if best_score > 0.65 else None


def upload_dari_folder(
    kode_paket: str,
    folder_path: str,
    log_fn=None,
    pdf_only: bool = False,
) -> dict:
    """
    Upload semua file yang cocok dari folder ke SPSE.
    Return {"results": [{"jenis", "nama", "ok", "error"}], "total_ok": int, "total_err": int}
    """
    def _log(msg):
        if log_fn: log_fn(msg)

    files = scan_folder(folder_path, pdf_only=pdf_only)
    if not files:
        return {"results": [], "total_ok": 0, "total_err": 0, "error": "Tidak ada file yang cocok di folder ini."}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    nd_files = [f for f in files if f["jenis"] == "nd"]
    non_nd_files = [f for f in files if f["jenis"] != "nd"]

    results = []
    nd_result = None

    def _upload_one(f):
        # log_fn TIDAK dipanggil dari sini (Streamlit tidak thread-safe)
        # — kumpulkan log di result, flush di main thread
        logs = []
        try:
            with open(f["path"], "rb") as fh:
                file_bytes = fh.read()
            logs.append(f"⬆️ Upload [{f['jenis']}] {f['nama']}...")
            res = upload_dokumen(
                kode_paket=kode_paket,
                jenis=f["jenis"],
                file_bytes=file_bytes,
                file_name=f["nama"],
                mime_type=f["mime"],
                log_fn=None,  # no Streamlit call in thread
            )
            ok = res.get("ok", False)
            logs.append(f"  {'✅' if ok else '❌'} {f['nama']} {'berhasil' if ok else 'gagal: ' + res.get('error','')}")
            return {"jenis": f["jenis"], "nama": f["nama"], "ok": ok, "error": res.get("error", ""), "versi": res.get("versi"), "_logs": logs}
        except Exception as e:
            logs.append(f"  ❌ Exception: {e}")
            return {"jenis": f["jenis"], "nama": f["nama"], "ok": False, "error": str(e), "versi": None, "_logs": logs}

    # Upload non-ND paralel, max 3 worker
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_upload_one, f): f for f in non_nd_files}
        for fut in as_completed(futures):
            r = fut.result()
            for msg in r.pop("_logs", []):
                _log(msg)  # flush log di main thread (aman untuk Streamlit)
            results.append(r)

    # Pilih PP (step 3) sebelum upload ND
    _log("🔗 Pilih PP (step 3)...")
    pp_ok = pilih_pp(kode_paket, log_fn=log_fn)
    if not pp_ok:
        _log("⚠️ Pilih PP gagal — lanjut upload ND tapi email mungkin gagal")

    # Upload ND setelah PP dipilih
    for f in nd_files:
        try:
            with open(f["path"], "rb") as fh:
                file_bytes = fh.read()
            _log(f"⬆️ Upload [nd] {f['nama']}...")
            res = upload_nota_dinas(
                kode_paket=kode_paket,
                file_bytes=file_bytes,
                file_name=f["nama"],
                mime_type=f["mime"],
                log_fn=log_fn,
            )
            ok = res.get("ok", False)
            if ok:
                nd_result = res
                _log(f"  ✅ {f['nama']} berhasil")
            else:
                _log(f"  ❌ {f['nama']} gagal: {res.get('error')}")
            results.append({"jenis": f["jenis"], "nama": f["nama"], "ok": ok, "error": res.get("error", ""), "versi": res.get("versi")})
        except Exception as e:
            _log(f"  ❌ Exception: {e}")
            results.append({"jenis": f["jenis"], "nama": f["nama"], "ok": False, "error": str(e), "versi": None})

    if nd_result:
        _log("📧 Kirim email pemberitahuan ke PP...")
        email_ok = kirim_email_pp(kode_paket, nd_result["path"], nd_result["fileId"], log_fn)
        if email_ok:
            _log("✅ Email ke PP berhasil dikirim")
        else:
            _log("⚠️ Email ke PP gagal — upload ND ok tapi email gagal")

    total_ok = sum(1 for r in results if r["ok"])
    total_err = len(results) - total_ok
    return {"results": results, "total_ok": total_ok, "total_err": total_err}


def upload_dokumen_dari_folder(
    kode_paket: str,
    folder_path: str,
    log_fn=None,
    pdf_only: bool = False,
) -> dict:
    """Pilih PP lalu upload dokumen PPK 1-9/11; Nota Dinas dikecualikan."""
    files = [
        f for f in scan_folder(folder_path, pdf_only=pdf_only)
        if re.match(r"^(?:[1-9]|11)\.\s", f["nama"]) and f["jenis"] != "nd"
    ]
    if not files:
        return {
            "results": [],
            "total_ok": 0,
            "total_err": 0,
            "error": "Tidak ada dokumen bernomor 1-9/11 (selain Nota Dinas) yang cocok di folder ini.",
        }

    def _log(msg):
        if log_fn:
            log_fn(msg)

    _log("🔗 Memilih Pejabat Pengadaan...")
    pp_ok = pilih_pp(kode_paket, log_fn=log_fn)
    if not pp_ok:
        _log("❌ Pemilihan Pejabat Pengadaan gagal; dokumen belum diupload.")
        return {
            "results": [],
            "total_ok": 0,
            "total_err": len(files),
            "pp_ok": False,
            "error": "Pemilihan Pejabat Pengadaan gagal; dokumen belum diupload.",
        }

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _upload_one(file_info):
        try:
            with open(file_info["path"], "rb") as fh:
                file_bytes = fh.read()
            result = upload_dokumen(
                kode_paket=kode_paket,
                jenis=file_info["jenis"],
                file_bytes=file_bytes,
                file_name=file_info["nama"],
                mime_type=file_info["mime"],
            )
            return {
                "jenis": file_info["jenis"],
                "nama": file_info["nama"],
                "ok": result.get("ok", False),
                "error": result.get("error", ""),
                "versi": result.get("versi"),
            }
        except Exception as exc:
            return {
                "jenis": file_info["jenis"],
                "nama": file_info["nama"],
                "ok": False,
                "error": str(exc),
                "versi": None,
            }

    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_upload_one, f): f for f in files}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status = "✅" if result["ok"] else "❌"
            suffix = "" if result["ok"] else f": {result['error']}"
            _log(f"{status} {result['nama']}{suffix}")

    total_ok = sum(1 for result in results if result["ok"])
    return {
        "results": results,
        "total_ok": total_ok,
        "total_err": len(results) - total_ok,
        "pp_ok": True,
    }


def upload_nota_dinas_dan_email(
    kode_paket: str,
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
    log_fn=None,
) -> dict:
    """Upload Nota Dinas lalu kirim email; pembuatan paket dilakukan tombol terpisah."""
    def _log(msg):
        if log_fn:
            log_fn(msg)

    _log(f"📨 Upload Nota Dinas: {file_name}...")
    upload_result = upload_nota_dinas(
        kode_paket=kode_paket,
        file_bytes=file_bytes,
        file_name=file_name,
        mime_type=mime_type,
        log_fn=log_fn,
    )
    if not upload_result.get("ok"):
        return {
            "ok": False,
            "upload_ok": False,
            "email_ok": False,
            "upload": upload_result,
            "error": upload_result.get("error", "Upload Nota Dinas gagal."),
        }

    _log("📧 Mengirim email pemberitahuan ke Pejabat Pengadaan...")
    email_ok = kirim_email_pp(
        kode_paket,
        upload_result.get("path", ""),
        upload_result.get("fileId", ""),
        log_fn=log_fn,
    )
    if email_ok:
        _log("✅ Nota Dinas terupload dan email berhasil dikirim")
    else:
        _log("⚠️ Nota Dinas terupload, tetapi email gagal dikirim")
    return {
        "ok": bool(email_ok),
        "upload_ok": True,
        "email_ok": bool(email_ok),
        "upload": upload_result,
        "error": "" if email_ok else "Email gagal dikirim; paket belum dibuat.",
    }
