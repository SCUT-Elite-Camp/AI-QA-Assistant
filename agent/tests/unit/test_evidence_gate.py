"""MiniCheck-only gate: exact inputs, fail-closed infrastructure and no scores."""
from types import SimpleNamespace
import pytest
import torch

from agent.evidence.gate import EvidenceGate, MiniCheck, VerificationUnavailable
from agent.runtime.budget import RunBudget
from agent.evidence.answer_grounding import parse_grounded_answer, validate_grounded_answer
from tests.unit.test_agent_runner import evidence, draft

pytestmark = pytest.mark.no_storage


class Tokenizer:
    eos_token='</s>'
    def __init__(self, length=40):
        self.calls=[]
        self.length=length
    def __call__(self,text,**kwargs):
        assert kwargs=={'truncation':False}
        self.calls.append(text)
        return {'input_ids':[1]*self.length,'attention_mask':[1]*self.length}
    def pad(self,encoded,return_tensors):
        assert return_tensors=='pt'
        return {'input_ids':torch.tensor([encoded[0]['input_ids']])}


def evaluate(label=1, length=40, binding=None):
    verifier=MiniCheck('unused')
    verifier.tokenizer=Tokenizer(length)
    calls=[]
    def forward(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(logits=torch.tensor([[0.,1.]] if label else [[1.,0.]]))
    verifier.model=forward
    sources=[evidence().model_dump()]
    binding=binding or validate_grounded_answer(parse_grounded_answer(draft()),sources)
    budget=RunBudget(10,8,30000,150000,10,60)
    result=EvidenceGate(verifier).evaluate(binding,sources,budget=budget)
    return result,verifier,calls,budget


@pytest.mark.parametrize('label,accepted',[(0,False),(1,True)])
def test_gate_uses_argmax_without_model_self_scores_or_evidence_count_rules(label,accepted):
    result,verifier,calls,budget=evaluate(label)
    assert result.accepted is accepted and len(calls)==1 and budget.verifications==1
    assert '</s>The release is planned.' in verifier.tokenizer.calls[-1]
    assert 'scores' not in result.claims[0] and 'confidence' not in result.claims[0]


def test_overlong_context_is_unverified_without_truncating_or_forwarding():
    result,_,calls,_=evaluate(length=513)
    assert not result.accepted and not calls
    assert result.claims[0]['verdict']=='unverified'
    assert 'token' in result.claims[0]['reason']


def test_binding_is_required_before_any_semantic_model():
    with pytest.raises(ValueError,match='valid_binding_required'):
        EvidenceGate().evaluate({'valid':False},[],budget=RunBudget(2,1,8000,10000,1,10))


def test_missing_model_is_unavailable_and_never_falls_back(tmp_path):
    with pytest.raises(VerificationUnavailable,match='minicheck_load_failed'):
        MiniCheck(str(tmp_path/'missing'))._load()


def test_missing_claim_verdict_fails_closed():
    binding=validate_grounded_answer(parse_grounded_answer(draft()),[evidence().model_dump()])
    with pytest.raises(VerificationUnavailable,match='incomplete_minicheck_result'):
        EvidenceGate(SimpleNamespace(check=lambda *args:[])).evaluate(binding,[evidence().model_dump()],
            budget=RunBudget(2,1,8000,10000,1,10))


def test_classifier_forward_failure_is_infrastructure_failure():
    verifier=MiniCheck('unused')
    verifier.tokenizer=Tokenizer()
    def broken(**kwargs):
        raise RuntimeError('inference unavailable')
    verifier.model=broken
    sources=[evidence().model_dump()]
    binding=validate_grounded_answer(parse_grounded_answer(draft()),sources)
    with pytest.raises(VerificationUnavailable,match='minicheck_inference_failed'):
        EvidenceGate(verifier).evaluate(binding,sources,budget=RunBudget(2,1,8000,10000,1,10))


@pytest.mark.parametrize('defect', ['missing_manifest', 'wrong_model', 'changed_weights', 'outside_path'])
def test_unverified_local_checkpoint_is_rejected_before_loading(tmp_path, monkeypatch, defect):
    import hashlib
    import json
    import transformers
    from unittest.mock import Mock
    weight = tmp_path / 'pytorch_model.bin'
    weight.write_bytes(b'reviewed checkpoint fixture')
    identity = {'repo': 'lytang/MiniCheck-DeBERTa-v3-Large', 'weight_file': weight.name,
                'sha256': hashlib.sha256(weight.read_bytes()).hexdigest()}
    if defect == 'wrong_model':
        identity['repo'] = 'another/classifier'
    elif defect == 'changed_weights':
        weight.write_bytes(b'unreviewed replacement')
    elif defect == 'outside_path':
        identity['weight_file'] = '../pytorch_model.bin'
    if defect != 'missing_manifest':
        (tmp_path / 'verified.json').write_text(json.dumps(identity), encoding='utf-8')
    load = Mock()
    monkeypatch.setattr(transformers.AutoModelForSequenceClassification, 'from_pretrained', load)
    with pytest.raises(VerificationUnavailable, match='minicheck_load_failed'):
        MiniCheck(str(tmp_path))._load()
    load.assert_not_called()


@pytest.mark.parametrize('filename,safetensors', [('pytorch_model.bin', False), ('model.safetensors', True)])
def test_loader_uses_the_hashed_weight_format_when_both_files_exist(tmp_path, monkeypatch, filename, safetensors):
    import hashlib
    import json
    import transformers
    from unittest.mock import Mock
    for name in ['pytorch_model.bin', 'model.safetensors']:
        (tmp_path / name).write_bytes(name.encode())
    identity = {'repo': 'lytang/MiniCheck-DeBERTa-v3-Large', 'weight_file': filename,
                'sha256': hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest()}
    (tmp_path / 'verified.json').write_text(json.dumps(identity), encoding='utf-8')
    load = Mock(return_value=(SimpleNamespace(config=SimpleNamespace(num_labels=2), eval=lambda: None), {}))
    monkeypatch.setattr(transformers.AutoTokenizer, 'from_pretrained', lambda *a, **kw: Tokenizer())
    monkeypatch.setattr(transformers.AutoModelForSequenceClassification, 'from_pretrained', load)
    MiniCheck(str(tmp_path))._load()
    assert load.call_args.kwargs['use_safetensors'] is safetensors
