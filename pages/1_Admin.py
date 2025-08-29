import pandas as pd
import streamlit as st
from datetime import timedelta
from rapidfuzz import fuzz, process
import cloudinary
import cloudinary.api
import cloudinary.uploader

st.set_page_config(page_title="Admin Panel", layout="wide")
st.title("🔑 Admin Panel")

# -------------------------------
# Auth
# -------------------------------
entered = st.text_input("Enter Admin Password", type="password")
if "admin" not in st.secrets or "password" not in st.secrets["admin"]:
    st.error("Admin password not configured. Add it under [admin] in secrets.")
    st.stop()

if entered != st.secrets["admin"]["password"]:
    st.warning("Access restricted. Enter the correct password to continue.")
    st.stop()

st.success("✅ Authenticated as Admin")

# -------------------------------
# Cloudinary config (for later user page usage)
# -------------------------------
if "cloudinary" in st.secrets:
    cloudinary.config(
        cloud_name=st.secrets["cloudinary"]["cloud_name"],
        api_key=st.secrets["cloudinary"]["api_key"],
        api_secret=st.secrets["cloudinary"]["api_secret"],
        secure=True
    )
else:
    st.warning("⚠️ Cloudinary not configured in secrets. The User page will still work except Image Availability.")

# -------------------------------
# Helpers & required columns
# -------------------------------
REQ_SHOPIFY = ["Barcode", "Design No", "Closing Qty", "CDN link"]
REQ_WAREHOUSE = ["Barcode", "Design No", "Closing Qty"]
REQ_EBO = ["Barcode", "Design No", "Closing Qty"]
REQ_ORDERS = ["Design No", "Quantity", "Created at"]  # Orders do not have Barcode

def load_file(file, req_cols, label):
    if file is None:
        return None
    df = pd.read_csv(file) if file.name.endswith(".csv") else pd.read_excel(file)
    df.columns = df.columns.str.strip()
    missing = [c for c in req_cols if c not in df.columns]
    if missing:
        st.error(f"{label} is missing required columns: {missing}")
        return None
    df["Design No"] = df["Design No"].astype(str)
    if "Barcode" in df.columns:
        df["Barcode"] = df["Barcode"].astype(str)
    if "Closing Qty" in df.columns:
        df["Closing Qty"] = pd.to_numeric(df["Closing Qty"], errors="coerce").fillna(0).astype(int)
    if "Quantity" in df.columns:
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0).astype(int)
    if "Created at" in df.columns:
        df["Created at"] = pd.to_datetime(df["Created at"], errors="coerce")
    return df

# -------------------------------
# Uploaders
# -------------------------------
st.sidebar.header("Upload Data (Admin)")
shopify_file = st.sidebar.file_uploader("Shopify Inventory", type=["csv", "xlsx"])
warehouse_file = st.sidebar.file_uploader("Warehouse Inventory", type=["csv", "xlsx"])
ebo_file = st.sidebar.file_uploader("EBO Inventory", type=["csv", "xlsx"])
orders_file = st.sidebar.file_uploader("Shopify Orders", type=["csv", "xlsx"])

shopify_df = load_file(shopify_file, REQ_SHOPIFY, "Shopify")
warehouse_df = load_file(warehouse_file, REQ_WAREHOUSE, "Warehouse")
ebo_df = load_file(ebo_file, REQ_EBO, "EBO")
orders_df = load_file(orders_file, REQ_ORDERS, "Orders")

# -------------------------------
# Save to session for User page
# -------------------------------
st.session_state["shopify_df"] = shopify_df
st.session_state["warehouse_df"] = warehouse_df
st.session_state["ebo_df"] = ebo_df
st.session_state["orders_df"] = orders_df

# Quick preview
with st.expander("📄 Preview Uploaded DataFrames"):
    if shopify_df is not None: st.write("**Shopify**", shopify_df.head())
    if warehouse_df is not None: st.write("**Warehouse**", warehouse_df.head())
    if ebo_df is not None: st.write("**EBO**", ebo_df.head())
    if orders_df is not None: st.write("**Orders**", orders_df.head())

if any(df is not None for df in [shopify_df, warehouse_df, ebo_df, orders_df]):
    st.success("✅ Data saved for this session. Navigate to **User** page to see dashboards.")
else:
    st.info("Upload files using the sidebar to enable the User dashboards.")
