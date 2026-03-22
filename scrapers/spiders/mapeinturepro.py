"""Spider for MaPeinturePRO - mapeinturepro.com

Strategy: Category crawl + JSON-LD extraction.
PrestaShop store, peinture professionnelle (Caparol, Sikkens, etc.).
JSON-LD: name, price, SKU, MPN, brand, description, availability.
Sitemap is empty (PrestaShop bug), so we crawl categories.
"""
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class MaPeintureProSpider(BaseBTPSpider):
    name = 'mapeinturepro'
    store_chain = 'mapeinturepro'
    allowed_domains = ['mapeinturepro.com']

    START_CATEGORIES = [
        'https://mapeinturepro.com/379-interieur',
        'https://mapeinturepro.com/380-exterieur',
        'https://mapeinturepro.com/381-bois',
        'https://mapeinturepro.com/382-sols',
        'https://mapeinturepro.com/383-metaux',
        'https://mapeinturepro.com/386-accessoires',
        'https://mapeinturepro.com/387-enduits',
        'https://mapeinturepro.com/390-preparation-des-supports',
        'https://mapeinturepro.com/388-colles',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2.0,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
    }

    def start_requests(self):
        for url in self.START_CATEGORIES:
            yield scrapy.Request(url, callback=self.parse_category)

    def parse_category(self, response):
        if response.status in (403, 404):
            return

        # Product links (PrestaShop pattern: /category/id-name.html)
        product_links = response.css(
            'a.product-thumbnail::attr(href), '
            'a.thumbnail.product-thumbnail::attr(href), '
            'h2.product-title a::attr(href), '
            'a[data-id-product]::attr(href)'
        ).getall()

        if not product_links:
            # Fallback: find links matching PrestaShop product URL patterns
            product_links = [
                link for link in response.css('a::attr(href)').getall()
                if re.search(r'/\d+-[a-z].*\.html', link)
            ]

        seen = set()
        for link in product_links:
            url = response.urljoin(link)
            if url not in seen:
                seen.add(url)
                yield scrapy.Request(url, callback=self.parse_product)

        # Subcategories
        subcategory_links = response.css(
            'a.subcategory-name::attr(href), '
            'div.subcategories a::attr(href)'
        ).getall()
        for link in subcategory_links:
            yield response.follow(link, callback=self.parse_category)

        # Pagination
        next_page = response.css(
            'a.next::attr(href), '
            'a[rel="next"]::attr(href), '
            'li.pagination_next a::attr(href)'
        ).get()
        if next_page:
            yield response.follow(next_page, callback=self.parse_category)

    def parse_product(self, response):
        if response.status in (403, 404):
            return

        # First pass: breadcrumb
        category = []
        for script in response.css('script[type="application/ld+json"]::text').getall():
            try:
                data = json.loads(script)
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    for item in data.get('itemListElement', []):
                        name = item.get('name', '').strip()
                        if name:
                            category.append(name)
            except (json.JSONDecodeError, ValueError):
                pass

        # Second pass: Product JSON-LD
        for script in response.css('script[type="application/ld+json"]::text').getall():
            try:
                data = json.loads(script)
            except (json.JSONDecodeError, ValueError):
                continue

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'Product':
                        data = item
                        break
                else:
                    continue

            if not isinstance(data, dict) or data.get('@type') != 'Product':
                continue

            name = data.get('name', '').strip()
            if not name:
                continue

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
            if not price:
                continue

            brand_data = data.get('brand', {})
            brand = brand_data.get('name', '') if isinstance(brand_data, dict) else ''

            sku = data.get('sku', '') or (offers.get('sku', '') if isinstance(offers, dict) else '')
            mpn = data.get('mpn', '') or (offers.get('mpn', '') if isinstance(offers, dict) else '')
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
