Option Explicit
Dim shell, fs, folder, command
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
command = "pyw -3 """ & folder & "\bootstrap.pyw"""
On Error Resume Next
shell.Run command, 0, False
If Err.Number <> 0 Then
    Err.Clear
    shell.Run "pythonw """ & folder & "\bootstrap.pyw""", 0, False
    If Err.Number <> 0 Then
        MsgBox "Easy Realms needs Python 3.11 or newer. Install it from python.org with the Python launcher and Tcl/Tk options enabled, then try again.", 48, "Easy Realms - Python required"
    End If
End If
