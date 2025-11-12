import streamlit as st
import pandas as pd
import time
import json
import os
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

# === Konfigurasi dasar ===
CACHE_DIR = "cached_data"
os.makedirs(CACHE_DIR, exist_ok=True)

# === Helper: caching sederhana ===
@st.cache_data
def cached_dataframe(name: str):
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        return pd.read_excel(path)
    return pd.DataFrame()

def save_cache(df: pd.DataFrame, name: str):
    path = os.path.join(CACHE_DIR, name)
    df.to_excel(path, index=False)

def clear_all_cache():
    st.cache_data.clear()
    for f in os.listdir(CACHE_DIR):
        os.remove(os.path.join(CACHE_DIR, f))

# === Fungsi Helper HTTP ===
def safe_request(url, headers, max_retries=3, timeout=15):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return resp
            else:
                st.warning(f"⚠️ Status {resp.status_code} untuk {url}")
        except requests.exceptions.Timeout:
            st.warning(f"⏳ Timeout ({attempt+1}/{max_retries}) untuk {url}")
        except requests.exceptions.RequestException as e:
            st.warning(f"❌ Error koneksi: {e}")
        time.sleep(2 * (attempt + 1))
    return None

def ambil_detail_kegiatan(row, headers):
    kd_survei = row['kd_survei']
    id_keg = row['id_keg']
    nama_survei = row['nama_survei']
    nama_keg = row['nama_keg']
    url = f'https://mitra-api.bps.go.id/api/mitra/listv3/{kd_survei}/{id_keg}/63/10'

    resp = safe_request(url, headers)
    if resp and resp.status_code == 200 and resp.json():
        res = resp.json()
        detail = pd.json_normalize(res)
        detail['kd_survei'] = kd_survei
        detail['nama_survei'] = nama_survei
        detail['id_keg'] = id_keg
        detail['nama_keg'] = nama_keg
        return detail
    return pd.DataFrame()

def ambil_kegiatan(row, headers):
    kode_keg = row['kd_survei']
    status_survei = row['status survei']
    nama_survei = row['nama']

    urls = [
        {'url': f'https://mitra-api.bps.go.id/api/keg/list/ks/{kode_keg}/2/0/1?p=63&k=10', 'status': "Belum Mulai"},
        {'url': f'https://mitra-api.bps.go.id/api/keg/list/ks/{kode_keg}/2/0/2?p=63&k=10', 'status': "Aktif"},
        {'url': f'https://mitra-api.bps.go.id/api/keg/list/ks/{kode_keg}/2/0/3?p=63&k=10', 'status': "Selesai"}
    ]

    semua_kegiatan = []
    for u in urls:
        resp = safe_request(u['url'], headers)
        if resp and resp.status_code == 200:
            try:
                res = resp.json()
                if res and 'keg_surveis' in res:
                    df = pd.json_normalize(res['keg_surveis'])
                    df['status kegiatan'] = u['status']
                    df['status survei'] = status_survei
                    semua_kegiatan.append(df)
            except Exception as e:
                st.warning(f"⚠️ Gagal parsing {nama_survei} - {u['status']}: {e}")
                continue

    if semua_kegiatan:
        return pd.concat(semua_kegiatan, ignore_index=True)
    return pd.DataFrame()

