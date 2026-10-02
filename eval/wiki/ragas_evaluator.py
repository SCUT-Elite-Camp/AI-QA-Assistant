from __future__ import annotations

import asyncio
import importlib.metadata
import ipaddress
import math
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse


RAGAS_METRIC_NAMES = (
    "ragas_context_precision",
    "ragas_context_recall",
    "answer_correctness",
    "faithfulness",
    "unsupported_claim_rate",
)


@dataclass(frozen=True)
class RagasConfig:
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 600.0
    allow_external: bool = False
    max_tokens: int = 4096


def ragas_version() -> str:
    try:
        return importlib.metadata.version("ragas")
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def validate_evaluator_endpoint(base_url: str, *, allow_external: bool) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Ragas evaluator base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("Ragas evaluator credentials must not be embedded in the base URL")
    hostname = parsed.hostname.lower()
    local = hostname == "localhost"
    if not local:
        try:
            local = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            local = False
    if not local and not allow_external:
        raise ValueError(
            "external Ragas evaluator is disabled; use a loopback endpoint or pass "
            "--ragas-allow-external after obtaining authorization"
        )
    return base_url.rstrip("/")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def id_context_scores(
    retrieved_context_ids: list[str], reference_context_ids: list[str]
) -> dict[str, float]:
    retrieved = _unique(retrieved_context_ids)
    reference = set(_unique(reference_context_ids))
    overlap = len(set(retrieved) & reference)
    return {
        "ragas_id_context_precision": overlap / len(retrieved) if retrieved else 0.0,
        "ragas_id_context_recall": overlap / len(reference) if reference else 0.0,
    }


def build_ragas_sample(
    record: Mapping[str, Any],
    *,
    reference_answer: str,
    reference_context_ids: list[str],
    evidence_content: Mapping[str, str],
) -> dict[str, Any]:
    retrieved_ids = _unique(
        [str(value) for value in record.get("retrieved_evidence_ids", []) if value]
    )
    reference_ids = _unique(reference_context_ids)
    retrieved_items = list(record.get("retrieved_items") or [])
    retrieved_contexts = [
        str(item.get("content") or "").strip()
        for item in retrieved_items
        if str(item.get("content") or "").strip()
    ]
    reference_contexts = [
        evidence_content[evidence_id]
        for evidence_id in reference_ids
        if evidence_id in evidence_content
    ]
    if len(reference_contexts) != len(reference_ids):
        missing = sorted(set(reference_ids) - set(evidence_content))
        raise ValueError(f"Ragas sample has unknown reference evidence IDs: {missing}")
    return {
        "query_id": str(record.get("query_id") or ""),
        "retrieval_path": str(record.get("retrieval_path") or ""),
        "user_input": str(record.get("query") or "").strip(),
        "retrieved_contexts": retrieved_contexts,
        "retrieved_context_ids": retrieved_ids,
        "reference_contexts": reference_contexts,
        "reference_context_ids": reference_ids,
        "response": str(record.get("answer") or "").strip(),
        "reference": reference_answer.strip(),
    }


def _metric_value(result: Any, name: str) -> float:
    value = float(getattr(result, "value", result))
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"Ragas metric {name} returned invalid value: {value}")
    return value


class RagasEvaluator:
    """Local-first Ragas 0.4 evaluator for completed retrieval records."""

    def __init__(self, config: RagasConfig) -> None:
        base_url = validate_evaluator_endpoint(
            config.base_url, allow_external=config.allow_external
        )
        if not config.model.strip():
            raise ValueError("Ragas evaluator model must not be empty")
        os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
        try:
            from openai import AsyncOpenAI
            from ragas.llms import llm_factory
            from ragas.metrics.collections import (
                ContextPrecisionWithReference,
                ContextRecall,
                FactualCorrectness,
                Faithfulness,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Ragas evaluation dependencies are missing; install "
            "eval/wiki/requirements-ragas.txt"
            ) from exc

        client = AsyncOpenAI(
            api_key=config.api_key or "local-ragas-evaluator",
            base_url=base_url,
            timeout=config.timeout,
            max_retries=0,
        )
        self._client = client
        llm = llm_factory(
            config.model,
            client=client,
            temperature=0,
            max_tokens=config.max_tokens,
        )
        self._metrics = {
            "ragas_context_precision": ContextPrecisionWithReference(llm=llm),
            "ragas_context_recall": ContextRecall(llm=llm),
            "answer_correctness": FactualCorrectness(
                llm=llm, mode="f1", atomicity="high", coverage="high"
            ),
            "faithfulness": Faithfulness(llm=llm),
        }

    async def _ascore(self, sample: Mapping[str, Any]) -> dict[str, float]:
        required = ("user_input", "retrieved_contexts", "response", "reference")
        missing = [name for name in required if not sample.get(name)]
        if missing:
            raise ValueError(f"Ragas sample is missing required fields: {missing}")

        calls = {
            "ragas_context_precision": self._metrics[
                "ragas_context_precision"
            ].ascore(
                user_input=sample["user_input"],
                reference=sample["reference"],
                retrieved_contexts=sample["retrieved_contexts"],
            ),
            "ragas_context_recall": self._metrics["ragas_context_recall"].ascore(
                user_input=sample["user_input"],
                retrieved_contexts=sample["retrieved_contexts"],
                reference=sample["reference"],
            ),
            "answer_correctness": self._metrics["answer_correctness"].ascore(
                response=sample["response"], reference=sample["reference"]
            ),
            "faithfulness": self._metrics["faithfulness"].ascore(
                user_input=sample["user_input"],
                response=sample["response"],
                retrieved_contexts=sample["retrieved_contexts"],
            ),
        }
        results = await asyncio.gather(*calls.values())
        scores = {
            name: _metric_value(result, name)
            for name, result in zip(calls, results, strict=True)
        }
        # Ragas Faithfulness is the supported atomic-claim ratio. Its exact
        # complement is therefore the claim-level unsupported rate.
        scores["unsupported_claim_rate"] = 1.0 - scores["faithfulness"]
        scores.update(
            id_context_scores(
                list(sample["retrieved_context_ids"]),
                list(sample["reference_context_ids"]),
            )
        )
        return scores

    async def _score_many_and_close(
        self, samples: list[Mapping[str, Any]]
    ) -> list[dict[str, float] | Exception]:
        results: list[dict[str, float] | Exception] = []
        try:
            for sample in samples:
                try:
                    results.append(await self._ascore(sample))
                except Exception as exc:
                    results.append(exc)
        finally:
            await self._client.close()
        return results

    def score_many(
        self, samples: list[Mapping[str, Any]]
    ) -> list[dict[str, float] | Exception]:
        """Score a batch on one event loop, then close the async HTTP client."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._score_many_and_close(samples))
        raise RuntimeError("RagasEvaluator.score_many cannot run inside an active event loop")
