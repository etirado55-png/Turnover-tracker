# --- Imports ---
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import pytz
import gspread
import pathlib
from google.oauth2.service_account import Credentials
from bootstrap_helpers import get_sheet_url, check_config

# --- Page Config (must be first st.* call) ---
st.set_page_config(page_title="Turnover Notes", page_icon="🗒️", layout="wide")

# ---- Writable uploads folder with OneDrive-or-local fallback ----
import pathlib, os, tempfile
import streamlit as st

def first_writable(paths):
    for p in paths:
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".write_test"
            t.write_text("ok", encoding="utf-8")
            t.unlink()
            return p
        except Exception:
            continue
    raise RuntimeError("No writable upload directory found")

CANDIDATES = [
    pathlib.Path("/home/eduardo/OneDrive/Turnover/uploads"),          # your Linux PC OneDrive
    pathlib.Path.home() / "OneDrive" / "Turnover" / "uploads",         # alt OneDrive layout
    pathlib.Path("/mount/data/uploads"),                               # Streamlit Cloud writable
    pathlib.Path.cwd() / "uploads",                                    # repo folder (may be read-only in cloud)
    pathlib.Path(tempfile.gettempdir()) / "turnover_uploads",          # always writable fallback
]

UPLOAD_DIR = first_writable(CANDIDATES)
st.caption(f"Attachments folder → {UPLOAD_DIR}")  # see which one is active
# ---- end uploads folder setup ----



def save_upload(uploaded_file, wo: str):
    safe_wo = str(wo).strip().replace("/", "_").replace("\\", "_")
    folder = UPLOAD_DIR / safe_wo
    folder.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    safe_name = uploaded_file.name.replace("/", "_").replace("\\", "_")
    out_path = folder / f"{ts}_{safe_name}"
    with open(out_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return out_path

def list_attachments(wo: str):
    folder = UPLOAD_DIR / str(wo)
    if not folder.exists():
        return []
    return sorted(folder.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)

st.caption(f"Uploads path → {UPLOAD_DIR}")  # shows exactly where files go
# --- END ---


# --- START upload section ---
# Use your OneDrive path here. If your sync_dir is different, paste that exact path.
BASE_DIR = "/home/eduardo/OneDrive"              # e.g., /home/you/OneDrive
UPLOAD_DIR = BASE_DIR / "Turnover" / "uploads"           # creates OneDrive/Turnover/uploads
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def save_upload(uploaded_file, subdir=""):
    folder = UPLOAD_DIR / subdir if subdir else UPLOAD_DIR
    folder.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() * 1000)
    safe_name = uploaded_file.name.replace("/", "_")
    out_path = folder / f"{timestamp}_{safe_name}"
    with open(out_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return out_path

tabs = st.tabs(["📤 Upload file(s)", "📷 Take a photo (iOS/Android/Desktop)"])

with tabs[0]:
    files = st.file_uploader(
        "Choose file(s)",
        type=["jpg", "jpeg", "png", "pdf", "csv", "xlsx"],
        accept_multiple_files=True,
        help="On iPhone/iPad, tap to pick from Photos or Files."
    )
    if files:
        for f in files:
            path = save_upload(f, subdir="user_uploads")
            st.success(f"Saved {f.name} to {path}")
            if f.type.startswith("image/"):
                st.image(f, caption=f.name)

with tabs[1]:
    photo = st.camera_input("Take a photo")
    if photo:
        path = save_upload(photo, subdir="camera")
        st.success(f"Photo saved to {path}")
        st.image(photo)
# --- END upload section ---
# ... your set_page_config + title + regular file_uploader code goes here ...

# === Camera (opt-in) ===
st.subheader("Optional: take a photo")
enable_cam = st.toggle(
    "Enable camera",
    value=False,
    help="Turn on only when you need it. Toggle off to release the camera."
)

# Use a placeholder so we can mount/unmount the widget
cam_slot = st.empty()

def save_upload(uploaded_file, subdir="camera"):
    UPLOAD_DIR = pathlib.Path("uploads")
    (UPLOAD_DIR / subdir).mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    safe = uploaded_file.name.replace("/", "_")
    out = UPLOAD_DIR / subdir / f"{ts}_{safe}"
    with open(out, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return out

if enable_cam:
    photo = cam_slot.camera_input("Take a photo", key="photo_input")
    if photo:
        path = save_upload(photo)
        st.success(f"Photo saved to {path}")
        st.image(photo)
else:
    # Unmount the widget and clear any prior value
    cam_slot.empty()
    if "photo_input" in st.session_state:
        del st.session_state["photo_input"]

# --- Settings ---
SHEET_NAME = "turnover_log"      # Rename your sheet tab OR set to "Sheet1"
CUTOFF_HOUR = 6                  # Night shift cutoff (6 AM)
TZ = pytz.timezone("America/New_York")

# --- Google Auth ---
creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
)
client = gspread.authorize(creds)

# --- Config Check (quiet if OK) ---
sheet_url = check_config(client, sheet_name=SHEET_NAME)
sheet = client.open_by_url(sheet_url).worksheet(SHEET_NAME)

# --- Helpers ---
def shift_today():
    now = datetime.now(TZ)
    return (now - timedelta(days=1)).date().isoformat() if now.hour < CUTOFF_HOUR else now.date().isoformat()

def ensure_header():
    if not sheet.get_all_values():
        sheet.append_row(["Date", "WO Number", "Title", "Resolution"])

def load_df():
    ensure_header()
    data = sheet.get_all_records()
    return pd.DataFrame(data, columns=["Date", "WO Number", "Title", "Resolution"])

def save_row(date_str, wo, title, resolution):
    """Add new or update today’s row with same WO."""
    df = load_df()
    mask = (df["Date"] == date_str) & (df["WO Number"].astype(str) == str(wo))
    if mask.any():
        idx = df[mask].index[0]
        row_num = idx + 2  # +1 header, +1 1-based rows
        if str(title).strip():
            sheet.update_cell(row_num, 3, title)
        sheet.update_cell(row_num, 4, resolution)
        return "updated"
    sheet.append_row([date_str, wo, title, resolution])
    return "added"

def numeric_sort_wo(df):
    def num(x):
        try:
            return int(str(x).replace("WO", ""))
        except:
            return 0
    if df.empty: 
        return df
    df = df.copy()
    df["WO Sort"] = df["WO Number"].apply(num)
    return df.sort_values("WO Sort").drop(columns=["WO Sort"])

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
