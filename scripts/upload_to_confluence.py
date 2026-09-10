import os
import sys
import time
import requests
import markdown

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.join(WORKSPACE_ROOT, "docs", "confluence_export")

BASE_URL = "https://huifengagent.atlassian.net/wiki"
SPACE_KEY = "RAG"
EMAIL = "784019158@qq.com"
API_TOKEN = "ATATT3xFfGF0gdYiW3We20WRC2m6DXFnkd9pvLnl22_ZZROgLbguKUzC4mn7j3ynTJGTySK5jf-RqEjGRuss9EZHTvawC-Q_RGh4_nRozpKGFYXJdwZanN1-63wJyQ8SQI3pv6aJ2aGUgxefSgYUAfAl6w_e2SrPzhRC2RljexrstK91lcbrg4Q=E7F139C8"
AUTH = (EMAIL, API_TOKEN)

def md_to_html(md_text):
    html = markdown.markdown(
        md_text,
        extensions=['tables', 'fenced_code', 'nl2br', 'sane_lists']
    )
    return html

def find_page_by_title(title):
    url = f"{BASE_URL}/rest/api/content"
    params = {
        "title": title,
        "spaceKey": SPACE_KEY,
        "expand": "version"
    }
    r = requests.get(url, params=params, auth=AUTH)
    if r.status_code == 200:
        results = r.json().get("results", [])
        if results:
            return results[0]
    return None

