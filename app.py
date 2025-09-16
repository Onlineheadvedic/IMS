import streamlit as st
import pandas as pd
from google.oauth2.service_account import Credentials
import gspread
from rapidfuzz import fuzz, process
from datetime import timedelta
import matplotlib.pyplot as plt
from googleapiclient.discovery import build

st.set_page_config(page_title="Inventory Dashboard", layout="wide")

# Load secrets
SERVICE_ACCOUNT_INFO = st.secrets["service_account"]
SPREADSHEET_ID = st.secrets["spreadsheet_id"]
DRIVE_FOLDER_ID = st.secrets.get("drive_folder_id")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
gc = gspread.authorize(creds)

# ---- Helpers for Google Sheets ----
def fetch_sheet_df(sheet_name, req_cols=None, label=""):
    try:
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(sheet_name)
        data = ws.get_all_values()
    except Exception as e:
        st.error(f"Error fetching '{sheet_name}': {e}")
        return None
    if len(data) < 2:
        st.error(f"Sheet '{sheet_name}' is empty or missing header/data.")
        return None
    df = pd.DataFrame(data[1:], columns=data)
    df.columns = df.columns.str.strip()
    if req_cols:
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

def fuzzy_best_match(query, choices):
    if not query or not len(choices):
        return None, 0
    match = process.extractOne(query, choices, scorer=fuzz.WRatio)
    if match:
        return match, match[1]
    return None, 0

# ---- Required Sheets ----
REQ_SHOPIFY = ["Barcode", "Design No", "Closing Qty", "CDN link"]
REQ_WAREHOUSE = ["Barcode", "Design No", "Closing Qty"]
REQ_EBO = ["Barcode", "Design No", "Closing Qty"]
REQ_ORDERS = ["Design No", "Quantity", "Created at"]

# ---- Load from Google Sheets ----
shopify_df = fetch_sheet_df("Shopify", REQ_SHOPIFY, "Shopify")
warehouse_df = fetch_sheet_df("Warehouse", REQ_WAREHOUSE, "Warehouse")
ebo_df = fetch_sheet_df("EBO", REQ_EBO, "EBO")
orders_df = fetch_sheet_df("Orders", REQ_ORDERS, "Orders")

st.title("📦 Inventory Dashboard — Shopify + Warehouse + EBO")

# ---- Key Metrics ----
wh_total = warehouse_df["Closing Qty"].sum() if warehouse_df is not None else 0
ebo_total = ebo_df["Closing Qty"].sum() if ebo_df is not None else 0
shop_total = shopify_df["Closing Qty"].sum() if shopify_df is not None else 0
overall_total = wh_total + ebo_total + shop_total
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Warehouse Qty", wh_total)
col2.metric("EBO Qty", ebo_total)
col3.metric("Shopify Qty", shop_total)
col4.metric("Overall Qty", overall_total)

# ---- Sales Trends (Reorder / Not Selling) ----
reorder_designs, notselling_designs = [], []
if orders_df is not None:
    max_date = orders_df["Created at"].max()
    if pd.notnull(max_date):
        cutoff = max_date - timedelta(days=3)
        recent = orders_df[orders_df["Created at"] >= cutoff]
        sales = recent.groupby("Design No")["Quantity"].sum().reset_index()
        for _, row in sales.iterrows():
            if row["Quantity"] > 10:
                reorder_designs.append(row["Design No"])
            elif row["Quantity"] < 10:
                notselling_designs.append(row["Design No"])
col5.metric("Reorder Designs (sales > 10, last 3d)", len(reorder_designs))
col6.metric("Not Selling (sales < 10, last 3d)", len(notselling_designs))

# ---- Tabs ----
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Inventory Overview",
    "🔍 Search",
    "📈 Sales Trends",
    "📂 Listed vs Non-Listed"
])

