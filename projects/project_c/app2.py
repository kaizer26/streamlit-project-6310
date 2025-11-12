from getpass import getpass
import tkinter as tk
from tkinter import filedialog
from typing import Dict
from tqdm import tqdm
import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
import platform
from http.cookiejar import Cookie, CookieJar
from requests.cookies import RequestsCookieJar
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, StaleElementReferenceException
# import browser_cookie3
import os, io, re, time, json, pickle, urllib.parse
from datetime import datetime
from pathlib import Path
import streamlit as st

def simpan_session(username, headers, cookies, session, password=None):
    session_path = pilih_folder_simpan("Pilih Folder untuk Menyimpan Session Login")

    # Cek apakah folder yang dipilih sudah bernama 'sessions'
    if os.path.basename(os.path.normpath(session_path)).lower() == "sessions":
        sessions_dir = session_path  # langsung gunakan folder itu
    else:
        sessions_dir = os.path.join(session_path, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)

    filepath = os.path.join(sessions_dir, f"{username}_session.pkl")
    with open(filepath, 'wb') as f:
        pickle.dump({'username': username, 'password': password,'headers': headers, 'cookies': cookies, 'session': session}, f)


def muat_session(username):
    sessions_dir = os.path.join(os.getcwd(), "sessions")

    filepath = os.path.join(sessions_dir, f"{username}_session.pkl")
    if os.path.exists(filepath):
        with open(filepath, 'rb') as f:
            data = pickle.load(f)
            if data.get('session'):
                st.success("✅ Session berhasil dimuat dari file.")
                return data.get('headers'), data.get('cookies'), data.get('session'), data.get('password', None)
    return None, None, None, None


def setup_driver_with_cookies(cookies, url='https://fasih-sm.bps.go.id') -> webdriver.Chrome:
    service = Service()
    chrome_options = Options()
    # chrome_options.add_argument("--headless")  # opsional
    
    # Matikan password manager & save password bubble
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    
    
    chrome_options.add_argument("--log-level=3")          # Hanya tampilkan error fatal
    chrome_options.add_argument("--disable-logging")      # Nonaktifkan log tambahan
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])  # Sembunyikan pesan logging Windows
    chrome_options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.get(url)  # penting: buka domain sebelum set cookie

    for name, value in cookies.items():
        cookie_dict = {
            'name': name,
            'value': value,
            'domain': '.bps.go.id'
        }
        try:
            driver.add_cookie(cookie_dict)
        except Exception as e:
            print(f"Gagal menambahkan cookie {name}: {e}")

    driver.refresh()  # reload supaya login aktif
    return driver

def is_session_valid(session):
    try:
        resp = session.get("https://fasih-sm.bps.go.id/survey/api/v1/surveys", allow_redirects=False)
        return resp.status_code == 200
    except:
        return False


def clear_screen():
    os.system('cls' if platform.system() == 'Windows' else 'clear')


def setup_driver() -> webdriver.Chrome:
    service = Service()
    chrome_options = Options()
    # chrome_options.add_argument("--headless")  # opsional
    
    # Matikan password manager & save password bubble
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    
    
    chrome_options.add_argument("--log-level=3")          # Hanya tampilkan error fatal
    chrome_options.add_argument("--disable-logging")      # Nonaktifkan log tambahan
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])  # Sembunyikan pesan logging Windows
    chrome_options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def login_sso(driver: webdriver.Chrome, username: str, password: str) -> None:
    driver.get("https://sso.bps.go.id")
    driver.find_element(By.NAME, "username").send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password)
    driver.find_element(By.XPATH, '//*[@id="kc-login"]').click()
    time.sleep(1)
    try:
        otp_element = driver.find_element(By.XPATH, '//*[@id="otp"]')
        # otp = input("Masukkan OTP yang Anda terima: ")
        otp = st.sidebar.text_input("OTP", max_chars=8)
        if st.sidebar.button("Kirim OTP", type="primary"):
            otp_element.send_keys(otp)
        time.sleep(1)
        driver.find_element(By.XPATH, '//*[@id="kc-login"]').click()
        st.sidebar.success("Login dengan OTP berhasil")
    except:
        st.sidebar.error("Login tanpa OTP berhasil")
    time.sleep(2)


