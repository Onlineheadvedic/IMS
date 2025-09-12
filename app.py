import streamlit as st
import pandas as pd
from google.oauth2.service_account import Credentials
import gspread
from googleapiclient.discovery import build
from rapidfuzz import fuzz, process
from datetime import timedelta
import matplotlib.pyplot as plt

# Configure page
st.set_page_config(page_title="Inventory Dashboard", layout="wide")

# Load secrets
SERVICE_ACCOUNT_INFO = st.secrets["service_account"]
SPREADSHEET_ID = st.secrets["spreadsheet_id"]
DRIVE_FOLDER_ID = st.secrets["drive_folder_id"]
ADMIN_PASSWORD = st.secrets["admin_password"]
CLOUDINARY_CONFIG = st.secrets["cloudinary"]

# Set Google API scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Authenticate Google service account
creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
gc = gspread.authorize(creds)

# Cloudinary config (optional, if you use it)
import cloudinary
cloudinary.config(
    cloud_name=CLOUDINARY_CONFIG["cloud_name"],
    api_key=CLOUDINARY_CONFIG["api_key"],
    api_secret=CLOUDINARY_CONFIG["api_secret"],
    secure=True,
)

# Helper: Fetch worksheet data as DataFrame
def fetch_sheet_df(sheet_name):
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(sheet_name)
    records = ws.get_all_records()
    return pd.DataFrame(records)

# Helper: fuzzy matching
def fuzzy_best_match(query, choices):
    if not query or not len(choices):
        return None, 0
    match = process.extractOne(query, choices, scorer=fuzz.WRatio)
    if match:
        return match[0], match[1]
    return None, 0

# Admin password sidebar input to select role
role_choice = st.sidebar.radio("Select View", ["User", "Admin"])
if role_choice == "Admin":
    pwd = st.sidebar.text_input("Enter Admin Password", type="password")
    if pwd == ADMIN_PASSWORD:
        role = "Admin"
        st.sidebar.success("✅ Admin access granted")
    else:
        role = "User"
        st.sidebar.error("❌ Incorrect password. Accessing User view.")
else:
    role = "User"

# Load data from Google Sheets
shopify_df = fetch_sheet_df("Shopify")
warehouse_df = fetch_sheet_df("Warehouse")
ebo_df = fetch_sheet_df("EBO")
orders_df = fetch_sheet_df("Orders")
users_df = fetch_sheet_df("Users")  # For login if you want to extend

# Clean Design No and Barcode columns for matching
for df in [shopify_df, warehouse_df, ebo_df]:
    df["Design No"] = df["Design No"].astype(str).str.strip()
    df["Barcode"] = df["Barcode"].astype(str).str.strip()

# Main dashboard metrics
wh_total = warehouse_df["Closing Qty"].sum()
ebo_total = ebo_df["Closing Qty"].sum()
shop_total = shopify_df["Closing Qty"].sum()
overall_total = wh_total + ebo_total + shop_total

col1, col2, col3, col4 = st.columns(4)
col1.metric("Warehouse Qty", wh_total)
col2.metric("EBO Qty", ebo_total)
col3.metric("Shopify Qty", shop_total)
col4.metric("Overall Qty", overall_total)

# Tab layout
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Inventory Overview", "🔍 Search", "📈 Sales Trends",
    "📂 Listed vs Non-Listed", "📷 Image Availability"
])

# Tab 1: Inventory Overview
with tab1:
    st.subheader("Inventory Overview")
    core_cols = ["Design No", "Barcode", "Color", "Size", "Closing Qty"]

    ws_group = warehouse_df[core_cols].groupby(["Design No", "Barcode"]).sum().reset_index()
    sh_group = shopify_df[core_cols].groupby(["Design No", "Barcode"]).sum().reset_index()
    ebo_group = ebo_df[core_cols].groupby(["Design No", "Barcode"]).sum().reset_index()

    merged = ws_group.merge(sh_group, on=["Design No", "Barcode"], how="outer", suffixes=('_Warehouse', '_Shopify'))
    merged = merged.merge(ebo_group, on=["Design No", "Barcode"], how="outer")
    merged.rename(columns={"Closing Qty": "Closing Qty_EBO"}, inplace=True)
    merged.fillna(0, inplace=True)
    merged["Total_QTY"] = merged[["Closing Qty_Warehouse", "Closing Qty_Shopify", "Closing Qty_EBO"]].sum(axis=1)

    st.dataframe(merged.sort_values("Total_QTY", ascending=False).head(50))

    top20 = merged.sort_values("Total_QTY", ascending=False).head(20)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(top20["Design No"], top20["Total_QTY"], color="skyblue")
    plt.xticks(rotation=45, ha="right")
    st.pyplot(fig)

