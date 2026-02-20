from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st

try:
    from .pipeline import dedup_by_doi
    from .sources.crossref_strict import fetch_from_crossref_strict
except ImportError:
    src_root = Path(__file__).resolve().parents[1]
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    from paperscout.pipeline import dedup_by_doi
    from paperscout.sources.crossref_strict import fetch_from_crossref_strict


DEFAULT_JOURNALS = [
    "Nature",
    "Science",
    "Journal of Applied Psychology",
    "Journal of Management",
    "Academy of Management Journal",
    "Organization Science",
    "Management Science",
]

DEFAULT_WORKSPACE_NAME = "Default Workspace"


def run() -> None:
    module_path = Path(__file__).resolve()
    cmd = [sys.executable, "-m", "streamlit", "run", str(module_path)]
    subprocess.run(cmd, check=False)


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-zÄÖÜäöüß\-]{3,}", (text or "").lower())
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "zur",
        "und",
        "der",
        "die",
        "das",
        "eine",
        "einer",
    }
    return [t for t in tokens if t not in stop]


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        return None


def _safe_date_from_iso(value: str | None, fallback: date) -> date:
    parsed = _parse_date(str(value or ""))
    return parsed.date() if parsed else fallback


def _workspace_store_path() -> Path:
    return Path.cwd() / ".paperscout" / "workspaces.json"


def _default_workspace_config() -> dict[str, object]:
    today = date.today()
    return {
        "selected_defaults": ["Nature", "Science", "Journal of Applied Psychology"],
        "manual_journals": "",
        "range_mode": "Letzte 90 Tage",
        "since": (today - timedelta(days=90)).isoformat(),
        "until": today.isoformat(),
        "rows": 120,
        "focus_query": "",
    }


def _default_store() -> dict[str, object]:
    return {"version": 1, "workspaces": {}}


def _sanitize_workspace_name(name: str) -> str:
    safe = re.sub(r"\s+", " ", (name or "").strip())
    return safe[:80]


def _load_workspace_store() -> dict[str, object]:
    path = _workspace_store_path()
    if not path.exists():
        return _default_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_store()
        if "workspaces" not in data or not isinstance(data["workspaces"], dict):
            data["workspaces"] = {}
        if "version" not in data:
            data["version"] = 1
        return data
    except Exception:
        return _default_store()


def _save_workspace_store(store: dict[str, object]) -> None:
    path = _workspace_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=True, indent=2), encoding="utf-8")


def _normalize_workspace_entry(entry: dict[str, object] | None) -> dict[str, object]:
    base = _default_workspace_config()
    if entry and isinstance(entry, dict):
        conf = entry.get("config")
        if isinstance(conf, dict):
            base.update(conf)
    today = date.today()
    rows_val = int(base.get("rows", 120))
    rows_val = max(20, min(300, rows_val))
    out_config = {
        "selected_defaults": list(base.get("selected_defaults", [])),
        "manual_journals": str(base.get("manual_journals", "")),
        "range_mode": str(base.get("range_mode", "Letzte 90 Tage")),
        "since": _safe_date_from_iso(str(base.get("since", "")), today - timedelta(days=90)).isoformat(),
        "until": _safe_date_from_iso(str(base.get("until", "")), today).isoformat(),
        "rows": rows_val,
        "focus_query": str(base.get("focus_query", "")),
    }
    last_keys = []
    last_run_at = ""
    last_result_count = 0
    if entry and isinstance(entry, dict):
        last_keys = list(entry.get("last_keys", []))
        last_run_at = str(entry.get("last_run_at", ""))
        try:
            last_result_count = int(entry.get("last_result_count", 0))
        except Exception:
            last_result_count = 0
    return {
        "config": out_config,
        "last_keys": [str(x) for x in last_keys if str(x).strip()],
        "last_run_at": last_run_at,
        "last_result_count": last_result_count,
    }


def _ensure_default_workspace(store: dict[str, object]) -> bool:
    workspaces = store.get("workspaces")
    if not isinstance(workspaces, dict):
        store["workspaces"] = {}
        workspaces = store["workspaces"]
    if not workspaces:
        workspaces[DEFAULT_WORKSPACE_NAME] = {
            "config": _default_workspace_config(),
            "last_keys": [],
            "last_run_at": "",
            "last_result_count": 0,
        }
        return True
    return False


