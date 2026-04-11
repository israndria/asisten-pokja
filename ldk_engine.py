"""
LDK Engine — scan form HTML, klasifikasi checkbox, build payload, submit.

Dipanggil dari app.py (Tab LDK Auto-fill).
"""

from ldk_config import AUTO_CHECK_KEYWORDS, CHECK_AND_FILL, SKIP_KEYWORDS, IJIN_USAHA_DEFAULT
import spse_browser


# ─────────────────────────────────────────────────────────────────────────────
# Scan Form HTML
# ─────────────────────────────────────────────────────────────────────────────

_SCAN_JS = """() => {
    const form = document.querySelector('form');
    // CSRF: coba berbagai kemungkinan
    const csrfMeta  = document.querySelector('meta[name="csrf-token"]');
    const csrfInput = document.querySelector('input[name="_token"]') ||
                      document.querySelector('input[name="authenticityToken"]');
    const csrf = csrfMeta  ? csrfMeta.content
               : csrfInput ? csrfInput.value
               : '';

    const checkboxes = [];
    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        // ── Ambil label teks ──────────────────────────────────────────────
        let label = '';

        // 1. <label for="id">
        if (cb.id) {
            const lbl = document.querySelector('label[for="' + cb.id + '"]');
            if (lbl) label = lbl.innerText.trim();
        }
        // 2. Saudara <td> dalam <tr> yang sama
        if (!label) {
            const tr = cb.closest('tr');
            if (tr) {
                const tds = tr.querySelectorAll('td');
                for (const td of tds) {
                    if (!td.contains(cb)) { label = td.innerText.trim(); break; }
                }
            }
        }
        // 3. <label> ancestor
        if (!label) {
            const pl = cb.closest('label');
            if (pl) label = pl.innerText.replace(/\\s+/g, ' ').trim();
        }

        // ── Cari text input / textarea terkait (dalam row yang sama) ─────
        let textInputName = null;
        const container = cb.closest('tr') || cb.closest('div') || cb.parentElement;
        if (container) {
            const txt = container.querySelector('input[type="text"], textarea');
            if (txt) textInputName = txt.name || txt.id || null;
        }

        // ── Hidden fields di row yang sama ────────────────────────────────
        const hiddenFields = {};
        if (container) {
            container.querySelectorAll('input[type="hidden"]').forEach(h => {
                hiddenFields[h.name] = h.value;
            });
        }

        checkboxes.push({
            name:          cb.name    || '',
            value:         cb.value   || '',
            checked:       cb.checked,
            disabled:      cb.disabled,
            label:         label,
            textInputName: textInputName,
            hiddenFields:  hiddenFields,
        });
    });

    return {
        action:    form ? form.action              : window.location.href,
        method:    form ? form.method.toUpperCase(): 'POST',
        csrf:      csrf,
        checkboxes: checkboxes,
    };
}"""


def scan_ldk_form() -> dict:
    """
    Scan halaman LDK yang aktif di browser.
    Return: {action, method, csrf, checkboxes: [...]}
    """
    page = spse_browser.halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka / halaman tidak aktif.")

    async def _do():
        return await page.evaluate(_SCAN_JS)

    return spse_browser._run(_do())


# ─────────────────────────────────────────────────────────────────────────────
# Klasifikasi Checkbox
# ─────────────────────────────────────────────────────────────────────────────

def _matches(label: str, keywords: list[str]) -> bool:
    label_lower = label.lower()
    return any(kw.lower() in label_lower for kw in keywords)


def classify_checkboxes(form_info: dict) -> dict:
    """
    Klasifikasikan semua checkbox berdasarkan ldk_config.
    Return:
    {
        "locked":         [cb, ...],        # disabled oleh SPSE
        "auto_check":     [cb, ...],        # centang saja
        "check_and_fill": [(cb, cfg), ...], # centang + isi teks
        "skip":           [cb, ...],        # tidak disentuh
        "unknown":        [cb, ...],        # tidak cocok keyword manapun → skip aman
    }
    """
    result = {
        "locked": [],
        "auto_check": [],
        "check_and_fill": [],
        "skip": [],
        "unknown": [],
    }

    for cb in form_info.get("checkboxes", []):
        # 1. Disabled (locked oleh SPSE) → skip
        # Juga cek class 'kso' (konsorsium) dan keyword tertentu
        is_kso = cb.get("className", "") == "kso"
        if cb["disabled"] or is_kso:
            result["locked"].append(cb)
            continue

        # 2. Keyword skip → tidak disentuh
        if _matches(cb["label"], SKIP_KEYWORDS):
            result["skip"].append(cb)
            continue

        # 3. Check + fill
        matched_fill = False
        for cfg in CHECK_AND_FILL:
            if cfg["keyword"].lower() in cb["label"].lower():
                result["check_and_fill"].append((cb, cfg))
                matched_fill = True
                break
        if matched_fill:
            continue

        # 4. Auto check
        if _matches(cb["label"], AUTO_CHECK_KEYWORDS):
            result["auto_check"].append(cb)
            continue

        # 5. Tidak cocok → unknown (skip aman, jangan submit sembarangan)
        result["unknown"].append(cb)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Build Payload
