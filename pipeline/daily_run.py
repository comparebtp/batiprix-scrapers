"""Daily scraping pipeline: run all spiders, match products, update indexes."""
import logging
import sys
import os
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import get_session, ScrapeRun, Product, StoreListing
from pipeline.matcher import run_matching
from sqlalchemy import func

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

SPIDERS = [
    'brico_depot',
    'tollens',
    'wurth',
    'castorama',
    'bricomarche',
    'bricorama',
    'leroy_merlin',
    # kiloutou and loxam are rental, not retail - excluded
]

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_spider(spider_name: str) -> ScrapeRun:
    """Run a single spider and log the result."""
    session = get_session()
    run = ScrapeRun(spider_name=spider_name, started_at=datetime.utcnow())
    session.add(run)
    session.commit()

    logger.info(f"Starting spider: {spider_name}")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'scrapy', 'crawl', spider_name],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min max per spider
        )

        if result.returncode == 0:
            run.status = 'success'
            # Count items from log output
            for line in result.stderr.split('\n'):
                if 'item_scraped_count' in line:
                    try:
                        count = int(line.split('item_scraped_count')[1].strip().strip(':').strip().split()[0].strip(','))
                        run.items_scraped = count
                    except (ValueError, IndexError):
                        pass
            logger.info(f"Spider {spider_name} completed: {run.items_scraped} items")
        else:
            run.status = 'failed'
            run.errors = 1
            logger.error(f"Spider {spider_name} failed: {result.stderr[-500:]}")

    except subprocess.TimeoutExpired:
        run.status = 'failed'
        run.errors = 1
        logger.error(f"Spider {spider_name} timed out after 600s")
    except Exception as e:
        run.status = 'failed'
        run.errors = 1
        logger.error(f"Spider {spider_name} error: {e}")

    run.finished_at = datetime.utcnow()
    session.commit()
    session.close()
    return run


def update_denormalized_fields():
    """Update min_price, max_price, listing_count on products."""
    session = get_session()
    products = session.query(Product).all()
    updated = 0

    for p in products:
        listings = session.query(StoreListing).filter(
            StoreListing.product_id == p.id
        ).all()
        prices = [float(l.current_price) for l in listings if l.current_price]

        new_min = min(prices) if prices else None
        new_max = max(prices) if prices else None
        new_count = len(listings)

        if p.min_price != new_min or p.max_price != new_max or p.listing_count != new_count:
            p.min_price = new_min
            p.max_price = new_max
            p.listing_count = new_count
            p.updated_at = datetime.utcnow()
            updated += 1

    session.commit()
    session.close()
    logger.info(f"Updated denormalized fields for {updated} products")


def generate_slugs():
    """Generate slugs for products that don't have one."""
    import re
    import unicodedata

    def slugify(text):
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
        text = text.lower().strip()
        text = re.sub(r'[^a-z0-9]+', '-', text)
        return text.strip('-')[:200]

    session = get_session()
    products = session.query(Product).filter(Product.slug.is_(None)).all()

    if not products:
        return

    existing_slugs = set(
        s[0] for s in session.query(Product.slug).filter(Product.slug.isnot(None)).all()
    )

    for p in products:
        slug = slugify(p.name)
        base = slug
        counter = 1
        while slug in existing_slugs:
            slug = f'{base}-{counter}'
            counter += 1
        existing_slugs.add(slug)
        p.slug = slug

    session.commit()
    session.close()
    logger.info(f"Generated slugs for {len(products)} products")


def extract_brands():
    """Extract brand names from product names."""
    BRANDS = [
        'bosch', 'makita', 'dewalt', 'metabo', 'hilti', 'magnusson', 'dexter',
        'stanley', 'facom', 'wurth', 'fischer', 'spit', 'milwaukee', 'festool',
        'karcher', 'ryobi', 'hitachi', 'tollens', 'zolpan', 'sika', 'weber',
        'knauf', 'placo', 'legrand', 'schneider', 'hager', 'grohe', 'hansgrohe',
        'geberit', 'roca', 'jacob delafon', 'ideal standard', 'goodhome', 'diall',
        'dremel', 'black+decker', 'einhell', 'parkside', 'brenner',
    ]
    session = get_session()
    products = session.query(Product).filter(Product.brand.is_(None)).all()
    count = 0
    for p in products:
        name_lower = p.name.lower()
        for brand in BRANDS:
            if brand in name_lower:
                p.brand = brand.title()
                count += 1
                break
    session.commit()
    session.close()
    logger.info(f"Extracted brands for {count} products")


def main():
    start = datetime.utcnow()
    logger.info("=" * 60)
    logger.info("DAILY SCRAPE PIPELINE STARTED")
    logger.info("=" * 60)

    # 1. Run each spider
    results = []
    for spider in SPIDERS:
        run = run_spider(spider)
        results.append(run)

    # 2. Match products
    logger.info("Running product matching...")
    run_matching()

    # 3. Categorize products
    logger.info("Running product categorization...")
    try:
        from pipeline.categorizer import categorize_products
        categorize_products()
    except Exception as e:
        logger.error(f"Categorization error: {e}")

    # 4. Generate slugs for new products
    logger.info("Generating slugs for new products...")
    generate_slugs()

    # 5. Update denormalized fields
    logger.info("Updating denormalized fields...")
    update_denormalized_fields()

    # 6. Extract brands
    logger.info("Extracting brands...")
    extract_brands()

    # 5. Summary
    elapsed = (datetime.utcnow() - start).total_seconds()
    total_items = sum(r.items_scraped or 0 for r in results)
    failed = sum(1 for r in results if r.status == 'failed')

    logger.info("=" * 60)
    logger.info(f"PIPELINE COMPLETE in {elapsed:.0f}s")
    logger.info(f"  Spiders: {len(results)} run, {failed} failed")
    logger.info(f"  Items scraped: {total_items}")

    session = get_session()
    logger.info(f"  Products in DB: {session.query(Product).count()}")
    logger.info(f"  Listings in DB: {session.query(StoreListing).count()}")
    session.close()
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
