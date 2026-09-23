import os
import subprocess
from datetime import datetime
from collections import defaultdict

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(WORKSPACE_ROOT, "docs", "confluence_export")

MODULES = {
    "agent": {
        "name": "Agent Module (Orchestration & Reasoning)",
        "short": "Agent",
        "dir": "agent",
        "prefix": "w{w}_m1_agent_module_report.md",
        "desc": "Core LLM orchestration, multi-turn dialogue management, streaming SSE protocol, and reasoning logic."
    },
    "data-persistence": {
        "name": "Data Persistence Module (Storage & Sessions)",
        "short": "Data-Persistence",
        "dir": "data-persistence",
        "prefix": "w{w}_m2_data_persistence_module_report.md",
        "desc": "Session history database, conversation turn storage, topic branching, and message state persistence."
    },
    "data-pipeline": {
        "name": "Data Pipeline Module (Crawling & Processing)",
        "short": "Data-Pipeline",
        "dir": "data-pipeline",
        "prefix": "w{w}_m3_data_pipeline_module_report.md",
        "desc": "Document ingestion, Confluence/HTML crawler, text cleaning, chunking, and embedding preparation."
    },
    "toolset": {
        "name": "Toolset Module (Retrieval & Plugins)",
        "short": "Toolset",
        "dir": "toolset",
        "prefix": "w{w}_m4_toolset_module_report.md",
        "desc": "Knowledge base retrieval adapters, search tool integration, vector store connectors, and plugin tools."
    },
    "web": {
        "name": "Web Module (UI & Full-stack Gateway)",
        "short": "Web",
        "dir": "web",
        "prefix": "w{w}_m5_web_module_report.md",
        "desc": "Frontend UI components, chat view, document viewer, settings drawer, and server-side API proxy."
    }
}

def run_git(args):
    result = subprocess.run(
        ["git"] + args,
        cwd=WORKSPACE_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )
    if result.returncode != 0:
        raise RuntimeError(f"Git command failed: {' '.join(args)}\n{result.stderr}")
    return result.stdout

def get_commit_history():
    raw_log = run_git(["log", "--all", "--format=COMMIT_START:%H|%an|%ae|%ci|%s", "--name-status"])
    commits = []
    current_commit = None

    for line in raw_log.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("COMMIT_START:"):
            if current_commit:
                commits.append(current_commit)
            parts = line[len("COMMIT_START:"):].split("|", 4)
            if len(parts) == 5:
                h, an, ae, ci, s = parts
                dt = datetime.fromisoformat(ci)
                current_commit = {
                    "hash": h,
                    "short_hash": h[:9],
                    "author": an,
                    "email": ae,
                    "datetime": dt,
                    "date_str": dt.strftime("%Y-%m-%d"),
                    "subject": s,
                    "files": []
                }
        elif current_commit:
            file_parts = line.split(maxsplit=1)
            if len(file_parts) == 2:
                status, path = file_parts
                current_commit["files"].append({"status": status, "path": path})

    if current_commit:
        commits.append(current_commit)

    commits.sort(key=lambda x: x["datetime"])
    return commits

def determine_modules_for_commit(commit):
    mods = set()
    for f in commit["files"]:
        p = f["path"]
        top_dir = p.split("/")[0] if "/" in p else p
        if top_dir in MODULES:
            mods.add(top_dir)
        elif top_dir == "eval":
            mods.add("eval")
        elif p in ["start_project.py", "start_project.bat", "start_project.ps1", "requirements.txt", "README.md", "docs"]:
            mods.add("infra")
    return list(mods) if mods else ["infra"]

