"""Scrapy items for BTP products."""
import scrapy


class BTPProductItem(scrapy.Item):
    """A product scraped from a BTP store website."""
    # Store info
    store_chain = scrapy.Field()      # "leroy_merlin", "castorama"...
    store_name = scrapy.Field()       # specific store name (optional)

    # Product identification
    product_name = scrapy.Field()     # name as shown on site
    product_url = scrapy.Field()      # link to product page
    sku = scrapy.Field()              # store-specific product code
    ean = scrapy.Field()              # EAN-13 barcode
    manufacturer = scrapy.Field()     # brand/manufacturer
    manufacturer_ref = scrapy.Field() # manufacturer reference

    # Price
    price = scrapy.Field()            # current price in EUR
    unit_price = scrapy.Field()       # price per unit (€/m², €/kg...)
    unit_label = scrapy.Field()       # "€/m²", "€/kg", "€/pièce"
    old_price = scrapy.Field()        # original price if on sale

    # Category
    category_path = scrapy.Field()    # ["Outillage", "Outillage électroportatif", "Perceuses"]

    # Details
    description = scrapy.Field()
    image_url = scrapy.Field()
    in_stock = scrapy.Field()         # True/False
    specifications = scrapy.Field()   # dict of technical specs
