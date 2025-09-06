import os
import streamlit as st

def get_sheet_url():
    """"
    Look for Google Sheet URL in multiple places:
    1. Top-level key in streamlit secrets (SHEET_URL)
    2. Inside [gcp_service_account] block in secrets
    3. Environment variable SHEET_URL
    """
    return (
        st.secrets.get("SHEET_URL")
        or (st.secrets.get("gcp_service_account") or {}).get("SHEET_URL")
        or os.environ.get("SHEET_URL")
    )

    # bootstrap.py
import os
import streamlit as st

def get_sheet_url():
    return (
        st.secrets.get("SHEET_URL")
        or (st.secrets.get("gcp_service_account") or {}).get("SHEET_URL")
        or os.environ.get("SHEET_URL")
    )

def check_config(client, sheet_name="turnover_log"):
    """Validate secrets + Google Sheet connectivity; quiet if OK, clear error if not."""
    errors = []

    # Secrets present?
    if "gcp_service_account" not in st.secrets:
        errors.append("❌ gcp_service_account missing in Streamlit secrets.")

    url = get_sheet_url()
    if not url:
        errors.append("❌ SHEET_URL missing (top-level secret, inside gcp_service_account, or env var).")

    # Can we open the sheet/tab?
    if url:
        try:
            sh = client.open_by_url(url)
            sh.worksheet(sheet_name)
        except Exception as e:
            errors.append(f"❌ Could not access sheet/tab '{sheet_name}': {e}")

    if errors:
        st.subheader("🔧 Configuration Check")
        st.error("Configuration issues detected:")
        for e in errors:
            st.write("-", e)
        st.stop()

    return url
