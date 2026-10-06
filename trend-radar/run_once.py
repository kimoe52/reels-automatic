"""Run the one-time Jev trend judgment and lock the reel format.

The candidate set is intentionally finite and auditable. Pandas computes the
mechanical recency/engagement signals; Jev only judges semantic fit and
reproducibility. The script refuses to call Jev again after a locked output
exists unless --overwrite is explicitly supplied.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError:  # The pip environment uses pandas; this keeps preview checks usable before install.
    pd = None


ROOT = Path(__file__).resolve().parent
DEFAULT_CANDIDATES = ROOT / "candidates.csv"
DEFAULT_OUTPUT = ROOT / "locked-format.json"


def load_candidates(path: Path) -> list[dict[str, Any]]:
    if pd is None:
        return load_candidates_without_pandas(path)

    frame = pd.read_csv(path)
    required = {
        "account",
        "title",
        "url",
        "published_at",
        "duration_seconds",
        "likes",
        "comments",
        "observed_format",
        "observed_structure",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"후보 CSV에 필요한 열이 없습니다: {', '.join(sorted(missing))}")

    frame["published_at"] = pd.to_datetime(frame["published_at"], utc=True)
    now = pd.Timestamp.now(tz="UTC")
    frame["age_days"] = ((now - frame["published_at"]).dt.total_seconds() / 86400).clip(lower=0)
    frame["engagement"] = frame["likes"].astype(float) + frame["comments"].astype(float)
    frame["engagement_per_day"] = frame["engagement"] / frame["age_days"].clip(lower=1)

    # This is only a transparent ordering signal, not a claim of virality.
    recency = 1 / (1 + frame["age_days"])
    response = frame["engagement"].map(lambda value: math.log1p(max(value, 0)))
    frame["mechanical_signal"] = (recency * response).round(4)
    records = frame.sort_values("mechanical_signal", ascending=False).to_dict(orient="records")
    for record in records:
        record["published_at"] = pd.Timestamp(record["published_at"]).isoformat()
    return records


def load_candidates_without_pandas(path: Path) -> list[dict[str, Any]]:
    """Small stdlib fallback; the normal one-shot environment installs pandas."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "account",
        "title",
        "url",
        "published_at",
        "duration_seconds",
        "likes",
        "comments",
        "observed_format",
        "observed_structure",
    }
    if not rows:
        raise ValueError("후보 CSV가 비어 있습니다.")
    missing = required.difference(rows[0])
    if missing:
        raise ValueError(f"후보 CSV에 필요한 열이 없습니다: {', '.join(sorted(missing))}")

    now = datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    for row in rows:
        published = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        age_days = max((now - published).total_seconds() / 86400, 0)
        likes = float(row["likes"])
        comments = float(row["comments"])
        engagement = likes + comments
        mechanical_signal = (1 / (1 + age_days)) * math.log1p(max(engagement, 0))
        records.append(
            {
                **row,
                "duration_seconds": int(row["duration_seconds"]),
                "likes": likes,
                "comments": comments,
                "published_at": published.isoformat(),
                "age_days": age_days,
                "engagement": engagement,
                "mechanical_signal": round(mechanical_signal, 4),
            }
        )
    return sorted(records, key=lambda record: record["mechanical_signal"], reverse=True)


