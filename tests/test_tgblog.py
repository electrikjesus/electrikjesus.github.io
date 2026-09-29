import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tgblog.config import load_config
from tgblog.parse import clean_html, parse_channel_page, parse_discussion
from tgblog.render import Renderer, github_repo, paragraphize, split_title
from tgblog.sync import _signature

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


class ParseChannelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = parse_channel_page((FIXTURES / "channel_page.html").read_text())
        cls.page = page
        cls.posts = {p["id"]: p for p in page["posts"]}

    def test_channel_info_and_pagination(self):
        self.assertEqual(self.page["channel"]["username"], "ejswonderemporium")
        self.assertIsInstance(self.page["before"], int)

    def test_service_message(self):
        self.assertTrue(self.posts[1]["service"])

    def test_album_photos_keep_message_ids(self):
        media = self.posts[271]["media"]
        self.assertEqual([m["msg_id"] for m in media], [271, 272, 273, 274])
        self.assertTrue(all(m["type"] == "photo" and m["remote"].startswith("https://") for m in media))
        self.assertEqual(self.posts[271]["forwarded_from"]["url"], "https://t.me/electrikjesus")

    def test_videos(self):
        playable = self.posts[28]["media"][0]
        self.assertEqual(playable["type"], "video")
        self.assertTrue(playable["remote_video"])
        self.assertEqual(playable["duration"], "0:16")
        too_big = self.posts[24]["media"][0]
        self.assertIsNone(too_big["remote_video"])
        self.assertTrue(too_big["remote_thumb"])
        # The blurred preview <video> must not be picked over the real one.
        self.assertNotIn("blured", self.posts[115]["media"][0]["remote_video"] or "")

    def test_document_album_captions(self):
        docs = self.posts[206]["media"]
        self.assertEqual([d["msg_id"] for d in docs], [206, 207])
        self.assertTrue(docs[0]["title"].endswith(".zip"))
        self.assertIn("MicroG", docs[0]["caption_html"])
        self.assertEqual(self.posts[206]["text_html"], "")

    def test_reply_and_code(self):
        post = self.posts[108]
        self.assertEqual(post["reply_to"]["id"], 107)
        self.assertIn("<code>", post["text_html"])
        self.assertNotIn("Build #2", post["text_html"])

    def test_link_preview(self):
        lp = self.posts[48]["link_preview"]
        self.assertEqual(lp["site"], "GitHub")
        self.assertEqual(lp["layout"], "large")
        self.assertTrue(lp["remote_image"])

    def test_hashtags_and_emoji(self):
        text = self.posts[56]["text_html"]
        self.assertIn('href="tg-hashtag:noMDM"', text)
        self.assertIn("🤔", text)
        self.assertNotIn("emoji", text)


class ParseDiscussionTest(unittest.TestCase):
    def test_comments(self):
        d = parse_discussion((FIXTURES / "discussion_275.html").read_text())
        self.assertEqual(d["count"], 2)
        self.assertEqual([c["id"] for c in d["comments"]], [305, 306])
        first, reply = d["comments"]
        self.assertEqual(first["author"], "Adu")
        self.assertEqual(first["color"], 4)
        self.assertIn("🥲", first["text_html"])
        self.assertEqual(reply["reply_to"]["id"], 305)
        self.assertEqual(reply["text_html"], "Try to leave and rejoin? I dunno")
        self.assertIsNone(d["before"])
        self.assertEqual(set(d["form"]), {"peer", "top_msg_id", "discussion_hash"})
        self.assertTrue(d["api_url"].startswith("https://t.me/api/method"))

    def test_unavailable_discussion(self):
        d = parse_discussion((FIXTURES / "discussion_unavailable.html").read_text())
        self.assertIsNone(d["count"])
        self.assertEqual(d["comments"], [])


class TextTest(unittest.TestCase):
    def test_clean_html_strips_attributes_and_unknown_tags(self):
        from bs4 import BeautifulSoup

        el = BeautifulSoup('<div><a href="https://x.y" onclick="evil()">x</a><script>bad()</script><b class="z">b</b></div>', "html.parser").div
        self.assertEqual(clean_html(el), '<a href="https://x.y">x</a>bad()<b>b</b>')

    def test_paragraphize(self):
        html = "Intro line<br/>second<br/><br/>### Heading<br/>- one<br/>- <code>two</code><br/>1. first<br/>2. second<br/>Outro"
        self.assertEqual(
            paragraphize(html),
            "<p>Intro line<br>second</p><h3>Heading</h3><ul><li>one</li><li><code>two</code></li></ul>"
            "<ol><li>first</li><li>second</li></ol><p>Outro</p>",
        )

    def test_paragraphize_keeps_pre_blocks(self):
        self.assertEqual(paragraphize("a<pre>x<br/>- y</pre>b"), "<p>a<pre>x<br/>- y</pre>b</p>")

    def test_bold_bullets(self):
        self.assertEqual(paragraphize("<b>● </b>Pulled updates"), "<ul><li>Pulled updates</li></ul>")

    def test_split_title(self):
        self.assertEqual(split_title("Lineage OS 21 - Build #7 <br/>Fixes"), ("Lineage OS 21 - Build #7", "Fixes"))
        long_line = "word " * 40
        title, body = split_title(long_line)
        self.assertTrue(title.endswith("…"))
        self.assertEqual(body, long_line)


