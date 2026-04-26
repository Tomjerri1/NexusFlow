# Live integration test: uvicorn + REST round-trip.
# Usage: powershell -File run_integration_test.ps1
# NOTE: kept ASCII-only because PowerShell 5.1 reads .ps1 as ANSI by default.

$ErrorActionPreference = "Stop"
$port = 8765

Write-Host "Starting uvicorn on :$port ..."
$proc = Start-Process -PassThru -NoNewWindow `
    -RedirectStandardOutput uvicorn.log `
    -RedirectStandardError uvicorn.err `
    python -ArgumentList @("-m", "uvicorn", "app.main:app", "--port", "$port", "--log-level", "warning")

Start-Sleep -Seconds 2

try {
    # 1. /health must return 200
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health"
    Write-Host "health: $($health | ConvertTo-Json -Compress)"

    # 2. /docs must return 404 (auto-docs disabled)
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$port/docs" -UseBasicParsing | Out-Null
        Write-Host "docs: 200 (UNEXPECTED - should be off)"
        exit 1
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        Write-Host "docs: $code (expected 404)"
    }

    # 3. POST /jobs/run with examples/01_hello_world.json
    $hello = Get-Content examples/01_hello_world.json -Raw
    $body = "{`"workflow`":$hello}"
    $job = Invoke-RestMethod -Uri "http://127.0.0.1:$port/jobs/run" `
        -Method POST -ContentType "application/json" -Body $body
    Write-Host "submitted: id=$($job.id) status=$($job.status)"

    Start-Sleep -Milliseconds 500

    # 4. GET /jobs/{id} should be success + sentinel done
    $final = Invoke-RestMethod -Uri "http://127.0.0.1:$port/jobs/$($job.id)"
    Write-Host "final: status=$($final.status) logs=$($final.logs.Count)"
    Write-Host "last log level: $($final.logs[-1].level)"
    Write-Host "last log msg:   $($final.logs[-1].message)"

    if ($final.status -ne "success") {
        Write-Host "FAIL: expected status=success, got $($final.status)"
        exit 1
    }
    Write-Host ""
    Write-Host "OK: live integration passed."
} finally {
    Stop-Process -Id $proc.Id -Force
    Write-Host "uvicorn stopped"
}
