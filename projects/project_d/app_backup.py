import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime
from st_aggrid import AgGrid, GridOptionsBuilder


# Setelah buat df_table (DataFrame hasil data), tampilkan dengan st-aggrid:
def tampilkan_tabel_aggrid(df_table):
    gb = GridOptionsBuilder.from_dataframe(df_table)
    gb.configure_pagination(paginationAutoPageSize=True)  # pagination otomatis
    gb.configure_default_column(resizable=True, sortable=True, filter=True)
    gb.configure_grid_options(domLayout='autoHeight')
    
    # Freeze kolom index (baris)
    gb.configure_column(df_table.index.name or df_table.index.names[0], pinned='left', lockPinned=True)
    
    gridOptions = gb.build()
    
    AgGrid(
        df_table,
        gridOptions=gridOptions,
        fit_columns_on_grid_load=True,
        enable_enterprise_modules=False,
        theme='alpine',  # kamu bisa coba tema lain: 'balham', 'material', dll
        height=500,
        width='100%',
    )


# --- Konfigurasi Streamlit ---
st.set_page_config(page_title="BPS Data Scraper", layout="wide")
st.title("📊 BPS API Data Fetcher")

# --- Fungsi HTTP request ---
@st.cache_data(show_spinner=False)
def getReq(url):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None

# --- Fungsi ambil domain ---
@st.cache_data(show_spinner=False)
def get_domains(api_key):
    url = f'https://webapi.bps.go.id/v1/api/domain/type/all/key/{api_key}/'
    data = getReq(url)
    if data and 'data' in data and len(data['data']) > 1:
        df = pd.DataFrame(data['data'][1])
        return df[['domain_id', 'domain_name']]
    return pd.DataFrame()

# --- Fungsi ambil variabel ---
@st.cache_data(show_spinner=False)
def getDataVar(base_url):
    data = getReq(base_url)
    if not data or 'data' not in data or not data['data']:
        return None

    pages = data['data'][0].get('pages', 0)
    if pages == 0:
        return None

    all_data = []
    for page in range(1, pages + 1):
        url_page = base_url.replace("/key/", f"/page/{page}/key/")
        res = getReq(url_page)
        if res and 'data' in res and len(res['data']) >= 2:
            all_data += res['data'][1]

    if not all_data:
        return None

    return pd.DataFrame(all_data)

# --- Sidebar Settings ---
st.sidebar.header("🔧 Pengaturan")

# API Key Input
KEY_ID = st.sidebar.text_input("Masukkan API Key BPS", value="687e204db62094de46edbcd7ed7cb204")

# Ambil daftar domain
domain_df = get_domains(KEY_ID)

# Pilih domain
if not domain_df.empty:
    selected_domains = st.sidebar.multiselect(
        "Pilih Domain",
        options=domain_df['domain_id'],
        format_func=lambda x: f"{x} - {domain_df[domain_df['domain_id'] == x]['domain_name'].values[0]}",
        default=[d for d in ['6310'] if d in domain_df['domain_id'].tolist()]
    )
else:
    st.sidebar.warning("Gagal mengambil daftar domain.")
    selected_domains = []

# Rentang tahun (kode BPS: 125 untuk 2025)
current_year = datetime.now().year
current_bps_code = current_year - 1900
year_range = st.sidebar.slider("Pilih rentang tahun (kode BPS)", 110, current_bps_code, (120, current_bps_code))

# --- Ambil Data Variabel ---
res_list = []
if selected_domains:
    with st.spinner("Mengambil daftar variabel dari domain..."):
        for domain in selected_domains:
            base_url = f"https://webapi.bps.go.id/v1/api/list/model/var/domain/{domain}/key/{KEY_ID}/"

            # --- Ambil semua variabel ---
            data_var = getDataVar(base_url)

            if data_var is not None and not data_var.empty:
                data_var["domain"] = domain
                res_list.append(data_var)

# Gabungkan hasil variabel
if res_list:
    res = pd.concat(res_list, ignore_index=True)
    st.success(f"Berhasil mengambil {len(res)} variabel.")

    # Cek apakah 'label' tersedia
    if 'label' in res.columns:
        st.dataframe(res[['var_id', 'label', 'domain']])
    else:
        st.warning("Kolom 'label' tidak ditemukan. Menampilkan semua kolom.")
        st.dataframe(res)
else:
    st.warning("Tidak ada data variabel yang ditemukan.")
    st.stop()

