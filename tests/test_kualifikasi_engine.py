import kualifikasi_engine


def test_fetch_peserta_only_counts_submitted_offer(monkeypatch):
    html = """
    <table>
      <tr>
        <td>1</td><td>CV. A. YANI PURA</td>
        <td><a href="/tapinkab/kualifikasi/11788975000/preview">Kualifikasi</a></td>
        <td><a href="/tapinkab/peserta/11788975000/cetaksuratpenawaran">Cetak</a></td>
        <td><a href="/tapinkab/peserta/11788975000/rincian_adminteknis">Detil</a></td>
        <td>Dikirim 2 Agustus 2026</td>
      </tr>
      <tr>
        <td>2</td><td>CV. Iar Ircha</td>
        <td><a href="/tapinkab/kualifikasi/11796690000/preview">Kualifikasi</a></td>
        <td>Belum dikirim</td>
      </tr>
    </table>
    """

    class Response:
        status_code = 200
        text = html

    monkeypatch.setattr(kualifikasi_engine.requests, "get", lambda *args, **kwargs: Response())
    result = kualifikasi_engine.fetch_peserta_by_id_lelang("10155297000")

    assert result["ok"] is True
    assert [row["nama"] for row in result["peserta"]] == ["CV. A. YANI PURA"]
    assert result["pesan"] == "1 peserta penawar ditemukan"
