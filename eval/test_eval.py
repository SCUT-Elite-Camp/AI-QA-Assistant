import unittest
import sys
from pathlib import Path

# Add project roots to sys.path to ensure imports work
project_root = Path(__file__).resolve().parent.parent
python_paths = [
    str(project_root),
    str(project_root / "eval")
]
for p in python_paths:
    if p not in sys.path:
        sys.path.insert(0, p)

from eval.metrics import (
    calculate_hit_rate,
    calculate_mrr,
    calculate_map,
    calculate_rouge_l,
    calculate_bleu
)


class TestMetrics(unittest.TestCase):
    def test_hit_rate(self):
        # Expected is in top-K
        self.assertEqual(calculate_hit_rate(["doc_1", "doc_2", "doc_3"], ["doc_2"], 3), 1.0)
        self.assertEqual(calculate_hit_rate(["doc_1", "doc_2", "doc_3"], ["doc_2"], 1), 0.0)
        # Multiple expected docs
        self.assertEqual(calculate_hit_rate(["doc_1", "doc_2"], ["doc_3", "doc_1"], 2), 1.0)
        # Expected not in top-K
        self.assertEqual(calculate_hit_rate(["doc_1", "doc_2"], ["doc_3"], 2), 0.0)

    def test_mrr(self):
        # First match at rank 2
        self.assertEqual(calculate_mrr(["doc_1", "doc_2", "doc_3"], ["doc_2"], 3), 0.5)
        # First match at rank 1
        self.assertEqual(calculate_mrr(["doc_1", "doc_2"], ["doc_1"], 2), 1.0)
        # No match
        self.assertEqual(calculate_mrr(["doc_1", "doc_2"], ["doc_3"], 2), 0.0)

    def test_map(self):
        # Match at rank 1 and 3
        # Expected = [doc_1, doc_3]
        # Precision at rank 1 = 1/1 = 1.0 (is a hit)
        # Precision at rank 2 = 1/2 = 0.5 (not a hit)
        # Precision at rank 3 = 2/3 = 0.667 (is a hit)
        # AP = (1.0 + 0.667) / 2 = 0.8333
        ap = calculate_map(["doc_1", "doc_2", "doc_3"], ["doc_1", "doc_3"], 3)
        self.assertAlmostEqual(ap, 0.8333, places=3)
        
        # No matches
        self.assertEqual(calculate_map(["doc_1", "doc_2"], ["doc_3"], 2), 0.0)

    def test_rouge_l(self):
        # Perfect match
        self.assertEqual(calculate_rouge_l("我是测试数据", "我是测试数据"), 1.0)
        # No match
        self.assertEqual(calculate_rouge_l("我是", "测试"), 0.0)
        # Empty string
        self.assertEqual(calculate_rouge_l("", "测试"), 0.0)
        
        # Partial match
        # LCS of "我是测试数据" and "我是数据" is "我是数据" (len 4 chars, or tokens: "我", "是", "数据")
        score = calculate_rouge_l("我是测试数据", "我是数据")
        self.assertTrue(0.0 < score < 1.0)

    def test_bleu(self):
        # Perfect match
        self.assertEqual(calculate_bleu("我是测试数据", "我是测试数据"), 1.0)
        # Empty input
        self.assertEqual(calculate_bleu("", "测试数据"), 0.0)
        # Short input should work without crashing
        self.assertTrue(0.0 <= calculate_bleu("测试", "另一个测试") <= 1.0)


if __name__ == "__main__":
    unittest.main()
