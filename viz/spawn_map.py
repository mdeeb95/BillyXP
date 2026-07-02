"""Plot the Teldrassil spawn/POI map from data/compiled/world.sqlite -> out/.

Spawns colored by kind; quest-giver / turn-in POIs highlighted and giver POIs labeled by
quest; objective `areas` overlaid as centroid+radius circles. This plot is the visual check
for the M0 bounding box (DESIGN §12 acceptance) and the tool used to iterate the box
(etl/NOTES.md §2).

Run:  make viz   (or  uv run python -m viz.spawn_map)

Orientation (M1 step 0c) — derived empirically from three known landmarks, not assumed:
vmangos world coords are **+X = north, +Y = west**. Verified against the compiled data:
  - Rut'theran Village (harbor, S below the tree) has the **min world X** → southernmost;
  - Shadowglen (NE) has the **max world X** and **min world Y** → north & east;
  - Darnassus (W) has the **max world Y** → westernmost.
So a north-up, east-right map is  plot_x = -world_y  (east to the right),  plot_y = world_x
(north up). The previous version plotted +Y rightward, putting west on the right — mirrored
east/west. `assert_orientation()` re-checks the three landmarks every run so this is verified,
not hardcoded.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "compiled" / "world.sqlite"
OUT = ROOT / "out" / "teldrassil_spawns.png"


def px(world_y: float) -> float:
    """World Y -> plot horizontal (east to the right; +Y is west, so negate)."""
    return -world_y


def py(world_x: float) -> float:
    """World X -> plot vertical (north up; +X is already north)."""
    return world_x


def assert_orientation(c: sqlite3.Connection) -> str:
    """Re-derive N-up orientation from landmarks; return a status line (raises if inconsistent)."""

    def mean_xy(sql: str, params: tuple[int, ...] = ()) -> tuple[float, float] | None:
        rows = c.execute(sql, params).fetchall()
        if not rows:
            return None
        return (sum(r[0] for r in rows) / len(rows), sum(r[1] for r in rows) / len(rows))

    shadowglen = mean_xy(
        "SELECT p.x, p.y FROM pois p JOIN quests q ON q.id=p.ref_id "
        "WHERE p.kind='GIVER' AND q.zone_or_sort=188"
    )
    darnassus = mean_xy(
        "SELECT x, y FROM pois WHERE kind='TURNIN' AND ref_id IN (487, 940, 935)"
    )
    ruttheran = mean_xy(
        "SELECT p.x, p.y FROM pois p JOIN quests q ON q.id=p.ref_id WHERE q.zone_or_sort=702"
    )
    if not (shadowglen and darnassus and ruttheran):
        return "orientation: landmarks missing — skipped check"
    # World +X = north: Shadowglen (N) > Darnassus > Rut'theran (S).
    assert shadowglen[0] > ruttheran[0], "landmark check: Shadowglen not north of Rut'theran"
    assert darnassus[0] > ruttheran[0], "landmark check: Darnassus not north of Rut'theran"
    # World +Y = west: Darnassus (W) has the largest Y; Shadowglen (E) the smallest.
    assert darnassus[1] > shadowglen[1], "landmark check: Darnassus not west of Shadowglen"
    return ("orientation OK: Shadowglen NE, Darnassus W, Rut'theran S "
            "(world +X=north, +Y=west; plot_x=-Y, plot_y=X)")


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"viz: {DB} not found - run `make etl` first.")
    c = sqlite3.connect(DB)

    status = assert_orientation(c)
    print(f"viz: {status}")

    creatures = c.execute("SELECT x, y FROM spawns WHERE kind='CREATURE'").fetchall()
    objects = c.execute("SELECT x, y FROM spawns WHERE kind='OBJECT'").fetchall()

    def poi(kind: str) -> list[tuple[float, float]]:
        return [(float(r[0]), float(r[1]))
                for r in c.execute("SELECT x, y FROM pois WHERE kind=?", (kind,))]

    givers = c.execute(
        "SELECT p.x, p.y, q.name FROM pois p JOIN quests q ON q.id=p.ref_id "
        "WHERE p.kind='GIVER'"
    ).fetchall()
    turnins = poi("TURNIN")
    trainers = poi("TRAINER")
    vendors = poi("VENDOR")
    hearths = poi("HEARTH")
    areas = c.execute("SELECT centroid_x, centroid_y, radius FROM areas").fetchall()

    box_row = c.execute("SELECT value FROM meta WHERE key='bounding_box'").fetchone()
    box = json.loads(box_row[0]) if box_row else None

    fig, ax = plt.subplots(figsize=(13, 13))

    # Spawns (transform world (x,y) -> plot (px(y), py(x))).
    if creatures:
        ax.scatter([px(r[1]) for r in creatures], [py(r[0]) for r in creatures],
                   s=5, c="#7aa6c2", alpha=0.45, edgecolors="none",
                   label=f"creature spawns ({len(creatures)})")
    if objects:
        ax.scatter([px(r[1]) for r in objects], [py(r[0]) for r in objects],
                   s=5, c="#b6a06a", alpha=0.35, marker="s", edgecolors="none",
                   label=f"object spawns ({len(objects)})")

    # Objective areas as centroid+radius circles (step 0c).
    for i, (cx, cy, radius) in enumerate(areas):
        ax.add_patch(Circle((px(float(cy)), py(float(cx))), float(radius), fill=False,
                            edgecolor="#3b7a57", linewidth=0.7, alpha=0.5, zorder=2,
                            label="objective area" if i == 0 else None))

    def scatter_poi(pts: list[tuple[float, float]], color: str, marker: str, label: str, size: int) -> None:
        if pts:
            ax.scatter([px(p[1]) for p in pts], [py(p[0]) for p in pts], s=size, c=color,
                       marker=marker, edgecolors="black", linewidths=0.4, zorder=5,
                       label=f"{label} ({len(pts)})")

    scatter_poi(trainers, "#5aa469", "^", "trainer", 70)
    scatter_poi(vendors, "#c9772e", "v", "vendor", 55)
    scatter_poi(hearths, "#8e44ad", "*", "innkeeper/hearth", 220)
    scatter_poi(turnins, "#d94f4f", "D", "quest turn-in", 55)

    if givers:
        ax.scatter([px(float(r[1])) for r in givers], [py(float(r[0])) for r in givers],
                   s=90, c="#f2c14e", marker="*", edgecolors="black", linewidths=0.5,
                   label=f"quest giver ({len(givers)})", zorder=6)
        seen: set[str] = set()
        for wx, wy, name in givers:
            if name in seen:
                continue
            seen.add(str(name))
            ax.annotate(str(name), (px(float(wy)), py(float(wx))), fontsize=6, xytext=(3, 3),
                        textcoords="offset points", zorder=7)

    off_plot = 0
    if box is not None:
        pad = 150.0
        # Box corners in plot space: x from -y, y from world x.
        ax.set_xlim(px(box["y1"]) - pad, px(box["y0"]) + pad)  # east (-y1) .. west (-y0)
        ax.set_ylim(py(box["x0"]) - pad, py(box["x1"]) + pad)
        off_plot = c.execute(
            "SELECT COUNT(*) FROM pois WHERE x < ? OR x > ? OR y < ? OR y > ?",
            (box["x0"], box["x1"], box["y0"], box["y1"]),
        ).fetchone()[0]

    subtitle = f" ({off_plot} out-of-zone POIs off-plot)" if off_plot else ""
    ax.set_title(f"Teldrassil - compiled spawns, POIs & areas (M1){subtitle}")
    ax.set_xlabel("east  <-  ->  west   (plot_x = -world_y)")
    ax.set_ylabel("south  <-  ->  north   (plot_y = world_x)")
    ax.set_aspect("equal")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.2)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT, dpi=130)
    print(f"viz: wrote {OUT} "
          f"({len(creatures)} creature + {len(objects)} object spawns, "
          f"{len(givers)} givers, {len(turnins)} turn-ins, {len(areas)} area circles)")
    c.close()


if __name__ == "__main__":
    main()
