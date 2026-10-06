"""Adopt only the exact motion-guide images identified in the user's screenshot."""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from storage import ROOT, _sha, _save

NAMES = {
    "검색되는 이름으로 정리한 모션 가이드.png",
    "검색 가능한 모션디자인 명칭 정리-2.png",
    "AI 영상 프롬프트 작성 가이드.png",
    "AI 모션효과 속도와 물리 치트시트.png",
    "AI 모션효과 일러스트 포스터.png",
    "AI 모션효과 핵심 15개.png",
    "AI 모션효과 7~12번 인포그래픽.png",
    "AI 모션효과 50개 정리해봄.png",
    "AI 모션효과 39~44번 미리보기.png",
    "귀여운 모션효과 인포그래픽 19–24.png",
    "AI 모션효과 32~38번 미리보기.png",
    "텍스트 효과 1~6번 인포그래픽.png",
    "AI 모션효과 25~31 인포그래픽.png",
    "AI 모션효과 7~12번 미리보기.png",
    "13~18번 AI 모션효과 미리보기.png",
    "AI 모션효과 19~24 인포그래픽.png",
    "AI 모션효과 45~50 인포그래픽.png",
    "AI 모션효과 50개 정리 포스터.png",
    "AI 영상 프롬프트 작성법 인포그래픽.png",
    "특이한 효과 15개 인포그래픽.png",
    "검색 가능한 모션디자인 명칭 정리.png",
}


def main() -> None:
    downloads = Path.home() / "Downloads"
    destination = ROOT / "research/reference-collection/모션효과 가이드"
    candidates = [path for path in downloads.iterdir()
                  if unicodedata.normalize("NFC", path.name) in NAMES
                  and path.is_file() and not path.is_symlink()]
    # Preflight every exact target before moving the first file.
    targets = [(path, destination / unicodedata.normalize("NFC", path.name), _sha(path))
               for path in candidates]
    for _, target, _ in targets:
        if target.exists():
            raise FileExistsError(f"같은 이름의 자료가 이미 있어 덮어쓰지 않습니다: {target.name}")
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for source, target, digest in targets:
        source.rename(target)
        if _sha(target) != digest:
            target.rename(source)
            raise ValueError("이동한 자료의 파일 검증에 실패했습니다")
        records.append({"from":str(source),"to":str(target),"sha256":digest})
    receipt = destination / ".relocations.json"
    previous = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {"files":[]}
    _save(receipt,{"files":[*previous["files"],*records],"deleted":False})
    print(json.dumps({"moved":len(records),"folder":str(destination),"original_bytes_preserved":True},ensure_ascii=False))


if __name__ == "__main__":
    main()
