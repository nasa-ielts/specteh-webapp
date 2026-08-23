import aiosqlite, json
from pathlib import Path
DB_PATH = Path(__file__).parent / "spectech.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL, name TEXT,
            role TEXT DEFAULT 'customer', language TEXT DEFAULT NULL,
            status TEXT DEFAULT 'active', phone_number TEXT DEFAULT NULL,
            card_number TEXT DEFAULT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS equipment(
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL,
            category TEXT NOT NULL, brand TEXT, plate_number TEXT, year INTEGER,
            capacity TEXT, price_per_hour REAL, specs TEXT,
            status TEXT DEFAULT 'available', verification_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL,
            category TEXT NOT NULL, equipment_id INTEGER, owner_id INTEGER,
            location TEXT NOT NULL, latitude REAL, longitude REAL,
            date_time TEXT NOT NULL, duration REAL NOT NULL, price REAL,
            status TEXT DEFAULT 'searching', comment TEXT, request_specs TEXT,
            owner_completed INTEGER DEFAULT 0, customer_completed INTEGER DEFAULT 0,
            owner_started INTEGER DEFAULT 0, customer_started INTEGER DEFAULT 0,
            work_started_at TEXT, work_ended_at TEXT,
            payment_method TEXT, final_amount REAL, commission REAL,
            payment_status TEXT DEFAULT 'unpaid', customer_payment_confirmed INTEGER DEFAULT 0,
            owner_payment_confirmed INTEGER DEFAULT 0, commission_paid INTEGER DEFAULT 0,
            commission_payment_submitted INTEGER DEFAULT 0, commission_paid_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS order_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, actor_id INTEGER,
            event TEXT NOT NULL, old_status TEXT, new_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        """)
        await migrate(db)
        await db.commit()

async def migrate(db):
    migrations=[
        ("orders","latitude","REAL"),("orders","longitude","REAL"),
        ("orders","owner_completed","INTEGER DEFAULT 0"),("orders","customer_completed","INTEGER DEFAULT 0"),
        ("orders","owner_started","INTEGER DEFAULT 0"),("orders","customer_started","INTEGER DEFAULT 0"),
        ("orders","work_started_at","TEXT"),("orders","work_ended_at","TEXT"),
        ("orders","payment_method","TEXT"),("orders","final_amount","REAL"),
        ("orders","commission","REAL"),("orders","payment_status","TEXT DEFAULT 'unpaid'"),
        ("orders","customer_payment_confirmed","INTEGER DEFAULT 0"),("orders","owner_payment_confirmed","INTEGER DEFAULT 0"),
        ("orders","commission_paid","INTEGER DEFAULT 0"),("orders","customer_payment_admin_confirmed","INTEGER DEFAULT 0"),("orders","commission_payment_submitted","INTEGER DEFAULT 0"),
        ("orders","commission_paid_at","TEXT")]
    for table,col,typ in migrations:
        cur=await db.execute(f"PRAGMA table_info({table})")
        cols={r[1] for r in await cur.fetchall()}
        if col not in cols: await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    for table,col,typ in [
        ("users","language","TEXT DEFAULT NULL"),("users","phone_number","TEXT DEFAULT NULL"),
        ("users","card_number","TEXT DEFAULT NULL") ,("equipment","specs","TEXT"),("orders","request_specs","TEXT")]:
        cur=await db.execute(f"PRAGMA table_info({table})")
        cols={r[1] for r in await cur.fetchall()}
        if col not in cols: await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

async def create_user(telegram_id,name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users(telegram_id,name) VALUES(?,?) ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name",(telegram_id,name)); await db.commit()
async def get_user(telegram_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM users WHERE telegram_id=?",(telegram_id,)); return await cur.fetchone()
async def set_phone(telegram_id, phone_number):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET phone_number=? WHERE telegram_id=?", (phone_number, telegram_id)); await db.commit()
async def set_card_number(telegram_id, card_number):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET card_number=? WHERE telegram_id=?", (card_number, telegram_id)); await db.commit()
async def get_owner_card(owner_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT card_number FROM users WHERE telegram_id=?", (owner_id,)); row=await cur.fetchone(); return row[0] if row else None
async def owner_has_unpaid_commission(owner_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT 1 FROM orders WHERE owner_id=? AND commission>0 AND commission_paid=0 AND status='completed' LIMIT 1", (owner_id,)); return await cur.fetchone() is not None
async def get_unpaid_commissions(owner_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row
        q="SELECT * FROM orders WHERE commission>0 AND commission_paid=0 AND status='completed'"
        args=()
        if owner_id is not None:q+=" AND owner_id=?";args=(owner_id,)
        q+=" ORDER BY id"
        cur=await db.execute(q,args); return await cur.fetchall()
async def mark_customer_payment(order_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE id=?", (order_id,)); o=await cur.fetchone()
        if not o or o["payment_status"] not in ("unpaid","customer_confirmed"): return None
        await db.execute("UPDATE orders SET customer_payment_confirmed=1,payment_status='customer_confirmed' WHERE id=?", (order_id,))
        await db.execute("INSERT INTO order_events(order_id,actor_id,event,old_status,new_status) VALUES(?,?,?,?,?)", (order_id,o["customer_id"],"customer_payment_confirmed",o["payment_status"],"customer_confirmed")); await db.commit(); return True
async def admin_confirm_customer_payment(order_id, approved):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE id=?",(order_id,)); o=await cur.fetchone()
        if not o or not o["customer_payment_confirmed"]: return None
        status="paid_verified" if approved else "unpaid"
        await db.execute("UPDATE orders SET customer_payment_admin_confirmed=? ,payment_status=? WHERE id=?",(1 if approved else 0,status,order_id))
        await db.execute("INSERT INTO order_events(order_id,actor_id,event,old_status,new_status) VALUES(?,?,?,?,?)",(order_id,0,"admin_payment_"+("approved" if approved else "rejected"),o["payment_status"],status)); await db.commit(); return True
async def mark_owner_payment_received(order_id, owner_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE id=?", (order_id,)); o=await cur.fetchone()
        if not o or o["owner_id"]!=owner_id or not o["customer_payment_confirmed"] or not o["customer_payment_admin_confirmed"]: return None
        await db.execute("UPDATE orders SET owner_payment_confirmed=1,payment_status='paid_confirmed' WHERE id=?", (order_id,))
        await db.execute("INSERT INTO order_events(order_id,actor_id,event,old_status,new_status) VALUES(?,?,?,?,?)", (order_id,owner_id,"owner_payment_received",o["payment_status"],"paid_confirmed")); await db.commit(); return True
async def submit_commission_payment(order_id, owner_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE id=?", (order_id,)); o=await cur.fetchone()
        if not o or o["owner_id"]!=owner_id or o["payment_status"]!="paid_confirmed" or o["commission_paid"]: return None
        await db.execute("UPDATE orders SET commission_payment_submitted=1 WHERE id=?",(order_id,))
        await db.execute("INSERT INTO order_events(order_id,actor_id,event,old_status,new_status) VALUES(?,?,?,?,?)",(order_id,owner_id,"commission_payment_submitted","paid_confirmed","commission_pending_admin")); await db.commit(); return True
async def mark_commission_paid(order_id, owner_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE id=?", (order_id,)); o=await cur.fetchone()
        if not o or not o["commission_payment_submitted"] or o["commission_paid"]: return None
        if owner_id is not None and o["owner_id"]!=owner_id:return None
        from datetime import datetime, timezone
        ts=datetime.now(timezone.utc).isoformat()
        await db.execute("UPDATE orders SET commission_paid=1,commission_paid_at=?,commission_payment_submitted=0 WHERE id=?", (ts,order_id))
        await db.execute("INSERT INTO order_events(order_id,actor_id,event,old_status,new_status) VALUES(?,?,?,?,?)", (order_id,owner_id or 0,"commission_paid","commission_pending_admin","commission_paid")); await db.commit(); return True
async def set_language(telegram_id,language):
    async with aiosqlite.connect(DB_PATH) as db: await db.execute("UPDATE users SET language=? WHERE telegram_id=?",(language,telegram_id)); await db.commit()
async def set_role(telegram_id,role):
    async with aiosqlite.connect(DB_PATH) as db: await db.execute("UPDATE users SET role=? WHERE telegram_id=?",(role,telegram_id)); await db.commit()
async def get_admin_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT telegram_id FROM users WHERE role='admin'"); return {r[0] for r in await cur.fetchall()}
async def create_order(customer_id,category,location,lat,lon,date_time,duration,comment,request_specs,payment_method="card"):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("INSERT INTO orders(customer_id,category,location,latitude,longitude,date_time,duration,comment,request_specs,payment_method) VALUES(?,?,?,?,?,?,?,?,?,?)",(customer_id,category,location,lat,lon,date_time,duration,comment,json.dumps(request_specs,ensure_ascii=False),payment_method)); oid=cur.lastrowid
        await db.execute("INSERT INTO order_events(order_id,actor_id,event,old_status,new_status) VALUES(?,?,?,?,?)",(oid,customer_id,"created",None,"searching")); await db.commit(); return oid
async def get_order(order_id):
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE id=?",(order_id,)); return await cur.fetchone()
async def get_customer_orders(customer_id):
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE customer_id=? ORDER BY id DESC",(customer_id,)); return await cur.fetchall()
async def get_owner_orders(owner_id):
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE owner_id=? ORDER BY id DESC",(owner_id,)); return await cur.fetchall()
async def add_equipment(owner_id,category,brand,plate,year,capacity,price,specs):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("INSERT INTO equipment(owner_id,category,brand,plate_number,year,capacity,price_per_hour,specs) VALUES(?,?,?,?,?,?,?,?)",(owner_id,category,brand,plate,year,capacity,price,specs)); await db.commit(); return cur.lastrowid
async def get_owner_equipment(owner_id):
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM equipment WHERE owner_id=? ORDER BY id DESC",(owner_id,)); return await cur.fetchall()
async def get_equipment(equipment_id):
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM equipment WHERE id=?",(equipment_id,)); return await cur.fetchone()
async def get_pending_equipment():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row
        cur=await db.execute("SELECT e.*,u.name owner_name,u.telegram_id owner_telegram_id,u.phone_number owner_phone FROM equipment e LEFT JOIN users u ON u.telegram_id=e.owner_id WHERE e.verification_status='pending' ORDER BY e.id")
        return await cur.fetchall()
async def verify_equipment(equipment_id,approved):
    async with aiosqlite.connect(DB_PATH) as db: await db.execute("UPDATE equipment SET verification_status=?,status=? WHERE id=?",("approved" if approved else "rejected","available" if approved else "frozen",equipment_id)); await db.commit()
async def get_available_equipment(category):
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM equipment WHERE category=? AND status='available' AND verification_status='approved'",(category,)); return await cur.fetchall()
async def set_equipment_status(equipment_id,status):
    async with aiosqlite.connect(DB_PATH) as db: await db.execute("UPDATE equipment SET status=? WHERE id=?",(status,equipment_id)); await db.commit()
async def delete_equipment(equipment_id):
    async with aiosqlite.connect(DB_PATH) as db: await db.execute("DELETE FROM equipment WHERE id=?",(equipment_id,)); await db.commit()
async def owner_has_order_on_date(owner_id,date_value):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT id FROM orders WHERE owner_id=? AND substr(date_time,1,10)=? AND status IN ('active','awaiting_confirmation','searching') LIMIT 1",(owner_id,date_value)); return await cur.fetchone() is not None
async def accept_order(order_id,owner_id,equipment_id,price):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE id=?",(order_id,)); row=await cur.fetchone()
        if not row or row["status"]!="searching":return False
        order_date=str(row["date_time"])[:10]
        cur=await db.execute("SELECT id FROM orders WHERE owner_id=? AND substr(date_time,1,10)=? AND status IN ('active','awaiting_confirmation','searching') LIMIT 1",(owner_id,order_date))
        if await cur.fetchone():return False
        cur=await db.execute("UPDATE orders SET status='active',owner_id=?,equipment_id=?,price=? WHERE id=? AND status='searching'",(owner_id,equipment_id,price,order_id))
        if cur.rowcount!=1:await db.rollback();return False
        await db.execute("INSERT INTO order_events(order_id,actor_id,event,old_status,new_status) VALUES(?,?,?,?,?)",(order_id,owner_id,"accepted","searching","active"));await db.commit();return True
async def mark_started(order_id,actor,role):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM orders WHERE id=?",(order_id,));o=await cur.fetchone()
        if not o or o["status"]!="active":return None
        col="owner_started" if role=="owner" else "customer_started";await db.execute(f"UPDATE orders SET {col}=1 WHERE id=?",(order_id,))
        cur=await db.execute("SELECT owner_started,customer_started,work_started_at FROM orders WHERE id=?",(order_id,));r=await cur.fetchone();started=False;started_at=r[2]
        if r[0] and r[1] and not r[2]:
            from datetime import datetime,timezone
            started_at=datetime.now(timezone.utc).isoformat();await db.execute("UPDATE orders SET work_started_at=?,status='in_progress' WHERE id=?",(started_at,order_id));started=True
        await db.execute("INSERT INTO order_events(order_id,actor_id,event,old_status,new_status) VALUES(?,?,?,?,?)",(order_id,actor,"start_confirmation",o["status"],"in_progress" if started else o["status"]));await db.commit();return {"started":started,"owner_started":bool(r[0]),"customer_started":bool(r[1]),"work_started_at":started_at}
async def mark_completed(order_id,actor,role):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row;cur=await db.execute("SELECT * FROM orders WHERE id=?",(order_id,));o=await cur.fetchone()
        if not o or o["status"] not in ("in_progress","awaiting_completion"):return None
        col="owner_completed" if role=="owner" else "customer_completed";await db.execute(f"UPDATE orders SET {col}=1 WHERE id=?",(order_id,))
        cur=await db.execute("SELECT owner_completed,customer_completed,equipment_id,work_started_at FROM orders WHERE id=?",(order_id,));r=await cur.fetchone();completed=bool(r[0] and r[1]);
        if completed:
            from datetime import datetime,timezone
            ended_at=datetime.now(timezone.utc).isoformat();await db.execute("UPDATE orders SET status='completed',work_ended_at=? WHERE id=?",(ended_at,order_id));
            if r[2]:await db.execute("UPDATE equipment SET status='available' WHERE id=?",(r[2],));new_status="completed"
        else:new_status="awaiting_completion"
        await db.execute("INSERT INTO order_events(order_id,actor_id,event,old_status,new_status) VALUES(?,?,?,?,?)",(order_id,actor,"completion_confirmation",o["status"],new_status));await db.commit();return {"completed":completed,"owner_completed":bool(r[0]),"customer_completed":bool(r[1]),"equipment_id":r[2],"work_started_at":r[3]}
async def set_payment_and_amount(order_id,payment_method,final_amount,commission):
    async with aiosqlite.connect(DB_PATH) as db: await db.execute("UPDATE orders SET payment_method=?,final_amount=?,commission=? WHERE id=?",(payment_method,final_amount,commission,order_id));await db.commit()
async def get_active_order_for_owner(owner_id):
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row;cur=await db.execute("SELECT * FROM orders WHERE owner_id=? AND status IN ('active','in_progress','awaiting_completion') LIMIT 1",(owner_id,));return await cur.fetchone()
async def get_all_orders():
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row;cur=await db.execute("SELECT * FROM orders ORDER BY id DESC");return await cur.fetchall()
async def get_active_orders():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row
        cur=await db.execute("""SELECT o.*,cu.name customer_name,cu.phone_number customer_phone,ou.name owner_name,ou.phone_number owner_phone,e.brand,e.plate_number,e.year
        FROM orders o LEFT JOIN users cu ON cu.telegram_id=o.customer_id LEFT JOIN users ou ON ou.telegram_id=o.owner_id LEFT JOIN equipment e ON e.id=o.equipment_id
        WHERE o.status IN ('active','in_progress','awaiting_completion') ORDER BY o.id DESC""")
        return await cur.fetchall()
async def get_searching_orders(category):
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row;cur=await db.execute("SELECT * FROM orders WHERE category=? AND status='searching' ORDER BY id",(category,));return await cur.fetchall()
async def get_verified_equipment():
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row;cur=await db.execute("SELECT e.*,u.name owner_name,u.telegram_id owner_telegram_id,u.phone_number owner_phone FROM equipment e LEFT JOIN users u ON u.telegram_id=e.owner_id WHERE e.verification_status='approved' ORDER BY e.id DESC");return await cur.fetchall()
async def get_pending_customer_payments():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row
        cur=await db.execute("SELECT o.*,cu.name customer_name,cu.phone_number customer_phone,ou.name owner_name,ou.phone_number owner_phone FROM orders o LEFT JOIN users cu ON cu.telegram_id=o.customer_id LEFT JOIN users ou ON ou.telegram_id=o.owner_id WHERE o.customer_payment_confirmed=1 AND o.customer_payment_admin_confirmed=0 AND o.status='completed' ORDER BY o.id DESC")
        return await cur.fetchall()
async def get_pending_commission_payments():
    async with aiosqlite.connect(DB_PATH) as db: db.row_factory=aiosqlite.Row;cur=await db.execute("SELECT o.*,u.name owner_name,u.telegram_id owner_telegram_id,u.phone_number owner_phone FROM orders o LEFT JOIN users u ON u.telegram_id=o.owner_id WHERE o.commission_payment_submitted=1 AND o.commission_paid=0 ORDER BY o.id DESC");return await cur.fetchall()
async def get_order_details_for_web(order_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row;cur=await db.execute("SELECT o.*, cu.name customer_name,cu.phone_number customer_phone, ou.name owner_name,ou.phone_number owner_phone,e.brand,e.plate_number,e.year,e.price_per_hour FROM orders o LEFT JOIN users cu ON cu.telegram_id=o.customer_id LEFT JOIN users ou ON ou.telegram_id=o.owner_id LEFT JOIN equipment e ON e.id=o.equipment_id WHERE o.id=?",(order_id,));return await cur.fetchone()
