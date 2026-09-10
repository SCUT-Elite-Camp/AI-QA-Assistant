# AI QA Assistant - One-Click PowerShell Launcher
$Host.UI.RawUI.WindowTitle = "AI QA Assistant - One-Click Launcher"

$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_DATASETS_OFFLINE = "1"
$env:DISABLE_SYMLINKS_WARNING = "1"

$pythonPath = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $pythonPath start_project.py
