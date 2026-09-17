"""Shared, result-only plotting helpers for the Transport-D paper figures."""

from __future__ import annotations

import json
import string
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import SymLogNorm, ListedColormap, BoundaryNorm
from matplotlib.patches import Rectangle
from qa_panel_alignment import require_matplotlib_panel_alignment
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MAIN_DIR = ROOT / "Figures/transport/main"
SUPP_DIR = ROOT / "Figures/transport/supplementary"
VALUES_DIR = ROOT / "Results/figures/transport"
QA_DIR = ROOT / "Results/figure_checks"
SVG_DIR = ROOT / "Figures/transport/svg"
GRID = ROOT / "Data/processed/transport/transport_grid_500m.parquet"
CITIES = ROOT / "Data/interim/aoi/gba_city_boundaries.geojson"
ANNUAL = ROOT / "Data/processed/transport/d_annual_accessibility_cell.parquet"
CONTRIBUTION = ROOT / "Data/processed/transport/d_project_attribution_cell.parquet"
MISSING_STATUS = "missing_walk_snap"

BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
RED = "#D55E00"
PURPLE = "#CC79A7"
SKY = "#56B4E9"
BLACK = "#1A1A1A"
GREY = "#767676"
LIGHT_GREY = "#D9D9D9"
DIVERGING = "RdBu_r"

mpl.rcParams.update(
    {
        "font.size": 8,
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "axes.labelsize": 8,
        "axes.titlesize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.035,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.65,
        "xtick.major.width": 0.65,
        "ytick.major.width": 0.65,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "svg.hashsalt": "transport-d-revision-20260916",
        "text.usetex": False,
        "mathtext.fontset": "dejavusans",
    }
)


def panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        0.015,
        0.985,
        label,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.5,
        fontweight="bold",
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.82, "pad": 1.4},
        zorder=30,
    )


def save_figure(fig: plt.Figure, stem: str, *, supplementary: bool = False) -> None:
    output = SUPP_DIR if supplementary else MAIN_DIR
    output.mkdir(parents=True, exist_ok=True)
    audit_alignment(fig, stem)
    svg_output = SVG_DIR / ("supplementary" if supplementary else "main")
    svg_output.mkdir(parents=True, exist_ok=True)
    fig.savefig(svg_output / f"{stem}.svg")
    fig.savefig(output / f"{stem}.pdf")
    fig.savefig(output / f"{stem}.png", dpi=300)
    plt.close(fig)


def audit_alignment(fig: plt.Figure, stem: str) -> None:
    """Physical panel check; colorbars and child inset axes are not data panels."""
    QA_DIR.mkdir(parents=True, exist_ok=True)
    options = getattr(fig, "_transport_alignment_options", {})
    fig.canvas.draw()
    require_matplotlib_panel_alignment(
        fig, json_out=QA_DIR / f"{stem}_alignment.json",
        tolerance_pt=1.5, strict=True,
        exclude_axes=[ax for ax in fig.axes if hasattr(ax, "_colorbar")], **options,
    )


def coverage_inset(ax, grid, values, spec, cities, norm):
    """Magnify the nonzero coverage extent without replacing the full-domain map."""
    active = np.isfinite(values) & (np.abs(values) > 1e-10)
    if not np.any(active):
        return
    bounds = grid.loc[active].total_bounds
    xmin, ymin, xmax, ymax = bounds + np.array([-1500, -1500, 1500, 1500])
    inset = ax.inset_axes([0.025, 0.54, 0.44, 0.43])
    inset.imshow(rasterize(grid, values, spec), origin="lower", extent=spec["extent"],
                 cmap=DIVERGING, norm=norm, interpolation="nearest", rasterized=True)
    clipped_boundaries = cities.boundary.clip((xmin, ymin, xmax, ymax))
    if not clipped_boundaries.empty:
        clipped_boundaries.plot(ax=inset, color="#888888", linewidth=0.3)
    inset.set(xlim=(xmin, xmax), ylim=(ymin, ymax), xticks=[], yticks=[])
    inset.set_aspect("equal")
    for spine in inset.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.6)
        spine.set_color("#777777")
    # The rectangle identifies the magnified area; no station symbols hide cells.
    ax.add_patch(Rectangle((xmin, ymin), xmax-xmin, ymax-ymin,
                          fill=False, ec="#777777", lw=0.6, zorder=29))
    return inset


