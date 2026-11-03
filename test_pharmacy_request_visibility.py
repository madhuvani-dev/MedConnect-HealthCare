import os
import unittest

os.environ['MEDCONNECT_DB_PATH'] = os.path.join(os.path.dirname(__file__), 'medconnect_test.db')
os.environ.setdefault('ADMIN_EMAIL', 'admin@test.com')
os.environ.setdefault('ADMIN_PASSWORD', 'TestAdminPassword!123')

from app import app
from db import get_db, init_db
from werkzeug.security import generate_password_hash


class TestPharmacyRequestVisibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = app.test_client()
        self.conn = get_db()
        self.cursor = self.conn.cursor()

        # Clean tables for isolated testing
        self.cursor.execute("DELETE FROM sms_notifications;")
        self.cursor.execute("DELETE FROM notifications;")
        self.cursor.execute("DELETE FROM responses;")
        self.cursor.execute("DELETE FROM requests;")
        self.cursor.execute("DELETE FROM pharmacies;")
        self.cursor.execute("DELETE FROM users;")
        self.conn.commit()

        # 1. Create System Admin
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES ('Admin User', 'admin@test.com', '9876543200', ?, 'admin');
        """, (generate_password_hash('TestAdminPassword!123'),))
        self.admin_id = self.cursor.lastrowid

        # 2. Create Existing Patient A (Bangalore center: 12.9716, 77.5946)
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Patient A', 'patienta@test.com', '9876543210', ?, 'patient', 12.9716, 77.5946);
        """, (generate_password_hash('pass123'),))
        self.patient_a_id = self.cursor.lastrowid

        # 3. Create Existing Approved Pharmacy (0.3 km away: 12.9720, 77.5970)
        self.cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES ('Existing Pharm User', 'existing_pharm@test.com', '9876543220', ?, 'pharmacy', 12.9720, 77.5970);
        """, (generate_password_hash('pass123'),))
        self.existing_pharm_user_id = self.cursor.lastrowid

        self.cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, 'Existing Pharmacy Indiranagar', 'Dr. Ramesh', 'DL-EXISTING-01', '100 Feet Road', 12.9720, 77.5970, 'approved');
        """, (self.existing_pharm_user_id,))
        self.existing_pharm_id = self.cursor.lastrowid

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def login_user(self, email, password='pass123'):
        return self.client.post('/api/auth/login', json={'email': email, 'password': password})

    def test_scenario_1_request_created_before_pharmacy_registers(self):
        """
        Scenario 1:
        A medicine request is created before a new pharmacy registers.
        After registration and login, the pharmacy can see that pending request.
        """
        # Step 1: Patient A logs in and creates a medicine request
        self.login_user('patienta@test.com')
        res_req = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Paracetamol 650mg'
        })
        self.assertEqual(res_req.status_code, 201)
        req_id = res_req.get_json()['request']['id']

        # Step 2: New pharmacy registers (coordinates: 12.9725, 77.5955, ~0.14 km away)
        res_reg = self.client.post('/api/auth/register-pharmacy', json={
            'name': 'New Pharmacist Bob',
            'email': 'newpharm@test.com',
            'phone': '9876543300',
            'password': 'Password123!',
            'pharmacy_name': 'New Horizon Pharmacy',
            'owner_name': 'Bob Smith',
            'dl_number': 'DL-NEW-777',
            'address': 'MG Road Metro Station',
            'latitude': 12.9725,
            'longitude': 77.5955
        })
        self.assertEqual(res_reg.status_code, 201)

        # Retrieve new pharmacy ID
        self.cursor.execute("SELECT id FROM pharmacies WHERE dl_number = 'DL-NEW-777';")
        new_pharm_row = self.cursor.fetchone()
        new_pharm_id = new_pharm_row['id']

        # Admin approves the new pharmacy
        self.login_user('admin@test.com', 'TestAdminPassword!123')
        res_approve = self.client.post(f'/api/admin/pharmacies/{new_pharm_id}/approve')
        self.assertEqual(res_approve.status_code, 200)

        # Step 3: New pharmacy logs in and accesses its feed
        res_login = self.login_user('newpharm@test.com', 'Password123!')
        self.assertEqual(res_login.status_code, 200)

        res_feed = self.client.get('/api/pharmacy/feed')
        self.assertEqual(res_feed.status_code, 200)
        feed_data = res_feed.get_json()

        requests_list = feed_data.get('requests', [])
        # The new pharmacy MUST see the older pending request
        matching = [r for r in requests_list if r['id'] == req_id]
        self.assertEqual(len(matching), 1, "New pharmacy must see pending request created before its registration.")
        self.assertEqual(matching[0]['medicine_name'], 'Paracetamol 650mg')
        self.assertFalse(matching[0]['has_responded'])

    def test_scenario_2_request_created_after_pharmacy_registers(self):
        """
        Scenario 2:
        A medicine request is created after the pharmacy registers.
        The pharmacy can see that request too.
        """
        # Step 1: New pharmacy registers and is approved
        res_reg = self.client.post('/api/auth/register-pharmacy', json={
            'name': 'Pharmacist Clara',
            'email': 'clara@test.com',
            'phone': '9876543301',
            'password': 'Password123!',
            'pharmacy_name': 'Clara Care Pharmacy',
            'owner_name': 'Clara Oswald',
            'dl_number': 'DL-NEW-888',
            'address': 'Brigade Road',
            'latitude': 12.9730,
            'longitude': 77.5960
        })
        self.assertEqual(res_reg.status_code, 201)

        self.cursor.execute("SELECT id FROM pharmacies WHERE dl_number = 'DL-NEW-888';")
        pharm_id = self.cursor.fetchone()['id']

        self.login_user('admin@test.com', 'TestAdminPassword!123')
        self.client.post(f'/api/admin/pharmacies/{pharm_id}/approve')

        # Step 2: Patient A creates a medicine request AFTER pharmacy registered
        self.login_user('patienta@test.com')
        res_req = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Amoxicillin 500mg'
        })
        self.assertEqual(res_req.status_code, 201)
        req_id = res_req.get_json()['request']['id']

        # Step 3: Pharmacy logs in and checks feed
        self.login_user('clara@test.com', 'Password123!')
        res_feed = self.client.get('/api/pharmacy/feed')
        self.assertEqual(res_feed.status_code, 200)

        requests_list = res_feed.get_json().get('requests', [])
        matching = [r for r in requests_list if r['id'] == req_id]
        self.assertEqual(len(matching), 1, "Pharmacy must see request created after registration.")
        self.assertEqual(matching[0]['medicine_name'], 'Amoxicillin 500mg')

    def test_scenario_3_existing_pharmacy_can_view_and_respond(self):
        """
        Scenario 3:
        Existing pharmacies can still view and respond to their relevant pending requests.
        """
        # Patient A creates a request
        self.login_user('patienta@test.com')
        res_req = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Metformin 500mg'
        })
        req_id = res_req.get_json()['request']['id']

        # Existing pharmacy logs in and checks feed
        self.login_user('existing_pharm@test.com')
        res_feed = self.client.get('/api/pharmacy/feed')
        self.assertEqual(res_feed.status_code, 200)
        requests_list = res_feed.get_json().get('requests', [])
        self.assertTrue(any(r['id'] == req_id for r in requests_list))

        # Existing pharmacy responds
        res_resp = self.client.post('/api/pharmacy/responses', json={
            'request_id': req_id,
            'availability_status': 'all_available',
            'notes': 'In stock in aisle 3.'
        })
        self.assertEqual(res_resp.status_code, 200)

        # Feed reflects responded state
        res_feed2 = self.client.get('/api/pharmacy/feed')
        req_item = next(r for r in res_feed2.get_json()['requests'] if r['id'] == req_id)
        self.assertTrue(req_item['has_responded'])
        self.assertEqual(req_item['my_response']['availability_status'], 'all_available')

    def test_scenario_4_closed_requests_not_in_pending_feed(self):
        """
        Scenario 4:
        Once a request is no longer pending (e.g. marked completed or cancelled),
        it follows the existing workflow and is not incorrectly displayed as a new pending request.
        """
        # Patient A creates request
        self.login_user('patienta@test.com')
        res_req = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Azithromycin 250mg'
        })
        req_id = res_req.get_json()['request']['id']

        # Verify it appears initially
        self.login_user('existing_pharm@test.com')
        res_feed = self.client.get('/api/pharmacy/feed')
        self.assertTrue(any(r['id'] == req_id for r in res_feed.get_json()['requests']))

        # Patient closes/completes the request
        self.login_user('patienta@test.com')
        res_close = self.client.post(f'/api/patient/requests/{req_id}/close', json={'status': 'completed'})
        self.assertEqual(res_close.status_code, 200)

        # Pharmacy checks feed: completed request must NOT be shown as pending
        self.login_user('existing_pharm@test.com')
        res_feed_after = self.client.get('/api/pharmacy/feed')
        self.assertFalse(any(r['id'] == req_id for r in res_feed_after.get_json()['requests']),
                         "Closed request must not appear in active pending feed.")

    def test_scenario_5_distance_filtering_maintained(self):
        """
        Scenario 5:
        Verify distance radius filtering is strictly maintained:
        Requests outside the patient's radius must not be visible to distant pharmacies.
        """
        # Patient creates request at Bangalore (12.9716, 77.5946) with 5km radius
        self.login_user('patienta@test.com')
        res_req = self.client.post('/api/patient/requests', json={
            'request_type': 'medicine_name',
            'medicine_name': 'Insulin Glargine'
        })
        req_id = res_req.get_json()['request']['id']

        # Register distant pharmacy (Mysore: 12.2958, 76.6394, ~130 km away)
        res_reg = self.client.post('/api/auth/register-pharmacy', json={
            'name': 'Distant Pharmacist',
            'email': 'distant@test.com',
            'phone': '9876543399',
            'password': 'Password123!',
            'pharmacy_name': 'Distant Mysore Pharmacy',
            'owner_name': 'Distant Owner',
            'dl_number': 'DL-DISTANT-999',
            'address': 'Palace Road Mysore',
            'latitude': 12.2958,
            'longitude': 76.6394
        })
        self.assertEqual(res_reg.status_code, 201)

        self.cursor.execute("SELECT id FROM pharmacies WHERE dl_number = 'DL-DISTANT-999';")
        distant_id = self.cursor.fetchone()['id']

        self.login_user('admin@test.com', 'TestAdminPassword!123')
        self.client.post(f'/api/admin/pharmacies/{distant_id}/approve')

        # Distant pharmacy logs in: request must NOT be in feed (beyond 5 km)
        self.login_user('distant@test.com', 'Password123!')
        res_feed = self.client.get('/api/pharmacy/feed')
        self.assertEqual(res_feed.status_code, 200)
        self.assertFalse(any(r['id'] == req_id for r in res_feed.get_json()['requests']),
                         "Distant pharmacy beyond search radius must not see request.")


if __name__ == '__main__':
    unittest.main()
