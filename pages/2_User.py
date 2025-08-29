import pandas as pd
import streamlit as st
from rapidfuzz import process
from datetime import timedelta
import matplotlib.pyplot as plt
import cloudinary
import cloudinary.api

st.title("👤 User Dashboard")

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

# ================================
# Get data from session_state
# ================================
shopify_df = st.session_state.get("shopify_df")
warehouse_df = st.session_state.get("warehouse_df")
ebo_df = st.session_state.get("ebo_df")
orders_df = st.session_state.get("orders_df")

if not any([shopify_df is not None, warehouse_df is not None, ebo_df is not None, orders_df is not None]):
    st.warning("⚠️ No data available. Please ask Admin to upload files first.")
    st.stop()

# ================================
# Show dashboards (your existing code reused)
# ================================
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


# Reorder / Not Selling
reorder_designs, notselling_designs = [], []
if orders_df is not None:
    max_date = orders_df["Created at"].max()
    if pd.notnull(max_date):
        cutoff = max_date - timedelta(days=3)  # 🔹 last 3 days
        recent = orders_df[orders_df["Created at"] >= cutoff]
        sales = recent.groupby("Design No")["Quantity"].sum().reset_index()
        for _, row in sales.iterrows():
            if row["Quantity"] > 10:
                reorder_designs.append(row["Design No"])
            elif row["Quantity"] < 10:
                notselling_designs.append(row["Design No"])


col5.metric("Reorder Designs (sales > 10, last 3d)", len(reorder_designs))
col6.metric("Not Selling (sales < 10, last 3d)", len(notselling_designs))


# Tabs
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

# 🔹 Configure your Google Drive folder path
image_folder = "/content/drive/MyDrive/ECOM"

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