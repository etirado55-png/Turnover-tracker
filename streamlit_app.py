# =========================================
# Turnover Notes — Streamlit single-file app
# =========================================

# --- Imports ---
import os
import time, random, string
import datetime as dt
import hmac, hashlib, base64, json
import pandas as pd
import streamlit as st
from gspread.exceptions import WorksheetNotFound, APIError
from gsheets_drive import get_gc, open_spreadsheet  # uses TURNOVER_SPREADSHEET_ID in secrets

# --- Page setup ---
st.set_page_config(page_title="Turnover Notes", page_icon="🗒️", layout="wide")

# --- One place to set the sheet tab name ---
TAB_NAME = "Entries"   # keep using the "Entries" tab

# Useful to sanity-check config up front (not strictly required)
SPREADSHEET_ID = st.secrets.get("TURNOVER_SPREADSHEET_ID") or os.getenv("TURNOVER_SPREADSHEET_ID")

# ===================== Auth (with “Keep me signed in”) =====================
APP_PASSWORD = st.secrets.get("APP_PASSWORD") or os.getenv("APP_PASSWORD")

def _setup_block():
    st.error("Authentication is not configured yet.")
    st.markdown("Add a password in `.streamlit/secrets.toml` or set APP_PASSWORD env var, then restart.")
    st.stop()

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def _unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def _sign(s: str) -> str:
    key = (APP_PASSWORD or "").encode()
    return _b64url(hmac.new(key, s.encode(), hashlib.sha256).digest())

def _make_remember_token(days: int = 14) -> str:
    payload = {"exp": int(time.time()) + days * 86400}
    body = _b64url(json.dumps(payload).encode())
    sig = _sign(body)
    return f"{body}.{sig}"

def _validate_token(token: str) -> bool:
    try:
        body, sig = token.split(".", 1)
        if _sign(body) != sig:
            return False
        data = json.loads(_unb64url(body))
        return int(time.time()) < int(data.get("exp", 0))
    except Exception:
        return False

def auth_gate():
    if not APP_PASSWORD:
        _setup_block()

    # already authenticated this run?
    if st.session_state.get("auth_ok"):
        return

    # Check remember-me token from URL (?tk=...)
    params = st.experimental_get_query_params()
    tk = params.get("tk", [""])[0]
    if tk and _validate_token(tk):
        st.session_state.auth_ok = True
        return

    # Show login UI
    st.markdown("### Login")
    pw = st.text_input("Password", type="password")
    stay = st.checkbox("Keep me signed in on this device")
    if st.button("Enter", type="primary", key="login_enter_btn"):
        if pw == APP_PASSWORD:
            st.session_state.auth_ok = True
            if stay:
                token = _make_remember_token(days=14)
                st.experimental_set_query_params(tk=token)  # persist over hard refresh
            try:
                st.rerun()
            except Exception:
                st.stop()
        else:
            st.error("Invalid password")
            st.stop()
    else:
        st.stop()

def logout():
    st.session_state.clear()
    st.experimental_set_query_params()  # clear token from URL
    try:
        st.rerun()
    except Exception:
        st.stop()

auth_gate()
st.sidebar.button("Logout", on_click=logout, key="logout_btn")

# ===================== Domain Constants =====================
LOCATIONS = [
    "JOW General","JOW Sc 1","JOW Sc 2","JOW Sc 3","JOW Sc 4","JOW Sc 5","JOW Sc 6","JOW Sc 7","JOW Sc 8",            #added more Locations 9/17/2025
    "World Celebration Gardens","Creations","Connections","CommuniCore Hall","Benchwork"
]
STATUSES = ["WIP", "Completed", "RTS", "WMATL"]

STATUS_COLOR = {           #changed WIP to color Red 9/17/2025
    "WIP": "#FF0000",
    "Completed": "#59c36a",
    "RTS": "#59c36a",
    "WMATL": "#5aa7ff"
}

