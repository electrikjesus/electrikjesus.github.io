"""Turn stored Telegram posts into Hugo content files."""

import html
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from .config import Config

log = logging.getLogger("tgblog")

TAG_RE = re.compile(r"<[^>]+>")
BR_RE = re.compile(r"<br\s*/?>", re.I)
BLOCK_RE = re.compile(r"<(pre|blockquote)\b[^>]*>.*?</\1>", re.S | re.I)
HEADING_MARK = r"#{1,6}"
BULLET_MARK = r"(?:[-•●▪◦*–]|\d{1,2}[.)])"
EMPTY_INLINE_RE = re.compile(r"<(b|strong|i|em|u|s)>\s*</\1>")
GENERATED_RE = re.compile(r"^\d+\.md$")
TITLE_MAX = 110


def plain(fragment: str) -> str:
    return html.unescape(TAG_RE.sub("", fragment or "")).strip()


def slugify(text: str) -> str:
    """Match Hugo's urlize for taxonomy term paths."""
    text = re.sub(r"\s+", "-", text.strip().lower())
    return re.sub(r"[^\w\-]", "", text)


def _strip_marker(line: str, mark: str) -> str:
    out = re.sub(rf"^((?:\s*<[^>]+>)*)\s*{mark}\s*", r"\1", line, count=1)
    return EMPTY_INLINE_RE.sub("", out).strip()


def paragraphize(fragment: str) -> str:
    """Convert Telegram's <br/>-separated text into paragraphs, headings and lists."""
    if not fragment.strip():
        return ""
    stash: list[str] = []

    def keep(m):
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"

    lines = BR_RE.split(BLOCK_RE.sub(keep, fragment))
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []
    list_tag = ""
    list_start = 1

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(para) + "</p>")
            para.clear()

    def flush_list():
        nonlocal list_tag
        if items:
            start = f' start="{list_start}"' if list_tag == "ol" and list_start != 1 else ""
            out.append(f"<{list_tag}{start}>" + "".join(f"<li>{i}</li>" for i in items) + f"</{list_tag}>")
            items.clear()
        list_tag = ""

    for raw in lines:
        line = raw.strip()
        text = plain(line)
        token = re.fullmatch(r"\x00(\d+)\x00", line)
        if token:
            flush_para()
            flush_list()
            out.append(stash[int(token.group(1))])
            continue
        if not text and "\x00" not in line:
            flush_para()
            flush_list()
            continue
        heading = re.match(r"(#{1,6})\s+\S", text)
        if heading:
            flush_para()
            flush_list()
            level = 2 if len(heading.group(1)) <= 2 else 3
            out.append(f"<h{level}>{_strip_marker(line, HEADING_MARK)}</h{level}>")
            continue
        bullet = re.match(rf"({BULLET_MARK})\s+\S", text)
        if bullet:
            flush_para()
            kind = "ol" if bullet.group(1)[0].isdigit() else "ul"
            if kind != list_tag:
                flush_list()
                list_tag = kind
                list_start = int(re.match(r"\d+", bullet.group(1)).group(0)) if kind == "ol" else 1
            items.append(_strip_marker(line, BULLET_MARK))
            continue
        flush_list()
        para.append(line)
    flush_para()
    flush_list()

    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], "".join(out))


def github_repo(root: Path) -> tuple[str | None, str | None]:
    """(owner, name) of the GitHub repository, from Actions or the origin remote."""
    slug = os.environ.get("GITHUB_REPOSITORY", "")
    if not slug:
        try:
            url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            url = ""
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
        slug = f"{m.group(1)}/{m.group(2)}" if m else ""
    owner, _, name = slug.partition("/")
    return owner or None, name or None


