"""
MedConnect SMS Notification Service
Handles phone number normalization, provider dispatching, duplicate prevention,
database tracking, and patient preferences.
"""

import os
import re
import json
import base64
import hashlib
import logging
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from db import get_db

logger = logging.getLogger('medconnect.sms')

# Standard MedConnect SMS Notification Templates
SMS_TEMPLATES = {
    'all_available': "MedConnect: Good news! The pharmacy has responded to your medicine request. The requested medicine is available. Please check MedConnect for details.",
    'some_available': "MedConnect: The pharmacy has responded to your medicine request. Some of the requested medicine is available. Please check MedConnect for details.",
    'not_available': "MedConnect: The pharmacy has responded to your medicine request. The requested medicine is currently unavailable. Please check MedConnect for details."
}


def mask_phone_number(phone: str) -> str:
    """
    Masks a phone number for privacy and safe server-side logging.
    Example: '+919876543210' -> '+91******3210', '9876543210' -> '******3210'
    Never outputs the full middle digits.
    """
    if not phone:
        return "<unavailable>"
    clean = str(phone).strip()
    if len(clean) <= 4:
        return "****"
    if clean.startswith('+91') and len(clean) >= 13:
        prefix = "+91"
        visible_tail = clean[-4:]
        masked_middle = "*" * (len(clean) - len(prefix) - len(visible_tail))
        return f"{prefix}{masked_middle}{visible_tail}"
    elif clean.startswith('+') and len(clean) >= 6:
        prefix = clean[:2]
        visible_tail = clean[-4:]
        masked_middle = "*" * (len(clean) - len(prefix) - len(visible_tail))
        return f"{prefix}{masked_middle}{visible_tail}"
    else:
        visible_tail = clean[-4:]
        masked_middle = "*" * (len(clean) - len(visible_tail))
        return f"{masked_middle}{visible_tail}"


def hash_phone_number(phone: str) -> str:
    """
    Returns a SHA-256 hash of the normalized phone number for safe indexing.
    """
    if not phone:
        return ""
    return hashlib.sha256(phone.strip().encode('utf-8')).hexdigest()


def normalize_indian_phone(raw_phone: str):
    """
    Validates and normalizes Indian mobile phone numbers to E.164 (+91XXXXXXXXXX).
    Supports:
      - 10 digits starting with 6, 7, 8, 9 (e.g. '9876543210')
      - With leading 0 (e.g. '09876543210')
      - With '91' country code (e.g. '919876543210')
      - With '+91' country code (e.g. '+919876543210')
      - Common formatting like spaces, dashes, parentheses
    Returns:
      (is_valid: bool, normalized: str or None, reason: str or None)
    """
    if not raw_phone:
        return False, None, "Patient phone number unavailable."

    # Strip whitespace, dashes, parentheses, dots
    cleaned = re.sub(r'[\s\-\(\)\.]', '', str(raw_phone).strip())

    if not cleaned:
        return False, None, "Patient phone number unavailable."

    # If it starts with +91
    if cleaned.startswith('+91'):
        digits = cleaned[3:]
        if len(digits) == 10 and digits[0] in '6789' and digits.isdigit():
            return True, f"+91{digits}", None
        else:
            return False, None, "Invalid Indian mobile number format after +91."

    # If it starts with 91 and has 12 digits
    if cleaned.startswith('91') and len(cleaned) == 12:
        digits = cleaned[2:]
        if digits[0] in '6789' and digits.isdigit():
            return True, f"+91{digits}", None

    # If it starts with 0 and has 11 digits
    if cleaned.startswith('0') and len(cleaned) == 11:
        digits = cleaned[1:]
        if digits[0] in '6789' and digits.isdigit():
            return True, f"+91{digits}", None

    # Standard 10-digit Indian mobile number
    if len(cleaned) == 10 and cleaned[0] in '6789' and cleaned.isdigit():
        return True, f"+91{cleaned}", None

    # Generic E.164 international support (e.g. +14155552671)
    if cleaned.startswith('+') and 10 <= len(cleaned) <= 16 and cleaned[1:].isdigit():
        return True, cleaned, None

    return False, None, "Invalid mobile number. Must be a valid 10-digit mobile number."


