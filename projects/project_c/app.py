# app.py
import os, io, re, time, json, pickle, urllib.parse
from datetime import datetime
from pathlib import Path
import pandas as pd
import streamlit as st
import requests
from requests.cookies import RequestsCookieJar

# =================== Setup ===================
st.set_page_config(page_title="FASIH — DW/RAW/Approve", layout="wide")
st.title("🧭 FASIH — Login • DaftarWilayah • Raw Data • Approve")

def init_state():
    for k,v in dict(
        driver=None, logged_in=False, username="",
        headers=None, cookies_dict=None, session_obj=None,
        otp_needed=False, daftarwilayah=None,
        survey_meta=None, survey_period_id=None, survey_period_name=None,
    ).items():
        if k not in st.session_state: st.session_state[k] = v
init_state()

# =================== Utils ===================
def slugify(text: str) -> str:
    text = (text or "survey").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-") or "survey"

def output_dirs(survey_name: str):
    base = os.path.abspath(os.getcwd())
    slug = slugify(survey_name or "survey")
    dw_dir  = os.path.join(base, "OUTPUT", "DaftarWilayah", slug)
    raw_dir = os.path.join(base, "OUTPUT", "RAW DATA", slug)
    appr_dir = os.path.join(base, "OUTPUT", "APPROVE LOGS", slug)
    os.makedirs(dw_dir, exist_ok=True)
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(appr_dir, exist_ok=True)
    return dw_dir, raw_dir, appr_dir

def clear_screen():
    try: os.system("cls" if os.name=="nt" else "clear")
    except Exception: pass

# =================== Selenium / Driver ===================
try:
    from selenium import webdriver as _webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.edge.service import Service as EdgeService
    from webdriver_manager.microsoft import EdgeChromiumDriverManager
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, ElementClickInterceptedException,
        StaleElementReferenceException, WebDriverException
    )
    webdriver_ok = True
except Exception:
    webdriver_ok = False

