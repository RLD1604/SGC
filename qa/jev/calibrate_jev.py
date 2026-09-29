"""Repeat batched Jev decisions over labeled synthetic SGC cases."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from run_jev_qa import DEFAULT_MODEL, QUALITY_LEVELS, VERDICT, call_jev


def questions_for(group: str, cases: list[dict]) -> dict:
    questions = {}
    for index, case in enumerate(cases):
        prefix, root = case["id"], f"cases[{index}]"
        if group == "fields":
            questions[f"{prefix}__quality"] = {
                "type": "score",
                "instructions": f"Avalie `{root}.record` como registro para comunicação condominial: clareza, especificidade, coerência e utilidade.",
                "criteria": QUALITY_LEVELS,
            }
            questions[f"{prefix}__verdict"] = {
                "type": "choice",
                "instructions": f"Decida se `{root}.record` pode seguir para um informe condominial.",
                "criteria": VERDICT,
            }
            questions[f"{prefix}__privacy_risk"] = {
                "type": "noul",
                "instructions": f"`{root}.record` expõe dado pessoal desnecessário, acusação sem fonte ou conteúdo impróprio?",
            }
        else:
            questions[f"{prefix}__quality"] = {
                "type": "score",
                "instructions": f"Avalie `{root}.edition` quanto a clareza, fluxo, relevância e concisão editorial.",
                "criteria": QUALITY_LEVELS,
            }
            questions[f"{prefix}__verdict"] = {
                "type": "choice",
                "instructions": f"Decida se `{root}.edition` está pronta para revisão final e publicação condominial.",
                "criteria": VERDICT,
            }
            questions[f"{prefix}__privacy_risk"] = {
                "type": "noul",
                "instructions": f"`{root}.edition` expõe dado pessoal desnecessário, acusação sem fonte ou conteúdo impróprio?",
            }
    return questions


def decision(answers: dict, case_id: str) -> tuple[str, dict]:
    verdict = answers[f"{case_id}__verdict"]
    quality = answers[f"{case_id}__quality"]
    privacy = answers[f"{case_id}__privacy_risk"]
    confidence = float(verdict.get("confidence", 0))
    privacy_value = float(privacy.get("noul", 0))
    score = float(quality.get("score", 0))
    if privacy_value >= 0.65 or (verdict.get("choice") == "reprovado" and confidence >= 0.65):
        status = "reprovado"
    elif verdict.get("choice") != "aprovado" or confidence < 0.65 or score < 2:
        status = "revisao_humana"
    else:
        status = "aprovado"
    return status, {"choice": verdict.get("choice"), "confidence": confidence, "quality": score, "privacyRisk": privacy_value}


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibração sintética e repetida do Jev")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("calibration_cases.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "results" / "jev" / "calibration.json")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        raise SystemExit("--runs deve estar entre 1 e 10")
    state = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = state.get("cases", [])
    if not cases or any(not {"id", "expected", "record", "edition"} <= set(case) for case in cases):
        raise SystemExit("Casos de calibração inválidos")
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Defina TYPESAFE_API_KEY no ambiente")
    report = {
        "at": datetime.now(timezone.utc).isoformat(), "modelRequested": args.model, "runs": args.runs,
        "stateSha256": hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "cases": {case["id"]: {"expected": case["expected"], "observations": []} for case in cases}, "usage": [],
    }
    for run in range(1, args.runs + 1):
        for group in ("fields", "blocks"):
            response = call_jev(api_key, args.model, state, questions_for(group, cases), args.timeout)
            report["usage"].append({"run": run, "group": group, "model": response.get("model"), **response.get("usage", {})})
            for case in cases:
                status, metrics = decision(response["answers"], case["id"])
                report["cases"][case["id"]]["observations"].append({"run": run, "group": group, "status": status, **metrics})
    passed = True
    for case_id, result in report["cases"].items():
        statuses = [item["status"] for item in result["observations"]]
        counts = Counter(statuses)
        result["counts"] = dict(counts)
        result["agreement"] = max(counts.values()) / len(statuses)
        result["matchedExpected"] = all(status == result["expected"] for status in statuses)
        passed &= result["matchedExpected"]
    report["passed"] = passed
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "report": str(args.output), "cases": {key: {"expected": value["expected"], "counts": value["counts"], "agreement": value["agreement"]} for key, value in report["cases"].items()}}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERRO: {error}", file=sys.stderr)
        raise SystemExit(2)