class SMSProviderResponse:
    def __init__(self, success: bool, message_id: str = None, error_message: str = None, raw_response: dict = None):
        self.success = success
        self.message_id = message_id
        self.error_message = error_message
        self.raw_response = raw_response or {}


class BaseSMSProvider:
    """Base abstract class for SMS provider integrations."""
    def send(self, to_phone: str, message: str) -> SMSProviderResponse:
        raise NotImplementedError


class TwilioSMSProvider(BaseSMSProvider):
    """
    Twilio REST API Provider
    Requires:
      - SMS_API_KEY: Account SID (AC...)
      - SMS_API_SECRET: Auth Token
      - SMS_SENDER_ID: Twilio Phone Number or Messaging Service SID
    """
    def __init__(self, account_sid: str, auth_token: str, sender_id: str):
        self.account_sid = account_sid.strip()
        self.auth_token = auth_token.strip()
        self.sender_id = sender_id.strip()

    def send(self, to_phone: str, message: str) -> SMSProviderResponse:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        
        post_data = {
            'To': to_phone,
            'From': self.sender_id,
            'Body': message
        }
        encoded_data = urllib.parse.urlencode(post_data).encode('utf-8')

        auth_str = f"{self.account_sid}:{self.auth_token}"
        b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('ascii')

        req = urllib.request.Request(url, data=encoded_data, method='POST')
        req.add_header('Authorization', f"Basic {b64_auth}")
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                sid = res_json.get('sid')
                status = res_json.get('status')
                
                if status in ('queued', 'sending', 'sent', 'delivered'):
                    return SMSProviderResponse(success=True, message_id=sid, raw_response=res_json)
                else:
                    return SMSProviderResponse(success=False, message_id=sid, error_message=f"Twilio status: {status}", raw_response=res_json)

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode('utf-8')
                error_json = json.loads(error_body)
                err_msg = error_json.get('message', f"HTTP Error {e.code}")
            except Exception:
                err_msg = f"Twilio API HTTP Error {e.code}"
            return SMSProviderResponse(success=False, error_message=err_msg)

        except urllib.error.URLError as e:
            return SMSProviderResponse(success=False, error_message=f"Twilio connection error: {str(e.reason)}")
        except Exception as e:
            return SMSProviderResponse(success=False, error_message=f"Twilio client error: {str(e)}")


class Fast2SMSSMSProvider(BaseSMSProvider):
    """
    Fast2SMS Provider for Indian Mobile Numbers
    Requires:
      - SMS_API_KEY: Fast2SMS API Key
      - SMS_SENDER_ID: Sender ID / Route
    """
    def __init__(self, api_key: str, sender_id: str = None):
        self.api_key = api_key.strip()
        self.sender_id = (sender_id or "FSTSMS").strip()

    def send(self, to_phone: str, message: str) -> SMSProviderResponse:
        url = "https://www.fast2sms.com/dev/bulkV2"
        # Fast2SMS expects 10-digit number for Indian recipients
        cleaned_num = to_phone.replace('+91', '').strip()

        payload = {
            "route": "v3",
            "sender_id": self.sender_id,
            "message": message,
            "language": "english",
            "flash": 0,
            "numbers": cleaned_num
        }
        encoded_data = json.dumps(payload).encode('utf-8')

        req = urllib.request.Request(url, data=encoded_data, method='POST')
        req.add_header('authorization', self.api_key)
        req.add_header('Content-Type', 'application/json')

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                if res_json.get('return') is True:
                    request_id = res_json.get('request_id', '')
                    return SMSProviderResponse(success=True, message_id=request_id, raw_response=res_json)
                else:
                    msg = res_json.get('message', ['Fast2SMS error'])
                    err_text = msg[0] if isinstance(msg, list) and msg else str(msg)
                    return SMSProviderResponse(success=False, error_message=err_text, raw_response=res_json)
        except urllib.error.HTTPError as e:
            return SMSProviderResponse(success=False, error_message=f"Fast2SMS HTTP Error {e.code}")
        except Exception as e:
            return SMSProviderResponse(success=False, error_message=f"Fast2SMS error: {str(e)}")


