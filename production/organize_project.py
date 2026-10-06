"""Recoverable organization of known project files; never touches other projects."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from project_paths import ROOT, DEFAULTS, project_path

sys.path.insert(0, str(ROOT / "production/card_motion"))
from storage import _copy, _sha, _save, reel_package

PROTOTYPES = {
    "make_jev_audio_v4.py", "make_jev_audio_v5.py", "make_jev_audio_v6.py",
    "make_jev_audio_v7.py", "make_jev_audio_v9.py", "render_72_rule_reel_v2.py",
    "render_72_rule_reel_v3.py", "render_demo.py", "render_jev_demo.py",
    "render_jev_screen_v8.py", "render_jev_v2.py", "render_jev_v3.py",
    "render_jev_v4.py", "render_jev_v5.py", "render_jev_v6.py",
    "render_jev_v7.py", "render_jev_v9.py",
}


def organize_files(root: Path = ROOT) -> dict:
    pairs = [(root / "production/vllo" / name,
              project_path("legacy_prototypes", root) / name) for name in sorted(PROTOTYPES)]
    notes = project_path("design_notes", root)
    pairs += [
        (root / "content/creative-direction-review-2026-09-24.md", notes / "2026-09-24_디자인 검토.md"),
        (root / "content/creative-direction-explanation-2026-09-24.md", notes / "2026-09-24_제작 방향.md"),
    ]
    pending = []
    for source, target in pairs:
        if source.is_symlink():
            if source.resolve() != target.resolve() or not target.is_file():
                raise ValueError(f"기존 호환 경로가 달라 이동을 중단했습니다: {source.name}")
            continue
        if not source.is_file() or target.exists():
            raise ValueError(f"원본이 없거나 대상 이름이 겹칩니다: {source.name}")
        pending.append((source, target, _sha(source)))
    records = []
    for source, target, digest in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        try:
            source.symlink_to(os.path.relpath(target, source.parent))
            if sys.platform == "darwin":
                subprocess.run(["/usr/bin/chflags", "-h", "hidden", str(source)], check=True)
            if _sha(target) != digest:
                raise ValueError("이동한 파일의 해시가 다릅니다")
        except Exception:
            if source.is_symlink():
                source.unlink()
            target.rename(source)
            raise
        records.append({"old": str(source), "new": str(target), "sha256": digest})

    source_cards = reel_package("stock-png-automatic-2026-10-04-v2", root) / "Inputs"
    references = project_path("cards_references", root)
    references.mkdir(parents=True, exist_ok=True)
    cards = []
    for number in range(1, 10):
        source = source_cards / f"card-{number:02d}.png"
        target = references / f"{number:02d}.png"
        if not source.is_file():
            raise FileNotFoundError(f"사용자 원본 카드가 없습니다: {source.name}")
        _copy(source, target)
        cards.append({"number": number, "file": target.name, "sha256": _sha(target), "source": str(source)})
    _save(references / ".sources.json", {"kind":"user_original_design_reference", "content_is_not_new_post_evidence":True, "cards":cards})
    report = {"relocated_files":records,"reference_cards":len(cards),"deleted_originals":False}
    receipt = project_path("scratch", root) / "organization" / "relocations.json"
    previous = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {"runs":[]}
    _save(receipt,{"runs":[*previous["runs"],report]})
    return report


def audit(root: Path = ROOT) -> dict:
    directories = {key: project_path(key,root).is_dir() for key in DEFAULTS}
    broken = []
    skip = {"node_modules", ".git", "__pycache__", ".work", "dist"}
    for current, names, files in os.walk(root, followlinks=False):
        names[:] = [name for name in names if name not in skip]
        for name in names + files:
            path = Path(current) / name
            if path.is_symlink() and not path.exists():
                broken.append(path.relative_to(root).as_posix())
    return {"configured_directories_exist":directories,"broken_links":broken,
            "passed":all(directories.values()) and not broken}


def main() -> None:
    parser = argparse.ArgumentParser(description="프로젝트 파일 이동 또는 경로 점검")
    parser.add_argument("--apply",action="store_true")
    args = parser.parse_args()
    result = organize_files() if args.apply else {}
    result["path_audit"] = audit()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["path_audit"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
