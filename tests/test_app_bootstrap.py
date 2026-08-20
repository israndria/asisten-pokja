from __future__ import annotations

import subprocess
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
CORE_CONFIG = APP_DIR.parent / "procurement_core" / "config.py"


def test_bootstrap_replaces_foreign_preloaded_config():
    code = f"""
import importlib.util
import sys
from pathlib import Path

core = Path(r"{CORE_CONFIG}")
app = Path(r"{APP_DIR}")
spec = importlib.util.spec_from_file_location("config", core)
foreign = importlib.util.module_from_spec(spec)
sys.modules["config"] = foreign
spec.loader.exec_module(foreign)
sys.path.insert(0, str(app))

from app_bootstrap import ensure_local_config

module = ensure_local_config(app)
assert Path(module.__file__).resolve().parent == app.resolve()
assert callable(module.sb)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(APP_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
