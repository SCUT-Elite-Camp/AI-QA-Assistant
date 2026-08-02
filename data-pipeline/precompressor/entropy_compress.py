"""LightMem entropy_compress 预压缩实现

原理（来自 LightMem 论文）：
- 用 CausalLM（如 GPT-2）对文本做前向传播
- 计算每个 token 的条件自信息: I(token) = -log₂(P(token | context))
- 高自信息 = 更难预测 = 文本信息量更大 → 保留
- 低自信息 = 高度可预测 = 冗余/套话 → 丢弃
- 按词级别聚合（average / first_token），保留 top-K 高信息量词
"""

import logging
import math
import re
from typing import Literal

import torch
from models.document import ContentBlock
from precompressor.base import BasePreCompressor

logger = logging.getLogger(__name__)

# 默认模型: GPT-2 小模型，CPU 可运行
DEFAULT_ENTROPY_MODEL = "gpt2"

# 中文分句正则
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[。！？；\n])\s*"
)
# 英文分句
_EN_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[.!?;])\s+"
)


def _split_sentences(text: str) -> list[str]:
    """中英文混合分句"""
    # 先按换行分，再按标点分
    sentences = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 中文标点分句
        parts = _SENTENCE_SPLIT_RE.split(line)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append(part)
    return sentences


def _split_words(text: str) -> list[str]:
    """简单分词（按空白/标点分割），用于词级聚合"""
    # 中文: 逐字分割后按标点/空白聚合
    # 英文: 按空白分词
    tokens = []
    current = []
    for ch in text:
        if ch.isspace() or ch in "，。！？；：、""''（）【】[]{}…—":
            if current:
                tokens.append("".join(current))
                current = []
        elif "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
            # CJK 字符：每个字一个 token
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(ch)
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return [t for t in tokens if t.strip()]