class SignatureTest(unittest.TestCase):
    def test_remote_urls_and_local_fields_ignored(self):
        a = {"id": 1, "media": [{"type": "photo", "remote": "https://cdn/a.jpg", "src": "/media/1.jpg"}], "comments": [1]}
        b = {"id": 1, "media": [{"type": "photo", "remote": "https://cdn/b.jpg"}]}
        self.assertEqual(_signature(a), _signature(b))


class ConfigTest(unittest.TestCase):
    def test_site_config_drives_mirror(self):
        cfg = load_config(ROOT / "hugo.toml")
        self.assertEqual(cfg.channel, "ejswonderemporium")
        self.assertEqual(cfg.discussion, "ejswonder")
        self.assertIn("electrikjesus", cfg.hide_forwarded_from)
        self.assertTrue(any(p.search("Bass OS build") for p in cfg.topics["Bass OS"]))
        self.assertEqual(cfg.posts_dir, ROOT / "telegram" / "posts")

    def test_missing_channel_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hugo.toml"
            path.write_text('title = "x"\n[params.telegram]\n  channel = ""\n')
            with self.assertRaises(SystemExit):
                load_config(path)

    def test_reset_removes_mirrored_data(self):
        from tgblog.sync import Syncer

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hugo.toml"
            path.write_text('[params.telegram]\n  channel = "newchannel"\n')
            cfg = load_config(path)
            cfg.posts_dir.mkdir(parents=True)
            (cfg.data_dir / "channel.json").write_text('{"username": "oldchannel"}')
            cfg.media_dir.mkdir(parents=True)
            syncer = Syncer(cfg)
            self.assertEqual(syncer.mirrored_channel(), "oldchannel")
            syncer.reset()
            self.assertFalse(cfg.data_dir.exists())
            self.assertFalse(cfg.media_dir.exists())


class RenderTest(unittest.TestCase):
    def test_render_groups_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "hugo.toml").write_text((ROOT / "hugo.toml").read_text())
            cfg = load_config(tmp / "hugo.toml")
            cfg.posts_dir.mkdir(parents=True)
            posts = [
                {"id": 10, "date": "2026-01-01T10:00:00+00:00", "text_html": "Bass OS build<br/>Details with <a class=\"hashtag\" href=\"tg-hashtag:noMDM\">#noMDM</a>", "media": []},
                {"id": 11, "date": "2026-01-01T10:01:00+00:00", "text_html": "", "media": [{"type": "photo", "msg_id": 11, "src": "/media/tg/11/11.jpg", "ratio": 1.5}]},
                {"id": 20, "date": "2026-01-02T10:00:00+00:00", "text_html": 'Follow-up<br/>See <a href="https://t.me/ejswonderemporium/11">this</a>', "media": [],
                 "comments": [{"id": 1, "author": "EJ's Wonder Emporium chat", "author_url": "https://t.me/ejswonder", "text_html": "hi", "date": "2026-01-02T11:00:00+00:00", "media": []}]},
            ]
            for p in posts:
                (cfg.posts_dir / f"{p['id']:06d}.json").write_text(json.dumps(p))
            self.assertEqual(Renderer(cfg).run(), 2)

            first = (cfg.content_dir / "10.md").read_text()
            front = json.loads(first[: first.index("\n}\n") + 2])
            self.assertEqual(front["title"], "Bass OS build")
            self.assertEqual(front["telegram"]["ids"], [10, 11])
            self.assertIn("noMDM", front["tags"])
            self.assertIn("Bass OS", front["tags"])
            self.assertEqual(front["kinds"], ["Photos"])
            self.assertIn('href="/tags/nomdm/"', first)

            second = (cfg.content_dir / "20.md").read_text()
            self.assertIn('href="/posts/10/#m11"', second)
            front2 = json.loads(second[: second.index("\n}\n") + 2])
            self.assertTrue(front2["comments"][0]["owner"])

    def test_github_repo(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            os.environ.pop("GITHUB_REPOSITORY", None)
            self.assertEqual(github_repo(Path(tmp)), (None, None))
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(["git", "-C", tmp, "remote", "add", "origin", "https://github.com/someone/site.git"], check=True)
            self.assertEqual(github_repo(Path(tmp)), ("someone", "site"))
            os.environ["GITHUB_REPOSITORY"] = "owner/repo"
            self.assertEqual(github_repo(Path(tmp)), ("owner", "repo"))


if __name__ == "__main__":
    unittest.main()
