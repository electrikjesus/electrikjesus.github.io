"""Settings for the mirror, read from the [params] section of the site's hugo.toml."""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    root: Path
    channel: str
    discussion: str = ""
    owner_names: list[str] = field(default_factory=list)
    hide_forwarded_from: list[str] = field(default_factory=list)
    merge_window_seconds: int = 120
    comment_refresh_days: int = 30
    video_max_mb: float = 0
    request_delay: float = 0.6
    topics: dict[str, list[re.Pattern]] = field(default_factory=dict)

    # Fixed layout of the repository.
    media_url: str = "/media/tg"

    @property
    def data_dir(self) -> Path:
        return self.root / "telegram"

    @property
    def posts_dir(self) -> Path:
        return self.data_dir / "posts"

    @property
    def media_dir(self) -> Path:
        return self.root / "static" / "media" / "tg"

    @property
    def content_dir(self) -> Path:
        return self.root / "content" / "posts"


def load_config(path: str | Path = "hugo.toml") -> Config:
    path = Path(path).resolve()
    params = tomllib.loads(path.read_text()).get("params", {})
    telegram = params.get("telegram", {})
    mirror = params.get("mirror", {})

    channel = str(telegram.get("channel", "")).lstrip("@").strip()
    if not channel:
        raise SystemExit(f"{path}: set params.telegram.channel to your public channel username")

    return Config(
        root=path.parent,
        channel=channel,
        discussion=str(telegram.get("discussion", "")).lstrip("@").strip(),
        owner_names=list(telegram.get("ownerNames", [])),
        hide_forwarded_from=[u.lstrip("@").lower() for u in telegram.get("hideForwardedFrom", [])],
        merge_window_seconds=int(mirror.get("mergeWindowSeconds", 120)),
        comment_refresh_days=int(mirror.get("commentRefreshDays", 30)),
        video_max_mb=float(mirror.get("videoMaxMB", 0)),
        request_delay=float(mirror.get("requestDelay", 0.6)),
        topics={
            name: [re.compile(p, re.IGNORECASE) for p in ([patterns] if isinstance(patterns, str) else patterns)]
            for name, patterns in params.get("topics", {}).items()
        },
    )
