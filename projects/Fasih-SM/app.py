import streamlit as st
import os, pickle, time, urllib.parse, requests, pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_data_for_smallcode(smallCode):
    try:
        url = f'https://fasih-sm.bps.go.id/assignment-general/api/assignments/get-principal-values-by-smallest-code/{survey_period_id}/{smallCode}'
        resp = st.session_state.session.get(url, headers=headers)
        if resp.status_code != 200 or not resp.text.strip():
            return [], []

        data = resp.json().get('data', [])
        if not data:
            return [], []

        local_results_assign = data
        local_results_answers = []

        for d in data:
            assignment_id = d.get('assignmentId')
            url_detail = f'https://fasih-sm.bps.go.id/assignment-general/api/assignment/get-by-id-with-data-for-scm?id={assignment_id}'
            resp_detail = sess.get(url_detail, headers=headers)
            if resp_detail.status_code != 200:
                continue

            try:
                detail_json = resp_detail.json()
                inner_str = detail_json.get("data", {}).get("data") if isinstance(detail_json.get("data"), dict) else detail_json.get("data")
                if isinstance(inner_str, str):
                    import json as _json
                    inner_json = _json.loads(inner_str)
                else:
                    inner_json = detail_json.get("data", {})
                answers = inner_json.get("answers", [])
                flat = {}
                for a in answers:
                    k = a.get("dataKey")
                    v = a.get("value") if "value" in a else a.get("dataValue")
                    flat[k] = v
                flat['assignment_id'] = assignment_id
                flat['smallCode'] = smallCode
                local_results_answers.append(flat)
            except Exception:
                continue

        return local_results_assign, local_results_answers
    except Exception as e:
        st.warning(f"Error smallCode {smallCode}: {e}")
        return [], []


# =============== FUNGSI DASAR ===============

def setup_driver() -> webdriver.Chrome:
    service = Service()
    chrome_options = Options()
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    chrome_options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    })
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def get_session_files(folder):
    if not os.path.exists(folder):
        return []
    return [f for f in os.listdir(folder) if f.endswith("_session.pkl")]


def muat_session(folder, username):
    filepath = os.path.join(folder, f"{username}_session.pkl")
    if os.path.exists(filepath):
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        return (
            data.get("headers"),
            data.get("cookies"),
            data.get("session"),
            data.get("password", None),
        )
    return None, None, None, None


def simpan_session(folder, username, headers, cookies, session, password=None):
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, f"{username}_session.pkl")
    with open(filepath, "wb") as f:
        pickle.dump(
            {
                "username": username,
                "password": password,
                "headers": headers,
                "cookies": cookies,
                "session": session,
            },
            f,
        )


def apply_cookies_to_driver(driver, cookies, domain):
    driver.get(f"https://{domain}")
    time.sleep(2)
    for name, value in cookies.items():
        try:
            driver.add_cookie({
                'name': name,
                'value': value,
                'domain': domain,
                'path': '/',
            })
        except Exception:
            pass


# =============== LOGIN ===============

def login_sso(driver, username, password):
    driver.get("https://sso.bps.go.id")
    driver.find_element(By.NAME, "username").send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password)
    driver.find_element(By.XPATH, '//*[@id="kc-login"]').click()
    time.sleep(1)
    # cek apakah diminta OTP
    try:
        otp_element = driver.find_element(By.XPATH, '//*[@id="otp"]')
        otp = st.text_input("Masukkan OTP (cek SMS atau email Anda):", type="password")
        if otp:
            otp_element.send_keys(otp)
            driver.find_element(By.XPATH, '//*[@id="kc-login"]').click()
            st.info("🔑 Login dengan OTP berhasil...")
            time.sleep(3)
    except NoSuchElementException:
        st.success("✅ Login tanpa OTP berhasil")
        time.sleep(2)


def main_login(driver, username, password):
    login_sso(driver, username, password)
    driver.get("https://fasih-sm.bps.go.id/oauth2/authorization/ics")
    time.sleep(3)
    driver.get("https://fasih-sm.bps.go.id/survey-collection/survey")
    time.sleep(3)

    cookies = driver.get_cookies()
    cookie_dict = {c['name']: c['value'] for c in cookies}

    xsrf_token = urllib.parse.unquote(cookie_dict.get("XSRF-TOKEN", ""))
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "X-XSRF-TOKEN": xsrf_token,
        "Referer": "https://fasih-sm.bps.go.id/",
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://fasih-sm.bps.go.id",
    }

    session = requests.Session()
    session.cookies.update(cookie_dict)
    session.headers.update(headers)

    return headers, cookie_dict, session, password

