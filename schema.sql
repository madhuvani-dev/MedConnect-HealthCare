-- MedConnect SQLite Database Schema
-- Exactly 4 Tables: users, pharmacies, requests, responses

-- 1. Users Table (Patients, Pharmacy accounts, Admins)
-- Stores credentials, role, and patient coordinates
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('patient', 'pharmacy', 'admin')),
    latitude REAL,          -- Patient latitude coordinate
    longitude REAL,         -- Patient longitude coordinate
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Pharmacies Table
-- Stores pharmacy-specific verification info, Drug License (DL), address, status, and pharmacy coordinates
CREATE TABLE IF NOT EXISTS pharmacies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    pharmacy_name TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    dl_number TEXT UNIQUE NOT NULL,  -- Drug License number
    address TEXT NOT NULL,
    latitude REAL NOT NULL,          -- Pharmacy latitude coordinate
    longitude REAL NOT NULL,         -- Pharmacy longitude coordinate
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 3. Requests Table
-- Stores medicine availability queries initiated by patients (Prescription or Medicine Name)
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    request_type TEXT NOT NULL CHECK(request_type IN ('prescription', 'medicine_name')),
    medicine_name TEXT,              -- Entered medicine name if request_type is 'medicine_name'
    prescription_file TEXT,          -- Filename stored in uploads/ if request_type is 'prescription'
    patient_lat REAL NOT NULL,       -- Patient latitude at time of request
    patient_lng REAL NOT NULL,       -- Patient longitude at time of request
    search_radius_km REAL NOT NULL DEFAULT 5.0,  -- Initial search radius (5.0 km)
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 4. Responses Table
-- Stores availability responses submitted by verified pharmacies
CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    pharmacy_id INTEGER NOT NULL,
    availability_status TEXT NOT NULL CHECK(availability_status IN ('all_available', 'some_available', 'not_available')),
    notes TEXT,                      -- Optional remarks or alternate options
    distance_km REAL NOT NULL,       -- Calculated distance between patient and pharmacy
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,
    FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id) ON DELETE CASCADE,
    UNIQUE(request_id, pharmacy_id)  -- One response per pharmacy per request
);
