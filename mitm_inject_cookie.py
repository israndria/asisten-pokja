"""
mitm_inject_cookie.py — Inject SPSE_SESSION dari browser ke request Apendo.
Jalankan: mitmdump -p 8892 -s mitm_inject_cookie.py
"""
from mitmproxy import http
import json, os, re

LOG = os.path.join(os.path.dirname(__file__), "mitm_headers_log.json")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "spse_session.json")

entries = []

def _load_session() -> str:
    """Baca SPSE_SESSION dari file yang ditulis engine."""
    try:
        with open(SESSION_FILE) as f:
            return json.load(f).get("SPSE_SESSION", "")
    except Exception:
        return ""


def request(flow: http.HTTPFlow):
    url = flow.request.pretty_url
    if "spse.inaproc.id" not in url or "lt17" not in url:
        return

    ua = flow.request.headers.get("User-Agent", "")
    if "Apendo" not in ua:
        return

    # Inject SPSE_SESSION jika kosong
    cookie_raw = flow.request.headers.get("Cookie", "")
    spse = _load_session()

    if spse and ("SPSE_SESSION=;" in cookie_raw or "SPSE_SESSION=" not in cookie_raw):
        # Ganti atau tambahkan SPSE_SESSION
        if "SPSE_SESSION=" in cookie_raw:
            cookie_raw = re.sub(r"SPSE_SESSION=[^;]*", f"SPSE_SESSION={spse}", cookie_raw)
        else:
            cookie_raw = f"SPSE_SESSION={spse}; " + cookie_raw
        flow.request.headers["Cookie"] = cookie_raw
        print(f"[INJECT] SPSE_SESSION diinjek ke {url[:80]}")


def response(flow: http.HTTPFlow):
    url = flow.request.pretty_url
    if "spse.inaproc.id" not in url or "lt17" not in url:
        return
    if "Apendo" not in flow.request.headers.get("User-Agent", ""):
        return

    req_h = dict(flow.request.headers)
    entry = {
        "method": flow.request.method,
        "url": url,
        "status": flow.response.status_code,
        "req_headers": req_h,
        "req_body": flow.request.get_text(strict=False) or "",
    }
    entries.append(entry)
    print(f"[{flow.response.status_code}] {flow.request.method} {url[:80]}")
    sig = req_h.get("Apendo-Signature", "")
    if sig:
        print(f"  SIG: {sig}")

    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=True)