# ---- Inventory Overview Tab ----
with tab1:
    st.subheader("Inventory Overview")
    # Only proceed if at least one source is present
    if warehouse_df is not None or shopify_df is not None or ebo_df is not None:
        # Build unified inventory table per Design No / Barcode / Size
        dfs = []
        for label, df in [("Warehouse", warehouse_df), ("Shopify", shopify_df), ("EBO", ebo_df)]:
            if df is not None:
                for col in ["Size"]:
                    if col not in df.columns:
                        df[col] = ""
                agg = df.groupby(["Design No", "Barcode", "Size"], dropna=False)["Closing Qty"].sum().reset_index()
                agg.rename(columns={"Closing Qty": f"{label}_Qty"}, inplace=True)
                dfs.append(agg)
        # Merge all sources
        merged = dfs
        for other in dfs[1:]:
            merged = merged.merge(other, on=["Design No", "Barcode", "Size"], how="outer")
        for col in ["Warehouse_Qty", "Shopify_Qty", "EBO_Qty"]:
            if col not in merged.columns:
                merged[col] = 0
        merged = merged.fillna(0)
        qty_cols = [c for c in merged.columns if c.endswith("_Qty")]
        merged["Total_QTY"] = merged[qty_cols].sum(axis=1)

        # ---- Image Lookup ----
        # Prepare file lookup from Google Drive
        photo_urls = []
        designs = merged["Design No"].astype(str).tolist()
        if DRIVE_FOLDER_ID:
            service = build("drive", "v3", credentials=creds)
            drive_files = {}
            for design in designs:
                # Use fuzzy matching
                query = f"'{DRIVE_FOLDER_ID}' in parents and trashed=false"
                resp = service.files().list(q=query, fields="files(id, name)", pageSize=1000).execute()
                files = resp.get("files", [])
                found = False
                for file in files:
                    name_score = fuzz.WRatio(design, file["name"])
                    if name_score >= 90:  # strict match
                        photo_urls.append(f"https://drive.google.com/uc?export=view&id={file['id']}")
                        found = True
                        break
                if not found:
                    # Fallback: look for name containing design number
                    for file in files:
                        if str(design) in file["name"]:
                            photo_urls.append(f"https://drive.google.com/uc?export=view&id={file['id']}")
                            found = True
                            break
                if not found:
                    photo_urls.append(None)
        else:
            photo_urls = [None for _ in designs]

        # Fallback to Shopify CDN if missing
        if shopify_df is not None:
            barcode_to_cdn = dict(zip(shopify_df["Barcode"], shopify_df["CDN link"]))
        else:
            barcode_to_cdn = {}

        display_rows = []
        for idx, row in merged.iterrows():
            img_url = photo_urls[idx] if photo_urls and photo_urls[idx] else None
            if not img_url and shopify_df is not None:
                # Try to match by barcode to CDN link
                bc = str(row["Barcode"])
                img_url = barcode_to_cdn.get(bc, None)
            # Compose display row
            display_rows.append({
                "PHOTO": img_url,
                "DESIGN NO": str(row["Design No"]),
                "BARCODE": str(row["Barcode"]),
                "SIZE": str(row["Size"]),
                "WAREHOUSE QTY": int(row["Warehouse_Qty"]),
                "SHOPIFY QTY": int(row["Shopify_Qty"]),
                "EBO QTY": int(row["EBO_Qty"]),
                "TOTAL QTY": int(row["Total_QTY"]),
            })

        # Sort by Total Qty
        display_rows_sorted = sorted(display_rows, key=lambda x: -x["TOTAL QTY"])
        final_df = pd.DataFrame(display_rows_sorted)
        st.write("### Inventory Table (by Design/Barcode/Size)")
        def custom_photo(x):
            if x:
                st.image(x, width=50)
            else:
                st.text("No Image")
        # Streamlit can't use df.style for images, so render per row
        for i, row in final_df.iterrows():
            cols = st.columns([1,2,2,1,2,2,2])
            if row["PHOTO"]:
                cols.image(row["PHOTO"], width=60)
            else:
                cols.empty()
            cols[1].write(row["DESIGN NO"])
            cols.write(row["BARCODE"])
            cols.write(row["SIZE"])
            cols.write(row["WAREHOUSE QTY"])
            cols.write(row["SHOPIFY QTY"])
            cols.write(row["EBO QTY"])

        # Top 20 Designs by Inventory
        st.subheader("Top 20 Designs by Inventory")
        top20 = final_df.head(20)
        fig, ax = plt.subplots(figsize=(10,5))
        ax.bar(top20["DESIGN NO"], top20["TOTAL QTY"], color="skyblue")
        ax.set_xlabel("Design No")
        ax.set_ylabel("Total Inventory")
        ax.set_title("Top 20 Designs by Inventory")
        plt.xticks(rotation=45, ha="right")
        st.pyplot(fig)

