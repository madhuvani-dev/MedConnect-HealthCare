import os
import sys
import unittest

os.environ['MEDCONNECT_DB_PATH'] = os.path.join(os.path.dirname(__file__), 'medconnect_test.db')

from app import app
from db import get_db, init_db
from werkzeug.security import generate_password_hash

class TestPharmacyNotifications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = app.test_client()
        self.conn = get_db()
        self.cursor = self.conn.cursor()
        
        # Clean test tables
        self.cursor.execute("DELETE FROM notifications;")
        self.cursor.execute("DELETE FROM responses;")
        self.cursor.execute("DELETE FROM requests;")
        self.cursor.execute("DELETE FROM pharmacies;")
        self.cursor.execute("DELETE FROM users;")
        self.conn.commit()

        # Seed Patient A (lat: 12.9716, lng: 77.5946 - Bangalore)
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Patient A', 'patienta@test.com', '9876543210', ?, 'patient', 12.9716, 77.5946);
        """, (generate_password_hash('pass123'),))
        self.patient_a_id = self.cursor.lastrowid

        # Seed Patient B (lat: 12.9720, lng: 77.5950)
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Patient B', 'patientb@test.com', '9876543211', ?, 'patient', 12.9720, 77.5950);
        """, (generate_password_hash('pass123'),))
        self.patient_b_id = self.cursor.lastrowid

        # Seed Pharmacy 1 User & Store (approved, 0.5 km away)
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES ('Pharm 1 User', 'pharm1@test.com', '9876543221', ?, 'pharmacy');
        """, (generate_password_hash('pass123'),))
        self.pharm1_user_id = self.cursor.lastrowid

        self.cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, 'Apollo Pharmacy Indiranagar', 'Dr. Ramesh', 'DL-KA-12345', '100 Feet Rd', 12.9720, 77.5980, 'approved');
        """, (self.pharm1_user_id,))
        self.pharm1_id = self.cursor.lastrowid

        # Seed Pharmacy 2 User & Store (approved, 1 km away)
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES ('Pharm 2 User', 'pharm2@test.com', '9876543222', ?, 'pharmacy');
        """, (generate_password_hash('pass123'),))
        self.pharm2_user_id = self.cursor.lastrowid

        self.cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, 'MedPlus Health', 'Dr. Suresh', 'DL-KA-67890', 'CMH Road', 12.9750, 77.6000, 'approved');
        """, (self.pharm2_user_id,))
        self.pharm2_id = self.cursor.lastrowid

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def login(self, email, password='pass123'):
        return self.client.post('/api/auth/login', json={'email': email, 'password': password})

    def test_primary_scenario_available(self):
        """
        Scenario:
        Patient A creates medicine request -> Pharmacy B receives request ->
        Pharmacy B selects "Medicine Available" -> Pharmacy B submits response ->
        Patient A logs in/refreshes -> Patient A sees unread notification with:
        Title: "Medicine Available"
        Message: "The pharmacy has responded to your medicine request. The requested medicine is available."
        """
        # 1. Patient A logs in and submits medicine request
        self.login('patienta@test.com')
        res = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Paracetamol 650mg'
        })
        self.assertEqual(res.status_code, 201)
        req_id = res.get_json()['request']['id']

        # 2. Pharmacy 1 logs in and sees request in feed
        self.login('pharm1@test.com')
        feed_res = self.client.get('/api/pharmacy/feed')
        self.assertEqual(feed_res.status_code, 200)
        feed_data = feed_res.get_json()
        self.assertTrue(any(r['id'] == req_id for r in feed_data['requests']))

        # 3. Pharmacy 1 submits "all_available"
        resp_res = self.client.post('/api/pharmacy/responses', json={
            'request_id': req_id,
            'availability_status': 'all_available',
            'notes': 'Ready for immediate pickup.'
        })
        self.assertEqual(resp_res.status_code, 200)
        self.assertIn('All medicines available', resp_res.get_json()['message'])

        # 4. Patient A logs in and checks notifications
        self.login('patienta@test.com')
        unread_res = self.client.get('/api/notifications/unread-count')
        self.assertEqual(unread_res.status_code, 200)
        self.assertGreaterEqual(unread_res.get_json()['unread_count'], 1)

        notif_res = self.client.get('/api/notifications')
        self.assertEqual(notif_res.status_code, 200)
        notifs = notif_res.get_json()['notifications']
        self.assertGreaterEqual(len(notifs), 1)

        # Check notification content
        matching = [n for n in notifs if n['related_request_id'] == req_id]
        self.assertTrue(len(matching) > 0)
        notif = matching[0]
        self.assertEqual(notif['title'], "Medicine Available")
        self.assertEqual(notif['message'], "The pharmacy has responded to your medicine request. The requested medicine is available.")
        self.assertEqual(notif['is_read'], 0)

    def test_partially_available(self):
        """
        Tests Partially Available title and message:
        Title: "Medicine Partially Available"
        Message: "The pharmacy has responded to your medicine request. Some of the requested medicine is available."
        """
        self.login('patienta@test.com')
        res = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Azithromycin 500mg'
        })
        req_id = res.get_json()['request']['id']

        self.login('pharm1@test.com')
        resp_res = self.client.post('/api/pharmacy/responses', json={
            'request_id': req_id,
            'availability_status': 'some_available',
            'notes': 'Only 3 strips left.'
        })
        self.assertEqual(resp_res.status_code, 200)

        self.login('patienta@test.com')
        notif_res = self.client.get('/api/notifications')
        notifs = notif_res.get_json()['notifications']
        matching = [n for n in notifs if n['related_request_id'] == req_id]
        self.assertTrue(len(matching) > 0)
        notif = matching[0]
        self.assertEqual(notif['title'], "Medicine Partially Available")
        self.assertEqual(notif['message'], "The pharmacy has responded to your medicine request. Some of the requested medicine is available.")

    def test_unavailable(self):
        """
        Tests Unavailable title and message:
        Title: "Medicine Unavailable"
        Message: "The pharmacy has responded to your medicine request. The requested medicine is currently unavailable."
        """
        self.login('patienta@test.com')
        res = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Remdesivir'
        })
        req_id = res.get_json()['request']['id']

        self.login('pharm1@test.com')
        resp_res = self.client.post('/api/pharmacy/responses', json={
            'request_id': req_id,
            'availability_status': 'not_available',
            'notes': 'Out of stock from distributor.'
        })
        self.assertEqual(resp_res.status_code, 200)

        self.login('patienta@test.com')
        notif_res = self.client.get('/api/notifications')
        notifs = notif_res.get_json()['notifications']
        matching = [n for n in notifs if n['related_request_id'] == req_id]
        self.assertTrue(len(matching) > 0)
        notif = matching[0]
        self.assertEqual(notif['title'], "Medicine Unavailable")
        self.assertEqual(notif['message'], "The pharmacy has responded to your medicine request. The requested medicine is currently unavailable.")

    def test_multiple_requests_from_different_patients(self):
        """
        Patient C and Patient D create requests.
        Pharmacy responds to each. Notifications must be isolated to the respective patient.
        """
        # Patient A creates Request 1
        self.login('patienta@test.com')
        res1 = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Metformin 500mg'
        })
        req1_id = res1.get_json()['request']['id']

        # Patient B creates Request 2
        self.login('patientb@test.com')
        res2 = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Atorvastatin 10mg'
        })
        req2_id = res2.get_json()['request']['id']

        # Pharmacy 1 responds to Request 1 (Patient A)
        self.login('pharm1@test.com')
        self.client.post('/api/pharmacy/responses', json={
            'request_id': req1_id,
            'availability_status': 'all_available'
        })

        # Pharmacy 1 responds to Request 2 (Patient B)
        self.client.post('/api/pharmacy/responses', json={
            'request_id': req2_id,
            'availability_status': 'some_available'
        })

        # Verify Patient A only has notification for Request 1
        self.login('patienta@test.com')
        notifs_a = self.client.get('/api/notifications').get_json()['notifications']
        req_ids_a = [n['related_request_id'] for n in notifs_a]
        self.assertIn(req1_id, req_ids_a)
        self.assertNotIn(req2_id, req_ids_a)

        # Verify Patient B only has notification for Request 2
        self.login('patientb@test.com')
        notifs_b = self.client.get('/api/notifications').get_json()['notifications']
        req_ids_b = [n['related_request_id'] for n in notifs_b]
        self.assertIn(req2_id, req_ids_b)
        self.assertNotIn(req1_id, req_ids_b)

    def test_multiple_pharmacies_responding_to_same_request(self):
        """
        Patient A creates request.
        Pharmacy 1 responds Available.
        Pharmacy 2 responds Partially Available.
        Patient A must receive both notifications.
        """
        self.login('patienta@test.com')
        res = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Insulin Glargine'
        })
        req_id = res.get_json()['request']['id']

        # Pharmacy 1 responds Available
        self.login('pharm1@test.com')
        self.client.post('/api/pharmacy/responses', json={
            'request_id': req_id,
            'availability_status': 'all_available'
        })

        # Pharmacy 2 responds Partially Available
        self.login('pharm2@test.com')
        self.client.post('/api/pharmacy/responses', json={
            'request_id': req_id,
            'availability_status': 'some_available'
        })

        # Patient A checks notifications
        self.login('patienta@test.com')
        notif_res = self.client.get('/api/notifications')
        notifs = [n for n in notif_res.get_json()['notifications'] if n['related_request_id'] == req_id]
        self.assertEqual(len(notifs), 2)
        titles = [n['title'] for n in notifs]
        self.assertIn("Medicine Available", titles)
        self.assertIn("Medicine Partially Available", titles)

    def test_alternative_aliases_and_url_routes(self):
        """
        Tests aliases like 'available', 'partially_available', 'unavailable'
        and route '/api/pharmacy/requests/<req_id>/respond'.
        """
        self.login('patienta@test.com')
        res = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Dolo 650'
        })
        req_id = res.get_json()['request_id']

        # Pharmacy responds via alternate route with 'available'
        self.login('pharm1@test.com')
        resp = self.client.post(f'/api/pharmacy/requests/{req_id}/respond', json={
            'availability': 'available',
            'notes': 'All strips available in stock.'
        })
        self.assertEqual(resp.status_code, 200)

        # Patient A verifies
        self.login('patienta@test.com')
        notifs = self.client.get('/api/notifications').get_json()['notifications']
        matching = [n for n in notifs if n['related_request_id'] == req_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['title'], "Medicine Available")
        self.assertEqual(matching[0]['message'], "The pharmacy has responded to your medicine request. The requested medicine is available.")

if __name__ == '__main__':
    unittest.main()
