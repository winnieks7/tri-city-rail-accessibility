#!/usr/bin/env python3
"""Decompose D project contributions into additive baseline-coverage strata.

The source project-cell Shapley values are immutable.  For each city, each
stratum numerator is divided by the full valid city population denominator;
therefore baseline-uncovered and baseline-covered components add exactly to the
published city mean.  Multi-city values then apply the frozen equal-city rule.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Data/processed/transport/d_project_attribution_cell.parquet"
TABLE = ROOT / "Results/tables/transport_d_baseline_coverage_decomposition.csv"
AUDIT = ROOT / "Results/pilots/transport_d_baseline_coverage_decomposition_audit.json"
REPORT = ROOT / "Results/TRANSPORT_D_BASELINE_COVERAGE_DECOMPOSITION.md"
TOLERANCE = 1e-10

METRICS = {
    "total_opportunity": "total_opportunity_contribution",
    "cross_city_opportunity": "cross_city_opportunity_contribution",
    "coverage": "coverage_contribution",
}
STRATA = {0.0: "baseline_uncovered", 1.0: "baseline_covered"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_share(component: float, total: float) -> float:
    return float(component / total) if abs(total) > TOLERANCE else np.nan


def city_rows(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    group_keys = ["event_id", "year", "event_label", "city"]
    for (event_id, year, event_label, city), group in data.groupby(
        group_keys, sort=False
    ):
        valid = group.loc[group["analysis_status"].ne("missing_walk_snap")]
        denominator = float(valid["population_weight"].sum())
        if denominator <= 0:
            raise RuntimeError(f"non-positive population denominator for {city}")
        observed_strata = set(valid["baseline_coverage"].dropna().unique())
        if not observed_strata <= set(STRATA):
            raise RuntimeError(
                f"non-binary baseline coverage for {event_id}/{city}: {observed_strata}"
            )
        for metric, column in METRICS.items():
            total = float(
                (valid[column] * valid["population_weight"]).sum() / denominator
            )
            for value, stratum in STRATA.items():
                selected = valid.loc[valid["baseline_coverage"].eq(value)]
                stratum_population = float(selected["population_weight"].sum())
                component = float(
                    (selected[column] * selected["population_weight"]).sum()
                    / denominator
                )
                rows.append(
                    {
                        "event_id": event_id,
                        "year": int(year),
                        "event_label": event_label,
                        "geography": city,
                        "metric": metric,
                        "baseline_stratum": stratum,
                        "full_valid_population_denominator": denominator,
                        "stratum_population": stratum_population,
                        "stratum_population_fraction": stratum_population
                        / denominator,
                        "additive_population_weighted_contribution": component,
                        "full_population_weighted_contribution": total,
                        "stratum_share_of_project_contribution": safe_share(
                            component, total
                        ),
                    }
                )
    return pd.DataFrame(rows)


def add_equal_city_rows(city: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    keys = ["event_id", "year", "event_label", "metric", "baseline_stratum"]
    for key, group in city.groupby(keys, sort=False):
        event_id, year, event_label, metric, stratum = key
        if group["geography"].nunique() != 3:
            raise RuntimeError(f"D equal-city summary lacks three cities for {event_id}")
        component = float(group["additive_population_weighted_contribution"].mean())
        total = float(group["full_population_weighted_contribution"].mean())
        rows.append(
            {
                "event_id": event_id,
                "year": int(year),
                "event_label": event_label,
                "geography": "D_equal_city",
                "metric": metric,
                "baseline_stratum": stratum,
                "full_valid_population_denominator": float(
                    group["full_valid_population_denominator"].sum()
                ),
                "stratum_population": float(group["stratum_population"].sum()),
                "stratum_population_fraction": float(
                    group["stratum_population_fraction"].mean()
                ),
                "additive_population_weighted_contribution": component,
                "full_population_weighted_contribution": total,
                "stratum_share_of_project_contribution": safe_share(component, total),
            }
        )
    return pd.concat([city, pd.DataFrame(rows)], ignore_index=True)


def build_audit(table: pd.DataFrame) -> dict:
    closure = (
        table.groupby(
            ["event_id", "year", "geography", "metric"], sort=False
        )
        .agg(
            component_sum=("additive_population_weighted_contribution", "sum"),
            expected=("full_population_weighted_contribution", "first"),
            rows=("baseline_stratum", "size"),
        )
        .reset_index()
    )
    closure["error"] = closure["component_sum"] - closure["expected"]
    max_error = float(closure["error"].abs().max())
    d = table.loc[table["geography"].eq("D_equal_city")]
    cumulative = (
        d.groupby(["metric", "baseline_stratum"], sort=False)[
            "additive_population_weighted_contribution"
        ]
        .sum()
        .unstack(fill_value=0.0)
    )
    overall: dict[str, dict] = {}
    for metric, row in cumulative.iterrows():
        uncovered = float(row.get("baseline_uncovered", 0.0))
        covered = float(row.get("baseline_covered", 0.0))
        total = uncovered + covered
        overall[metric] = {
            "baseline_uncovered_contribution": uncovered,
            "baseline_covered_contribution": covered,
            "total_contribution": total,
            "baseline_uncovered_share": safe_share(uncovered, total),
            "baseline_covered_share": safe_share(covered, total),
        }
    checks = {
        "source_exists": SOURCE.exists(),
        "all_rows_have_two_strata": bool(closure["rows"].eq(2).all()),
        "all_baseline_strata_binary": bool(
            set(table["baseline_stratum"]) == set(STRATA.values())
        ),
        "all_D_events_have_three_cities": bool(
            table.loc[table["geography"].ne("D_equal_city")]
            .groupby("event_id")["geography"]
            .nunique()
            .eq(3)
            .all()
        ),
        "component_closure_within_tolerance": max_error <= TOLERANCE,
        "expected_event_count": table["event_id"].nunique() == 29,
        "expected_metric_count": table["metric"].nunique() == 3,
    }
    return {
        "analysis": "transport_D_additive_baseline_coverage_decomposition",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha256(SOURCE),
        "method": "within each city, stratum weighted numerators divided by the full valid city population denominator; D summary is the equal mean of city components",
        "tolerance": TOLERANCE,
        "counts": {
            "rows": len(table),
            "events": int(table["event_id"].nunique()),
            "metrics": int(table["metric"].nunique()),
            "geographies": int(table["geography"].nunique()),
        },
        "maximum_absolute_component_closure_error": max_error,
        "overall_D_equal_city": overall,
        "checks": checks,
        "passed": all(checks.values()),
    }


def write_report(audit: dict) -> None:
    overall = audit["overall_D_equal_city"]
    lines = [
        "# D组年初覆盖分层的可加总贡献",
        "",
        "该分解不重跑可达性结果。每个城市内，年初未覆盖与已覆盖起点的加权贡献分子均除以同一个完整有效人口分母，因此两部分严格加总为项目的城市平均贡献；D组再按冻结规则对三市等权。",
        "",
        f"- 审计：{'PASS' if audit['passed'] else 'FAIL'}",
        f"- 最大绝对闭合误差：{audit['maximum_absolute_component_closure_error']:.3e}",
        "",
        "## 2017—2024年29个事件的累计分解",
        "",
        "| 指标 | 年初未覆盖贡献 | 年初已覆盖贡献 | 未覆盖份额 |",
        "|---|---:|---:|---:|",
    ]
    labels = {
        "total_opportunity": "总机会",
        "cross_city_opportunity": "跨市机会",
        "coverage": "覆盖",
    }
    for metric in METRICS:
        item = overall[metric]
        lines.append(
            "| {label} | {uncovered:.6f} | {covered:.6f} | {share:.2%} |".format(
                label=labels[metric],
                uncovered=item["baseline_uncovered_contribution"],
                covered=item["baseline_covered_contribution"],
                share=item["baseline_uncovered_share"],
            )
        )
    lines.extend(
        [
            "",
            "份额是模型化项目贡献的加性来源，不是受益人口比例、历史首次服务比例或因果分配。若项目总贡献接近零，项目级分层份额记为缺失而不强行解释。",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    source = pd.read_parquet(SOURCE)
    table = add_equal_city_rows(city_rows(source))
    table = table.sort_values(
        ["year", "event_id", "geography", "metric", "baseline_stratum"]
    ).reset_index(drop=True)
    audit = build_audit(table)
    if not audit["passed"]:
        raise RuntimeError(json.dumps(audit, ensure_ascii=False, indent=2))
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(TABLE, index=False)
    audit["output"] = {
        "path": str(TABLE.relative_to(ROOT)),
        "rows": len(table),
        "sha256": sha256(TABLE),
    }
    AUDIT.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_report(audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
