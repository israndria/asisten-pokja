import sys
import json
import asyncio
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        
        # Cari page edit
        page = next((p for p in ctx.pages if '10092474000/edit' in p.url), None)
        if not page:
            print("Page not found")
            return

        JS = '''(() => {
            const result = {
                url: window.location.href,
                links: []
            };
            document.querySelectorAll("a[href]").forEach(el => {
                result.links.push({
                    text: el.innerText.trim(),
                    href: el.getAttribute("href"),
                    id: el.id,
                    class: el.className
                });
            });
            return result;
        })()'''
        
        res = await page.evaluate(JS)
        print(json.dumps(res, indent=2))

if __name__ == "__main__":
    asyncio.run(inspect())
