param(
    [Parameter(Mandatory)]
    [int]$Port
)
$pids = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($listenPid in $pids) {
    try {
        Stop-Process -Id $listenPid -Force -ErrorAction Stop
    }
    catch {
        # Ignore; port may belong to elevated / system process.
    }
}
