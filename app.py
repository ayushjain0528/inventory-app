import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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

# ---------------- LOAD USERS ----------------
def load_users():
    data = user_sheet.get_all_records()
    users = {}
    for row in data:
        users[row["Username"].strip()] = {
            "password": str(row["Password"]).strip(),
            "role": row["Role"]
        }
    return users

# ---------------- LOGIN STATE ----------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""

users = load_users()

# ---------------- LOGIN ----------------
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

st.markdown(
    f"""
    <h3 style='text-align: center; color: #2e7d32;'>
        🌿 Evergreen Irrigation
    </h3>
    <p style='text-align: center;'>Welcome, {st.session_state.username}</p>
    <hr>
    """,
    unsafe_allow_html=True
)

# ---------------- MENU ----------------
if st.session_state.role == "admin":
    menu = st.sidebar.radio(
        "📌 Navigation",
        ["Dashboard", "Add Item", "Production", "Dispatch", "Reports", "Change Password"]
    )
else:
    menu = st.sidebar.radio(
        "📌 Navigation",
        ["Dashboard", "Add Item", "Production", "Dispatch", "Change Password"]
    )

# ---------------- LOAD DATA ----------------
data = main_sheet.get_all_records()
df = pd.DataFrame(data)

# ---------------- PROCESS ----------------
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

if not df.empty:
    df["Unit"] = df.apply(
        lambda x: item_unit_map.get(x["Item"], "") if str(x["Unit"]).strip() == "" else x["Unit"],
        axis=1
    )

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
            main_sheet.append_row([
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
            st.success("Added")
            st.rerun()

# ---------------- PRODUCTION ----------------
elif menu == "Production":

    item = st.selectbox("Item", df["Item"].unique())
    unit = item_unit_map.get(item, "")
    st.info(f"Unit: {unit}")

    qty = st.number_input("Quantity", min_value=1)

    if st.button("Submit", use_container_width=True):
        main_sheet.append_row([
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
        st.success("Production Added")
        st.rerun()

# ---------------- DISPATCH ----------------
elif menu == "Dispatch":

    item = st.selectbox("Item", df["Item"].unique())
    unit = item_unit_map.get(item, "")
    st.info(f"Unit: {unit}")

    qty = st.number_input("Dispatch Quantity", min_value=1)
    start = st.text_input("Start Bill")
    end = st.text_input("End Bill")
    vehicle = st.text_input("Vehicle Number")

    stock = df[df["Item"] == item]["Net"].sum()
    st.info(f"Available Stock: {int(stock)}")

    if st.button("Dispatch", use_container_width=True):
        if qty > stock:
            st.error("Not enough stock")
        else:
            main_sheet.append_row([
                str(datetime.now()),
                st.session_state.username,
                item,
                "DISPATCH",
                qty,
                unit,
                start,
                end,
                vehicle
            ])
            st.success("Dispatch Done")
            st.rerun()

# ---------------- REPORTS (ADMIN ONLY) ----------------
elif menu == "Reports":

    if st.session_state.role != "admin":
        st.error("Access denied")
    else:
        st.subheader("📊 Reports")

        summary = df.groupby(["Item", "Unit"])["Net"].sum().reset_index()
        st.dataframe(summary, use_container_width=True)

        st.subheader("👤 User Activity")
        user_report = df.groupby(["User", "Type"])["QTY"].sum().reset_index()
        st.dataframe(user_report, use_container_width=True)

# ---------------- CHANGE PASSWORD ----------------
elif menu == "Change Password":

    st.subheader("🔑 Change Password")

    current = st.text_input("Current Password", type="password")
    new = st.text_input("New Password", type="password")

    if st.button("Update Password", use_container_width=True):

        users_data = user_sheet.get_all_records()

        for i, row in enumerate(users_data):
            if row["Username"].strip() == st.session_state.username:

                if str(row["Password"]).strip() != current:
                    st.error("Wrong password")
                else:
                    user_sheet.update_cell(i+2, 2, new)
                    st.success("Password updated")
                    st.rerun()
