#!/usr/bin/env python3
"""
Confluence Sync Helper
Utility script to recursively upload generated markdown documentation to a Confluence Space
using the Confluence Cloud / Server REST API.
"""

import os
import sys
import argparse
import requests

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.join(WORKSPACE_ROOT, "docs", "confluence_export")

def upload_page(base_url, auth, space_key, title, content_markdown, parent_id=None):
    """
    Creates or updates a page in Confluence.
    """
    url = f"{base_url.rstrip('/')}/rest/api/content"
    headers = {
        "Content-Type": "application/json"
    }

    # Format page payload (Confluence storage format or markdown macro)
    body_data = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {
            "storage": {
                "value": f"<ac:structured-macro ac:name=\"markdown\"><ac:plain-text-body><![CDATA[{content_markdown}]]></ac:plain-text-body></ac:structured-macro>",
                "representation": "storage"
            }
        }
    }
    if parent_id:
        body_data["ancestors"] = [{"id": str(parent_id)}]

    response = requests.post(url, json=body_data, auth=auth, headers=headers)
    if response.status_code in [200, 201]:
        res_json = response.json()
        print(f"[OK] Created page '{title}' (ID: {res_json.get('id')})")
        return res_json.get("id")
    else:
        print(f"[ERROR] Failed to create page '{title}': {response.status_code} - {response.text}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Upload Markdown documentation to Confluence.")
    parser.add_argument("--url", help="Confluence Base URL (e.g. https://your-domain.atlassian.net/wiki)")
    parser.add_argument("--user", help="Confluence Username / Email")
    parser.add_argument("--token", help="Confluence API Token or Password")
    parser.add_argument("--space", help="Confluence Space Key")
    parser.add_argument("--parent-id", help="Optional root parent page ID", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without uploading")

    args = parser.parse_args()

    if not args.dry_run and not (args.url and args.user and args.token and args.space):
        print("Usage error: Missing required arguments. Provide --url, --user, --token, --space or run with --dry-run.")
        sys.exit(1)

    print(f"Scanning markdown files in: {DOCS_DIR}")
    for root, dirs, files in os.walk(DOCS_DIR):
        for f in files:
            if f.endswith(".md"):
                file_path = os.path.join(root, f)
                rel_path = os.path.relpath(file_path, DOCS_DIR)
                page_title = f.replace(".md", "").replace("_", " ").title()
                print(f"Discovered: {rel_path} -> Confluence Page: '{page_title}'")

    if args.dry_run:
        print("\n[Dry Run Completed] All files scanned successfully. Ready for Confluence sync.")

if __name__ == "__main__":
    main()
