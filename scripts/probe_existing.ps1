# Inspect only the recorded application instance. Never accept arbitrary HTTP 200.
$userRoot = if ($env:QIXI_USER_DIR) { $env:QIXI_USER_DIR } else { Join-Path $env:LOCALAPPDATA 'QixiGuide' }
try {
  $instance = Get-Content -LiteralPath (Join-Path $userRoot 'instance/current.json') -Raw | ConvertFrom-Json
  $url = 'http://127.0.0.1:{0}' -f $instance.port
  $health = Invoke-RestMethod -Uri ($url + '/api/health') -TimeoutSec 2
  if ($health.ok -eq $true -and $health.app_id -eq 'qixi-guide' -and $health.api_version -eq 2 -and $health.instance_id -eq $instance.instance_id -and $health.build_id -eq $instance.build_id) {
    Write-Output $url
    exit 0
  }
} catch { }
exit 1
