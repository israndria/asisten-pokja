Dim shell, fso, port, checkResult, cmd, python, appDir, appPy

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
appDir  = fso.GetParentFolderName(WScript.ScriptFullName)
python  = shell.Environment("Process")("POKJA_PYTHON")
If Len(python) = 0 Then python = "C:\WinPython313\python\python.exe"
If Not fso.FileExists(python) Then
    python = fso.GetAbsolutePathName(appDir & "\..\Runtime\WPy64-313110\python\python.exe")
End If
appPy   = appDir & "\app.py"
port    = "8502"

shell.Environment("Process")("POKJA_CODE_ROOT") = appDir
shell.Environment("Process")("POKJA_PYTHON") = python
If Len(shell.Environment("Process")("POKJA_V19_ROOT")) = 0 Then _
    shell.Environment("Process")("POKJA_V19_ROOT") = fso.GetAbsolutePathName(appDir & "\..\procurement_core")
If Len(shell.Environment("Process")("POKJA_DRIVE_ROOT")) = 0 Then _
    shell.Environment("Process")("POKJA_DRIVE_ROOT") = "C:\POKJA2026"
If Len(shell.Environment("Process")("POKJA_SECRET_ROOT")) = 0 Then _
    shell.Environment("Process")("POKJA_SECRET_ROOT") = fso.GetAbsolutePathName(appDir & "\..\Secrets")
shell.CurrentDirectory = appDir
If Not fso.FileExists(appDir & "\ui_dpa.py") Then WScript.Quit

' Cek apakah port sudah aktif
checkResult = shell.Run("cmd /c netstat -ano | findstr :" & port & " | findstr LISTENING", 0, True)

If checkResult = 0 Then
    WScript.Quit
Else
    shell.CurrentDirectory = appDir
    cmd = """" & python & """ -m streamlit run """ & appPy & """"
    cmd = cmd & " --server.port " & port
    cmd = cmd & " --server.headless true"
    cmd = cmd & " --server.runOnSave true"
    cmd = cmd & " --server.fileWatcherType auto"
    cmd = cmd & " --browser.gatherUsageStats false"
    shell.Run cmd, 0, False
End If
