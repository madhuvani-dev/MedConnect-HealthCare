from flask import Blueprint, request, jsonify, session, send_from_directory
from db import get_db
from utils import calculate_haversine_distance, role_required, login_required, UPLOAD_FOLDER

pharmacy_bp = Blueprint('pharmacy', __name__)


@pharmacy_bp.route('/api/pharmacy/feed', methods=['GET'])
@role_required('pharmacy')
def get_pharmacy_feed():
    """
    Returns active patient requests where the distance between the pharmacy
    and the patient is within the request's current search_radius_km.
    Also indicates if this pharmacy has already submitted a response.
    """
    pharmacy_id = session.get('pharmacy_id')
    conn = get_db()
    cursor = conn.cursor()

    # Get this pharmacy's coordinates
    cursor.execute("SELECT id, latitude, longitude, pharmacy_name FROM pharmacies WHERE id = ?;", (pharmacy_id,))
    pharmacy = cursor.fetchone()

    if not pharmacy:
        conn.close()
        return jsonify({'error': 'Pharmacy details not found.'}), 404

    pharm_lat = pharmacy['latitude']
    pharm_lng = pharmacy['longitude']

    # Fetch all active requests with patient details
    cursor.execute("""
        SELECT r.id, r.patient_id, r.request_type, r.medicine_name, r.prescription_file,
               r.patient_lat, r.patient_lng, r.search_radius_km, r.status, r.created_at,
               u.name as patient_name, u.phone as patient_phone
        FROM requests r
        JOIN users u ON r.patient_id = u.id
        WHERE r.status = 'active'
        ORDER BY r.created_at DESC;
    """)
    all_requests = cursor.fetchall()

    # Check which requests this pharmacy already responded to
    cursor.execute("""
        SELECT request_id, availability_status, notes, created_at
        FROM responses
        WHERE pharmacy_id = ?;
    """, (pharmacy_id,))
    my_responses = {row['request_id']: dict(row) for row in cursor.fetchall()}

    conn.close()

    eligible_feed = []
    for req in all_requests:
        req_dict = dict(req)
        # Calculate distance between pharmacy and patient
        dist = calculate_haversine_distance(pharm_lat, pharm_lng, req['patient_lat'], req['patient_lng'])
        req_dict['distance_km'] = dist
        
        # Check if pharmacy is within the patient's search radius
        if dist <= req['search_radius_km']:
            req_dict['has_responded'] = req['id'] in my_responses
            req_dict['my_response'] = my_responses.get(req['id'])
            eligible_feed.append(req_dict)

    # Sort by distance (closest requests first)
    eligible_feed.sort(key=lambda x: x['distance_km'])

    return jsonify({
        'pharmacy_name': pharmacy['pharmacy_name'],
        'requests': eligible_feed
    }), 200


