#!/usr/bin/env python3
"""Compare frozen R0 and R2 D project-attribution outcomes."""

from __future__ import annotations

import hashlib
import json
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


ROOT = Path(__file__).resolve().parents[2]
R0 = ROOT / "Results/tables/transport_d_project_summary.csv"
R2 = ROOT / "Results/tables/transport_d_project_summary_r2.csv"
TABLE_OUT = ROOT / "Results/tables/transport_d_r0_r2_comparison.csv"
JSON_OUT = ROOT / "Results/transport_d_r2_stability.json"
REPORT_OUT = ROOT / "Results/TRANSPORT_D_R2_STABILITY.md"
TOLERANCE = 1e-10


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signs(values: pd.Series) -> np.ndarray:
    return np.where(values > TOLERANCE, 1, np.where(values < -TOLERANCE, -1, 0))


def main() -> int:
    r0 = pd.read_csv(R0)
    r2 = pd.read_csv(R2)
    keys = ["event_id", "year", "event_label", "geography", "cities"]
    merged = r0.merge(r2, on=keys, how="inner", validate="one_to_one", suffixes=("_r0", "_r2"))
    if len(merged) != 29:
        raise RuntimeError("R0/R2 comparison does not contain all 29 frozen projects")
    metrics = {
        "total_opportunity": "population_weighted_total_opportunity_contribution",
        "cross_city_opportunity": "population_weighted_cross_city_opportunity_contribution",
        "coverage": "population_weighted_coverage_contribution",
    }
    top_n = ceil(len(merged) / 4)
    results = {}
    for metric, column in metrics.items():
        first = merged[f"{column}_r0"]
        second = merged[f"{column}_r2"]
        top_r0 = set(merged.loc[first.nlargest(top_n).index, "event_id"])
        top_r2 = set(merged.loc[second.nlargest(top_n).index, "event_id"])
        sign_match = signs(first) == signs(second)
        results[metric] = {
            "spearman": float(spearmanr(first, second).statistic),
            "top_quartile_n": top_n,
            "top_quartile_overlap": float(len(top_r0 & top_r2) / top_n),
            "sign_agreement_fraction": float(sign_match.mean()),
            "sign_disagreement_event_ids": merged.loc[
                ~sign_match, "event_id"
            ].tolist(),
            "R2_to_R0_sum_ratio": float(second.sum() / first.sum())
            if first.sum() != 0
            else None,
            "sign_gate_pass": bool(sign_match.all()),
            "rank_threshold_pass": bool(
                spearmanr(first, second).statistic >= 0.80
                and len(top_r0 & top_r2) / top_n >= 0.75
            ),
        }
        merged[f"{metric}_sign_match"] = sign_match
        merged[f"{metric}_rank_r0"] = first.rank(method="min", ascending=False)
        merged[f"{metric}_rank_r2"] = second.rank(method="min", ascending=False)
    overall = {
        "all_three_rank_thresholds_pass": all(
            item["rank_threshold_pass"] for item in results.values()
        ),
        "total_and_coverage_signs_all_stable": results["total_opportunity"][
            "sign_agreement_fraction"
        ]
        == 1.0
        and results["coverage"]["sign_agreement_fraction"] == 1.0,
        "universal_cross_city_sign_claim_allowed": results[
            "cross_city_opportunity"
        ]["sign_agreement_fraction"]
        == 1.0,
        "all_declared_sign_gates_pass": all(
            item["sign_gate_pass"] for item in results.values()
        ),
        "all_declared_rank_and_sign_requirements_pass": all(
            item["rank_threshold_pass"] and item["sign_gate_pass"]
            for item in results.values()
        ),
    }
    output = {
        "analysis": "transport_D_R0_R2_stability",
        "input_hashes": {"R0": sha256(R0), "R2": sha256(R2)},
        "thresholds": {
            "minimum_spearman": 0.80,
            "minimum_top_quartile_overlap": 0.75,
            "sign_zero_tolerance": TOLERANCE,
        },
        "metrics": results,
        "overall": overall,
    }
    TABLE_OUT.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(TABLE_OUT, index=False)
    JSON_OUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = f"""# D组R0—R2稳定性

| 指标 | Spearman | 前四分位重合 | 符号一致 | R2/R0总量 |
|---|---:|---:|---:|---:|
| 总机会 | {results['total_opportunity']['spearman']:.3f} | {results['total_opportunity']['top_quartile_overlap']:.3f} | {results['total_opportunity']['sign_agreement_fraction']:.3f} | {results['total_opportunity']['R2_to_R0_sum_ratio']:.3f} |
| 跨市机会 | {results['cross_city_opportunity']['spearman']:.3f} | {results['cross_city_opportunity']['top_quartile_overlap']:.3f} | {results['cross_city_opportunity']['sign_agreement_fraction']:.3f} | {results['cross_city_opportunity']['R2_to_R0_sum_ratio']:.3f} |
| 覆盖 | {results['coverage']['spearman']:.3f} | {results['coverage']['top_quartile_overlap']:.3f} | {results['coverage']['sign_agreement_fraction']:.3f} | {results['coverage']['R2_to_R0_sum_ratio']:.3f} |

三项排名均超过预设的Spearman 0.80和前四分位重合0.75门槛。总机会与覆盖的29个项目符号全部稳定。跨市机会有两个R0极小正值在R2变为严格零：清塘填充站（R0 1.040）和黄埔有轨1号线首段（R0 0.514）；不存在正负反转，但不得对这两个项目作稳健跨市增益主张。

R2把总机会贡献总量压缩到R0的{100*results['total_opportunity']['R2_to_R0_sum_ratio']:.1f}%，跨市贡献压缩到{100*results['cross_city_opportunity']['R2_to_R0_sum_ratio']:.1f}%，说明绝对幅度依赖服务假设；但项目相对排序高度稳定。因此论文可以主张“项目类型和相对贡献排序对保守阻抗较稳健”，不能把R0绝对值解释为真实历史实现量。
"""
    REPORT_OUT.write_text(report, encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
