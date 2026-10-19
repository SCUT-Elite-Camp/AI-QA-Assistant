"""Local MiniCheck support verification, after exact claim/source binding."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import threading

from agent.config.settings import settings
from agent.evidence.verification_context import build_verification_inputs
from agent.evidence.minicheck_identity import verified_minicheck_weights
from agent.service.access_guard import check_model_access
from agent.service.permission_service import PermissionResolutionError
from agent.errors.exceptions import BudgetExceeded


class VerificationUnavailable(RuntimeError):
    pass


class MiniCheck:
    def __init__(self, path: str):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.tokenizer = self.model = None

    def _load(self):
        if self.model is not None:
            return
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            _, use_safetensors = verified_minicheck_weights(self.path)
            torch.set_num_threads(settings.MINICHECK_CPU_THREADS)
            tokenizer = AutoTokenizer.from_pretrained(self.path, local_files_only=True, trust_remote_code=False)
            model, diagnostic = AutoModelForSequenceClassification.from_pretrained(
                self.path, local_files_only=True, trust_remote_code=False,
                dtype=torch.float32, output_loading_info=True, use_safetensors=use_safetensors)
            if any(diagnostic.values()) or model.config.num_labels != 2 or not tokenizer.eos_token:
                raise ValueError("invalid_minicheck_weights")
            model.eval()
            self.tokenizer, self.model = tokenizer, model
        except Exception as exc:
            raise VerificationUnavailable("minicheck_load_failed") from exc

    def _encode(self, premise, claim):
        return self.tokenizer(premise + self.tokenizer.eos_token + claim, truncation=False)

    def check(self, binding, evidence, budget):
        check_model_access()
        if not self.lock.acquire(timeout=budget.remaining_seconds()):
            raise VerificationUnavailable("minicheck_capacity_timeout")
        try:
            self._load()
            budget.remaining_seconds()
            inputs = build_verification_inputs(binding, evidence,
                token_counter=lambda p, c: len(self._encode(p, c)["input_ids"]), max_input_tokens=512)
            rows = []
            for item in inputs:
                budget.verify()
                verdict, reason = "unverified", item.reason
                if item.status == "ready":
                    import torch
                    check_model_access()
                    batch = self.tokenizer.pad([self._encode(item.premise, item.claim)], return_tensors="pt")
                    with torch.inference_mode():
                        label = int(self.model(**batch).logits.argmax(dim=-1).item())
                    verdict, reason = ("supported" if label == 1 else "not_supported"), "minicheck_argmax"
                    budget.remaining_seconds()
                    check_model_access()
                rows.append({"claim_id": item.claim_id, "text": item.claim,
                             "verdict": verdict, "reason": reason})
            return rows
        except (BudgetExceeded, PermissionResolutionError, VerificationUnavailable):
            raise
        except Exception as exc:
            raise VerificationUnavailable("minicheck_inference_failed") from exc
        finally:
            self.lock.release()


@lru_cache(maxsize=1)
def local_minicheck(path: str):
    return MiniCheck(path)


@dataclass(frozen=True)
class SupportCheck:
    accepted: bool
    claims: list[dict]

    def feedback(self, binding):
        originals = {item["claim_id"]: item for item in binding["claims"]}
        return {"kind": "claim_support_not_confirmed", "claims": [
            {**row, "supports": originals[row["claim_id"]]["supports"]}
            for row in self.claims if row["verdict"] != "supported"],
            "instruction": "Reconsider against current sources. This verdict is not proof of falsity. "
                           "Acquire evidence, correct or remove unsupported assertions, or abstain."}


class EvidenceGate:
    def __init__(self, verifier=None):
        self.verifier = verifier

    def evaluate(self, binding, evidence, *, budget):
        if not binding.get("valid"):
            raise ValueError("valid_binding_required")
        check_model_access()
        verifier = self.verifier or local_minicheck(settings.MINICHECK_MODEL_PATH)
        claims = verifier.check(binding, evidence, budget)
        if [c["claim_id"] for c in claims] != [c["claim_id"] for c in binding["claims"]]:
            raise VerificationUnavailable("incomplete_minicheck_result")
        check_model_access()
        return SupportCheck(bool(claims) and all(c["verdict"] == "supported" for c in claims), claims)
