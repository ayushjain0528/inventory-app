import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import secrets
import gspread
from google.oauth2.service_account import Credentials
import time
import io
import difflib

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Evergreen Irrigation",
    page_icon="🌿",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ─────────────────────────────────────────────
# INSTALLABLE APP (PWA)
# Lets a phone's "Add to Home Screen" install this as a real app icon
# that opens full-screen (no browser address bar), instead of a bookmark.
# Requires: static/manifest.json, static/icon-192.png, static/icon-512.png,
# static/sw.js, and enableStaticServing = true in .streamlit/config.toml
# ─────────────────────────────────────────────
import streamlit.components.v1 as components
components.html("""
<script>
(function() {
  const doc = window.parent.document;
  if (doc.querySelector('link[rel="manifest"]')) return;  // already injected

  const manifest = doc.createElement('link');
  manifest.rel = 'manifest';
  manifest.href = './app/static/manifest.json';
  doc.head.appendChild(manifest);

  const touchIcon = doc.createElement('link');
  touchIcon.rel = 'apple-touch-icon';
  touchIcon.href = './app/static/apple-touch-icon.png';
  doc.head.appendChild(touchIcon);

  const themeColor = doc.createElement('meta');
  themeColor.name = 'theme-color';
  themeColor.content = '#2e7d32';
  doc.head.appendChild(themeColor);

  const favicon = doc.createElement('link');
  favicon.rel = 'icon';
  favicon.href = './app/static/favicon.ico';
  doc.head.appendChild(favicon);

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./app/static/sw.js').catch(function(){});
  }
})();
</script>
""", height=0, width=0)

# ─────────────────────────────────────────────
# REMEMBER-ME SYNC
# On a fresh app open, if this phone has a saved login token in
# localStorage but the current URL doesn't carry it, reload once with
# ?t=<token> so the Python side below can auto-login. After a manual
# login with "Keep me signed in" checked, the token is written back
# into localStorage and the URL so the NEXT open skips the login form.
# ─────────────────────────────────────────────
components.html("""
<script>
(function() {
  const win = window.parent;
  const doc = win.document;
  const saved = localStorage.getItem('evergreen_token');
  const url = new URL(win.location.href);
  if (saved && !url.searchParams.get('t')) {
    url.searchParams.set('t', saved);
    win.location.replace(url.toString());
  }
})();
</script>
""", height=0, width=0)

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
    .log-move {font-weight: 600; color: #1565c0;}
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

    /* Bigger, easier-to-tap buttons everywhere — especially the home menu */
    div[data-testid="stButton"] button {
        font-size: 15px;
        padding: 0.7rem 0.8rem;
        min-height: 46px;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# LOCATIONS / AREAS
# ─────────────────────────────────────────────
LOCATIONS = ["Factory", "Godown 1", "Godown 2"]
DEFAULT_LOCATION = "Factory"   # old transactions without a location count here


# ─────────────────────────────────────────────
# GOOGLE SHEETS
# ─────────────────────────────────────────────
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_sheets():
    # Credentials come from .streamlit/secrets.toml ([gcp_service_account])
    # or Streamlit Cloud secrets — never from a credentials.json in the repo.
    if "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=SCOPE
        )
    else:
        # Local-only fallback; keep credentials.json in .gitignore
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPE)
    client = gspread.authorize(creds)
    ss = client.open("Inventory App Data")

    tx = ss.worksheet("Transactions")
    us = ss.worksheet("Users")

    # Ensure new columns exist on the Transactions header row
    header = tx.row_values(1)
    if "Location" not in header:
        tx.update_cell(1, len(header) + 1, "Location")
        header.append("Location")
    if "To Location" not in header:
        tx.update_cell(1, len(header) + 1, "To Location")
        header.append("To Location")
    if "Shift" not in header:
        tx.update_cell(1, len(header) + 1, "Shift")

    # Ensure a Prices sheet exists (admin-only price data)
    try:
        pr = ss.worksheet("Prices")
    except gspread.exceptions.WorksheetNotFound:
        pr = ss.add_worksheet(title="Prices", rows=500, cols=3)
        pr.update("A1:B1", [["Item", "Price"]])

    # Ensure a Sessions sheet exists ("keep me signed in" tokens)
    try:
        se = ss.worksheet("Sessions")
    except gspread.exceptions.WorksheetNotFound:
        se = ss.add_worksheet(title="Sessions", rows=500, cols=5)
        se.update("A1:E1", [["Token", "Username", "Role", "Created", "Expiry"]])

    return tx, us, pr, se

main_sheet, user_sheet, price_sheet, session_sheet = get_sheets()

SESSION_DAYS = 30   # how long "keep me signed in" lasts before a phone needs to log in again


def create_session(username: str, role: str) -> str:
    """Create a persistent login token for this device and store it in the Sessions sheet."""
    token  = secrets.token_urlsafe(24)
    expiry = (datetime.now() + timedelta(days=SESSION_DAYS)).isoformat()
    safe_append(session_sheet, [token, username, role, str(datetime.now()), expiry])
    return token


def validate_session(token: str):
    """Return (username, role) if token is valid and not expired, else None.
    Expired tokens are cleaned up when encountered."""
    if not token:
        return None
    try:
        rows = session_sheet.get_all_records()
    except Exception:
        return None
    for i, r in enumerate(rows):
        if str(r.get("Token", "")).strip() == token:
            try:
                expiry = datetime.fromisoformat(str(r.get("Expiry", "")))
            except ValueError:
                return None
            if datetime.now() > expiry:
                try:
                    session_sheet.delete_rows(i + 2)
                except Exception:
                    pass
                return None
            return str(r.get("Username", "")).strip(), str(r.get("Role", "")).strip().lower()
    return None