def get_chrome_or_edge(headless=False):
    if not webdriver_ok:
        raise RuntimeError("Install: pip install selenium webdriver-manager")
    # Prefer Chrome
    try:
        copts = ChromeOptions()
        if headless: copts.add_argument("--headless=new")
        copts.add_argument("--window-size=1920,1080")
        copts.add_argument("--no-sandbox")
        copts.add_argument("--disable-dev-shm-usage")
        copts.add_argument("--disable-gpu")
        copts.add_experimental_option("excludeSwitches", ["enable-automation"])
        copts.add_experimental_option("useAutomationExtension", False)
        candidates = [
            os.getenv("CHROME_PATH"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        chrome_binary = next((p for p in candidates if p and Path(p).exists()), None)
        if chrome_binary:
            copts.binary_location = chrome_binary
        service = ChromeService(ChromeDriverManager().install())
        return _webdriver.Chrome(service=service, options=copts)
    except Exception:
        # Fallback Edge
        eopts = EdgeOptions()
        if headless: eopts.add_argument("--headless=new")
        eopts.add_argument("--window-size=1920,1080")
        return _webdriver.Edge(service=EdgeService(EdgeChromiumDriverManager().install()), options=eopts)

# ---------- NEW: injeksi cookies + handshake OAuth ----------
def _cookies_to_items(cookies):
    # menerima RequestsCookieJar, dict, atau list selenium
    if isinstance(cookies, dict):
        return list(cookies.items())
    if isinstance(cookies, RequestsCookieJar):
        return [(c.name, c.value) for c in cookies]
    try:
        return [(c.get("name"), c.get("value")) for c in cookies]
    except Exception:
        return []

def _add_all_cookies_to_host(driver, host_url, items):
    driver.get(host_url)                # harus berada di host tsb
    time.sleep(0.8)
    for name, value in items:
        if not name: 
            continue
        try:
            driver.add_cookie({"name": name, "value": value, "domain": ".bps.go.id", "path": "/"})
        except Exception:
            # coba host-only
            try:
                dom = urllib.parse.urlparse(host_url).hostname
                driver.add_cookie({"name": name, "value": value, "domain": dom, "path": "/"})
            except Exception:
                pass

def inject_cookies_and_handshake(session_or_cookies, headless=False):
    """
    1) Buat / reuse driver
    2) Suntik cookies ke sso.bps.go.id dan fasih-sm.bps.go.id
    3) Handshake OAuth ke FASIH
    4) Kembalikan driver
    """
    drv = st.session_state.driver
    try:
        _ = drv.current_url
    except Exception:
        drv = get_chrome_or_edge(headless=headless)

    # siapkan pairs cookies
    if isinstance(session_or_cookies, requests.Session):
        items = _cookies_to_items(session_or_cookies.cookies)
    else:
        items = _cookies_to_items(session_or_cookies)

    # injeksi ke kedua host (beberapa cookie host-only)
    _add_all_cookies_to_host(drv, "https://sso.bps.go.id", items)
    _add_all_cookies_to_host(drv, "https://fasih-sm.bps.go.id", items)

    # refresh + handshake oauth
    drv.get("https://fasih-sm.bps.go.id/oauth2/authorization/ics"); time.sleep(3)
    drv.get("https://fasih-sm.bps.go.id/survey-collection/survey"); time.sleep(2)

    st.session_state.driver = drv
    return drv

# =================== Session (requests) ===================
def cookiejar_from_driver(driver) -> RequestsCookieJar:
    jar = RequestsCookieJar()
    for c in driver.get_cookies():
        jar.set(c["name"], c["value"], domain=c.get("domain") or ".bps.go.id", path=c.get("path") or "/")
    return jar

def cookies_dict_from_cookiejar(jar: RequestsCookieJar) -> dict:
    return {c.name: c.value for c in jar}

def build_session_from_cookiejar(cookie_jar: RequestsCookieJar):
    sess = requests.Session()
    sess.cookies = cookie_jar
    xsrf_raw = cookie_jar.get("XSRF-TOKEN", "")
    xsrf_token = urllib.parse.unquote(xsrf_raw) if xsrf_raw else ""
    headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'X-XSRF-TOKEN': xsrf_token,
        'Referer': 'https://fasih-sm.bps.go.id/',
        'User-Agent': 'Mozilla/5.0',
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://fasih-sm.bps.go.id'
    }
    sess.headers.update(headers)
    return headers, sess

def simpan_session(username, headers, cookies_dict):
    sessions_dir = os.path.join(os.getcwd(), "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    path = os.path.join(sessions_dir, f"{username}_session.pkl")
    with open(path, "wb") as f:
        pickle.dump({"username": username, "headers": headers, "cookies": cookies_dict, "ts": time.strftime("%F %T")}, f)
    return path

def muat_session(username):
    sessions_dir = os.path.join(os.getcwd(), "sessions")
    path = os.path.join(sessions_dir, f"{username}_session.pkl")
    if not os.path.exists(path): return None, None, None, None
    data = pickle.load(open(path, "rb"))
    headers = data.get("headers") or {}
    cookies_dict = data.get("cookies") or {}
    sess = requests.Session()
    for k,v in cookies_dict.items():
        sess.cookies.set(k, v, domain=".bps.go.id", path="/")
    if headers: sess.headers.update(headers)
    return headers, cookies_dict, sess, data.get("ts")

# =================== SSO / OTP / OAuth ===================
def sso_start_login(driver, username, password, timeout=30):
    driver.get("https://sso.bps.go.id")
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.NAME, "username")))
    driver.find_element(By.NAME, "username").send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password)
    driver.find_element(By.ID, "kc-login").click()
    try:
        WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#otp, input#otp, input[name='otp']")))
        return True
    except Exception:
        return False

def sso_submit_otp(driver, otp_value, timeout=120):
    WebDriverWait(driver, 30).until(lambda d: d.find_element(By.CSS_SELECTOR, "#otp, input#otp, input[name='otp']"))
    otp_el = driver.find_element(By.CSS_SELECTOR, "#otp, input#otp, input[name='otp']")
    otp_el.clear(); otp_el.send_keys(otp_value)
    try: driver.find_element(By.ID, "kc-login").click()
    except Exception: pass
    WebDriverWait(driver, timeout).until(lambda d: "fasih-sm.bps.go.id" in (d.current_url or "") or len(d.find_elements(By.CSS_SELECTOR, "#otp, input#otp"))==0)

def fasih_handshake_and_session(driver):
    driver.get("https://fasih-sm.bps.go.id/oauth2/authorization/ics"); time.sleep(5)
    driver.get("https://fasih-sm.bps.go.id/survey-collection/survey"); time.sleep(3)
    jar = cookiejar_from_driver(driver)
    headers, sess = build_session_from_cookiejar(jar)
    return headers, cookies_dict_from_cookiejar(jar), sess