def write_values(stem: str, payload: dict) -> None:
    VALUES_DIR.mkdir(parents=True, exist_ok=True)
    (VALUES_DIR / f"{stem}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_grid_and_boundaries(valid_only: bool = True) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    annual_ids = pd.read_parquet(
        ANNUAL, columns=["grid_id", "analysis_status"]
    ).drop_duplicates("grid_id")
    if valid_only:
        annual_ids = annual_ids.loc[annual_ids["analysis_status"].ne("missing_walk_snap")]
    grid = gpd.read_parquet(
        GRID,
        columns=["grid_id", "grid_x_index", "grid_y_index", "gba_city", "split_group", "geometry"],
    )
    grid = grid.merge(annual_ids[["grid_id"]], on="grid_id", validate="one_to_one")
    grid = gpd.GeoDataFrame(grid, geometry="geometry", crs=gpd.read_parquet(GRID).crs)
    grid = grid.sort_values("grid_id").reset_index(drop=True)
    cities = gpd.read_file(CITIES).to_crs(grid.crs)
    return grid, cities


def load_missing_origin_grid() -> gpd.GeoDataFrame:
    """Return the frozen origins excluded because no valid walking snap exists."""
    annual_ids = pd.read_parquet(
        ANNUAL, columns=["grid_id", "analysis_status"]
    ).drop_duplicates("grid_id")
    missing_ids = annual_ids.loc[
        annual_ids["analysis_status"].eq(MISSING_STATUS), ["grid_id"]
    ]
    full_grid = gpd.read_parquet(
        GRID,
        columns=["grid_id", "geometry"],
    )
    missing = full_grid.merge(missing_ids, on="grid_id", validate="one_to_one")
    return gpd.GeoDataFrame(missing, geometry="geometry", crs=full_grid.crs)


def mark_missing_origins(ax: plt.Axes, missing: gpd.GeoDataFrame) -> None:
    """Distinguish excluded origins from valid structural-zero cells."""
    if missing.empty:
        return
    centroids = missing.geometry.centroid
    ax.scatter(
        centroids.x,
        centroids.y,
        marker="x",
        s=0.65,
        linewidths=0.18,
        color="#929292",
        alpha=0.65,
        zorder=18,
        rasterized=True,
    )


def annual_level_limit(metric: str, percentile: float = 99.5) -> float:
    """One level colour limit shared by every 2017--2024 map of a metric."""
    annual = pd.read_parquet(ANNUAL, columns=["analysis_status", metric])
    values = annual.loc[
        annual["analysis_status"].ne(MISSING_STATUS), metric
    ].to_numpy(dtype=float)
    display = np.log1p(np.clip(values, 0, None))
    return float(np.percentile(display[np.isfinite(display)], percentile))


def event_code_map(frame: pd.DataFrame) -> dict[str, str]:
    """Stable short codes used where full frozen identifiers are unreadable."""
    events = (
        frame[["event_id", "year"]]
        .drop_duplicates()
        .sort_values(["year", "event_id"])
        .reset_index(drop=True)
    )
    return {
        str(row.event_id): f"P{index + 1:02d}"
        for index, row in enumerate(events.itertuples(index=False))
    }


def raster_spec(grid: pd.DataFrame) -> dict:
    min_x = int(grid["grid_x_index"].min())
    max_x = int(grid["grid_x_index"].max())
    min_y = int(grid["grid_y_index"].min())
    max_y = int(grid["grid_y_index"].max())
    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
        "shape": (max_y - min_y + 1, max_x - min_x + 1),
        "extent": (min_x * 500, (max_x + 1) * 500, min_y * 500, (max_y + 1) * 500),
    }


def rasterize(grid: pd.DataFrame, values: pd.Series | np.ndarray, spec: dict | None = None) -> np.ndarray:
    spec = spec or raster_spec(grid)
    array = np.full(spec["shape"], np.nan, dtype=float)
    x = grid["grid_x_index"].to_numpy(dtype=int) - spec["min_x"]
    y = grid["grid_y_index"].to_numpy(dtype=int) - spec["min_y"]
    array[y, x] = np.asarray(values, dtype=float)
    return array


def values_on_grid(grid: pd.DataFrame, frame: pd.DataFrame, value_column: str) -> np.ndarray:
    indexed = frame.set_index("grid_id")[value_column]
    return indexed.reindex(grid["grid_id"]).to_numpy(dtype=float)