def delete_session(token: str):
    """Remove a token from the Sessions sheet (used on logout)."""
    if not token:
        return
    try:
        rows = session_sheet.get_all_records()
        for i, r in enumerate(rows):
            if str(r.get("Token", "")).strip() == token:
                session_sheet.delete_rows(i + 2)
                return
    except Exception:
        pass


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
TX_COLS = ["Timestamp", "Username", "Item", "Type", "QTY", "Unit",
           "Start Bill", "End Bill", "Vehicle", "Location", "To Location", "Shift"]

@st.cache_data(ttl=60)
def load_data():
    records = main_sheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=TX_COLS)
    df = pd.DataFrame(records)

    # Normalise column names: strip whitespace, fix common casing issues
    df.columns = [str(c).strip() for c in df.columns]
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
        "location": "Location", "area": "Location",
        "to location": "To Location", "to area": "To Location",
        "shift": "Shift",
    }
    df.rename(columns={c: col_aliases[c.lower()] for c in df.columns
                       if c.lower() in col_aliases}, inplace=True)

    for col in TX_COLS:
        if col not in df.columns:
            df[col] = ""

    df["QTY"] = pd.to_numeric(df["QTY"], errors="coerce").fillna(0)

    # Old rows without a location belong to the Factory by default
    df["Location"] = df["Location"].replace("", pd.NA).fillna(DEFAULT_LOCATION)

    def _net(r):
        if r["Type"] in ("OPENING", "PRODUCTION", "PURCHASE"):
            return r["QTY"]
        if r["Type"] == "TRANSFER":
            return 0
        if r["Type"] == "ADJUSTMENT":
            return r["QTY"]          # signed: +ve adds stock, -ve removes
        return -r["QTY"]             # DISPATCH
    df["Net"] = df.apply(_net, axis=1)
    return df


@st.cache_data(ttl=120)
def load_users():
    rows = user_sheet.get_all_records()
    return {
        r["Username"].strip(): {
            "password": str(r["Password"]).strip(),
            "role": str(r["Role"]).strip().lower()
        }
        for r in rows
    }


@st.cache_data(ttl=120)
def load_prices():
    """Item -> price. Admin-only data; never rendered for other roles."""
    rows = price_sheet.get_all_records()
    out = {}
    for r in rows:
        item = str(r.get("Item", "")).strip()
        if item:
            try:
                out[item] = float(r.get("Price", 0) or 0)
            except (TypeError, ValueError):
                out[item] = 0.0
    return out


def get_summary(df):
    """Current TOTAL stock per item (all areas combined)."""
    if df.empty:
        return pd.DataFrame(columns=["Item", "Unit", "Stock"])
    s = df.groupby(["Item", "Unit"])["Net"].sum().reset_index()
    s.columns = ["Item", "Unit", "Stock"]
    s["Stock"] = s["Stock"].round(2)
    return s


def get_location_ledger(df):
    """Expand transactions into per-area effects.
    IN types add at Location, DISPATCH subtracts at Location,
    TRANSFER subtracts at Location and adds at To Location."""
    if df.empty:
        return pd.DataFrame(columns=["Item", "Unit", "Location", "Qty"])
    rows = []
    for _, r in df.iterrows():
        loc = r["Location"] if r["Location"] in LOCATIONS else DEFAULT_LOCATION
        if r["Type"] in ("OPENING", "PRODUCTION", "PURCHASE"):
            rows.append((r["Item"], r["Unit"], loc, r["QTY"]))
        elif r["Type"] == "DISPATCH":
            rows.append((r["Item"], r["Unit"], loc, -r["QTY"]))
        elif r["Type"] == "TRANSFER":
            to = r["To Location"] if r["To Location"] in LOCATIONS else DEFAULT_LOCATION
            rows.append((r["Item"], r["Unit"], loc, -r["QTY"]))
            rows.append((r["Item"], r["Unit"], to, r["QTY"]))
        elif r["Type"] == "ADJUSTMENT":
            rows.append((r["Item"], r["Unit"], loc, r["QTY"]))   # signed
    led = pd.DataFrame(rows, columns=["Item", "Unit", "Location", "Qty"])
    return led


def get_location_summary(df):
    """Stock per item per area."""
    led = get_location_ledger(df)
    if led.empty:
        return pd.DataFrame(columns=["Item", "Unit", "Location", "Stock"])
    s = led.groupby(["Item", "Unit", "Location"])["Qty"].sum().reset_index()
    s.columns = ["Item", "Unit", "Location", "Stock"]
    s["Stock"] = s["Stock"].round(2)
    return s


def stock_at(loc_summary, item, location):
    """Available qty of an item at one area."""
    if loc_summary.empty:
        return 0.0
    m = loc_summary[(loc_summary["Item"] == item) &
                    (loc_summary["Location"] == location)]
    return float(m["Stock"].sum())


def item_unit_map(df):
    m = {}
    if df.empty:
        return m
    for _, r in df.iterrows():
        if r["Item"] and r["Item"] not in m and str(r.get("Unit", "")).strip():
            m[r["Item"]] = str(r["Unit"]).strip()
    return m


# ─────────────────────────────────────────────
# CATEGORIES  (derived — no schema change)
# ─────────────────────────────────────────────
CATEGORIES = [
    "ISI Pipes", "Non-ISI Pipes", "Branded Pipes",
    "Fittings & Accessories", "Raw Material", "Other"
]

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
# DUPLICATE-NAME GUARD
# ─────────────────────────────────────────────
def _norm_name(s: str) -> str:
    """Normalise for comparison: lowercase, collapse spaces, unify mm/mil spacing."""
    s = s.lower().strip()
    s = s.replace(".", " ").replace("-", " ").replace("/", " ")
    s = " ".join(s.split())
    for u in ["mm", "mil", "cm", "kg", "mts", "mtr"]:
        s = s.replace(f" {u}", u)
    return s

