// pipelineData.js - Data Pipeline 数据处理流水线与节点数据源
export const pipelineNodes = [
  {
    id: "node-01",
    step: "01",
    title: "多源文档接入",
    subtitle: "PDF / DOCX / PPTX / Confluence ...",
    callout: "接入企业内多种文档源\n统一进入处理流水线。",
    icon: "document",
    color: "#2563EB",
    colorBg: "#eff6ff",
    details: {
      name: "01 / 多源文档接入 (Knowledge Sources)",
      why: "企业知识分散在多种异构格式与第三方系统（如 Confluence、企业网盘），传统方案格式割裂、无法统一版本与权限控制。",
      design: "通过统一的 SourceAdapter 协议抽象，建立不可变输入快照（Document Snapshot）与唯一 SHA-256 指纹，确保来源可审计、防篡改。",
      technology: "PyMuPDF (PDF AST 抽取), python-docx (结构化文档对象), Confluence REST API 增量拉取器, SHA-256 校验和。",
      io: "输入: 原始二进制文件 (PDF / DOCX / PPTX / Confluence Export) | 输出: 标准化 Document Snapshot 原始快照"
    }
  },
  {
    id: "node-02",
    step: "02",
    title: "结构化解析",
    subtitle: "构建文档 AST，保留标题、表格、层级结构",
    callout: "两遍扫描解析文档结构\n提取内容块与语义信息。",
    icon: "layers",
    color: "#8B5CF6",
    colorBg: "#f5f3ff",
    details: {
      name: "02 / 结构化解析 (Structure Parsing)",
      why: "纯文本简单平铺会导致层级丢失、表格错乱、上下文割裂，严重损害大模型对文档逻辑的理解与定位。",
      design: "采用两遍扫描算法（Two-pass Parser），第一遍构建完整的文档抽象语法树（AST），第二遍抽取标题级联路径、复杂表格单元与语义块。",
      technology: "自定义 Document AST 解析器, Markdown Table 矩阵标准化, 标题层级栈（H1-H6 Breadcrumbs 路径推导）。",
      io: "输入: Document Snapshot 快照 | 输出: 带标题拓扑与表格关系的结构化 Document AST 树"
    }
  },
  {
    id: "node-03",
    step: "03",
    title: "两级分块与知识拓扑",
    subtitle: "同时生成精确证据块与章节级导航",
    callout: "兼顾精准检索与全局理解\n为后续 Wiki 构建提供基础。",
    icon: "topology",
    color: "#2563EB",
    colorBg: "#eff6ff",
    isHighlighted: true,
    subtracks: [
      {
        id: "chunk-evidence",
        name: "Evidence Chunk",
        label: "精确事实片段",
        icon: "evidence",
        color: "#2563EB",
        colorBg: "#eff6ff",
        details: {
          name: "Evidence Chunk 精确事实片段",
          why: "大粒度切片会导致检索噪声过大、Token 浪费以及难以精确定位引用出处，降低问答可信度。",
          design: "以 300~500 Token 为事实切片单位，保留字符级原文偏移（quote_start / quote_end）与切片哈希，生成可验证的最小证据单元。",
          technology: "递归语义分块器, 句子窗口滑动（Overlap 10%）, 严格 Evidence Provenance 签名机制。",
          io: "输入: AST 章节正文片段 | 输出: 绑定行号/字符偏移且带 SHA-256 签名的 Verified Evidence 切片"
        }
      },
      {
        id: "chunk-section",
        name: "Section Tree",
        label: "章节层级结构",
        icon: "tree",
        color: "#10B981",
        colorBg: "#ecfdf5",
        details: {
          name: "Section Tree 章节层级结构",
          why: "微小切片丢失了文档章节的大纲全貌，难以回答跨段落归纳、架构分析和全景概览型提问。",
          design: "保留完整的父子章节树（Section Tree），每个 Evidence 挂载所属的 Section 节点，为 Agent 提供向上回溯大纲的能力。",
          technology: "有向无环拓扑树（Section Graph）, 章节级 Summary 聚合, 语义路径编码与层级关联索引。",
          io: "输入: 标题层级节点与全文章节目录 | 输出: 支持上下钻取的 Section 知识拓扑大纲树"
        }
      }
    ],
    details: {
      name: "03 / 两级分块与知识拓扑 (Intelligent Chunking)",
      why: "传统固定长度切片（Fixed-size Chunking）在面对精确事实检索与宏观主题理解时存在不可调和的矛盾。",
      design: "独创“双粒度分块体系”：微观上沉淀不可篡改的 Evidence Chunk，宏观上构建保持父子关系的 Section Tree，精准与宏观兼备。",
      technology: "两级拓扑分块引擎 (Dual-granularity Chunker), SQLite 关系映射, 树状层级索引。",
      io: "输入: 结构化 Document AST 树 | 输出: Evidence Chunk 切片集 + Section Tree 拓扑大纲"
    }
  },
  {
    id: "node-04",
    step: "04",
    title: "向量化与双路索引",
    subtitle: "语义向量 + 关键词索引",
    callout: "生成向量与倒排索引\n支持混合检索与权限过滤。",
    icon: "search",
    color: "#2563EB",
    colorBg: "#eff6ff",
    details: {
      name: "04 / 向量化与双路索引 (Index & Retrieval)",
      why: "单一向量检索对专业术语、专有编号、精确代码命中率低；传统 BM25 对语义泛化与同义理解能力弱。",
      design: "采用密集向量（Dense Embedding）与稀疏关键词倒排索引（Sparse BM25）并行双路建库，结合 RRF 倒数排名融合算法。",
      technology: "BGE-M3 (密集向量 1024 维), SQLite FTS5 / BM25 词法倒排索引, Milvus 向量引擎, RRF (Reciprocal Rank Fusion)。",
      io: "输入: Evidence 切片与文本语义元数据 | 输出: 双路混合检索索引 (向量集合 + 全文倒排库)"
    }
  },
  {
    id: "node-05",
    step: "05",
    title: "存储与权限同步",
    subtitle: "知识入库，建立访问边界",
    callout: "持久化存储并同步权限\n支持增量更新与文档撤回。",
    icon: "database",
    color: "#10B981",
    colorBg: "#ecfdf5",
    details: {
      name: "05 / 存储与权限同步 (Knowledge Ready)",
      why: "企业知识库有严苛的数据合规与权限要求；文档更新时若不能原子刷新与即时清理，会发生权限越界与脏读。",
      design: "知识入库即绑定源系统原生 ACL 权限元数据，与用户会话实时求交集；支持文档软删除与秒级硬撤回（Tombstone 清理）。",
      technology: "AccessGuard (本地 ACL ∩ 企业原生权限), Turso / SQLite 持久化, 增量同步审计日志, 权限边界隔离。",
      io: "输入: 索引工件与用户/部门权限标签 | 输出: 具备安全访问边界的企业级结构化知识资产"
    }
  }
];