def get_authenticated_cookies(driver: webdriver.Chrome) -> RequestsCookieJar:
    selenium_cookies = driver.get_cookies()
    jar = RequestsCookieJar()
    for cookie in selenium_cookies:
        jar.set(
            name=cookie['name'],
            value=cookie['value'],
            domain=cookie.get('domain'),
            path=cookie.get('path', '/'),
            secure=cookie.get('secure', False)
        )
    return jar


def ambil_semua_sls_smallcode_dari_kabupaten(kabupaten_id, level_region, region_group_id, headers, cookies, region_level1, region_level2):
    print("\n=== Mengambil semua kecamatan, desa, dan sls dari kabupaten berdasarkan ID ===")
    print(":param kabupaten_id: ID kabupaten (level2Id)")
    print(":param region_group_id: groupId dari region metadata")
    print(":param headers: headers berisi XSRF dan lainnya")
    print(":param cookies: cookies hasil login SSO")
    print(":return: DataFrame berisi daftar sls beserta id dan struktur wilayahnya\n")

    if not isinstance(level_region, list) or len(level_region) < 3:
        if len(level_region) == 2:
            print("❌ Regionlevel Hanya Sampai Kabupaten.")
            return pd.DataFrame([region_level2])
        elif len(level_region) == 1:
            print("❌ Regionlevel Hanya Sampai Provinsi.")
            return pd.DataFrame([region_level1])
        else:
            print("❌ Regionlevel tidak valid.")
            return pd.DataFrame()

    result = []

    try:
        # Ambil semua kecamatan
        url_kecamatan = f"https://fasih-sm.bps.go.id/region/api/v1/region/level3?groupId={region_group_id}&level2Id={kabupaten_id}"
        resp_kec = requests.get(url_kecamatan, headers=headers, cookies=cookies)
        resp_kec.raise_for_status()
        daftar_kecamatan = resp_kec.json().get('data', [])
    except Exception as e:
        print(f"❌ Gagal mengambil data kecamatan: {e}")
        return pd.DataFrame()

    for kec in daftar_kecamatan:
        kecamatan_id = kec['id']
        kecamatan_name = kec['name']
        kecamatan_kode = kec['fullCode']
        print(f"📍 Kecamatan: {kecamatan_name}")

        if len(level_region) == 3:
            result.append({
                f'{level_region[2]['name']}_id': kecamatan_id,
                f'{level_region[2]['name']}': kecamatan_name,
                'smallcode': kecamatan_kode,
            })
            continue

        try:
            # Ambil semua desa dari kecamatan
            url_desa = f"https://fasih-sm.bps.go.id/region/api/v1/region/level4?groupId={region_group_id}&level3Id={kecamatan_id}"
            resp_desa = requests.get(url_desa, headers=headers, cookies=cookies)
            resp_desa.raise_for_status()
            daftar_desa = resp_desa.json().get('data', [])
        except Exception as e:
            print(f"❌ Gagal mengambil desa dari {kecamatan_name}: {e}")
            continue

        for desa in daftar_desa:
            desa_id = desa['id']
            desa_name = desa['name']
            desa_kode = desa['fullCode']
            print(f"  🏘️ Desa: {desa_name}")

            if len(level_region) == 4:
                result.append({
                    f'{level_region[2]['name']}_id': kecamatan_id,
                    f'{level_region[2]['name']}': kecamatan_name,
                    f'{level_region[3]['name']}_id': desa_id,
                    f'{level_region[3]['name']}': desa_name,
                    'smallcode': desa_kode,
                })
                continue

            try:
                # Ambil semua SLS dari desa
                url_sls = f"https://fasih-sm.bps.go.id/region/api/v1/region/level5?groupId={region_group_id}&level4Id={desa_id}"
                resp_sls = requests.get(url_sls, headers=headers, cookies=cookies)
                resp_sls.raise_for_status()
                daftar_sls = resp_sls.json().get('data', [])
            except Exception as e:
                print(f"❌ Gagal mengambil SLS dari {desa_name}: {e}")
                continue

            for sls in daftar_sls:
                sls_id = sls['id']
                sls_name = sls['name']
                sls_kode = sls['fullCode']
                print(f"    🧾 SLS: {sls_name} ({sls_kode})")

                if len(level_region) == 5:
                    result.append({
                        f'{level_region[2]['name']}_id': kecamatan_id,
                        f'{level_region[2]['name']}': kecamatan_name,
                        f'{level_region[3]['name']}_id': desa_id,
                        f'{level_region[3]['name']}': desa_name,
                        f'{level_region[4]['name']}_id': sls_id,
                        f'{level_region[4]['name']}': sls_name,
                        'smallcode': sls_kode,
                    })
                    continue

                try:
                    # Ambil semua SUB SLS dari SLS
                    url_subsls = f"https://fasih-sm.bps.go.id/region/api/v1/region/level6?groupId={region_group_id}&level5Id={sls_id}"
                    resp_subsls = requests.get(url_subsls, headers=headers, cookies=cookies)
                    resp_subsls.raise_for_status()
                    daftar_subsls = resp_subsls.json().get('data', [])
                except Exception as e:
                    print(f"❌ Gagal mengambil SUB SLS dari {sls_name}: {e}")
                    continue

                for subsls in daftar_subsls:
                    subsls_id = subsls['id']
                    subsls_name = subsls['name']
                    subsls_kode = subsls['fullCode']
                    print(f"        🧾 SubSLS: {subsls_name} ({subsls_kode})")

                    result.append({
                        f'{level_region[2]['name']}_id': kecamatan_id,
                        f'{level_region[2]['name']}': kecamatan_name,
                        f'{level_region[3]['name']}_id': desa_id,
                        f'{level_region[3]['name']}': desa_name,
                        f'{level_region[4]['name']}_id': sls_id,
                        f'{level_region[4]['name']}': sls_name,
                        f'{level_region[5]['name']}_id': subsls_id,
                        f'{level_region[5]['name']}': subsls_name,
                        'smallcode': subsls_kode,
                    })

    if not result:
        print("⚠️ Tidak ada data yang berhasil diambil.")
    return pd.DataFrame(result)

