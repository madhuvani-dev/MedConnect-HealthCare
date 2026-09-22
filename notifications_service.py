import logging
from db import get_db
from utils import calculate_haversine_distance

logger = logging.getLogger('medconnect.notifications')

def create_notification(user_id, title, message, notif_type='system', related_request_id=None, conn=None):
    """
    Creates an individual notification record for a specific user.
    Can reuse an existing SQLite connection or open a new one.
    Fails safely without raising exceptions to calling business logic.
    """
    should_close = False
    try:
        if conn is None:
            conn = get_db()
            should_close = True
        
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO notifications (user_id, title, message, type, related_request_id, is_read)
            VALUES (?, ?, ?, ?, ?, 0);
        """, (user_id, title.strip(), message.strip(), notif_type, related_request_id))
        
        if should_close:
            conn.commit()
            
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"[Notification] Failed to create notification for user {user_id}: {e}")
        return None
    finally:
        if should_close and conn:
            conn.close()

def notify_admins(title, message, notif_type='system', related_request_id=None):
    """
    Broadcasts a notification to all registered Admin users.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE role = 'admin';")
        admins = cursor.fetchall()
        
        for admin in admins:
            create_notification(
                user_id=admin['id'],
                title=title,
                message=message,
                notif_type=notif_type,
                related_request_id=related_request_id,
                conn=conn
            )
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[Notification] Failed to notify admins: {e}")

def notify_nearby_pharmacies_for_request(request_id, req_type, medicine_name, patient_lat, patient_lng, radius_km, exclude_user_ids=None):
    """
    Finds all approved pharmacies within the request search radius and creates a notification.
    """
    if exclude_user_ids is None:
        exclude_user_ids = set()
        
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id as pharmacy_id, p.user_id, p.pharmacy_name, p.latitude, p.longitude
            FROM pharmacies p
            WHERE p.status = 'approved';
        """)
        pharmacies = cursor.fetchall()
        
        notified_count = 0
        for pharm in pharmacies:
            if pharm['user_id'] in exclude_user_ids:
                continue
                
            dist = calculate_haversine_distance(patient_lat, patient_lng, pharm['latitude'], pharm['longitude'])
            if dist <= float(radius_km):
                if req_type == 'prescription':
                    title = "New Prescription Request Nearby"
                    msg = f"A patient within {dist} km uploaded a prescription requesting medicine availability."
                else:
                    med_label = f"'{medicine_name}'" if medicine_name else "medicines"
                    title = "New Medicine Inquiry Nearby"
                    msg = f"A patient within {dist} km is searching for {med_label}."
                    
                create_notification(
                    user_id=pharm['user_id'],
                    title=title,
                    message=msg,
                    notif_type='request_new',
                    related_request_id=request_id,
                    conn=conn
                )
                notified_count += 1
                
        conn.commit()
        conn.close()
        return notified_count
    except Exception as e:
        logger.error(f"[Notification] Failed to notify nearby pharmacies for request {request_id}: {e}")
        return 0

def notify_patient_for_response(request_id, pharmacy_name=None, availability_status='all_available', notes=None, distance_km=None, conn=None):
    """
    Notifies the patient when a verified pharmacy responds to their inquiry.
    Uses exact required notification titles and messages:
      - Available: "Medicine Available" / "The pharmacy has responded to your medicine request. The requested medicine is available."
      - Partially Available: "Medicine Partially Available" / "The pharmacy has responded to your medicine request. Some of the requested medicine is available."
      - Unavailable: "Medicine Unavailable" / "The pharmacy has responded to your medicine request. The requested medicine is currently unavailable."
    """
    should_close = False
    try:
        if conn is None:
            conn = get_db()
            should_close = True

        cursor = conn.cursor()
        cursor.execute("SELECT id, patient_id, medicine_name, request_type FROM requests WHERE id = ?;", (request_id,))
        req = cursor.fetchone()

        if not req:
            if should_close:
                conn.close()
            return None

        patient_id = req['patient_id']

        avail_str = str(availability_status).strip().lower()
        if avail_str in ('all_available', 'available', 'all'):
            title = "Medicine Available"
            msg = "The pharmacy has responded to your medicine request. The requested medicine is available."
        elif avail_str in ('some_available', 'partially_available', 'partial', 'some'):
            title = "Medicine Partially Available"
            msg = "The pharmacy has responded to your medicine request. Some of the requested medicine is available."
        else:
            title = "Medicine Unavailable"
            msg = "The pharmacy has responded to your medicine request. The requested medicine is currently unavailable."

        notif_id = create_notification(
            user_id=patient_id,
            title=title,
            message=msg,
            notif_type='request_response',
            related_request_id=request_id,
            conn=conn
        )

        if should_close:
            conn.commit()
            conn.close()

        return notif_id
    except Exception as e:
        logger.error(f"[Notification] Failed to notify patient for response on request {request_id}: {e}")
        if should_close and conn:
            conn.close()
        return None

def notify_pharmacy_status_update(pharmacy_id, new_status, pharmacy_name=None):
    """
    Notifies pharmacy user account when admin approves or rejects their registration.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, pharmacy_name FROM pharmacies WHERE id = ?;", (pharmacy_id,))
        pharm = cursor.fetchone()
        
        if not pharm:
            conn.close()
            return
            
        user_id = pharm['user_id']
        p_name = pharmacy_name or pharm['pharmacy_name']
        
        if new_status == 'approved':
            title = "Pharmacy Registration Approved!"
            msg = f"Congratulations! Your pharmacy '{p_name}' has been verified by the Drug Control Administrator. You can now log in, view patient inquiries, and submit availability."
            notif_type = 'pharmacy_approval'
        else:
            title = "Pharmacy Registration Rejected"
            msg = f"Your registration for '{p_name}' was rejected by the administrator. Please ensure your Drug License (DL) details are valid."
            notif_type = 'pharmacy_rejection'
            
        create_notification(
            user_id=user_id,
            title=title,
            message=msg,
            notif_type=notif_type,
            related_request_id=None,
            conn=conn
        )
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[Notification] Failed to notify pharmacy {pharmacy_id} status change: {e}")

def notify_pharmacies_for_request_status(request_id, new_status):
    """
    Notifies pharmacies who submitted a response that the request has been closed or cancelled.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT p.user_id, r.id as request_id
            FROM responses resp
            JOIN pharmacies p ON resp.pharmacy_id = p.id
            JOIN requests r ON resp.request_id = r.id
            WHERE resp.request_id = ?;
        """, (request_id,))
        pharmacies = cursor.fetchall()
        
        status_label = "completed" if new_status == 'completed' else "cancelled"
        for pharm in pharmacies:
            create_notification(
                user_id=pharm['user_id'],
                title=f"Request #{request_id} Marked {status_label.capitalize()}",
                message=f"The patient has marked medicine request #{request_id} as {status_label}.",
                notif_type='request_status',
                related_request_id=request_id,
                conn=conn
            )
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[Notification] Failed to notify pharmacies on request {request_id} status: {e}")