export const wikiPanelData = {
  id: "wiki-panel",
  title: "Wiki",
  headline: "跨文档概念导航层",
  description: "在本项目中，Wiki 由离线流水线自动化编译，用于构建跨文档的概念与实体网络，帮助 Agent 进行全景探索与主题关联。",
  features: [
    {
      id: "nav",
      title: "仅做导航引导",
      desc: "提供概念关联与主题探索入口",
      color: "#2563EB",
      icon: "compass"
    },
    {
      id: "no-auth",
      title: "不作为引用权威",
      desc: "最终答案必须回溯原始 Evidence",
      color: "#EF4444",
      icon: "ban"
    },
    {
      id: "permission",
      title: "严格隔离与权限保护",
      desc: "按租户隔离，默认关闭，防止信息泄露",
      color: "#2563EB",
      icon: "shield-lock"
    }
  ],
  details: {
    name: "Wiki 概念层 (Cross-Document Concept Navigation)",
    why: "Agent 在多跳推理和全景探索时容易陷入检索盲区；但如果允许 Wiki 作为引用源，模型可能引用离线合成的虚假文本导致幻觉。",
    design: "严守核心原则：Wiki ≠ Citation Authority，Evidence = Final Source。Wiki 只充当导航地图，最终答案必须降落回权威的原始 Evidence 切片。",
    technology: "WikiStore SQLite 实体/页面关系表, FTS5 概念搜索, BGE-M3 页面向量, 严格 Quarantined 访问守卫隔离机制。",
    io: "输入: 全局文档 Evidence 与 Section 拓扑 | 输出: 自动化概念网络与实体关系导航图 (无直接引用权)"
  }
};