def pilih_file(filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]) -> str:
    clear_screen()
    print("=== Pilih file untuk diproses ===")
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title="Pilih file", filetypes=filetypes)
    if file_path:
        print(f"File terpilih: {file_path}")
        time.sleep(1)
        return file_path
    else:
        print("Tidak memilih file, membatalkan operasi.")
        time.sleep(1)
        return ""


def pilih_folder_simpan(judul) -> str:
    clear_screen()
    print(f"=== {judul} ===")
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title=f"{judul}")
    if folder:
        print(f"Folder terpilih: {folder}")
        time.sleep(1)
        return folder
    else:
        print("Tidak memilih folder, menggunakan direktori saat ini.")
        time.sleep(1)
        return os.getcwd()
    
# Ekstrak jawaban
def extract_answers(answers):
    result = {}
    for item in answers:
        key = item.get("dataKey")
        ans = item.get("answer")

        if isinstance(ans, list):
            # Jika list berisi dict dengan 'value' dan 'label'
            if all(isinstance(i, dict) and 'value' in i and 'label' in i for i in ans):
                gabungan = [f"{i['value']}. {i['label']}" for i in ans]
                result[key] = ", ".join(gabungan)
            else:
                result[key] = ", ".join(str(i) for i in ans)
        elif isinstance(ans, dict):
            value = ans.get('value', '')
            label = ans.get('label', '')
            result[key] = f"{value}. {label}"
        else:
            result[key] = str(ans)
    return result

def fetch_detail(d):
    assignment_id = d['assignmentId']
    url = f'https://fasih-sm.bps.go.id/assignment-general/api/assignment/get-by-id-with-data-for-scm?id={assignment_id}'
    try:
        resp_detail = session.get(url, headers=headers, timeout=15)
        detail_json = resp_detail.json()
        inner_json = json.loads(detail_json["data"]["data"])
        answers = inner_json["answers"]
        answer_label = [item["dataKey"] for item in answers]
        answer_values = extract_answers(answers=answers)
        df = pd.DataFrame([answer_values], columns=answer_label)
        df['assignment_id'] = assignment_id
        return df
    except Exception as e:
        print(f"⚠️ Error parsing assignment_id {assignment_id}: {e}")
        return None

