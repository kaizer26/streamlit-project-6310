import streamlit as st
import pandas as pd
import io
import datetime
from datetime import date

from urllib.parse import quote

def bersihkan_angka(val):
    if pd.isna(val):
        return None

    # Jika sudah angka
    if isinstance(val, (int, float)):
        return int(val) if float(val).is_integer() else float(val)

    val = str(val).strip()

    # Buang semua spasi
    val = val.replace(" ", "")

    # Jika mengandung koma dan tidak ada titik, maka koma diasumsikan sebagai ribuan → hapus
    if "," in val and "." not in val:
        val = val.replace(",", "")
    # Jika mengandung titik dan tidak ada koma, maka titik diasumsikan sebagai ribuan → hapus
    elif "." in val and "," not in val:
        val = val.replace(".", "")
    # Jika mengandung keduanya: kita asumsikan format Indonesia → "." ribuan, "," desimal
    elif "," in val and "." in val:
        val = val.replace(".", "")
        val = val.replace(",", ".")

    try:
        f = float(val)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


st.set_page_config(page_title="Rekap Kegiatan Petugas", layout="wide")
st.title("📋 Rekap Kegiatan Petugas (SPK WATCH)")

uploaded_file = st.file_uploader("📤 Upload File Excel (.xlsx)", type=["xlsx"])
sheet_url = "https://docs.google.com/spreadsheets/d/1bRXZoNccjInvoHfIZfwKaR96sa_u4tWC"

# Tampilkan tombol proses setelah file diunggah