# =============== FUNGSI AMBIL WILAYAH (STREAMLIT-FRIENDLY) ===============

def ambil_semua_sls_smallcode_dari_kabupaten(
    kabupaten_id,
    level_region,
    region_group_id,
    headers,
    cookies,
    region_level1,
    region_level2
):
    st.write("### 🌍 Mengambil semua wilayah dari kabupaten...")
    st.caption(
        "Proses ini akan menelusuri kecamatan, desa, SLS, dan sub-SLS sesuai level region yang tersedia."
    )

    progress_bar = st.progress(0.0)
    status_text = st.empty()

    if not isinstance(level_region, list) or len(level_region) < 3:
        if len(level_region) == 2:
            st.warning("❌ Region level hanya sampai Kabupaten.")
            return pd.DataFrame([region_level2])
        elif len(level_region) == 1:
            st.warning("❌ Region level hanya sampai Provinsi.")
            return pd.DataFrame([region_level1])
        else:
            st.error("❌ Struktur region tidak valid.")
            return pd.DataFrame()

    result = []
    # Ambil semua kecamatan
    try:
        url_kecamatan = (
            f"https://fasih-sm.bps.go.id/region/api/v1/region/level3"
            f"?groupId={region_group_id}&level2Id={kabupaten_id}"
        )
        resp_kec = requests.get(url_kecamatan, headers=headers, cookies=cookies)
        resp_kec.raise_for_status()
        daftar_kecamatan = resp_kec.json().get("data", []) or []
    except Exception as e:
        st.error(f"❌ Gagal mengambil data kecamatan: {e}")
        return pd.DataFrame()

    total_kecamatan = len(daftar_kecamatan)
    if total_kecamatan == 0:
        st.warning("⚠️ Tidak ditemukan kecamatan untuk kabupaten ini.")
        return pd.DataFrame()

    processed_kec = 0

    for kec in daftar_kecamatan:
        processed_kec += 1
        pct = processed_kec / total_kecamatan
        # progress expects number 0..1 or 0..100 — st.progress accepts float 0..1 as well
        try:
            progress_bar.progress(pct)
        except Exception:
            # fallback to percentage int
            progress_bar.progress(int(pct * 100))

        status_text.text(f"📍 Kecamatan {processed_kec}/{total_kecamatan}: {kec.get('name')}")

        kecamatan_id = kec.get("id")
        kecamatan_name = kec.get("name")
        kecamatan_kode = kec.get("fullCode")

        # Jika level hanya sampai kecamatan
        if len(level_region) == 3:
            result.append({
                f"{level_region[2]['name']}_id": kecamatan_id,
                f"{level_region[2]['name']}": kecamatan_name,
                "smallcode": kecamatan_kode,
            })
            continue

        # Ambil desa
        try:
            url_desa = (
                f"https://fasih-sm.bps.go.id/region/api/v1/region/level4"
                f"?groupId={region_group_id}&level3Id={kecamatan_id}"
            )
            resp_desa = requests.get(url_desa, headers=headers, cookies=cookies)
            resp_desa.raise_for_status()
            daftar_desa = resp_desa.json().get("data", []) or []
        except Exception as e:
            st.warning(f"❌ Gagal mengambil desa dari {kecamatan_name}: {e}")
            continue

        for desa in daftar_desa:
            desa_id = desa.get("id")
            desa_name = desa.get("name")
            desa_kode = desa.get("fullCode")

            if len(level_region) == 4:
                result.append({
                    f"{level_region[2]['name']}_id": kecamatan_id,
                    f"{level_region[2]['name']}": kecamatan_name,
                    f"{level_region[3]['name']}_id": desa_id,
                    f"{level_region[3]['name']}": desa_name,
                    "smallcode": desa_kode,
                })
                continue

            # Ambil SLS
            try:
                url_sls = (
                    f"https://fasih-sm.bps.go.id/region/api/v1/region/level5"
                    f"?groupId={region_group_id}&level4Id={desa_id}"
                )
                resp_sls = requests.get(url_sls, headers=headers, cookies=cookies)
                resp_sls.raise_for_status()
                daftar_sls = resp_sls.json().get("data", []) or []
            except Exception as e:
                st.warning(f"❌ Gagal mengambil SLS dari {desa_name}: {e}")
                continue

            for sls in daftar_sls:
                sls_id = sls.get("id")
                sls_name = sls.get("name")
                sls_kode = sls.get("fullCode")

                if len(level_region) == 5:
                    result.append({
                        f"{level_region[2]['name']}_id": kecamatan_id,
                        f"{level_region[2]['name']}": kecamatan_name,
                        f"{level_region[3]['name']}_id": desa_id,
                        f"{level_region[3]['name']}": desa_name,
                        f"{level_region[4]['name']}_id": sls_id,
                        f"{level_region[4]['name']}": sls_name,
                        "smallcode": sls_kode,
                    })
                    continue

                # Ambil SUB SLS
                try:
                    url_subsls = (
                        f"https://fasih-sm.bps.go.id/region/api/v1/region/level6"
                        f"?groupId={region_group_id}&level5Id={sls_id}"
                    )
                    resp_subsls = requests.get(url_subsls, headers=headers, cookies=cookies)
                    resp_subsls.raise_for_status()
                    daftar_subsls = resp_subsls.json().get("data", []) or []
                except Exception as e:
                    st.warning(f"❌ Gagal mengambil SubSLS dari {sls_name}: {e}")
                    continue

                for subsls in daftar_subsls:
                    subsls_id = subsls.get("id")
                    subsls_name = subsls.get("name")
                    subsls_kode = subsls.get("fullCode")

                    result.append({
                        f"{level_region[2]['name']}_id": kecamatan_id,
                        f"{level_region[2]['name']}": kecamatan_name,
                        f"{level_region[3]['name']}_id": desa_id,
                        f"{level_region[3]['name']}": desa_name,
                        f"{level_region[4]['name']}_id": sls_id,
                        f"{level_region[4]['name']}": sls_name,
                        f"{level_region[5]['name']}_id": subsls_id,
                        f"{level_region[5]['name']}": subsls_name,
                        "smallcode": subsls_kode,
                    })

        time.sleep(0.2)

    progress_bar.progress(1.0)
    status_text.text("✅ Selesai mengambil seluruh wilayah.")

    df_result = pd.DataFrame(result)
    if df_result.empty:
        st.warning("⚠️ Tidak ada data wilayah yang berhasil diambil.")

    return df_result