def get_all_survey_answers(id_survey, template_id, nama_kab, nama_survey, daftarwilayah, headers, cookies, session):

    # Ambil surveyPeriodsId
    try:
        url = f'https://fasih-sm.bps.go.id/survey/api/v1/surveys/{id_survey}'
        resp = session.get(url, headers=headers)
        
        # Pastikan status OK
        if resp.status_code == 200:
            survey_periods = resp.json()['data']['surveyPeriods']
            clear_screen()
            print("📅 Daftar Survey Periods:")
            for i, period in enumerate(survey_periods):
                print(f"{i}. ID: {period['id']}, Periode: {period['name']}, Start: {period['startDate']}, End: {period['endDate']}")

            # Pilih salah satu (misalnya: input dari user)
            selected_index = int(input("Pilih index survey period: "))
            selected_period = survey_periods[selected_index]
            surveyPeriodsId = selected_period['id']
            surveyPeriodsName = selected_period['name']

            print(f"\n✅ Anda memilih: {selected_period['name']} (ID: {surveyPeriodsId})")

        else:
            print(f"❌ Gagal mendapatkan data: {resp.status_code} - {resp.text}")
            
    except Exception as e:
        print(f"❌ Gagal mengambil surveyPeriodsId: {e}")
        return pd.DataFrame()

    save_dir = pilih_folder_simpan("Pilih lokasi penyimpanan file Excel")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Raw_Data_{nama_kab}_{nama_survey}_{surveyPeriodsName}_{timestamp}.xlsx"
    filename2 = f"Assignment_{nama_kab}_{nama_survey}_{surveyPeriodsName}_{timestamp}.xlsx"
    filepath = os.path.join(save_dir, filename)
    filepath2 = os.path.join(save_dir, filename2)

    res_list = []
    res2_list = []

    start_time = time.time()  # Catat waktu mulai

    try:
        for smallCode in tqdm(daftarwilayah['smallcode'], desc="Mengambil data SLS", unit="SLS"):
            url = f'https://fasih-sm.bps.go.id/assignment-general/api/assignments/get-principal-values-by-smallest-code/{surveyPeriodsId}/{smallCode}'
            resp = session.get(url, headers=headers)
            if resp.status_code != 200 or not resp.text.strip():
                print(f"❌ Gagal ambil data untuk smallCode {smallCode}, status_code={resp.status_code}")
                continue

            data = resp.json().get('data', [])
            if not isinstance(data, list) or not data:
                continue

            res2_list.append(pd.DataFrame(data))
            # data2 = pd.DataFrame(data)

            for d in data:
                assignment_id = d['assignmentId']
                url_detail = f'https://fasih-sm.bps.go.id/assignment-general/api/assignment/get-by-id-with-data-for-scm?id={assignment_id}'
                review_assignment_url = f'https://fasih-sm.bps.go.id/survey-collection/survey-review/{assignment_id}/{template_id}/{surveyPeriodsId}/a/1'
                try:
                    resp_detail = session.get(url_detail, headers=headers)
                    detail_json = resp_detail.json()
                    inner_json = json.loads(detail_json["data"]["data"])
                    answers = inner_json["answers"]
                    answer_label = [item["dataKey"] for item in answers]
                    answer_values = extract_answers(answers)
                    df = pd.DataFrame([answer_values], columns=answer_label)
                    df['assignment_id'] = assignment_id
                    df['link_preview'] = review_assignment_url
                    df['status_assignment'] = getLastHistory(assignment_id)
                    res_list.append(df)
                except Exception as e:
                    print(f"⚠️ Gagal ambil detail assignment_id {assignment_id}: {e}")

            # res2_list.append(data2)
            print(f"✅ SLS '{smallCode}' | Jumlah Assignment: {len(data)}")

    except Exception as e:
        print("🚨 Terjadi error fatal saat mengambil data:")
        print(e)
    finally:
        # Simpan data yang sempat terkumpul, walaupun error
        if res_list:
            try:
                df_main = pd.concat(res_list, ignore_index=True)
                df_main.fillna('', inplace=True)
                df_main.to_excel(filepath, index=False)
                print(f"✅ Data utama (partial/full) disimpan ke: {filepath}")
            except Exception as e:
                print(f"⚠️ Gagal simpan data utama: {e}")
        else:
            print("⚠️ Tidak ada data 'answers' yang bisa disimpan.")

        if res2_list:
            try:
                df_assign = pd.concat(res2_list, ignore_index=True)
                df_assign.fillna('', inplace=True)
                df_assign.to_excel(filepath2, index=False)
                print(f"✅ Data assignment (partial/full) disimpan ke: {filepath2}")
            except Exception as e:
                print(f"⚠️ Gagal simpan data assignment: {e}")
        else:
            print("⚠️ Tidak ada data assignment yang bisa disimpan.")

        # Hitung dan tampilkan lama proses
        end_time = time.time()
        elapsed = end_time - start_time
        menit, detik = divmod(elapsed, 60)
        print(f"⏱️ Proses selesai dalam {int(menit)} menit {int(detik)} detik.")

    # Return hasil meskipun tidak lengkap
    return pd.concat(res_list, ignore_index=True) if res_list else pd.DataFrame()


