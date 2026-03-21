"""Scrapy pipelines for validation, normalization, and DB storage."""
import html
import re
import logging
from datetime import datetime
from unidecode import unidecode
from scrapy.exceptions import DropItem

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import (
    Store, StoreListing, PriceHistory, Product,
    get_engine, Base
)
from sqlalchemy.orm import sessionmaker
from pipeline.spec_extractor import extract_specs, specs_to_json

logger = logging.getLogger(__name__)


class ValidationPipeline:
    """Drop items with missing or invalid data."""

    def process_item(self, item, spider):
        # Must have a name
        if not item.get('product_name'):
            raise DropItem("Missing product name")

        # Must have a price
        price = item.get('price')
        if price is None:
            raise DropItem(f"Missing price for {item['product_name']}")

        # Price must be a positive number
        try:
            price = float(price)
            if price <= 0:
                raise DropItem(f"Invalid price {price} for {item['product_name']}")
            if price > 100000:
                raise DropItem(f"Suspiciously high price {price} for {item['product_name']}")
            item['price'] = price
        except (ValueError, TypeError):
            raise DropItem(f"Non-numeric price for {item['product_name']}")

        # Must have store chain
        if not item.get('store_chain'):
            raise DropItem(f"Missing store_chain for {item['product_name']}")

        # Clean unit price
        if item.get('unit_price'):
            try:
                item['unit_price'] = float(item['unit_price'])
            except (ValueError, TypeError):
                item['unit_price'] = None

        return item


class NormalizationPipeline:
    """Normalize product names and extract identifiers."""

    def process_item(self, item, spider):
        # Normalize product name
        name = item['product_name']
        name = html.unescape(name)
        name = re.sub(r'\s+', ' ', name).strip()
        item['product_name'] = name

        # Decode HTML entities in description
        if item.get('description'):
            item['description'] = html.unescape(item['description'])

        # Clean EAN
        if item.get('ean'):
            ean = re.sub(r'\D', '', str(item['ean']))
            item['ean'] = ean if len(ean) == 13 else None

        # Clean manufacturer ref
        if item.get('manufacturer_ref'):
            item['manufacturer_ref'] = str(item['manufacturer_ref']).strip()

        # Normalize manufacturer name
        if item.get('manufacturer'):
            item['manufacturer'] = item['manufacturer'].strip().title()

        # Ensure category_path is a list
        if isinstance(item.get('category_path'), str):
            item['category_path'] = [c.strip() for c in item['category_path'].split('>')]

        return item


class DatabasePipeline:
    """Store scraped items in the database."""

    def open_spider(self, spider):
        engine = get_engine()
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.session = Session()
        self._store_cache = {}
        self._item_count = 0

    def close_spider(self, spider):
        self.session.commit()
        self.session.close()

    def _get_store_id(self, chain, store_name=None):
        """Get the store ID for a chain, preferring a specific store_name if provided."""
        cache_key = (chain, store_name)
        if cache_key not in self._store_cache:
            if store_name:
                store = self.session.query(Store).filter_by(chain=chain, name=store_name).first()
                if not store:
                    logger.warning(f"Store '{store_name}' not found for chain '{chain}', falling back to first store")
                    store = self.session.query(Store).filter_by(chain=chain).first()
            else:
                store = self.session.query(Store).filter_by(chain=chain).first()
                if store:
                    logger.warning(f"No store_name provided for chain '{chain}', using first store: {store.name}")
            if store:
                self._store_cache[cache_key] = store.id
            else:
                logger.warning(f"No store found for chain: {chain}")
                return None
        return self._store_cache.get(cache_key)

    def process_item(self, item, spider):
        try:
            return self._process_item_inner(item)
        except Exception as e:
            logger.error(f"Error processing item: {e}")
            self.session.rollback()
            return item

    def _process_item_inner(self, item):
        store_id = self._get_store_id(item['store_chain'], store_name=item.get('store_name'))
        if not store_id:
            return item

        sku = item.get('sku') if item.get('sku') else (item.get('product_url', '')[-50:] or 'unknown')

        # Upsert listing
        listing = self.session.query(StoreListing).filter_by(
            store_id=store_id,
            store_sku=sku
        ).first()

        if listing:
            # Update existing
            old_price = float(listing.current_price) if listing.current_price else None
            listing.store_product_name = item['product_name']
            listing.current_price = item['price']
            listing.unit_price = item.get('unit_price')
            listing.unit_label = item.get('unit_label')
            listing.in_stock = item.get('in_stock', True)
            listing.store_ean = item.get('ean')
            listing.store_manufacturer_ref = item.get('manufacturer_ref')
            listing.image_url = item.get('image_url')
            listing.category_path = ' > '.join(item['category_path']) if item.get('category_path') else None
            listing.last_scraped_at = datetime.utcnow()

            # Record price change
            if old_price != item['price']:
                history = PriceHistory(listing_id=listing.id, price=item['price'])
                self.session.add(history)
        else:
            # Create new listing
            listing = StoreListing(
                store_id=store_id,
                store_product_name=item['product_name'],
                store_product_url=item.get('product_url'),
                store_sku=sku,
                store_ean=item.get('ean'),
                store_manufacturer_ref=item.get('manufacturer_ref'),
                current_price=item['price'],
                unit_price=item.get('unit_price'),
                unit_label=item.get('unit_label'),
                in_stock=item.get('in_stock', True),
                image_url=item.get('image_url'),
                category_path=' > '.join(item['category_path']) if item.get('category_path') else None,
                last_scraped_at=datetime.utcnow(),
            )
            self.session.add(listing)
            self.session.flush()

            # Initial price history
            history = PriceHistory(listing_id=listing.id, price=item['price'])
            self.session.add(history)

        # Propagate brand/description to linked Product if it exists
        if listing.product_id:
            product = self.session.query(Product).get(listing.product_id)
            if product:
                if not product.brand and item.get('manufacturer'):
                    product.brand = item['manufacturer']
                if not product.description and item.get('description'):
                    product.description = item['description']

                # Extract and store specifications
                spider_specs = item.get('specifications') or {}
                if isinstance(spider_specs, str):
                    import json
                    try:
                        spider_specs = json.loads(spider_specs)
                    except:
                        spider_specs = {}

                parsed_specs = extract_specs(item.get('product_name', ''), spider_specs)

                if parsed_specs and product:
                    product.specifications = specs_to_json(parsed_specs)
                    # Denormalized fields
                    if parsed_specs.get('volume') and not product.volume:
                        product.volume = parsed_specs['volume'][:20]
                    if parsed_specs.get('color') and not product.color:
                        product.color = parsed_specs['color'][:50]
                    if parsed_specs.get('weight') and not product.weight:
                        product.weight = parsed_specs['weight'][:20]
                    if parsed_specs.get('dimensions') and not product.dimensions:
                        product.dimensions = parsed_specs['dimensions'][:50]
                    if parsed_specs.get('pack_size') and not product.pack_size:
                        product.pack_size = parsed_specs['pack_size'][:30]
                    if parsed_specs.get('finish') and not product.finish:
                        product.finish = parsed_specs['finish'][:30]

        # Commit every 100 items
        self._item_count += 1
        if self._item_count % 100 == 0:
            self.session.commit()

        return item