if st.button("▶️ Proses Data"):
    try:
        sheet_list = [
            "SPK Jan", "SPK Feb", "SPK Mar", "SPK Apr", "SPK Mei", "SPK Juni",
            "SPK Juli", "SPK Agt", "SPK Sep", "SPK Okt", "SPK Nop", "SPK Des",
            "SPK Olah Jan", "SPK Olah Feb", "SPK Olah Mar", "SPK Olah Apr", "SPK Olah Mei", "SPK Olah Juni",
            "SPK Olah Juli", "SPK Olah Agt", "SPK Olah Sep", "SPK Olah Okt", "SPK Olah Nop", "SPK Olah Des"
        ]

        data_long = []
        progress_text = st.empty()
        progress_bar = st.progress(0)
        status_log = st.empty()

        for i, sheet in enumerate(sheet_list):
            progress_text.markdown(f"🔄 Sedang memproses: **{sheet}**")
            progress_bar.progress((i + 1) / len(sheet_list))

            try:
                if uploaded_file:
                    df = pd.read_excel(uploaded_file, sheet_name=sheet, dtype={"NIK": str})
                else:
                    # csv_url = f"{sheet_url}/gviz/tq?tqx=out:csv&sheet={sheet.replace(' ', '%20')}"
                    csv_url = f"{sheet_url}/export?format=csv&gid="
                    df = pd.read_csv(csv_url, dtype={"NIK": str})
                
                df.columns = df.columns.astype(str)

                if "Nama" not in df.columns:
                    # st.warning(f"⚠️ Sheet '{sheet}' tidak memiliki kolom 'Nama'")
                    continue

                for _, row in df.iterrows():
                    nama = str(row.get("Nama", "")).strip()
                    nik = str(row.get("NIK", "")).strip()
                    asal = str(row.get("Asal", "")).strip()
                    jabatan = str(row.get("Jabatan", "")).strip()

                    if not nama or nama.lower() == "nan":
                        continue

                    for n in range(1, 21):
                        k_col = f"Kegiatan {n}"
                        v_col = f"Volume {n}"
                        j_col = f"Jadwal {n}"
                        n_col = f"Nilai {n}"

                        if k_col in df.columns:
                            kegiatan = row.get(k_col, "")
                            volume = row.get(v_col, "")
                            jadwal = row.get(j_col, "")
                            
                            # Coba ambil 'Nilai {n}' jika ada
                            if n_col in df.columns:
                                nilai = row.get(n_col, "")
                            else:
                                # Kalau 'Nilai {n}' tidak ada, cari nilai setelah kolom 'Jadwal {n}'
                                try:
                                    j_index = df.columns.get_loc(j_col)
                                    next_col = df.columns[j_index + 1]
                                    nilai = row.get(next_col, "")
                                except (KeyError, IndexError):
                                    nilai = ""  # Kolom tidak ditemukan atau index out of range

                            if pd.isna(kegiatan) or str(kegiatan).strip() == "":
                                continue

                            data_long.append({
                                "Nama": nama,
                                "NIK": nik,
                                "Asal": asal,
                                "Jabatan": jabatan,
                                "Kegiatan": str(kegiatan).strip(),
                                "Volume": str(volume).strip(),
                                "Jadwal": str(jadwal).strip(),
                                "Nilai": bersihkan_angka(nilai),
                                "Sumber Sheet": sheet
                            })

                # st.success(f"✅ Selesai memproses sheet: {sheet}")

            except Exception as e:
                status_log.error(f"❌ Gagal membaca sheet {sheet}: {e}")
            else:
                status_log.success(f"✅ Selesai memproses sheet: {sheet}")

        progress_text.markdown("✅ **Semua sheet selesai diproses.**")
        progress_bar.empty()

        df_final = pd.DataFrame(data_long)

        # ========= REKAP: Mitra yang belum pernah mengikuti kegiatan =========
        # Helper agar default selalu Series (bukan string)
        def safe_col(df, colname):
            if colname in df.columns:
                return df[colname]
            # Series kosong dengan panjang sesuai df dan index yang sama
            return pd.Series([""] * len(df), index=df.index, dtype="object")

        # Coba muat DB mitra 2025
        df_mitra = None
        try:
            if uploaded_file:
                df_mitra = pd.read_excel(uploaded_file, sheet_name="db mitra 2025", dtype={"NIK": str})
            else:
                csv_url_mitra = f"{sheet_url}/gviz/tq?tqx=out:csv&sheet={'db%20mitra%202025'}"
                df_mitra = pd.read_csv(csv_url_mitra, dtype={"NIK": str})
        except Exception as e:
            st.warning(f"⚠️ Sheet 'db mitra 2025' tidak bisa dibaca: {e}")

        def norm_nik(s):
            if pd.isna(s): 
                return ""
            return str(s).strip().replace(" ", "")

        def norm_nama(s):
            if pd.isna(s):
                return ""
            return " ".join(str(s).strip().split()).upper()

        if df_mitra is not None and not df_mitra.empty:
            # Samakan nama kolom jika ada variasi
            if "NAMA" not in df_mitra.columns:
                calon = [c for c in df_mitra.columns if str(c).strip().lower() == "nama"]
                if calon:
                    df_mitra.rename(columns={calon[0]: "Nama"}, inplace=True)
            if "NIK" not in df_mitra.columns:
                calon = [c for c in df_mitra.columns if str(c).strip().lower() == "nik"]
                if calon:
                    df_mitra.rename(columns={calon[0]: "NIK"}, inplace=True)

            # Key normalisasi (gunakan safe_col agar selalu Series)
            df_mitra["key_nik"] = safe_col(df_mitra, "NIK").astype(str).map(norm_nik)
            df_mitra["key_nama"] = safe_col(df_mitra, "Nama").astype(str).map(norm_nama)

            # Ambil set mitra yang sudah aktif (pernah punya kegiatan)
            if not df_final.empty:
                aktif_nik = set(safe_col(df_final, "NIK").astype(str).map(norm_nik))
                aktif_nama = set(safe_col(df_final, "Nama").astype(str).map(norm_nama))
            else:
                aktif_nik, aktif_nama = set(), set()

            # Pernah ikut jika match NIK atau Nama
            df_mitra["pernah_ikut"] = df_mitra["key_nik"].isin(aktif_nik) | df_mitra["key_nama"].isin(aktif_nama)

            df_mitra_belum = df_mitra[~df_mitra["pernah_ikut"]].copy()

            st.session_state["df_mitra_belum"] = df_mitra_belum.copy()
            st.session_state["df_mitra"] = df_mitra.copy()
            st.session_state["df_final"] = df_final.copy()
            
            st.success(
                f"Jumlah Mitra dalam DB: {len(df_mitra)} | "
                f"Sudah pernah ikut: {int(df_mitra['pernah_ikut'].sum())} | "
                f"Belum pernah ikut: {len(df_mitra_belum)}"
            )
            if not df_mitra_belum.empty:
                kolom_prioritas = [c for c in ["Nama", "NIK", "Asal", "Jabatan"] if c in df_mitra_belum.columns]
            else:
                st.info("Semua mitra di DB sudah pernah tercatat mengikuti kegiatan.")

        
        if not df_final.empty:
            st.success(f"📊 Total data kegiatan: {len(df_final)} baris")
            st.dataframe(df_final, use_container_width=True)

            # --- Rekap 1: Mitra per Kegiatan per Bulan
            df_rekap = df_final.groupby(
                ["Sumber Sheet", "Kegiatan", "Nama", "NIK", "Asal", "Jabatan"]
            ).size().reset_index(name="Jumlah Kegiatan")

            df_rekap_agg = df_rekap.groupby(["Sumber Sheet", "Kegiatan"])["Nama"].nunique().reset_index(name="Jumlah Mitra")

            # --- Rekap 2: Total Nilai per Petugas per Bulan
            df_per_nama_per_bulan = df_final.groupby(
                ["Sumber Sheet", "Nama", "NIK", "Asal", "Jabatan"]
            )["Nilai"].sum().reset_index(name="Total Nilai")

            # --- Rekap 3: Total Nilai per Kegiatan
            df_nilai_per_kegiatan = df_final.groupby("Kegiatan")["Nilai"].sum().reset_index(name="Total Nilai")

            # --- Rekap 4: Jumlah Kegiatan per Petugas per Bulan
            df_jumlah_kegiatan_per_nama = df_final.groupby(
                ["Sumber Sheet", "Nama", "NIK", "Asal", "Jabatan"]
            ).size().reset_index(name="Jumlah Kegiatan")
            
            # Batas maksimum nilai dalam sebulan
            BATAS_MAKS = 3644000

            # Cek nama mitra yang melebihi batas
            df_melebihi_batas = df_per_nama_per_bulan[df_per_nama_per_bulan["Total Nilai"] > BATAS_MAKS]

            if not df_melebihi_batas.empty:
                st.warning(f"⚠️ Ada {len(df_melebihi_batas)} mitra yang melebihi batas nilai Rp{BATAS_MAKS:,} dalam satu bulan!")
                st.dataframe(df_melebihi_batas)

            # ✅ Tampilkan semua rekap
            st.subheader("📊 Rekap Jumlah Mitra per Kegiatan per Sheet")
            st.dataframe(df_rekap_agg, use_container_width=True)

            st.subheader("📊 Rekap Jumlah Kegiatan per Nama per Bulan")
            st.dataframe(df_jumlah_kegiatan_per_nama, use_container_width=True)
            
            st.subheader("📊 Rekap Total Nilai per Nama per Bulan")
            st.dataframe(df_per_nama_per_bulan, use_container_width=True)

            st.subheader("📊 Rekap Total Nilai per Kegiatan")
            st.dataframe(df_nilai_per_kegiatan, use_container_width=True)
            
            # --- Rekap 5: Jumlah Mitra per Kegiatan (Tanpa Sheet)
            st.subheader("📊 Rekap Jumlah Mitra per Kegiatan (Gabungan Semua Sheet)")

            df_jumlah_mitra_per_kegiatan = (
                df_final.groupby("Sumber Sheet")["Nama"]
                .nunique()
                .reset_index(name="Jumlah Mitra Unik")
                .sort_values("Jumlah Mitra Unik", ascending=False)
            )

            st.dataframe(df_jumlah_mitra_per_kegiatan, use_container_width=True)
            st.caption(f"Total kegiatan: {len(df_jumlah_mitra_per_kegiatan)}")
            
            # Simpan hasil ke session agar tidak hilang saat UI rerun
            st.session_state["df_final"] = df_final.copy()
            st.session_state["df_mitra"] = df_mitra.copy()
            


            # ✅ Export ke Excel
            with io.BytesIO() as buffer:
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_final.to_excel(writer, index=False, sheet_name="Kegiatan")
                    df_rekap_agg.to_excel(writer, index=False, sheet_name="Rekap")
                    df_per_nama_per_bulan.to_excel(writer, index=False, sheet_name="Rekap Per Nama Per Bulan")
                    df_nilai_per_kegiatan.to_excel(writer, index=False, sheet_name="Rekap Nilai per Kegiatan")
                    df_jumlah_kegiatan_per_nama.to_excel(writer, index=False, sheet_name="Rekap Jumlah Kegiatan")
                    # Tambahkan sheet Mitra Belum Ikut bila ada
                    try:
                        if df_mitra is not None:
                            df_mitra.to_excel(writer, index=False, sheet_name="DB Mitra 2025")
                        if 'df_mitra_belum' in locals() and df_mitra_belum is not None:
                            df_mitra_belum.to_excel(writer, index=False, sheet_name="Mitra Belum Ikut")
                    except Exception as e:
                        # Tidak fatal; tetap lanjutkan
                        pass

                st.download_button(
                    label="📥 Download Hasil Excel (5 Sheet)",
                    data=buffer.getvalue(),
                    file_name="Rekap Kegiatan Mitra.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.warning("Tidak ada data kegiatan ditemukan.")

    except Exception as e:
        st.error(f"Terjadi kesalahan: {e}")
else:
    st.info("Klik tombol '▶️ Proses Data' untuk memulai.")


st.markdown("---")
st.subheader("🧾 Mitra Belum Ikut — Filter & Tabel")

if "df_mitra_belum" in st.session_state and not st.session_state["df_mitra_belum"].empty:
    df_view = st.session_state["df_mitra_belum"].copy()

    # Pastikan kolom turunan ada (idempotent)
    today = datetime.date.today()

    def hitung_umur(tgl):
        if pd.isna(tgl) or str(tgl).strip() == "":
            return ""
        t = pd.to_datetime(tgl, errors="coerce")
        if pd.isna(t):
            return ""
        return today.year - t.year - ((today.month, today.day) < (t.month, t.day))

    def format_wa(no):
        if pd.isna(no):
            return ""
        digits = "".join(c for c in str(no) if c.isdigit())
        if not digits:
            return ""
        # Normalisasi Indonesia: 08xxxxx / 8xxxxx -> 628xxxxx
        if digits.startswith("0"):
            digits = "62" + digits[1:]
        elif digits.startswith("8"):
            digits = "62" + digits
        return f"https://wa.me/{digits}"

    if "umur" not in df_view.columns and "tgl_lahir" in df_view.columns:
        df_view["umur"] = df_view["tgl_lahir"].apply(hitung_umur)
    if "wa_link" not in df_view.columns and "notelp" in df_view.columns:
        df_view["wa_link"] = df_view["notelp"].apply(format_wa)

    # 🔽 Multi-select filter nama_pos (tidak memicu proses ulang data, hanya filter tampilan)
    if "nama_pos" in df_view.columns:
        opsi_pos = sorted(df_view["nama_pos"].dropna().unique().tolist())
        pilihan = st.multiselect("📌 Pilih Posisi Mitra (bisa lebih dari satu):", options=opsi_pos, default=[])
        if pilihan:
            df_view = df_view[df_view["nama_pos"].isin(pilihan)]

    # Kolom yang ditampilkan
    kolom_prioritas = [c for c in [
        "nama_lengkap", "nik", "nama_pos", "email",
        "alamat_kec", "alamat_desa", "umur", "wa_link"
    ] if c in df_view.columns]
    df_tampil = df_view[kolom_prioritas] if kolom_prioritas else df_view

    st.dataframe(
        df_tampil,
        use_container_width=True,
        column_config={
            "wa_link": st.column_config.LinkColumn(
                "WhatsApp",
                help="Klik untuk chat via WhatsApp",
                display_text="Chat WA"
            )
        }
    )
else:
    st.info("Belum ada data 'Mitra Belum Ikut'. Klik ▶️ Proses Data terlebih dahulu.")
    

st.markdown("---")
st.subheader("👥 Daftar Mitra per Kegiatan")

if "df_final" in st.session_state and not st.session_state["df_final"].empty:
    dfk = st.session_state["df_final"].copy()

    # Dropdown sheet/bulan
    if "Sumber Sheet" not in dfk.columns:
        st.warning("Kolom 'Sumber Sheet' tidak ditemukan di data kegiatan.")
    else:
        sheet_options = sorted(dfk["Sumber Sheet"].dropna().astype(str).unique().tolist())
        selected_sheet = st.selectbox("📅 Pilih bulan/sheet:", ["(Semua)"] + sheet_options, index=0)

        dfk_sheet = dfk if selected_sheet == "(Semua)" else dfk[dfk["Sumber Sheet"] == selected_sheet]

        # Dropdown kegiatan berdasarkan sheet terpilih
        if "Kegiatan" not in dfk_sheet.columns or dfk_sheet.empty:
            st.info("Tidak ada data kegiatan untuk sheet terpilih.")
        else:
            kegiatan_options = sorted(dfk_sheet["Kegiatan"].dropna().astype(str).unique().tolist())
            selected_kegiatan = st.selectbox("🗂️ Pilih kegiatan:", kegiatan_options if kegiatan_options else ["(Tidak ada)"])

            if kegiatan_options:
                dff = dfk_sheet[dfk_sheet["Kegiatan"].astype(str) == selected_kegiatan].copy()
                if dff.empty:
                    st.info("Belum ada entri untuk kegiatan ini.")
                else:
                    # Pastikan Nilai numerik untuk agregasi
                    dff["Nilai"] = pd.to_numeric(dff.get("Nilai", 0), errors="coerce").fillna(0)

                    # Kolom identitas mitra yang tersedia
                    id_cols = [c for c in ["Nama", "NIK", "Asal", "Jabatan"] if c in dff.columns and c != ""]
                    if not id_cols:
                        id_cols = ["Nama"] if "Nama" in dff.columns else []

                    # Rekap unik per mitra
                    agg = (
                        dff.groupby(id_cols, dropna=False)
                           .agg(Jumlah_Kegiatan=("Kegiatan", "count"),
                                Total_Nilai=("Nilai", "sum"))
                           .reset_index()
                           .sort_values(["Total_Nilai", "Jumlah_Kegiatan"], ascending=[False, False])
                    )

                    keterangan_sheet = selected_sheet if selected_sheet != "(Semua)" else "semua sheet"
                    st.caption(f"Menampilkan mitra yang tercatat pada kegiatan **{selected_kegiatan}** di **{keterangan_sheet}**.")
                    st.dataframe(agg, use_container_width=True)

                    # Detail baris (setiap entri)
                    with st.expander("🔎 Lihat baris detail (setiap entri)"):
                        cols_show = [c for c in ["Sumber Sheet", "Kegiatan", "Nama", "NIK", "Asal", "Jabatan", "Volume", "Jadwal", "Nilai"] if c in dff.columns]
                        st.dataframe(dff[cols_show] if cols_show else dff, use_container_width=True)

                    # Download CSV
                    st.download_button(
                        "⬇️ Download (CSV) — Rekap Mitra",
                        data=agg.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"rekap_mitra_{selected_kegiatan.replace(' ', '_')}_{selected_sheet.replace(' ', '_')}.csv",
                        mime="text/csv",
                    )
                    st.download_button(
                        "⬇️ Download (CSV) — Detail Baris",
                        data=dff.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"detail_baris_{selected_kegiatan.replace(' ', '_')}_{selected_sheet.replace(' ', '_')}.csv",
                        mime="text/csv",
                    )
else:
    st.info("Belum ada data kegiatan di memori. Klik ▶️ Proses Data terlebih dahulu.")



# === Laporan Kegiatan Mitra per Bulan (PDF) ===
import io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

st.markdown("---")
st.subheader("📄 Laporan PDF: Kegiatan Mitra per Bulan")
styles = getSampleStyleSheet()
styleN = styles["Normal"]


# Pastikan data kegiatan ada
if "df_final" not in st.session_state or st.session_state["df_final"].empty:
    st.info("Belum ada data kegiatan. Klik ▶️ Proses Data terlebih dahulu.")
else:
    df_all = st.session_state["df_final"].copy()

    # (Opsional) DB Mitra untuk identitas lebih lengkap
    df_db = st.session_state.get("df_mitra", None)
    if df_db is None and "df_mitra_belum" in st.session_state:
        # tidak ideal, tapi coba ambil struktur dari df_mitra_belum jika user belum simpan df_mitra
        df_db = st.session_state["df_mitra_belum"].copy()

    # Pilih bulan/sheet
    sheet_opts = sorted(df_all["Sumber Sheet"].dropna().astype(str).unique().tolist())
    bulan = st.selectbox("📅 Pilih Bulan/Sheet untuk laporan:", sheet_opts, index=0 if sheet_opts else None)

    # (Opsional) filter kegiatan tertentu atau semua
    df_bulan = df_all[df_all["Sumber Sheet"] == bulan].copy()
    keg_opts1 = ["(Semua)"] + sorted(df_bulan["Kegiatan"].dropna().astype(str).unique().tolist())
    pilih_kegiatan1 = st.selectbox("🗂️ Pilih Kegiatan (opsional):", keg_opts1, index=0)

    if pilih_kegiatan1 != "(Semua)":
        df_bulan = df_bulan[df_bulan["Kegiatan"].astype(str) == pilih_kegiatan1]

    # Normalisasi kolom yang digunakan
    if "Nilai" in df_bulan.columns:
        df_bulan["Nilai"] = pd.to_numeric(df_bulan["Nilai"], errors="coerce").fillna(0)

    # Tentukan kunci identitas utama (NIK kalau ada, fallback Nama)
    use_nik = "NIK" in df_bulan.columns and df_bulan["NIK"].notna().any()
    key_col = "NIK" if use_nik else "Nama"

    # UI: bisa pilih subset mitra (opsional)
    daftar_mitra = sorted(df_bulan[key_col].dropna().astype(str).unique().tolist())
    pilih_mitra = st.multiselect(f"👥 Pilih {key_col} untuk dibikinkan laporan (kosongkan untuk semua):", daftar_mitra, default=[])

    # Tombol generate
    if st.button("🧾 Buat PDF Laporan"):
        if df_bulan.empty:
            st.warning("Tidak ada entri pada filter ini.")
        else:
            # Siapkan lookup identitas dari DB Mitra (berdasarkan NIK atau Nama)
            def norm_nik(x):
                if pd.isna(x): return ""
                return str(x).strip().replace(" ", "")

            def norm_nama(x):
                if pd.isna(x): return ""
                return " ".join(str(x).strip().split()).upper()

            mitra_lookup = {}
            if df_db is not None and not df_db.empty:
                # siapkan kolom standar
                for alt, std in [("nama_lengkap", "nama_lengkap"), ("nik", "nik"),
                                 ("nama_pos", "nama_pos"), ("email", "email"),
                                 ("alamat_kec", "alamat_kec"), ("alamat_desa", "alamat_desa"),
                                 ("tgl_lahir", "tgl_lahir"), ("notelp", "notelp")]:
                    if alt not in df_db.columns:
                        # coba mapping alternatif dari versi sebelumnya
                        if alt == "nik" and "NIK" in df_db.columns: df_db.rename(columns={"NIK": "nik"}, inplace=True)
                        if alt == "nama_lengkap" and "Nama" in df_db.columns: df_db.rename(columns={"Nama": "nama_lengkap"}, inplace=True)

                # index by nik kalau ada, else by nama_lengkap
                if "nik" in df_db.columns and df_db["nik"].notna().any():
                    df_db["_key"] = df_db["nik"].map(norm_nik)
                elif "nama_lengkap" in df_db.columns:
                    df_db["_key"] = df_db["nama_lengkap"].map(norm_nama)
                else:
                    df_db["_key"] = ""

                for _, r in df_db.iterrows():
                    mitra_lookup[str(r.get("_key", ""))] = {
                        "nama_lengkap": r.get("nama_lengkap", ""),
                        "nik": r.get("nik", ""),
                        "nama_pos": r.get("nama_pos", ""),
                        "email": r.get("email", ""),
                        "alamat_kec": r.get("alamat_kec", ""),
                        "alamat_desa": r.get("alamat_desa", ""),
                        "tgl_lahir": r.get("tgl_lahir", ""),
                        "notelp": r.get("notelp", ""),
                    }

            # Kelompokkan per mitra
            df_bulan["_key_mitra"] = df_bulan[key_col].astype(str)
            if key_col == "NIK":
                df_bulan["_key_norm"] = df_bulan["_key_mitra"].map(norm_nik)
            else:
                df_bulan["_key_norm"] = df_bulan["_key_mitra"].map(norm_nama)

            # Filter subset mitra jika dipilih
            if pilih_mitra:
                pilih_set = set([str(x) for x in pilih_mitra])
                df_bulan = df_bulan[df_bulan["_key_mitra"].isin(pilih_set)]

            grouped = df_bulan.sort_values([key_col, "Jadwal", "Kegiatan"]).groupby("_key_norm")

            # ==== Bangun PDF ====
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                leftMargin=18*mm, rightMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm
            )
            
            story = []

            def fmt_rp(x):
                try:
                    return f"Rp{int(x):,}".replace(",", ".")
                except:
                    try:
                        return f"Rp{float(x):,.0f}".replace(",", ".")
                    except:
                        return str(x)

            def fmt_tgl(x):
                # terima string / datetime; kembalikan "dd-mm-yyyy"
                try:
                    t = pd.to_datetime(x, errors="coerce")
                    if pd.isna(t): return str(x)
                    return t.strftime("%d-%m-%Y")
                except:
                    return str(x)

            def umur_from_tgl(tgl):
                if tgl in [None, "", float("nan")]: return ""
                t = pd.to_datetime(tgl, errors="coerce")
                if pd.isna(t): return ""
                today = datetime.today().date()
                return today.year - t.year - ((today.month, today.day) < (t.month, t.day))

            def wa_text(no):
                if not no: return ""
                digits = "".join(c for c in str(no) if c.isdigit())
                if not digits: return ""
                if digits.startswith("0"):
                    digits = "62" + digits[1:]
                elif digits.startswith("8"):
                    digits = "62" + digits
                return f"+{digits}" if not digits.startswith("62") else digits

            judul = f"Laporan Kegiatan Mitra — {bulan}"
            story.append(Paragraph(judul, styles["Title"]))
            story.append(Spacer(1, 6))

            # urutan kunci agar konsisten
            keys_urut = sorted(grouped.groups.keys())

            for idx, key in enumerate(keys_urut, start=1):
                df_m = grouped.get_group(key).copy()

                # Tentukan identitas (ambil dari DB bila ada)
                ident = {}
                if key in mitra_lookup and mitra_lookup[key]:
                    ident = mitra_lookup[key]
                else:
                    # fallback: ambil dari df kegiatan
                    ident = {
                        "nama_lengkap": df_m["Nama"].iloc[0] if "Nama" in df_m.columns else "",
                        "nik": df_m["NIK"].iloc[0] if "NIK" in df_m.columns else "",
                        "nama_pos": df_m["Asal"].iloc[0] if "Asal" in df_m.columns else "",
                        "email": "",
                        "alamat_kec": "",
                        "alamat_desa": "",
                        "tgl_lahir": "",
                        "notelp": "",
                    }

                # Header identitas
                meta = [
                    ["Nama", ident.get("nama_lengkap", "") or df_m.get("Nama", pd.Series([""])).iloc[0]],
                    ["NIK", ident.get("nik", "")],
                    ["POS", ident.get("nama_pos", "")],
                    ["Email", ident.get("email", "")],
                    ["Alamat", f"{ident.get('alamat_desa','')} - {ident.get('alamat_kec','')}"],
                ]
                # umur (jika tersedia tgl_lahir)
                u = umur_from_tgl(ident.get("tgl_lahir", ""))
                if u != "":
                    meta.append(["Umur", f"{u} tahun"])
                # WA (jika tersedia no telp)
                w = wa_text(ident.get("notelp", ""))
                if w:
                    meta.append(["WhatsApp", w])

                tbl_ident = Table(meta, hAlign="LEFT", colWidths=[35*mm, 120*mm])
                tbl_ident.setStyle(TableStyle([
                    ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
                    ("FONTSIZE", (0,0), (-1,-1), 9),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ]))

                story.append(Paragraph(f"<b>Mitra {idx} / {len(keys_urut)}</b>", styles["Heading3"]))
                story.append(tbl_ident)
                story.append(Spacer(1, 4))

                # Tabel kegiatan
                cols = ["No", "Tanggal/Jadwal", "Kegiatan", "Volume", "Nilai"]
                rows = [cols]
                for i, r in enumerate(df_m.itertuples(index=False), start=1):
                    jadwal_text = fmt_tgl(getattr(r, "Jadwal", "")) if "Jadwal" in df_m.columns else ""
                    jadwal = Paragraph(jadwal_text, styleN)   # <<< pakai Paragraph
                    keg = Paragraph(str(getattr(r, "Kegiatan", "")), styleN)
                    vol = Paragraph(str(getattr(r, "Volume", "")), styleN)
                    nilai = fmt_rp(getattr(r, "Nilai", 0)) if "Nilai" in df_m.columns else ""
                    rows.append([i, jadwal, keg, vol, nilai])
                    
                # total
                total_nilai = df_m["Nilai"].sum() if "Nilai" in df_m.columns else 0
                rows.append(["", "", "", "Total", fmt_rp(total_nilai)])

                tbl_keg = Table(
                                    rows,
                                    hAlign="LEFT",
                                    colWidths=[12*mm, None, 80*mm, 25*mm, 30*mm]  # kolom ke-2 (Tanggal) auto-wrap
                                )
                tbl_keg.setStyle(TableStyle([
                    ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
                    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
                    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                    ("ALIGN", (0,0), (0,-1), "CENTER"),
                    ("ALIGN", (3,1), (3,-2), "CENTER"),
                    ("ALIGN", (4,1), (4,-1), "RIGHT"),
                    ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
                    ("FONTSIZE", (0,0), (-1,-1), 9),
                    ("WORDWRAP", (1,1), (1,-1), None),   # kolom Tanggal wrap
                ]))
                story.append(tbl_keg)

                # halaman baru per mitra
                if idx < len(keys_urut):
                    story.append(PageBreak())

            doc.build(story)

            pdf_bytes = buffer.getvalue()
            buffer.close()

            st.success(f"PDF berhasil dibuat untuk {len(keys_urut)} mitra di bulan {bulan}.")
            st.download_button(
                "⬇️ Download PDF Laporan",
                data=pdf_bytes,
                file_name=f"Laporan_Kegiatan_Mitra_{bulan.replace(' ','_')}.pdf",
                mime="application/pdf",
            )


