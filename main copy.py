import streamlit as st
import subprocess
import webbrowser
import os
from pathlib import Path

st.set_page_config(page_title="Portal Project Streamlit", page_icon="🚀", layout="wide")

st.title("🚀 Portal Project Streamlit")
st.markdown("Pilih project yang ingin dijalankan:")

# Folder tempat semua project berada
projects_dir = Path("projects")
project_folders = [p for p in projects_dir.iterdir() if p.is_dir()]

projects = []
base_port = 8502

# Bangun daftar project otomatis
for i, folder in enumerate(sorted(project_folders)):
    app_file = folder / "app.py"
    if app_file.exists():
        projects.append({
            "name": f"📁 {folder.name.replace('_', ' ').title()}",
            "path": str(app_file),
            "port": base_port + i
        })

# Tampilkan project dalam grid
cols = st.columns(3)
for idx, proj in enumerate(projects):
    col = cols[idx % 3]
    with col:
        st.markdown(f"### {proj['name']}")
        st.write(f"File: `{proj['path']}`")
        st.write(f"Port: `{proj['port']}`")
        if st.button(f"🚀 Jalankan {proj['name']}", key=proj["name"]):
            subprocess.Popen(
                ["streamlit", "run", proj["path"], "--server.port", str(proj["port"])]
            )
            webbrowser.open_new_tab(f"http://localhost:{proj['port']}")
            st.success(f"{proj['name']} dijalankan di port {proj['port']}")
