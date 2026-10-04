"""Quality judgments for SGC fields and editorial blocks using TypeSafe Jev.

Only synthetic fixtures are used by default. Supplying another input file may
transmit its textual content to TypeSafe and requires separate approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.13.0"
QUALITY_LEVELS = [
    "Inadequado: confuso, contraditório ou sem informação utilizável",
    "Fraco: parcialmente compreensível, mas exige correção relevante",
    "Bom: claro e utilizável, com no máximo pequenos ajustes",
    "Excelente: claro, específico, conciso e pronto para publicação",
]
VERDICT = {
    "aprovado": "O conteúdo atende ao critério e pode seguir",
    "revisar": "O conteúdo é aproveitável, mas requer revisão humana",
    "reprovado": "O conteúdo viola o critério ou não contém informação suficiente",
}


def question_set(kind: str, state: dict) -> dict:
    questions: dict[str, dict] = {}
    if kind == "fields":
        paths = {
            "title": "record.title", "local": "record.local", "who": "record.who",
            "date": "record.date", "category": "record.category", "progress": "record.progress",
            "body": "record.body", "photo_caption": "record.photo_caption",
        }
        for name, path in paths.items():
            questions[f"{name}__quality"] = {
                "type": "score",
                "instructions": f"Avalie apenas `{path}` como campo de um registro de comunicação condominial. Meça clareza, especificidade e utilidade para moradores; não invente contexto ausente.",
                "criteria": QUALITY_LEVELS,
            }
            questions[f"{name}__verdict"] = {
                "type": "choice",
                "instructions": f"Decida se `{path}` pode seguir para um informe condominial, considerando o restante de `record` somente para verificar coerência.",
                "criteria": VERDICT,
            }
        questions["body__factual_tone"] = {"type": "noul", "instructions": "`record.body` usa tom factual, respeitoso e apropriado para comunicação condominial?"}
        questions["record__privacy_risk"] = {"type": "noul", "instructions": "`record` expõe dado pessoal desnecessário, acusação sem fonte ou informação sensível imprópria para moradores?"}
    elif kind == "blocks":
        for index, _ in enumerate(state["edition"]["blocks"]):
            path, prefix = f"edition.blocks[{index}]", f"block_{index}"
            questions[f"{prefix}__quality"] = {
                "type": "score",
                "instructions": f"Avalie `{path}` como bloco editorial de informe condominial. Meça clareza, coesão interna, relevância para moradores e concisão.",
                "criteria": QUALITY_LEVELS,
            }
            questions[f"{prefix}__verdict"] = {
                "type": "choice",
                "instructions": f"Decida se `{path}` está pronto para integrar `edition`, considerando sua função indicada em `{path}.type` e sem exigir fatos que não estejam no estado.",
                "criteria": VERDICT,
            }
            questions[f"{prefix}__source_alignment"] = {"type": "noul", "instructions": f"O conteúdo de `{path}` é compatível com suas referências em `{path}.sources` e com o restante do estado?"}
            questions[f"{prefix}__privacy_risk"] = {"type": "noul", "instructions": f"`{path}` expõe dado pessoal desnecessário, acusação sem fonte ou informação sensível imprópria?"}
        questions["edition__flow"] = {"type": "score", "instructions": "Avalie a progressão editorial de `edition.blocks`, da abertura ao encerramento, quanto à continuidade e ausência de repetição.", "criteria": QUALITY_LEVELS}
        questions["edition__verdict"] = {
            "type": "choice",
            "instructions": (
                "Decida se `edition` está coerente como informe completo e pode avançar para a revisão final humana obrigatória. "
                "Escolha `aprovado` quando puder avançar sem correção editorial prévia; escolha `revisar` somente quando o "
                "conteúdo precisar de correção antes dessa etapa. A existência da revisão humana obrigatória, por si só, "
                "não é motivo para escolher `revisar`."
            ),
            "criteria": VERDICT,
        }
    else:
        raise ValueError(f"grupo desconhecido: {kind}")
    return questions


def _number(value, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Resposta Jev inválida em {label}: número esperado")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise RuntimeError(f"Resposta Jev inválida em {label}: fora da faixa")
    return result


def validate_response(response: dict, model: str, questions: dict) -> dict:
    if not isinstance(response, dict) or response.get("model") != model:
        raise RuntimeError("Resposta Jev inválida: modelo divergente")
    answers = response.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise RuntimeError("Resposta Jev inválida: conjunto de respostas divergente")
    usage = response.get("usage")
    if not isinstance(usage, dict) or any(isinstance(usage.get(key), bool) or not isinstance(usage.get(key), int) or usage[key] < 0 for key in ("input_tokens", "output_tokens")):
        raise RuntimeError("Resposta Jev inválida: uso de tokens ausente")
    for key, question in questions.items():
        answer = answers[key]
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise RuntimeError(f"Resposta Jev inválida em {key}: tipo divergente")
        kind = question["type"]
        if kind == "score":
            _number(answer.get("score"), 0, len(question["criteria"]) - 1, key + ".score")
            _number(answer.get("confidence"), 0, 1, key + ".confidence")
        elif kind == "choice":
            if answer.get("choice") not in question["criteria"]:
                raise RuntimeError(f"Resposta Jev inválida em {key}: escolha desconhecida")
            _number(answer.get("confidence"), 0, 1, key + ".confidence")
        elif kind == "noul":
            _number(answer.get("noul"), 0, 1, key + ".noul")
    return response


def call_jev(api_key: str, model: str, state: dict, questions: dict, timeout: int) -> dict:
    body = json.dumps({"state": state, "model": model, "questions": questions}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(API_URL, data=body, method="POST", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.headers.get_content_type() != "application/json":
                    raise RuntimeError("TypeSafe devolveu conteúdo não JSON")
                return validate_response(json.load(response), model, questions)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"TypeSafe respondeu HTTP {error.code}") from error
        except urllib.error.URLError as error:
            if attempt == 2:
                raise RuntimeError("Não foi possível acessar TypeSafe") from error
        time.sleep(2 ** attempt)
    raise RuntimeError("TypeSafe indisponível")


def classify(answers: dict) -> tuple[str, list[str]]:
    status, reasons = "aprovado", []
    for key, answer in answers.items():
        if key.endswith("__privacy_risk") and float(answer.get("noul", 0)) >= 0.65:
            status = "reprovado"
            reasons.append(f"{key}: risco >= 0,65")
        if key.endswith("__verdict"):
            choice, confidence = answer.get("choice"), float(answer.get("confidence", 0))
            if choice == "reprovado" and confidence >= 0.65:
                status = "reprovado"
                reasons.append(f"{key}: reprovado com confiança {confidence:.2f}")
            elif choice != "aprovado" or confidence < 0.65:
                if status != "reprovado": status = "revisao_humana"
                reasons.append(f"{key}: {choice or 'sem decisão'}; confiança {confidence:.2f}")
        if key.endswith("__quality") and float(answer.get("score", 0)) < 2:
            if status != "reprovado": status = "revisao_humana"
            reasons.append(f"{key}: qualidade {float(answer.get('score', 0)):.2f}/3")
        if (key.endswith("__factual_tone") or key.endswith("__source_alignment")) and float(answer.get("noul", 0)) < 0.65:
            if status != "reprovado": status = "revisao_humana"
            reasons.append(f"{key}: aderência {float(answer.get('noul', 0)):.2f}")
    return status, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Bateria editorial SGC com Jev")
    parser.add_argument("--input", type=Path, default=Path(__file__).with_name("fixtures.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "results" / "jev" / "report.json")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true", help="valida e mostra a quantidade de perguntas sem transmitir dados")
    args = parser.parse_args()
    state = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(state.get("record"), dict) or not isinstance(state.get("edition", {}).get("blocks"), list):
        raise SystemExit("Entrada inválida: são obrigatórios record e edition.blocks.")
    payload_hash = hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    groups = {name: question_set(name, state) for name in ("fields", "blocks")}
    if args.dry_run:
        print(json.dumps({"status": "dry_run", "model": args.model, "stateSha256": payload_hash, "questions": {name: len(value) for name, value in groups.items()}}, ensure_ascii=False))
        return 0
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Defina TYPESAFE_API_KEY no ambiente; a chave nunca deve ser gravada no projeto.")
    report = {"at": datetime.now(timezone.utc).isoformat(), "requestedModel": args.model, "stateSha256": payload_hash, "source": args.input.name, "groups": {}}
    exit_code = 0
    for name, questions in groups.items():
        response = call_jev(api_key, args.model, state, questions, args.timeout)
        answers = response.get("answers", {})
        missing = sorted(set(questions) - set(answers))
        if missing: raise RuntimeError(f"Resposta incompleta em {name}: {', '.join(missing)}")
        status, reasons = classify(answers)
        if status != "aprovado": exit_code = 1
        report["groups"][name] = {"status": status, "reasons": reasons, "model": response.get("model"), "usage": response.get("usage", {}), "answers": answers}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(args.output), "groups": {k: v["status"] for k, v in report["groups"].items()}}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        raise SystemExit(2)
