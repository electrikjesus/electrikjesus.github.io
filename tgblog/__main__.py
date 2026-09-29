import argparse
import logging
import os
import sys

from .config import load_config
from .render import Renderer
from .sync import Syncer


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tgblog", description="Mirror a public Telegram channel into a Hugo blog.")
    ap.add_argument("--config", default="hugo.toml", help="site config file (default: hugo.toml)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_text in (("sync", "fetch new/edited posts and comments into telegram/"), ("all", "sync, then render")):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--full", action="store_true", help="re-crawl the entire channel history and all comments")
        s.add_argument("--no-comments", action="store_true", help="skip fetching comments")
    sub.add_parser("render", help="generate Hugo content from telegram/")
    r = sub.add_parser("reset", help="delete all mirrored posts and media (telegram/ and static/media/tg/)")
    r.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(args.config)

    if args.cmd == "reset":
        if not args.yes and input(f"Delete everything mirrored from @{cfg.channel}? [y/N] ").strip().lower() != "y":
            return 1
        Syncer(cfg).reset()
        logging.info("mirror reset; the next sync imports @%s from scratch", cfg.channel)
        return 0

    if args.cmd in ("sync", "all"):
        changes = Syncer(cfg).run(full=args.full, comments=not args.no_comments)
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as fh:
                fh.write(f"changed={'true' if changes else 'false'}\n")
    if args.cmd in ("render", "all"):
        Renderer(cfg).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
