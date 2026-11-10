# DT1 local split (PRD §13.5), PowerShell twin of local_cluster.sh for Windows without Git Bash:
# start one `flipwise dc-serve` per datacentre on 127.0.0.1, wait for /health, run
# `flipwise run --mode remote`, then stop every service, also on failure or Ctrl-C (R-DEP-3).
#
#   .\scripts\local_cluster.ps1 [--base-port 8101] [--n-dc 3] [--crash DC:N] <run args>
#   .\scripts\local_cluster.ps1 --scenario tests/fixtures/toy --policy decision_flip
#
# --crash DC:N is fault injection for R-DEP-3: service DC exits on its N-th simulation request.
# Service logs end up in results/<run_id>/dc-<id>.log (or the run's --out folder).
# Arguments are parsed by hand: an advanced param() block would read `--out` as PowerShell's
# own -OutVariable/-OutBuffer. The flags match local_cluster.sh.
$BasePort = 8101; $NDc = 3; $Crash = ''; $RunArgs = @()
for ($k = 0; $k -lt $args.Count; $k++) {
    switch ($args[$k]) {
        '--base-port' { $BasePort = [int]$args[++$k] }
        '--n-dc' { $NDc = [int]$args[++$k] }
        '--crash' { $Crash = [string]$args[++$k] }
        default { $RunArgs += [string]$args[$k] }
    }
}
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$py = if (Test-Path .venv\Scripts\python.exe) { '.venv\Scripts\python.exe' } else { uv sync -q; '.venv\Scripts\python.exe' }
$py = (Resolve-Path $py).Path
$ports = 0..($NDc - 1) | ForEach-Object { $BasePort + $_ }
$urls = $ports | ForEach-Object { "http://127.0.0.1:$_" }
$urlList = $urls -join ','

# Refuse busy ports before starting anything (the same bind test as local_cluster.sh).
& $py -c "import socket, sys`nfor p in sys.argv[1:]:`n    s = socket.socket()`n    try:`n        s.bind(('127.0.0.1', int(p)))`n    except OSError:`n        sys.exit('port ' + p + ' is in use')`n    finally:`n        s.close()" @ports
if ($LASTEXITCODE -ne 0) { Write-Host "local_cluster: port in use; nothing started"; exit 2 }
$logDir = Join-Path ([IO.Path]::GetTempPath()) ("flipwise_cluster_" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory $logDir | Out-Null
$procs = @()
$status = 1

function Stop-Services {
    # /T stops each launcher's whole tree, including the interpreter the venv launcher starts.
    # Only processes this script started are touched, never "whatever holds the port".
    # Through cmd and never fatal: in Windows PowerShell 5.1 with ErrorActionPreference 'Stop', a
    # native program's stderr (taskkill's "not found" for a service that already crashed) is a
    # terminating error, which used to abort this loop and leave the later services running.
    foreach ($proc in $script:procs) {
        try { cmd /c "taskkill /F /T /PID $($proc.Id) >nul 2>&1" } catch { }
    }
    $script:procs = @()
}
try {
    for ($i = 0; $i -lt $NDc; $i++) {
        $argList = @('-m', 'flipwise.cli', 'dc-serve', '--dc-id', "$i", '--port', "$($ports[$i])")
        if ($Crash -and $Crash.Split(':')[0] -eq "$i") { $argList += @('--crash-at-request', $Crash.Split(':')[1]) }
        $procs += Start-Process -FilePath $py -ArgumentList $argList -PassThru -NoNewWindow `
            -RedirectStandardOutput (Join-Path $logDir "dc-$i.log") -RedirectStandardError (Join-Path $logDir "dc-$i.err")
    }

    $deadline = (Get-Date).AddSeconds(20)
    foreach ($u in $urls) {
        while ($true) {
            try { Invoke-RestMethod "$u/health" -TimeoutSec 1 | Out-Null; break }
            catch {
                if ((Get-Date) -gt $deadline) { throw "local_cluster: $u did not answer /health in 20 s" }
                Start-Sleep -Milliseconds 100
            }
        }
    }
    Write-Host "local_cluster: $NDc services up on $urlList"

    $runLog = Join-Path $logDir 'run.log'
    # Native stderr must not become a terminating error here: the exit code is what counts.
    $ErrorActionPreference = 'Continue'
    & $py -m flipwise.cli run --mode remote --dc-urls $urlList @RunArgs 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $runLog
    $status = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
}
finally {
    Stop-Services
}

$runDir = Select-String -Path (Join-Path $logDir 'run.log') -Pattern '^wrote (.+)$' -ErrorAction SilentlyContinue |
    Select-Object -Last 1 | ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() }
if ($status -eq 0 -and $runDir) {
    Copy-Item (Join-Path $logDir 'dc-*.log') $runDir
    Write-Host "local_cluster: done; service logs in $runDir"
} else {
    Write-Host "local_cluster: run failed (exit $status); service logs in $logDir"
}
exit $status