def parse_assignment_status(data_json):
    hasil = []
    data_list = data_json.get("data", [])

    if not data_list:
        hasil.append({
            "No": 0,
            "assignment_id": None,
            "date": None,
            "status_assignment": "Open"
        })
    else:
        for i, item in enumerate(data_list, start=1):
            hasil.append({
                "No": i,
                "assignment_id": item.get("assignment_id"),
                "date": item.get("date_created"),
                "status_assignment": item.get("status_alias")
            })
    
    return hasil


def getRoles(surveyPeriodeId, headers, cookies, session):
    # Ambil surveyPeriodsId
    url = f'https://fasih-sm.bps.go.id/survey/api/v1/users/myinfo?surveyPeriodId={surveyPeriodeId}'
    resp = session.get(url, headers=headers)
    surveyRole = resp.json()['data']['surveyRole']['description']
    return surveyRole


def getLastHistory(assignmentId):
    history_url = f'https://fasih-sm.bps.go.id/assignment-general/api/assignment-history/get-by-assignment-id?assignmentId={assignmentId}'
    resp_history = session.get(history_url, headers=headers)
    history = parse_assignment_status(resp_history.json())
    try:
        status_assignment = history[-1]['status_assignment']
    except:
        status_assignment = history[0]['status_assignment']

    return status_assignment




