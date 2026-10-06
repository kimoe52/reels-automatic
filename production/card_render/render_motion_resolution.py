#!/usr/bin/env python3
"""Author the editable 480p/upscale motion graphic for the verified Threads post.

This is an explicit story variant, not a generic AI-written video template. Text is
checked against the preserved source before native Tesseract actions are emitted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BLUE = "#265FF2"
INK = "#15191F"
PAPER = "#F7F7F2"
PALE = "#E7EEFF"
WHITE = "#FFFFFF"
CORAL = "#FF6E62"
CORAL_PALE = "#FFEAE6"
MINT = "#DFF3E8"
LINE = "#CFD6DE"
MUTED = "#667080"
FONT_DISPLAY = ("Black Han Sans", "Regular")
FONT_BODY = ("Pretendard Variable", "Bold")
SCENES = [(0, 3200), (3200, 8000), (8000, 13200), (13200, 18500), (18500, 23500)]


def color(hex_value: str) -> list[float]:
    raw = hex_value.lstrip("#")
    return [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1]


def transform(x: float, y: float, anchor=(0, 0), rotation=0, opacity=100) -> dict:
    return {"anchorPoint": list(anchor), "position": [x, y], "scale": [100, 100],
            "rotation": rotation, "opacity": opacity}


class Author:
    def __init__(self):
        self.actions: list[dict] = []
        self.next_id = 1

    def rect(self, name: str, x: float, y: float, w: float, h: float, fill: str,
             start: int, end: int, roundness=0, stroke: str | None = None, stroke_width=0) -> int:
        layer_id = self.next_id
        self.next_id += 1
        shape = {"size": [w, h], "fillColor": color(fill), "roundness": roundness}
        if stroke:
            shape.update({"strokeEnabled": True, "strokeColor": color(stroke), "strokeWidth": stroke_width})
        self.actions.append({"type": "createFxRectLayer", "compositionId": "main", "layerId": layer_id,
                             "name": name, "insertIndex": 0,
                             "activeRange": {"start": start, "duration": end - start},
                             "transform": transform(x, y), "rect": shape})
        return layer_id

    def text(self, name: str, content: str, x: float, y: float, w: float, h: float,
             size: float, fill: str, start: int, end: int, *, display=False,
             align="left", opacity=100) -> int:
        layer_id = self.next_id
        self.next_id += 1
        family, style = FONT_DISPLAY if display else FONT_BODY
        self.actions.append({"type": "createFxTextLayer", "compositionId": "main", "layerId": layer_id,
                             "name": name, "insertIndex": 0,
                             "activeRange": {"start": start, "duration": end - start},
                             "transform": transform(x, y, opacity=opacity),
                             "sourceText": {"text": content, "fontFamily": family, "fontStyle": style,
                                            "fontSize": size, "fillColor": color(fill),
                                            "justification": align, "boxText": True,
                                            "boxPosition": [0, 0], "boxSize": [w, h],
                                            "leading": size * 1.15}})
        return layer_id

    def keys(self, layer_id: int, property_type: str, points: list[tuple[int, float]], *, smooth=True) -> None:
        keyframes = []
        for index, (time_ms, value) in enumerate(points):
            easing = ({"type": "cubicBezier", "x1": .18, "y1": .78, "x2": .22, "y2": 1}
                      if smooth and index else {"type": "linear"})
            keyframes.append({"id": f"layer-{layer_id}-{property_type}-{time_ms}",
                              "layerTime": time_ms, "value": {"type": "float", "value": value},
                              "easing": easing})
        self.actions.append({"type": "setFxPropertyKeyframes", "compositionId": "main",
                             "property": {"layerId": layer_id, "propertyType": property_type},
                             "keyframes": keyframes})

    def enter(self, layer_id: int, x: float, y: float, at: int, *, dx=0, dy=80,
              duration=420, fade=True) -> None:
        def leading(value: float) -> list[tuple[int, float]]:
            return [(0, value)] + ([(at, value)] if at else [])
        if dx:
            self.keys(layer_id, "positionX", leading(x + dx) + [(at + duration, x)])
        if dy:
            self.keys(layer_id, "positionY", leading(y + dy) + [(at + duration, y)])
        if fade:
            self.keys(layer_id, "opacity", leading(0) + [(at + min(duration, 260), 100)])

    def punch(self, layer_id: int) -> None:
        # Keep a meaningful first frame: the headline is present at the cut
        # while its subtle settle still provides impact
        self.keys(layer_id, "scaleX", [(0, 104), (250, 100)])
        self.keys(layer_id, "scaleY", [(0, 104), (250, 100)])

    def base(self, index: int, section: str, background=PAPER) -> tuple[int, int]:
        start, end = SCENES[index]
        self.rect(f"{index + 1} 배경", 0, 0, 1080, 1920, background, start, end)
        self.rect(f"{index + 1} 좌측 포인트", 70, 149, 14, 14, BLUE, start, end, 7)
        self.text(f"{index + 1} 계정", "@sto.ckai", 101, 132, 300, 60, 31, INK, start, end)
        self.text(f"{index + 1} 장면 라벨", section, 70, 216, 900, 90, 41, MUTED, start, end)
        self.rect(f"{index + 1} 하단 구분선", 70, 1504, 940, 3, LINE, start, end)
        self.text(f"{index + 1} 출처", "원문  Threads @sto.ckai", 70, 1532, 850, 60, 30, MUTED, start, end)
        for n in range(5):
            self.rect(f"{index + 1} 진행 {n + 1}", 70 + n * 190, 1477, 174, 8,
                      BLUE if n < index else LINE, start, end, 4)
        progress = self.rect(f"{index + 1} 진행 중", 70 + index * 190, 1477, 174, 8,
                             BLUE, start, end, 4)
        self.keys(progress, "scaleX", [(0, 0), (end - start - 100, 100)], smooth=False)
        return start, end


def author_actions() -> list[dict]:
    a = Author()

    # 0–3.2s: large, immediate claim; red slash is the one deliberate jolt.
    s, e = a.base(0, "AI 영상 만들 때")
    title = a.text("첫 질문", "720p부터?", 67, 352, 970, 226, 178, INK, s, e, display=True)
    a.punch(title)
    token = a.text("토큰 아까움", "토큰 아까움", 75, 631, 960, 188, 139, INK, s, e, display=True)
    a.enter(token, 75, 631, 350, dx=-240, dy=0)
    slash = a.rect("720p 먼저 시작 금지선", 72, 569, 840, 24, CORAL, s, e, 12)
    a.keys(slash, "scaleX", [(0, 0), (900, 0), (1190, 100)])
    badge = a.rect("480p 먼저 배경", 70, 938, 660, 172, BLUE, s, e, 38)
    a.enter(badge, 70, 938, 1280, dx=680, dy=0, duration=420)
    label = a.text("480p 먼저", "480p 먼저", 102, 959, 615, 138, 97, WHITE, s, e, display=True)
    a.enter(label, 102, 959, 1330, dx=680, dy=0, duration=420)
    reason = a.text("첫 근거", "한 번에 원하는 장면이\n잘 나오지 않으니까", 78, 1178, 930, 188, 60, INK, s, e)
    a.enter(reason, 78, 1178, 1810, dy=60)

    # 3.2–8s: retries are visible as repeated tiles; 720p means costlier misses.
    s, e = a.base(1, "왜 처음엔 480p인가")
    headline = a.text("반복 생성 설명", "같은 프롬프트도\n여러 번 뽑게 됨", 72, 338, 936, 246, 101, INK, s, e, display=True)
    a.punch(headline)
    a.rect("480p 비교판", 70, 676, 448, 524, PALE, s, e, 38)
    a.rect("720p 비교판", 562, 676, 448, 524, CORAL_PALE, s, e, 38)
    left = a.text("480p 라벨", "480p", 107, 715, 370, 160, 124, BLUE, s, e, display=True)
    right = a.text("720p 라벨", "720p", 598, 715, 370, 160, 124, INK, s, e, display=True)
    a.enter(left, 107, 715, 470, dx=-430, dy=0)
    a.enter(right, 598, 715, 670, dx=430, dy=0)
    for i in range(3):
        tile = a.rect(f"480p 시도 {i + 1}", 111 + i * 112, 911, 88, 138, WHITE, s, e, 14, BLUE, 4)
        a.enter(tile, 111 + i * 112, 911, 970 + i * 120, dy=110, duration=330)
    a.text("여러 번 시도", "여러 번 시도", 107, 1072, 370, 90, 47, INK, s, e)
    for i in range(3):
        tile = a.rect(f"720p 실패작 {i + 1}", 601 + i * 112, 911, 88, 138, WHITE, s, e, 14, CORAL, 4)
        a.enter(tile, 601 + i * 112, 911, 1110 + i * 110, dy=110, duration=330)
    a.text("실패작도 고해상도", "실패작도 고해상도", 599, 1072, 390, 95, 41, INK, s, e)
    # The bars convey a comparison, not a measured token ratio
    bar_a = a.rect("480p 토큰 바", 107, 1180, 260, 8, BLUE, s, e, 4)
    bar_b = a.rect("720p 토큰 바", 599, 1180, 354, 8, CORAL, s, e, 4)
    a.keys(bar_a, "scaleX", [(0, 0), (1750, 0), (2130, 100)])
    a.keys(bar_b, "scaleX", [(0, 0), (1930, 0), (2410, 100)])
    tail = a.text("토큰 차이", "720p는 생성 토큰을 더 씀", 80, 1282, 920, 118, 61, INK, s, e, display=True)
    a.enter(tail, 80, 1282, 2000, dy=80)

    # 8–13.2s: a visible three-step pipeline, selected frame stays the same.
    s, e = a.base(2, "추천 순서")
    head = a.text("순서 제목", "뽑고 → 고르고 → 키우기", 70, 331, 970, 192, 85, INK, s, e, display=True)
    a.punch(head)
    steps = [
        ("01", "480p로 여러 번 생성", 588, PALE, BLUE, -660),
        ("02", "마음에 드는 하나 선택", 832, WHITE, INK, 660),
        ("03", "선택본만 업스케일", 1076, MINT, INK, -660),
    ]
    for idx, (num, copy, y, fill, ink, offset) in enumerate(steps):
        card = a.rect(f"단계 {num} 패널", 70, y, 940, 190, fill, s, e, 34, BLUE if idx == 1 else None, 5)
        a.enter(card, 70, y, 350 + idx * 650, dx=offset, dy=0, duration=470)
        number = a.text(f"단계 {num} 번호", num, 107, y + 37, 120, 103, 72, BLUE, s, e, display=True)
        a.enter(number, 107, y + 37, 430 + idx * 650, dx=offset, dy=0, duration=470)
        body = a.text(f"단계 {num} 문구", copy, 236, y + 55, 720, 92, 58, ink, s, e)
        a.enter(body, 236, y + 55, 460 + idx * 650, dx=offset, dy=0, duration=470)
    a.rect("단계 연결선 1", 532, 790, 14, 38, BLUE, s, e, 7)
    a.rect("단계 연결선 2", 532, 1034, 14, 38, BLUE, s, e, 7)
    tracker = a.rect("진행 선택 표시", 52, 638, 12, 80, BLUE, s, e, 6)
    a.keys(tracker, "positionY", [(0, 638), (1250, 638), (2000, 882),
                                   (2850, 882), (3650, 1126)])
    foot = a.text("선택본만", "선택한 영상만 화질을 높임", 77, 1340, 920, 89, 50, BLUE, s, e)
    a.enter(foot, 77, 1340, 3030, dy=70)

    # 13.2–18.5s: explicit distinction; same card geometry remains on upscale lane.
    s, e = a.base(3, "여기서 중요한 차이")
    heading = a.text("업스케일 부등호", "업스케일 ≠ 재생성", 65, 346, 960, 185, 103, INK, s, e, display=True)
    a.punch(heading)
    underline = a.rect("차이 강조선", 70, 558, 902, 16, BLUE, s, e, 8)
    a.keys(underline, "scaleX", [(0, 0), (520, 0), (900, 100)])
    a.rect("재생성 설명 배경", 70, 674, 440, 545, CORAL_PALE, s, e, 36)
    a.rect("업스케일 설명 배경", 570, 674, 440, 545, PALE, s, e, 36)
    left_title = a.text("재생성", "720p 재생성", 105, 713, 370, 110, 64, INK, s, e, display=True)
    right_title = a.text("업스케일", "업스케일", 605, 713, 370, 110, 75, BLUE, s, e, display=True)
    a.enter(left_title, 105, 713, 500, dx=-360, dy=0)
    a.enter(right_title, 605, 713, 700, dx=360, dy=0)
    # Two variants on the left versus one retained frame expanding on the right.
    a.rect("재생성 원본 프레임", 147, 866, 190, 140, WHITE, s, e, 16, CORAL, 5)
    changed = a.rect("재생성 변경 프레임", 231, 919, 190, 140, WHITE, s, e, 16, CORAL, 5)
    a.keys(changed, "rotation", [(0, 0), (1350, 0), (1770, 12)])
    original = a.rect("업스케일 원본 프레임", 681, 889, 197, 148, WHITE, s, e, 16, BLUE, 5)
    a.keys(original, "scaleX", [(0, 70), (1500, 70), (2300, 115)])
    a.keys(original, "scaleY", [(0, 70), (1500, 70), (2300, 115)])
    a.text("재생성 차이", "구도·움직임·얼굴\n달라질 수 있음", 101, 1075, 372, 127, 42, INK, s, e)
    a.text("업스케일 차이", "이미 고른 영상 그대로\n해상도·선명도만 높임", 600, 1075, 385, 127, 42, INK, s, e)
    bottom = a.text("개념 정리", "다시 뽑는 게 아니라 후처리", 82, 1296, 916, 100, 57, INK, s, e, display=True)
    a.enter(bottom, 82, 1296, 2800, dy=80)

    # 18.5–23.5s: the source's dice analogy, with one winning tile retained.
    s, e = a.base(4, "한 줄로 정리")
    last = a.text("480p 비유", "480p = 주사위 굴리기", 64, 348, 970, 170, 102, INK, s, e, display=True)
    a.punch(last)
    for idx, x in enumerate([125, 345, 565, 785]):
        tile = a.rect(f"주사위 후보 {idx + 1}", x, 612, 162, 242, WHITE, s, e, 24,
                      BLUE if idx == 2 else LINE, 7 if idx == 2 else 4)
        a.enter(tile, x, 612, 420 + idx * 160, dy=250, duration=420)
        if idx == 2:
            a.rect("선택 표시", x + 18, 630, 126, 24, BLUE, s, e, 12)
    arrow = a.rect("당첨 화살표 가로", 331, 936, 418, 18, BLUE, s, e, 9)
    arrow_head = a.rect("당첨 화살표 머리", 718, 915, 52, 52, BLUE, s, e, 12)
    a.keys(arrow, "scaleX", [(0, 0), (1500, 0), (1870, 100)])
    a.keys(arrow_head, "opacity", [(0, 0), (1780, 0), (1950, 100)])
    outcome = a.text("업스케일 비유", "업스케일 =\n당첨본 화질 마감", 69, 1025, 940, 268, 104, INK, s, e, display=True)
    a.enter(outcome, 69, 1025, 1900, dy=100, duration=430)
    coda = a.text("마지막 결론", "잘 나온 하나만 720p·1080p로", 75, 1338, 920, 86, 49, BLUE, s, e)
    a.enter(coda, 75, 1338, 2750, dy=70)

    return a.actions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    source = json.loads((args.spec.parent.parent / "source.json").read_text(encoding="utf-8"))
    if spec.get("source", {}).get("id") != "18001430661007646" or source.get("id") != "18001430661007646":
        raise ValueError("이 모션 구성은 확인된 480p·업스케일 원문에만 사용합니다")
    for phrase in ("720p부터 돌리면 토큰 아까움", "480p로 여러 번 생성", "업스케일 ≠ 720p로 다시 생성", "주사위 굴리는 단계"):
        if phrase not in source["text"]:
            raise ValueError(f"원문과 모션 대본이 어긋났습니다: {phrase}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(author_actions(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