# Tab 2: Search
with tab2:
    st.subheader("Search by Design No or Barcode")
    query = st.text_input("Enter Design No or Barcode")
    if query:
        results = []
        for label, df in [("Warehouse", warehouse_df), ("Shopify", shopify_df), ("EBO", ebo_df)]:
            qty = 0
            if "Barcode" in df.columns and query in df["Barcode"].values:
                qty = df[df["Barcode"] == query]["Closing Qty"].sum()
            else:
                match, _ = fuzzy_best_match(query, df["Design No"].unique())
                if match:
                    qty = df[df["Design No"] == match]["Closing Qty"].sum()
            results.append({"Source": label, "Qty": int(qty)})
        results.append({"Source": "Total", "Qty": sum(r["Qty"] for r in results)})
        st.table(pd.DataFrame(results))

        cdn = None
        if "CDN link" in shopify_df.columns:
            if query in shopify_df["Barcode"].values:
                cdn = shopify_df.loc[shopify_df["Barcode"] == query, "CDN link"].iloc[0]
            else:
                match, _ = fuzzy_best_match(query, shopify_df["Design No"].unique())
                if match:
                    cdn = shopify_df.loc[shopify_df["Design No"] == match, "CDN link"].iloc[0]
        if cdn:
            st.image(cdn, caption=f"Design {query}")
        else:
            st.warning("No CDN image found.")

# Tab 3: Sales Trends
with tab3:
    st.subheader("📈 Sales Trends (last 3 days)")
    reorder, notselling = [], []
    if not orders_df.empty:
        orders_df["Created at"] = pd.to_datetime(orders_df["Created at"])
        max_date = orders_df["Created at"].max()
        cutoff = max_date - timedelta(days=3)
        recent = orders_df[orders_df["Created at"] >= cutoff]
        sales = recent.groupby("Design No")["Quantity"].sum().reset_index()
        for _, row in sales.iterrows():
            if row["Quantity"] > 10:
                reorder.append(row["Design No"])
            elif row["Quantity"] < 10:
                notselling.append(row["Design No"])
        st.write("### 🚀 Reorder Designs")
        st.table(pd.DataFrame({"Design No": reorder})) if reorder else st.info("No designs to reorder.")
        st.write("### 💤 Not Selling")
        st.table(pd.DataFrame({"Design No": notselling})) if notselling else st.info("All moving well.")

# Tab 4: Listed vs Non-Listed
with tab4:
    st.header("🛍️ Product Classification")
    shop_designs = set(shopify_df["Design No"].dropna().astype(str))
    warehouse_designs = set(warehouse_df["Design No"].dropna().astype(str))
    listed = warehouse_designs & shop_designs
    nonlisted = warehouse_designs - shop_designs

    st.metric("Listed", len(listed))
    st.metric("Non-Listed", len(nonlisted))
    st.write("✅ Listed Products")
    st.dataframe(warehouse_df[warehouse_df["Design No"].isin(listed)])
    st.write("📸 Photoshoot Required")
    st.dataframe(warehouse_df[warehouse_df["Design No"].isin(nonlisted)])

# Tab 5: Image Availability from Google Drive
with tab5:
    st.header("📷 Image Availability from Google Drive")
    designs = warehouse_df["Design No"].dropna().astype(str).tolist()
    service = build("drive", "v3", credentials=creds)
    results = []
    for design in designs:
        query = f"'{DRIVE_FOLDER_ID}' in parents and name contains '{design}' and trashed=false"
        resp = service.files().list(q=query, pageSize=1, fields="files(id, name)").execute()
        files = resp.get("files", [])
        if files:
            file_id = files[0]["id"]
            url = f"https://drive.google.com/uc?export=view&id={file_id}"
            status = "✅ Available"
        else:
            url = ""
            status = "❌ Missing"
        results.append({"Design No": design, "Image Status": status, "URL": url})
    st.dataframe(pd.DataFrame(results))
