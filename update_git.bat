@echo off
title Update GitHub Repository
echo ======================================================
echo          GIT AUTO UPDATE SCRIPT by ChatGPT
echo ======================================================
echo.

REM Tampilkan status git
git status
echo.

REM Tambahkan semua perubahan
echo Menambahkan semua perubahan...
git add .
echo.

REM Minta pesan commit dari pengguna
set /p msg=Masukkan pesan commit: 

REM Commit dengan pesan yang dimasukkan
git commit -m "%msg%"
echo.

REM Sinkronisasi dengan repo GitHub
echo Menarik perubahan terbaru (git pull)...
git pull origin master
echo.

REM Kirim ke repository GitHub
echo Mengirim perubahan ke GitHub...
git push origin master
echo.

echo ======================================================
echo             PROSES SELESAI!
echo ======================================================
pause
