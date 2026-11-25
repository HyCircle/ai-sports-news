"""Sport definitions, curated RSS sources, URL canonicalization, and noise filters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class SportMeta:
    key: str
    name: str
    badge: str
    feeds: tuple[str, ...]


SPORTS: tuple[SportMeta, ...] = (
    SportMeta(
        key="baseball",
        name="棒球 (MLB)",
        badge="MLB",
        feeds=(
            "https://www.espn.com/espn/rss/mlb/news",
            "https://www.mlb.com/feeds/news/rss.xml",
            "https://www.cbssports.com/rss/headlines/mlb/",
        ),
    ),
    SportMeta(
        key="football",
        name="橄榄球 (NFL)",
        badge="NFL",
        feeds=(
            "https://www.espn.com/espn/rss/nfl/news",
            "https://www.cbssports.com/rss/headlines/nfl/",
            "https://profootballtalk.nbcsports.com/feed/",
        ),
    ),
    SportMeta(
        key="formula1",
        name="F1 赛车",
        badge="F1",
        feeds=(
            "https://feeds.bbci.co.uk/sport/formula1/rss.xml",
            "https://www.skysports.com/rss/12433",
            "https://www.the-race.com/category/formula-1/feed/",
        ),
    ),
    SportMeta(
        key="soccer",
        name="足球",
        badge="足球",
        feeds=(
            "https://www.espn.com/espn/rss/soccer/news",
            "https://feeds.bbci.co.uk/sport/football/rss.xml",
            "https://www.skysports.com/rss/12040",
            "https://www.cbssports.com/rss/headlines/soccer/",
        ),
    ),
    SportMeta(
        key="basketball",
        name="篮球 (NBA)",
        badge="NBA",
        feeds=(
            "https://www.espn.com/espn/rss/nba/news",
            "https://www.cbssports.com/rss/headlines/nba/",
            "https://basketball.realgm.com/rss/wiretap/0/0.xml",
        ),
    ),
)

SPORT_MAP: dict[str, SportMeta] = {s.key: s for s in SPORTS}
ALL_SPORT_KEYS: tuple[str, ...] = tuple(s.key for s in SPORTS)

_TRACKING_PARAM_PREFIXES = ("utm_", "at_", "fbclid", "gclid", "mc_", "ocid", "intcmp")
_VALID_HOST_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")

_BETTING_URL_RE = re.compile(
    r"(/betting/|/odds/|/fantasy/|prop-picks|prop-bets|best-bets|dfs-picks|sportsline|parlay)",
    re.IGNORECASE,
)
_BETTING_TITLE_RE = re.compile(
    r"\b(best bets?|prop bets?|prop picks?|betting odds|odds,? picks?|dfs picks?|fantasy (basketball|football|baseball|soccer|impact|rankings?|outlook)|sportsline|parlay|how to watch|promo code|save \d+%)\b",
    re.IGNORECASE,
)
_PREDICTION_TITLE_RE = re.compile(
    r"(\bvs\.?\b.*\b(predictions?|picks?|odds)\b|\b(predictions?|picks)\s*[:|-]|\bexpert picks\b|\bpower rankings?\b|\bbracket predictions?\b|\ball-star picks\b)",
    re.IGNORECASE,
)
_VIDEO_URL_RE = re.compile(
    r"(/watch/|/video/|/videos/|/iplayer/)",
    re.IGNORECASE,
)
_PODCAST_URL_RE = re.compile(
    r"(/sounds/|/podcast/|/podcasts/)",
    re.IGNORECASE,
)
_LIVE_BLOG_URL_RE = re.compile(r"/live-blog/", re.IGNORECASE)


def canonicalize_url(raw_url: str) -> str | None:
    """Validate and normalize an article URL, stripping tracking query parameters.

    Returns None when the URL is malformed (e.g. 'https://www.bbc.co.ukundefined').
    """
    raw = (raw_url or "").strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if not host or not _VALID_HOST_RE.match(host):
        return None
    # Reject concatenated malformed TLD suffixes such as ".co.ukundefined"
    tld = host.rsplit(".", 1)[-1]
    if len(tld) > 10:
        return None

    kept_params = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith(_TRACKING_PARAM_PREFIXES)
    ]
    clean_query = urlencode(kept_params, doseq=True)
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, clean_query, ""))


def classify_noise(url: str, title: str) -> str | None:
    """Return a filter reason string for deterministic non-news noise, else None."""
    if _VIDEO_URL_RE.search(url):
        return "video"
    if _PODCAST_URL_RE.search(url) or "podcast" in title.lower():
        return "podcast"
    if _BETTING_URL_RE.search(url) or _BETTING_TITLE_RE.search(title):
        return "betting_or_promo"
    if _PREDICTION_TITLE_RE.search(title):
        return "prediction_or_rankings"
    if _LIVE_BLOG_URL_RE.search(url):
        return "live_blog"
    return None