def format_map_axis(
    ax: plt.Axes,
    cities: gpd.GeoDataFrame,
    spec: dict,
    *,
    city_labels: bool = False,
    boundary_color: str = "#303030",
) -> None:
    target = cities.loc[cities["gba_city"].isin(["Guangzhou", "Foshan", "Dongguan"])]
    target.boundary.plot(ax=ax, color=boundary_color, linewidth=0.45, zorder=15)
    ax.set_xlim(spec["extent"][0], spec["extent"][1])
    ax.set_ylim(spec["extent"][2], spec["extent"][3])
    ax.set_aspect("equal")
    ax.set_axis_off()
    if city_labels:
        labels = {"Guangzhou": "GZ", "Foshan": "FS", "Dongguan": "DG"}
        for row in target.itertuples(index=False):
            point = row.geometry.representative_point()
            ax.text(
                point.x,
                point.y,
                labels[row.gba_city],
                ha="center",
                va="center",
                fontsize=8,
                color="#303030",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 1.0, "pad": 0.8},
                zorder=28,
            )


def signed_norm(values: np.ndarray, percentile: float = 99.5) -> tuple[SymLogNorm, float, float]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    nonzero = np.abs(finite[np.abs(finite) > 1e-14])
    if not len(nonzero):
        return SymLogNorm(linthresh=1.0, vmin=-1.0, vmax=1.0, base=10), 1.0, 1.0
    limit = float(np.percentile(nonzero, percentile))
    limit = max(limit, float(nonzero.min()))
    linthresh = max(float(np.percentile(nonzero, 15)) * 0.5, limit * 1e-5)
    return SymLogNorm(linthresh=linthresh, vmin=-limit, vmax=limit, base=10), limit, linthresh


def signed_colorbar_ticks(cbar, norm) -> None:
    """Five equally spaced display ticks; leave the signed normalization intact."""
    ticks = np.asarray(norm.inverse(np.linspace(0, 1, 5)), dtype=float)
    ticks[2] = 0.0
    def label(v):
        if abs(v) >= 1e6:
            return f"{v/1e6:.2g}M"
        if abs(v) >= 1e3:
            return f"{v/1e3:.3g}k"
        return f"{v:.2g}"
    cbar.set_ticks(ticks)
    cbar.set_ticklabels([label(v) for v in ticks])
    cbar.minorticks_off()


def add_scale_bar(ax: plt.Axes, spec: dict, length_km: int = 25) -> None:
    xmin, xmax, ymin, ymax = spec["extent"]
    x0 = xmin + 0.055 * (xmax - xmin)
    y0 = ymin + 0.05 * (ymax - ymin)
    length = length_km * 1000
    ax.plot([x0, x0 + length], [y0, y0], color=BLACK, lw=1.1, zorder=25)
    ax.text(x0 + length / 2, y0 + 0.012 * (ymax - ymin), f"{length_km} km", ha="center", va="bottom", fontsize=7.5, bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.6, "alpha": 1.0}, zorder=25)


def add_north_arrow(ax: plt.Axes) -> None:
    """Add a compact north-up orientation cue in axes coordinates."""
    ax.annotate(
        "",
        xy=(0.945, 0.97),
        xytext=(0.945, 0.86),
        xycoords="axes fraction",
        textcoords="axes fraction",
        ha="center",
        va="bottom",
        fontsize=7.5,
        fontweight="bold",
        arrowprops={"arrowstyle": "-|>", "color": BLACK, "lw": 0.8},
        zorder=30,
    )
    ax.text(0.945, 0.75, "N", transform=ax.transAxes, ha="center", va="center",
            fontsize=7.5, fontweight="bold", zorder=30)


def event_topology_change(builder, event_id: str, target_crs) -> dict[str, gpd.GeoDataFrame]:
    """Return added/removed track and active-stop geometry for one frozen package.

    The comparison is the event singleton versus the event-year empty coalition.
    It is a topology-only operation and does not evaluate accessibility outcomes.
    """
    package = builder.packages[event_id]
    year = int(package["year"])
    empty = builder.build(year, set())
    singleton = builder.build(year, {event_id})
    edge_key = ["sequence_id", "route_identity", "component_id", "from_order", "to_order"]
    stop_key = ["sequence_id", "route_identity", "stop_order"]

    empty_edge_keys = set(map(tuple, empty["edges"][edge_key].itertuples(index=False, name=None)))
    singleton_edge_keys = set(
        map(tuple, singleton["edges"][edge_key].itertuples(index=False, name=None))
    )
    empty_stop = empty["stops"].loc[empty["stops"]["passenger_service_active"]]
    singleton_stop = singleton["stops"].loc[
        singleton["stops"]["passenger_service_active"]
    ]
    empty_stop_keys = set(map(tuple, empty_stop[stop_key].itertuples(index=False, name=None)))
    singleton_stop_keys = set(
        map(tuple, singleton_stop[stop_key].itertuples(index=False, name=None))
    )

    def select(frame: gpd.GeoDataFrame, keys: list[str], wanted: set[tuple]) -> gpd.GeoDataFrame:
        mask = [tuple(row) in wanted for row in frame[keys].itertuples(index=False, name=None)]
        return frame.loc[mask].to_crs(target_crs)

    return {
        "added_edges": select(singleton["edges"], edge_key, singleton_edge_keys - empty_edge_keys),
        "removed_edges": select(empty["edges"], edge_key, empty_edge_keys - singleton_edge_keys),
        "added_stops": select(singleton_stop, stop_key, singleton_stop_keys - empty_stop_keys),
        "removed_stops": select(empty_stop, stop_key, empty_stop_keys - singleton_stop_keys),
    }


