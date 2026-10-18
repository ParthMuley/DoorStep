# DOORSTEP DEMO - start the V2 agents in separate windows (Windows / PowerShell).
# Usage (repo root, .env filled in, backend running):  .\scripts\run_agents.ps1
# Until B's contract v2 routes land, run the DEV backend first:  .venv\Scripts\python scripts\dev_backend_v2.py
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$modules = @("doorstep.agents.matching", "doorstep.agents.escalation", "doorstep.agents.post_calamity",
             "doorstep.agents.calamity_checker", "doorstep.agents.coordinator")
$orgs = @("eastside_rides_demo", "neighbor_sedans_demo", "red_cross_demo", "civic_shelter_demo", "recovery_housing_demo")
foreach ($org in $orgs) {
    Start-Process -FilePath $python -ArgumentList "-m", "doorstep.agents.organization", $org -WorkingDirectory $root
    Start-Sleep -Seconds 1
}
foreach ($module in $modules) {
    Start-Process -FilePath $python -ArgumentList "-m", $module -WorkingDirectory $root
    Start-Sleep -Seconds 1
}
