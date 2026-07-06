# TASK

## Goal
Samakan `_is_tender_selesai` (app.py) dengan pola `pl_engine.is_paket_selesai` — cek `status_tahap` (kolom Supabase, live-refresh) dulu, baru fallback ke `status` lama. Saat ini `_is_tender_selesai` cuma cek `status` — belum baca `status_tahap` walau kolom itu sudah ada & sudah di-upsert oleh `kirimpesan_engine.enrich_paket_supabase()`.

## File Target
- `app.py` line 58-67 — fungsi `_TENDER_SELESAI_KW` + `_is_tender_selesai(p)`

## Konteks
- Referensi pola yang mau ditiru: `pl_engine.py` line 43-53 (`_TAHAP_SELESAI_KEYWORDS` + `is_paket_selesai`):
  ```python
  _TAHAP_SELESAI_KEYWORDS = ("penandatanganan kontrak", "paket sudah selesai", "sudah selesai")

  def is_paket_selesai(r: dict) -> bool:
      tahap = (r.get("tahap_spse") or "").lower()
      if tahap:
          return any(k in tahap for k in _TAHAP_SELESAI_KEYWORDS)
      return any(k in (r.get("status") or "").lower() for k in _TAHAP_SELESAI_KEYWORDS)
  ```
- Tender infra sudah setara: `kirimpesan_engine.fetch_tahap_tender()` (line 442) scrape badge tahap dari `/lelang/{kode}`, `enrich_paket_supabase()` (line 552) upsert ke kolom `status_tahap` Supabase.
- Filter pemakai fungsi ini ada di app.py sekitar line 8073-8114 (`_selesai_kodes`, `_tender_tahun_cocok`, checklist "Buat Folder Paket" Tab 0 tender) — baca `_r.get("status_tahap")` dari `_draft_rows` (row Supabase), BUKAN dari live-scrape `status`. Jangan ubah pemanggil, cukup ubah body fungsi `_is_tender_selesai` supaya prioritaskan `status_tahap` kalau ada, fallback `status` kalau kosong.
- Keyword list JANGAN diubah drastis — pertahankan `_TENDER_SELESAI_KW` existing (lebih lengkap dari PL punya), cuma logic prioritas sumber yang diubah.

## Konteks Tambahan — Bug Terkait (SUDAH DIFIX, jangan diutak-atik ulang)
- Ada bug terpisah baru saja difix di `_tender_tahun_cocok` (app.py sekitar line 8092-8103): fallback lama pakai `"2026" in diambil_pada` (string match tahun) — SALAH karena bulk-import historis (paket lama nomor_pp kosong) numpuk di tanggal 2026-05-04, ikut ke-match palsu. Sudah diganti jadi cek selisih hari `(datetime.now() - diambil_pada_dt).days <= 14`. Fix ini SUDAH diterapkan & compile OK, user lagi test — JANGAN sentuh ulang kecuali user lapor masih bug.

## Selesai Jika
- [ ] `_is_tender_selesai` cek `status_tahap` dulu (kalau non-empty), fallback ke `status` kalau `status_tahap` kosong
- [ ] `py_compile app.py` OK
- [ ] Grep pemanggil `_is_tender_selesai` (harusnya cuma di line ~8077 area `_selesai_kodes`) — pastikan tidak ada pemanggil lain yang keliru asumsi signature berubah
- [ ] Lapor ke user, TUNGGU konfirmasi sebelum push (aturan CLAUDE.md — dilarang push sebelum user OK)
