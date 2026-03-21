"""Cross-store product matching using EAN, manufacturer ref, and spec-aware fuzzy matching."""
import logging
import re
from rapidfuzz import fuzz
from collections import defaultdict

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import Product, StoreListing, get_session
from pipeline.normalizer import normalize_product_name, extract_dimensions, extract_volume_weight
from pipeline.spec_extractor import extract_specs

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 85  # raised from 82 to reduce false matches


def _extract_color(name: str) -> str | None:
    """Extract color from product name for matching."""
    specs = extract_specs(name)
    return specs.get('color')


def _extract_key_specs(name: str) -> dict:
    """Extract specs that MUST match for two products to be considered identical."""
    specs = extract_specs(name)
    key = {}
    if specs.get('color'):
        key['color'] = specs['color']
    if specs.get('volume'):
        key['volume'] = specs['volume'].lower().replace(',', '.').replace(' ', '')
    if specs.get('dimensions'):
        key['dimensions'] = re.sub(r'\s+', '', specs['dimensions']).lower()
    if specs.get('weight'):
        key['weight'] = specs['weight'].lower().replace(',', '.').replace(' ', '')
    if specs.get('finish'):
        key['finish'] = specs['finish']
    if specs.get('power'):
        key['power'] = specs['power'].lower().replace(' ', '')
    if specs.get('pack_size'):
        # Normalize: "500 pièces" -> "500"
        m = re.search(r'(\d+)', specs['pack_size'])
        if m:
            key['pack_qty'] = m.group(1)
    return key


def _specs_compatible(specs_a: dict, specs_b: dict) -> bool:
    """Check if two products' key specs are compatible (can be the same product).

    Rules:
    - If both have a spec (color, volume, etc.), they MUST match
    - If only one has it, it's ambiguous — allow match but with penalty
    """
    for key in ('color', 'volume', 'dimensions', 'weight', 'finish', 'power', 'pack_qty'):
        val_a = specs_a.get(key)
        val_b = specs_b.get(key)
        if val_a and val_b and val_a != val_b:
            return False
    return True


def _get_blocking_key(name: str) -> str:
    """Create a blocking key for O(n) instead of O(n²) matching.

    Products with different blocking keys are never compared.
    Key = first significant word (brand or product type).
    """
    normalized = normalize_product_name(name)
    words = normalized.split()
    # Use first 2 significant words as blocking key
    return ' '.join(words[:2]) if len(words) >= 2 else (words[0] if words else '')


def match_by_ean(session):
    """Match store listings to canonical products by EAN code."""
    unmatched = session.query(StoreListing).filter(
        StoreListing.product_id.is_(None),
        StoreListing.store_ean.isnot(None),
        StoreListing.store_ean != ''
    ).all()

    matched = 0
    for listing in unmatched:
        product = session.query(Product).filter_by(ean=listing.store_ean).first()
        if product:
            listing.product_id = product.id
            matched += 1
        else:
            product = Product(
                name=listing.store_product_name,
                canonical_name=normalize_product_name(listing.store_product_name),
                ean=listing.store_ean,
                manufacturer_ref=listing.store_manufacturer_ref,
            )
            session.add(product)
            session.flush()
            listing.product_id = product.id
            matched += 1

    session.commit()
    logger.info(f"EAN matching: {matched}/{len(unmatched)} listings matched")
    return matched


def match_by_manufacturer_ref(session):
    """Match by manufacturer reference number."""
    unmatched = session.query(StoreListing).filter(
        StoreListing.product_id.is_(None),
        StoreListing.store_manufacturer_ref.isnot(None),
        StoreListing.store_manufacturer_ref != ''
    ).all()

    matched = 0
    for listing in unmatched:
        product = session.query(Product).filter_by(
            manufacturer_ref=listing.store_manufacturer_ref
        ).first()
        if product:
            listing.product_id = product.id
            matched += 1

    session.commit()
    logger.info(f"Manufacturer ref matching: {matched}/{len(unmatched)} listings matched")
    return matched


