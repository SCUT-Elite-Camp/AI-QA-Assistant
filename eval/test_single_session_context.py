import os
import sys
import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Force stdout/stderr to utf-8 encoding on Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Setup project root paths
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agent"))

API_URL = "http://127.0.0.1:8000/api/chat"
SESSION_ID = f"test_session_drift_{int(time.time())}"
LOG_DIR = project_root / "eval" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def send_chat_request(query: str, session_id: str, top_k: int = 3) -> dict:
    payload = {
        "query": query,
        "session_id": session_id,
        "top_k": top_k,
        "retrieval_mode": "bm25",
        "stream": False
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    
    start_t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            latency = time.time() - start_t
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
            res_json["latency_sec"] = round(latency, 2)
            return res_json
    except urllib.error.HTTPError as e:
        err_text = e.read().decode('utf-8')
        raise RuntimeError(f"HTTP {e.code} Error: {err_text}")
    except Exception as e:
        raise RuntimeError(f"Request failed: {e}")

def run_test():
    print("=" * 70)
    print("  AI-QA-Assistant 单次对话窗口上下文记忆与指令遵循能力测试")
    print("=" * 70)
    print(f"Session ID:  {SESSION_ID}")
    print(f"Target API:  {API_URL}")
    print(f"Log Dir:     {LOG_DIR}")
    print("-" * 70)

    turns_def = [
        {
            "turn": 1,
            "user_query": "你好，请记下以下项目信息：项目名称是 Project Titan，安全密钥是 TITAN-SECURE-9942，预算为 $750,000。另外，请遵守指令：你后续的每一次回答末尾都必须单独成行添加标签 `[TAG: SESSION_ACTIVE]`。请确认你已记住上述信息并理解指令。",
            "checks": {
                "tag_required": True,
                "facts_introduced": ["Project Titan", "TITAN-SECURE-9942", "$750,000"]
            }
        },
        {
            "turn": 2,
            "user_query": "请简要介绍一下人工智能在医疗领域的应用场景有哪些？（用2-3句话概述即可）",
            "checks": {
                "tag_required": True,
            }
        },
        {
            "turn": 3,
            "user_query": "请问我刚才提到的项目安全密钥是什么？",
            "checks": {
                "tag_required": True,
                "expected_fact": "TITAN-SECURE-9942"
            }
        },
        {
            "turn": 4,
            "user_query": "请从现在开始，回答任何问题都必须使用 Markdown 无序列表（- 开头）格式。请问 RAG 系统主要由哪几个核心步骤组成？",
            "checks": {
                "tag_required": True,
                "list_format_required": True
            }
        },
        {
            "turn": 5,
            "user_query": "请详细解释向量数据库索引算法 HNSW 的基本原理和优势。（请尽可能详细，说明底层图结构与搜索效率）",
            "checks": {
                "tag_required": True,
                "list_format_required": True
            }
        },
        {
            "turn": 6,
            "user_query": "现在验证之前的信息：请问我们项目叫什么名字？预算是多少？",
            "checks": {
                "tag_required": True,
                "expected_facts": ["Project Titan", "$750,000"]
            }
        },
        {
            "turn": 7,
            "user_query": "请再提醒我一下，项目安全密钥是什么？",
            "checks": {
                "tag_required": True,
                "expected_fact": "TITAN-SECURE-9942"
            }
        },
        {
            "turn": 8,
            "user_query": "简要说明软件开发中的 CI/CD 流程。",
            "checks": {
                "tag_required": True,
                "list_format_required": True
            }
        },
        {
            "turn": 9,
            "user_query": "请列出在最开始（第一轮对话中）我向你交代的所有项目基本信息（包括名称、密钥、预算）以及首个回答指令规则。",
            "checks": {
                "tag_required": True,
                "expected_facts": ["Project Titan", "TITAN-SECURE-9942", "$750,000"],
                "expected_instruction": "[TAG: SESSION_ACTIVE]"
            }
        },
        {
            "turn": 10,
            "user_query": "总结我们目前为止讨论的要点。",
            "checks": {
                "tag_required": True,
                "list_format_required": True
            }
        }
    ]

    results = []
    first_drift_turn = None

    for item in turns_def:
        turn_num = item["turn"]
        query = item["user_query"]
        checks = item["checks"]

        print(f"\n[Turn {turn_num}/10] 发送请求...")
        print(f"User > {query[:80]}..." if len(query) > 80 else f"User > {query}")

        try:
            res = send_chat_request(query, SESSION_ID)
            answer = res.get("answer", "")
            latency = res.get("latency_sec", 0)

            print(f"Assistant ({latency}s) > {answer[:120]}..." if len(answer) > 120 else f"Assistant ({latency}s) > {answer}")

            # Verification
            tag_pass = True
            if checks.get("tag_required"):
                tag_pass = "[TAG: SESSION_ACTIVE]" in answer

            list_pass = True
            if checks.get("list_format_required"):
                lines = [l.strip() for l in answer.strip().split("\n") if l.strip()]
                list_pass = any(l.startswith("- ") or l.startswith("-\t") for l in lines)

            fact_pass = True
            missing_facts = []
            if "expected_fact" in checks:
                target = checks["expected_fact"]
                if target.lower() not in answer.lower():
                    fact_pass = False
                    missing_facts.append(target)

            if "expected_facts" in checks:
                for target in checks["expected_facts"]:
                    if target.lower() not in answer.lower():
                        fact_pass = False
                        missing_facts.append(target)

            # Turn Status Determination
            turn_status = "PASS"
            drift_reasons = []

            if not fact_pass:
                turn_status = "DRIFT_FACT"
                drift_reasons.append(f"丢失事实记忆: {missing_facts}")
            
            if not tag_pass:
                if turn_status == "PASS":
                    turn_status = "DRIFT_INSTRUCTION"
                drift_reasons.append("未遵循标签指令 [TAG: SESSION_ACTIVE]")
                
            if not list_pass:
                if turn_status == "PASS":
                    turn_status = "DRIFT_INSTRUCTION"
                drift_reasons.append("未遵循列表格式指令")

            if turn_status != "PASS" and first_drift_turn is None:
                first_drift_turn = turn_num

            is_evicted = turn_num > 5

            tag_symbol = "[OK]" if tag_pass else "[FAIL]"
            list_symbol = "[OK]" if list_pass else ("N/A" if not checks.get('list_format_required') else "[FAIL]")
            fact_symbol = "[OK]" if fact_pass else "[FAIL]"

            print(f"  --> Status: {turn_status} | Tag: {tag_symbol} | ListFormat: {list_symbol} | FactRecall: {fact_symbol}")
            if drift_reasons:
                print(f"      [飘逸详情]: {'; '.join(drift_reasons)}")
            if is_evicted:
                print(f"      [内存窗口注记]: 第{turn_num}轮消息已超过短时记忆容量上限 (MAX_MEMORY_MESSAGES=10)，首轮对话已被挤出窗口！")

            turn_result = {
                "turn": turn_num,
                "user_query": query,
                "assistant_answer": answer,
                "latency_sec": latency,
                "checks": checks,
                "tag_pass": tag_pass,
                "list_pass": list_pass,
                "fact_pass": fact_pass,
                "missing_facts": missing_facts,
                "turn_status": turn_status,
                "drift_reasons": drift_reasons,
                "memory_evicted": is_evicted,
                "trace_id": res.get("trace_id", "")
            }
            results.append(turn_result)

        except Exception as e:
            print(f"  [ERROR] Turn {turn_num}: {e}")
            results.append({
                "turn": turn_num,
                "user_query": query,
                "error": str(e),
                "turn_status": "ERROR"
            })

    # Summary
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = LOG_DIR / f"single_session_context_test_{timestamp_str}.json"
    md_path = LOG_DIR / f"single_session_context_test_{timestamp_str}.md"

    summary_data = {
        "session_id": SESSION_ID,
        "timestamp": timestamp_str,
        "total_turns": len(turns_def),
        "first_drift_turn": first_drift_turn,
        "passed_turns": sum(1 for r in results if r.get("turn_status") == "PASS"),
        "results": results
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # Generate Markdown log
    md_content = f"# 单次对话窗口上下文记忆与指令遵循能力测试报告\n\n"
    md_content += f"- **测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    md_content += f"- **Session ID**: `{SESSION_ID}`\n"
    md_content += f"- **总测试轮次**: {len(turns_def)}\n"
    md_content += f"- **通过轮次**: {summary_data['passed_turns']} / {len(turns_def)}\n"
    md_content += f"- **首次出现飘逸/失效轮次**: Turn {first_drift_turn if first_drift_turn else '无（全通过）'}\n\n"
    md_content += f"## 详细对话与验证记录\n\n"

    for r in results:
        t = r["turn"]
        status_icon = "PASS" if r.get("turn_status") == "PASS" else f"DRIFT: {r.get('turn_status')}"
        md_content += f"### Turn {t} [{status_icon}]\n"
        md_content += f"**User**:\n```text\n{r['user_query']}\n```\n\n"
        if "error" in r:
            md_content += f"**Error**: `{r['error']}`\n\n"
        else:
            missing_str = ", ".join(r["missing_facts"])
            reasons_str = "; ".join(r["drift_reasons"])
            md_content += f"**Assistant** (耗时: {r['latency_sec']}s):\n```text\n{r['assistant_answer']}\n```\n\n"
            md_content += f"**自动评估断言**:\n"
            md_content += f"- 标签指令 `[TAG: SESSION_ACTIVE]`: {'✓' if r['tag_pass'] else '❌ 未按要求包含'}\n"
            if r['checks'].get('list_format_required'):
                md_content += f"- 列表格式指令: {'✓' if r['list_pass'] else '❌ 未按要求格式输出'}\n"
            if 'expected_fact' in r['checks'] or 'expected_facts' in r['checks']:
                md_content += f"- 事实召回保留: {'✓ 成功回忆' if r['fact_pass'] else f'❌ 缺失要素 ({missing_str})'}\n"
            if r['memory_evicted']:
                md_content += f"- 内存状态: ⚠️ 已超出 MAX_MEMORY_MESSAGES=10 限制，早期上下文被从内存队列中清理\n"
            if r['drift_reasons']:
                md_content += f"- **飘逸原因**: {reasons_str}\n"
            md_content += "\n---\n\n"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print("\n" + "=" * 70)
    print("  测试完成！数据已持久化保存:")
    print(f"  JSON 日志: {json_path}")
    print(f"  MD 报告:   {md_path}")
    print("=" * 70)

if __name__ == "__main__":
    run_test()