def plot_event_topology_change(
    ax: plt.Axes,
    change: dict[str, gpd.GeoDataFrame],
    *,
    linewidth: float = 0.5,
    show_stops: bool = True,
) -> None:
    """Overlay event track/station actions with redundant line and point symbols."""
    if not change["added_edges"].empty:
        change["added_edges"].plot(
            ax=ax, color="#666666", linewidth=linewidth, alpha=0.65, linestyle="solid", zorder=23
        )
    if not change["removed_edges"].empty:
        change["removed_edges"].plot(
            ax=ax, color=RED, linewidth=linewidth, linestyle=(0, (3, 1.5)), zorder=23
        )
    if show_stops and not change["added_stops"].empty:
        change["added_stops"].plot(
            ax=ax,
            color="white",
            edgecolor="#111111",
            marker="^",
            markersize=5,
            linewidth=0.4,
            alpha=0.65,
            zorder=24,
        )
    if show_stops and not change["removed_stops"].empty:
        change["removed_stops"].plot(
            ax=ax, color=RED, marker="x", markersize=6, linewidth=0.5, zorder=24
        )


def event_topology_legend_handles() -> list[Line2D]:
    return [
        Line2D([0], [0], color="#666666", lw=0.8, label="Added/activated track"),
        Line2D([0], [0], color=RED, lw=0.8, linestyle=(0, (3, 1.5)), label="Removed/suspended track"),
        Line2D([0], [0], marker="^", color="#111111", markerfacecolor="white", lw=0, label="Activated station"),
        Line2D([0], [0], marker="x", color=RED, lw=0, label="Closed station"),
        Line2D([0], [0], marker="x", color="#4D4D4D", lw=0, label="Excluded missing snap"),
        Line2D([0], [0], color="#303030", lw=0.65, label="Municipal boundary"),
    ]


def alphabet_labels(n: int) -> list[str]:
    labels = list(string.ascii_lowercase)
    if n > len(labels):
        labels.extend(["a" + letter for letter in string.ascii_lowercase[: n - len(labels)]])
    return labels[:n]


def plot_annual_atlas(metric: str, stem: str, colour_label: str) -> None:
    grid, cities = load_grid_and_boundaries(valid_only=True)
    missing = load_missing_origin_grid()
    spec = raster_spec(grid)
    annual = pd.read_parquet(
        ANNUAL, columns=["grid_id", "analysis_status", "year", metric]
    )
    annual = annual.loc[annual["analysis_status"].ne("missing_walk_snap")]
    years = list(range(2017, 2025))
    all_values = annual[metric].to_numpy(dtype=float)
    if metric in {"total_opportunity", "cross_city_opportunity"}:
        vmax = annual_level_limit(metric)
        cmap = "viridis"
    else:
        vmax = 1.0
        cmap = ListedColormap(["#E8EEF1", BLUE])
    fig, axes = plt.subplots(2, 4, figsize=(7.3, 4.8), constrained_layout=True)
    labels = alphabet_labels(8)
    image = None
    for index, (ax, year) in enumerate(zip(axes.flat, years)):
        frame = annual.loc[annual["year"].eq(year), ["grid_id", metric]]
        values = values_on_grid(grid, frame, metric)
        if metric in {"total_opportunity", "cross_city_opportunity"}:
            values = np.log1p(np.clip(values, 0, None))
        image = ax.imshow(
            rasterize(grid, values, spec),
            origin="lower",
            extent=spec["extent"],
            cmap=cmap,
            vmin=0,
            vmax=vmax,
            interpolation="nearest",
            rasterized=True,
        )
        format_map_axis(ax, cities, spec, city_labels=(index == 0))
        if index == 0:
            add_scale_bar(ax, spec)
            add_north_arrow(ax)
        mark_missing_origins(ax, missing)
        panel_label(ax, labels[index])
        ax.text(0.5, -0.025, str(year), transform=ax.transAxes, ha="center", va="top", fontsize=8)
    cbar = fig.colorbar(image, ax=axes.ravel().tolist(), fraction=0.018, pad=0.015)
    cbar.set_label(colour_label)
    if metric == "coverage":
        cbar.set_ticks([0.25, 0.75])
        cbar.set_ticklabels(["Uncovered", "Covered"])
        cbar.ax.tick_params(length=0)
    save_figure(fig, stem, supplementary=True)
    write_values(
        stem,
        {
            "metric": metric,
            "years": years,
            "valid_origin_count": int(len(grid)),
            "missing_walk_snap_count": int(len(missing)),
            "missing_origin_display": "grey x; excluded from summaries",
            "structural_zero_display": "valid zero retained in the colour scale",
            "display_transform": "log1p" if metric != "coverage" else "none",
            "colour_upper_limit": vmax,
            "colour_limit_percentile": 99.5 if metric != "coverage" else None,
        },
    )


