import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8070/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen3.5-27B-Q4:Instruct")
LLM_API_KEY = os.getenv("LLM_API_KEY")

DB_PATH = Path(os.getenv("SPNEWS_DB", "spnews.db"))

RSS_SOURCES = {
    "baseball": [
        "https://www.espn.com/espn/rss/mlb/news",
        "https://www.mlb.com/feeds/news/rss.xml",
        "https://www.cbssports.com/rss/headlines/mlb/",
    ],
    "football": [
        "https://www.espn.com/espn/rss/nfl/news",
        "https://www.cbssports.com/rss/headlines/nfl/",
        "https://profootballtalk.nbcsports.com/feed/",
    ],
    "formula1": [
        "https://feeds.bbci.co.uk/sport/formula1/rss.xml",
        "https://www.skysports.com/rss/12433",
        "https://the-race.com/feed/",
    ],
    "soccer": [
        "https://www.espn.com/espn/rss/soccer/news",
        "https://feeds.bbci.co.uk/sport/football/rss.xml",
        "https://www.skysports.com/rss/12040",
        "https://www.cbssports.com/rss/headlines/soccer/",
    ],
    "basketball": [
        "https://www.espn.com/espn/rss/nba/news",
        "https://www.cbssports.com/rss/headlines/nba/",
        "https://bleacherreport.com/nba.rss",
    ],
}

SPORT_NAMES = {
    "baseball": "棒球 (MLB)",
    "football": "橄榄球 (NFL)",
    "formula1": "F1 赛车",
    "soccer": "足球",
    "basketball": "篮球 (NBA)",
}

DEFAULT_TIMEZONE = "America/Chicago"

RSS_FETCH_DAYS = 7  # Only import RSS entries published within the last N days (0 = no limit)
