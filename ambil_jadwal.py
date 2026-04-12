"""Ambil konten halaman jadwal via Chrome DevTools Protocol (HTTP-based)."""
import subprocess
import json
import sys

CDP_PORT = 9222

def devtools_command(target_id, method, params=None):
    """Kirim command ke Chrome DevTools via chrome-remote-debugging."""
    import asyncio
    import websockets
    
    async def _run():
        url = f"ws://127.0.0.1:{CDP_PORT}/devtools/page/{target_id}"
        async with websockets.connect(url) as ws:
            cmd = {
                "id": 1,
                "method": method,
                "params": params or {}
            }
            await ws.send(json.dumps(cmd))
            resp = json.loads(await ws.recv())
            return resp
    
    return asyncio.get_event_loop().run_until_complete(_run())

def main():
    # Get tab info
    import urllib.request
    tabs = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{CDP_PORT}/json').read())
    target = None
    for t in tabs:
        if 'jadwal' in t.get('url', ''):
            target = t
            break
    
    if not target:
        print("Tab jadwal tidak ditemukan!")
        print("Tabs yang ada:")
        for i, t in enumerate(tabs):
            if t['type'] == 'page':
                print(f"  [{i}] {t['title'][:60]} | {t['url'][:100]}")
        return
    
    target_id = target['id']
    print(f"Target: {target['title']}")
    print(f"ID: {target_id}")
    
    # Ambil HTML via DevTools
    try:
        result = devtools_command(target_id, "Runtime.evaluate", {
            "expression": "document.documentElement.outerHTML",
            "returnByValue": True
        })
        
        html = result['result']['result']['value']
        print(f"\nHTML length: {len(html):,}")
        
        with open("jadwal_debug.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved: jadwal_debug.html")
        
        # Ambil teks juga
        text_result = devtools_command(target_id, "Runtime.evaluate", {
            "expression": "document.body.innerText",
            "returnByValue": True
        })
        text = text_result['result']['result']['value']
        print(f"\nText length: {len(text):,}")
        
        with open("jadwal_debug_text.txt", "w", encoding="utf-8") as f:
            f.write(text)
        print("Saved: jadwal_debug_text.txt")
        
        # Tampilkan 3000 karakter pertama
        print("\n" + "="*60)
        print("BODY TEXT (first 3000 chars):")
        print("="*60)
        print(text[:3000])
        
    except Exception as e:
        print(f"Error: {e}")
        print("Mungkin perlu install websockets: pip install websockets")

if __name__ == "__main__":
    main()
