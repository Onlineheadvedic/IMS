import pandas as pd
import streamlit as st
from rapidfuzz import fuzz, process
from datetime import timedelta
import matplotlib.pyplot as plt
import os

# 🔹 Cloudinary
import cloudinary
import cloudinary.api
import cloudinary.uploader

# ================================
# CONFIG
# ================================
st.set_page_config(page_title="Inventory Dashboard", layout="wide")

# ✅ Setup Cloudinary config (securely from secrets)
cloudinary.config(
    cloud_name=st.secrets["cloudinary"]["cloud_name"],
    api_key=st.secrets["cloudinary"]["api_key"],
    api_secret=st.secrets["cloudinary"]["api_secret"],
    secure=True
)

# ================================
# ROLE SELECTION WITH PASSWORD
# ================================
role_choice = st.sidebar.radio("Select View", ["User", "Admin"])

# ✅ Setup Admin Passwords
admin.config(
    ADMIN_PASSWORD = st.secrets["admin_password"]
)

if role_choice == "Admin":
    pwd = st.sidebar.text_input("Enter Admin Password", type="password")
    if pwd == ADMIN_PASSWORD:   # ✅ Check against Streamlit secrets
        role = "Admin"
        st.sidebar.success("✅ Admin access granted")
    else:
        st.sidebar.error("❌ Incorrect password. Falling back to User view.")
        role = "User"
else:
    role = "User"

# Required Columns
REQ_SHOPIFY = ["Barcode", "Design No", "Closing Qty", "CDN link"]
REQ_WAREHOUSE = ["Barcode", "Design No", "Closing Qty"]
REQ_EBO = ["Barcode", "Design No", "Closing Qty"]
REQ_ORDERS = ["Design No", "Quantity", "Created at"]


# Helpers
def fuzzy_best_match(query, choices):
    if not query or not len(choices):
        return None, 0
    match = process.extractOne(query, choices, scorer=fuzz.WRatio)
    if match:
        return match[0], match[1]
    return None, 0


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


# ================================
# FILE UPLOADS (ADMIN ONLY)
# ================================
if role == "Admin":
    st.sidebar.header("Upload Data")

    shopify_file = st.sidebar.file_uploader("Shopify Inventory", type=["csv", "xlsx"])
    warehouse_file = st.sidebar.file_uploader("Warehouse Inventory", type=["csv", "xlsx"])
    ebo_file = st.sidebar.file_uploader("EBO Inventory", type=["csv", "xlsx"])
    orders_file = st.sidebar.file_uploader("Shopify Orders", type=["csv", "xlsx"])

    shopify_df = load_file(shopify_file, REQ_SHOPIFY, "Shopify")
    warehouse_df = load_file(warehouse_file, REQ_WAREHOUSE, "Warehouse")
    ebo_df = load_file(ebo_file, REQ_EBO, "EBO")
    orders_df = load_file(orders_file, REQ_ORDERS, "Orders")

    # ✅ Save uploaded data in session_state so users can see it
    st.session_state["shopify_df"] = shopify_df
    st.session_state["warehouse_df"] = warehouse_df
    st.session_state["ebo_df"] = ebo_df
    st.session_state["orders_df"] = orders_df

else:  # USER MODE
    # ✅ Load data from session_state (uploaded earlier by admin)
    shopify_df = st.session_state.get("shopify_df")
    warehouse_df = st.session_state.get("warehouse_df")
    ebo_df = st.session_state.get("ebo_df")
    orders_df = st.session_state.get("orders_df")

    if not any([shopify_df is not None, warehouse_df is not None, ebo_df is not None]):
        st.warning("⚠️ No data available. Please ask Admin to upload files.")
        st.stop()

# ================================
# DASHBOARD (COMMON FOR BOTH)
# ================================
st.title("📦 Inventory Dashboard — Shopify + Warehouse + EBO")

# Key Metrics
wh_total = warehouse_df["Closing Qty"].sum() if warehouse_df is not None else 0
ebo_total = ebo_df["Closing Qty"].sum() if ebo_df is not None else 0
shop_total = shopify_df["Closing Qty"].sum() if shopify_df is not None else 0
overall_total = wh_total + ebo_total + shop_total

col1, col2, col3, col4 = st.columns(4)
col1.metric("Warehouse Qty", wh_total)
col2.metric("EBO Qty", ebo_total)
col3.metric("Shopify Qty", shop_total)
col4.metric("Overall Qty", overall_total)

# ================================
# EXISTING TABS (Unchanged)
# ================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Inventory Overview", "🔍 Search", "📈 Sales Trends",
    "📂 Listed vs Non-Listed", "📷 Image Availability"
])

