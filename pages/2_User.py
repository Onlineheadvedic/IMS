import pandas as pd
import streamlit as st
from rapidfuzz import fuzz, process
from datetime import timedelta
import matplotlib.pyplot as plt
import cloudinary
import cloudinary.api
import cloudinary.uploader

st.set_page_config(page_title="User Dashboard", layout="wide")
st.title("👤 User Dashboard (Read-only)")

# -------------------------------
# Cloudinary config for Image Availability tab
# -------------------------------
if "cloudinary" in st.secrets:
    cloudinary.config(
        cloud_name=st.secrets["cloudinary"]["cloud_name"],
        api_key=st.secrets["cloudinary"]["api_key"],
        api_secret=st.secrets["cloudinary"]["api_secret"],
        secure=True
    )
else:
    st.warning("⚠️ Cloudinary not configured. Image Availability tab may not work.")

# -------------------------------
# Get data uploaded by Admin (session_state)
# -------------------------------
shopify_df = st.session_state.get("shopify_df")
warehouse_df = st.session_state.get("warehouse_df")
ebo_df = st.session_state.get("ebo_df")
orders_df = st.session_state.get("orders_df")

if all(df is None for df in [shopify_df, warehouse_df, ebo_df, orders_df]):
    st.warning("No data available. Ask Admin to upload files in the Admin page.")
    st.stop()

# -------------------------------
# Helpers (same as your app)
# -------------------------------
def fuzzy_best_match(query, choices):
    if not query or not len(choices):
        return None, 0
    match = process.extractOne(query, choices, scorer=fuzz.WRatio)
    if match:
        return match[0], match[1]
    return None, 0

# -------------------------------
# Key Metrics (same as your app)
# -------------------------------
wh_total = warehouse_df["Closing Qty"].sum() if warehouse_df is not None else 0
ebo_total = ebo_df["Closing Qty"].sum() if ebo_df is not None else 0
shop_total = shopify_df["Closing Qty"].sum() if shopify_df is not None else 0
overall_total = wh_total + ebo_total + shop_total

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Warehouse Qty", wh_total)
col2.metric("EBO Qty", ebo_total)
col3.metric("Shopify Qty", shop_total)
col4.metric("Overall Qty", overall_total)

# -------------------------------
# Reorder / Not Selling (same)
# -------------------------------
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

# -------------------------------
# Tabs (your original 5 tabs: 1–4 + Image Availability)
# -------------------------------
tab1, tab2, tab3, tab4 = st.tabs(["📊 Inventory Overview", "🔍 Search", "📈 Sales Trends", "📂 Listed vs Non-Listed"])

# ========= Tab 1: Inventory Overview =========
with tab1:
    if shopify_df is not None or warehouse_df is not None or ebo_df is not None:
        st.subheader("Inventory Overview")
        combined = []
        for label, df in [("Warehouse", warehouse_df), ("Shopify", shopify_df), ("EBO", ebo_df)]:
            if df is not None:
                agg = df.groupby(["Design No", "Barcode", "Color", "Size"], dropna=False)["Closing Qty"].sum().reset_index()
                agg.rename(columns={"Closing Qty": f"{label}_Qty"}, inplace=True)
                combined.append(agg)

        if combined:
            merged = combined[0]
            for part in combined[1:]:
                merged = merged.merge(part, on=["Design No", "Barcode", "Color", "Size"], how="outer")
            merged = merged.fillna(0)

            qty_cols = [c for c in merged.columns if c.endswith("_Qty")]
            merged["Total_QTY"] = merged[qty_cols].sum(axis=1)

            st.dataframe(
                merged[["Design No", "Barcode", "Color", "Size"] + qty_cols + ["Total_QTY"]]
                .sort_values("Total_QTY", ascending=False)
                .head(50)
            )

            st.subheader("Top 20 Designs by Inventory")
            top20 = merged.sort_values("Total_QTY", ascending=False).head(20)
            fig, ax = plt.subplots(figsize=(10,5))
            ax.bar(top20["Design No"], top20["Total_QTY"])
            ax.set_xlabel("Design No")
            ax.set_ylabel("Total Inventory")
            ax.set_title("Top 20 Designs by Inventory")
            plt.xticks(rotation=45, ha="right")
            st.pyplot(fig)

# ========= Tab 2: Search =========
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

# ========= Tab 3: Sales Trends =========
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
        st.warning("Upload Shopify Orders file (by Admin) to see sales trends.")

# ========= Tab 4: Listed vs Non-Listed =========
with tab4:
    st.header("🛍️ Product Classification")
    if shopify_df is None:
        st.warning("Please ask Admin to upload the Shopify file.")
    elif warehouse_df is None and ebo_df is None:
        st.warning("Please ask Admin to upload Warehouse and/or EBO files.")
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
                listed.append({"Design No": d, "Barcode": b, "Closing Qty": closing_qty, "Match Type": "Exact"})
            else:
                match_data = process.extractOne(d, shopify_designs)
                if match_data:
                    match, score = match_data[0], match_data[1]
                    if score >= 80:
                        listed.append({"Design No": d, "Barcode": b, "Closing Qty": closing_qty, "Match Type": f"Fuzzy ({score})"})
                    else:
                        nonlisted.append({"Design No": d, "Barcode": b, "Closing Qty": closing_qty})
                else:
                    nonlisted.append({"Design No": d, "Barcode": b, "Closing Qty": closing_qty})

        listed_df = pd.DataFrame(listed)
        nonlisted_df = pd.DataFrame(nonlisted)

        c1, c2 = st.columns(2)
        c1.metric("Listed Products", len(listed_df))
        c2.metric("Non-Listed Products", len(nonlisted_df))

        st.write("### ✅ Listed Products (Matched with Shopify)")
        st.dataframe(listed_df) if not listed_df.empty else st.warning("No listed products found.")

        st.write("### 📸 Photoshoot Required")
        st.info("These designs exist in Warehouse/EBO but are missing in Shopify. (Includes Closing Qty)")
        st.dataframe(nonlisted_df) if not nonlisted_df.empty else st.success("No products pending photoshoot.")

# ========= Tab 5: Image Availability (Cloudinary) =========
tab5 = st.tabs(["📷 Image Availability"])[0]
with tab5:
    st.header("📷 Check Image Availability from Cloudinary")

    if warehouse_df is None:
        st.warning("Please ask Admin to upload the Warehouse file first.")
    else:
        try:
            cloud_resources = cloudinary.api.resources(type="upload", max_results=500).get("resources", [])
            file_map = {res["public_id"].lower(): res["secure_url"] for res in cloud_resources}

            availability = []
            for _, row in warehouse_df.iterrows():
                design_no = str(row.get("Design No", "")).strip().lower()
                closing_qty = row.get("Closing Qty", 0)

                matched_file = None
                matched_url = None
                for pid, url in file_map.items():
                    if design_no in pid:
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

            available = availability_df[availability_df["Image Status"] == "✅ Available"]
            if not available.empty:
                st.write("### Preview Available Images")
                for _, r in available.head(20).iterrows():
                    st.image(r["Image URL"], caption=f"Design {r['Design No']} (Qty: {r['Closing Qty']})", width=150)

            missing = availability_df[availability_df["Image Status"] == "❌ Not Available"]
            if not missing.empty:
                st.warning("Missing images for these designs:")
                st.table(missing[["Design No", "Closing Qty"]])
            else:
                st.success("🎉 All warehouse designs have images on Cloudinary!")

        except Exception as e:
            st.error(f"Cloudinary API error: {e}")