# The columns your sheet must have in row 1 (and what the app expects everywhere)
EXPECTED_HEADERS = [
    "WO", "Title", "Resolution", "Date", "Location",
    "Status", "Attachments", "EntryID", "CreatedAt"
]

# ===================== Helpers =====================
def gen_entry_id() -> str:
    ts = int(time.time() * 1000)
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"E{ts}{rnd}"

def ensure_headers(ws):
    """Ensure header row exists and matches EXPECTED_HEADERS."""
    first_row = ws.row_values(1)
    if not first_row or [c.strip() for c in first_row] != EXPECTED_HEADERS:
        ws.update("A1", [EXPECTED_HEADERS])
        try:
            ws.freeze(rows=1)
        except Exception:
            pass

def _open_entries_ws():
    """Open/create the worksheet defined by TAB_NAME and ensure headers."""
    gc = get_gc()
    sh = open_spreadsheet(gc=gc)  # relies on TURNOVER_SPREADSHEET_ID in secrets/env
    try:
        ws = sh.worksheet(TAB_NAME)
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=TAB_NAME, rows=1000, cols=20)
    ensure_headers(ws)
    return ws

def read_all(ws):
    """Read all rows safely, even on an empty/new sheet."""
    try:
        return ws.get_all_records(default_blank="")
    except Exception:
        return []

def append_entry(row: dict) -> None:
    """Append a dict entry in the correct column order to the sheet."""
    ws = _open_entries_ws()
    ordered = [
        row.get("WO",""),
        row.get("Title",""),
        row.get("Resolution",""),
        row.get("Date",""),
        row.get("Location",""),
        row.get("Status",""),
        row.get("Attachments",""),
        row.get("EntryID",""),
        row.get("CreatedAt",""),
    ]
    ws.append_row(ordered, value_input_option="USER_ENTERED")

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize aliases and guarantee required columns exist."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    alias = {
        "WO #": "WO", "WO#": "WO", "Work Order": "WO",
        "Tittle": "Title",
        "Loc": "Location", "Area": "Location", "Place": "Location",
        "Entry ID": "EntryID", "Created At": "CreatedAt",
    }
    df.rename(columns=alias, inplace=True)

    for col in EXPECTED_HEADERS:
        if col not in df.columns:
            df[col] = ""
    return df

def load_df() -> pd.DataFrame:
    """Read the sheet into a DataFrame with the expected schema."""
    ws = _open_entries_ws()
    rows = read_all(ws)  # list[dict]
    df = pd.DataFrame(rows)
    df = normalize_columns(df)
    if not df.empty:
        df["Date"] = df["Date"].astype(str)
        df["CreatedAt"] = df["CreatedAt"].astype(str)
    return df

def latest_status_by_wo(df: pd.DataFrame) -> pd.DataFrame:
    """Return most recent row per WO using CreatedAt timestamp."""
    if df.empty:
        return df
    tmp = df.copy()
    tmp["CreatedAt_ts"] = pd.to_datetime(tmp["CreatedAt"], errors="coerce")
    tmp = tmp.sort_values("CreatedAt_ts").groupby("WO", as_index=False).tail(1)
    return tmp

def colored_status(s: str) -> str:
    color = STATUS_COLOR.get(s, "#ccc")
    return (
        f"<span style='background:{color}; color:#0f172a; padding:2px 8px; "
        f"border-radius:999px; font-size:12px; font-weight:600;'>{s}</span>"
    )

def wo_line(wo: str, title: str, res: str) -> str:
    return f"• WO{wo} — {title} | {res}"

def unicode_bold(s: str) -> str:
    """Return a 'plain text' string using Unicode mathematical bold letters/digits."""
    out = []
    for ch in s:
        if "A" <= ch <= "Z":
            out.append(chr(ord(ch) - ord("A") + 0x1D400))  # 𝐀..𝐙
        elif "a" <= ch <= "z":
            out.append(chr(ord(ch) - ord("a") + 0x1D41A))  # 𝐚..𝐳
        elif "0" <= ch <= "9":
            out.append(chr(ord(ch) - ord("0") + 0x1D7CE))  # 𝟎..𝟗
        else:
            out.append(ch)
    return "".join(out)


