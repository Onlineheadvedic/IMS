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
    df = pd.DataFrame(data[1:], columns=data[0])

    # Normalize columns: strip spaces, lower case, remove internal spaces for matching
    def normalize_col(col):
        return str(col).strip().lower().replace(' ', '')

    df.columns = [normalize_col(col) for col in df.columns]

    if req_cols:
        req_cols_norm = [normalize_col(c) for c in req_cols]
        missing = [c for c in req_cols_norm if c not in df.columns]
        if missing:
            st.error(f"{label} is missing required columns: {missing}")
            return None

    # Map normalized column names back to the actual columns for use
    col_map = {normalize_col(col): col for col in data[0]}

    # Rename dataframe columns to normalized names for consistent access
    df.rename(columns={col_map[nc]: nc for nc in col_map}, inplace=True)

    # Cast types using normalized column names
    if "designno" in df.columns:
        df["designno"] = df["designno"].astype(str)
    if "barcode" in df.columns:
        df["barcode"] = df["barcode"].astype(str)
    if "closingqty" in df.columns:
        df["closingqty"] = pd.to_numeric(df["closingqty"], errors="coerce").fillna(0).astype(int)
    if "quantity" in df.columns:
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
    if "createdat" in df.columns:
        df["createdat"] = pd.to_datetime(df["createdat"], errors="coerce")

    return df

def fuzzy_best_match(query, choices):
    if not query or not len(choices):
        return None, 0
    match = process.extractOne(query, choices, scorer=fuzz.WRatio)
    if match:
        return match[0], match[1]
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
wh_total = warehouse_df["closingqty"].sum() if warehouse_df is not None else 0
ebo_total = ebo_df["closingqty"].sum() if ebo_df is not None else 0
shop_total = shopify_df["closingqty"].sum() if shopify_df is not None else 0
overall_total = wh_total + ebo_total + shop_total
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Warehouse Qty", wh_total)
col2.metric("EBO Qty", ebo_total)
col3.metric("Shopify Qty", shop_total)
col4.metric("Overall Qty", overall_total)

