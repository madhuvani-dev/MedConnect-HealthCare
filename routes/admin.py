from flask import Blueprint, request, jsonify
from db import get_db
from utils import role_required

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')


@admin_bp.route('/pharmacies', methods=['GET'])
@role_required('admin')
def get_admin_pharmacies():
    """
    Returns all registered pharmacies grouped or filtered by status.
    """
    status_filter = request.args.get('status')
    conn = get_db()
    cursor = conn.cursor()

    query = """
        SELECT p.id, p.user_id, p.pharmacy_name, p.owner_name, p.dl_number,
               p.address, p.latitude, p.longitude, p.status, p.created_at,
               u.name as contact_name, u.email, u.phone
        FROM pharmacies p
        JOIN users u ON p.user_id = u.id
    """
    params = []
    if status_filter in ('pending', 'approved', 'rejected'):
        query += " WHERE p.status = ?"
        params.append(status_filter)
    
    query += " ORDER BY p.created_at DESC;"

    cursor.execute(query, tuple(params))
    pharmacies = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return jsonify({'pharmacies': pharmacies}), 200


@admin_bp.route('/pharmacies/<int:pharm_id>/approve', methods=['POST'])
@role_required('admin')
def approve_pharmacy(pharm_id):
    """
    Approves a pending pharmacy registration, allowing them to log in and receive requests.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, pharmacy_name FROM pharmacies WHERE id = ?;", (pharm_id,))
    pharm = cursor.fetchone()

    if not pharm:
        conn.close()
        return jsonify({'error': 'Pharmacy not found.'}), 404

    cursor.execute("UPDATE pharmacies SET status = 'approved' WHERE id = ?;", (pharm_id,))
    conn.commit()
    conn.close()

    return jsonify({'message': f'Pharmacy "{pharm["pharmacy_name"]}" has been approved successfully.'}), 200


@admin_bp.route('/pharmacies/<int:pharm_id>/reject', methods=['POST'])
@role_required('admin')
def reject_pharmacy(pharm_id):
    """
    Rejects a pharmacy registration.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, pharmacy_name FROM pharmacies WHERE id = ?;", (pharm_id,))
    pharm = cursor.fetchone()

    if not pharm:
        conn.close()
        return jsonify({'error': 'Pharmacy not found.'}), 404

    cursor.execute("UPDATE pharmacies SET status = 'rejected' WHERE id = ?;", (pharm_id,))
    conn.commit()
    conn.close()

    return jsonify({'message': f'Pharmacy "{pharm["pharmacy_name"]}" registration was rejected.'}), 200


@admin_bp.route('/users', methods=['GET'])
@role_required('admin')
def get_admin_users():
    """
    Returns registered patients and user accounts for monitoring.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, email, phone, role, latitude, longitude, created_at
        FROM users
        ORDER BY created_at DESC;
    """)
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return jsonify({'users': users}), 200


@admin_bp.route('/stats', methods=['GET'])
@role_required('admin')
def get_admin_stats():
    """
    Returns high-level platform statistics.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total_patients FROM users WHERE role = 'patient';")
    total_patients = cursor.fetchone()['total_patients']

    cursor.execute("SELECT COUNT(*) as total_pharmacies FROM pharmacies;")
    total_pharmacies = cursor.fetchone()['total_pharmacies']

    cursor.execute("SELECT COUNT(*) as approved_pharmacies FROM pharmacies WHERE status = 'approved';")
    approved_pharmacies = cursor.fetchone()['approved_pharmacies']

    cursor.execute("SELECT COUNT(*) as pending_pharmacies FROM pharmacies WHERE status = 'pending';")
    pending_pharmacies = cursor.fetchone()['pending_pharmacies']

    cursor.execute("SELECT COUNT(*) as total_requests FROM requests;")
    total_requests = cursor.fetchone()['total_requests']

    cursor.execute("SELECT COUNT(*) as total_responses FROM responses;")
    total_responses = cursor.fetchone()['total_responses']

    conn.close()

    return jsonify({
        'stats': {
            'total_patients': total_patients,
            'total_pharmacies': total_pharmacies,
            'approved_pharmacies': approved_pharmacies,
            'pending_pharmacies': pending_pharmacies,
            'total_requests': total_requests,
            'total_responses': total_responses
        }
    }), 200
