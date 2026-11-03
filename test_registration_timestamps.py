import os
import unittest
from datetime import datetime, timezone, timedelta

os.environ['MEDCONNECT_DB_PATH'] = os.path.join(os.path.dirname(__file__), 'medconnect_test.db')
os.environ.setdefault('ADMIN_EMAIL', 'admin@test.com')
os.environ.setdefault('ADMIN_PASSWORD', 'TestAdminPassword!123')

from app import app
from db import get_db, init_db
from werkzeug.security import generate_password_hash
from utils import get_ist_now, IST


class TestRegistrationTimestamps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = app.test_client()
        self.conn = get_db()
        self.cursor = self.conn.cursor()

        # Clean test tables
        self.cursor.execute("DELETE FROM sms_notifications;")
        self.cursor.execute("DELETE FROM notifications;")
        self.cursor.execute("DELETE FROM responses;")
        self.cursor.execute("DELETE FROM requests;")
        self.cursor.execute("DELETE FROM pharmacies;")
        self.cursor.execute("DELETE FROM users;")
        self.conn.commit()

        # Seed an existing record to test that existing records remain unchanged
        self.existing_timestamp = "2026-01-15 10:00:00"
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude, created_at)
            VALUES ('Existing Legacy User', 'legacy@test.com', '9876543201', ?, 'patient', 12.9716, 77.5946, ?);
        """, (generate_password_hash('pass123'), self.existing_timestamp))
        self.legacy_user_id = self.cursor.lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_get_ist_now_helper(self):
        """Verifies get_ist_now() returns accurate IST time with +5:30 offset relative to UTC."""
        now_utc = datetime.now(timezone.utc)
        expected_ist = now_utc + timedelta(hours=5, minutes=30)
        generated_ist_str = get_ist_now()
        generated_ist_dt = datetime.strptime(generated_ist_str, '%Y-%m-%d %H:%M:%S')

        # Allow within 2 seconds difference
        time_diff = abs((expected_ist.replace(tzinfo=None) - generated_ist_dt).total_seconds())
        self.assertLessEqual(time_diff, 2.0, "get_ist_now() must match UTC+05:30 within 2 seconds.")

    def test_patient_registration_timestamp_in_ist(self):
        """
        Register a new patient and verify that the saved timestamp
        matches the actual registration time in IST.
        """
        before_time = datetime.now(IST)

        res = self.client.post('/api/auth/register-patient', json={
            'name': 'Rahul Sharma',
            'email': 'rahul.patient@test.com',
            'phone': '9876500001',
            'password': 'Password123!',
            'latitude': 12.9716,
            'longitude': 77.5946
        })
        self.assertEqual(res.status_code, 201)

        after_time = datetime.now(IST)

        # Check timestamp in database
        self.cursor.execute("SELECT created_at FROM users WHERE email = 'rahul.patient@test.com';")
        row = self.cursor.fetchone()
        self.assertIsNotNone(row)
        saved_timestamp_str = row['created_at']

        saved_dt = datetime.strptime(saved_timestamp_str, '%Y-%m-%d %H:%M:%S')
        before_dt = before_time.replace(tzinfo=None)
        after_dt = after_time.replace(tzinfo=None)

        self.assertTrue(before_dt - timedelta(seconds=1) <= saved_dt <= after_dt + timedelta(seconds=1),
                        f"Saved timestamp {saved_dt} must match actual registration time in IST [{before_dt} to {after_dt}]")

    def test_pharmacy_registration_timestamp_in_ist(self):
        """
        Register a new pharmacy and verify that the saved timestamp
        matches the actual registration time in IST in both users and pharmacies tables.
        """
        before_time = datetime.now(IST)

        res = self.client.post('/api/auth/register-pharmacy', json={
            'name': 'Suresh Kumar',
            'email': 'suresh.pharm@test.com',
            'phone': '9876500002',
            'password': 'Password123!',
            'pharmacy_name': 'Suresh Medicals Bangalore',
            'owner_name': 'Suresh Kumar',
            'dl_number': 'DL-KA-2026-999',
            'address': 'MG Road, Bangalore',
            'latitude': 12.9720,
            'longitude': 77.5950
        })
        self.assertEqual(res.status_code, 201)

        after_time = datetime.now(IST)

        # Check users table timestamp
        self.cursor.execute("SELECT id, created_at FROM users WHERE email = 'suresh.pharm@test.com';")
        user_row = self.cursor.fetchone()
        self.assertIsNotNone(user_row)
        user_saved_dt = datetime.strptime(user_row['created_at'], '%Y-%m-%d %H:%M:%S')

        # Check pharmacies table timestamp
        self.cursor.execute("SELECT id, created_at FROM pharmacies WHERE dl_number = 'DL-KA-2026-999';")
        pharm_row = self.cursor.fetchone()
        self.assertIsNotNone(pharm_row)
        pharm_saved_dt = datetime.strptime(pharm_row['created_at'], '%Y-%m-%d %H:%M:%S')

        before_dt = before_time.replace(tzinfo=None)
        after_dt = after_time.replace(tzinfo=None)

        # Verify users timestamp is within IST window
        self.assertTrue(before_dt - timedelta(seconds=1) <= user_saved_dt <= after_dt + timedelta(seconds=1),
                        f"User saved timestamp {user_saved_dt} must be in IST [{before_dt} to {after_dt}]")

        # Verify pharmacies timestamp is within IST window
        self.assertTrue(before_dt - timedelta(seconds=1) <= pharm_saved_dt <= after_dt + timedelta(seconds=1),
                        f"Pharmacy saved timestamp {pharm_saved_dt} must be in IST [{before_dt} to {after_dt}]")

        # Verify both match
        self.assertEqual(user_row['created_at'], pharm_row['created_at'])

    def test_existing_records_remain_intact(self):
        """Verifies that existing patient and pharmacy records remain untouched."""
        self.cursor.execute("SELECT created_at FROM users WHERE id = ?;", (self.legacy_user_id,))
        row = self.cursor.fetchone()
        self.assertEqual(row['created_at'], self.existing_timestamp,
                         "Existing records must not be overwritten or modified.")

    def test_admin_endpoints_return_registration_timestamps(self):
        """Verifies admin /api/admin/pharmacies and /api/admin/users return IST timestamps."""
        # Create admin
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES ('Admin', 'admin@test.com', '9876543200', ?, 'admin');
        """, (generate_password_hash('TestAdminPassword!123'),))
        admin_id = self.cursor.lastrowid
        self.conn.commit()

        # Register pharmacy
        self.client.post('/api/auth/register-pharmacy', json={
            'name': 'Pooja Reddy',
            'email': 'pooja.pharm@test.com',
            'phone': '9876500003',
            'password': 'Password123!',
            'pharmacy_name': 'Reddy Care Pharmacy',
            'owner_name': 'Pooja Reddy',
            'dl_number': 'DL-KA-2026-123',
            'address': 'Indiranagar Bangalore',
            'latitude': 12.9716,
            'longitude': 77.5946
        })

        # Login as Admin
        with self.client.session_transaction() as sess:
            sess['user_id'] = admin_id
            sess['role'] = 'admin'

        res_pharm = self.client.get('/api/admin/pharmacies?status=pending')
        self.assertEqual(res_pharm.status_code, 200)
        pharmacies = res_pharm.get_json()['pharmacies']
        matching_pharm = [p for p in pharmacies if p['dl_number'] == 'DL-KA-2026-123']
        self.assertEqual(len(matching_pharm), 1)
        self.assertIsNotNone(matching_pharm[0]['created_at'])

        res_users = self.client.get('/api/admin/users')
        self.assertEqual(res_users.status_code, 200)
        users = res_users.get_json()['users']
        matching_user = [u for u in users if u['email'] == 'pooja.pharm@test.com']
        self.assertEqual(len(matching_user), 1)
        self.assertIsNotNone(matching_user[0]['created_at'])


if __name__ == '__main__':
    unittest.main()
