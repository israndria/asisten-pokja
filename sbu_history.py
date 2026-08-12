"""Shared local SBU history for Tender and PL PK setup screens."""

import json
import re
from pathlib import Path


SBU_HISTORY_PATH = Path(__file__).resolve().parent / "data" / "sbu_history.json"
LEGACY_SBU_HISTORY_PATHS = (
    SBU_HISTORY_PATH.with_name("tender_sbu_history.json"),
)
LEGACY_PK_SBU_HISTORY_PATH = SBU_HISTORY_PATH.with_name("pl_sbu_history.json")
DEFAULT_SBU_HISTORY = (
    {"baru": "SBU BS002 Bangunan Sipil Jembatan, Jalan Layang, Fly Over, dan Underpass KBLI 42102", "lama": ""},
    {"baru": "SBU BS001 Konstruksi Bangunan Sipil Jalan atau Konstruksi Jalan Pada Permukaan Tanah KBLI 42101", "lama": ""},
    {"baru": "SBU BG009 Konstruksi Gedung Lainnya atau Konstruksi Konvensional Gedung Lainnya KBLI 41019", "lama": ""},
    {"baru": "SBU BS010 Konstruksi Bangunan Prasarana Sumber Daya Air KBLI 42911", "lama": ""},
    {"baru": "SBU BG006 Konstruksi Gedung Pendidikan KBLI 41016 atau Konstruksi Konvensional Gedung Pendidikan", "lama": ""},
)


def _is_license_text(value: str) -> bool:
    """Reject legacy generic izin rows from the SBU-only history."""
    upper = str(value or "").upper()
    return "PERIZINAN BERUSAHA" in upper or "IZIN USAHA DI BIDANG" in upper


def is_consultancy_sbu(value: str) -> bool:
    """True for JKK/consultancy history entries, not construction SBU."""
    upper = str(value or "").upper()
    return bool(
        re.search(r"\b(?:RE|RK)\d{3}\b", upper)
        or "KONSULT" in upper
        or "REKAYASA" in upper
    )


def _read_entries(path: Path) -> list[dict[str, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(raw, list):
        return []

    entries = []
    for item in raw:
        if isinstance(item, str):
            baru, lama = item, ""
        elif isinstance(item, dict):
            baru, lama = item.get("baru"), item.get("lama")
        else:
            continue
        baru = str(baru or "").strip()
        lama = str(lama or "").strip()
        if baru and not _is_license_text(baru):
            entries.append({"baru": baru, "lama": lama})
    return entries


def _history_key(entry: dict[str, str]) -> tuple[str, ...]:
    """Use code+KBLI identity so legacy wording variants do not duplicate UI."""
    baru = entry["baru"]
    lama = entry["lama"].casefold()
    code = re.search(r"\b([A-Z]{2}\d{3})\b", baru, re.IGNORECASE)
    kbli = re.search(r"\bKBLI\s+(\d{5})\b", baru, re.IGNORECASE)
    if code and kbli:
        return ("code-kbli", code.group(1).upper(), kbli.group(1), lama)
    return ("text", re.sub(r"\s+", " ", baru).casefold(), lama)


def compact_sbu_label(value: str | dict[str, str]) -> str:
    """Short selectbox label; caller still receives the complete SBU text."""
    text = value.get("baru", "") if isinstance(value, dict) else str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    code = re.search(r"\b([A-Z]{2}\d{3})\b", text, re.IGNORECASE)
    kbli = re.search(r"\bKBLI\s+(\d{5})\b", text, re.IGNORECASE)
    if not code:
        return text

    title = re.sub(
        rf"^\s*SBU\s+{re.escape(code.group(1))}\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Legacy JKK entries sometimes place code at end and start with
    # "KBLI ... atau KBLI ... -"; remove wrapper before truncating.
    title = re.sub(
        rf"\s*\(?{re.escape(code.group(1))}\)?\s*",
        " ",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"^\s*KBLI\s+\d{5}\s+atau\s+KBLI\s+\d{5}\s*-\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"^\s*KBLI\s+\d{5}\s*", "", title, flags=re.IGNORECASE)
    if kbli:
        title = re.split(r"\s+KBLI\s+\d{5}\b", title, maxsplit=1, flags=re.IGNORECASE)[0]
    title = title.strip(" -")
    if len(title) > 36:
        title = title[:33].rstrip() + "..."
    label = code.group(1).upper()
    if title:
        label += f" — {title}"
    if kbli:
        label += f" · KBLI {kbli.group(1)}"
    return label


def load_sbu_history(
    path: Path = SBU_HISTORY_PATH,
    legacy_paths: tuple[Path, ...] = LEGACY_SBU_HISTORY_PATHS,
) -> list[dict[str, str]]:
    """Load shared history, merging legacy files for safe one-time migration."""
    history = []
    seen = set()
    sources = (path, *legacy_paths)
    # pl_sbu_history.json was shared by JKK and PK in the old implementation.
    # Migrate only entries that are clearly non-consultancy, so JKK history
    # (RE/RK/konsultansi) does not leak into the Tender/PK selector.
    if LEGACY_PK_SBU_HISTORY_PATH not in sources:
        sources += (LEGACY_PK_SBU_HISTORY_PATH,)
    for source in sources:
        for entry in _read_entries(source):
            if source == LEGACY_PK_SBU_HISTORY_PATH and is_consultancy_sbu(entry["baru"]):
                continue
            key = _history_key(entry)
            if key not in seen:
                seen.add(key)
                history.append(entry)
    for entry in DEFAULT_SBU_HISTORY:
        key = _history_key(entry)
        if key not in seen:
            seen.add(key)
            history.append(dict(entry))
    return history[:20]


def save_sbu_history(
    baru: str,
    lama: str = "",
    path: Path = SBU_HISTORY_PATH,
    legacy_paths: tuple[Path, ...] = LEGACY_SBU_HISTORY_PATHS,
) -> list[dict[str, str]]:
    """Put one SBU pair first and persist it to canonical history."""
    baru = str(baru or "").strip()
    lama = str(lama or "").strip()
    if not baru or _is_license_text(baru):
        return load_sbu_history(path, legacy_paths)

    entry = {"baru": baru, "lama": lama}
    history = [
        item for item in load_sbu_history(path, legacy_paths)
        if (item["baru"], item["lama"]) != (baru, lama)
    ]
    history.insert(0, entry)
    history = history[:20]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except (OSError, TypeError, ValueError):
        pass
    return history
