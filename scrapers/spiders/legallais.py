"""Spider for Legallais - legallais.com

Strategy:
1. Login via Playwright (Cloudflare Turnstile captcha on login page prevents
   simple HTTP POST).  Once logged in, extract the session cookie and inject
   it into Scrapy's cookie jar so that all subsequent requests see prices.
2. Fetch product sitemap XMLs (sitemap.products.1..10.xml) for ~100 000 URLs.
3. Parse each product page using the inline `FROM_TEMPLATE` JS object which
   contains: article codes, brand, prices (priceLevels with base_price,
   net_price, discount), categories, images, stock info.
4. Fallback to DOM parsing (c-price__price, h1, breadcrumb) when
   FROM_TEMPLATE is missing.

Prices require a pro account login (prices are hidden for anonymous users).
Login credentials are passed as spider arguments or read from settings.

Sitemap index: https://www.legallais.com/sitemap.xml
  -> sitemap.products.1.xml .. sitemap.products.10.xml

Sharding: use -a shard=N -a total_shards=M to split the URL list across
parallel spider instances.

Note: Do NOT set TWISTED_REACTOR or DOWNLOAD_HANDLERS in custom_settings.
"""
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class LegallaisSpider(BaseBTPSpider):
    name = 'legallais'
    store_chain = 'legallais'
    allowed_domains = ['legallais.com', 'www.legallais.com']

    # 10 product sitemaps
    SITEMAP_URLS = [
        f'https://www.legallais.com/sitemap.products.{i}.xml'
        for i in range(1, 11)
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
        'ROBOTSTXT_OBEY': False,
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

    # Login credentials (can be overridden via -a email=... -a password=...)
    LOGIN_EMAIL = 'batiprix@outlook.fr'
    LOGIN_PASSWORD = 'BatiPrix!2026#Legallais'
    LOGIN_URL = 'https://www.legallais.com/user/connection'

    # Auth cookie names needed for authenticated session
    AUTH_COOKIE_NAMES = [
        'legallais', 'auth_identifier', 'auth_secret_token', 'auth_machine_token',
    ]

    def __init__(self, shard=None, total_shards=None,
                 email=None, password=None,
                 session_cookie=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shard = int(shard) if shard is not None else None
        self.total_shards = int(total_shards) if total_shards is not None else None
        self.email = email or self.LOGIN_EMAIL
        self.password = password or self.LOGIN_PASSWORD
        # Allow passing a pre-obtained session cookie to skip Playwright login
        # session_cookie can be a single 'legallais' cookie value (basic) or
        # a JSON dict of all auth cookies
        self.auth_cookies = {}
        if session_cookie:
            try:
                self.auth_cookies = json.loads(session_cookie)
            except (json.JSONDecodeError, ValueError):
                # Assume it's just the legallais cookie value
                self.auth_cookies = {'legallais': session_cookie}
        self.logged_in = bool(self.auth_cookies)
        self.seen_urls = set()

    # ------------------------------------------------------------------
    # Login via Playwright (one-time, to bypass Turnstile captcha)
    # ------------------------------------------------------------------

    def start_requests(self):
        """If auth cookies are provided, skip login and go straight to
        sitemap fetching.  Otherwise, attempt login via Playwright."""

        if self.auth_cookies:
            self.logged_in = True
            self.logger.info("Using pre-supplied auth cookies")
            for req in self._sitemap_requests(): yield req
        else:
            # Try Playwright login
            self.logger.info("Attempting Playwright login to obtain session cookie...")
            yield self._playwright_login_request()

    def _playwright_login_request(self):
        """Create a Playwright request to the login page."""
        try:
            from scrapy_playwright.page import PageMethod
        except ImportError:
            self.logger.error(
                "scrapy-playwright is not installed. Either install it or "
                "provide auth cookies via: -a session_cookie=JSON\n"
                "To get cookies manually:\n"
                "  1. Login at https://www.legallais.com/user/connection in your browser\n"
                "  2. Open DevTools > Application > Cookies > www.legallais.com\n"
                "  3. Copy values for: legallais, auth_identifier, auth_secret_token, auth_machine_token\n"
                '  4. Run: scrapy crawl legallais -a session_cookie=\'{"legallais":"VAL","auth_identifier":"VAL","auth_secret_token":"VAL","auth_machine_token":"VAL"}\''
            )
            return scrapy.Request(
                self.LOGIN_URL,
                callback=self._login_fallback,
                dont_filter=True,
            )

        return scrapy.Request(
            self.LOGIN_URL,
            callback=self._handle_playwright_login,
            meta={
                'playwright': True,
                'playwright_include_page': True,
                'playwright_page_methods': [
                    PageMethod('wait_for_load_state', 'networkidle'),
                    PageMethod('wait_for_timeout', 2000),
                ],
            },
            errback=self._login_errback,
            dont_filter=True,
        )

    async def _handle_playwright_login(self, response):
        """Fill login form via Playwright and submit."""
        page = response.meta.get('playwright_page')
        try:
            # Fill email
            await page.fill('#connection-id', self.email)
            await page.fill('#connection-passwd', self.password)

            # Wait for Turnstile to solve (it auto-solves for real browsers)
            await page.wait_for_timeout(3000)

            # Click submit button
            await page.click('form[action*="connection"] button[type="submit"]')

            # Wait for redirect to dashboard
            await page.wait_for_load_state('networkidle')
            await page.wait_for_timeout(2000)

            current_url = page.url
            self.logger.info(f"After login, URL: {current_url}")

            if 'connection' not in current_url:
                # Login successful - extract all auth cookies
                cookies = await page.context.cookies()
                for cookie in cookies:
                    if cookie['name'] in self.AUTH_COOKIE_NAMES:
                        self.auth_cookies[cookie['name']] = cookie['value']

                if 'legallais' in self.auth_cookies:
                    self.logged_in = True
                    self.logger.info(
                        f"Login successful! Got {len(self.auth_cookies)} auth cookies."
                    )
                else:
                    self.logger.warning(
                        "Login seemed successful but no 'legallais' cookie found. "
                        "Proceeding anyway (prices may not be visible)."
                    )
            else:
                self.logger.error(
                    "Login failed - still on connection page. "
                    "Check credentials or provide session_cookie manually."
                )
        finally:
            if page:
                await page.close()

        # Proceed to sitemaps regardless
        for req in self._sitemap_requests():
            yield req

    async def _login_errback(self, failure):
        """Handle Playwright login failure."""
        page = failure.request.meta.get('playwright_page')
        if page:
            await page.close()
        self.logger.error(f"Playwright login failed: {failure.value}")
        self.logger.info("Proceeding without login (prices will be hidden)")
        for req in self._sitemap_requests():
            yield req

    def _login_fallback(self, response):
        """Fallback when Playwright is not available."""
        self.logger.warning(
            "Proceeding without login. Prices will not be visible.\n"
            "To scrape with prices, provide a session cookie:\n"
            "  scrapy crawl legallais -a session_cookie=YOUR_COOKIE_VALUE"
        )
        for req in self._sitemap_requests(): yield req

    # ------------------------------------------------------------------
    # Sitemap fetching
    # ------------------------------------------------------------------

    def _sitemap_requests(self):
        """Yield requests to fetch product sitemap XMLs."""
        for url in self.SITEMAP_URLS:
            yield scrapy.Request(
                url,
                callback=self.parse_sitemap,
                cookies=self.auth_cookies if self.auth_cookies else {},
                dont_filter=True,
            )

    def parse_sitemap(self, response):
        """Parse a sitemap XML and extract product URLs."""
        # Remove XML namespaces for simpler parsing
        body = response.text
        body = re.sub(r'\sxmlns[^"]*"[^"]*"', '', body)

        urls = re.findall(r'<loc>\s*(https?://[^<]+/produit/[^<]+)\s*</loc>', body)

        self.logger.info(
            f"Sitemap {response.url}: found {len(urls)} product URLs"
        )

        # Apply sharding
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
                cookies=self.auth_cookies if self.auth_cookies else {},
                errback=self.handle_error,
            )

    # ------------------------------------------------------------------
    # Product page parsing
    # ------------------------------------------------------------------

    def parse_product(self, response):
        """Parse a product page.

        Primary extraction from FROM_TEMPLATE JS object embedded in inline
        script.  Falls back to DOM parsing for breadcrumbs and price.
        """
        if response.status in (403, 404):
            return

        # --- Extract breadcrumb from JSON-LD ---
        category_path = self._extract_breadcrumb(response)

        # --- Try FROM_TEMPLATE JS extraction (richest data source) ---
        template_data = self._extract_from_template(response)

        if template_data:
            articles = template_data.get('articles', [])
            if articles:
                for article in articles:
                    item = self._parse_article(article, response, category_path)
                    if item:
                        yield item
                return

        # --- Fallback: DOM-based extraction ---
        for req in self._fallback_dom_parse(response, category_path): yield req

    def _extract_from_template(self, response):
        """Extract the FROM_TEMPLATE JS object from inline scripts.

        The object is assigned as: const FROM_TEMPLATE={articles:[...], ...}
        It contains article data with prices, brand, categories, images.
        """
        for script in response.css('script:not([src])::text').getall():
            if 'FROM_TEMPLATE' not in script:
                continue

            # Extract the JSON-like object after FROM_TEMPLATE=
            match = re.search(
                r'FROM_TEMPLATE\s*=\s*(\{.+?\})\s*;?\s*(?:const|var|let|$)',
                script,
                re.DOTALL,
            )
            if not match:
                # Try a simpler pattern - grab until end of script
                match = re.search(
                    r'FROM_TEMPLATE\s*=\s*(\{.+)',
                    script,
                    re.DOTALL,
                )
                if not match:
                    continue
                raw = match.group(1).rstrip().rstrip(';')
            else:
                raw = match.group(1)

            # The JS object uses single quotes and JS booleans (!0, !1)
            # Convert to valid JSON
            try:
                data = self._js_to_json(raw)
                return data
            except (json.JSONDecodeError, ValueError) as e:
                self.logger.debug(
                    f"Failed to parse FROM_TEMPLATE JSON: {e}"
                )
                continue

        return None

    @staticmethod
    def _js_to_json(js_str):
        """Convert a JS object literal to a Python dict.

        Handles: unquoted keys, single quotes, !0/!1 booleans, null,
        trailing commas.
        """
        # Replace JS booleans
        s = js_str.replace('!0', 'true').replace('!1', 'false')
        # Replace single quotes with double quotes
        s = re.sub(r"(?<!\\)'", '"', s)
        # Fix escaped single quotes that are now escaped double quotes
        s = s.replace("\\'", "'")
        # Quote unquoted object keys: {key: -> {"key":
        # Matches word chars at start of key position (after { or ,)
        s = re.sub(
            r'(?<=[{,])\s*([a-zA-Z_]\w*)\s*:',
            r' "\1":',
            s,
        )
        # Remove trailing commas before } or ]
        s = re.sub(r',\s*([}\]])', r'\1', s)
        # Handle undefined -> null
        s = re.sub(r'\bundefined\b', 'null', s)
        return json.loads(s)

    def _parse_article(self, article, response, category_path):
        """Parse a single article dict from FROM_TEMPLATE."""
        reference = article.get('reference') or article.get('code', '')
        if not reference:
            return None

        # Product name
        name = article.get('title', '')
        if not name:
            name = article.get('imageTitle', '')
        if not name:
            return None

        # Brand
        brand = article.get('brandTitle', '')

        # Price - use priceLevels (customer-specific pricing)
        price = None
        price_levels = article.get('priceLevels', [])
        if price_levels:
            # Take first price level (quantity=1)
            level = price_levels[0]
            # net_price is the customer's negotiated price
            price = level.get('net_price') or level.get('base_price')
            if price is not None:
                try:
                    price = round(float(price), 2)
                except (ValueError, TypeError):
                    price = None

        # Fallback to base_price at article level
        if price is None:
            base = article.get('base_price')
            if base is not None:
                try:
                    price = round(float(base), 2)
                except (ValueError, TypeError):
                    pass

        # Image
        image = article.get('imageUrl', '')
        if image and not image.startswith('http'):
            image = response.urljoin(image)

        # Category path from article data
        if not category_path:
            cats = article.get('categories', {})
            cat_parts = []
            for key in ('universe', 'family', 'subFamily'):
                cat_obj = cats.get(key, {})
                if isinstance(cat_obj, dict) and cat_obj.get('title'):
                    cat_parts.append(cat_obj['title'])
            if cat_parts:
                category_path = cat_parts

        # Product URL
        link = article.get('link', '')
        if link:
            product_url = response.urljoin(link)
        else:
            product_url = response.url

        # Description
        description = article.get('description', '')
        if description:
            # Remove HTML tags
            description = re.sub(r'<[^>]+>', ' ', description).strip()
            description = re.sub(r'\s+', ' ', description)
            if len(description) > 500:
                description = description[:500]

        # Manufacturer ref (codeProvider = supplier reference)
        mfr_ref = article.get('codeProvider', '')

        # Stock
        stock_info = article.get('stock', {})
        in_stock = article.get('orderable', False)

        # Old price (base price when there's a discount)
        old_price = None
        if price_levels:
            level = price_levels[0]
            if level.get('showBasePrice') and level.get('showRemise'):
                base_p = level.get('base_price')
                if base_p and price and float(base_p) > price:
                    old_price = round(float(base_p), 2)

        return self.make_item(
            product_name=name,
            product_url=product_url,
            sku=reference,
            manufacturer=brand or None,
            manufacturer_ref=mfr_ref or None,
            price=price,
            old_price=old_price,
            unit_label='HT' if price else None,
            image_url=image or None,
            description=description or None,
            category_path=category_path or None,
            in_stock=in_stock,
        )

    # ------------------------------------------------------------------
    # Breadcrumb extraction from JSON-LD
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_breadcrumb(response):
        """Extract category path from BreadcrumbList JSON-LD."""
        for script in response.css(
            'script[type="application/ld+json"]::text'
        ).getall():
            try:
                data = json.loads(script.rstrip(';'))
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            if data.get('@type') != 'BreadcrumbList':
                continue

            items = data.get('itemListElement', [])
            path = []
            for item in items:
                name = item.get('name', '').strip()
                # Skip "Accueil" (home)
                if name and name.lower() != 'accueil':
                    path.append(name)
            # Remove the last item (it's the product sub-category title,
            # not a real category)
            if len(path) > 1:
                return path[:-1]
            return path

        return []

    # ------------------------------------------------------------------
    # Fallback DOM parsing
    # ------------------------------------------------------------------

    def _fallback_dom_parse(self, response, category_path):
        """Parse product data from DOM when FROM_TEMPLATE is missing."""
        # Product name from h1
        h1 = response.css('h1::text').get('')
        if not h1:
            h1 = ' '.join(response.css('h1 *::text').getall()).strip()
        if not h1:
            return

        # Brand from h1 suffix "- BRANDNAME" or brand link
        brand = ''
        brand_link = response.css('a[href*="/marque/"] img::attr(alt)').get('')
        if brand_link:
            brand = brand_link.strip()
        elif ' - ' in h1:
            parts = h1.rsplit(' - ', 1)
            brand = parts[-1].strip()
            h1 = parts[0].strip()

        # Reference from "Ref. XXXXXX" element
        ref_text = response.css('.c-buy-box *::text').getall()
        ref_text = ' '.join(ref_text)
        ref_match = re.search(r'R[ée]f\.?\s*(\d+)', ref_text)
        sku = ref_match.group(1) if ref_match else ''

        # Price from c-price__price
        price_text = response.css('.c-price--final .c-price__price::text').get('')
        price = self.parse_price(price_text)

        # Image
        image = response.css(
            'a[href*="cdn.legallais.com"] img::attr(src)'
        ).get('')
        if not image:
            image = response.css(
                'img[src*="cdn.legallais.com"]::attr(src)'
            ).get('')

        # Description
        desc_el = response.css('.c-product-description')
        description = ''
        if desc_el:
            description = ' '.join(desc_el.css('::text').getall()).strip()
            description = re.sub(r'\s+', ' ', description)[:500]

        if not h1:
            return

        yield self.make_item(
            product_name=h1,
            product_url=response.url,
            sku=sku or None,
            manufacturer=brand or None,
            price=price,
            unit_label='HT' if price else None,
            image_url=image or None,
            description=description or None,
            category_path=category_path or None,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def handle_error(self, failure):
        """Log request failures without crashing."""
        self.logger.warning(
            f"Request failed: {failure.request.url} - {failure.value}"
        )
