"""Parsers for Telegram's public web preview (t.me/s/<channel>) and discussion widget HTML."""

import re
from urllib.parse import unquote

from bs4 import BeautifulSoup, NavigableString, Tag

BG_URL_RE = re.compile(r"background-image:\s*url\(['\"]?([^'\")]+)['\"]?\)")
PADDING_RE = re.compile(r"padding-top:\s*([\d.]+)%")
POST_ID_RE = re.compile(r"/(\d+)(?:\?.*)?$")

ALLOWED_TAGS = {"a", "b", "strong", "i", "em", "u", "s", "del", "code", "pre", "blockquote", "br", "span"}
# Containers whose contents belong to something other than the message body.
NESTED_SCOPES = (
    "tgme_widget_message_reply",
    "tgme_widget_message_reply_template",
    "tgme_widget_message_link_preview",
    "tgme_widget_message_one_media",
)


def _classes(el: Tag) -> list[str]:
    return el.get("class") or []


def _bg_url(el: Tag | None) -> str | None:
    if el is None:
        return None
    m = BG_URL_RE.search(el.get("style", ""))
    if not m:
        return None
    url = m.group(1)
    return "https:" + url if url.startswith("//") else url


def _ratio(el: Tag | None) -> float | None:
    """Width/height ratio from Telegram's padding-top trick or data-ratio."""
    if el is None:
        return None
    if el.get("data-ratio"):
        try:
            return round(float(el["data-ratio"]), 4)
        except ValueError:
            pass
    for node in [el, *el.find_all(True)]:
        m = PADDING_RE.search(node.get("style", ""))
        if m and float(m.group(1)) > 0:
            return round(100 / float(m.group(1)), 4)
    return None


def _msg_id(href: str | None) -> int | None:
    if not href:
        return None
    m = POST_ID_RE.search(href)
    return int(m.group(1)) if m else None


def _text(el: Tag | None) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _in_scope(el: Tag, root: Tag, scopes=NESTED_SCOPES) -> bool:
    """True when el is not nested in one of the given containers below root."""
    for parent in el.parents:
        if parent is root:
            return True
        if any(c in scopes for c in _classes(parent)):
            return False
    return True


def _find_scoped(root: Tag, selector: str, scopes=NESTED_SCOPES) -> list[Tag]:
    return [el for el in root.select(selector) if _in_scope(el, root, scopes)]


def clean_html(el: Tag | None) -> str:
    """Reduce Telegram message markup to a small, safe subset of inline HTML."""
    if el is None:
        return ""
    el = BeautifulSoup(str(el), "html.parser").find(True)

    for emoji in el.select("i.emoji, tg-emoji"):
        emoji.replace_with(NavigableString(emoji.get_text()))

    for node in el.find_all(True):
        if node is el:
            continue
        name = node.name
        if name == "tg-spoiler" or "tgme_widget_message_spoiler" in _classes(node):
            node.name, node.attrs = "span", {"class": "spoiler"}
            continue
        if name not in ALLOWED_TAGS:
            node.unwrap()
            continue
        if name == "a":
            href = node.get("href", "")
            if href.startswith("?q=%23") or href.startswith("?q=#"):
                tag = unquote(href[3:]).lstrip("#")
                node.attrs = {"class": "hashtag", "href": f"tg-hashtag:{tag}"}
            elif href.startswith("?"):
                node.unwrap()
            else:
                node.attrs = {"href": href}
        elif name == "span":
            node.unwrap()
        else:
            node.attrs = {}

    return el.decode_contents().strip()


