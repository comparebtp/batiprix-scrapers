"""Spider for Bricozor - bricozor.com

Strategy: Sitemap-based, HTTP-only, JSON-LD extraction.
Small catalog (~1000 products) but prices visible (TTC + HT).
JSON-LD: name, price, brand, SKU, MPN. No EAN.

Sitemap: https://www.bricozor.com/sitemap.xml (single file, all products)

Note: Do NOT set TWISTED_REACTOR or DOWNLOAD_HANDLERS in custom_settings.
"""
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class BricozorSpider(BaseBTPSpider):
    name = 'bricozor'
    store_chain = 'bricozor'
    allowed_domains = ['bricozor.com', 'www.bricozor.com']

    custom_settings = {
        'DOWNLOAD_DELAY': 1.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 4,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
    }

    def start_requests(self):
        yield scrapy.Request(
            'https://www.bricozor.com/sitemap.xml',
            callback=self.parse_sitemap,
            dont_filter=True,
        )

    def parse_sitemap(self, response):
        body = response.text
        body = re.sub(r'\sxmlns[^"]*"[^"]*"', '', body)
        urls = re.findall(r'<loc>\s*(https?://[^<]+/p-\d+[^<]*)\s*</loc>', body)
        self.logger.info(f"Sitemap: found {len(urls)} product URLs")
        for url in urls:
            yield scrapy.Request(url, callback=self.parse_product, errback=self.handle_error)

    def parse_product(self, response):
        if response.status in (403, 404):
            return

        for script in response.css('script[type="application/ld+json"]::text').getall():
            try:
                data = json.loads(script.rstrip(';'))
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict) or data.get('@type') != 'Product':
                continue

            name = data.get('name', '')
            if not name:
                continue

            brand_data = data.get('brand', {})
            brand = brand_data.get('name', '') if isinstance(brand_data, dict) else ''

            offers = data.get('offers', {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = None
            if isinstance(offers, dict):
                p = offers.get('price')
                if p:
                    try:
                        price = round(float(p), 2)
                    except (ValueError, TypeError):
                        pass

            sku = data.get('sku', '')
            mpn = data.get('mpn', '')
            gtin = data.get('gtin13') or data.get('gtin') or ''

            image = data.get('image', '')
            if isinstance(image, list):
                image = image[0] if image else ''

            description = data.get('description', '')
            if description:
                description = re.sub(r'<[^>]+>', ' ', description).strip()
                description = re.sub(r'\s+', ' ', description)[:500]

            yield self.make_item(
                product_name=name,
                product_url=response.url,
                sku=sku or None,
                ean=gtin if gtin and len(gtin) in (8, 13) else None,
                manufacturer=brand or None,
                manufacturer_ref=mpn or None,
                price=price,
                unit_label='TTC' if price else None,
                image_url=image or None,
                description=description or None,
                in_stock=True,
            )
            return

    def handle_error(self, failure):
        self.logger.warning(f"Request failed: {failure.request.url} - {failure.value}")
