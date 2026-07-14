"""Finalisasi data paket untuk dibaca Excel.

Publish hanya memverifikasi data yang sudah tersimpan, lalu menulis manifest
timestamp ke Supabase dan sidecar lokal paket. Tidak melakukan scrape/POST SPSE.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import sb


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _write_sidecar(folder_paket: str | None, manifest: dict) -> str | None:
    if not folder_paket:
        return None
    root = Path(folder_paket)
    if not root.is_dir():
        return None
    path = root / "_workflow_publish.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def get_manifest(kode_tender: str, folder_paket: str | None = None) -> dict:
    """Ambil manifest lokal jika ada, fallback ke data_snapshot Supabase."""
    if folder_paket:
        path = Path(folder_paket) / "_workflow_publish.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
    try:
        row = (
            sb().table("draft_paket")
            .select("data_snapshot")
            .eq("kode_tender", kode_tender)
            .limit(1)
            .execute()
        )
        return _as_dict((row.data or [{}])[0].get("data_snapshot", {})).get("_workflow", {})
    except Exception:
        return {}


def publish_paket(
    kode_tender: str,
    folder_paket: str | None,
    peserta_terpilih: list[dict],
) -> dict:
    """Validasi data tersimpan, lalu publish manifest paket."""
    if not kode_tender:
        return {"ok": False, "error": "kode_tender kosong"}

    selected_ids = {str(p.get("kualifikasi_id", "")) for p in peserta_terpilih if p.get("kualifikasi_id")}
    try:
        client = sb()
        kk = client.table("kk_evaluasi_peserta").select("urutan,nama,updated_at").eq(
            "kode_tender", kode_tender
        ).order("urutan").limit(3).execute().data or []
        identitas = client.table("peserta_identitas").select("peserta_id,nama_perusahaan").eq(
            "kode_tender", kode_tender
        ).limit(3).execute().data or []
        harga = client.table("harga_penawaran").select(
            "peserta_id,nama_peserta,total_penawaran"
        ).eq("kode_tender", kode_tender).limit(1000).execute().data or []

        harga_ids = {str(row.get("peserta_id", "")) for row in harga}
        selected_missing_kk = max(0, len(selected_ids) - len(kk))
        selected_missing_harga = len(selected_ids - harga_ids)
        now = datetime.now(timezone.utc).isoformat()
        manifest = {
            "kode_tender": kode_tender,
            "last_published_at": now,
            "source": "Asisten Pokja / Publish Paket",
            "version": 1,
            "counts": {
                "peserta_dipilih": len(selected_ids),
                "kk": len(kk),
                "identitas": len(identitas),
                "harga_rows": len(harga),
            },
            "status": {
                "kk": "OK" if not selected_missing_kk else "Belum lengkap",
                "identitas": "OK" if len(identitas) >= len(selected_ids) else "Belum lengkap",
                "harga": "OK" if not selected_missing_harga else "Belum ada/parsial",
            },
            "warnings": [],
        }
        if selected_missing_kk:
            manifest["warnings"].append("KK Evaluasi peserta terpilih belum lengkap")
        if len(identitas) < len(selected_ids):
            manifest["warnings"].append("Identitas peserta belum lengkap")
        if selected_missing_harga:
            manifest["warnings"].append("Harga penawaran peserta terpilih belum lengkap")

        # DML aman: pertahankan isi data_snapshot yang sudah ada.
        draft = client.table("draft_paket").select("data_snapshot").eq(
            "kode_tender", kode_tender
        ).limit(1).execute().data or []
        snapshot = _as_dict(draft[0].get("data_snapshot", {})) if draft else {}
        snapshot["_workflow"] = manifest
        client.table("draft_paket").update({"data_snapshot": snapshot}).eq(
            "kode_tender", kode_tender
        ).execute()

        manifest["sidecar"] = _write_sidecar(folder_paket, manifest)
        return {"ok": True, "manifest": manifest}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
