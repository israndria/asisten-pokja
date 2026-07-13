"""Download Summary Non Tender per paket PL."""

import os
import re
from urllib.parse import unquote

import requests

from config import SPSE_BASE_URL


def download_summary_nontender(kode_paket: str, folder_paket: str, cookie_str: str) -> dict:
    """Download PDF Summary Non Tender ke folder BA paket."""
    if not folder_paket or not os.path.isdir(folder_paket):
        return {"ok": False, "pesan": "Folder paket belum ditemukan"}
    url = f"{SPSE_BASE_URL}admin/utility/viewpdfpl?id={kode_paket}"
    try:
        response = requests.get(
            url,
            headers={
                "Cookie": cookie_str,
                "User-Agent": "Mozilla/5.0",
                "Referer": f"{SPSE_BASE_URL}nontender/{kode_paket}",
            },
            timeout=60,
        )
        content_type = response.headers.get("Content-Type", "").lower()
        if response.status_code != 200 or "pdf" not in content_type:
            return {"ok": False, "pesan": f"HTTP {response.status_code} bukan PDF ({content_type})"}

        disposition = response.headers.get("Content-Disposition", "")
        match = re.search(r"filename\s*=\s*\"?([^\";]+)", disposition, re.I)
        filename = unquote(match.group(1).strip()) if match else f"Summary-Report-{kode_paket}.pdf"
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename).strip() or f"Summary-Report-{kode_paket}.pdf"
        target_dir = os.path.join(folder_paket, "7. Berita Acara + Summary Non Tender")
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, filename)
        with open(target, "wb") as handle:
            handle.write(response.content)
        return {"ok": True, "path": target, "bytes": len(response.content), "pesan": f"PDF disimpan: {target}"}
    except Exception as e:
        return {"ok": False, "pesan": f"Download summary gagal: {e}"}