# === Fungsi login ===
def login_sso(username, password):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    options.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})
    driver = webdriver.Chrome(service=Service(), options=options)

    driver.get("https://manajemen-mitra.bps.go.id/launcher")
    wait = WebDriverWait(driver, 20)

    try:
        tombol_login = wait.until(
            EC.element_to_be_clickable((By.XPATH, "/html/body/div/div[1]/div/div/div/div/span/form/div/div[4]/button"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", tombol_login)
        tombol_login.click()
    except TimeoutException:
        st.error("❌ Gagal menemukan tombol login SSO.")
        driver.quit()
        return None
    except ElementClickInterceptedException:
        st.warning("⚠️ Tombol login tertutup overlay, menunggu sebentar...")
        time.sleep(3)
        driver.execute_script("arguments[0].click();", tombol_login)

    wait.until(EC.presence_of_element_located((By.ID, "username")))
    driver.find_element(By.ID, "username").send_keys(username)
    driver.find_element(By.ID, "password").send_keys(password)
    driver.find_element(By.ID, "kc-login").click()
    time.sleep(3)

    st.success("--- Berhasil Login ---")

    for i in range(2):
        logs = driver.get_log("performance")
        driver.get("https://manajemen-mitra.bps.go.id/launcher")
        driver.get("https://manajemen-mitra.bps.go.id/mitra/seleksi")
        time.sleep(2)

    for entry in logs:
        if "Bearer" in str(entry["message"]):
            json_message_data = json.loads(str(entry["message"]))
            try:
                authorization_json = json_message_data['message']['params']['request']['headers']['Authorization']
            except:
                authorization_json = json_message_data['message']['params']['headers']['Authorization']
            driver.quit()
            return authorization_json

    driver.quit()
    st.error("❌ Token Bearer tidak ditemukan!")
    return None


# === STREAMLIT UI ===
st.title("📊 Dashboard Rekap Mitra per Kegiatan BPS")
st.caption("Scraping otomatis data mitra BPS (Kabupaten Tanah Bumbu)")

# Tombol reset cache
if st.button("♻️ Reset Cache & Mulai Ulang"):
    clear_all_cache()
    for key in ["token", "survei_df", "kegiatan_df", "mitra_df", "last_selected"]:
        if key in st.session_state:
            del st.session_state[key]
    st.warning("Cache dihapus, silakan jalankan ulang scraping.")
    st.stop()

# === LOGIN HANDLER ===
if "token" not in st.session_state:
    st.session_state["token"] = None

if st.session_state["token"]:
    st.success("✅ Token login tersedia.")
else:
    username = st.text_input("👤 Username SSO")
    password = st.text_input("🔒 Password SSO", type="password")
    if st.button("🚀 Login & Jalankan Scraping"):
        with st.spinner("Login ke SSO dan mengambil token..."):
            token = login_sso(username, password)
        if token:
            st.session_state["token"] = token
            st.success("✅ Login berhasil. Silakan lanjutkan.")
        else:
            st.stop()

token = st.session_state["token"]
if not token:
    st.stop()

headers = {
    'Accept': 'application/json, text/plain, */*',
    'Authorization': token,
    'Origin': 'https://manajemen-mitra.bps.go.id',
    'Referer': 'https://manajemen-mitra.bps.go.id/'
}

# === AMBIL DATA SURVEI ===
if "survei_df" not in st.session_state:
    survei_df = cached_dataframe("list_survey.xlsx")
    if survei_df.empty:
        with st.spinner("Mengambil daftar survei..."):
            berjalan = requests.get('https://mitra-api.bps.go.id/api/survei/list/1', headers=headers).json()['surveis']
            selesai = requests.get('https://mitra-api.bps.go.id/api/survei/list/2', headers=headers).json()['surveis']
            survei_df = pd.concat([
                pd.json_normalize(berjalan).assign(**{'status survei': 'Berjalan'}),
                pd.json_normalize(selesai).assign(**{'status survei': 'Selesai'})
            ], ignore_index=True)
            save_cache(survei_df, "list_survey.xlsx")
    st.session_state["survei_df"] = survei_df

survei_df = st.session_state["survei_df"]
st.success(f"📦 Ditemukan {len(survei_df)} survei.")

# === AMBIL DATA KEGIATAN ===
if "kegiatan_df" not in st.session_state:
    kegiatan_df = cached_dataframe("list_kegiatan.xlsx")
    if kegiatan_df.empty:
        progress = st.progress(0)
        list_all_survey = []
        total = len(survei_df)
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(ambil_kegiatan, row, headers): idx for idx, row in survei_df.iterrows()}
            for i, future in enumerate(as_completed(futures)):
                result = future.result()
                if not result.empty:
                    list_all_survey.append(result)
                progress.progress((i + 1) / total)
        kegiatan_df = pd.concat(list_all_survey, ignore_index=True)
        save_cache(kegiatan_df, "list_kegiatan.xlsx")
    st.session_state["kegiatan_df"] = kegiatan_df

kegiatan_df = st.session_state["kegiatan_df"]
st.success(f"✅ {len(kegiatan_df)} kegiatan berhasil diambil.")

# === PILIH KEGIATAN ===
st.subheader("📌 Pilih Kegiatan")

if not kegiatan_df.empty:
    kegiatan_df['label_kegiatan'] = (
        kegiatan_df['nama_survei'] + " — " +
        kegiatan_df['nama_keg'] + " (" + kegiatan_df['status kegiatan'] + ")"
    )

    pilihan = st.selectbox(
        "Pilih salah satu kegiatan:",
        options=kegiatan_df['label_kegiatan'].unique(),
        index=None,
        key="pilihan_kegiatan",
        placeholder="Pilih kegiatan untuk melihat daftar mitra..."
    )

    if pilihan:
        selected_row = kegiatan_df[kegiatan_df['label_kegiatan'] == pilihan].iloc[0]
        st.info(f"📄 Menampilkan mitra untuk: **{selected_row['nama_survei']} - {selected_row['nama_keg']}**")

        if "mitra_df" not in st.session_state or st.session_state.get("last_selected") != pilihan:
            with st.spinner("🔍 Mengambil daftar mitra..."):
                detail_df = ambil_detail_kegiatan(selected_row, headers)
                st.session_state["mitra_df"] = detail_df
                st.session_state["last_selected"] = pilihan
        else:
            detail_df = st.session_state["mitra_df"]

        if not detail_df.empty:
            st.success(f"🎯 Total {len(detail_df)} mitra ditemukan.")
            st.dataframe(detail_df)

            tanggalsekarang = time.strftime("%Y%m%d")
            filename = f"{tanggalsekarang} - Daftar Mitra - {selected_row['nama_keg']}.xlsx"
            detail_df.to_excel(filename, index=False)

            st.download_button(
                label="💾 Download Daftar Mitra",
                data=open(filename, "rb"),
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("❌ Tidak ada mitra untuk kegiatan ini.")
else:
    st.warning("Belum ada data kegiatan untuk ditampilkan.")
