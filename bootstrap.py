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

    def check_config(client, sheet_name="turnover_log"):
        """check secrets and sheet connectivity before running the app.
        show debug info only if something is missing or broken.
        """
        errors = []

        # check secrets
        url = get_sheet_url()
        if "gcp_service_account" not in st.secrets:
            errors.append("x gcp_service_account missing")

        if not url:
            errors.append("x SHEET_URL missing(top-level, inside gcp_service_account, or env)")

        # check sheet access
        if url:
            try:
                sh = client.open_by_url(url)
                sh.worksheet(sheet_name)
            except Exeption as e:
                errors.append(f"x could not access sheet/tab '{sheet_name': {e}")

        # Report in UI
        if errors:
            st.subheader("🔧 Configuration Check")
            st.error("Configuration issues detected:")
            for e in errors:
                st.writes("-", e)
            st.stop()

        # Return the URL if all good
        return url
