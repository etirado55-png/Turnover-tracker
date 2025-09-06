# streamlit_app.py  — Turnover Notes (attachments with OneDrive-or-local fallback)

import os
import time
import tempfile
import pathlib
import streamlit as st

# 1) Page setup
st.set_page_config(page_title="Turnover Notes", page_icon="🗒️", layout="wide")
st.title("Turnover Notes")

# 2) Pick a writable uploads folder (tries OneDrive path on your PC, falls back elsewhere)
def first_writable(paths):
    for p in paths:
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".write_test"
            t.write_text("ok", encoding="utf-8")
            t.unlink(missing_ok=True)
            return p
        except Exception:
            continue
    raise RuntimeError("No writable upload directory found.")

# If you ever move machines, just change the first candidate to your OneDrive path
CANDIDATES = [
    pathlib.Path("/home/eduardo/OneDrive/Turnover/uploads"),           # your Linux OneDrive
    pathlib.Path.home() / "OneDrive" / "Turnover" / "uploads",         # alt OneDrive layout
    pathlib.Path("/mount/data/uploads"),                                # Streamlit Cloud writable
    pathlib.Path.cwd() / "uploads",                                     # repo folder (may be RO in cloud)
    pathlib.Path(tempfile.gettempdir()) / "turnover_uploads",           # always-writable fallback
]
UPLOAD_DIR = first_writable(CANDIDATES)
st.caption(f"Attachments folder → {UPLOAD_DIR}")

# 3) Helpers
def safe_wo(wo: str) -> str:
    return str(wo).strip().replace("/", "_").replace("\\", "_")

