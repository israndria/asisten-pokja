"""Worker scheduler mandiri untuk auto-post Pemberian Penjelasan Tender.

Worker ini sengaja dipisahkan dari sesi Streamlit. Server Streamlit dapat hidup
tanpa ada browser yang membuka localhost; karena itu loop auto-post tidak boleh
bergantung pada lifecycle sesi UI.
"""

from __future__ import annotations

import time
from pathlib import Path

import msvcrt

from config import ASISTEN_INSTANCE, STATE_DIR
import penjelasan_engine


_LOCK_FILE = Path(STATE_DIR) / "penjelasan_scheduler.lock"


def _acquire_singleton():
    """Kunci satu byte agar launcher ganda tidak mem-post dua kali."""
    handle = _LOCK_FILE.open("a+b")
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def _touch_heartbeat() -> None:
    penjelasan_engine.WORKER_HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    penjelasan_engine.WORKER_HEARTBEAT_FILE.write_text(
        str(time.time()), encoding="ascii"
    )


def main(poll_seconds: float = 5.0) -> int:
    """Jalankan worker sampai dihentikan oleh Windows/proses induk."""
    if ASISTEN_INSTANCE != "TENDER":
        # Mencegah worker salah start di instance PP/PPK.
        return 2

    lock_handle = _acquire_singleton()
    if lock_handle is None:
        return 0

    penjelasan_engine.start_scheduler()
    try:
        while True:
            _touch_heartbeat()
            if not penjelasan_engine.is_scheduler_running():
                # Recovery jika thread daemon berhenti karena exception tak
                # terduga; queue tetap persisten sehingga tidak ada jadwal
                # yang hilang.
                penjelasan_engine.start_scheduler()
            time.sleep(max(1.0, float(poll_seconds)))
    except KeyboardInterrupt:
        penjelasan_engine.stop_scheduler()
        return 0
    finally:
        try:
            penjelasan_engine.WORKER_HEARTBEAT_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
