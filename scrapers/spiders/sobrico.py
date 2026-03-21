"""Spider for Sobrico - sobrico.com

Strategy: HTTP-only, category crawl + JSON-LD.
Rich JSON-LD: name, price, EAN (gtin), brand, MPN, SKU, description, rating.
"""
import json
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class SobricoSpider(BaseBTPSpider):
    name = 'sobrico'
    store_chain = 'sobrico'
    allowed_domains = ['sobrico.com']

    custom_settings = {
        'DOWNLOAD_DELAY': 1.0,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 4,
        'DOWNLOAD_HANDLERS': {},
        'TWISTED_REACTOR': None,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    # BTP-relevant category entry points
    START_CATEGORIES = [
        'https://www.sobrico.com/outillage-electroportatif_C70933.html',
        'https://www.sobrico.com/outillage-a-main_C70940.html',
        'https://www.sobrico.com/quincaillerie_C70935.html',
        'https://www.sobrico.com/plomberie_C70938.html',
        'https://www.sobrico.com/electricite_C70934.html',
        'https://www.sobrico.com/peinture_C70937.html',
        'https://www.sobrico.com/fixation_C70936.html',
        'https://www.sobrico.com/chauffage_C71159.html',
        'https://www.sobrico.com/jardin_C70939.html',
        'https://www.sobrico.com/equipement-de-protection_C70941.html',
    ]

    def start_requests(self):
        # Try sitemap first
        yield scrapy.Request(
            'https://www.sobrico.com/sitemap/Sitemap_SoBrico',
            callback=self.parse_sitemap,
            errback=lambda f: self.start_categories()
        )

    def start_categories(self):
        for url in self.START_CATEGORIES:
            yield scrapy.Request(url, callback=self.parse_category)

    def parse_sitemap(self, response):
        import gzip as gz
        # Decompress if gzipped
        try:
            body = gz.decompress(response.body)
            from scrapy.http import TextResponse
            response = TextResponse(url=response.url, body=body, encoding='utf-8')
        except:
            pass

        response.selector.remove_namespaces()
        # Check if it's a sitemap index
        sitemaps = response.xpath('//sitemap/loc/text()').getall()
        if sitemaps:
            for url in sitemaps:
                yield scrapy.Request(url, callback=self.parse_sitemap)
            return

        # Product URLs
        urls = response.xpath('//url/loc/text()').getall()
        self.logger.info(f"Sitemap: {len(urls)} URLs")
        product_count = 0
        for url in urls:
            if '/p/' in url:
                product_count += 1
                yield scrapy.Request(url, callback=self.parse_product)
        self.logger.info(f"Found {product_count} product URLs")

        if product_count == 0:
            yield from self.start_categories()

    def parse_category(self, response):
        # Extract product links from category page
        links = response.css('a[data-product-tile-link]::attr(href), a.product-tile-link::attr(href)').getall()
        if not links:
            links = response.css('a[href*="/p/"]::attr(href), a[href*="_P"]::attr(href)').getall()

        for link in links:
            yield response.follow(link, callback=self.parse_product)

        # Pagination
        next_page = response.css('a.next::attr(href), a[rel="next"]::attr(href), a[aria-label="Suivant"]::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self.parse_category)

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

                ean = data.get('gtin') or data.get('gtin13') or ''
                # Clean EAN (sometimes has leading 0)
                if ean and len(ean) > 13:
                    ean = ean[-13:]

                brand = data.get('brand', {})
                if isinstance(brand, dict):
                    brand = brand.get('name', '')

                sku = data.get('sku', '')
                mpn = data.get('mpn', '')
                image = data.get('image', '')
                if isinstance(image, list):
                    image = image[0] if image else ''
                if isinstance(image, dict):
                    image = image.get('url', '')

                desc = data.get('description', '')[:500] if data.get('description') else ''

                # Category from URL
                category = []
                for bc_script in scripts:
                    try:
                        bc = json.loads(bc_script)
                        if bc.get('@type') == 'BreadcrumbList':
                            for item in bc.get('itemListElement', []):
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
