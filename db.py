import os
import sqlite3
try:
    from werkzeug.security import generate_password_hash
except ImportError:
    import hashlib
    def generate_password_hash(p):
        return f"sha256${hashlib.sha256(p.encode()).hexdigest()}"

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'medconnect.db')
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.sql')

def get_db():
    """
    Establishes and returns a connection to the SQLite database.
    Row factory is set to sqlite3.Row for dictionary-like column access.
    """
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """
    Initializes the database using schema.sql and creates a default admin
    account if one does not already exist.
    """
    conn = get_db()
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    
    # Check if a default admin exists
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1;")
    admin = cursor.fetchone()
    
    if not admin:
        default_admin_email = "admin@medconnect.local"
        default_admin_password = "admin123"  # Simple development password
        password_hash = generate_password_hash(default_admin_password)
        
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES (?, ?, ?, ?, ?);
        """, ("System Admin", default_admin_email, "9876543210", password_hash, "admin"))
        conn.commit()
        print(f"[DB] Initialized database with default admin: {default_admin_email} (password: {default_admin_password})")
    else:
        conn.commit()
    
    conn.close()

if __name__ == "__main__":
    init_db()
    print("[DB] Database initialized successfully.")
