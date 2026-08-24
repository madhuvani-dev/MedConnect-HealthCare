from flask import Blueprint, request, jsonify, session
from db import get_db
from utils import save_prescription_file, role_required, calculate_haversine_distance

patient_bp = Blueprint('patient', __name__, url_prefix='/api/patient')


@patient_bp.route('/location', methods=['POST'])
@role_required('patient')
def update_patient_location():
    """
    Updates the patient's current latitude and longitude coordinates.
    """
    data = request.get_json() or {}
    lat = data.get('latitude')
    lng = data.get('longitude')

    if lat is None or lng is None:
        return jsonify({'error': 'Latitude and longitude coordinates are required.'}), 400

    try:
        lat = float(lat)
        lng = float(lng)
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
            return jsonify({'error': 'Coordinates out of valid geographical range.'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Coordinates must be valid numbers.'}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET latitude = ?, longitude = ? WHERE id = ?;
    """, (lat, lng, session['user_id']))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Location updated successfully.', 'latitude': lat, 'longitude': lng}), 200


@patient_bp.route('/requests', methods=['POST'])
@role_required('patient')
def create_patient_request():
    """
    Creates a new medicine request.
    Supports either:
    1. Prescription file upload (multipart/form-data)
    2. Medicine name entry (multipart/form-data or JSON)
    Initial search radius is set to 5.0 km.
    """
    patient_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    # Get patient's stored coordinates if not provided in the form
    cursor.execute("SELECT latitude, longitude FROM users WHERE id = ?;", (patient_id,))
    patient = cursor.fetchone()

    # Handle multipart or JSON payload
    req_type = request.form.get('request_type') or (request.json.get('request_type') if request.is_json else None)
    medicine_name = request.form.get('medicine_name') or (request.json.get('medicine_name') if request.is_json else None)
    
    lat = request.form.get('latitude') or (request.json.get('latitude') if request.is_json else None)
    lng = request.form.get('longitude') or (request.json.get('longitude') if request.is_json else None)

    # Resolve coordinates
    if lat is not None and lng is not None:
        try:
            req_lat = float(lat)
            req_lng = float(lng)
        except ValueError:
            req_lat = patient['latitude'] if patient and patient['latitude'] else None
            req_lng = patient['longitude'] if patient and patient['longitude'] else None
    else:
        req_lat = patient['latitude'] if patient and patient['latitude'] else None
        req_lng = patient['longitude'] if patient and patient['longitude'] else None

    if req_lat is None or req_lng is None:
        conn.close()
        return jsonify({'error': 'Please set your location first before submitting a request.'}), 400

    prescription_filename = None

    if req_type == 'prescription':
        if 'prescription_file' not in request.files:
            conn.close()
            return jsonify({'error': 'Prescription file is required for prescription requests.'}), 400
        
        file_obj = request.files['prescription_file']
        prescription_filename = save_prescription_file(file_obj)
        if not prescription_filename:
            conn.close()
            return jsonify({'error': 'Invalid file format. Allowed formats: PNG, JPG, JPEG, PDF, WEBP.'}), 400

    elif req_type == 'medicine_name':
        if not medicine_name or not medicine_name.strip():
            conn.close()
            return jsonify({'error': 'Please enter a medicine name.'}), 400
        medicine_name = medicine_name.strip()
    else:
        conn.close()
        return jsonify({'error': "Invalid request type. Must be 'prescription' or 'medicine_name'."}), 400

    # Insert request with initial 5.0 km radius
    cursor.execute("""
        INSERT INTO requests (patient_id, request_type, medicine_name, prescription_file, patient_lat, patient_lng, search_radius_km, status)
        VALUES (?, ?, ?, ?, ?, ?, 5.0, 'active');
    """, (patient_id, req_type, medicine_name, prescription_filename, req_lat, req_lng))
    
    conn.commit()
    new_request_id = cursor.lastrowid
    conn.close()

    return jsonify({
        'message': 'Request submitted successfully to verified pharmacies within 5 km radius!',
        'request_id': new_request_id
    }), 201


@patient_bp.route('/requests', methods=['GET'])
@role_required('patient')
def get_patient_requests():
    """
    Returns all requests submitted by the logged-in patient,
    including the count of responses received for each.
    """
    patient_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT r.id, r.request_type, r.medicine_name, r.prescription_file,
               r.patient_lat, r.patient_lng, r.search_radius_km, r.status, r.created_at,
               COUNT(resp.id) as response_count,
               SUM(CASE WHEN resp.availability_status = 'all_available' THEN 1 ELSE 0 END) as all_available_count,
               SUM(CASE WHEN resp.availability_status = 'some_available' THEN 1 ELSE 0 END) as some_available_count,
               SUM(CASE WHEN resp.availability_status = 'not_available' THEN 1 ELSE 0 END) as not_available_count
        FROM requests r
        LEFT JOIN responses resp ON r.id = resp.request_id
        WHERE r.patient_id = ?
        GROUP BY r.id
        ORDER BY r.created_at DESC;
    """, (patient_id,))

    rows = cursor.fetchall()
    requests_list = [dict(row) for row in rows]
    conn.close()

    return jsonify({'requests': requests_list}), 200


@patient_bp.route('/requests/<int:req_id>/responses', methods=['GET'])
@role_required('patient')
def get_request_responses(req_id):
    """
    Returns all approved verified pharmacies within the request's current search radius,
    along with their response status, notes, contact details, and distance.
    """
    patient_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    # Verify that this request belongs to this patient
    cursor.execute("""
        SELECT id, patient_id, request_type, medicine_name, prescription_file, 
               patient_lat, patient_lng, search_radius_km, status, created_at 
        FROM requests 
        WHERE id = ? AND patient_id = ?;
    """, (req_id, patient_id))
    req = cursor.fetchone()
    if not req:
        conn.close()
        return jsonify({'error': 'Request not found.'}), 404

    req_lat = req['patient_lat']
    req_lng = req['patient_lng']
    search_radius = float(req['search_radius_km'])

    # Fetch all approved pharmacies with user contact info and their response to this request if present
    cursor.execute("""
        SELECT p.id as pharmacy_id, p.pharmacy_name, p.owner_name, p.dl_number, 
               p.address, p.latitude, p.longitude, p.status as pharmacy_status,
               u.phone, u.email,
               resp.id as response_id, resp.availability_status, resp.notes, resp.created_at as response_created_at
        FROM pharmacies p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN responses resp ON resp.pharmacy_id = p.id AND resp.request_id = ?
        WHERE p.status = 'approved';
    """, (req_id,))

    rows = cursor.fetchall()
    conn.close()

    pharmacies_list = []
    for row in rows:
        pharm_lat = row['latitude']
        pharm_lng = row['longitude']
        distance_km = calculate_haversine_distance(req_lat, req_lng, pharm_lat, pharm_lng)

        # Only include pharmacies within the request's current search radius
        if distance_km <= search_radius:
            has_responded = bool(row['response_id'])
            pharmacies_list.append({
                'id': row['pharmacy_id'],
                'pharmacy_name': row['pharmacy_name'],
                'owner_name': row['owner_name'],
                'dl_number': row['dl_number'],
                'address': row['address'],
                'phone': row['phone'],
                'email': row['email'],
                'latitude': float(pharm_lat) if pharm_lat is not None else None,
                'longitude': float(pharm_lng) if pharm_lng is not None else None,
                'distance_km': distance_km,
                'has_responded': has_responded,
                'availability_status': row['availability_status'] if has_responded else None,
                'notes': row['notes'] if has_responded else None,
                'created_at': row['response_created_at'] if has_responded else None
            })

    # Sort pharmacies: responded first (with available first), then by distance ascending
    def sort_key(item):
        status_priority = {
            'all_available': 1,
            'some_available': 2,
            'not_available': 3,
            None: 4
        }
        resp_priority = 0 if item['has_responded'] else 1
        stat_prio = status_priority.get(item['availability_status'], 4)
        return (resp_priority, stat_prio, item['distance_km'])

    pharmacies_list.sort(key=sort_key)

    return jsonify({
        'request': dict(req),
        'pharmacies': pharmacies_list,
        'responses': pharmacies_list
    }), 200


@patient_bp.route('/requests/<int:req_id>/expand-radius', methods=['POST'])
@role_required('patient')
def expand_request_radius(req_id):
    """
    Increases the search radius of a patient's active request by 5 km (or specified step)
    so more distant verified pharmacies can see and fulfill it.
    """
    patient_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, search_radius_km, status FROM requests WHERE id = ? AND patient_id = ?;", (req_id, patient_id))
    req = cursor.fetchone()

    if not req:
        conn.close()
        return jsonify({'error': 'Request not found.'}), 404

    if req['status'] != 'active':
        conn.close()
        return jsonify({'error': 'Cannot expand radius for inactive requests.'}), 400

    current_radius = req['search_radius_km']
    new_radius = round(current_radius + 5.0, 1)

    cursor.execute("UPDATE requests SET search_radius_km = ? WHERE id = ?;", (new_radius, req_id))
    conn.commit()
    conn.close()

    return jsonify({
        'message': f'Search radius expanded from {current_radius} km to {new_radius} km. More nearby pharmacies can now respond.',
        'new_radius_km': new_radius
    }), 200


@patient_bp.route('/requests/<int:req_id>/close', methods=['POST'])
@role_required('patient')
def close_request(req_id):
    """
    Marks a request as 'completed' or 'cancelled'.
    """
    data = request.get_json() or {}
    new_status = data.get('status', 'completed')
    if new_status not in ('completed', 'cancelled'):
        new_status = 'completed'

    patient_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("UPDATE requests SET status = ? WHERE id = ? AND patient_id = ?;", (new_status, req_id, patient_id))
    conn.commit()
    conn.close()

    return jsonify({'message': f'Request marked as {new_status}.'}), 200
