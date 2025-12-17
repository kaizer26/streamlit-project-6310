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
from multiprocessing import Pool, cpu_count
from functools import partial
from tqdm import tqdm


# === Konfigurasi dasar ===
KEY_ID = '687e204db62094de46edbcd7ed7cb204'
CACHE_DIR = "cached_data"
os.makedirs(CACHE_DIR, exist_ok=True)

# === Helper: caching sederhana ===
@st.cache_data
def getReq(url):
    """Ambil data dari URL dan kembalikan hasil JSON jika sukses, None jika gagal."""
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data
        else:
            print(f"Gagal mengambil data: {response.status_code}")
            return None
    except Exception as e:
        print(f"Terjadi error saat request: {e}")
        return None

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

def worker_detail_mitra(id_mitra, headers):
    try:
        url = f'https://mitra-api.bps.go.id/api/mitra/id/{id_mitra}'
        resp = safe_request(url, headers)

        if resp and resp.status_code == 200 and resp.json():
            df = pd.json_normalize(resp.json())
            df['id_mitra'] = id_mitra
            return df
    except:
        pass
    return pd.DataFrame()


def ambil_detail_mitra(id_mitra, headers):
    """Ambil detail satu mitra berdasarkan ID"""
    url = f'https://mitra-api.bps.go.id/api/mitra/id/{id_mitra}'
    resp = safe_request(url, headers)

    if resp and resp.status_code == 200 and resp.json():
        try:
            return pd.json_normalize(resp.json())
        except:
            return pd.DataFrame()
    return pd.DataFrame()


SEMUA_KOLOM = set()
def ambil_detail_kegiatan(row, headers, kode_prov, kode_kab, versi=3):
    kd_survei = row['kd_survei']
    id_keg = row['id_keg']
    nama_survei = row['nama_survei']
    nama_keg = row['nama_keg']

    # Endpoint list
    if versi == 3:
        url = f'https://mitra-api.bps.go.id/api/mitra/listv3/{kd_survei}/{id_keg}/{kode_prov}/{kode_kab}'
    else:
        url = f'https://mitra-api.bps.go.id/api/mitra/listv4/{kd_survei}/{id_keg}/{kode_prov}/{kode_kab}'

    resp = safe_request(url, headers)

    if not (resp and resp.status_code == 200 and resp.json()):
        return pd.DataFrame()

    list_mitra = pd.json_normalize(resp.json())

    # metadata kegiatan
    list_mitra['kd_survei'] = kd_survei
    list_mitra['nama_survei'] = nama_survei
    list_mitra['id_keg'] = id_keg
    list_mitra['nama_keg'] = nama_keg

    # Ambil id_mitra
    list_id = list_mitra.get('id_mitra', list_mitra.get('id')).tolist()

    if not list_id:
        return pd.DataFrame()

    # =========================================================
    #   MULTIPROCESSING + tqdm
    # =========================================================
    worker = partial(worker_detail_mitra, headers=headers)

    total_cpu = max(cpu_count() - 1, 1)

    with Pool(total_cpu) as pool:
        detail_list = list(
            tqdm(pool.imap(worker, list_id), 
                 total=len(list_id), 
                 desc=f"Ambil detail mitra {nama_keg}")
        )

    # Buang yang kosong
    detail_list = [d for d in detail_list if not d.empty]

    if not detail_list:
        return pd.DataFrame()

    # Merge seluruh detail
    df_detail = pd.concat(detail_list, ignore_index=True)

    # Merge metadata kegiatan
    df_merged = df_detail.merge(list_mitra, on='id_mitra', how='left')

    # Pastikan semua kolom lengkap
    global SEMUA_KOLOM
    SEMUA_KOLOM.update(df_merged.columns)

    for kol in SEMUA_KOLOM:
        if kol not in df_merged.columns:
            df_merged[kol] = ""

    return df_merged

