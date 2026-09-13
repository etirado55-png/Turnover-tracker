# bays_capsules_status.py
#
# 2×2 Bays & Capsules View + SMALL colored title (no big white banner)
# - Grid: [ Bay 1 ][ Bay 2 ]
#         [ Bay 3 ][ Bay 4 ]
# - Only OPEN work orders (latest row per WO) appear
# - Append Box "Submit Update" writes a new row to the Entries sheet

import re
import html
import time
import random
import string
import datetime as dt
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from gspread.exceptions import APIError
from gsheets_drive import get_gc, open_spreadsheet

# ---------- Timezone ----------
TZ = ZoneInfo("America/New_York")

def _now_et():
    """Current time in Eastern Time."""
    return datetime.now(TZ)

def _working_date() -> dt.date:
    """Overnight shift: before 7 AM rolls back to previous day."""
    now = _now_et()
    if now.hour < 7:
        return (now - dt.timedelta(days=1)).date()
    return now.date()

def _now_utc_isostr() -> str:
    """UTC ISO timestamp matching main app format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# ---------- One-time CSS ----------
if "resogreen_css_applied" not in st.session_state:
    st.markdown("<style>.resogreen{color:#0b8a2a;font-weight:500;}</style>", unsafe_allow_html=True)
    st.session_state["resogreen_css_applied"] = True

# Namespaced widget keys to avoid DuplicateWidgetID across the app
NS = st.session_state.setdefault("__bcap_ns", "bcap")
def _k(s: str) -> str:
    return f"{NS}_{s}"

st.markdown("""
<style>
.bay-card{
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 10px rgba(0,0,0,.18);
  transition: transform .15s ease, box-shadow .15s ease, border-color .2s ease;
  backdrop-filter: saturate(120%) blur(4px);
}
.bay-card:hover{
  transform: translateY(-1px);
  box-shadow: 0 10px 26px rgba(0,0,0,.24);
  border-color: rgba(255,255,255,0.18);
}
.bay-header{
  color: #fff;
  display:flex; align-items:center; justify-content:space-between;
  position: relative;
}
.bay-header::after{
  content:"";
  position:absolute; left:-20%; top:0; height:3px; width:40%;
  background: rgba(255,255,255,.6);
  filter: blur(2px);
  animation: glide 3.2s linear infinite;
}
@keyframes glide { 0%{transform:translateX(0)} 100%{transform:translateX(320%)} }
.bay-title{font-weight:800;font-size:1.35rem;line-height:1.15;}
.bay-meta{font-size:0.9rem;opacity:.92;}
</style>
""", unsafe_allow_html=True)

# ------------------ Config ------------------

TAB_NAME = "Entries"

EXPECTED_HEADERS = [
    "WO", "Title", "Resolution", "Date", "Location",
    "Status", "AssignedTo", "Attachments", "EntryID", "CreatedAt",
    "Capsule", "Bay", "CapsuleID"
]

CLOSED_STATUSES = {"COMPLETED", "COMP", "CLOSED", "RTS", "DONE"}

APPEND_STATUSES = [
    "APPR", "WIP", "WMATL", "WAPPR", "PO Created", "NOTE",
    "Completed", "CLOSED"
]

_BAY_COLOR = {
    "1": "#e6b800",
    "2": "#1e66d0",
    "3": "#d9730d",
    "4": "#0b8a2a",
}
_BAY_COLOR_DARK = {
    "1": "#b58f00",
    "2": "#1653a9",
    "3": "#b25e0a",
    "4": "#086d22",
}

STATUS_COLOR = {
    "APPR": "#FFA500",
    "WIP": "#FF0000",
    "Completed": "#59c36a",
    "CLOSED": "#59c36a",
    "WMATL": "#5aa7ff",
    "WAPPR": "#6b7280",
    "PO Created": "#6b7280",
    "NOTE": "#6b7280",
}
def _norm_key(s: str) -> str:
    s = (s or "").strip().replace("_", " ")
    s = " ".join(s.split())
    return s.upper()
_COMBINED_COLOR_MAP = {_norm_key(k): v for k, v in STATUS_COLOR.items()}

def colored_status(text: str, bg: str | None = None, fg: str = "white") -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if bg is None:
        bg = _COMBINED_COLOR_MAP.get(_norm_key(text), "#6b7280")
    return (
        f"<span style='display:inline-block;padding:.15rem .5rem;border-radius:9999px;"
        f"font-size:.75rem;font-weight:600;background:{bg};color:{fg};'>{html.escape(text)}</span>"
    )

# ------------------ Sheet helpers ------------------

def _with_backoff(fn, *args, **kwargs):
    delay = 1.0
    for _ in range(6):
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            msg = str(e).lower()
            if "quota" in msg or "ratelimit" in msg or "exceeded" in msg:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("Google Sheets backoff exhausted")

def _open_entries_ws():
    gc = get_gc()
    sh = open_spreadsheet(gc=gc)

    try:
        ws = sh.worksheet(TAB_NAME)
    except Exception:
        ws = _with_backoff(sh.add_worksheet, title=TAB_NAME, rows=2000, cols=20)
        _with_backoff(ws.update, "A1", [EXPECTED_HEADERS])
        try:
            ws.freeze(rows=1)
        except Exception:
            pass
        return ws

    first_row = _with_backoff(ws.row_values, 1)

    if not first_row:
        _with_backoff(ws.update, "A1", [EXPECTED_HEADERS])
        try:
            ws.freeze(rows=1)
        except Exception:
            pass
        return ws

    headers_clean = [h.strip() for h in first_row]
    missing = [h for h in EXPECTED_HEADERS if h not in headers_clean]
    if missing:
        new_headers = headers_clean + missing
        _with_backoff(ws.update, "A1", [new_headers])

    return ws


@st.cache_data(ttl=30)
def load_entries_df() -> pd.DataFrame:
    ws = _open_entries_ws()
    rows = _with_backoff(ws.get_all_records)
    return pd.DataFrame(rows)

def _sheet_headers(ws) -> list[str]:
    return [h.strip() for h in ws.row_values(1)]

def _row_from_dict(data: dict, headers: list[str]) -> list[str]:
    return [str(data.get(h, "")) for h in headers]

def append_entry(row: dict) -> None:
    ws = _open_entries_ws()
    headers = _sheet_headers(ws)
    values = _row_from_dict(row, headers)
    _with_backoff(ws.append_row, values, value_input_option="USER_ENTERED")

def gen_entry_id() -> str:
    ts = int(time.time() * 1000)
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"E{ts}{rnd}"

# ------------------ Time normalizers ------------------

_BAY_RE = re.compile(r"\bbay\s*([1-4])\b", re.I)
_CAP_RE = re.compile(r"\bcap(?:sule)?\s*#?\s*0*([1-9]|10)\b", re.I)

def _norm_bay_value(val: str, fallback_location: str = "") -> str:
    s = str(val or "").strip()
    if not s and fallback_location:
        s = str(fallback_location).strip()
    if s.isdigit() and s in {"1", "2", "3", "4"}:
        return s
    m = _BAY_RE.search(s)
    if m:
        return m.group(1)
    m2 = re.search(r"\b([1-4])\b", s)
    if m2:
        return m2.group(1)
    return ""

def _norm_capsule_value(val: str, *fallback_fields: str) -> str:
    def _scan(txt: str) -> str:
        m = _CAP_RE.search(txt)
        if m:
            return f"Cap #{m.group(1)}"
        m2 = re.search(r"\b([1-9]|10)\b", txt)
        if m2:
            return f"Cap #{m2.group(1)}"
        return ""
    s = str(val or "").strip()
    hit = _scan(s)
    if hit:
        return hit
    for f in fallback_fields:
        t = str(f or "").strip()
        hit = _scan(t)
        if hit:
            return hit
    return ""

def _parse_ts_row(created_at: str, date_str: str):
    if pd.notna(created_at) and str(created_at).strip():
        ts = pd.to_datetime(created_at, errors="coerce", utc=True)
        if pd.notna(ts):
            return ts
    if pd.notna(date_str) and str(date_str).strip():
        ts = pd.to_datetime(date_str, errors="coerce")
        if pd.notna(ts):
            return ts
    return pd.NaT

def _norm_ts(series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(series, errors="coerce", utc=True)
    return ts.fillna(pd.Timestamp("1970-01-01", tz="UTC"))

# ------------------ Latest + History builders ------------------

def _latest_rows_per_wo(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "WO" not in df.columns:
        return df.iloc[0:0] if isinstance(df, pd.DataFrame) else pd.DataFrame()

    d = df.copy()
    d["WO"] = d["WO"].astype(str).str.strip()
    d = d[d["WO"] != ""].copy()

    if d.empty:
        return d

    d["__ts"] = [_parse_ts_row(ca, dt_) for ca, dt_ in zip(d.get("CreatedAt", ""), d.get("Date", ""))]
    d["__created_sort"] = d["CreatedAt"].astype(str).str.strip() if "CreatedAt" in d.columns else ""
    d["__ts_norm"] = _norm_ts(d["__ts"])

    out = (
        d.sort_values(["__ts_norm", "__created_sort"], ascending=[True, True])
         .groupby("WO", as_index=False, sort=False)
         .tail(1)
         .copy()
    )

    return out.drop(columns=["__ts_norm", "__created_sort"], errors="ignore")

def _build_history_map(df: pd.DataFrame) -> dict:
    out = {}
    d = df.copy()
    d["__ts"] = [_parse_ts_row(ca, dt_) for ca, dt_ in zip(d.get("CreatedAt", ""), d.get("Date", ""))]
    d["__created_sort"] = d["CreatedAt"].astype(str).str.strip() if "CreatedAt" in d.columns else ""
    d["__ts_norm"] = _norm_ts(d["__ts"])

    for wo, thread in d.groupby(d["WO"].astype(str).str.strip(), dropna=False, sort=False):
        thr = thread.sort_values(["__ts_norm", "__created_sort"], ascending=[False, False])
        items = []
        for _, r in thr.iterrows():
            dt_str = str(r.get("Date", "")).strip()
            st_str = str(r.get("Status", "")).strip()
            res    = str(r.get("Resolution", "")).strip() or str(r.get("Description", "")).strip()
            parts = []
            if dt_str:
                parts.append(f"[{dt_str}]")
            if st_str:
                parts.append(st_str)
            if res:
                parts.append(res)
            if parts:
                items.append(" ".join(parts))
        out[wo] = items
    return out

# ------------------ Filters + small helpers ------------------

def _filter_open_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Status" not in df.columns:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    out = df.copy()
    out["Status"] = out["Status"].astype(str).str.strip().str.upper()
    return out[~out["Status"].isin(CLOSED_STATUSES)].copy()

def _normalize_history(row):
    hist = row.get("History", "")
    if isinstance(hist, list):
        hist_list = [str(x) for x in hist if str(x).strip()]
        hist_list = [h for h in hist_list if h.lower() != "nan"]
        return hist_list
    if isinstance(hist, str):
        parts = [p.strip() for p in hist.splitlines() if p.strip()]
        parts = [p for p in parts if p.lower() != "nan"]
        return parts
    return []

def _latest_resolution_text(row):
    history_list = _normalize_history(row)
    if not history_list:
        return ""
    return history_list[0]

def _wo_header_text(row):
    wo_no   = str(row.get("WO", "")).strip()
    cap_raw = str(row.get("Capsule", "")).strip()
    title   = str(row.get("Title", "")).strip()
    cap_part = f" | {cap_raw}" if cap_raw else ""
    return f"{wo_no}{cap_part} | {title}"

# ------------------ UI: Append Box + WO renderers ------------------

def _render_append_box():
    st.markdown(
        """
        <div style="
            background: transparent;
            padding:12px 14px;
            border:1px solid rgba(255,255,255,.15);
            border-radius:10px;
            margin-top:16px;
        ">
            <div style="font-weight:700; font-size:1.0rem; text-align:center;">
                Append Box
            </div>
        """,
        unsafe_allow_html=True
    )

    sel = st.session_state.get("selected_wo")
    if not sel:
        st.caption("Select a WO from any bay to stage an update.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    wo_no   = sel.get("WO", "")
    title   = sel.get("Title", "")
    capsule = sel.get("Capsule", "")
    bay     = sel.get("Bay", "")
    status  = sel.get("Status", "")

    st.markdown(
        f"<div style='font-weight:500;'>Editing {html.escape(wo_no)} | {html.escape(title)} | "
        f"{html.escape(capsule)} | Bay {html.escape(bay)}</div>",
        unsafe_allow_html=True
    )

    if "append_status" not in st.session_state:
        st.session_state["append_status"] = status or "NOTE"
    current = st.session_state.get("append_status", "NOTE")
    try:
        idx = APPEND_STATUSES.index(current)
    except ValueError:
        idx = 0

    chosen = st.selectbox(
        "Status",
        APPEND_STATUSES,
        index=idx,
        key=_k("status_select")
    )
    st.session_state["append_status"] = chosen

    if "append_text" not in st.session_state:
        st.session_state["append_text"] = ""
    st.session_state["append_text"] = st.text_area(
        "New Resolution / Note to append (becomes the newest entry)",
        value=st.session_state["append_text"],
        height=120,
        key=_k("text_area")
    )

    if st.button("Submit Update", key=_k("submit_btn"), use_container_width=True):
        _submit_append_update()

    st.markdown("</div>", unsafe_allow_html=True)

def _render_single_wo(row):
    wo_no = str(row.get("WO", "")).strip()
    header_line = _wo_header_text(row)
    status_txt  = str(row.get("Status", "")).strip()
    status_pill = colored_status(status_txt)

    st.markdown(
        f"<div style='display:flex;align-items:center;gap:.5rem;'>"
        f"<strong>{html.escape(header_line)}</strong> {status_pill}"
        f"</div>",
        unsafe_allow_html=True
    )

    latest_txt = _latest_resolution_text(row)
    if latest_txt:
        st.markdown(
            f"<div class='resogreen'>Latest: {html.escape(latest_txt)}</div>",
            unsafe_allow_html=True
        )

    with st.expander("Details & History", expanded=False):
        full_hist = _normalize_history(row)
        if full_hist:
            st.markdown("**Full History (newest first):**")
            for h in full_hist:
                st.write(f"- {h}")
        else:
            st.caption("No history recorded for this WO.")

        if st.button(f"Select {wo_no}", key=_k(f"select_{wo_no}")):
            st.session_state["selected_wo"] = {
                "WO": wo_no,
                "Title": str(row.get("Title", "")).strip(),
                "Status": status_txt,
                "Capsule": str(row.get("Capsule", "")).strip(),
                "Bay": str(row.get("Bay", "")).strip(),
                "Location": str(row.get("Location", "")).strip(),
            }
            st.session_state["append_status"] = st.session_state["selected_wo"]["Status"] or "NOTE"
            st.session_state["append_text"] = ""
            st.toast(f"WO {wo_no} loaded below")

def _render_bay(df_all, bay_number: str):
    accent = _BAY_COLOR.get(str(bay_number), "#444")
    accent_dark = _BAY_COLOR_DARK.get(str(bay_number), "#333")

    series_bay = df_all.get("Bay", pd.Series(index=df_all.index, dtype=object)).astype(str).str.strip()
    bay_mask = series_bay == str(bay_number)
    df_bay = df_all[bay_mask].copy() if not df_all.empty else pd.DataFrame()
    df_bay_open = _filter_open_rows(df_bay)
    n = len(df_bay_open)
    compact = (n == 0)

    st.markdown("<div class='bay-card'>", unsafe_allow_html=True)

    header_pad = "8px 12px" if compact else "12px 14px"
    st.markdown(
        f"""
        <div class="bay-header" style="
            background: linear-gradient(135deg, {accent} 0%, {accent_dark} 100%);
            padding:{header_pad};
        ">
          <div class="bay-title">Bay #{html.escape(str(bay_number))}</div>
          <div class="bay-meta">Open WO: {n}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    body_pad = "10px 12px" if compact else "12px 14px 10px 14px"
    st.markdown(f"<div style='padding:{body_pad};'>", unsafe_allow_html=True)

    if compact:
        st.caption("No open work orders in this bay.")
    else:
        sort_cols = []
        if "Capsule" in df_bay_open.columns:
            sort_cols.append("Capsule")
        if "WO" in df_bay_open.columns:
            sort_cols.append("WO")
        if sort_cols:
            df_bay_open = df_bay_open.sort_values(sort_cols)

        st.markdown("<div style='max-height:420px; overflow:auto; padding-right:4px;'>",
                    unsafe_allow_html=True)
        for _, row in df_bay_open.iterrows():
            _render_single_wo(row)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# ------------------ Submit handler ------------------

