"""Card copy for Threads posts: prompt, answer checks, and the Codex route.

The same prompt works for ChatGPT on the web and for Codex. Answers are checked
before anything is drawn: the 4–6 card structure, every layout's required
fields, illustration names, and Latin words or numbers not present in the post.
The source post id deterministically picks a card theme. New Reel specs use
the native motion generator; retries keep the same design without state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import icons
from render_cards import COVERS, ENDINGS, LAYOUTS, THEMES, scratch_directory
from render_reel import STYLES as HTML_REEL_STYLES


# copy and hand_arrow are UI decoration functions; clipboard and roads have their own cover fields.
ICONS = set(icons.DRAWINGS) - {"copy", "hand_arrow", "clipboard", "roads"}
LIST_ICONS = set(icons.GLYPHS)
COVER_ICONS = set(icons.GLYPHS)
CHARACTERS = {"human", "creature"}
VISUALS = {*CHARACTERS, "roads"}
BAND_VISUALS = {*CHARACTERS, "icons", "roads"}
ALLOWED_TERMS = {"ai"}
DEFAULT_MODEL = "gpt-5.6-terra"
AUTO_REEL_STYLES = ("motion",)
REEL_STYLES = (*HTML_REEL_STYLES, *AUTO_REEL_STYLES)
SETTING_KEYS = {
    "layout", "icon", "icon_left", "icon_text", "icons", "visual", "prop", "character",
    "marks_line", "slim", "bar", "theme", "reel_style",
}
RULES = """너는 인스타그램 카드뉴스 문안 편집자야. 아래 스레드 글마다 4~6장짜리 카드뉴스 문안을 만들어.
캔버스나 파일을 쓰지 말고, 설명 없이 ```json 코드블록 하나로만 답해.

사실·문장 규칙
- 원문에 있는 사실만 쓴다. 원문에 없는 숫자, 기능, 성과, 평가, 가격, 제품명을 만들지 않는다.
- 제목만 자극적으로 바꾸지 않는다. 원문의 핵심 결론·비교·순서·표현을 보존한다.
- 짧은 해요체로 쓴다. 본문 한 줄은 한글 20자 안팎, 제목 한 줄은 12자 안팎이다.
- 줄바꿈은 \\n으로 직접 넣고 2~3줄을 넘기지 않는다. 프롬프트 원문만 최대 6줄이다.
- 강조는 장마다 최대 2곳: {단어}=강조색, [단어]=밑줄. 두 괄호를 중첩하지 않는다.
- 한 카드에는 메시지 하나만 둔다. 같은 말을 제목·본문·결론에서 반복하지 않는다.

구성 규칙
- 첫 장은 cover / cover_vs / cover_band 중 하나, 마지막 장은 list / cta 중 하나다.
- 중간 장은 compare, split, steps, flow, grid, ranked, keyword, memo, prompt 중에서 고른다.
- 같은 레이아웃을 연속으로 쓰지 않는다. 단, 순위 항목을 한 장씩 보여주는 ranked만 최대 2장 연속 쓸 수 있다. CTA는 마지막 한 장에만 쓰고 행동 요청은 저장 하나만 쓴다.
- 비교가 핵심이면 cover_vs + compare 또는 split, 순서가 핵심이면 steps 또는 flow를 우선한다.
- 도구·항목이 4개면 grid, 순위 항목 하나를 크게 보여주면 ranked, 한 문장이 핵심이면 keyword를 쓴다.
- 원문의 정확한 입력문·프롬프트를 보여줄 때만 prompt, 팁 2~4개는 memo를 쓴다.
- 캐릭터는 한 덱에 최대 2장, 한 카드에 하나만 사용한다. 표지·마무리를 우선하고 정보보다 크게 만들 목적의 문구를 쓰지 않는다.
- `원글 미디어: 있음`으로 표시된 글은 프로그램이 실제 파일을 릴스에 따로 넣는다. 보지 못한 사진·영상 내용을 추측하거나 카드 문구로 설명하지 않는다.
- icon은 __ICONS__ 중 하나다. list·cta·cover 아이콘은 __LIST_ICONS__ 중 하나다.

레이아웃별 필드
- cover: layout,title, badge?,subtitle?, visual(roads|human|creature), prop?(clipboard), note?({title?,text,slim?})
- cover_vs: layout,left,right,title,subtitle?,icons?(0~3개),character?(human|creature)
- cover_band: layout,title,kicker?,visual(human|creature|roads|icons),number?,icons?(visual=icons일 때 1~3개)
- compare: layout,label?,title,body?,left/right({name,text,icon}),connector?,note?
- split: layout,label?,title,left/right({name,text,icon}),verdict?,verdict_label?
- steps: layout,title,steps 2~4개({lead,key,icon?/icon_left?/character?/badge?/options?}),note?
- flow: layout,title,body?,steps 정확히 3개({name,text,icon,icon_text?}),note?
- grid: layout,label?,title,items 정확히 4개({name,text,icon}),note?
- ranked: layout,rank,name,tag?,text,icon,note?
- keyword: layout,kicker?,text,sub?,character?
- memo: layout,label?,title,items 2~4개({title,text}),note?
- prompt: layout,label?,title,box_label?,prompt(원문의 정확한 문구),after?,character?,note?
- list: layout,title,items 2~4개({icon,title,text}),highlight?({title,text})
- cta: layout,kicker?,title,icon?(기본 bookmark),points(2~3개),character?

답 형식: {"posts":[{"id":"글 ID 그대로","cards":[카드 4~6개]}]} 글마다 하나씩 넣는다."""


def build_prompt(posts: list[dict[str, Any]]) -> str:
    rules = RULES.replace("__ICONS__", ", ".join(sorted(ICONS)))
    rules = rules.replace("__LIST_ICONS__", ", ".join(sorted(LIST_ICONS)))
    blocks = []
    for post in posts:
        media = post.get("_media_types", [])
        media_note = f"있음 ({', '.join(media)}) — 내용 추측 금지" if media else "없음"
        blocks.append(f"글 ID: {post['id']}\n원글 미디어: {media_note}\n<<<\n{str(post['text']).strip()}\n>>>")
    return f"{rules}\n\n원문\n{'\n\n'.join(blocks)}\n"


def extract_json(answer: str) -> Any:
    text = answer.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("답에서 JSON을 찾지 못했습니다")
    return json.loads(text[start:end + 1])


def looks_like_answer(text: str) -> bool:
    try:
        data = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and isinstance(data.get("posts", data.get("cards")), list)


def text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 문구가 없습니다")
    return value


def items(value: Any, minimum: int, maximum: int, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} 항목은 {minimum}~{maximum}개여야 합니다")
    return value


def check_icon(value: Any, allowed: set[str], label: str) -> None:
    if value not in allowed:
        raise ValueError(f"{label} 아이콘이 목록에 없습니다: {value}")


def check_pair(card: dict[str, Any], index: int) -> None:
    for key in ("left", "right"):
        side = card.get(key)
        if not isinstance(side, dict):
            raise ValueError(f"{index}장 {key} 항목이 없습니다")
        text(side.get("name"), f"{index}장 {key}.name")
        text(side.get("text"), f"{index}장 {key}.text")
        check_icon(side.get("icon"), ICONS, f"{index}장 {key}")


def check_cards(cards: Any) -> list[dict[str, Any]]:
    if not isinstance(cards, list) or not 4 <= len(cards) <= 6:
        raise ValueError("카드는 4~6장이어야 합니다")
    if not all(isinstance(card, dict) for card in cards):
        raise ValueError("카드 형식이 올바르지 않습니다")
    if cards[0].get("layout") not in COVERS:
        raise ValueError(f"첫 장은 {', '.join(sorted(COVERS))} 중 하나여야 합니다")
    if cards[-1].get("layout") not in ENDINGS:
        raise ValueError(f"마지막 장은 {', '.join(sorted(ENDINGS))} 중 하나여야 합니다")
    for index, card in enumerate(cards, start=1):
        layout = card.get("layout")
        if layout not in LAYOUTS:
            raise ValueError(f"{index}장 레이아웃이 올바르지 않습니다: {layout}")
        if index > 1 and layout in COVERS:
            raise ValueError(f"{index}장에는 표지 레이아웃을 쓸 수 없습니다")
        if index < len(cards) and layout in ENDINGS:
            raise ValueError(f"{index}장에는 마무리 레이아웃을 쓸 수 없습니다")
        if index > 1 and layout == cards[index - 2].get("layout") and layout != "ranked":
            raise ValueError(f"{index - 1}장과 {index}장 레이아웃이 같습니다: {layout}")
        if index > 2 and layout == "ranked" and all(card_before.get("layout") == "ranked" for card_before in cards[index - 3:index]):
            raise ValueError("ranked는 최대 2장까지만 연속으로 쓸 수 있습니다")

        if layout == "cover":
            text(card.get("title"), f"{index}장 title")
            card.setdefault("visual", "human")
            if card["visual"] not in VISUALS:
                raise ValueError(f"{index}장 visual이 올바르지 않습니다: {card['visual']}")
            if card.get("prop") not in {None, "clipboard"}:
                raise ValueError(f"{index}장 prop이 올바르지 않습니다")
        elif layout == "cover_vs":
            for key in ("left", "right", "title"):
                text(card.get(key), f"{index}장 {key}")
            if card.get("character") not in {None, *CHARACTERS}:
                raise ValueError(f"{index}장 캐릭터가 올바르지 않습니다")
            names = card.get("icons", [])
            if not isinstance(names, list) or len(names) > 3:
                raise ValueError(f"{index}장 icons는 최대 3개입니다")
            for name in names:
                check_icon(name, COVER_ICONS, f"{index}장")
        elif layout == "cover_band":
            text(card.get("title"), f"{index}장 title")
            card.setdefault("visual", "human")
            if card["visual"] not in BAND_VISUALS:
                raise ValueError(f"{index}장 visual이 올바르지 않습니다: {card['visual']}")
            names = card.get("icons", [])
            if card["visual"] == "icons" and not isinstance(names, list):
                raise ValueError(f"{index}장 icons 형식이 올바르지 않습니다")
            if card["visual"] == "icons" and not 1 <= len(names) <= 3:
                raise ValueError(f"{index}장 icons는 1~3개여야 합니다")
            for name in names:
                check_icon(name, COVER_ICONS, f"{index}장")
        elif layout in {"compare", "split"}:
            text(card.get("title"), f"{index}장 title")
            check_pair(card, index)
        elif layout == "steps":
            text(card.get("title"), f"{index}장 title")
            for step in items(card.get("steps"), 2, 4, f"{index}장 steps"):
                text(step.get("lead"), f"{index}장 step.lead")
                text(step.get("key"), f"{index}장 step.key")
                for key in ("icon", "icon_left"):
                    if key in step:
                        check_icon(step[key], ICONS, f"{index}장 step.{key}")
                if step.get("character") not in {None, *CHARACTERS}:
                    raise ValueError(f"{index}장 step 캐릭터가 올바르지 않습니다")
                options = step.get("options")
                if options is not None and (not isinstance(options, list) or not 2 <= len(options) <= 4
                                            or not all(isinstance(option, str) and option.strip() for option in options)):
                    raise ValueError(f"{index}장 step options는 문구 2~4개여야 합니다")
        elif layout == "flow":
            text(card.get("title"), f"{index}장 title")
            for step in items(card.get("steps"), 3, 3, f"{index}장 flow steps"):
                text(step.get("name"), f"{index}장 step.name")
                text(step.get("text"), f"{index}장 step.text")
                check_icon(step.get("icon"), ICONS, f"{index}장 step")
        elif layout == "grid":
            text(card.get("title"), f"{index}장 title")
            for item in items(card.get("items"), 4, 4, f"{index}장 grid items"):
                text(item.get("name"), f"{index}장 item.name")
                text(item.get("text"), f"{index}장 item.text")
                check_icon(item.get("icon"), ICONS, f"{index}장 item")
        elif layout == "ranked":
            for key in ("rank", "name", "text"):
                text(card.get(key), f"{index}장 {key}")
            check_icon(card.get("icon"), ICONS, f"{index}장")
        elif layout == "keyword":
            text(card.get("text"), f"{index}장 text")
            if card.get("character") not in {None, *CHARACTERS}:
                raise ValueError(f"{index}장 캐릭터가 올바르지 않습니다")
        elif layout == "memo":
            text(card.get("title"), f"{index}장 title")
            for item in items(card.get("items"), 2, 4, f"{index}장 memo items"):
                text(item.get("title"), f"{index}장 item.title")
                text(item.get("text"), f"{index}장 item.text")
        elif layout == "prompt":
            text(card.get("title"), f"{index}장 title")
            prompt = text(card.get("prompt"), f"{index}장 prompt")
            if len(prompt) > 240 or len(prompt.splitlines()) > 6:
                raise ValueError(f"{index}장 prompt는 240자·6줄 이하여야 합니다")
            if card.get("character") not in {None, *CHARACTERS}:
                raise ValueError(f"{index}장 캐릭터가 올바르지 않습니다")
        elif layout == "list":
            text(card.get("title"), f"{index}장 title")
            for item in items(card.get("items"), 2, 4, f"{index}장 list items"):
                text(item.get("title"), f"{index}장 item.title")
                text(item.get("text"), f"{index}장 item.text")
                check_icon(item.get("icon"), LIST_ICONS, f"{index}장 item")
            if card.get("highlight"):
                text(card["highlight"].get("title"), f"{index}장 highlight.title")
                text(card["highlight"].get("text"), f"{index}장 highlight.text")
        elif layout == "cta":
            text(card.get("title"), f"{index}장 title")
            check_icon(card.setdefault("icon", "bookmark"), LIST_ICONS, f"{index}장")
            points = card.get("points", [])
            if not isinstance(points, list) or not 2 <= len(points) <= 3 or not all(isinstance(point, str) and point.strip() for point in points):
                raise ValueError(f"{index}장 points는 문구 2~3개여야 합니다")
            if card.get("character") not in {None, *CHARACTERS}:
                raise ValueError(f"{index}장 캐릭터가 올바르지 않습니다")

    character_cards = sum(
        card.get("character") in CHARACTERS
        or card.get("visual") in CHARACTERS
        or any(step.get("character") in CHARACTERS for step in card.get("steps", []))
        for card in cards)
    if character_cards > 2:
        raise ValueError("캐릭터 카드는 한 덱에 최대 2장만 쓸 수 있습니다")
    for shown in visible_text(cards):
        if len(shown) > 360:
            raise ValueError("카드 문구 하나가 360자를 넘습니다")
    return cards


def parse_answer(answer: str, post_ids: list[str]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Split one answer into checked card lists per post, plus a reason for each post that failed."""
    try:
        data = extract_json(answer)
    except (ValueError, json.JSONDecodeError) as exc:
        return {}, {post_id: f"답 JSON을 읽지 못했습니다: {exc}" for post_id in post_ids}
    if isinstance(data, dict) and "cards" in data and len(post_ids) == 1:
        data = {"posts": [{"id": post_ids[0], "cards": data["cards"]}]}
    posts = data.get("posts") if isinstance(data, dict) else None
    if not isinstance(posts, list):
        return {}, {post_id: "답에 posts 목록이 없습니다" for post_id in post_ids}
    results: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for item in posts:
        post_id = str(item.get("id", "")) if isinstance(item, dict) else ""
        if post_id not in post_ids or post_id in results:
            continue
        try:
            results[post_id] = check_cards(item.get("cards"))
        except (ValueError, TypeError, AttributeError) as exc:
            errors[post_id] = str(exc)
    for post_id in post_ids:
        if post_id not in results:
            errors.setdefault(post_id, "답에 이 글이 없습니다")
    return results, errors


def visible_text(value: Any) -> list[str]:
    """Every string a reader will see, skipping layout and illustration settings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [shown for key, item in value.items() if key not in SETTING_KEYS for shown in visible_text(item)]
    if isinstance(value, list):
        return [shown for item in value for shown in visible_text(item)]
    return []


WORD_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*")
# Keep the unit with a number.  A bare `100` in a source saying `1000원` must
# never be accepted through substring matching, and `100%` has a different
# factual meaning from `100원`.
NUMBER_TOKEN = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?\s*(?:[%년월일시간분초원달러회개명번])?")


def _number_key(value: str) -> tuple[str, str]:
    """Return a numeric value and its visible unit, with grouping spaces removed."""
    compact = re.sub(r"\s+", "", value)
    match = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?)([%년월일시간분초원달러회개명번]?)", compact)
    if not match:  # Defensive: NUMBER_TOKEN is the only caller today.
        return compact, ""
    return match.group(1).replace(",", ""), match.group(2)


def unknown_terms(cards: list[dict[str, Any]], source: str) -> list[str]:
    """Visible Latin words and numeric claims that are absent from the source.

    This is deliberately mechanical.  It does not claim that prose is true;
    it prevents an answer from introducing a new English product name or an
    Arabic number.  Numbers are compared as complete tokens, never substrings.
    A source's `1000원` therefore cannot approve `100%` or `100`.
    """
    source_words = {word.casefold() for word in WORD_TOKEN.findall(source)}
    source_numbers = {_number_key(token) for token in NUMBER_TOKEN.findall(source)}
    unknown: set[str] = set()
    for shown in visible_text(cards):
        for word in WORD_TOKEN.findall(shown):
            if word.casefold() not in source_words and word.casefold() not in ALLOWED_TERMS:
                unknown.add(word)
        for token in NUMBER_TOKEN.findall(shown):
            value, unit = _number_key(token)
            # A unit printed on a card is a claim.  If the source only showed
            # the number without that unit, force the author to keep it out.
            allowed = (value, unit) in source_numbers if unit else any(number == value for number, _ in source_numbers)
            if not allowed:
                unknown.add(token.strip())
    return sorted(unknown)


def design_for(post: dict[str, Any]) -> tuple[str, str]:
    """Choose a stable bright information layout from the post's actual subject.

    Topic words bias the deck palette while the source hash keeps retries
    stable. The automatic Reel route always chooses editable native motion.
    """
    identity = str(post.get("id") or post.get("permalink") or post.get("timestamp") or "post")
    source = str(post.get("text") or "")
    subject = source.casefold()
    checksum = int.from_bytes(hashlib.blake2s(f"{identity}\n{source}".encode(), digest_size=8).digest())
    if (any(term in subject for term in ("가격", "비용", "절약", "돈", "달러", "구독"))
            or re.search(r"\d[\d,]*\s*원", source)):
        themes = ("kraft", "mono")
    elif any(term in subject for term in ("코드", "앱", "위젯", "개발", "자동화", "api", "프롬프트")):
        themes = ("mint", "paper", "mono")
    elif any(term in subject for term in ("디자인", "이미지", "영상", "사진", "편집", "릴스")):
        themes = ("paper", "gray", "mono")
    else:
        themes = tuple(THEMES)
    return themes[checksum % len(themes)], "motion"


def build_spec(post: dict[str, Any], cards: list[dict[str, Any]], series: str, *,
               theme: str | None = None, reel_style: str | None = None,
               media: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cards = copy.deepcopy(cards)
    username = str(post.get("username") or "").lstrip("@")
    permalink = str(post.get("permalink") or "")
    chosen_theme, chosen_style = design_for(post)
    theme, reel_style = theme or chosen_theme, reel_style or chosen_style
    if theme not in THEMES or reel_style not in REEL_STYLES:
        raise ValueError(f"디자인 선택이 올바르지 않습니다: {theme}/{reel_style}")
    cards[-1]["sources_label"] = "원문"
    cards[-1]["sources"] = [["Threads", re.sub(r"^https?://(www\.)?", "", permalink)]]
    spec = {"handle": f"@{username}", "series": series, "theme": theme, "reel_style": reel_style,
            "source": {"id": post.get("id"), "permalink": permalink, "timestamp": post.get("timestamp")},
            "audio": ({"decision": "sfx_only", "reason": "음악 없이 주요 화면 전환에만 짧은 효과음"}
                      if reel_style == "motion" else
                      {"decision": "review_required",
                       "reason": "원문 주제에 맞는 승인 음원을 지정한 뒤 릴스를 만듭니다"}),
            "cards": cards}
    if media:
        spec.update(media_root="../source-media", media=copy.deepcopy(media))
    return spec


def ask_codex(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 600) -> str:
    """Codex with the signed-in ChatGPT account, read-only, inside an empty folder."""
    codex = shutil.which("codex") or "/opt/homebrew/bin/codex"
    with tempfile.TemporaryDirectory(prefix="card-copy-", dir=scratch_directory("card-copy")) as work:
        answer = Path(work) / "answer.txt"
        result = subprocess.run(
            [codex, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
             "-m", model, "-o", str(answer), prompt],
            cwd=work, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0 or not answer.is_file():
            tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["출력 없음"]
            raise RuntimeError(f"Codex 실행 실패: {tail[0][:200]}")
        return answer.read_text(encoding="utf-8")