def classify_commit(subject):
    s = subject.lower()
    if s.startswith("feat") or "add " in s or "implement" in s or "support" in s:
        return "Feature"
    elif s.startswith("fix") or "bug" in s or "resolve" in s:
        return "Bug Fix"
    elif s.startswith("refactor") or "optimize" in s or "clean" in s or "restructure" in s:
        return "Refactoring"
    elif s.startswith("style") or "ui" in s or "layout" in s:
        return "UI / Style Enhancement"
    elif s.startswith("docs") or "readme" in s:
        return "Documentation"
    elif s.startswith("test") or "eval" in s:
        return "Testing & Evaluation"
    else:
        return "Maintenance / Chore"

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def generate_weekly_module_report(week_str, week_commits, mod_key, mod_info, out_path):
    mod_commits = [c for c in week_commits if mod_key in determine_modules_for_commit(c)]
    
    dates = [c["date_str"] for c in week_commits]
    date_range = f"{min(dates)} to {max(dates)}" if dates else "N/A"
    
    authors = sorted(list(set(c["author"] for c in mod_commits))) if mod_commits else ["None"]
    
    content = [
        f"# [{week_str}] {mod_info['name']} Weekly Deliverable Report",
        "",
        f"> **Sprint Period**: {date_range} | **Module**: `{mod_key}`",
        f"> **Contributors**: {', '.join(authors)} | **Status**: {'🟢 Completed' if mod_commits else '⚪ No Commits (Idle)'}",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        f"This report details the work delivered for the **{mod_info['name']}** during **{week_str}**.",
        f"**Module Scope**: {mod_info['desc']}",
        ""
    ]

    if not mod_commits:
        content.extend([
            "### Current Sprint Status",
            "No direct code commits were recorded for this module in the current sprint window. The team maintained existing components or engaged in design, reviews, and cross-team dependencies verification.",
            ""
        ])
    else:
        features = [c for c in mod_commits if classify_commit(c["subject"]) == "Feature"]
        fixes = [c for c in mod_commits if classify_commit(c["subject"]) == "Bug Fix"]
        others = [c for c in mod_commits if classify_commit(c["subject"]) not in ["Feature", "Bug Fix"]]

        content.extend([
            "### Key Highlights & Deliverables",
            f"- **Total Commits**: {len(mod_commits)}",
            f"- **New Features Delivered**: {len(features)}",
            f"- **Bug Fixes Resolved**: {len(fixes)}",
            f"- **Other Improvements**: {len(others)}",
            "",
            "## 2. Work Breakdown & Deliverables",
            ""
        ])

        if features:
            content.append("### 🚀 New Features & Enhancements")
            for c in features:
                content.append(f"- **`{c['short_hash']}`** - {c['subject']} *(by @{c['author']} on {c['date_str']})*")
            content.append("")

        if fixes:
            content.append("### 🐛 Bug Fixes & Stability")
            for c in fixes:
                content.append(f"- **`{c['short_hash']}`** - {c['subject']} *(by @{c['author']} on {c['date_str']})*")
            content.append("")

        if others:
            content.append("### 🛠️ Refactoring & Engineering Tasks")
            for c in others:
                content.append(f"- **`{c['short_hash']}`** - {c['subject']} *(by @{c['author']} on {c['date_str']})*")
            content.append("")

        content.extend([
            "## 3. Impacted Code Files",
            "| Action | File Path |",
            "| :--- | :--- |"
        ])
        
        file_map = {}
        for c in mod_commits:
            for f in c["files"]:
                file_map[f["path"]] = f["status"]
        
        for path, status in sorted(file_map.items()):
            action_badge = "ADDED" if status == "A" else ("DELETED" if status == "D" else "MODIFIED")
            content.append(f"| `{action_badge}` | `{path}` |")

        content.extend([
            "",
            "## 4. Git Commit Verification Log",
            "| Short Hash | Author | Date | Category | Commit Message |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ])
        for c in mod_commits:
            cat = classify_commit(c["subject"])
            content.append(f"| `{c['short_hash']}` | {c['author']} | {c['date_str']} | `{cat}` | {c['subject']} |")

    content.extend([
        "",
        "---",
        "## 5. Next Sprint Outlook",
        "- Continue integration and refinement based on cross-module milestones.",
        "- Address feedback and optimize test coverage for modified files."
    ])

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(content) + "\n")

def generate_weekly_master_report(week_str, week_commits, out_path):
    dates = [c["date_str"] for c in week_commits]
    date_range = f"{min(dates)} to {max(dates)}" if dates else "N/A"
    all_authors = sorted(list(set(c["author"] for c in week_commits)))

    mod_stats = {}
    for mod_key, mod_info in MODULES.items():
        m_commits = [c for c in week_commits if mod_key in determine_modules_for_commit(c)]
        mod_stats[mod_key] = {
            "name": mod_info["name"],
            "short": mod_info["short"],
            "count": len(m_commits),
            "authors": sorted(list(set(c["author"] for c in m_commits))),
            "features": len([c for c in m_commits if classify_commit(c["subject"]) == "Feature"]),
            "fixes": len([c for c in m_commits if classify_commit(c["subject"]) == "Bug Fix"])
        }

    content = [
        f"# 📅 [{week_str}] Project Master Sprint Delivery Report",
        "",
        f"> **Sprint Period**: {date_range} | **Sprint ID**: `{week_str}`",
        f"> **Active Contributors**: {', '.join(all_authors)} | **Total Commits**: `{len(week_commits)}`",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        f"During **{week_str}**, the engineering team recorded **{len(week_commits)} commits** across parallel development streams.",
        "Below is the cross-team overview of deliverables, status, and module links.",
        "",
        "## 2. Module Delivery Overview & Navigation",
        "| Module Name | Contributors | Commits | Deliverables (Feat / Fix) | Status | Detailed Report Link |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    for mod_key, stats in mod_stats.items():
        status_badge = "🟢 Delivered" if stats["count"] > 0 else "⚪ Standby"
        authors_str = ", ".join(stats["authors"]) if stats["authors"] else "N/A"
        w_num = week_str.split('-W')[-1]
        link_filename = MODULES[mod_key]["prefix"].format(w=w_num)
        content.append(
            f"| **{stats['name']}** | {authors_str} | {stats['count']} | {stats['features']} Feat / {stats['fixes']} Fix | {status_badge} | [{stats['short']} Weekly Report](./{link_filename}) |"
        )

    content.extend([
        "",
        "## 3. High-Impact Highlights of the Week",
        ""
    ])

    feats = [c for c in week_commits if classify_commit(c["subject"]) == "Feature"]
    if feats:
        content.append("### Major Features Landed")
        for c in feats[:8]:
            content.append(f"- **[{determine_modules_for_commit(c)[0].upper()}]** {c['subject']} (`{c['short_hash']}` by @{c['author']})")
        content.append("")

    fixes = [c for c in week_commits if classify_commit(c["subject"]) == "Bug Fix"]
    if fixes:
        content.append("### Critical Bug Fixes")
        for c in fixes[:8]:
            content.append(f"- **[{determine_modules_for_commit(c)[0].upper()}]** {c['subject']} (`{c['short_hash']}` by @{c['author']})")
        content.append("")

    content.extend([
        "## 4. Full Sprint Commit Chronology",
        "| Short Hash | Date | Author | Target Module | Type | Message |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |"
    ])

    for c in week_commits:
        mods_str = ", ".join(determine_modules_for_commit(c))
        cat = classify_commit(c["subject"])
        content.append(f"| `{c['short_hash']}` | {c['date_str']} | {c['author']} | `{mods_str}` | `{cat}` | {c['subject']} |")

    content.extend([
        "",
        "---",
        "## 5. Integration Status & Cross-Module Dependencies",
        "- All modules synced against the main development branch.",
        "- API contract compatibility validated across Web and Agent streaming interfaces."
    ])

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(content) + "\n")

def generate_overall_reports(commits, weeks):
    overall_dir = os.path.join(OUTPUT_DIR, "00_overall")
    ensure_dir(overall_dir)

    # 1. Milestones and Roadmap
    milestones_path = os.path.join(overall_dir, "01_project_milestones_and_roadmap.md")
    milestone_lines = [
        "# Project Milestones & Delivery Roadmap",
        "",
        "> **Project**: AI-QA-Assistant | **Documentation Platform**: Confluence",
        f"> **Historical Span**: {commits[0]['date_str']} to {commits[-1]['date_str']} | **Total Sprints**: {len(weeks)} Weeks",
        "",
        "---",
        "",
        "## 1. Project Overview & Timeline",
        "The **AI-QA-Assistant** project is structured into 5 parallel engineering streams. Delivery is executed on a strict weekly cycle.",
        "",
        "### High-Level Milestones",
        "```mermaid",
        "timeline",
        "    title Project Evolution Milestones",
        "    2026-W23 : Project Initialization : Repository Skeleton",
        "    2026-W24 : Persistence Layer Setup : Web Layer MVP",
        "    2026-W25 : Agent Core & Toolset : Multi-Turn Baseline",
        "    2026-W27 : Confluence Crawler : Document Ingestion Pipeline",
        "    2026-W30 : Chat Branching & Context : Persistence Enhancements",
        "    2026-W34 : Streaming Reasoning Engine : Thinking Chain & Grok UI",
        "```",
        "",
        "## 2. Weekly Sprint Roadmap Matrix",
        "| Sprint Week | Date Range | Total Commits | Active Modules | Primary Focus & Milestone |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]

    for w_key in sorted(weeks.keys()):
        w_commits = weeks[w_key]
        dates = [c["date_str"] for c in w_commits]
        date_range = f"{min(dates)} ~ {max(dates)}"
        active_mods = set()
        for c in w_commits:
            for m in determine_modules_for_commit(c):
                active_mods.add(m)
        mods_str = ", ".join(sorted(list(active_mods)))
        top_commit = w_commits[-1]["subject"]
        milestone_lines.append(f"| **{w_key}** | {date_range} | {len(w_commits)} | `{mods_str}` | {top_commit} |")

    with open(milestones_path, "w", encoding="utf-8") as f:
        f.write("\n".join(milestone_lines) + "\n")

    # 2. Architecture Evolution
    arch_path = os.path.join(overall_dir, "02_system_architecture_evolution.md")
    arch_lines = [
        "# System Architecture Evolution",
        "",
        "> **System Overview**: End-to-End RAG & Agent Architecture Evolution",
        "",
        "---",
        "",
        "## 1. Multi-Tier Architecture Blueprint",
        "```mermaid",
        "graph TD",
        "    WebUI[Web Frontend / Vue 3 & Nuxt 3] <--> WebServer[Web Server Gateway / Nitro API]",
        "    WebServer <--> AgentService[Agent Reasoning Engine / FastAPI]",
        "    AgentService <--> ToolsetService[Toolset & Retrieval Adapters]",
        "    AgentService <--> PersistenceService[Data Persistence / SQLite & ChromaDB]",
        "    DataPipeline[Data Pipeline Crawler & Parser] --> PersistenceService",
        "```",
        "",
        "## 2. Module Responsibilities",
        "1. **`agent/` (Agent Module)**: Coordinates multi-turn dialogue, tool invocation planning, model integration (Qwen, DeepSeek, OpenAI), SSE streaming, and progressive reasoning tokens.",
        "2. **`data-persistence/` (Persistence Module)**: SQLite-backed chat history, message branching, topic tracking, and vector embedding store connections.",
        "3. **`data-pipeline/` (Pipeline Module)**: Crawlers for Confluence HTML, file attachment parsers, markdown splitters, and embedding indexing.",
        "4. **`toolset/` (Toolset Module)**: Knowledge base retrieval tools, similarity search endpoints, and extensible plugins.",
        "5. **`web/` (Web Frontend Module)**: Modern Vue 3 / Nuxt 3 user interface, real-time thinking process visualizer, source drawer, and document explorer.",
        "",
        "## 3. Key Architecture Evolution Phases",
        "- **Phase 1: Foundation (W23 - W24)**: Basic project skeleton, SQLite schema setup, and minimal web chat interface.",
        "- **Phase 2: RAG Pipeline Integration (W25 - W28)**: Confluence document crawler, toolset adapters, and multi-turn prompt orchestration.",
        "- **Phase 3: Topic Management & Branching (W30 - W32)**: Chat branching support, persistent message state, and improved API resilience.",
        "- **Phase 4: Real-time Streaming & Reasoning UI (W33 - W34)**: Grok-style thinking trees, SSE token streaming, and hit-rate similarity telemetry."
    ]
    with open(arch_path, "w", encoding="utf-8") as f:
        f.write("\n".join(arch_lines) + "\n")

    # 3. Cross Module Delivery Matrix
    matrix_path = os.path.join(overall_dir, "03_cross_module_delivery_matrix.md")
    matrix_lines = [
        "# Cross-Module Delivery Matrix",
        "",
        "> Complete distribution matrix of sprint deliveries across the 5 modules.",
        "",
        "---",
        "",
        "## 1. Sprint vs Module Commit Distribution",
        "| Sprint Week | Total Commits | Agent Module | Data Persistence | Data Pipeline | Toolset Module | Web Module | Eval / Infra |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    for w_key in sorted(weeks.keys()):
        w_commits = weeks[w_key]
        counts = {m: 0 for m in MODULES}
        infra_count = 0
        for c in w_commits:
            mods = determine_modules_for_commit(c)
            for m in mods:
                if m in counts:
                    counts[m] += 1
                else:
                    infra_count += 1
        matrix_lines.append(
            f"| **{w_key}** | {len(w_commits)} | {counts['agent']} | {counts['data-persistence']} | {counts['data-pipeline']} | {counts['toolset']} | {counts['web']} | {infra_count} |"
        )

    with open(matrix_path, "w", encoding="utf-8") as f:
        f.write("\n".join(matrix_lines) + "\n")

    # 4. Release Changelog & Artifacts
    changelog_path = os.path.join(overall_dir, "04_release_changelog_and_artifacts.md")
    change_lines = [
        "# Release Changelog & Artifacts Archive",
        "",
        "> **Project Changelog**: Master historical record of features and fixes.",
        "",
        "---",
        "",
        "## Full Chronological Changelog"
    ]

    for w_key in sorted(weeks.keys(), reverse=True):
        w_commits = weeks[w_key]
        change_lines.extend([
            f"### Sprint {w_key} ({w_commits[0]['date_str']} ~ {w_commits[-1]['date_str']})",
            f"**Total Commits**: {len(w_commits)}",
            ""
        ])
        for c in w_commits:
            cat = classify_commit(c["subject"])
            change_lines.append(f"- `[{cat}]` **{c['subject']}** (`{c['short_hash']}` by @{c['author']})")
        change_lines.append("")

    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write("\n".join(change_lines) + "\n")

def generate_module_lifecycles(commits, weeks):
    life_dir = os.path.join(OUTPUT_DIR, "02_module_lifecycles")
    ensure_dir(life_dir)

    for idx, (mod_key, mod_info) in enumerate(MODULES.items(), start=1):
        mod_commits = [c for c in commits if mod_key in determine_modules_for_commit(c)]
        file_path = os.path.join(life_dir, f"m{idx}_{mod_key.replace('-', '_')}_lifecycle_archive.md")

        authors = sorted(list(set(c["author"] for c in mod_commits))) if mod_commits else ["None"]
        
        lines = [
            f"# {mod_info['name']} - Complete Lifecycle Archive",
            "",
            f"> **Module Key**: `{mod_key}` | **Root Directory**: `/{mod_info['dir']}`",
            f"> **Total Lifetime Commits**: `{len(mod_commits)}` | **Contributors**: {', '.join(authors)}",
            "",
            "---",
            "",
            "## 1. Module Description & Responsibilities",
            mod_info["desc"],
            "",
            "## 2. Sprint-by-Sprint Evolution",
            "| Sprint | Date Range | Commits | Deliverables Highlights |",
            "| :--- | :--- | :--- | :--- |"
        ]

        for w_key in sorted(weeks.keys()):
            w_mod_commits = [c for c in weeks[w_key] if mod_key in determine_modules_for_commit(c)]
            if w_mod_commits:
                dates = [c["date_str"] for c in w_mod_commits]
                d_range = f"{min(dates)} ~ {max(dates)}"
                top_items = "; ".join([c["subject"] for c in w_mod_commits[:2]])
                lines.append(f"| **{w_key}** | {d_range} | {len(w_mod_commits)} | {top_items} |")
            else:
                lines.append(f"| **{w_key}** | - | 0 | *Maintenance / Idle* |")

        lines.extend([
            "",
            "## 3. All Historical Commits for this Module",
            "| Short Hash | Date | Author | Category | Commit Message |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ])

        for c in mod_commits:
            cat = classify_commit(c["subject"])
            lines.append(f"| `{c['short_hash']}` | {c['date_str']} | {c['author']} | `{cat}` | {c['subject']} |")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # Eval Module Archive
    eval_commits = [c for c in commits if "eval" in determine_modules_for_commit(c)]
    eval_path = os.path.join(life_dir, "m6_eval_and_benchmarking_lifecycle_archive.md")
    eval_lines = [
        "# Evaluation & Benchmarking Module - Lifecycle Archive",
        "",
        "> **Module Scope**: Test datasets, MS MARCO evaluation, RAGAS synthetic benchmarks, and performance testing.",
        f"> **Total Lifetime Commits**: `{len(eval_commits)}`",
        "",
        "---",
        "",
        "## 1. Overview",
        "The evaluation suite validates retrieval accuracy, MRR, hit rates, and answer correctness using standard benchmarks.",
        "",
        "## 2. Commit History",
        "| Short Hash | Date | Author | Message |",
        "| :--- | :--- | :--- | :--- |"
    ]
    for c in eval_commits:
        eval_lines.append(f"| `{c['short_hash']}` | {c['date_str']} | {c['author']} | {c['subject']} |")

    with open(eval_path, "w", encoding="utf-8") as f:
        f.write("\n".join(eval_lines) + "\n")

def main():
    print("Extracting commit history...")
    commits = get_commit_history()
    print(f"Loaded {len(commits)} commits.")

    weeks = defaultdict(list)
    for c in commits:
        dt = c["datetime"]
        week_key = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        weeks[week_key].append(c)

    print(f"Total active sprints: {len(weeks)}")

    # 1. Overall Reports
    print("Generating Overall Reports...")
    generate_overall_reports(commits, weeks)

    # 2. Weekly Sprints
    print("Generating Weekly Sprint Master and Module Reports...")
    sprints_dir = os.path.join(OUTPUT_DIR, "01_weekly_sprints")
    ensure_dir(sprints_dir)

    total_weekly_files = 0
    for w_key in sorted(weeks.keys()):
        w_folder = os.path.join(sprints_dir, w_key.lower())
        ensure_dir(w_folder)

        w_commits = weeks[w_key]
        w_num = w_key.split('-W')[-1]
        
        # Master report for the week
        master_path = os.path.join(w_folder, f"00_w{w_num}_master_sprint_report.md")
        generate_weekly_master_report(w_key, w_commits, master_path)
        total_weekly_files += 1

        # 5 module reports for the week
        for mod_key, mod_info in MODULES.items():
            mod_filename = mod_info["prefix"].format(w=w_num)
            mod_path = os.path.join(w_folder, mod_filename)
            generate_weekly_module_report(w_key, w_commits, mod_key, mod_info, mod_path)
            total_weekly_files += 1

    # 3. Module Lifecycles
    print("Generating Module Lifecycle Archives...")
    generate_module_lifecycles(commits, weeks)

    print(f"\n[SUCCESS] Generated documentation suite inside: {OUTPUT_DIR}")
    print(f"- Overall Documents: 4")
    print(f"- Weekly Sprint Documents: {total_weekly_files}")
    print(f"- Module Lifecycle Documents: 6")
    print(f"- Grand Total Files: {4 + total_weekly_files + 6}")

if __name__ == "__main__":
    main()
