"""Migrate SQLite data to Neon PostgreSQL.

Usage:
    python db/migrate_to_neon.py <neon_connection_string>

Example:
    python db/migrate_to_neon.py "postgresql://user:pass@host.neon.tech/neondb?sslmode=require"
"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    os.system(f'"{sys.executable}" -m pip install psycopg2-binary')
    import psycopg2


SQLITE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'btp_comparateur.db')


def create_schema(pg_conn):
    """Create PostgreSQL schema."""
    cur = pg_conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stores (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        chain VARCHAR(50) NOT NULL,
        address TEXT,
        city VARCHAR(50),
        postal_code VARCHAR(10),
        lat NUMERIC(9,6),
        lng NUMERIC(9,6),
        website VARCHAR(255)
    );

    CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        slug VARCHAR(100) NOT NULL,
        parent_id INTEGER REFERENCES categories(id)
    );

    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        canonical_name VARCHAR(255),
        slug VARCHAR(255) UNIQUE,
        ean VARCHAR(13),
        brand VARCHAR(100),
        manufacturer VARCHAR(100),
        manufacturer_ref VARCHAR(50),
        category_id INTEGER REFERENCES categories(id),
        unit VARCHAR(20),
        description TEXT,
        image_url TEXT,
        min_price NUMERIC(10,2),
        max_price NUMERIC(10,2),
        listing_count INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_products_slug ON products(slug);
    CREATE INDEX IF NOT EXISTS idx_products_ean ON products(ean);
    CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);

    CREATE TABLE IF NOT EXISTS store_listings (
        id SERIAL PRIMARY KEY,
        store_id INTEGER NOT NULL REFERENCES stores(id),
        product_id INTEGER REFERENCES products(id),
        store_product_name VARCHAR(255) NOT NULL,
        store_product_url TEXT,
        store_sku VARCHAR(50),
        store_ean VARCHAR(13),
        store_manufacturer_ref VARCHAR(50),
        current_price NUMERIC(10,2),
        old_price NUMERIC(10,2),
        unit_price NUMERIC(10,2),
        unit_label VARCHAR(20),
        in_stock BOOLEAN DEFAULT TRUE,
        category_path TEXT,
        image_url TEXT,
        last_scraped_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(store_id, store_sku)
    );
    CREATE INDEX IF NOT EXISTS idx_listings_product ON store_listings(product_id);
    CREATE INDEX IF NOT EXISTS idx_listings_store ON store_listings(store_id);

    CREATE TABLE IF NOT EXISTS price_history (
        id SERIAL PRIMARY KEY,
        listing_id INTEGER NOT NULL REFERENCES store_listings(id),
        price NUMERIC(10,2) NOT NULL,
        scraped_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id);

    CREATE TABLE IF NOT EXISTS scrape_runs (
        id SERIAL PRIMARY KEY,
        started_at TIMESTAMP,
        finished_at TIMESTAMP,
        spider_name VARCHAR(50),
        items_scraped INTEGER DEFAULT 0,
        items_new INTEGER DEFAULT 0,
        items_updated INTEGER DEFAULT 0,
        errors INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'running'
    );
    """)
    pg_conn.commit()
    print("Schema created.")


def migrate_table(sqlite_conn, pg_conn, table, columns, has_id=True):
    """Migrate a single table."""
    cur_s = sqlite_conn.cursor()
    cur_p = pg_conn.cursor()

    cols = ', '.join(columns)
    placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])

    cur_s.execute(f"SELECT {cols} FROM {table}")
    rows = cur_s.fetchall()

    if not rows:
        print(f"  {table}: 0 rows (empty)")
        return

    # Use %s for psycopg2
    ph = ', '.join(['%s'] * len(columns))
    insert_sql = f"INSERT INTO {table} ({cols}) VALUES ({ph}) ON CONFLICT DO NOTHING"

    for row in rows:
        # Convert None values and fix encoding
        cleaned = []
        for i_col, val in enumerate(row):
            if isinstance(val, bytes):
                val = val.decode('utf-8', errors='replace')
            # SQLite stores booleans as integers, cast for PostgreSQL
            if i_col < len(columns) and columns[i_col] == 'in_stock' and isinstance(val, int):
                val = bool(val)
            cleaned.append(val)
        try:
            cur_p.execute(insert_sql, cleaned)
        except Exception as e:
            print(f"  Warning: {e}")
            pg_conn.rollback()
            continue

    pg_conn.commit()

    # Reset sequence if table has serial ID
    if has_id and 'id' in columns:
        cur_p.execute(f"SELECT MAX(id) FROM {table}")
        max_id = cur_p.fetchone()[0]
        if max_id:
            cur_p.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), {max_id})")
            pg_conn.commit()

    print(f"  {table}: {len(rows)} rows migrated")


def main():
    if len(sys.argv) < 2:
        print("Usage: python db/migrate_to_neon.py <neon_connection_string>")
        print('Example: python db/migrate_to_neon.py "postgresql://user:pass@host.neon.tech/neondb?sslmode=require"')
        sys.exit(1)

    neon_url = sys.argv[1]

    print(f"SQLite: {SQLITE_PATH}")
    print(f"Neon: {neon_url[:50]}...")

    # Connect
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = psycopg2.connect(neon_url)

    # Create schema
    print("\nCreating PostgreSQL schema...")
    create_schema(pg_conn)

    # Migrate tables in order (respecting foreign keys)
    print("\nMigrating data...")

    migrate_table(sqlite_conn, pg_conn, 'stores',
        ['id', 'name', 'chain', 'address', 'city', 'postal_code', 'lat', 'lng', 'website'])

    migrate_table(sqlite_conn, pg_conn, 'categories',
        ['id', 'name', 'slug', 'parent_id'])

    migrate_table(sqlite_conn, pg_conn, 'products',
        ['id', 'name', 'canonical_name', 'slug', 'ean', 'brand', 'manufacturer',
         'manufacturer_ref', 'category_id', 'unit', 'description', 'image_url',
         'min_price', 'max_price', 'listing_count', 'updated_at'])

    migrate_table(sqlite_conn, pg_conn, 'store_listings',
        ['id', 'store_id', 'product_id', 'store_product_name', 'store_product_url',
         'store_sku', 'store_ean', 'store_manufacturer_ref', 'current_price',
         'old_price', 'unit_price', 'unit_label', 'in_stock', 'category_path',
         'image_url', 'last_scraped_at'])

    migrate_table(sqlite_conn, pg_conn, 'price_history',
        ['id', 'listing_id', 'price', 'scraped_at'])

    # Verify
    print("\nVerifying...")
    cur = pg_conn.cursor()
    for table in ['stores', 'categories', 'products', 'store_listings', 'price_history']:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {cur.fetchone()[0]} rows")

    sqlite_conn.close()
    pg_conn.close()
    print("\nMigration complete!")


if __name__ == '__main__':
    main()
