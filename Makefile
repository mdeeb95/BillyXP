# XPWhat build targets (DESIGN §4). On Windows without `make`, use ./make.ps1 <target>.
# All targets run through uv so the pinned dependency set is used.

.PHONY: etl validate viz backtest verify-freeze test typecheck all

etl:            ## raw dump -> data/compiled/world.sqlite + validation report
	uv run python -m etl.build

validate:       ## check compiled DB against M0 acceptance criteria
	uv run python -m etl.validate

viz:            ## Teldrassil spawn/POI map -> out/
	uv run python -m viz.spawn_map

backtest:       ## (stub until M1+) route backtest
	uv run python -m eval.backtest

verify-freeze:  ## while m1-freeze is active: clean tree + route sha + reproduce PREDICTIONS.md
	uv run python -m eval.verify_freeze

test:
	uv run pytest

typecheck:
	uv run pyright

all: etl validate viz