# =================== Domain helpers ===================
def extract_answers(answers):
    res = {}
    for item in answers:
        key = item.get("dataKey")
        ans = item.get("answer")
        if isinstance(ans, list):
            if all(isinstance(i, dict) and 'value' in i and 'label' in i for i in ans):
                res[key] = ", ".join(f"{i['value']}. {i['label']}" for i in ans)
            else:
                res[key] = ", ".join(str(i) for i in ans)
        elif isinstance(ans, dict):
            res[key] = f"{ans.get('value','')}. {ans.get('label','')}"
        else:
            res[key] = str(ans)
    return res

def try_fetch_assignments(session, headers, survey_period_id, template_id, smallcode):
    base = "https://fasih-sm.bps.go.id/assignment-general/api/assignments/get-principal-values-by-smallest-code"
    urlA = f"{base}/{survey_period_id}/{template_id}/{smallcode}"
    r = session.get(urlA, headers=headers, timeout=40)
    if r.ok:
        try: return r.json().get("data", []) or []
        except Exception: pass
    urlB = f"{base}/{survey_period_id}/{smallcode}"
    r2 = session.get(urlB, headers=headers, timeout=40)
    if r2.ok:
        try: return r2.json().get("data", []) or []
        except Exception: pass
    return []

def parse_assignment_status(history_json):
    out = []
    try:
        data = history_json.get("data") or []
        for item in data:
            status_name = item.get("statusName") or item.get("status") or ""
            created_at = item.get("createdAt") or item.get("created_at") or ""
            out.append({"status_assignment": status_name, "created_at": created_at})
    except Exception:
        pass
    return out

# =================== Ambil DaftarWilayah (hierarkis) ===================
def ambil_semua_sls_smallcode_dari_kabupaten(
    kabupaten_id, level_region, region_group_id, headers, cookies, region_level1, region_level2,
):
    st.write("=== Mengambil kecamatan → desa → SLS (→ SubSLS bila ada) ===")
    if not isinstance(level_region, list) or len(level_region) < 3:
        if isinstance(level_region, list) and len(level_region) == 2:
            st.warning("❌ Regionlevel hanya sampai Kabupaten."); return pd.DataFrame([region_level2])
        elif isinstance(level_region, list) and len(level_region) == 1:
            st.warning("❌ Regionlevel hanya sampai Provinsi."); return pd.DataFrame([region_level1])
        else:
            st.error("❌ Regionlevel tidak valid."); return pd.DataFrame()

    result = []
    try:
        url_kec = f"https://fasih-sm.bps.go.id/region/api/v1/region/level3?groupId={region_group_id}&level2Id={kabupaten_id}"
        resp_kec = requests.get(url_kec, headers=headers, cookies=cookies, timeout=40)
        resp_kec.raise_for_status()
        daftar_kecamatan = resp_kec.json().get('data', [])
    except Exception as e:
        st.error(f"❌ Gagal mengambil data kecamatan: {e}"); return pd.DataFrame()

    for kec in daftar_kecamatan:
        kec_id = kec['id']; kec_name = kec['name']; kec_code = kec['fullCode']
        # st.write(f"📍 Kecamatan: {kec_name}")
        if len(level_region) == 3:
            result.append({f"{level_region[2]['name']}_id": kec_id, f"{level_region[2]['name']}": kec_name, 'smallcode': kec_code})
            continue
        try:
            url_desa = f"https://fasih-sm.bps.go.id/region/api/v1/region/level4?groupId={region_group_id}&level3Id={kec_id}"
            resp_desa = requests.get(url_desa, headers=headers, cookies=cookies, timeout=40)
            resp_desa.raise_for_status()
            daftar_desa = resp_desa.json().get('data', [])
        except Exception as e:
            st.warning(f"❌ Gagal mengambil desa dari {kec_name}: {e}"); continue

        for desa in daftar_desa:
            desa_id = desa['id']; desa_name = desa['name']; desa_code = desa['fullCode']
            # st.write(f"🏘️ Desa: {desa_name}")
            if len(level_region) == 4:
                result.append({
                    f"{level_region[2]['name']}_id": kec_id, f"{level_region[2]['name']}": kec_name,
                    f"{level_region[3]['name']}_id": desa_id, f"{level_region[3]['name']}": desa_name,
                    'smallcode': desa_code
                }); continue
            try:
                url_sls = f"https://fasih-sm.bps.go.id/region/api/v1/region/level5?groupId={region_group_id}&level4Id={desa_id}"
                resp_sls = requests.get(url_sls, headers=headers, cookies=cookies, timeout=40)
                resp_sls.raise_for_status()
                daftar_sls = resp_sls.json().get('data', [])
            except Exception as e:
                st.warning(f"❌ Gagal mengambil SLS dari {desa_name}: {e}"); continue

            for sls in daftar_sls:
                sls_id = sls['id']; sls_name = sls['name']; sls_code = sls['fullCode']
                # st.write(f"🧾 SLS: {sls_name} ({sls_code})")
                if len(level_region) == 5:
                    result.append({
                        f"{level_region[2]['name']}_id": kec_id, f"{level_region[2]['name']}": kec_name,
                        f"{level_region[3]['name']}_id": desa_id, f"{level_region[3]['name']}": desa_name,
                        f"{level_region[4]['name']}_id": sls_id, f"{level_region[4]['name']}": sls_name,
                        'smallcode': sls_code
                    }); continue
                try:
                    url_subsls = f"https://fasih-sm.bps.go.id/region/api/v1/region/level6?groupId={region_group_id}&level5Id={sls_id}"
                    resp_subsls = requests.get(url_subsls, headers=headers, cookies=cookies, timeout=40)
                    resp_subsls.raise_for_status()
                    daftar_subsls = resp_subsls.json().get('data', [])
                except Exception as e:
                    st.warning(f"❌ Gagal mengambil SubSLS dari {sls_name}: {e}"); continue
                for subsls in daftar_subsls:
                    subsls_id = subsls['id']; subsls_name = subsls['name']; subsls_code = subsls['fullCode']
                    # st.write(f"📄 SubSLS: {subsls_name} ({subsls_code})")
                    result.append({
                        f"{level_region[2]['name']}_id": kec_id, f"{level_region[2]['name']}": kec_name,
                        f"{level_region[3]['name']}_id": desa_id, f"{level_region[3]['name']}": desa_name,
                        f"{level_region[4]['name']}_id": sls_id, f"{level_region[4]['name']}": sls_name,
                        f"{level_region[5]['name']}_id": subsls_id, f"{level_region[5]['name']}": subsls_name,
                        'smallcode': subsls_code
                    })

    if not result: st.warning("⚠️ Tidak ada data yang berhasil diambil.")
    else: st.success(f"✅ Total baris wilayah: {len(result)}")
    return pd.DataFrame(result)

