#!/usr/bin/env python3
"""Compare frozen D R0 results with the R3 pedestrian-snap sensitivity."""

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
R3 = ROOT / "Results/tables/transport_d_project_summary_r3.csv"
TABLE = ROOT / "Results/tables/transport_d_r0_r3_comparison.csv"
JSON_OUT = ROOT / "Results/transport_d_r3_stability.json"
REPORT = ROOT / "Results/TRANSPORT_D_R3_STABILITY.md"
TOLERANCE = 1e-10
METRICS = {
    "total_opportunity": "population_weighted_total_opportunity_contribution",
    "cross_city_opportunity": "population_weighted_cross_city_opportunity_contribution",
    "coverage": "population_weighted_coverage_contribution",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signs(values: pd.Series) -> np.ndarray:
    return np.where(values > TOLERANCE, 1, np.where(values < -TOLERANCE, -1, 0))


def main() -> int:
    r0 = pd.read_csv(R0)
    r3 = pd.read_csv(R3)
    keys = ["event_id", "year", "event_label", "geography", "cities"]
    merged = r0.merge(r3, on=keys, validate="one_to_one", suffixes=("_r0", "_r3"))
    if len(merged) != 29:
        raise RuntimeError("R0/R3 comparison does not contain all 29 projects")
    top_n = ceil(len(merged) / 4)
    results: dict[str, dict] = {}
    for metric, column in METRICS.items():
        first = merged[f"{column}_r0"]
        second = merged[f"{column}_r3"]
        top_first = set(merged.loc[first.nlargest(top_n).index, "event_id"])
        top_second = set(merged.loc[second.nlargest(top_n).index, "event_id"])
        match = signs(first) == signs(second)
        results[metric] = {
            "spearman": float(spearmanr(first, second).statistic),
            "top_quartile_n": top_n,
            "top_quartile_overlap": float(len(top_first & top_second) / top_n),
            "sign_agreement_fraction": float(match.mean()),
            "sign_disagreement_event_ids": merged.loc[~match, "event_id"].tolist(),
            "R3_to_R0_sum_ratio": float(second.sum() / first.sum())
            if abs(first.sum()) > TOLERANCE
            else None,
            "sign_gate_pass": bool(match.all()),
        }
        results[metric]["rank_threshold_pass"] = bool(
            results[metric]["spearman"] >= 0.80
            and results[metric]["top_quartile_overlap"] >= 0.75
        )
        merged[f"{metric}_sign_match"] = match
        merged[f"{metric}_rank_r0"] = first.rank(method="min", ascending=False)
        merged[f"{metric}_rank_r3"] = second.rank(method="min", ascending=False)
    output = {
        "analysis": "transport_D_R0_R3_stability",
        "input_hashes": {"R0": sha256(R0), "R3": sha256(R3)},
        "thresholds": {
            "minimum_spearman": 0.80,
            "minimum_top_quartile_overlap": 0.75,
            "sign_zero_tolerance": TOLERANCE,
        },
        "metrics": results,
        "all_rank_thresholds_pass": all(
            value["rank_threshold_pass"] for value in results.values()
        ),
        "all_sign_gates_pass": all(
            value["sign_gate_pass"] for value in results.values()
        ),
        "all_rank_and_sign_requirements_pass": all(
            value["rank_threshold_pass"] and value["sign_gate_pass"]
            for value in results.values()
        ),
        "interpretation": "R3 is a predeclared but post-outcome-constructed deterministic pedestrian-snap sensitivity; it is not an independent replication",
    }
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(TABLE, index=False)
    JSON_OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    labels = {
        "total_opportunity": "总机会",
        "cross_city_opportunity": "跨市机会",
        "coverage": "覆盖",
    }
    lines = [
        "# D组R0—R3吸附敏感性",
        "",
        "R3对满足冻结50米附加连接距离条件的对象改用第二近步行节点；轨道拓扑、事件、机会面和服务参数均保持R0。该规则虽在合同中预先声明，但R3路径表在D开启后确定性构建，因此属于补充敏感性而非独立确认。",
        "",
        "| 指标 | Spearman | 前四分位重合 | 符号一致 | R3/R0累计比 |",
        "|---|---:|---:|---:|---:|",
    ]
    for metric, label in labels.items():
        item = results[metric]
        lines.append(
            f"| {label} | {item['spearman']:.4f} | {item['top_quartile_overlap']:.3f} | {item['sign_agreement_fraction']:.3f} | {item['R3_to_R0_sum_ratio']:.3f} |"
        )
    lines.extend(
        [
            "",
            "符号差异事件必须逐项披露；排名阈值通过不等于绝对幅度或现实服务时间得到验证。",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
