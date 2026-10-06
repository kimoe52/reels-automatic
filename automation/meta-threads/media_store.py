#!/usr/bin/env python3
"""Download Threads attachments into a post-local, URL-free media store.

Only HTTPS media URLs returned by the official Threads API enter this module.
Redirects and DNS answers are checked against private/local address ranges, no
Threads token is sent to the CDN, downloads are bounded and atomically renamed,
and the durable manifest contains hashes and local filenames rather than signed
URLs. Renderers consume `spec_items()` and never load a remote URL.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


MAX_ITEMS = 10
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_VIDEO_BYTES = 500 * 1024 * 1024
CONTENT_TYPES = {
    "image/jpeg": ("IMAGE", ".jpg"),
    "image/png": ("IMAGE", ".png"),
    "image/webp": ("IMAGE", ".webp"),
    "video/mp4": ("VIDEO", ".mp4"),
    "video/quicktime": ("VIDEO", ".mov"),
}


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _public_https(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Threads 미디어 URL이 안전한 HTTPS 주소가 아닙니다")
    try:
        if parsed.port not in {None, 443}:
            raise ValueError("Threads 미디어 URL의 포트가 443이 아닙니다")
    except ValueError as exc:
        raise ValueError("Threads 미디어 URL 포트가 올바르지 않습니다") from exc
    try:
        answers = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Threads 미디어 호스트를 확인할 수 없습니다") from exc
    if not answers:
        raise ValueError("Threads 미디어 호스트의 IP를 확인할 수 없습니다")
    for answer in answers:
        address = ipaddress.ip_address(answer[4][0].split("%", 1)[0])
        if (address.is_private or address.is_loopback or address.is_link_local or address.is_multicast
                or address.is_reserved or address.is_unspecified):
            raise ValueError("Threads 미디어 URL이 로컬/사설 주소를 가리킵니다")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: urllib.request.Request, fp: Any, code: int, msg: str,
                         headers: Any, new_url: str) -> urllib.request.Request | None:
        _public_https(new_url)
        return super().redirect_request(request, fp, code, msg, headers, new_url)


def _download(url: str, folder: Path, stem: str, expected: str) -> tuple[Path, str, int]:
    _public_https(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), SafeRedirect())
    request = urllib.request.Request(url, headers={"Accept": f"{expected.lower()}/*", "User-Agent": "sto.ckai-media-archive/1"})
    try:
        with opener.open(request, timeout=45) as response:
            _public_https(response.geturl())
            content_type = str(response.headers.get_content_type()).lower()
            details = CONTENT_TYPES.get(content_type)
            if not details or details[0] != expected:
                raise ValueError(f"Threads 미디어 Content-Type이 올바르지 않습니다: {content_type}")
            limit = MAX_IMAGE_BYTES if expected == "IMAGE" else MAX_VIDEO_BYTES
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > limit:
                raise ValueError(f"Threads {expected.lower()} 파일이 허용 크기를 넘습니다")
            suffix = details[1]
            target = folder / f"{stem}{suffix}"
            temporary = folder / f".{stem}.partial-{os.getpid()}{suffix}"
            size = 0
            try:
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f"Threads {expected.lower()} 파일이 허용 크기를 넘습니다")
                        output.write(chunk)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return target, content_type, size
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Threads 미디어 다운로드 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Threads 미디어 다운로드 연결 실패") from exc


def _image_info(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size
    except (OSError, ValueError) as exc:
        raise ValueError(f"Threads 이미지 파일을 읽을 수 없습니다: {path.name}") from exc


def _video_info(path: Path) -> tuple[int, int, float]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"Threads 영상 파일을 읽을 수 없습니다: {path.name}")
    value = json.loads(result.stdout)
    stream = (value.get("streams") or [{}])[0]
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    duration = float((value.get("format") or {}).get("duration") or 0)
    if not width or not height or duration <= 0:
        raise ValueError(f"Threads 영상 정보가 올바르지 않습니다: {path.name}")
    return width, height, duration


def _thumbnail(video: Path, target: Path) -> Path:
    temporary = target.with_name(f".{target.stem}.partial-{os.getpid()}{target.suffix}")
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "0", "-i", str(video),
         "-frames:v", "1", "-vf", "scale='min(1080,iw)':-2", str(temporary)],
        capture_output=True, text=True)
    if result.returncode or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        raise ValueError(f"Threads 영상 썸네일을 만들 수 없습니다: {video.name}")
    os.replace(temporary, target)
    return target


def child_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("data", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def source_media_rows(post: dict[str, Any]) -> list[dict[str, Any]]:
    rows = child_rows(post.get("children")) if str(post.get("media_type")) == "CAROUSEL_ALBUM" else [post]
    return [row for row in rows[:MAX_ITEMS] if str(row.get("media_type")) in {"IMAGE", "VIDEO"}]


def public_source(value: Any) -> Any:
    """Remove expiring/signed CDN URLs before source.json or a processed snapshot is stored."""
    if isinstance(value, dict):
        return {key: public_source(item) for key, item in value.items() if key not in {"media_url", "thumbnail_url"}}
    if isinstance(value, list):
        return [public_source(item) for item in value]
    return value


def _manifest_valid(folder: Path, manifest: dict[str, Any]) -> bool:
    items = manifest.get("items")
    if (manifest.get("version") != 1 or not isinstance(items, list)
            or str(manifest.get("source_id") or "") != folder.parent.name):
        return False
    try:
        counts_match = int(manifest.get("missing_count") or 0) == 0 and int(manifest.get("item_count") or 0) == len(items)
    except (TypeError, ValueError):
        return False
    if not counts_match:
        return False
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("file"), str):
            return False
        paths = [folder / item["file"]]
        if item.get("thumbnail"):
            paths.append(folder / item["thumbnail"])
        if any(not path.resolve().is_relative_to(folder.resolve()) or not path.is_file() for path in paths):
            return False
        if item.get("sha256") != file_hash(paths[0]):
            return False
        if len(paths) == 2 and item.get("thumbnail_sha256") != file_hash(paths[1]):
            return False
    return True


def sync_post_media(post: dict[str, Any], post_folder: Path) -> Path | None:
    """Download a post's API media once and return the durable URL-free manifest."""
    rows = source_media_rows(post)
    if not rows:
        return None
    folder = post_folder / "source-media"
    manifest_path = folder / "manifest.json"
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = {}
    if _manifest_valid(folder, existing):
        return manifest_path

    folder.mkdir(parents=True, exist_ok=True)
    saved, missing = [], 0
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        kind = str(row.get("media_type"))
        url = str(row.get("media_url") or "")
        if not url:
            missing += 1
            continue
        media, mime, size = _download(url, folder, f"{index:02d}", kind)
        if kind == "IMAGE":
            width, height = _image_info(media)
            duration = None
            thumbnail = None
        else:
            width, height, duration = _video_info(media)
            thumbnail_url = str(row.get("thumbnail_url") or "")
            if thumbnail_url:
                thumb, _, _ = _download(thumbnail_url, folder, f"{index:02d}-thumb", "IMAGE")
                _image_info(thumb)
                thumbnail = thumb.name
            else:
                thumbnail = _thumbnail(media, folder / f"{index:02d}-thumb.jpg").name
        saved.append({"type": kind, "file": media.name, "thumbnail": thumbnail,
                      "sha256": file_hash(media),
                      "thumbnail_sha256": file_hash(folder / thumbnail) if thumbnail else None,
                      "mime": mime, "bytes": size,
                      "width": width, "height": height, "duration": duration,
                      "alt_text": str(row.get("alt_text") or "")[:500]})
    manifest = {"version": 1, "source_id": str(post.get("id") or ""),
                "source_media_type": str(post.get("media_type") or ""),
                "item_count": total, "missing_count": missing, "items": saved,
                "downloaded_at": datetime.now(timezone.utc).isoformat()}
    write_json_atomic(manifest_path, manifest)
    return manifest_path


def read_manifest(post_folder: Path) -> dict[str, Any]:
    path = post_folder / "source-media" / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) and _manifest_valid(path.parent, value) else {}


def spec_items(post_folder: Path) -> list[dict[str, Any]]:
    """Copy only renderer fields from the manifest; no URL or absolute path can cross this boundary."""
    manifest = read_manifest(post_folder)
    result = []
    values = manifest.get("items", []) if manifest else []
    for index, item in enumerate(values, start=1):
        kind = item["type"]
        label = f"원글 {'영상' if kind == 'VIDEO' else '이미지'}"
        if len(values) > 1:
            label += f" {index}/{len(values)}"
        alt = str(item.get("alt_text") or "").strip()
        result.append({"type": kind, "file": item["file"], "sha256": item["sha256"],
                       **({"thumbnail": item["thumbnail"], "thumbnail_sha256": item["thumbnail_sha256"]}
                          if item.get("thumbnail") else {}),
                       "fit": "contain", "label": label,
                       **({"caption": alt} if alt and len(alt) <= 100 else {})})
    return result
