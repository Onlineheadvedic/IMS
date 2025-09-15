import streamlit as st
import pandas as pd
from google.oauth2.service_account import Credentials
import gspread
from googleapiclient.discovery import build
from rapidfuzz import fuzz, process
from datetime import timedelta
import matplotlib.pyplot as plt

st.set_page_config(page_title="Inventory Dashboard", layout="wide")

# Load secrets
SERVICE_ACCOUNT_INFO = st.secrets["service_account"]
SPREADSHEET_ID = st.secrets["spreadsheet_id"]
DRIVE_FOLDER_ID = st.secrets["drive_folder_id"]
ADMIN_PASSWORD = st.secrets["admin_password"]
CLOUDINARY_CONFIG = st.secrets["cloudinary"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
gc = gspread.authorize(creds)

def fetch_sheet_df(sheet_name):
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(sheet_name)
    data = ws.get_all_values()
    if len(data) < 2:
        st.error(f"Sheet '{sheet_name}' is empty or missing header/data.")
        return pd.DataFrame()
    df = pd.DataFrame(data[1:], columns=data[0])
    return df

def fuzzy_best_match(query, choices, threshold=80):
    if not query:
        return None, 0
    if choices is None:
        choices = []
    try:
        choices = [str(c) for c in choices]
    except Exception:
        choices = []
    if len(choices) == 0:
        return None, 0
    result = process.extractOne(query, choices, scorer=fuzz.WRatio)
    if result and result[1] >= threshold:
        return result[0], result[1]
    return None, 0

role = "User"
if st.sidebar.checkbox("Admin Login"):
    pwd = st.sidebar.text_input("Enter Admin Password", type="password")
    if pwd == ADMIN_PASSWORD:
        role = "Admin"
        st.sidebar.success("Admin access granted.")
    else:
        st.sidebar.error("Wrong password. Access as User.")

shopify_df = fetch_sheet_df("Shopify")
warehouse_df = fetch_sheet_df("Warehouse")
ebo_df = fetch_sheet_df("EBO")
orders_df = fetch_sheet_df("Orders")

for df in (shopify_df, warehouse_df, ebo_df):
    if not df.empty:
        df["Design No"] = df["Design No"].astype(str).str.strip()
        df["Barcode"] = df["Barcode"].astype(str).str.strip()
        df["Closing Qty"] = pd.to_numeric(df["Closing Qty"], errors="coerce")

wh_total = warehouse_df["Closing Qty"].sum() if not warehouse_df.empty else 0
ebo_total = ebo_df["Closing Qty"].sum() if not ebo_df.empty else 0
shop_total = shopify_df["Closing Qty"].sum() if not shopify_df.empty else 0
overall_total = wh_total + ebo_total + shop_total

c1, c2, c3, c4 = st.columns(4)
c1.metric("Warehouse Qty", wh_total)
c2.metric("EBO Qty", ebo_total)
c3.metric("Shopify Qty", shop_total)
c4.metric("Total Inventory", overall_total)

tabs = st.tabs(["Inventory Overview", "Search", "Sales Trends", "Listed vs Non-listed", "Image Availability"])

with tabs[0]:
    st.subheader("Inventory Overview")
    cols = ["Design No", "Barcode", "Color", "Size", "Closing Qty"]
    if not warehouse_df.empty and not shopify_df.empty and not ebo_df.empty:
        ws_sum = warehouse_df[cols].groupby(["Design No", "Barcode"]).sum().reset_index()
        sh_sum = shopify_df[cols].groupby(["Design No", "Barcode"]).sum().reset_index()
        ebo_sum = ebo_df[cols].groupby(["Design No", "Barcode"]).sum().reset_index()
        merged = ws_sum.merge(sh_sum, on=["Design No", "Barcode"], how="outer", suffixes=('_Warehouse', '_Shopify'))
        merged = merged.merge(ebo_sum, on=["Design No", "Barcode"], how="outer")
        merged.rename(columns={"Closing Qty": "Closing Qty_EBO"}, inplace=True)
        merged.fillna(0, inplace=True)
        merged["Total Qty"] = merged[["Closing Qty_Warehouse", "Closing Qty_Shopify", "Closing Qty_EBO"]].sum(axis=1)
        st.dataframe(merged.sort_values("Total Qty", ascending=False).head(50))
        top20 = merged.sort_values("Total Qty", ascending=False).head(20)
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(top20["Design No"], top20["Total Qty"], color="skyblue")
        plt.xticks(rotation=45, ha="right")
        st.pyplot(fig)
    else:
        st.info("Some sheets are empty; cannot show merged inventory.")

with tabs[1]:
    st.subheader("Search Inventory")
    query = st.text_input("Search by Design No or Barcode")
    results = []
    threshold = 80
    for label, df in [("Warehouse", warehouse_df), ("Shopify", shopify_df), ("EBO", ebo_df)]:
        qty = 0
        if not df.empty:
            barcodes = df["Barcode"].unique()
            design_nos = df["Design No"].unique()
            if "Barcode" in df.columns and query in barcodes:
                qty = df[df["Barcode"] == query]["Closing Qty"].sum()
            else:
                match, score = fuzzy_best_match(query, design_nos, threshold)
                if match:
                    qty = df[df["Design No"] == match]["Closing Qty"].sum()
        results.append({"Source": label, "Qty": int(qty)})
    results.append({"Source": "Total", "Qty": sum(r["Qty"] for r in results)})
    st.table(pd.DataFrame(results))

    cdn_link = None
    if not shopify_df.empty and "CDN link" in shopify_df.columns:
        barcodes = shopify_df["Barcode"].unique()
        design_nos = shopify_df["Design No"].unique()
        if query in barcodes:
            cdn_link = shopify_df.loc[shopify_df["Barcode"] == query, "CDN link"].iloc[0]
        else:
            match, score = fuzzy_best_match(query, design_nos, threshold)
            if match:
                cdn_link = shopify_df.loc[shopify_df["Design No"] == match, "CDN link"].iloc[0]
    if cdn_link:
        st.image(cdn_link)
    else:
        st.info("No image found.")

with tabs[2]:
    st.subheader("Sales Trends (Last 3 days)")
    if not orders_df.empty:
        orders_df["Created at"] = pd.to_datetime(orders_df["Created at"])
        max_date = orders_df["Created at"].max()
        cutoff_date = max_date - timedelta(days=3)
        recent_orders = orders_df[orders_df["Created at"] >= cutoff_date]
        sales_summary = recent_orders.groupby("Design No")["Quantity"].sum().reset_index()
        sales_summary["Quantity"] = pd.to_numeric(sales_summary["Quantity"], errors="coerce")
        reorder = sales_summary[sales_summary["Quantity"] > 10]["Design No"].tolist()
        not_selling = sales_summary[sales_summary["Quantity"] < 10]["Design No"].tolist()
        st.write("### Designs to Reorder")
        if reorder:
            st.table(pd.DataFrame({"Design No": reorder}))
        else:
            st.info("No designs require reorder.")
        st.write("### Designs Not Selling")
        if not_selling:
            st.table(pd.DataFrame({"Design No": not_selling}))
        else:
            st.info("All designs are selling well.")
    else:
        st.info("No order data to analyze.")

with tabs[3]:
    st.subheader("Listed vs Non-listed Products (Robust Fuzzy Matching)")
    threshold = 80
    listed_idx = []
    non_listed_idx = []
    shopify_designs = list(shopify_df["Design No"].dropna().astype(str).unique()) if not shopify_df.empty else []
    if not warehouse_df.empty:
        for idx, row in warehouse_df.iterrows():
            design = str(row["Design No"]).strip()
            if shopify_designs:
                result = process.extractOne(design, shopify_designs, scorer=fuzz.WRatio)
                if result is not None:
                    match, score = result
                    if score >= threshold:
                        listed_idx.append(idx)
                    else:
                        non_listed_idx.append(idx)
                else:
                    non_listed_idx.append(idx)
            else:
                non_listed_idx.append(idx)
        st.metric("Listed Products", len(listed_idx))
        st.metric("Non-Listed Products", len(non_listed_idx))
        st.write("### Listed Products (Available Online)")
        st.dataframe(warehouse_df.iloc[listed_idx])
        st.write("### Non-Listed Products (Photoshoot Required)")
        st.dataframe(warehouse_df.iloc[non_listed_idx])
    else:
        st.info("Warehouse sheet is empty.")
with tab4:
    st.header("🛍️ Product Classification")

    if shopify_df is None:
        st.warning("Please upload the Shopify file first in Tab 1.")
    elif warehouse_df is None and ebo_df is None:
        st.warning("Please upload Warehouse and/or EBO files in Tabs 2 & 3.")
    else:
        # Collect Shopify identifiers
        shopify_designs = set(shopify_df["Design No"].astype(str).tolist())
        shopify_barcodes = set(shopify_df["Barcode"].astype(str).tolist())

        # Merge Warehouse + EBO into one dataframe
        external_df_list = []
        if warehouse_df is not None:
            external_df_list.append(warehouse_df[["Design No", "Barcode", "Closing Qty"]])
        if ebo_df is not None:
            external_df_list.append(ebo_df[["Design No", "Barcode", "Closing Qty"]])

        external_df = pd.concat(external_df_list, ignore_index=True).drop_duplicates()

        listed = []
        nonlisted = []

        for _, row in external_df.iterrows():
            d = str(row.get("Design No", ""))
            b = str(row.get("Barcode", ""))
            closing_qty = row.get("Closing Qty", 0)

            # ✅ Check exact match for Design No or Barcode
            if (d in shopify_designs) or (b in shopify_barcodes):
                listed.append({
                    "Design No": d,
                    "Barcode": b,
                    "Closing Qty": closing_qty,
                    "Match Type": "Exact"
                })
            else:
                # ✅ Fuzzy match on Design No if exact fails
                match_data = process.extractOne(d, shopify_designs)
                if match_data:
                    match, score = match_data[0], match_data[1]
                    if score >= 80:
                        listed.append({
                            "Design No": d,
                            "Barcode": b,
                            "Closing Qty": closing_qty,
                            "Match Type": f"Fuzzy ({score})"
                        })
                    else:
                        nonlisted.append({
                            "Design No": d,
                            "Barcode": b,
                            "Closing Qty": closing_qty
                        })
                else:
                    nonlisted.append({
                        "Design No": d,
                        "Barcode": b,
                        "Closing Qty": closing_qty
                    })

        # Convert to DataFrames
        listed_df = pd.DataFrame(listed)
        nonlisted_df = pd.DataFrame(nonlisted)

        # Metrics
        c1, c2 = st.columns(2)
        c1.metric("Listed Products", len(listed_df))
        c2.metric("Non-Listed Products", len(nonlisted_df))

        # Show listed
        st.write("### ✅ Listed Products (Matched with Shopify)")
        if not listed_df.empty:
            st.dataframe(listed_df)
        else:
            st.warning("No listed products found.")

        # Show non-listed (Photoshoot Required)
        st.write("### 📸 Photoshoot Required")
        st.info("These designs exist in Warehouse/EBO but are missing in Shopify. (Includes Closing Qty)")
        if not nonlisted_df.empty:
            st.dataframe(nonlisted_df)
        else:
            st.success("No products pending photoshoot.")
        import os

# 🔹 Configure your Google Drive folder path
image_folder = "/content/drive/MyDrive/ProductImages"

tab5 = st.tabs(["📷 Image Availability"])[0]

with tab5:
    st.header("📷 Check Image Availability from Google Drive")

    if warehouse_df is None:
        st.warning("Please upload the Warehouse file first.")
    else:
        if not os.path.exists(image_folder):
            st.error(f"Image folder not found: {image_folder}")
        else:
            # List all files in the folder
            drive_files = os.listdir(image_folder)

            availability = []
            for _, row in warehouse_df.iterrows():
                design_no = str(row.get("Design No", "")).strip()
                closing_qty = row.get("Closing Qty", 0)

                # Check if any file matches Design No
                matched_file = None
                for f in drive_files:
                    if design_no.lower() in f.lower():  # Case-insensitive match
                        matched_file = f
                        break

                if matched_file:
                    file_path = os.path.join(image_folder, matched_file)
                    availability.append({
                        "Design No": design_no,
                        "Closing Qty": closing_qty,
                        "Image Status": "✅ Available",
                        "Image File": f,
                        "File Path": file_path
                    })
                else:
                    availability.append({
                        "Design No": design_no,
                        "Closing Qty": closing_qty,
                        "Image Status": "❌ Not Available",
                        "Image File": "",
                        "File Path": ""
                    })

            # Convert to DataFrame
            availability_df = pd.DataFrame(availability)

            st.write("### Image Availability Status")
            st.dataframe(availability_df)

            # ✅ Option: Show only missing images
            missing = availability_df[availability_df["Image Status"] == "❌ Not Available"]
            if not missing.empty:
                st.warning("Missing images for these designs:")
                st.table(missing[["Design No", "Closing Qty"]])




