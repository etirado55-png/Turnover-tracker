# bootstrap.py
import os
import streamlit as st

def get_sheet_url():
    """
    Find Google Sheet URL from:
    1) top-level secret SHEET_URL
    2) inside [gcp_service_account] as SHEET_URL
    3) environment variable SHEET_URL
    """
    return (
        st.secrets.get("SHEET_URL")
        or (st.secrets.get("gcp_service_account") or {}).get("SHEET_URL")
        or os.environ.get("SHEET_URL")
    )

def check_config(client, sheet_name="turnover_log"):
    """
    Validate secrets + Google Sheet connectivity.
    Stays quiet if OK; shows one clear error block and stops if not.
    Returns the resolved sheet URL.
    """
    errors = []

    if "gcp_service_account" not in st.secrets:
        errors.append("❌ gcp_service_account missing in Streamlit secrets.")

    url = get_sheet_url()
    if not url:
        errors.append("❌ SHEET_URL missing (top-level secret, inside gcp_service_account, or env var).")

    if url:
        try:
            sh = client.open_by_url(url)
            sh.worksheet(sheet_name)
        except Exception as e:
            # use format() to avoid f-strings / quoting issues
            errors.append("❌ Could not access sheet/tab '{}': {}".format(sheet_name, e))

    if errors:
        st.subheader("🔧 Configuration Check")
        st.error("Configuration issues detected:")
        for e in errors:
            st.write("-", e)
        st.stop()

    return url