def safe_col(df: pd.DataFrame, name: str) -> pd.Series:
    """Return a safe column (or empty) so filters never KeyError."""
    return df[name] if name in df.columns else pd.Series([""] * len(df), index=df.index)

def apply_filters(df0,
                  query_text: str,
                  start_date: dt.date | None,
                  end_date: dt.date | None,
                  loc_filter: list[str],
                  status_filter: list[str]) -> pd.DataFrame:
    out = df0.copy()
    q = (query_text or "").strip().lower()
    if q:
        mask = (
            safe_col(out, "WO").astype(str).str.lower().str.contains(q, na=False) |
            safe_col(out, "Title").astype(str).str.lower().str.contains(q, na=False) |
            safe_col(out, "Resolution").astype(str).str.lower().str.contains(q, na=False) |
            safe_col(out, "Location").astype(str).str.lower().str.contains(q, na=False)
        )
        out = out[mask]
    if isinstance(start_date, dt.date):
        out = out[safe_col(out, "Date") >= start_date.strftime("%Y-%m-%d")]
    if isinstance(end_date, dt.date):
        out = out[safe_col(out, "Date") <= end_date.strftime("%Y-%m-%d")]
    if loc_filter:
        out = out[safe_col(out, "Location").isin(loc_filter)]
    if status_filter:
        out = out[safe_col(out, "Status").isin(status_filter)]
    return out

def load_df(sheet_name: str):                       #added 9/17/2025
    gc = get_gc()
    sh = open_spreadsheet(sheet_name)
    try:
        ws = sh.worksheet(sheet_name)
    except WorksheetNotFound:]
        header_map = {
            "WorkOrders": ["EntryID","WO","Title","Resolution","Status","Priority","Location","Scene","CreatedAt","UpdatedAt","AttachURL"],
            "RFM":       ["EntryID","RFM","Title","Description","Status","Priority","Location","Scene","RequestedBy","CreatedAt","UpdatedAt","AttachURL"],
        }
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=len(headers_map[sheet_name]))
        ws.append_row(headers_map[sheet_name])
    return pd.DataFrame(sh.worksheet(sheet_name).get_all_records())
        

# === QUICK EDIT HELPERS ===
def _open_entries_ws_and_values():
    """Return worksheet and all values (including header)."""
    ws = _open_entries_ws()
    vals = ws.get_all_values()
    return ws, vals

def _latest_rownum_for_wo(wo: str):
    """
    Find the most recent row number (1-based) for a WO using CreatedAt column.
    Returns (row_number, row_dict). row_number includes header, so >=2 if found.
    """
    ws, vals = _open_entries_ws_and_values()
    if not vals or len(vals) < 2:
        return None, {}

    headers = vals[0]
    idx = {h: i for i, h in enumerate(headers)}
    if "WO" not in idx:
        return None, {}

    i_wo = idx["WO"]
    i_created = idx.get("CreatedAt", None)

    latest_row = None
    latest_ts = ""
    latest_dict = {}

    for rnum in range(2, len(vals) + 1):
        row = vals[rnum - 1]
        if len(row) <= i_wo:
            continue
        if row[i_wo].strip() != str(wo).strip():
            continue
        created = row[i_created] if (i_created is not None and len(row) > i_created) else ""
        if created >= latest_ts:
            latest_ts = created
            latest_row = rnum
            latest_dict = {h: (row[idx[h]] if idx[h] < len(row) else "") for h in headers}

    return latest_row, latest_dict

def _update_row_values(ws, rownum: int, new_dict: dict) -> None:
    """Overwrite the given row (A:I) with ordered values per our schema."""
    ordered = [
        new_dict.get("WO",""),
        new_dict.get("Title",""),
        new_dict.get("Resolution",""),
        new_dict.get("Date",""),
        new_dict.get("Location",""),
        new_dict.get("Status",""),
        new_dict.get("Attachments",""),
        new_dict.get("EntryID",""),
        new_dict.get("CreatedAt",""),
    ]
    ws.update(f"A{rownum}:I{rownum}", [ordered], value_input_option="USER_ENTERED")

