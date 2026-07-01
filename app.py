import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Evergreen Irrigation",
    page_icon="🌿",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    #MainMenu, footer, header {visibility: hidden;}
    .block-container {padding-top: 0.8rem; padding-bottom: 2rem; max-width: 720px;}

    /* Top bar */
    .topbar {
        display: flex; justify-content: space-between; align-items: center;
        padding: 10px 0 6px; border-bottom: 1px solid #e8e8e8; margin-bottom: 12px;
    }
    .topbar-title {font-size: 18px; font-weight: 600; color: #2e7d32;}
    .topbar-user {font-size: 12px; color: #888;}

    /* Metric row */
    div[data-testid="metric-container"] {
        background: #f1f8e9;
        border: 1px solid #c5e1a5;
        border-radius: 10px;
        padding: 10px 14px;
    }
    div[data-testid="metric-container"] label {font-size: 12px !important; color: #558b2f !important;}
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        font-size: 22px !important; font-weight: 600 !important; color: #2e7d32 !important;
    }

    /* Stock rows */
    .item-row {
        display: flex; justify-content: space-between; align-items: center;
        padding: 7px 0; border-bottom: 1px solid #f5f5f5; font-size: 14px;
    }
    .item-name {font-weight: 500; color: #222;}
    .item-spec {font-size: 12px; color: #999; margin-top: 1px;}
    .qty-ok   {font-weight: 600; color: #2e7d32;}
    .qty-low  {font-weight: 600; color: #e65100;}
    .qty-zero {font-weight: 600; color: #c62828;}

    /* Section header */
    .sec-head {
        font-size: 11px; font-weight: 700; text-transform: uppercase;
        letter-spacing: .06em; color: #888; margin: 16px 0 4px;
    }

    /* Log rows */
    .log-row {
        display: flex; justify-content: space-between; align-items: flex-start;
        padding: 8px 0; border-bottom: 1px solid #f5f5f5; font-size: 13px;
    }
    .log-in  {font-weight: 600; color: #2e7d32;}
    .log-out {font-weight: 600; color: #c62828;}
    .log-meta {font-size: 11px; color: #aaa; margin-top: 2px;}

    /* Dispatch load card */
    .disp-item {
        display: flex; justify-content: space-between;
        background: #f9fbe7; border: 1px solid #dce775;
        border-radius: 8px; padding: 8px 12px; margin-bottom: 6px; font-size: 13px;
    }

    /* Primary button override */
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: #2e7d32 !important;
        border-color: #2e7d32 !important;
        color: white !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background-color: #1b5e20 !important;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# GOOGLE SHEETS
# ─────────────────────────────────────────────
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_sheets():
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
    client = gspread.authorize(creds)
    ss = client.open("Inventory App Data")
    return ss.worksheet("Transactions"), ss.worksheet("Users")

main_sheet, user_sheet = get_sheets()


def safe_append(sheet, row, retries=3):
    for _ in range(retries):
        try:
            sheet.append_row(row, value_input_option="USER_ENTERED")
            return True
        except Exception:
            time.sleep(2)
    return False


# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_data():
    records = main_sheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=[
            "Timestamp", "Username", "Item", "Type",
            "QTY", "Unit", "Start Bill", "End Bill", "Vehicle"
        ])
    df = pd.DataFrame(records)

    # Normalise column names: strip whitespace, fix common casing issues
    df.columns = [c.strip() for c in df.columns]
    # Map any alternate header spellings to expected names
    col_aliases = {
        "timestamp": "Timestamp", "time stamp": "Timestamp",
        "username": "Username", "user name": "Username", "user": "Username",
        "item": "Item", "item name": "Item",
        "type": "Type",
        "qty": "QTY", "quantity": "QTY",
        "unit": "Unit",
        "start bill": "Start Bill", "startbill": "Start Bill",
        "end bill": "End Bill", "endbill": "End Bill",
        "vehicle": "Vehicle", "vehicle no": "Vehicle", "vehicle no.": "Vehicle",
    }
    df.rename(columns={c: col_aliases[c.lower()] for c in df.columns if c.lower() in col_aliases}, inplace=True)

    # Ensure essential columns exist
    for col in ["Timestamp", "Username", "Item", "Type", "QTY", "Unit", "Start Bill", "End Bill", "Vehicle"]:
        if col not in df.columns:
            df[col] = ""

    df["QTY"] = pd.to_numeric(df["QTY"], errors="coerce").fillna(0)
    df["Net"] = df.apply(
        lambda r: r["QTY"] if r["Type"] in ("OPENING", "PRODUCTION", "PURCHASE") else -r["QTY"],
        axis=1
    )
    return df


@st.cache_data(ttl=120)
def load_users():
    rows = user_sheet.get_all_records()
    return {
        r["Username"].strip(): {
            "password": str(r["Password"]).strip(),
            "role": r["Role"]
        }
        for r in rows
    }


def get_summary(df):
    """Current stock per item."""
    if df.empty:
        return pd.DataFrame(columns=["Item", "Unit", "Stock"])
    s = df.groupby(["Item", "Unit"])["Net"].sum().reset_index()
    s.columns = ["Item", "Unit", "Stock"]
    s["Stock"] = s["Stock"].round(2)
    return s


def item_unit_map(df):
    m = {}
    if df.empty:
        return m
    for _, r in df.iterrows():
        if r["Item"] and r["Item"] not in m and str(r.get("Unit","")).strip():
            m[r["Item"]] = str(r["Unit"]).strip()
    return m


# ─────────────────────────────────────────────
# CATEGORIES  (derived — no schema change)
# ─────────────────────────────────────────────
CATEGORIES = [
    "ISI Pipes", "Non-ISI Pipes", "Branded Pipes",
    "Fittings & Accessories", "Raw Material", "Other"
]

# Keyword → category map used to auto-tag items
_CAT_KEYWORDS = {
    "ISI Pipes":             ["isi"],
    "Branded Pipes":         ["tulsi","everflow","evergreen platinum","rk diamond",
                              "green flow","saha sri","nisha","tamaka"],
    "Fittings & Accessories":["ball valve","filter","venturi","flush valve",
                              "hydrocyclone","dripper","microtube","buffer tube",
                              "spiral tube","clamp","mesh","sprinkler","riser","rubber","arv"],
    "Raw Material":          ["lldpe","hdpe","masterbatch","ppa","sdg rp"],
}

def guess_category(name: str) -> str:
    n = name.lower()
    for cat, kws in _CAT_KEYWORDS.items():
        if any(k in n for k in kws):
            return cat
    return "Non-ISI Pipes"


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
for k, v in [("logged_in", False), ("username", ""), ("role", "")]:
    if k not in st.session_state:
        st.session_state[k] = v

if not st.session_state.logged_in:
    st.markdown("""
    <div style='text-align:center;padding:50px 0 24px'>
        <div style='font-size:52px'>🌿</div>
        <h2 style='color:#2e7d32;margin:6px 0 4px'>Evergreen Irrigation</h2>
        <p style='color:#888;font-size:14px'>Stock Management</p>
    </div>
    """, unsafe_allow_html=True)

    users = load_users()
    uname = st.text_input("Username", placeholder="Enter username")
    pwd   = st.text_input("Password", type="password", placeholder="Enter password")

    if st.button("Login", use_container_width=True, type="primary"):
        u = uname.strip()
        p = pwd.strip()
        if u in users and users[u]["password"] == p:
            st.session_state.logged_in = True
            st.session_state.username  = u
            st.session_state.role      = users[u]["role"]
            st.rerun()
        else:
            st.error("Wrong username or password")
    st.stop()


# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
c1, c2 = st.columns([7, 1])
with c1:
    st.markdown(
        f"<div class='topbar'>"
        f"<span class='topbar-title'>🌿 Evergreen</span>"
        f"<span class='topbar-user'>👤 {st.session_state.username}</span>"
        f"</div>",
        unsafe_allow_html=True
    )
with c2:
    st.markdown("<div style='padding-top:8px'></div>", unsafe_allow_html=True)
    if st.button("Logout", use_container_width=True):
        for k in ["logged_in","username","role","dispatch_items"]:
            st.session_state.pop(k, None)
        st.rerun()


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
df      = load_data()
summary = get_summary(df)
units   = item_unit_map(df)
items   = sorted(df["Item"].unique().tolist()) if not df.empty else []


# ─────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────
tab_labels = ["📦 Stock", "⬇️ Stock In", "⬆️ Stock Out", "📋 History"]
if st.session_state.role == "admin":
    tab_labels.append("⚙️ Admin")

tabs = st.tabs(tab_labels)


# ══════════════════════════════════════════════
# TAB 1 — STOCK
# ══════════════════════════════════════════════
with tabs[0]:

    if summary.empty:
        st.info("No stock data yet — add items via **Stock In**.")
    else:
        total      = len(summary)
        out        = int((summary["Stock"] <= 0).sum())
        isi_items  = [i for i in summary["Item"] if "isi" in i.lower()]
        isi_stock  = int(summary[summary["Item"].isin(isi_items)]["Stock"].sum())

        m1, m2, m3 = st.columns(3)
        m1.metric("Total SKUs",   total)
        m2.metric("Out of Stock", out)
        m3.metric("ISI Rolls",    isi_stock)

        st.markdown("---")

        # Search + category filter
        search   = st.text_input("🔍 Search", placeholder="Item name…", label_visibility="collapsed")
        cat_pick = st.selectbox("Category", ["All"] + CATEGORIES,
                                label_visibility="collapsed", key="stock_cat")

        view = summary.copy()
        if search:
            view = view[view["Item"].str.contains(search, case=False, na=False)]

        # Assign guessed category for grouping
        view["_cat"] = view["Item"].apply(guess_category)
        if cat_pick != "All":
            view = view[view["_cat"] == cat_pick]

        if view.empty:
            st.caption("No items match.")
        else:
            for cat, grp in view.groupby("_cat"):
                st.markdown(f"<div class='sec-head'>{cat}</div>", unsafe_allow_html=True)
                for _, row in grp.sort_values("Item").iterrows():
                    q   = row["Stock"]
                    cls = "qty-zero" if q <= 0 else ("qty-low" if q <= 10 else "qty-ok")
                    st.markdown(
                        f"<div class='item-row'>"
                        f"  <div><div class='item-name'>{row['Item']}</div></div>"
                        f"  <div class='{cls}'>{q} {row['Unit']}</div>"
                        f"</div>",
                        unsafe_allow_html=True
                    )


# ══════════════════════════════════════════════
# TAB 2 — STOCK IN
# ══════════════════════════════════════════════
with tabs[1]:
    st.markdown("#### ⬇️ Stock In")
    st.caption("Record new production, supplier deliveries, or opening balances.")

    txn_label = st.radio(
        "What are you recording?",
        ["Production (made in factory)", "Purchase (received from supplier)", "Opening Balance"],
        horizontal=True
    )
    TYPE_MAP = {
        "Production (made in factory)":        "PRODUCTION",
        "Purchase (received from supplier)":   "PURCHASE",
        "Opening Balance":                     "OPENING",
    }
    in_type = TYPE_MAP[txn_label]

    # Category → narrow item list
    in_cat  = st.selectbox("Filter by category", ["— All —"] + CATEGORIES, key="in_cat")
    if in_cat != "— All —":
        cat_items = [i for i in items if guess_category(i) == in_cat]
    else:
        cat_items = items

    # Existing or new
    options     = cat_items + ["➕ New item…"]
    sel_item    = st.selectbox("Item", options, key="in_item")
    is_new      = sel_item == "➕ New item…"

    if is_new:
        new_name  = st.text_input("Item Name")
        new_unit  = st.selectbox("Unit", ["Roll","Bag","Box","Nos","Piece","Set","Kg"])
        item_name = new_name.strip()
        item_unit = new_unit
    else:
        item_name = sel_item
        item_unit = units.get(sel_item, "")
        cur_stock = summary[summary["Item"] == sel_item]["Stock"].sum() if not summary.empty else 0
        st.info(f"Current stock: **{cur_stock} {item_unit}**")

    in_qty    = st.number_input("Quantity", min_value=0.5, step=0.5, key="in_qty")
    in_remark = st.text_input("Remark (optional)", placeholder="Batch no., supplier name…")

    if st.button("✅ Submit Stock In", use_container_width=True, type="primary"):
        if not item_name:
            st.error("Enter item name.")
        elif not item_unit:
            st.error("Enter unit.")
        elif in_qty <= 0:
            st.error("Quantity must be > 0.")
        else:
            ok = safe_append(main_sheet, [
                str(datetime.now()),
                st.session_state.username,
                item_name,
                in_type,
                in_qty,
                item_unit,
                in_remark,   # reusing Start Bill column for remark on non-dispatch rows
                "",
                ""
            ])
            if ok:
                load_data.clear()
                st.success(f"Added {in_qty} {item_unit} — {item_name}")
                st.rerun()
            else:
                st.error("Failed to save. Check your connection and try again.")


# ══════════════════════════════════════════════
# TAB 3 — STOCK OUT / DISPATCH
# ══════════════════════════════════════════════
with tabs[2]:
    st.markdown("#### ⬆️ Stock Out / Dispatch")

    if "dispatch_items" not in st.session_state:
        st.session_state.dispatch_items = []

    # Bill info
    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        start_bill = st.text_input("Start Bill No.")
    with col_b2:
        end_bill   = st.text_input("End Bill No.")
    with col_b3:
        vehicle    = st.text_input("Vehicle No.")

    st.markdown("---")
    st.markdown("**Add items to this load**")

    # Category filter → smaller dropdown
    out_cat = st.selectbox("Filter by category", ["— All —"] + CATEGORIES, key="out_cat")
    if out_cat != "— All —":
        out_items = [i for i in items if guess_category(i) == out_cat]
    else:
        out_items = items

    col_i1, col_i2, col_i3 = st.columns([3, 1, 1])
    with col_i1:
        disp_item = st.selectbox("Item", out_items if out_items else ["No items yet"], key="disp_item")
    with col_i2:
        disp_qty  = st.number_input("Qty", min_value=0.5, step=0.5, key="disp_qty")
    with col_i3:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        add_clicked = st.button("➕ Add", use_container_width=True, key="add_item")

    if add_clicked and out_items:
        in_load   = sum(i["qty"] for i in st.session_state.dispatch_items if i["item"] == disp_item)
        available = float(summary[summary["Item"] == disp_item]["Stock"].sum()) - in_load \
                    if not summary.empty else 0
        if disp_qty > available:
            st.error(f"Only {available} available (including items already in this load).")
        else:
            st.session_state.dispatch_items.append({
                "item": disp_item,
                "qty":  disp_qty,
                "unit": units.get(disp_item, "")
            })
            st.rerun()

    # Show current load
    if st.session_state.dispatch_items:
        st.markdown("---")
        st.markdown("**Current load:**")
        for idx, row in enumerate(st.session_state.dispatch_items):
            col_r1, col_r2 = st.columns([5, 1])
            with col_r1:
                st.markdown(
                    f"<div class='disp-item'>"
                    f"<span><b>{row['item']}</b></span>"
                    f"<span>{row['qty']} {row['unit']}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )
            with col_r2:
                if st.button("🗑️", key=f"del_{idx}"):
                    st.session_state.dispatch_items.pop(idx)
                    st.rerun()

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            if st.button("Clear Load", use_container_width=True):
                st.session_state.dispatch_items = []
                st.rerun()
        with col_d2:
            if st.button("🚀 Dispatch", use_container_width=True, type="primary"):
                if not start_bill:
                    st.error("Enter start bill number.")
                else:
                    failed = False
                    for row in st.session_state.dispatch_items:
                        ok = safe_append(main_sheet, [
                            str(datetime.now()),
                            st.session_state.username,
                            row["item"],
                            "DISPATCH",
                            row["qty"],
                            row["unit"],
                            start_bill,
                            end_bill,
                            vehicle
                        ])
                        if not ok:
                            failed = True
                    if failed:
                        st.error("Some items failed to save. Check Google Sheets.")
                    else:
                        load_data.clear()
                        st.session_state.dispatch_items = []
                        st.success("✅ Dispatch recorded!")
                        st.rerun()
    else:
        st.caption("No items added yet.")


# ══════════════════════════════════════════════
# TAB 4 — HISTORY
# ══════════════════════════════════════════════
with tabs[3]:
    st.markdown("#### 📋 Transaction History")

    if df.empty:
        st.info("No transactions yet.")
    else:
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            h_search = st.text_input("🔍 Search", placeholder="Item name, user…", key="h_search")
        with col_f2:
            h_type   = st.selectbox("Type", ["All","PRODUCTION","PURCHASE","OPENING","DISPATCH"], key="h_type")

        h_dates = st.date_input("Date range (optional)", value=[], key="h_dates")

        hist = df.copy()
        if h_search:
            mask = (
                hist["Item"].str.contains(h_search, case=False, na=False) |
                hist["Username"].str.contains(h_search, case=False, na=False)
            )
            hist = hist[mask]
        if h_type != "All":
            hist = hist[hist["Type"] == h_type]
        if isinstance(h_dates, (list, tuple)) and len(h_dates) == 2:
            hist["_d"] = pd.to_datetime(hist["Timestamp"], errors="coerce").dt.date
            hist = hist[(hist["_d"] >= h_dates[0]) & (hist["_d"] <= h_dates[1])]

        ts_col = "Timestamp" if "Timestamp" in hist.columns else hist.columns[0]
        hist = hist.sort_values(ts_col, ascending=False).head(300)

        # Render as clean rows
        for _, r in hist.iterrows():
            is_in  = r["Type"] in ("PRODUCTION","PURCHASE","OPENING")
            cls    = "log-in" if is_in else "log-out"
            prefix = "+" if is_in else "−"
            ts     = str(r["Timestamp"])[:16]
            bill   = f"Bill {r.get('Start Bill','')}–{r.get('End Bill','')}" \
                     if r.get("Start Bill") else ""
            meta   = f"{r['Type']} · {r['Username']} · {ts}" + (f" · {bill}" if bill else "")
            if r.get("Vehicle"):
                meta += f" · {r['Vehicle']}"
            st.markdown(
                f"<div class='log-row'>"
                f"  <div><div style='font-weight:500'>{r['Item']}</div>"
                f"      <div class='log-meta'>{meta}</div></div>"
                f"  <div class='{cls}'>{prefix}{r['QTY']} {r['Unit']}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

        st.caption(f"{len(hist)} records shown")

        if st.session_state.role == "admin":
            csv = hist.drop(columns=["Net","_d"], errors="ignore").to_csv(index=False).encode()
            st.download_button("⬇️ Export CSV", csv, "transactions.csv", "text/csv",
                               use_container_width=True)

    # Change password (non-admin users access it here)
    if st.session_state.role != "admin":
        st.markdown("---")
        with st.expander("🔑 Change Password"):
            cp_cur = st.text_input("Current Password", type="password", key="cp_cur")
            cp_new = st.text_input("New Password",     type="password", key="cp_new")
            if st.button("Update Password", key="cp_btn"):
                rows = user_sheet.get_all_records()
                for i, row in enumerate(rows):
                    if row["Username"].strip() == st.session_state.username:
                        if str(row["Password"]).strip() != cp_cur:
                            st.error("Current password is wrong.")
                        else:
                            user_sheet.update_cell(i + 2, 2, cp_new)
                            load_users.clear()
                            st.success("Password updated.")
                        break


# ══════════════════════════════════════════════
# TAB 5 — ADMIN  (admin only)
# ══════════════════════════════════════════════
if st.session_state.role == "admin":
    with tabs[4]:
        st.markdown("#### ⚙️ Admin")

        section = st.radio("", ["Change Password", "Users", "Stock Summary"], horizontal=True,
                           label_visibility="collapsed")

        if section == "Change Password":
            cp_cur2 = st.text_input("Current Password", type="password", key="acp_cur")
            cp_new2 = st.text_input("New Password",     type="password", key="acp_new")
            cp_con2 = st.text_input("Confirm Password", type="password", key="acp_con")
            if st.button("Update", use_container_width=True, type="primary"):
                if cp_new2 != cp_con2:
                    st.error("New passwords don't match.")
                else:
                    rows = user_sheet.get_all_records()
                    for i, row in enumerate(rows):
                        if row["Username"].strip() == st.session_state.username:
                            if str(row["Password"]).strip() != cp_cur2:
                                st.error("Current password is wrong.")
                            else:
                                user_sheet.update_cell(i + 2, 2, cp_new2)
                                load_users.clear()
                                st.success("Password updated.")
                            break

        elif section == "Users":
            st.caption("Registered users:")
            all_users = load_users()
            for u, d in all_users.items():
                st.markdown(f"**{u}** — {d['role']}")

        elif section == "Stock Summary":
            if summary.empty:
                st.info("No data.")
            else:
                summary["Category"] = summary["Item"].apply(guess_category)
                st.dataframe(
                    summary[["Category","Item","Unit","Stock"]]
                        .sort_values(["Category","Item"])
                        .reset_index(drop=True),
                    use_container_width=True,
                    height=500
                )
                csv = summary.to_csv(index=False).encode()
                st.download_button("⬇️ Download Stock CSV", csv, "stock_summary.csv", "text/csv",
                                   use_container_width=True)
