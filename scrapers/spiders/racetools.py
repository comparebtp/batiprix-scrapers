"""Spider for Racetools - racetools.fr

Strategy: Sitemap-based, JSON-LD extraction.
Shopify store with ~9,800 products. Outillage pro (Makita, Bosch, DeWalt, Milwaukee, Facom).
JSON-LD: name, price, brand, SKU, availability. No EAN/GTIN typically.

Sitemap index: https://racetools.fr/sitemap.xml
Product sitemaps: sitemap_products_1.xml through sitemap_products_5.xml (with ?from=&to= params)
"""
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class RacetoolsSpider(BaseBTPSpider):
    name = 'racetools'
    store_chain = 'racetools'
    allowed_domains = ['racetools.fr']

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

    def __init__(self, shard=None, total_shards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shard = int(shard) if shard is not None else None
        self.total_shards = int(total_shards) if total_shards is not None else None

    def start_requests(self):
        yield scrapy.Request(
            'https://racetools.fr/sitemap.xml',
            callback=self.parse_sitemap_index,
            dont_filter=True,
        )

    def parse_sitemap_index(self, response):
        body = response.text
        body = re.sub(r'\sxmlns[^"]*"[^"]*"', '', body)
        urls = re.findall(r'<loc>\s*(https?://[^<]*sitemap_products[^<]*)\s*</loc>', body)
        self.logger.info(f"Sitemap index: found {len(urls)} product sitemaps")
        for url in urls:
            # XML-decode &amp; to &
            url = url.replace('&amp;', '&')
            yield scrapy.Request(url, callback=self.parse_sitemap, dont_filter=True)

    def parse_sitemap(self, response):
        body = response.text
        body = re.sub(r'\sxmlns[^"]*"[^"]*"', '', body)
        urls = re.findall(r'<loc>\s*(https?://racetools\.fr/products/[^<]+)\s*</loc>', body)
        self.logger.info(f"Product sitemap: {len(urls)} product URLs")

        if self.shard is not None and self.total_shards is not None:
            chunk_size = max(1, len(urls) // self.total_shards)
            start = self.shard * chunk_size
            end = len(urls) if self.shard == self.total_shards - 1 else start + chunk_size
            urls = urls[start:end]
            self.logger.info(f"Shard {self.shard}/{self.total_shards}: {len(urls)} URLs")

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
            if isinstance(image, dict):
                image = image.get('url', '')

            description = data.get('description', '')
            if description:
                description = re.sub(r'<[^>]+>', ' ', description).strip()
                description = re.sub(r'\s+', ' ', description)[:500]

            # Category from breadcrumb
            category = []
            for s2 in response.css('script[type="application/ld+json"]::text').getall():
                try:
                    bc = json.loads(s2)
                    if isinstance(bc, dict) and bc.get('@type') == 'BreadcrumbList':
                        for item in bc.get('itemListElement', []):
                            cat_name = item.get('name', '').strip()
                            if cat_name:
                                category.append(cat_name)
                except:
                    pass

            availability = ''
            if isinstance(offers, dict):
                availability = offers.get('availability', '')

            yield self.make_item(
                product_name=name,
                product_url=response.url,
                sku=sku or None,
                ean=gtin if gtin and len(gtin) in (8, 13) else None,
                manufacturer=brand or None,
                manufacturer_ref=mpn or None,
                price=price,
                image_url=image or None,
                description=description or None,
                category_path=category or None,
                in_stock=availability.endswith('InStock'),
            )
            return

    def handle_error(self, failure):
        self.logger.warning(f"Request failed: {failure.request.url} - {failure.value}")
