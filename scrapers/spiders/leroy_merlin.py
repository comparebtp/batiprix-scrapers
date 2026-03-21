"""Spider for Leroy Merlin France - leroymerlin.fr

Strategy: DataDome blocks all browser access. Instead:
1. Fetch product sitemaps (accessible with Googlebot UA)
2. Extract product URLs (contain name + reference in the URL)
3. Try to fetch individual pages with Googlebot UA for JSON-LD
4. Fallback: extract what we can from sitemap + URL structure

URL pattern: /produits/NOM-DU-PRODUIT-REFXXXXXXXX.html
"""
import re
import json
import logging
import scrapy
from scrapers.spiders.base import BaseBTPSpider

logger = logging.getLogger(__name__)


class LeroyMerlinSpider(BaseBTPSpider):
    name = 'leroy_merlin'
    store_chain = 'leroy_merlin'
    allowed_domains = ['leroymerlin.fr']

    # BTP-relevant categories to filter from sitemap
    BTP_KEYWORDS = {
        'outillage', 'outil', 'perceuse', 'visseuse', 'meuleuse', 'scie',
        'tournevis', 'marteau', 'pince', 'cle', 'niveau', 'metre',
        'peinture', 'rouleau', 'pinceau', 'enduit', 'lasure', 'vernis',
        'plomberie', 'robinet', 'tuyau', 'raccord', 'siphon', 'mitigeur',
        'electricite', 'cable', 'interrupteur', 'prise', 'disjoncteur', 'tableau',
        'carrelage', 'colle', 'joint', 'mortier', 'ciment', 'beton',
        'isolation', 'laine', 'polystyrene', 'plaque', 'placo',
        'vis', 'boulon', 'ecrou', 'cheville', 'fixation', 'clou',
        'parpaing', 'brique', 'agglo', 'ferraillage', 'acier',
        'menuiserie', 'bois', 'panneau', 'lame', 'terrasse',
        'quincaillerie', 'serrure', 'charniere', 'poignee',
        'sanitaire', 'wc', 'lavabo', 'douche', 'baignoire',
        'chauffage', 'radiateur', 'chaudiere', 'pompe',
        'eclairage', 'ampoule', 'spot', 'luminaire', 'projecteur',
    }

    custom_settings = {
        'DOWNLOAD_DELAY': 1,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
        'ROBOTSTXT_OBEY': False,  # We use Googlebot UA
        'USER_AGENT': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
        # No need to override DOWNLOAD_HANDLERS or TWISTED_REACTOR.
        # Playwright only activates for requests with meta={'playwright': True}.
    }

    def start_requests(self):
        # Fetch product sitemaps (99 total, but start with first few)
        max_sitemaps = getattr(self, 'max_sitemaps', 20)
        for i in range(1, int(max_sitemaps) + 1):
            yield scrapy.Request(
                f'https://www.leroymerlin.fr/sitemap-product{i}.xml',
                callback=self.parse_sitemap,
                meta={'sitemap_index': i},
            )

    def parse_sitemap(self, response):
        """Parse product sitemap XML and extract product URLs."""
        idx = response.meta.get('sitemap_index', '?')

        # Parse XML - extract <loc> tags
        # Scrapy gives us the raw XML, parse with regex for simplicity
        urls = re.findall(r'<loc>(https://www\.leroymerlin\.fr/produits/[^<]+)</loc>', response.text)
        logger.info(f"Sitemap {idx}: found {len(urls)} product URLs")

        btp_count = 0
        for url in urls:
            # Filter for BTP-relevant products
            url_lower = url.lower()
            if self._is_btp_product(url_lower):
                btp_count += 1
                yield scrapy.Request(
                    url,
                    callback=self.parse_product_page,
                    meta={'product_url': url},
                    errback=self.handle_product_error,
                )

        logger.info(f"Sitemap {idx}: {btp_count}/{len(urls)} are BTP-relevant")

    def _is_btp_product(self, url_lower):
        """Check if a product URL is BTP-relevant based on keywords."""
        # Extract the path part
        path = url_lower.replace('https://www.leroymerlin.fr/produits/', '')
        return any(kw in path for kw in self.BTP_KEYWORDS)

    def parse_product_page(self, response):
        """Try to extract product data from the page.
        DataDome will likely block most requests, so we have a fallback."""

        if response.status == 403:
            # Blocked - extract what we can from URL
            yield from self._extract_from_url(response.meta['product_url'])
            return

        # If we got through, look for JSON-LD or __NEXT_DATA__
        # JSON-LD
        json_ld_scripts = response.css('script[type="application/ld+json"]::text').getall()
        for script_text in json_ld_scripts:
            try:
                data = json.loads(script_text)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Product':
                            yield self._parse_json_ld_product(item, response.url)
                            return
                elif isinstance(data, dict) and data.get('@type') == 'Product':
                    yield self._parse_json_ld_product(data, response.url)
                    return
            except json.JSONDecodeError:
                continue

        # __NEXT_DATA__ fallback
        next_data_text = response.css('script#__NEXT_DATA__::text').get()
        if next_data_text:
            try:
                next_data = json.loads(next_data_text)
                page_props = next_data.get('props', {}).get('pageProps', {})
                product = page_props.get('product', {})
                if product:
                    yield self._parse_next_data_product(product, response.url)
                    return
            except json.JSONDecodeError:
                pass

        # Last resort - extract from URL
        yield from self._extract_from_url(response.url)

    def _parse_json_ld_product(self, data, url):
        """Parse a JSON-LD Product object."""
        offers = data.get('offers', {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        return self.make_item(
            product_name=data.get('name', ''),
            product_url=url,
            sku=data.get('sku', ''),
            ean=data.get('gtin13') or data.get('gtin'),
            manufacturer=data.get('brand', {}).get('name', '') if isinstance(data.get('brand'), dict) else str(data.get('brand', '')),
            price=offers.get('price'),
            image_url=data.get('image', [''])[0] if isinstance(data.get('image'), list) else data.get('image', ''),
            in_stock='InStock' in str(offers.get('availability', '')),
            category_path=self._extract_category_from_url(url),
        )

    def _parse_next_data_product(self, product, url):
        """Parse product from __NEXT_DATA__."""
        price_data = product.get('price', {})
        price = price_data.get('value') if isinstance(price_data, dict) else price_data

        brand = product.get('brand', '')
        if isinstance(brand, dict):
            brand = brand.get('name', '')

        return self.make_item(
            product_name=product.get('title') or product.get('name', ''),
            product_url=url,
            sku=str(product.get('ref') or product.get('id', '')),
            ean=product.get('ean'),
            manufacturer=brand,
            price=price,
            image_url=product.get('images', [{}])[0].get('url', '') if product.get('images') else '',
            in_stock=product.get('available', True),
            category_path=self._extract_category_from_url(url),
        )

    def _extract_from_url(self, url):
        """Extract basic product info from URL structure.
        URL format: /produits/NOM-du-produit-REFXXXXXXXX.html
        """
        path = url.replace('https://www.leroymerlin.fr/produits/', '').replace('.html', '')

        # Extract reference (last number group in URL)
        ref_match = re.search(r'-(\d{7,10})$', path)
        ref = ref_match.group(1) if ref_match else ''

        # Extract name (everything before the ref)
        name_part = path
        if ref:
            name_part = path[:-(len(ref) + 1)]  # remove "-REF" from end

        # Clean name: replace hyphens with spaces, title case
        name = name_part.split('/')[-1].replace('-', ' ').strip()
        name = ' '.join(word.capitalize() if len(word) > 2 else word for word in name.split())

        if name:
            yield self.make_item(
                product_name=name,
                product_url=url,
                sku=ref,
                category_path=self._extract_category_from_url(url),
                # No price available from URL - will be None
                price=None,
            )

    def _extract_category_from_url(self, url):
        """Extract category path from URL structure."""
        path = url.replace('https://www.leroymerlin.fr/produits/', '')
        parts = path.split('/')
        # Last part is the product slug, everything before is categories
        if len(parts) > 1:
            return [p.replace('-', ' ').title() for p in parts[:-1]]
        return []

    def handle_product_error(self, failure):
        url = failure.request.url
        logger.debug(f"Failed to fetch product page: {url}")
        # Still extract from URL
        for item in self._extract_from_url(url):
            yield item
