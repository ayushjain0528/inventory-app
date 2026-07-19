"""
Evergreen Irrigation — Stock Viewer (VIEW ONLY)
================================================
Salesperson sees: Category, Brand, Item, Spec (MTR), Unit, Available Qty.
No entry. No prices. Nothing can be changed from the app.

Data source: the 'Transactions' tab of the stock Google Sheet, which holds the
daily stock layout:
    A=Category  B=Brand  C=Item  D=MTR/Spec  E=Unit  F=Price  G=Current Stock
    H=Amount    I onward = daily Opening/Shift A/Shift B/out/closing blocks
The app reads ONLY columns A-E and G, rows 3 onward. F (price) and H (amount)
are never read, so the salesperson can never see them.

One-time setup:
1. Streamlit Cloud -> App -> Settings -> Secrets, paste:

       [gcp_service_account]
       type = "service_account"
       project_id = "..."
       private_key_id = "..."
       private_key = "..."
       client_email = "..."
       client_id = "..."
       token_uri = "https://oauth2.googleapis.com/token"

       [sheet]
       spreadsheet_id = "1x6JEBx1RdhR2ONLAOnHjswK0-dTD5wIHdnvntMiBCEQ"
       tab_name = "Transactions"

2. Share the Google Sheet with the service account email (Viewer is enough).
3. Remove credentials.json from the GitHub repo (secrets stay in Streamlit only)
   and rotate the old key in Google Cloud Console since it was public.
"""

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Evergreen Stock", page_icon="🌱", layout="wide")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
FIRST_DATA_ROW = 3  # rows 1-2 are headers in the stock layout


@st.cache_data(ttl=60, show_spinner="Loading stock…")
def load_stock() -> pd.DataFrame:
    info = dict(st.secrets["gcp_service_account"])
    # Fix the private key no matter how it was pasted into Secrets:
    # handles literal \n text, real line breaks, stray spaces/quotes.
    key = info.get("private_key", "").strip().strip('"').strip("'")
    key = key.replace("\\n", "\n").strip()
    if not key.endswith("\n"):
        key += "\n"
    info["private_key"] = key
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(st.secrets["sheet"]["spreadsheet_id"])
    ws = sh.worksheet(st.secrets["sheet"].get("tab_name", "Transactions"))

    # Read only what the salesperson may see: A-E (identity) and G (qty).
    identity = ws.get(f"A{FIRST_DATA_ROW}:E1000")
    qty = ws.get(f"G{FIRST_DATA_ROW}:G1000")

    rows = []
    for i, rec in enumerate(identity):
        rec = (rec + [""] * 5)[:5]
        cat, brand, item, mtr, unit = (v.strip() for v in rec)
        if not item:  # stop at first row without an item name
            break
        q_raw = qty[i][0] if i < len(qty) and qty[i] else "0"
        q = pd.to_numeric(q_raw.replace(",", ""), errors="coerce")
        rows.append(
            {
                "Category": cat,
                "Brand": brand,
                "Item": item,
                "Spec": mtr,
                "Unit": unit,
                "Available Qty": 0 if pd.isna(q) else q,
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
