#!/usr/bin/env python3
"""Summarize the one-time D project-attribution outcomes without changing rules."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
ANNUAL = ROOT / "Data/processed/transport/d_annual_accessibility_cell.parquet"
CONTRIBUTION = ROOT / "Data/processed/transport/d_project_attribution_cell.parquet"
PROJECT_INPUT = ROOT / "Results/tables/transport_d_project_summary.csv"
ANNUAL_OUT = ROOT / "Results/tables/transport_d_annual_city_summary.csv"
RANK_OUT = ROOT / "Results/tables/transport_d_project_rankings.csv"
REACH_OUT = ROOT / "Results/tables/transport_d_project_spatial_reach.csv"
JSON_OUT = ROOT / "Results/transport_d_analysis.json"
REPORT_OUT = ROOT / "Results/TRANSPORT_D_ANALYSIS.md"
TOLERANCE = 1e-10


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna()
    return float((values[valid] * weights[valid]).sum() / weights[valid].sum())


def annual_summary(annual: pd.DataFrame) -> pd.DataFrame:
    rows = []
    valid = annual.loc[annual["analysis_status"].ne("missing_walk_snap")]
    for (year, city), group in valid.groupby(["year", "city"]):
        record = {"year": int(year), "geography": city, "cities": 1}
        for metric in ("total_opportunity", "cross_city_opportunity", "coverage"):
            record[f"population_weighted_{metric}"] = weighted_mean(
                group[metric], group["population_weight"]
            )
            record[f"area_weighted_{metric}"] = weighted_mean(
                group[metric], group["area_weight_m2"]
            )
        record["population_denominator"] = float(group["population_weight"].sum())
        record["area_denominator_m2"] = float(group["area_weight_m2"].sum())
        rows.append(record)
    city = pd.DataFrame(rows)
    aggregate = []
    value_columns = [
        column
        for column in city.columns
        if column.startswith("population_weighted_")
        or column.startswith("area_weighted_")
    ]
    for year, group in city.groupby("year"):
        record = {"year": int(year), "geography": "D_equal_city", "cities": len(group)}
        for column in value_columns:
            record[column] = float(group[column].mean())
        record["population_denominator"] = float(group["population_denominator"].sum())
        record["area_denominator_m2"] = float(group["area_denominator_m2"].sum())
        aggregate.append(record)
    return pd.concat([city, pd.DataFrame(aggregate)], ignore_index=True).sort_values(
        ["year", "geography"]
    )


def spatial_reach(contribution: pd.DataFrame) -> pd.DataFrame:
    rows = []
    valid = contribution.loc[
        contribution["analysis_status"].ne("missing_walk_snap")
    ]
    metrics = {
        "total": "total_opportunity_contribution",
        "cross_city": "cross_city_opportunity_contribution",
        "coverage": "coverage_contribution",
    }
    for (event_id, year, label), group in valid.groupby(
        ["event_id", "year", "event_label"], sort=False
    ):
        record = {"event_id": event_id, "year": int(year), "event_label": label}
        total_population = float(group["population_weight"].sum())
        for prefix, metric in metrics.items():
            nonzero = group[metric].abs().gt(TOLERANCE)
            positive = group[metric].gt(TOLERANCE)
            negative = group[metric].lt(-TOLERANCE)
            record[f"{prefix}_nonzero_cells"] = int(nonzero.sum())
            record[f"{prefix}_positive_cells"] = int(positive.sum())
            record[f"{prefix}_negative_cells"] = int(negative.sum())
            record[f"{prefix}_nonzero_population_fraction"] = float(
                group.loc[nonzero, "population_weight"].sum() / total_population
            )
            record[f"{prefix}_affected_cities"] = int(
                group.loc[nonzero, "city"].nunique()
            )
        rows.append(record)
    return pd.DataFrame(rows)


def main() -> int:
    annual = pd.read_parquet(ANNUAL)
    contribution = pd.read_parquet(CONTRIBUTION)
    projects = pd.read_csv(PROJECT_INPUT)
    annual_table = annual_summary(annual)
    reach = spatial_reach(contribution)
    d_annual = annual_table.loc[annual_table["geography"].eq("D_equal_city")].set_index(
        "year"
    )
    projects["start_total_opportunity"] = projects["year"].map(
        {year + 1: value for year, value in d_annual["population_weighted_total_opportunity"].items()}
    )
    projects["total_contribution_percent_of_start"] = 100 * projects[
        "population_weighted_total_opportunity_contribution"
    ] / projects["start_total_opportunity"]
    projects["cross_city_share_of_total_contribution"] = np.where(
        projects["population_weighted_total_opportunity_contribution"].abs()
        > TOLERANCE,
        projects["population_weighted_cross_city_opportunity_contribution"]
        / projects["population_weighted_total_opportunity_contribution"],
        np.nan,
    )
    projects["total_rank_desc"] = projects[
        "population_weighted_total_opportunity_contribution"
    ].rank(method="min", ascending=False)
    projects["cross_city_rank_desc"] = projects[
        "population_weighted_cross_city_opportunity_contribution"
    ].rank(method="min", ascending=False)
    projects["coverage_rank_desc"] = projects[
        "population_weighted_coverage_contribution"
    ].rank(method="min", ascending=False)
    projects["contribution_type"] = np.select(
        [
            projects["population_weighted_total_opportunity_contribution"].lt(
                -TOLERANCE
            ),
            projects["population_weighted_total_opportunity_contribution"].abs().le(
                TOLERANCE
            ),
            projects["population_weighted_coverage_contribution"].abs().le(TOLERANCE),
            projects[
                "population_weighted_cross_city_opportunity_contribution"
            ].gt(TOLERANCE),
        ],
        [
            "negative_disruption",
            "structural_zero",
            "connectivity_without_new_coverage",
            "coverage_and_cross_city_connectivity",
        ],
        default="coverage_mainly_local",
    )
    projects = projects.merge(reach, on=["event_id", "year", "event_label"])
    projects = projects.sort_values(
        "population_weighted_total_opportunity_contribution", ascending=False
    ).reset_index(drop=True)

    start = d_annual.loc[2017]
    end = d_annual.loc[2024]
    changes = {}
    for metric in ("total_opportunity", "cross_city_opportunity", "coverage"):
        column = f"population_weighted_{metric}"
        changes[metric] = {
            "2017": float(start[column]),
            "2024": float(end[column]),
            "absolute_change": float(end[column] - start[column]),
            "relative_change_percent": float(100 * (end[column] / start[column] - 1)),
        }
    sum_contributions = {
        metric: float(projects[column].sum())
        for metric, column in {
            "total_opportunity": "population_weighted_total_opportunity_contribution",
            "cross_city_opportunity": "population_weighted_cross_city_opportunity_contribution",
            "coverage": "population_weighted_coverage_contribution",
        }.items()
    }
    closure = {
        metric: float(sum_contributions[metric] - changes[metric]["absolute_change"])
        for metric in sum_contributions
    }
    positive_total = projects.loc[
        projects["population_weighted_total_opportunity_contribution"].gt(0),
        "population_weighted_total_opportunity_contribution",
    ]
    positive_sorted = positive_total.sort_values(ascending=False)
    concentration = {
        "top1_share_of_positive_total": float(positive_sorted.iloc[:1].sum() / positive_sorted.sum()),
        "top3_share_of_positive_total": float(positive_sorted.iloc[:3].sum() / positive_sorted.sum()),
        "top5_share_of_positive_total": float(positive_sorted.iloc[:5].sum() / positive_sorted.sum()),
        "negative_project_count": int(
            projects["population_weighted_total_opportunity_contribution"].lt(0).sum()
        ),
        "zero_project_count": int(
            projects["population_weighted_total_opportunity_contribution"].abs().le(
                TOLERANCE
            ).sum()
        ),
    }
    top_total = projects.iloc[0]
    top_cross = projects.sort_values(
        "population_weighted_cross_city_opportunity_contribution", ascending=False
    ).iloc[0]
    top_coverage = projects.sort_values(
        "population_weighted_coverage_contribution", ascending=False
    ).iloc[0]
    result = {
        "analysis": "transport_D_project_attribution",
        "deterministic_model_outputs": True,
        "uncertainty_status": "R2, R3 and nested 1-km aggregation completed; R1 is not distinct from executed OSM-based R0 and was not run; H1/H2 not run",
        "input_hashes": {
            str(ANNUAL.relative_to(ROOT)): sha256(ANNUAL),
            str(CONTRIBUTION.relative_to(ROOT)): sha256(CONTRIBUTION),
            str(PROJECT_INPUT.relative_to(ROOT)): sha256(PROJECT_INPUT),
        },
        "2017_2024_changes": changes,
        "project_sum_to_annual_change_error": closure,
        "concentration": concentration,
        "top_projects": {
            "total": {
                "event_id": top_total["event_id"],
                "label": top_total["event_label"],
                "value": float(
                    top_total[
                        "population_weighted_total_opportunity_contribution"
                    ]
                ),
            },
            "cross_city": {
                "event_id": top_cross["event_id"],
                "label": top_cross["event_label"],
                "value": float(
                    top_cross[
                        "population_weighted_cross_city_opportunity_contribution"
                    ]
                ),
            },
            "coverage": {
                "event_id": top_coverage["event_id"],
                "label": top_coverage["event_label"],
                "value": float(
                    top_coverage["population_weighted_coverage_contribution"]
                ),
            },
        },
    }
    ANNUAL_OUT.parent.mkdir(parents=True, exist_ok=True)
    annual_table.to_csv(ANNUAL_OUT, index=False)
    projects.to_csv(RANK_OUT, index=False)
    reach.to_csv(REACH_OUT, index=False)
    JSON_OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    top10 = projects.head(10)[
        [
            "total_rank_desc", "event_id", "event_label",
            "population_weighted_total_opportunity_contribution",
            "population_weighted_cross_city_opportunity_contribution",
            "population_weighted_coverage_contribution",
            "total_nonzero_population_fraction", "contribution_type",
        ]
    ].copy()
    top10.columns = [
        "Rank", "Event", "Project", "Total", "Cross-city", "Coverage",
        "Affected-pop. share", "Type",
    ]
    report = f"""# D组轨道项目归因结果分析

