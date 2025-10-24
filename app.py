import streamlit as st
import requests
from PIL import Image
from io import BytesIO, StringIO
import pandas as pd
import time
from datetime import date
from base64 import b64decode

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
st.set_page_config(page_title="QR Attendance System", layout="wide")

# 🔹 Replace with your deployed FastAPI backend URL (no trailing slash)
BACKEND_URL = "https://finbackend-r3ex.onrender.com"

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------
def get_headers(role):
    token = st.session_state.get(f"{role}_token")
    return {"Authorization": f"Bearer {token}"} if token else {}

def api_post(endpoint, json=None, headers=None, files=None):
    """Wrapper for safe POST requests."""
    try:
        full_url = f"{BACKEND_URL}{endpoint}"
        st.write(f"📡 POST → {full_url}")  # Debug
        r = requests.post(full_url, json=json, headers=headers, files=files, timeout=30)
        st.write(f"📬 Response: {r.status_code}")  # Debug
        if r.status_code in (200, 201):
            return r.json()
        else:
            st.error(f"Error {r.status_code}: {r.text}")
    except Exception as e:
        st.error(str(e))

def api_get(endpoint, headers=None):
    """Wrapper for safe GET requests."""
    try:
        full_url = f"{BACKEND_URL}{endpoint}"
        r = requests.get(full_url, headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json()
        else:
            st.error(f"Error {r.status_code}: {r.text}")
    except Exception as e:
        st.error(str(e))

# ------------------------------------------------------------
# NAVIGATION
# ------------------------------------------------------------
page = st.sidebar.radio("Navigation", ["HR Dashboard", "Employee Dashboard", "QR Display"])

# ------------------------------------------------------------
# HR DASHBOARD
# ------------------------------------------------------------
if page == "HR Dashboard":
    st.title("👩‍💼 HR Dashboard")

    # ---------- LOGIN / REGISTER ----------
    if "hr_token" not in st.session_state:
        st.subheader("Login / Register")
        mode = st.radio("Action", ["Login", "Register"])
        name = st.text_input("HR Name")
        password = st.text_input("Password", type="password")

        if st.button("Proceed"):
            if mode == "Register":
                # --- Registration flow ---
                payload = {"name": name, "password": password}
                res = api_post("/auth/hr/register", payload)
                if res:
                    st.success("✅ Registered successfully! Please log in now using your credentials.")
                else:
                    st.error("❌ Registration failed. Try again.")
            else:
                # --- Login flow ---
                payload = {"name": name, "password": password}
                res = api_post("/auth/hr/login", payload)
                if res and "access_token" in res:
                    st.session_state.hr_token = res["access_token"]
                    st.success("✅ Logged in successfully!")
                    st.rerun()
                else:
                    st.error("❌ Invalid credentials or login failed.")
    else:
        # ---------- ONCE LOGGED IN ----------
        st.success("HR logged in ✅")

        # ---------- COMPANY CREATION ----------
        st.subheader("🏢 Company Management")
        cname = st.text_input("Company Name")
        lat = st.number_input("Latitude", format="%.5f")
        lon = st.number_input("Longitude", format="%.5f")
        radius = st.number_input("Radius (meters)", value=500)
        if st.button("Create Company"):
            api_post("/company/create",
                     {"name": cname, "latitude": lat, "longitude": lon, "radius_m": radius},
                     headers=get_headers("hr"))

        # ---------- EMPLOYEE MANAGEMENT ----------
        st.subheader("👷 Employee Management")
        with st.expander("Add Single Employee"):
            ename = st.text_input("Employee Name")
            eemail = st.text_input("Employee Email")
            epass = st.text_input("Employee Password", type="password")
            active = st.checkbox("Active", value=True)
            if st.button("Add Employee"):
                api_post("/employee/add",
                         {"name": ename, "email": eemail, "password": epass, "is_active": active},
                         headers=get_headers("hr"))

        with st.expander("Upload Bulk Employees (Excel)"):
            file = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])
            if file and st.button("Upload Excel File"):
                try:
                    res = requests.post(
                        f"{BACKEND_URL}/employee/upload_excel",
                        headers=get_headers("hr"),
                        files={"file": file},
                    )
                    if res.status_code == 200:
                        st.success("✅ Employees uploaded successfully!")
                    else:
                        st.error(res.text)
                except Exception as e:
                    st.error(str(e))

        # ---------- VIEW EMPLOYEES ----------
        st.subheader("📋 View Employees")
        if st.button("Load Employee List"):
            res = api_get("/employee/list", headers=get_headers("hr"))
            if res:
                df = pd.DataFrame(res)
                st.dataframe(df)

        # ---------- ATTENDANCE VIEW ----------
        st.subheader("📊 Company Attendance")
        start = st.date_input("Start Date", value=date.today())
        end = st.date_input("End Date", value=date.today())
        if st.button("Fetch Attendance"):
            res = api_get(f"/attendance/company?start_date={start}&end_date={end}",
                          headers=get_headers("hr"))
            if res:
                st.dataframe(pd.DataFrame(res))
            else:
                st.info("No attendance found for this range.")

        # ---------- EXPORT ATTENDANCE ----------
        st.subheader("📥 Download Attendance (Excel)")
        if st.button("Download Excel"):
            try:
                r = requests.get(f"{BACKEND_URL}/export/attendance", headers=get_headers("hr"))
                if r.status_code == 200:
                    csv_data = StringIO(r.text)
                    df = pd.read_csv(csv_data)
                    excel_buffer = BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                        df.to_excel(writer, index=False, sheet_name="Attendance")
                    st.download_button("⬇️ Download Excel",
                        data=excel_buffer.getvalue(),
                        file_name=f"attendance_{date.today()}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                else:
                    st.error(f"Error {r.status_code}: {r.text}")
            except Exception as e:
                st.error(str(e))

        # ---------- QR MANAGEMENT ----------
        st.subheader("🔁 QR Management")
        if st.button("Regenerate QR"):
            api_post("/qr/regenerate", headers=get_headers("hr"))
            st.success("QR regenerated successfully!")

        # ---------- LOGOUT ----------
        if st.button("Logout HR"):
            del st.session_state["hr_token"]
            st.rerun()


# ------------------------------------------------------------
# EMPLOYEE DASHBOARD (with automatic GPS location capture)
# ------------------------------------------------------------
elif page == "Employee Dashboard":
    import streamlit.components.v1 as components

    st.title("👷 Employee Dashboard")

    # Get QR token from URL query parameters
    qr_token = st.query_params.get("token") if hasattr(st, "query_params") else None
    if not qr_token:
        st.error("⚠️ Please scan the QR code to open this page.")
        st.stop()

    # ---------- EMPLOYEE LOGIN ----------
    if "employee_token" not in st.session_state:
        st.subheader("Login")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
            res = api_post("/auth/employee/login", {"email": email, "password": password})
            if res and "access_token" in res:
                st.session_state.employee_token = res["access_token"]
                st.success("✅ Logged in successfully!")
                st.rerun()
            else:
                st.error("❌ Invalid credentials or login failed.")
    else:
        st.success("Employee logged in ✅")

        # ---------- LOCATION SHARING ----------
        st.subheader("📍 Share Your Location Automatically")

        # Display current location info
        if "location" not in st.session_state:
            st.session_state.location = None

        location_placeholder = st.empty()

        get_location_button = st.button("📍 Get Current Location")

        if get_location_button:
            get_location_js = """
            <script>
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const lat = position.coords.latitude.toFixed(6);
                    const lon = position.coords.longitude.toFixed(6);
                    const loc = lat + "," + lon;
                    window.parent.postMessage({type: 'location', text: loc}, '*');
                },
                (error) => {
                    window.parent.postMessage({type: 'location_error', text: error.message}, '*');
                }
            );
            </script>
            """
            components.html(get_location_js, height=0)

        # Listen for JS messages
        components.html(
            """
            <script>
            window.addEventListener('message', (event) => {
                if (event.data.type === 'location') {
                    const loc = event.data.text;
                    const streamlitInput = window.parent.document.querySelector('iframe[srcdoc*="streamlit"]');
                    if (streamlitInput) {
                        window.parent.postMessage({isStreamlitMessage: true, type: 'streamlit:setSessionState', key: 'location', value: loc}, '*');
                    }
                }
            });
            </script>
            """,
            height=0,
        )

        # Show location if already fetched
        if st.session_state.location:
            try:
                lat, lon = map(float, st.session_state.location.split(","))
                st.success(f"✅ Location shared! Latitude: {lat}, Longitude: {lon}")
            except Exception:
                st.error("⚠️ Error parsing location data.")
        else:
            st.info("Click '📍 Get Current Location' to share your GPS coordinates.")

        # ---------- ATTENDANCE ACTIONS ----------
        st.subheader("🕒 Attendance Actions")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Check In"):
                if not st.session_state.location:
                    st.warning("⚠️ Please share your location first.")
                else:
                    lat, lon = map(float, st.session_state.location.split(","))
                    api_post(
                        "/attendance/checkin",
                        {"token": qr_token, "latitude": lat, "longitude": lon},
                        headers=get_headers("employee"),
                    )

        with col2:
            if st.button("Check Out"):
                if not st.session_state.location:
                    st.warning("⚠️ Please share your location first.")
                else:
                    lat, lon = map(float, st.session_state.location.split(","))
                    api_post(
                        "/attendance/checkout",
                        {"token": qr_token, "latitude": lat, "longitude": lon},
                        headers=get_headers("employee"),
                    )

        # ---------- VIEW MY ATTENDANCE ----------
        st.subheader("📊 View My Attendance")
        start = st.date_input("Start Date", value=date.today(), key="emp_start")
        end = st.date_input("End Date", value=date.today(), key="emp_end")
        if st.button("Get My Attendance"):
            res = api_get(f"/attendance/my?start_date={start}&end_date={end}", headers=get_headers("employee"))
            if res:
                st.dataframe(pd.DataFrame(res))
            else:
                st.info("No records found.")

        # ---------- LOGOUT ----------
        if st.button("Logout Employee"):
            del st.session_state["employee_token"]
            st.rerun()



# ------------------------------------------------------------
# QR DISPLAY (Compact & Fixed)
# ------------------------------------------------------------
else:
    st.title("🏢 Company QR Display")
    st.info("QR auto-refreshes every 30 seconds.")

    company_id = st.number_input("Enter Company ID", min_value=1, step=1)
    qr_placeholder = st.empty()

    if company_id:
        while True:
            qr_res = api_get(f"/qr/current/{company_id}")
            if qr_res:
                img_b64 = qr_res.get("qr_image") or qr_res.get("image_base64")

                if img_b64:
                    try:
                        img_data = b64decode(img_b64)
                        qr_img = Image.open(BytesIO(img_data))

                        # --- Reduce image size ---
                        target_size = (300, 300)  # adjust smaller/larger if you want
                        qr_img = qr_img.resize(target_size)

                        # --- Display neatly centered ---
                        st.markdown("<div style='text-align:center;'>", unsafe_allow_html=True)
                        qr_placeholder.image(
                            qr_img,
                            caption=f"Company ID: {qr_res.get('company_id', company_id)} | Active QR",
                            use_column_width=False
                        )
                        st.markdown("</div>", unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"⚠️ Failed to load QR image: {str(e)}")
                else:
                    st.warning("⚠️ QR image data missing in backend response.")
            else:
                st.warning("⚠️ No active QR found for this company.")

            time.sleep(30)
