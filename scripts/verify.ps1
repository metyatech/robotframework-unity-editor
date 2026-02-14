Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

python -m ruff format --check .
python -m ruff check .
python -m pyright
python -m pytest
python -m pip_audit -r requirements-audit.txt
