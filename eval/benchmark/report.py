"""基准评估报告生成

生成多配置对比表格和 Markdown 报告。
"""


def print_comparison_table(results: dict) -> str:
    """打印终端友好的对比表格

    Args:
        results: BenchmarkRunner.run() 的输出
    """
    config_results = results.get("results", {})
    if not config_results:
        return "No results to display."

    # 收集所有指标名
    all_metrics = set()
    for cfg_results in config_results.values():
        all_metrics.update(cfg_results.keys())
    all_metrics.discard("config")
    all_metrics.discard("num_queries")

    # 排序: NDCG → Recall → MRR → Precision → latency
    def metric_sort_key(name):
        for prefix in ["NDCG", "Recall", "MRR", "Precision"]:
            if name.startswith(prefix):
                return (0, name)
        return (1, name)

    sorted_metrics = sorted(all_metrics, key=metric_sort_key)

    # 找出每个指标的最佳值（用于加粗）
    best_values = {}
    for metric in sorted_metrics:
        if not metric.endswith(("_ci_low", "_ci_high")):
            best = 0.0
            best_cfg = ""
            for cfg_name, cfg_results in config_results.items():
                val = cfg_results.get(metric, 0)
                if val > best:
                    best = val
                    best_cfg = cfg_name
            best_values[metric] = (best, best_cfg)

    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append(f"  BENCHMARK RESULTS: {results.get('dataset', 'N/A')}")
    lines.append(f"  Settings: {results.get('settings', {})}")
    lines.append("=" * 80)

    # 表头
    header = f"{'Metric':<22}"
    for cfg_name in config_results:
        header += f" {cfg_name:>16}"
    lines.append(header)
    lines.append("-" * 80)

    # 每行一个指标
    for metric in sorted_metrics:
        if metric.endswith("_ci_low") or metric.endswith("_ci_high"):
            continue  # CI 不单独显示，用 ± 格式

        row = f"  {metric:<20}"
        for cfg_name in config_results:
            val = config_results[cfg_name].get(metric)
            if val is None:
                row += f" {'N/A':>16}"
                continue

            if isinstance(val, float):
                ci_low = config_results[cfg_name].get(f"{metric}_ci_low")
                ci_high = config_results[cfg_name].get(f"{metric}_ci_high")
                if ci_low is not None and ci_high is not None:
                    row += f" {val:>10.4f}±{(ci_high - val):.3f}"
                else:
                    row += f" {val:>16.4f}"
            else:
                row += f" {str(val):>16}"

        # 标出最佳
        if metric in best_values:
            row += "  ← best"

        lines.append(row)

    lines.append("=" * 80)
    lines.append("  ↑ values show mean ± bootstrap 95% CI half-width")
    lines.append("")

    output = "\n".join(lines)
    print(output)
    return output


def generate_markdown_report(results: dict, output_path: str = "") -> str:
    """生成 Markdown 格式的评估报告

    Args:
        results: BenchmarkRunner.run() 的输出
        output_path: 输出文件路径（可选）

    Returns:
        Markdown 文本
    """
    config_results = results.get("results", {})
    settings = results.get("settings", {})

    all_metrics = set()
    for cfg_results in config_results.values():
        all_metrics.update(cfg_results.keys())
    all_metrics.discard("config")
    all_metrics.discard("num_queries")

    # 指标排序
    def metric_sort_key(name):
        for prefix in ["NDCG", "Recall", "MRR", "Precision"]:
            if name.startswith(prefix):
                return (0, name)
        return (1, name)

    sorted_metrics = sorted(all_metrics, key=metric_sort_key)

    md = []
    md.append(f"# Benchmark Report: {results.get('dataset', 'N/A')}")
    md.append("")
    md.append(f"- **Documents**: {settings.get('max_docs', 'N/A')}")
    md.append(f"- **Queries**: {settings.get('max_queries', 'N/A')}")
    md.append(f"- **Top-K**: {settings.get('top_k', 'N/A')}")
    md.append("")

    # 表格
    cfg_names = list(config_results.keys())
    header = "| Metric | " + " | ".join(cfg_names) + " |"
    md.append(header)
    sep = "|" + "|".join([" --- " for _ in range(len(cfg_names) + 1)]) + "|"
    md.append(sep)

    for metric in sorted_metrics:
        if metric.endswith("_ci_low") or metric.endswith("_ci_high"):
            continue

        vals = []
        best_val = -1
        best_idx = -1
        for i, cfg_name in enumerate(cfg_names):
            v = config_results[cfg_name].get(metric)
            if v is not None and isinstance(v, (int, float)):
                if v > best_val:
                    best_val = v
                    best_idx = i
            vals.append(v)

        cells = [f"**{metric}**"]
        for i, v in enumerate(vals):
            if v is None:
                cells.append("N/A")
            elif i == best_idx and best_val > 0:
                cells.append(f"**{v:.4f}**")
            else:
                cells.append(f"{v:.4f}")

        md.append("| " + " | ".join(cells) + " |")

    md.append("")
    md.append("*Bold values indicate best result for each metric.*")
    md.append("")

    # 延迟单独列出
    if "avg_latency_ms" in sorted_metrics:
        md.append("## Latency")
        md.append("")
        for cfg_name in cfg_names:
            lat = config_results[cfg_name].get("avg_latency_ms", "N/A")
            md.append(f"- **{cfg_name}**: {lat:.1f} ms" if isinstance(lat, float) else f"- **{cfg_name}**: {lat}")
        md.append("")

    report = "\n".join(md)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

    return report
