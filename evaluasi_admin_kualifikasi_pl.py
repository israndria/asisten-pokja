"""Submit evaluasi administrasi & kualifikasi PL (Non-Tender) — centang LULUS semua peserta."""

import os
import re
import sys
import requests
from bs4 import BeautifulSoup
from contextlib import contextmanager

import spse_browser
from config import SPSE_BASE_URL


@contextmanager
def _quiet():
    _orig = sys.stderr
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
        yield
    finally:
        try:
            sys.stderr.close()
        except Exception:
            pass
        sys.stderr = _orig

BASE = SPSE_BASE_URL.rstrip("/")


def _headers(referer: str = "") -> dict:
    cookie = spse_browser.get_spse_cookies()
    return {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "Referer": referer or BASE,
    }


def scrape_peserta_evaluasi(kode_paket: str) -> dict:
    """
    Scrape tabel peserta dari /evaluasinontender/{kode_paket} via CDP (bukan requests — SPSE sering timeout).
    Return: {"ok": bool, "peserta": [{"nama", "id_nontender"}], "pesan": str}
    id_nontender = ID per peserta (bukan ID paket).
    """
    import asyncio

    url = f"{BASE}/evaluasinontender/{kode_paket}"

    async def _fetch():
        page = await spse_browser._connect_cdp_async(url, navigate=True)
        await asyncio.sleep(2)
        return await page.evaluate("""() => {
            var peserta = [];
            document.querySelectorAll('a[href]').forEach(function(a) {
                var m = a.href.match(/\\/evaluasinontender\\/(\\d+)\\/detail/);
                if (!m) return;
                var nama = a.innerText.trim();
                if (!nama) return;
                if (peserta.some(function(p) { return p.id_nontender === m[1]; })) return;
                peserta.push({nama: nama, id_nontender: m[1]});
            });
            return peserta;
        }""")

    try:
        with _quiet():
            peserta_list = spse_browser._run(_fetch())
        if not peserta_list:
            return {"ok": False, "peserta": [], "pesan": "Tidak ada peserta ditemukan"}
        return {"ok": True, "peserta": peserta_list, "pesan": f"{len(peserta_list)} peserta"}
    except Exception as e:
        return {"ok": False, "peserta": [], "pesan": str(e)}


def _scrape_form_evaluasi(id_nontender: str) -> dict:
    """
    GET /evaluasinontender/{id_nontender}/detail via CDP → scrape semua form evaluasi.
    Pakai CDP bukan requests karena SPSE sering timeout via direct HTTP.
    """
    import asyncio

    url = f"{BASE}/evaluasinontender/{id_nontender}/detail"

    async def _fetch():
        page = await spse_browser._connect_cdp_async(url, navigate=True)
        await asyncio.sleep(2)

        # Klik Validasi KSWP via dispatchEvent (tombol ada di tab tersembunyi → Playwright .click() timeout)
        # Server update hidden input[name='kswp'] via JS XHR callback setelah klik
        await page.evaluate("""async () => {
            // Aktifkan tab kualifikasi dulu agar event listener terpasang
            var tabs = Array.from(document.querySelectorAll('.nav-tabs a, .nav a'));
            var kualTab = tabs.find(function(t) { return t.innerText.toLowerCase().includes('kualifikasi'); });
            if (kualTab) kualTab.click();
            await new Promise(function(r) { setTimeout(r, 300); });

            // Dispatch click pada tombol Validasi KSWP
            var btn = Array.from(document.querySelectorAll('a')).find(function(el) {
                return el.innerText.trim() === 'Validasi KSWP';
            });
            if (btn) btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));

            // Tunggu XHR selesai + DOM update
            await new Promise(function(r) { setTimeout(r, 2500); });
        }""")
        await asyncio.sleep(0.5)

        return await page.evaluate("""() => {
            var result = {
                token: "",
                checklist_admin: [],
                checklist_kualifikasi: {
                    checklistIjin: [], checklistAdmin: [], checklistTeknis: [], kswp: ""
                },
                checklist_teknis: [],
                checklist_harga: [],
                kswp_result: null
            };
            document.querySelectorAll("form").forEach(function(form) {
                var action = form.action || "";
                var tok = form.querySelector("input[name='authenticityToken']");
                if (tok && !result.token) result.token = tok.value;

                if (action.includes("checklist_admin")) {
                    form.querySelectorAll("input[type='checkbox']").forEach(function(cb) {
                        if (cb.value) result.checklist_admin.push(cb.value);
                    });
                } else if (action.includes("checklist_kualifikasi")) {
                    form.querySelectorAll("input[type='checkbox']").forEach(function(cb) {
                        var n = cb.name || "";
                        var v = cb.value || "";
                        if (!v) return;
                        if (n.startsWith("checklistIjin")) result.checklist_kualifikasi.checklistIjin.push(v);
                        else if (n.startsWith("checklistAdmin")) result.checklist_kualifikasi.checklistAdmin.push(v);
                        else if (n.startsWith("checklistTeknis")) result.checklist_kualifikasi.checklistTeknis.push(v);
                    });
                    var kswp = form.querySelector("input[name='kswp']");
                    if (kswp) result.checklist_kualifikasi.kswp = kswp.value;
                } else if (action.includes("checklist_teknis")) {
                    form.querySelectorAll("input[type='checkbox']").forEach(function(cb) {
                        if (cb.value) result.checklist_teknis.push(cb.value);
                    });
                } else if (action.includes("checklist_harga")) {
                    form.querySelectorAll("input[type='checkbox']").forEach(function(cb) {
                        if (cb.value) result.checklist_harga.push(cb.value);
                    });
                }
            });
            return result;
        }""")

    try:
        with _quiet():
            return spse_browser._run(_fetch())
    except Exception as e:
        return {"error": str(e)}


