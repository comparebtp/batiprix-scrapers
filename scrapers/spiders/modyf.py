"""Spider for Würth Modyf - modyf.fr

Strategy: HTTP-only, sitemap-based.
Magento 2 + Hyva Themes. JSON-LD Product with price, SKU, description.
~490 products: safety shoes, work clothing, PPE.
Affiliate link: append ?ae=292 to all URLs.
"""
import json
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class ModyfSpider(BaseBTPSpider):
    name = 'modyf'
    store_chain = 'modyf'
    allowed_domains = ['modyf.fr']

    # Affiliate tracking parameter
    AFFILIATE_PARAM = '?ae=292'

    custom_settings = {
        'DOWNLOAD_DELAY': 1.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 3,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    def start_requests(self):
        yield scrapy.Request(
            'https://www.modyf.fr/media/sitemap/sitemap_fr_fr.xml',
            callback=self.parse_sitemap
        )

    def parse_sitemap(self, response):
        response.selector.remove_namespaces()
        urls = response.xpath('//url/loc/text()').getall()
        self.logger.info(f"Sitemap: {len(urls)} URLs")

        product_count = 0
        for url in urls:
            # Product pages: have a SKU-like pattern or are not category/cms pages
            if url.endswith('.html') or ('-m' in url.split('/')[-1] and '/' not in url.replace('https://www.modyf.fr/', '')):
                # Skip category pages (they have subcategories)
                path = url.replace('https://www.modyf.fr/', '')
                if '/' not in path and path and not path.startswith(('chaussures-de-securite', 'vetements-', 'accessoires', 'collections', 'nouveautes', 'soldes', 'selection')):
                    continue
                product_count += 1
                yield scrapy.Request(url, callback=self.parse_product)

        # Also try all non-root URLs as potential products
        if product_count == 0:
            for url in urls:
                path = url.replace('https://www.modyf.fr/', '').strip('/')
                if path and '/' not in path:
                    yield scrapy.Request(url, callback=self.parse_product)

        self.logger.info(f"Sent {product_count} URLs to product parser")

    def parse_product(self, response):
        scripts = response.xpath('//script[@type="application/ld+json"]/text()').getall()
        if not scripts:
            # Try with flexible selector
            import re
            scripts = re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', response.text, re.DOTALL | re.IGNORECASE)

        for script in scripts:
            try:
                data = json.loads(script.strip())
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

                sku = data.get('sku', '')
                ean = data.get('gtin13') or data.get('gtin') or ''

                image = data.get('image', '')
                if isinstance(image, list):
                    image = image[0] if image else ''
                if isinstance(image, dict):
                    image = image.get('url', '')

                desc = data.get('description', '')[:500] if data.get('description') else ''

                # Add affiliate parameter to product URL
                product_url = response.url
                if '?' in product_url:
                    product_url += '&ae=292'
                else:
                    product_url += '?ae=292'

                # Category from breadcrumb
                category = []
                for s in scripts:
                    try:
                        bc = json.loads(s.strip())
                        if bc.get('@type') == 'BreadcrumbList':
                            for item in bc.get('itemListElement', []):
                                category.append(item.get('name', ''))
                    except:
                        pass

                yield self.make_item(
                    product_name=name,
                    product_url=product_url,
                    sku=sku or None,
                    ean=ean or None,
                    manufacturer='Würth Modyf',
                    price=price,
                    image_url=image or None,
                    description=desc or None,
                    category_path=category or ['Vêtements de travail'],
                    in_stock=offers.get('availability', '').endswith('InStock'),
                )
                return

            except (json.JSONDecodeError, ValueError, KeyError):
                continue
