from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import penjelasan_engine as engine


def test_pembukaan_to_html_preserves_lines_and_escapes_markup():
    source = "Baris 1\n\n2. <wajib> & aman"

    result = engine._pembukaan_to_html(source)

    assert result == "Baris 1<br><br>2. &lt;wajib&gt; &amp; aman"


def test_parse_jadwal_html_selects_pemberian_penjelasan():
    html = """
    <table>
      <tr><th>No</th><th>Tahap</th><th>Mulai</th><th>Sampai</th><th>Perubahan</th></tr>
      <tr><td>1</td><td>Pengumuman</td><td>14 Agustus 2026 11:00</td><td>21 Agustus 2026 09:00</td><td>-</td></tr>
      <tr><td>2</td><td><strong>Pemberian Penjelasan</strong></td><td>18 Agustus 2026 09:00</td><td>18 Agustus 2026 11:00</td><td>-</td></tr>
    </table>
    """

    rows = engine._parse_jadwal_html(html)

    assert len(rows) == 1
    assert rows[0]["kegiatan"] == "Pemberian Penjelasan"
    assert rows[0]["mulai_dt"] == datetime(2026, 8, 18, 9, 0, tzinfo=engine.TZ_WITA)
    assert rows[0]["selesai_dt"] == datetime(2026, 8, 18, 11, 0, tzinfo=engine.TZ_WITA)


def test_get_jadwal_pemberian_penjelasan_prefers_spse():
    spse_row = {
        "kegiatan": "Pemberian Penjelasan",
        "mulai_dt": datetime(2026, 8, 18, 9, 0, tzinfo=engine.TZ_WITA),
        "selesai_dt": datetime(2026, 8, 18, 11, 0, tzinfo=engine.TZ_WITA),
    }

    with patch.object(engine, "parse_jadwal", return_value=[spse_row]), patch.object(
        engine, "get_jadwal_dari_gcalendar"
    ) as gcal:
        result = engine.get_jadwal_pemberian_penjelasan("10156445000")

    assert result["sumber"] == "SPSE"
    assert result["mulai_dt"] == spse_row["mulai_dt"]
    gcal.assert_not_called()


def test_get_jadwal_pemberian_penjelasan_uses_gcal_only_as_fallback():
    waktu = datetime(2026, 8, 18, 9, 0, tzinfo=engine.TZ_WITA)
    with patch.object(engine, "parse_jadwal", side_effect=RuntimeError("403")), patch.object(
        engine, "get_jadwal_dari_gcalendar", return_value={"10156445000": waktu}
    ):
        result = engine.get_jadwal_pemberian_penjelasan("10156445000")

    assert result["sumber"] == "Google Calendar (fallback)"
    assert result["mulai_dt"] == waktu


def test_update_pembukaan_posts_encoded_uraian_to_correct_endpoint():
    response = type("Response", (), {"status_code": 200, "headers": {}, "text": "ok"})()
    with patch.object(engine, "_post_spse", return_value=response) as post:
        result = engine.update_pembukaan("10156445000", "Halo\nDua")

    assert result["ok"] is True
    assert result["status"] == 200
    endpoint = post.call_args.args[0]
    payload = post.call_args.args[1]
    assert endpoint.endswith("/penjelasan/10156445000/pembukaan_pengadaan")
    assert payload["uraian"] == "Halo%3Cbr%3EDua"


def test_auto_post_pembukaan_does_not_require_participant_questions():
    with patch.object(engine, "update_pembukaan", return_value={"ok": True, "status": 200}):
        result = engine.auto_post_pembukaan("10156445000", "tender")

    assert result["total"] == 1
    assert result["sukses"] == 1
    assert result["gagal"] == 0


def test_sync_jobs_from_gcal_is_idempotent_and_updates_pending_time():
    with TemporaryDirectory() as temp_dir:
        event_start = datetime(2026, 8, 20, 9, 0, tzinfo=engine.TZ_WITA)
        event_end = datetime(2026, 8, 20, 11, 0, tzinfo=engine.TZ_WITA)
        event = {
            "event_id": "gcal-event-1",
            "summary": "Pemberian Penjelasan 10156445000",
            "description": "Kode paket 10156445000",
            "start": event_start,
            "end": event_end,
        }
        jobs_path = Path(temp_dir) / "jobs.json"
        with patch.object(engine, "JOBS_FILE", jobs_path), patch.object(
            engine, "LEGACY_JOBS_FILE", Path(temp_dir) / "legacy.json"
        ), patch.object(engine, "get_penjelasan_events", return_value=[event]):
            first = engine.sync_jobs_from_gcal(now=event_start - timedelta(minutes=5))
            second = engine.sync_jobs_from_gcal(now=event_start - timedelta(minutes=4))

            assert first["added"] == 1
            assert second["added"] == 0
            assert len(engine.get_jobs()) == 1

            moved_start = event_start.replace(hour=10)
            moved_end = event_end.replace(hour=12)
            moved = {**event, "start": moved_start, "end": moved_end}
            with patch.object(engine, "get_penjelasan_events", return_value=[moved]):
                changed = engine.sync_jobs_from_gcal(now=event_start)

            assert changed["updated"] == 1
            assert engine.get_jobs()[0]["waktu_fire"] == moved_start.isoformat()


def test_legacy_no_question_result_is_migrated_back_to_pending():
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        legacy = root / "legacy.json"
        current = root / "state" / "jobs.json"
        current.parent.mkdir()
        legacy.write_text(
            '[{"paket_id":"10156445000","jenis":"tender",'
            '"status":"fired","result":{"pesan":"Tidak ada pertanyaan"}}]',
            encoding="utf-8",
        )
        with patch.object(engine, "JOBS_FILE", current), patch.object(
            engine, "LEGACY_JOBS_FILE", legacy
        ):
            jobs = engine._load_jobs()

        assert jobs[0]["status"] == "pending"
        assert jobs[0]["result"] is None
