#!/usr/bin/env python3
"""Run the frozen nested 1 km aggregation sensitivity for D cell outputs."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import spearmanr


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "Codes/config/transport_d_1km_aggregation_sensitivity.json"
GRID500 = ROOT / "Data/processed/transport/transport_grid_500m.parquet"
GRID1000 = ROOT / "Data/processed/transport/transport_grid_1000m.parquet"
ANNUAL500 = ROOT / "Data/processed/transport/d_annual_accessibility_cell.parquet"
PROJECT500 = ROOT / "Data/processed/transport/d_project_attribution_cell.parquet"
PRIMARY_SUMMARY = ROOT / "Results/tables/transport_d_project_summary.csv"
ANNUAL1000 = ROOT / "Data/processed/transport/d_annual_accessibility_1km_aggregation.parquet"
PROJECT1000 = ROOT / "Data/processed/transport/d_project_attribution_1km_aggregation.parquet"
SUMMARY1000 = ROOT / "Results/tables/transport_d_project_summary_1km.csv"
COMPARISON = ROOT / "Results/tables/transport_d_500m_1km_comparison.csv"
AUDIT = ROOT / "Results/pilots/transport_d_1km_aggregation_sensitivity_audit.json"
REPORT = ROOT / "Results/TRANSPORT_D_1KM_AGGREGATION_SENSITIVITY.md"

ANNUAL_METRICS = ["total_opportunity", "cross_city_opportunity", "coverage"]
PROJECT_METRICS = [f"{metric}_contribution" for metric in ANNUAL_METRICS]
TOLERANCE = 1e-10


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def complete_parent_mapping() -> pd.DataFrame:
    cities = {"Guangzhou", "Foshan", "Dongguan"}
    g500 = gpd.read_parquet(GRID500)[
        ["grid_id", "parent_1km_id", "gba_city", "analysis_eligible"]
    ]
    g500 = g500.loc[g500["analysis_eligible"] & g500["gba_city"].isin(cities)]
    g1000 = gpd.read_parquet(GRID1000)[
        ["grid_id", "gba_city", "analysis_eligible"]
    ].rename(columns={"grid_id": "parent_1km_id", "gba_city": "parent_city"})
    g1000 = g1000.loc[
        g1000["analysis_eligible"] & g1000["parent_city"].isin(cities)
    ]
    mapping = g500.merge(g1000, on="parent_1km_id", validate="many_to_one")
    counts = mapping.groupby("parent_1km_id").agg(
        child_count=("grid_id", "size"),
        child_city_count=("gba_city", "nunique"),
        child_city=("gba_city", "first"),
        parent_city=("parent_city", "first"),
    )
    complete = counts.loc[
        counts["child_count"].eq(4)
        & counts["child_city_count"].eq(1)
        & counts["child_city"].eq(counts["parent_city"])
    ].index
    return mapping.loc[mapping["parent_1km_id"].isin(complete), [
        "grid_id", "parent_1km_id", "gba_city"
    ]].copy()


def weighted_aggregate(
    data: pd.DataFrame,
    group_columns: list[str],
    metric_columns: list[str],
) -> pd.DataFrame:
    valid = data.loc[data["analysis_status"].ne("missing_walk_snap")].copy()
    for metric in metric_columns:
        valid[f"__pop_{metric}"] = valid[metric] * valid["population_weight"]
        valid[f"__area_{metric}"] = valid[metric] * valid["area_weight_m2"]
    aggregations: dict[str, tuple[str, str]] = {
        "population_weight": ("population_weight", "sum"),
        "area_weight_m2": ("area_weight_m2", "sum"),
        "source_500m_cells": ("grid_id", "nunique"),
    }
    for metric in metric_columns:
        aggregations[f"__pop_{metric}"] = (f"__pop_{metric}", "sum")
        aggregations[f"__area_{metric}"] = (f"__area_{metric}", "sum")
    output = valid.groupby(group_columns, sort=False).agg(**aggregations).reset_index()
    for metric in metric_columns:
        output[metric] = output[f"__pop_{metric}"] / output["population_weight"]
        output[f"area_weighted_{metric}"] = (
            output[f"__area_{metric}"] / output["area_weight_m2"]
        )
        output = output.drop(columns=[f"__pop_{metric}", f"__area_{metric}"])
    return output


def project_summary(frame: pd.DataFrame) -> pd.DataFrame:
    city_rows: list[dict] = []
    keys = ["event_id", "year", "event_label", "city"]
    for key, group in frame.groupby(keys, sort=False):
        event_id, year, label, city = key
        pop = float(group["population_weight"].sum())
        area = float(group["area_weight_m2"].sum())
        record = {
            "event_id": event_id,
            "year": int(year),
            "event_label": label,
            "geography": city,
            "population_denominator": pop,
            "area_denominator_m2": area,
            "parent_1km_cells": int(group["parent_1km_id"].nunique()),
        }
        for metric in PROJECT_METRICS:
            record[f"population_weighted_{metric}"] = float(
                (group[metric] * group["population_weight"]).sum() / pop
            )
            record[f"area_weighted_{metric}"] = float(
                (group[f"area_weighted_{metric}"] * group["area_weight_m2"]).sum()
                / area
            )
        city_rows.append(record)
    city = pd.DataFrame(city_rows)
    summary_rows: list[dict] = []
    value_columns = [
        column
        for column in city.columns
        if column.startswith("population_weighted_")
        or column.startswith("area_weighted_")
    ]
    for (event_id, year, label), group in city.groupby(
        ["event_id", "year", "event_label"], sort=False
    ):
        if group["geography"].nunique() != 3:
            raise RuntimeError(f"missing D city in 1 km summary for {event_id}")
        record = {
            "event_id": event_id,
            "year": int(year),
            "event_label": label,
            "geography": "D_equal_city",
            "cities": 3,
            "parent_1km_cells": int(group["parent_1km_cells"].sum()),
        }
        for column in value_columns:
            record[column] = float(group[column].mean())
        summary_rows.append(record)
    return pd.DataFrame(summary_rows)


def selected_child_summary(frame: pd.DataFrame) -> pd.DataFrame:
    # Each source row is already one 500 m cell, so a per-cell groupby would
    # only reproduce the same 1.38 million rows.  Reuse the summary routine
    # directly on the retained support and expose the raw cell metric as its
    # identical area-weighted value.
    selected = frame.loc[
        frame["analysis_status"].ne("missing_walk_snap")
    ].copy()
    selected["parent_1km_id"] = selected["grid_id"]
    for metric in PROJECT_METRICS:
        selected[f"area_weighted_{metric}"] = selected[metric]
    return project_summary(selected)


def sign(value: float) -> int:
    if value > TOLERANCE:
        return 1
    if value < -TOLERANCE:
        return -1
    return 0


def comparison_table(primary: pd.DataFrame, sensitivity: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    merged = primary.merge(
        sensitivity,
        on=["event_id", "year", "event_label"],
        suffixes=("_500m", "_1km"),
        validate="one_to_one",
    )
    rows: list[pd.DataFrame] = []
    stability: dict[str, dict] = {}
    top_n = math.ceil(len(merged) / 4)
    for metric in PROJECT_METRICS:
        column = f"population_weighted_{metric}"
        first = merged[f"{column}_500m"]
        second = merged[f"{column}_1km"]
        rho = float(spearmanr(first, second).statistic)
        first_top = set(merged.nlargest(top_n, f"{column}_500m")["event_id"])
        second_top = set(merged.nlargest(top_n, f"{column}_1km")["event_id"])
        overlap = len(first_top & second_top) / top_n
        sign_agreement = float(
            np.mean([sign(a) == sign(b) for a, b in zip(first, second)])
        )
        ratio = float(second.sum() / first.sum()) if abs(first.sum()) > TOLERANCE else np.nan
        stability[metric] = {
            "spearman": rho,
            "top_quartile_n": top_n,
            "top_quartile_overlap": overlap,
            "sign_agreement": sign_agreement,
            "sum_1km_to_500m_ratio": ratio,
        }
        rows.append(
            pd.DataFrame(
                {
                    "event_id": merged["event_id"],
                    "year": merged["year"],
                    "event_label": merged["event_label"],
                    "metric": metric,
                    "value_500m_full_support": first,
                    "value_1km_complete_parent_support": second,
                    "difference": second - first,
                    "sign_500m": [sign(value) for value in first],
                    "sign_1km": [sign(value) for value in second],
                }
            )
        )
    return pd.concat(rows, ignore_index=True), stability


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    mapping = complete_parent_mapping()
    annual500 = pd.read_parquet(ANNUAL500).merge(
        mapping, on="grid_id", how="inner", validate="many_to_one"
    ).rename(columns={"gba_city": "mapped_city"})
    project500 = pd.read_parquet(PROJECT500).merge(
        mapping, on="grid_id", how="inner", validate="many_to_one"
    ).rename(columns={"gba_city": "mapped_city"})
    if not annual500["city"].eq(annual500["mapped_city"]).all() or not project500[
        "city"
    ].eq(project500["mapped_city"]).all():
        raise RuntimeError("parent mapping city mismatch")

    annual1000 = weighted_aggregate(
        annual500,
        ["year", "city", "parent_1km_id"],
        ANNUAL_METRICS,
    )
    project1000 = weighted_aggregate(
        project500,
        ["event_id", "year", "event_label", "city", "parent_1km_id"],
        PROJECT_METRICS,
    )
    summary1000 = project_summary(project1000)
    selected500 = selected_child_summary(project500)
    internal_columns = [f"population_weighted_{metric}" for metric in PROJECT_METRICS]
    internal = selected500.merge(
        summary1000,
        on=["event_id", "year", "event_label"],
        suffixes=("_selected500", "_aggregated1000"),
        validate="one_to_one",
    )
    internal_error = max(
        float(
            (
                internal[f"{column}_selected500"]
                - internal[f"{column}_aggregated1000"]
            ).abs().max()
        )
        for column in internal_columns
    )

    primary = pd.read_csv(PRIMARY_SUMMARY)
    primary = primary.loc[primary["geography"].eq("D_equal_city")]
    comparison, stability = comparison_table(primary, summary1000)

    project_by_year = {
        int(year): group
        for year, group in project1000.groupby("year", sort=False)
    }
    annual_index = annual1000.set_index(["year", "city", "parent_1km_id"])
    closure_errors: list[float] = []
    for year, group in project_by_year.items():
        summed = group.groupby(["city", "parent_1km_id"])[PROJECT_METRICS].sum()
        before = annual_index.loc[year - 1]
        after = annual_index.loc[year]
        for annual_metric, project_metric in zip(ANNUAL_METRICS, PROJECT_METRICS):
            expected = after[annual_metric] - before[annual_metric]
            aligned = summed[project_metric].reindex(expected.index)
            closure_errors.extend((aligned - expected).abs().tolist())

    full_cells = pd.read_parquet(ANNUAL500, columns=["grid_id", "year", "population_weight"])
    base = full_cells.loc[full_cells["year"].eq(2017)].drop_duplicates("grid_id")
    base_status = pd.read_parquet(
        ANNUAL500,
        columns=["grid_id", "year", "population_weight", "analysis_status"],
    )
    base_status = base_status.loc[base_status["year"].eq(2017)].drop_duplicates("grid_id")
    retained_ids = set(mapping["grid_id"])
    retained_population = float(
        base.loc[base["grid_id"].isin(retained_ids), "population_weight"].sum()
    )
    full_population = float(base["population_weight"].sum())
    valid_base = base_status.loc[base_status["analysis_status"].ne("missing_walk_snap")]
    retained_valid_population = float(
        valid_base.loc[
            valid_base["grid_id"].isin(retained_ids), "population_weight"
        ].sum()
    )
    full_valid_population = float(valid_base["population_weight"].sum())
    rank_threshold = float(cfg["rank_threshold"])
    overlap_threshold = float(cfg["top_quartile_overlap_threshold"])
    checks = {
        "all_retained_parents_have_four_children": bool(
            mapping.groupby("parent_1km_id").size().eq(4).all()
        ),
        "all_parent_children_stay_in_one_city": bool(
            mapping.groupby("parent_1km_id")["gba_city"].nunique().eq(1).all()
        ),
        "expected_event_count": summary1000["event_id"].nunique() == 29,
        "internal_aggregation_closure": internal_error <= TOLERANCE,
        "annual_project_closure": max(closure_errors) <= cfg["closure_tolerance"],
        "total_rank_threshold": stability["total_opportunity_contribution"]["spearman"]
        >= rank_threshold,
        "cross_rank_threshold": stability["cross_city_opportunity_contribution"]["spearman"]
        >= rank_threshold,
        "total_top_quartile_threshold": stability["total_opportunity_contribution"]["top_quartile_overlap"]
        >= overlap_threshold,
        "cross_top_quartile_threshold": stability["cross_city_opportunity_contribution"]["top_quartile_overlap"]
        >= overlap_threshold,
        "total_sign_gate": stability["total_opportunity_contribution"]["sign_agreement"]
        == 1.0,
        "cross_sign_gate": stability["cross_city_opportunity_contribution"]["sign_agreement"]
        == 1.0,
        "coverage_sign_gate": stability["coverage_contribution"]["sign_agreement"]
        == 1.0,
    }
    audit = {
        "analysis": "transport_D_nested_1km_aggregation_sensitivity",
        "interpretation_boundary": cfg["interpretation"],
        "config": str(CONFIG.relative_to(ROOT)),
        "config_sha256": sha256(CONFIG),
        "source_hashes": {
            str(GRID500.relative_to(ROOT)): sha256(GRID500),
            str(GRID1000.relative_to(ROOT)): sha256(GRID1000),
            str(ANNUAL500.relative_to(ROOT)): sha256(ANNUAL500),
            str(PROJECT500.relative_to(ROOT)): sha256(PROJECT500),
        },
        "support": {
            "complete_1km_parents": int(mapping["parent_1km_id"].nunique()),
            "analyzed_1km_parents_after_missing_snap_filter": int(
                annual1000["parent_1km_id"].nunique()
            ),
            "retained_500m_children": int(mapping["grid_id"].nunique()),
            "full_500m_cells": int(base["grid_id"].nunique()),
            "cell_fraction_retained": float(mapping["grid_id"].nunique() / base["grid_id"].nunique()),
            "population_fraction_retained": retained_population / full_population,
            "valid_population_fraction_retained": retained_valid_population
            / full_valid_population,
        },
        "maximum_internal_aggregation_error": internal_error,
        "maximum_annual_project_closure_error": float(max(closure_errors)),
        "stability": stability,
        "checks": checks,
        "rank_gates_passed": all(
            checks[key]
            for key in [
                "total_rank_threshold",
                "cross_rank_threshold",
                "total_top_quartile_threshold",
                "cross_top_quartile_threshold",
            ]
        ),
        "all_sign_gates_passed": all(
            checks[key]
            for key in ["total_sign_gate", "cross_sign_gate", "coverage_sign_gate"]
        ),
        "passed": all(checks.values()),
    }
    ANNUAL1000.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY1000.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    annual1000.to_parquet(ANNUAL1000, index=False)
    project1000.to_parquet(PROJECT1000, index=False)
    summary1000.to_csv(SUMMARY1000, index=False)
    comparison.to_csv(COMPARISON, index=False)
    audit["outputs"] = {
        str(ANNUAL1000.relative_to(ROOT)): {"rows": len(annual1000), "sha256": sha256(ANNUAL1000)},
        str(PROJECT1000.relative_to(ROOT)): {"rows": len(project1000), "sha256": sha256(PROJECT1000)},
        str(SUMMARY1000.relative_to(ROOT)): {"rows": len(summary1000), "sha256": sha256(SUMMARY1000)},
        str(COMPARISON.relative_to(ROOT)): {"rows": len(comparison), "sha256": sha256(COMPARISON)},
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# D组嵌套1公里聚合敏感性",
        "",
        "1公里结果只由四个对齐且同城的500米完整子格聚合，不重算轨道路径。内部聚合闭合与支持域变化分开报告；这不是独立复现。",
        "",
        f"- 完整1公里父格：{audit['support']['complete_1km_parents']:,}",
        f"- 保留500米子格：{audit['support']['retained_500m_children']:,}/{audit['support']['full_500m_cells']:,}（{audit['support']['cell_fraction_retained']:.2%}）",
        f"- 保留人口：{audit['support']['population_fraction_retained']:.2%}",
        f"- 内部聚合最大误差：{internal_error:.3e}",
        f"- 年度项目闭合最大误差：{max(closure_errors):.3e}",
        "",
        "| 指标 | Spearman | 前四分位重合 | 符号一致 | 1km/500m累计比 |",
        "|---|---:|---:|---:|---:|",
    ]
    labels = {
        "total_opportunity_contribution": "总机会",
        "cross_city_opportunity_contribution": "跨市机会",
        "coverage_contribution": "覆盖",
    }
    for metric, label in labels.items():
        item = stability[metric]
        lines.append(
            f"| {label} | {item['spearman']:.4f} | {item['top_quartile_overlap']:.3f} | {item['sign_agreement']:.3f} | {item['sum_1km_to_500m_ratio']:.3f} |"
        )
    lines.extend([
        "",
        f"审计：{'PASS' if audit['passed'] else 'FAIL'}。排名比较同时包含边界不完整父格被排除所带来的支持域敏感性，不能称为第二套网络结果。",
    ])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    # A sensitivity can legitimately reveal a failed sign gate; the output is
    # complete and should remain available for claim qualification.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
