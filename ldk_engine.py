"""
LDK Engine v3 — Multi-row Izin Usaha + Kinerja Penyedia.

Dipanggil dari app.py (Tab LDK Auto-fill).
"""

from ldk_config import AUTO_CHECK_KEYWORDS, CHECK_AND_FILL, SKIP_KEYWORDS, IJIN_USAHA_DEFAULT
import spse_browser


# ─────────────────────────────────────────────────────────────────────────────
# Scan Form HTML
# ─────────────────────────────────────────────────────────────────────────────

_SCAN_JS = """() => {
    const form = document.querySelector('form');
    const csrfInput = document.querySelector('input[name="_token"]') ||
                      document.querySelector('input[name="authenticityToken"]');
    const csrf = csrfInput ? csrfInput.value : '';

    const checkboxes = [];
    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        let label = '';
        if (cb.id) {
            const lbl = document.querySelector('label[for="' + cb.id + '"]');
            if (lbl) label = lbl.innerText.trim();
        }
        if (!label) {
            const tr = cb.closest('tr');
            if (tr) {
                const tds = tr.querySelectorAll('td');
                for (const td of tds) {
                    if (!td.contains(cb)) { label = td.innerText.trim(); break; }
                }
            }
        }
        if (!label) {
            const pl = cb.closest('label');
            if (pl) label = pl.innerText.replace(/\\s+/g, ' ').trim();
        }

        let textInputName = null;
        const container = cb.closest('tr') || cb.closest('div') || cb.parentElement;
        if (container) {
            const txt = container.querySelector('input[type="text"], textarea');
            if (txt) textInputName = txt.name || txt.id || null;
        }

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
            className:     cb.className || '',
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
    result = {
        "locked": [],
        "auto_check": [],
        "check_and_fill": [],
        "skip": [],
        "unknown": [],
    }

    for cb in form_info.get("checkboxes", []):
        is_kso = cb.get("className", "") == "kso"
        if cb["disabled"] or is_kso:
            result["locked"].append(cb)
            continue

        if _matches(cb["label"], SKIP_KEYWORDS):
            result["skip"].append(cb)
            continue

        matched_fill = False
        for cfg in CHECK_AND_FILL:
            if cfg["keyword"].lower() in cb["label"].lower():
                result["check_and_fill"].append((cb, cfg))
                matched_fill = True
                break
        if matched_fill:
            continue

        if _matches(cb["label"], AUTO_CHECK_KEYWORDS):
            result["auto_check"].append(cb)
            continue

        result["unknown"].append(cb)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Build Payload
# ─────────────────────────────────────────────────────────────────────────────

def build_payload(
    form_info: dict,
    classified: dict,
    ijin_usaha_rows: list[dict] | None = None,
    kinerja_text: str = "",
) -> dict:
    """
    Konstruksi POST payload.
    - Multi-row Izin Usaha
    - Kinerja Penyedia (check + fill text)
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

    # Multi-row Izin Usaha
    rows = ijin_usaha_rows or [IJIN_USAHA_DEFAULT]
    for i, row in enumerate(rows):
        payload[f"ijin[{i}].chk_nama"] = row.get("jenis_izin", "")
        payload[f"ijin[{i}].chk_klasifikasi"] = row.get("klasifikasi", "")

    # Kinerja Penyedia text (jika ada)
    if kinerja_text:
        payload["kinerja_text"] = kinerja_text

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────────────────────

def submit_ldk(
    form_info: dict,
    payload: dict,
    ijin_usaha_rows: list[dict] | None = None,
    kinerja_text: str = "",
    add_kinerja: bool = False,
) -> dict:
    """
    Submit LDK dengan langkah:
    1. Klik checkbox yang harus dicentang
    2. Isi multi-row Izin Usaha
    3. Jika add_kinerja: klik "Tambah Syarat Teknis" + isi Kinerja Penyedia
    4. Submit form secara native
    """
    page = spse_browser.halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")

    # Step 1: Klik checkbox
    checkbox_items = []
    for name, val in payload.items():
        if name.startswith("syaratAdmin") or name.startswith("syaratTeknis"):
            if not isinstance(val, list):
                checkbox_items.append({"name": name, "value": str(val)})

    if checkbox_items:
        spse_browser._run(page.evaluate("""(items) => {
            items.forEach(item => {
                document.querySelectorAll(`input[type="checkbox"][name="${item.name}"][value="${item.value}"]`).forEach(cb => {
                    if (!cb.checked && !cb.disabled) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                });
            });
        }""", checkbox_items))

    # Step 2: Isi multi-row Izin Usaha
    rows = ijin_usaha_rows or [IJIN_USAHA_DEFAULT]
    for i, row in enumerate(rows):
        spse_browser._run(page.evaluate("""(i, row) => {
            const namaInput = document.querySelector(`input[name="ijin[${i}].chk_nama"]`);
            const klasInput = document.querySelector(`input[name="ijin[${i}].chk_klasifikasi"]`);
            if (namaInput) { namaInput.value = row.jenis_izin || ''; namaInput.dispatchEvent(new Event('input', {bubbles:true})); }
            if (klasInput) { klasInput.value = row.klasifikasi || ''; klasInput.dispatchEvent(new Event('input', {bubbles:true})); }
        }""", i, row))

    # Step 3: Jika perlu tambah Kinerja Penyedia
    if add_kinerja and kinerja_text:
        # Klik "Tambah Syarat Teknis"
        tambah_btn = page.query_selector('button#tambahSyaratTeknis, button:has-text("Tambah Syarat Teknis")')
        if tambah_btn:
            tambah_btn.click()
            spse_browser._run(page.wait_for_timeout(2000))
        
        # Isi checkbox + text Kinerja Penyedia
        spse_browser._run(page.evaluate("""(text) => {
            // Cari checkbox kinerja penyedia yang baru ditambahkan
            const allCbs = document.querySelectorAll('input[type="checkbox"]');
            let targetCb = null;
            allCbs.forEach(cb => {
                if (cb.name.includes('syaratTeknis') && !cb.checked && !cb.disabled) {
                    // Cek apakah label mengandung "kinerja"
                    let label = '';
                    const tr = cb.closest('tr');
                    if (tr) {
                        const tds = tr.querySelectorAll('td');
                        for (const td of tds) {
                            if (!td.contains(cb)) { label = td.innerText.trim(); break; }
                        }
                    }
                    if (label.toLowerCase().includes('kinerja')) {
                        targetCb = cb;
                    }
                }
            });
            
            if (targetCb) {
                targetCb.checked = true;
                targetCb.dispatchEvent(new Event('change', { bubbles: true }));
                
                // Isi text jika ada textarea/input
                const container = targetCb.closest('tr') || targetCb.parentElement;
                if (container) {
                    const txt = container.querySelector('input[type="text"], textarea');
                    if (txt) {
                        txt.value = text;
                        txt.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                }
            }
        }""", kinerja_text))

    # Step 4: Submit form native
    spse_browser._run(page.evaluate("""() => {
        const form = document.querySelector('form');
        if (!form) return { ok: false, error: 'Form tidak ditemukan' };
        form.submit();
    }"""))

    spse_browser._run(page.wait_for_timeout(3000))

    return {
        "ok": True,
        "status": 200,
        "url": spse_browser._run(page.evaluate("() => window.location.href")),
    }
