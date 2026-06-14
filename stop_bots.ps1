$killed = 0
$targets = @(
    @{ pattern='bot_donchian_v3'; name='BTC Donchian' },
    @{ pattern='bot_ema_pullback_eth'; name='ETH EMA' }
)

foreach ($t in $targets) {
    $py = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match $t.pattern }
    foreach ($p in $py) {
        $pyId   = $p.ProcessId
        $parId  = $p.ParentProcessId
        Write-Host "[1] Ubivaem Python $($t.name) PID $pyId"
        Stop-Process -Id $pyId -Force -ErrorAction SilentlyContinue
        $parent = Get-Process -Id $parId -ErrorAction SilentlyContinue
        if ($parent) {
            Write-Host "[2] Ubivaem roditelya $($parent.ProcessName) PID $parId (loop)"
            Stop-Process -Id $parId -Force -ErrorAction SilentlyContinue
        }
        $killed++
    }
}

if ($killed -eq 0) {
    Write-Host '[INFO] Python-protsessy botov ne naydeny. Pytayemsya nayti CMD-loop...'
    $cmd = Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" | Where-Object { $_.CommandLine -match 'run_donchian_loop|run_ema_loop' }
    foreach ($c in $cmd) {
        Write-Host "[3] Ubivaem CMD-loop PID $($c.ProcessId)"
        Stop-Process -Id $c.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
}

if ($killed -eq 0) {
    Write-Host '[INFO] Boty ne naydeny. Mozhet, oni uzhe ostanovleny?'
}
