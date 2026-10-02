import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "jev"))
from run_jev_qa import classify, validate_response


class JevContractTests(unittest.TestCase):
    def setUp(self):
        self.questions = {
            "body__quality": {"type": "score", "criteria": ["a", "b", "c", "d"]},
            "body__verdict": {"type": "choice", "criteria": {"aprovado": "ok", "revisar": "r", "reprovado": "x"}},
            "body__factual_tone": {"type": "noul"},
        }
        self.answers = {
            "body__quality": {"type": "score", "score": 3, "confidence": .9},
            "body__verdict": {"type": "choice", "choice": "aprovado", "confidence": .9},
            "body__factual_tone": {"type": "noul", "noul": .9},
        }

    def response(self):
        return {"model": "jev-1.13.0", "answers": self.answers, "usage": {"input_tokens": 1, "output_tokens": 1}}

    def test_accepts_complete_strict_response(self):
        response = self.response()
        self.assertIs(validate_response(response, "jev-1.13.0", self.questions), response)

    def test_rejects_non_finite_score(self):
        response = self.response()
        response["answers"]["body__quality"]["score"] = math.nan
        with self.assertRaises(RuntimeError):
            validate_response(response, "jev-1.13.0", self.questions)

    def test_rejects_missing_or_extra_answer(self):
        response = self.response()
        response["answers"]["extra"] = {"type": "noul", "noul": 1}
        with self.assertRaises(RuntimeError):
            validate_response(response, "jev-1.13.0", self.questions)

    def test_rejects_model_substitution(self):
        with self.assertRaises(RuntimeError):
            validate_response(self.response(), "outro-modelo", self.questions)

    def test_low_factual_alignment_requires_human_review(self):
        self.answers["body__factual_tone"]["noul"] = .2
        self.assertEqual(classify(self.answers)[0], "revisao_humana")

    def test_privacy_risk_overrides_approval(self):
        self.answers["record__privacy_risk"] = {"type": "noul", "noul": .8}
        self.assertEqual(classify(self.answers)[0], "reprovado")


if __name__ == "__main__":
    unittest.main()
