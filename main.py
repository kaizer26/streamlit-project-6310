import streamlit as st
import importlib.util
import os
from pathlib import Path

st.set_page_config(page_title="Portal Project Streamlit", page_icon="🚀", layout="wide")

st.title("🚀 Portal Project Streamlit")
st.markdown("Pilih project yang ingin dijalankan:")

# Folder tempat semua project berada
projects_dir = Path("projects")
project_folders = [p for p in projects_dir.iterdir() if p.is_dir()]

# Buat dictionary daftar project
projects = []
for folder in sorted(project_folders):
    app_file = folder / "app.py"
    if app_file.exists():
        projects.append({
            "name": folder.name.replace('_', ' ').title(),
            "path": app_file
        })

# Sidebar untuk navigasi antar project
st.sidebar.title("📂 Daftar Project")
menu = st.sidebar.radio("Pilih Project:", [p["name"] for p in projects])

# Temukan project yang dipilih
selected_project = next((p for p in projects if p["name"] == menu), None)

if selected_project:
    st.markdown(f"## 📊 {selected_project['name']}")
    app_path = selected_project["path"]

    # Muat modul secara dinamis
    spec = importlib.util.spec_from_file_location("app_module", app_path)
    app_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_module)

    # Jika file app.py punya fungsi run(), panggil itu
    if hasattr(app_module, "run"):
        app_module.run()
    else:
        st.info("Menjalankan isi langsung dari file app.py...")
        # Eksekusi file Streamlit langsung (fallback)
        exec(app_path.read_text(), {"st": st})
