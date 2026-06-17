# RAGent - 企业知识库问答系统 (Q1 阶段)

RAGent 是一个基于检索增强生成 (RAG) 技术的企业知识库问答系统。本项目旨在实现一轮对话的基础功能验证，打通“用户提问 → 文档检索 → 答案生成 → 展示引用”的完整链路。

---

## 技术选型

- **用户层**:
  - 前端: Vue 单页面应用 (Vue 3 / SFC)
  - 后端路由与 API 转发: Flask
- **Agent 推理层**:
  - LLM 接口: 兼容 OpenAI/DeepSeek 等流式对话接口
  - 决策机制: 简化版单轮 RAG Agent
- **检索工具集**:
  - 向量检索: Milvus HNSW 向量近似最近邻检索 (ANN)
  - 关键词检索: 基于 `rank_bm25` 的 BM25Okapi 算法，结合 `jieba` 中文分词
  - 融合算法: 倒数排序融合 (RRF, Reciprocal Rank Fusion)
- **数据处理管线**:
  - 解析器: PyMuPDF (PDF解析)、`python-docx` (DOCX解析)
  - 向量化: OpenAI `text-embedding-3-small` 嵌入模型 (1536维)
- **数据持久化**:
  - 向量存储: Milvus Standalone (Docker 部署)
  - 文档/元数据存储: 本地 JSON 文件存储 (`./data/documents/`)

---

## 项目目录结构

当前已搭建好的项目骨架结构如下：

```text
RAGent/
├── docker-compose.yml           # Milvus 向量数据库的 Docker Compose 部署配置
├── requirements.txt             # Python 后端第三方依赖包
├── README.md                    # 项目说明文档
├── data/                        # 数据存储目录
│   ├── documents/               # 存储已解析的 JSON 原文及元数据
│   └── raws/                    # 存放文档原始数据
├── models/                      # 数据模型定义
│   ├── __init__.py
│   └── document.py              # Pydantic 统一文档、章节树与分块模型
├── storage/                     # 数据持久化交互
│   ├── __init__.py
│   ├── milvus_store.py          # Milvus 读写及 Collection 管理
│   └── document_store.py        # 本地 JSON 文档的读写接口
├── parsers/                     # 文档解析层
│   ├── __init__.py
│   ├── base.py                  # 文档解析器抽象基类
│   ├── pdf_parser.py            # PDF 文档解析器
│   ├── docx_parser.py           # DOCX 文档解析器
│   └── registry.py              # 解析器注册与工厂分发
├── pipeline/                    # 离线数据处理管线
│   ├── __init__.py
│   ├── chunker.py               # 文本切分与重叠分块逻辑
│   ├── embedder.py              # 文本向量化接口
│   └── process.py               # “解析-切片-向量化-写入”流程编排
├── retrieval/                   # 检索器模块
│   ├── __init__.py
│   ├── search.py                # 混合检索入口 (Vector + BM25 + RRF 融合)
│   └── bm25_index.py            # 本地 BM25 索引维护与检索
├── agent/                       # Agent 核心逻辑
│   ├── __init__.py
│   ├── agent.py                 # RAG Agent 主流程 (trace_id / 检索 / LLM 组装)
│   ├── prompt.py                # 幻觉抑制 Prompt 模板
│   └── llm.py                   # LLM API 推理引擎调用
├── server/                      # API 后端服务
│   ├── __init__.py
│   └── app.py                   # Flask App，提供流式 SSE 问答接口
├── frontend/                    # Vue 前端项目
│   ├── index.html
│   ├── package.json
│   └── src/
│       ├── main.js
│       ├── App.vue
│       └── components/
│           ├── ChatWindow.vue   # 聊天对话主界面
│           └── MessageItem.vue  # 单条消息（包含来源引用卡片）
└── tests/                       # 测试套件
    ├── __init__.py
    ├── test_storage.py          # 存储读写测试
    ├── test_parser.py           # 解析与分块测试
    ├── test_retrieval.py        # 检索及 RRF 融合测试
    └── test_agent.py            # Agent 与 LLM 链路测试
```

---

## 项目启动

### 1. 启动 Docker 服务
在项目根目录下执行下面的命令，启动 Milvus 及其依赖组件（etcd、MinIO）：

```bash
docker-compose up -d
```

### 2. 安装 Python 依赖
建议先创建并激活 Python 虚拟环境，然后安装后端依赖：

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```