# =================== Sidebar: Login / Session ===================
st.sidebar.header("🔐 Session")
mode = st.sidebar.radio("Mode:", ["Login SSO", "Muat Session", "Logout"], index=0)

if mode == "Logout":
    for k in list(st.session_state.keys()): st.session_state[k] = None
    init_state(); st.sidebar.success("Reset session."); st.stop()

if mode == "Muat Session":
    user = st.sidebar.text_input("Username untuk muat", value=st.session_state.username or "")
    headless_after_load = st.sidebar.checkbox("Buka browser headless saat injeksi", value=False)

    # NEW: tombol cek API untuk memverifikasi session
    def _api_ok(sess):
        try:
            test_payload = {"pageNumber":0,"pageSize":1,"sortBy":"CREATED_AT","sortDirection":"DESC","keywordSearch":""}
            u = "https://fasih-sm.bps.go.id/survey/api/v1/surveys/datatable?surveyType=Pencacahan"
            r = sess.post(u, json=test_payload, timeout=20)
            return r.status_code, r.text[:200]
        except Exception as e:
            return -1, str(e)

    if st.sidebar.button("📂 Muat & Suntik ke Browser"):
        h, cdict, sess, ts = muat_session(user)
        if not h:
            st.sidebar.warning("Session tidak ditemukan."); st.stop()
        st.session_state.headers = h
        st.session_state.cookies_dict = cdict
        st.session_state.session_obj = sess
        st.session_state.username = user
        st.session_state.logged_in = True

        # Coba injeksi + handshake ke browser
        try:
            drv = inject_cookies_and_handshake(sess, headless=headless_after_load)
            st.sidebar.success(f"Driver siap (cookies diinjeksikan).")
        except Exception as e:
            st.sidebar.error(f"Gagal injeksi ke driver: {e}")

        # Uji API
        code, preview = _api_ok(sess)
        if code == 200:
            st.sidebar.success(f"API OK (200). Session aktif. Dibuat: {ts}")
        else:
            st.sidebar.error(f"API gagal ({code}). Kemungkinan session expired → lakukan Login SSO.")
            st.sidebar.caption(preview)

