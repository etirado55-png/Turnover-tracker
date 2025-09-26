# =========================================
# Turnover Notes — Streamlit single-file app (rate-limit safe, fixed build)
# =========================================

# --- Imports ---   
import os
import time, random, string
import datetime as dt
import hmac, hashlib, base64, json
import pandas as pd
import html
import streamlit as st
import secrets, hashlib

# --- Simple user management helpers ---
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def ensure_user_sheet():
    sh = open_spreadsheet(gc=get_gc())
    try:
        return sh.worksheet("Users")
    except WorksheetNotFound:
        ws = sh.add_worksheet(title="Users", rows=100, cols=4)
        ws.update("A1:D1", [["Email","Role","Enabled","TokenHash"]])
        return ws

def load_users_df():
    wa = ensure_user_sheet()
    return pd.DataFrame(ws.get_all_records())

# auth_gate for Users Table
def auth_gate():
    ss = st.session_state
    params = st.querry_params #property not a function
    key = (params.get("key", [None])[0] or "").strip()

    users = load_users_df()

# If a ?key=... is present, validate it
if key:
    row = users[
        (users["TokenHash"] == _hash_token(key)) &
        (users["Enabled"].astype(str).str.lower().isin(["true","1","yes","y"]))
    ]
    if not row.empty:
        ss["user_email"] = row.iloc[0]["Email"]
        ss["user_role"] = str(row.iloc[0].get("Role","viewer")).lower()
        return

# Already authenticated in this session?
if ss.get("user_email"):
    return

# Block everything else
st.error("Access denied. Ask an admin for an access link.")
st.stop()
    
from gspread.exceptions import WorksheetNotFound, APIError
from html import escape  # put this near your imports (once)
st.info(
    """Disclaimer:
This document/system/information is intended for official use only. Unauthorized access, disclosure, or distribution is strictly prohibited. 
All use is subject to monitoring and review to ensure compliance with applicable policies and regulations."""
)
from gsheets_drive import get_gc, open_spreadsheet  # uses TURNOVER_SPREADSHEET_ID in secrets

# --- Page setup ---
st.set_page_config(page_title="Turnover Notes", page_icon="🗒️", layout="wide")
auth_gate() # << place early so Unauthorized users can`t see anything.

User_email = st.session_state.get("user_email","unknown")
user_role = st.session_state.get("user_role","viewer")
is_editor = user_role in ("editor","admin")

st.caption(f"sign in as:{user_email} . role: {user_role}")

# --- One place to set the sheet tab name ---
TAB_NAME = "Entries"   # keep using the "Entries" tab
RFM_TAB = "RFM"        # RFM tab

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
    "JOW General","JOW Sc 1","JOW Sc 2","JOW Sc 3","JOW Sc 4","JOW Sc 5","JOW Sc 6","JOW Sc 7","JOW Sc 8",
    "World Celebration Gardens","Creations","Connections","CommuniCore Hall","Benchwork"
]
STATUSES = ["APPR", "WIP", "Completed", "RTS", "WMATL"]

STATUS_COLOR = {           # changed WIP to color Red 9/17/2025
    "APPR": "#FFA500",
    "WIP": "#FF0000",
    "Completed": "#59c36a",
    "RTS": "#59c36a",
    "WMATL": "#5aa7ff"
}

# --- Add RFM colors + any custom free-text tags you want hard-colored ---
RFM_STATUS_COLOR = {
    "Draft": "#6b7280",
    "WAPPR": "#0ea5e9",
    "PO Created": "#a855f7",
    "Close": "#10b981",
}

# Entries (WO) headers
EXPECTED_HEADERS = [
    "WO", "Title", "Resolution", "Date", "Location",
    "Status", "Attachments", "EntryID", "CreatedAt"
]

# RFM headers (for tracker + writes)
RFM_HEADERS = [
    "RFM", "Title", "Description", "Date", "Location",
    "Status", "Attachments", "EntryID", "CreatedAt"
]

LEGACY_SEARCH_ENABLED = False


# ===================== Rate-limit helpers (NEW) =====================

def _with_backoff(fn, *args, **kwargs):
    """Run gspread calls with exponential backoff on quota errors."""
    delay = 1.0
    for _ in range(6):  # ~63s total worst case
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

# ===================== Worksheet open (cached) =====================

@st.cache_resource
def _open_entries_ws():
    """Open/create the Entries worksheet and ensure headers."""
    gc = get_gc()
    sh = open_spreadsheet(gc=gc)  # relies on TURNOVER_SPREADSHEET_ID in secrets/env
    try:
        ws = sh.worksheet(TAB_NAME)
    except WorksheetNotFound:
        ws = _with_backoff(sh.add_worksheet, title=TAB_NAME, rows=2000, cols=20)
    # Ensure headers
    first_row = _with_backoff(ws.row_values, 1)
    if not first_row or [c.strip() for c in first_row] != EXPECTED_HEADERS:
        _with_backoff(ws.update, "A1", [EXPECTED_HEADERS])
        try:
            _with_backoff(ws.freeze, rows=1)
        except Exception:
            pass
    return ws

@st.cache_resource
def _open_rfm_ws():
    """Open/create the RFM worksheet and ensure headers."""
    gc = get_gc()
    sh = open_spreadsheet(gc=gc)
    try:
        ws = sh.worksheet(RFM_TAB)
    except WorksheetNotFound:
        ws = _with_backoff(sh.add_worksheet, title=RFM_TAB, rows=2000, cols=20)
    first_row = _with_backoff(ws.row_values, 1)
    if not first_row or [c.strip() for c in first_row] != RFM_HEADERS:
        _with_backoff(ws.update, "A1", [RFM_HEADERS])
        try:
            _with_backoff(ws.freeze, rows=1)
        except Exception:
            pass
    return ws

# ===================== Reads (cached) =====================

@st.cache_data(ttl=60)
def _get_all_values(tab_name: str):
    """
    One big read per tab, cached for 60s.
    NOTE: Using a Worksheet object means the range must be relative (no sheet name),
    otherwise gspread prefixes it again (e.g., "'Entries'!Entries!A1").
    """
    ws = _open_entries_ws() if tab_name == TAB_NAME else _open_rfm_ws()
    rng = "A1:Z5000"               # relative to the worksheet
    data = _with_backoff(ws.get, rng)  # returns list[list]
    return data

