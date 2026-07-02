"""Plot the Teldrassil spawn/POI map from data/compiled/world.sqlite -> out/.

Spawns colored by kind; quest-giver / turn-in POIs highlighted and giver POIs labeled by
quest. This plot is the visual check for the M0 bounding box (DESIGN §12 acceptance) and
the tool used to iterate the box (etl/NOTES.md §2).

Run:  make viz   (or  uv run python -m viz.spawn_map)

Note on axes: vmangos world coords are (x north/south, y east/west). We plot y on the
horizontal axis and x on the vertical so the map reads in the usual N-up orientation.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "compiled" / "world.sqlite"
OUT = ROOT / "out" / "teldrassil_spawns.png"


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"viz: {DB} not found - run `make etl` first.")
    c = sqlite3.connect(DB)

    creatures = c.execute("SELECT y, x FROM spawns WHERE kind='CREATURE'").fetchall()
    objects = c.execute("SELECT y, x FROM spawns WHERE kind='OBJECT'").fetchall()

    def poi(kind: str) -> list[tuple[float, float]]:
        return [(float(r[0]), float(r[1]))
                for r in c.execute("SELECT y, x FROM pois WHERE kind=?", (kind,))]

    givers = c.execute(
        "SELECT p.y, p.x, q.name FROM pois p JOIN quests q ON q.id=p.ref_id "
        "WHERE p.kind='GIVER'"
    ).fetchall()
    turnins = poi("TURNIN")
    trainers = poi("TRAINER")
    vendors = poi("VENDOR")
    hearths = poi("HEARTH")

    box_row = c.execute("SELECT value FROM meta WHERE key='bounding_box'").fetchone()
    box = json.loads(box_row[0]) if box_row else None

    fig, ax = plt.subplots(figsize=(13, 13))

    if creatures:
        cy, cx = zip(*creatures)
        ax.scatter(cy, cx, s=5, c="#7aa6c2", alpha=0.45, label=f"creature spawns ({len(creatures)})",
                   edgecolors="none")
    if objects:
        oy, ox = zip(*objects)
        ax.scatter(oy, ox, s=5, c="#b6a06a", alpha=0.35, label=f"object spawns ({len(objects)})",
                   marker="s", edgecolors="none")

    def scatter_poi(pts: list[tuple[float, float]], color: str, marker: str, label: str, size: int) -> None:
        if pts:
            py, px = zip(*pts)
            ax.scatter(py, px, s=size, c=color, marker=marker, label=f"{label} ({len(pts)})",
                       edgecolors="black", linewidths=0.4, zorder=5)

    scatter_poi(trainers, "#5aa469", "^", "trainer", 70)
    scatter_poi(vendors, "#c9772e", "v", "vendor", 55)
    scatter_poi(hearths, "#8e44ad", "*", "innkeeper/hearth", 220)
    scatter_poi(turnins, "#d94f4f", "D", "quest turn-in", 55)

    if givers:
        gy = [float(r[0]) for r in givers]
        gx = [float(r[1]) for r in givers]
        ax.scatter(gy, gx, s=90, c="#f2c14e", marker="*", edgecolors="black",
                   linewidths=0.5, label=f"quest giver ({len(givers)})", zorder=6)
        seen: set[str] = set()
        for y, x, name in givers:
            if name in seen:
                continue
            seen.add(str(name))
            ax.annotate(str(name), (float(y), float(x)), fontsize=6, xytext=(3, 3),
                        textcoords="offset points", zorder=7)

    off_plot = 0
    if box is not None:
        pad = 150.0
        ax.set_xlim(box["y0"] - pad, box["y1"] + pad)
        ax.set_ylim(box["x0"] - pad, box["x1"] + pad)
        # count out-of-zone POIs that fall outside the plotted box
        off_plot = c.execute(
            "SELECT COUNT(*) FROM pois WHERE x < ? OR x > ? OR y < ? OR y > ?",
            (box["x0"], box["x1"], box["y0"], box["y1"]),
        ).fetchone()[0]

    subtitle = f" ({off_plot} out-of-zone POIs off-plot)" if off_plot else ""
    ax.set_title(f"Teldrassil - compiled spawns & POIs (M0){subtitle}")
    ax.set_xlabel("world Y (east <-> west)")
    ax.set_ylabel("world X (south <-> north)")
    ax.set_aspect("equal")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.2)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT, dpi=130)
    print(f"viz: wrote {OUT} "
          f"({len(creatures)} creature + {len(objects)} object spawns, "
          f"{len(givers)} givers, {len(turnins)} turn-ins)")
    c.close()


if __name__ == "__main__":
    main()
