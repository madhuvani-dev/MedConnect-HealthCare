from flask import Blueprint, request, jsonify, session
from db import get_db
from utils import login_required

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')

@notifications_bp.route('', methods=['GET'], strict_slashes=False)
@notifications_bp.route('/', methods=['GET'], strict_slashes=False)
@login_required
def get_notifications():
    """
    Retrieves the authenticated user's notifications.
    Supports filtering by status ('all', 'unread', 'read') and limiting count.
    Never exposes another user's notifications.
    """
    user_id = session.get('user_id')
    status_filter = request.args.get('filter', 'all').lower()
    limit = request.args.get('limit', 50, type=int)
    if limit is None or limit <= 0 or limit > 200:
        limit = 50

    conn = get_db()
    cursor = conn.cursor()

    # Base query for notifications
    query = """
        SELECT n.id, n.user_id, n.title, n.message, n.type,
               n.related_request_id, n.is_read, n.created_at,
               r.request_type, r.medicine_name, r.status as request_status
        FROM notifications n
        LEFT JOIN requests r ON n.related_request_id = r.id
        WHERE n.user_id = ?
    """
    params = [user_id]

    if status_filter == 'unread':
        query += " AND n.is_read = 0"
    elif status_filter == 'read':
        query += " AND n.is_read = 1"

    query += " ORDER BY n.created_at DESC LIMIT ?;"
    params.append(limit)

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    notifications_list = [dict(row) for row in rows]

    # Calculate total unread count for the bell badge
    cursor.execute("SELECT COUNT(*) as unread_count FROM notifications WHERE user_id = ? AND is_read = 0;", (user_id,))
    unread_count = cursor.fetchone()['unread_count']

    conn.close()

    return jsonify({
        'notifications': notifications_list,
        'unread_count': unread_count,
        'filter': status_filter
    }), 200


@notifications_bp.route('/unread-count', methods=['GET'], strict_slashes=False)
@notifications_bp.route('/unread-count/', methods=['GET'], strict_slashes=False)
@login_required
def get_unread_count():
    """
    Quick endpoint for polling unread count to update the navigation bell badge.
    """
    user_id = session.get('user_id')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as unread_count FROM notifications WHERE user_id = ? AND is_read = 0;", (user_id,))
    row = cursor.fetchone()
    conn.close()

    return jsonify({'unread_count': row['unread_count'] if row else 0}), 200


@notifications_bp.route('/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_as_read(notif_id):
    """
    Marks a single notification as read.
    Validates ownership to prevent unauthorized updates.
    """
    user_id = session.get('user_id')
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM notifications WHERE id = ? AND user_id = ?;", (notif_id, user_id))
    notif = cursor.fetchone()

    if not notif:
        conn.close()
        return jsonify({'error': 'Notification not found or access denied.'}), 404

    cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?;", (notif_id, user_id))
    conn.commit()

    cursor.execute("SELECT COUNT(*) as unread_count FROM notifications WHERE user_id = ? AND is_read = 0;", (user_id,))
    unread_count = cursor.fetchone()['unread_count']
    conn.close()

    return jsonify({
        'success': True,
        'message': 'Notification marked as read.',
        'unread_count': unread_count
    }), 200


@notifications_bp.route('/<int:notif_id>/unread', methods=['POST'])
@login_required
def mark_as_unread(notif_id):
    """
    Marks a notification as unread.
    """
    user_id = session.get('user_id')
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM notifications WHERE id = ? AND user_id = ?;", (notif_id, user_id))
    notif = cursor.fetchone()

    if not notif:
        conn.close()
        return jsonify({'error': 'Notification not found or access denied.'}), 404

    cursor.execute("UPDATE notifications SET is_read = 0 WHERE id = ? AND user_id = ?;", (notif_id, user_id))
    conn.commit()

    cursor.execute("SELECT COUNT(*) as unread_count FROM notifications WHERE user_id = ? AND is_read = 0;", (user_id,))
    unread_count = cursor.fetchone()['unread_count']
    conn.close()

    return jsonify({
        'success': True,
        'message': 'Notification marked as unread.',
        'unread_count': unread_count
    }), 200


@notifications_bp.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_as_read():
    """
    Marks all notifications for the authenticated user as read.
    """
    user_id = session.get('user_id')
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0;", (user_id,))
    updated_rows = cursor.rowcount
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message': f'{updated_rows} notifications marked as read.',
        'unread_count': 0
    }), 200


@notifications_bp.route('/<int:notif_id>', methods=['DELETE'])
@login_required
def delete_notification(notif_id):
    """
    Deletes a single notification belonging to the authenticated user.
    """
    user_id = session.get('user_id')
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM notifications WHERE id = ? AND user_id = ?;", (notif_id, user_id))
    notif = cursor.fetchone()

    if not notif:
        conn.close()
        return jsonify({'error': 'Notification not found or access denied.'}), 404

    cursor.execute("DELETE FROM notifications WHERE id = ? AND user_id = ?;", (notif_id, user_id))
    conn.commit()

    cursor.execute("SELECT COUNT(*) as unread_count FROM notifications WHERE user_id = ? AND is_read = 0;", (user_id,))
    unread_count = cursor.fetchone()['unread_count']
    conn.close()

    return jsonify({
        'success': True,
        'message': 'Notification deleted.',
        'unread_count': unread_count
    }), 200
