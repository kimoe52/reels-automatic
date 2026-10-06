"""Project-local production storage and human-readable, review-only exports."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_paths import project_path

ROOT = Path(__file__).resolve().parents[2]
WORK = "제작 자료"
VIDEOS = "완성 영상"
PROOFS = "검수 이미지"


def reel_package(name: str, root: Path = ROOT) -> Path:
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("제작 폴더 이름이 올바르지 않습니다")
    return project_path("reels_work", root) / name


def reel_manifests(reels: Path, root: Path | None = None) -> list[Path]:
    # Legacy aliases remain valid for existing jobs, hashes and saved links.
    found: dict[Path, Path] = {}
    project_root = root if root is not None else reels.parent.parent
    for base in (project_path("reels_work", project_root), reels):
        for path in sorted(base.glob("*/reel-production.json")):
            found.setdefault(path.resolve(), path)
    return sorted(found.values())


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_render(marker: dict, package: Path, marker_path: Path) -> bool:
    """Never export an old video whose reviewed source has changed."""
    if marker.get("status") != "ready_for_review":
        return False
    package = package.resolve()
    inputs = marker.get("source_inputs")
    if inputs is not None:
        if not isinstance(inputs, list) or not inputs:
            return False
        for item in inputs:
            if not isinstance(item, dict):
                return False
            name = item.get("file")
            if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
                return False
            source = (package / name).resolve()
            if not source.is_relative_to(package) or not source.is_file() or _sha(source) != item.get("sha256"):
                return False
        return True
    manifest = package / "reel-production.json"
    data = _json(manifest)
    if not manifest.is_file() or not isinstance(data.get("cards"), list):
        return False
    reviewed_time = marker_path.stat().st_mtime_ns
    if manifest.stat().st_mtime_ns > reviewed_time:
        return False
    for card in data["cards"]:
        source = (package / str(card.get("file", ""))).resolve()
        if not source.is_relative_to(package) or not source.is_file() or source.stat().st_mtime_ns > reviewed_time:
            return False
        if card.get("source_sha256") and _sha(source) != card["source_sha256"]:
            return False
    return True


def _title(value: str) -> str:
    title = unicodedata.normalize("NFC", value)
    title = re.sub(r'[/:\\\x00-\x1f]', " ", title)
    return re.sub(r"\s+", " ", title).strip(" .")[:72] or "제목 없는 영상"


def _copy(source: Path, target: Path) -> None:
    if target.is_file() and _sha(source) == _sha(target):
        return
    if target.exists():
        raise FileExistsError(f"기존 내보낸 파일을 덮어쓰지 않습니다: {target.name}")
    temporary = target.with_name(f".{target.name}-{os.getpid()}")
    shutil.copy2(source, temporary)
    if _sha(source) != _sha(temporary):
        raise ValueError("복사 파일 검증에 실패했습니다")
    os.replace(temporary, target)


def export_render(status: dict, root: Path = ROOT) -> dict:
    """Copies for Finder, not auto-publishing or an additional approval."""
    if status.get("status") != "ready_for_review":
        return status
    manifest = Path(str(status.get("manifest", ""))).resolve()
    project = root.resolve()
    if not manifest.is_relative_to(project) or not manifest.is_file():
        return status
    marker_path = manifest.parent / "renders/latest.json"
    marker = _json(marker_path)
    if not marker_path.is_file() or marker.get("video") != status.get("video") or not current_render(marker, manifest.parent, marker_path):
        return status
    video = Path(str(marker.get("video", ""))).resolve()
    proof = Path(str(marker.get("proof", ""))).resolve()
    if any(not p.is_relative_to(project) or not p.is_file() for p in (video, proof)):
        return status
    videos, proofs = project_path("reels_videos", root), project_path("reels_proofs", root)
    videos.mkdir(parents=True, exist_ok=True); proofs.mkdir(parents=True, exist_ok=True)
    catalog_path = videos / ".catalog.json"
    catalog = _json(catalog_path)
    entries = catalog.setdefault("entries", {})
    key = video.relative_to(project).as_posix()
    entry = entries.get(key)
    if entry and entry.get("sha256") == _sha(video):
        name = entry["name"]
    else:
        date = datetime.fromtimestamp(marker_path.stat().st_mtime).strftime("%Y-%m-%d")
        title = _title(str(_json(manifest).get("deck_title") or "카드 영상"))
        base = f"{date}_{title}"
        number = 1
        while (videos / f"{base}_{number:02d}_검수대기.mp4").exists() or (proofs / f"{base}_{number:02d}_검수대기.png").exists():
            number += 1
        name = f"{base}_{number:02d}_검수대기"
    exported_video = videos / f"{name}.mp4"
    exported_proof = proofs / f"{name}.png"
    _copy(video, exported_video); _copy(proof, exported_proof)
    entries[key] = {"name": name, "sha256": _sha(video), "source": str(video), "proof": str(proof)}
    _save(catalog_path, catalog)
    return {**status, "finder_video": str(exported_video), "finder_proof": str(exported_proof)}


def organize(root: Path = ROOT) -> dict:
    reels = project_path("reels_root", root)
    work = project_path("reels_work", root)
    destinations = {work, project_path("reels_videos", root), project_path("reels_proofs", root)}
    for directory in destinations | {reels}:
        directory.mkdir(parents=True, exist_ok=True)
    moved = []
    for source in sorted(reels.iterdir()):
        if source.name.startswith(".") or source in destinations or source.is_symlink():
            continue
        if source.name == "storyboard-draft.md":
            destination = work / "릴스 구성 기준.md"
        elif source.is_dir():
            destination = work / source.name
        else:
            continue
        if destination.exists():
            raise FileExistsError(f"폴더가 겹쳐 이동을 중단했습니다: {source.name}")
        source.rename(destination)
        try:
            source.symlink_to(os.path.relpath(destination, source.parent), target_is_directory=destination.is_dir())
            if sys.platform == "darwin":
                subprocess.run(["/usr/bin/chflags", "-h", "hidden", str(source)], check=True)
        except Exception:
            # Restore the original location if its compatibility route fails.
            if source.is_symlink():
                source.unlink()
            destination.rename(source)
            raise
        moved.append({"old": str(source), "new": str(destination)})
    exports = []
    for manifest in reel_manifests(reels, root):
        marker_path = manifest.parent / "renders/latest.json"
        status = _json(marker_path)
        result = export_render({**status, "manifest": str(manifest)}, root)
        if result.get("finder_video"):
            exports.append(result["finder_video"])
    report = {"moved_packages": moved, "exported_videos": exports,
              "deleted_originals": False, "automatic_publishing": False}
    # Append records so rerunning does not discard the original relocation map.
    report_path = work / ".organization.json"
    history = _json(report_path).get("runs", [])
    _save(report_path, {"runs": [*history, report]})
    return report


def archive_fixture_cards(root: Path = ROOT) -> dict:
    """Separate known temporary unit-test decks from the user's card library."""
    library = project_path("cards_library", root)
    archive = root / "production/card_motion/tests/artifacts/archived-card-news"
    temporary_root = Path(tempfile.gettempdir()).resolve()
    candidates = []
    for folder in sorted(library.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        data = _json(folder / "cards.json")
        plan = Path(str(data.get("plan") or ".")).resolve()
        if (data.get("title") == "테스트" and data.get("source_id") == ""
                and plan.name == "card-plan.json" and plan.is_relative_to(temporary_root)
                and plan.parent.name.startswith("tmp") and len(data.get("cards", [])) == 4):
            candidates.append(folder)
    for folder in candidates:
        if (archive / folder.name).exists():
            raise FileExistsError("같은 테스트 보관 폴더가 있어 덮어쓰지 않습니다")
    archive.mkdir(parents=True, exist_ok=True)
    records = []
    for folder in candidates:
        target = archive / folder.name
        folder.rename(target)
        records.append({"from": str(folder), "to": str(target)})
    receipt = archive / ".relocations.json"
    history = _json(receipt).get("files", [])
    _save(receipt, {"files": [*history, *records], "deleted": False})
    return {"test_decks_archived": len(records), "archive": str(archive), "deleted": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="릴스 자료를 프로젝트 안에서 정리합니다")
    parser.add_argument("--organize", action="store_true")
    parser.add_argument("--archive-fixtures", action="store_true")
    args = parser.parse_args()
    if not args.organize and not args.archive_fixtures:
        parser.error("--organize 또는 --archive-fixtures를 지정해야 합니다")
    report = {}
    if args.organize:
        report.update(organize())
    if args.archive_fixtures:
        report.update(archive_fixture_cards())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