@pharmacy_bp.route('/api/pharmacy/responses', methods=['POST'])
@pharmacy_bp.route('/api/pharmacy/requests/<int:url_req_id>/respond', methods=['POST'])
@pharmacy_bp.route('/api/pharmacy/requests/<int:url_req_id>/responses', methods=['POST'])
@role_required('pharmacy')
def submit_pharmacy_response(url_req_id=None):
    """
    Submits or updates an availability response for an active patient request.
    Availability options:
      - 'all_available' / 'available'
      - 'some_available' / 'partially_available'
      - 'not_available' / 'unavailable'
    """
    print("PHARMACY RESPONSE START")

    pharmacy_id = session.get('pharmacy_id')
    data = request.get_json() or {}
    req_id = url_req_id or data.get('request_id') or data.get('req_id')
    raw_availability = data.get('availability_status') or data.get('availability') or data.get('status')
    notes = (data.get('notes') or '').strip()

    if not req_id or not raw_availability:
        return jsonify({'error': 'Request ID and availability status are required.'}), 400

    print(f"REQUEST ID: {req_id}")

    # Normalize availability input and map to database status and required notification text
    avail_str = str(raw_availability).strip().lower()
    if avail_str in ('all_available', 'available', 'all'):
        availability = 'all_available'
        notif_title = "Medicine Available"
        notif_message = "The pharmacy has responded to your medicine request. The requested medicine is available."
    elif avail_str in ('some_available', 'partially_available', 'partial', 'some'):
        availability = 'some_available'
        notif_title = "Medicine Partially Available"
        notif_message = "The pharmacy has responded to your medicine request. Some of the requested medicine is available."
    elif avail_str in ('not_available', 'unavailable', 'none', 'out_of_stock'):
        availability = 'not_available'
        notif_title = "Medicine Unavailable"
        notif_message = "The pharmacy has responded to your medicine request. The requested medicine is currently unavailable."
    else:
        return jsonify({'error': 'Invalid availability status.'}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        # Resolve pharmacy_id if missing from session
        if not pharmacy_id:
            cursor.execute("SELECT id FROM pharmacies WHERE user_id = ?;", (session.get('user_id'),))
            pharm_row = cursor.fetchone()
            if pharm_row:
                pharmacy_id = pharm_row['id']
                session['pharmacy_id'] = pharmacy_id

        # Get pharmacy details
        cursor.execute("SELECT id, pharmacy_name, latitude, longitude FROM pharmacies WHERE id = ?;", (pharmacy_id,))
        pharmacy = cursor.fetchone()
        if not pharmacy:
            conn.close()
            return jsonify({'error': 'Pharmacy profile record not found.'}), 404

        # Validate the request and identify the patient who originally submitted the request
        cursor.execute("SELECT id, patient_id, patient_lat, patient_lng, status FROM requests WHERE id = ?;", (req_id,))
        req = cursor.fetchone()

        if not req or req['status'] != 'active':
            conn.close()
            return jsonify({'error': 'Request not found or no longer active.'}), 404

        patient_id = req['patient_id']
        print(f"PATIENT ID: {patient_id}")

        # Calculate distance
        dist = calculate_haversine_distance(pharmacy['latitude'], pharmacy['longitude'], req['patient_lat'], req['patient_lng'])

        # Save/update the pharmacy availability response in the database
        cursor.execute("""
            INSERT INTO responses (request_id, pharmacy_id, availability_status, notes, distance_km)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(request_id, pharmacy_id) DO UPDATE SET
                availability_status = excluded.availability_status,
                notes = excluded.notes,
                distance_km = excluded.distance_km,
                created_at = CURRENT_TIMESTAMP;
        """, (req_id, pharmacy_id, availability, notes, dist))

        # Confirm the database operation succeeded
        conn.commit()
        print("RESPONSE SAVED")

        # Create notification for the identified patient
        print("NOTIFICATION CREATION START")
        cursor.execute("""
            INSERT INTO notifications (user_id, title, message, type, related_request_id, is_read)
            VALUES (?, ?, ?, 'request_response', ?, 0);
        """, (patient_id, notif_title, notif_message, req_id))
        conn.commit()
        notif_id = cursor.lastrowid
        conn.close()
        print(f"NOTIFICATION CREATED: {notif_id}")



        status_text = "All medicines available" if availability == 'all_available' else ("Some medicines available" if availability == 'some_available' else "Not available")

        print("PHARMACY RESPONSE COMPLETE")

        return jsonify({
            'message': f'Response submitted successfully: "{status_text}"',
            'distance_km': dist,
            'availability_status': availability,
            'request_id': req_id
        }), 200

    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"[Error] Failed in submit_pharmacy_response: {e}")
        return jsonify({'error': f'Database error: {str(e)}'}), 500


@pharmacy_bp.route('/uploads/prescriptions/<path:filename>')
@login_required
def serve_prescription(filename):
    """
    Securely serves uploaded prescription documents to authenticated users
    (patients viewing their own uploads, pharmacies reviewing incoming requests, or admins).
    """
    return send_from_directory(UPLOAD_FOLDER, filename)