def _parse_media_item(el: Tag, post_id: int, caption: Tag | None = None) -> dict | None:
    cls = _classes(el)
    msg_id = _msg_id(el.get("href")) or post_id
    item: dict
    if "tgme_widget_message_photo_wrap" in cls:
        item = {"type": "photo", "msg_id": msg_id, "remote": _bg_url(el), "ratio": _ratio(el)}
    elif "tgme_widget_message_video_player" in cls or "tgme_widget_message_roundvideo_player" in cls:
        video = next((v for v in el.select("video") if "blured" not in _classes(v)), None)
        wrap = el.select_one(".tgme_widget_message_video_wrap, .tgme_widget_message_roundvideo_wrap")
        item = {
            "type": "video",
            "msg_id": msg_id,
            "remote_thumb": _bg_url(el.select_one(".tgme_widget_message_video_thumb, .tgme_widget_message_roundvideo_thumb")),
            "remote_video": video.get("src") if video else None,
            "duration": _text(el.select_one(".message_video_duration, .tgme_widget_message_roundvideo_duration")) or None,
            "ratio": _ratio(wrap) or (1.0 if "roundvideo" in " ".join(cls) else None),
            "round": "tgme_widget_message_roundvideo_player" in cls,
        }
    elif "tgme_widget_message_document_wrap" in cls:
        item = {
            "type": "document",
            "msg_id": msg_id,
            "title": _text(el.select_one(".tgme_widget_message_document_title")),
            "size": _text(el.select_one(".tgme_widget_message_document_extra")),
        }
    elif "tgme_widget_message_voice_player" in cls or "tgme_widget_message_audio" in " ".join(cls):
        item = {
            "type": "audio",
            "msg_id": msg_id,
            "title": _text(el.select_one(".tgme_widget_message_audio_title")) or "Audio",
            "size": _text(el.select_one(".tgme_widget_message_voice_duration, .tgme_widget_message_audio_performer")),
        }
    elif "tgme_widget_message_sticker_wrap" in cls:
        img = el.select_one("img, i")
        remote = (img.get("src") if img and img.name == "img" else None) or _bg_url(img)
        item = {"type": "sticker", "msg_id": msg_id, "remote": remote}
    else:
        return None
    if caption is not None:
        item["caption_html"] = clean_html(caption)
    return item


MEDIA_SELECTOR = ", ".join(
    [
        "a.tgme_widget_message_photo_wrap",
        "a.tgme_widget_message_video_player",
        "a.tgme_widget_message_roundvideo_player",
        "a.tgme_widget_message_document_wrap",
        ".tgme_widget_message_voice_player",
        ".tgme_widget_message_sticker_wrap",
    ]
)


def _parse_media(bubble: Tag, post_id: int) -> list[dict]:
    items: list[dict] = []
    for el in bubble.select(MEDIA_SELECTOR + ", .tgme_widget_message_one_media"):
        if "tgme_widget_message_one_media" in _classes(el):
            if not _in_scope(el, bubble):
                continue
            caption = el.select_one(".tgme_widget_message_text")
            for inner in el.select(MEDIA_SELECTOR):
                item = _parse_media_item(inner, post_id, caption)
                if item:
                    items.append(item)
            continue
        if not _in_scope(el, bubble):
            continue
        item = _parse_media_item(el, post_id)
        if item:
            items.append(item)
    return items


def _parse_poll(bubble: Tag) -> dict | None:
    poll = bubble.select_one(".tgme_widget_message_poll")
    if not poll:
        return None
    return {
        "question": _text(poll.select_one(".tgme_widget_message_poll_question")),
        "type": _text(poll.select_one(".tgme_widget_message_poll_type")),
        "options": [
            {
                "text": _text(opt.select_one(".tgme_widget_message_poll_option_text")),
                "percent": _text(opt.select_one(".tgme_widget_message_poll_option_percent")),
            }
            for opt in poll.select(".tgme_widget_message_poll_option")
        ],
    }


def _parse_link_preview(bubble: Tag) -> dict | None:
    lp = bubble.select_one("a.tgme_widget_message_link_preview")
    if not lp:
        return None
    large = lp.select_one(".link_preview_image, .link_preview_video_thumb")
    small = lp.select_one(".link_preview_right_image")
    return {
        "url": lp.get("href"),
        "site": _text(lp.select_one(".link_preview_site_name")),
        "title": _text(lp.select_one(".link_preview_title")),
        "description_html": clean_html(lp.select_one(".link_preview_description")),
        "remote_image": _bg_url(large or small),
        "layout": "large" if large else "small",
        "ratio": _ratio(large) if large else None,
    }


def _parse_reply(bubble: Tag) -> dict | None:
    reply = next(iter(_find_scoped(bubble, ".tgme_widget_message_reply", scopes=("tgme_widget_message_reply_template",))), None)
    if not reply:
        return None
    return {
        "id": _msg_id(reply.get("href")) or (int(reply["data-reply-to"]) if reply.get("data-reply-to") else None),
        "author": _text(reply.select_one(".tgme_widget_message_author_name")),
        "text": _text(reply.select_one(".tgme_widget_message_text")),
    }


def _parse_reactions(msg: Tag) -> list[dict]:
    out = []
    for r in msg.select(".tgme_reaction"):
        emoji_el = r.select_one("b")
        emoji = emoji_el.get_text() if emoji_el else ("⭐" if "tgme_reaction_paid" in _classes(r) else "")
        count = r.get_text().replace(emoji, "", 1).strip() if emoji else r.get_text(strip=True)
        if emoji or count:
            out.append({"emoji": emoji, "count": count})
    return out


