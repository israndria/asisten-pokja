-- ============================================================
-- DPA Full-Text Search Migration
-- Jalankan di Supabase SQL Editor:
-- https://supabase.com/dashboard/project/iubvqphzalodqqhpatcy/sql
-- ============================================================

-- 1. Enable pg_trgm (fuzzy search + fast ILIKE)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. dpa_item_belanja — tambah kolom tsvector generated
--    'simple' config = no stemming = cocok bahasa Indonesia
ALTER TABLE dpa_item_belanja
  ADD COLUMN IF NOT EXISTS search_vec tsvector
  GENERATED ALWAYS AS (
    to_tsvector('simple',
      coalesce(uraian, '') || ' ' ||
      coalesce(nama_paket, '') || ' ' ||
      coalesce(spesifikasi, '') || ' ' ||
      coalesce(kode_rekening, '')
    )
  ) STORED;

-- 3. dpa_subkegiatan — tambah kolom tsvector generated
ALTER TABLE dpa_subkegiatan
  ADD COLUMN IF NOT EXISTS search_vec tsvector
  GENERATED ALWAYS AS (
    to_tsvector('simple',
      coalesce(subkegiatan_nama, '') || ' ' ||
      coalesce(kegiatan_nama, '') || ' ' ||
      coalesce(program_nama, '') || ' ' ||
      coalesce(subkegiatan_kode, '') || ' ' ||
      coalesce(satker, '')
    )
  ) STORED;

-- 4. GIN index untuk FTS (@@)
CREATE INDEX IF NOT EXISTS idx_dpa_item_fts
  ON dpa_item_belanja USING GIN(search_vec);

CREATE INDEX IF NOT EXISTS idx_dpa_sk_fts
  ON dpa_subkegiatan USING GIN(search_vec);

-- 5. GIN trigram index untuk fuzzy ILIKE + typo tolerance
CREATE INDEX IF NOT EXISTS idx_dpa_item_uraian_trgm
  ON dpa_item_belanja USING GIN(uraian gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_dpa_item_paket_trgm
  ON dpa_item_belanja USING GIN(nama_paket gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_dpa_sk_nama_trgm
  ON dpa_subkegiatan USING GIN(subkegiatan_nama gin_trgm_ops);

-- 6. Index untuk filter cepat (satker, tahun, kode_rekening prefix)
CREATE INDEX IF NOT EXISTS idx_dpa_item_satker
  ON dpa_item_belanja(subkegiatan_id);

CREATE INDEX IF NOT EXISTS idx_dpa_sk_satker_tahun
  ON dpa_subkegiatan(satker, tahun_anggaran);

CREATE INDEX IF NOT EXISTS idx_dpa_item_kode_rek
  ON dpa_item_belanja(kode_rekening);

-- ============================================================
-- VERIFY
-- ============================================================
SELECT
  (SELECT count(*) FROM dpa_item_belanja) AS total_item,
  (SELECT count(*) FROM dpa_subkegiatan) AS total_sk,
  (SELECT count(*) FROM pg_indexes WHERE tablename IN ('dpa_item_belanja','dpa_subkegiatan')) AS total_indexes;
