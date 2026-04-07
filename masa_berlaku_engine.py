"""
Masa Berlaku Penawaran Engine
URL target: /lelang/[ID]/edit

Alur:
1. scan_edit_form() → ambil semua field (radio, text, select, hidden)
2. auto_detect_fields() → identifikasi radio masa berlaku + number input
3. build_payload() → konstruksi POST payload dengan nilai 40
4. submit_masa_berlaku() → kirim via fetch (API) dari browser context
"""

import re
import spse_browser

# ─────────────────────────────────────────────────────────────────────────────
# JS Scan — ambil semua input field termasuk radio dan select
# ─────────────────────────────────────────────────────────────────────────────

_SCAN_JS = """() => {
    const form = document.querySelector('form');
    const csrfMeta  = document.querySelector('meta[name="csrf-token"]');
    const csrfInput = document.querySelector('input[name="_token"]');
    const csrf = csrfMeta  ? csrfMeta.content
               : csrfInput ? csrfInput.value
               : '';

    // Helper: cari label teks untuk elemen
    function getLabel(el) {
        // 1. <label for="id">
        if (el.id) {
            const lbl = document.querySelector('label[for="' + el.id + '"]');
            if (lbl) return lbl.innerText.trim();
        }
        // 2. Saudara dalam <tr> yang sama
        const tr = el.closest('tr');
        if (tr) {
            const tds = tr.querySelectorAll('td, th');
            for (const td of tds) {
                if (!td.contains(el)) return td.innerText.trim();
            }
        }
        // 3. Label ancestor
        const pl = el.closest('label');
        if (pl) return pl.innerText.replace(/\\s+/g, ' ').trim();
        // 4. Div/span sebelumnya
        const prev = el.previousElementSibling;
        if (prev && ['LABEL','SPAN','DIV','TD','TH'].includes(prev.tagName)) {
            return prev.innerText.trim();
        }
        return '';
    }

    const fields = [];

    // Radio buttons
    document.querySelectorAll('input[type="radio"]').forEach(el => {
        fields.push({
            type:     'radio',
            name:     el.name   || '',
            value:    el.value  || '',
            checked:  el.checked,
            disabled: el.disabled,
            id:       el.id     || '',
            label:    getLabel(el),
        });
    });

    // Text, number inputs (bukan hidden/submit/checkbox/radio)
    document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"])').forEach(el => {
        fields.push({
            type:        el.type        || 'text',
            name:        el.name        || '',
            value:       el.value       || '',
            placeholder: el.placeholder || '',
            disabled:    el.disabled,
            id:          el.id          || '',
            label:       getLabel(el),
        });
    });

    // Select
    document.querySelectorAll('select').forEach(el => {
        const opts = Array.from(el.options).map(o => ({ value: o.value, text: o.text, selected: o.selected }));
        fields.push({
            type:     'select',
            name:     el.name    || '',
            value:    el.value   || '',
            disabled: el.disabled,
            id:       el.id      || '',
            label:    getLabel(el),
            options:  opts,
        });
    });

    // Textarea
    document.querySelectorAll('textarea').forEach(el => {
        fields.push({
            type:     'textarea',
            name:     el.name  || '',
            value:    el.value || '',
            disabled: el.disabled,
            id:       el.id    || '',
            label:    getLabel(el),
        });
    });

    return {
        action:  form ? form.action              : window.location.href,
        method:  form ? form.method.toUpperCase(): 'POST',
        csrf:    csrf,
        url:     window.location.href,
        fields:  fields,
    };
}"""


def scan_edit_form() -> dict:
    """
    Scan halaman /lelang/[ID]/edit yang aktif di browser.
    Return: {action, method, csrf, url, fields: [...]}
    """
    page = spse_browser.halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka / halaman tidak aktif.")

    async def _do():
        return await page.evaluate(_SCAN_JS)

    return spse_browser._run(_do())


# ─────────────────────────────────────────────────────────────────────────────
# Auto-detect field masa berlaku
# ─────────────────────────────────────────────────────────────────────────────

_MASA_BERLAKU_KEYWORDS = ["masa berlaku", "masa_berlaku", "berlaku_penawaran", "berlaku penawaran"]
_HARI_KEYWORDS = ["hari", "days", "day", "jumlah"]

def _is_masa_berlaku(field: dict) -> bool:
    name_lower  = field.get("name",  "").lower()
    label_lower = field.get("label", "").lower()
    combined = name_lower + " " + label_lower
    return any(kw in combined for kw in _MASA_BERLAKU_KEYWORDS)