def find_similar_items(name: str, existing: list, threshold: float = 0.72):
    """Return existing item names that look like `name` (possible duplicates)."""
    n = _norm_name(name)
    hits = []
    for e in existing:
        en = _norm_name(e)
        if n == en:
            hits.append((e, 1.0))
            continue
        ratio = difflib.SequenceMatcher(None, n, en).ratio()
        # also catch containment: "16 round isi" inside "16mm round isi pipe"
        if ratio >= threshold or n in en or en in n:
            hits.append((e, ratio))
    hits.sort(key=lambda x: -x[1])
    return [h[0] for h in hits[:5]]


# ─────────────────────────────────────────────
# LOGIN  (with "keep me signed in" so a phone doesn't ask every time)
# ─────────────────────────────────────────────
for k, v in [("logged_in", False), ("username", ""), ("role", ""), ("token", None)]:
    if k not in st.session_state:
        st.session_state[k] = v

# Try auto-login from a saved token before showing the login form
if not st.session_state.logged_in:
    url_token = st.query_params.get("t")
    if url_token:
        result = validate_session(url_token)
        if result:
            st.session_state.username  = result[0]
            st.session_state.role      = result[1]
            st.session_state.logged_in = True
            st.session_state.token     = url_token

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
    keep  = st.checkbox("Keep me signed in on this phone", value=True)
    st.caption("With this on, you won't need to log in again next time you open the app.")

    if st.button("Login", use_container_width=True, type="primary"):
        u = uname.strip()
        p = pwd.strip()
        if u in users and users[u]["password"] == p:
            st.session_state.logged_in = True
            st.session_state.username  = u
            st.session_state.role      = users[u]["role"]

            if keep:
                token = create_session(u, users[u]["role"])
                st.session_state.token = token
                components.html(f"""
                <script>
                (function() {{
                  const win = window.parent;
                  localStorage.setItem('evergreen_token', '{token}');
                  const url = new URL(win.location.href);
                  url.searchParams.set('t', '{token}');
                  win.history.replaceState(null, '', url.toString());
                }})();
                </script>
                """, height=0, width=0)
            st.rerun()
        else:
            st.error("Wrong username or password")
    st.stop()

# Role normalisation: anything that isn't sales/admin works the factory pages
ROLE = st.session_state.role
if ROLE not in ("admin", "sales"):
    ROLE = "factory"


# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
c1, c2 = st.columns([7, 1])
with c1:
    st.markdown(
        f"<div class='topbar'>"
        f"<span class='topbar-title'>🌿 Evergreen</span>"
        f"<span class='topbar-user'>👤 {st.session_state.username} · {ROLE}</span>"
        f"</div>",
        unsafe_allow_html=True
    )
with c2:
    st.markdown("<div style='padding-top:8px'></div>", unsafe_allow_html=True)
    if st.button("Logout", use_container_width=True):
        if st.session_state.get("token"):
            delete_session(st.session_state.token)
        components.html("""
        <script>
        (function() {
          const win = window.parent;
          localStorage.removeItem('evergreen_token');
          const url = new URL(win.location.href);
          url.searchParams.delete('t');
          win.history.replaceState(null, '', url.toString());
        })();
        </script>
        """, height=0, width=0)
        for k in ["logged_in","username","role","token","dispatch_items",
                  "stockin_items","factory_page","admin_page"]:
            st.session_state.pop(k, None)
        st.rerun()


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
df          = load_data()
summary     = get_summary(df)
loc_summary = get_location_summary(df)
units       = item_unit_map(df)
items       = sorted(df["Item"].unique().tolist()) if not df.empty else []


