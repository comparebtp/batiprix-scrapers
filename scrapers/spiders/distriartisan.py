"""Spider for Distriartisan - distriartisan.fr

Strategy: HTTP-only, sitemap-based.
Magento 2 with JSON-LD Product structured data.
Fields: name, price, EAN (gtin13), brand, image, description, SKU, MPN, category.
"""
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class DistriartisanSpider(BaseBTPSpider):
    name = 'distriartisan'
    store_chain = 'distriartisan'
    allowed_domains = ['distriartisan.fr']

    custom_settings = {
        'DOWNLOAD_DELAY': 1.0,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 4,
        'DOWNLOAD_HANDLERS': {},
        'TWISTED_REACTOR': None,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    def start_requests(self):
        # Sitemaps from robots.txt
        sitemaps = [
            'https://www.distriartisan.fr/sitemapProduitsRetail_1.xml',
            'https://www.distriartisan.fr/sitemapProduitsMkp_1.xml',
            'https://www.distriartisan.fr/sitemapProduitsMkp_2.xml',
            'https://www.distriartisan.fr/sitemapProduitsMkp_3.xml',
        ]
        for url in sitemaps:
            yield scrapy.Request(url, callback=self.parse_sitemap)

    def parse_sitemap(self, response):
        # Extract product URLs from sitemap XML
        response.selector.remove_namespaces()
        urls = response.xpath('//url/loc/text()').getall()
        self.logger.info(f"Found {len(urls)} URLs in {response.url}")
        for url in urls:
            # Only product pages (not categories)
            if '/p/' in url or url.count('/') > 4:
                yield scrapy.Request(url, callback=self.parse_product)

    def parse_product(self, response):
        # Extract JSON-LD
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

                # Price
                offers = data.get('offers', {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get('price')
                if not price:
                    continue
                price = float(price)

                # EAN
                ean = data.get('gtin13') or data.get('gtin') or ''

                # Brand
                brand = data.get('brand', {})
                if isinstance(brand, dict):
                    brand = brand.get('name', '')

                # SKU
                sku = data.get('sku', '')

                # MPN
                mpn = data.get('mpn', '')

                # Image
                image = data.get('image', '')
                if isinstance(image, list):
                    image = image[0] if image else ''
                if isinstance(image, dict):
                    image = image.get('url', '')

                # Description
                desc = data.get('description', '')[:500] if data.get('description') else ''

                # Category from breadcrumb
                category = []
                for bc in scripts:
                    try:
                        bc_data = json.loads(bc)
                        if bc_data.get('@type') == 'BreadcrumbList':
                            for item in bc_data.get('itemListElement', []):
                                category.append(item.get('name', ''))
                    except:
                        pass

                yield self.make_item(
                    product_name=name,
                    product_url=response.url,
                    sku=sku or None,
                    ean=ean or None,
                    manufacturer=brand or None,
                    manufacturer_ref=mpn or None,
                    price=price,
                    image_url=image or None,
                    description=desc or None,
                    category_path=category or None,
                    in_stock=offers.get('availability', '').endswith('InStock'),
                )
                return

            except (json.JSONDecodeError, ValueError, KeyError):
                continue
