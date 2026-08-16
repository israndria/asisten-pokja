import conflict_engine
from datetime import date


class _Result:
    data = []


class _Table:
    def __init__(self, db, name):
        self.db = db
        self.name = name
        self.filters = []
        self.operation = "select"
        self.rows = None

    def select(self, *_args):
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, *_args):
        return self

    def upsert(self, rows, on_conflict):
        self.operation = "upsert"
        self.rows = rows
        self.conflict_keys = on_conflict.split(",")
        return self

    def execute(self):
        current = self.db.setdefault(self.name, [])
        if self.operation == "delete":
            self.db[self.name] = [
                row for row in current
                if not all(row.get(key) == value for key, value in self.filters)
            ]
        elif self.operation == "upsert":
            for row in self.rows or []:
                match = next(
                    (
                        old for old in current
                        if all(old.get(key) == row.get(key) for key in self.conflict_keys)
                    ),
                    None,
                )
                if match is None:
                    current.append(dict(row))
                else:
                    match.update(row)
        result = _Result()
        result.data = list(self.db.get(self.name, []))
        return result


class _DB(dict):
    def table(self, name):
        return _Table(self, name)


def test_sync_from_pdf_replaces_stale_personnel_and_ignores_equipment(monkeypatch):
    db = _DB(
        paket_personil=[
            {
                "kode_tender": "T-1",
                "peserta_id": "P-1",
                "nama_personil": "Personel Lama",
            },
            {
                "kode_tender": "T-1",
                "peserta_id": "P-2",
                "nama_personil": "Personel Peserta Lain",
            },
        ]
    )
    monkeypatch.setattr(conflict_engine, "_sb", lambda: db)

    result = conflict_engine.sync_from_pdf(
        "T-1",
        "P-1",
        "CV Contoh",
        [
            "Budi Santoso (Tenaga Ahli)",
            "BUDI SANTOSO (Cadangan)",
            "Citra Dewi (Petugas K3)",
        ],
    )

    rows = db["paket_personil"]
    assert result == {"personil": 2}
    assert {row["nama_personil"] for row in rows} == {
        "Budi Santoso",
        "Citra Dewi",
        "Personel Peserta Lain",
    }
    assert "paket_alat" not in db


def test_tender_assignment_window_uses_gcal_sppbj_plus_excel_duration(monkeypatch):
    db = _DB(
        draft_paket=[{
            "kode_tender": "T-1",
            "nama_tender": "Paket Contoh",
            "folder_dibuat": "01. Paket Contoh",
            "kode_pokja": "001",
        }]
    )
    monkeypatch.setattr(conflict_engine, "_sb", lambda: db)
    monkeypatch.setattr(
        conflict_engine,
        "_get_tgl_sppbj_gcal",
        lambda _nama, kode_tender="": date(2026, 8, 16),
    )
    monkeypatch.setattr(
        conflict_engine,
        "_read_tender_duration_excel",
        lambda _kode, _row: 30,
    )

    assert conflict_engine._get_jadwal_paket("T-1") == (
        date(2026, 8, 16),
        date(2026, 9, 15),
    )


def test_parse_hari_jangka_accepts_numeric_excel_value():
    assert conflict_engine._parse_hari_jangka(45) == 45