# ─────────────────────────────────────────────
# SHARED RENDERERS  (never show price outside admin)
# ─────────────────────────────────────────────
def render_summary_page(title="📦 Stock Summary", show_export=False):
    """Total stock per item — what the sales role sees before confirming orders."""
    st.markdown(f"#### {title}")
    if summary.empty:
        st.info("No stock data yet.")
        return

    total = len(summary)
    out   = int((summary["Stock"] <= 0).sum())
    isi_items = [i for i in summary["Item"] if "isi" in i.lower()]
    isi_stock = int(summary[summary["Item"].isin(isi_items)]["Stock"].sum())

    m1, m2, m3 = st.columns(3)
    m1.metric("Total SKUs",   total)
    m2.metric("Out of Stock", out)
    m3.metric("ISI Rolls",    isi_stock)

    st.markdown("---")

    search   = st.text_input("🔍 Search", placeholder="Item name…",
                             label_visibility="collapsed", key="sum_search")
    cat_pick = st.selectbox("Category", ["All"] + CATEGORIES,
                            label_visibility="collapsed", key="sum_cat")

    view = summary.copy()
    if search:
        view = view[view["Item"].str.contains(search, case=False, na=False)]
    view["_cat"] = view["Item"].apply(guess_category)
    if cat_pick != "All":
        view = view[view["_cat"] == cat_pick]

    if view.empty:
        st.caption("No items match.")
        return

    st.caption(f"{len(view)} item(s)")
    for cat, grp in view.groupby("_cat"):
        st.markdown(f"<div class='sec-head'>{cat}</div>", unsafe_allow_html=True)
        for _, row in grp.sort_values("Item").iterrows():
            q   = row["Stock"]
            cls = "qty-zero" if q <= 0 else ("qty-low" if q <= 10 else "qty-ok")
            st.markdown(
                f"<div class='item-row'>"
                f"  <div><div class='item-name'>{row['Item']}</div></div>"
                f"  <div class='{cls}'>{q:g} {row['Unit']}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

    if show_export:
        st.markdown("---")
        export = view.rename(columns={"_cat": "Category"})[["Category", "Item", "Unit", "Stock"]]
        csv = export.sort_values(["Category", "Item"]).to_csv(index=False).encode()
        st.download_button("⬇️ Download Stock CSV", csv, "stock_summary.csv", "text/csv",
                           use_container_width=True, key="summary_csv")


def render_stock_by_area():
    """Area-wise stock — what the factory role works from."""
    st.markdown("#### 📦 Stock by Area")
    if loc_summary.empty:
        st.info("No stock data yet — add items via **Stock In**.")
        return

    area_pick = st.selectbox("Area", ["All areas"] + LOCATIONS, key="area_pick")

    search   = st.text_input("🔍 Search", placeholder="Item name…",
                             label_visibility="collapsed", key="area_search")
    cat_pick = st.selectbox("Category", ["All"] + CATEGORIES,
                            label_visibility="collapsed", key="area_cat")

    if area_pick == "All areas":
        # Pivot: one row per item, one column per area + total
        pivot = loc_summary.pivot_table(index=["Item", "Unit"],
                                        columns="Location", values="Stock",
                                        aggfunc="sum", fill_value=0).reset_index()
        for loc in LOCATIONS:
            if loc not in pivot.columns:
                pivot[loc] = 0
        pivot["Total"] = pivot[LOCATIONS].sum(axis=1).round(2)

        view = pivot.copy()
        if search:
            view = view[view["Item"].str.contains(search, case=False, na=False)]
        view["Category"] = view["Item"].apply(guess_category)
        if cat_pick != "All":
            view = view[view["Category"] == cat_pick]

        if view.empty:
            st.caption("No items match.")
            return
        st.dataframe(
            view[["Category", "Item", "Unit"] + LOCATIONS + ["Total"]]
                .sort_values(["Category", "Item"]).reset_index(drop=True),
            use_container_width=True, height=480
        )
    else:
        view = loc_summary[loc_summary["Location"] == area_pick].copy()
        if search:
            view = view[view["Item"].str.contains(search, case=False, na=False)]
        view["_cat"] = view["Item"].apply(guess_category)
        if cat_pick != "All":
            view = view[view["_cat"] == cat_pick]
        view = view[view["Stock"] != 0]

        if view.empty:
            st.caption(f"No stock at {area_pick}.")
            return
        st.caption(f"{len(view)} item(s) at {area_pick}")
        for cat, grp in view.groupby("_cat"):
            st.markdown(f"<div class='sec-head'>{cat}</div>", unsafe_allow_html=True)
            for _, row in grp.sort_values("Item").iterrows():
                q   = row["Stock"]
                cls = "qty-zero" if q <= 0 else ("qty-low" if q <= 10 else "qty-ok")
                st.markdown(
                    f"<div class='item-row'>"
                    f"  <div><div class='item-name'>{row['Item']}</div></div>"
                    f"  <div class='{cls}'>{q:g} {row['Unit']}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )


def render_stock_in():
    st.markdown("#### ⬇️ Stock In")
    st.caption("Set type and area once, add all items from this run, submit together.")

    if "stockin_items" not in st.session_state:
        st.session_state.stockin_items = []

    # ── Common details for the whole batch ──
    txn_label = st.radio(
        "What are you recording?",
        ["Production (made in factory)", "Purchase (received from supplier)", "Opening Balance"],
        horizontal=True, key="in_txn_label"
    )
    TYPE_MAP = {
        "Production (made in factory)":        "PRODUCTION",
        "Purchase (received from supplier)":   "PURCHASE",
        "Opening Balance":                     "OPENING",
    }
    in_type = TYPE_MAP[txn_label]

    in_shift = ""
    if in_type == "PRODUCTION":
        in_shift = st.radio("Shift", ["A", "B"], horizontal=True, key="in_shift")

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        in_loc = st.selectbox("Store at area", LOCATIONS, key="in_loc")
    with col_c2:
        in_remark = st.text_input("Remark for this batch (optional)",
                                  placeholder="Batch no., supplier…", key="in_remark")

    st.markdown("---")
    st.markdown("**Add items to this batch**")

    in_cat = st.selectbox("Filter by category", ["— All —"] + CATEGORIES, key="in_cat")
    if in_cat != "— All —":
        cat_items = [i for i in items if guess_category(i) == in_cat]
    else:
        cat_items = items

    options  = cat_items + ["➕ New item…"]
    sel_item = st.selectbox("Item", options, key="in_item")
    is_new   = sel_item == "➕ New item…"

    dup_matches = []
    if is_new:
        new_name  = st.text_input("Item Name", key="in_new_name")
        new_unit  = st.selectbox("Unit", ["Roll","Bag","Box","Nos","Piece","Set","Kg","Mts"],
                                 key="in_new_unit")
        item_name = new_name.strip()
        item_unit = new_unit

        # ── Duplicate-name guard ──
        if item_name:
            dup_matches = find_similar_items(item_name, items)
            if dup_matches:
                st.warning("⚠️ Similar item(s) already exist — using an existing item "
                           "keeps stock in one place:")
                use_existing = st.selectbox(
                    "Use existing item instead?",
                    ["— No, this is a different item —"] + dup_matches,
                    key="in_dup_pick"
                )
                if use_existing != "— No, this is a different item —":
                    item_name = use_existing
                    item_unit = units.get(use_existing, new_unit)
                    is_new    = False
                    st.info(f"Using existing item: **{item_name}**")
    else:
        item_name = sel_item
        item_unit = units.get(sel_item, "")
        here  = stock_at(loc_summary, sel_item, in_loc)
        total = summary[summary["Item"] == sel_item]["Stock"].sum() if not summary.empty else 0
        st.info(f"At {in_loc}: **{here:g} {item_unit}** · All areas: **{total:g} {item_unit}**")

    col_q1, col_q2 = st.columns([2, 1])
    with col_q1:
        in_qty = st.number_input("Quantity", min_value=0.5, step=0.5, key="in_qty")
    with col_q2:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        add_in = st.button("➕ Add", use_container_width=True, key="in_add")

    if add_in:
        if not item_name:
            st.error("Enter item name.")
        elif not item_unit:
            st.error("Enter unit.")
        elif in_qty <= 0:
            st.error("Quantity must be > 0.")
        elif any(r["item"] == item_name for r in st.session_state.stockin_items):
            st.error(f"{item_name} is already in this batch — delete it below to change the qty.")
        else:
            st.session_state.stockin_items.append({
                "item": item_name,
                "qty":  in_qty,
                "unit": item_unit,
                "new":  is_new,
            })
            st.rerun()

    # ── Current batch ──
    if st.session_state.stockin_items:
        st.markdown("---")
        shift_txt = f", Shift {in_shift}" if in_shift else ""
        st.markdown(f"**Current batch ({txn_label.split(' ')[0]}{shift_txt}, at {in_loc}):**")
        for idx, row in enumerate(st.session_state.stockin_items):
            col_r1, col_r2 = st.columns([5, 1])
            with col_r1:
                tag = " <span style='color:#e65100;font-size:11px'>(new item)</span>" if row["new"] else ""
                st.markdown(
                    f"<div class='disp-item'>"
                    f"<span><b>{row['item']}</b>{tag}</span>"
                    f"<span>{row['qty']} {row['unit']}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )
            with col_r2:
                if st.button("🗑️", key=f"in_del_{idx}"):
                    st.session_state.stockin_items.pop(idx)
                    st.rerun()

        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("Clear Batch", use_container_width=True, key="in_clear"):
                st.session_state.stockin_items = []
                st.rerun()
        with col_s2:
            if st.button("✅ Submit Batch", use_container_width=True, type="primary",
                         key="in_submit"):
                failed = False
                for row in st.session_state.stockin_items:
                    ok = safe_append(main_sheet, [
                        str(datetime.now()),
                        st.session_state.username,
                        row["item"],
                        in_type,
                        row["qty"],
                        row["unit"],
                        in_remark,   # reusing Start Bill column for remark on non-dispatch rows
                        "",
                        "",
                        in_loc,
                        "",
                        in_shift
                    ])
                    if not ok:
                        failed = True
                if failed:
                    st.error("Some items failed to save. Check Google Sheets — "
                             "saved items will appear in History; re-add only the missing ones.")
                else:
                    n = len(st.session_state.stockin_items)
                    load_data.clear()
                    st.session_state.stockin_items = []
                    st.success(f"✅ {n} item(s) recorded at {in_loc}.")
                    st.rerun()
    else:
        st.caption("No items added yet.")


def render_dispatch():
    st.markdown("#### 🚚 Dispatch")
    st.caption("Set bill and area once, add all items in this load, dispatch together.")

    if "dispatch_items" not in st.session_state:
        st.session_state.dispatch_items = []

    disp_loc = st.selectbox("Dispatch from area", LOCATIONS, key="disp_loc")

    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        start_bill = st.text_input("Start Bill No.")
    with col_b2:
        end_bill   = st.text_input("End Bill No.")
    with col_b3:
        vehicle    = st.text_input("Vehicle No.")

    st.markdown("---")
    st.markdown("**Add items to this load**")

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
        in_load   = sum(i["qty"] for i in st.session_state.dispatch_items
                        if i["item"] == disp_item and i["loc"] == disp_loc)
        available = stock_at(loc_summary, disp_item, disp_loc) - in_load
        if disp_qty > available:
            st.error(f"Only {available:g} available at {disp_loc} "
                     f"(including items already in this load).")
        else:
            st.session_state.dispatch_items.append({
                "item": disp_item,
                "qty":  disp_qty,
                "unit": units.get(disp_item, ""),
                "loc":  disp_loc
            })
            st.rerun()

    if st.session_state.dispatch_items:
        st.markdown("---")
        st.markdown("**Current load:**")
        for idx, row in enumerate(st.session_state.dispatch_items):
            col_r1, col_r2 = st.columns([5, 1])
            with col_r1:
                st.markdown(
                    f"<div class='disp-item'>"
                    f"<span><b>{row['item']}</b> <span style='color:#999'>({row['loc']})</span></span>"
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
                            vehicle,
                            row["loc"],
                            "",
                            ""
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


def render_transfer():
    st.markdown("#### 🔄 Transfer Between Areas")
    st.caption("Move stock from one area to another — total stock across all areas stays the same.")

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        from_loc = st.selectbox("From area", LOCATIONS, key="tr_from")
    with col_t2:
        to_opts = [l for l in LOCATIONS if l != from_loc]
        to_loc  = st.selectbox("To area", to_opts, key="tr_to")

    tr_cat = st.selectbox("Filter by category", ["— All —"] + CATEGORIES, key="tr_cat")
    if tr_cat != "— All —":
        tr_items = [i for i in items if guess_category(i) == tr_cat]
    else:
        tr_items = items

    # Only items with stock at the source area
    tr_items = [i for i in tr_items if stock_at(loc_summary, i, from_loc) > 0]

    if not tr_items:
        st.info(f"No stock available at {from_loc}.")
        return

    tr_item = st.selectbox("Item", tr_items, key="tr_item")
    avail   = stock_at(loc_summary, tr_item, from_loc)
    st.caption(f"Available at {from_loc}: **{avail:g} {units.get(tr_item,'')}**")

    tr_qty    = st.number_input("Quantity", min_value=0.5, step=0.5, key="tr_qty")
    tr_remark = st.text_input("Remark (optional)", key="tr_remark",
                              placeholder="Reason, vehicle, person…")

    if st.button("🔄 Submit Transfer", use_container_width=True, type="primary"):
        if tr_qty <= 0:
            st.error("Quantity must be > 0.")
        elif tr_qty > avail:
            st.error(f"Only {avail:g} available at {from_loc}.")
        else:
            ok = safe_append(main_sheet, [
                str(datetime.now()),
                st.session_state.username,
                tr_item,
                "TRANSFER",
                tr_qty,
                units.get(tr_item, ""),
                tr_remark,
                "",
                "",
                from_loc,
                to_loc,
                ""
            ])
            if ok:
                load_data.clear()
                st.success(f"Moved {tr_qty:g} {tr_item}: {from_loc} → {to_loc}")
                st.rerun()
            else:
                st.error("Failed to save. Check your connection and try again.")


def render_history():
    st.markdown("#### 📋 Transaction History")

    if df.empty:
        st.info("No transactions yet.")
        return

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        h_search = st.text_input("🔍 Search", placeholder="Item name, user…", key="h_search")
    with col_f2:
        h_type   = st.selectbox("Type", ["All","PRODUCTION","PURCHASE","OPENING","DISPATCH","TRANSFER","ADJUSTMENT"], key="h_type")

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

    for _, r in hist.iterrows():
        if r["Type"] == "TRANSFER":
            cls    = "log-move"
            prefix = "⇄ "
            loctxt = f"{r['Location']} → {r['To Location']}"
        elif r["Type"] == "ADJUSTMENT":
            cls    = "log-in" if r["QTY"] >= 0 else "log-out"
            prefix = "±"
            loctxt = r["Location"]
        else:
            is_in  = r["Type"] in ("PRODUCTION","PURCHASE","OPENING")
            cls    = "log-in" if is_in else "log-out"
            prefix = "+" if is_in else "−"
            loctxt = r["Location"]
        ts   = str(r["Timestamp"])[:16]
        bill = f"Bill {r.get('Start Bill','')}–{r.get('End Bill','')}" \
               if r["Type"] == "DISPATCH" and r.get("Start Bill") else ""
        shift = f" (Shift {r['Shift']})" if str(r.get("Shift", "")).strip() else ""
        meta = f"{r['Type']}{shift} · {loctxt} · {r['Username']} · {ts}" + (f" · {bill}" if bill else "")
        if r.get("Vehicle"):
            meta += f" · {r['Vehicle']}"
        st.markdown(
            f"<div class='log-row'>"
            f"  <div><div style='font-weight:500'>{r['Item']}</div>"
            f"      <div class='log-meta'>{meta}</div></div>"
            f"  <div class='{cls}'>{prefix}{r['QTY']:g} {r['Unit']}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

    st.caption(f"{len(hist)} records shown")

    if ROLE == "admin":
        csv = hist.drop(columns=["Net","_d"], errors="ignore").to_csv(index=False).encode()
        st.download_button("⬇️ Export CSV", csv, "transactions.csv", "text/csv",
                           use_container_width=True)


def render_change_password():
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


def render_prices_and_value():
    """ADMIN ONLY — item prices and stock valuation."""
    st.markdown("#### 💰 Prices & Stock Value")
    st.caption("Prices are visible only to admin. Factory and sales never see this page.")

    prices = load_prices()

    if summary.empty:
        st.info("No stock data yet.")
        return

    val = summary.copy()
    val["Category"] = val["Item"].apply(guess_category)
    val["Price"]    = val["Item"].map(prices).fillna(0.0)
    val["Value"]    = (val["Stock"] * val["Price"]).round(2)

    total_value = val["Value"].sum()
    priced      = int((val["Price"] > 0).sum())

    m1, m2 = st.columns(2)
    m1.metric("Total Stock Value", f"₹ {total_value:,.0f}")
    m2.metric("Items with price set", f"{priced} / {len(val)}")

    st.markdown("---")
    st.markdown("**Edit prices** (per unit):")

    editable = val[["Category", "Item", "Unit", "Stock", "Price"]] \
        .sort_values(["Category", "Item"]).reset_index(drop=True)
    edited = st.data_editor(
        editable,
        use_container_width=True,
        height=420,
        disabled=["Category", "Item", "Unit", "Stock"],
        column_config={
            "Price": st.column_config.NumberColumn("Price (₹)", min_value=0.0, step=0.5, format="%.2f"),
        },
        key="price_editor"
    )

    if st.button("💾 Save Prices", use_container_width=True, type="primary"):
        rows = [["Item", "Price"]]
        for _, r in edited.iterrows():
            try:
                p = float(r["Price"])
            except (TypeError, ValueError):
                p = 0.0
            rows.append([r["Item"], p])
        try:
            price_sheet.clear()
            price_sheet.update(f"A1:B{len(rows)}", rows)
            load_prices.clear()
            st.success("Prices saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save prices: {e}")

    st.markdown("---")
    st.markdown("**Valuation table:**")
    show = val[["Category","Item","Unit","Stock","Price","Value"]] \
        .sort_values(["Category","Item"]).reset_index(drop=True)
    st.dataframe(show, use_container_width=True, height=400)
    csv = show.to_csv(index=False).encode()
    st.download_button("⬇️ Download Valuation CSV", csv, "stock_valuation.csv",
                       "text/csv", use_container_width=True)


def render_reconcile():
    """ADMIN ONLY — enter physical counts, see variance, post adjustments."""
    st.markdown("#### 🔍 Physical Count & Reconciliation")
    st.caption("Enter today's physical count. Leave a row blank to skip it. "
               "Submitting posts ADJUSTMENT entries so system stock matches reality.")

    if summary.empty:
        st.info("No stock data yet.")
        return

    rec_mode = st.radio("Counting", ["By area", "Total (all areas combined)"],
                        horizontal=True, key="rec_mode")

    if rec_mode == "By area":
        rec_loc = st.selectbox("Area being counted", LOCATIONS, key="rec_loc")
        base = loc_summary[loc_summary["Location"] == rec_loc][["Item", "Unit", "Stock"]].copy()
        # include items that exist but have zero at this area
        known = summary[["Item", "Unit"]].copy()
        base = known.merge(base, on=["Item", "Unit"], how="left").fillna({"Stock": 0})
    else:
        rec_loc = DEFAULT_LOCATION   # total-mode adjustments post at Factory
        base = summary[["Item", "Unit", "Stock"]].copy()

    rec_cat = st.selectbox("Filter by category", ["— All —"] + CATEGORIES, key="rec_cat")
    base["Category"] = base["Item"].apply(guess_category)
    if rec_cat != "— All —":
        base = base[base["Category"] == rec_cat]

    base = base.rename(columns={"Stock": "System"})
    base["Physical"] = None
    base = base[["Category", "Item", "Unit", "System", "Physical"]] \
        .sort_values(["Category", "Item"]).reset_index(drop=True)

    edited = st.data_editor(
        base,
        use_container_width=True,
        height=440,
        disabled=["Category", "Item", "Unit", "System"],
        column_config={
            "Physical": st.column_config.NumberColumn("Physical Count", min_value=0, step=0.5),
        },
        key=f"rec_editor_{rec_mode}_{rec_loc}_{rec_cat}"
    )

    counted = edited.dropna(subset=["Physical"]).copy()
    if counted.empty:
        st.caption("Enter counts above to see variance.")
        return

    counted["Variance"] = (pd.to_numeric(counted["Physical"], errors="coerce")
                           - counted["System"]).round(2)
    diffs = counted[counted["Variance"] != 0]

    st.markdown("---")
    m1, m2, m3 = st.columns(3)
    m1.metric("Items counted", len(counted))
    m2.metric("Matching", len(counted) - len(diffs))
    m3.metric("With variance", len(diffs))

    if diffs.empty:
        st.success("✅ All counted items match system stock. Nothing to adjust.")
        return

    st.markdown("**Variances found:**")
    for _, r in diffs.iterrows():
        sign = "+" if r["Variance"] > 0 else ""
        cls  = "qty-ok" if r["Variance"] > 0 else "qty-zero"
        st.markdown(
            f"<div class='item-row'>"
            f"  <div><div class='item-name'>{r['Item']}</div>"
            f"  <div class='item-spec'>System {r['System']:g} → Physical {r['Physical']:g}</div></div>"
            f"  <div class='{cls}'>{sign}{r['Variance']:g} {r['Unit']}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

    csv = counted[["Category","Item","Unit","System","Physical","Variance"]] \
        .to_csv(index=False).encode()
    st.download_button("⬇️ Download Reconciliation CSV", csv,
                       f"reconciliation_{datetime.now().strftime('%d-%m-%Y')}.csv",
                       "text/csv", use_container_width=True)

    rec_remark = st.text_input("Remark for adjustments",
                               value=f"Physical count {datetime.now().strftime('%d/%m/%Y')}",
                               key="rec_remark")

    st.warning(f"This will post **{len(diffs)} ADJUSTMENT** entries "
               f"at **{rec_loc if rec_mode == 'By area' else 'Factory (total mode)'}**. "
               "Review the variances above first.")
    confirm = st.checkbox("I have verified these counts are correct", key="rec_confirm")

    if st.button("📝 Post Adjustments", use_container_width=True, type="primary",
                 disabled=not confirm):
        failed = False
        for _, r in diffs.iterrows():
            ok = safe_append(main_sheet, [
                str(datetime.now()),
                st.session_state.username,
                r["Item"],
                "ADJUSTMENT",
                float(r["Variance"]),        # signed
                r["Unit"],
                rec_remark,
                "",
                "",
                rec_loc,
                "",
                ""
            ])
            if not ok:
                failed = True
        if failed:
            st.error("Some adjustments failed to save. Check Google Sheets and re-run — "
                     "already-posted items will now show zero variance.")
        else:
            load_data.clear()
            st.success(f"✅ Posted {len(diffs)} adjustments. Stock now matches physical count.")
            st.rerun()


def render_daily_report():
    """ADMIN ONLY — day-wise production (by shift) and dispatch as an Excel download."""
    st.markdown("#### 📅 Daily Report")
    st.caption("Day-wise production (Shift A / B) and dispatch, as separate sheets in one Excel file.")

    if df.empty:
        st.info("No transactions yet.")
        return

    d = df.copy()
    d["Date"] = pd.to_datetime(d["Timestamp"], errors="coerce").dt.date
    d = d.dropna(subset=["Date"])

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        r_from = st.date_input("From", value=d["Date"].min(), key="rep_from")
    with col_r2:
        r_to   = st.date_input("To", value=d["Date"].max(), key="rep_to")

    d = d[(d["Date"] >= r_from) & (d["Date"] <= r_to)]

    prod = d[d["Type"] == "PRODUCTION"].copy()
    disp = d[d["Type"] == "DISPATCH"].copy()

    m1, m2 = st.columns(2)
    m1.metric("Production entries", len(prod))
    m2.metric("Dispatch entries", len(disp))

    if prod.empty and disp.empty:
        st.info("No production or dispatch in this date range.")
        return

    # ── Build the workbook in memory ──
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:

        # Sheet 1: Production (flat, day-wise, shift-wise)
        if not prod.empty:
            p = prod[["Date", "Shift", "Item", "Unit", "QTY", "Location",
                      "Username", "Start Bill"]].copy()
            p = p.rename(columns={"QTY": "Qty", "Start Bill": "Remark",
                                  "Location": "Area", "Username": "User"})
            p["Shift"] = p["Shift"].replace("", "—")
            p = p.sort_values(["Date", "Shift", "Item"])
            p.to_excel(writer, sheet_name="Production", index=False)

            # Sheet 2: Production pivot — Item rows × Date columns, split by shift
            pv = prod.copy()
            pv["Shift"] = pv["Shift"].replace("", "—")
            pv["Day"] = pd.to_datetime(pv["Date"]).apply(lambda x: x.strftime("%d/%m/%Y"))
            pivot = pv.pivot_table(index=["Item", "Unit"],
                                   columns=["Day", "Shift"],
                                   values="QTY", aggfunc="sum", fill_value=0)
            pivot["Total"] = pivot.sum(axis=1)
            pivot.to_excel(writer, sheet_name="Production Pivot")

        # Sheet 3: Dispatch (flat, day-wise)
        if not disp.empty:
            q = disp[["Date", "Item", "Unit", "QTY", "Location",
                      "Start Bill", "End Bill", "Vehicle", "Username"]].copy()
            q = q.rename(columns={"QTY": "Qty", "Location": "From Area",
                                  "Username": "User"})
            q = q.sort_values(["Date", "Start Bill", "Item"])
            q.to_excel(writer, sheet_name="Dispatch", index=False)

            # Sheet 4: Dispatch daily totals per item
            dd = disp.copy()
            dd["Day"] = pd.to_datetime(dd["Date"]).apply(lambda x: x.strftime("%d/%m/%Y"))
            dv = dd.pivot_table(index=["Item", "Unit"], columns="Day",
                                values="QTY", aggfunc="sum", fill_value=0)
            dv["Total"] = dv.sum(axis=1)
            dv.to_excel(writer, sheet_name="Dispatch Pivot")

        # Auto-fit column widths
        for ws in writer.book.worksheets:
            for col_cells in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0
                            for c in col_cells) + 2
                ws.column_dimensions[col_cells[0].column_letter].width = min(width, 32)

    buf.seek(0)
    fname = f"Evergreen_Daily_Report_{r_from.strftime('%d-%m-%Y')}_to_{r_to.strftime('%d-%m-%Y')}.xlsx"
    st.download_button("⬇️ Download Excel Report", buf, fname,
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True, type="primary")

    # Quick on-screen preview
    if not prod.empty:
        st.markdown("**Production preview:**")
        prev = prod.groupby(["Date", "Shift", "Item", "Unit"])["QTY"].sum().reset_index()
        prev["Shift"] = prev["Shift"].replace("", "—")
        st.dataframe(prev.sort_values(["Date", "Shift", "Item"]),
                     use_container_width=True, height=260, hide_index=True)
    if not disp.empty:
        st.markdown("**Dispatch preview:**")
        prev2 = disp.groupby(["Date", "Item", "Unit"])["QTY"].sum().reset_index()
        st.dataframe(prev2.sort_values(["Date", "Item"]),
                     use_container_width=True, height=260, hide_index=True)


def render_admin():
    st.markdown("#### ⚙️ Admin")
    st.caption("For stock figures with export, use the 📊 Summary tab.")

    section = st.radio("", ["Change Password", "Users"], horizontal=True,
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
        st.caption("Registered users (set Role to: admin, sales, or factory):")
        all_users = load_users()
        for u, d in all_users.items():
            st.markdown(f"**{u}** — {d['role']}")


# ─────────────────────────────────────────────
# TAP-ONCE HOME MENU
# One tap to pick a screen, one tap ("← Menu") to come back — no tabs
# to search through. The menu is shown fresh every time the app opens.
# ─────────────────────────────────────────────
def render_home_menu(sections, state_key):
    """sections: list of (section_title or None, [(icon_label, page_key), ...])"""
    st.markdown(
        f"<p style='text-align:center;color:#888;font-size:13px;margin:2px 0 18px'>"
        f"What would you like to do, {st.session_state.username}?</p>",
        unsafe_allow_html=True
    )
    for title, tiles in sections:
        if title:
            st.markdown(f"<div class='sec-head'>{title}</div>", unsafe_allow_html=True)
        for row_start in range(0, len(tiles), 2):
            cols = st.columns(2)
            for col, (label, page_key) in zip(cols, tiles[row_start:row_start + 2]):
                with col:
                    if st.button(label, use_container_width=True, key=f"menu_{page_key}"):
                        st.session_state[state_key] = page_key
                        st.rerun()


def render_with_back(state_key, render_fn):
    if st.button("← Menu", key=f"back_{state_key}"):
        st.session_state[state_key] = None
        st.rerun()
    render_fn()


# ─────────────────────────────────────────────
# PAGES BY ROLE
# ─────────────────────────────────────────────
if ROLE == "sales":
    # ── Sales — a single screen, nothing to navigate at all ──
    render_summary_page("📦 Stock Summary")
    st.markdown("---")
    render_change_password()

elif ROLE == "factory":
    if "factory_page" not in st.session_state:
        st.session_state.factory_page = None

    FACTORY_MENU = [
        (None, [
            ("📦 Stock",     "stock"),
            ("⬇️ Stock In",  "in"),
            ("🚚 Dispatch",  "out"),
            ("🔄 Transfer",  "transfer"),
            ("📋 History",   "history"),
        ]),
    ]
    FACTORY_PAGES = {
        "stock":    render_stock_by_area,
        "in":       render_stock_in,
        "out":      render_dispatch,
        "transfer": render_transfer,
        "history":  render_history,
    }

    if st.session_state.factory_page is None:
        render_home_menu(FACTORY_MENU, "factory_page")
        st.markdown("---")
        render_change_password()
    else:
        render_with_back("factory_page", FACTORY_PAGES[st.session_state.factory_page])

else:  # admin
    if "admin_page" not in st.session_state:
        st.session_state.admin_page = None

    ADMIN_MENU = [
        ("Daily Work", [
            ("📦 Stock",      "stock"),
            ("📊 Summary",    "summary"),
            ("⬇️ Stock In",   "in"),
            ("🚚 Dispatch",   "out"),
            ("🔄 Transfer",   "transfer"),
            ("📋 History",    "history"),
        ]),
        ("Admin Tools", [
            ("📅 Report",     "report"),
            ("🔍 Reconcile",  "reconcile"),
            ("💰 Prices",     "prices"),
            ("⚙️ Admin",      "admin"),
        ]),
    ]
    ADMIN_PAGES = {
        "stock":     render_stock_by_area,
        "summary":   lambda: render_summary_page("📊 Stock Summary", show_export=True),
        "in":        render_stock_in,
        "out":       render_dispatch,
        "transfer":  render_transfer,
        "history":   render_history,
        "report":    render_daily_report,
        "reconcile": render_reconcile,
        "prices":    render_prices_and_value,
        "admin":     render_admin,
    }

    if st.session_state.admin_page is None:
        render_home_menu(ADMIN_MENU, "admin_page")
    else:
        render_with_back("admin_page", ADMIN_PAGES[st.session_state.admin_page])