def approveByPML(id_survey, template_id, nama_kab, nama_survey, daftarwilayah, headers, cookies, session):
    # Ambil surveyPeriodsId
    url = f'https://fasih-sm.bps.go.id/survey/api/v1/surveys/{id_survey}'
    resp = session.get(url, headers=headers)

    # Pastikan status OK
    if resp.status_code == 200:
        survey_periods = resp.json()['data']['surveyPeriods']
        clear_screen()
        print("📅 Daftar Survey Periods:")
        for i, period in enumerate(survey_periods):
            print(f"{i}. ID: {period['id']}, Periode: {period['name']}, Start: {period['startDate']}, End: {period['endDate']}")

        # Pilih salah satu (misalnya: input dari user)
        selected_index = int(input("Pilih index survey period: "))
        selected_period = survey_periods[selected_index]
        surveyPeriodsId = selected_period['id']
        surveyPeriodsName = selected_period['name']

        print(f"\n✅ Anda memilih: {selected_period['name']} (ID: {surveyPeriodsId})")

    else:
        print(f"❌ Gagal mendapatkan data: {resp.status_code} - {resp.text}")

    # Pilih folder simpan dan siapkan nama file
    save_dir = pilih_folder_simpan("Pilih lokasi penyimpanan file Excel")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_log = f"Log_Approve_{nama_kab}_{nama_survey}_{timestamp}.xlsx"

    filepath_log = os.path.join(save_dir, filename_log)
    # print(f"Roles sebagai: {roles}")
    # Ambil role user
    roles = getRoles(surveyPeriodsId, headers, cookies, session)
    print(f"Roles sebagai: {roles}")
    pilih1 = input("Ingin melakukan approval untuk semua wilayah? (Y/N): ").strip().upper()

    # Inisialisasi DataFrame untuk menyimpan log approval
    log_approve = []

    start_time = time.time()  # Catat waktu mulai

    # Loop per smallCode
    for smallCode in tqdm(daftarwilayah['smallcode'], desc="Mengapprove data SLS", unit="Data"):
        url = f'https://fasih-sm.bps.go.id/assignment-general/api/assignments/get-principal-values-by-smallest-code/{surveyPeriodsId}/{smallCode}'
        resp = session.get(url, headers=headers)
        
        if resp.status_code != 200 or not resp.text.strip():
            print(f"❌ Gagal mengambil data untuk smallCode {smallCode}, status_code={resp.status_code}")
            continue

        try:
            data = resp.json().get('data', [])
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error untuk smallCode {smallCode}: {e}")
            continue
        
        if not data:
            print(f"ℹ️ Tidak ada data isian untuk smallCode {smallCode}.")
            continue
        
        print("---------------------------------------------------------------------\n")
        print(f"\n📌 Ditemukan {len(data)} data isian untuk wilayah {smallCode}.")
        
        if pilih1 != 'Y':
            pilih2 = input("Ingin lanjut approval untuk wilayah ini? (Y/N): ").strip().upper()
            # pilih2 = 'Y'
            if pilih2 != "Y":
                print(f"⏭️ Melewati approval untuk {smallCode}.")
                continue
        
        status_assignment_filter = ''
        for d in data:
            assignment_id = d['assignmentId']
            history_url = f'https://fasih-sm.bps.go.id/assignment-general/api/assignment-history/get-by-assignment-id?assignmentId={assignment_id}'
            resp_history = session.get(history_url, headers=headers)
            review_assignment_url = f'https://fasih-sm.bps.go.id/survey-collection/survey-review/{assignment_id}/{template_id}/{surveyPeriodsId}/a/1'
            try:
                history = parse_assignment_status(resp_history.json())
                status_assignment = history[-1]['status_assignment']
                approved = False
                keterangan = ""

                if (
                    (roles == 'Pengawas' and status_assignment == 'SUBMITTED BY Pencacah') or
                    (roles == 'PML' and status_assignment == 'SUBMITTED BY PPL') or
                    (roles == 'Admin Kabupaten' and status_assignment == 'APPROVED BY Pengawas') or
                    (roles == 'Admin Kabupaten' and status_assignment == 'APPROVED BY PML') or
                    (roles == 'Admin Kabupaten' and status_assignment == 'EDITED BY Admin Kabupaten') or
                    (roles == 'Admin Provinsi' and status_assignment == 'COMPLETED BY Admin Kabupaten')
                ):
                    status_assignment_filter = status_assignment
                    try:
                        driver.get(review_assignment_url)
                        
                        wait = WebDriverWait(driver, 30)

                        # Tunggu spinner overlay hilang
                        # wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "ngx-spinner-overlay")))

                        # Tunggu tombol approve muncul dan terlihat
                        wait.until(EC.presence_of_element_located((By.ID, "buttonApprove")))
                        # wait.until(EC.visibility_of_element_located((By.ID, "buttonApprove")))
                        
                        # Tunggu tombol benar-benar bisa diklik
                        approve_button = wait.until(EC.element_to_be_clickable((By.ID, "buttonApprove")))

                        clicked = False
                        attempt = 0
                        max_attempts = 5

                        while not clicked and attempt < max_attempts:
                            try:
                                print(f"🔁 Mencoba klik tombol approve... percobaan ke-{attempt+1}")
                                time.sleep(0.5)  # beri jeda agar stabil
                                approve_button.click()
                                clicked = True
                                print("✅ Klik tombol approve berhasil.")
                            except (ElementClickInterceptedException, StaleElementReferenceException) as e:
                                attempt += 1
                                print(f"⚠️ Klik gagal: {e}. Mengulang...")
                                # Refresh element jika perlu
                                approve_button = wait.until(EC.element_to_be_clickable((By.ID, "buttonApprove")))
                            except Exception as e:
                                print(f"❌ Error lain saat klik approve: {e}")
                                break

                        # Konfirmasi 1
                        wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="fasih"]/div/div/div[6]/button[1]')))
                        wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="fasih"]/div/div/div[6]/button[1]')))
                        confirm1 = driver.find_element(By.XPATH, '//*[@id="fasih"]/div/div/div[6]/button[1]')
                        confirm1.click()

                        # Konfirmasi 2 (jika ada)
                        try:
                            wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="fasih"]/div/div/div[6]/button[1]')))
                            confirm2 = driver.find_element(By.XPATH, '//*[@id="fasih"]/div/div/div[6]/button[1]')
                            confirm2.click()
                        except TimeoutException:
                            pass

                        approved = True
                        keterangan = "✅ Approved"
                        print(f"✅ Approved assignment {assignment_id}")

                    except TimeoutException:
                        keterangan = "❌ Timeout: Elemen tidak muncul"
                        print(f"❌ Timeout untuk assignment {assignment_id}")
                    except ElementClickInterceptedException as e:
                        keterangan = f"❌ Klik gagal karena ditutup elemen lain: {e}"
                        print(f"❌ Klik gagal untuk assignment {assignment_id}: {e}")
                    except Exception as e:
                        keterangan = f"❌ Error saat klik approve: {e}"
                        print(f"❌ Error klik approve untuk assignment {assignment_id}: {e}")

                else:
                    keterangan = f"❌ Belum memenuhi syarat approve (status: {status_assignment})"
                    print(f"ℹ️ Assignment {assignment_id} belum bisa diapprove (status: {status_assignment})")

                # Tambahkan log
                log_approve.append({
                    'assignment_id': assignment_id,
                    'link_assignment': review_assignment_url,
                    'smallCode': smallCode,
                    'status_assignment': status_assignment,
                    'approved': approved,
                    'keterangan': keterangan
                })

            except Exception as e:
                print(f"❌ Gagal memproses assignment {assignment_id}: {e}")
                log_approve.append({
                    'assignment_id': assignment_id,
                    'link_assignment': review_assignment_url,
                    'smallCode': smallCode,
                    'status_assignment': 'ERROR',
                    'approved': False,
                    'keterangan': f"❌ Exception: {e}"
                })

    # Simpan log approval ke Excel
    df_log = pd.DataFrame(log_approve)
    df_log.to_excel(filepath_log, index=False)

    # Filter hanya assignment yang memenuhi syarat status untuk diapprove
    status_filter = df_log['status_assignment'].isin([status_assignment_filter])

    # Hitung jumlah berhasil dan gagal approve dari yang seharusnya bisa diapprove
    jumlah_seharusnya = df_log[status_filter]
    jumlah_approve = jumlah_seharusnya['approved'].sum()
    jumlah_gagal = len(jumlah_seharusnya) - jumlah_approve

    # Hitung dan tampilkan lama proses
    end_time = time.time()
    elapsed = end_time - start_time
    jam, sisa = divmod(elapsed, 3600)
    menit, detik = divmod(sisa, 60)


    clear_screen()
    print(f"\n📄 Log hasil approval disimpan di: {filepath_log}")
    print(f"✅ Proses approval selesai untuk wilayah {nama_kab}")
    print(f"   - Jumlah berhasil approve: {jumlah_approve}")
    print(f"   - Jumlah gagal approve   : {jumlah_gagal}")
    # print(f"⏱️ Proses selesai dalam {int(menit)} menit {int(detik)} detik.")
    print(f"⏱️ Proses selesai dalam {int(jam)} jam {int(menit)} menit {int(detik)} detik.")


