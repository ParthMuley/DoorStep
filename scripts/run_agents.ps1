# DOORSTEP DEMO - start the three Fetch.ai agents in separate windows (Windows / PowerShell).
# Usage: .\scripts\run_agents.ps1            (from the repo root, with .env filled in)
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
foreach ($module in "transport_provider", "destination_provider", "coordinator") {
    Start-Process -FilePath $python -ArgumentList "-m", "doorstep.agents.$module" -WorkingDirectory $root
    Start-Sleep -Seconds 2
}
