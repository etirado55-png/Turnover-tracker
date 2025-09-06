# streamlit_app.py — Turnover Notes (uploads + CSV + camera; OneDrive-or-local safe)

import os
import csv
import time
import tempfile
import pathlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# ---------------- 1) PAGE SETUP ----------------
st.set_page_config(page_title="Turnover Notes", page_icon="🗒️", layout="wide")
st.title("Turnover Notes")

# ---------------- 2) DATE HELPER ----------------
def shift_today(cutover_hour: int = 4, tz_name: str = "America/New_York"):
    """Return 'workday' date; before cutover treat as previous day."""
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    if now.hour < cutover_hour:
        return (now - timedelta(days=1)).date()
    return now.date()

today = shift_today()
st.caption(f"Turnover date → {today}")

# ---------------- 3) WRITABLE BASE DIR (OneDrive-or-local fallback) ----------------
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
    raise RuntimeError("No writable base directory found.")

# Pick ONE base place for app data (uploads + CSV)
BASE_CANDIDATES = [
    pathlib.Path("/home/eduardo/OneDrive/Turnover"),            # your Linux OneDrive
    pathlib.Path.home() / "OneDrive" / "Turnover",              # alt OneDrive layout
    pathlib.Path("/mount/data/turnover"),                       # Streamlit Cloud writable
    pathlib.Path.cwd() / "turnover_data",                       # repo folder (may be RO in cloud)
    pathlib.Path(tempfile.gettempdir()) / "turnover_data",      # always-writable fallback
]
BASE_DIR = first_writable(BASE_CANDIDATES)

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATA_FILE = DATA_DIR / "turnover.csv"   # WO,Title,Resolution,Date

st.caption(f"Attachments folder → {UPLOAD_DIR}")
st.caption(f"Data file → {DATA_FILE}")

# ---------------- 4) DATA (CSV) ----------------
CSV_COLUMNS = ["WO", "Title", "Resolution", "Date"]

def init_csv():
    if not DATA_FILE.exists():
        with open(DATA_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)

def load_df() -> pd.DataFrame:
    init_csv()
    try:
        df = pd.read_csv(DATA_FILE, dtype=str)
    except Exception:
        init_csv()
        df = pd.read_csv(DATA_FILE, dtype=str)
    # Ensure expected columns exist
    for col in CSV_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    # Normalize WO as string
    df["WO"] = df["WO"].astype(str)
    return df[CSV_COLUMNS]

def append_row(wo: str, title: str, resolution: str, date_str: str):
    init_csv()
    with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([str(wo), title, resolution, date_str])

# ---------------- 5) ATTACHMENTS HELPERS ----------------
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

# ---------------- 6) UI — QUICK ENTRY (OPTIONAL) ----------------
with st.expander("Add a quick turnover row (optional)"):
    c1, c2, c3 = st.columns([1.2, 2, 2])
    with c1:
        wo_new = st.text_input("WO", placeholder="146720560")
    with c2:
        title_new = st.text_input("Title", placeholder="Replace Ocean PEEP computer")
    with c3:
        resolution_new = st.text_input("Resolution", placeholder="Replaced; verified show OK")
    if st.button("Add row", disabled=not wo_new or not title_new):
        append_row(wo_new, title_new, resolution_new, str(today))
        st.success(f"Added WO {wo_new}")

# Load DF now that helpers exist
df = load_df()
# --- TODAY'S WORK ORDERS BOX (paste right after: df = load_df()) ---
today_str = str(today)  # uses shift_today() you already defined
st.divider()
st.subheader(f"Today's Work Orders — {today_str}")

today_rows = df[df["Date"] == today_str]

if today_rows.empty:
    st.info("No rows logged for today yet.")
else:
    st.caption(f"{len(today_rows)} item(s)")
    st.dataframe(today_rows, use_container_width=True, hide_index=True)

    # Optional: quick peek at attachments for each of today's WOs
    if st.toggle("Show today's attachments", value=False, key="show_today_atts"):
        for _, row in today_rows.iterrows():
            wo = str(row["WO"])
            st.markdown(f"**WO {wo}** — {row['Title']}")
            attachments = list_attachments(wo)
            if not attachments:
                st.write("• No attachments")
            else:
                # show images inline; list non-images
                shown = 0
                for p in attachments:
                    if is_image(p) and p.exists() and shown < 4:   # cap thumbnails so it stays tidy
                        st.image(str(p), caption=p.name, use_column_width=True)
                        shown += 1
                    else:
                        st.write(f"• {p.name} — {p}")
            st.divider()
# --- END TODAY'S WORK ORDERS BOX ---

# ---------------- 7) UI — ATTACH FILES TO A WO ----------------
st.divider()
st.subheader("Attach files to a Work Order")

wo_for_upload = st.text_input("WO number to attach to", key="wo_attach")
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

# ---------------- 8) UI — OPTIONAL CAMERA (toggle) ----------------
st.divider()
st.subheader("Take a photo (optional)")
cam_on = st.toggle("Enable camera", value=False, help="Toggle on to open camera, off to release it.")
cam_slot = st.empty()
if cam_on:
    wo_for_cam = st.text_input("WO to attach camera photo to", key="wo_cam")
    photo = cam_slot.camera_input("Take a photo")
    if wo_for_cam and photo:
        try:
            p = save_upload(photo, wo_for_cam)
            st.success(f"Photo saved → {p}")
            st.image(photo)
        except Exception as e:
            st.error(f"Failed to save photo: {e}")
else:
    cam_slot.empty()
    if "photo" in st.session_state:
        del st.session_state["photo"]

# ---------------- 9) UI — SEARCH & VIEW ----------------
st.divider()
st.subheader("Search WOs and view attachments")

q = st.text_input("Search by WO (exact) or filter by text in Title/Resolution")
show_df = df.copy()

hits = pd.DataFrame()
if q:
    # exact WO match OR substring in title/resolution
    hits = show_df[
        (show_df["WO"].astype(str) == str(q)) |
        (show_df["Title"].str.contains(q, case=False, na=False)) |
        (show_df["Resolution"].str.contains(q, case=False, na=False))
    ]

st.markdown("**Results**")
if q:
    if hits.empty:
        st.info("No rows match.")
    else:
        st.dataframe(hits, use_container_width=True, hide_index=True)
else:
    st.dataframe(show_df.tail(25), use_container_width=True, hide_index=True)

# If the query looks like a WO number, show its attachments below
wo_guess = q if q and q.isdigit() else ""
if wo_guess:
    st.markdown(f"**Attachments for WO {wo_guess}**")
    items = list_attachments(wo_guess)
    if not items:
        st.info("No attachments found for that WO.")
    else:
        st.caption(f"{len(items)} file(s) (newest first).")
        for p in items:
            if is_image(p) and p.exists():
                st.image(str(p), caption=p.name)
            else:
                st.write(f"• {p.name} — {p}")

# ---------------- 10) HELP ----------------
with st.expander("Where is everything saved?"):
    st.markdown(
        f"""
- **Base folder**: `{BASE_DIR}`
- **CSV file**: `{DATA_FILE}` (created if missing)
- **Attachments**: `{UPLOAD_DIR}` → `…/uploads/WO/<timestamp>_filename.ext`
- On your Linux PC (with OneDrive path available), this syncs to OneDrive.
- On Streamlit Cloud, it falls back to a local writable folder (ephemeral).
"""
    )
