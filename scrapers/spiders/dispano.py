"""Spider for Dispano - dispano.fr

Strategy: Sitemap-based, HTTP-only, JSON-LD extraction.
Same group as Cedeo/Point P (Saint-Gobain) — identical page structure.
Bois, panneaux, menuiseries. Prices TTC, EAN available.

Sitemap index: https://www.dispano.fr/sitemap_index.xml
  -> articles_urls_1.xml

Note: Do NOT set TWISTED_REACTOR or DOWNLOAD_HANDLERS in custom_settings.
"""
import gzip
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class DispanoSpider(BaseBTPSpider):
    name = 'dispano'
    store_chain = 'dispano'
    allowed_domains = ['dispano.fr', 'www.dispano.fr']

    SITEMAP_URLS = [
        'https://www.dispano.fr/articles_urls_1.xml',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2.0,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 3,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'DEFAULT_REQUEST_HEADERS': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
        },
        'RETRY_TIMES': 2,
        'RETRY_HTTP_CODES': [429, 500, 502, 503],
    }

    def start_requests(self):
        for url in self.SITEMAP_URLS:
            yield scrapy.Request(url, callback=self.parse_sitemap, dont_filter=True)

    def parse_sitemap(self, response):
        body = response.body
        if body[:2] == b'\x1f\x8b':
            body = gzip.decompress(body)
        text = body.decode('utf-8', errors='replace')
        text = re.sub(r'\sxmlns[^"]*"[^"]*"', '', text)
        urls = re.findall(r'<loc>\s*(https?://[^<]+/p/[^<]+)\s*</loc>', text)
        self.logger.info(f"Sitemap {response.url}: found {len(urls)} product URLs")
        for url in urls:
            yield scrapy.Request(url, callback=self.parse_product, errback=self.handle_error)

    def parse_product(self, response):
        if response.status in (403, 404):
            return

        product_data = None
        breadcrumb = []

        for script in response.css('script[type="application/ld+json"]::text').getall():
            try:
                data = json.loads(script.rstrip(';'))
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            dtype = data.get('@type', '')
            if dtype == 'Product':
                product_data = data
            elif dtype == 'BreadcrumbList':
                for item in data.get('itemListElement', []):
                    name = item.get('name', '').strip()
                    if name and name.lower() not in ('dispano', 'accueil'):
                        breadcrumb.append(name)

        if not product_data:
            return

        name = product_data.get('name', '')
        if not name:
            return

        brand_data = product_data.get('brand', {})
        brand = brand_data.get('name', '') if isinstance(brand_data, dict) else ''

        offers = product_data.get('offers', {})
        price = None
        if isinstance(offers, dict):
            p = offers.get('price')
            if p is not None:
                try:
                    price = round(float(p), 2)
                except (ValueError, TypeError):
                    pass

        ean = None
        product_id = product_data.get('productID', '')
        if product_id and product_id.startswith('ean:'):
            ean_val = product_id[4:].strip()
            if ean_val.isdigit() and len(ean_val) in (8, 13):
                ean = ean_val

        sku = None
        sku_match = re.search(r'-A(\d+)$', response.url)
        if sku_match:
            sku = sku_match.group(1)

        image_data = product_data.get('image', {})
        image_url = None
        if isinstance(image_data, dict):
            image_url = image_data.get('url', '')
        elif isinstance(image_data, str):
            image_url = image_data

        description = product_data.get('description', '')
        if description:
            description = re.sub(r'<[^>]+>', ' ', description).strip()
            description = re.sub(r'\s+', ' ', description)[:500]

        yield self.make_item(
            product_name=name,
            product_url=response.url,
            sku=sku,
            ean=ean,
            manufacturer=brand or None,
            price=price,
            unit_label='TTC' if price else None,
            image_url=image_url or None,
            description=description or None,
            category_path=breadcrumb if breadcrumb else None,
            in_stock=True,
        )

    def handle_error(self, failure):
        self.logger.warning(f"Request failed: {failure.request.url} - {failure.value}")
