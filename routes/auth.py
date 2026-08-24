from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import bcrypt
from db import get_db

def verify_user_password(stored_hash, candidate_password):
    if not stored_hash or not candidate_password:
        return False
    if stored_hash.startswith('$2b$') or stored_hash.startswith('$2a$') or stored_hash.startswith('$2y$'):
        try:
            return bcrypt.checkpw(candidate_password.encode('utf-8'), stored_hash.encode('utf-8'))
        except Exception:
            pass
    try:
        return check_password_hash(stored_hash, candidate_password)
    except Exception:
        return False

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@auth_bp.route('/register-patient', methods=['POST'])
def register_patient():
    """
    Registers a new Patient account.
    """
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()
    lat = data.get('latitude')
    lng = data.get('longitude')

    if not name or not email or not phone or not password:
        return jsonify({'error': 'Name, email, phone, and password are required.'}), 400

    if lat is None or lng is None:
        return jsonify({'error': 'Please select your location on the map so MedConnect can find nearby pharmacies.'}), 400

    try:
        lat = float(lat)
        lng = float(lng)
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return jsonify({'error': 'Invalid coordinates provided. Latitude must be between -90 and 90, longitude between -180 and 180.'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Coordinates must be valid numbers.'}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Check if email is already taken
    cursor.execute("SELECT id FROM users WHERE email = ?;", (email,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'error': 'Email address is already registered.'}), 409

    password_hash = generate_password_hash(password)
    try:
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role, latitude, longitude)
            VALUES (?, ?, ?, ?, 'patient', ?, ?);
        """, (name, email, phone, password_hash, lat, lng))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()

        # Log the user in directly
        session.clear()
        session['user_id'] = user_id
        session['name'] = name
        session['role'] = 'patient'

        return jsonify({
            'message': 'Patient registration successful.',
            'redirect': '/patient/dashboard'
        }), 201
    except Exception as e:
        conn.close()
        return jsonify({'error': f'Database error: {str(e)}'}), 500


@auth_bp.route('/register-pharmacy', methods=['POST'])
def register_pharmacy():
    """
    Registers a new Pharmacy. It creates a user row and a linked pharmacy row
    with 'pending' verification status awaiting Admin approval.
    """
    data = request.get_json() or {}
    contact_name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()

    pharmacy_name = data.get('pharmacy_name', '').strip()
    owner_name = data.get('owner_name', '').strip()
    dl_number = data.get('dl_number', '').strip().upper()
    address = data.get('address', '').strip()
    lat = data.get('latitude')
    lng = data.get('longitude')

    if not all([contact_name, email, phone, password, pharmacy_name, owner_name, dl_number, address]):
        return jsonify({'error': 'All fields including Pharmacy Name, Owner, DL Number, Address and Phone are required.'}), 400

    if lat is None or lng is None:
        return jsonify({'error': 'Pharmacy geographic coordinates (latitude and longitude) are required.'}), 400

    try:
        lat = float(lat)
        lng = float(lng)
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return jsonify({'error': 'Invalid coordinates provided. Latitude must be between -90 and 90, longitude between -180 and 180.'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Coordinates must be valid numbers.'}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Check if email is already taken
    cursor.execute("SELECT id FROM users WHERE email = ?;", (email,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'error': 'Email address is already registered.'}), 409

    # Check if DL number is already taken
    cursor.execute("SELECT id FROM pharmacies WHERE dl_number = ?;", (dl_number,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'error': 'Drug License (DL) number is already registered.'}), 409

    password_hash = generate_password_hash(password)
    try:
        # 1. Insert user
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES (?, ?, ?, ?, 'pharmacy');
        """, (contact_name, email, phone, password_hash))
        user_id = cursor.lastrowid

        # 2. Insert pharmacy details (default status is 'pending')
        cursor.execute("""
            INSERT INTO pharmacies (user_id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending');
        """, (user_id, pharmacy_name, owner_name, dl_number, address, lat, lng))

        conn.commit()
        conn.close()

        return jsonify({
            'message': 'Pharmacy registered successfully! Your account is pending admin verification before you can log in.',
            'redirect': '/login?registered=pending'
        }), 201
    except Exception as e:
        conn.close()
        return jsonify({'error': f'Database error: {str(e)}'}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Authenticates user and initiates Flask session with role-specific data.
    """
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({'error': 'Please provide both email and password.'}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?;", (email,))
    user = cursor.fetchone()

    if not user or not verify_user_password(user['password_hash'], password):
        conn.close()
        return jsonify({'error': 'Invalid email or password.'}), 401

    role = user['role']
    pharmacy_id = None
    pharmacy_status = None

    if role == 'pharmacy':
        cursor.execute("SELECT id, status, pharmacy_name FROM pharmacies WHERE user_id = ?;", (user['id'],))
        pharmacy = cursor.fetchone()
        if not pharmacy:
            conn.close()
            return jsonify({'error': 'Pharmacy profile record not found.'}), 404
        
        pharmacy_id = pharmacy['id']
        pharmacy_status = pharmacy['status']

        if pharmacy_status == 'pending':
            conn.close()
            return jsonify({
                'error': 'Your pharmacy registration is currently pending admin verification. Please wait for approval.'
            }), 403
        elif pharmacy_status == 'rejected':
            conn.close()
            return jsonify({
                'error': 'Your pharmacy registration was rejected by the administrator. Contact support for assistance.'
            }), 403

    conn.close()

    # Set session variables
    session.clear()
    session['user_id'] = user['id']
    session['name'] = user['name']
    session['email'] = user['email']
    session['role'] = role
    if pharmacy_id:
        session['pharmacy_id'] = pharmacy_id
        session['pharmacy_status'] = pharmacy_status

    redirect_url = '/patient/dashboard' if role == 'patient' else ('/pharmacy/dashboard' if role == 'pharmacy' else '/admin/dashboard')

    return jsonify({
        'message': 'Login successful.',
        'user': {
            'id': user['id'],
            'name': user['name'],
            'email': user['email'],
            'role': role
        },
        'redirect': redirect_url
    }), 200


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logs out the current user by clearing the session."""
    session.clear()
    return jsonify({'message': 'Logged out successfully.', 'redirect': '/login'}), 200


@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """Returns currently authenticated user data and coordinates."""
    if 'user_id' not in session:
        return jsonify({'authenticated': False}), 200

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, phone, role, latitude, longitude, created_at FROM users WHERE id = ?;", (session['user_id'],))
    user = cursor.fetchone()

    if not user:
        conn.close()
        session.clear()
        return jsonify({'authenticated': False}), 200

    user_dict = dict(user)
    pharmacy_info = None

    if user_dict['role'] == 'pharmacy':
        cursor.execute("SELECT id, pharmacy_name, owner_name, dl_number, address, latitude, longitude, status FROM pharmacies WHERE user_id = ?;", (user['id'],))
        pharmacy = cursor.fetchone()
        if pharmacy:
            pharmacy_info = dict(pharmacy)

    conn.close()

    return jsonify({
        'authenticated': True,
        'user': user_dict,
        'pharmacy': pharmacy_info
    }), 200
