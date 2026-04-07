"""
Checklist Engine — scan form HTML, klasifikasi checkbox, build payload, submit.

URL target: /dokumen/[ID]/checklist
Dipanggil dari app.py (Tab Checklist Dokumen Penawaran).

Sama dengan LDK engine, tapi tanpa CHECK_AND_FILL (checklist ini hanya centang).
"""

from checklist_config import AUTO_CHECK_KEYWORDS, SKIP_KEYWORDS
import spse_browser


# ─────────────────────────────────────────────────────────────────────────────
# Scan Form HTML (sama persis dengan ldk_engine)
# ─────────────────────────────────────────────────────────────────────────────

_SCAN_JS = """() => {
    const form = document.querySelector('form');
    const csrfMeta  = document.querySelector('meta[name="csrf-token"]');
    const csrfInput = document.querySelector('input[name="_token"]');
    const csrf = csrfMeta  ? csrfMeta.content
               : csrfInput ? csrfInput.value
               : '';

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

        checkboxes.push({
            name:    cb.name    || '',
            value:   cb.value   || '',
            checked: cb.checked,
            disabled: cb.disabled,
            label:   label,
        });
    });

    return {
        action:     form ? form.action               : window.location.href,
        method:     form ? form.method.toUpperCase() : 'POST',
        csrf:       csrf,
        checkboxes: checkboxes,
    };
}"""


def scan_checklist_form() -> dict:
    """
    Scan halaman checklist yang aktif di browser.
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
    Klasifikasikan semua checkbox berdasarkan checklist_config.
    Return:
    {
        "locked":      [cb, ...],   # disabled oleh SPSE
        "auto_check":  [cb, ...],   # centang saja
        "skip":        [cb, ...],   # tidak disentuh (usaha besar, dll)
        "unknown":     [cb, ...],   # tidak cocok keyword manapun
    }
    """
    result = {
        "locked":     [],
        "auto_check": [],
        "skip":       [],
        "unknown":    [],
    }

    for cb in form_info.get("checkboxes", []):
        if cb["disabled"]:
            result["locked"].append(cb)
            continue

        if _matches(cb["label"], SKIP_KEYWORDS):
            result["skip"].append(cb)
            continue

        if _matches(cb["label"], AUTO_CHECK_KEYWORDS):
            result["auto_check"].append(cb)
            continue

        result["unknown"].append(cb)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Build Payload
# ─────────────────────────────────────────────────────────────────────────────

def build_payload(form_info: dict, classified: dict) -> dict:
    """
    Konstruksi POST payload dari hasil klasifikasi.
    Hanya checkbox auto_check yang di-include.
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

    for cb in classified["auto_check"]:
        _add(cb["name"], cb["value"])

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────────────────────

def submit_checklist(form_info: dict, payload: dict) -> dict:
    """Submit payload ke SPSE via API (dari dalam browser context)."""
    return spse_browser.submit_via_fetch(
        endpoint_url=form_info["action"],
        payload=payload,
        method=form_info.get("method", "POST"),
    )