def plot_project_atlas(metric: str, stem: str, colour_label: str) -> None:
    from Codes.analysis.transport_event_state import FrozenEventStateBuilder

    grid, cities = load_grid_and_boundaries(valid_only=True)
    missing = load_missing_origin_grid()
    spec = raster_spec(grid)
    data = pd.read_parquet(
        CONTRIBUTION,
        columns=["grid_id", "analysis_status", "year", "event_id", "event_label", metric],
    )
    data = data.loc[data["analysis_status"].ne("missing_walk_snap")]
    events = (
        data[["event_id", "year", "event_label"]]
        .drop_duplicates()
        .sort_values(["year", "event_id"])
        .reset_index(drop=True)
    )
    codes = event_code_map(events)
    state_builder = FrozenEventStateBuilder()
    norm, limit, linthresh = signed_norm(data[metric].to_numpy(dtype=float), percentile=99.5)
    fig, axes = plt.subplots(6, 5, figsize=(7.3, 8.4), constrained_layout=True)
    labels = alphabet_labels(len(events))
    image = None
    panel_map = []
    for index, ax in enumerate(axes.flat):
        if index >= len(events):
            ax.set_visible(False)
            continue
        event = events.iloc[index]
        frame = data.loc[data["event_id"].eq(event["event_id"]), ["grid_id", metric]]
        values = values_on_grid(grid, frame, metric)
        image = ax.imshow(
            rasterize(grid, values, spec),
            origin="lower",
            extent=spec["extent"],
            cmap=DIVERGING,
            norm=norm,
            interpolation="nearest",
            rasterized=True,
        )
        format_map_axis(ax, cities, spec, city_labels=(index == 0))
        change = event_topology_change(state_builder, str(event["event_id"]), grid.crs)
        plot_event_topology_change(ax, change, linewidth=0.35, show_stops=(metric != "coverage_contribution"))
        if index == 0:
            add_scale_bar(ax, spec)
            add_north_arrow(ax)
        mark_missing_origins(ax, missing)
        panel_label(ax, labels[index])
        ax.text(
            0.5,
            -0.018,
            codes[str(event["event_id"])],
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=8.0,
        )
        panel_map.append(
            {
                "panel": labels[index],
                "event_id": event["event_id"],
                "event_code": codes[str(event["event_id"])],
                "year": int(event["year"]),
                "event_label": event["event_label"],
            }
        )
    cbar = fig.colorbar(image, ax=axes.ravel().tolist(), fraction=0.018, pad=0.012)
    signed_colorbar_ticks(cbar, norm)
    cbar.set_label(colour_label)
    fig.legend(
        handles=event_topology_legend_handles(),
        loc="outside lower center",
        ncol=3,
        frameon=False,
        fontsize=6.2,
    )
    save_figure(fig, stem, supplementary=True)
    write_values(
        stem,
        {
            "metric": metric,
            "event_count": int(len(events)),
            "valid_origin_count": int(len(grid)),
            "missing_walk_snap_count": int(len(missing)),
            "missing_origin_display": "grey x; excluded from summaries",
            "zero_contribution_display": "valid zero retained near the neutral colour",
            "normalization": "symmetric logarithmic",
            "absolute_colour_limit": limit,
            "linear_threshold": linthresh,
            "colour_limit_percentile_of_nonzero_absolute_values": 99.5,
            "panels": panel_map,
        },
    )
