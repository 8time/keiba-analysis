<#
  JV-Link オッズ取り込みバッチ

  使い方: PowerShellで実行（Claude Code不要）
    .\scripts\ingest_batch.ps1 1          # バッチ1: 1986-1995
    .\scripts\ingest_batch.ps1 2          # バッチ2: 1996-2005
    .\scripts\ingest_batch.ps1 3          # バッチ3: 2006-2015
    .\scripts\ingest_batch.ps1 4          # バッチ4: 2016-2026
    .\scripts\ingest_batch.ps1 all        # 全部一気に（寝る前に）

  所要時間目安: 1バッチ = 約3-5時間
#>
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Batch
)

$PY = "C:\Users\kimnhaty\pythonx86-312\tools\python.exe"
$SCRIPT = Join-Path $PSScriptRoot "jvlink_ingest.py"

# gen_pyキャッシュクリア（COM接続エラー防止）
$genpy = Join-Path $env:LOCALAPPDATA "Temp\gen_py"
if (Test-Path $genpy) { Remove-Item $genpy -Recurse -Force -Confirm:$false }

$batches = @{
    "1" = @(1986, 1995)
    "2" = @(1996, 2005)
    "3" = @(2006, 2015)
    "4" = @(2016, 2026)
}

function Run-Batch($from, $to) {
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  BATCH: $from - $to" -ForegroundColor Cyan
    Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') START" -ForegroundColor Cyan
    Write-Host "========================================`n" -ForegroundColor Cyan

    & $PY $SCRIPT --from-year $from --to-year $to

    Write-Host "`n  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') DONE ($from-$to)" -ForegroundColor Green
}

if ($Batch -eq "all") {
    foreach ($key in ($batches.Keys | Sort-Object)) {
        $range = $batches[$key]
        Run-Batch $range[0] $range[1]
    }
    Write-Host "`n*** ALL BATCHES COMPLETE ***" -ForegroundColor Yellow
} elseif ($batches.ContainsKey($Batch)) {
    $range = $batches[$Batch]
    Run-Batch $range[0] $range[1]
} else {
    Write-Host "Unknown batch: $Batch" -ForegroundColor Red
    Write-Host "Usage: .\ingest_batch.ps1 {1|2|3|4|all}"
}
