"""SQLAlchemy models for BTP price comparator."""
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, UniqueConstraint, Text, Numeric
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

Base = declarative_base()


class Store(Base):
    __tablename__ = 'stores'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    chain = Column(String(50), nullable=False)  # "leroy_merlin", "castorama"...
    address = Column(Text)
    city = Column(String(50))
    postal_code = Column(String(10))
    lat = Column(Numeric(9, 6))
    lng = Column(Numeric(9, 6))
    website = Column(String(255))

    listings = relationship('StoreListing', back_populates='store')

    def __repr__(self):
        return f"<Store {self.chain} - {self.name} ({self.city})>"


class Category(Base):
    __tablename__ = 'categories'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey('categories.id'), nullable=True)

    parent = relationship('Category', remote_side=[id], backref='children')
    products = relationship('Product', back_populates='category')

    def __repr__(self):
        return f"<Category {self.name}>"


class Product(Base):
    __tablename__ = 'products'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    canonical_name = Column(String(255))  # normalized name for matching
    slug = Column(String(255), index=True, unique=True)
    ean = Column(String(13), index=True)  # barcode
    brand = Column(String(100))  # extracted brand name
    manufacturer = Column(String(100))
    manufacturer_ref = Column(String(50))
    category_id = Column(Integer, ForeignKey('categories.id'))
    unit = Column(String(20))  # "piece", "m2", "kg", "litre"
    description = Column(Text)
    image_url = Column(Text)
    specifications = Column(Text)  # JSON string of all specs
    volume = Column(String(20))  # "2.5 L", "10 L"
    color = Column(String(50))  # "blanc", "gris anthracite"
    weight = Column(String(20))  # "25 kg"
    dimensions = Column(String(50))  # "300x600mm", "5x60mm"
    pack_size = Column(String(30))  # "lot de 10", "500 pièces"
    finish = Column(String(30))  # "satin", "mat", "brillant"
    min_price = Column(Numeric(10, 2))  # denormalized: cheapest listing
    max_price = Column(Numeric(10, 2))  # denormalized: most expensive listing
    listing_count = Column(Integer, default=0)  # denormalized: number of store listings
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship('Category', back_populates='products')
    listings = relationship('StoreListing', back_populates='product')

    def __repr__(self):
        return f"<Product {self.name} (EAN: {self.ean})>"


class StoreListing(Base):
    __tablename__ = 'store_listings'

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey('stores.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=True)  # nullable until matched
    store_product_name = Column(String(255), nullable=False)
    store_product_url = Column(Text)
    store_sku = Column(String(50))
    store_ean = Column(String(13))  # EAN as found on the store's site
    store_manufacturer_ref = Column(String(50))
    current_price = Column(Numeric(10, 2))
    old_price = Column(Numeric(10, 2))  # previous price (for showing discounts)
    unit_price = Column(Numeric(10, 2))
    unit_label = Column(String(20))  # "€/m²", "€/kg"...
    in_stock = Column(Boolean, default=True)
    category_path = Column(Text)  # raw category path from store
    image_url = Column(Text)
    last_scraped_at = Column(DateTime, default=datetime.utcnow)

    store = relationship('Store', back_populates='listings')
    product = relationship('Product', back_populates='listings')
    price_history = relationship('PriceHistory', back_populates='listing')

    __table_args__ = (
        UniqueConstraint('store_id', 'store_sku', name='uq_store_sku'),
    )

    def __repr__(self):
        return f"<StoreListing {self.store_product_name} @ {self.current_price}€>"


class PriceHistory(Base):
    __tablename__ = 'price_history'

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey('store_listings.id'), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    listing = relationship('StoreListing', back_populates='price_history')


class ScrapeRun(Base):
    __tablename__ = 'scrape_runs'

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    spider_name = Column(String(50))
    items_scraped = Column(Integer, default=0)
    items_new = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    status = Column(String(20), default='running')  # running, success, failed


def get_engine():
    url = os.getenv('DATABASE_URL', 'sqlite:///data/btp_comparateur.db')
    return create_engine(url, echo=False)


def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    print(f"Database initialized: {engine.url}")
    return engine
