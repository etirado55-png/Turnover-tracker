import streamlit as st
from google.oauth2 import service_account
import gspread
from gspread.exceptions import WorksheetNotFound

# Scopes: you can tighten to drive.file after everything works
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ===== Credentials / client =====

def _service_account_info():
    # Expects [gcp_service_account] in .streamlit/secrets.toml
    return dict(st.secrets["gcp_service_account"])

def get_creds(scopes=SCOPES):
    return service_account.Credentials.from_service_account_info(
        _service_account_info(), scopes=scopes
    )

@st.cache_resource
def get_gc(scopes=SCOPES):
    return gspread.authorize(get_creds(scopes))

# ===== Spreadsheet helpers =====

def open_spreadsheet(gc=None, spreadsheet_id: str | None = None):
    """
    Open the existing Google Sheet by ID (no file creation).
    """
    if spreadsheet_id is None:
        spreadsheet_id = st.secrets.get("TURNOVER_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("TURNOVER_SPREADSHEET_ID not set in secrets.")
    if gc is None:
        gc = get_gc()
    return gc.open_by_key(spreadsheet_id)

def ensure_worksheet_and_headers(
    sh, ws_title: str, headers: list[str], rows=2000
):
    """
    Ensure worksheet exists and header row is set.
    """
    try:
        ws = sh.worksheet(ws_title)
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=ws_title, rows=rows, cols=max(26, len(headers)))
        ws.update("1:1", [headers])
        try: ws.freeze(rows=1)
        except Exception: pass
        return ws

    # Ensure header row if empty
    vals = ws.get("1:1")
    current = vals[0] if vals else []
    if not current or all((c or "").strip() == "" for c in current):
        ws.update("1:1", [headers])
        try: ws.freeze(rows=1)
        except Exception: pass
    return ws

# ===== Data operations =====

def fetch_all(ws):
    """Return (headers, rows) where rows is a list of lists (no header)."""
    all_vals = ws.get_all_values()
    if not all_vals:
        return [], []
    headers = all_vals[0]
    rows = all_vals[1:]
    return headers, rows

def append_row(ws, data_row: list[str]):
    ws.append_row(data_row, value_input_option="USER_ENTERED")

def find_row_by_wo(ws, wo_col_index: int, wo_value: str):
    """
    Return (row_number_1_based, row_values) or (None, None) if not found.
    wo_col_index is 0-based index into the data rows (not counting header).
    """
    headers, rows = fetch_all(ws)
    for i, r in enumerate(rows, start=2):  # +1 header, +1 to make 1-based row index
        try:
            if (r[wo_col_index] or "").strip() == (wo_value or "").strip():
                return i, r
        except IndexError:
            continue
    return None, None

def update_row(ws, row_number_1_based: int, new_row_values: list[str]):
    """
    Replace entire row (except header). Assumes new_row_values length <= current sheet width.
    """
    rng = f"{row_number_1_based}:{row_number_1_based}"
    ws.update(rng, [new_row_values], value_input_option="USER_ENTERED")
