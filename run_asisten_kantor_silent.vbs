Dim shell, port, checkResult, cmd, python, appDir, appPy

python  = "C:\WinPython313\python\python.exe"
appDir  = "G:\Other computers\My Laptop\@ POKJA 2026\Asisten_Pokja"
appPy   = appDir & "\app.py"
port    = "8502"

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Sinkronkan source sebelum Streamlit start; cegah app.py/module beda versi.
shell.CurrentDirectory = appDir
shell.Run "cmd /c git pull --ff-only origin master", 0, True

' Tunggu Google Drive menyelesaikan file hasil pull.
For i = 1 To 30
    If fso.FileExists(appDir & "\ui_dpa.py") Then Exit For
    WScript.Sleep 1000
Next
If Not fso.FileExists(appDir & "\ui_dpa.py") Then WScript.Quit

' Cek apakah port sudah aktif
checkResult = shell.Run("cmd /c netstat -ano | findstr :" & port, 0, True)

If checkResult = 0 Then
    WScript.Quit
Else
    shell.CurrentDirectory = appDir
    cmd = """" & python & """ -m streamlit run """ & appPy & """"
    cmd = cmd & " --server.port " & port
    cmd = cmd & " --server.headless true"
    cmd = cmd & " --browser.gatherUsageStats false"
    shell.Run cmd, 0, False
End If