def build_state(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = [
        "account",
        "title",
        "url",
        "published_at",
        "duration_seconds",
        "likes",
        "comments",
        "observed_format",
        "observed_structure",
        "age_days",
        "engagement",
        "mechanical_signal",
    ]
    candidates = [{field: record[field] for field in fields} for record in records]
    return {
        "purpose": "이번 한 번의 바이브코딩 릴스 트렌드 평가. 이후 Jev를 반복 호출하지 않고 결과를 영상 포맷으로 고정한다.",
        "constraints": [
            "실제 화면 또는 명확히 표시된 예시 화면으로 주장과 동작을 증명한다.",
            "사용자의 직접 촬영 없이 Flow와 VLLO로 재현 가능해야 한다.",
            "유행 신호와 채널 적합성을 섞지 말고 별도로 판단한다.",
            "조회수·완주율·저장 수는 제공되지 않았으므로 추정하지 않는다.",
        ],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump())
    if hasattr(value, "__dict__"):
        return jsonable(vars(value))
    return str(value)


def judge_once(state: dict[str, Any]) -> dict[str, Any]:
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise RuntimeError(
            "TYPESAFE_API_KEY가 없습니다. 키를 채팅에 붙여넣지 말고, 이번 실행 셸에서만 설정하세요."
        )

    try:
        from typesafe_sdk import Choice, TypeSafeClient
    except ImportError as exc:
        raise RuntimeError(
            "TypeSafe SDK가 없습니다. 이 폴더의 가상환경에서 `python -m pip install -r requirements.txt`를 실행하세요."
        ) from exc

    questions = {
        "format": Choice(
            instructions="후보 중 이 채널의 Jev 소개 릴스에 가장 적합한 하나의 편집 형식을 고르세요.",
            criteria={
                "result_first_demo": "완성된 결과나 실제 앱 화면을 첫 장면에 보여주고, 조작 과정으로 기능을 증명한다.",
                "problem_first": "시청자가 겪는 구체적인 문제를 먼저 고정하고, 뒤에서 해결 화면을 보여준다.",
                "tool_roundup": "여러 도구나 선택지를 카드·목록으로 비교하고 각각의 역할을 짧게 설명한다.",
                "none": "후보 형식만으로는 Jev의 판단과 실행 차이를 오해 없이 보여주기 어렵다.",
            },
        ),
        "channel_fit": Choice(
            instructions="후보 묶음이 '짧은 설명 + 실제 화면 증명' 중심의 이 채널에 얼마나 잘 맞는지 고르세요.",
            criteria={
                "high": "Jev의 판단 상황과 실행 결과를 직접 화면에 배치하기 쉽다.",
                "medium": "응용 가능하지만 화면 증명이나 설명을 추가로 설계해야 한다.",
                "low": "분위기나 개인 상황은 강하지만 Jev의 역할을 흐릴 가능성이 크다.",
            },
        ),
        "reproducibility": Choice(
            instructions="Flow·VLLO와 캡처 화면만으로 같은 형식을 재현할 수 있는 정도를 고르세요.",
            criteria={
                "high": "직접 촬영이나 검증되지 않은 생성 결과 없이 반복 제작할 수 있다.",
                "medium": "일부 생성·편집 실험이 필요하지만 구현 가능성이 있다.",
                "low": "실제 서비스 접근이나 촬영 의존성이 커서 재현이 어렵다.",
            },
        ),
        "evidence_quality": Choice(
            instructions="후보 형식이 주장과 실제 동작을 구분해 보여주는 증거 품질을 고르세요.",
            criteria={
                "high": "실제 화면·입력·결과가 연결되어 과장 없이 설명된다.",
                "medium": "핵심 화면은 있으나 일부는 합성 예시로 명확히 표시해야 한다.",
                "low": "분위기나 자막에 의존해 실제 동작을 확인하기 어렵다.",
            },
        ),
    }

    with TypeSafeClient() as client:
        response = client.system_one(state=state, questions=questions)

    answers = getattr(response, "choices", None)
    if answers is None:
        answers = getattr(response, "answers", {})
    return jsonable(answers)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jev 1회성 트렌드 평가")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true", help="기존 결과가 있어도 다시 호출")
    args = parser.parse_args()

    if args.output.exists() and not args.overwrite:
        raise SystemExit(
            f"이미 결과가 있습니다: {args.output}\n반복 호출하지 않으려면 그대로 사용하고, 정말 다시 평가할 때만 --overwrite를 지정하세요."
        )

    records = load_candidates(args.candidates)
    state = build_state(records)
    jev = judge_once(state)
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "one_shot": True,
        "candidate_file": str(args.candidates),
        "mechanical_ranking": [
            {field: record[field] for field in ("account", "title", "url", "mechanical_signal")}
            for record in records
        ],
        "jev": jev,
        "next_step": "이 결과로 릴스의 형식·템포·자막 구조를 고정하고 Jev 호출을 중단한다.",
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"완료: {args.output}")


if __name__ == "__main__":
    main()
