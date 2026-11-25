"""Deterministic tests for URL canonicalization and noise classification."""

from spnews.sources import canonicalize_url, classify_noise


def test_canonicalize_url_strips_tracking_and_preserves_meaningful_params():
    assert (
        canonicalize_url(
            "https://www.bbc.com/sport/football/articles/c123?at_medium=RSS&at_campaign=rss"
        )
        == "https://www.bbc.com/sport/football/articles/c123"
    )
    assert (
        canonicalize_url(
            "https://www.espn.com/soccer/report/_/gameId/748480?utm_source=rss&foo=bar"
        )
        == "https://www.espn.com/soccer/report/_/gameId/748480?foo=bar"
    )


def test_canonicalize_url_rejects_malformed_hosts_and_schemes():
    assert canonicalize_url("https://www.bbc.co.ukundefined") is None
    assert canonicalize_url("") is None
    assert canonicalize_url("javascript:alert(1)") is None
    assert canonicalize_url("not-a-url") is None


def test_classify_noise_catches_real_spam_patterns():
    assert (
        classify_noise(
            "https://www.cbssports.com/nba/news/nba-player-prop-picks-odds-model/",
            "NBA player prop picks, odds: Model reveals three best bets",
        )
        == "betting_or_promo"
    )
    assert (
        classify_noise(
            "https://www.skysports.com/watch/video/13539559/miami-gp-highlights",
            "Miami Grand Prix | Qualifying highlights",
        )
        == "video"
    )
    assert (
        classify_noise(
            "https://www.bbc.co.uk/sounds/play/p0nj5vkv",
            "F1: Chequered Flag",
        )
        == "podcast"
    )
    assert (
        classify_noise(
            "https://www.skysports.com/f1/live-blog/12433/13537703/miami-gp-live",
            "Miami GP LIVE!",
        )
        == "live_blog"
    )


def test_classify_noise_keeps_real_news():
    assert (
        classify_noise(
            "https://www.espn.com/nba/story/_/id/48652810/lakers-eliminate-rockets-game-6-rout",
            "Lakers blow out Rockets, advance to face Thunder",
        )
        is None
    )
    assert (
        classify_noise(
            "https://www.the-race.com/business/williams-and-alpine-breached-f1-cost-cap/",
            "Williams and Alpine breached F1 cost cap rules",
        )
        is None
    )
