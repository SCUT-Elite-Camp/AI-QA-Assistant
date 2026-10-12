// architectureData.js - 系统整体架构分层与节点数据源
export const architectureLayers = [
  {
    id: "layer-user",
    type: "user",
    title: "用户",
    subtitle: "企业内部员工",
    icon: "user",
    color: "#2563EB",
    details: {
      name: "企业用户 / 客户端访问主体",
      role: "发起业务提问、交互会话与研判任务",
      tech: "标准 Web 浏览器 / 企业客户端，持有基于 Cookie 的独立 Session",
      io: "输入: 自然语言 Query、业务研判指令 | 输出: 流式回答、可穿透证据卡片、思维链过程"
    }
  },
  {
    id: "layer-01",
    step: "01",
    tag: "交互与展现层",
    enTitle: "Client & BFF Gateway",
    summary: "基于 Vue 3 + Nitro 的 Web 应用，提供流式问答体验，并处理会话安全与权限隔离。",
    metaText: "Web 应用 · SSE 流式响应 · 会话安全",
    icon: "window",
    color: "#2563EB",
    colorClass: "blue",
    details: {
      name: "交互与展现层 (Client & BFF Gateway)",
      role: "负责多端流式渲染、用户会话所有权校验与敏感凭据隔离",
      tech: "Vue 3, TypeScript, Nitro BFF, Server-Sent Events (SSE), HTTP-only Cookie",
      io: "输入: 用户提问与会话请求 | 输出: 实时打字机 Token 流、证据卡片引用 (Citation)、结构化推理步骤"
    }
  },
  {
    id: "layer-02",
    step: "02",
    tag: "Agent 智能编排层",
    enTitle: "Agent Orchestrator",
    summary: "根据问题复杂度自动路由，提供 Fast 快速响应与 Thinking 深度推理双轨能力，并结合记忆实现上下文协同。",
    metaText: "意图识别 · 双轨推理 · 记忆协同",
    icon: "agent-network",
    color: "#8B5CF6",
    colorClass: "violet",
    hasSubtracks: true,
    subtracks: [
      {
        id: "fast-track",
        name: "Fast",
        label: "快速知识响应",
        icon: "zap",
        color: "#8B5CF6",
        details: {
          name: "Fast 快速响应路径 (FastLoop)",
          role: "针对高频单意图或事实型提问，跳过冗长前置改写，实现毫秒级快速闭环",
          tech: "ExecutionProfileResolver 意图分流, EvidenceGate 轻量门禁, 单次极速推理生成",
          io: "输入: 事实型业务问题 | 输出: 毫秒级直出回答 (~6.9s 端到端时延)，附带直接证据引用"
        }
      },
      {
        id: "thinking-track",
        name: "Thinking",
        label: "复杂研判搜索",
        icon: "brain",
        color: "#7C3AED",
        details: {
          name: "Thinking 深度推理路径 (AgentRunner)",
          role: "针对跨文档对比、深度归纳与长链路研判，执行多轮反思、拓扑探索与证据交叉验证",
          tech: "ReAct 状态机循环, CoverageAssessor 覆盖度评估器, Wiki 知识拓扑拓展",
          io: "输入: 复杂对比、归纳或跨空间研判问题 | 输出: 深入研判报告、结构化思维链与多源聚合证据"
        }
      }
    ],
    details: {
      name: "Agent 智能编排层 (Agent Orchestrator)",
      role: "统一大脑调度，根据意图复杂度毫秒级动态分流，协调短期与长期记忆",
      tech: "FastAPI, Python 3.10+, AsyncIO, ContextVar 上下文边界隔离, MemoryCoordinator",
      io: "输入: 会话上下文与意图向量 | 输出: 双轨推理生成的流式回答与审计追踪链条"
    }
  },
  {
    id: "layer-03",
    step: "03",
    tag: "工具与检索适配层",
    enTitle: "Toolset & Retrieval Engine",
    summary: "混合搜索引擎、权限控制与证据链路打通，确保检索结果既相关又安全可靠。",
    metaText: "混合检索 · 权限控制 · 证据链路",
    icon: "search",
    color: "#0284C7",
    colorClass: "cyan",
    details: {
      name: "工具与检索适配层 (Toolset & Retrieval Engine)",
      role: "执行语义与词法混合召回、实时 ACL 权限交集求取以及证据哈希双向指纹质检",
      tech: "HybridSearchEngine (RRF 倒数排名融合), AccessGuard (本地 ACL ∩ 原生权限), EvidenceGate & CitationCheck",
      io: "输入: 语义检索 Query 与用户 Session 权限上下文 | 输出: 经过零信任权限过滤的可信证据切片 (evidence.provenance.v1)"
    }
  },
  {
    id: "layer-04",
    step: "04",
    tag: "存储与数据层",
    enTitle: "Persistence & Data Pipeline",
    summary: "向量、词法与原文的多模态存储矩阵，以及增量感知的数据处理流水线。",
    metaText: "向量库 · 全文索引 · 原文存储 · 数据流水线",
    icon: "database",
    color: "#10B981",
    colorClass: "green",
    details: {
      name: "存储与数据层 (Persistence & Data Pipeline)",
      role: "提供稠密向量/全文倒排/原文对象多模态持久化，并通过 CDC 变更检测实现增量感知与秒级同步",
      tech: "Milvus (512维 HNSW), BM25 词法倒排, MinIO S3 原文桶, SQLite / Turso, AST 语法树切片, CDC (MD5 + SHA-256)",
      io: "输入: 外部多格式文档 (PDF/DOCX/PPTX/Confluence) | 输出: 结构化多模态索引与切片实体持久化"
    }
  }
];

export const keyDecisions = [
  {
    number: "01",
    title: "双轨 Agent 编排",
    description: "根据问题复杂度动态选择 Fast 或 Thinking 路径，兼顾响应速度与深度研判能力。",
    icon: "dual-track",
    color: "#8B5CF6",
    link: "04_agent_dual_track.html"
  },
  {
    number: "02",
    title: "混合检索与权限控制",
    description: "结合语义检索与关键词检索，并在检索阶段引入企业权限控制，确保检索结果相关且安全。",
    icon: "search-shield",
    color: "#0284C7",
    link: "06_access_control_and_security.html"
  },
  {
    number: "03",
    title: "可验证的可信回答",
    description: "通过引用原始材料和推理过程，构建从检索到生成的全链路证据闭环。",
    icon: "shield-check",
    color: "#10B981",
    link: "02_data_pipeline.html"
  }
];