def _set_session_from_workspace_config(config: dict[str, object]) -> None:
    today = date.today()
    st.session_state["selected_defaults_input"] = [
        j for j in list(config.get("selected_defaults", [])) if j in DEFAULT_JOURNALS
    ]
    st.session_state["manual_journals_input"] = str(config.get("manual_journals", ""))
    st.session_state["range_mode_input"] = str(config.get("range_mode", "Letzte 90 Tage"))
    st.session_state["since_input"] = _safe_date_from_iso(
        str(config.get("since", "")), today - timedelta(days=90)
    )
    st.session_state["until_input"] = _safe_date_from_iso(str(config.get("until", "")), today)
    st.session_state["rows_input"] = int(config.get("rows", 120))
    st.session_state["focus_query_input"] = str(config.get("focus_query", ""))


def _read_workspace_config_from_session() -> dict[str, object]:
    since = st.session_state.get("since_input", date.today() - timedelta(days=90))
    until = st.session_state.get("until_input", date.today())
    return {
        "selected_defaults": list(st.session_state.get("selected_defaults_input", [])),
        "manual_journals": str(st.session_state.get("manual_journals_input", "")),
        "range_mode": str(st.session_state.get("range_mode_input", "Letzte 90 Tage")),
        "since": since.isoformat() if isinstance(since, date) else str(since),
        "until": until.isoformat() if isinstance(until, date) else str(until),
        "rows": int(st.session_state.get("rows_input", 120)),
        "focus_query": str(st.session_state.get("focus_query_input", "")),
    }


def _set_date_preset_for_range_mode(range_mode: str) -> None:
    today = date.today()
    if range_mode == "Letzte 30 Tage":
        st.session_state["since_input"] = today - timedelta(days=30)
        st.session_state["until_input"] = today
    elif range_mode == "Letzte 90 Tage":
        st.session_state["since_input"] = today - timedelta(days=90)
        st.session_state["until_input"] = today
    elif range_mode == "Letztes Jahr":
        st.session_state["since_input"] = today - timedelta(days=365)
        st.session_state["until_input"] = today


def _extract_journals(uploaded_file, manual_input: str, selected_defaults: list[str]) -> list[str]:
    journals = list(selected_defaults)
    if manual_input.strip():
        for part in re.split(r"[;\n,]+", manual_input):
            j = part.strip()
            if j:
                journals.append(j)

    if uploaded_file is not None:
        name = uploaded_file.name.lower()
        try:
            if name.endswith((".xlsx", ".xls")):
                df = pd.read_excel(uploaded_file)
            else:
                df = pd.read_csv(uploaded_file)
            for col in ["Journal", "journal", "JOURNAL", "container-title", "container_title"]:
                if col in df.columns:
                    journals.extend(
                        [str(x).strip() for x in df[col].dropna().tolist() if str(x).strip()]
                    )
                    break
        except Exception:
            st.warning("Journals-Datei konnte nicht gelesen werden.")

    uniq: list[str] = []
    seen = set()
    for j in journals:
        k = j.lower().strip()
        if k and k not in seen:
            seen.add(k)
            uniq.append(j.strip())
    return uniq


def _articles_to_df(articles: Iterable) -> pd.DataFrame:
    rows = []
    for a in articles:
        doi = (a.doi or "").strip()
        doi_url = doi if doi.startswith("http") else (f"https://doi.org/{doi}" if doi else "")
        rows.append(
            {
                "journal": a.journal or "",
                "title": a.title or "",
                "authors": ", ".join(a.authors or []),
                "doi": doi,
                "doi_url": doi_url,
                "issued": a.issued or "",
                "abstract": a.abstract or "",
            }
        )
    return pd.DataFrame(rows)


def _record_key(row) -> str:
    doi = str(row.get("doi", "")).strip().lower()
    if doi:
        return f"doi:{doi}"
    title = re.sub(r"\s+", " ", str(row.get("title", "")).strip().lower())
    journal = re.sub(r"\s+", " ", str(row.get("journal", "")).strip().lower())
    issued = str(row.get("issued", "")).strip()
    return f"meta:{title}|{journal}|{issued}"