def match_by_fuzzy_name(session):
    """Match remaining unmatched listings by spec-aware fuzzy name similarity.

    Improvements over naive fuzzy:
    1. Blocking: only compare products with similar first words (O(n) not O(n²))
    2. Spec-aware: products with different color/volume/dimensions are NEVER matched
    3. Higher threshold: 85% instead of 82%
    """
    unmatched = session.query(StoreListing).filter(
        StoreListing.product_id.is_(None)
    ).all()

    products = session.query(Product).all()
    if not products:
        for listing in unmatched:
            product = Product(
                name=listing.store_product_name,
                canonical_name=normalize_product_name(listing.store_product_name),
                ean=listing.store_ean,
                manufacturer_ref=listing.store_manufacturer_ref,
            )
            session.add(product)
            session.flush()
            listing.product_id = product.id
        session.commit()
        logger.info(f"Created {len(unmatched)} new canonical products")
        return len(unmatched)

    # Build blocking index: group products by first 2 words
    product_index = defaultdict(list)
    product_data = {}
    for p in products:
        canon = p.canonical_name or normalize_product_name(p.name)
        key = _get_blocking_key(p.name)
        product_index[key].append(p.id)
        product_data[p.id] = {
            'name': canon,
            'specs': _extract_key_specs(p.name),
        }

    matched = 0
    created = 0
    for listing in unmatched:
        listing_name = normalize_product_name(listing.store_product_name)
        listing_specs = _extract_key_specs(listing.store_product_name)
        listing_key = _get_blocking_key(listing.store_product_name)

        best_score = 0
        best_product_id = None

        # Only compare with products in the same block (+ neighbors)
        candidates = set()
        candidates.update(product_index.get(listing_key, []))
        # Also check similar blocking keys (first word only)
        first_word = listing_key.split()[0] if listing_key else ''
        for bkey, pids in product_index.items():
            if bkey.startswith(first_word):
                candidates.update(pids)

        for pid in candidates:
            pdata = product_data[pid]

            # Spec compatibility check FIRST (fast rejection)
            if not _specs_compatible(listing_specs, pdata['specs']):
                continue

            score = fuzz.token_sort_ratio(listing_name, pdata['name'])
            if score > best_score:
                best_score = score
                best_product_id = pid

        if best_score >= FUZZY_THRESHOLD and best_product_id:
            listing.product_id = best_product_id
            matched += 1
        else:
            product = Product(
                name=listing.store_product_name,
                canonical_name=listing_name,
                ean=listing.store_ean,
                manufacturer_ref=listing.store_manufacturer_ref,
            )
            session.add(product)
            session.flush()
            listing.product_id = product.id
            # Add to index for future matches
            new_key = _get_blocking_key(listing.store_product_name)
            product_index[new_key].append(product.id)
            product_data[product.id] = {
                'name': listing_name,
                'specs': listing_specs,
            }
            created += 1

    session.commit()
    logger.info(f"Fuzzy matching: {matched} matched, {created} new products created")
    return matched


def unmatch_bad_matches(session):
    """Find and break bad matches where specs don't match.

    Run this on existing data to fix products that were incorrectly
    grouped together by the old matcher.
    """
    # Find products with multiple listings
    from sqlalchemy import func
    multi = session.query(
        StoreListing.product_id,
        func.count(StoreListing.id).label('cnt')
    ).filter(
        StoreListing.product_id.isnot(None)
    ).group_by(StoreListing.product_id).having(func.count(StoreListing.id) > 3).all()

    unmatched_count = 0
    for product_id, count in multi:
        listings = session.query(StoreListing).filter_by(product_id=product_id).all()
        if len(listings) <= 1:
            continue

        # Get specs for each listing
        listing_specs = []
        for l in listings:
            specs = _extract_key_specs(l.store_product_name)
            listing_specs.append((l, specs))

        # Find the "reference" specs (from the product itself)
        product = session.query(Product).get(product_id)
        if not product:
            continue
        ref_specs = _extract_key_specs(product.name)

        # Check each listing against the reference
        for listing, specs in listing_specs:
            if not _specs_compatible(specs, ref_specs):
                # This listing doesn't belong to this product — unmatch it
                listing.product_id = None
                unmatched_count += 1

    session.commit()
    logger.info(f"Unmatched {unmatched_count} bad matches")
    return unmatched_count


def rematch_orphans(session):
    """Re-match listings that were unmatched by unmatch_bad_matches."""
    match_by_ean(session)
    match_by_manufacturer_ref(session)
    match_by_fuzzy_name(session)


def run_matching():
    """Run all matching strategies in order."""
    session = get_session()
    try:
        logger.info("Starting product matching...")
        match_by_ean(session)
        match_by_manufacturer_ref(session)
        match_by_fuzzy_name(session)

        # Stats
        total = session.query(StoreListing).count()
        matched = session.query(StoreListing).filter(StoreListing.product_id.isnot(None)).count()
        products = session.query(Product).count()
        logger.info(f"Matching complete: {matched}/{total} listings matched to {products} products")
    finally:
        session.close()


def fix_existing_matches():
    """Fix bad matches in existing data, then re-match orphans."""
    session = get_session()
    try:
        logger.info("Fixing bad matches...")
        unmatched = unmatch_bad_matches(session)
        if unmatched > 0:
            logger.info(f"Re-matching {unmatched} orphaned listings...")
            rematch_orphans(session)

        # Update denormalized fields
        from sqlalchemy import func
        products = session.query(Product).all()
        for p in products:
            listings = session.query(StoreListing).filter_by(product_id=p.id).all()
            if listings:
                prices = [float(l.current_price) for l in listings if l.current_price]
                p.listing_count = len(listings)
                p.min_price = min(prices) if prices else None
                p.max_price = max(prices) if prices else None
            else:
                p.listing_count = 0
                p.min_price = None
                p.max_price = None
        session.commit()

        total = session.query(StoreListing).count()
        matched = session.query(StoreListing).filter(StoreListing.product_id.isnot(None)).count()
        products_count = session.query(Product).filter(Product.listing_count > 0).count()
        logger.info(f"Fix complete: {matched}/{total} listings, {products_count} active products")
    finally:
        session.close()


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument('--fix', action='store_true', help='Fix existing bad matches')
    args = parser.parse_args()

    if args.fix:
        fix_existing_matches()
    else:
        run_matching()