class EntropyCompressor(BasePreCompressor):
    """基于 CausalLM 自信息的文本压缩器

    对应 LightMem 的 entropy_compress 后端。

    使用方式:
        compressor = EntropyCompressor(model_name="gpt2", device="cpu")
        compressed = compressor.compress(long_text, compress_rate=0.6)
    """

    def __init__(
        self,
        model_name: str = DEFAULT_ENTROPY_MODEL,
        device: str = "cpu",
        word_strategy: Literal["average", "first_token"] = "average",
        max_length: int = 1024,
    ):
        """
        Args:
            model_name: HuggingFace CausalLM 模型名 (默认 gpt2)
            device: 推理设备 (cpu / cuda)
            word_strategy: 词级聚合策略
                - "average": 取词内所有 token 的平均自信息
                - "first_token": 只取词的首 token 自信息
            max_length: 模型最大上下文长度（超过则分块处理）
        """
        self.model_name = model_name
        self.device = device
        self.word_strategy = word_strategy
        self.max_length = max_length

        self._model = None
        self._tokenizer = None

    @property
    def name(self) -> str:
        return "entropy_compress"

    def _load_model(self):
        """延迟加载模型（首次调用时加载）"""
        if self._model is not None:
            return

        logger.info(f"Loading entropy model: {self.model_name} on {self.device}")
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        # GPT-2 tokenizer 通常没有 pad_token
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=torch.float32 if self.device == "cpu" else torch.float16,
            device_map=self.device if self.device == "cuda" else None,
        )
        self._model.eval()

        if self.device == "cpu":
            self._model.to(self.device)

        logger.info(f"Entropy model loaded: {self.model_name}")

    def compress(self, text: str, compress_rate: float = 0.6) -> str:
        """按句子级保留 high-surprisal 片段

        流程:
        1. 分句
        2. 每句计算词级自信息
        3. 句子内排序，保留 top-K 高信息量词
        4. 完全被过滤的句子丢弃
        5. 拼接保留内容
        """
        if not text or not text.strip():
            return text

        sentences = _split_sentences(text)
        if not sentences:
            return text

        self._load_model()

        kept_sentences = []
        for sentence in sentences:
            words = _split_words(sentence)
            if not words:
                continue

            info_scores = self._compute_word_information(sentence, words)

            # 按自信息降序排列，保留 top-K 词
            k = max(1, int(len(words) * compress_rate))
            sorted_indices = sorted(
                range(len(info_scores)),
                key=lambda i: info_scores[i],
                reverse=True,
            )
            kept_indices = set(sorted_indices[:k])

            # 仅保留高信息量词（保持原序）
            kept_words = [
                words[i] for i in range(len(words)) if i in kept_indices
            ]

            if kept_words:
                kept_sentences.append("".join(kept_words))

        return "\n".join(kept_sentences)

    def _compute_word_information(
        self, text: str, words: list[str]
    ) -> list[float]:
        """计算每个词的自信息量

        1. Tokenize
        2. 前向传播获取 logits
        3. 计算 P(token | context) 和 I = -log2(P)
        4. 按词聚合
        """
        # Tokenize
        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length,
        )
        input_ids = inputs["input_ids"].to(self.device)
        seq_len = input_ids.shape[1]

        if seq_len < 2:
            return [0.0] * len(words)

        # 前向传播
        with torch.no_grad():
            outputs = self._model(input_ids)
            logits = outputs.logits  # [1, seq_len, vocab_size]

        # 计算自信息: I(t) = -log2(P(t | context))
        # P(t | context) = softmax(logits[t-1])[input_ids[t]]
        probs = torch.softmax(logits, dim=-1)
        # token t 的概率 = logits[t-1] 对 input_ids[t] 的 softmax
        # indices: [1, seq_len-1, 1]  -> gather target token probability
        target_probs = probs[0, torch.arange(seq_len - 1), input_ids[0, 1:]]
        target_probs = torch.clamp(target_probs, min=1e-12)

        # 自信息（以 bit 为单位）
        token_info = -torch.log2(target_probs).cpu().tolist()
        # 第一个 token 没有前驱，给最低信息量
        token_info = [0.0] + token_info

        # 词级聚合
        word_info = self._aggregate_word_info(text, words, input_ids, token_info)
        return word_info

    def _aggregate_word_info(
        self,
        text: str,
        words: list[str],
        input_ids: torch.Tensor,
        token_info: list[float],
    ) -> list[float]:
        """将 token 级别的自信息聚合到词级别

        策略:
        - "average": 词内所有 token 的平均
        - "first_token": 词的首 token 自信息
        """
        # 获取每个 word 在原文中的起止位置
        word_ranges = []
        pos = 0
        for word in words:
            # 找 word 在 text 中的位置（跳过空白）
            while pos < len(text) and text[pos].isspace():
                pos += 1
            start = pos
            end = start + len(word)
            word_ranges.append((start, end))
            pos = end

        # 找到每个 token 对应的字符范围（使用 tokenizer 的 offset mapping）
        # 简化: 按 token 解码后匹配
        token_texts = [
            self._tokenizer.decode([input_ids[0, i].item()])
            for i in range(input_ids.shape[1])
        ]

        word_infos = []
        ti = 0  # token index
        for wi, (w_start, w_end) in enumerate(word_ranges):
            accumulated = 0.0
            token_count = 0
            char_pos = 0

            # 推进到当前 word 的起始位置
            while ti < len(token_texts) and char_pos < w_start:
                ttext = token_texts[ti]
                char_pos += len(ttext)
                ti += 1

            # 收集 word 范围内的所有 token
            start_ti = ti
            while ti < len(token_texts) and char_pos < w_end:
                if ti < len(token_info):
                    accumulated += token_info[ti]
                    token_count += 1
                ttext = token_texts[ti]
                char_pos += len(ttext)
                ti += 1

            if token_count == 0:
                word_infos.append(0.0)
            elif self.word_strategy == "first_token":
                word_infos.append(token_info[start_ti] if start_ti < len(token_info) else 0.0)
            else:
                word_infos.append(accumulated / token_count)

        return word_infos

    def compress_blocks(
        self, blocks: list[ContentBlock], compress_rate: float = 0.6
    ) -> list[ContentBlock]:
        """对 ContentBlock 列表做压缩

        标题块不压缩（保留完整结构），正文块按文本压缩。
        """
        result = []
        for block in blocks:
            if block.block_type == "heading":
                # 标题不压缩
                result.append(block)
            elif block.block_type == "table":
                # 表格不压缩（结构化数据不宜截断）
                result.append(block)
            elif block.text:
                compressed_text = self.compress(block.text, compress_rate)
                if compressed_text.strip():
                    # 创建新块，保留原 block 的结构属性
                    new_block = ContentBlock(
                        block_type=block.block_type,
                        level=block.level,
                        text=compressed_text,
                        bold=block.bold,
                        italic=block.italic,
                    )
                    result.append(new_block)
                # 如果压缩后为空，跳过该块
            else:
                result.append(block)
        return result