if mode == "Login SSO":
    user = st.sidebar.text_input("Username", value=st.session_state.username or "")
    pwd  = st.sidebar.text_input("Password", type="password")
    headless = st.sidebar.checkbox("Headless (OFF jika OTP)", value=False)
    c1,c2 = st.sidebar.columns(2)
    with c1:
        if st.sidebar.button("▶️ Login"):
            try:
                drv = get_chrome_or_edge(headless=headless)
                needs_otp = sso_start_login(drv, user, pwd)
                st.session_state.driver = drv
                st.session_state.username = user
                if needs_otp:
                    st.session_state.otp_needed = True
                    st.sidebar.warning("Masukkan OTP di bawah, lalu Kirim.")
                else:
                    h, cdict, sess = fasih_handshake_and_session(drv)
                    st.session_state.headers = h
                    st.session_state.cookies_dict = cdict
                    st.session_state.session_obj = sess
                    st.session_state.logged_in = True
                    st.sidebar.success("Login berhasil.")
            except Exception as e:
                st.sidebar.error(f"Gagal login awal: {e}")
    with c2:
        if st.sidebar.button("🧪 Tes Driver"):
            try:
                d = get_chrome_or_edge(headless=False); d.get("https://example.com")
                st.sidebar.success("Driver OK"); time.sleep(2); d.quit()
            except Exception as e:
                st.sidebar.error(f"Driver gagal: {e}")

    if st.session_state.otp_needed and st.session_state.driver:
        otp = st.sidebar.text_input("OTP", max_chars=8)
        if st.sidebar.button("Kirim OTP", type="primary"):
            try:
                sso_submit_otp(st.session_state.driver, otp)
                h, cdict, sess = fasih_handshake_and_session(st.session_state.driver)
                st.session_state.headers = h
                st.session_state.cookies_dict = cdict
                st.session_state.session_obj = sess
                st.session_state.logged_in = True
                st.session_state.otp_needed = False
                st.sidebar.success("Login + OTP sukses.")
            except Exception as e:
                st.sidebar.error(f"Gagal submit OTP: {e}")

if st.session_state.logged_in and st.session_state.headers and st.session_state.cookies_dict:
    if st.sidebar.button("💾 Simpan Session"):
        try:
            p = simpan_session(st.session_state.username, st.session_state.headers, st.session_state.cookies_dict)
            st.sidebar.success(f"Tersimpan: {p}")
        except Exception as e:
            st.sidebar.error(f"Gagal simpan: {e}")

# Guard
if not st.session_state.logged_in or st.session_state.session_obj is None:
    st.info("Silakan Login SSO atau Muat Session di sidebar.")
    st.stop()

session = st.session_state.session_obj
headers = st.session_state.headers
cookies_dict = st.session_state.cookies_dict
st.success(f"Login sebagai: {st.session_state.username}")

# =================== 1) SURVEY + period ===================
st.header("1) Pilih Survei")
payload = {"pageNumber": 0,"pageSize": 100,"sortBy": "CREATED_AT","sortDirection": "DESC","keywordSearch": ""}
url_survey = "https://fasih-sm.bps.go.id/survey/api/v1/surveys/datatable?surveyType=Pencacahan"
resp = session.post(url_survey, headers=headers, json=payload, timeout=40); resp.raise_for_status()
surveys = resp.json()["data"]["content"]
idx = st.selectbox("Survei", list(range(len(surveys))), format_func=lambda i: f"{surveys[i]['name']} (id:{surveys[i]['id']})")
id_survey = surveys[idx]["id"]; nama_survey = surveys[idx]["name"]

# metadata + level_region
meta = session.get(f"https://fasih-sm.bps.go.id/survey/api/v1/surveys/{id_survey}", headers=headers, timeout=40).json()["data"]
st.session_state.survey_meta = meta
group_id = meta["regionGroupId"]
template_id = meta["surveyTemplates"][-1]["templateId"]

resp_level_region = session.get(f'https://fasih-sm.bps.go.id/region/api/v1/region-metadata?id={group_id}', headers=headers, timeout=40)
level_region = resp_level_region.json()["data"]["level"]

