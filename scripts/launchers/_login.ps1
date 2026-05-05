$proc = Start-Process -FilePath 'C:\Users\dell\.local\bin\onchainos.exe' -ArgumentList 'wallet login aijfanta@gmail.com' -PassThru -WindowStyle Hidden
Start-Sleep 3
$proc.StandardInput.WriteLine('897195')
$proc.StandardInput.Close()
$proc.WaitForExit()
Write-Output ('Exit:' + $proc.ExitCode)