export const designDecisions = [
  {
    id: "decision-01",
    step: "01",
    title: "结构感知的文档解析",
    desc: "保留标题层级、表格与附件关系，避免知识碎片化。",
    icon: "document",
    color: "#2563EB",
    colorBg: "#eff6ff",
    details: {
      name: "核心设计 01: 结构感知的文档解析",
      why: "传统 OCR 或纯文本抽取丢失了标题从属关系，导致表格拆散、上下文断裂，AI 无法理解长文结构。",
      design: "两遍扫描 AST 架构，将标题路径作为语义元数据注入每个块，表格转化为 Markdown 矩阵保持行列关系完整。",
      technology: "自定义 AST 语法树生成器, 表格完整性保护机制, 标题层级递归解析 (H1-H6 Breadcrumb)。",
      io: "保障复杂技术文档、表格及跨页段落具备语义连续性"
    }
  },
  {
    id: "decision-02",
    step: "02",
    title: "双粒度知识索引",
    desc: "同时支持精确的证据片段检索与章节级的全局理解。",
    icon: "layers",
    color: "#8B5CF6",
    colorBg: "#f5f3ff",
    details: {
      name: "核心设计 02: 双粒度知识索引",
      why: "单一粒度无法同时满足“精确定位具体数值”与“总结整章业务逻辑”两种截然不同的问答需求。",
      design: "构建 Evidence Chunk 与 Section Tree 双轨映射网格，支持细粒度切片直达与粗粒度大纲展开。",
      technology: "双粒度拓扑引擎, Section 级语义摘要, 切片至章节反向指针寻址。",
      io: "精准事实问题与宏观主题对比均能获得最优召回表现"
    }
  },
  {
    id: "decision-03",
    step: "03",
    title: "增量更新与权限同步",
    desc: "通过变更感知和权限映射，实现知识的持续更新与安全下线。",
    icon: "refresh",
    color: "#10B981",
    colorBg: "#ecfdf5",
    details: {
      name: "核心设计 03: 增量更新与权限同步",
      why: "文档频繁修改、增删以及部门权限变动，传统周期性全量重构消耗巨大且存在数据不一致窗口。",
      design: "基于 SHA-256 内容哈希检测增量变更，删除文档触发级联物理清除与向量下线；入库即绑定权限白名单。",
      technology: "版本哈希比对管道, 软/硬删除原子事务, AccessGuard 零信任权限同步机制。",
      io: "变更秒级更新，删除彻底清理，企业级权限边界永不越界"
    }
  }
];

export const leftFeatures = [
  {
    title: "多源异构解析",
    desc: "支持 PDF、Word、Confluence 等格式",
    icon: "document",
    color: "#2563EB",
    colorBg: "#eff6ff"
  },
  {
    title: "结构化知识提取",
    desc: "保留文档层级、表格与语义结构",
    icon: "layers",
    color: "#8B5CF6",
    colorBg: "#f5f3ff"
  },
  {
    title: "增量更新与撤权",
    desc: "变更秒级同步，删除文档彻底清理",
    icon: "refresh",
    color: "#10B981",
    colorBg: "#ecfdf5"
  },
  {
    title: "内建权限同步",
    desc: "知识入库即绑定访问边界",
    icon: "shield-check",
    color: "#2563EB",
    colorBg: "#eff6ff"
  }
];