# pilih period
periods = meta.get("surveyPeriods", [])
idxp = st.selectbox("Survey Period", list(range(len(periods))), format_func=lambda i: f"{periods[i]['name']} ({periods[i].get('startDate','?')}→{periods[i].get('endDate','?')})")
survey_period_id = periods[idxp]["id"]; survey_period_name = periods[idxp]["name"]
st.session_state.survey_period_id = survey_period_id
st.session_state.survey_period_name = survey_period_name

# =================== 2) Wilayah ===================
st.header("2) Wilayah")
prov = session.get(f"https://fasih-sm.bps.go.id/region/api/v1/region/level1?groupId={group_id}", headers=headers, timeout=40).json().get("data", [])
idx_prov = st.selectbox("Provinsi", list(range(len(prov))), format_func=lambda i: prov[i]["name"])
fullcode_prov = prov[idx_prov]["fullCode"]; id_prov = prov[idx_prov]["id"]; code_prov = prov[idx_prov]["code"]; name_prov = prov[idx_prov]["name"]

kab = session.get(f"https://fasih-sm.bps.go.id/region/api/v1/region/level2?groupId={group_id}&level1FullCode={fullcode_prov}", headers=headers, timeout=40).json().get("data", [])
idx_kab = st.selectbox("Kabupaten/Kota", list(range(len(kab))), format_func=lambda i: kab[i]["name"])
id_kab = kab[idx_kab]["id"]; nama_kab = kab[idx_kab]["name"]; fullcode_kab = kab[idx_kab]["fullCode"]; code_kab = kab[idx_kab]["code"]; name_kab = kab[idx_kab]["name"]

region_level1 = {'id': id_prov, 'fullCode': fullcode_prov, 'code': code_prov, 'name': name_prov, 'smallcode': fullcode_prov}
region_level2 = {'id': id_kab, 'fullCode': fullcode_kab, 'code': code_kab, 'name': name_kab, 'smallcode': fullcode_kab}

DW_DIR, RAW_DIR, APPR_DIR = output_dirs(nama_survey)
st.caption(f"📁 DaftarWilayah → {DW_DIR}")
st.caption(f"📁 RAW DATA → {RAW_DIR}")
st.caption(f"📁 APPROVE LOGS → {APPR_DIR}")

# =================== 3) DaftarWilayah (API / Upload) ===================
st.header("3) DaftarWilayah (API / Upload)")
up = st.file_uploader("Unggah Excel daftarwilayah (opsional)", type=["xlsx","xls"])
col_dw1, col_dw2 = st.columns(2)
with col_dw1:
    if st.button("🌐 Ambil dari API (hierarkis)"):
        with st.spinner("Mengambil daftar wilayah…"):
            df_dw = ambil_semua_sls_smallcode_dari_kabupaten(
                kabupaten_id=id_kab,
                level_region=level_region,
                region_group_id=group_id,
                headers=headers,
                cookies=session.cookies,            # **pakai session aktif**
                region_level1=region_level1,
                region_level2=region_level2
            )
            st.session_state.daftarwilayah = df_dw
            st.success(f"OK: {len(df_dw)} baris")
with col_dw2:
    if up:
        st.session_state.daftarwilayah = pd.read_excel(up)
        st.success(f"Diunggah: {len(st.session_state.daftarwilayah)} baris")
    if st.button("💾 Simpan daftarwilayah ke OUTPUT/DaftarWilayah/NamaSurvey"):
        if st.session_state.daftarwilayah is None or st.session_state.daftarwilayah.empty:
            st.warning("Belum ada data daftarwilayah.")
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Daftar_wilayah_{fullcode_kab}_{nama_survey}_{ts}.xlsx"
            path = os.path.join(DW_DIR, filename)
            st.session_state.daftarwilayah.to_excel(path, index=False)
            st.success(f"✅ Disimpan: {path}")

