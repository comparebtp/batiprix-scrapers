"""Spider for MaterielElectrique - materielelectrique.com

Strategy: HTTP-only, sitemap-based.
JSON-LD Product with EAN (gtin13), price, brand, description, category.
Very large catalog (50K-100K products), zero anti-bot.
"""
import json
import gzip
import scrapy
from scrapers.spiders.base import BaseBTPSpider
from io import BytesIO


class MaterielElectriqueSpider(BaseBTPSpider):
    name = 'materiel_electrique'
    store_chain = 'materiel_electrique'
    allowed_domains = ['materielelectrique.com']

    custom_settings = {
        'DOWNLOAD_DELAY': 0.8,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 5,
        'DOWNLOAD_HANDLERS': {},
        'TWISTED_REACTOR': None,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    def start_requests(self):
        yield scrapy.Request(
            'https://www.materielelectrique.com/sitemap.xml',
            callback=self.parse_sitemap_index
        )

    def parse_sitemap_index(self, response):
        response.selector.remove_namespaces()
        # Sitemap index contains links to sub-sitemaps
        sitemaps = response.xpath('//sitemap/loc/text()').getall()
        self.logger.info(f"Found {len(sitemaps)} sub-sitemaps")
        for url in sitemaps:
            # Only product sitemaps
            if 'product' in url.lower() or 'catalog' in url.lower():
                yield scrapy.Request(url, callback=self.parse_sitemap)

    def parse_sitemap(self, response):
        # Handle gzipped sitemaps
        if response.url.endswith('.gz'):
            try:
                body = gzip.decompress(response.body)
                from scrapy.http import TextResponse
                response = TextResponse(
                    url=response.url,
                    body=body,
                    encoding='utf-8'
                )
            except:
                pass

        response.selector.remove_namespaces()
        urls = response.xpath('//url/loc/text()').getall()
        self.logger.info(f"Sitemap {response.url}: {len(urls)} URLs")

        for url in urls:
            # Product pages have pattern like /product-name-p-12345.html
            if '-p-' in url:
                yield scrapy.Request(url, callback=self.parse_product)

    def parse_product(self, response):
        scripts = response.xpath('//script[@type="application/ld+json"]/text()').getall()
        for script in scripts:
            try:
                data = json.loads(script)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Product':
                            data = item
                            break
                    else:
                        continue
                if data.get('@type') != 'Product':
                    continue

                name = data.get('name', '').strip()
                if not name:
                    continue

                offers = data.get('offers', {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get('price')
                if not price:
                    continue
                price = float(price)

                ean = data.get('gtin13') or data.get('gtin') or ''

                brand = data.get('brand', '')
                if isinstance(brand, dict):
                    brand = brand.get('name', '')

                sku = data.get('sku', '')

                image = data.get('image', '')
                if isinstance(image, list):
                    image = image[0] if image else ''
                if isinstance(image, dict):
                    image = image.get('url', '')

                desc = data.get('description', '')[:500] if data.get('description') else ''

                category = data.get('category', '')
                category_list = [category] if category else []

                yield self.make_item(
                    product_name=name,
                    product_url=response.url,
                    sku=sku or None,
                    ean=ean or None,
                    manufacturer=brand or None,
                    price=price,
                    image_url=image or None,
                    description=desc or None,
                    category_path=category_list or None,
                    in_stock=offers.get('availability', '').endswith('InStock'),
                )
                return

            except (json.JSONDecodeError, ValueError, KeyError):
                continue
