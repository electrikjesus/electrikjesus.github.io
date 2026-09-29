"""Fetch new/edited channel posts and comments, download media, and persist JSON state."""

import json
import logging
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import frames
from .config import Config
from .parse import parse_channel_page, parse_discussion

log = logging.getLogger("tgblog")

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
REMOTE_KEYS = ("remote", "remote_thumb", "remote_video", "remote_image", "remote_photo")
MAX_COMMENT_PAGES = 50


class Fetcher:
    def __init__(self, delay: float):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last = 0.0

    def _wait(self):
        pause = self.delay - (time.monotonic() - self._last)
        if pause > 0:
            time.sleep(pause)
        self._last = time.monotonic()

    def request(self, method: str, url: str, **kw) -> requests.Response:
        for attempt in range(4):
            self._wait()
            try:
                resp = self.session.request(method, url, timeout=30, **kw)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                if attempt == 3:
                    raise
                backoff = 2 ** (attempt + 1)
                log.warning("%s %s failed (%s), retrying in %ss", method, url, exc, backoff)
                time.sleep(backoff)
        raise RuntimeError("unreachable")

    def get(self, url: str, **kw) -> requests.Response:
        return self.request("GET", url, **kw)


def _dump(path: Path, data) -> bool:
    """Write JSON only when content changed, keeping git history quiet."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def _strip_remote(obj):
    if isinstance(obj, dict):
        return {k: _strip_remote(v) for k, v in obj.items() if k not in REMOTE_KEYS}
    if isinstance(obj, list):
        return [_strip_remote(v) for v in obj]
    return obj


def _ext(url: str, default: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm"} else default


class Syncer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = Fetcher(cfg.request_delay)
        self.changed: set[str] = set()

    # ---------- storage ----------

    def post_path(self, post_id: int) -> Path:
        return self.cfg.posts_dir / f"{post_id:06d}.json"

    def load_posts(self) -> dict[int, dict]:
        posts = {}
        if self.cfg.posts_dir.exists():
            for f in sorted(self.cfg.posts_dir.glob("*.json")):
                data = json.loads(f.read_text())
                posts[data["id"]] = data
        return posts

    def save_post(self, post: dict):
        if _dump(self.post_path(post["id"]), post):
            self.changed.add(f"post {post['id']}")

    def delete_post(self, post_id: int):
        self.post_path(post_id).unlink(missing_ok=True)
        shutil.rmtree(self.cfg.media_dir / str(post_id), ignore_errors=True)
        self.changed.add(f"deleted {post_id}")

    # ---------- media ----------

    def download(self, url: str | None, dest: Path, max_bytes: int | None = None) -> str | None:
        """Download url to dest (unless it already exists) and return its public URL."""
        if not url or url.startswith("data:"):
            return None
        public = f"{self.cfg.media_url}/{dest.relative_to(self.cfg.media_dir).as_posix()}"
        if dest.exists():
            return public
        try:
            if max_bytes is not None:
                head = self.http.request("HEAD", url, allow_redirects=True)
                size = int(head.headers.get("Content-Length") or 0)
                if not size or size > max_bytes:
                    return None
            resp = self.http.get(url)
        except requests.RequestException as exc:
            log.warning("media download failed for %s: %s", dest.name, exc)
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        self.changed.add(f"media {dest.name}")
        return public

    def localize_media(self, owner_id: int, items: list[dict], prefix: str = "", old: list[dict] | None = None):
        folder = self.cfg.media_dir / str(owner_id)
        old_by_key = {(m.get("type"), m.get("msg_id")): m for m in (old or [])}
        video_limit = int(self.cfg.video_max_mb * 1024 * 1024) if self.cfg.video_max_mb > 0 else None
        for i, m in enumerate(items):
            key = f"{prefix}{m.get('msg_id', i)}"
            prev = old_by_key.get((m.get("type"), m.get("msg_id")), {})
            if m["type"] in ("photo", "sticker"):
                url = m.get("remote")
                m["src"] = self.download(url, folder / f"{key}{_ext(url or '', '.jpg')}") or prev.get("src")
            elif m["type"] == "video":
                thumb = m.get("remote_thumb")
                m["thumb"] = self.download(thumb, folder / f"{key}-thumb{_ext(thumb or '', '.jpg')}") or prev.get("thumb")
                if video_limit and m.get("remote_video"):
                    m["video"] = self.download(m["remote_video"], folder / f"{key}.mp4", max_bytes=video_limit) or prev.get("video")
                elif prev.get("video"):
                    m["video"] = prev["video"]
                if "poster" in prev:
                    m["poster"] = prev["poster"]
                else:
                    self.ensure_poster(owner_id, m, m.get("remote_video"), key)

    def ensure_poster(self, owner_id: int, m: dict, remote_video: str | None, key: str) -> bool:
        """Replace a black Telegram thumbnail with a frame from the video. Sets m["poster"] once checked."""
        if "poster" in m or not m.get("thumb"):
            return False
        thumb = self.cfg.media_dir / m["thumb"].removeprefix(self.cfg.media_url + "/")
        level = frames.brightness(thumb) if thumb.exists() else None
        if level is None:
            return False
        m["poster"] = None
        if level < frames.DARK_LEVEL and remote_video:
            dest = self.cfg.media_dir / str(owner_id) / f"{key}-poster.jpg"
            if frames.grab_poster(remote_video, dest, m.get("duration")):
                m["poster"] = f"{self.cfg.media_url}/{dest.relative_to(self.cfg.media_dir).as_posix()}"
                self.changed.add(f"media {dest.name}")
                log.info("post %s: poster frame for black video thumbnail %s", owner_id, key)
        return True

    def backfill_posters(self, stored: dict, parsed: dict) -> bool:
        """Check thumbnails of an unchanged post that were stored before poster frames existed."""
        remote = {m.get("msg_id"): m.get("remote_video") for m in parsed.get("media", []) if m["type"] == "video"}
        changed = False
        for m in stored.get("media", []):
            if m["type"] == "video" and "poster" not in m:
                changed |= self.ensure_poster(stored["id"], m, remote.get(m.get("msg_id")), str(m.get("msg_id")))
        return changed

    def localize_post(self, post: dict, old: dict | None):
        self.localize_media(post["id"], post["media"], old=(old or {}).get("media"))
        lp = post.get("link_preview")
        if lp:
            url = lp.get("remote_image")
            old_lp = (old or {}).get("link_preview") or {}
            lp["image"] = self.download(url, self.cfg.media_dir / str(post["id"]) / f"preview{_ext(url or '', '.jpg')}") or old_lp.get("image")

    # ---------- channel posts ----------

    def fetch_page(self, before: int | None = None) -> dict:
        url = f"https://t.me/s/{self.cfg.channel}"
        return parse_channel_page(self.http.get(url, params={"before": before} if before else None).text)

    def sync_posts(self, posts: dict[int, dict], full: bool) -> set[int]:
        """Crawl pages newest-first. Returns ids of posts that were new or changed."""
        touched: set[int] = set()
        known_max = max(posts) if posts else 0
        crawl_complete = False
        seen: set[int] = set()
        before = None
        channel = None

        for _ in range(1000):
            page = self.fetch_page(before)
            channel = channel or page["channel"]
            ids = [p["id"] for p in page["posts"]]
            if not ids:
                crawl_complete = True
                break
            seen.update(ids)

            for parsed in page["posts"]:
                old = posts.get(parsed["id"])
                if old and _signature(parsed) == _signature(old):
                    if self.backfill_posters(old, parsed):
                        self.save_post(old)
                    continue
                merged = {**parsed, "comments": (old or {}).get("comments", []), "comments_count": (old or {}).get("comments_count", 0)}
                self.localize_post(merged, old)
                final = _strip_remote(merged)
                if final != old:
                    posts[parsed["id"]] = final
                    self.save_post(final)
                    touched.add(parsed["id"])
                    log.info("%s post %s", "updated" if old else "added", parsed["id"])

            # Posts missing from inside a fetched page's id range were deleted on Telegram.
            lo, hi = min(ids), max(ids)
            for pid in [p for p in posts if lo <= p <= hi and p not in seen]:
                log.info("post %s no longer exists on Telegram, removing", pid)
                del posts[pid]
                self.delete_post(pid)

            before = page["before"]
            if before is None:
                crawl_complete = True
                break
            if not full and min(ids) <= known_max:
                break

        if full and crawl_complete:
            for pid in [p for p in posts if p not in seen]:
                log.info("post %s not found in full crawl, removing", pid)
                del posts[pid]
                self.delete_post(pid)

        if channel:
            self.save_channel(channel)
        return touched

    def video_links(self) -> dict:
        """Current playable URLs for every stored video, which Telegram only hands out with short-lived tokens.

        Returns {"urls": {msg_id: url}, "too_big": [msg_id, ...]} for videos Telegram won't serve on the web.
        """
        wanted = sorted(
            {m["msg_id"] for p in self.load_posts().values() for m in p.get("media", []) if m["type"] == "video" and not m.get("video")},
            reverse=True,
        )
        urls, too_big = {}, []
        while wanted:
            top = wanted[0]
            page = self.fetch_page(before=top + 1)
            found = {m["msg_id"]: m.get("remote_video") for p in page["posts"] for m in p["media"] if m["type"] == "video"}
            ids = [p["id"] for p in page["posts"]] + list(found)
            if not ids:
                break
            lo = min(min(ids), top)
            for mid in [w for w in wanted if w >= lo]:
                if found.get(mid):
                    urls[mid] = found[mid]
                elif mid in found:
                    too_big.append(mid)
            wanted = [w for w in wanted if w < lo]
        log.info("video links: %d playable, %d too big for the web", len(urls), len(too_big))
        return {"urls": urls, "too_big": sorted(too_big)}

    def save_channel(self, info: dict):
        path = self.cfg.data_dir / "channel.json"
        old = json.loads(path.read_text()) if path.exists() else {}
        info = dict(info)
        remote = info.pop("remote_photo", None)
        info["photo"] = self.download(remote, self.cfg.media_dir / f"channel{_ext(remote or '', '.jpg')}") or old.get("photo")
        info["discussion"] = self.cfg.discussion
        if _dump(path, info):
            self.changed.add("channel")

    # ---------- comments ----------

    def fetch_comments(self, post_id: int) -> dict | None:
        url = f"https://t.me/{self.cfg.channel}/{post_id}"
        first = parse_discussion(self.http.get(url, params={"embed": 1, "discussion": 1, "comments_limit": 100}).text)
        if first["count"] is None and not first["comments"]:
            return None
        comments = {c["id"]: c for c in first["comments"]}
        before, pages = first["before"], 0
        while before and first["api_url"] and first["form"] and pages < MAX_COMMENT_PAGES:
            resp = self.http.request(
                "POST",
                first["api_url"],
                data={**first["form"], "before_id": before, "method": "loadComments"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            ).json()
            if not resp.get("ok"):
                log.warning("loadComments failed for post %s: %s", post_id, resp)
                break
            page = parse_discussion(resp.get("comments_html", ""))
            new = [c for c in page["comments"] if c["id"] not in comments]
            if not new:
                break
            comments.update((c["id"], c) for c in new)
            before, pages = page["before"], pages + 1
        ordered = sorted(comments.values(), key=lambda c: c["id"])
        return {"count": first["count"] if first["count"] is not None else len(ordered), "comments": ordered}

    def sync_comments(self, posts: dict[int, dict], ids: set[int], full: bool):
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg.comment_refresh_days)
        for pid in sorted(posts, reverse=True):
            post = posts[pid]
            if post.get("service"):
                continue
            recent = post.get("date") and datetime.fromisoformat(post["date"]) >= cutoff
            if not (full or recent or pid in ids):
                continue
            try:
                result = self.fetch_comments(pid)
            except requests.RequestException as exc:
                log.warning("comments fetch failed for post %s: %s", pid, exc)
                continue
            if result is None:
                continue
            old_by_id = {c["id"]: c for c in post.get("comments", [])}
            for c in result["comments"]:
                self.localize_media(pid, c["media"], prefix=f"c{c['id']}-", old=old_by_id.get(c["id"], {}).get("media"))
            comments = _strip_remote(result["comments"])
            if comments != post.get("comments") or result["count"] != post.get("comments_count"):
                post["comments"], post["comments_count"] = comments, result["count"]
                self.save_post(post)
                log.info("post %s: %d comments", pid, len(comments))

    def reset(self):
        """Forget every mirrored post, comment and downloaded file."""
        shutil.rmtree(self.cfg.data_dir, ignore_errors=True)
        shutil.rmtree(self.cfg.media_dir, ignore_errors=True)
        self.changed.add("reset")

    def mirrored_channel(self) -> str | None:
        path = self.cfg.data_dir / "channel.json"
        return json.loads(path.read_text()).get("username") if path.exists() else None

    def run(self, full: bool = False, comments: bool = True) -> set[str]:
        previous = self.mirrored_channel()
        if previous and previous.lower() != self.cfg.channel.lower():
            log.warning("channel changed from %s to %s: starting a fresh mirror", previous, self.cfg.channel)
            self.reset()
        posts = self.load_posts()
        full = full or not posts
        log.info("sync start: %d stored posts, full=%s", len(posts), full)
        touched = self.sync_posts(posts, full)
        if comments and self.cfg.discussion:
            self.sync_comments(posts, touched, full)
        log.info("sync done: %d changes", len(self.changed))
        return self.changed


LOCAL_KEYS = ("src", "thumb", "poster", "video", "image", "comments", "comments_count")


def _signature(post: dict):
    """Post content without remote URLs (rotate per fetch) or local-only fields, for edit detection."""
    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in obj.items() if k not in REMOTE_KEYS and k not in LOCAL_KEYS}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj

    return strip(post)
