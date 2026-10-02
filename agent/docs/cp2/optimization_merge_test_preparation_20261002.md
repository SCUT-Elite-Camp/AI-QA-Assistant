# G1/G2 English test preparation — 2026-10-02

本地以 `origin/agent-dev-infra` 的 `7bb9687` 为基础合并 `origin/optimization` 的 `242120b`。保留 Deep Research 的计划、审批、证据、报告、任务恢复及评测能力，同时接入 optimization 的 Chat、检索、权限、私有资料和新版 frontend。原来的 Research 页面与组件已迁入 `frontend`。

## 英文优先

- 新数据集：`eval/deep_research_a/datasets/cases.en.v1.json`，18 个英文问题，英文评分事实及禁止声明，报告语言 `en-US`。
- 新资料清单：`eval/deep_research_a/manifests/source_manifests.en.v1.json`，更新英文问题哈希，保留原资料范围、内容哈希、版本和引用定位。
- 涉及的 14 份资料全部以英文为主；全部资料哈希校验通过。
- 历史中文数据集与资料清单保留，新一轮结果建立独立英文基线，不直接与旧中文得分比较。
- Research 默认报告语言、英文任务规划、缺少证据时的报告回退和模型异常恢复提示均支持英文。历史中文回归用例显式指定中文。
- 本地英文向量模型 `BAAI/bge-small-en-v1.5` 为 384 维，与现有 Milvus `doc_chunks` 的 1,292 条向量记录匹配。未重建或覆盖 Milvus。

## 当前配置和验证

配置来自 Git 忽略的 `agent/.env`。用户的 API key 保留，模型为 `qwen3.6-flash`，Base URL 为用户指定的阿里云兼容接口。未配置分阶段替代模型，未启用隐式模型降级。一次极小英文连通性请求返回 HTTP 200。

Docker 的 Milvus、etcd、MinIO 已启动。本地 Agent 测试服务地址 `http://127.0.0.1:8010`，`/health` 正常、`/ready` 检索就绪。frontend 的本地配置已指向该服务，共享密钥保存在忽略的 `.env` 中。

验证结果：后端、toolset 和评测资产全套 665 项通过；新增英文专项 3 项通过；前端 186 项通过，类型检查及 Vite/Nitro 生产构建通过。日志在 `outputs/optimization_g1_g2_preparation_20261002/`。

## 启动和运行

在项目根目录的两个 PowerShell 终端执行。服务已运行时不要重复启动：

```powershell
& D:/miniconda3/envs/htc_qa/python.exe -X utf8 agent/scripts/g1_g2_english.py check
& D:/miniconda3/envs/htc_qa/python.exe -X utf8 agent/scripts/g1_g2_english.py serve
```

服务 ready 后，在另一个终端启动完整英文 G1/G2：

```powershell
& D:/miniconda3/envs/htc_qa/python.exe -X utf8 agent/scripts/g1_g2_english.py run --parallel-groups --output-dir outputs/g1_g2_english_full_fixed_20261002
```

共 `18 × 2 × 3 = 108` 次，只有 G1 `fast_chat` 和 G2 `deep_research_current`。使用独立的研究任务数据库与 checkpoint，防止恢复旧队列。输出位于 `outputs/g1_g2_english_20261002/`，保存配置、资料清单、原始响应和运行记录。下次新实验请给 serve/check/run 指定同一个新的 `--output-dir`。

The English pilot and targeted summary rerun have completed. A full attempt produced 23 records before a document-discovery evidence issue was found and the batch was stopped. That issue is patched and covered by 634 passing regression tests. Online revalidation and the replacement 108-run batch are blocked by Aliyun HTTP 403 AccessDenied.Unpurchased. See `outputs/g1_g2_english_status_20261002.md` for the preserved partial scores and resume steps.

## 比较边界

G1 实际使用 Milvus/BM25 混合检索；G2 当前使用冻结本地 JSON 资料检索。配置明确记录这个差异，因此这轮比较反映现有两条产品链路，不宣称使用完全一致的检索后端。G3 Page Index 未纳入本次运行。

单独调用 A-side 评分脚本时，要同时选择英文资产，避免误用历史中文问题哈希和匹配规则：

```powershell
$env:DR_EVAL_DATASET_PATH = 'D:/htc_qa/eval/deep_research_a/datasets/cases.en.v1.json'
$env:DR_EVAL_MANIFEST_PATH = 'D:/htc_qa/eval/deep_research_a/manifests/source_manifests.en.v1.json'
```

历史 `frozen_baseline.json` 是旧实现的溯源记录；新模型和代码配置以当前实验目录的 `config/frozen_environment.json` 为准。密钥、模型权重、数据库、备份及运行日志均不应提交。

## Online pilot fixes and resume

- Test retrieval selects a separate 1,172-chunk BM25 index through `BM25_INDEX_PATH`; the original index is preserved.
- Benchmark request timeout is 300 seconds; automatic chat-title generation is disabled for evaluation requests.
- Independent groups can run in parallel; requests inside each group remain sequential.
- Answer repair preserves citation numbers when selecting evidence subsets. Factual answers require source chunks instead of document-discovery summaries.
- Same-model judging is authorized. Use `agent/scripts/review_g1_g2_english.py <experiment-directory> --judge` after generation.
- Before the replacement run, restore model access and repeat the DR-A-003 three-repetition pilot. The denied pilot does not establish answer quality.
- Start `serve` and `run` with the same fresh output directory. The suggested replacement directory is `outputs/g1_g2_english_full_fixed_20261002`.
