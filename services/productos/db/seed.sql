-- Products service seed data (PostgreSQL).
-- SAMPLE DATA: prices, descriptions and capacities are invented examples.
-- Products 19-21 (Smart TV) use a placeholder image to be replaced later by a
-- real photo with the same file name.
-- Idempotent: safe to run more than once, it never deletes rows.
-- Run it inside one transaction (psql --single-transaction), so this file has
-- no BEGIN/COMMIT.

INSERT INTO categories (slug, name) VALUES
    ('accessories',          'Accessories'),
    ('electronics-computer', 'Electronics & Computer'),
    ('laptops-desktops',     'Laptops & Desktops'),
    ('mobiles-tablets',      'Mobiles & Tablets'),
    ('smart-tv',             'Smart TV')
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name
    WHERE categories.name IS DISTINCT FROM EXCLUDED.name;

INSERT INTO products (id, name, description, category_id, price, image_file, image_is_placeholder)
SELECT v.id, v.name, v.description, c.id, v.price, v.image_file, v.is_placeholder
FROM (VALUES
    (1,  'Instant Film Camera',                  'Compact instant camera with built-in flash.',                'electronics-computer',  99.99, 'product-1.png',  FALSE),
    (2,  'Smart Fitness Band',                   'Color-display activity tracker with white silicone strap.',  'accessories',           79.99, 'product-2.png',  FALSE),
    (3,  'Compact Smartphone 4.7"',              'Touchscreen smartphone with a dark metal frame.',            'mobiles-tablets',      299.00, 'product-3.png',  FALSE),
    (4,  'DSLR Camera with 50mm Lens',           'Digital SLR camera body with a fast 50mm lens.',             'electronics-computer', 1299.00, 'product-4.png', FALSE),
    (5,  '24-70mm Zoom Camera Lens',             'Standard zoom lens for DSLR cameras.',                       'electronics-computer', 449.00, 'product-5.png',  FALSE),
    (6,  'Home Security Camera',                 'Compact indoor camera with wide-angle lens.',                'electronics-computer',  39.99, 'product-6.png',  FALSE),
    (7,  'Instant Film Camera Bundle',           'Instant camera with a film pack included.',                  'electronics-computer', 119.00, 'product-7.png',  FALSE),
    (8,  'Wireless Noise-Cancelling Headphones', 'Over-ear black headphones with soft ear cushions.',          'accessories',          249.99, 'product-8.png',  FALSE),
    (9,  'All-in-One Desktop Bundle',            '21.5" all-in-one desktop with wireless keyboard and mouse.', 'laptops-desktops',     1499.00, 'product-9.png', FALSE),
    (10, 'Touchscreen Smartphone 32GB',          'Smartphone with a bright icon-based home screen.',           'mobiles-tablets',      199.00, 'product-10.png', FALSE),
    (11, '14" Laptop',                           'Black laptop with full keyboard and trackpad.',              'laptops-desktops',     549.00, 'product-11.png', FALSE),
    (12, '24" LED Monitor',                      'Desktop monitor with slim bezel and stand.',                 'laptops-desktops',     169.99, 'product-12.png', FALSE),
    (13, 'Smart Fitness Band Lite',              'Lighter version of the activity tracker, white strap.',      'accessories',           59.99, 'product-13.png', FALSE),
    (14, 'Quadcopter Camera Drone',              'Four-rotor drone with a built-in camera.',                   'electronics-computer', 189.00, 'product-14.png', FALSE),
    (15, 'Flagship Smartphone 128GB, Teal',      'Teal smartphone with a triple rear camera.',                 'mobiles-tablets',      749.00, 'product-15.png', FALSE),
    (16, 'Large-Screen Smartphone with Stylus',  '5.7" smartphone with a stylus.',                             'mobiles-tablets',      399.00, 'product-16.png', FALSE),
    (17, 'Smartphone with Silicone Case',        'Black smartphone with a protective silicone case.',          'mobiles-tablets',      129.00, 'product-17.png', FALSE),
    (18, 'Classic Smartphone 16GB',              'Black smartphone with a camera on the back.',                'mobiles-tablets',      149.00, 'product-18.png', FALSE),
    (19, 'Smart TV 01',                          '43" Smart TV.',                                              'smart-tv',             399.00, 'smart-tv-01.png', TRUE),
    (20, 'Smart TV 02',                          '55" Smart TV.',                                              'smart-tv',             599.00, 'smart-tv-02.png', TRUE),
    (21, 'Smart TV 03',                          '65" Smart TV.',                                              'smart-tv',             899.00, 'smart-tv-03.png', TRUE)
) AS v (id, name, description, category_slug, price, image_file, is_placeholder)
JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (id) DO UPDATE
    SET name                 = EXCLUDED.name,
        description          = EXCLUDED.description,
        category_id          = EXCLUDED.category_id,
        price                = EXCLUDED.price,
        image_file           = EXCLUDED.image_file,
        image_is_placeholder = EXCLUDED.image_is_placeholder,
        updated_at           = now()
    WHERE (products.name, products.description, products.category_id, products.price,
           products.image_file, products.image_is_placeholder)
          IS DISTINCT FROM
          (EXCLUDED.name, EXCLUDED.description, EXCLUDED.category_id, EXCLUDED.price,
           EXCLUDED.image_file, EXCLUDED.image_is_placeholder);

-- Fail loudly (and roll back) if a category slug was missing and rows were skipped.
DO $$
BEGIN
    IF (SELECT count(*) FROM products WHERE id BETWEEN 1 AND 21) <> 21 THEN
        RAISE EXCEPTION 'Seed incomplete: expected 21 products with ids 1-21';
    END IF;
END
$$;

-- Keep the identity sequence ahead of the explicit ids used above.
SELECT setval(pg_get_serial_sequence('products', 'id'), (SELECT max(id) FROM products));