# ---------- Callbacks ----------
def reset_addwo():
    ss = st.session_state
    ss.wo_number = ""
    ss.wo_title = ""
    ss.wo_resolution = ""
    ss.wo_attachments = ""
    ss.wo_status = "WIP"
    ss.wo_location = LOCATIONS[0]
    ss.wo_date = dt.date.today()

def handle_submit():
    ss = st.session_state
    # Validation
    if not str(ss.wo_number).strip() or not str(ss.wo_title).strip():
        ss.flash = ("warning", "WO Number and Title are required.")
        return
    if ss.wo_status in {"Completed", "RTS"} and not str(ss.wo_resolution).strip():
        ss.flash = ("warning", "Resolution is required when Status is Completed or RTS.")
        return
    # Build and save
    row = {
        "WO": str(ss.wo_number).strip(),
        "Title": str(ss.wo_title).strip(),
        "Resolution": str(ss.wo_resolution).strip(),
        "Date": ss.wo_date.strftime("%Y-%m-%d"),
        "Location": ss.wo_location,
        "Status": ss.wo_status,
        "Attachments": str(ss.wo_attachments).strip(),
        "EntryID": gen_entry_id(),
        "CreatedAt": dt.datetime.now().isoformat(timespec="seconds"),
    }
    try:
        append_entry(row)
        ss.flash = ("success", f"{row['Date']} | [{row['Status']}] WO {row['WO']} - {row['Title']} added!")
        ss.toast_msg = "Entry saved to Google Sheets ✅"
        reset_addwo()
    except Exception as e:
        ss.flash = ("error", f"Write failed: {e}")

# ===================== UI =====================
st.title("Turnover Notes")

# Step 2: toggle right under the title added 9/17/2025
is_rfm = st.toggle("RFM mode", value=False, help="Switch between Work Orders and Requests For Maintenance")
sheet = "RFM" if is_rfm else "WorkOrders"

# --- Left panel: Add WO Entry (sidebar) ---
with st.sidebar:
    st.header("Add New" + ("RFM" if is_rfm else "Work Order"))

    STATUS_OPTIONS = (STATUSES if not is_rfm else STATUSES + ["Submitted"])          # ["WIP","Completed","RTS","WMATL"]
    LOCATION_OPTIONS = LOCATIONS

    # Defaults (set once per run before widgets)
    st.session_state.setdefault("wo_date", dt.date.today())
    st.session_state.setdefault("wo_number", "")
    st.session_state.setdefault("wo_title", "")
    st.session_state.setdefault("wo_resolution", "")
    st.session_state.setdefault("wo_status", "WIP")
    st.session_state.setdefault("wo_location", LOCATION_OPTIONS[0])
    st.session_state.setdefault("wo_attachments", "")

    # Show any flash messages from callbacks
    if "flash" in st.session_state:
        level, msg = st.session_state.pop("flash")
        getattr(st, level)(msg)
        if level == "success" and st.session_state.get("toast_msg"):
            st.toast(st.session_state.pop("toast_msg"), icon="💾")

    # Widgets: rely on keys only (no `value=` args)    added 9/17/2025
    st.date_input("Date", key="wo_date")
    st.text_input("RFM Number" if is_rfm else "Work Order Number", key="wo_number")
    st.text_input("Title", key="wo_title")
    st.selectbox("Status", STATUS_OPTIONS, key="wo_status")
    st.selectbox("Location", LOCATION_OPTIONS, key="wo_location")
    st.text_area("Description" if is_rfm else "Resolution", key="wo_resolution",
                 help=("Optional while Submitted/WIP" if is_rfm else
                       "Optional for WIP/WMATL. Required for Completed/RTS."))
    st.text_input("Attachments (URLs, comma-separated; optional)", key="wo_attachments")

    col1, col2 = st.columns(2)
    with col1:
        # Submit via callback (safe to mutate widget state)
        st.button("Submit", key="sidebar_addwo_submit_cb",
                  on_click=handle_submit,
                  kwargs={"sheet": sheet, "is_rfm": is_rfm})
    with col2:
        # Clear via callback
        st.button("Clear", key="sidebar_addwo_clear_cb",
                  on_click=reset_addwo,
                  kwargs={"is_rfm": is_rfm})
        