# --- Ambil Data Availability ---
res_list2 = []
shown_json_for_var = False
with st.spinner("Memeriksa ketersediaan data untuk setiap variabel dan tahun..."):
    for idx, row in res.iterrows():
        var_id = row['var_id']
        label = row['label'] if 'label' in row else ''
        for domain in selected_domains:
            for thn in range(year_range[0], year_range[1] + 1):
                url2 = f'https://webapi.bps.go.id/v1/api/list/model/data/domain/{domain}/var/{var_id}/th/{thn}/key/{KEY_ID}/'
                data = getReq(url2)
                
                if data and data.get('data-availability') == 'available':
                    res_list2.append({
                        'var_id': var_id,
                        'nama_variabel': data['var'][0]['label'] if 'var' in data and data['var'] else '',
                        'domain': domain,
                        'tahun': data['tahun'][0]['label'] if 'tahun' in data and data['tahun'] else thn,
                        'data-availability': data.get('data-availability', 'unavailable'),
                        'last_update': data.get('last_update', '')
                    })

                    if not shown_json_for_var:
                        with st.expander(f"📎 Contoh response JSON: DATA | VarID {var_id} - Tahun {thn} - Domain {domain}"):
                            st.markdown(f"🔗 **URL:** `{url2}`")
                            st.json(data)
                        shown_json_for_var = True

                elif data:
                    res_list2.append({
                        'var_id': var_id,
                        'nama_variabel': row['label'] if 'label' in row else '',
                        'domain': domain,
                        'tahun': thn,
                        'data-availability': data.get('data-availability', 'unavailable'),
                        'last_update': ''
                    })

# Tampilkan hasil akhir
if res_list2:
    df_availability = pd.DataFrame(res_list2)
    st.success(f"Berhasil memproses {len(df_availability)} entri data.")
    st.dataframe(df_availability)

    # Tombol download
    st.download_button(
        "📥 Download Hasil (CSV)",
        data=df_availability.to_csv(index=False),
        file_name="data_availability_bps.csv",
        mime="text/csv"
    )
else:
    st.warning("Tidak ada data availability yang ditemukan.")
    st.stop()

# Filter available saja
df_available = df_availability[df_availability['data-availability'] == 'available'].reset_index(drop=True)

# Dropdown pilihan unik (gabungan info)
options = df_available.apply(
    lambda x: f"nama_variabel: {x['nama_variabel']} | domain: {x['domain']} | tahun: {x['tahun']}",
    axis=1
)
selected = st.selectbox("Pilih Data Tersedia", options)

# Jika sudah pilih, tampilkan tabel
if selected:
    idx = options[options == selected].index[0]
    var_id = df_available.loc[idx, 'var_id']
    domain = df_available.loc[idx, 'domain']
    thn = df_available.loc[idx, 'tahun']
    if len(str(thn)) == 4:
        thn = int(thn) - 1900  # konversi ke kode BPS jika perlu
        
    url3 = f'https://webapi.bps.go.id/v1/api/list/model/data/domain/{domain}/var/{var_id}/th/{thn}/key/{KEY_ID}/'
    json_data = getReq(url3)
    st.write(f"🔗 **URL Data Detail:** `{url3}`")
    st.write("### Hasil Data Detail:")
    if not json_data:
        st.error("Gagal mengambil data detail.")
        st.stop()

    # Ambil label untuk header tabel
    labelvervar = json_data.get("labelvervar", "Label")
    var_label = json_data["var"][0]["label"] if json_data.get("var") else "Data"

    vervar_list = json_data.get('vervar', [])
    turvar_list = json_data.get('turvar', [])

    vervar_labels = [v['label'] for v in vervar_list]
    turvar_labels = [t['label'] for t in turvar_list]

    # Buat dict mapping val->index untuk vervar (7 dan 8 digit) dan turvar
    vervar_val_idx_7 = {str(v['val']).zfill(7): i for i, v in enumerate(vervar_list) if len(str(v['val'])) <= 7}
    vervar_val_idx_8 = {str(v['val']).zfill(8): i for i, v in enumerate(vervar_list) if len(str(v['val'])) <= 8}
    turvar_val_idx = {str(t['val']).zfill(3): j for j, t in enumerate(turvar_list)}

    # Data datacontent
    datacontent = json_data.get("datacontent", {})

    # Buat matriks data sesuai ukuran vervar x turvar
    table_data = np.zeros((len(vervar_labels), len(turvar_labels)), dtype=int)

    for key, value in datacontent.items():
        key_len = len(key)
        if key_len == 17:
            vervar_part = key[0:8]
            turvar_part = key[10:13]
            if vervar_part in vervar_val_idx_8 and turvar_part in turvar_val_idx:
                i = vervar_val_idx_8[vervar_part]
                j = turvar_val_idx[turvar_part]
                table_data[i, j] = value
        elif key_len == 16:
            vervar_part = key[0:7]
            turvar_part = key[9:12]
            if vervar_part in vervar_val_idx_7 and turvar_part in turvar_val_idx:
                i = vervar_val_idx_7[vervar_part]
                j = turvar_val_idx[turvar_part]
                table_data[i, j] = value

    df_table = pd.DataFrame(table_data, index=vervar_labels, columns=turvar_labels)
    # Misal labelvervar = "Kecamatan"
    df_table.index.name = labelvervar

    # Tampilkan judul dan tabel
    st.markdown(f"#### {var_label} menurut {labelvervar} tahun {thn + 1900}")
    # st.dataframe(df_table)
    st.dataframe(df_table, width=1000)
    