@st.cache_data(ttl=60)
def load_df() -> pd.DataFrame:
    """Read the Entries sheet into a DataFrame with the expected schema."""
    values = _get_all_values(TAB_NAME)
    if not values:
        return pd.DataFrame(columns=EXPECTED_HEADERS)
    header, *rows = values
    # drop empty rows
    rows = [r for r in rows if any((str(c).strip() if c is not None else "") for c in r)]
    df = pd.DataFrame(rows, columns=header[: len(header)])
    df = normalize_columns(df)
    if not df.empty:
        df["Date"] = df["Date"].astype(str)
        df["CreatedAt"] = df["CreatedAt"].astype(str)
    return df

@st.cache_data(ttl=60)
def load_rfm_df() -> pd.DataFrame:
    """Read the RFM sheet into a DataFrame (ensures columns exist)."""
    values = _get_all_values(RFM_TAB)
    if not values:
        return pd.DataFrame(columns=RFM_HEADERS)
    header, *rows = values
    rows = [r for r in rows if any((str(c).strip() if c is not None else "") for c in r)]
    df = pd.DataFrame(rows, columns=header[: len(header)])
    for c in RFM_HEADERS:
        if c not in df.columns:
            df[c] = ""
    if not df.empty:
        df["Date"] = df["Date"].astype(str)
        df["CreatedAt"] = df["CreatedAt"].astype(str)
    return df

# ===================== Helpers =====================

def gen_entry_id() -> str:
    ts = int(time.time() * 1000)
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"E{ts}{rnd}"

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
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

