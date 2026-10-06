#!/usr/bin/env python3
"""Read the authenticated Threads user's posts without copying its token.

The existing blog automation owns the Meta credentials. This script only reads
that protected env file, fetches the user's Threads list, and stores a local
snapshot plus a small cursor state. It never publishes or prints post text.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
META_ROOT = ROOT / "automation" / "meta-threads"
sys.path.insert(0, str(META_ROOT))

from media_store import public_source, spec_items, sync_post_media  # noqa: E402
from thread_source import merge_author_thread, relation_id  # noqa: E402

DEFAULT_ENV = Path.home() / "Library" / "Application Support" / "AppMarketing" / ".env"
DEFAULT_API_BASE = "https://graph.threads.net/v1.0"
STATE_PATH = ROOT / "automation" / "meta-threads" / "state" / "threads_state.json"
SNAPSHOT_DIR = ROOT / "automation" / "meta-threads" / "fetch" / "snapshots"
QUEUE_DIR = ROOT / "automation" / "meta-threads" / "queue"
MEDIA_FIELDS = "id,media_type,media_url,thumbnail_url,alt_text"
FIELDS = f"id,text,timestamp,permalink,username,media_type,media_url,thumbnail_url,children,alt_text"
MAX_PAGES = 20
MAX_CHILDREN = 10
REPLY_FIELDS = "id,text,timestamp,permalink,username,root_post,replied_to,is_reply,is_reply_owned_by_me"


def fetch_reply_rows(token: str, api_base: str, *, root_id: str | None = None) -> list[dict[str, Any]]:
    """Exhaust author replies (or one conversation), never silently truncate."""
    base = urllib.parse.urlparse(api_base)
    if base.scheme != "https" or base.netloc != "graph.threads.net" or not re.fullmatch(r"/v\d+\.\d+", base.path):
        raise ValueError("Threads 공식 API 주소가 아니어서 후속 글을 조회하지 않았어요")
    if root_id is not None and not root_id.isdigit():
        raise ValueError("후속 원문의 글 ID 형식이 올바르지 않아요")
    endpoint = f"/{root_id}/conversation" if root_id else "/me/replies"
    query = urllib.parse.urlencode({"fields": REPLY_FIELDS, "limit": "50", "reverse": "false"})
    url = f"{api_base}{endpoint}?{query}"
    rows = []; visited = set()
    expected_path = base.path + endpoint
    for _ in range(MAX_PAGES):
        if url in visited:
            raise ValueError("Threads 댓글 페이지가 반복되어 조회를 중단했어요")
        visited.add(url)
        try:
            payload = request_json(url, token)
        except RuntimeError as exc:
            status = re.search(r"HTTP (\d{3})", str(exc))
            raise ValueError("Threads 후속 글 조회 불가" + (f" · HTTP {status.group(1)}" if status else "")
                             + " · 기존 연결의 댓글 읽기 권한·연결을 확인해야 해요") from None
        rows.extend(page_rows(payload))
        link = next_page_url(payload, api_base)
        if link and not root_id:
            parsed_link = urllib.parse.urlparse(link)
            # Graph's pagination ID can differ from the app-scoped /me ID.
            # Keep pagination on /me, using only its returned cursor/query:
            # never switch the authenticated request to another numeric user.
            if re.fullmatch(re.escape(base.path) + r"/\d+/replies", parsed_link.path):
                link = urllib.parse.urlunparse(parsed_link._replace(path=expected_path))
        if link is None or (link and urllib.parse.urlparse(link).path != expected_path):
            raise ValueError("Threads 후속 글 페이지 주소가 달라 조회를 중단했어요")
        if not link:
            return rows
        url = link
    raise ValueError("Threads 댓글 페이지 한도를 넘어 원문이 완전하지 않아요")


def enrich_thread_sources(posts: list[dict[str, Any]], token: str, api_base: str) -> tuple[list[dict[str, Any]], int]:
    """Also recheck existing roots: a late self reply is not a new root post."""
    roots = {}
    markers = {}
    for path in QUEUE_DIR.glob("*/*/source.json"):
        try:
            post = json.loads(path.read_text(encoding="utf-8"))
            identifier = str(post.get("id") or "") if isinstance(post, dict) else ""
            if identifier.isdigit() and post.get("username"):
                roots[identifier] = post
                marker = path.parent / "source-thread.json"
                markers[identifier] = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
        except (OSError, ValueError):
            continue
    new_ids = {str(post.get("id") or "") for post in posts}
    for post in posts:
        if str(post.get("id") or "").isdigit() and post.get("username"):
            roots[str(post["id"])] = post
    if not roots:
        return posts, 0
    replies = fetch_reply_rows(token, api_base)
    grouped: dict[str, list[dict[str, Any]]] = {}
    assignments = {identifier: identifier for identifier in roots}
    # A deleted/inaccessible root may omit root_post. Recover only when the
    # parent graph independently links it to one of our stored roots.
    for row in replies:
        declared = relation_id(row.get("root_post"))
        if declared:
            assignments[str(row.get("id") or "")] = declared
    for _ in range(len(replies)):
        changed = False
        for row in replies:
            identifier = str(row.get("id") or "")
            parent = relation_id(row.get("replied_to"))
            if identifier and identifier not in assignments and parent in assignments:
                assignments[identifier] = assignments[parent]; changed = True
        if not changed:
            break
    for row in replies:
        root_id = assignments.get(str(row.get("id") or ""), "")
        if root_id in roots:
            grouped.setdefault(root_id, []).append(row)
    write_json_atomic(QUEUE_DIR / ".author-replies.json", {
        "pagination_complete": True, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(replies), "unassigned_count": sum(not assignments.get(str(row.get("id") or "")) for row in replies),
        "posts": public_source(replies),
    })
    enriched = {str(post.get("id") or ""): post for post in posts}
    updates = 0
    for identifier, post in roots.items():
        thread = merge_author_thread(post, grouped.get(identifier, []))
        previous = markers.get(identifier, {})
        changed = (previous.get("version") != 2 or previous.get("fingerprint") != thread["fingerprint"]
                   or previous.get("excluded") != thread["excluded"])
        if identifier in new_ids or changed:
            enriched[identifier] = {**post, "_author_thread": thread}
            if identifier not in new_ids:
                updates += 1
    return list(enriched.values()), updates


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_settings() -> tuple[str, str, Path]:
    env_path = Path(os.environ.get("APP_MARKETING_ENV", str(DEFAULT_ENV))).expanduser()
    file_values = parse_env(env_path)
    token = os.environ.get("THREADS_ACCESS_TOKEN", file_values.get("THREADS_ACCESS_TOKEN", "")).strip()
    api_base = os.environ.get("THREADS_API_BASE", file_values.get("THREADS_API_BASE", DEFAULT_API_BASE)).strip().rstrip("/")
    return token, api_base, env_path


def read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"seen_ids": [], "last_timestamp": ""}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"seen_ids": [], "last_timestamp": ""}
    return payload if isinstance(payload, dict) else {"seen_ids": [], "last_timestamp": ""}


def write_json_atomic(path: Path, payload: Any) -> None:
    """Replace the file in one step so an interrupted run never leaves half a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def since_value(value: str) -> str:
    """Convert our readable ISO cursor to the Graph API timestamp format."""
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return str(int(parsed.timestamp()))
    except ValueError:
        return value