# ====== LAPORAN DOCX BERDASARKAN TEMPLATE WORD ======
from docxtpl import DocxTemplate
import zipfile

st.markdown("---")
st.subheader("📝 Laporan DOCX: Kegiatan Mitra per Bulan (berdasarkan Template Word)")

# Upload template DOCX
template_file = st.file_uploader("📄 Upload Template Word (.docx) dengan placeholder Jinja", type=["docx"], key="tpl_docx")

# Ambil data yang sudah diproses
if "df_final" not in st.session_state or st.session_state["df_final"].empty:
    st.info("Belum ada data kegiatan. Klik ▶️ Proses Data terlebih dahulu.")
else:
    df_all = st.session_state["df_final"].copy()
    df_db = None
    if "df_mitra" in st.session_state and not st.session_state["df_mitra"].empty:
        df_db = st.session_state["df_mitra"].copy()
    elif "df_mitra_belum" in st.session_state and not st.session_state["df_mitra_belum"].empty:
        df_db = st.session_state["df_mitra_belum"].copy()  # fallback minimal

    # Pilihan bulan/sheet
    sheet_opts = sorted(df_all["Sumber Sheet"].dropna().astype(str).unique().tolist())
    bulan = st.selectbox("📅 Pilih Bulan/Sheet:", sheet_opts, index=0 if sheet_opts else None)

    # Filter kegiatan (opsional)
    df_bulan = df_all[df_all["Sumber Sheet"] == bulan].copy()
    keg_opts2 = ["(Semua)"] + sorted(df_bulan["Kegiatan"].dropna().astype(str).unique().tolist())
    pilih_kegiatan2 = st.selectbox("🗂️ Pilih Kegiatan yg Diinginkan (opsional):", keg_opts2, index=0)
    if pilih_kegiatan2 != "(Semua)":
        df_bulan = df_bulan[df_bulan["Kegiatan"].astype(str) == pilih_kegiatan2]

    # Normalisasi kolom nilai
    if "Nilai" in df_bulan.columns:
        df_bulan["Nilai"] = pd.to_numeric(df_bulan["Nilai"], errors="coerce").fillna(0)

    # Kunci grup: utamakan NIK bila ada, jika tidak ada pakai Nama
    use_nik = "NIK" in df_bulan.columns and df_bulan["NIK"].notna().any()
    key_col = "NIK" if use_nik else "Nama"

    # Multiselect mitra
    daftar_mitra = sorted(df_bulan[key_col].dropna().astype(str).unique().tolist())
    pilih_mitra = st.multiselect(f"👥 Pilih {key_col} untuk dibuatkan laporan (kosongkan untuk semua):", daftar_mitra, default=[])

    # ===== Helper normalisasi & lookup identitas =====
    def norm_nik(x):
        if pd.isna(x): return ""
        return "".join(c for c in str(x) if c.isdigit())

    def norm_nama(x):
        if pd.isna(x): return ""
        return " ".join(str(x).strip().split()).upper()

    def hitung_umur(tgl):
        t = pd.to_datetime(tgl, errors="coerce")
        if pd.isna(t): 
            return ""
        today = date.today()   # ✅ sekarang bener
        return today.year - t.year - ((today.month, today.day) < (t.month, t.day))


    def wa_format(no):
        digits = "".join(c for c in str(no) if c.isdigit())
        if not digits: return ""
        if digits.startswith("0"):
            digits = "62" + digits[1:]
        elif digits.startswith("8"):
            digits = "62" + digits
        return f"https://wa.me/{digits}"

    def fmt_rp(x):
        try:
            return f"Rp{int(float(x)):,}".replace(",", ".")
        except:
            return str(x)

    def fmt_tgl(x):
        t = pd.to_datetime(x, errors="coerce")
        if pd.isna(t): return str(x)
        return t.strftime("%d-%m-%Y")

    def prep_df_mitra(df_mitra_raw):
        if df_mitra_raw is None or df_mitra_raw.empty:
            return {}, {}
        df = df_mitra_raw.copy()

        # Samakan nama kolom umum
        if "Nama" in df.columns and "nama_lengkap" not in df.columns:
            df.rename(columns={"Nama": "nama_lengkap"}, inplace=True)
        if "NIK" in df.columns and "nik" not in df.columns:
            df.rename(columns={"NIK": "nik"}, inplace=True)

        for c in ["nama_lengkap","nik","nama_pos","email","alamat_kec","alamat_desa","tgl_lahir","notelp"]:
            if c not in df.columns:
                df[c] = ""

        df["nik_norm"]  = df["nik"].map(norm_nik)
        df["nama_norm"] = df["nama_lengkap"].map(norm_nama)

        # Buat dict lookup
        by_nik  = {r["nik_norm"]: r for _, r in df.iterrows() if r.get("nik_norm")}
        by_nama = {r["nama_norm"]: r for _, r in df.iterrows() if r.get("nama_norm")}
        return by_nik, by_nama

    by_nik, by_nama = prep_df_mitra(df_db)

    def get_identitas_safety(nik_val, nama_val):
        key_nik  = norm_nik(nik_val)
        key_nama = norm_nama(nama_val)
        row = None
        if key_nik and key_nik in by_nik:   row = by_nik[key_nik]
        elif key_nama and key_nama in by_nama: row = by_nama[key_nama]

        if row is None:
            # fallback dari data kegiatan
            return {
                "nama_lengkap": nama_val or "",
                "nik": nik_val or "",
                "nama_pos": "",
                "email": "",
                "alamat_kec": "",
                "alamat_desa": "",
                "tgl_lahir": "",
                "notelp": "",
            }
        else:
            return {
                "nama_lengkap": row.get("nama_lengkap",""),
                "nik": row.get("nik",""),
                "nama_pos": row.get("nama_pos",""),
                "email": row.get("email",""),
                "alamat_kec": row.get("alamat_kec",""),
                "alamat_desa": row.get("alamat_desa",""),
                "tgl_lahir": row.get("tgl_lahir",""),
                "notelp": row.get("notelp",""),
            }

    # ===== Tombol Generate DOCX =====
    if st.button("🧾 Buat Laporan DOCX (ZIP)"):
        if template_file is None:
            st.warning("Upload template Word (.docx) terlebih dahulu.")
        elif df_bulan.empty:
            st.warning("Tidak ada data pada filter ini.")
        else:
            # Filter subset mitra (jika dipilih)
            work = df_bulan.copy()
            if pilih_mitra:
                pilih_set = set([str(x) for x in pilih_mitra])
                work = work[work[key_col].astype(str).isin(pilih_set)]

            # Group per mitra
            groups = work.groupby(key_col, dropna=True)
            if groups.ngroups == 0:
                st.info("Tidak ada mitra pada filter ini.")
            else:
                # Siapkan ZIP in-memory
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    # generate satu per mitra
                    for key_val, df_mitra_bln in groups:
                        nama_val = df_mitra_bln["Nama"].iloc[0] if "Nama" in df_mitra_bln.columns else str(key_val)
                        nik_val  = df_mitra_bln["NIK"].iloc[0]  if "NIK"  in df_mitra_bln.columns else (str(key_val) if key_col=="NIK" else "")
                        ident = get_identitas_safety(nik_val, nama_val)

                        # Susun daftar kegiatan
                        rows = []
                        total_nilai = 0
                        for _, r in df_mitra_bln.iterrows():
                            jad = fmt_tgl(r.get("Jadwal", ""))
                            keg = str(r.get("Kegiatan", ""))
                            vol = str(r.get("Volume", ""))
                            nil = float(r.get("Nilai", 0)) if pd.notna(r.get("Nilai", 0)) else 0
                            total_nilai += nil
                            rows.append({
                                "jadwal": jad,
                                "nama": keg,
                                "volume": vol,
                                "nilai": fmt_rp(nil),
                            })

                        context = {
                            "bulan": bulan,
                            "nama_lengkap": ident["nama_lengkap"],
                            "nik": ident["nik"],
                            "nama_pos": ident["nama_pos"],
                            "email": ident["email"],
                            "alamat_kec": ident["alamat_kec"],
                            "alamat_desa": ident["alamat_desa"],
                            "umur": hitung_umur(ident["tgl_lahir"]),
                            "whatsapp": wa_format(ident["notelp"]),
                            "kegiatan": rows,
                            "total_nilai": fmt_rp(total_nilai),
                        }

                        # Render docx dari template upload
                        tpl = DocxTemplate(template_file)
                        tpl.render(context)

                        # Simpan ke buffer per-file, lalu tulis ke ZIP
                        outfile_name = f"laporan_{(ident['nik'] or key_val)}_{bulan.replace(' ','_')}.docx"
                        out_buf = io.BytesIO()
                        tpl.save(out_buf)
                        zf.writestr(outfile_name, out_buf.getvalue())

                st.success(f"Berhasil membuat laporan untuk {groups.ngroups} mitra.")
                st.download_button(
                    "⬇️ Download ZIP Laporan DOCX",
                    data=zip_buf.getvalue(),
                    file_name=f"Laporan_Mitra_{bulan.replace(' ','_')}.zip",
                    mime="application/zip",
                )
