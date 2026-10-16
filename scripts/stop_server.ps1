# 停止本程序在 8017/8018/8019 上的服务。
# 做法：找监听这些端口的进程 → 确认进程名是 python/pythonw → 停止（不碰其他程序）。
$ports = 8017, 8018, 8019
$pids = @{}
foreach ($port in $ports) {
  try {
    $found = netstat -ano -p tcp | Select-String (":{0}\s" -f $port) | Select-String "LISTENING"
    foreach ($l in $found) {
      if ($l.Line -match "LISTENING\s+(\d+)") { $pids[$matches[1]] = $port }
    }
  } catch { }
}
if ($pids.Count -eq 0) {
  Write-Host "没有发现正在运行的小向导服务（端口 8017-8019）。"
  exit 0
}
$killed = 0
foreach ($pidText in @($pids.Keys)) {
  $proc = Get-Process -Id $pidText -ErrorAction SilentlyContinue
  if (-not $proc) { continue }
  if ($proc.ProcessName -notin @("python", "pythonw")) {
    Write-Host ("端口 {0} 被 {1}（PID {2}）占用，不是小向导的进程，跳过。" -f $pids[$pidText], $proc.ProcessName, $pidText)
    continue
  }
  try {
    Stop-Process -Id $pidText -Force -ErrorAction Stop
    Write-Host ("已停止 PID {0}（端口 {1}）" -f $pidText, $pids[$pidText])
    $killed++
  } catch {
    Write-Host ("PID {0} 停止失败：{1}" -f $pidText, $_.Exception.Message)
  }
}
if ($killed -eq 0) { Write-Host "没有停掉任何进程（可能服务本来就没跑）。" }
else { Write-Host ("共停止 {0} 个进程。" -f $killed) }
