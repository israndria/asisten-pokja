Dim fso, shell

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)

python = shell.Environment("Process")("POKJA_PYTHON")
If Len(python) = 0 Then python = fso.GetAbsolutePathName(appDir & "\..\Runtime\WPy64-313110\python\python.exe")
If Not fso.FileExists(python) Then python = "C:\WinPython313\python\python.exe"
If Not fso.FileExists(python) Then WScript.Quit

appPy = appDir & "\app.py"
port = "8506"
shell.Environment("Process")("POKJA_CODE_ROOT") = appDir
shell.Environment("Process")("POKJA_PYTHON") = python
shell.Environment("Process")("ASISTEN_INSTANCE") = "TENDER"
shell.Environment("Process")("ASISTEN_FIXED_ROLE") = "POKJA"
shell.Environment("Process")("SPSE_CDP_PORT") = "9223"

checkResult = shell.Run("cmd /c netstat -ano | findstr :" & port & " | findstr LISTENING", 0, True)
If checkResult <> 0 Then
    shell.CurrentDirectory = appDir
    cmd = """" & python & """ -m streamlit run """ & appPy & """"
    cmd = cmd & " --server.port " & port
    cmd = cmd & " --server.headless true"
    cmd = cmd & " --server.runOnSave false"
    cmd = cmd & " --server.fileWatcherType none"
    cmd = cmd & " --browser.gatherUsageStats false"
    shell.Run cmd, 0, False
End If