def create_or_update_page(title, md_content, parent_id=None):
    html_content = md_to_html(md_content)
    existing = find_page_by_title(title)
    
    headers = {"Content-Type": "application/json"}
    
    if existing:
        page_id = existing["id"]
        current_version = existing["version"]["number"]
        payload = {
            "id": page_id,
            "type": "page",
            "title": title,
            "space": {"key": SPACE_KEY},
            "body": {
                "storage": {
                    "value": html_content,
                    "representation": "storage"
                }
            },
            "version": {
                "number": current_version + 1
            }
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
            
        r = requests.put(f"{BASE_URL}/rest/api/content/{page_id}", json=payload, auth=AUTH, headers=headers)
        if r.status_code in [200, 201]:
            print(f"[UPDATED] '{title}' (ID: {page_id})")
            return page_id
        else:
            print(f"[ERROR UPDATE] '{title}': {r.status_code} - {r.text}")
            return page_id
    else:
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": SPACE_KEY},
            "body": {
                "storage": {
                    "value": html_content,
                    "representation": "storage"
                }
            }
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
            
        r = requests.post(f"{BASE_URL}/rest/api/content", json=payload, auth=AUTH, headers=headers)
        if r.status_code in [200, 201]:
            page_id = r.json().get("id")
            print(f"[CREATED] '{title}' (ID: {page_id})")
            return page_id
        else:
            print(f"[ERROR CREATE] '{title}': {r.status_code} - {r.text}")
            return None

def get_space_homepage_id():
    r = requests.get(f"{BASE_URL}/rest/api/space/{SPACE_KEY}?expand=homepage", auth=AUTH)
    if r.status_code == 200:
        return r.json().get("homepage", {}).get("id")
    return None

def main():
    print(f"Connecting to Confluence space '{SPACE_KEY}' at {BASE_URL}...")
    homepage_id = get_space_homepage_id()
    print(f"Space Homepage ID: {homepage_id}")

    # 1. Create Root Parent Folder Page
    root_title = "AI-QA-Assistant Project Engineering Records & Sprints"
    root_md = """# AI-QA-Assistant Project Engineering Records & Sprint Deliverables

> **Documentation Hub**: Comprehensive Historical & Sprint Records for AI-QA-Assistant.
> **Project Scope**: 5 Parallel Development Modules + Evaluation & Infrastructure.

---

## Documentation Directory Structure

This documentation knowledge base is organized into three main sections:

1. **00. Project Overall Records & Milestones**: High-level roadmaps, system architecture evolution, cross-module delivery matrix, and changelog.
2. **01. Weekly Agile Sprints (W23 - W34)**: Detailed week-by-week sprint delivery reports and individual module breakdown pages.
3. **02. Module Lifecycle Archives**: Long-term vertical evolution histories for each of the 5 core modules and the evaluation suite.
"""
    root_id = create_or_update_page(root_title, root_md, parent_id=homepage_id)
    if not root_id:
        print("Failed to create root parent page. Aborting.")
        return

    # 2. Section 00: Overall Records
    sec0_title = "00. Project Overall Records & Milestones"
    sec0_md = "# 00. Project Overall Records & Milestones\n\nHigh-level architectural evolution, milestones, delivery matrix, and master changelog."
    sec0_id = create_or_update_page(sec0_title, sec0_md, parent_id=root_id)
    
    overall_files = [
        ("01_project_milestones_and_roadmap.md", "01. Project Milestones & Delivery Roadmap"),
        ("02_system_architecture_evolution.md", "02. System Architecture Evolution"),
        ("03_cross_module_delivery_matrix.md", "03. Cross-Module Delivery Matrix"),
        ("04_release_changelog_and_artifacts.md", "04. Release Changelog & Artifacts Archive")
    ]
    for filename, page_title in overall_files:
        fpath = os.path.join(DOCS_DIR, "00_overall", filename)
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            create_or_update_page(page_title, content, parent_id=sec0_id)
            time.sleep(0.3)

    # 3. Section 01: Weekly Sprints
    sec1_title = "01. Weekly Agile Sprints (W23 - W34)"
    sec1_md = "# 01. Weekly Agile Sprints (W23 - W34)\n\nWeekly sprint packages containing master sprint reports and per-module deliverables."
    sec1_id = create_or_update_page(sec1_title, sec1_md, parent_id=root_id)

    sprints_dir = os.path.join(DOCS_DIR, "01_weekly_sprints")
    sprint_folders = sorted(os.listdir(sprints_dir))

    for folder in sprint_folders:
        folder_path = os.path.join(sprints_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        
        w_upper = folder.upper()
        master_file = [f for f in os.listdir(folder_path) if f.startswith("00_w") and f.endswith(".md")]
        if not master_file:
            continue
            
        master_path = os.path.join(folder_path, master_file[0])
        with open(master_path, "r", encoding="utf-8") as f:
            master_content = f.read()
            
        sprint_page_title = f"Sprint {w_upper} Master Delivery Report"
        sprint_page_id = create_or_update_page(sprint_page_title, master_content, parent_id=sec1_id)
        time.sleep(0.3)

        # Upload module child pages under this sprint
        module_files = [
            ("m1_agent", f"Sprint {w_upper} - M1 Agent Module Deliverables"),
            ("m2_data_persistence", f"Sprint {w_upper} - M2 Data Persistence Module Deliverables"),
            ("m3_data_pipeline", f"Sprint {w_upper} - M3 Data Pipeline Module Deliverables"),
            ("m4_toolset", f"Sprint {w_upper} - M4 Toolset Module Deliverables"),
            ("m5_web", f"Sprint {w_upper} - M5 Web Module Deliverables")
        ]
        
        for key, mod_title in module_files:
            target_f = [f for f in os.listdir(folder_path) if key in f and f.endswith(".md")]
            if target_f:
                m_path = os.path.join(folder_path, target_f[0])
                with open(m_path, "r", encoding="utf-8") as f:
                    m_content = f.read()
                create_or_update_page(mod_title, m_content, parent_id=sprint_page_id)
                time.sleep(0.3)

    # 4. Section 02: Module Lifecycles
    sec2_title = "02. Module Lifecycle Archives"
    sec2_md = "# 02. Module Lifecycle Archives\n\nLong-term evolutionary records for each module."
    sec2_id = create_or_update_page(sec2_title, sec2_md, parent_id=root_id)

    life_dir = os.path.join(DOCS_DIR, "02_module_lifecycles")
    life_files = [
        ("m1_agent_lifecycle_archive.md", "M1 - Agent Module Lifecycle Archive"),
        ("m2_data_persistence_lifecycle_archive.md", "M2 - Data Persistence Module Lifecycle Archive"),
        ("m3_data_pipeline_lifecycle_archive.md", "M3 - Data Pipeline Module Lifecycle Archive"),
        ("m4_toolset_lifecycle_archive.md", "M4 - Toolset Module Lifecycle Archive"),
        ("m5_web_lifecycle_archive.md", "M5 - Web Module Lifecycle Archive"),
        ("m6_eval_and_benchmarking_lifecycle_archive.md", "M6 - Eval & Benchmarking Lifecycle Archive")
    ]
    for filename, page_title in life_files:
        fpath = os.path.join(life_dir, filename)
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            create_or_update_page(page_title, content, parent_id=sec2_id)
            time.sleep(0.3)

    print("\n[SUCCESS] All documentation pages uploaded to Confluence successfully!")

if __name__ == "__main__":
    main()