# --- Quick Edit Last Entry (by WO) ---
st.sidebar.divider()
st.sidebar.subheader("Edit Last Entry (by " + ("RFM" if is_rfm else "WO") + ")")

# Initialize session keys for persistent edit flow
for k, v in {
    "edit_loaded": False,
    "edit_rownum": None,
    "edit_rowdata": {},
    "edit_wo_selected": "",
}.items():
    st.session_state.setdefault(k, v)

# Load form (enter a WO and load latest)  added 9/17/2025
with st.sidebar.form("edit_wo_form"):
    edit_label = "RFM # to edit" if is_rfm else "WO # to edit"
    edit_wo = st.text_input(edit_label, placeholder="e.g., RFM-20250001" if is_rfm else "e.g., 146720560").strip()
    load_btn = st.form_submit_button("Load Last Entry", use_container_width=True)

if load_btn and edit_wo:
    key_col = "RFM" if is_rfm else "WO"
    rownum, rowdata = _latest_rownum_for_id(sheet, key_col, edit_wo)  # your finder should accept sheet+key
    if not rownum:
        st.sidebar.error(f"{key_col}{edit_wo} not found.")
    else:
        st.session_state.edit_loaded = True
        st.session_state.edit_rownum = rownum
        st.session_state.edit_rowdata = rowdata
        st.session_state.edit_wo_selected = edit_wo
        st.sidebar.success(f"Loaded last entry for {key_col}{edit_wo} (row {rownum})")

# If loaded, show edit fields
if st.session_state.edit_loaded and st.session_state.edit_rownum:
    rowdata = st.session_state.edit_rowdata
    edit_wo = st.session_state.edit_wo_selected
    rownum  = st.session_state.edit_rownum

    cur_date = rowdata.get("Date", "") or dt.date.today().strftime("%Y-%m-%d")
    try:
        cur_date_val = dt.datetime.strptime(cur_date, "%Y-%m-%d").date()
    except Exception:
        cur_date_val = dt.date.today()

    with st.sidebar.form("edit_wo_fields", clear_on_submit=False):
        new_title = st.text_area("Title", value=rowdata.get("Title",""), height=90, key=f"edit_title_{rownum}")
        new_res   = st.text_area("Resolution", value=rowdata.get("Resolution",""), height=180, key=f"edit_res_{rownum}")
        new_date  = st.date_input("Date", value=cur_date_val, key=f"edit_date_{rownum}")

        # Location/Status with safe defaults
        loc_idx  = LOCATIONS.index(rowdata.get("Location","")) if rowdata.get("Location","") in LOCATIONS else 0
        stat_idx = STATUSES.index(rowdata.get("Status","")) if rowdata.get("Status","") in STATUSES else 0
        new_loc  = st.selectbox("Location", LOCATIONS, index=loc_idx, key=f"edit_loc_{rownum}")
        new_stat = st.selectbox("Status", STATUSES, index=stat_idx, key=f"edit_stat_{rownum}")

        new_att  = st.text_input("Attachments (URLs, optional)", value=rowdata.get("Attachments",""), key=f"edit_att_{rownum}")

        col_a, col_b = st.columns(2)
        with col_a:
            confirm = st.form_submit_button("Save Changes", use_container_width=True)
        with col_b:
            cancel  = st.form_submit_button("Cancel", use_container_width=True)

    # Handle Cancel
    if cancel:
        st.session_state.edit_loaded = False
        st.session_state.edit_rownum = None
        st.session_state.edit_rowdata = {}
        st.session_state.edit_wo_selected = ""
        st.sidebar.info("Edit canceled.")

    # Handle Save (with conditional resolution requirement)
    if confirm:
        try:
            if new_stat in {"Completed", "RTS"} and not (new_res or "").strip():
                st.sidebar.warning("Resolution is required when Status is Completed or RTS.")
            else:
                ws = _open_entries_ws()
                new_dict = {
                    "WO": edit_wo,
                    "Title": (new_title or "").strip(),
                    "Resolution": (new_res or "").strip(),
                    "Date": new_date.strftime("%Y-%m-%d"),
                    "Location": new_loc,
                    "Status": new_stat,
                    "Attachments": (new_att or "").strip(),
                    "EntryID": rowdata.get("EntryID","") or gen_entry_id(),
                    "CreatedAt": dt.datetime.now().isoformat(timespec="seconds"),
                }
                _update_row_values(ws, rownum, new_dict)
                st.sidebar.success(f"Updated WO{edit_wo} (row {rownum}) ✅")
                st.toast("Entry updated", icon="✏️")

                # Clear selection and refresh UI/data
                st.session_state.edit_loaded = False
                st.session_state.edit_rownum = None
                st.session_state.edit_rowdata = {}
                st.session_state.edit_wo_selected = ""
                st.rerun()
        except Exception as e:
            st.sidebar.error(f"Update failed: {e}")

