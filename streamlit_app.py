import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import pytz
import gspread
from google.oauth2.service_account import Credentials

from bootstrap import get_sheet_url, check_config

# ================== Settings ==================
SHEET_NAME = "turnover_log"        # or "Sheet1" if that's your tab name
CUTOFF_HOUR = 6                    # Night-shift cutoff (6 AM)
TZ = pytz.timezone("America/New_York")

# ================== Auth (uses Streamlit secrets) ==================
creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
)
client = gspread.authorize(creds)

# Run a silent health check (shows a red banner only if broken)
sheet_url = check_config(client, sheet_name=SHEET_NAME)
sheet = client.open_by_url(sheet_url).worksheet(SHEET_NAME)

# ================== Helpers ==================
def shift_today():
    now = datetime.now(TZ)
    if now.hour < CUTOFF_HOUR:
        return (now - timedelta(days=1)).date().isoformat()
    return now.date().isoformat()

def ensure_header():
    values = sheet.get_all_values()
    if not values:
        sheet.append_row(["Date", "WO Number", "Title", "Resolution"])

def load_df():
    ensure_header()
    data = sheet.get_all_records()
    return pd.DataFrame(data, columns=["Date", "WO Number", "Title", "Resolution"])

def save_row(date_str, wo, title, resolution):
    """
    Add a new row for today's date OR update the existing row with the same WO.
    - Title only overwritten if provided (non-empty).
    - Resolution can be blank (we don't invent text).
    """
    df = load_df()
    mask = (df["Date"] == date_str) & (df["WO Number"].astype(str) == str(wo))
    if mask.any():
        idx = df[mask].index[0]  # 0-based
        row_num = idx + 2        # +1 header row, +1 for 1-based indexing
        if str(title).strip():
            sheet.update_cell(row_num, 3, title)
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

today = shift_today()
df = load_df()
df_today = numeric_sort_wo(df[df["Date"] == today])

tab_input, tab_today, tab_search, tab_export = st.tabs(
    ["➕ Add/Update", "📅 Today", "🔎 Search", "📤 Export"]
)

# ---------- Add/Update (with dropdown of today's WOs) ----------
with tab_input:
    st.subheader(f"Add or Update (Shift date: **{today}**, cutoff {CUTOFF_HOUR:02d}:00 {TZ.zone})")

    left, right = st.columns([1, 2])

    with left:
        options = ["— Select a WO from today —"] + [
            f"WO{row['WO Number']} — {row['Title']}" for _, row in df_today.iterrows()
        ]
        sel = st.selectbox("Pick today’s WO (optional) to auto-fill:", options, index=0, key="selected_label")

        def parse_selected(s):
            if s.startswith("WO") and " — " in s:
                wo_part, title_part = s.split(" — ", 1)
                return wo_part.replace("WO", "").strip(), title_part
            return "", ""

        if sel != "— Select a WO from today —":
            wo_prefill, title_prefill = parse_selected(sel)
            # fetch existing resolution (if any)
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
                # force-refresh the page state
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
        # Build text in your exact format:
        lines = [f"# {today}", "", "Daily PM completed, Rain curtain Filters cleaned.", ""]
        for _, r in df_today.iterrows():
            lines.append(f"- **WO{r['WO Number']} — {r['Title']}** | {r['Resolution']}")
        export_text = "\n".join(lines)

        st.code(export_text, language="markdown")
        st.download_button("Download as .txt", export_text, file_name=f"turnover_{today}.txt")
        st.caption("Tip: long-press/copy on your phone, or download and upload to OneDrive.")
