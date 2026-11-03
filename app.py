import os
import argparse
from flask import Flask, render_template, session, redirect, url_for

from db import init_db
from utils import role_required, login_required, UPLOAD_FOLDER
from routes.auth import auth_bp
from routes.patient import patient_bp
from routes.pharmacy import pharmacy_bp
from routes.admin import admin_bp
from routes.notifications import notifications_bp

# 1. Create the Flask app
app = Flask(__name__)

# 2. Set the secret key
app.secret_key = os.environ.get('SECRET_KEY') or 'medconnect-dev-secret-key-2026'

# 3. Create the uploads directory
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 4. Initialize the database
with app.app_context():
    init_db()

# 5. Register the Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(patient_bp)
app.register_blueprint(pharmacy_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(notifications_bp)

# 6. HTML Page Routes
@app.route('/')
def index():
    """Landing Page with overview and quick links to user roles."""
    return render_template('index.html')


@app.route('/login')
def login_page():
    """Unified login page for Patients, Pharmacies, and Admins."""
    if 'user_id' in session:
        role = session.get('role')
        if role == 'patient':
            return redirect(url_for('patient_dashboard'))
        elif role == 'pharmacy':
            return redirect(url_for('pharmacy_dashboard'))
        elif role == 'admin':
            return redirect(url_for('admin_dashboard'))
    return render_template('login.html')


@app.route('/register')
def register_page():
    """Registration page for Patients and Pharmacies."""
    if 'user_id' in session:
        return redirect(url_for('login_page'))
    return render_template('register.html')


@app.route('/patient/dashboard')
@role_required('patient')
def patient_dashboard():
    """Patient Dashboard with request creator, active inquiries, and embedded health disclaimer."""
    return render_template('patient_dashboard.html')


@app.route('/pharmacy/dashboard')
@role_required('pharmacy')
def pharmacy_dashboard():
    """Pharmacy Dashboard showing nearby patient requests and response management."""
    return render_template('pharmacy_dashboard.html')


@app.route('/admin/login')
def admin_login_page():
    """Non-public administrative login route."""
    if 'user_id' in session:
        role = session.get('role')
        if role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('index'))
    return render_template('login.html', is_admin_portal=True)


@app.route('/admin')
def admin_root():
    """Redirects /admin to dashboard if authenticated admin, or /admin/login if not."""
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('admin_login_page'))


@app.route('/admin/dashboard')
@role_required('admin')
def admin_dashboard():
    """Admin Dashboard for reviewing pending pharmacy registrations and system activity."""
    return render_template('admin_dashboard.html')


@app.route('/notifications')
@login_required
def notifications_page():
    """Dedicated Notifications Page showing all user alerts and history."""
    return render_template('notifications.html')


# 7. Start the Flask server
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="MedConnect Flask Server")
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 3000)), help="Port to bind")
    parser.add_argument('--host', type=str, default='0.0.0.0', help="Host to bind")
    args, _ = parser.parse_known_args()

    print(f"[*] Starting MedConnect Flask Server on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)
