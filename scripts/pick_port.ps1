# 输出 8017/8018/8019 中第一个空闲端口；都占用则输出 0（给 start.bat 用）
$busy = @{}
try {
  netstat -ano -p tcp | Select-String "LISTENING" | ForEach-Object {
    if ($_ -match "127\.0\.0\.1:(80\d\d)\s") { $busy[$matches[1]] = $true }
  }
} catch { }
foreach ($p in "8017", "8018", "8019") {
  if (-not $busy.ContainsKey($p)) { Write-Output $p; exit 0 }
}
Write-Output "0"
