"""Spider for Point P - pointp.fr

Strategy: Sitemap-based, HTTP-only, JSON-LD extraction.
Same group as Cedeo (Saint-Gobain) — identical page structure.
100K+ construction materials with prices TTC.

Sitemap index: https://www.pointp.fr/sitemap_index.xml
  -> articles_urls_1.xml, articles_urls_2.xml

Sharding: use -a shard=N -a total_shards=M to split the URL list.

Note: Do NOT set TWISTED_REACTOR or DOWNLOAD_HANDLERS in custom_settings.
"""
import gzip
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class PointPSpider(BaseBTPSpider):
    name = 'pointp'
    store_chain = 'pointp'
    allowed_domains = ['pointp.fr', 'www.pointp.fr']

    SITEMAP_URLS = [
        f'https://www.pointp.fr/sitemap/articles_urls_{i}.xml'
        for i in range(1, 3)
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

    def __init__(self, shard=None, total_shards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shard = int(shard) if shard is not None else None
        self.total_shards = int(total_shards) if total_shards is not None else None
        self.seen_urls = set()

    def start_requests(self):
        for url in self.SITEMAP_URLS:
            yield scrapy.Request(
                url,
                callback=self.parse_sitemap,
                dont_filter=True,
            )

    def parse_sitemap(self, response):
        """Parse sitemap XML (possibly gzipped) and extract product URLs."""
        body = response.body
        if body[:2] == b'\x1f\x8b':
            body = gzip.decompress(body)
        text = body.decode('utf-8', errors='replace')
        text = re.sub(r'\sxmlns[^"]*"[^"]*"', '', text)

        urls = re.findall(r'<loc>\s*(https?://[^<]+/p/[^<]+)\s*</loc>', text)

        self.logger.info(
            f"Sitemap {response.url}: found {len(urls)} product URLs"
        )

        if self.shard is not None and self.total_shards is not None:
            urls = [
                u for i, u in enumerate(urls)
                if i % self.total_shards == self.shard
            ]
            self.logger.info(
                f"Shard {self.shard}/{self.total_shards}: "
                f"processing {len(urls)} URLs from this sitemap"
            )

        for url in urls:
            if url in self.seen_urls:
                continue
            self.seen_urls.add(url)
            yield scrapy.Request(
                url,
                callback=self.parse_product,
                errback=self.handle_error,
            )

    def parse_product(self, response):
        """Parse a product page using JSON-LD structured data."""
        if response.status in (403, 404):
            return

        product_data = None
        breadcrumb = []
        properties = []

        for script in response.css(
            'script[type="application/ld+json"]::text'
        ).getall():
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
                items = data.get('itemListElement', [])
                for item in items:
                    name = item.get('name', '').strip()
                    if name and name.lower() not in ('point.p', 'accueil'):
                        breadcrumb.append(name)
            elif dtype == 'PropertyValue':
                properties.append({
                    'name': data.get('name', ''),
                    'value': data.get('value', ''),
                })

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
            description = re.sub(r'\s+', ' ', description)
            if len(description) > 500:
                description = description[:500]

        category_path = breadcrumb if breadcrumb else None

        mfr_ref = None
        for prop in properties:
            if 'référence' in prop.get('name', '').lower():
                mfr_ref = prop.get('value', '')
                break

        yield self.make_item(
            product_name=name,
            product_url=response.url,
            sku=sku,
            ean=ean,
            manufacturer=brand or None,
            manufacturer_ref=mfr_ref or None,
            price=price,
            unit_label='TTC' if price else None,
            image_url=image_url or None,
            description=description or None,
            category_path=category_path,
            in_stock=True,
        )

    def handle_error(self, failure):
        """Log request failures without crashing."""
        self.logger.warning(
            f"Request failed: {failure.request.url} - {failure.value}"
        )
