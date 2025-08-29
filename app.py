import streamlit as st

# App config
st.set_page_config(page_title="Inventory Dashboard", layout="wide")

# Sidebar navigation
st.sidebar.title("🔍 Navigation")
view = st.sidebar.radio("Choose view:", ["User", "Admin"])

st.title("📦 Inventory Dashboard — Shopify + Warehouse + EBO")

st.markdown(
    """
Welcome! Use the sidebar to navigate:

- **Admin**: Upload data files (password protected).
- **User**: View dashboards and insights (read-only).
"""
)

st.info("Tip: Configure credentials in **Settings → Secrets** on Streamlit Community Cloud.")

# Admin section
if view == "Admin":
    st.subheader("🔑 Admin View")

    # Check password (from secrets)
    password = st.text_input("Enter admin password:", type="password")
    if password == st.secrets["password"]:
        st.success("Access granted ✅")
        uploaded_file = st.file_uploader("Upload a data file (CSV/Excel)", type=["csv", "xlsx"])
        if uploaded_file:
            st.write(f"✅ File `{uploaded_file.name}` uploaded successfully!")
            # process file here...
    elif password:
        st.error("❌ Incorrect password")

# User section
elif view == "User":
    st.subheader("👥 User View")
    st.write("Here you can show dashboards and insights from the uploaded files.")
    # Example placeholder
    st.metric("Total Products", "1,250")
    st.metric("Out of Stock", "45")
    st.metric("Pending Orders", "132")
