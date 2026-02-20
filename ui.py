from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path

import streamlit as st


def main() -> None:
    repo_root = Path(__file__).resolve().parent
    src_dir = repo_root / "src"
    pkg_ui_path = src_dir / "paperscout" / "ui.py"

    if pkg_ui_path.exists():
        spec = importlib.util.spec_from_file_location("paperscout_ui_app", pkg_ui_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "_render_main"):
                module._render_main()
                return

    legacy_ui_path = repo_root / "paperscoutV2.py"
    if legacy_ui_path.exists():
        runpy.run_path(str(legacy_ui_path), run_name="__main__")
        return

    st.error(
        "Kein gueltiger Entrypoint gefunden. Erwartet: src/paperscout/ui.py oder paperscoutV2.py"
    )


if __name__ == "__main__":
    main()
