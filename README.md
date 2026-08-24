# MedConnect

**MedConnect** is a localized healthcare communication platform that connects patients directly with verified neighborhood pharmacies. It enables patients to discover nearby pharmacies within an adjustable geographical search radius, request medicine availability via medicine names or prescription uploads, and view real-time pharmacy responses with direct Google Maps navigation links.

---

## Features

- **Role-Based Authentication & Sessions**: Dedicated roles for Patients, Pharmacies, and System Administrators with secure session management and role-protected routes.
- **Patient Registration & Location Selection**: Interactive Leaflet / OpenStreetMap location picker to set and update patient home or current coordinates.
- **Pharmacy Registration & Verification Workflow**: Pharmacies register with Drug License (DL) numbers, business details, and physical store coordinates, entering a `pending` state until reviewed.
- **Admin Verification Portal**: Administrators review pending pharmacy applications, inspect licenses, verify locations, and approve or reject registrations.
- **Medicine Requests**:
  - Search by medicine name or upload physical prescription documents (PDF, JPG, PNG, WEBP).
  - Configurable search radius (defaults to 5.0 km).
- **Proximity Calculation Engine**: Haversine distance algorithm calculates accurate distances between patients and pharmacies in kilometers.
- **Nearby Pharmacy Discovery & Feed**: Verified pharmacies receive an incoming feed of active requests within their proximity radius.
- **Real-Time Pharmacy Responses**: Pharmacies reply with stock status (*All medicines available*, *Some available*, or *Not available*) and optional notes/substitutes.
- **Dynamic Search Radius Expansion**: Patients can expand their request radius by +5 km increments if immediate nearby stores are out of stock.
- **Google Maps Navigation**: One-click navigation buttons opening Google Maps with directions from the patient's coordinates to the responding pharmacy.
- **Secure File Storage**: Prescription uploads are stored securely and served only to authenticated parties.
- **Zero Heavy Framework Overhead**: Built with pure Python Flask, Jinja2, standard SQLite, vanilla CSS, and vanilla JavaScript.

---

## Technology Stack

- **Backend**: Python 3.10+, Flask 3.x (Blueprints, Sessions, Routing)
- **Security & Hashing**: Werkzeug Security, bcrypt
- **Database**: SQLite 3 (`medconnect.db`, `schema.sql`)
- **Frontend / Templates**: Jinja2 HTML5, Vanilla CSS3 (custom responsive styling), Vanilla JavaScript (ES6+ Fetch API)
- **Mapping & Geocoding**: Leaflet.js, OpenStreetMap tiles, Nominatim reverse geocoding
- **Navigation**: Google Maps Directions API URL format

---

## Project Structure

```
MedConnect/
├── app.py                     # Flask application entry point, session setup & page routes
├── db.py                      # SQLite connection helper & schema initializer
├── utils.py                   # Role decorators, Haversine formula & file upload helpers
├── schema.sql                 # SQLite DDL schema (users, pharmacies, requests, responses)
├── requirements.txt           # Python pip dependencies
├── README.md                  # Project documentation & setup instructions
├── .gitignore                 # Git ignore rules for virtual environments, secrets & uploads
├── .env.example               # Example environment configuration
│
├── routes/                    # Modular Flask Blueprints
│   ├── __init__.py            # Blueprint package initializer
│   ├── auth.py                # Authentication, registration & login endpoints (/api/auth/*)
│   ├── patient.py             # Patient requests & radius expansion endpoints (/api/patient/*)
│   ├── pharmacy.py            # Pharmacy feed & availability responses (/api/pharmacy/*)
│   └── admin.py               # Admin verification & analytics endpoints (/api/admin/*)
│
├── templates/                 # Jinja2 HTML Templates
│   ├── base.html              # Base layout with responsive navigation & footer
│   ├── index.html             # Landing page with role overview
│   ├── login.html             # Unified login portal
│   ├── register.html          # Patient and Pharmacy registration with Leaflet map
│   ├── patient_dashboard.html # Patient dashboard for managing inquiries & responses
│   ├── pharmacy_dashboard.html# Pharmacy dashboard for reviewing nearby requests
│   └── admin_dashboard.html   # Admin portal for approving pharmacy licenses
│
├── static/                    # Frontend Static Assets
│   ├── css/
│   │   └── style.css          # Vanilla CSS stylesheet
│   └── js/
│       ├── auth.js            # Auth forms & registration map picker logic
│       ├── patient.js         # Patient dashboard, map markers & request handlers
│       ├── pharmacy.js        # Pharmacy dashboard feed & response submission
│       └── admin.js           # Admin approval/rejection actions & statistics
│
└── uploads/                   # Local directory for user prescription documents
    └── .gitkeep               # Preserves directory structure in version control
```

---

## Local Setup & Installation

### Prerequisites
- Python 3.10 or higher installed on your system
- VS Code (or your preferred IDE)

---

### Windows (VS Code / PowerShell)

1. Open the project folder in VS Code:
   ```powershell
   cd path\to\MedConnect
   ```

2. Create a virtual environment:
   ```powershell
   python -m venv venv
   ```

3. Activate the virtual environment:
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
   *(If script execution is disabled, run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`)*

4. Install the required Python packages:
   ```powershell
   pip install -r requirements.txt
   ```

5. (Optional) Create your local environment file:
   ```powershell
   Copy-Item .env.example .env
   ```

6. Run the Flask application:
   ```powershell
   python app.py
   ```

7. Open your browser and navigate to:
   ```
   http://127.0.0.1:5000
   ```
   *(Or the port displayed in your terminal output)*

---

### macOS / Linux (Terminal)

1. Open the terminal and navigate to the project directory:
   ```bash
   cd /path/to/MedConnect
   ```

2. Create a virtual environment:
   ```bash
   python3 -m venv venv
   ```

3. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. (Optional) Copy the environment configuration:
   ```bash
   cp .env.example .env
   ```

6. Start the Flask server:
   ```bash
   python3 app.py
   ```

7. Open your browser and visit:
   ```
   http://127.0.0.1:5000
   ```

---

## Environment Variables

Copy `.env.example` to create your local `.env` file:
```bash
cp .env.example .env
```

| Variable | Description | Default |
| :--- | :--- | :--- |
| `SECRET_KEY` | Flask cryptographic session key | `medconnect-secret-session-key-dev-12345` |
| `PORT` | Local server port to bind | `5000` (or `3000` in container) |
| `HOST` | Local host interface | `0.0.0.0` or `127.0.0.1` |
| `FLASK_ENV` | Flask environment mode | `development` |

---

## Database

MedConnect utilizes an embedded **SQLite 3** database (`medconnect.db`).
- On initial launch, `db.py` executes `schema.sql` to create all required tables:
  1. `users` (Patients, Pharmacies, Admins)
  2. `pharmacies` (Store details, Drug License number, approval status)
  3. `requests` (Medicine inquiries and prescription links)
  4. `responses` (Pharmacy stock status and notes)
- A default System Administrator account is automatically provisioned if no admin exists:
  - **Email**: `admin@medconnect.local`
  - **Password**: `admin123` *(change in production)*

---

## Prescription Uploads & Privacy

Uploaded prescription files are stored locally in the `uploads/` directory.
- Prescriptions are sensitive medical documents and are ignored by `.gitignore` (`uploads/*`).
- The `uploads/.gitkeep` file ensures the folder structure is preserved in GitHub without tracking private files.
