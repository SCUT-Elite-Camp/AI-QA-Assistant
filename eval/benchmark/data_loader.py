"""基准数据集加载器

支持两种数据源:
1. 自包含内置数据集 (built-in): 从项目文档自动生成，无需网络
2. HuggingFace 数据集 (hf): 从 HuggingFace Hub 下载标准基准

内置数据集生成方法:
- 从 data-persistence/data/documents/ 读取已处理的文档
- 提取关键信息块作为"查询目标"
- 构造自然查询语句
- 标注 source document 为相关文档
- 输出为标准 corpus/queries/qrels 格式

评估协议与 MTEB/BEIR 一致: NDCG@K, Recall@K, MRR@K
"""

import json
import logging
import os
import random
import re
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

project_root = Path(__file__).resolve().parent.parent.parent

KNOWN_DATASETS = {
    "builtin-zh": {
        "type": "builtin",
        "description": "内置中文文档检索基准（从项目文档自动生成）",
    },
}


class BenchmarkDataset:
    """统一格式的检索基准数据集"""

    def __init__(self, name: str):
        self.name = name
        self.corpus: dict[str, str] = {}
        self.queries: dict[str, str] = {}
        self.qrels: dict[str, dict[str, int]] = {}
        self._loaded = False

    def load(
        self,
        max_docs: Optional[int] = None,
        num_queries: int = 50,
        seed: int = 42,
    ) -> "BenchmarkDataset":
        """加载数据集

        Args:
            max_docs: 限制语料库文档数
            num_queries: 生成查询数量（仅内置数据集）
            seed: 随机种子（仅内置数据集，确保可复现）

        Returns:
            self
        """
        if self._loaded:
            return self

        dataset_info = KNOWN_DATASETS.get(self.name)
        if dataset_info is None:
            raise ValueError(
                f"Unknown dataset: {self.name}. "
                f"Known: {list(KNOWN_DATASETS.keys())}"
            )

        if dataset_info["type"] == "builtin":
            self._load_builtin(max_docs=max_docs, num_queries=num_queries, seed=seed)
        else:
            raise ValueError(f"Unknown dataset type: {dataset_info['type']}")

        self._loaded = True
        return self

    def _load_builtin(
        self,
        max_docs: Optional[int] = None,
        num_queries: int = 50,
        seed: int = 42,
    ):
        """从项目文档生成内置基准数据集

        流程:
        1. 读取 data-persistence/data/documents/*.json
        2. 解析每个文档的 chunks
        3. 从 chunks 中采样/提取查询
        4. 标注 source doc 为相关

        查询生成规则（基于 chunk 内容，不依赖 LLM）:
        - 事实句→问题: "根据文档，{关键信息}是什么？"
        - 定义句→问题: "{术语}的定义是什么？"
        - 量化句→问题: "{实体}的{属性}是多少？"
        """
        import jieba

        rng = random.Random(seed)

        # 1. 加载文档
        docs_dir = project_root / "data-persistence" / "data" / "documents"
        if not docs_dir.exists():
            logger.warning(f"Documents dir not found: {docs_dir}")
            self._generate_fallback_dataset(rng)
            return

        doc_files = sorted(docs_dir.glob("*.json"))
        if not doc_files:
            logger.warning("No document JSON files found")
            self._generate_fallback_dataset(rng)
            return

        rng.shuffle(doc_files)
        if max_docs:
            doc_files = doc_files[:max_docs]

        logger.info(f"Loading {len(doc_files)} documents from {docs_dir}")

        # 2. 构建 corpus
        all_chunks = []  # [(doc_id, chunk_index, text)]

        for doc_file in doc_files:
            try:
                with open(doc_file, "r", encoding="utf-8") as f:
                    doc_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read {doc_file}: {e}")
                continue

            doc_id = doc_data.get("doc_id", doc_file.stem)
            chunks = doc_data.get("chunks", [])

            if not chunks:
                # 可能是整个文档文本
                content = doc_data.get("content", "")
                if content:
                    self.corpus[doc_id] = content

            for chunk in chunks:
                chunk_text = chunk.get("text", chunk.get("chunk_text", ""))
                if chunk_text:
                    chunk_idx = chunk.get("chunk_index", chunk.get("index", 0))
                    chunk_id = f"{doc_id}::chunk_{chunk_idx}"
                    self.corpus[chunk_id] = chunk_text
                    all_chunks.append((doc_id, chunk_id, chunk_text))

        logger.info(f"Corpus: {len(self.corpus)} documents/chunks")

        # 3. 生成查询
        if len(all_chunks) < 5:
            logger.warning("Too few chunks, using fallback dataset")
            self._generate_fallback_dataset(rng)
            return

        generated_queries = []

        for doc_id, chunk_id, text in all_chunks:
            text = text.strip()
            if len(text) < 30:
                continue

            # 尝试从文本中生成不同类型的查询
            sentences = re.split(r'(?<=[。！？；\n])\s*', text)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 15]

            for sent in sentences[:3]:  # 每段最多 3 个查询候选
                query = self._sentence_to_query(sent)
                if query and len(query) > 8:
                    generated_queries.append((query, chunk_id, doc_id))

        rng.shuffle(generated_queries)

        # 去重（相似查询只保留一个）
        seen = set()
        unique_queries = []
        for query, chunk_id, doc_id in generated_queries:
            key = "".join(jieba.lcut(query)[:5])
            if key not in seen:
                seen.add(key)
                unique_queries.append((query, chunk_id, doc_id))

        # 限制查询数量
        if num_queries and len(unique_queries) > num_queries:
            unique_queries = unique_queries[:num_queries]

        logger.info(f"Generated {len(unique_queries)} queries")

        # 4. 填充 queries + qrels
        for i, (query_text, chunk_id, doc_id) in enumerate(unique_queries):
            qid = f"Q{i:04d}"
            self.queries[qid] = query_text
            self.qrels[qid] = {chunk_id: 1}  # source chunk 为相关

        logger.info(f"Built-in dataset ready: "
                     f"{len(self.corpus)} docs, "
                     f"{len(self.queries)} queries, "
                     f"{len(self.qrels)} annotated")

    @staticmethod
    def _sentence_to_query(sentence: str) -> Optional[str]:
        """将陈述句转换为查询问题

        使用基于模式的方法，无需 LLM。
        """
        sentence = sentence.strip().rstrip("。，；：！？,.!?;:")

        # 检测包含"是"的定义句 → "什么是..."
        if "是" in sentence:
            # 提取"是"前面的主语
            parts = sentence.split("是", 1)
            subject = parts[0].strip()
            if 2 <= len(subject) <= 25:
                return f"什么是{subject}？"

        # 检测包含数字的量化句 → "...是多少"
        numbers = re.findall(r'\d+(?:\.\d+)?', sentence)
        if numbers and len(sentence) > 20:
            # 提取关键词
            keywords = re.sub(r'[\d\.]+', '', sentence)[:30].strip()
            if keywords:
                return f"根据文档，{keywords}是多少？"

        # 默认：将整个句子转为问题形式
        if len(sentence) > 10:
            short = sentence[:40]
            return "“" + short + "”的内容是什么？"
            # 上面这行等价于: "“{short}”的内容是什么？"

        return None

    def _generate_fallback_dataset(self, rng: random.Random):
        """当项目文档不可用时，生成小型 fallback 数据集"""
        logger.info("Generating fallback dataset...")

        # 中文科技/企业文档风格的语料
        fallback_corpus = {
            "doc_01::chunk_0": "公司实行每周五天、每日八小时的标准工时制度。工作时间为周一至周五上午09:00至12:00，下午13:30至18:00。",
            "doc_01::chunk_1": "员工加班需提前申请，经部门负责人审批后方可执行。加班费按照国家劳动法规定支付：工作日加班1.5倍，休息日加班2倍，法定假日加班3倍。",
            "doc_02::chunk_0": "系统采用三层微服务架构：前端交互层使用React框架，网关层使用Go语言开发，核心引擎层使用Python实现AI Agent功能。",
            "doc_02::chunk_1": "数据存储层采用MySQL作为主数据库，Redis用于缓存和会话管理，Milvus向量数据库用于文档检索和相似度匹配。",
            "doc_02::chunk_2": "系统部署在Kubernetes集群上，使用Docker容器化。每个微服务至少部署3个副本以保证高可用性。",
            "doc_03::chunk_0": "项目采用Scrum敏捷开发方法，每个Sprint周期为两周。团队由5名后端开发、3名前端开发、2名测试工程师和1名产品经理组成。",
            "doc_03::chunk_1": "代码审查是强制性的，所有代码必须经过至少一位资深工程师审查后方可合并到主分支。CI/CD流水线使用GitHub Actions自动执行测试和部署。",
            "doc_04::chunk_0": "数据安全策略规定：所有用户数据在传输过程中使用TLS 1.3加密，存储时使用AES-256加密。敏感数据（如密码）使用bcrypt哈希存储。",
            "doc_04::chunk_1": "系统日志保留期限为90天，审计日志保留期限为1年。日志使用ELK Stack进行收集、分析和可视化。",
            "doc_05::chunk_0": "AI模型采用RAG（检索增强生成）架构。检索部分使用BGE-small-en-v1.5模型将文档编码为384维向量，存储在Milvus向量数据库中。",
            "doc_05::chunk_1": "生成部分使用本地部署的Qwen2.5:14B模型通过Ollama提供服务。Agent具有自主循环能力，可以多次调用检索工具来收集足够信息。",
        }

        # 预定义查询和相关性标注
        fallback_queries = {
            "Q0001": "公司的标准工作时间是怎样的？",
            "Q0002": "员工加班费如何计算？",
            "Q0003": "系统的技术架构包含哪些层？",
            "Q0004": "数据存储使用了哪些数据库？",
            "Q0005": "系统的高可用性如何保证？",
            "Q0006": "项目采用什么开发流程？",
            "Q0007": "代码审查有什么要求？",
            "Q0008": "数据传输和存储的加密方式是什么？",
            "Q0009": "日志保留期限是多久？",
            "Q0010": "AI系统的检索部分使用了什么技术？",
        }

        fallback_qrels = {
            "Q0001": {"doc_01::chunk_0": 1},
            "Q0002": {"doc_01::chunk_1": 1},
            "Q0003": {"doc_02::chunk_0": 1},
            "Q0004": {"doc_02::chunk_1": 1},
            "Q0005": {"doc_02::chunk_2": 1},
            "Q0006": {"doc_03::chunk_0": 1},
            "Q0007": {"doc_03::chunk_1": 1},
            "Q0008": {"doc_04::chunk_0": 1},
            "Q0009": {"doc_04::chunk_1": 1},
            "Q0010": {"doc_05::chunk_0": 1},
        }

        self.corpus = fallback_corpus
        self.queries = fallback_queries
        self.qrels = fallback_qrels

        logger.info(f"Fallback dataset: {len(self.corpus)} docs, "
                     f"{len(self.queries)} queries")

    def get_queries_with_qrels(self) -> list[tuple[str, str]]:
        """获取有相关性标注的查询列表"""
        result = []
        for qid in self.qrels:
            if qid in self.queries:
                result.append((qid, self.queries[qid]))
        return result

    @property
    def stats(self) -> dict:
        return {
            "name": self.name,
            "num_docs": len(self.corpus),
            "num_queries": len(self.queries),
            "num_annotated_queries": len(self.qrels),
        }

    def save(self, path: str):
        """保存数据集到 JSON 文件"""
        data = {
            "name": self.name,
            "corpus": self.corpus,
            "queries": self.queries,
            "qrels": self.qrels,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Dataset saved to {path}")

    @classmethod
    def load_from_file(cls, path: str) -> "BenchmarkDataset":
        """从 JSON 文件加载数据集"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        ds = cls(data["name"])
        ds.corpus = data["corpus"]
        ds.queries = data["queries"]
        ds.qrels = data["qrels"]
        ds._loaded = True
        return ds


def load_dataset(
    name: str = "builtin-zh",
    max_docs: Optional[int] = None,
    num_queries: int = 50,
    seed: int = 42,
) -> BenchmarkDataset:
    """便捷函数：加载指定数据集

    Args:
        name: "builtin-zh" (内置) 或 HuggingFace 数据集名
        max_docs: 限制语料库文档数
        num_queries: 生成查询数（仅内置数据集）
        seed: 随机种子（确保可复现）

    Returns:
        BenchmarkDataset 实例
    """
    dataset = BenchmarkDataset(name)
    dataset.load(max_docs=max_docs, num_queries=num_queries, seed=seed)
    return dataset
