Dim shell, fso, port, checkResult, cmd, python, appDir, appPy

Set fso = CreateObject("Scripting.FileSystemObject")
appDir  = fso.GetParentFolderName(WScript.ScriptFullName)
python  = fso.GetAbsolutePathName(appDir & "\..\Runtime\WPy64-313110\python\python.exe")
appPy   = appDir & "\app.py"
port    = "8502"

Set shell = CreateObject("WScript.Shell")
shell.Environment("Process")("POKJA_CODE_ROOT") = appDir
shell.Environment("Process")("POKJA_PYTHON") = python

' Cek apakah port sudah aktif
checkResult = shell.Run("cmd /c netstat -ano | findstr :" & port & " | findstr LISTENING", 0, True)

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
