"""
Evergreen Irrigation — Stock Viewer (VIEW ONLY, no credentials needed)
======================================================================
Reads the link-shared stock Google Sheet directly. No service account,
no private key, no gspread — nothing to go wrong.

Requirement: the Google Sheet must be shared as "Anyone with the link: Viewer"
(it already is).

Streamlit Secrets needed (keep only this, the gcp_service_account part
can stay or be deleted, it is not used anymore):

    [sheet]
    spreadsheet_id = "1x6JEBx1RdhR2ONLAOnHjswK0-dTD5wIHdnvntMiBCEQ"
    gid = "0"

Sheet layout (Transactions tab):
    A=Category B=Brand C=Item D=MTR/Spec E=Unit F=Price G=Current Stock ...
Rows 1-2 are headers; data starts at row 3.
The app shows ONLY columns A-E and G. Price and Amount are never displayed.
"""

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Evergreen Stock", page_icon="🌱", layout="wide")

FIRST_DATA_ROW = 3  # sheet row where items start (rows 1-2 are headers)


@st.cache_data(ttl=60, show_spinner="Loading stock…")
def load_stock() -> pd.DataFrame:
    sid = st.secrets["sheet"]["spreadsheet_id"]
    gid = str(st.secrets["sheet"].get("gid", "0"))
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
    raw = pd.read_csv(url, header=None, dtype=str)

    rows = []
    for _, r in raw.iloc[FIRST_DATA_ROW - 1 :].iterrows():
        get = lambda i: (r[i] if i in r and pd.notna(r[i]) else "").strip()
        item = get(2)
        if not item:  # stop at first row without an item name
            break
        qty = pd.to_numeric(get(6).replace(",", ""), errors="coerce")
        rows.append(
            {
                "Category": get(0),
                "Brand": get(1),
                "Item": item,
                "Spec": get(3),
                "Unit": get(4),
                "Available Qty": 0 if pd.isna(qty) else qty,
            }
        )
    return pd.DataFrame(rows)


st.title("🌱 Evergreen Irrigation — Available Stock")

try:
    df = load_stock()
except Exception as e:
    st.error("Could not load stock. Check internet, or contact Ayush.")
    st.caption(f"Technical detail: {e}")
    st.stop()

if df.empty:
    st.warning("No stock rows found in the sheet.")
    st.stop()

# ---------------- filters ----------------
c1, c2, c3 = st.columns([2.5, 2, 1.2])
with c1:
    search = st.text_input(
        "🔍 Search", placeholder="e.g. 8mil, 16mm round, sprinkler, ball valve"
    )
with c2:
    cat = st.selectbox("Category", ["All"] + sorted(df["Category"].unique()))
with c3:
    in_stock = st.toggle("In stock only", value=True)

view = df
if cat != "All":
    view = view[view["Category"] == cat]
if search.strip():
    s = search.strip().lower()
    view = view[
        view["Item"].str.lower().str.contains(s, na=False)
        | view["Spec"].str.lower().str.contains(s, na=False)
        | view["Brand"].str.lower().str.contains(s, na=False)
    ]
if in_stock:
    view = view[view["Available Qty"] > 0]

st.caption(f"{len(view)} items · updates automatically from the stock sheet")
st.dataframe(
    view.reset_index(drop=True),
    use_container_width=True,
    hide_index=True,
    column_config={
        "Available Qty": st.column_config.NumberColumn(format="%.10g"),
    },
)

if st.button("🔄 Refresh now"):
    load_stock.clear()
    st.rerun()
