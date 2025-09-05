import streamlit as st
# --- Debug secrets (temporary) ---
st.subheader("🔐 Secrets Debug")
st.write("Secrets keys found:", list(st.secrets.keys()))

# Check for the specific ones you need
if "gcp_service_account" in st.secrets:
    st.success("✅ gcp_service_account is present")
else:
    st.error("❌ gcp_service_account is missing")

if "SHEET_URL" in st.secrets:
    st.success("✅ SHEET_URL is present")
    st.write("Sheet URL (first 60 chars):", st.secrets["SHEET_URL"][:60] + "...")
else:
    st.error("❌ SHEET_URL is missing")

import pandas as pd
from datetime import datetime, timedelta
import pytz
import gspread
from google.oauth2.service_account import Credentials

# ================== Settings ==================
SHEET_NAME = "turnover_log"        # Tab name inside your Google Sheet
CUTOFF_HOUR = 6                    # Night-shift cutoff (6 AM)
TZ = pytz.timezone("America/New_York")

# ======= Auth to Google Sheets (Streamlit Secrets) =======
# In Streamlit Cloud: Settings → Secrets → add [gcp_service_account] and SHEET_URL
creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
)
client = gspread.authorize(creds)
sheet = client.open_by_url(st.secrets["SHEET_URL"]).worksheet(SHEET_NAME)

# ================== Helpers ==================
def ensure_header():
    values = sheet.get_all_values()
    if not values:
        sheet.append_row(["Date", "WO Number", "Title", "Resolution"])

def shift_today():
    now = datetime.now(TZ)
    if now.hour < CUTOFF_HOUR:
        return (now - timedelta(days=1)).date().isoformat()
    return now.date().isoformat()

def load_df():
    ensure_header()
    data = sheet.get_all_records()
    return pd.DataFrame(data, columns=["Date", "WO Number", "Title", "Resolution"])

def save_row(date_str, wo, title, resolution):
    """Add new or update today’s row with same WO."""
    df = load_df()
    mask = (df["Date"] == date_str) & (df["WO Number"].astype(str) == str(wo))
    if mask.any():
        idx = df[mask].index[0]     # 0-based
        row_num = idx + 2           # +1 header, +1 1-based rows
        # Update title if provided (don’t wipe it out if user leaves blank)
        if str(title).strip():
            sheet.update_cell(row_num, 3, title)
        # Resolution can be blank (don’t invent text)
        sheet.update_cell(row_num, 4, resolution)
        return "updated"
    else:
        sheet.append_row([date_str, wo, title, resolution])
        return "added"

def numeric_sort_wo(df):
    def num(x):
        try:
            return int(str(x).replace("WO", ""))
        except:
            return 0
    if not df.empty:
        df = df.copy()
        df["WO Sort"] = df["WO Number"].apply(num)
        df = df.sort_values("WO Sort").drop(columns=["WO Sort"])
    return df

# ================== UI ==================
st.set_page_config(page_title="Turnover Notes", page_icon="🗒️", layout="wide")
st.title("Turnover Notes Tracker (Web)")

# Make state keys once
for k, v in {
    "wo": "",
    "title": "",
    "resolution": "",
    "selected_label": "",
    "refresh_toggle": False,
}.items():
    st.session_state.setdefault(k, v)

today = shift_today()
df = load_df()
df_today = numeric_sort_wo(df[df["Date"] == today])

tab_input, tab_today, tab_search, tab_export = st.tabs(
    ["➕ Add/Update", "📅 Today", "🔎 Search", "📤 Export"]
)

# ---------- Add/Update (with dropdown of today's WOs) ----------
with tab_input:
    st.subheader(f"Add or Update (Shift date: **{today}**, cutoff {CUTOFF_HOUR:02d}:00 {TZ.zone})")

    left, right = st.columns([1,2])
    with left:
        # Build dropdown labels like "WO146732350 — Title"
        options = ["— Select a WO from today —"] + [
            f"WO{row['WO Number']} — {row['Title']}" for _, row in df_today.iterrows()
        ]

        selected = st.selectbox(
            "Pick today’s WO to auto-fill (optional):",
            options,
            index=0,
            key="selected_label",
        )

        def parse_selected(sel):
            if sel.startswith("WO") and " — " in sel:
                wo_part, title_part = sel.split(" — ", 1)
                wo_clean = wo_part.replace("WO", "").strip()
                return wo_clean, title_part
            return "", ""

        # If user chose an item, prefill fields (including any existing resolution)
        if selected != "— Select a WO from today —":
            wo_clean, title_prefill = parse_selected(selected)
            st.session_state.wo = wo_clean
            st.session_state.title = title_prefill
            # pull current resolution for that WO (if any)
            mask = (df_today["WO Number"].astype(str) == wo_clean)
            if mask.any():
                st.session_state.resolution = str(df_today.loc[mask, "Resolution"].iloc[0] or "")
        else:
            # leave whatever is in the fields (manual entry allowed)
            pass

        # Manual fields (can override dropdown prefill)
        st.session_state.wo = st.text_input("WO Number", value=st.session_state.wo, placeholder="146732350")
    with right:
        st.session_state.title = st.text_input("Title", value=st.session_state.title, placeholder="Count and identify INOP GL at WCG")
        st.session_state.resolution = st.text_area("Resolution (optional)", value=st.session_state.resolution, height=120)

    c1, c2, c3 = st.columns([1,1,1])
    with c1:
        if st.button("Save / Update Today’s WO", type="primary"):
            wo_in = str(st.session_state.wo).strip()
            title_in = str(st.session_state.title).strip()
            res_in = str(st.session_state.resolution).strip()
            if wo_in and title_in:
                status = save_row(today, wo_in, title_in, res_in)
                st.success(f"WO{wo_in} {status}.")
                # little refresh to update Today tab & dropdown
                st.session_state.refresh_toggle = not st.session_state.refresh_toggle
            else:
                st.error("WO Number and Title are required.")
    with c2:
        if st.button("Clear fields"):
            st.session_state.wo = ""
            st.session_state.title = ""
            st.session_state.resolution = ""
            st.session_state.selected_label = "— Select a WO from today —"
    with c3:
        if st.button("Refresh list"):
            st.session_state.refresh_toggle = not st.session_state.refresh_toggle

# ---------- Today ----------
with tab_today:
    st.subheader(f"Today’s WOs — {today}")
    if df_today.empty:
        st.write("No entries for today yet.")
    else:
        st.dataframe(df_today.fillna(""), use_container_width=True)

# ---------- Search ----------
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

# ---------- Export ----------
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
