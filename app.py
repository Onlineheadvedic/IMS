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

# ✅ Setup Cloudinary config (Replace with your credentials)
cloudinary.config(
    cloud_name = "dc5dywe6s",
    api_key = "659391858798484",
    api_secret = "aOHsSN8tXHI7JuHzBLqZ7DS3Zx4",
    secure=True
)

# Required Columns
REQ_SHOPIFY = ["Barcode", "Design No", "Closing Qty", "CDN link"]
REQ_WAREHOUSE = ["Barcode", "Design No", "Closing Qty"]
REQ_EBO = ["Barcode", "Design No", "Closing Qty"]
REQ_ORDERS = ["Design No", "Quantity", "Created at"]  # 🔹 Orders do not have Barcode


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


# Sidebar Uploads
st.sidebar.header("Upload Data")
shopify_file = st.sidebar.file_uploader("Shopify Inventory", type=["csv", "xlsx"])
warehouse_file = st.sidebar.file_uploader("Warehouse Inventory", type=["csv", "xlsx"])
ebo_file = st.sidebar.file_uploader("EBO Inventory", type=["csv", "xlsx"])
orders_file = st.sidebar.file_uploader("Shopify Orders", type=["csv", "xlsx"])


# Load
shopify_df = load_file(shopify_file, REQ_SHOPIFY, "Shopify")
warehouse_df = load_file(warehouse_file, REQ_WAREHOUSE, "Warehouse")
ebo_df = load_file(ebo_file, REQ_EBO, "EBO")
orders_df = load_file(orders_file, REQ_ORDERS, "Orders")


# Dashboard Title
st.title("📦 Inventory Dashboard — Shopify + Warehouse + EBO")


# Key Metrics
wh_total = warehouse_df["Closing Qty"].sum() if warehouse_df is not None else 0
ebo_total = ebo_df["Closing Qty"].sum() if ebo_df is not None else 0
shop_total = shopify_df["Closing Qty"].sum() if shopify_df is not None else 0
overall_total = wh_total + ebo_total + shop_total

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Warehouse Qty", wh_total)
col2.metric("EBO Qty", ebo_total)
col3.metric("Shopify Qty", shop_total)
col4.metric("Overall Qty", overall_total)

# -----------------------------
# (Existing tabs unchanged…)
# -----------------------------
tab1, tab2, tab3, tab4 = st.tabs(["📊 Inventory Overview", "🔍 Search", "📈 Sales Trends", "📂 Listed vs Non-Listed"])

# Inventory Overview
with tab1:
    if shopify_df is not None or warehouse_df is not None or ebo_df is not None:
        st.subheader("Inventory Overview")
        combined = []
        for label, df in [("Warehouse", warehouse_df), ("Shopify", shopify_df), ("EBO", ebo_df)]:
            if df is not None:
                # Keep extra columns (Barcode, Color, Size) along with qty
                agg = df.groupby(["Design No", "Barcode", "Color", "Size"], dropna=False)["Closing Qty"].sum().reset_index()
                agg.rename(columns={"Closing Qty": f"{label}_Qty"}, inplace=True)
                combined.append(agg)

        if combined:
            # Merge all sources on Design No, Barcode, Color, Size
            merged = combined[0]
            for part in combined[1:]:
                merged = merged.merge(part, on=["Design No", "Barcode", "Color", "Size"], how="outer")

            merged = merged.fillna(0)

            # Calculate total qty
            qty_cols = [c for c in merged.columns if c.endswith("_Qty")]
            merged["Total_QTY"] = merged[qty_cols].sum(axis=1)

            # Show table
            st.dataframe(
                merged[["Design No", "Barcode", "Color", "Size"] + qty_cols + ["Total_QTY"]]
                .sort_values("Total_QTY", ascending=False)
                .head(50)
            )

            # 🔹 Graph: Top 20 Designs by Inventory
            st.subheader("Top 20 Designs by Inventory")
            top20 = merged.sort_values("Total_QTY", ascending=False).head(20)
            fig, ax = plt.subplots(figsize=(10,5))
            ax.bar(top20["Design No"], top20["Total_QTY"], color="skyblue")
            ax.set_xlabel("Design No")
            ax.set_ylabel("Total Inventory")
            ax.set_title("Top 20 Designs by Inventory")
            plt.xticks(rotation=45, ha="right")
            st.pyplot(fig)


# Search
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


        # Show CDN image (unchanged)
        if shopify_df is not None:
            if "Barcode" in shopify_df.columns and query in shopify_df["Barcode"].values:
                cdn = shopify_df.loc[shopify_df["Barcode"] == query, "CDN link"].iloc[0]
            else:
                match, _ = fuzzy_best_match(query, shopify_df["Design No"].unique())
                if match:
                    cdn = shopify_df.loc[shopify_df["Design No"] == match, "CDN link"].iloc[0]
                else:
                    cdn = None
            if cdn:
                st.image(cdn, caption=f"Design {query}")
            else:
                st.warning("No CDN link found in Shopify for this design.")


# Sales Trends
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
        st.warning("Upload Shopify Orders file to see sales trends.")


# ===============================
# 📂 Listed vs Non-Listed Section (UPDATED)
# ===============================
# -------------------------
# TAB 4 - Product Classification with Fuzzy Matching + Closing Qty
# -------------------------
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

tab5 = st.tabs(["📷 Image Availability"])[0]

with tab5:
    st.header("📷 Check Image Availability from Cloudinary")

    if warehouse_df is None:
        st.warning("Please upload the Warehouse file first.")
    else:
        try:
            # 🔹 Fetch first 500 resources from Cloudinary (adjust max_results if needed)
            cloudinary_files = cloudinary.api.resources(type="upload", max_results=500)["resources"]
            file_map = {res["public_id"].lower(): res["secure_url"] for res in cloudinary_files}

            availability = []
            for _, row in warehouse_df.iterrows():
                design_no = str(row.get("Design No", "")).strip().lower()
                closing_qty = row.get("Closing Qty", 0)

                matched_file = None
                matched_url = None
                for pid, url in file_map.items():
                    if design_no in pid:  # partial match in Cloudinary public_id
                        matched_file = pid
                        matched_url = url
                        break

                if matched_file:
                    availability.append({
                        "Design No": design_no,
                        "Closing Qty": closing_qty,
                        "Image Status": "✅ Available",
                        "Image File": matched_file,
                        "Image URL": matched_url
                    })
                else:
                    availability.append({
                        "Design No": design_no,
                        "Closing Qty": closing_qty,
                        "Image Status": "❌ Not Available",
                        "Image File": "",
                        "Image URL": ""
                    })

            availability_df = pd.DataFrame(availability)

            st.write("### Image Availability Status")
            st.dataframe(availability_df)

            # ✅ Show thumbnails for available images
            available = availability_df[availability_df["Image Status"] == "✅ Available"]
            if not available.empty:
                st.write("### Preview Available Images")
                for _, row in available.head(20).iterrows():
                    st.image(row["Image URL"], caption=f"Design {row['Design No']} (Qty: {row['Closing Qty']})", width=150)

            # ✅ Show only missing
            missing = availability_df[availability_df["Image Status"] == "❌ Not Available"]
            if not missing.empty:
                st.warning("Missing images for these designs:")
                st.table(missing[["Design No", "Closing Qty"]])
            else:
                st.success("🎉 All warehouse designs have images on Cloudinary!")

        except Exception as e:
            st.error(f"Cloudinary API error: {e}")