def _post_checklist(endpoint_url: str, token: str, fields: dict, referer: str) -> dict:
    """
    POST multipart/form-data ke endpoint_url.
    fields: dict name→value atau name→list[value].
    Return: {"ok": bool, "status_code": int, "pesan": str}
    """
    try:
        data = [("authenticityToken", token)]
        for name, val in fields.items():
            if isinstance(val, list):
                for v in val:
                    data.append((name, v))
            else:
                data.append((name, val))
        data.append(("uraian", ""))

        r = requests.post(
            endpoint_url,
            data=data,
            headers={**_headers(referer), "Content-Type": None},  # requests set boundary
            timeout=15,
            allow_redirects=True,
        )
        # SPSE biasanya redirect 302 ke halaman hasil — anggap sukses
        ok = r.status_code in (200, 302, 303)
        return {"ok": ok, "status_code": r.status_code, "pesan": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "status_code": 0, "pesan": str(e)}


def submit_evaluasi_lulus_peserta(
    id_nontender: str,
    admin: bool = True,
    kualifikasi: bool = True,
    teknis: bool = False,
    harga: bool = False,
    progress_cb=None,
) -> dict:
    """
    Submit evaluasi LULUS untuk 1 peserta (admin, kualifikasi, teknis, harga).
    Semua checkbox di-centang (kirim semua value dari server).

    Return: {"ok": bool, "admin_ok": bool, "kualifikasi_ok": bool, "teknis_ok": bool, "harga_ok": bool, "pesan": str}
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    _log(f"  Scrape form evaluasi id={id_nontender}...")
    form_data = _scrape_form_evaluasi(id_nontender)
    if "error" in form_data:
        return {"ok": False, "admin_ok": False, "kualifikasi_ok": False, "teknis_ok": False, "harga_ok": False, "pesan": form_data["error"]}

    token = form_data["token"]
    referer = f"{BASE}/evaluasinontender/{id_nontender}/detail"
    admin_ok = False
    kualifikasi_ok = False
    teknis_ok = False
    harga_ok = False

    if admin:
        vals = form_data.get("checklist_admin", [])
        if vals:
            url_admin = f"{BASE}/evaluasinontender/{id_nontender}/checklist_admin"
            fields = {f"checklist[{i}]": v for i, v in enumerate(vals)}
            res = _post_checklist(url_admin, token, fields, referer)
            admin_ok = res["ok"]
            _log(f"  Admin checklist: {res['pesan']} ({'OK' if admin_ok else 'GAGAL'})")
        else:
            _log("  [skip] checklist_admin kosong")
            admin_ok = True  # tidak ada syarat admin

    if kualifikasi:
        kq = form_data.get("checklist_kualifikasi", {})
        url_kual = f"{BASE}/evaluasinontender/{id_nontender}/checklist_kualifikasi"
        fields_kq = {}
        for i, v in enumerate(kq.get("checklistIjin", [])):
            fields_kq[f"checklistIjin[{i}]"] = v
        for i, v in enumerate(kq.get("checklistAdmin", [])):
            fields_kq[f"checklistAdmin[{i}]"] = v
        for i, v in enumerate(kq.get("checklistTeknis", [])):
            fields_kq[f"checklistTeknis[{i}]"] = v
        if kq.get("kswp"):
            fields_kq["kswp"] = kq["kswp"]
        if fields_kq:
            res = _post_checklist(url_kual, token, fields_kq, referer)
            kualifikasi_ok = res["ok"]
            _log(f"  Kualifikasi checklist: {res['pesan']} ({'OK' if kualifikasi_ok else 'GAGAL'})")
        else:
            _log("  [skip] checklist_kualifikasi kosong")
            kualifikasi_ok = True

    if teknis:
        vals_tek = form_data.get("checklist_teknis", [])
        if vals_tek:
            url_tek = f"{BASE}/evaluasinontender/{id_nontender}/checklist_teknis"
            fields_tek = {f"checklist[{i}]": v for i, v in enumerate(vals_tek)}
            res_tek = _post_checklist(url_tek, token, fields_tek, referer)
            teknis_ok = res_tek["ok"]
            _log(f"  Teknis checklist: {res_tek['pesan']} ({'OK' if teknis_ok else 'GAGAL'})")
        else:
            _log("  [skip] checklist_teknis kosong")
            teknis_ok = True

    if harga:
        vals_hrg = form_data.get("checklist_harga", [])
        if vals_hrg:
            url_hrg = f"{BASE}/evaluasinontender/{id_nontender}/checklist_harga"
            fields_hrg = {f"checklist[{i}]": v for i, v in enumerate(vals_hrg)}
            fields_hrg["lulus"] = "true"  # Radio button lulus
            res_hrg = _post_checklist(url_hrg, token, fields_hrg, referer)
            harga_ok = res_hrg["ok"]
            _log(f"  Harga checklist: {res_hrg['pesan']} ({'OK' if harga_ok else 'GAGAL'})")
        else:
            _log("  [skip] checklist_harga kosong")
            harga_ok = True

    ok = (not admin or admin_ok) and \
         (not kualifikasi or kualifikasi_ok) and \
         (not teknis or teknis_ok) and \
         (not harga or harga_ok)

    return {
        "ok": ok,
        "admin_ok": admin_ok,
        "kualifikasi_ok": kualifikasi_ok,
        "teknis_ok": teknis_ok,
        "harga_ok": harga_ok,
        "pesan": "Lulus" if ok else "Sebagian gagal",
        "token": token,
    }


def evaluasi_batch_lulus(
    kode_paket: str,
    admin: bool = True,
    kualifikasi: bool = True,
    teknis: bool = False,
    harga: bool = False,
    progress_cb=None,
) -> dict:
    """
    Scrape list peserta dari /evaluasinontender/{kode_paket} lalu submit LULUS semua.

    Return: {
        "ok": bool,
        "hasil": [{"nama", "id_nontender", "admin_ok", "kualifikasi_ok", "teknis_ok", "harga_ok", "pesan"}],
        "ringkasan": str,
    }
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    _log(f"Scrape peserta evaluasi paket {kode_paket}...")
    res_peserta = scrape_peserta_evaluasi(kode_paket)
    if not res_peserta["ok"]:
        return {"ok": False, "hasil": [], "ringkasan": res_peserta["pesan"]}

    peserta_list = res_peserta["peserta"]
    _log(f"{len(peserta_list)} peserta ditemukan")

    hasil = []
    last_token = ""
    for p in peserta_list:
        _log(f"Peserta: {p['nama']} (id={p['id_nontender']})")
        res = submit_evaluasi_lulus_peserta(
            p["id_nontender"],
            admin=admin,
            kualifikasi=kualifikasi,
            teknis=teknis,
            harga=harga,
            progress_cb=progress_cb
        )
        if res.get("token"):
            last_token = res["token"]
        hasil.append({
            "nama": p["nama"],
            "id_nontender": p["id_nontender"],
            "admin_ok": res.get("admin_ok", False),
            "kualifikasi_ok": res.get("kualifikasi_ok", False),
            "teknis_ok": res.get("teknis_ok", False),
            "harga_ok": res.get("harga_ok", False),
            "pesan": res.get("pesan", ""),
        })

    n_ok = sum(
        1 for h in hasil
        if (not admin or h["admin_ok"]) and
           (not kualifikasi or h["kualifikasi_ok"]) and
           (not teknis or h["teknis_ok"]) and
           (not harga or h["harga_ok"])
    )

    lbls = []
    if admin: lbls.append("admin")
    if kualifikasi: lbls.append("kual")
    if teknis: lbls.append("teknis")
    if harga: lbls.append("harga")
    lbl_str = "+".join(lbls)

    ringkasan = f"{n_ok}/{len(hasil)} peserta lulus {lbl_str}"

    # ── Auto-konfirmasi verifikasi data SIKaP (tombol Terverifikasi) di halaman list utama ──
    if kualifikasi and any(h["kualifikasi_ok"] for h in hasil):
        _log("Auto-konfirmasi verifikasi data SIKaP...")
        try:
            import asyncio
            url_list = f"{BASE}/evaluasinontender/{kode_paket}"

            async def _process_sikap():
                page = await spse_browser._connect_cdp_async(url_list, navigate=True)
                await asyncio.sleep(2)
                return await page.evaluate("""() => {
                    var token = "";
                    var f = document.querySelector("input[name='authenticityToken']");
                    if (f) token = f.value;

                    var urls = Array.from(document.querySelectorAll('a'))
                        .filter(el => el.href && el.href.includes('konfirmasi_verifikasi'))
                        .map(el => el.href);

                    return {token: token, urls: urls};
                }""")

            sikap_data = spse_browser._run(_process_sikap())
            token_sikap = sikap_data.get("token") or last_token
            urls_konfirm = sikap_data.get("urls", [])

            if urls_konfirm and token_sikap:
                _log(f"  Menemukan {len(urls_konfirm)} tombol konfirmasi SIKaP. Memproses...")
                for s_url in urls_konfirm:
                    m_psr = re.search(r"/evaluasinontender/(\d+)/konfirmasi_verifikasi", s_url)
                    if m_psr:
                        psr_id = m_psr.group(1)
                        url_sikap_submit = f"{BASE}/evaluasinontender/{kode_paket}/submit_konfirmasi_verifikasi_sikap"
                        payload_sikap = {
                            "authenticityToken": token_sikap,
                            "psr_id": psr_id,
                            "simpan": "simpan"
                        }
                        res_sikap = requests.post(
                            url_sikap_submit,
                            data=payload_sikap,
                            headers={**_headers(url_list), "Content-Type": "application/x-www-form-urlencoded"},
                            timeout=15,
                            allow_redirects=False
                        )
                        if res_sikap.status_code in (200, 302):
                            _log(f"    Penyedia ID {psr_id}: Berhasil verifikasi data SIKaP")
                        else:
                            _log(f"    Penyedia ID {psr_id}: Gagal verifikasi (HTTP {res_sikap.status_code})")
            else:
                _log("  [skip] Tidak ada tombol konfirmasi SIKaP / token CSRF tidak ditemukan")
        except Exception as e:
            _log(f"  Gagal auto-konfirmasi SIKaP: {e}")

    return {
        "ok": n_ok == len(hasil),
        "hasil": hasil,
        "ringkasan": ringkasan,
    }