class MSG91SMSProvider(BaseSMSProvider):
    """
    MSG91 SMS Gateway Provider
    Requires:
      - SMS_API_KEY: MSG91 authkey
      - SMS_SENDER_ID: 6-character sender ID
    """
    def __init__(self, auth_key: str, sender_id: str):
        self.auth_key = auth_key.strip()
        self.sender_id = (sender_id or "MEDCON").strip()

    def send(self, to_phone: str, message: str) -> SMSProviderResponse:
        url = "https://control.msg91.com/api/sendhttp.php"
        cleaned_num = to_phone.replace('+', '').strip()
        params = {
            'authkey': self.auth_key,
            'mobiles': cleaned_num,
            'message': message,
            'sender': self.sender_id,
            'route': '4',
            'country': '91'
        }
        encoded_data = urllib.parse.urlencode(params).encode('utf-8')
        req = urllib.request.Request(url, data=encoded_data, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_body = response.read().decode('utf-8').strip()
                # MSG91 returns message ID on success
                if re.match(r'^[a-zA-Z0-9]+$', res_body) and len(res_body) > 10:
                    return SMSProviderResponse(success=True, message_id=res_body)
                else:
                    return SMSProviderResponse(success=False, error_message=f"MSG91 response: {res_body}")
        except Exception as e:
            return SMSProviderResponse(success=False, error_message=f"MSG91 error: {str(e)}")


class UnconfiguredSMSProvider(BaseSMSProvider):
    """
    Fallback provider when SMS credentials are not yet set in environment.
    Fails safely without breaking MedConnect.
    """
    def __init__(self, reason: str = "SMS provider credentials not configured in environment variables."):
        self.reason = reason

    def send(self, to_phone: str, message: str) -> SMSProviderResponse:
        return SMSProviderResponse(success=False, error_message=self.reason)


def get_sms_provider() -> tuple[BaseSMSProvider, str]:
    """
    Initializes and returns the configured SMS provider based on environment variables.
    Returns (provider_instance, provider_name).
    """
    provider_name = os.environ.get('SMS_PROVIDER', '').strip().lower()
    api_key = os.environ.get('SMS_API_KEY', '').strip()
    api_secret = os.environ.get('SMS_API_SECRET', '').strip()
    sender_id = os.environ.get('SMS_SENDER_ID', '').strip()

    # If provider is explicitly specified
    if provider_name == 'twilio':
        if not api_key or not api_secret or not sender_id:
            return UnconfiguredSMSProvider("Twilio requires SMS_API_KEY (Account SID), SMS_API_SECRET (Auth Token), and SMS_SENDER_ID."), "twilio"
        return TwilioSMSProvider(account_sid=api_key, auth_token=api_secret, sender_id=sender_id), "twilio"

    elif provider_name == 'fast2sms':
        if not api_key:
            return UnconfiguredSMSProvider("Fast2SMS requires SMS_API_KEY."), "fast2sms"
        return Fast2SMSSMSProvider(api_key=api_key, sender_id=sender_id), "fast2sms"

    elif provider_name == 'msg91':
        if not api_key or not sender_id:
            return UnconfiguredSMSProvider("MSG91 requires SMS_API_KEY and SMS_SENDER_ID."), "msg91"
        return MSG91SMSProvider(auth_key=api_key, sender_id=sender_id), "msg91"

    # Default auto-detect if API key is provided
    if api_key.startswith('AC') and api_secret:
        return TwilioSMSProvider(account_sid=api_key, auth_token=api_secret, sender_id=sender_id or "+10000000000"), "twilio"
    elif api_key:
        return Fast2SMSSMSProvider(api_key=api_key, sender_id=sender_id), "fast2sms"

    return UnconfiguredSMSProvider("SMS provider not configured (SMS_API_KEY missing)."), (provider_name or "none")


def is_duplicate_sms(conn, request_id: int, pharmacy_id: int, message_type: str, cooldown_seconds: int = 300) -> bool:
    """
    Checks if an SMS has already been sent or is pending for the exact same
    (request_id, pharmacy_id, message_type) within the cooldown window.
    Prevents duplicate SMS from page refresh, network retry, or double clicks.
    """
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, created_at, status
            FROM sms_notifications
            WHERE request_id = ?
              AND pharmacy_id = ?
              AND message_type = ?
              AND status IN ('sent', 'pending')
              AND (strftime('%s', 'now') - strftime('%s', created_at)) < ?
            LIMIT 1;
        """, (request_id, pharmacy_id, message_type, cooldown_seconds))
        return cursor.fetchone() is not None
    except Exception as e:
        logger.warning(f"Error checking duplicate SMS: {e}")
        return False


def send_patient_response_sms(request_id: int, pharmacy_id: int, availability_status: str, notification_id: int = None, conn=None) -> dict:
    """
    Sends an SMS alert to the patient who created the medicine request.
    This function is executed AFTER the pharmacy response and in-app notification are saved.
    
    Adheres strictly to the required sequence:
      1. Map status to required SMS message template.
      2. Identify original patient from requests database record.
      3. Check patient SMS notification preference (ON/OFF).
      4. Check idempotency / duplicate protection.
      5. Retrieve patient's registered phone number from users table.
      6. Normalize and validate phone number (Indian +91 format).
      7. Safe log: "SMS notification requested".
      8. Record pending SMS record in sms_notifications table.
      9. Call provider send().
      10. Safe log: "SMS notification sent successfully" or "SMS notification failed".
      11. Update sms_notifications table.
      
    Under NO circumstances will this function raise an exception or break MedConnect.
    """
    should_close = False
    try:
        if conn is None:
            conn = get_db()
            should_close = True

        cursor = conn.cursor()

        # 1. Normalize availability status and map to required SMS template
        avail_str = str(availability_status).strip().lower()
        if avail_str in ('all_available', 'available', 'all'):
            msg_key = 'all_available'
        elif avail_str in ('some_available', 'partially_available', 'partial', 'some'):
            msg_key = 'some_available'
        elif avail_str in ('not_available', 'unavailable', 'none', 'out_of_stock'):
            msg_key = 'not_available'
        else:
            msg_key = 'all_available'

        sms_body = SMS_TEMPLATES[msg_key]

        # 2. Identify original patient from trusted requests record
        cursor.execute("SELECT id, patient_id FROM requests WHERE id = ?;", (request_id,))
        req_row = cursor.fetchone()
        if not req_row:
            logger.warning(f"Cannot send SMS: Request {request_id} not found.")
            return {'success': False, 'status': 'failed', 'error': 'Request not found'}

        patient_id = req_row['patient_id']

        # 3. Retrieve patient details (phone, sms_enabled preference) from users table
        cursor.execute("SELECT id, phone, sms_enabled FROM users WHERE id = ?;", (patient_id,))
        patient_row = cursor.fetchone()
        if not patient_row:
            logger.warning(f"Cannot send SMS: Patient user {patient_id} not found.")
            return {'success': False, 'status': 'failed', 'error': 'Patient user record not found'}

        patient_phone = patient_row['phone'] if 'phone' in patient_row.keys() else None
        sms_enabled = patient_row['sms_enabled'] if 'sms_enabled' in patient_row.keys() else 1

        # Check patient preference
        if sms_enabled == 0:
            print("SMS notification skipped: Patient opted out of SMS notifications")
            masked = mask_phone_number(patient_phone)
            cursor.execute("""
                INSERT INTO sms_notifications (request_id, notification_id, patient_id, pharmacy_id, phone_masked, phone_hash, message_type, message_body, provider, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'skipped', 'Patient opted out of SMS notifications');
            """, (request_id, notification_id, patient_id, pharmacy_id, masked, hash_phone_number(patient_phone), msg_key, sms_body, 'preference'))
            conn.commit()
            return {'success': False, 'status': 'skipped', 'reason': 'opted_out'}

        # 4. Check for duplicate SMS (Idempotency)
        if is_duplicate_sms(conn, request_id, pharmacy_id, msg_key):
            print(f"SMS notification skipped: Duplicate response detected for request {request_id}")
            masked = mask_phone_number(patient_phone)
            cursor.execute("""
                INSERT INTO sms_notifications (request_id, notification_id, patient_id, pharmacy_id, phone_masked, phone_hash, message_type, message_body, provider, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'skipped', 'Duplicate response within cooldown window');
            """, (request_id, notification_id, patient_id, pharmacy_id, masked, hash_phone_number(patient_phone), msg_key, sms_body, 'idempotency'))
            conn.commit()
            return {'success': False, 'status': 'skipped', 'reason': 'duplicate'}

        # 5. Validate and normalize phone number
        is_valid_phone, normalized_phone, phone_err = normalize_indian_phone(patient_phone)
        masked_phone = mask_phone_number(normalized_phone or patient_phone)

        if not is_valid_phone:
            print(f"SMS notification failed: {phone_err or 'Patient phone number unavailable.'}")
            cursor.execute("""
                INSERT INTO sms_notifications (request_id, notification_id, patient_id, pharmacy_id, phone_masked, phone_hash, message_type, message_body, provider, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'failed', ?);
            """, (request_id, notification_id, patient_id, pharmacy_id, masked_phone, hash_phone_number(patient_phone), msg_key, sms_body, 'validation', phone_err or 'Patient phone number unavailable.'))
            conn.commit()
            return {'success': False, 'status': 'failed', 'error': phone_err or 'Patient phone number unavailable.'}

        # 6. Retrieve configured provider
        provider, provider_name = get_sms_provider()

        # 7. Safe log: SMS notification requested
        print(f"SMS notification requested for patient (masked: {masked_phone}) via provider '{provider_name}'")

        # 8. Record initial pending entry in sms_notifications
        cursor.execute("""
            INSERT INTO sms_notifications (request_id, notification_id, patient_id, pharmacy_id, phone_masked, phone_hash, message_type, message_body, provider, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending');
        """, (request_id, notification_id, patient_id, pharmacy_id, masked_phone, hash_phone_number(normalized_phone), msg_key, sms_body, provider_name))
        conn.commit()
        sms_record_id = cursor.lastrowid

        # 9. Send SMS via provider
        provider_resp = provider.send(normalized_phone, sms_body)

        # 10. Update record and emit safe log
        if provider_resp.success:
            print(f"SMS notification sent successfully (ID: {provider_resp.message_id or sms_record_id})")
            cursor.execute("""
                UPDATE sms_notifications
                SET status = 'sent',
                    provider_message_id = ?,
                    sent_at = CURRENT_TIMESTAMP
                WHERE id = ?;
            """, (provider_resp.message_id, sms_record_id))
            conn.commit()
            return {'success': True, 'status': 'sent', 'message_id': provider_resp.message_id}
        else:
            safe_err = provider_resp.error_message or "Provider rejected request"
            print(f"SMS notification failed: {safe_err}")
            cursor.execute("""
                UPDATE sms_notifications
                SET status = 'failed',
                    error_message = ?
                WHERE id = ?;
            """, (safe_err, sms_record_id))
            conn.commit()
            return {'success': False, 'status': 'failed', 'error': safe_err}

    except Exception as e:
        safe_err_str = f"Internal SMS error: {str(e)}"
        print(f"SMS notification failed: {safe_err_str}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return {'success': False, 'status': 'failed', 'error': safe_err_str}
    finally:
        if should_close and conn:
            conn.close()
