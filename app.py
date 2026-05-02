import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

# ---------------- CONFIG ----------------
st.set_page_config(
    page_title="Evergreen Inventory",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ---------------- GOOGLE SHEETS ----------------
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

spreadsheet = client.open("Inventory App Data")
main_sheet = spreadsheet.worksheet("Transactions")
user_sheet = spreadsheet.worksheet("Users")

# ---------------- SAFE APPEND ----------------
def safe_append(sheet, row):
    for _ in range(3):
        try:
            sheet.append_row(row)
            return True
        except:
            time.sleep(2)
    return False

# ---------------- CACHE ----------------
@st.cache_data(ttl=30)
def load_data():
    return main_sheet.get_all_records()

@st.cache_data(ttl=60)
def load_users():
    data = user_sheet.get_all_records()
    users = {}
    for row in data:
        users[row["Username"].strip()] = {
            "password": str(row["Password"]).strip(),
            "role": row["Role"]
        }
    return users

# ---------------- LOGIN ----------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""

users = load_users()

if not st.session_state.logged_in:

    st.title("🔐 Evergreen Irrigation Login")

    username = st.text_input("Username").strip()
    password = st.text_input("Password", type="password").strip()

    if st.button("Login", use_container_width=True):
        if username in users and users[username]["password"] == password:
            st.session_state.logged_in = True
            st.session_state.username = username
            st.session_state.role = users[username]["role"]
            st.success("Login successful")
            st.rerun()
        else:
            st.error("Invalid credentials")

    st.stop()

# ---------------- HEADER ----------------
col1, col2 = st.columns([8, 2])
with col2:
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

st.markdown(f"""
<h3 style='text-align: center; color: #2e7d32;'>Evergreen Irrigation</h3>
<p style='text-align: center;'>Welcome, {st.session_state.username}</p>
<hr>
""", unsafe_allow_html=True)

# ---------------- MENU ----------------
if st.session_state.role == "admin":
    menu = st.sidebar.radio("📌 Navigation",
        ["Dashboard", "Add Item", "Production", "Dispatch", "Reports", "Change Password"]
    )
else:
    menu = st.sidebar.radio("📌 Navigation",
        ["Dashboard", "Add Item", "Production", "Dispatch", "Change Password"]
    )

# ---------------- LOAD DATA ----------------
data = load_data()
df = pd.DataFrame(data)

if not df.empty:
    df["QTY"] = pd.to_numeric(df["QTY"], errors="coerce").fillna(0)

    df["Net"] = df.apply(
        lambda x: x["QTY"] if x["Type"] in ["OPENING", "PRODUCTION"] else -x["QTY"],
        axis=1
    )

# ---------------- ITEM → UNIT ----------------
item_unit_map = {}
if not df.empty:
    for _, row in df.iterrows():
        if row["Item"] not in item_unit_map and str(row["Unit"]).strip() != "":
            item_unit_map[row["Item"]] = row["Unit"]

# ---------------- DASHBOARD ----------------
if menu == "Dashboard":

    st.subheader("📊 Dashboard")

    if df.empty:
        st.info("No data available")
    else:
        summary = df.groupby(["Item", "Unit"])["Net"].sum().reset_index()
        summary.columns = ["Item", "Unit", "Stock"]

        st.dataframe(summary, use_container_width=True)

        low = summary[summary["Stock"] < 50]
        if not low.empty:
            st.error("⚠️ Low Stock")
            st.dataframe(low)

# ---------------- ADD ITEM ----------------
elif menu == "Add Item":

    item = st.text_input("Item Name")
    unit = st.text_input("Unit")
    qty = st.number_input("Opening Quantity", min_value=0)

    if st.button("Add", use_container_width=True):
        if item == "":
            st.error("Enter item")
        elif item in item_unit_map:
            st.warning("Item already exists")
        else:
            success = safe_append(main_sheet, [
                str(datetime.now()),
                st.session_state.username,
                item,
                "OPENING",
                qty,
                unit,
                "",
                "",
                ""
            ])

            if success:
                load_data.clear()
                st.success("Added")
                st.rerun()
            else:
                st.error("Failed to add item")

# ---------------- PRODUCTION ----------------
elif menu == "Production":

    item = st.selectbox("Item", df["Item"].unique())
    unit = item_unit_map.get(item, "")
    st.info(f"Unit: {unit}")

    qty = st.number_input("Quantity", min_value=1)

    if st.button("Submit", use_container_width=True):
        success = safe_append(main_sheet, [
            str(datetime.now()),
            st.session_state.username,
            item,
            "PRODUCTION",
            qty,
            unit,
            "",
            "",
            ""
        ])

        if success:
            load_data.clear()
            st.success("Production Added")
            st.rerun()
        else:
            st.error("Failed")

# ---------------- DISPATCH (MULTI ITEM) ----------------
elif menu == "Dispatch":

    st.subheader("🚚 Dispatch Load")

    start = st.text_input("Start Bill")
    end = st.text_input("End Bill")
    vehicle = st.text_input("Vehicle Number")

    if "dispatch_items" not in st.session_state:
        st.session_state.dispatch_items = []

    col1, col2, col3 = st.columns(3)

    with col1:
        item = st.selectbox("Item", df["Item"].unique())

    with col2:
        qty = st.number_input("Quantity", min_value=1)

    with col3:
        if st.button("➕ Add"):
            stock = df[df["Item"] == item]["Net"].sum()
            if qty > stock:
                st.error(f"Stock only: {int(stock)}")
            else:
                st.session_state.dispatch_items.append({
                    "item": item,
                    "qty": qty,
                    "unit": item_unit_map.get(item, "")
                })

    if st.session_state.dispatch_items:
        st.subheader("📦 Items in Load")
        st.dataframe(pd.DataFrame(st.session_state.dispatch_items))

    if st.button("🚀 Dispatch Load"):

        if not start or not end:
            st.error("Enter bill range")
        elif not st.session_state.dispatch_items:
            st.error("Add items")
        else:
            for row in st.session_state.dispatch_items:
                safe_append(main_sheet, [
                    str(datetime.now()),
                    st.session_state.username,
                    row["item"],
                    "DISPATCH",
                    row["qty"],
                    row["unit"],
                    start,
                    end,
                    vehicle
                ])

            load_data.clear()
            st.session_state.dispatch_items = []
            st.success("Dispatch Done")
            st.rerun()

# ---------------- REPORTS ----------------
elif menu == "Reports":

    if st.session_state.role != "admin":
        st.error("Access denied")
    else:
        summary = df.groupby(["Item", "Unit"])["Net"].sum().reset_index()
        st.dataframe(summary)

# ---------------- CHANGE PASSWORD ----------------
elif menu == "Change Password":

    current = st.text_input("Current Password", type="password")
    new = st.text_input("New Password", type="password")

    if st.button("Update Password"):
        users_data = user_sheet.get_all_records()

        for i, row in enumerate(users_data):
            if row["Username"].strip() == st.session_state.username:

                if str(row["Password"]).strip() != current:
                    st.error("Wrong password")
                else:
                    user_sheet.update_cell(i+2, 2, new)
                    st.success("Updated")
                    st.rerun()
