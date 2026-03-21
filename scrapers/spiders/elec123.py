"""Spider for 123elec - 123elec.com

Strategy: Sitemap-based + category crawl fallback.
Platform: Magento 2 (Hyva theme), electrical supplies specialist.
JSON-LD: Product with price, brand, gtin13, sku, description, reviews.
Sitemap: https://www.123elec.com/media/sitemap/sitemap.xml (~9000 URLs, mix of categories and products).
No aggressive anti-bot. ROBOTSTXT_OBEY: True.
"""
import json
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class Elec123Spider(BaseBTPSpider):
    name = 'elec123'
    store_chain = 'elec123'
    allowed_domains = ['123elec.com']

    custom_settings = {
        'DOWNLOAD_DELAY': 1.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 3,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
    }

    # BTP-relevant category entry points
    START_CATEGORIES = [
        'https://www.123elec.com/gamme-materiel-electrique.html',
        'https://www.123elec.com/gamme-materiel-electrique/disjoncteurs.html',
        'https://www.123elec.com/gamme-materiel-electrique/interrupteurs-differentiels.html',
        'https://www.123elec.com/gamme-materiel-electrique/tableaux-electriques.html',
        'https://www.123elec.com/gamme-materiel-electrique/parafoudres.html',
        'https://www.123elec.com/interrupteurs-et-prises.html',
        'https://www.123elec.com/interrupteurs-et-prises/interrupteurs-et-prises-legrand/legrand-celiane.html',
        'https://www.123elec.com/cables-gaines-conduits.html',
        'https://www.123elec.com/cables-gaines-conduits/fils-electriques.html',
        'https://www.123elec.com/boites-connecteurs.html',
        'https://www.123elec.com/coffrets-de-communication-vdi-tv.html',
        'https://www.123elec.com/eclairage-luminaire.html',
        'https://www.123elec.com/chauffage-climatisation-ecs.html',
        'https://www.123elec.com/vmc-hottes-aeration.html',
        'https://www.123elec.com/securite-acces.html',
        'https://www.123elec.com/equipement-electrique-outillage.html',
    ]

    # Fallback product URLs for testing
    start_urls = [
        'https://www.123elec.com/legrand-disjoncteur-electrique-dnx3-uni-neutre-2a.html',
        'https://www.123elec.com/block-fire-extincteur-boule-automatique-poudre-abc-bfi-abc02.html',
    ]

    def start_requests(self):
        """Try sitemap first, fallback to category crawl."""
        self._category_started = False

        yield scrapy.Request(
            'https://www.123elec.com/media/sitemap/sitemap.xml',
            callback=self.parse_sitemap,
            errback=self._on_sitemap_fail,
            dont_filter=True,
        )

    def _on_sitemap_fail(self, failure):
        """Sitemap failed, start category crawl."""
        self.logger.warning(f"Sitemap failed: {failure.value}")
        if not self._category_started:
            yield from self._start_category_crawl()

    def parse_sitemap(self, response):
        """Parse sitemap and extract product URLs."""
        if response.status != 200:
            self.logger.warning(f"Sitemap returned {response.status}")
            if not self._category_started:
                yield from self._start_category_crawl()
            return

        response.selector.remove_namespaces()
        urls = response.xpath('//url/loc/text()').getall()
        self.logger.info(f"Sitemap: {len(urls)} total URLs")

        # On 123elec, product URLs are typically flat (no subdirectory in path)
        # and end with .html. Category URLs tend to have subdirectories.
        # However, some product URLs have subdirectories too.
        # We send all .html URLs to parse_product; the parser will skip non-products
        # (no JSON-LD Product) gracefully.
        product_count = 0
        for url in urls:
            if url.endswith('.html'):
                product_count += 1
                yield scrapy.Request(url, callback=self.parse_product)

        self.logger.info(f"Sent {product_count} URLs to product parser")

    def _start_category_crawl(self):
        """Start crawling from category entry points."""
        self._category_started = True
        self.logger.info(f"Starting category crawl with {len(self.START_CATEGORIES)} entries")
        for url in self.START_CATEGORIES:
            yield scrapy.Request(
                url,
                callback=self.parse_category,
                meta={'depth': 0},
                dont_filter=True,
            )

    def parse_category(self, response):
        """Extract product links from category pages."""
        depth = response.meta.get('depth', 0)

        # Find product links
        product_links = set()
        for link in response.css('a::attr(href)').getall():
            full_url = response.urljoin(link)
            if (
                '123elec.com/' in full_url
                and full_url.endswith('.html')
                and '/checkout/' not in full_url
                and '/customer/' not in full_url
                and '/catalogsearch/' not in full_url
                and '/media/' not in full_url
                and '/static/' not in full_url
            ):
                product_links.add(full_url)

        self.logger.info(f"Category {response.url}: {len(product_links)} links")
        for url in product_links:
            yield scrapy.Request(url, callback=self.parse_product)

        # Pagination
        next_page = response.css('a[rel="next"]::attr(href)').get()
        if not next_page:
            next_page = response.css(
                'li.pages-item-next a::attr(href), '
                'a.action.next::attr(href), '
                'a[title="Suivant"]::attr(href), '
                'a[title="Page suivante"]::attr(href)'
            ).get()
        if next_page:
            yield response.follow(next_page, callback=self.parse_category,
                                  meta={'depth': depth})

        # Subcategories (max depth 3)
        if depth < 3:
            for link in response.css('a::attr(href)').getall():
                full_url = response.urljoin(link)
                if (
                    '123elec.com/' in full_url
                    and not full_url.endswith('.html')
                    and '/checkout/' not in full_url
                    and '/customer/' not in full_url
                    and '?' not in full_url
                    and '#' not in full_url
                    and full_url.rstrip('/') != response.url.rstrip('/')
                    and full_url.count('/') >= 4
                ):
                    yield scrapy.Request(
                        full_url,
                        callback=self.parse_category,
                        meta={'depth': depth + 1},
                    )

    def parse_product(self, response):
        """Extract product data from JSON-LD structured data."""
        scripts = response.xpath('//script[@type="application/ld+json"]/text()').getall()

        # First pass: BreadcrumbList for category
        category = []
        for script in scripts:
            try:
                data = json.loads(script)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'BreadcrumbList':
                            data = item
                            break
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    for item in data.get('itemListElement', []):
                        name = item.get('name', '').strip()
                        if name:
                            category.append(name)
            except (json.JSONDecodeError, ValueError):
                pass

        # Second pass: Product
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

                # EAN - 123elec has gtin13 in JSON-LD
                ean = data.get('gtin13') or data.get('gtin') or ''

                # Brand
                brand = data.get('brand', {})
                if isinstance(brand, dict):
                    brand = brand.get('name', '')

                # SKU
                sku = data.get('sku', '')

                # MPN - try to extract manufacturer ref from page
                mpn = data.get('mpn', '')
                if not mpn:
                    # 123elec shows "Fabricant : XXXXX" on product pages
                    fab_ref = response.css(
                        'span:contains("Fabricant")::text, '
                        'div:contains("Fabricant")::text'
                    ).re_first(r'Fabricant\s*:\s*(\S+)')
                    if fab_ref:
                        # Strip brackets that sometimes appear in the reference
                        mpn = fab_ref.strip('[](){}')

                # Image
                image = data.get('image', '')
                if isinstance(image, list):
                    image = image[0] if image else ''
                if isinstance(image, dict):
                    image = image.get('url', '')

                # Description
                desc = data.get('description', '')[:500] if data.get('description') else ''

                # Weight (available in JSON-LD on 123elec)
                weight = data.get('weight', '')

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

        # Fallback: meta tags (for pages without JSON-LD Product)
        self._parse_product_fallback(response, category)

    def _parse_product_fallback(self, response, category):
        """Fallback extraction from meta tags and DOM."""
        # Check if this is actually a product page (has product:price meta)
        price_str = response.css('meta[property="product:price:amount"]::attr(content)').get()
        if not price_str:
            # Not a product page (likely a category), skip silently
            return

        name = (
            response.css('meta[property="og:title"]::attr(content)').get()
            or response.css('h1.page-title span::text, h1::text').get()
        )
        if not name:
            return
        name = name.strip()

        price = self.parse_price(price_str)
        if not price:
            return

        image = response.css('meta[property="og:image"]::attr(content)').get()
        brand = response.css('meta[property="product:brand"]::attr(content)').get()

        sku = response.css(
            'div[itemprop="sku"]::text, '
            '.product.attribute.sku .value::text'
        ).get()

        desc = response.css('meta[property="og:description"]::attr(content)').get()
        if desc:
            desc = desc[:500]

        yield self.make_item(
            product_name=name,
            product_url=response.url,
            sku=sku.strip() if sku else None,
            manufacturer=brand or None,
            price=price,
            image_url=image or None,
            description=desc or None,
            category_path=category or None,
        )
