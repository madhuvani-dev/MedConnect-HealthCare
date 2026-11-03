"""
MedConnect SMS & Web Push Notification Service (Deferred to Future Scope)

NOTE: SMS notifications and Web Push alerts have been officially deferred
to future enhancement increments. This module acts as a safe, dormant stub:
- No external SMS provider credentials (Twilio, Fast2SMS, MSG91) are required.
- All core medicine request, response, and real-time in-app notification
  workflows remain 100% operational via notifications_service.py.
- Existing database columns (users.sms_enabled) and tables (sms_notifications)
  are preserved for full backward compatibility without destructive migrations.
"""

import logging

logger = logging.getLogger('medconnect.sms')


def mask_phone_number(phone: str) -> str:
    """
    Masks a phone number for privacy if needed.
    """
    if not phone:
        return "<unavailable>"
    clean = str(phone).strip()
    if len(clean) <= 4:
        return "****"
    visible_tail = clean[-4:]
    masked_middle = "*" * (len(clean) - len(visible_tail))
    return f"{masked_middle}{visible_tail}"


def send_patient_response_sms(*args, **kwargs) -> dict:
    """
    Dormant stub for future SMS integration.
    Currently a safe no-op since SMS is deferred to future scope.
    """
    logger.debug("SMS notifications deferred to future scope; skipping SMS dispatch.")
    return {
        "status": "deferred",
        "message": "SMS notifications are deferred to future scope."
    }
