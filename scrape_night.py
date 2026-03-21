"""
Nightly scrape script for CompareBTP.
Runs all spiders sequentially (SQLite locks prevent parallel),
then runs matcher, spec extraction, and denormalization.

Usage: python scrape_night.py
"""
import subprocess
import sys
import os
import time
import json
import logging
from datetime import datetime

# ─── Config ──────────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
PYTHON = r"C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe"

SPIDERS = [
    {
        "name": "brico_depot",
        "settings": {"DOWNLOAD_DELAY": "0.5"},
    },
    {
        "name": "tollens",
        "settings": {},
    },
    {
        "name": "sobrico",
        "settings": {},
    },
    {
        "name": "materiel_electrique",
        "settings": {},
    },
    {
        "name": "wurth",
        "settings": {"DOWNLOAD_DELAY": "2.5"},
    },
    {
        "name": "distriartisan",
        "settings": {"DOWNLOAD_DELAY": "2.0"},
    },
]

# ─── Logging setup ───────────────────────────────────────
def setup_logging():
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(DATA_DIR, f"scrape_log_{today}.txt")
    os.makedirs(DATA_DIR, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger = logging.getLogger("scrape_night")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger, log_file


def run_spider(logger, spider_name, extra_settings=None):
    """Run a single scrapy spider via subprocess. Returns (success, duration, item_count)."""
    cmd = [PYTHON, "-m", "scrapy", "crawl", spider_name]

    if extra_settings:
        for key, val in extra_settings.items():
            cmd.extend(["-s", f"{key}={val}"])

    logger.info(f"{'='*60}")
    logger.info(f"STARTING SPIDER: {spider_name}")
    logger.info(f"Command: {' '.join(cmd)}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        duration = time.time() - start
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        # Extract item count from scrapy stats in stderr
        item_count = 0
        for line in result.stderr.splitlines():
            if "item_scraped_count" in line:
                try:
                    item_count = int(line.split("item_scraped_count")[-1].strip().strip(":").strip().rstrip(","))
                except (ValueError, IndexError):
                    pass

        if result.returncode == 0:
            logger.info(f"FINISHED {spider_name}: {item_count} items in {minutes}m{seconds}s")
            return True, duration, item_count
        else:
            logger.error(f"FAILED {spider_name} (exit code {result.returncode}) after {minutes}m{seconds}s")
            # Log last 20 lines of stderr for debugging
            stderr_lines = result.stderr.strip().splitlines()
            for line in stderr_lines[-20:]:
                logger.error(f"  {line}")
            return False, duration, item_count

    except Exception as e:
        duration = time.time() - start
        logger.error(f"EXCEPTION running {spider_name}: {e}")
        return False, duration, 0


def run_matcher(logger):
    """Run the matcher with --fix flag."""
    logger.info(f"{'='*60}")
    logger.info("RUNNING MATCHER (--fix)")

    start = time.time()
    try:
        result = subprocess.run(
            [PYTHON, "-m", "pipeline.matcher", "--fix"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        duration = time.time() - start

        # Log output
        for line in result.stdout.strip().splitlines():
            if line.strip():
                logger.info(f"  {line}")
        for line in result.stderr.strip().splitlines():
            if line.strip():
                logger.info(f"  {line}")

        if result.returncode == 0:
            logger.info(f"Matcher finished in {duration:.1f}s")
            return True
        else:
            logger.error(f"Matcher failed (exit code {result.returncode})")
            return False

    except Exception as e:
        logger.error(f"EXCEPTION running matcher: {e}")
        return False


def extract_specs_for_new_products(logger):
    """Extract specs for products that don't have specifications yet."""
    logger.info(f"{'='*60}")
    logger.info("EXTRACTING SPECS FOR NEW PRODUCTS")

    start = time.time()
    try:
        # Import directly since spec_extractor has no CLI
        sys.path.insert(0, PROJECT_DIR)
        from db.models import Product, get_session
        from pipeline.spec_extractor import extract_specs

        session = get_session()
        # Find products without specs
        products = session.query(Product).filter(
            Product.specifications.is_(None)
        ).all()

        logger.info(f"Found {len(products)} products without specs")
        updated = 0

        for p in products:
            try:
                specs = extract_specs(p.name)
                if specs:
                    p.specifications = json.dumps(specs, ensure_ascii=False)
                    # Also update individual spec columns
                    if specs.get("color") and not p.color:
                        p.color = specs["color"]
                    if specs.get("volume") and not p.volume:
                        p.volume = specs["volume"]
                    if specs.get("weight") and not p.weight:
                        p.weight = specs["weight"]
                    if specs.get("dimensions") and not p.dimensions:
                        p.dimensions = specs["dimensions"]
                    if specs.get("finish") and not p.finish:
                        p.finish = specs["finish"]
                    if specs.get("pack_size") and not p.pack_size:
                        p.pack_size = specs["pack_size"]
                    updated += 1
            except Exception as e:
                logger.warning(f"Spec extraction failed for product {p.id}: {e}")

        session.commit()
        session.close()
        duration = time.time() - start
        logger.info(f"Specs extracted for {updated}/{len(products)} products in {duration:.1f}s")
        return True

    except Exception as e:
        logger.error(f"EXCEPTION extracting specs: {e}")
        return False


def update_denormalized_fields(logger):
    """Update min_price, max_price, listing_count on all products."""
    logger.info(f"{'='*60}")
    logger.info("UPDATING DENORMALIZED FIELDS")

    start = time.time()
    try:
        sys.path.insert(0, PROJECT_DIR)
        from db.models import Product, StoreListing, get_session

        session = get_session()
        products = session.query(Product).all()
        updated = 0

        for p in products:
            listings = session.query(StoreListing).filter_by(product_id=p.id).all()
            prices = [float(l.current_price) for l in listings if l.current_price]
            new_count = len(listings)
            new_min = min(prices) if prices else None
            new_max = max(prices) if prices else None

            if p.listing_count != new_count or p.min_price != new_min or p.max_price != new_max:
                p.listing_count = new_count
                p.min_price = new_min
                p.max_price = new_max
                updated += 1

        session.commit()
        total_products = len(products)
        total_listings = session.query(StoreListing).count()
        session.close()

        duration = time.time() - start
        logger.info(f"Updated {updated}/{total_products} products in {duration:.1f}s")
        logger.info(f"Total products: {total_products}, Total listings: {total_listings}")
        return True, total_products, total_listings

    except Exception as e:
        logger.error(f"EXCEPTION updating denormalized fields: {e}")
        return False, 0, 0


def main():
    logger, log_file = setup_logging()

    logger.info("=" * 60)
    logger.info("NIGHTLY SCRAPE STARTED")
    logger.info(f"Log file: {log_file}")
    logger.info("=" * 60)

    total_start = time.time()
    results = {}

    # ─── Phase 1: Run all spiders sequentially ───────────
    total_items = 0
    for spider_conf in SPIDERS:
        name = spider_conf["name"]
        success, duration, items = run_spider(logger, name, spider_conf.get("settings"))
        results[name] = {"success": success, "duration": duration, "items": items}
        total_items += items

    # ─── Phase 2: Run matcher ────────────────────────────
    matcher_ok = run_matcher(logger)

    # ─── Phase 3: Extract specs for new products ─────────
    specs_ok = extract_specs_for_new_products(logger)

    # ─── Phase 4: Update denormalized fields ─────────────
    denorm_result = update_denormalized_fields(logger)
    if isinstance(denorm_result, tuple):
        denorm_ok, total_products, total_listings = denorm_result
    else:
        denorm_ok, total_products, total_listings = denorm_result, 0, 0

    # ─── Summary ─────────────────────────────────────────
    total_duration = time.time() - total_start
    total_minutes = int(total_duration // 60)
    total_seconds = int(total_duration % 60)

    logger.info("")
    logger.info("=" * 60)
    logger.info("NIGHTLY SCRAPE SUMMARY")
    logger.info("=" * 60)

    for name, r in results.items():
        status = "OK" if r["success"] else "FAILED"
        mins = int(r["duration"] // 60)
        secs = int(r["duration"] % 60)
        logger.info(f"  {name:25s} {status:6s}  {r['items']:6d} items  {mins}m{secs}s")

    logger.info(f"  {'Matcher':25s} {'OK' if matcher_ok else 'FAILED'}")
    logger.info(f"  {'Spec extraction':25s} {'OK' if specs_ok else 'FAILED'}")
    logger.info(f"  {'Denormalization':25s} {'OK' if denorm_ok else 'FAILED'}")
    logger.info("")
    logger.info(f"  Total items scraped: {total_items}")
    logger.info(f"  Total products in DB: {total_products}")
    logger.info(f"  Total listings in DB: {total_listings}")
    logger.info(f"  Total time: {total_minutes}m{total_seconds}s")
    logger.info("=" * 60)

    # Exit with error code if any spider failed
    any_failed = any(not r["success"] for r in results.values())
    if any_failed:
        logger.warning("Some spiders failed - check log for details")
        sys.exit(1)


if __name__ == "__main__":
    main()
