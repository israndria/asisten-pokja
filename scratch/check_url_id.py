import sys
import json
import asyncio
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        # Visit the URL constructed by my script
        url = "https://spse.inaproc.id/tapinkab/dokumen/10092474000/uploaduraian"
        
        try:
            await page.goto(url, wait_until="networkidle")
            res = await page.evaluate('() => document.body.innerHTML.substring(0, 1000)')
            print(res)
        finally:
            await page.close()

if __name__ == "__main__":
    asyncio.run(inspect())
