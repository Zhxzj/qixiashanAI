# 等本程序的服务就绪，并输出访问地址（给 start.bat 用）
param([int]$Port = 8017, [int]$TimeoutSec = 45)
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:{0}/api/health" -f $Port) -TimeoutSec 2
    if ($r.StatusCode -eq 200) {
      Write-Output ("http://127.0.0.1:{0}" -f $Port)
      exit 0
    }
  } catch { Start-Sleep -Milliseconds 700 }
  Start-Sleep -Milliseconds 700
}
exit 1