def save_upload(uploaded_file, wo: str) -> pathlib.Path:
    """Save to UPLOAD_DIR/<WO>/timestamp_filename and return the path."""
    folder = UPLOAD_DIR / safe_wo(wo)
    folder.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    safe_name = uploaded_file.name.replace("/", "_").replace("\\", "_")
    out_path = folder / f"{ts}_{safe_name}"
    with open(out_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return out_path

def list_attachments(wo: str):
    """Return newest-first list of Path objects under UPLOAD_DIR/<WO>."""
    folder = UPLOAD_DIR / safe_wo(wo)
    if not folder.exists():
        return []
    return sorted(folder.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)

def is_image(path: pathlib.Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

# 4) UI — Attach files to a WO
st.divider()
st.subheader("Attach files to a Work Order")

wo_for_upload = st.text_input("WO number to attach to (e.g., 146720560)", key="wo_attach")
files = st.file_uploader(
    "Choose file(s)",
    type=["jpg","jpeg","png","gif","webp","pdf","csv","xlsx","txt","mp4"],
    accept_multiple_files=True
)

if wo_for_upload and files:
    saved_ct = 0
    for f in files:
        try:
            p = save_upload(f, wo_for_upload)
            saved_ct += 1
            st.success(f"Saved {f.name} → {p}")
        except Exception as e:
            st.error(f"Failed to save {f.name}: {e}")
    if saved_ct:
        st.toast(f"Attached {saved_ct} file(s) to WO {wo_for_upload}", icon="✅")

# 5) UI — View attachments for an old WO
st.divider()
st.subheader("View attachments for an old WO")

wo_search = st.text_input("Enter WO to view attachments", key="wo_view")
if wo_search:
    items = list_attachments(wo_search)
    if not items:
        st.info("No attachments found for that WO.")
    else:
        st.caption(f"{len(items)} file(s) found for WO {safe_wo(wo_search)} (newest first).")
        for p in items:
            if is_image(p) and p.exists():
                st.image(str(p), caption=p.name)
            else:
                st.write(f"• {p.name} — {p}")

# 6) (Optional) Quick help
with st.expander("Where do files go?"):
    st.markdown(
        f"""
- **On your Linux PC**: uploads save under `{UPLOAD_DIR}` (and sync to OneDrive if that path is your OneDrive).
- **On Streamlit Cloud**: uploads fall back to a local folder (ephemeral).
- Each WO gets a subfolder: `…/uploads/WO_NUMBER/<timestamp>_filename.ext`.
"""
    )
# --- date helpers (must be defined before use) ---
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # stdlib timezone in Python 3.9+

def shift_today(cutover_hour: int = 4, tz_name: str = "America/New_York"):
    """
    Returns the 'workday' date. Before 04:00 local, treat it as the previous day.
    Change cutover_hour if your shift rolls at a different time.
    """
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    if now.hour < cutover_hour:
        return (now - timedelta(days=1)).date()
    return now.date()
# --- end helpers ---

# --- UI ---
st.title("Turnover Notes Tracker (Web)")

today = shift_today()
df = load_df()
df_today = numeric_sort_wo(df[df["Date"] == today])

tab_input, tab_today, tab_search, tab_export = st.tabs(
    ["➕ Add/Update", "📅 Today", "🔎 Search", "📤 Export"]
)

# Add/Update (with dropdown of today's WOs)
with tab_input:
    st.subheader(f"Add or Update (Shift date: **{today}**, cutoff {CUTOFF_HOUR:02d}:00 {TZ.zone})")
    left, right = st.columns([1, 2])

    with left:
        options = ["— Select a WO from today —"] + [
            f"WO{row['WO Number']} — {row['Title']}" for _, row in df_today.iterrows()
        ]
        sel = st.selectbox("Pick today’s WO to auto-fill (optional):", options, index=0, key="selected_label")

        def parse_selected(s):
            if s.startswith("WO") and " — " in s:
                wo_part, title_part = s.split(" — ", 1)
                return wo_part.replace("WO", "").strip(), title_part
            return "", ""

        if sel != "— Select a WO from today —":
            wo_prefill, title_prefill = parse_selected(sel)
            res_prefill = ""
            mask = (df_today["WO Number"].astype(str) == wo_prefill)
            if mask.any():
                res_prefill = str(df_today.loc[mask, "Resolution"].iloc[0] or "")
        else:
            wo_prefill, title_prefill, res_prefill = "", "", ""

        wo = st.text_input("WO Number", value=wo_prefill, placeholder="146732350")

    with right:
        title_in = st.text_input("Title", value=title_prefill, placeholder="Count and identify INOP GL at WCG")
        res_in = st.text_area("Resolution (optional)", value=res_prefill, height=120)

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Save / Update Today’s WO", type="primary"):
            if wo.strip() and title_in.strip():
                status = save_row(today, wo.strip(), title_in.strip(), res_in.strip())
                st.success(f"WO{wo} {status}.")
                st.rerun()
            else:
                st.error("WO Number and Title are required.")
    with c2:
        if st.button("Clear fields"):
            st.session_state.selected_label = "— Select a WO from today —"
            st.rerun()
    with c3:
        if st.button("Refresh list"):
            st.rerun()

# Today
with tab_today:
    st.subheader(f"Today’s WOs — {today}")
    if df_today.empty:
        st.write("No entries for today yet.")
    else:
        st.dataframe(df_today.fillna(""), use_container_width=True)

# Search
with tab_search:
    st.subheader("Search by Title / Resolution")
    q = st.text_input("Search text", placeholder="e.g., PDS 3091")
    today_only = st.checkbox("Search today only", value=True)
    if st.button("Run Search"):
        base = df_today if today_only else df
        if q.strip():
            ql = q.lower()
            hits = base[
                base["Title"].str.lower().str.contains(ql, na=False)
                | base["Resolution"].str.lower().str.contains(ql, na=False)
            ]
        else:
            hits = base.iloc[0:0]
        if hits.empty:
            scope = "today" if today_only else "all dates"
            st.warning(f"No matches for “{q}” in {scope}.")
        else:
            st.dataframe(numeric_sort_wo(hits), use_container_width=True)

# Export
with tab_export:
    st.subheader("Export Today’s Turnover (plain text)")
    if df_today.empty:
        st.info("No entries to export yet.")
    else:
        lines = [f"# {today}", "", "Daily PM completed, Rain curtain Filters cleaned.", ""]
        for _, r in df_today.iterrows():
            lines.append(f"- **WO{r['WO Number']} — {r['Title']}** | {r['Resolution']}")
        export_text = "\n".join(lines)
        st.code(export_text, language="markdown")
        st.download_button("Download as .txt", export_text, file_name=f"turnover_{today}.txt")
        st.caption("Tip: long-press/copy on your phone, or download and upload to OneDrive.")
