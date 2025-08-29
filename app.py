import streamlit as st

st.set_page_config(page_title="Inventory Dashboard", layout="wide")

st.title("📦 Inventory Dashboard — Shopify + Warehouse + EBO")

st.markdown(
    """
Welcome! Use the sidebar to navigate:

- **Admin**: Upload data files (password protected).
- **User**: View dashboards and insights (read-only).
"""
)

st.info("Tip: Configure credentials in **Settings → Secrets** on Streamlit Community Cloud.")
