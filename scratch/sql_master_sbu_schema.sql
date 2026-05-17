-- SQL DDL: tambah kolom subklasifikasi_kode + index
-- Run di Supabase SQL Editor: https://supabase.com/dashboard/project/iubvqphzalodqqhpatcy/sql

-- Step 1: Tambah kolom subklasifikasi_kode (jika belum ada)
ALTER TABLE master_sbu ADD COLUMN IF NOT EXISTS subklasifikasi_kode TEXT;

-- Step 2: Index untuk lookup cepat
CREATE INDEX IF NOT EXISTS idx_master_sbu_subklasifikasi_kode ON master_sbu(subklasifikasi_kode);
CREATE INDEX IF NOT EXISTS idx_master_sbu_klasifikasi ON master_sbu(klasifikasi);

-- Step 3: Backfill subklasifikasi_kode dari sbu_baru via regex (jalankan setelah ALTER)
UPDATE master_sbu
SET subklasifikasi_kode = SUBSTRING(sbu_baru FROM '([A-Z]{2}\d{3})')
WHERE subklasifikasi_kode IS NULL OR subklasifikasi_kode = '';

-- Verifikasi
SELECT subklasifikasi_kode, klasifikasi, COUNT(*)
FROM master_sbu
GROUP BY subklasifikasi_kode, klasifikasi
ORDER BY subklasifikasi_kode
LIMIT 30;
