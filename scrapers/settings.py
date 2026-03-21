"""Scrapy settings for BTP price comparator."""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_NAME = "btp_comparateur"
SPIDER_MODULES = ["scrapers.spiders"]
NEWSPIDER_MODULE = "scrapers.spiders"

# Respectful scraping
ROBOTSTXT_OBEY = os.getenv("RESPECT_ROBOTS_TXT", "true").lower() == "true"
DOWNLOAD_DELAY = float(os.getenv("SCRAPE_DELAY", "2.5"))
CONCURRENT_REQUESTS_PER_DOMAIN = int(os.getenv("MAX_CONCURRENT_PER_DOMAIN", "2"))
CONCURRENT_REQUESTS = 4
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5

# Headers
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Pipelines
ITEM_PIPELINES = {
    "scrapers.pipelines.ValidationPipeline": 100,
    "scrapers.pipelines.NormalizationPipeline": 200,
    "scrapers.pipelines.DatabasePipeline": 300,
}

# Asyncio reactor — required by scrapy-playwright and modern Scrapy (2.14+).
# Always set it so spiders don't need to manage reactor settings.
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# Playwright (for JS-heavy sites) — only loaded if scrapy-playwright is installed.
# HTTP-only spiders work fine with these handlers; Playwright only activates
# for requests that include meta={'playwright': True}.
try:
    import scrapy_playwright  # noqa: F401
    DOWNLOAD_HANDLERS = {
        "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    }
    PLAYWRIGHT_BROWSER_TYPE = "chromium"
    PLAYWRIGHT_LAUNCH_OPTIONS = {
        "headless": True,
    }
except ImportError:
    pass  # HTTP-only spiders don't need Playwright

# Feeds (JSON backup)
FEEDS = {
    "data/%(name)s_%(time)s.json": {
        "format": "json",
        "encoding": "utf-8",
        "overwrite": False,
    }
}

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# Cache (avoid re-downloading during dev)
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400  # 24h
HTTPCACHE_DIR = "data/httpcache"
