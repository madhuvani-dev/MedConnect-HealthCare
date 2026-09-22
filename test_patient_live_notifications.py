import io
import os
import sys
import unittest

os.environ['MEDCONNECT_DB_PATH'] = os.path.join(os.path.dirname(__file__), 'medconnect_test.db')

from app import app
from db import get_db, init_db
from werkzeug.security import generate_password_hash

class TestPatientLiveNotifications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = app.test_client()
        self.conn = get_db()
        self.cursor = self.conn.cursor()

        # Clean tables
        self.cursor.execute("DELETE FROM sms_notifications;")
        self.cursor.execute("DELETE FROM notifications;")
        self.cursor.execute("DELETE FROM responses;")
        self.cursor.execute("DELETE FROM requests;")
        self.cursor.execute("DELETE FROM pharmacies;")
        self.cursor.execute("DELETE FROM users;")
        self.conn.commit()

        # Create Patient 1
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Alice Patient', 'alice@test.com', '9876543210', ?, 'patient', 12.9716, 77.5946);
        """, (generate_password_hash('pass123'),))
        self.patient_id = self.cursor.lastrowid

        # Create Patient 2 (Other Patient)
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Bob Patient', 'bob@test.com', '9876543299', ?, 'patient', 12.9750, 77.5980);
        """, (generate_password_hash('pass123'),))
        self.other_patient_id = self.cursor.lastrowid

        # Create Pharmacy User & Store
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES ('City Pharmacy User', 'citypharm@test.com', '9876543220', ?, 'pharmacy');
        """, (generate_password_hash('pass123'),))
        self.pharm_user_id = self.cursor.lastrowid

        self.cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, 'City Pharmacy', 'Dr. Ramesh', 'DL-TEST-999', 'MG Road', 12.9720, 77.5950, 'approved');
        """, (self.pharm_user_id,))
        self.pharmacy_id = self.cursor.lastrowid

        # Create Medicine Request for Patient 1
        self.cursor.execute("""
            INSERT INTO requests (patient_id, request_type, medicine_name, patient_lat, patient_lng, search_radius_km, status)
            VALUES (?, 'medicine_name', 'Paracetamol 650mg', 12.9716, 77.5946, 5.0, 'active');
        """, (self.patient_id,))
        self.request_id = self.cursor.lastrowid
        self.conn.commit()
        self.conn.close()

    def tearDown(self):
        pass

    def test_live_pharmacy_response_and_patient_notification_flow(self):
        """
        Tests the full live flow:
        1. Pharmacy logs in and submits response ('all_available').
        2. Backend creates notification in database with correct recipient user_id.
        3. Patient logs in and calls /api/notifications.
        4. Patient calls /api/notifications/unread-count.
        5. Notification bell and unread count are confirmed.
        6. Patient marks notification as read.
        """
        # Step 1: Pharmacy logs in
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.pharm_user_id
            sess['pharmacy_id'] = self.pharmacy_id
            sess['role'] = 'pharmacy'
            sess['pharmacy_status'] = 'approved'

        # Capture printed safe logs to verify Step 1 logging requirements
        import io
        from contextlib import redirect_stdout
        log_stream = io.StringIO()

        with redirect_stdout(log_stream):
            resp = self.client.post('/api/pharmacy/responses', json={
                'request_id': self.request_id,
                'availability_status': 'all_available',
                'notes': 'Fresh stock arrived today.'
            })

        self.assertEqual(resp.status_code, 200)
        logs = log_stream.getvalue()

        # Verify all required safe logs appear in execution
        self.assertIn("PHARMACY RESPONSE START", logs)
        self.assertIn(f"REQUEST ID: {self.request_id}", logs)
        self.assertIn(f"PATIENT ID: {self.patient_id}", logs)
        self.assertIn("RESPONSE SAVED", logs)
        self.assertIn("NOTIFICATION CREATION START", logs)
        self.assertIn("NOTIFICATION CREATED:", logs)
        self.assertIn("PHARMACY RESPONSE COMPLETE", logs)

        # Step 2: Verify notification in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notifications WHERE user_id = ?;", (self.patient_id,))
        notifs = cursor.fetchall()
        self.assertEqual(len(notifs), 1)

        notif = notifs[0]
        self.assertEqual(notif['user_id'], self.patient_id)
        self.assertEqual(notif['title'], "Medicine Available")
        self.assertEqual(notif['message'], "The pharmacy has responded to your medicine request. The requested medicine is available.")
        self.assertEqual(notif['type'], 'request_response')
        self.assertEqual(notif['related_request_id'], self.request_id)
        self.assertEqual(notif['is_read'], 0)
        conn.close()

        # Step 3: Switch session to Patient 1
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.patient_id
            sess['role'] = 'patient'
            sess['name'] = 'Alice Patient'

        # Step 4: Patient calls /api/notifications
        res_notif = self.client.get('/api/notifications')
        self.assertEqual(res_notif.status_code, 200)
        data_notif = res_notif.get_json()

        self.assertEqual(data_notif['unread_count'], 1)
        self.assertEqual(len(data_notif['notifications']), 1)
        self.assertEqual(data_notif['notifications'][0]['title'], "Medicine Available")
        self.assertEqual(data_notif['notifications'][0]['is_read'], 0)

        # Step 5: Patient calls /api/notifications/unread-count
        res_count = self.client.get('/api/notifications/unread-count')
        self.assertEqual(res_count.status_code, 200)
        data_count = res_count.get_json()
        self.assertEqual(data_count['unread_count'], 1)

        # Step 6: Mark notification as read
        notif_id = notif['id']
        res_read = self.client.post(f'/api/notifications/{notif_id}/read')
        self.assertEqual(res_read.status_code, 200)
        data_read = res_read.get_json()
        self.assertEqual(data_read['unread_count'], 0)

        # Step 7: Check count again
        res_count_after = self.client.get('/api/notifications/unread-count')
        self.assertEqual(res_count_after.get_json()['unread_count'], 0)

        # Step 8: Other patient does NOT see Alice's notifications
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.other_patient_id
            sess['role'] = 'patient'

        other_res = self.client.get('/api/notifications')
        self.assertEqual(other_res.get_json()['unread_count'], 0)
        self.assertEqual(len(other_res.get_json()['notifications']), 0)

    def test_partial_and_unavailable_notification_text(self):
        """
        Tests that partially available and unavailable responses generate the exact required notification text.
        """
        # Create second request
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO requests (patient_id, request_type, medicine_name, patient_lat, patient_lng, search_radius_km, status)
            VALUES (?, 'medicine_name', 'Amoxicillin 500mg', 12.9716, 77.5946, 5.0, 'active');
        """, (self.patient_id,))
        req2_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Pharmacy responds 'some_available'
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.pharm_user_id
            sess['pharmacy_id'] = self.pharmacy_id
            sess['role'] = 'pharmacy'
            sess['pharmacy_status'] = 'approved'

        resp1 = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.request_id,
            'availability_status': 'some_available',
            'notes': 'Strip of 5 available.'
        })
        self.assertEqual(resp1.status_code, 200)

        # Pharmacy responds 'not_available' for req2
        resp2 = self.client.post('/api/pharmacy/responses', json={
            'request_id': req2_id,
            'availability_status': 'not_available',
            'notes': 'Out of stock.'
        })
        self.assertEqual(resp2.status_code, 200)

        # Check Patient notifications
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.patient_id
            sess['role'] = 'patient'

        res = self.client.get('/api/notifications')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['unread_count'], 2)

        titles = [n['title'] for n in data['notifications']]
        self.assertIn("Medicine Partially Available", titles)
        self.assertIn("Medicine Unavailable", titles)

        # Test mark all read
        mark_all = self.client.post('/api/notifications/mark-all-read')
        self.assertEqual(mark_all.status_code, 200)

        res_after = self.client.get('/api/notifications/unread-count')
        self.assertEqual(res_after.get_json()['unread_count'], 0)

if __name__ == '__main__':
    unittest.main()
