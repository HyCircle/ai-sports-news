LLM_BASE_URL = "http://10.0.0.181:8070/v1"
# LLM_MODEL = "Qwen3.5-35B-A3B-Q4_K_M:Thinking"
LLM_MODEL = "Qwen3.5-27B-Q4:Instruct"
# LLM_MODEL = "GLM-4.7-Flash:UD-Q4_K_XL"

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
}

SPORT_NAMES = {
    "baseball": "棒球 (MLB)",
    "football": "橄榄球 (NFL)",
    "formula1": "F1 赛车",
}

DEFAULT_TIMEZONE = "America/Chicago"

REASON_LIMIT = -1  # 推理预算限制，单位为 Token，-1:无限制 (default)，0:禁用