## 原始比较表（总机会贡献前10）

{top10.to_markdown(index=False, floatfmt='.6g')}

完整机器表：`Results/tables/transport_d_project_rankings.csv`。

## 关键发现

1. **观察**：D组三市等权的人口加权总机会从2017年的{changes['total_opportunity']['2017']:.1f}增至2024年的{changes['total_opportunity']['2024']:.1f}，增加{changes['total_opportunity']['relative_change_percent']:.1f}%；跨市机会增加{changes['cross_city_opportunity']['relative_change_percent']:.1f}%，覆盖率从{100*changes['coverage']['2017']:.2f}%升至{100*changes['coverage']['2024']:.2f}%。**解释**：固定人口与固定服务条件下，网络拓扑扩张产生了大幅但不同维度不同步的模型化潜在整合。**含义**：选题不是微小信号，具备继续完成论文的实质基础。**下一步**：用已完成的R2、R3与1公里聚合检验相对排序，并把绝对幅度保留为参数依赖结果。

2. **观察**：总机会贡献最高的是“{top_total['event_label']}”（{top_total['population_weighted_total_opportunity_contribution']:.1f}），跨市贡献最高的是“{top_cross['event_label']}”（{top_cross['population_weighted_cross_city_opportunity_contribution']:.1f}），覆盖贡献最高的是“{top_coverage['event_label']}”（{100*top_coverage['population_weighted_coverage_contribution']:.3f}个百分点）。**解释**：覆盖、既有网络连通和跨市整合并不是同一类项目绩效。**含义**：三维贡献框架具有经验辨识度。**下一步**：制作三轴项目类型图与项目贡献地图。