# ---------------- Streamlit wrappers for actions ----------------
def streamlit_get_all_survey_answers(id_survey, template_id, nama_kab, nama_survey, daftarwilayah_df, headers, cookies, sess, survey_period_id, save_folder):
    """Ambil jawaban assignment berdasarkan daftarwilayah_df['smallcode'] dan survey_period_id.
       Simpan 2 file: raw answers & assignment list. Kembalikan file paths."""
    if daftarwilayah_df is None or 'smallcode' not in daftarwilayah_df.columns:
        st.error("Daftar wilayah kosong atau tidak mengandung kolom 'smallcode'.")
        return None, None

    st.write("Jumlah wilayah:", len(daftarwilayah_df))
    st.dataframe(daftarwilayah_df.head())
    # prepare filenames
    
    # Buat subfolder otomatis di dalam OUTPUT/nama_survey
    output_dir = os.path.join(save_folder, "output", nama_survey)
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_answers = f"Raw_Data_{nama_kab}_{nama_survey}_{timestamp}.xlsx"
    filename_assign = f"Assignment_{nama_kab}_{nama_survey}_{timestamp}.xlsx"
    path_answers = os.path.join(output_dir, filename_answers)
    path_assign = os.path.join(output_dir, filename_assign)

    results_answers = []
    results_assign = []
    total = len(daftarwilayah_df['smallcode'])
    p = st.progress(0)
    count = 0

    start_time = time.time()
    for smallCode in daftarwilayah_df['smallcode']:
        try:
            url = f'https://fasih-sm.bps.go.id/assignment-general/api/assignments/get-principal-values-by-smallest-code/{survey_period_id}/{smallCode}'
            resp = sess.get(url, headers=headers)
            # st.write(f"Memeriksa smallCode: {smallCode}")
            # st.write(f"URL: {url}")
            # st.write(f"Status: {resp.status_code}")
            # st.write(f"Response text: {resp.text[:500]}")   

            if resp.status_code != 200 or not resp.text.strip():
                # skip
                count += 1
                p.progress(int(count/total*100))
                continue

            data = resp.json().get('data', [])
            if not data:
                count += 1
                p.progress(int(count/total*100))
                continue

            # save assignment raw objects
            results_assign.extend(data)

            # for each assignment get detail
            for d in data:
                assignment_id = d.get('assignmentId')
                url_detail = f'https://fasih-sm.bps.go.id/assignment-general/api/assignment/get-by-id-with-data-for-scm?id={assignment_id}'
                resp_detail = sess.get(url_detail, headers=headers)
                if resp_detail.status_code != 200:
                    continue
                try:
                    detail_json = resp_detail.json()
                    # some responses have JSON string inside "data"
                    inner_str = detail_json.get("data", {}).get("data") if isinstance(detail_json.get("data"), dict) else detail_json.get("data")
                    if isinstance(inner_str, str):
                        import json as _json
                        inner_json = _json.loads(inner_str)
                    else:
                        inner_json = detail_json.get("data", {})
                    answers = inner_json.get("answers", [])
                    # build a flat dict of answers
                    flat = {}
                    for a in answers:
                        k = a.get("dataKey")
                        v = a.get("value") if "value" in a else a.get("dataValue")
                        flat[k] = v
                    flat['assignment_id'] = assignment_id
                    flat['smallCode'] = smallCode
                    results_answers.append(flat)
                except Exception:
                    continue

        except Exception as e:
            st.warning(f"Error smallCode {smallCode}: {e}")
        count += 1
        p.progress(int(count/total*100))

    # save
    if results_answers:
        df_ans = pd.DataFrame(results_answers).fillna('')
        os.makedirs(save_folder, exist_ok=True)
        df_ans.to_excel(path_answers, index=False)
    else:
        df_ans = pd.DataFrame()

    if results_assign:
        df_assign = pd.DataFrame(results_assign).fillna('')
        os.makedirs(save_folder, exist_ok=True)
        df_assign.to_excel(path_assign, index=False)
    else:
        df_assign = pd.DataFrame()

    elapsed = time.time() - start_time
    st.success(f"Selesai ambil data — waktu: {int(elapsed//60)} menit {int(elapsed%60)} detik.")
    return (path_answers if not df_ans.empty else None, path_assign if not df_assign.empty else None)