if st.session_state.daftarwilayah is not None:
    st.dataframe(st.session_state.daftarwilayah.head(200), use_container_width=True)
    buf_dw = io.BytesIO()
    st.session_state.daftarwilayah.to_excel(buf_dw, index=False); buf_dw.seek(0)
    st.download_button("⬇️ Download daftarwilayah.xlsx", buf_dw.getvalue(),
                       file_name="daftarwilayah.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.stop()

# =================== 4) Ambil Raw Data (opsional) ===================
st.header("4) Ambil Raw Data (opsional)")
def ambil_raw():
    res_rows, assign_parts = [], []
    total = len(st.session_state.daftarwilayah['smallcode'])
    prog = st.progress(0); status = st.empty()
    for i, small in enumerate(st.session_state.daftarwilayah['smallcode'], start=1):
        try:
            data_assign = try_fetch_assignments(session, headers, survey_period_id, template_id, small)
            if data_assign: assign_parts.append(pd.DataFrame(data_assign))
            for d in data_assign:
                aid = d.get("assignmentId")
                if not aid: continue
                r = session.get("https://fasih-sm.bps.go.id/assignment-general/api/assignment/get-by-id-with-data-for-scm",
                                headers=headers, params={"id": aid}, timeout=40)
                if not r.ok:
                    status.write(f"❌ {small}: gagal detail {aid} ({r.status_code})"); continue
                inner = json.loads(r.json()["data"]["data"])
                row = pd.DataFrame([extract_answers(inner.get("answers", []))])
                row["assignment_id"] = aid
                row["link_preview"] = f"https://fasih-sm.bps.go.id/survey-collection/survey-review/{aid}/{template_id}/{survey_period_id}/a/1"
                res_rows.append(row)
            status.write(f"✅ {small}: {len(data_assign)} assignment")
        except Exception as e:
            status.write(f"❌ {small}: {e}")
        finally:
            prog.progress(int(i/total*100))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # RAW
    out1 = io.BytesIO()
    df_main = pd.concat(res_rows, ignore_index=True) if res_rows else pd.DataFrame()
    with pd.ExcelWriter(out1, engine="openpyxl") as w: df_main.to_excel(w, index=False, sheet_name="raw_answers")
    out1.seek(0)
    file_raw = f"Raw_Data_{fullcode_kab}_{nama_survey}_{survey_period_name}_{ts}.xlsx"
    with open(os.path.join(RAW_DIR, file_raw), "wb") as f: f.write(out1.getvalue())
    st.download_button("⬇️ Download RAW", out1.getvalue(), file_name=file_raw,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    # ASSIGN
    out2 = io.BytesIO()
    df_assign = pd.concat(assign_parts, ignore_index=True) if assign_parts else pd.DataFrame()
    with pd.ExcelWriter(out2, engine="openpyxl") as w: df_assign.to_excel(w, index=False, sheet_name="assignments")
    out2.seek(0)
    file_assign = f"Assignment_{fullcode_kab}_{nama_survey}_{survey_period_name}_{ts}.xlsx"
    with open(os.path.join(RAW_DIR, file_assign), "wb") as f: f.write(out2.getvalue())
    st.download_button("⬇️ Download ASSIGN", out2.getvalue(), file_name=file_assign,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if st.button("▶️ Mulai Ambil Raw Data"):
    ambil_raw()

# =================== 5) APPROVE (UI) ===================
st.header("5) Approve Assignments (UI)")
role = st.selectbox("Pilih Role:", ["Pengawas", "PML", "Admin Kabupaten", "Admin Provinsi"], index=1)
approve_all = st.checkbox("Approve semua wilayah", value=True)
subset_mode = st.checkbox("Gunakan subset smallcode", value=False)
subset_smalls = []
if subset_mode:
    smalls_all = list(st.session_state.daftarwilayah['smallcode'])
    subset_smalls = st.multiselect("Pilih smallcode", options=smalls_all, default=smalls_all[:10])
headless_browser = st.checkbox("Browser headless (lebih cepat, kadang kurang stabil)", value=False)

def _role_allows(role_name: str, current_status: str) -> bool:
    return (
        (role_name == 'Pengawas' and current_status == 'SUBMITTED BY Pencacah')
        or (role_name == 'PML' and current_status == 'SUBMITTED BY PPL')
        or (role_name == 'Admin Kabupaten' and current_status in ['APPROVED BY Pengawas', 'APPROVED BY PML', 'EDITED BY Admin Kabupaten'])
        or (role_name == 'Admin Provinsi' and current_status == 'COMPLETED BY Admin Kabupaten')
    )

def run_approve_ui():
    # pastikan injeksi + handshake (jika user hanya Muat Session)
    drv = inject_cookies_and_handshake(session, headless=headless_browser)

    base_assign = "https://fasih-sm.bps.go.id/assignment-general/api/assignments/get-principal-values-by-smallest-code"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = os.path.join(APPR_DIR, f"Log_Approve_{nama_kab}_{nama_survey}_{survey_period_name}_{ts}.xlsx")

    log_rows = []
    smcodes = subset_smalls if subset_mode else list(st.session_state.daftarwilayah['smallcode'])
    total = len(smcodes)
    prog = st.progress(0)
    status = st.empty()

    for i, smallCode in enumerate(smcodes, start=1):
        try:
            # ambil assignments (dua pola)
            urlA = f'{base_assign}/{survey_period_id}/{template_id}/{smallCode}'
            rA = session.get(urlA, headers=headers, timeout=40)
            data = []
            if rA.ok:
                try: data = rA.json().get('data', []) or []
                except Exception: data = []
            if not data:
                urlB = f'{base_assign}/{survey_period_id}/{smallCode}'
                rB = session.get(urlB, headers=headers, timeout=40)
                if rB.ok:
                    try: data = rB.json().get('data', []) or []
                    except Exception: data = []

            if not data:
                status.write(f"ℹ️ {smallCode}: tidak ada data isian.")
                prog.progress(int(i/total*100))
                continue

            for d in data:
                assignment_id = d.get('assignmentId')
                if not assignment_id: continue
                review_url = f'https://fasih-sm.bps.go.id/survey-collection/survey-review/{assignment_id}/{template_id}/{survey_period_id}/a/1'
                hist_url   = f'https://fasih-sm.bps.go.id/assignment-general/api/assignment-history/get-by-assignment-id?assignmentId={assignment_id}'
                try:
                    r = session.get(hist_url, headers=headers, timeout=30)
                    hist_list = parse_assignment_status(r.json())
                    status_assignment = hist_list[-1]['status_assignment'] if hist_list else ""
                except Exception as e:
                    status_assignment = ""
                    status.write(f"⚠️ {smallCode}: gagal riwayat {assignment_id}: {e}")

                approved = False
                ket = ""
                try:
                    if not _role_allows(role, status_assignment):
                        ket = f"❌ Belum memenuhi syarat (status: {status_assignment})"
                    else:
                        drv.get(review_url)
                        wait = WebDriverWait(drv, 30)
                        btn = wait.until(EC.element_to_be_clickable((By.ID, "buttonApprove")))
                        clicked, attempt, max_attempts = False, 0, 5
                        while not clicked and attempt < max_attempts:
                            try:
                                time.sleep(0.5)
                                btn.click(); clicked = True
                            except (ElementClickInterceptedException, StaleElementReferenceException):
                                attempt += 1
                                btn = wait.until(EC.element_to_be_clickable((By.ID, "buttonApprove")))
                        if not clicked:
                            raise RuntimeError("Gagal klik Approve")

                        # Konfirmasi 1
                        try:
                            conf = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="fasih"]/div/div/div[6]/button[1]')))
                            conf.click()
                        except TimeoutException:
                            pass
                        # Konfirmasi 2 (opsional)
                        try:
                            conf2 = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="fasih"]/div/div/div[6]/button[1]')))
                            conf2.click()
                        except TimeoutException:
                            pass

                        approved = True
                        ket = "✅ Approved"
                        status.write(f"✅ {smallCode}: approved {assignment_id}")
                except TimeoutException:
                    ket = "❌ Timeout elemen"
                except WebDriverException as e:
                    ket = f"❌ WebDriver error: {e}"
                except Exception as e:
                    ket = f"❌ Error: {e}"

                log_rows.append({
                    "smallCode": smallCode,
                    "assignment_id": assignment_id,
                    "status_assignment": status_assignment,
                    "approved": approved,
                    "keterangan": ket,
                    "link_assignment": review_url,
                })
        except Exception as e:
            status.write(f"🚨 {smallCode}: error {e}")
        finally:
            prog.progress(int(i/total*100))

    df_log = pd.DataFrame(log_rows)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df_log.to_excel(w, index=False, sheet_name="approve_log")
    out.seek(0)
    with open(logfile, "wb") as f: f.write(out.getvalue())
    st.success(f"✅ Log disimpan: {logfile}")
    st.download_button("⬇️ Download Log Approve", out.getvalue(),
                       file_name=os.path.basename(logfile),
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.dataframe(df_log, use_container_width=True)

if st.button("🚀 Jalankan Approve"):
    if st.session_state.daftarwilayah is None or st.session_state.daftarwilayah.empty:
        st.warning("Daftarwilayah kosong.")
    else:
        try:
            run_approve_ui()
        except Exception as e:
            st.error(f"Gagal menjalankan approve: {e}")