def latest_status_by_wo(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    tmp = df.copy()
    tmp["CreatedAt_ts"] = pd.to_datetime(tmp["CreatedAt"], errors="coerce")
    tmp = tmp.sort_values("CreatedAt_ts").groupby("WO", as_index=False).tail(1)
    return tmp

def latest_status_by_rfm(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    tmp = df.copy()
    tmp["CreatedAt_ts"] = pd.to_datetime(tmp["CreatedAt"], errors="coerce")
    tmp = tmp.sort_values("CreatedAt_ts").groupby("RFM", as_index=False).tail(1)
    return tmp

def wo_line(wo: str, title: str, res: str) -> str:
    return f"• WO{wo} — {title} | {res}"

def unicode_bold(s: str) -> str:
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

def drop_rfm_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "WO" not in df.columns:
        return df
    return df[~df["WO"].astype(str).str.upper().str.startswith("RFM")]
    
# --- Normalization + unified color map + pill renderer ---
def _norm_key(s: str) -> str:
    s = (s or "").strip().replace("_", " ")
    s = " ".join(s.split())   # collapse repeated spaces
    return s.upper()

# Combine WO + RFM colors, normalized for robust lookup
_RAW_COLOR_MAP = {**STATUS_COLOR, **RFM_STATUS_COLOR}
COMBINED_COLOR_MAP = {_norm_key(k): v for k, v in _RAW_COLOR_MAP.items()}

def colored_status(text: str, bg: str | None = None, fg: str = "white"):
    """
    Return an HTML pill for a status or free text.
    If bg is None, pick from COMBINED_COLOR_MAP using normalized text.
    """
    text = (text or "").strip()
    if not text:
        return ""
    if bg is None:
        bg = COMBINED_COLOR_MAP.get(_norm_key(text), "#6b7280")  # neutral fallback
    return (
        f"<span style='display:inline-block;padding:.15rem .5rem;border-radius:9999px;"
        f"font-size:.75rem;font-weight:600;background:{bg};color:{fg};'>{text}</span>"
    )

def append_progress_note(wo: str, title: str, note: str, status: str, loc: str, date_val: dt.date | None = None):
    """Append a 'work performed' note for an existing WO without changing the schema."""
    if not wo.strip():
        raise ValueError("WO is required for a progress note.")
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    row = {
        "WO": wo.strip(),
        "Title": (title or "").strip(),         # keep the same title (or allow edits)
        "Resolution": (note or "").strip(),     # <= your 'work performed' text goes here
        "Date": (date_val or dt.date.today()).strftime("%Y-%m-%d"),
        "Location": (loc or LOCATIONS[0]),
        "Status": (status or "WIP"),            # you can leave status as-is or choose another
        "Attachments": "",
        "EntryID": gen_entry_id(),
        "CreatedAt": now_iso,
    }
    append_entry(row)


# === QUICK EDIT HELPERS (WOs) ===

def _latest_rownum_for_wo(wo: str):
    """
    Find the most recent row number (1-based) for a WO using CreatedAt column.
    Returns (row_number, row_dict). row_number includes header, so >=2 if found.
    Uses cached read for speed, only reads raw values once if needed.
    """
    values = _get_all_values(TAB_NAME)
    if not values or len(values) < 2:
        return None, {}
    headers = values[0]
    idx = {h: i for i, h in enumerate(headers)}
    if "WO" not in idx:
        return None, {}
    i_wo = idx["WO"]
    i_created = idx.get("CreatedAt", None)

    latest_row = None
    latest_ts = ""
    latest_dict = {}

    for rnum in range(2, len(values) + 1):
        row = values[rnum - 1]
        if len(row) <= i_wo:
            continue
        if (row[i_wo] or "").strip() != str(wo).strip():
            continue
        created = row[i_created] if (i_created is not None and len(row) > i_created) else ""
        if created >= latest_ts:
            latest_ts = created
            latest_row = rnum
            latest_dict = {h: (row[idx[h]] if idx[h] < len(row) else "") for h in headers}

    return latest_row, latest_dict

# ---------- Last-known getters ----------
def _last_for_wo(wo: str) -> dict:
    d = latest_status_by_wo(load_df())
    if d.empty:
        return {}
    m = d[d["WO"].astype(str).str.strip() == str(wo).strip()]
    return m.iloc[0].to_dict() if not m.empty else {}

def _last_for_rfm(rfm: str) -> dict:
    d = latest_status_by_rfm(load_rfm_df())
    if d.empty:
        return {}
    m = d[d["RFM"].astype(str).str.strip() == str(rfm).strip()]
    return m.iloc[0].to_dict() if not m.empty else {}

# ---------- Append note (WO) ----------
def append_progress_note(wo: str, title: str | None, note: str, status: str | None,
                         loc: str | None, date_val: dt.date | None = None):
    if not str(wo).strip():
        raise ValueError("WO is required.")
    last = _last_for_wo(wo)
    use_title = (title or last.get("Title") or "").strip()
    use_loc   = (loc   or last.get("Location") or LOCATIONS[0]).strip()
    use_stat  = (status or last.get("Status") or "WIP").strip()
    row = {
        "WO": str(wo).strip(),
        "Title": use_title,
        "Resolution": (note or "").strip(),
        "Date": (date_val or dt.date.today()).strftime("%Y-%m-%d"),
        "Location": use_loc,
        "Status": use_stat,
        "Attachments": "",
        "EntryID": gen_entry_id(),
        "CreatedAt": dt.datetime.now().isoformat(timespec="seconds"),
    }
    append_entry(row)

# ---------- Append note (RFM) ----------
def append_rfm_note(rfm: str, title: str | None, note: str, status: str | None,
                    loc: str | None, date_val: dt.date | None = None):
    if not str(rfm).strip():
        raise ValueError("RFM is required.")
    last = _last_for_rfm(rfm)
    use_title = (title or last.get("Title") or "").strip()
    use_loc   = (loc   or last.get("Location") or LOCATIONS[0]).strip()
    use_stat  = (status or last.get("Status") or "Submitted").strip()
    row = {
        "RFM": str(rfm).strip(),
        "Title": use_title,
        "Description": (note or "").strip(),
        "Date": (date_val or dt.date.today()).strftime("%Y-%m-%d"),
        "Location": use_loc,
        "Status": use_stat,
        "Attachments": "",
        "EntryID": gen_entry_id(),
        "CreatedAt": dt.datetime.now().isoformat(timespec="seconds"),
    }
    append_rfm_entry(row)


# === QUICK EDIT HELPERS (RFMs) — NEW ===

def _latest_rownum_for_rfm(rfm: str):
    """
    Find the most recent row number (1-based) for an RFM using CreatedAt.
    Returns (row_number, row_dict).
    """
    values = _get_all_values(RFM_TAB)
    if not values or len(values) < 2:
        return None, {}
    headers = values[0]
    idx = {h: i for i, h in enumerate(headers)}
    if "RFM" not in idx:
        return None, {}
    i_rfm = idx["RFM"]
    i_created = idx.get("CreatedAt", None)

    latest_row = None
    latest_ts = ""
    latest_dict = {}

    for rnum in range(2, len(values) + 1):
        row = values[rnum - 1]
        if len(row) <= i_rfm:
            continue
        if (row[i_rfm] or "").strip() != str(rfm).strip():
            continue
        created = row[i_created] if (i_created is not None and len(row) > i_created) else ""
        if created >= latest_ts:
            latest_ts = created
            latest_row = rnum
            latest_dict = {h: (row[idx[h]] if idx[h] < len(row) else "") for h in headers}

    return latest_row, latest_dict

def _update_row_values(ws, rownum: int, new_dict: dict) -> None:
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
    _with_backoff(ws.update, f"A{rownum}:I{rownum}", [ordered], value_input_option="USER_ENTERED")
    st.cache_data.clear()

# RFM updater — NEW
def _update_rfm_row_values(ws, rownum: int, new_dict: dict) -> None:
    ordered = [
        new_dict.get("RFM",""),
        new_dict.get("Title",""),
        new_dict.get("Description",""),
        new_dict.get("Date",""),
        new_dict.get("Location",""),
        new_dict.get("Status",""),
        new_dict.get("Attachments",""),
        new_dict.get("EntryID",""),
        new_dict.get("CreatedAt",""),
    ]
    _with_backoff(ws.update, f"A{rownum}:I{rownum}", [ordered], value_input_option="USER_ENTERED")
    st.cache_data.clear()

# ---------- Write helpers (with backoff + cache bust) ----------

def append_entry(row: dict) -> None:
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
    _with_backoff(ws.append_row, ordered, value_input_option="USER_ENTERED")
    st.cache_data.clear()

def append_rfm_entry(row: dict) -> None:
    ws = _open_rfm_ws()
    ordered = [
        row.get("RFM",""),
        row.get("Title",""),
        row.get("Description",""),
        row.get("Date",""),
        row.get("Location",""),
        row.get("Status",""),
        row.get("Attachments",""),
        row.get("EntryID",""),
        row.get("CreatedAt",""),
    ]
    _with_backoff(ws.append_row, ordered, value_input_option="USER_ENTERED")
    st.cache_data.clear()

# ---------- Add/Submit helpers (wired to UI) ----------

def reset_addwo():
    ss = st.session_state
    ss.wo_number = ""
    ss.wo_title = ""
    ss.wo_resolution = ""
    ss.wo_attachments = ""
    ss.wo_status = "APPR"
    ss.wo_location = LOCATIONS[0]
    ss.wo_date = dt.date.today()

def clear_addwo():
    st.session_state["wo_number"]     = ""
    st.session_state["wo_title"]      = ""
    st.session_state["wo_resolution"] = ""
    st.session_state["wo_attachments"]= ""
    st.session_state["wo_status"]     = "APPR"
    st.session_state["wo_location"]   = LOCATIONS[0]
    st.session_state["wo_date"]       = dt.date.today()
    st.rerun()

# Defaults + clear for Quick Progress Note
def _ensure_quick_defaults():
    st.session_state.setdefault("qp_kind", "WO")  # WO | RFM
    st.session_state.setdefault("qp_id", "")
    st.session_state.setdefault("qp_title", "")
    st.session_state.setdefault("qp_loc", LOCATIONS[0])
    st.session_state.setdefault("qp_keep_status", True)
    st.session_state.setdefault("qp_status", "WIP")  # used if keep_status=False for WO
    st.session_state.setdefault("qp_status_rfm", "Submitted")  # used if RFM + keep_status=False
    st.session_state.setdefault("qp_date", dt.date.today())
    st.session_state.setdefault("qp_note", "")

def _qp_on_id_change():
    kind = st.session_state.get("qp_kind", "WO")
    _id  = str(st.session_state.get("qp_id", "")).strip()
    if not _id:
        return
    data = _last_for_wo(_id) if kind == "WO" else _last_for_rfm(_id)
    if not data:
        # Clear title/location if ID not found
        st.session_state["qp_title"] = ""
        st.session_state["qp_loc"] = LOCATIONS[0]
        return
    # Auto-fill from last known entry
    st.session_state["qp_title"] = data.get("Title", "") or st.session_state.get("qp_title", "")
    st.session_state["qp_loc"]   = data.get("Location", LOCATIONS[0])
    # Seed the override pickers with last status (in case user unchecks "Keep")
    last_status = data.get("Status", "WIP")
    if kind == "WO":
        st.session_state["qp_status"] = last_status if last_status in STATUSES else "WIP"
    else:
        st.session_state["qp_status_rfm"] = last_status if last_status in ["Submitted","WAPPR","PO Created","Close"] else "Submitted"

def clear_quick_note():
    st.session_state["qp_kind"] = "WO"
    st.session_state["qp_id"] = ""
    st.session_state["qp_title"] = ""
    st.session_state["qp_loc"] = LOCATIONS[0]
    st.session_state["qp_keep_status"] = True
    st.session_state["qp_status"] = "WIP"
    st.session_state["qp_status_rfm"] = "Submitted"
    st.session_state["qp_date"] = dt.date.today()
    st.session_state["qp_note"] = ""
    st.rerun()


def handle_submit(is_rfm: bool = False):
    ss = st.session_state
    if not str(ss.wo_number).strip() or not str(ss.wo_title).strip():
        label = "RFM Number" if is_rfm else "WO Number"
        ss.flash = ("warning", f"{label} and Title are required.")
        return
    if (not is_rfm) and ss.wo_status in {"Completed", "RTS"} and not str(ss.wo_resolution).strip():
        ss.flash = ("warning", "Resolution is required when Status is Completed or RTS.")
        return

    now_iso = dt.datetime.now().isoformat(timespec="seconds")

    try:
        if is_rfm:
            row = {
                "RFM": str(ss.wo_number).strip(),
                "Title": str(ss.wo_title).strip(),
                "Description": str(ss.wo_resolution).strip(),
                "Date": ss.wo_date.strftime("%Y-%m-%d"),
                "Location": ss.wo_location,
                "Status": ss.wo_status,
                "Attachments": str(ss.wo_attachments).strip(),
                "EntryID": gen_entry_id(),
                "CreatedAt": now_iso,
            }
            append_rfm_entry(row)
            ss.flash = ("success", f"{row['Date']} | [{row['Status']}] RFM {row['RFM']} - {row['Title']} added!")
            ss.toast_msg = "RFM saved to Google Sheets ✅"
            reset_addwo()
        else:
            row = {
                "WO": str(ss.wo_number).strip(),
                "Title": str(ss.wo_title).strip(),
                "Resolution": str(ss.wo_resolution).strip(),
                "Date": ss.wo_date.strftime("%Y-%m-%d"),
                "Location": ss.wo_location,
                "Status": ss.wo_status,
                "Attachments": str(ss.wo_attachments).strip(),
                "EntryID": gen_entry_id(),
                "CreatedAt": now_iso,
            }
            append_entry(row)
            ss.flash = ("success", f"{row['Date']} | [{row['Status']}] WO {row['WO']} - {row['Title']} added!")
            ss.toast_msg = "Entry saved to Google Sheets ✅"
            reset_addwo()
    except Exception as e:
        ss.flash = ("error", f"Write failed: {e}")

# ===================== UI =====================

st.title("Turnover Notes")

# Toggle (label-only influence for now; edit panel remains WO)
is_rfm = st.toggle("RFM mode", value=False, help="Switch between Work Orders and Requests For Maintenance")
sheet = "RFM" if is_rfm else "WorkOrders"  # retained for future extension

# --- Left panel: Add WO/RFM Entry (sidebar) ---
with st.sidebar.expander("➕ Add New " + ("RFM" if is_rfm else "Work Order"), expanded=False):

    if is_editor:
        #render the input forms
    if "flash" in st.session_state:
        level, msg = st.session_state.pop("flash")
        getattr(st, level)(msg)
        if level == "success" and st.session_state.get("toast_msg"):
            st.toast(st.session_state.pop("toast_msg"), icon="💾")

    if is_rfm:
        st.caption("Material Att ROBLK004")   # only shows in RFM mode

    else:
        st.info("Read_only access. Ask an editor/aadmin if you need edit rights.")
        
    if user_role in ("admin",):  # only admins see this
        with st.sidebar.expander("Invite a user", expanded=False):
            if st.button("Generate invite link"):
                new_token = secrets.token_urlsafe(16)
                app_url = st.secrets.get("APP_URL", "https://https://ogyeyjt5zk4ycmhvwsy8xb.streamlit.app/")
                invite_url = f"{app_url}?key={new_token}"
                st.code(invite_url, language="text")
                st.write("TokenHash (paste into Users sheet):")
                st.code(_hash_token(new_token), language="text")
                st.caption("Set Email, Role (viewer/editor), Enabled=TRUE in the Users sheet.")

    

    STATUS_OPTIONS = (STATUSES if not is_rfm else ["Draft", "WAPPR", "PO Created", "Close"])
    LOCATION_OPTIONS = LOCATIONS

    st.session_state.setdefault("wo_date", dt.date.today())
    st.session_state.setdefault("wo_number", "")
    st.session_state.setdefault("wo_title", "")
    st.session_state.setdefault("wo_resolution", "")
    st.session_state.setdefault("wo_status", "APPR")
    st.session_state.setdefault("wo_location", LOCATION_OPTIONS[0])
    st.session_state.setdefault("wo_attachments", "")

    st.date_input("Date", key="wo_date")
    st.text_input("RFM Number" if is_rfm else "Work Order Number", key="wo_number")
    st.text_input("Title", key="wo_title")
    st.selectbox("Status", STATUS_OPTIONS, key="wo_status")
    st.selectbox("Location", LOCATION_OPTIONS, key="wo_location")
    st.text_area("Description" if is_rfm else "Resolution", key="wo_resolution",
                 help=("Optional while Submitted/WIP" if is_rfm else
                       "Use this for work-performed notes. Required for Completed/RTS."))
    st.text_input("Attachments (URLs, comma-separated; optional)", key="wo_attachments")

    col1, col2 = st.columns(2)
    with col1:
        st.button("Submit", key="sidebar_addwo_submit_cb",
                  on_click=lambda: handle_submit(is_rfm=is_rfm))
    with col2:
        st.button("Clear", key="sidebar_addwo_clear_cb", on_click=clear_addwo)



# ===================== Quick Edit Last Entry (by WO/RFM) — COLLAPSED =====================
with st.sidebar.expander("✏️ Edit Last Entry (" + ("RFM" if is_rfm else "WO") + ")", expanded=False):

    # Defaults
    for k, v in {
        "edit_loaded": False,
        "edit_rownum": None,
        "edit_rowdata": {},
        "edit_wo_selected": "",
    }.items():
        st.session_state.setdefault(k, v)

    with st.form("edit_wo_form"):
        edit_label = "RFM # to edit" if is_rfm else "WO # to edit"
        edit_wo = st.text_input(edit_label, placeholder="e.g., RFM-20250001" if is_rfm else "e.g., 146720560").strip()
        load_btn = st.form_submit_button("Load Last Entry", use_container_width=True)

    # Load last entry depending on mode
    if load_btn and edit_wo and not is_rfm:
        rownum, rowdata = _latest_rownum_for_wo(edit_wo)
        if not rownum:
            st.error(f"WO{edit_wo} not found.")
        else:
            st.session_state.edit_loaded = True
            st.session_state.edit_rownum = rownum
            st.session_state.edit_rowdata = rowdata
            st.session_state.edit_wo_selected = edit_wo
            st.success(f"Loaded last entry for WO{edit_wo} (row {rownum})")
    elif load_btn and edit_wo and is_rfm:
        rownum, rowdata = _latest_rownum_for_rfm(edit_wo)
        if not rownum:
            st.error(f"RFM{edit_wo} not found.")
        else:
            st.session_state.edit_loaded = True
            st.session_state.edit_rownum = rownum
            st.session_state.edit_rowdata = rowdata
            st.session_state.edit_wo_selected = edit_wo
            st.success(f"Loaded last entry for RFM{edit_wo} (row {rownum})")

    # Render edit form if loaded
    if st.session_state.edit_loaded and st.session_state.edit_rownum:
        rowdata = st.session_state.edit_rowdata
        edit_wo = st.session_state.edit_wo_selected
        rownum  = st.session_state.edit_rownum

        cur_date = rowdata.get("Date", "") or dt.date.today().strftime("%Y-%m-%d")
        try:
            cur_date_val = dt.datetime.strptime(cur_date, "%Y-%m-%d").date()
        except Exception:
            cur_date_val = dt.date.today()

        with st.form("edit_wo_fields", clear_on_submit=False):
            new_title = st.text_area("Title", value=rowdata.get("Title",""), height=90, key=f"edit_title_{rownum}")

            label = "Description" if is_rfm else "Resolution"
            cur_val = rowdata.get("Description" if is_rfm else "Resolution", "")
            new_res = st.text_area(label, value=cur_val, height=180, key=f"edit_res_{rownum}")

            new_date  = st.date_input("Date", value=cur_date_val, key=f"edit_date_{rownum}")

            STAT_OPTS = (STATUSES if not is_rfm else ["Submitted", "WAPPR", "PO Created", "Close"])
            loc_idx  = LOCATIONS.index(rowdata.get("Location","")) if rowdata.get("Location","") in LOCATIONS else 0
            stat_raw = rowdata.get("Status","")
            stat_idx = STAT_OPTS.index(stat_raw) if stat_raw in STAT_OPTS else 0

            new_loc  = st.selectbox("Location", LOCATIONS, index=loc_idx, key=f"edit_loc_{rownum}")
            new_stat = st.selectbox("Status", STAT_OPTS, index=stat_idx, key=f"edit_stat_{rownum}")

            new_att  = st.text_input("Attachments (URLs, optional)", value=rowdata.get("Attachments",""), key=f"edit_att_{rownum}")

            col_a, col_b = st.columns(2)
            with col_a:
                confirm = st.form_submit_button("Save Changes", use_container_width=True)
            with col_b:
                cancel  = st.form_submit_button("Cancel", use_container_width=True)

            if confirm:
                try:
                    if not is_rfm and new_stat in {"Completed", "RTS"} and not (new_res or "").strip():
                        st.warning("Resolution is required when Status is Completed or RTS.")
                    else:
                        if is_rfm:
                            ws = _open_rfm_ws()
                            new_dict = {
                                "RFM": edit_wo,
                                "Title": (new_title or "").strip(),
                                "Description": (new_res or "").strip(),
                                "Date": new_date.strftime("%Y-%m-%d"),
                                "Location": new_loc,
                                "Status": new_stat,
                                "Attachments": (new_att or "").strip(),
                                "EntryID": rowdata.get("EntryID","") or gen_entry_id(),
                                "CreatedAt": dt.datetime.now().isoformat(timespec="seconds"),
                            }
                            _update_rfm_row_values(ws, rownum, new_dict)
                            st.success(f"Updated RFM{edit_wo} (row {rownum}) ✅")
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

                        st.toast("Entry updated", icon="✏️")
                        st.session_state.edit_loaded = False
                        st.session_state.edit_rownum = None
                        st.session_state.edit_rowdata = {}
                        st.session_state.edit_wo_selected = ""
                        st.cache_data.clear()
                        st.rerun()
                except Exception as e:
                    st.error(f"Update failed: {e}")

            if cancel:
                st.session_state.edit_loaded = False
                st.session_state.edit_rownum = None
                st.session_state.edit_rowdata = {}
                st.session_state.edit_wo_selected = ""
                st.info("Edit canceled.")

# ===================== Quick Progress Note (append WO/RFM) =====================
_ensure_quick_defaults()
with st.sidebar.expander("📝 Quick Progress Note (append WO/RFM)", expanded=False):
    q_kind = st.radio("Type", ["WO", "RFM"], horizontal=True, key="qp_kind")

    # ID input triggers auto-fill of title/location
    st.text_input("ID (#)", key="qp_id", placeholder="e.g., 146720560 or 2025-0001", on_change=_qp_on_id_change)

    # Show last-known snapshot (read-only preview)
    _id_preview = str(st.session_state.get("qp_id","")).strip()
    if _id_preview:
        data = _last_for_wo(_id_preview) if q_kind == "WO" else _last_for_rfm(_id_preview)
        if data:
            _dt = data.get("Date","")
            _st = data.get("Status","")
            _ti = data.get("Title","")
            _lo = data.get("Location","")
            st.caption(f"Last known: **{_ti}**  [{_lo}] — {_st}  ({_dt})")

    # Auto-filled Title/Location remain editable (in case you want to tweak)
    st.text_input("Title (optional)", key="qp_title", placeholder="auto-fills from last known")
    st.selectbox("Location", LOCATIONS, key="qp_loc")
    st.date_input("Date", key="qp_date")
    st.text_area("Work performed / note", key="qp_note",
                 placeholder="What did you do? Parts swapped, tests run, readings, etc.", height=120)

    keep = st.checkbox("Keep current status (from last entry)", key="qp_keep_status")
    if not keep:
        if q_kind == "WO":
            st.selectbox("Status for this note (WO)", STATUSES, key="qp_status")
        else:
            st.selectbox("Status for this note (RFM)", ["Submitted","WAPPR","PO Created","Close"], key="qp_status_rfm")

    c1, c2 = st.columns(2)
    with c1:
        submit_qp = st.button("Append Note", use_container_width=True, key="qp_submit_btn")
    with c2:
        st.button("Clear", use_container_width=True, key="qp_clear_btn", on_click=clear_quick_note)

    if submit_qp:
        try:
            kind = st.session_state.get("qp_kind", "WO")
            _id  = str(st.session_state.get("qp_id","")).strip()
            if not _id:
                st.error("ID is required (WO or RFM number).")
            else:
                title = st.session_state.get("qp_title","") or None
                note  = st.session_state.get("qp_note","")
                loc   = st.session_state.get("qp_loc", LOCATIONS[0])
                datev = st.session_state.get("qp_date", dt.date.today())
                status = None
                if not st.session_state.get("qp_keep_status", True):
                    status = st.session_state.get("qp_status") if kind == "WO" else st.session_state.get("qp_status_rfm")

                if kind == "WO":
                    append_progress_note(_id, title, note, status, loc, datev)
                else:
                    append_rfm_note(_id, title, note, status, loc, datev)

                st.toast("Note appended ✅", icon="🧷")
                st.cache_data.clear()
                clear_quick_note()
        except Exception as e:
            st.error(f"Could not append: {e}")


# --- Data load for main panels ---

def _explain_api_error(e: APIError) -> str:
    try:
        import json as _json
        payload = _json.loads(e.response.text)
        code = payload.get("error", {}).get("code")
        msg = payload.get("error", {}).get("message")
        return f"{code}: {msg}"
    except Exception:
        return str(e)

try:
    if not SPREADSHEET_ID:
        raise RuntimeError("TURNOVER_SPREADSHEET_ID is not set in secrets or environment.")
    df = load_df()
    rfm_df = load_rfm_df()
except APIError as e:
    detail = _explain_api_error(e)
    st.error("Google Sheets API error while opening the spreadsheet.")
    st.code(detail)
    st.info(
        """Fix checklist:\n"
        "1) In Streamlit **secrets**, set `TURNOVER_SPREADSHEET_ID` to the ID from your sheet URL (between `/d/` and `/edit`).\n"
        "2) Share the Google Sheet with your **service account** email (Editor). The email is the `client_email` in your credentials JSON.\n"
        "3) Ensure the **Google Sheets API** (and Drive API if you create tabs) is enabled for the project."""
    )
    df = pd.DataFrame(columns=EXPECTED_HEADERS)
    rfm_df = pd.DataFrame(columns=RFM_HEADERS)
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.info("`TURNOVER_SPREADSHEET_ID` is missing or invalid.")
    df = pd.DataFrame(columns=EXPECTED_HEADERS)
    rfm_df = pd.DataFrame(columns=RFM_HEADERS)

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
        # --- Search Results (WOs + RFMs) ---
    if query and query.strip():
        q = query.strip().lower()

        # WOs come from your existing df
        wo_df = df.copy()

        # RFMs come from the RFM tab
        rfm_df = load_rfm_df().copy()

        # Build simple full-text blobs (self-contained; no new helpers needed)
        def _mk_blob(d, cols_priority):
            if d.empty:
                return pd.Series([], dtype=str)
            cols = [c for c in cols_priority if c in d.columns]
            if cols:
                blob = d[cols].astype(str).agg(" ".join, axis=1)
            else:
                blob = d.astype(str).apply(lambda r: " ".join(map(str, r.values)), axis=1)
            return blob.str.lower()

        if not wo_df.empty:
            wo_df["_searchblob"] = _mk_blob(wo_df, ["WO","Title","Resolution","Status","Location","Notes","Date"])
        if not rfm_df.empty:
            rfm_df["_searchblob"] = _mk_blob(rfm_df, ["RFM","Title","Resolution","Status","Notes","Date"])

        # Filter by query
        wo_hits  = wo_df[ wo_df["_searchblob"].str.contains(q, na=False) ] if not wo_df.empty  else wo_df
        rfm_hits = rfm_df[ rfm_df["_searchblob"].str.contains(q, na=False) ] if not rfm_df.empty else rfm_df

        # Prepare columns to show
        wo_cols = [c for c in ["WO","Title","Resolution","Status","Date"] if (not wo_hits.empty and c in wo_hits.columns)]
        if not wo_cols and not wo_hits.empty:
            wo_cols = [c for c in wo_hits.columns if c not in ["_searchblob"]][:5]

        if not rfm_hits.empty:
            # Present RFM with a WO-like column for readability
            view = rfm_hits.rename(columns={"RFM": "WO"}) if "RFM" in rfm_hits.columns else rfm_hits.copy()
            view["WO"] = "RFM-" + view["WO"].astype(str)
        else:
            view = rfm_hits

        rfm_cols = [c for c in ["WO","Title","Resolution","Status","Date"] if (not view.empty and c in view.columns)]
        if not rfm_cols and not view.empty:
            rfm_cols = [c for c in view.columns if c not in ["_searchblob"]][:5]

# --- Normalize filter vars (in case this block runs in a different scope) ---
if "query"       not in locals(): query = ""
if "start"       not in locals(): start = None
if "end"         not in locals(): end = None
if "loc_mult"    not in locals(): loc_mult = []
if "status_mult" not in locals(): status_mult = []
use_dates = bool(start or end)

ss = st.session_state
query       = ss.get("query", query)
start       = ss.get("start", start)
end         = ss.get("end", end)
loc_mult    = ss.get("loc_mult", loc_mult)
status_mult = ss.get("status_mult", status_mult)
use_dates   = bool(start or end)

       # --- Global Search Results (across all dates/status) ---
st.subheader("Search Results")
matches = apply_filters(df.copy(), query, start, end, loc_mult, status_mult)

if (query or "").strip() or use_dates or loc_mult or status_mult:
    if matches.empty:
        st.caption("No matches.")
    else:
        import html, re

        # Pull simple keywords from the query for highlighting
        terms = [t for t in re.findall(r"\w+", (query or "")) if len(t) > 1]

        def highlight(txt: str) -> str:
            """HTML-escape then highlight query terms."""
            s = html.escape(str(txt or ""))
            for t in terms:
                s = re.sub(
                    re.escape(t), 
                    lambda m: f"<span style='background:#fff3cd'>{m.group(0)}</span>",
                    s,
                    flags=re.IGNORECASE
                )
            return s

        # We want one result per WO that had any matching row
        wo_ids = [str(x) for x in matches["WO"].astype(str).unique()]

        for wo in wo_ids:
            # Full thread for this WO (oldest -> newest)
            thread = df[df["WO"].astype(str) == wo].copy()
            if "CreatedAt" in thread.columns:
                thread["CreatedAt_ts"] = pd.to_datetime(thread["CreatedAt"], errors="coerce")
                thread = thread.sort_values("CreatedAt_ts")

            # Latest entry (summary line)
            last = thread.tail(1).iloc[0]
            title  = str(last.get("Title",""))
            res    = str(last.get("Resolution",""))
            status = str(last.get("Status",""))
            loc    = str(last.get("Location",""))
            date   = str(last.get("Date",""))

            # Count how many rows in this thread actually match the query (for a small badge)
            def row_hits(row) -> bool:
                blob = " ".join([str(row.get("Title","")), str(row.get("Resolution","")), str(row.get("Location",""))])
                return any(t.lower() in blob.lower() for t in terms)
            hit_count = int(thread.apply(row_hits, axis=1).sum()) if terms else 0
            hit_badge = f"<span style='opacity:.6;'>[{hit_count} match{'es' if hit_count!=1 else ''}]</span>" if hit_count else ""

            pill = colored_status(status)

            # Build the expanded history (oldest -> newest) with highlights
            hist_items = []
            for _, rr in thread.iterrows():
                p   = colored_status(str(rr.get("Status","")))
                d   = highlight(rr.get("Date",""))
                t   = highlight(rr.get("Title",""))
                rsz = highlight(rr.get("Resolution",""))
                hist_items.append(f"<li><b>{d}</b> — {t} | {rsz} &nbsp; {p}</li>")
            hist_html = "<ul style='margin-top:.5rem;'>" + "".join(hist_items) + "</ul>"

            # Clickable summary using <details> so the SUMMARY is the row itself
            summary_html = (
                wo_line(wo, highlight(title), highlight(res))
                + f" &nbsp; <span style='opacity:.7;'>[{html.escape(loc)}]</span> &nbsp; {pill} &nbsp; "
                + f"<span style='opacity:.6;'>{html.escape(date)}</span> &nbsp; {hit_badge}"
            )

            block = f"""
            <details style="padding:.4rem .6rem; border-radius:.5rem; border:1px solid #2a2a2a20; margin-bottom:.35rem;">
              <summary style="cursor:pointer; list-style:none;">
                <span style="display:inline-block; transform:translateY(1px);">{summary_html}</span>
              </summary>
              {hist_html}
            </details>
            """
            st.markdown(block, unsafe_allow_html=True)
else:
    st.caption("Use the search or filters to find entries.")


# --- Right-side panels ---
left, right = st.columns([1.2, 2])

# Today’s WOs (exclude WMATL)
# Today’s WOs (dedup by WO; show latest only + history)
with left:
    st.subheader("Today’s WOs")
    today_str = dt.date.today().strftime("%Y-%m-%d")
    todays = df[(df["Date"] == today_str)].copy()
    todays = drop_rfm_rows(todays)
    todays = apply_filters(todays, query, start, end, loc_mult, status_mult)

    if todays.empty:
        st.caption("No entries today.")
    else:
        # keep only the latest entry per WO
        latest_today = todays.copy()
        latest_today["CreatedAt_ts"] = pd.to_datetime(latest_today["CreatedAt"], errors="coerce")
        latest_today = latest_today.sort_values("CreatedAt_ts").groupby("WO", as_index=False).tail(1)

        # order nicely
        latest_today = latest_today.sort_values("CreatedAt_ts")

        for _, r in latest_today.iterrows():
            wo  = str(r.get("WO",""))
            loc = str(r.get("Location",""))
        
            # Full thread (oldest -> newest)
            thread = df[df["WO"].astype(str) == wo].copy()
            if "CreatedAt" in thread.columns:
                thread["CreatedAt_ts"] = pd.to_datetime(thread["CreatedAt"], errors="coerce")
                thread = thread.sort_values("CreatedAt_ts")
        
            # Latest entry = last input
            last = thread.tail(1).iloc[0] if not thread.empty else r
            last_title  = str(last.get("Title",""))
            last_res    = str(last.get("Resolution",""))
            last_status = str(last.get("Status",""))
            last_date   = str(last.get("Date",""))
        
            # Status pill for quick read
            pill = colored_status(last_status)
        
            # Escape user text to avoid breaking HTML
            etitle = html.escape(last_title)
            eres   = html.escape(last_res)
            eloc   = html.escape(loc)
            edate  = html.escape(last_date)
        
            # Build history HTML (oldest -> newest)
            hist_rows = []
            for _, rr in thread.iterrows():
                p   = colored_status(str(rr.get("Status","")))
                d   = html.escape(str(rr.get("Date","")))
                t   = html.escape(str(rr.get("Title","")))
                res = html.escape(str(rr.get("Resolution","")))
                hist_rows.append(
                    f"<li><b>{d}</b> — {t} | {res} &nbsp; {p}</li>"
                )
            hist_html = "<ul style='margin-top:.5rem;'>" + "".join(hist_rows) + "</ul>"
        
            # Clickable row using <details><summary>
           # Build the green resolution HTML safely, then hand it to wo_line
            green_res = f"<span style='color:#1a7f37;'>{eres}</span>"
            
            summary_html = (
                wo_line(wo, etitle, green_res)
                + f" &nbsp; <span style='opacity:.7;'>[{eloc}]</span> &nbsp; {pill} &nbsp; "
                + f"<span style='opacity:.6;'>{edate}</span>"
            )

        
            block = f"""
            <details style="padding:.4rem .6rem; border-radius:.5rem; border:1px solid #2a2a2a20; margin-bottom:.35rem;">
              <summary style="cursor:pointer; list-style:none;">
                <span style="display:inline-block; transform:translateY(1px);">{summary_html}</span>
              </summary>
              {hist_html}
            </details>
            """
        
            st.markdown(block, unsafe_allow_html=True)

# Open WOs (includes WMATL). Show latest entry per WO.
with right:
    st.subheader("Open WOs")
    latest = latest_status_by_wo(df)
    open_wo = latest[~latest["Status"].isin(["Completed","RTS","WMATL"])].copy()
    open_wo = drop_rfm_rows(open_wo)
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

                if str(r.get("Attachments","")):
                    links = [x.strip() for x in str(r["Attachments"]).split(',') if x.strip()]
                    st.caption("Attachments:")
                    for i, url in enumerate(links, 1):
                        st.markdown(f"- [File {i}]({url})")

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

# ===== RFM TRACKER (read-only list; editing via sidebar) =====
st.subheader("Open RFMs")
rfm_df_latest = latest_status_by_rfm(rfm_df)
open_rfm = rfm_df_latest[~rfm_df_latest["Status"].isin(["Completed","RTS"])].copy()

if open_rfm.empty:
    st.caption("No open RFMs 🎉")
else:
    if "CreatedAt" in open_rfm.columns:
        open_rfm = open_rfm.sort_values("CreatedAt")

    from html import escape  # safe to put here or at top of file once

    for _, r in open_rfm.iterrows():
        label = str(r.get("Status", "")).strip()
        title = str(r.get("Title", "")) or ""
        desc  = str(r.get("Description", "")) or ""
        loc   = str(r.get("Location", "")) or ""
        rfmno = str(r.get("RFM", "")) or ""

        pill = colored_status(label)

        title_html = escape(title)
        loc_html   = escape(loc)
        desc_html  = (
            f"<div style='margin-top:.35rem; white-space:pre-wrap;'>{escape(desc)}</div>"
            if desc.strip() else ""
        )

        attachments = str(r.get("Attachments", "")).strip()
        att_html = ""
        if attachments:
            links = [x.strip() for x in attachments.split(",") if x.strip()]
            if links:
                items = "\n".join(
                    f"<li><a href='{escape(url)}' target='_blank' rel='noopener'>File {i}</a></li>"
                    for i, url in enumerate(links, 1)
                )
                att_html = f"<div style='opacity:.75;margin-top:.25rem;'>Attachments:</div><ul>{items}</ul>"

        details_html = f"""
<details style="margin:.25rem 0 .5rem 0;">
  <summary style="cursor:pointer; display:flex; align-items:center; gap:.5rem;">
    {pill}
    <span><strong>RFM{escape(rfmno)} — {title_html}</strong> <span style='opacity:.75;'>[{loc_html}]</span></span>
  </summary>
  <div style="padding:.5rem 0 0 .25rem;">
    {desc_html}
    {att_html}
  </div>
</details>
        """.strip()

        st.markdown(details_html, unsafe_allow_html=True)

# WMATL box (compact, readable on dark theme)
st.subheader("WMATL")
wmatl_latest = latest_status_by_wo(df)
wmatl = wmatl_latest[wmatl_latest["Status"] == "WMATL"].copy()
wmatl = drop_rfm_rows(wmatl)
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
    if "CreatedAt" in wmatl.columns:
        wmatl = wmatl.sort_values("CreatedAt")
    tags = [f"<span class='wmatl-tag'>WO{r['WO']} — {r['Title']}</span>" for _, r in wmatl.iterrows()]
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
                first_row = _with_backoff(ws.row_values, 1)
                if not first_row or [c.strip() for c in first_row] != EXPECTED_HEADERS:
                    _with_backoff(ws.update, "A1", [EXPECTED_HEADERS])
                    try:
                        _with_backoff(ws.freeze, rows=1)
                    except Exception:
                        pass
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
        st.info(
            "- Service account doesn’t have **edit** access to this spreadsheet.\n"
            "- Wrong spreadsheet ID/URL in your secrets.\n"
            "- Network/credentials issue."
        )

# CSV backup
st.divider()
try:
    csv_bytes = pd.DataFrame(df).to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV (backup)", csv_bytes,
                       file_name="turnover_log.csv", mime="text/csv",
                       use_container_width=True, key="download_csv_btn")
except Exception:
    pass