def split_title(text_html: str) -> tuple[str | None, str]:
    """Use a short first line as the post title; return (title, remaining html)."""
    lines = BR_RE.split(text_html)
    while lines and not plain(lines[0]):
        lines.pop(0)
    if not lines:
        return None, ""
    first = re.sub(r"^#+\s*", "", plain(lines[0])).strip()
    if first and len(first) <= TITLE_MAX:
        rest = lines[1:]
        while rest and not plain(rest[0]):
            rest.pop(0)
        return first.rstrip(":").strip(), "<br/>".join(rest)
    sentence = re.split(r"(?<=[.!?])\s", first, maxsplit=1)[0]
    if len(sentence) > 90:
        sentence = sentence[:80].rsplit(" ", 1)[0].rstrip(",;:-— ") + "…"
    return sentence, text_html


TELEGRAM_ICON = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19'
    'L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3'
    'l-1.99 1.93c-.23.23-.42.42-.83.42z"/></svg>'
)


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


class Renderer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.channel_url = f"https://t.me/{cfg.channel}"
        self.link_map: dict[int, str] = {}
        videos_file = cfg.root / "data" / "videos.json"
        videos = json.loads(videos_file.read_text()) if videos_file.exists() else {}
        self.video_urls: dict[int, str] = {int(k): v for k, v in videos.get("urls", {}).items()}
        self.tme_re = re.compile(rf'href="https?://t\.me/{re.escape(cfg.channel)}/(\d+)(?:\?[^"#]*)?"', re.I)

    # ---------- loading & grouping ----------

    def load(self) -> tuple[list[dict], dict]:
        posts = [json.loads(f.read_text()) for f in sorted(self.cfg.posts_dir.glob("*.json"))]
        posts.sort(key=lambda p: p["id"])
        channel_file = self.cfg.data_dir / "channel.json"
        channel = json.loads(channel_file.read_text()) if channel_file.exists() else {}
        return [p for p in posts if not p.get("service")], channel

    def group(self, posts: list[dict]) -> list[list[dict]]:
        groups: list[list[dict]] = []
        prev_time = None
        for post in posts:
            t = datetime.fromisoformat(post["date"])
            window = self.cfg.merge_window_seconds
            if groups and prev_time and window > 0 and (t - prev_time).total_seconds() <= window:
                groups[-1].append(post)
            else:
                groups.append([post])
            prev_time = t
        return groups

    # ---------- html building ----------

    def rewrite_links(self, fragment: str, ugc: bool = False) -> str:
        fragment = re.sub(r'href="tg-hashtag:([^"]+)"', lambda m: f'href="/tags/{slugify(html.unescape(m.group(1)))}/"', fragment)

        def internal(m):
            target = int(m.group(1))
            slug = self.link_map.get(target)
            return f'href="/posts/{slug}/#m{target}"' if slug else m.group(0)

        fragment = self.tme_re.sub(internal, fragment)
        if ugc:
            fragment = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" rel="nofollow ugc noopener"', fragment)
        return fragment

    def tg_url(self, msg_id: int) -> str:
        return f"{self.channel_url}/{msg_id}"

    def gallery(self, items: list[dict], group_key: str) -> str:
        if not items:
            return ""
        cells = []
        for m in items:
            ratio = m.get("ratio") or 1.3333
            if m["type"] == "photo" and m.get("src"):
                cells.append(
                    f'<a class="tg-photo" href="{esc(m["src"])}" data-lightbox="{group_key}" style="--r:{ratio}">'
                    f'<img src="{esc(m["src"])}" alt="" loading="lazy" decoding="async"></a>'
                )
            elif m["type"] == "video":
                duration = f'<span class="tg-duration">{esc(m["duration"])}</span>' if m.get("duration") else ""
                still = m.get("poster") or m.get("thumb")
                poster = f' poster="{esc(still)}"' if still else ""
                round_cls = " round" if m.get("round") else ""
                src = m.get("video") or self.video_urls.get(m["msg_id"])
                if src:
                    cells.append(
                        f'<div class="tg-video{round_cls}" style="--r:{ratio}"><video src="{esc(src)}"{poster} controls playsinline preload="none"'
                        f' data-tg-post="{esc(self.cfg.channel)}/{m["msg_id"]}"></video></div>'
                    )
                else:
                    img = f'<img src="{esc(still)}" alt="" loading="lazy" decoding="async">' if still else ""
                    cells.append(
                        f'<a class="tg-video{round_cls}" href="{self.tg_url(m["msg_id"])}" style="--r:{ratio}" target="_blank" rel="noopener">'
                        f'{img}<span class="tg-watch">{TELEGRAM_ICON}Watch on Telegram</span>{duration}</a>'
                    )
            elif m["type"] == "sticker" and m.get("src"):
                cells.append(f'<span class="tg-sticker"><img src="{esc(m["src"])}" alt="Sticker" loading="lazy"></span>')
        if not cells:
            return ""
        return f'<div class="tg-gallery n{min(len(cells), 5)}">{"".join(cells)}</div>'

    def files(self, items: list[dict]) -> str:
        rows = []
        for m in items:
            if m["type"] not in ("document", "audio"):
                continue
            caption = m.get("caption_html")
            cap = f'<div class="tg-file-caption">{paragraphize(self.rewrite_links(caption))}</div>' if caption else ""
            rows.append(
                f'<div class="tg-file-row"><a class="tg-file {m["type"]}" href="{self.tg_url(m["msg_id"])}">'
                f'<span class="tg-file-icon" aria-hidden="true"></span><span class="tg-file-body">'
                f'<span class="tg-file-name">{esc(m.get("title") or "File")}</span>'
                f'<span class="tg-file-meta">{esc(m.get("size"))}{" · " if m.get("size") else ""}Get it on Telegram</span>'
                f"</span></a>{cap}</div>"
            )
        return f'<div class="tg-files">{"".join(rows)}</div>' if rows else ""

    def link_card(self, lp: dict | None) -> str:
        if not lp or not lp.get("url"):
            return ""
        layout = lp.get("layout", "small") if lp.get("image") else "text"
        img = ""
        if lp.get("image"):
            ratio = lp.get("ratio") or 1.9
            img = f'<span class="tg-link-image" style="--r:{ratio}"><img src="{esc(lp["image"])}" alt="" loading="lazy" decoding="async"></span>'
        desc = lp.get("description_html") or ""
        desc_text = plain(BR_RE.sub(" ", desc))
        if len(desc_text) > 280:
            desc_text = desc_text[:270].rsplit(" ", 1)[0] + "…"
        return (
            f'<a class="tg-link-card {layout}" href="{esc(lp["url"])}">{img}<span class="tg-link-body">'
            f'<span class="tg-link-site">{esc(lp.get("site"))}</span>'
            f'<span class="tg-link-title">{esc(lp.get("title"))}</span>'
            f'<span class="tg-link-desc">{esc(desc_text)}</span></span></a>'
        )

    def poll(self, poll: dict | None) -> str:
        if not poll:
            return ""
        opts = "".join(
            f'<li style="--p:{esc(o["percent"].rstrip("%") or 0)}%"><span>{esc(o["text"])}</span><b>{esc(o["percent"])}</b></li>'
            for o in poll.get("options", [])
        )
        return f'<div class="tg-poll"><p class="tg-poll-q">{esc(poll.get("question"))}</p><p class="tg-poll-type">{esc(poll.get("type"))}</p><ul>{opts}</ul></div>'

    def message(self, post: dict, text_html: str) -> str:
        parts = [f'<section class="tg-msg" id="m{post["id"]}">']
        fwd = post.get("forwarded_from")
        fwd_user = ((fwd or {}).get("url") or "").rstrip("/").rsplit("/", 1)[-1].lower()
        if fwd and fwd_user not in self.cfg.hide_forwarded_from:
            name = esc(fwd.get("name"))
            who = f'<a href="{esc(fwd["url"])}">{name}</a>' if fwd.get("url") else name
            parts.append(f'<p class="tg-forward">Forwarded from {who}</p>')
        reply = post.get("reply_to")
        if reply and reply.get("id"):
            slug = self.link_map.get(reply["id"])
            href = f"/posts/{slug}/#m{reply['id']}" if slug else self.tg_url(reply["id"])
            parts.append(
                f'<a class="tg-reply" href="{href}"><span class="tg-reply-author">{esc(reply.get("author"))}</span>'
                f'<span class="tg-reply-text">{esc(reply.get("text"))}</span></a>'
            )
        parts.append(self.gallery(post.get("media", []), f"m{post['id']}"))
        parts.append(self.files(post.get("media", [])))
        if text_html.strip():
            parts.append(f'<div class="tg-text">{paragraphize(self.rewrite_links(text_html))}</div>')
        parts.append(self.link_card(post.get("link_preview")))
        parts.append(self.poll(post.get("poll")))
        if post.get("unsupported") and not post.get("media"):
            parts.append(f'<a class="tg-unsupported" href="{self.tg_url(post["id"])}">This post has media that can only be viewed in Telegram</a>')
        parts.append("</section>")
        return "".join(p for p in parts if p)

    # ---------- entries ----------

    def fallback_title(self, group: list[dict]) -> str:
        media = [m for p in group for m in p.get("media", [])]
        photos = sum(m["type"] == "photo" for m in media)
        videos = [m for m in media if m["type"] == "video"]
        docs = [m for m in media if m["type"] in ("document", "audio")]
        if docs:
            return docs[0].get("title") or "New file"
        if videos and not photos:
            return "New video" + (f" ({videos[0]['duration']})" if videos[0].get("duration") else "")
        if photos:
            return "New photo" if photos == 1 else f"{photos} new photos"
        lp = next((p["link_preview"] for p in group if p.get("link_preview")), None)
        if lp and lp.get("title"):
            return lp["title"]
        return "Update from " + datetime.fromisoformat(group[0]["date"]).strftime("%b %-d, %Y")

    def is_owner(self, comment: dict) -> bool:
        url = (comment.get("author_url") or "").rstrip("/").lower()
        own_urls = {f"https://t.me/{self.cfg.channel}".lower(), f"https://t.me/{self.cfg.discussion}".lower()}
        return url in own_urls or comment.get("author") in self.cfg.owner_names

    def comments(self, group: list[dict]) -> list[dict]:
        out = []
        for post in group:
            for c in post.get("comments", []):
                out.append(
                    {
                        "id": c["id"],
                        "post": post["id"],
                        "author": c.get("author") or "Anonymous",
                        "author_url": c.get("author_url"),
                        "initial": (c.get("initial") or "?")[:2],
                        "color": c.get("color", 0),
                        "owner": self.is_owner(c),
                        "date": c.get("date"),
                        "url": c.get("url"),
                        "reply_to": c.get("reply_to"),
                        "html": paragraphize(self.rewrite_links(c.get("text_html", ""), ugc=True)),
                        "photos": [m["src"] for m in c.get("media", []) if m.get("src")],
                    }
                )
        return sorted(out, key=lambda c: (c["date"] or "", c["id"]))

    def reactions(self, group: list[dict]) -> list[dict]:
        totals: dict[str, int | str] = {}
        for post in group:
            for r in post.get("reactions", []):
                count = r.get("count", "")
                if str(count).isdigit() and str(totals.get(r["emoji"], 0)).isdigit():
                    totals[r["emoji"]] = int(totals.get(r["emoji"], 0)) + int(count)
                else:
                    totals.setdefault(r["emoji"], count)
        return [{"emoji": e, "count": c} for e, c in sorted(totals.items(), key=lambda kv: -int(kv[1]) if str(kv[1]).isdigit() else 0)]

    def entry(self, group: list[dict]) -> tuple[str, dict, str]:
        slug = str(group[0]["id"])
        title = None
        bodies = []
        texts = []
        for post in group:
            text_html = post.get("text_html") or ""
            if title is None and plain(text_html):
                title, text_html = split_title(text_html)
            bodies.append(self.message(post, text_html))
            texts.append(plain(BR_RE.sub(" ", text_html)))
            texts.extend(plain(BR_RE.sub(" ", m.get("caption_html", ""))) for m in post.get("media", []))
        title = title or self.fallback_title(group)

        media = [m for p in group for m in p.get("media", [])]
        visual = [
            {"src": m.get("src") or m.get("poster") or m.get("thumb"), "video": m["type"] == "video", "ratio": m.get("ratio")}
            for m in media
            if m["type"] in ("photo", "video") and (m.get("src") or m.get("poster") or m.get("thumb"))
        ]
        previews = [p["link_preview"] for p in group if p.get("link_preview")]
        cover = visual[0]["src"] if visual else next((lp["image"] for lp in previews if lp.get("image")), None)

        full_text = " ".join(t for t in [title, *texts] if t)
        search_text = full_text + " " + " ".join(m.get("title", "") for m in media)
        hashtags = re.findall(r'href="tg-hashtag:([^"]+)"', " ".join(p.get("text_html", "") for p in group))
        tags = list(dict.fromkeys([html.unescape(h) for h in hashtags] + [name for name, pats in self.cfg.topics.items() if any(p.search(search_text) for p in pats)]))

        kinds = []
        if any(m["type"] == "photo" for m in media):
            kinds.append("Photos")
        if any(m["type"] == "video" for m in media):
            kinds.append("Videos")
        if any(m["type"] in ("document", "audio") for m in media):
            kinds.append("Files")
        if previews:
            kinds.append("Links")

        summary = " ".join(t for t in texts if t).strip()
        if not summary and previews:
            summary = previews[0].get("title", "")
        if len(summary) > 240:
            summary = summary[:230].rsplit(" ", 1)[0].rstrip(",;:-— ") + "…"

        comments = self.comments(group)
        dates = [p["date"] for p in group] + [c["date"] for c in comments if c["date"]]
        front = {
            "title": title,
            "date": group[0]["date"],
            "lastmod": max(dates),
            "slug": slug,
            "aliases": [f"/posts/{p['id']}/" for p in group[1:]],
            "summary": summary,
            "tags": tags,
            "kinds": kinds,
            "images": [cover] if cover else [],
            "thumbs": visual[:4],
            "media_count": len(visual),
            "telegram": {
                "url": self.tg_url(group[0]["id"]),
                "ids": [p["id"] for p in group],
                "comments_url": self.tg_url(group[-1]["id"]),
            },
            "reactions": self.reactions(group),
            "comment_count": max(len(comments), sum(p.get("comments_count") or 0 for p in group)),
            "comments": comments,
        }
        return slug, front, "\n".join(bodies)

    def run(self) -> int:
        posts, channel = self.load()
        groups = self.group(posts)
        self.link_map = {}
        for group in groups:
            slug = str(group[0]["id"])
            for p in group:
                self.link_map[p["id"]] = slug
                for m in p.get("media", []):
                    if m.get("msg_id"):
                        self.link_map[m["msg_id"]] = slug

        out_dir = self.cfg.content_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        written = set()
        for group in groups:
            slug, front, body = self.entry(group)
            name = f"{slug}.md"
            text = json.dumps(front, ensure_ascii=False, indent=2) + "\n\n" + body + "\n"
            path = out_dir / name
            if not path.exists() or path.read_text() != text:
                path.write_text(text)
            written.add(name)
        for stale in out_dir.iterdir():
            if GENERATED_RE.match(stale.name) and stale.name not in written:
                stale.unlink()

        data_dir = self.cfg.root / "data"
        data_dir.mkdir(exist_ok=True)
        channel = {**channel, "url": self.channel_url, "chat_url": f"https://t.me/{self.cfg.discussion}" if self.cfg.discussion else None, "post_count": len(posts)}
        (data_dir / "channel.json").write_text(json.dumps(channel, ensure_ascii=False, indent=2) + "\n")
        owner, repo = github_repo(self.cfg.root)
        (data_dir / "repo.json").write_text(json.dumps({"owner": owner, "name": repo}) + "\n")
        log.info("rendered %d entries from %d posts", len(groups), len(posts))
        return len(groups)