def _submit_append_update():
    """Write a new row using ET working date and UTC CreatedAt — matches main app format."""
    sel = st.session_state.get("selected_wo") or {}
    if not sel:
        st.error("No WO selected.")
        return

    wo = str(sel.get("WO", "")).strip()
    if not wo:
        st.error("Selected WO is empty.")
        return

    title   = str(sel.get("Title", "")).strip()
    loc     = str(sel.get("Location", "")).strip()
    bay     = str(sel.get("Bay", "")).strip()
    capsule = str(sel.get("Capsule", "")).strip()
    status  = str(st.session_state.get("append_status", "NOTE")).strip()
    note    = str(st.session_state.get("append_text", "")).strip()

    # Reload latest row for this WO to fill any missing fields
    entries_df = load_entries_df()
    if not entries_df.empty and "WO" in entries_df.columns:
        wo_rows = entries_df[entries_df["WO"].astype(str).str.strip() == wo].copy()
        if not wo_rows.empty:
            wo_rows["__ts"] = [
                _parse_ts_row(ca, dt_) for ca, dt_ in zip(wo_rows.get("CreatedAt", ""), wo_rows.get("Date", ""))
            ]
            latest = wo_rows.sort_values("__ts").iloc[-1]
            if not title:   title   = str(latest.get("Title", "")).strip()
            if not loc:     loc     = str(latest.get("Location", "")).strip()
            if not bay:     bay     = str(latest.get("Bay", "")).strip()
            if not capsule: capsule = str(latest.get("Capsule", "")).strip()

    if not bay or not capsule:
        st.error(f"Cannot append — Bay/Capsule missing. Bay='{bay}' Capsule='{capsule}'")
        return

    row = {
        "WO":          wo,
        "Title":       title,
        "Resolution":  note,
        # ✅ Use ET working date (respects overnight shift) — matches main app WORKING_DATE
        "Date":        _working_date().strftime("%Y-%m-%d"),
        "Location":    loc,
        "Status":      status,
        "AssignedTo":  "",
        "Attachments": "",
        "EntryID":     gen_entry_id(),
        # ✅ UTC ISO with timezone offset — matches main app now_utc_isostr() format
        "CreatedAt":   _now_utc_isostr(),
        "Capsule":     capsule,
        "Bay":         bay,
        "CapsuleID":   "",
    }

    try:
        append_entry(row)
        st.session_state.setdefault("selected_wo", {})["Status"] = status
        st.success(f"Update saved for WO {wo} ({status}).")
        st.session_state.pop("append_text", None)

        if str(status).upper() in {"COMPLETED", "CLOSED", "COMP", "RTS", "DONE"}:
            st.session_state.pop("selected_wo", None)

        try:
            st.cache_data.clear()
        except Exception:
            pass
        try:
            st.cache_resource.clear()
        except Exception:
            pass

        st.rerun()

    except Exception as e:
        st.error(f"Failed to save update: {e}")