def main(driver, username, password=None):
    res = 'N'
    while res.upper() != 'Y':
        res = input("Apakah sudah konek VPN? (Y/N): ")

    clear_screen()

    print("✅ Pastikan package berikut sudah terinstal:")
    for pkg in [
        "time", "urllib.parse", "datetime", "os", "getpass", "tkinter",
        "tqdm", "pandas", "requests", "json", "selenium", "platform", "http"
    ]:
        print(f"- {pkg}")
    input("Apakah semua package di atas sudah terinstall? Tekan ENTER untuk lanjut...")

    time.sleep(3)
    clear_screen()
    if not password:
        password = input("Masukkan password SSO: ")
        
    login_sso(driver, username, password)
    
    # Login ke FASIH
    driver.get("https://fasih-sm.bps.go.id/oauth2/authorization/ics")
    print("Login Fasih")
    # time.sleep(500)
    # Tambahkan redirect manual ke halaman dashboard untuk memastikan cookie muncul
    driver.get("https://fasih-sm.bps.go.id/survey-collection/survey")
    print("Login Fasih Survey")
    # time.sleep(300)

    cookies = get_authenticated_cookies(driver)

    xsrf_token = urllib.parse.unquote(cookies.get('XSRF-TOKEN', ''))
    xsrf_token1 = cookies.get('XSRF-TOKEN', '')
    print("XSRF Token1:", xsrf_token)
    print("XSRF Token2:", xsrf_token1)

    headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'X-XSRF-TOKEN': xsrf_token,
        'Referer': 'https://fasih-sm.bps.go.id/',
        'User-Agent': 'Mozilla/5.0',
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://fasih-sm.bps.go.id'
    }

    session = requests.Session()
    session.cookies = cookies  # gunakan RequestsCookieJar lengkap
    # session.cookies.update(cookies)
    session.headers.update(headers)
    session.cookies.update(cookies)
    print("Berhasil Login!")
    return headers, cookies, session, password


# === Fungsi Suntik Cookie ke Driver ===
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
        except Exception as e:
            print(f"⚠️ Gagal menambahkan cookie {name}: {e}")
    st.success("✅ Cookies berhasil disuntikkan ke:", domain)
    # clear_screen()

def init_state():
    for k,v in dict(
        driver=None, logged_in=False, username="",
        headers=None, cookies_dict=None, session_obj=None,
        otp_needed=False, daftarwilayah=None,
        survey_meta=None, survey_period_id=None, survey_period_name=None,
    ).items():
        if k not in st.session_state: st.session_state[k] = v