# --- Data load for main panels ---
# Make Sheets errors non-fatal and helpful
def _explain_api_error(e: APIError) -> str:
    try:
        # gspread keeps raw JSON in e.response.text
        import json as _json
        payload = _json.loads(e.response.text)
        code = payload.get("error", {}).get("code")
        msg = payload.get("error", {}).get("message")
        return f"{code}: {msg}"
    except Exception:
        return str(e)

df = pd.DataFrame(columns=EXPECTED_HEADERS)
try:
    if not SPREADSHEET_ID:
        raise RuntimeError("TURNOVER_SPREADSHEET_ID is not set in secrets or environment.")
    df = load_df(sheet)
    st.dataframe(df, use_container_width=True)
except APIError as e:
    detail = _explain_api_error(e)
    st.error("Google Sheets API error while opening the spreadsheet.")
    st.code(detail)
    st.info(
        "Fix checklist:\n"
        "1) In Streamlit **secrets**, set `TURNOVER_SPREADSHEET_ID` to the ID from your sheet URL (between `/d/` and `/edit`).\n"
        "2) Share the Google Sheet with your **service account** email (Editor). The email is the `client_email` in your credentials JSON.\n"
        "3) Ensure the **Google Sheets API** (and Drive API if you create tabs) is enabled for the project."
    )
except Exception as e:
    st.error(f"Failed to load data: {e}")
    if not SPREADSHEET_ID:
        st.info("`TURNOVER_SPREADSHEET_ID` is missing. Add it to `.streamlit/secrets.toml`:\n\n"
                "[[secrets]]\nTURNOVER_SPREADSHEET_ID = \"your-google-sheet-id\"")

# --- Search + Copy Turnover (Today) ---
with st.container():
    c1, c2 = st.columns([3, 1])

    with c1:
        query = st.text_input(
            "Search (WO, Title, Resolution, Location)",
            placeholder="gpu, pathway, Tag 82, breaker 12...",
            key="search_query",
        )

    with c2:
        copy_clicked = st.button(
            "Copy Turnover (Today)",
            use_container_width=True,
            key="copy_today_btn",
        )

    if copy_clicked:
        today_str = dt.date.today().strftime("%Y-%m-%d")
        today_df = df[(df["Date"] == today_str) & (~df["Status"].isin(["WMATL"]))].copy()
        
        # Pretty (Markdown) preview — bold WO + Title
        pretty_lines = [
            f"- **WO{r['WO']} — {r['Title']}** | {r['Resolution']}"
            for _, r in today_df.iterrows()
        ]
        pretty_txt = "\n".join(pretty_lines) if pretty_lines else "(No entries today)"
        st.markdown(pretty_txt)
        
        # Plain text with Unicode-bold WO + Title
        plain_bold_lines = [
            f"- {unicode_bold(f'WO{r['WO']} — {r['Title']}')} | {r['Resolution']}"
            for _, r in today_df.iterrows()
        ]
        plain_bold_txt = "\n".join(plain_bold_lines) if plain_bold_lines else "(No entries today)"
        st.text_area("Copy from here (plain text w/ bold characters)", plain_bold_txt,
                 height=180, key="copy_today_plain_bold")
    