def parse_channel_page(html: str) -> dict:
    """Parse a t.me/s/<channel> page into channel info, posts and pagination hints."""
    soup = BeautifulSoup(html, "html.parser")

    info = {}
    header = soup.select_one(".tgme_channel_info")
    if header:
        photo = header.select_one(".tgme_page_photo_image img")
        info = {
            "title": _text(header.select_one(".tgme_channel_info_header_title")),
            "username": _text(header.select_one(".tgme_channel_info_header_username")).lstrip("@"),
            "description_html": clean_html(header.select_one(".tgme_channel_info_description")),
            "remote_photo": photo.get("src") if photo else None,
        }

    posts = []
    for msg in soup.select(".tgme_widget_message[data-post]"):
        post_id = int(msg["data-post"].rsplit("/", 1)[1])
        bubble = msg.select_one(".tgme_widget_message_bubble") or msg
        time_el = msg.select_one(".tgme_widget_message_date time")
        fwd = msg.select_one(".tgme_widget_message_forwarded_from_name")
        text_el = next(iter(_find_scoped(bubble, ".tgme_widget_message_text")), None)

        post = {
            "id": post_id,
            "date": time_el.get("datetime") if time_el else None,
            "service": "service_message" in _classes(msg),
            "forwarded_from": {"name": _text(fwd), "url": fwd.get("href")} if fwd else None,
            "reply_to": _parse_reply(bubble),
            "media": _parse_media(bubble, post_id),
            "text_html": clean_html(text_el),
            "link_preview": _parse_link_preview(bubble),
            "poll": _parse_poll(bubble),
            "reactions": _parse_reactions(msg),
            "unsupported": bool(
                _find_scoped(bubble, ".message_media_not_supported_wrap", scopes=NESTED_SCOPES + ("tgme_widget_message_video_player",))
            ),
        }
        posts.append(post)

    prev_link = soup.select_one('link[rel="prev"]')
    before = None
    if prev_link and "before=" in prev_link.get("href", ""):
        before = int(prev_link["href"].split("before=")[1].split("&")[0])
    return {"channel": info, "posts": posts, "before": before}


def parse_discussion(html: str) -> dict:
    """Parse discussion widget HTML (full page or loadComments fragment)."""
    soup = BeautifulSoup(html, "html.parser")
    comments = []
    for msg in soup.select(".tgme_widget_message[data-post-id]"):
        bubble = msg.select_one(".tgme_widget_message_bubble") or msg
        author = msg.select_one(".tgme_widget_message_author .tgme_widget_message_author_name")
        author_link = author if author and author.name == "a" else (author.find_parent("a") if author else None)
        photo = msg.select_one(".tgme_widget_message_user_photo")
        color = next((c[7:] for c in _classes(photo) if c.startswith("bgcolor")), "0") if photo else "0"
        text_el = next(iter(_find_scoped(bubble, ".tgme_widget_message_text")), None)
        time_el = msg.select_one(".tgme_widget_message_date time")
        date_link = msg.select_one("a.tgme_widget_message_date")
        comments.append(
            {
                "id": int(msg["data-post-id"]),
                "author": _text(author),
                "author_url": author_link.get("href") if author_link else None,
                "initial": (photo.get("data-content") if photo else "") or (_text(author)[:1] or "?"),
                "color": int(color) if color.isdigit() else 0,
                "date": time_el.get("datetime") if time_el else None,
                "url": date_link.get("href") if date_link else None,
                "reply_to": _parse_reply(bubble),
                "text_html": clean_html(text_el),
                "media": _parse_media(bubble, int(msg["data-post-id"])),
            }
        )

    more_before = None
    for more in soup.select(".js-messages_more[data-before]"):
        if "hide" not in _classes(more):
            more_before = int(more["data-before"])

    form = {}
    for name in ("peer", "top_msg_id", "discussion_hash"):
        inp = soup.select_one(f'form.js-new_message_form input[name="{name}"]')
        if inp:
            form[name] = inp.get("value")

    api_url = None
    m = re.search(r'"api_url":"([^"]+)"', html)
    if m:
        api_url = m.group(1).replace("\\/", "/")

    count = None
    m = re.search(r'"comments_cnt":(\d+)', html)
    if m:
        count = int(m.group(1))

    return {"comments": comments, "before": more_before, "form": form, "api_url": api_url, "count": count}