# -----------------
# Tab 1 — Overview
# -----------------
with tab1:
    if shopify_df is not None or warehouse_df is not None or ebo_df is not None:
        st.subheader("Inventory Overview")
        combined = []
        for label, df in [("Warehouse", warehouse_df), ("Shopify", shopify_df), ("EBO", ebo_df)]:
            if df is not None and "Closing Qty" in df.columns:
                agg = df.groupby(["Design No", "Barcode"], dropna=False)["Closing Qty"].sum().reset_index()
                agg.rename(columns={"Closing Qty": f"{label}_Qty"}, inplace=True)
                combined.append(agg)

        if combined:
            merged = combined[0]
            for part in combined[1:]:
                merged = merged.merge(part, on=["Design No", "Barcode"], how="outer")
            merged = merged.fillna(0)

            qty_cols = [c for c in merged.columns if c.endswith("_Qty")]
            merged["Total_QTY"] = merged[qty_cols].sum(axis=1)

            st.dataframe(merged.sort_values("Total_QTY", ascending=False).head(50))

            # Chart
            st.subheader("Top 20 Designs by Inventory")
            top20 = merged.sort_values("Total_QTY", ascending=False).head(20)
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.bar(top20["Design No"], top20["Total_QTY"], color="skyblue")
            plt.xticks(rotation=45, ha="right")
            st.pyplot(fig)

# -----------------
# Tab 2 — Search
# -----------------
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
        results.append({"Source": "Total", "Qty": sum(r["Qty"] for r in results)})
        st.table(pd.DataFrame(results))

        # CDN Image
        if shopify_df is not None and "CDN link" in shopify_df.columns:
            cdn = None
            if "Barcode" in shopify_df.columns and query in shopify_df["Barcode"].values:
                cdn = shopify_df.loc[shopify_df["Barcode"] == query, "CDN link"].iloc[0]
            else:
                match, _ = fuzzy_best_match(query, shopify_df["Design No"].unique())
                if match:
                    cdn = shopify_df.loc[shopify_df["Design No"] == match, "CDN link"].iloc[0]
            if cdn:
                st.image(cdn, caption=f"Design {query}")
            else:
                st.warning("No CDN link found.")

# -----------------
# Tab 3 — Sales Trends
# -----------------
with tab3:
    st.subheader("📈 Sales Trends (last 3 days)")
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

        st.write("### 🚀 Reorder Designs")
        st.table(pd.DataFrame({"Design No": reorder_designs})) if reorder_designs else st.info("No designs to reorder.")

        st.write("### 💤 Not Selling")
        st.table(pd.DataFrame({"Design No": notselling_designs})) if notselling_designs else st.info("All moving well.")

# -----------------
# Tab 4 — Listed vs Non-Listed
# -----------------
with tab4:
    st.header("🛍️ Product Classification")
    if shopify_df is not None and (warehouse_df is not None or ebo_df is not None):
        shopify_designs = set(shopify_df["Design No"].astype(str).tolist())
        external_df_list = []
        if warehouse_df is not None:
            external_df_list.append(warehouse_df[["Design No", "Barcode", "Closing Qty"]])
        if ebo_df is not None:
            external_df_list.append(ebo_df[["Design No", "Barcode", "Closing Qty"]])
        external_df = pd.concat(external_df_list, ignore_index=True).drop_duplicates()

        listed, nonlisted = [], []
        for _, row in external_df.iterrows():
            d = str(row["Design No"])
            if d in shopify_designs:
                listed.append(row)
            else:
                nonlisted.append(row)

        st.metric("Listed", len(listed))
        st.metric("Non-Listed", len(nonlisted))

        if listed:
            st.write("✅ Listed Products")
            st.dataframe(pd.DataFrame(listed))
        if nonlisted:
            st.write("📸 Photoshoot Required")
            st.dataframe(pd.DataFrame(nonlisted))

# -----------------
# Tab 5 — Image Availability
# -----------------
with tab5:
    st.header("📷 Image Availability from Cloudinary")
    if warehouse_df is not None:
        try:
            cloud_files = cloudinary.api.resources(type="upload", max_results=500)["resources"]
            file_map = {res["public_id"].lower(): res["secure_url"] for res in cloud_files}
            availability = []
            for _, row in warehouse_df.iterrows():
                design = str(row["Design No"]).lower()
                qty = row["Closing Qty"]
                matched_url = None
                for pid, url in file_map.items():
                    if design in pid:
                        matched_url = url
                        break
                availability.append({
                    "Design No": design,
                    "Closing Qty": qty,
                    "Image Status": "✅ Available" if matched_url else "❌ Missing",
                    "URL": matched_url or ""
                })
            st.dataframe(pd.DataFrame(availability))
        except Exception as e:
            st.error(f"Cloudinary API error: {e}")