# ---- Search Tab ----
with tab2:
    st.subheader("Search by Design No or Barcode")
    query = st.text_input("Enter Design No or Barcode")
    if query:
        results = []
        for label, df in [("Warehouse", warehouse_df), ("Shopify", shopify_df), ("EBO", ebo_df)]:
            qty = 0
            if df is not None:
                if "Barcode" in df.columns and query in df["Barcode"].values:
                    qty = df[df["Barcode"] == query]["Closing Qty"].sum()
                else:
                    match, score = fuzzy_best_match(query, df["Design No"].unique())
                    if match:
                        qty = df[df["Design No"] == match]["Closing Qty"].sum()
            results.append({"Source": label, "Qty": int(qty)})
        total = sum(r["Qty"] for r in results)
        results.append({"Source": "Total", "Qty": total})
        st.table(pd.DataFrame(results))
        # Show CDN image
        cdn = None
        if shopify_df is not None:
            if "Barcode" in shopify_df.columns and query in shopify_df["Barcode"].values:
                cdn = shopify_df.loc[shopify_df["Barcode"] == query, "CDN link"].iloc
            else:
                match, _ = fuzzy_best_match(query, shopify_df["Design No"].unique())
                if match:
                    cdn = shopify_df.loc[shopify_df["Design No"] == match, "CDN link"].iloc
        if cdn:
            st.image(cdn, caption=f"Design {query}")
        else:
            st.warning("No CDN link found in Shopify for this design.")

# ---- Sales Trends Tab ----
with tab3:
    st.subheader("📈 Sales Trends (last 3 days)")
    if orders_df is not None:
        st.write("### 🚀 Reorder Designs (sales > 10)")
        if reorder_designs:
            st.table(pd.DataFrame({"Design No": reorder_designs}))
        else:
            st.info("No designs require reorder.")
        st.write("### 💤 Not Selling (sales < 10)")
        if notselling_designs:
            st.table(pd.DataFrame({"Design No": notselling_designs}))
        else:
            st.info("No non-moving designs detected.")
    else:
        st.warning("Order data missing.")

# ---- Listed vs Non-Listed Tab ----
with tab4:
    st.header("🛍️ Product Classification")
    if shopify_df is None:
        st.warning("Shopify sheet missing.")
    elif warehouse_df is None and ebo_df is None:
        st.warning("Warehouse/EBO sheets missing.")
    else:
        shopify_designs = set(shopify_df["Design No"].astype(str).tolist())
        shopify_barcodes = set(shopify_df["Barcode"].astype(str).tolist())
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
            if (d in shopify_designs) or (b in shopify_barcodes):
                listed.append({
                    "Design No": d,
                    "Barcode": b,
                    "Closing Qty": closing_qty,
                    "Match Type": "Exact"
                })
            else:
                match_data = process.extractOne(d, shopify_designs)
                if match_data:
                    match, score = match_data, match_data[1]
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
        listed_df = pd.DataFrame(listed)
        nonlisted_df = pd.DataFrame(nonlisted)
        c1, c2 = st.columns(2)
        c1.metric("Listed Products", len(listed_df))
        c2.metric("Non-Listed Products", len(nonlisted_df))
        st.write("### ✅ Listed Products (Matched with Shopify)")
        if not listed_df.empty:
            st.dataframe(listed_df)
        else:
            st.warning("No listed products found.")
        st.write("### 📸 Photoshoot Required")
        st.info("These designs exist in Warehouse/EBO but are missing in Shopify. (Includes Closing Qty)")
        if not nonlisted_df.empty:
            st.dataframe(nonlisted_df)
        else:
            st.success("No products pending photoshoot.")

# ---- Image Availability Tab ----
tab5 = st.tabs(["📷 Image Availability"])
with tab5:
    st.header("📷 Check Image Availability from Google Drive")
    if warehouse_df is None or warehouse_df.empty or not DRIVE_FOLDER_ID:
        st.warning("Warehouse sheet/Drive folder missing.")
    else:
        service = build("drive", "v3", credentials=creds)
        designs = warehouse_df["Design No"].dropna().astype(str).unique()
        image_data = []
        for design in designs:
            query = f"'{DRIVE_FOLDER_ID}' in parents and name contains '{design}' and trashed=false"
            try:
                response = service.files().list(q=query, pageSize=1, fields="files(id, name)").execute()
                files = response.get("files", [])
                if files:
                    file_id = files["id"]
                    url = f"https://drive.google.com/uc?export=view&id={file_id}"
                    status = "✅ Available"
                else:
                    url = ""
                    status = "❌ Not Available"
            except Exception as e:
                url = ""
                status = f"❌ Error: {e}"
            image_data.append({"Design No": design, "Image Status": status, "Image URL": url})
        availability_df = pd.DataFrame(image_data)
        st.write("### Image Availability Status")
        st.dataframe(availability_df)
        # Optionally show missing images only
        missing = availability_df[availability_df["Image Status"] == "❌ Not Available"]
        if not missing.empty:
            st.warning("Missing images for these designs:")
            st.table(missing[["Design No"]])