# ─────────────────────────────────────────────────────────────────────────────

def build_payload(form_info: dict, classified: dict, ijin_usaha: dict | None = None) -> dict:
    """
    Konstruksi POST payload dari hasil klasifikasi.
    - CSRF token selalu disertakan
    - Hanya checkbox auto_check + check_and_fill yang di-include
    - Checkbox dengan name sama (multi-value) digabung jadi list
    - Izin Usaha fields selalu di-include (wajib)
    """
    payload = {}

    if form_info.get("csrf"):
        payload["_token"] = form_info["csrf"]

    def _add(name: str, value: str):
        if not name:
            return
        if name in payload:
            existing = payload[name]
            if isinstance(existing, list):
                existing.append(value)
            else:
                payload[name] = [existing, value]
        else:
            payload[name] = value

    # Auto-check
    for cb in classified["auto_check"]:
        _add(cb["name"], cb["value"])

    # Check + fill
    for cb, cfg in classified["check_and_fill"]:
        _add(cb["name"], cb["value"])
        if cb["textInputName"]:
            payload[cb["textInputName"]] = cfg["text"]

    # Izin Usaha (wajib)
    ijin = ijin_usaha or IJIN_USAHA_DEFAULT
    payload["ijin[0].chk_nama"] = ijin.get("nama", IJIN_USAHA_DEFAULT["nama"])
    payload["ijin[0].chk_klasifikasi"] = ijin.get("klasifikasi", IJIN_USAHA_DEFAULT["klasifikasi"])

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────────────────────

def submit_ldk(form_info: dict, payload: dict, ijin_usaha: dict | None = None) -> dict:
    """
    Submit LDK dengan 2 langkah:
    1. Klik checkbox + isi Izin Usaha DI browser (client-side)
    2. Submit form secara native (bukan fetch) agar SPSE proses dengan benar
    """
    page = spse_browser.halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")

    # Step 1: Klik checkbox yang harus dicentang
    checkbox_items = []
    for name, val in payload.items():
        if name.startswith("syaratAdmin") or name.startswith("syaratTeknis"):
            if not isinstance(val, list):
                checkbox_items.append({"name": name, "value": str(val)})

    if checkbox_items:
        spse_browser._run(page.evaluate("""(items) => {
            const clicked = [];
            items.forEach(item => {
                document.querySelectorAll(`input[type="checkbox"][name="${item.name}"][value="${item.value}"]`).forEach(cb => {
                    if (!cb.checked && !cb.disabled) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                        clicked.push(item.name);
                    }
                });
            });
            return clicked;
        }""", checkbox_items))

    # Step 1b: Isi Izin Usaha fields
    ijin = ijin_usaha or IJIN_USAHA_DEFAULT
    spse_browser._run(page.evaluate("""(ijin) => {
        const namaInput = document.querySelector('input[name="ijin[0].chk_nama"]');
        const klasInput = document.querySelector('input[name="ijin[0].chk_klasifikasi"]');
        if (namaInput) { namaInput.value = ijin.nama; namaInput.dispatchEvent(new Event('input', {bubbles:true})); }
        if (klasInput) { klasInput.value = ijin.klasifikasi; klasInput.dispatchEvent(new Event('input', {bubbles:true})); }
    }""", ijin))

    # Step 2: Submit form secara native (bukan fetch)
    spse_browser._run(page.evaluate("""() => {
        const form = document.querySelector('form');
        if (!form) return { ok: false, error: 'Form tidak ditemukan' };
        form.submit();
    }"""))

    # Tunggu halaman berubah
    spse_browser._run(page.wait_for_timeout(3000))

    return {
        "ok": True,
        "status": 200,
        "url": spse_browser._run(page.evaluate("() => window.location.href")),
    }