# --- Filters ---
with st.expander("Filters", expanded=False):
    fc0, fc1, fc2, fc3 = st.columns([1,1,1,1])
    with fc0:
        use_dates = st.checkbox("Filter by date range", key="use_date_range")
    with fc1:
        start = st.date_input("Start date", value=dt.date.today(), key="filter_start") if use_dates else None
    with fc2:
        end = st.date_input("End date", value=dt.date.today(), key="filter_end") if use_dates else None
    with fc3:
        loc_mult = st.multiselect("Location filter", LOCATIONS, key="filter_locs")
    status_mult = st.multiselect("Status filter", STATUSES, key="filter_status")

# --- Global Search Results (across all dates/status) ---
st.subheader("Search Results")
matches = apply_filters(df.copy(), query, start, end, loc_mult, status_mult)
if (query or "").strip() or use_dates or loc_mult or status_mult:
    if matches.empty:
        st.caption("No matches.")
    else:
        if "CreatedAt" in matches.columns:
            matches = matches.sort_values("CreatedAt")
        for _, r in matches.iterrows():
            pill = colored_status(str(r["Status"]))
            st.markdown(
                f"{wo_line(str(r['WO']), str(r['Title']), str(r['Resolution']))} "
                f"&nbsp; <span style='opacity:.7;'>[{r.get('Location','')}]</span> &nbsp; {pill} "
                f"&nbsp; <span style='opacity:.5;'>{r.get('Date','')}</span>",
                unsafe_allow_html=True
            )
else:
    st.caption("Use the search or filters to find entries.")

# --- Right-side panels ---
left, right = st.columns([1.2, 2])

# Today’s WOs (exclude WMATL)
with left:
    st.subheader("Today’s WOs")
    today_str = dt.date.today().strftime("%Y-%m-%d")
    todays = df[(df["Date"] == today_str) & (~df["Status"].isin(["WMATL"]))].copy()
    todays = apply_filters(todays, query, start, end, loc_mult, status_mult)
    if todays.empty:
        st.caption("No entries today.")
    else:
        if "CreatedAt" in todays.columns:
            todays = todays.sort_values("CreatedAt")
        for _, r in todays.iterrows():
            pill = colored_status(str(r["Status"]))
            st.markdown(
                f"{wo_line(str(r['WO']), str(r['Title']), str(r['Resolution']))} "
                f"&nbsp; <span style='opacity:.7;'>[{r['Location']}]</span> &nbsp; {pill}",
                unsafe_allow_html=True
            )

# Open WOs (includes WMATL). Show latest entry per WO.
with right:
    st.subheader("Open WOs")
    latest = latest_status_by_wo(df)
    open_wo = latest[~latest["Status"].isin(["Completed","RTS","WMATL"])].copy()
    open_wo = apply_filters(open_wo, query, start, end, loc_mult, status_mult)
    if open_wo.empty:
        st.caption("No open WOs 🎉")
    else:
        if "CreatedAt" in open_wo.columns:
            open_wo = open_wo.sort_values("CreatedAt")
        for _, r in open_wo.iterrows():
            pill = colored_status(str(r["Status"]))
            with st.expander(f"WO{r['WO']} — {r['Title']}  [{r['Location']}]  ", expanded=False):
                st.markdown(pill, unsafe_allow_html=True)
                st.write(r["Resolution"])

                # attachments (if any)
                if str(r.get("Attachments","")).strip():
                    links = [x.strip() for x in str(r["Attachments"]).split(',') if x.strip()]
                    st.caption("Attachments:")
                    for i, url in enumerate(links, 1):
                        st.markdown(f"- [File {i}]({url})")

                # full thread for this WO
                thread = df[df["WO"] == r["WO"]].copy()
                if "CreatedAt" in thread.columns:
                    thread = thread.sort_values("CreatedAt")
                with st.expander("History", expanded=False):
                    for _, rr in thread.iterrows():
                        p = colored_status(str(rr["Status"]))
                        st.markdown(
                            f"- **{rr['Date']}** — {rr['Title']} | {rr['Resolution']} &nbsp; {p}",
                            unsafe_allow_html=True
                        )

