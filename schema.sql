CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    name TEXT,
    role TEXT DEFAULT 'customer',
    status TEXT DEFAULT 'active',
    phone_number TEXT,
    card_number TEXT,
    language TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    brand TEXT,
    model TEXT,
    year INTEGER,
    plate_number TEXT,
    capacity TEXT,
    price_per_hour REAL,
    specs TEXT,
    status TEXT DEFAULT 'available',
    verification_status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    equipment_id INTEGER,
    owner_id INTEGER,
    location TEXT,
    latitude REAL,
    longitude REAL,
    date_time TEXT,
    duration REAL DEFAULT 0,
    price REAL,
    status TEXT DEFAULT 'searching',
    comment TEXT,
    request_specs TEXT,
    owner_completed INTEGER DEFAULT 0,
    customer_completed INTEGER DEFAULT 0,
    owner_started INTEGER DEFAULT 0,
    customer_started INTEGER DEFAULT 0,
    work_started_at TEXT,
    work_ended_at TEXT,
    payment_method TEXT,
    final_amount REAL,
    commission REAL,
    payment_status TEXT DEFAULT 'unpaid',
    customer_payment_confirmed INTEGER DEFAULT 0,
    customer_payment_admin_confirmed INTEGER DEFAULT 0,
    owner_payment_confirmed INTEGER DEFAULT 0,
    commission_paid INTEGER DEFAULT 0,
    commission_payment_submitted INTEGER DEFAULT 0,
    commission_paid_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    actor_id INTEGER,
    event TEXT,
    old_status TEXT,
    new_status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