def streamlit_approve_by_pml(id_survey, template_id, nama_kab, nama_survey, daftarwilayah_df, headers, cookies, sess, survey_period_id, save_folder, driver):
    """
    Sederhana: ambil assignments per smallcode, masuk ke review page via driver (yang sudah login),
    klik approve jika kondisi terpenuhi. Karena proses ini bergantung pada driver/element, UI hanya
    akan menjalankan dan menyimpan log excel hasil attempt.
    """
    if daftarwilayah_df is None or 'smallcode' not in daftarwilayah_df.columns:
        st.error("Daftar wilayah kosong atau tidak mengandung kolom 'smallcode'.")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_log = f"Log_Approve_{nama_kab}_{nama_survey}_{timestamp}.xlsx"
    path_log = os.path.join(save_folder, filename_log)

    log_rows = []
    total = len(daftarwilayah_df['smallcode'])
    p = st.progress(0)
    count = 0
    start_time = time.time()

    for smallCode in daftarwilayah_df['smallcode']:
        try:
            url = f'https://fasih-sm.bps.go.id/assignment-general/api/assignments/get-principal-values-by-smallest-code/{survey_period_id}/{smallCode}'
            resp = sess.get(url, headers=headers)
            if resp.status_code != 200 or not resp.text.strip():
                count += 1
                p.progress(int(count/total*100))
                continue
            data = resp.json().get('data', [])
            if not data:
                count += 1
                p.progress(int(count/total*100))
                continue

            for d in data:
                assignment_id = d.get('assignmentId')
                review_url = f'https://fasih-sm.bps.go.id/survey-collection/survey-review/{assignment_id}/{template_id}/{survey_period_id}/a/1'
                status_assignment = ''  # could be derived via history endpoint if needed
                approved = False
                keterangan = ""

                try:
                    # open review page in driver and attempt clicking approve
                    driver.get(review_url)
                    time.sleep(1)
                    # waiting / element handling is fragile — adjust if page structure different
                    # Try to click button with id 'buttonApprove'
                    try:
                        btn = driver.find_element(By.ID, "buttonApprove")
                        btn.click()
                        time.sleep(0.5)
                        # click confirm if appears
                        try:
                            confirm = driver.find_element(By.XPATH, '//*[@id="fasih"]/div/div/div[6]/button[1]')
                            confirm.click()
                        except Exception:
                            pass
                        approved = True
                        keterangan = "Approved"
                    except Exception as ebtn:
                        keterangan = f"Button not clickable / not found: {ebtn}"
                except Exception as e:
                    keterangan = f"Error opening review: {e}"

                log_rows.append({
                    "assignment_id": assignment_id,
                    "smallCode": smallCode,
                    "review_url": review_url,
                    "approved": approved,
                    "keterangan": keterangan
                })
        except Exception as e:
            st.warning(f"Error smallCode {smallCode}: {e}")
        count += 1
        p.progress(int(count/total*100))

    # save log
    df_log = pd.DataFrame(log_rows)
    os.makedirs(save_folder, exist_ok=True)
    df_log.to_excel(path_log, index=False)
    elapsed = time.time() - start_time
    st.success(f"Selesai approve attempt — waktu: {int(elapsed//60)} menit {int(elapsed%60)} detik.")
    return path_log



