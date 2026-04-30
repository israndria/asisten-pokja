import sys
import json
import asyncio
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        
        # Open a new page to avoid messing with user's tab
        page = await ctx.new_page()
        # The user has the edit page open, so we can use its ID
        # Actually the link for Uraian Singkat Pekerjaan is /tapinkab/dokumen/10088266000/uploaduraian
        url = "https://spse.inaproc.id/tapinkab/dokumen/10088266000/uploaduraian"
        
        try:
            await page.goto(url, wait_until="networkidle")
            
            JS = '''(() => {
                const result = {
                    url: window.location.href,
                    html_preview: document.body.innerHTML.substring(0, 2000),
                    tables: []
                };
                document.querySelectorAll("table").forEach((t, i) => {
                    result.tables.push({
                        id: t.id,
                        class: t.className,
                        text: t.innerText.substring(0, 200)
                    });
                });
                return result;
            })()'''
            
            res = await page.evaluate(JS)
            print(json.dumps(res, indent=2))
        finally:
            await page.close()

if __name__ == "__main__":
    asyncio.run(inspect())
