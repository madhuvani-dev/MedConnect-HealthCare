from .auth import auth_bp
from .patient import patient_bp
from .pharmacy import pharmacy_bp
from .admin import admin_bp

__all__ = ['auth_bp', 'patient_bp', 'pharmacy_bp', 'admin_bp']