# WMATL box (compact, readable on dark theme)
st.subheader("WMATL")
wmatl_latest = latest_status_by_wo(df)
wmatl = wmatl_latest[wmatl_latest["Status"] == "WMATL"].copy()
wmatl = apply_filters(wmatl, query, start, end, loc_mult, status_mult)
if wmatl.empty:
    st.caption("No WOs waiting on material.")
else:
    st.markdown(
        """
        <style>
        .wmatl-tag {
            background: #eaf2ff;
            color: #0f172a;
            padding: 4px 10px;
            margin: 4px;
            display: inline-block;
            border-radius: 10px;
            border: 1px solid rgba(2,6,23,.12);
            font-weight: 600;
            font-size: 0.9rem;
            line-height: 1.2;
            white-space: nowrap;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    tags = []
    if "CreatedAt" in wmatl.columns:
        wmatl = wmatl.sort_values("CreatedAt")
    for _, r in wmatl.iterrows():
        tags.append(f"<span class='wmatl-tag'>WO{r['WO']} — {r['Title']}</span>")
    st.markdown(" ".join(tags), unsafe_allow_html=True)

# --- Diagnostics (optional but handy) ---
with st.expander("Sheet Diagnostics", expanded=False):
    try:
        gc = get_gc()
        sh = open_spreadsheet(gc=gc)
        st.write("**Spreadsheet title:**", sh.title)
        try:
            st.write("**Spreadsheet URL:**", sh.url)
        except Exception:
            pass
        tabs = [ws.title for ws in sh.worksheets()]
        st.write("**Tabs found:**", tabs)

        colA, colB = st.columns(2)
        with colA:
            if st.button("Create/Repair tab & headers", key="diag_repair_headers_btn"):
                ws = _open_entries_ws()
                ensure_headers(ws)
                st.success(f"'{TAB_NAME}' tab ready with headers.")
        with colB:
            if st.button("Run write test", key="diag_write_test_btn"):
                test = {
                    "WO": "TEST-000",
                    "Title": "Diagnostics write test",
                    "Resolution": "If you see this row in Sheets, writes work.",
                    "Date": dt.date.today().strftime("%Y-%m-%d"),
                    "Location": LOCATIONS[0],
                    "Status": "WIP",
                    "Attachments": "",
                    "EntryID": gen_entry_id(),
                    "CreatedAt": dt.datetime.now().isoformat(timespec="seconds"),
                }
                append_entry(test)
                st.success("Wrote test row. Check the sheet.")
    except APIError as e:
        st.error("Diagnostics: Google Sheets API error.")
        st.code(_explain_api_error(e))
        st.info("Make sure the service account has Editor access and the spreadsheet ID is correct.")
    except Exception as e:
        st.error(f"Diagnostics error: {e}")
        st.info("Common causes:\n"
                "- Service account doesn’t have **edit** access to this spreadsheet.\n"
                "- Wrong spreadsheet ID/URL in your secrets.\n"
                "- Network/credentials issue.")

# CSV backup
st.divider()
csv_bytes = df.to_csv(index=False).encode("utf-8")
st.download_button("Download CSV (backup)", csv_bytes,
                   file_name="turnover_log.csv", mime="text/csv",
                   use_container_width=True, key="download_csv_btn")
