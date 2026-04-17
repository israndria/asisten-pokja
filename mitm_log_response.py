"""
mitm_log_response.py — Capture RESPONSE body dari /lt17 endpoints
Jalankan: mitmdump -p 8888 -s mitm_log_response.py
"""
from mitmproxy import http
import json, os

LOG = os.path.join(os.path.dirname(__file__), "mitm_headers_log.json")
entries = []

FILTER_KEYWORDS = ["/lt17"]

def response(flow: http.HTTPFlow):
    url = flow.request.pretty_url
    if not any(k in url for k in FILTER_KEYWORDS):
        return

    method = flow.request.method
    status = flow.response.status_code
    req_headers = dict(flow.request.headers)
    req_body = flow.request.get_text(strict=False) or ""

    entry = {
        "method": method,
        "url": url,
        "status": status,
        "req_headers": req_headers,
        "req_body": req_body[:500],
    }
    entries.append(entry)

    print(f"\n[{status}] {method} {url}")
    for k, v in req_headers.items():
        print(f"  {k}: {v}")

    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=True)
