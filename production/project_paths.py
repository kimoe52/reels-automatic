"""One project-relative path contract shared by the widget and Python programs."""
from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "queue": "automation/meta-threads/queue",
    "cards_library": "content/card-news/generated",
    "cards_references": "content/card-news/references/주식 첫 투자",
    "reels_root": "content/reels",
    "reels_work": "content/reels/제작 자료",
    "reels_videos": "content/reels/완성 영상",
    "reels_proofs": "content/reels/검수 이미지",
    "design_notes": "research/디자인 기획",
    "motion_guides": "research/reference-collection/모션효과 가이드",
    "legacy_prototypes": "production/vllo/이전 시안",
    "scratch": ".work",
}


def _normalized(path: Path) -> Path:
    return Path(unicodedata.normalize("NFC", str(path.resolve())))


def project_path(key: str, root: Path = ROOT) -> Path:
    if key not in DEFAULTS:
        raise ValueError(f"알 수 없는 프로젝트 경로: {key}")
    config = root / "project-paths.json"
    paths = DEFAULTS
    if config.is_file():
        settings = json.loads(config.read_text(encoding="utf-8"))
        if settings.get("version") != 1 or not isinstance(settings.get("paths"), dict):
            raise ValueError("프로젝트 경로 설정 형식이 올바르지 않습니다")
        paths = {**DEFAULTS, **settings["paths"]}
    value = paths[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("비어 있는 프로젝트 경로는 사용할 수 없습니다")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
        raise ValueError("프로젝트 밖 경로는 사용할 수 없습니다")
    result = root / relative
    if not _normalized(result).is_relative_to(_normalized(root)):
        raise ValueError("프로젝트 밖을 가리키는 링크는 사용할 수 없습니다")
    return result


def scratch_directory(kind: str, root: Path = ROOT) -> Path:
    if not kind or Path(kind).name != kind or kind in {".", ".."}:
        raise ValueError("임시 작업 종류가 올바르지 않습니다")
    directory = project_path("scratch", root) / kind
    if not _normalized(directory).is_relative_to(_normalized(root)):
        raise ValueError("프로젝트 밖 임시 폴더는 사용할 수 없습니다")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description="프로젝트 내부의 실제 저장 경로를 확인합니다")
    parser.add_argument("--path", choices=sorted(DEFAULTS))
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()
    if args.path:
        path = project_path(args.path)
        if args.create:
            path.mkdir(parents=True, exist_ok=True)
        print(path)
    else:
        print(json.dumps({key:str(project_path(key)) for key in DEFAULTS},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