# === Fungsi ambil_kegiatan dengan kode wilayah dinamis ===
def ambil_kegiatan(row, headers, kode_prov, kode_kab):
    kode_keg = row['kd_survei']
    status_survei = row['status survei']
    nama_survei = row['nama']

    urls = [
        {'url': f'https://mitra-api.bps.go.id/api/keg/list/ks/{kode_keg}/2/0/1?p={kode_prov}&k={kode_kab}', 'status': "Belum Mulai"},
        {'url': f'https://mitra-api.bps.go.id/api/keg/list/ks/{kode_keg}/2/0/2?p={kode_prov}&k={kode_kab}', 'status': "Aktif"},
        {'url': f'https://mitra-api.bps.go.id/api/keg/list/ks/{kode_keg}/2/0/3?p={kode_prov}&k={kode_kab}', 'status': "Selesai"}
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

@st.cache_data(show_spinner=False)
def ambil_detail_kegiatan_cached(row_dict, headers, kode_prov, kode_kab, versi=3):
    row = pd.Series(row_dict)
    return ambil_detail_kegiatan(row, headers, kode_prov, kode_kab, versi)


@st.cache_data(show_spinner=False)
def ambil_kegiatan_cached(selected_survei_dict, headers, kode_prov, kode_kab):
    selected_survei = pd.Series(selected_survei_dict)
    return ambil_kegiatan(selected_survei, headers, kode_prov, kode_kab)


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
st.set_page_config(page_title="📊 Dashboard Rekap Mitra per Kegiatan BPS", layout="wide")
st.title("📊 Dashboard Rekap Mitra per Kegiatan BPS")
st.caption("Scraping otomatis data mitra BPS (Kabupaten Tanah Bumbu)")

# Tombol reset cache
if st.button("♻️ Reset Cache & Mulai Ulang"):
    clear_all_cache()
    for key in ["token", "survei_df", "kegiatan_df", "mitra_df", "last_selected"]:
        if key in st.session_state:
            del st.session_state[key]
    st.warning("🧹 Semua cache & sesi login dihapus. Halaman akan dimuat ulang...")
    time.sleep(1)   
    st.rerun()  # versi baru pengganti st.experimental_rerun()

# === LOGIN HANDLER ===
if "token" not in st.session_state:
    st.session_state["token"] = None

if st.session_state["token"]:
    st.success("✅ Token login tersedia.")
else:
    # Pilih Domain SSO
    st.subheader("🔐 Login SSO BPS")
    
    # === Ambil daftar domain dari API ===
    list_domain = getReq(f"https://webapi.bps.go.id/v1/api/domain/type/all/key/{KEY_ID}/")

    # pastikan hasilnya DataFrame atau list berisi 4 digit kode wilayah
    if list_domain and 'data' in list_domain:
        domain_df = pd.DataFrame(list_domain['data'][1])
        # ambil hanya kolom kode (4 digit)
        domain_codes = domain_df['domain_id'].tolist()  # sesuai struktur yang kamu sebut
    else:
        domain_codes = ['6310']  # default fallback

    # === Pilihan domain ===
    default_domain = "6310"

    # cari posisi default domain di list (jika ada)
    if default_domain in domain_codes:
        default_index = domain_codes.index(default_domain)
    else:
        default_index = 0  # fallback kalau 6310 tidak ditemukan

    domain = st.selectbox("Pilih Domain (kode wilayah)", domain_codes, index=default_index)

    # pecah domain jadi 2 bagian: provinsi dan kabupaten
    kode_prov = domain[:2]
    kode_kab = domain[2:]

    # simpan di session_state supaya tetap ada setelah reload
    st.session_state["kode_prov"] = kode_prov
    st.session_state["kode_kab"] = kode_kab

    username = st.text_input("👤 Username SSO", value="vivi.cantika")
    password = st.text_input("🔒 Password SSO", value="Vivi2405", type="password")
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

# === PILIH SURVEI ===
st.subheader("📌 Pilih Survei")

if not survei_df.empty:
    pilihan_survei = st.selectbox(
        "Pilih salah satu survei:",
        options=survei_df['nama'].unique(),
        index=None,
        placeholder="Pilih survei untuk melihat daftar kegiatan..."
    )

    if pilihan_survei:
        selected_survei = survei_df[survei_df['nama'] == pilihan_survei].iloc[0]
        # st.info(f"📄 Mengambil kegiatan untuk survei: **{selected_survei['nama']}**")

        # Ambil kegiatan HANYA untuk survei ini
        with st.spinner("🔍 Mengambil daftar kegiatan..."):
            selected_survei_dict = selected_survei.to_dict()

            kegiatan_df = ambil_kegiatan_cached(
                selected_survei_dict, headers,
                st.session_state.get("kode_prov", "63"),
                st.session_state.get("kode_kab", "10"),
            )

        if not kegiatan_df.empty:
            # st.success(f"✅ Ditemukan {len(kegiatan_df)} kegiatan untuk survei {selected_survei['nama']}.")
            
            kegiatan_df['label_kegiatan'] = (
                kegiatan_df['nama_keg'] + " (" + kegiatan_df['status kegiatan'] + ")"
            )

            pilihan_kegiatan = st.selectbox(
                "Pilih kegiatan:",
                options=kegiatan_df['label_kegiatan'].unique(),
                index=None,
                key="pilihan_kegiatan",
                placeholder="Pilih kegiatan untuk melihat daftar mitra..."
            )

            if pilihan_kegiatan:
                selected_row = kegiatan_df[kegiatan_df['label_kegiatan'] == pilihan_kegiatan].iloc[0]
                # st.info(f"📄 Mengambil mitra untuk kegiatan: **{selected_row['nama_keg']}**")

                with st.spinner("🧩 Mengambil daftar mitra..."):
                    selected_row_dict = selected_row.to_dict()

                    detail_df_v3 = ambil_detail_kegiatan_cached(
                        selected_row_dict, headers,
                        st.session_state.get("kode_prov", "63"),
                        st.session_state.get("kode_kab", "10"),
                        versi=3
                    )

                    detail_df_v4 = ambil_detail_kegiatan_cached(
                        selected_row_dict, headers,
                        st.session_state.get("kode_prov", "63"),
                        st.session_state.get("kode_kab", "10"),
                        versi=4
                    )                   

                if not detail_df_v3.empty and not detail_df_v4.empty:
                    st.dataframe(detail_df_v3)
                    st.success(f"🎯 Total {len(detail_df_v3)} mitra ditemukan.")
                    # 🔹 Daftar kolom yang ingin diekspor
                    kolom_dipilih = [
                        "mitra_detail.nik",
                        "mitra_detail.nama_lengkap",
                        "mitra_detail.email",
                        "ket_status",
                        "nama_pos_daftar",
                        "id_mitra",
                        "mitra_detail.npwp",
                        "mitra_detail.username",
                        "mitra_detail.alamat_detail",
                        "mitra_detail.alamat_prov",
                        "mitra_detail.alamat_kab",
                        "mitra_detail.alamat_kec",
                        "mitra_detail.alamat_desa",
                        "mitra_detail.tgl_lahir",
                        "mitra_detail.jns_kelamin",
                        "mitra_detail.agama",
                        "mitra_detail.status_kawin",
                        "mitra_detail.pendidikan",
                        "mitra_detail.pekerjaan",
                        "mitra_detail.desc_pekerjaan_lain",
                        "mitra_detail.no_telp",
                        "mitra_detail.foto",
                        "mitra_detail.foto_ktp",
                        "mitra_detail.catatan",
                        "mitra_detail.is_pegawai",
                        "mitra_detail.sobat_id",
                        "mitra_detail.ijazah",
                        "mitra_detail.is_capi",
                        "mitra_detail.is_motor",
                        "mitra_detail.is_naik_motor",
                        "mitra_detail.is_hp_android",
                        "mitra_detail.is_kl_lain",
                        "mitra_detail.nama_kl",
                        "mitra_detail.keterangan_kl",
                        "mitra_detail.is_bisa_komputer",
                        "mitra_detail.is_laptop",
                        "mitra_detail.is_ujian",
                        "nama_survei",
                        "id_keg",
                        "nama_keg",
                    ]
                    
                    kolom_dipilih1 = [
                        "mitra_detail.nik",
                        "mitra_detail.nama_lengkap",
                        "mitra_detail.email",
                        "nama_pos_daftar",
                        "ket_status",
                        "skor",
                        "tes_start",
                        "tes_end",
                        "agreement_status",]
                    
                    kolom_dipilih2 = [
                        "mitra.idmitra",
                        "mitra.nik",
                        "mitra.nama_lengkap",
                        "mitra.email",
                        "mitra.username",
                        "mitra.status",
                        "mitra.npwp",
                        "mitra.alamat_detail",
                        "mitra.alamat_prov",
                        "mitra.alamat_kab",
                        "mitra.alamat_kec",
                        "mitra.alamat_desa",
                        "mitra.alamat_is",
                        "mitra.tgl_lahir",
                        "mitra.jns_kelamin",
                        "mitra.agama",
                        "mitra.status_kawin",
                        "mitra.pendidikan",
                        "mitra.pekerjaan",
                        "mitra.desc_pekerjaan_lain",
                        "mitra.no_telp",
                        "mitra.is_pendataan_bps",
                        "mitra.is_sp",
                        "mitra.is_st",
                        "mitra.is_se",
                        "mitra.is_susenas",
                        "mitra.is_sakernas",
                        "mitra.is_sbh",
                        "mitra.foto",
                        "mitra.foto_ktp",
                        "mitra.catatan",
                        "mitra.is_agree",
                        "mitra.is_complete",
                        "mitra.sobat_id",
                        "mitra.ijazah",
                        "mitra.is_capi",
                        "mitra.is_motor",
                        "mitra.is_naik_motor",
                        "mitra.is_hp_android",
                        "mitra.is_kl_lain",
                        "mitra.nama_kl",
                        "mitra.keterangan_kl",
                        "mitra.kd_bank",
                        "mitra.rekening",
                        "mitra.kd_prov_lahir",
                        "mitra.kd_kab_lahir",
                        "mitra.is_bisa_komputer",
                        "mitra.is_laptop",
                        "mitra.merk_hp",
                        "mitra.tipe_hp",
                        "mitra.ram_hp",
                        "mitra.lahir_ln",
                        "mitra.lahir_tempat_ln",
                        "mitra.rekening_nama",
                        "mitra.is_ujian",
                        "id_mitra",
                        "id_ms",
                        "kd_survei",
                        "id_kegiatan",
                        "id_posisi",
                        "nama_pos",
                        "kd_prov",
                        "kd_kab",
                        "status",
                        "ket_status",
                        "kd_mitra",
                        "id_posisi_daftar",
                        "nama_pos_daftar",
                        "nama_survei",
                        "id_keg",
                        "nama_keg",

                    ]
                    
                    # 🔹 Hanya ambil kolom yang tersedia (untuk menghindari error jika ada kolom hilang)
                    kolom_tersedia = [k for k in kolom_dipilih if k in detail_df_v3.columns]
                    kolom_tersedia2 = [k for k in kolom_dipilih2 if k in detail_df_v3.columns]
                                                
                    export_df = detail_df_v3[kolom_tersedia]
                    export_df1 = detail_df_v4.reindex(columns=kolom_dipilih1, fill_value="")
                    
                    tanggalsekarang = time.strftime("%Y%m%d")
                    filename = f"{tanggalsekarang} - Daftar Mitra - {selected_row['nama_keg']} - Full.xlsx"
                    filename1 = f"{tanggalsekarang} - Daftar Mitra - {selected_row['nama_keg']} - 2.xlsx"
                    filename2 = f"{tanggalsekarang} - Daftar Mitra - {selected_row['nama_keg']} - (Seleksi).xlsx"
                    
                    detail_df_v3.to_excel(filename, index=False)
                    # 🔹 Simpan ke buffer Excel tanpa buat file fisik
                    from io import BytesIO
                    buffer = BytesIO()
                    buffer1 = BytesIO()
                    export_df.to_excel(buffer, index=False, engine='openpyxl')
                    buffer.seek(0)
                    export_df1.to_excel(buffer1, index=False, engine='openpyxl')
                    buffer1.seek(0)

                    # 🔹 Tombol download
                    st.download_button(
                        label="💾 Download Daftar Mitra Seleksi (Excel)",
                        data=buffer1,
                        file_name=filename2,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    st.download_button(
                        label="💾 Download Daftar Mitra (Excel)",
                        data=buffer,
                        file_name=filename1,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    st.download_button(
                        label="💾 Download Daftar Mitra (Full)",
                        data=open(filename, "rb"),
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.warning("❌ Tidak ada mitra untuk kegiatan ini.")
        else:
            st.warning("🚫 Tidak ditemukan kegiatan untuk survei ini.")
else:
    st.warning("Belum ada data survei untuk ditampilkan.")

    