def auto_detect_fields(form_info: dict) -> dict:
    """
    Identifikasi otomatis:
    - radio_field: nama field radio masa berlaku
    - radio_value_40: value radio yang berisi '40' (atau kosong kalau tidak ada radio)
    - number_field: nama field angka hari (bisa sama atau berbeda)
    - ambiguous: list field yang mungkin relevan tapi tidak yakin

    Return: {
        radio_name: str|None,
        radio_value_40: str|None,
        number_name: str|None,
        all_radios: [{name, value, label, checked}, ...],  # semua radio di form
        possible_number: [{name, value, label}, ...],
        confident: bool,
    }
    """
    fields = form_info.get("fields", [])

    radios = [f for f in fields if f["type"] == "radio"]
    texts  = [f for f in fields if f["type"] in ("text", "number")]

    # Kelompokkan radio by name
    radio_groups = {}
    for r in radios:
        radio_groups.setdefault(r["name"], []).append(r)

    # Cari radio group yang relevan (nama atau label mengandung keyword)
    masa_berlaku_radio_name = None
    radio_value_40 = None

    for name, group in radio_groups.items():
        # Cek nama group
        name_match = any(kw in name.lower() for kw in _MASA_BERLAKU_KEYWORDS)
        # Cek label salah satu option
        label_match = any(_is_masa_berlaku(r) for r in group)

        if name_match or label_match:
            masa_berlaku_radio_name = name
            # Cari option yang nilainya '40'
            for r in group:
                if r["value"] == "40" or "40" in r.get("label", ""):
                    radio_value_40 = r["value"]
                    break
            # Fallback: cari option pertama yang mengandung angka 40
            if not radio_value_40:
                for r in group:
                    if re.search(r'\b40\b', r.get("label", "")):
                        radio_value_40 = r["value"]
                        break
            break

    # Cari number/text field untuk isian angka hari
    masa_berlaku_number_name = None
    possible_number = []

    for f in texts:
        if _is_masa_berlaku(f):
            masa_berlaku_number_name = f["name"]
            break
        # Kandidat: field angka kecil yang mungkin adalah hari
        name_l = f["name"].lower()
        if any(kw in name_l for kw in _HARI_KEYWORDS):
            possible_number.append(f)

    # Jika tidak ada exact match, pakai kandidat pertama
    if not masa_berlaku_number_name and possible_number:
        masa_berlaku_number_name = possible_number[0]["name"]

    confident = bool(masa_berlaku_radio_name or masa_berlaku_number_name)

    return {
        "radio_name":     masa_berlaku_radio_name,
        "radio_value_40": radio_value_40,
        "number_name":    masa_berlaku_number_name,
        "all_radios":     radios,
        "radio_groups":   {k: v for k, v in radio_groups.items()},
        "possible_number": possible_number,
        "confident":      confident,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Build Payload
# ─────────────────────────────────────────────────────────────────────────────

def build_payload(
    form_info:   dict,
    detected:    dict,
    nilai_hari:  int = 40,
    radio_name:  str | None = None,   # override manual dari UI
    radio_value: str | None = None,   # override manual
    number_name: str | None = None,   # override manual
) -> dict:
    """
    Bangun POST payload:
    - _token (CSRF)
    - radio masa berlaku → value 40 (atau sesuai override)
    - number field → '40'
    - Semua hidden input ikut disertakan
    """
    payload: dict = {}

    if form_info.get("csrf"):
        payload["_token"] = form_info["csrf"]

    # Sertakan semua hidden input (metode, _method, dll)
    page = spse_browser.halaman_aktif()
    if page:
        hidden = spse_browser._run(page.evaluate("""() =>
            Array.from(document.querySelectorAll('input[type="hidden"]'))
            .map(el => ({ name: el.name, value: el.value }))
        """))
        for h in hidden:
            if h["name"] and h["name"] != "_token":
                payload[h["name"]] = h["value"]

    # Radio
    r_name  = radio_name  or detected.get("radio_name")
    r_value = radio_value or detected.get("radio_value_40")
    if r_name and r_value:
        payload[r_name] = r_value
    elif r_name and not r_value:
        # Tidak tahu value exak → isi string angka
        payload[r_name] = str(nilai_hari)

    # Number field
    n_name = number_name or detected.get("number_name")
    if n_name:
        payload[n_name] = str(nilai_hari)

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────────────────────

def submit_masa_berlaku(form_info: dict, payload: dict) -> dict:
    """Submit payload ke endpoint form edit lelang."""
    return spse_browser.submit_via_fetch(
        endpoint_url=form_info["action"],
        payload=payload,
        method=form_info.get("method", "POST"),
    )
