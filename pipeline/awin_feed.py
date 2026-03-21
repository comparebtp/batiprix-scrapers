"""Awin product feed importer.

Once approved as an affiliate on Awin, download the product feed CSV/XML
for Leroy Merlin, Castorama, and ManoMano, then import into our DB.

Awin feed fields:
  - product_id (required)
  - product_name (required)
  - description (required)
  - price (required)
  - deep_link (required)
  - image_url
  - brand_name
  - ean
  - merchant_category
  - currency
  - delivery_cost
  - specifications

Usage:
  python -m pipeline.awin_feed --file feed_leroy_merlin.csv --chain leroy_merlin
  python -m pipeline.awin_feed --file feed_castorama.csv --chain castorama
  python -m pipeline.awin_feed --url "https://productdata.awin.com/datafeed/download/..." --chain leroy_merlin
"""
import csv
import io
import sys
import os
import re
import logging
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.models import StoreListing, Store, get_session, init_db

logger = logging.getLogger(__name__)

# Map Awin chain names to our store chains
CHAIN_MAP = {
    'leroy_merlin': 'leroy_merlin',
    'castorama': 'castorama',
    'manomano': 'manomano',
}


def parse_csv_feed(file_path_or_content: str, is_content=False):
    """Parse an Awin CSV feed. Returns list of product dicts."""
    products = []

    if is_content:
        reader = csv.DictReader(io.StringIO(file_path_or_content))
    else:
        with open(file_path_or_content, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            products = list(reader)
            return [_normalize_csv_row(row) for row in products]

    return [_normalize_csv_row(row) for row in reader]


def _normalize_csv_row(row):
    """Normalize CSV field names (Awin uses various naming conventions)."""
    # Try multiple possible field names for each data point
    def get(keys):
        for k in keys:
            v = row.get(k, '').strip()
            if v:
                return v
        return ''

    price_str = get(['price', 'search_price', 'base_price', 'aw_product_price'])
    try:
        price = float(re.sub(r'[^\d.,]', '', price_str).replace(',', '.')) if price_str else None
    except ValueError:
        price = None

    return {
        'product_id': get(['product_id', 'aw_product_id', 'merchant_product_id', 'id']),
        'name': get(['product_name', 'title', 'name', 'aw_product_name']),
        'description': get(['description', 'product_description', 'aw_product_description']),
        'price': price,
        'url': get(['deep_link', 'deeplink', 'merchant_deep_link', 'aw_deep_link', 'product_url', 'link']),
        'image_url': get(['image_url', 'merchant_image_url', 'aw_image_url', 'image', 'img_url']),
        'brand': get(['brand_name', 'brand', 'manufacturer', 'aw_brand_name']),
        'ean': get(['ean', 'gtin', 'upc', 'barcode', 'aw_ean']),
        'category': get(['merchant_category', 'category', 'product_category', 'aw_category']),
        'sku': get(['merchant_product_id', 'sku', 'mpn', 'model_number']),
        'currency': get(['currency', 'aw_currency']) or 'EUR',
        'in_stock': get(['in_stock', 'stock_status', 'availability']).lower() in ('1', 'true', 'yes', 'in stock', 'instock', ''),
    }


def parse_xml_feed(file_path: str):
    """Parse an Awin XML feed."""
    tree = ET.parse(file_path)
    root = tree.getroot()

    products = []
    # Handle different XML structures
    for product_el in root.iter('product'):
        product = {}
        for child in product_el:
            tag = child.tag.lower().replace('-', '_').replace(' ', '_')
            product[tag] = child.text or ''

        products.append(_normalize_csv_row(product))

    return products


def download_feed(url: str, output_path: str = None):
    """Download a feed from Awin URL."""
    logger.info(f"Downloading feed from {url[:80]}...")
    headers = {
        'User-Agent': 'CompareBTP Feed Importer/1.0',
    }
    r = requests.get(url, headers=headers, timeout=120, stream=True)
    r.raise_for_status()

    content = r.text
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"Feed saved to {output_path}")

    return content


def import_feed(products: list, chain: str, store_name: str = None):
    """Import parsed products into the database."""
    session = get_session()

    # Get or create a generic store for this chain
    store = session.query(Store).filter_by(chain=chain).first()
    if not store:
        store = Store(
            name=store_name or chain.replace('_', ' ').title(),
            chain=chain,
            city='En ligne',
            website=f'https://www.{chain.replace("_", "")}.fr',
        )
        session.add(store)
        session.flush()

    imported = 0
    updated = 0
    skipped = 0

    for product in products:
        if not product.get('name') or product.get('price') is None:
            skipped += 1
            continue

        # Check if listing already exists
        existing = None
        if product.get('sku'):
            existing = session.query(StoreListing).filter_by(
                store_id=store.id, store_sku=product['sku']
            ).first()

        if existing:
            # Update price
            if existing.current_price != product['price']:
                existing.current_price = product['price']
                existing.last_scraped_at = datetime.utcnow()
                updated += 1
        else:
            listing = StoreListing(
                store_id=store.id,
                store_product_name=product['name'][:255],
                store_product_url=product.get('url', ''),
                store_sku=product.get('sku', product.get('product_id', ''))[:50] or None,
                store_ean=product.get('ean', '')[:13] or None,
                store_manufacturer_ref=product.get('sku', ''),
                current_price=product['price'],
                in_stock=product.get('in_stock', True),
                category_path=product.get('category', ''),
                image_url=product.get('image_url', ''),
                last_scraped_at=datetime.utcnow(),
            )
            session.add(listing)
            imported += 1

        # Commit in batches
        if (imported + updated) % 500 == 0:
            session.commit()
            logger.info(f"Progress: {imported} imported, {updated} updated...")

    session.commit()
    logger.info(f"Feed import complete: {imported} new, {updated} updated, {skipped} skipped")
    session.close()
    return imported, updated, skipped


def main():
    parser = argparse.ArgumentParser(description='Import Awin product feed')
    parser.add_argument('--file', help='Path to CSV or XML feed file')
    parser.add_argument('--url', help='URL to download feed from')
    parser.add_argument('--chain', required=True, choices=list(CHAIN_MAP.keys()),
                        help='Store chain name')
    parser.add_argument('--format', choices=['csv', 'xml'], default='csv',
                        help='Feed format (default: csv)')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    init_db()

    if args.url:
        content = download_feed(args.url, f'data/feed_{args.chain}.{args.format}')
        products = parse_csv_feed(content, is_content=True) if args.format == 'csv' else []
    elif args.file:
        if args.format == 'xml':
            products = parse_xml_feed(args.file)
        else:
            products = parse_csv_feed(args.file)
    else:
        print("Provide --file or --url")
        sys.exit(1)

    print(f"Parsed {len(products)} products from feed")
    if products:
        print(f"Sample: {products[0]['name'][:60]} - {products[0]['price']}EUR")

    imported, updated, skipped = import_feed(products, CHAIN_MAP[args.chain])
    print(f"\nDone: {imported} imported, {updated} updated, {skipped} skipped")


if __name__ == '__main__':
    main()
