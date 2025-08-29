import streamlit as st

st.set_page_config(page_title="Inventory Dashboard", layout="wide")

st.title("📦 Inventory Dashboard")

st.markdown("""
Welcome!  
- If you are **Admin**, go to the **Admin page** (from sidebar) and upload files.  
- If you are a **User**, go to the **User page** to view results.
""")

st.info("Use the sidebar to navigate between **Admin** and **User** views.")
