import os
import unittest
import io
from datetime import datetime, timezone, timedelta

os.environ['MEDCONNECT_DB_PATH'] = os.path.join(os.path.dirname(__file__), 'medconnect_test.db')
os.environ.setdefault('ADMIN_EMAIL', 'admin@test.com')
os.environ.setdefault('ADMIN_PASSWORD', 'TestAdminPassword!123')

from app import app
from db import get_db, init_db
from werkzeug.security import generate_password_hash
from utils import get_ist_now, IST


class TestMedicineRequestTimestamp(unittest.TestCase):
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

        # 1. Create Patient (Bangalore: 12.9716, 77.5946)
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Aarav Patel', 'aarav.patient@test.com', '9876543210', ?, 'patient', 12.9716, 77.5946);
        """, (generate_password_hash('Password123!'),))
        self.patient_id = self.cursor.lastrowid

        # 2. Create Pharmacy User & Approved Pharmacy (0.5 km away: 12.9720, 77.5960)
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Apollo Pharmacist', 'apollo.pharm@test.com', '9876543220', ?, 'pharmacy', 12.9720, 77.5960);
        """, (generate_password_hash('Password123!'),))
        self.pharm_user_id = self.cursor.lastrowid

        self.cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, 'Apollo Pharmacy MG Road', 'Rajesh Sharma', 'DL-KA-2026-001', '12 MG Road', 12.9720, 77.5960, 'approved');
        """, (self.pharm_user_id,))
        self.pharmacy_id = self.cursor.lastrowid

        # 3. Existing Legacy Request to verify existing records remain unchanged
        self.existing_req_timestamp = "2026-01-15 11:30:00"
        self.cursor.execute("""
            INSERT INTO requests (patient_id, request_type, medicine_name, patient_lat, patient_lng, search_radius_km, status, created_at)
            VALUES (?, 'medicine_name', 'Metformin 500mg', 12.9716, 77.5946, 5.0, 'completed', ?);
        """, (self.patient_id, self.existing_req_timestamp))
        self.legacy_request_id = self.cursor.lastrowid

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_new_medicine_request_timestamp_in_ist(self):
        """
        Verify that creating a new medicine request automatically records
        the correct timestamp in Indian Standard Time (IST, UTC+05:30).
        """
        # Login as patient
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.patient_id
            sess['role'] = 'patient'

        before_time = datetime.now(IST)

        res = self.client.post('/api/patient/requests', data={
            'request_type': 'medicine_name',
            'medicine_name': 'Paracetamol 650mg'
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        new_req_id = data['request_id']

        after_time = datetime.now(IST)

        # Check database timestamp
        self.cursor.execute("SELECT created_at FROM requests WHERE id = ?;", (new_req_id,))
        row = self.cursor.fetchone()
        self.assertIsNotNone(row)
        saved_ts_str = row['created_at']

        # Parse saved timestamp
        saved_dt = datetime.strptime(saved_ts_str, '%Y-%m-%d %H:%M:%S')
        before_dt = before_time.replace(tzinfo=None)
        after_dt = after_time.replace(tzinfo=None)

        # Must match actual creation time in IST (within +/- 2 seconds)
        self.assertTrue(
            before_dt - timedelta(seconds=2) <= saved_dt <= after_dt + timedelta(seconds=2),
            f"Saved request timestamp {saved_dt} must match actual creation time in IST [{before_dt} to {after_dt}]"
        )

        # Confirm difference from UTC is approximately +5 hours 30 minutes
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        time_diff = saved_dt - utc_now
        # Difference should be ~5.5 hours (+/- 10 seconds)
        expected_seconds = 5.5 * 3600
        self.assertAlmostEqual(time_diff.total_seconds(), expected_seconds, delta=10,
                               msg=f"Request timestamp must be in IST (+05:30 ahead of UTC), diff was {time_diff.total_seconds()}s")

    def test_new_prescription_request_timestamp_in_ist(self):
        """
        Verify that creating a prescription request also receives the correct IST timestamp.
        """
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.patient_id
            sess['role'] = 'patient'

        before_time = datetime.now(IST)

        data = {
            'request_type': 'prescription',
            'prescription_file': (io.BytesIO(b"%PDF-1.4 test prescription data"), 'prescription.pdf')
        }
        res = self.client.post('/api/patient/requests', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 201)
        new_req_id = res.get_json()['request_id']

        after_time = datetime.now(IST)

        self.cursor.execute("SELECT created_at FROM requests WHERE id = ?;", (new_req_id,))
        row = self.cursor.fetchone()
        self.assertIsNotNone(row)
        saved_dt = datetime.strptime(row['created_at'], '%Y-%m-%d %H:%M:%S')

        before_dt = before_time.replace(tzinfo=None)
        after_dt = after_time.replace(tzinfo=None)
        self.assertTrue(before_dt - timedelta(seconds=2) <= saved_dt <= after_dt + timedelta(seconds=2))

    def test_patient_and_pharmacy_views_show_identical_correct_timestamp(self):
        """
        Verify that both patient endpoint (/api/patient/requests) and pharmacy feed
        (/api/pharmacy/feed) return the identical, accurate IST timestamp for the request.
        """
        # Create request as patient
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.patient_id
            sess['role'] = 'patient'

        create_res = self.client.post('/api/patient/requests', data={
            'request_type': 'medicine_name',
            'medicine_name': 'Azithromycin 500mg'
        })
        self.assertEqual(create_res.status_code, 201)
        req_id = create_res.get_json()['request_id']

        # Patient views requests
        patient_res = self.client.get('/api/patient/requests')
        self.assertEqual(patient_res.status_code, 200)
        patient_requests = patient_res.get_json()['requests']
        patient_req = next((r for r in patient_requests if r['id'] == req_id), None)
        self.assertIsNotNone(patient_req)
        patient_timestamp = patient_req['created_at']

        # Pharmacy views incoming feed
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.pharm_user_id
            sess['role'] = 'pharmacy'
            sess['pharmacy_id'] = self.pharmacy_id
            sess['pharmacy_status'] = 'approved'

        pharm_res = self.client.get('/api/pharmacy/feed')
        self.assertEqual(pharm_res.status_code, 200)
        pharm_requests = pharm_res.get_json()['requests']
        pharm_req = next((r for r in pharm_requests if r['id'] == req_id), None)
        self.assertIsNotNone(pharm_req)
        pharm_timestamp = pharm_req['created_at']

        # Verify both views return the exact same IST timestamp
        self.assertEqual(patient_timestamp, pharm_timestamp,
                         "Patient and Pharmacy must view the exact same timestamp string")

        # Verify it conforms to IST format YYYY-MM-DD HH:MM:SS
        parsed = datetime.strptime(patient_timestamp, '%Y-%m-%d %H:%M:%S')
        self.assertIsNotNone(parsed)

    def test_existing_requests_remain_unchanged(self):
        """
        Verify that existing legacy requests and their timestamps remain intact.
        """
        self.cursor.execute("SELECT created_at, status FROM requests WHERE id = ?;", (self.legacy_request_id,))
        row = self.cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['created_at'], self.existing_req_timestamp,
                         "Existing requests must not be modified or overwritten")
        self.assertEqual(row['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
