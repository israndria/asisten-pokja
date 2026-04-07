"""
LDK Engine — scan form HTML, klasifikasi checkbox, build payload, submit.

Dipanggil dari app.py (Tab LDK Auto-fill).
"""

from ldk_config import AUTO_CHECK_KEYWORDS, CHECK_AND_FILL, SKIP_KEYWORDS
import spse_browser


# ─────────────────────────────────────────────────────────────────────────────
# Scan Form HTML
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

        checkboxes.push({
            name:          cb.name    || '',
            value:         cb.value   || '',
            checked:       cb.checked,
            disabled:      cb.disabled,
            label:         label,
            textInputName: textInputName,
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
        if cb["disabled"]:
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

def build_payload(form_info: dict, classified: dict) -> dict:
    """
    Konstruksi POST payload dari hasil klasifikasi.
    - CSRF token selalu disertakan
    - Hanya checkbox auto_check + check_and_fill yang di-include
    - Checkbox dengan name sama (multi-value) digabung jadi list
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

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────────────────────

def submit_ldk(form_info: dict, payload: dict) -> dict:
    """Submit payload ke SPSE via API (dari dalam browser context)."""
    return spse_browser.submit_via_fetch(
        endpoint_url=form_info["action"],
        payload=payload,
        method=form_info.get("method", "POST"),
    )
