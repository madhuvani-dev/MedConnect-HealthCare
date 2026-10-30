import os
import sqlite3
from werkzeug.security import generate_password_hash

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
    Initializes the database schema safely without modifying or overwriting existing data.
    - Applies schema tables and indexes idempotently using CREATE TABLE/INDEX IF NOT EXISTS.
    - Performs safe column migration for sms_enabled on existing users tables.
    - Preserves existing admin account (never overwrites credentials on startup).
    - Bootstraps an initial admin only if the database has zero admin accounts.
    - Does NOT automatically create secondary owner accounts or demo accounts in production.
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        
        # 1. Safe migration: check if 'users' table exists and whether 'sms_enabled' column is present
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(users);")
            columns = [row[1] for row in cursor.fetchall()]
            if 'sms_enabled' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN sms_enabled INTEGER NOT NULL DEFAULT 1 CHECK(sms_enabled IN (0, 1));")
                conn.commit()

        # 2. Apply base schema (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS)
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())
        
        # 3. Admin Account Handling:
        # Check if ANY admin account already exists.
        # If one exists, NEVER update, overwrite, or synchronize its credentials on startup.
        cursor.execute("SELECT id, email FROM users WHERE role = 'admin' LIMIT 1;")
        existing_admin = cursor.fetchone()

        if not existing_admin:
            # Only create a bootstrap admin account if the database contains NO admin user
            admin_email_raw = os.environ.get("ADMIN_EMAIL", "")
            admin_password_raw = os.environ.get("ADMIN_PASSWORD", "")
            admin_email = clean_config_val(admin_email_raw, "ADMIN_EMAIL").lower()
            admin_password = clean_config_val(admin_password_raw, "ADMIN_PASSWORD")

            if admin_email and admin_password:
                password_hash = generate_password_hash(admin_password)
                cursor.execute("""
                    INSERT INTO users (name, email, phone, password_hash, role)
                    VALUES (?, ?, ?, ?, 'admin');
                """, ("System Admin", admin_email, "9876543210", password_hash))
                conn.commit()
            else:
                raise RuntimeError(
                    "No administrator account found in database and ADMIN_EMAIL / ADMIN_PASSWORD "
                    "environment variables are not configured. Please configure ADMIN_EMAIL and ADMIN_PASSWORD "
                    "to bootstrap the initial admin account."
                )
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    print("[DB] Database initialized successfully.")
