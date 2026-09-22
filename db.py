import os
import sqlite3
try:
    from werkzeug.security import generate_password_hash
except ImportError:
    import hashlib
    def generate_password_hash(p):
        return f"sha256${hashlib.sha256(p.encode()).hexdigest()}"

from utils import clean_config_val

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'medconnect.db')
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.sql')

def get_db_path():
    """
    Returns the database file path, allowing override via MEDCONNECT_DB_PATH (e.g. during testing).
    """
    return os.environ.get('MEDCONNECT_DB_PATH', DATABASE_PATH)

def get_db():
    """
    Establishes and returns a connection to the SQLite database.
    Row factory is set to sqlite3.Row for dictionary-like column access.
    """
    conn = sqlite3.connect(get_db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def init_db():
    """
    Initializes the database using schema.sql and creates a default admin
    account and demo accounts if configured.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Safe migration: add sms_enabled column to users if table already existed
    try:
        cursor.execute("SELECT sms_enabled FROM users LIMIT 1;")
    except sqlite3.OperationalError:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN sms_enabled INTEGER NOT NULL DEFAULT 1 CHECK(sms_enabled IN (0, 1));")
            conn.commit()
        except Exception:
            pass

    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    
    # Check if an admin exists or is configured in environment
    admin_email_raw = os.environ.get("ADMIN_EMAIL", "")
    admin_password_raw = os.environ.get("ADMIN_PASSWORD", "")
    admin_email = clean_config_val(admin_email_raw, "ADMIN_EMAIL").lower()
    admin_password = clean_config_val(admin_password_raw, "ADMIN_PASSWORD")

    cursor.execute("SELECT id, email FROM users WHERE role = 'admin' LIMIT 1;")
    admin = cursor.fetchone()

    if admin_email and admin_password:
        password_hash = generate_password_hash(admin_password)
        if not admin:
            cursor.execute("""
                INSERT INTO users (name, email, phone, password_hash, role)
                VALUES (?, ?, ?, ?, 'admin');
            """, ("System Admin", admin_email, "9876543210", password_hash))
            conn.commit()
        else:
            # Synchronize admin account credentials
            cursor.execute("""
                UPDATE users SET email = ?, password_hash = ? WHERE id = ?;
            """, (admin_email, password_hash, admin['id']))
            conn.commit()
    elif not admin:
        # Fallback default admin if no custom environment credentials provided
        default_admin_email = "admin@medconnect.local"
        default_admin_pass = "Admin@1234"
        password_hash = generate_password_hash(default_admin_pass)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES (?, ?, ?, ?, 'admin');
        """, ("System Admin", default_admin_email, "9876543210", password_hash))
        conn.commit()

    # Ensure owner user email has admin access with the admin password
    owner_email = "siliveruvishnuteja21@gmail.com"
    cursor.execute("SELECT id FROM users WHERE email = ?;", (owner_email,))
    if not cursor.fetchone():
        owner_pass = admin_password or "medconnectadmin2026"
        owner_hash = generate_password_hash(owner_pass)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES (?, ?, ?, ?, 'admin');
        """, ("System Admin (Owner)", owner_email, "9876543210", owner_hash))
        conn.commit()

    # Ensure demo Patient and Pharmacy exist for effortless testing
    cursor.execute("SELECT id FROM users WHERE email = 'aarav@test.com';")
    if not cursor.fetchone():
        demo_patient_hash = generate_password_hash("Password123!")
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude, sms_enabled)
            VALUES ('Aarav Sharma', 'aarav@test.com', '9876543210', ?, 'patient', 12.9716, 77.5946, 1);
        """, (demo_patient_hash,))
        conn.commit()

    cursor.execute("SELECT id FROM users WHERE email = 'medplus@test.com';")
    medplus_user = cursor.fetchone()
    if not medplus_user:
        demo_pharmacy_hash = generate_password_hash("Password123!")
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude, sms_enabled)
            VALUES ('MedPlus Pharmacy Manager', 'medplus@test.com', '9876543220', ?, 'pharmacy', 12.9725, 77.5955, 1);
        """, (demo_pharmacy_hash,))
        medplus_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, 'MedPlus Pharmacy MG Road', 'Rajesh K', 'DL-KA-001', '12 MG Road, Bangalore', 12.9725, 77.5955, 'approved');
        """, (medplus_id,))
        conn.commit()

    conn.close()

if __name__ == "__main__":
    init_db()
    print("[DB] Database initialized successfully.")