# =============== STREAMLIT UI ===============

st.set_page_config(page_title="Monitoring FASIH", page_icon="🌐", layout="wide")
st.title("🌐 Aplikasi Monitoring FASIH")

# session_state defaults
if "login_success" not in st.session_state:
    st.session_state.login_success = False
if "headers" not in st.session_state:
    st.session_state.headers = None
if "cookies" not in st.session_state:
    st.session_state.cookies = None
if "session" not in st.session_state:
    st.session_state.session = None
if "driver" not in st.session_state:
    st.session_state.driver = None
if "username" not in st.session_state:
    st.session_state.username = None
if "session" not in st.session_state:
    st.session_state.session = None

# Session state
if "otp_needed" not in st.session_state:
    st.session_state.otp_needed = False
if "password" not in st.session_state:
    st.session_state.password = ""

# ---------- FORM LOGIN (tidak diubah prosesnya) ---------- #
with st.expander("🔐 Login ke FASIH", expanded=not st.session_state.get("login_success", False)):

    session_folder = st.text_input("📁 Masukkan path folder session:", value="sessions")

    driver = st.session_state.get("driver", None)
    username = None
    password = None
    headers = None
    cookies = None
    session = None
    login_success = False

    # Pilih username dari file session
    session_files = get_session_files(session_folder)
    if session_files:
        usernames = [f.replace("_session.pkl", "") for f in session_files]
        username_choice = st.selectbox("Pilih username tersimpan:", ["(Masukkan manual)"] + usernames)

        if username_choice != "(Masukkan manual)":
            username = username_choice
            headers, cookies, session, password = muat_session(session_folder, username)
            if password:
                st.info(f"🔄 Session ditemukan untuk **{username}** (password otomatis diisi)")
        else:
            username = st.text_input("Masukkan username SSO:")
    else:
        username = st.text_input("Masukkan username SSO:")

    if not password:
        password = st.text_input("Masukkan password SSO:", type="password")

    if st.button("🚀 Mulai Login / Cek Session"):
        if not username or not password:
            st.warning("Mohon isi username dan password terlebih dahulu.")
            st.stop()

        driver = setup_driver()
        st.session_state["driver"] = driver

        if session:
            st.write(f"🔄 Menggunakan session tersimpan untuk {username}...")
            apply_cookies_to_driver(driver, session.cookies.get_dict(), "sso.bps.go.id")
            apply_cookies_to_driver(driver, session.cookies.get_dict(), "fasih-sm.bps.go.id")

            driver.get("https://fasih-sm.bps.go.id/survey-collection/survey")
            st.write("⏳ Mengecek validitas session...")
            max_wait = 15
            start_time = time.time()
            valid = False
            while time.time() - start_time < max_wait:
                url_now = driver.current_url
                if "survey" in url_now or "collection" in url_now:
                    valid = True
                    break
                time.sleep(1)

            if valid:
                st.success("✅ Session masih valid! Browser akan tetap terbuka.")
                st.session_state.login_success = True
            else:
                st.warning("⚠️ Session tidak valid / reload lama. Login ulang diperlukan.")
                headers, cookies, session, password = main_login(driver, username, password)
                simpan_session(session_folder, username, headers, cookies, session, password)
                st.success("✅ Session baru berhasil disimpan.")
                st.session_state.login_success = True

            st.session_state["headers"] = headers
            st.session_state["session"] = session
            st.session_state["cookies"] = cookies
            st.session_state["username"] = username
            st.session_state["password"] = password

        else:
            st.warning("🔐 Tidak ada session tersimpan. Login manual diperlukan.")
            headers, cookies, session, password = main_login(driver, username, password)
            simpan_session(session_folder, username, headers, cookies, session, password)
            st.success("✅ Login berhasil dan session tersimpan.")
            st.session_state.login_success = True
            st.session_state["headers"] = headers
            st.session_state["session"] = session
            st.session_state["cookies"] = cookies
            st.session_state["username"] = username
            st.session_state["password"] = password

        # Setelah login selesai, langsung rerun agar expander tertutup
        st.rerun()


    # ✅ Tambahkan tombol manual untuk menutup browser
    if "driver" in st.session_state and st.session_state["driver"] is not None:
        if st.button("❌ Tutup Browser"):
            try:
                simpan_session(session_folder, username, headers, cookies, session, password)
                st.session_state["driver"].quit()
                st.session_state["driver"] = None
                st.success("Browser berhasil ditutup.")
            except Exception as e:
                st.error(f"Gagal menutup browser: {e}")
    # ---------- AKHIR FORM LOGIN ---------- #