# ---- Sales Trends (Reorder / Not Selling) ----
reorder_designs, notselling_designs = [], []
if orders_df is not None:
    max_date = orders_df["createdat"].max()
    if pd.notnull(max_date):
        cutoff = max_date - timedelta(days=3)
        recent = orders_df[orders_df["createdat"] >= cutoff]
        sales = recent.groupby("designno")["quantity"].sum().reset_index()
        for _, row in sales.iterrows():
            if row["quantity"] > 10:
                reorder_designs.append(row["designno"])
            elif row["quantity"] < 10:
                notselling_designs.append(row["designno"])
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
    if warehouse_df is not None or shopify_df is not None or ebo_df is not None:
        dfs = []
        for label, df in [("Warehouse", warehouse_df), ("Shopify", shopify_df), ("EBO", ebo_df)]:
            if df is not None:
                for col in ["size"]:
                    if col not in df.columns:
                        df[col] = ""
                agg = df.groupby(["designno", "barcode", "size"], dropna=False)["closingqty"].sum().reset_index()
                agg.rename(columns={"closingqty": f"{label}_Qty"}, inplace=True)
                dfs.append(agg)
        merged = dfs[0]
        for other in dfs[1:]:
            merged = merged.merge(other, on=["designno", "barcode", "size"], how="outer")
        for col in ["Warehouse_Qty", "Shopify_Qty", "EBO_Qty"]:
            if col not in merged.columns:
                merged[col] = 0
        merged = merged.fillna(0)
        qty_cols = [c for c in merged.columns if c.endswith("_Qty")]
        merged["Total_QTY"] = merged[qty_cols].sum(axis=1)

        photo_urls = []
        designs = merged["designno"].astype(str).tolist()
        if DRIVE_FOLDER_ID:
            service = build("drive", "v3", credentials=creds)
            for design in designs:
                query = f"'{DRIVE_FOLDER_ID}' in parents and trashed=false"
                resp = service.files().list(q=query, fields="files(id, name)", pageSize=1000).execute()
                files = resp.get("files", [])
                found = False
                for file in files:
                    name_score = fuzz.WRatio(design, file["name"])
                    if name_score >= 90:
                        photo_urls.append(f"https://drive.google.com/uc?export=view&id={file['id']}")
                        found = True
                        break
                if not found:
                    for file in files:
                        if str(design) in file["name"]:
                            photo_urls.append(f"https://drive.google.com/uc?export=view&id={file['id']}")
                            found = True
                            break
                if not found:
                    photo_urls.append(None)
        else:
            photo_urls = [None for _ in designs]

        if shopify_df is not None:
            barcode_to_cdn = dict(zip(shopify_df["barcode"], shopify_df["cdnlink"]))
        else:
            barcode_to_cdn = {}

        display_rows = []
        for idx, row in merged.iterrows():
            img_url = photo_urls[idx] if photo_urls and photo_urls[idx] else None
            if not img_url and shopify_df is not None:
                bc = str(row["barcode"])
                img_url = barcode_to_cdn.get(bc, None)
            display_rows.append({
                "PHOTO": img_url,
                "DESIGN NO": str(row["designno"]),
                "BARCODE": str(row["barcode"]),
                "SIZE": str(row["size"]),
                "WAREHOUSE QTY": int(row["Warehouse_Qty"]),
                "SHOPIFY QTY": int(row["Shopify_Qty"]),
                "EBO QTY": int(row["EBO_Qty"]),
                "TOTAL QTY": int(row["Total_QTY"]),
            })

        display_rows_sorted = sorted(display_rows, key=lambda x: -x["TOTAL QTY"])
        final_df = pd.DataFrame(display_rows_sorted)
        st.write("### Inventory Table (by Design/Barcode/Size)")
        for i, row in final_df.iterrows():
            cols = st.columns([1,2,2,1,2,2,2])
            if row["PHOTO"]:
                cols[0].image(row["PHOTO"], width=60)
            else:
                cols[0].empty()
            cols[1].write(row["DESIGN NO"])
            cols[2].write(row["BARCODE"])
            cols[3].write(row["SIZE"])
            cols[4].write(row["WAREHOUSE QTY"])
            cols[5].write(row["SHOPIFY QTY"])
            cols[6].write(row["EBO QTY"])

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
                if "barcode" in df.columns and query in df["barcode"].values:
                    qty = df[df["barcode"] == query]["closingqty"].sum()
                else:
                    match, score = fuzzy_best_match(query, df["designno"].unique())
                    if match:
                        qty = df[df["designno"] == match]["closingqty"].sum()
            results.append({"Source": label, "Qty": int(qty)})
        total = sum(r["Qty"] for r in results)
        results.append({"Source": "Total", "Qty": total})
        st.table(pd.DataFrame(results))
        cdn = None
        if shopify_df is not None:
            if "barcode" in shopify_df.columns and query in shopify_df["barcode"].values:
                cdn = shopify_df.loc[shopify_df["barcode"] == query, "cdnlink"].iloc[0]
            else:
                match, _ = fuzzy_best_match(query, shopify_df["designno"].unique())
                if match:
                    cdn = shopify_df.loc[shopify_df["designno"] == match, "cdnlink"].iloc[0]
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
        shopify_designs = set(shopify_df["designno"].astype(str).tolist())
        shopify_barcodes = set(shopify_df["barcode"].astype(str).tolist())
        external_df_list = []
        if warehouse_df is not None:
            external_df_list.append(warehouse_df[["designno", "barcode", "closingqty"]])
        if ebo_df is not None:
            external_df_list.append(ebo_df[["designno", "barcode", "closingqty"]])
        external_df = pd.concat(external_df_list, ignore_index=True).drop_duplicates()
        listed = []
        nonlisted = []
        for _, row in external_df.iterrows():
            d = str(row.get("designno", ""))
            b = str(row.get("barcode", ""))
            closing_qty = row.get("closingqty", 0)
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
tab5 = st.tabs(["📷 Image Availability"])[0]
with tab5:
    st.header("📷 Check Image Availability from Google Drive")
    if warehouse_df is None or warehouse_df.empty or not DRIVE_FOLDER_ID:
        st.warning("Warehouse sheet/Drive folder missing.")
    else:
        service = build("drive", "v3", credentials=creds)
        designs = warehouse_df["designno"].dropna().astype(str).unique()
        image_data = []
        for design in designs:
            query = f"'{DRIVE_FOLDER_ID}' in parents and name contains '{design}' and trashed=false"
            try:
                response = service.files().list(q=query, pageSize=1, fields="files(id, name)").execute()
                files = response.get("files", [])
                if files:
                    file_id = files[0]["id"]
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
        missing = availability_df[availability_df["Image Status"] == "❌ Not Available"]
        if not missing.empty:
            st.warning("Missing images for these designs:")
            st.table(missing[["Design No"]])
