import os
import unittest

os.environ['MEDCONNECT_DB_PATH'] = os.path.join(os.path.dirname(__file__), 'medconnect_test.db')

from unittest.mock import patch
from app import app
from db import get_db, init_db
from werkzeug.security import generate_password_hash
from sms_service import (
    normalize_indian_phone,
    mask_phone_number,
    SMSProviderResponse,
    BaseSMSProvider,
    SMS_TEMPLATES
)

class MockSuccessSMSProvider(BaseSMSProvider):
    def __init__(self):
        self.sent_messages = []

    def send(self, to_phone: str, message: str) -> SMSProviderResponse:
        msg_id = f"SM_TEST_{len(self.sent_messages) + 1:04d}"
        self.sent_messages.append({'to': to_phone, 'body': message, 'id': msg_id})
        return SMSProviderResponse(success=True, message_id=msg_id)


class MockFailingSMSProvider(BaseSMSProvider):
    def send(self, to_phone: str, message: str) -> SMSProviderResponse:
        return SMSProviderResponse(success=False, error_message="Mock Gateway 500: Provider service timeout")


class TestSMSNotifications(unittest.TestCase):
    HASHED_PW = None

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.HASHED_PW = generate_password_hash('pass123')

    def setUp(self):
        self.client = app.test_client()
        conn = get_db()
        cursor = conn.cursor()

        # Clean tables
        cursor.execute("DELETE FROM sms_notifications;")
        cursor.execute("DELETE FROM notifications;")
        cursor.execute("DELETE FROM responses;")
        cursor.execute("DELETE FROM requests;")
        cursor.execute("DELETE FROM pharmacies;")
        cursor.execute("DELETE FROM users;")
        conn.commit()

        # Seed Patient 1 (Valid Indian phone: 9876543210)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude, sms_enabled)
            VALUES ('Aarav Sharma', 'aarav@test.com', '9876543210', ?, 'patient', 12.9716, 77.5946, 1);
        """, (self.HASHED_PW,))
        self.patient_1_id = cursor.lastrowid

        # Seed Patient 2 (Different patient, phone: 9123456780)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude, sms_enabled)
            VALUES ('Diya Patel', 'diya@test.com', '9123456780', ?, 'patient', 12.9720, 77.5950, 1);
        """, (self.HASHED_PW,))
        self.patient_2_id = cursor.lastrowid

        # Seed Patient 3 (Invalid / missing phone)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude, sms_enabled)
            VALUES ('NoPhone User', 'nophone@test.com', '', ?, 'patient', 12.9725, 77.5955, 1);
        """, (self.HASHED_PW,))
        self.patient_3_id = cursor.lastrowid

        # Seed Pharmacy 1 User & Store (approved)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES ('MedPlus Staff', 'medplus@test.com', '9876500001', ?, 'pharmacy');
        """, (self.HASHED_PW,))
        self.pharm1_user_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, 'MedPlus Pharmacy MG Road', 'Rajesh K', 'DL-KA-001', 'MG Road', 12.9725, 77.5955, 'approved');
        """, (self.pharm1_user_id,))
        self.pharm1_id = cursor.lastrowid

        # Seed Pharmacy 2 User & Store (approved)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES ('Apollo Staff', 'apollo@test.com', '9876500002', ?, 'pharmacy');
        """, (self.HASHED_PW,))
        self.pharm2_user_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, 'Apollo Pharmacy Brigade', 'Suresh M', 'DL-KA-002', 'Brigade Road', 12.9730, 77.5960, 'approved');
        """, (self.pharm2_user_id,))
        self.pharm2_id = cursor.lastrowid

        # Seed Request 1 (by Patient 1, Active)
        cursor.execute("""
            INSERT INTO requests (patient_id, request_type, medicine_name, patient_lat, patient_lng, search_radius_km, status)
            VALUES (?, 'medicine_name', 'Paracetamol 650mg', 12.9716, 77.5946, 5.0, 'active');
        """, (self.patient_1_id,))
        self.req_1_id = cursor.lastrowid

        # Seed Request 2 (by Patient 2, Active)
        cursor.execute("""
            INSERT INTO requests (patient_id, request_type, medicine_name, patient_lat, patient_lng, search_radius_km, status)
            VALUES (?, 'medicine_name', 'Amoxicillin 500mg', 12.9720, 77.5950, 5.0, 'active');
        """, (self.patient_2_id,))
        self.req_2_id = cursor.lastrowid

        # Seed Request 3 (by Patient 3, Active - No Phone)
        cursor.execute("""
            INSERT INTO requests (patient_id, request_type, medicine_name, patient_lat, patient_lng, search_radius_km, status)
            VALUES (?, 'medicine_name', 'Cetirizine 10mg', 12.9725, 77.5955, 5.0, 'active');
        """, (self.patient_3_id,))
        self.req_3_id = cursor.lastrowid

        conn.commit()
        conn.close()

    def login(self, email, password='pass123'):
        return self.client.post('/api/auth/login', json={'email': email, 'password': password})

    # -------------------------------------------------------------
    # TEST 1: Pharmacy responds "Available"
    # -> In-app notification created -> SMS requested
    # -------------------------------------------------------------
    @patch('sms_service.get_sms_provider')
    def test_1_pharmacy_responds_available(self, mock_get_provider):
        mock_provider = MockSuccessSMSProvider()
        mock_get_provider.return_value = (mock_provider, "mock_success")

        self.login('medplus@test.com')
        res = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'all_available',
            'notes': 'In stock and ready for pickup.'
        })
        self.assertEqual(res.status_code, 200)

        conn = get_db()
        cursor = conn.cursor()

        # Verify in-app notification created
        cursor.execute("""
            SELECT * FROM notifications 
            WHERE user_id = ? AND related_request_id = ?;
        """, (self.patient_1_id, self.req_1_id))
        notif = cursor.fetchone()
        self.assertIsNotNone(notif)
        self.assertEqual(notif['title'], "Medicine Available")
        self.assertIn("The requested medicine is available", notif['message'])

        # Verify SMS record created with 'all_available' template and status 'sent'
        cursor.execute("""
            SELECT * FROM sms_notifications 
            WHERE request_id = ? AND patient_id = ?;
        """, (self.req_1_id, self.patient_1_id))
        sms = cursor.fetchone()
        self.assertIsNotNone(sms)
        self.assertEqual(sms['status'], 'sent')
        self.assertEqual(sms['message_type'], 'all_available')
        self.assertEqual(sms['message_body'], SMS_TEMPLATES['all_available'])
        self.assertTrue(sms['phone_masked'].endswith('3210'))
        self.assertNotIn('9876543210', sms['phone_masked'])

        conn.close()

        # Verify provider actually received the SMS dispatch
        self.assertEqual(len(mock_provider.sent_messages), 1)
        self.assertEqual(mock_provider.sent_messages[0]['to'], '+919876543210')

    # -------------------------------------------------------------
    # TEST 2: Pharmacy responds "Partially Available"
    # -> In-app notification created -> SMS requested
    # -------------------------------------------------------------
    @patch('sms_service.get_sms_provider')
    def test_2_pharmacy_responds_partially_available(self, mock_get_provider):
        mock_provider = MockSuccessSMSProvider()
        mock_get_provider.return_value = (mock_provider, "mock_success")

        self.login('medplus@test.com')
        res = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'some_available',
            'notes': 'Only 1 strip remaining.'
        })
        self.assertEqual(res.status_code, 200)

        conn = get_db()
        cursor = conn.cursor()

        # Verify in-app notification
        cursor.execute("""
            SELECT * FROM notifications 
            WHERE user_id = ? AND related_request_id = ?;
        """, (self.patient_1_id, self.req_1_id))
        notif = cursor.fetchone()
        self.assertIsNotNone(notif)
        self.assertEqual(notif['title'], "Medicine Partially Available")
        self.assertIn("Some of the requested medicine is available", notif['message'])

        # Verify SMS record created with 'some_available' template
        cursor.execute("""
            SELECT * FROM sms_notifications 
            WHERE request_id = ? AND patient_id = ?;
        """, (self.req_1_id, self.patient_1_id))
        sms = cursor.fetchone()
        self.assertIsNotNone(sms)
        self.assertEqual(sms['status'], 'sent')
        self.assertEqual(sms['message_type'], 'some_available')
        self.assertEqual(sms['message_body'], SMS_TEMPLATES['some_available'])

        conn.close()

    # -------------------------------------------------------------
    # TEST 3: Pharmacy responds "Unavailable"
    # -> In-app notification created -> SMS requested
    # -------------------------------------------------------------
    @patch('sms_service.get_sms_provider')
    def test_3_pharmacy_responds_unavailable(self, mock_get_provider):
        mock_provider = MockSuccessSMSProvider()
        mock_get_provider.return_value = (mock_provider, "mock_success")

        self.login('medplus@test.com')
        res = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'not_available',
            'notes': 'Currently out of stock.'
        })
        self.assertEqual(res.status_code, 200)

        conn = get_db()
        cursor = conn.cursor()

        # Verify in-app notification
        cursor.execute("""
            SELECT * FROM notifications 
            WHERE user_id = ? AND related_request_id = ?;
        """, (self.patient_1_id, self.req_1_id))
        notif = cursor.fetchone()
        self.assertIsNotNone(notif)
        self.assertEqual(notif['title'], "Medicine Unavailable")
        self.assertIn("currently unavailable", notif['message'])

        # Verify SMS record created with 'not_available' template
        cursor.execute("""
            SELECT * FROM sms_notifications 
            WHERE request_id = ? AND patient_id = ?;
        """, (self.req_1_id, self.patient_1_id))
        sms = cursor.fetchone()
        self.assertIsNotNone(sms)
        self.assertEqual(sms['status'], 'sent')
        self.assertEqual(sms['message_type'], 'not_available')
        self.assertEqual(sms['message_body'], SMS_TEMPLATES['not_available'])

        conn.close()

    # -------------------------------------------------------------
    # TEST 4: Patient has no valid phone number
    # -> In-app notification works -> SMS skipped safely
    # -------------------------------------------------------------
    @patch('sms_service.get_sms_provider')
    def test_4_patient_no_valid_phone_skips_safely(self, mock_get_provider):
        mock_provider = MockSuccessSMSProvider()
        mock_get_provider.return_value = (mock_provider, "mock_success")

        # Pharmacy responds to Request 3 (Patient 3 has empty phone)
        self.login('medplus@test.com')
        res = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_3_id,
            'availability_status': 'all_available'
        })
        self.assertEqual(res.status_code, 200)

        conn = get_db()
        cursor = conn.cursor()

        # In-app notification MUST be created and working
        cursor.execute("""
            SELECT * FROM notifications 
            WHERE user_id = ? AND related_request_id = ?;
        """, (self.patient_3_id, self.req_3_id))
        notif = cursor.fetchone()
        self.assertIsNotNone(notif)
        self.assertEqual(notif['title'], "Medicine Available")

        # SMS is safely marked failed or skipped, provider NOT called
        cursor.execute("""
            SELECT * FROM sms_notifications 
            WHERE request_id = ? AND patient_id = ?;
        """, (self.req_3_id, self.patient_3_id))
        sms = cursor.fetchone()
        self.assertIsNotNone(sms)
        self.assertEqual(sms['status'], 'failed')
        self.assertIn('phone', sms['error_message'].lower())
        self.assertEqual(len(mock_provider.sent_messages), 0)

        conn.close()

    # -------------------------------------------------------------
    # TEST 5: SMS provider returns an error
    # -> Pharmacy response remains successful (200 OK)
    # -> In-app notification remains available
    # -> SMS status becomes failed
    # -------------------------------------------------------------
    @patch('sms_service.get_sms_provider')
    def test_5_sms_provider_error_resilience(self, mock_get_provider):
        mock_provider = MockFailingSMSProvider()
        mock_get_provider.return_value = (mock_provider, "mock_failing")

        self.login('medplus@test.com')
        res = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'all_available'
        })
        # Crucial requirement: Pharmacy response must STILL succeed (200 OK)
        self.assertEqual(res.status_code, 200)

        conn = get_db()
        cursor = conn.cursor()

        # In-app notification MUST still be created and intact
        cursor.execute("""
            SELECT * FROM notifications 
            WHERE user_id = ? AND related_request_id = ?;
        """, (self.patient_1_id, self.req_1_id))
        notif = cursor.fetchone()
        self.assertIsNotNone(notif)

        # SMS record is marked as failed with the provider error message
        cursor.execute("""
            SELECT * FROM sms_notifications 
            WHERE request_id = ? AND patient_id = ?;
        """, (self.req_1_id, self.patient_1_id))
        sms = cursor.fetchone()
        self.assertIsNotNone(sms)
        self.assertEqual(sms['status'], 'failed')
        self.assertIn('Mock Gateway 500', sms['error_message'])

        conn.close()

    # -------------------------------------------------------------
    # TEST 6: Duplicate pharmacy-response request
    # -> Only one SMS sent for the same response
    # -------------------------------------------------------------
    @patch('sms_service.get_sms_provider')
    def test_6_duplicate_response_idempotency(self, mock_get_provider):
        mock_provider = MockSuccessSMSProvider()
        mock_get_provider.return_value = (mock_provider, "mock_success")

        self.login('medplus@test.com')

        # First response
        res1 = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'all_available'
        })
        self.assertEqual(res1.status_code, 200)

        # Second identical response submitted immediately
        res2 = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'all_available'
        })
        self.assertEqual(res2.status_code, 200)

        # Provider send() was called exactly ONCE
        self.assertEqual(len(mock_provider.sent_messages), 1)

        conn = get_db()
        cursor = conn.cursor()

        # Check records in sms_notifications: exactly 1 'sent', second is 'skipped'
        cursor.execute("""
            SELECT status, count(*) as cnt 
            FROM sms_notifications 
            WHERE request_id = ? AND pharmacy_id = ?
            GROUP BY status;
        """, (self.req_1_id, self.pharm1_id))
        counts = {row['status']: row['cnt'] for row in cursor.fetchall()}
        self.assertEqual(counts.get('sent'), 1)
        self.assertEqual(counts.get('skipped'), 1)

        conn.close()

    # -------------------------------------------------------------
    # TEST 7: Multiple patients
    # -> Each patient receives SMS only for their own request
    # -------------------------------------------------------------
    @patch('sms_service.get_sms_provider')
    def test_7_multiple_patients_isolated(self, mock_get_provider):
        mock_provider = MockSuccessSMSProvider()
        mock_get_provider.return_value = (mock_provider, "mock_success")

        self.login('medplus@test.com')

        # Respond to Patient 1's request (Req 1)
        res_p1 = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'all_available'
        })
        self.assertEqual(res_p1.status_code, 200)

        # Respond to Patient 2's request (Req 2)
        res_p2 = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_2_id,
            'availability_status': 'some_available'
        })
        self.assertEqual(res_p2.status_code, 200)

        conn = get_db()
        cursor = conn.cursor()

        # Verify Patient 1 received only Req 1 SMS
        cursor.execute("""
            SELECT * FROM sms_notifications 
            WHERE patient_id = ?;
        """, (self.patient_1_id,))
        p1_sms = cursor.fetchall()
        self.assertEqual(len(p1_sms), 1)
        self.assertEqual(p1_sms[0]['request_id'], self.req_1_id)
        self.assertEqual(p1_sms[0]['message_type'], 'all_available')

        # Verify Patient 2 received only Req 2 SMS
        cursor.execute("""
            SELECT * FROM sms_notifications 
            WHERE patient_id = ?;
        """, (self.patient_2_id,))
        p2_sms = cursor.fetchall()
        self.assertEqual(len(p2_sms), 1)
        self.assertEqual(p2_sms[0]['request_id'], self.req_2_id)
        self.assertEqual(p2_sms[0]['message_type'], 'some_available')

        conn.close()

    # -------------------------------------------------------------
    # TEST 8: Multiple pharmacies responding to same request
    # -> Each legitimate response generates appropriate notification & SMS
    # -------------------------------------------------------------
    @patch('sms_service.get_sms_provider')
    def test_8_multiple_pharmacies_distinct_sms(self, mock_get_provider):
        mock_provider = MockSuccessSMSProvider()
        mock_get_provider.return_value = (mock_provider, "mock_success")

        # Pharmacy 1 responds "Available"
        self.login('medplus@test.com')
        res_pharm1 = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'all_available'
        })
        self.assertEqual(res_pharm1.status_code, 200)

        # Pharmacy 2 responds "Partially Available"
        self.login('apollo@test.com')
        res_pharm2 = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'some_available'
        })
        self.assertEqual(res_pharm2.status_code, 200)

        conn = get_db()
        cursor = conn.cursor()

        # Both legitimate responses should generate distinct SMS records
        cursor.execute("""
            SELECT pharmacy_id, message_type, status 
            FROM sms_notifications 
            WHERE request_id = ? AND status = 'sent'
            ORDER BY id ASC;
        """, (self.req_1_id,))
        sms_rows = cursor.fetchall()
        self.assertEqual(len(sms_rows), 2)
        self.assertEqual(sms_rows[0]['pharmacy_id'], self.pharm1_id)
        self.assertEqual(sms_rows[0]['message_type'], 'all_available')
        self.assertEqual(sms_rows[1]['pharmacy_id'], self.pharm2_id)
        self.assertEqual(sms_rows[1]['message_type'], 'some_available')

        conn.close()

    # -------------------------------------------------------------
    # TEST 9: Patient opts out of SMS Notifications
    # -> In-app notification created, SMS skipped safely
    # -------------------------------------------------------------
    @patch('sms_service.get_sms_provider')
    def test_9_patient_sms_preference_opt_out(self, mock_get_provider):
        mock_provider = MockSuccessSMSProvider()
        mock_get_provider.return_value = (mock_provider, "mock_success")

        # Patient 1 updates preference to OFF
        self.login('aarav@test.com')
        pref_res = self.client.post('/api/patient/preferences', json={'sms_enabled': False})
        self.assertEqual(pref_res.status_code, 200)
        self.assertFalse(pref_res.get_json()['sms_notifications_enabled'])

        # Pharmacy responds to Request 1
        self.login('medplus@test.com')
        res = self.client.post('/api/pharmacy/responses', json={
            'request_id': self.req_1_id,
            'availability_status': 'all_available'
        })
        self.assertEqual(res.status_code, 200)

        conn = get_db()
        cursor = conn.cursor()

        # In-app notification MUST be created
        cursor.execute("""
            SELECT * FROM notifications 
            WHERE user_id = ? AND related_request_id = ?;
        """, (self.patient_1_id, self.req_1_id))
        self.assertIsNotNone(cursor.fetchone())

        # SMS is recorded as 'skipped' due to patient opt-out
        cursor.execute("""
            SELECT * FROM sms_notifications 
            WHERE request_id = ? AND patient_id = ?;
        """, (self.req_1_id, self.patient_1_id))
        sms = cursor.fetchone()
        self.assertIsNotNone(sms)
        self.assertEqual(sms['status'], 'skipped')
        self.assertIn('opted out', sms['error_message'].lower())
        self.assertEqual(len(mock_provider.sent_messages), 0)

        conn.close()

    # -------------------------------------------------------------
    # TEST 10: Indian Phone Number Normalization & Masking
    # -------------------------------------------------------------
    def test_10_phone_normalization_and_masking(self):
        # 10 digits
        ok, num, _ = normalize_indian_phone("9876543210")
        self.assertTrue(ok)
        self.assertEqual(num, "+919876543210")

        # Leading 0
        ok, num, _ = normalize_indian_phone("09876543210")
        self.assertTrue(ok)
        self.assertEqual(num, "+919876543210")

        # With 91
        ok, num, _ = normalize_indian_phone("919876543210")
        self.assertTrue(ok)
        self.assertEqual(num, "+919876543210")

        # With +91
        ok, num, _ = normalize_indian_phone("+919876543210")
        self.assertTrue(ok)
        self.assertEqual(num, "+919876543210")

        # Invalid formats
        ok, _, err = normalize_indian_phone("12345")
        self.assertFalse(ok)

        ok, _, err = normalize_indian_phone(None)
        self.assertFalse(ok)

        # Privacy Masking
        self.assertEqual(mask_phone_number("+919876543210"), "+91******3210")
        self.assertEqual(mask_phone_number("9876543210"), "******3210")
        self.assertEqual(mask_phone_number(None), "<unavailable>")


if __name__ == '__main__':
    unittest.main()