# ------------------ Entry point ------------------

def show_bays_capsules(df_all: pd.DataFrame):
    """
    Show all open WO threads in Bays & Capsules.
    Visibility decided by WO thread — stays visible until that WO's latest row is closed.
    """
    st.title("Bays & Capsules Status")

    if df_all is None or df_all.empty:
        df_all = pd.DataFrame(columns=[
            "WO", "Title", "Status", "Bay", "Capsule", "History",
            "Date", "CreatedAt", "Resolution", "Description", "Location"
        ])

    d = df_all.copy()

    for c in ["WO", "Title", "Status", "Bay", "Capsule", "History",
              "Date", "CreatedAt", "Resolution", "Description", "Location"]:
        if c not in d.columns:
            d[c] = ""

    d["WO"]       = d["WO"].astype(str).str.strip()
    d["Status"]   = d["Status"].astype(str).str.strip()
    d["Location"] = d["Location"].astype(str).str.strip()

    d["Bay"] = [_norm_bay_value(b, loc) for b, loc in zip(d["Bay"], d["Location"])]
    d["Capsule"] = [
        _norm_capsule_value(c, t, r, desc)
        for c, t, r, desc in zip(d["Capsule"], d["Title"], d["Resolution"], d["Description"])
    ]

    d = d[
        d["Bay"].isin(["1", "2", "3", "4"]) &
        d["Capsule"].astype(str).str.strip().ne("") &
        d["WO"].ne("")
    ].copy()

    if d.empty:
        st.caption("No capsule-related entries found.")
        _render_append_box()
        return

    latest = _latest_rows_per_wo(d)
    latest_open = _filter_open_rows(latest)
    hist_map = _build_history_map(d)
    latest_open = latest_open.copy()
    latest_open["History"] = latest_open["WO"].astype(str).map(hist_map).apply(
        lambda v: v if isinstance(v, list) else []
    )

    latest_open["__sort_cap"] = latest_open["Capsule"].astype(str).str.extract(r"(\d+)")[0].fillna("999")
    latest_open["__sort_cap"] = pd.to_numeric(latest_open["__sort_cap"], errors="coerce").fillna(999)

    top_left, top_right = st.columns(2)
    with top_left:
        _render_bay(latest_open.sort_values(["__sort_cap", "WO"]), bay_number="1")
    with top_right:
        _render_bay(latest_open.sort_values(["__sort_cap", "WO"]), bay_number="2")

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    bottom_left, bottom_right = st.columns(2)
    with bottom_left:
        _render_bay(latest_open.sort_values(["__sort_cap", "WO"]), bay_number="3")
    with bottom_right:
        _render_bay(latest_open.sort_values(["__sort_cap", "WO"]), bay_number="4")

    _render_append_box()