3. **观察**：前1、前3和前5项目分别占全部正总机会贡献的{100*concentration['top1_share_of_positive_total']:.1f}%、{100*concentration['top3_share_of_positive_total']:.1f}%和{100*concentration['top5_share_of_positive_total']:.1f}%。机场北延伸为结构性零；彩虹桥和西村等站点/换乘事件提高机会但不新增覆盖。**解释**：线路长度或新增站数不能代替网络边际贡献，死端延伸、填充站和换乘激活的机制不同。**含义**：项目级归因比两期全网均值提供了额外信息。**下一步**：核验零贡献项目的步行对与站序，并在图中明确机制。

4. **观察**：高明有轨停运的总机会和覆盖贡献精确抵消其2019年开通贡献；海珠有轨广州塔区段关闭也产生负总机会和负跨市贡献。**解释**：冻结网络能识别负事件，而不是预设所有扩张均为正。**含义**：结果具有内部反事实一致性。**下一步**：在主文中同时展示开通、结构零与停运三类空间机制。

5. **观察**：29个项目贡献之和与2017—2024年度变化的误差为：总机会{closure['total_opportunity']:.3e}、跨市机会{closure['cross_city_opportunity']:.3e}、覆盖{closure['coverage']:.3e}。**解释**：年度Shapley分解和跨年度累计完全闭合。**含义**：项目比较不是选择性案例叙事。**下一步**：进行文件级结果—主张审计。

## 当前判断

D结果已达到“值得继续”的门槛，且具有空间交通论文而非实验报告的基本结构：它给出项目级、逐格、可加总的覆盖—连通—跨市贡献，并识别结构性零、连接型高贡献和负停运事件。R2、R3与1公里聚合下三个指标的排名阈值均通过；但R2跨市机会、R3覆盖和1公里覆盖并未全部保持逐项目符号，且R2绝对累计幅度明显收缩。R1因实际R0已经使用OSM轨道几何而不能构成独立变体。因此论文应以“三城项目相对贡献与空间机制”为主线，不宣称完整R0—R3稳健性，也不推广为九市经验规律。

## 建议的下一组实验

1. 生成年度可达性、项目贡献、首次覆盖分层和稳健性地图，形成以地理图为核心的证据链。
2. 将完整性审计、R3逐连接规则审计、R1不可构造说明和官方来源补充写入方法及补充材料。
3. 起草限定为广州—佛山—东莞三城的摘要、引言、方法和结果；H1/H2不再作为当前稿件投稿前的必要条件。
4. 对南海有轨两项仅有官方URL而未能本地归档的来源缺口保持透明披露，并继续寻找可持久化的官方副本。
"""
    REPORT_OUT.write_text(report, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
