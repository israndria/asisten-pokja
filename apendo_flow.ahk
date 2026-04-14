; apendo_flow.ahk — Full automation Apendo v5.1.5
; Args: apendo_path, token_url, folder_output, log_file
; Semua mouse click pakai ControlClick (Win32 message, bypass Qt synthetic event filter)

#NoEnv
#SingleInstance Force

; Baca argumen via A_Args (support path dengan spasi & karakter khusus)
apendo        := A_Args[1]
token         := A_Args[2]
folder        := A_Args[3]
logfile       := A_Args[4]
jumlah_peserta := A_Args[5] ? A_Args[5] + 0 : 3  ; default 3

if (!apendo || !token || !folder || !logfile) {
    MsgBox, Usage: apendo_flow.ahk apendo_path token_url folder_output log_file [jumlah_peserta]
    ExitApp, 1
}

; Helper log
AppendLog(msg) {
    global logfile
    FormatTime, ts,, HH:mm:ss
    FileAppend, [%ts%] %msg%`n, %logfile%
}

AppendLog("START apendo_flow.ahk")
AppendLog("Apendo: " . apendo)
AppendLog("Token: " . SubStr(token, 1, 60) . "...")
AppendLog("Folder: " . folder)

; ── STEP 1: Launch Apendo ─────────────────────────────────────────
AppendLog("Meluncurkan Apendo...")
SplitPath, apendo, , apendo_dir
Run, "%apendo%", %apendo_dir%
WinWait, Aplikasi Pengaman Dokumen,, 20
if ErrorLevel {
    AppendLog("FAIL: Apendo tidak muncul dalam 20 detik")
    ExitApp, 2
}
WinActivate, Aplikasi Pengaman Dokumen
Sleep, 3000
AppendLog("Apendo terbuka")

; ── STEP 2: Set clipboard dengan token ────────────────────────────
AppendLog("Set clipboard dengan token...")
Clipboard := token
ClipWait, 3
if ErrorLevel {
    AppendLog("FAIL: ClipWait timeout")
    ExitApp, 3
}
Sleep, 1000
AppendLog("Clipboard siap")

; ── STEP 3: Klik area textarea untuk fokus ────────────────────────
; Textarea token ada di sekitar x=410, y=200 (window size ~800x600)
AppendLog("Klik textarea token...")
ControlClick, x410 y200, Aplikasi Pengaman Dokumen, , LEFT, 1, NA
Sleep, 800

; ── STEP 4: Paste token dengan Ctrl+V ─────────────────────────────
AppendLog("Paste token Ctrl+V...")
Send, ^v
Sleep, 2500
AppendLog("Token di-paste")

; ── STEP 5: Klik tombol Kirim Token ───────────────────────────────
; Tombol Kirim Token ada di sekitar x=116, y=261
AppendLog("Klik Kirim Token...")
ControlClick, x116 y261, Aplikasi Pengaman Dokumen, , LEFT, 1, NA
AppendLog("Kirim Token diklik, menunggu loading...")
Sleep, 6000

; ── STEP 6: Handle JS Confirm "Setting folder" → tekan ESC ───────
; ESC = skip Select Folder, pakai folder default, langsung masuk halaman tender
AppendLog("Cek dialog JS Confirm...")
WinWait, JavaScript Confirm,, 8
if ErrorLevel {
    AppendLog("JS Confirm tidak muncul, lanjut...")
} else {
    WinActivate, JavaScript Confirm
    WinWaitActive, JavaScript Confirm,, 3
    Send, {Escape}
    AppendLog("JS Confirm -> ESC (skip Select Folder)")
    Sleep, 1000
}

; ── STEP 7: Tunggu Apendo load + pindah window ke posisi tetap ────
AppendLog("Menunggu Apendo load data tender...")
Sleep, 15000

; ── STEP 8: Klik tab "Pembukaan Dokumen Penawaran" ────────────────
; Screen 256,163 (tanpa WinMove — koordinat aktual dari cursor)
AppendLog("STEP8: WinActivate...")
WinActivate, Aplikasi Pengaman Dokumen
Sleep, 500
AppendLog("STEP8: Send Click tab Pembukaan...")
Send, {Click 256, 163}
AppendLog("STEP8: Sleep 1500...")
Sleep, 1500
AppendLog("STEP8: Tab Pembukaan Dokumen Penawaran diklik")

; ── STEP 9: Klik tombol "Buka Dokumen Penawaran" ──────────────────
; Screen 343,221 (tanpa WinMove — koordinat aktual dari cursor)
AppendLog("STEP9: WinActivate...")
WinActivate, Aplikasi Pengaman Dokumen
Sleep, 300
AppendLog("STEP9: Send Click Buka Dokumen Penawaran...")
Send, {Click 343, 221}
AppendLog("STEP9: Menunggu proses dekripsi (20 detik)...")
Sleep, 20000

; ── STEP 10: Klik semua tombol Unduh per peserta ──────────────────
; Koordinat akurat dari cursor: Peserta 1 Screen 638,368 | Peserta 2 Screen 638,456 | Interval 88px
AppendLog("Mulai klik tombol Unduh per peserta...")
WinActivate, Aplikasi Pengaman Dokumen
Sleep, 300

AppendLog("Jumlah peserta: " . jumlah_peserta)
Loop, %jumlah_peserta%
{
    unduh_screen_y := 368 + (A_Index - 1) * 88
    AppendLog("Klik Unduh peserta " . A_Index . " @ screen x=638, y=" . unduh_screen_y)
    Send, {Click 638, %unduh_screen_y%}
    Sleep, 12000  ; tunggu decrypt per peserta

    IfWinNotExist, Aplikasi Pengaman Dokumen
    {
        AppendLog("Window Apendo hilang, stop")
        break
    }
}

AppendLog("DONE")
ExitApp, 0
