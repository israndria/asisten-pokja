import json, re

with open('mitm_response_log.json', encoding='utf-8') as f:
    raw = f.read()

# Parse manual entry per entry
entries = []
depth = 0
start = None
for i, c in enumerate(raw):
    if c == '{':
        if depth == 0:
            start = i
        depth += 1
    elif c == '}':
        depth -= 1
        if depth == 0 and start is not None:
            try:
                obj = json.loads(raw[start:i+1])
                entries.append(obj)
            except:
                pass
            start = None

print(f"Total entries: {len(entries)}")
for e in entries:
    req_h = e.get('req_headers', {})
    sig = req_h.get('Apendo-Signature', '')
    ua = req_h.get('User-Agent', '')
    cookie = req_h.get('Cookie', '')
    url = e.get('url', '')
    if sig or '80ed3c39' in url or 'lt17' in url:
        print(f"\nURL: {url}")
        print(f"STATUS: {e.get('status')}")
        print(f"UA: {ua}")
        print(f"SIG: {sig}")
        print(f"COOKIE: {cookie[:100]}")
