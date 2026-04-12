Dim shell, port, checkResult, cmd, python, appDir, appPy

python  = "D:\Dokumen\@ POKJA 2026\V19_Scheduler\WPy64-313110\python\pythonw.exe"
appDir  = "D:\Dokumen\@ POKJA 2026\Asisten_Pokja"
appPy   = appDir & "\app.py"
port    = "8502"

Set shell = CreateObject("WScript.Shell")

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
