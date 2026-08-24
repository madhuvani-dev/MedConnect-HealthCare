import math
import os
import uuid
from functools import wraps
from flask import session, jsonify, redirect, url_for, request
from werkzeug.utils import secure_filename

# Allowed file extensions for prescription uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'webp'}
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')

def allowed_file(filename):
    """
    Checks if an uploaded file has an allowed extension.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_prescription_file(file_storage):
    """
    Saves an uploaded prescription file with a unique secure filename.
    Returns the generated filename or None if invalid.
    """
    if not file_storage or file_storage.filename == '':
        return None
    
    if not allowed_file(file_storage.filename):
        return None
    
    # Ensure upload folder exists
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    # Generate unique filename to prevent collisions and path injection
    original_clean = secure_filename(file_storage.filename)
    extension = original_clean.rsplit('.', 1)[1].lower() if '.' in original_clean else 'jpg'
    unique_filename = f"rx_{uuid.uuid4().hex[:12]}.{extension}"
    
    filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
    file_storage.save(filepath)
    return unique_filename

def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculates the great-circle distance between two geographic coordinates
    (latitude, longitude in decimal degrees) using the Haversine formula.
    Returns distance in kilometers (km), rounded to 2 decimal places.
    """
    if None in (lat1, lon1, lat2, lon2):
        return 9999.0
    
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (ValueError, TypeError):
        return 9999.0

    # Earth radius in kilometers
    R = 6371.0
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    distance = R * c
    
    return round(distance, 2)

def login_required(f):
    """
    Decorator to protect routes that require authentication.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized. Please log in.'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(required_role):
    """
    Decorator to restrict access to specific roles ('patient', 'pharmacy', 'admin').
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            print(f"[ROLE_CHECK] required_role={required_role}, user_id={session.get('user_id')}, role={session.get('role')}, pharmacy_id={session.get('pharmacy_id')}, pharmacy_status={session.get('pharmacy_status')}")

            if 'user_id' not in session:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Unauthorized. Please log in.'}), 401
                return redirect(url_for('login_page'))
            
            user_role = session.get('role')
            if user_role != required_role:
                if request.path.startswith('/api/'):
                    return jsonify({'error': f'Forbidden. {required_role.capitalize()} access required.'}), 403
                return redirect(url_for('index'))
            
            # Extra check for pharmacy verification status
            if required_role == 'pharmacy':
                pharmacy_status = session.get('pharmacy_status')
                if pharmacy_status != 'approved':
                    if request.path.startswith('/api/'):
                        return jsonify({'error': 'Pharmacy account is pending approval or rejected.'}), 403
                    return redirect(url_for('login_page', message='Your pharmacy registration is pending admin approval.'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
