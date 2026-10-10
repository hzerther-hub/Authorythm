# 以管理员运行:把 Python 3.13 前置到机器级 PATH(reg.exe 读写 REG_EXPAND_SZ)
$ErrorActionPreference = 'Stop'
$log = 'E:\pydrama\docs\_elevate_path_result.txt'
$key = 'HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
$p313  = 'C:\Users\user\AppData\Local\Programs\Python\Python313\'
$p313s = 'C:\Users\user\AppData\Local\Programs\Python\Python313\Scripts\'

try {
  $query = C:\Windows\System32\reg.exe query $key /v Path 2>&1
  $line = ($query | Select-String -Pattern 'Path\s+REG_\w+\s+(.*)$').Matches[0].Groups[1].Value
  if (-not $line) { throw 'registry Path not found' }

  if ($line.StartsWith($p313)) {
    Set-Content -Path $log -Value 'ALREADY-SET' -Encoding UTF8
    exit 0
  }

  $new = $p313 + ';' + $p313s + ';' + $line
  C:\Windows\System32\reg.exe add $key /v Path /t REG_EXPAND_SZ /d "$new" /f | Out-Null

  $check = (C:\Windows\System32\reg.exe query $key /v Path 2>&1 | Select-String -Pattern 'Path\s+REG_\w+\s+(.*)$').Matches[0].Groups[1].Value
  if ($check.StartsWith($p313)) {
    Set-Content -Path $log -Value 'OK' -Encoding UTF8
  } else {
    Set-Content -Path $log -Value 'VERIFY-FAILED: ' + $check.Substring(0, 80) -Encoding UTF8
  }
} catch {
  Set-Content -Path $log -Value ('ERROR: ' + $_.Exception.Message) -Encoding UTF8
}
