"""Spider for Au Comptoir de la Quincaillerie - aucomptoirdelaquincaillerie.fr

Strategy: Sitemap-based, microdata extraction (itemprop).
Custom CMS with ~15,500 products. Quincaillerie pro (serrurerie, ferronnerie, outillage).
No JSON-LD Product, but rich microdata: name, price, sku, mpn, gtin13, brand.

Sitemap: https://www.aucomptoirdelaquincaillerie.fr/sitemap-index.xml
Product sitemap: siteMapsFRProduit1.xml (~15,500 product URLs)
Product URL pattern: /product-name-aNNN.html
"""
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class AuComptoirQuincaillerieSpider(BaseBTPSpider):
    name = 'aucomptoirquincaillerie'
    store_chain = 'aucomptoirquincaillerie'
    allowed_domains = ['aucomptoirdelaquincaillerie.fr', 'www.aucomptoirdelaquincaillerie.fr']

    custom_settings = {
        'DOWNLOAD_DELAY': 2.0,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 3,
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
            'https://www.aucomptoirdelaquincaillerie.fr/siteMapsFRProduit1.xml',
            callback=self.parse_sitemap,
            dont_filter=True,
        )

    def parse_sitemap(self, response):
        body = response.text
        body = re.sub(r'\sxmlns[^"]*"[^"]*"', '', body)
        urls = re.findall(r'<loc>\s*(https?://[^<]+\.html)\s*</loc>', body)
        self.logger.info(f"Sitemap: found {len(urls)} product URLs")

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

        # Extract microdata (itemprop attributes)
        name = response.css('[itemprop="name"]::text').get()
        if not name:
            name = response.css('h1::text').get()
        if not name:
            return
        name = name.strip()
        if not name:
            return

        # Price from itemprop
        price_str = response.css('[itemprop="price"]::attr(content)').get()
        if not price_str:
            price_str = response.css('[itemprop="price"]::text').get()
        price = self.parse_price(price_str)
        if not price:
            return

        # SKU
        sku = response.css('[itemprop="sku"]::attr(content)').get()
        if not sku:
            sku = response.css('[itemprop="sku"]::text').get()
        if sku:
            sku = sku.strip()

        # MPN
        mpn = response.css('[itemprop="mpn"]::attr(content)').get()
        if not mpn:
            mpn = response.css('[itemprop="mpn"]::text').get()
        if mpn:
            mpn = mpn.strip()
            # Clean "mpn:" prefix if present
            mpn = re.sub(r'^mpn:', '', mpn).strip()

        # GTIN / EAN
        gtin = response.css('[itemprop="gtin13"]::attr(content)').get()
        if not gtin:
            gtin = response.css('[itemprop="gtin13"]::text').get()
        if gtin:
            gtin = gtin.strip()

        # Brand
        brand = response.css('[itemprop="brand"]::text').get()
        if not brand:
            brand = response.css('[itemprop="brand"] [itemprop="name"]::text').get()
        if brand:
            brand = brand.strip()

        # Image
        image = response.css('[itemprop="image"]::attr(content)').get()
        if not image:
            image = response.css('[itemprop="image"]::attr(src)').get()
        if image:
            image = response.urljoin(image)

        # Description
        description = response.css('[itemprop="description"]::text').get()
        if not description:
            description = response.css('meta[name="description"]::attr(content)').get()
        if description:
            description = re.sub(r'<[^>]+>', ' ', description).strip()
            description = re.sub(r'\s+', ' ', description)[:500]

        # Availability
        availability = response.css('[itemprop="availability"]::attr(content)').get()
        if not availability:
            availability = response.css('[itemprop="availability"]::attr(href)').get()
        in_stock = bool(availability and 'InStock' in availability)

        yield self.make_item(
            product_name=name,
            product_url=response.url,
            sku=sku or None,
            ean=gtin if gtin and len(gtin) in (8, 13) and gtin.isdigit() else None,
            manufacturer=brand or None,
            manufacturer_ref=mpn or None,
            price=price,
            image_url=image or None,
            description=description or None,
            in_stock=in_stock,
        )

    def handle_error(self, failure):
        self.logger.warning(f"Request failed: {failure.request.url} - {failure.value}")