def _attach_paper_keys(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        out["paper_key"] = pd.Series(dtype="string")
        return out
    out["paper_key"] = out.apply(_record_key, axis=1)
    return out


def _add_scores(df: pd.DataFrame, focus_query: str) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    today = datetime.utcnow()
    out["issued_dt"] = out["issued"].astype(str).map(_parse_date)
    out["days_ago"] = out["issued_dt"].map(
        lambda d: (today - d).days if isinstance(d, datetime) else 9999
    )

    valid_days = out.loc[out["days_ago"] < 9999, "days_ago"]
    if valid_days.empty:
        out["recency_score"] = 20.0
    else:
        min_d = float(valid_days.min())
        max_d = float(valid_days.max())
        if max_d == min_d:
            out["recency_score"] = 100.0
        else:
            out["recency_score"] = out["days_ago"].map(
                lambda d: max(0.0, 100.0 - ((d - min_d) / (max_d - min_d)) * 100.0)
                if d < 9999
                else 0.0
            )

    focus_tokens = set(_tokenize(focus_query))
    if focus_tokens:

        def _rel(row) -> float:
            text = f"{row.get('title', '')} {row.get('abstract', '')}"
            doc_tokens = set(_tokenize(text))
            if not doc_tokens:
                return 0.0
            overlap = len(doc_tokens & focus_tokens)
            return min(100.0, (overlap / max(len(focus_tokens), 1)) * 100.0)

        out["relevance_score"] = out.apply(_rel, axis=1)
    else:
        out["relevance_score"] = 50.0

    out["signal_score"] = (0.65 * out["recency_score"] + 0.35 * out["relevance_score"]).round(1)
    return out.sort_values(["signal_score", "issued"], ascending=[False, False])


def _inject_style() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=IBM+Plex+Serif:wght@400;500;700&display=swap');
        :root {
          --bg-a: #f6f3e8;
          --bg-b: #d7e7e4;
          --ink: #122521;
          --muted: #3a5a54;
          --accent: #e05a2a;
          --accent-2: #2e7d6a;
          --card: rgba(255, 255, 255, 0.78);
          --border: rgba(18, 37, 33, 0.14);
        }
        .stApp {
          background:
            radial-gradient(circle at 15% 20%, rgba(224,90,42,0.18), transparent 32%),
            radial-gradient(circle at 85% 18%, rgba(46,125,106,0.16), transparent 30%),
            linear-gradient(140deg, var(--bg-a), var(--bg-b));
        }
        html, body, [class*="css"] {
          font-family: "Space Grotesk", sans-serif;
          color: var(--ink);
        }
        .hero {
          border: 1px solid var(--border);
          background: linear-gradient(145deg, rgba(255,255,255,0.9), rgba(255,255,255,0.72));
          border-radius: 22px;
          padding: 24px 24px 18px 24px;
          box-shadow: 0 12px 30px rgba(18, 37, 33, 0.08);
          margin-bottom: 14px;
        }
        .hero h1 {
          font-family: "IBM Plex Serif", serif;
          font-size: 2.05rem;
          line-height: 1.15;
          margin: 0;
          letter-spacing: -0.02em;
        }
        .hero p {
          margin: 10px 0 0 0;
          color: var(--muted);
          font-size: 1rem;
        }
        .paper-card {
          border: 1px solid var(--border);
          border-left: 5px solid var(--accent-2);
          background: var(--card);
          border-radius: 16px;
          padding: 14px 16px;
          margin-bottom: 10px;
          backdrop-filter: blur(3px);
        }
        .paper-title {
          font-weight: 700;
          margin-bottom: 6px;
          line-height: 1.25;
        }
        .paper-meta {
          color: var(--muted);
          font-size: 0.9rem;
          margin-bottom: 7px;
        }
        .paper-abs {
          color: #1d3833;
          font-size: 0.94rem;
        }
        .stButton > button[kind="primary"] {
          border-radius: 999px;
          border: 0;
          background: linear-gradient(120deg, var(--accent), #f38b37);
          color: white;
          font-weight: 700;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_cards(df: pd.DataFrame, start: int, end: int) -> None:
    page = df.iloc[start:end]
    for _, row in page.iterrows():
        title = html.escape(str(row.get("title", ""))) or "Ohne Titel"
        journal = html.escape(str(row.get("journal", "")))
        issued = html.escape(str(row.get("issued", "")) or "n/a")
        signal = row.get("signal_score", 0.0)
        doi = str(row.get("doi", ""))
        doi_url = str(row.get("doi_url", ""))
        abstract = html.escape(str(row.get("abstract", ""))[:420])
        doi_link = f"<a href='{doi_url}' target='_blank'>DOI öffnen</a>" if doi_url else "keine DOI"
        st.markdown(
            (
                "<div class='paper-card'>"
                f"<div class='paper-title'>{title}</div>"
                f"<div class='paper-meta'>{journal} · {issued} · Signal {signal}</div>"
                f"<div class='paper-meta'>{doi_link}</div>"
                f"<div class='paper-abs'>{abstract}</div>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )
        with st.expander("Details"):
            st.write({"authors": row.get("authors", ""), "doi": doi})


def _render_empty_state() -> None:
    st.info(
        "Noch keine Daten geladen. Starte links einen Scan, um den Signal Feed zu erzeugen."
    )
    st.markdown(
        """
        **Was du sofort bekommst**
        - Signal Feed mit Relevanz- und Recency-Score
        - DOI-basierte Exporte (CSV/XLSX)
        - Delta-Ansicht: neu seit letztem Workspace-Run
        """,
    )


def _render_main() -> None:
    st.set_page_config(
        page_title="paperscout: Research Signal Console",
        page_icon=":microscope:",
        layout="wide",
    )
    _inject_style()

    store = _load_workspace_store()
    if _ensure_default_workspace(store):
        _save_workspace_store(store)
    workspace_names = sorted((store.get("workspaces") or {}).keys())

    if "active_workspace" not in st.session_state or st.session_state["active_workspace"] not in workspace_names:
        st.session_state["active_workspace"] = workspace_names[0]
    active_workspace = st.session_state["active_workspace"]
    if (
        "workspace_select_input" not in st.session_state
        or st.session_state["workspace_select_input"] not in workspace_names
    ):
        st.session_state["workspace_select_input"] = active_workspace
    active_entry = _normalize_workspace_entry((store.get("workspaces") or {}).get(active_workspace))

    if "workspace_loaded_for" not in st.session_state or st.session_state["workspace_loaded_for"] != active_workspace:
        _set_session_from_workspace_config(active_entry["config"])
        st.session_state["workspace_loaded_for"] = active_workspace

    if "results_df" not in st.session_state:
        st.session_state["results_df"] = pd.DataFrame()
    if "new_since_last_run_df" not in st.session_state:
        st.session_state["new_since_last_run_df"] = pd.DataFrame()
    if "last_run_meta" not in st.session_state:
        st.session_state["last_run_meta"] = {}

    st.markdown(
        """
        <div class="hero">
          <h1>paperscout: Research Signal Console</h1>
          <p>
            Von Journal-Scan zu kuratiertem Signal Feed in einem Run.
            Mit Workspaces, gespeicherten Scans und Delta-Tracking.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown("### Workspaces")

        selected_workspace = st.selectbox(
            "Aktiver Workspace",
            options=workspace_names,
            key="workspace_select_input",
        )

        if selected_workspace != active_workspace:
            st.session_state["active_workspace"] = selected_workspace
            selected_entry = _normalize_workspace_entry((store.get("workspaces") or {}).get(selected_workspace))
            _set_session_from_workspace_config(selected_entry["config"])
            st.session_state["workspace_loaded_for"] = selected_workspace
            st.session_state["results_df"] = pd.DataFrame()
            st.session_state["new_since_last_run_df"] = pd.DataFrame()
            st.session_state["last_run_meta"] = {}
            st.rerun()

        create_name = st.text_input("Neuer Workspace", value="", key="workspace_create_name")
        ws_col1, ws_col2 = st.columns(2)
        create_clicked = ws_col1.button("Erstellen", use_container_width=True)
        delete_clicked = ws_col2.button("Löschen", use_container_width=True)
        confirm_delete = st.checkbox("Löschen bestätigen", value=False, key="workspace_delete_confirm")
        save_config_clicked = st.button("Config speichern", use_container_width=True)

        if create_clicked:
            safe_name = _sanitize_workspace_name(create_name)
            if not safe_name:
                st.warning("Bitte einen Workspace-Namen angeben.")
            elif safe_name in (store.get("workspaces") or {}):
                st.warning("Workspace existiert bereits.")
            else:
                (store.get("workspaces") or {})[safe_name] = {
                    "config": _default_workspace_config(),
                    "last_keys": [],
                    "last_run_at": "",
                    "last_result_count": 0,
                }
                _save_workspace_store(store)
                st.session_state["active_workspace"] = safe_name
                st.session_state["workspace_select_input"] = safe_name
                st.session_state["workspace_create_name"] = ""
                st.rerun()

        if delete_clicked:
            if len(workspace_names) <= 1:
                st.warning("Mindestens ein Workspace muss erhalten bleiben.")
            elif not confirm_delete:
                st.warning("Bitte Löschen bestätigen.")
            else:
                (store.get("workspaces") or {}).pop(active_workspace, None)
                _ensure_default_workspace(store)
                _save_workspace_store(store)
                next_workspace = sorted((store.get("workspaces") or {}).keys())[0]
                st.session_state["active_workspace"] = next_workspace
                st.session_state["workspace_select_input"] = next_workspace
                st.session_state["results_df"] = pd.DataFrame()
                st.session_state["new_since_last_run_df"] = pd.DataFrame()
                st.session_state["last_run_meta"] = {}
                st.rerun()

        if save_config_clicked:
            current = _read_workspace_config_from_session()
            current_entry = _normalize_workspace_entry((store.get("workspaces") or {}).get(active_workspace))
            (store.get("workspaces") or {})[active_workspace] = {
                "config": current,
                "last_keys": current_entry.get("last_keys", []),
                "last_run_at": current_entry.get("last_run_at", ""),
                "last_result_count": current_entry.get("last_result_count", 0),
            }
            _save_workspace_store(store)
            st.success("Workspace-Konfiguration gespeichert.")

        active_entry = _normalize_workspace_entry((store.get("workspaces") or {}).get(active_workspace))
        if active_entry.get("last_run_at"):
            st.caption(
                f"Letzter Run: {active_entry['last_run_at']} · "
                f"{active_entry.get('last_result_count', 0)} Treffer"
            )
        else:
            st.caption("Noch kein Run in diesem Workspace.")

        st.markdown("---")
        st.markdown("### Command Center")

        selected_defaults = st.multiselect(
            "Starter-Journals",
            options=DEFAULT_JOURNALS,
            key="selected_defaults_input",
        )
        manual_journals = st.text_area(
            "Weitere Journals (Zeile, Komma oder Semikolon)",
            key="manual_journals_input",
            height=110,
            placeholder="z. B. Organization Science; Management Science",
        )
        upload = st.file_uploader(
            "Journals-Datei",
            type=["xlsx", "xls", "csv"],
            key="workspace_journal_upload",
        )

        range_mode = st.radio(
            "Zeitraum",
            options=["Letzte 30 Tage", "Letzte 90 Tage", "Letztes Jahr", "Custom"],
            key="range_mode_input",
        )
        if range_mode != "Custom":
            _set_date_preset_for_range_mode(range_mode)

        since = st.date_input("Seit", key="since_input")
        until = st.date_input("Bis", key="until_input")
        rows = st.slider(
            "Max Treffer pro Journal",
            min_value=20,
            max_value=300,
            step=20,
            key="rows_input",
        )
        focus_query = st.text_area(
            "Research Focus (optional)",
            key="focus_query_input",
            placeholder="z. B. leadership under uncertainty in healthcare teams",
        )

        run_scan = st.button("Scan starten", use_container_width=True, type="primary")
        reset = st.button("Reset Session", use_container_width=True)

    if reset:
        st.session_state["results_df"] = pd.DataFrame()
        st.session_state["new_since_last_run_df"] = pd.DataFrame()
        st.session_state["last_run_meta"] = {}
        st.rerun()

    if run_scan:
        journals = _extract_journals(upload, manual_journals, selected_defaults)
        if not journals:
            st.error("Bitte mindestens ein Journal auswählen oder eingeben.")
        elif since > until:
            st.error("Ungültiger Zeitraum: 'Seit' darf nicht nach 'Bis' liegen.")
        else:
            current_entry = _normalize_workspace_entry((store.get("workspaces") or {}).get(active_workspace))
            previous_keys = set(current_entry.get("last_keys", []))

            all_articles = []
            errors = []
            progress = st.progress(0, text="Scan startet...")
            for idx, journal in enumerate(journals, start=1):
                progress.progress(
                    int((idx - 1) / len(journals) * 100),
                    text=f"Scanne {journal}",
                )
                try:
                    arts = fetch_from_crossref_strict(
                        journal=journal,
                        rows=int(rows),
                        since=since.isoformat(),
                        until=until.isoformat(),
                    )
                    all_articles.extend(arts)
                except Exception as exc:
                    errors.append(f"{journal}: {exc}")
            progress.progress(100, text="Aufbereitung läuft...")

            deduped = dedup_by_doi(all_articles)
            df = _articles_to_df(deduped)
            if not df.empty:
                df = _add_scores(df, focus_query)
            df = _attach_paper_keys(df)

            if previous_keys and not df.empty:
                new_df = df[~df["paper_key"].isin(previous_keys)].copy()
            else:
                new_df = pd.DataFrame(columns=df.columns)

            st.session_state["results_df"] = df
            st.session_state["new_since_last_run_df"] = new_df
            run_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            st.session_state["last_run_meta"] = {
                "workspace": active_workspace,
                "journals": journals,
                "since": since.isoformat(),
                "until": until.isoformat(),
                "rows": int(rows),
                "focus_query": focus_query,
                "errors": errors,
                "new_count": len(new_df),
                "run_at": run_at,
            }

            (store.get("workspaces") or {})[active_workspace] = {
                "config": _read_workspace_config_from_session(),
                "last_keys": df["paper_key"].astype(str).tolist()[:10000],
                "last_run_at": run_at,
                "last_result_count": len(df),
            }
            _save_workspace_store(store)

            st.success(f"Scan abgeschlossen: {len(df)} Treffer.")
            if previous_keys:
                st.info(f"Neu seit letztem Run in '{active_workspace}': {len(new_df)}")
            else:
                st.info("Erster Run in diesem Workspace: Delta-Basis wurde angelegt.")
            if errors:
                with st.expander("Journals mit Fehlern", expanded=False):
                    st.write("\n".join(errors))

    df = st.session_state.get("results_df", pd.DataFrame())
    meta = st.session_state.get("last_run_meta", {})
    new_since_last_run = st.session_state.get("new_since_last_run_df", pd.DataFrame())
    if df.empty:
        _render_empty_state()
        return

    high_signal_new = 0
    if not new_since_last_run.empty and "signal_score" in new_since_last_run.columns:
        signal_vals = pd.to_numeric(new_since_last_run["signal_score"], errors="coerce").fillna(0.0)
        high_signal_new = int((signal_vals >= 80.0).sum())
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Treffer", len(df))
    c2.metric("Journals", len(set(df["journal"].astype(str).tolist())))
    abs_share = round((df["abstract"].astype(str).str.len() > 0).mean() * 100.0, 1)
    c3.metric("Mit Abstract", f"{abs_share}%")
    c4.metric("Neu seit letztem Run", len(new_since_last_run))
    c5.metric("Workspace", meta.get("workspace", st.session_state.get("active_workspace", "-")))
    if high_signal_new:
        st.warning(f"{high_signal_new} neue High-Signal-Papers (Signal >= 80) entdeckt.")

    with st.expander("Filter", expanded=True):
        f1, f2, f3 = st.columns([2, 1, 1])
        keyword = f1.text_input("Keyword in Titel/Abstract", value="")
        journal_filter = f2.multiselect(
            "Journal",
            sorted(df["journal"].astype(str).dropna().unique().tolist()),
            default=[],
        )
        abstract_only = f3.checkbox("Nur mit Abstract", value=False)

    filtered = df.copy()
    if keyword.strip():
        k = keyword.strip().lower()
        mask = (
            filtered["title"].astype(str).str.lower().str.contains(k, na=False)
            | filtered["abstract"].astype(str).str.lower().str.contains(k, na=False)
        )
        filtered = filtered[mask]
    if journal_filter:
        filtered = filtered[filtered["journal"].isin(journal_filter)]
    if abstract_only:
        filtered = filtered[filtered["abstract"].astype(str).str.len() > 0]

    tab_feed, tab_delta, tab_data, tab_export = st.tabs(
        ["Signal Feed", "Neu seit letztem Run", "Dataset", "Export"]
    )

    with tab_feed:
        st.caption(f"{len(filtered)} Ergebnisse im aktuellen Filter.")
        top_terms = Counter(
            t
            for txt in (filtered["title"].astype(str) + " " + filtered["abstract"].astype(str)).tolist()
            for t in _tokenize(txt)
        ).most_common(12)
        if top_terms:
            st.write("Top Terms:", ", ".join(t for t, _ in top_terms))

        if "issued" in filtered.columns:
            time_df = filtered.copy()
            time_df["issued_dt"] = time_df["issued"].astype(str).map(_parse_date)
            time_df = time_df.dropna(subset=["issued_dt"])
            if not time_df.empty:
                monthly = (
                    time_df.assign(month=time_df["issued_dt"].dt.to_period("M").astype(str))
                    .groupby("month")["title"]
                    .count()
                    .rename("papers")
                )
                st.line_chart(monthly)

        page_size = st.selectbox("Ergebnisse pro Seite", [10, 20, 30], index=1, key="feed_page_size")
        total = len(filtered)
        pages = max((total - 1) // page_size + 1, 1)
        page = st.number_input(
            "Seite",
            min_value=1,
            max_value=pages,
            value=1,
            step=1,
            key="feed_page_number",
        )
        start = (page - 1) * page_size
        end = min(start + page_size, total)
        st.caption(f"Zeige {start + 1} bis {end} von {total}.")
        if total > 0:
            _render_cards(filtered, start, end)
        else:
            st.info("Keine Ergebnisse für den aktuellen Filter.")

    with tab_delta:
        if new_since_last_run.empty:
            st.info("Keine neuen Treffer seit dem letzten Run in diesem Workspace.")
        else:
            st.success(f"{len(new_since_last_run)} neue Treffer seit dem letzten Workspace-Run.")
            d1, d2 = st.columns([1, 2])
            min_signal = d1.slider(
                "Min. Signal",
                min_value=0.0,
                max_value=100.0,
                value=65.0,
                step=5.0,
                key="delta_min_signal",
            )
            delta_journals = d2.multiselect(
                "Journals (Delta)",
                options=sorted(new_since_last_run["journal"].astype(str).dropna().unique().tolist()),
                default=[],
                key="delta_journals",
            )
            signal_vals = pd.to_numeric(new_since_last_run["signal_score"], errors="coerce").fillna(0.0)
            delta_view = new_since_last_run[signal_vals >= float(min_signal)].copy()
            if delta_journals:
                delta_view = delta_view[delta_view["journal"].isin(delta_journals)]
            st.caption(f"{len(delta_view)} neue Treffer im Delta-Filter.")
            if not delta_view.empty:
                st.dataframe(
                    delta_view[
                        ["signal_score", "issued", "journal", "title", "authors", "doi_url"]
                    ].rename(columns={"doi_url": "doi"}),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Im Delta-Filter sind aktuell keine Treffer.")

    with tab_data:
        display = filtered[
            [
                "signal_score",
                "relevance_score",
                "recency_score",
                "issued",
                "journal",
                "title",
                "authors",
                "doi_url",
            ]
        ].copy()
        display = display.rename(
            columns={
                "signal_score": "signal",
                "relevance_score": "relevance",
                "recency_score": "recency",
                "doi_url": "doi",
            }
        )
        st.dataframe(display, use_container_width=True, hide_index=True)

    with tab_export:
        csv_data = filtered.to_csv(index=False).encode("utf-8")
        st.download_button(
            "CSV herunterladen",
            data=csv_data,
            file_name=f"paperscout_results_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            filtered.to_excel(writer, index=False, sheet_name="papers")
        st.download_button(
            "Excel herunterladen",
            data=buf.getvalue(),
            file_name=f"paperscout_results_{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        if not new_since_last_run.empty:
            delta_csv = new_since_last_run.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Delta CSV herunterladen",
                data=delta_csv,
                file_name=f"paperscout_delta_{date.today().isoformat()}.csv",
                mime="text/csv",
                use_container_width=True,
            )


if __name__ == "__main__":
    _render_main()