# =================== Setup ===================
st.set_page_config(page_title="FASIH — DW/RAW/Approve", layout="wide")
st.title("🧭 FASIH — Login • DaftarWilayah • Raw Data • Approve")


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


# =================== Sidebar: Login / Session ===================
st.sidebar.header("🔐 Session")
mode = st.sidebar.radio("Mode:", ["Login SSO", "Muat Session", "Logout"], index=0)

if mode == "Logout":
    for k in list(st.session_state.keys()): st.session_state[k] = None
    init_state(); st.sidebar.success("Reset session."); st.stop()

if mode == "Muat Session":
    st.session_state.username = st.sidebar.text_input("Username untuk muat", value=st.session_state.username or "")
    headless_after_load = st.sidebar.checkbox("Buka browser headless saat injeksi", value=False)
    
    if st.sidebar.button("📂 Muat & Suntik ke Browser"):
        st.session_state.driver = setup_driver()
        time.sleep(2)
        st.session_state.headers, st.session_state.cookies, st.session_state.session, st.session_state.password = muat_session(st.session_state.username)
        
        if st.session_state.session:
            st.write(f"🔄 Menggunakan session tersimpan untuk {st.session_state.username}")
            apply_cookies_to_driver(st.session_state.driver, st.session_state.session.cookies.get_dict(), "sso.bps.go.id")
            apply_cookies_to_driver(st.session_state.driver, st.session_state.session.cookies.get_dict(), "fasih-sm.bps.go.id")
            st.session_state.driver.get("https://fasih-sm.bps.go.id/survey-collection/survey")
            time.sleep(2)

            # Cek session valid
            try:
                st.write("Cek session valid")
                cek = st.session_state.driver.current_url == 'https://fasih-sm.bps.go.id/survey-collection/survey'
                if not cek:
                    st.write("Session expired")
                    raise Exception("Session expired")
            except:
                st.write("🔐 Session lama tidak valid. Login ulang diperlukan.")
                headers, cookies, session, password = main(st.session_state.driver, st.session_state.username, st.session_state.password)
                simpan_session(st.session_state.username, headers, cookies, session, password)
        else:
            st.write("🔐 Tidak ada session tersimpan. Login diperlukan.")
            headers, cookies, session, password = main(st.session_state.driver, st.session_state.username, st.session_state.password)
            simpan_session(st.session_state.username, headers, cookies, session, password)

if mode == "Login SSO":
    user = st.sidebar.text_input("Username", value=st.session_state.username or "")
    pwd  = st.sidebar.text_input("Password", type="password")
    headless = st.sidebar.checkbox("Headless (OFF jika OTP)", value=False)
    c1,c2 = st.sidebar.columns(2)
    
    with c1:
        if st.sidebar.button("▶️ Login"):
            try:
                st.session_state.driver = setup_driver()
                login_sso(driver=st.session_state.driver, username=user, password=pwd)  # dummy call to avoid error
                
                # Login ke FASIH
                st.session_state.driver.get("https://fasih-sm.bps.go.id/oauth2/authorization/ics")
                st.write("Login Fasih")
                # time.sleep(500)
                # Tambahkan redirect manual ke halaman dashboard untuk memastikan cookie muncul
                st.session_state.driver.get("https://fasih-sm.bps.go.id/survey-collection/survey")
                st.write("Login Fasih Survey")
                # time.sleep(300)

                cookies = get_authenticated_cookies(st.session_state.driver)

                xsrf_token = urllib.parse.unquote(cookies.get('XSRF-TOKEN', ''))
                xsrf_token1 = cookies.get('XSRF-TOKEN', '')
                st.write("XSRF Token1:", xsrf_token)
                st.write("XSRF Token2:", xsrf_token1)

                headers = {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-XSRF-TOKEN': xsrf_token,
                    'Referer': 'https://fasih-sm.bps.go.id/',
                    'User-Agent': 'Mozilla/5.0',
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/plain, */*',
                    'Origin': 'https://fasih-sm.bps.go.id'
                }

                session = requests.Session()
                session.cookies = cookies  # gunakan RequestsCookieJar lengkap
                # session.cookies.update(cookies)
                session.headers.update(headers)
                session.cookies.update(cookies)
                st.success("Berhasil Login!")
                
                
                
                st.session_state.username = user            
                st.session_state.headers = headers
                st.session_state.cookies_dict = cookies
                st.session_state.session_obj = session
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
