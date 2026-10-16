# 如果本程序已经有服务在 8017/8018/8019 上运行，输出它的地址（给 start.bat 用）
foreach ($p in 8017, 8018, 8019) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:{0}/api/health" -f $p) -TimeoutSec 2
    if ($r.StatusCode -eq 200) {
      Write-Output ("http://127.0.0.1:{0}" -f $p)
      exit 0
    }
  } catch { }
}
exit 1