# =================== SETELAH LOGIN =====================
if st.session_state.get("login_success", False):

    st.divider()
    st.subheader("📊 Menu Survei FASIH")

    headers = st.session_state["headers"]
    req_session = st.session_state["session"]
    cookies = st.session_state["cookies"]

    # --- Ambil daftar survei
    try:
        url_survey = "https://fasih-sm.bps.go.id/survey/api/v1/surveys/datatable?surveyType=Pencacahan"
        payload = {"pageNumber": 0, "pageSize": 100, "sortBy": "CREATED_AT", "sortDirection": "DESC", "keywordSearch": ""}
        resp = req_session.post(url_survey, json=payload)
        resp.raise_for_status()
        data = resp.json()
        surveys = data.get('data', {}).get('content', [])
    except Exception as e:
        st.error(f"Gagal ambil daftar survei: {e}")
        surveys = []

    survey_options = ["-- pilih survei --"] + [f"{s.get('name')} (id:{s.get('id')})" for s in surveys]
    selected_survey_label = st.selectbox("Daftar Survei:", survey_options)
    if selected_survey_label != "-- pilih survei --":
        sel = next((s for s in surveys if f"{s.get('name')} (id:{s.get('id')})" == selected_survey_label), None)
        if sel:
            id_survey = sel.get('id')
            nama_survey = sel.get('name')

            # fetch survey metadata
            try:
                url_group = f"https://fasih-sm.bps.go.id/survey/api/v1/surveys/{id_survey}"
                rg = req_session.get(url_group, headers=headers).json()
                group_id = rg['data'].get('regionGroupId')
                template_id = None
                if rg['data'].get('surveyTemplates'):
                    template_id = rg['data']['surveyTemplates'][-1].get('templateId')
                url_level_region = f'https://fasih-sm.bps.go.id/region/api/v1/region-metadata?id={group_id}'
                level_region = req_session.get(url_level_region, headers=headers).json().get('data', {}).get('level', [])
            except Exception as e:
                st.error(f"Gagal ambil metadata survei: {e}")
                group_id = None
                template_id = None
                level_region = []

            # Step B: provinsi
            # st.header("2. Pilih Provinsi")
            provinces = []
            try:
                url_prov = f"https://fasih-sm.bps.go.id/region/api/v1/region/level1?groupId={group_id}"
                data_prov = req_session.get(url_prov, headers=headers).json()
                provinces = data_prov.get('data', [])
            except Exception as e:
                st.error(f"Gagal ambil daftar provinsi: {e}")

            prov_options = ["-- pilih provinsi --"] + [f"{p['name']} ({p['fullCode']})" for p in provinces]
            selected_prov_label = st.selectbox("Provinsi:", prov_options)
            if selected_prov_label != "-- pilih provinsi --":
                p = next((x for x in provinces if f"{x['name']} ({x['fullCode']})" == selected_prov_label), None)
                if p:
                    fullcode_prov = p.get('fullCode')
                    id_prov = p.get('id')
                    code_prov = p.get('code')
                    name_prov = p.get('name')

                    # Step C: kabupaten
                    # st.header("3. Pilih Kabupaten / Kota")
                    try:
                        url_kab = f"https://fasih-sm.bps.go.id/region/api/v1/region/level2?groupId={group_id}&level1FullCode={fullcode_prov}"
                        data_kab = req_session.get(url_kab, headers=headers).json()
                        kab_list = data_kab.get('data', [])
                    except Exception as e:
                        st.error(f"Gagal ambil daftar kabupaten: {e}")
                        kab_list = []

                    kab_options = ["-- pilih kabupaten --"] + [f"{k['name']} ({k.get('fullCode')})" for k in kab_list]
                    selected_kab_label = st.selectbox("Kabupaten / Kota:", kab_options)
                    if selected_kab_label != "-- pilih kabupaten --":
                        k = next((x for x in kab_list if f"{x['name']} ({x.get('fullCode')})" == selected_kab_label), None)
                        if k:
                            id_kab = k.get('id')
                            nama_kab = k.get('name')
                            fullcode_kab = k.get('fullCode')
                            code_kab = k.get('code')

                            st.success(f"Survei: **{nama_survey}**  —  Provinsi: **{name_prov}**  —  Kabupaten: **{nama_kab}**")

                            # Period selection (try endpoint; otherwise manual)
                            periods = []
                            try:
                                url_period = f'https://fasih-sm.bps.go.id/survey/api/v1/surveys/{id_survey}'
                                rp = req_session.get(url_period, headers=headers)
                                if rp.ok:
                                    pdatas = rp.json()['data']['surveyPeriods']
                                    # buat mapping label -> id agar bisa ditampilkan dengan nama tapi ambil id
                                    period_options = {f"{p['name']} (Start: {p['startDate']} - End: {p['endDate']})": p['id'] for p in pdatas}
                                    labels = list(period_options.keys())
                                else:
                                    period_options = {}
                                    labels = []
                            except Exception:
                                period_options = {}
                                labels = []

                            if labels:
                                selected_label = st.selectbox("Pilih Periode Survey:", ["-- pilih periode --"] + labels)
                                survey_period_id = None if selected_label == "-- pilih periode --" else period_options[selected_label]
                            else:
                                survey_period_id = st.text_input("Periode (isi ID jika perlu):", value="")


                            # Daftar wilayah: uploader atau ambil via API
                            uploaded_file = st.file_uploader("Unggah file Excel Daftar Wilayah (opsional)", type=["xls", "xlsx"])
                            daftarwilayah_df = None

                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            wilayah_dir = os.path.join(os.getcwd(), "Daftar Wilayah", nama_survey)
                            os.makedirs(wilayah_dir, exist_ok=True)

                            if uploaded_file is not None:
                                try:
                                    daftarwilayah_df = pd.read_excel(uploaded_file)
                                    st.success("📥 File berhasil diunggah.")
                                    st.dataframe(daftarwilayah_df.head(10))

                                except Exception as e:
                                    st.error(f"Gagal baca file: {e}")

                            if daftarwilayah_df is None:
                                if st.button("🌐 Ambil daftar wilayah dari API"):
                                    with st.spinner("Mengambil daftar wilayah dari server..."):
                                        region_level1 = {'id': id_prov, 'fullCode': fullcode_prov, 'code': code_prov, 'name': name_prov, 'smallcode': fullcode_prov}
                                        region_level2 = {'id': id_kab, 'fullCode': fullcode_kab, 'code': code_kab, 'name': nama_kab, 'smallcode': fullcode_kab}
                                        df_wil = ambil_semua_sls_smallcode_dari_kabupaten(
                                            id_kab, level_region, group_id, headers, cookies,
                                            region_level1=region_level1, region_level2=region_level2
                                        )

                                        if df_wil is not None and not df_wil.empty:
                                            st.session_state.daftarwilayah = df_wil
                                            st.success("📥 Daftar wilayah berhasil diambil.")
                                            st.dataframe(df_wil.head(20))

                                            # Simpan hasil API ke folder Daftar Wilayah/<nama_survey>/
                                            save_path = os.path.join(wilayah_dir, f"daftar_wilayah_api_{nama_kab}_{timestamp}.xlsx")
                                            df_wil.to_excel(save_path, index=False)
                                            st.info(f"💾 File daftar wilayah tersimpan di: `{save_path}`")

                                        else:
                                            st.warning("Gagal ambil daftar wilayah atau hasil kosong.")

                            else:
                                st.session_state.daftarwilayah = daftarwilayah_df


                            # ACTIONS (placeholder untuk langkah selanjutnya)
                            # st.header("5. Pilih Aksi Lanjutan")
                            aksi = st.selectbox("Aksi:", ["-- pilih aksi --", "Ambil Raw Data", "Approve Assignment"])
                            save_folder = st.text_input("Folder untuk menyimpan hasil (local)", value=os.getcwd())

                            if st.button("Jalankan Aksi"):
                                if aksi == "-- pilih aksi --":
                                    st.warning("Pilih aksi terlebih dahulu.")
                                else:
                                    if st.session_state.session is None:
                                        st.error("Requests session tidak tersedia.")
                                    else:
                                        if st.session_state.daftarwilayah is None or st.session_state.daftarwilayah.empty:
                                            st.warning("Daftar wilayah kosong. Unggah file atau ambil dari API dahulu.")
                                        else:
                                            # ensure survey_period_id given (string or numeric)
                                            if not survey_period_id:
                                                st.warning("Isi atau pilih survey period ID terlebih dahulu.")
                                            else:
                                                if aksi == "Ambil Raw Data":
                                                    with st.spinner("Mengambil raw data..."):
                                                        path_answers, path_assign = streamlit_get_all_survey_answers(
                                                            id_survey=id_survey,
                                                            template_id=template_id,
                                                            nama_kab=fullcode_kab,
                                                            nama_survey=nama_survey,
                                                            daftarwilayah_df=st.session_state.daftarwilayah,
                                                            headers=st.session_state.headers,
                                                            cookies=st.session_state.cookies,
                                                            sess=st.session_state.session,
                                                            survey_period_id=survey_period_id,
                                                            save_folder=save_folder
                                                        )
                                                        if path_answers:
                                                            with open(path_answers, "rb") as fh:
                                                                st.download_button("Download Raw Data Excel", fh.read(), file_name=os.path.basename(path_answers))
                                                        if path_assign:
                                                            with open(path_assign, "rb") as fh:
                                                                st.download_button("Download Assignment Excel", fh.read(), file_name=os.path.basename(path_assign))
                                                elif aksi == "Approve Assignment":
                                                    if st.session_state.driver is None:
                                                        st.warning("Driver tidak tersedia — buka browser / login dulu.")
                                                    else:
                                                        with st.spinner("Menjalankan auto-approve (berbasis driver)..."):
                                                            logpath = streamlit_approve_by_pml(
                                                                id_survey=id_survey,
                                                                template_id=template_id,
                                                                nama_kab=nama_kab,
                                                                nama_survey=nama_survey,
                                                                daftarwilayah_df=st.session_state.daftarwilayah,
                                                                headers=st.session_state.headers,
                                                                cookies=st.session_state.cookies,
                                                                sess=st.session_state.session,
                                                                survey_period_id=survey_period_id,
                                                                save_folder=save_folder,
                                                                driver=st.session_state.driver
                                                            )
                                                            if logpath:
                                                                with open(logpath, "rb") as fh:
                                                                    st.download_button("Download Log Approve Excel", fh.read(), file_name=os.path.basename(logpath))
    st.markdown("---")
    # Logout / close options
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔓 Logout (keep browser open)"):
            st.session_state.logged_in = False
            st.session_state.headers = None
            st.session_state.cookies = None
            st.session_state.session = None
            st.session_state.username = None
            st.session_state.password = None
            st.success("Logged out (UI cleared).")
    with col2:
        if st.button("❌ Tutup Browser dan Logout"):
            if st.session_state.driver:
                try:
                    st.session_state.driver.quit()
                except Exception:
                    pass
            st.session_state.driver = None
            st.session_state.logged_in = False
            st.session_state.headers = None
            st.session_state.cookies = None
            st.session_state.session = None
            st.session_state.username = None
            st.session_state.password = None
            st.success("Browser ditutup dan logout.")

else:
    st.info("Belum login — buka expand Login di atas untuk masuk.")

# ✅ Tombol tutup browser global (jika masih ingin menutup)
if "driver" in st.session_state and st.session_state["driver"] is not None:
    if st.button("❌ Tutup Browser (global)"):
        try:
            st.session_state.driver.quit()
        except Exception:
            pass
        st.session_state.driver = None
        st.success("Browser berhasil ditutup.")
