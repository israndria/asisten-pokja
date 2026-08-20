"""Bootstrap guard untuk import modul lokal Asisten Pokja."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType


def ensure_local_config(app_dir: str | os.PathLike[str]) -> ModuleType:
    """Pastikan bare import ``config`` menunjuk config milik Asisten.

    Streamlit dapat mempertahankan ``sys.modules`` saat hot-reload. Jika proses
    sebelumnya memuat ``procurement_core/config.py``, perubahan ``sys.path``
    saja tidak cukup karena Python akan memakai modul cache tersebut.
    """
    expected_dir = Path(app_dir).resolve()
    expected_text = str(expected_dir)

    sys.path[:] = [
        entry for entry in sys.path
        if os.path.abspath(entry or os.curdir) != expected_text
    ]
    sys.path.insert(0, expected_text)

    loaded = sys.modules.get("config")
    if loaded is not None:
        loaded_file = getattr(loaded, "__file__", "")
        try:
            loaded_dir = Path(loaded_file).resolve().parent
        except (OSError, RuntimeError, TypeError, ValueError):
            loaded_dir = None
        if loaded_dir != expected_dir:
            sys.modules.pop("config", None)

    module = importlib.import_module("config")
    module_file = Path(getattr(module, "__file__", "")).resolve()
    if module_file.parent != expected_dir:
        raise ImportError(
            f"config lokal tidak aktif: {module_file}; expected {expected_dir}"
        )
    return module