def request_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401:
            raise RuntimeError(
                "Threads API HTTP 401: 액세스 토큰이 만료되었거나 유효하지 않습니다. "
                "기존 블로그 자동화에서 `./bin/app-marketing refresh-tokens` 또는 `./bin/app-marketing connect`를 실행하세요."
            ) from exc
        raise RuntimeError(f"Threads API HTTP {exc.code}: {body[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Threads API 연결 실패: {exc.reason}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Threads API가 JSON이 아닌 응답을 반환했습니다.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Threads API 응답 형식이 올바르지 않습니다.")
    return payload


def fetch_page(token: str, api_base: str, *, since: str = "", limit: int = 50) -> dict[str, Any]:
    fields: dict[str, str] = {"fields": FIELDS, "limit": str(limit)}
    if since:
        fields["since"] = since_value(since)
    query = urllib.parse.urlencode(fields)
    return request_json(f"{api_base}/me/threads?{query}", token)


def page_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("data", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def child_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("data", [])
    return [item for item in value if isinstance(item, dict)][:MAX_CHILDREN] if isinstance(value, list) else []


def fetch_media_object(media_id: str, token: str, api_base: str) -> dict[str, Any]:
    if not media_id or not media_id.isdigit():
        raise RuntimeError("Threads 자식 미디어 ID 형식이 올바르지 않습니다")
    query = urllib.parse.urlencode({"fields": MEDIA_FIELDS})
    payload = request_json(f"{api_base}/{urllib.parse.quote(media_id, safe='')}?{query}", token)
    if str(payload.get("id") or "") != media_id:
        raise RuntimeError("Threads 자식 미디어 응답 ID가 요청과 다릅니다")
    return payload


def hydrate_media(posts: list[dict[str, Any]], token: str, api_base: str) -> list[dict[str, Any]]:
    """Resolve carousel child ids while signed media URLs are still fresh."""
    hydrated = []
    for original in posts:
        post = dict(original)
        if str(post.get("media_type")) == "CAROUSEL_ALBUM":
            children = []
            for child in child_rows(post.get("children")):
                media_id = str(child.get("id") or "")
                details = child
                if media_id and (not child.get("media_type") or not child.get("media_url")):
                    details = fetch_media_object(media_id, token, api_base)
                children.append(details)
            post["children"] = children
        hydrated.append(post)
    return hydrated


def sanitized_paging(value: Any) -> dict[str, Any]:
    """Keep cursors and same-origin links, but never persist an access_token query."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"next", "previous"} and isinstance(item, str):
            parsed = urllib.parse.urlparse(item)
            query = [(name, content) for name, content in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
                     if name != "access_token"]
            result[key] = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
        elif key == "cursors" and isinstance(item, dict):
            result[key] = {str(name): str(content) for name, content in item.items()}
    return result


def next_page_url(payload: dict[str, Any], api_base: str) -> str | None:
    """Return the API's next link, "" on the last page, or None for another origin.

    The token is sent in the Authorization header, so an access_token query is dropped.
    """
    paging = payload.get("paging")
    link = str(paging.get("next") or "") if isinstance(paging, dict) else ""
    if not link:
        return ""
    parsed = urllib.parse.urlparse(link)
    base = urllib.parse.urlparse(api_base)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        return None
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
             if key != "access_token"]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def reached_saved_window(rows: list[dict[str, Any]], since: str, seen: set[str]) -> bool:
    """Pages are newest first; a seen ID or an older timestamp means the gap is covered."""
    return any(str(row.get("id", "")) in seen or str(row.get("timestamp") or since) < since
               for row in rows)


def fetch_posts(token: str, api_base: str, *, since: str, limit: int,
                seen: set[str], backfill_history: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    """Read incrementally, or exhaust the official newest-to-oldest pagination.

    A missing cursor is an initial history import, not a one-page sample.  A
    requested history backfill also deliberately ignores the incremental
    cursor and seen IDs; those IDs are only used later to avoid rehydration.
    """
    full_history = backfill_history or not since
    payload = fetch_page(token, api_base, since="" if full_history else since, limit=limit)
    rows = page_rows(payload)
    posts = list(rows)
    pages, truncated = 1, False
    visited_urls: set[str] = set()
    while (full_history or rows) and (full_history or not reached_saved_window(rows, since, seen)):
        url = next_page_url(payload, api_base)
        if url == "":
            break
        if url is None or url in visited_urls or pages >= MAX_PAGES:
            truncated = True
            break
        visited_urls.add(url)
        payload = request_json(url, token)
        rows = page_rows(payload)
        # Keep extra incremental pages inside the saved window even if a next
        # link drops `since`; history mode needs every row.
        if full_history:
            posts.extend(rows)
        else:
            posts.extend(row for row in rows if str(row.get("timestamp") or since) >= since)
        pages += 1
    return posts, payload, truncated


def write_snapshot(payload: dict[str, Any], posts: list[dict[str, Any]], *, truncated: bool = False,
                   mode: str = "incremental", history_complete: bool = False, updated_count: int = 0) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = SNAPSHOT_DIR / f"threads-{stamp}.json"
    write_json_atomic(path, {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "new_count": len(posts) - updated_count,
        "updated_count": updated_count,
        "truncated": truncated,
        "mode": mode,
        "history_complete": history_complete,
        "posts": posts,
        "paging": sanitized_paging(payload.get("paging")),
    })
    return path


def queue_source_ids() -> set[str]:
    """Return IDs already handed to transform, including ones trimmed from state."""
    saved: set[str] = set()
    for source_path in QUEUE_DIR.glob("*/*/source.json"):
        try:
            source = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(source, dict):
            continue
        post_id = str(source.get("id") or source.get("post_id") or source_path.parent.name)
        if post_id:
            saved.add(post_id)
    return saved


def unique_posts(posts: list[dict[str, Any]], excluded_ids: set[str]) -> list[dict[str, Any]]:
    """Preserve API order while preventing duplicate media hydration/output."""
    unique: list[dict[str, Any]] = []
    emitted = set(excluded_ids)
    for post in posts:
        post_id = str(post.get("id") or "")
        if not post_id or post_id in emitted:
            continue
        emitted.add(post_id)
        unique.append(post)
    return unique


def backfill_media(post_ids: list[str], token: str, api_base: str) -> list[dict[str, Any]]:
    """Refresh media for existing queue posts without touching fetch cursor state."""
    results = []
    query = urllib.parse.urlencode({"fields": FIELDS})
    for post_id in post_ids:
        if not post_id.isdigit():
            raise ValueError(f"Threads 글 ID 형식이 올바르지 않습니다: {post_id}")
        sources = sorted(QUEUE_DIR.glob(f"*/{post_id}/source.json"))
        if not sources:
            raise ValueError(f"queue에서 Threads 글을 찾을 수 없습니다: {post_id}")
        post = request_json(f"{api_base}/{urllib.parse.quote(post_id, safe='')}?{query}", token)
        if str(post.get("id") or "") != post_id:
            raise RuntimeError("Threads 미디어 응답 ID가 요청과 다릅니다")
        post = hydrate_media([post], token, api_base)[0]
        for source_path in sources:
            folder = source_path.parent
            manifest = sync_post_media(post, folder)
            try:
                existing = json.loads(source_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            sanitized = public_source(post)
            for key in ("media_type", "children", "alt_text"):
                if key in sanitized:
                    existing[key] = sanitized[key]
            write_json_atomic(source_path, existing)
            items = spec_items(folder)
            spec_path = folder / "card-render" / "spec.json"
            if items and spec_path.is_file():
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                spec["media_root"] = "../source-media"
                spec["media"] = items
                write_json_atomic(spec_path, spec)
            results.append({"id": post_id, "folder": str(folder), "manifest": str(manifest) if manifest else None,
                            "media": len(items)})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Meta Threads 본인 게시물 수집")
    parser.add_argument("--check-only", action="store_true", help="토큰·설정만 확인하고 API를 호출하지 않음")
    parser.add_argument("--backfill-media", action="append", metavar="POST_ID",
                        help="기존 queue 글의 미디어만 공식 API로 다시 받아 저장 (여러 번 가능)")
    parser.add_argument("--backfill-history", action="store_true",
                        help=f"최신 글부터 과거 끝까지 다시 수집 (최대 {MAX_PAGES}쪽 안전 제한)")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        raise SystemExit("--limit은 1~50 사이여야 합니다.")

    token, api_base, env_path = load_settings()
    if not token:
        raise SystemExit(f"THREADS_ACCESS_TOKEN이 없습니다: {env_path}")
    if args.check_only:
        print(json.dumps({"configured": True, "api_base": api_base, "env_path": str(env_path)}, ensure_ascii=False))
        return 0
    if args.backfill_media:
        try:
            results = backfill_media(args.backfill_media, token, api_base)
        except (OSError, ValueError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({"backfilled": len(results), "results": results}, ensure_ascii=False))
        return 0

    state = read_state()
    since = str(state.get("last_timestamp") or "")
    stored_ids = state.get("seen_ids")
    previous_ids = [str(item) for item in stored_ids] if isinstance(stored_ids, list) else []
    seen = set(previous_ids)
    source_ids = queue_source_ids()
    mode = "history" if args.backfill_history or not since else "incremental"
    posts, payload, truncated = fetch_posts(
        token, api_base, since=since, limit=args.limit, seen=seen,
        backfill_history=args.backfill_history)
    new_posts = hydrate_media(unique_posts(posts, seen | source_ids), token, api_base)
    actual_new_count = len(new_posts)
    updated_count = 0
    if not truncated:
        try:
            new_posts, updated_count = enrich_thread_sources(new_posts, token, api_base)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1  # No snapshot or cursor update can hide a failed reply scan.
    previous_history_complete = state.get("history_complete")
    history_complete = (mode == "history" and not truncated) or bool(previous_history_complete)
    snapshot = write_snapshot(payload, new_posts, truncated=truncated, mode=mode,
                              history_complete=history_complete, updated_count=updated_count)

    if truncated:
        print(f"오류: 다음 페이지를 끝까지 읽지 못했습니다 (최대 {MAX_PAGES}쪽). "
              "누락 방지를 위해 수집 커서를 갱신하지 않습니다.", file=sys.stderr)
        print(json.dumps({"fetched": len(posts), "new": len(new_posts), "snapshot": str(snapshot),
                          "truncated": True, "mode": mode,
                          "history_complete": bool(previous_history_complete)}, ensure_ascii=False))
        return 1

    timestamps = [str(post.get("timestamp", "")) for post in posts if post.get("timestamp")]
    latest = max([since, *timestamps])
    # Keep arrival order so trimming to 500 drops the oldest IDs first.
    seen_ids = [*previous_ids, *(str(post.get("id", "")) for post in posts if post.get("id"))]
    next_state = {**state,
        "seen_ids": list(dict.fromkeys(seen_ids))[-500:],
        "last_timestamp": latest,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if mode == "history":
        next_state["history_complete"] = True
    elif "history_complete" in state:
        next_state["history_complete"] = previous_history_complete
    write_json_atomic(STATE_PATH, next_state)
    result: dict[str, Any] = {"fetched": len(posts), "new": actual_new_count, "updated_sources": updated_count, "snapshot": str(snapshot),
                              "mode": mode, "history_complete": next_state.get("history_complete", False)}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
