"""Spider for Würth France - eshop.wurth.fr

Strategy:
1. Use the Suggest API (ViewParametricSearch-Suggest) to discover product groups
   from BTP search terms. This returns product group IDs, names, and images.
2. Build category URLs from those IDs and visit product group pages.
3. On product group pages, extract the embedded JS data (familyVo/modelContainer)
   for product names, SKUs, images, and links.
4. Follow individual product (.sku) pages to get JSON-LD structured data with
   gtin13 (EAN), exact SKU, and availability.
5. Prices require login, so we extract what's publicly available.

Also crawls BTP-relevant top-level categories to discover products not
found via search terms.
"""
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class WurthSpider(BaseBTPSpider):
    name = 'wurth'
    store_chain = 'wurth'
    allowed_domains = ['eshop.wurth.fr']

    BASE_URL = 'https://eshop.wurth.fr'
    SUGGEST_URL = (
        'https://eshop.wurth.fr/is-bin/INTERSHOP.enfinity/WFS/'
        '3107-B1-Site/fr_FR/-/EUR/ViewParametricSearch-Suggest'
    )

    # BTP search terms to cover the catalog
    SEARCH_TERMS = [
        # Outillage a main
        'tournevis', 'pince', 'cle', 'marteau', 'niveau', 'metre',
        'scie', 'cisaille', 'lime', 'burin', 'spatule', 'truelle',
        # Outillage electroportatif
        'perceuse', 'visseuse', 'meuleuse', 'perforateur', 'scie sauteuse',
        'ponceuse', 'rabot', 'defonceuse', 'decoupeur',
        # Visserie fixation
        'vis', 'boulon', 'ecrou', 'cheville', 'rivet', 'agrafe',
        'clou', 'rondelle', 'tige filetee',
        # Produits chimiques
        'colle', 'mastic', 'silicone', 'mousse polyurethane', 'degrippant',
        'lubrifiant', 'nettoyant frein', 'scellement chimique',
        # Electricite
        'cable', 'gaine', 'collier', 'attache cable', 'domino', 'connecteur',
        # Mesure
        'metre laser', 'niveau laser', 'equerre', 'compas', 'rapporteur',
        # EPI
        'gant', 'lunette protection', 'casque', 'chaussure securite',
        'gilet', 'bouchon oreille',
        # Abrasifs
        'disque', 'foret', 'lame scie', 'trepan', 'meche',
        # Plomberie
        'raccord', 'tuyau', 'collier serrage', 'robinet', 'joint',
        # Construction
        'echafaudage', 'echelle', 'escabeau', 'brouette', 'serre joint',
    ]

    # BTP-relevant top-level category IDs for crawling
    CATEGORY_IDS = [
        ('Chevillage', '310745'),
        ('Fixation-directe', '310740'),
        ('Installation-electrique', '310755'),
        ('Machines', '310750'),
        ('Materiel-de-construction', '310710'),
        ('Metrologie', '310761'),
        ('Outils-manuels', '310760'),
        ('Produits-chimiques', '310730'),
        ('Abrasifs-et-outils-coupants', '310775'),
        ('Equipement-de-securite-et-de-protection', '310705'),
        ('Equipement-d-atelier-et-de-chantier', '310720'),
        ('Vis-Boulons-Rivets-Clous-et-Agrafes', '310735'),
        ('Sanitaire-chauffage-climatisation', '310780'),
        ('Tuyaux-raccords-et-colliers-de-serrage', '310721'),
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
        'DOWNLOAD_HANDLERS': {},
        'TWISTED_REACTOR': None,
        'ROBOTSTXT_OBEY': False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_refs = set()          # deduplicate SKUs across all sources
        self.seen_group_ids = set()     # deduplicate product group pages

    def start_requests(self):
        # --- Phase 1: Search via Suggest API ---
        for term in self.SEARCH_TERMS:
            yield scrapy.Request(
                f'{self.SUGGEST_URL}?SearchTerm={term}',
                callback=self.parse_suggest,
                meta={'search_term': term},
                headers={'Accept': 'application/json'},
            )

        # --- Phase 2: Crawl category tree ---
        for cat_name, cat_id in self.CATEGORY_IDS:
            url = (
                f'{self.BASE_URL}/Categories-produits/{cat_name}/'
                f'{cat_id}.cyid/3107.cgid/fr/FR/EUR/'
            )
            yield scrapy.Request(
                url,
                callback=self.parse_category,
                meta={'category_path': [cat_name.replace('-', ' ')], 'depth': 0},
            )

    # ------------------------------------------------------------------
    # Phase 1: Suggest API -> product group pages
    # ------------------------------------------------------------------

    def parse_suggest(self, response):
        """Parse the JSON suggest API response."""
        search_term = response.meta.get('search_term', '')
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            self.logger.warning(f"Suggest API: invalid JSON for '{search_term}'")
            return

        products = data.get('compressedProducts', [])
        self.logger.info(
            f"Suggest '{search_term}': {len(products)} product groups "
            f"(total: {data.get('numberOfFoundProducts', '?')})"
        )

        for item in products:
            label = item.get('label', '').strip()
            value = item.get('value', '')
            image = item.get('image', '')

            # Extract product group ID: "nameExact:31076013030305:nameExact tournevis"
            id_match = re.search(r'nameExact:(\d+)', value)
            if not id_match:
                continue
            group_id = id_match.group(1)

            if group_id in self.seen_group_ids:
                continue
            self.seen_group_ids.add(group_id)

            # Build category-style URL to the product group
            slug = re.sub(r'[^a-zA-Z0-9]+', '-', label).strip('-')
            group_url = (
                f'{self.BASE_URL}/Categories-produits/{slug}/'
                f'{group_id}.cyid/3107.cgid/fr/FR/EUR/'
            )

            yield scrapy.Request(
                group_url,
                callback=self.parse_product_group,
                meta={
                    'category_path': [search_term.title()],
                    'group_name': label,
                    'group_image': image,
                    'group_id': group_id,
                },
                errback=self.handle_error,
            )

    # ------------------------------------------------------------------
    # Phase 2: Category tree crawling
    # ------------------------------------------------------------------

    def parse_category(self, response):
        """Parse a category page: either subcategories or product groups."""
        category_path = response.meta.get('category_path', [])
        depth = response.meta.get('depth', 0)

        # Look for subcategory links (pattern: /Categories-produits/Name/ID.cyid/...)
        sub_links = response.css(
            'a[href*=".cyid/3107.cgid/"]::attr(href)'
        ).getall()

        # Deduplicate and filter to child categories only
        seen_urls = set()
        for href in sub_links:
            full_url = response.urljoin(href)
            if full_url in seen_urls or full_url == response.url:
                continue
            seen_urls.add(full_url)

            # Extract category name from URL
            name_match = re.search(r'/Categories-produits/([^/]+)/', full_url)
            cat_name = name_match.group(1).replace('-', ' ') if name_match else ''

            # Extract the category ID
            id_match = re.search(r'/(\d+)\.cyid/', full_url)
            if not id_match:
                continue
            cat_id = id_match.group(1)

            # If ID is long enough (>= 10 digits), it's likely a product group page
            if len(cat_id) >= 10:
                if cat_id not in self.seen_group_ids:
                    self.seen_group_ids.add(cat_id)
                    yield scrapy.Request(
                        full_url,
                        callback=self.parse_product_group,
                        meta={
                            'category_path': category_path + [cat_name],
                            'group_id': cat_id,
                        },
                        errback=self.handle_error,
                    )
            elif depth < 4:
                # Subcategory - go deeper
                yield scrapy.Request(
                    full_url,
                    callback=self.parse_category,
                    meta={
                        'category_path': category_path + [cat_name],
                        'depth': depth + 1,
                    },
                )

    # ------------------------------------------------------------------
    # Product group page -> individual product detail pages
    # ------------------------------------------------------------------

    def parse_product_group(self, response):
        """Parse a product group page. Extract embedded JS data and follow
        to individual product .sku pages for full details."""
        category_path = response.meta.get('category_path', [])
        group_name = response.meta.get('group_name', '')

        # Try to extract the embedded familyVo/modelContainer JS data
        # which contains product SKUs and URLs
        body_text = response.text

        # Look for SKU links: href containing ".sku/fr/FR/EUR/"
        sku_links = response.css('a[href*=".sku/fr/FR/EUR/"]::attr(href)').getall()

        # Also extract SKU links from embedded JS
        js_sku_matches = re.findall(
            r'"itemUrl"\s*:\s*"([^"]*\.sku/fr/FR/EUR/[^"]*)"', body_text
        )
        sku_links.extend(js_sku_matches)

        # Also look for SKU patterns in quickBuyInfo
        js_sku_ids = re.findall(r'"productSku"\s*:\s*"([^"]+)"', body_text)

        # Build .sku URLs from SKU IDs if we have them but no links
        if js_sku_ids and not sku_links:
            for sku_id in js_sku_ids:
                sku_url = f'{self.BASE_URL}/{sku_id}.sku/fr/FR/EUR/'
                sku_links.append(sku_url)

        # Deduplicate
        seen_skus = set()
        unique_links = []
        for link in sku_links:
            # Extract SKU from URL
            sku_match = re.search(r'/([^/]+)\.sku/', link)
            if sku_match:
                sku = sku_match.group(1)
                if sku not in seen_skus:
                    seen_skus.add(sku)
                    unique_links.append(link)

        self.logger.info(
            f"Product group '{group_name or response.url}': "
            f"found {len(unique_links)} SKU links"
        )

        for link in unique_links:
            full_url = response.urljoin(link)
            yield scrapy.Request(
                full_url,
                callback=self.parse_product_detail,
                meta={'category_path': category_path},
                errback=self.handle_error,
            )

        # If no SKU links found, try to extract product info directly
        # from JSON-LD on this page (it might be a single-product group)
        if not unique_links:
            yield from self._extract_from_jsonld(response, category_path)

    # ------------------------------------------------------------------
    # Product detail page (.sku URL) -> final item extraction
    # ------------------------------------------------------------------

    def parse_product_detail(self, response):
        """Parse a product detail page and extract item data from JSON-LD."""
        category_path = response.meta.get('category_path', [])
        yield from self._extract_from_jsonld(response, category_path)

    def _extract_from_jsonld(self, response, category_path):
        """Extract product data from JSON-LD structured data on the page."""
        # Find JSON-LD script blocks
        ld_scripts = response.css('script[type="application/ld+json"]::text').getall()

        for script_text in ld_scripts:
            try:
                ld_data = json.loads(script_text)
            except (json.JSONDecodeError, ValueError):
                continue

            ld_type = ld_data.get('@type', '')

            if ld_type == 'ProductGroup':
                # Product group with variants
                group_name = ld_data.get('name', '')
                group_desc = ld_data.get('description', '')
                variants = ld_data.get('hasVariant', [])

                if not variants:
                    # Single product group without explicit variants
                    sku = ld_data.get('sku', '')
                    ean = ld_data.get('gtin13', '')
                    if sku and sku not in self.seen_refs:
                        self.seen_refs.add(sku)
                        yield self._build_item(
                            name=group_name,
                            sku=sku,
                            ean=ean,
                            url=ld_data.get('url', response.url),
                            image=self._get_image(ld_data),
                            description=group_desc,
                            category_path=category_path,
                            response=response,
                        )

                for variant in variants:
                    sku = variant.get('sku', '')
                    if not sku or sku in self.seen_refs:
                        continue
                    self.seen_refs.add(sku)

                    ean = variant.get('gtin13', '')
                    name = variant.get('name', group_name)
                    url = variant.get('@id', '') or self._get_offer_url(variant)
                    image = self._get_image(variant) or self._get_image(ld_data)
                    in_stock = self._parse_availability(variant)

                    # Try to extract price from offers
                    price = self._extract_price_from_offers(variant)

                    yield self._build_item(
                        name=name,
                        sku=sku,
                        ean=ean,
                        url=url or response.url,
                        image=image,
                        price=price,
                        in_stock=in_stock,
                        description=group_desc,
                        category_path=category_path,
                        response=response,
                    )

            elif ld_type == 'Product':
                sku = ld_data.get('sku', '')
                if not sku or sku in self.seen_refs:
                    continue
                self.seen_refs.add(sku)

                ean = ld_data.get('gtin13', '')
                name = ld_data.get('name', '')
                image = self._get_image(ld_data)
                in_stock = self._parse_availability(ld_data)
                price = self._extract_price_from_offers(ld_data)

                yield self._build_item(
                    name=name,
                    sku=sku,
                    ean=ean,
                    url=ld_data.get('url', response.url),
                    image=image,
                    price=price,
                    in_stock=in_stock,
                    description=ld_data.get('description', ''),
                    category_path=category_path,
                    response=response,
                )

        # Fallback: try to extract price from page text if JSON-LD had none
        # Look for the specific HT price pattern on the page
        if not ld_scripts:
            yield from self._fallback_extract(response, category_path)

    def _fallback_extract(self, response, category_path):
        """Fallback extraction from page HTML when no JSON-LD is available."""
        # Try to get product name from h1
        title = response.css('h1::text').get('').strip()
        if not title:
            title = response.css('h1 *::text').get('').strip()
        if not title:
            return

        # Try to get article number
        ref_text = response.css('*::text').re_first(r'Art\.\s*N[°o]\s*([\d\s]+)')
        ref = ref_text.strip().replace(' ', '') if ref_text else ''

        if not ref or ref in self.seen_refs:
            return
        self.seen_refs.add(ref)

        # Try price - look specifically for HT price patterns
        price = self._extract_ht_price(response)

        # Image
        img = response.css(
            'img[src*="media.witglobal.net"]::attr(src)'
        ).get('')

        # EAN from page text
        ean = response.css('*::text').re_first(r'EAN\s*:?\s*(\d{13})') or ''

        yield self._build_item(
            name=title,
            sku=ref,
            ean=ean,
            url=response.url,
            image=img,
            price=price,
            category_path=category_path,
            response=response,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_item(self, name, sku, ean, url, image, category_path,
                    response, price=None, in_stock=None, description=''):
        """Build a BTPProductItem via make_item."""
        return self.make_item(
            product_name=name,
            product_url=url,
            sku=sku,
            ean=ean or None,
            manufacturer_ref=sku,
            manufacturer='Würth',
            price=price,
            unit_label='€ HT' if price else None,
            image_url=image or '',
            category_path=category_path,
            in_stock=in_stock,
            description=description or None,
        )

    @staticmethod
    def _get_image(ld_obj):
        """Extract image URL from a JSON-LD object."""
        img = ld_obj.get('image', '')
        if isinstance(img, list):
            return img[0] if img else ''
        return img or ''

    @staticmethod
    def _get_offer_url(ld_obj):
        """Extract URL from offers in JSON-LD."""
        offers = ld_obj.get('offers', {})
        if isinstance(offers, list):
            return offers[0].get('url', '') if offers else ''
        return offers.get('url', '')

    @staticmethod
    def _parse_availability(ld_obj):
        """Parse schema.org availability to boolean."""
        offers = ld_obj.get('offers', {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        avail = offers.get('availability', '')
        if 'InStock' in avail:
            return True
        if 'OutOfStock' in avail:
            return False
        return None

    @staticmethod
    def _extract_price_from_offers(ld_obj):
        """Extract numeric price from JSON-LD offers if present."""
        offers = ld_obj.get('offers', {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = offers.get('price')
        if price is not None:
            try:
                return round(float(price), 2)
            except (ValueError, TypeError):
                pass
        return None

    def _extract_ht_price(self, response):
        """Extract HT (hors taxes) price from page text.

        Looks specifically for patterns like '12,50 € H.T.' or '12.50 EUR HT'
        to avoid grabbing TTC prices or unrelated numbers.
        """
        all_text = ' '.join(response.css('::text').getall())

        # Pattern 1: "XX,XX € H.T." or "XX,XX€ HT"
        ht_match = re.search(
            r'(\d+(?:[.,]\d+)?)\s*€\s*H\.?T\.?', all_text
        )
        if ht_match:
            return float(ht_match.group(1).replace(',', '.'))

        # Pattern 2: "XX,XX EUR HT"
        ht_match = re.search(
            r'(\d+(?:[.,]\d+)?)\s*EUR\s*H\.?T\.?', all_text
        )
        if ht_match:
            return float(ht_match.group(1).replace(',', '.'))

        return None

    def handle_error(self, failure):
        """Log request failures without crashing."""
        self.logger.warning(f"Request failed: {failure.request.url} - {failure.value}")
