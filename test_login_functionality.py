import os
import unittest

os.environ['MEDCONNECT_DB_PATH'] = os.path.join(os.path.dirname(__file__), 'medconnect_test.db')
os.environ.setdefault('ADMIN_EMAIL', 'admin@test.com')
os.environ.setdefault('ADMIN_PASSWORD', 'TestAdminPassword!123')

from app import app
from db import get_db, init_db
from werkzeug.security import generate_password_hash


class TestLoginFunctionality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = app.test_client()
        self.conn = get_db()
        self.cursor = self.conn.cursor()

        # Clean tables for clean test state
        self.cursor.execute("DELETE FROM sms_notifications;")
        self.cursor.execute("DELETE FROM notifications;")
        self.cursor.execute("DELETE FROM responses;")
        self.cursor.execute("DELETE FROM requests;")
        self.cursor.execute("DELETE FROM pharmacies;")
        self.cursor.execute("DELETE FROM users;")
        self.conn.commit()

        # Seed Patient
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Alice Patient', 'alice@test.com', '9876543210', ?, 'patient', 12.9716, 77.5946);
        """, (generate_password_hash('Password123!'),))
        self.patient_id = self.cursor.lastrowid

        # Seed Approved Pharmacy
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Bob Pharmacist', 'bob@test.com', '9876543220', ?, 'pharmacy', 12.9720, 77.5950);
        """, (generate_password_hash('Password123!'),))
        self.pharm_user_id = self.cursor.lastrowid

        self.cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, 'Bob Pharmacy', 'Bob Smith', 'DL-TEST-1234', 'MG Road', 12.9720, 77.5950, 'approved');
        """, (self.pharm_user_id,))
        self.pharmacy_id = self.cursor.lastrowid

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_quick_demo_credentials_removed_from_login_html(self):
        """Verifies that Quick Demo Credentials is removed from both /login and /admin/login."""
        res_login = self.client.get('/login')
        self.assertEqual(res_login.status_code, 200)
        html_login = res_login.get_data(as_text=True)
        self.assertNotIn("Quick Demo Credentials", html_login)
        self.assertNotIn("demo-login-btn", html_login)
        self.assertNotIn("Click to auto-fill", html_login)
        self.assertIn("New to MedConnect?", html_login)
        self.assertIn("Register as Patient", html_login)
        self.assertIn("Register as Pharmacy", html_login)

        res_admin = self.client.get('/admin/login')
        self.assertEqual(res_admin.status_code, 200)
        html_admin = res_admin.get_data(as_text=True)
        self.assertNotIn("Quick Demo Credentials", html_admin)
        self.assertNotIn("demo-login-btn", html_admin)

    def test_registered_patient_can_login(self):
        """Verifies registered patient can log in successfully."""
        res = self.client.post('/api/auth/login', json={
            'email': 'alice@test.com',
            'password': 'Password123!'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['user']['email'], 'alice@test.com')
        self.assertEqual(data['user']['role'], 'patient')
        self.assertEqual(data['redirect'], '/patient/dashboard')

    def test_registered_pharmacy_can_login(self):
        """Verifies registered approved pharmacy can log in successfully."""
        res = self.client.post('/api/auth/login', json={
            'email': 'bob@test.com',
            'password': 'Password123!'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['user']['email'], 'bob@test.com')
        self.assertEqual(data['user']['role'], 'pharmacy')
        self.assertEqual(data['redirect'], '/pharmacy/dashboard')

    def test_invalid_login_credentials(self):
        """Verifies that invalid password displays existing error message."""
        res = self.client.post('/api/auth/login', json={
            'email': 'alice@test.com',
            'password': 'WrongPassword123'
        })
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()['error'], 'Invalid email or password.')

    def test_missing_login_fields(self):
        """Verifies validation for missing email or password."""
        res = self.client.post('/api/auth/login', json={
            'email': '',
            'password': ''
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error'], 'Please provide both email and password.')


if __name__ == '__main__':
    unittest.main()
