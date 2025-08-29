import pandas as pd
import streamlit as st
from rapidfuzz import fuzz, process
from datetime import timedelta
import matplotlib.pyplot as plt
import cloudinary
import cloudinary.api

# ================================
# Auth for Admin
# ================================
st.title("🔑 Admin Panel")

password = st.text_input("Enter Admin Password", type="password")
if password != st.secrets["admin"]["password"]:
    st.error("❌ Wrong password. Access denied.")
    st.stop()

st.success("✅ Logged in as Admin")

# ================================
# Cloudinary Config
# ================================
if "cloudinary" in st.secrets:
    cloudinary.config(
        cloud_name=st.secrets["cloudinary"]["cloud_name"],
        api_key=st.secrets["cloudinary"]["api_key"],
        api_secret=st.secrets["cloudinary"]["api_secret"],
        secure=True
    )
else:
    st.warning("⚠️ Cloudinary not configured. Add credentials in secrets.toml")

# ================================
# File Uploads
# ================================
st.sidebar.header("Upload Data")
shopify_file = st.sidebar.file_uploader("Shopify Inventory", type=["csv", "xlsx"])
warehouse_file = st.sidebar.file_uploader("Warehouse Inventory", type=["csv", "xlsx"])
ebo_file = st.sidebar.file_uploader("EBO Inventory", type=["csv", "xlsx"])
orders_file = st.sidebar.file_uploader("Shopify Orders", type=["csv", "xlsx"])

REQ_SHOPIFY = ["Barcode", "Design No", "Closing Qty", "CDN link"]
REQ_WAREHOUSE = ["Barcode", "Design No", "Closing Qty"]
REQ_EBO = ["Barcode", "Design No", "Closing Qty"]
REQ_ORDERS = ["Design No", "Quantity", "Created at"]

def load_file(file, req_cols, label):
    if file is None: return None
    df = pd.read_csv(file) if file.name.endswith(".csv") else pd.read_excel(file)
    df.columns = df.columns.str.strip()
    missing = [c for c in req_cols if c not in df.columns]
    if missing:
        st.error(f"{label} missing required columns: {missing}")
        return None
    df["Design No"] = df["Design No"].astype(str)
    if "Closing Qty" in df.columns:
        df["Closing Qty"] = pd.to_numeric(df["Closing Qty"], errors="coerce").fillna(0).astype(int)
    if "Quantity" in df.columns:
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0).astype(int)
    if "Created at" in df.columns:
        df["Created at"] = pd.to_datetime(df["Created at"], errors="coerce")
    return df

shopify_df = load_file(shopify_file, REQ_SHOPIFY, "Shopify")
warehouse_df = load_file(warehouse_file, REQ_WAREHOUSE, "Warehouse")
ebo_df = load_file(ebo_file, REQ_EBO, "EBO")
orders_df = load_file(orders_file, REQ_ORDERS, "Orders")

# ================================
# Store in session_state for User view
# ================================
st.session_state["shopify_df"] = shopify_df
st.session_state["warehouse_df"] = warehouse_df
st.session_state["ebo_df"] = ebo_df
st.session_state["orders_df"] = orders_df

st.success("✅ Data uploaded. Users can now view results in the User page.")
