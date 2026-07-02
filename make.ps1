# Windows shim for the Makefile targets (no `make` on this box).
# Usage:  ./make.ps1 etl      ./make.ps1 validate      ./make.ps1 viz
param([Parameter(Mandatory = $true)][string]$Target)

switch ($Target) {
    "etl"       { uv run python -m etl.build }
    "validate"  { uv run python -m etl.validate }
    "viz"       { uv run python -m viz.spawn_map }
    "backtest"  { uv run python -m eval.backtest }
    "verify-freeze" { uv run python -m eval.verify_freeze }
    "test"      { uv run pytest }
    "typecheck" { uv run pyright }
    "all"       { uv run python -m etl.build; uv run python -m etl.validate; uv run python -m viz.spawn_map }
    default     { Write-Error "Unknown target: $Target (etl|validate|viz|backtest|verify-freeze|test|typecheck|all)"; exit 1 }
}
