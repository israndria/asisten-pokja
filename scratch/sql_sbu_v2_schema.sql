-- ============================================================
-- SBU v2 schema (Option B: 3 tabel — baru, lama, mapping)
-- Run di Supabase SQL Editor:
-- https://supabase.com/dashboard/project/iubvqphzalodqqhpatcy/sql
-- ============================================================

-- Step 1: Tabel master_sbu_baru (KBLI 2020) — PK = kode (RK003, AR001, dst)
CREATE TABLE IF NOT EXISTS master_sbu_baru (
    kode TEXT PRIMARY KEY,                  -- 'RK003', 'AR001'
    klasifikasi TEXT NOT NULL,              -- 'Rekayasa', 'Arsitektur'
    nama_full TEXT NOT NULL,                -- 'Subklasifikasi RK003 (KBLI 2020) Jasa Rekayasa Pekerjaan Teknik Sipil Transportasi'
    nama_singkat TEXT,                      -- 'Jasa Rekayasa Pekerjaan Teknik Sipil Transportasi'
    kbli_2020 TEXT,                         -- '71102'
    jabatan_ahli TEXT,                      -- 'Ahli Teknik Bangunan Gedung'
    skk_kode TEXT,                          -- 'SKK Ahli Muda Teknik Bangunan Gedung'
    lingkup_pekerjaan TEXT,                 -- multi-line text dari Permen PUPR 8/2022
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sbu_baru_klasifikasi ON master_sbu_baru(klasifikasi);

-- Step 2: Tabel master_sbu_lama (KBLI 2017) — PK = kode (RE104, AR101, dst)
CREATE TABLE IF NOT EXISTS master_sbu_lama (
    kode TEXT PRIMARY KEY,                  -- 'RE104', 'AR101'
    nama_full TEXT NOT NULL,                -- 'Subklasifikasi Jasa Desain Rekayasa untuk Pekerjaan Teknik Sipil Transportasi (KBLI 2017) RE104'
    nama_singkat TEXT,                      -- 'Jasa Desain Rekayasa untuk Pekerjaan Teknik Sipil Transportasi'
    kbli_2017 TEXT,                         -- '71102'
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Step 3: Junction table — many-to-many mapping
CREATE TABLE IF NOT EXISTS sbu_mapping (
    id SERIAL PRIMARY KEY,
    kode_baru TEXT NOT NULL REFERENCES master_sbu_baru(kode) ON DELETE CASCADE,
    kode_lama TEXT NOT NULL REFERENCES master_sbu_lama(kode) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(kode_baru, kode_lama)
);

CREATE INDEX IF NOT EXISTS idx_sbu_mapping_kode_baru ON sbu_mapping(kode_baru);
CREATE INDEX IF NOT EXISTS idx_sbu_mapping_kode_lama ON sbu_mapping(kode_lama);

-- Step 4: View untuk query mudah (kode_baru → list semua padanan lama)
CREATE OR REPLACE VIEW v_sbu_complete AS
SELECT
    b.kode AS kode_baru,
    b.klasifikasi,
    b.nama_full AS sbu_baru_full,
    b.nama_singkat AS sbu_baru_singkat,
    b.kbli_2020,
    b.jabatan_ahli,
    b.skk_kode,
    l.kode AS kode_lama,
    l.nama_full AS sbu_lama_full,
    l.nama_singkat AS sbu_lama_singkat,
    l.kbli_2017
FROM master_sbu_baru b
LEFT JOIN sbu_mapping m ON m.kode_baru = b.kode
LEFT JOIN master_sbu_lama l ON l.kode = m.kode_lama
ORDER BY b.klasifikasi, b.kode, l.kode;

-- Verifikasi
SELECT 'Tabel created. Lanjut migrate dari master_sbu (lama).' AS status;
