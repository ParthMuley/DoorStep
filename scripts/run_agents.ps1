# DOORSTEP DEMO - start the V2 agents in separate windows (Windows / PowerShell).
# Usage (repo root, .env filled in, backend running):  .\scripts\run_agents.ps1
# Until B's contract v2 routes land, run the DEV backend first:  .venv\Scripts\python scripts\dev_backend_v2.py
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$modules = @("doorstep.agents.volunteer_network", "doorstep.agents.matching", "doorstep.agents.escalation",
             "doorstep.agents.post_calamity", "doorstep.agents.calamity_checker", "doorstep.agents.coordinator")
foreach ($module in $modules) {
    Start-Process -FilePath $python -ArgumentList "-m", $module -WorkingDirectory $root
    Start-Sleep -Seconds 1
}
