"""Validate scraped data quality."""
import logging
from collections import Counter

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import StoreListing, Store, get_session

logger = logging.getLogger(__name__)


def validate_scrape_results(chain: str = None):
    """Run validation checks on scraped data and print report."""
    session = get_session()
    try:
        query = session.query(StoreListing)
        if chain:
            store_ids = [s.id for s in session.query(Store).filter_by(chain=chain).all()]
            query = query.filter(StoreListing.store_id.in_(store_ids))

        listings = query.all()
        if not listings:
            print(f"No listings found{f' for {chain}' if chain else ''}")
            return

        print(f"\n{'='*60}")
        print(f"VALIDATION REPORT{f' - {chain}' if chain else ''}")
        print(f"{'='*60}")
        print(f"Total listings: {len(listings)}")

        # Price checks
        prices = [float(l.current_price) for l in listings if l.current_price]
        if prices:
            print(f"\nPrices:")
            print(f"  Min: {min(prices):.2f}€")
            print(f"  Max: {max(prices):.2f}€")
            print(f"  Avg: {sum(prices)/len(prices):.2f}€")
            print(f"  Median: {sorted(prices)[len(prices)//2]:.2f}€")

            # Suspicious prices
            very_cheap = [l for l in listings if l.current_price and float(l.current_price) < 0.10]
            very_expensive = [l for l in listings if l.current_price and float(l.current_price) > 10000]
            if very_cheap:
                print(f"  ⚠ {len(very_cheap)} products under 0.10€")
                for l in very_cheap[:5]:
                    print(f"    - {l.store_product_name}: {l.current_price}€")
            if very_expensive:
                print(f"  ⚠ {len(very_expensive)} products over 10,000€")
                for l in very_expensive[:5]:
                    print(f"    - {l.store_product_name}: {l.current_price}€")

        # EAN coverage
        with_ean = sum(1 for l in listings if l.store_ean)
        print(f"\nIdentifiers:")
        print(f"  With EAN: {with_ean}/{len(listings)} ({100*with_ean/len(listings):.0f}%)")

        with_ref = sum(1 for l in listings if l.store_manufacturer_ref)
        print(f"  With manufacturer ref: {with_ref}/{len(listings)} ({100*with_ref/len(listings):.0f}%)")

        # Category coverage
        with_cat = sum(1 for l in listings if l.category_path)
        print(f"  With category: {with_cat}/{len(listings)} ({100*with_cat/len(listings):.0f}%)")

        # Stock
        in_stock = sum(1 for l in listings if l.in_stock)
        print(f"\nStock: {in_stock}/{len(listings)} in stock ({100*in_stock/len(listings):.0f}%)")

        # Duplicates check
        names = [l.store_product_name for l in listings]
        dupes = {name: count for name, count in Counter(names).items() if count > 1}
        if dupes:
            print(f"\n⚠ {len(dupes)} duplicate product names found")
            for name, count in sorted(dupes.items(), key=lambda x: -x[1])[:5]:
                print(f"  - '{name}' x{count}")

        print(f"\n{'='*60}\n")

    finally:
        session.close()


if __name__ == '__main__':
    import sys
    chain = sys.argv[1] if len(sys.argv) > 1 else None
    validate_scrape_results(chain)
