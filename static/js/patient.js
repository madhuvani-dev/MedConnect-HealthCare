/**
 * MedConnect - Patient Portal JavaScript
 *
 * Handles:
 * - Patient profile & coordinates setup (GPS / Manual)
 * - Prescription uploads & Medicine name requests
 * - Real-time request polling and radius expansion
 * - "Nearby Verified Pharmacies" discovery modal
 * - Interactive Leaflet map with directions & Google Maps navigation
 */

let currentPatientLocation = { lat: null, lng: null };
let activeRequestsCache = [];
let currentViewingReqId = null;

// Leaflet map instance and markers for the pharmacy discovery modal
let pharmacyMap = null;
let patientMarker = null;
let pharmacyMarkers = [];
let isMapVisible = false;

// Leaflet map instance and state for the Location Update modal
let dashLocationMap = null;
let dashLocationMarker = null;
let tempSelectedLocation = { lat: null, lng: null, address: '' };

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    initPatientDashboard();
  });
} else {
  initPatientDashboard();
}

async function initPatientDashboard() {
  // 1. Load patient profile & coordinates
  await loadPatientProfile();

  // 2. Setup request creation forms
  setupRequestForms();

  // 3. Load existing requests
  await loadPatientRequests();

  // 4. Periodically refresh requests every 10 seconds
  setInterval(async () => {
    await loadPatientRequests();
    // If modal is currently open, refresh the modal view to show any new responses in real time
    if (currentViewingReqId) {
      await refreshResponsesModalSilently(currentViewingReqId);
    }
  }, 10000);
}

/* =========================================================
   GEOCODING & REVERSE GEOCODING HELPERS
   ========================================================= */

async function reverseGeocodeCoords(lat, lng) {
  try {
    const url = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lng)}&zoom=18&addressdetails=1`;
    const res = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error('Geocoding service error');
    const data = await res.json();
    if (data && (data.display_name || data.address)) {
      const addr = data.address || {};
      const parts = [];
      const primary = addr.road || addr.suburb || addr.neighbourhood || addr.residential || addr.commercial;
      if (primary) parts.push(primary);
      const locality = addr.city || addr.town || addr.village || addr.county || addr.district;
      if (locality && !parts.includes(locality)) parts.push(locality);
      const state = addr.state;
      if (state && !parts.includes(state)) parts.push(state);
      const country = addr.country;
      if (country && !parts.includes(country)) parts.push(country);

      if (parts.length >= 2) {
        return parts.join(', ');
      }
      return data.display_name;
    }
  } catch (err) {
    console.warn('Reverse geocoding error:', err);
  }
  return null;
}

async function searchLocationQuery(query) {
  try {
    const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1&addressdetails=1`;
    const res = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error('Search request failed');
    const results = await res.json();
    if (results && results.length > 0) {
      const item = results[0];
      const lat = parseFloat(item.lat);
      const lng = parseFloat(item.lon);
      let displayName = item.display_name;

      const addr = item.address || {};
      const parts = [];
      const primary = addr.road || addr.suburb || addr.neighbourhood || addr.residential || addr.commercial;
      if (primary) parts.push(primary);
      const locality = addr.city || addr.town || addr.village || addr.county || addr.district;
      if (locality && !parts.includes(locality)) parts.push(locality);
      const state = addr.state;
      if (state && !parts.includes(state)) parts.push(state);
      const country = addr.country;
      if (country && !parts.includes(country)) parts.push(country);

      if (parts.length >= 2) {
        displayName = parts.join(', ');
      }

      return { lat, lng, displayName };
    }
  } catch (err) {
    console.warn('Location search error:', err);
  }
  return null;
}

/* =========================================================
   PATIENT PROFILE & LOCATION MANAGEMENT
   ========================================================= */

async function loadPatientProfile() {
  try {
    const res = await fetch('/api/auth/me');
    const data = await res.json();

    if (data.authenticated && data.user) {
      const nameElement = document.getElementById('patient-display-name');
      if (nameElement) {
        nameElement.textContent = data.user.name;
      }

      if (
        data.user.latitude !== null &&
        data.user.latitude !== undefined &&
        data.user.longitude !== null &&
        data.user.longitude !== undefined
      ) {
        currentPatientLocation.lat = parseFloat(data.user.latitude);
        currentPatientLocation.lng = parseFloat(data.user.longitude);
        await updateLocationUI(currentPatientLocation.lat, currentPatientLocation.lng);
      } else {
        showLocationPrompt();
      }
    }
  } catch (e) {
    console.error('Failed to load patient profile:', e);
  }
}

async function updateLocationUI(lat, lng, knownAddress = null) {
  const locBadge = document.getElementById('location-status-badge');
  const locAddress = document.getElementById('current-location-address');

  if (locBadge) {
    locBadge.className = 'badge badge-approved';
    locBadge.textContent = 'Location Set';
  }

  if (locAddress) {
    if (knownAddress) {
      locAddress.textContent = knownAddress;
    } else {
      locAddress.textContent = 'Fetching address...';
      const address = await reverseGeocodeCoords(lat, lng);
      locAddress.textContent = address || `Registered Location (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
    }
  }
}

function showLocationPrompt() {
  const locBadge = document.getElementById('location-status-badge');
  const locAddress = document.getElementById('current-location-address');

  if (locBadge) {
    locBadge.className = 'badge badge-pending';
    locBadge.textContent = 'Location Not Set';
  }
  if (locAddress) {
    locAddress.textContent = 'No location registered yet. Click "Update Location" to choose your area.';
  }
}

/* =========================================================
   UPDATE LOCATION MODAL
   ========================================================= */

function openLocationModal() {
  const modalBackdrop = document.getElementById('location-modal-backdrop');
  if (!modalBackdrop) return;

  modalBackdrop.classList.add('open');

  const defaultLat = currentPatientLocation.lat || 17.3850;
  const defaultLng = currentPatientLocation.lng || 78.4867;

  tempSelectedLocation.lat = defaultLat;
  tempSelectedLocation.lng = defaultLng;

  setTimeout(() => {
    initOrUpdateDashMap(defaultLat, defaultLng);
  }, 150);
}

function closeLocationModal() {
  const modalBackdrop = document.getElementById('location-modal-backdrop');
  if (modalBackdrop) {
    modalBackdrop.classList.remove('open');
  }
  const alertBox = document.getElementById('dash-modal-loc-alert');
  if (alertBox) alertBox.style.display = 'none';
}

function initOrUpdateDashMap(lat, lng) {
  const mapElem = document.getElementById('dash-location-map');
  if (!mapElem || typeof L === 'undefined') return;

  if (!dashLocationMap) {
    dashLocationMap = L.map('dash-location-map').setView([lat, lng], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(dashLocationMap);

    dashLocationMap.on('click', async (e) => {
      await setDashModalLocation(e.latlng.lat, e.latlng.lng);
    });

    setupDashModalControls();
  } else {
    dashLocationMap.invalidateSize();
    dashLocationMap.setView([lat, lng], 14);
  }

  setDashModalLocation(lat, lng);
}

async function setDashModalLocation(lat, lng, explicitAddress = null) {
  tempSelectedLocation.lat = parseFloat(lat);
  tempSelectedLocation.lng = parseFloat(lng);

  if (!dashLocationMarker) {
    dashLocationMarker = L.marker([lat, lng], { draggable: true }).addTo(dashLocationMap);
    dashLocationMarker.on('dragend', async (e) => {
      const pos = e.target.getLatLng();
      await setDashModalLocation(pos.lat, pos.lng);
    });
  } else {
    dashLocationMarker.setLatLng([lat, lng]);
  }

  const addressElem = document.getElementById('dash-selected-address-text');
  if (addressElem) {
    if (explicitAddress) {
      tempSelectedLocation.address = explicitAddress;
      addressElem.textContent = explicitAddress;
    } else {
      addressElem.textContent = 'Fetching address...';
      const addr = await reverseGeocodeCoords(lat, lng);
      const display = addr || `${parseFloat(lat).toFixed(4)}, ${parseFloat(lng).toFixed(4)}`;
      tempSelectedLocation.address = display;
      addressElem.textContent = display;
    }
  }
}

function setupDashModalControls() {
  const searchInput = document.getElementById('dash-modal-loc-search');
  const searchBtn = document.getElementById('btn-dash-search-loc');
  const feedback = document.getElementById('dash-loc-feedback');

  const doSearch = async () => {
    if (!searchInput) return;
    const query = searchInput.value.trim();
    if (!query) return;

    if (searchBtn) {
      searchBtn.disabled = true;
      searchBtn.textContent = 'Searching...';
    }

    const res = await searchLocationQuery(query);
    if (searchBtn) {
      searchBtn.disabled = false;
      searchBtn.textContent = '🔍 Search';
    }

    if (res) {
      dashLocationMap.setView([res.lat, res.lng], 15);
      await setDashModalLocation(res.lat, res.lng, res.displayName);
      if (feedback) feedback.textContent = '';
    } else {
      if (feedback) {
        feedback.textContent = 'Location not found. Please try another place name.';
        feedback.style.color = 'var(--danger)';
      }
    }
  };

  if (searchBtn) {
    searchBtn.addEventListener('click', doSearch);
  }
  if (searchInput) {
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        doSearch();
      }
    });
  }

  const btnDetect = document.getElementById('btn-dash-detect-loc');
  if (btnDetect) {
    btnDetect.addEventListener('click', () => {
      if (!navigator.geolocation) {
        if (feedback) {
          feedback.textContent = 'Geolocation is not supported by your browser.';
          feedback.style.color = 'var(--danger)';
        }
        return;
      }

      const orig = btnDetect.textContent;
      btnDetect.textContent = '⏳ Detecting...';
      btnDetect.disabled = true;

      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const lat = pos.coords.latitude;
          const lng = pos.coords.longitude;
          dashLocationMap.setView([lat, lng], 15);
          await setDashModalLocation(lat, lng);
          btnDetect.textContent = orig;
          btnDetect.disabled = false;
          if (feedback) {
            feedback.textContent = '📍 Current location detected.';
            feedback.style.color = 'var(--success)';
          }
        },
        (err) => {
          console.warn('Dashboard geolocation error:', err);
          btnDetect.textContent = orig;
          btnDetect.disabled = false;
          if (feedback) {
            feedback.textContent = 'Location permission was denied. You can search or select on the map.';
            feedback.style.color = 'var(--danger)';
          }
        },
        { enableHighAccuracy: true, timeout: 10000 }
      );
    });
  }
}

async function saveUpdatedPatientLocation() {
  if (tempSelectedLocation.lat === null || tempSelectedLocation.lng === null) {
    alert('Please select a valid location on the map first.');
    return;
  }

  const saveBtn = document.getElementById('btn-dash-save-location');
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
  }

  try {
    const res = await fetch('/api/patient/location', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        latitude: tempSelectedLocation.lat,
        longitude: tempSelectedLocation.lng
      })
    });

    const data = await res.json();
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Location';
    }

    if (res.ok) {
      currentPatientLocation.lat = tempSelectedLocation.lat;
      currentPatientLocation.lng = tempSelectedLocation.lng;
      await updateLocationUI(currentPatientLocation.lat, currentPatientLocation.lng, tempSelectedLocation.address);
      closeLocationModal();
    } else {
      const alertBox = document.getElementById('dash-modal-loc-alert');
      if (alertBox) {
        alertBox.className = 'alert alert-danger';
        alertBox.textContent = data.error || 'Failed to update location.';
        alertBox.style.display = 'block';
      }
    }
  } catch (err) {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Location';
    }
    console.error('Error saving updated location:', err);
  }
}

/* =========================================================
   REQUEST CREATION FORMS
   ========================================================= */

function setupRequestForms() {
  const tabRx = document.getElementById('tab-req-rx');
  const tabName = document.getElementById('tab-req-name');
  const formRx = document.getElementById('form-prescription-section');
  const formName = document.getElementById('form-medicine-section');

  if (tabRx && tabName && formRx && formName) {
    tabRx.addEventListener('click', () => {
      tabRx.classList.add('active');
      tabName.classList.remove('active');
      formRx.classList.add('active');
      formName.classList.remove('active');
    });

    tabName.addEventListener('click', () => {
      tabName.classList.add('active');
      tabRx.classList.remove('active');
      formName.classList.add('active');
      formRx.classList.remove('active');
    });
  }

  // Prescription Upload Form
  const formPrescription = document.getElementById('form-prescription-upload');
  if (formPrescription) {
    formPrescription.addEventListener('submit', async (e) => {
      e.preventDefault();

      if (currentPatientLocation.lat === null || currentPatientLocation.lng === null) {
        alert('Please set or detect your location first so nearby verified pharmacies can receive your request.');
        return;
      }

      const fileInput = document.getElementById('prescription-file');
      if (!fileInput.files || fileInput.files.length === 0) {
        alert('Please select a prescription document or image to upload.');
        return;
      }

      const formData = new FormData();
      formData.append('request_type', 'prescription');
      formData.append('prescription_file', fileInput.files[0]);
      formData.append('latitude', currentPatientLocation.lat);
      formData.append('longitude', currentPatientLocation.lng);

      const submitBtn = document.getElementById('btn-submit-rx');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Broadcasting to nearby pharmacies...';

      try {
        const res = await fetch('/api/patient/requests', {
          method: 'POST',
          body: formData
        });
        const data = await res.json();

        if (res.ok) {
          alert('Prescription submitted! Request broadcasted to verified pharmacies within 5.0 km.');
          formPrescription.reset();
          await loadPatientRequests();
          if (data.request && data.request.id) {
            viewResponsesModal(data.request.id);
          }
        } else {
          alert(data.error || 'Failed to submit prescription request.');
        }
      } catch (err) {
        console.error(err);
        alert('Error uploading prescription.');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Broadcast Prescription Request (5 km Radius)';
      }
    });
  }

  // Medicine Name Form
  const formMedName = document.getElementById('form-medicine-name');
  if (formMedName) {
    formMedName.addEventListener('submit', async (e) => {
      e.preventDefault();

      if (currentPatientLocation.lat === null || currentPatientLocation.lng === null) {
        alert('Please set or detect your location first so nearby verified pharmacies can be reached.');
        return;
      }

      const medInput = document.getElementById('medicine-name-input');
      const medName = medInput.value.trim();

      if (!medName) {
        alert('Please enter a medicine name.');
        return;
      }

      const submitBtn = document.getElementById('btn-submit-med');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Broadcasting inquiry...';

      try {
        const res = await fetch('/api/patient/requests', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            request_type: 'medicine_name',
            medicine_name: medName,
            latitude: currentPatientLocation.lat,
            longitude: currentPatientLocation.lng
          })
        });
        const data = await res.json();

        if (res.ok) {
          alert(`Inquiry for "${medName}" broadcasted to verified pharmacies within 5.0 km!`);
          formMedName.reset();
          await loadPatientRequests();
          if (data.request && data.request.id) {
            viewResponsesModal(data.request.id);
          }
        } else {
          alert(data.error || 'Failed to submit medicine request.');
        }
      } catch (err) {
        console.error(err);
        alert('Error submitting inquiry.');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Check Availability Nearby (5 km Radius)';
      }
    });
  }
}

/* =========================================================
   LOAD PATIENT REQUESTS TABLE
   ========================================================= */

async function loadPatientRequests() {
  try {
    const res = await fetch('/api/patient/requests');
    const data = await res.json();

    const tableBody = document.getElementById('patient-requests-tbody');
    const emptyState = document.getElementById('no-requests-message');

    if (!tableBody) return;

    if (!data.requests || data.requests.length === 0) {
      tableBody.innerHTML = '';
      if (emptyState) emptyState.style.display = 'block';
      return;
    }

    if (emptyState) emptyState.style.display = 'none';
    activeRequestsCache = data.requests;

    let rowsHtml = '';

    data.requests.forEach((req) => {
      const isRx = req.request_type === 'prescription';

      const itemTitle = isRx
        ? `<span style="font-weight: 600;">Prescription Document</span> (<a href="/uploads/prescriptions/${escapeHtml(req.prescription_file)}" target="_blank" class="btn-link" style="text-decoration: underline;">View File</a>)`
        : `<span style="font-weight: 600;">${escapeHtml(req.medicine_name)}</span>`;

      let statusBadge = `<span class="badge badge-approved">Active</span>`;
      if (req.status === 'completed') {
        statusBadge = `<span class="badge badge-neutral">Completed</span>`;
      } else if (req.status === 'cancelled') {
        statusBadge = `<span class="badge badge-rejected">Cancelled</span>`;
      }

      let responseSummary = '';
      if (req.response_count === 0) {
        responseSummary = `<span class="badge badge-pending">Waiting for responses</span>`;
      } else {
        responseSummary = `
          <div style="display: flex; gap: 4px; flex-wrap: wrap;">
            <span class="badge badge-neutral">${req.response_count} Response${req.response_count > 1 ? 's' : ''}</span>
            ${req.all_available_count > 0 ? `<span class="badge badge-all">${req.all_available_count} All Avail</span>` : ''}
            ${req.some_available_count > 0 ? `<span class="badge badge-some">${req.some_available_count} Some Avail</span>` : ''}
            ${req.not_available_count > 0 ? `<span class="badge badge-none">${req.not_available_count} Not Avail</span>` : ''}
          </div>
        `;
      }

      const dateFormatted = new Date(req.created_at).toLocaleString();

      rowsHtml += `
        <tr>
          <td><strong>#${req.id}</strong></td>
          <td>
            ${isRx ? '<span class="badge badge-some">Prescription</span>' : '<span class="badge badge-neutral">Medicine Name</span>'}
          </td>
          <td>${itemTitle}</td>
          <td>
            <div style="display: flex; align-items: center; gap: 6px;">
              <span>${req.search_radius_km} km</span>
              ${
                req.status === 'active'
                  ? `<button onclick="expandRadius(${req.id})" class="btn btn-sm btn-outline" title="Expand search radius by +5 km">+5 km</button>`
                  : ''
              }
            </div>
          </td>
          <td>${responseSummary}</td>
          <td><small class="text-muted">${dateFormatted}</small></td>
          <td>${statusBadge}</td>
          <td>
            <div style="display: flex; gap: 6px;">
              <button onclick="viewResponsesModal(${req.id})" class="btn btn-sm btn-primary">
                View Pharmacies
              </button>
              ${
                req.status === 'active'
                  ? `<button onclick="closeRequest(${req.id})" class="btn btn-sm btn-secondary" title="Mark request completed">Done</button>`
                  : ''
              }
            </div>
          </td>
        </tr>
      `;
    });

    tableBody.innerHTML = rowsHtml;
  } catch (err) {
    console.error('Error fetching patient requests:', err);
  }
}

/* =========================================================
   EXPAND SEARCH RADIUS & CLOSE REQUEST
   ========================================================= */

async function expandRadius(reqId) {
  try {
    const res = await fetch(`/api/patient/requests/${reqId}/expand-radius`, {
      method: 'POST'
    });
    const data = await res.json();

    if (res.ok) {
      alert(data.message);
      await loadPatientRequests();
      // If modal is open for this request, refresh its contents immediately
      if (currentViewingReqId === reqId) {
        await viewResponsesModal(reqId);
      }
    } else {
      alert(data.error || 'Failed to expand radius.');
    }
  } catch (err) {
    console.error(err);
    alert('Error connecting to server.');
  }
}

async function closeRequest(reqId) {
  if (!confirm('Mark this request as completed?')) {
    return;
  }

  try {
    const res = await fetch(`/api/patient/requests/${reqId}/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'completed' })
    });

    if (res.ok) {
      await loadPatientRequests();
      if (currentViewingReqId === reqId) {
        await viewResponsesModal(reqId);
      }
    }
  } catch (err) {
    console.error(err);
    alert('Error closing request.');
  }
}

/* =========================================================
   NEARBY VERIFIED PHARMACIES & MAP MODAL
   ========================================================= */

async function viewResponsesModal(reqId) {
  currentViewingReqId = reqId;

  const modalBackdrop = document.getElementById('responses-modal-backdrop');
  const modalContent = document.getElementById('modal-responses-list');
  const modalHeaderTitle = document.getElementById('modal-request-title');
  const modalSubtitle = document.getElementById('modal-request-subtitle');
  const modalStats = document.getElementById('modal-pharmacy-stats');
  const btnModalExpand = document.getElementById('btn-modal-expand-radius');

  if (!modalBackdrop || !modalContent) return;

  modalContent.innerHTML = `
    <div class="empty-state" style="padding: 24px;">
      <p>🔍 Finding verified pharmacies near your coordinates...</p>
    </div>
  `;

  modalBackdrop.classList.add('open');

  try {
    const res = await fetch(`/api/patient/requests/${reqId}/responses`);
    const data = await res.json();

    if (!res.ok) {
      modalContent.innerHTML = `
        <div class="alert alert-danger">
          ${data.error || 'Failed to load pharmacy details.'}
        </div>
      `;
      return;
    }

    const req = data.request;
    const pharmacies = data.pharmacies || data.responses || [];

    if (modalHeaderTitle) {
      modalHeaderTitle.textContent =
        req.request_type === 'prescription'
          ? `Prescription Request #${req.id} — Nearby Pharmacies`
          : `Medicine: "${req.medicine_name}" — Nearby Pharmacies`;
    }

    if (modalSubtitle) {
      modalSubtitle.textContent = `Current Search Radius: ${req.search_radius_km} km • Status: ${req.status.toUpperCase()}`;
    }

    // Configure Expand Radius button in modal
    if (btnModalExpand) {
      if (req.status === 'active') {
        btnModalExpand.style.display = 'inline-flex';
        btnModalExpand.textContent = `+5 km (Now ${req.search_radius_km} km)`;
        btnModalExpand.onclick = () => expandRadius(req.id);
      } else {
        btnModalExpand.style.display = 'none';
      }
    }

    const respondedCount = pharmacies.filter((p) => p.has_responded).length;
    const totalNearby = pharmacies.length;

    if (modalStats) {
      modalStats.innerHTML = `
        <strong>${totalNearby} verified ${totalNearby === 1 ? 'pharmacy' : 'pharmacies'}</strong> found within <strong>${req.search_radius_km} km</strong>
        &bull; <span style="color: ${respondedCount > 0 ? 'var(--success)' : 'var(--warning)'};">${respondedCount} responded</span>
      `;
    }

    // Render Leaflet Map Markers
    renderPharmacyMap(req, pharmacies);

    // Empty state if no verified pharmacies exist in the current radius
    if (pharmacies.length === 0) {
      modalContent.innerHTML = `
        <div class="empty-state" style="padding: 30px;">
          <div class="empty-state-icon">⏳</div>
          <h4 style="margin-bottom: 8px;">No Verified Pharmacies Found in ${req.search_radius_km} km</h4>
          <p class="text-muted" style="margin-bottom: 16px; max-width: 480px; margin-left: auto; margin-right: auto;">
            We couldn't find any approved pharmacies within ${req.search_radius_km} km of your request coordinates.
            Expand the search radius to broadcast your request to pharmacies located further away.
          </p>
          ${
            req.status === 'active'
              ? `<button onclick="expandRadius(${req.id})" class="btn btn-primary">
                  🔍 Expand Search Radius (+5 km)
                </button>`
              : ''
          }
        </div>
      `;
      return;
    }

    // Render Pharmacy Cards
    let itemsHtml = '';

    pharmacies.forEach((p) => {
      let statusBadge = '';
      if (p.has_responded) {
        if (p.availability_status === 'all_available') {
          statusBadge = `<span class="badge badge-all">🟢 All Available</span>`;
        } else if (p.availability_status === 'some_available') {
          statusBadge = `<span class="badge badge-some">🟠 Some Available</span>`;
        } else {
          statusBadge = `<span class="badge badge-none">🔴 Not Available</span>`;
        }
      } else {
        statusBadge = `<span class="badge badge-pending">🟡 Awaiting Response</span>`;
      }

      const hasCoordinates =
        p.latitude !== null &&
        p.latitude !== undefined &&
        p.longitude !== null &&
        p.longitude !== undefined;

      // Google Maps directions URL (origin = patient lat/lng, destination = pharmacy lat/lng)
      let navigationUrl = '#';
      if (hasCoordinates) {
        if (req.patient_lat && req.patient_lng) {
          navigationUrl = `https://www.google.com/maps/dir/?api=1&origin=${req.patient_lat},${req.patient_lng}&destination=${p.latitude},${p.longitude}&travelmode=driving`;
        } else if (currentPatientLocation.lat && currentPatientLocation.lng) {
          navigationUrl = `https://www.google.com/maps/dir/?api=1&origin=${currentPatientLocation.lat},${currentPatientLocation.lng}&destination=${p.latitude},${p.longitude}&travelmode=driving`;
        } else {
          navigationUrl = `https://www.google.com/maps/dir/?api=1&destination=${p.latitude},${p.longitude}&travelmode=driving`;
        }
      }

      itemsHtml += `
        <div class="card" style="margin-bottom: 14px; padding: 18px; border: 1px solid var(--border-color); border-left: 4px solid ${p.has_responded ? 'var(--primary)' : '#f59e0b'};">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; gap: 12px; flex-wrap: wrap;">
            <div>
              <h4 style="color: var(--primary-dark); font-size: 1.1rem; margin-bottom: 2px;">
                🏪 ${escapeHtml(p.pharmacy_name)}
              </h4>
              <p style="font-size: 0.85rem; color: var(--text-muted); margin: 0;">
                Proprietor: <strong>${escapeHtml(p.owner_name)}</strong> &nbsp;|&nbsp; DL No: <strong>${escapeHtml(p.dl_number)}</strong>
              </p>
            </div>
            <div>
              ${statusBadge}
            </div>
          </div>

          <div style="font-size: 0.9rem; margin-bottom: 10px; color: var(--text-main);">
            <p style="margin-bottom: 4px;">
              <strong>📍 Address:</strong> ${escapeHtml(p.address)}
            </p>
            <div style="display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin-top: 6px;">
              <span class="badge badge-neutral">
                📏 ${p.distance_km} km away
              </span>
              ${
                p.phone
                  ? `<span><strong>📞 Phone:</strong> <a href="tel:${escapeHtml(p.phone)}" style="font-weight: 600;">${escapeHtml(p.phone)}</a></span>`
                  : ''
              }
            </div>
          </div>

          ${
            p.notes
              ? `
                <div style="background: var(--bg-muted); padding: 8px 12px; border-radius: var(--radius-sm); font-size: 0.88rem; margin-bottom: 12px; border: 1px solid var(--border-color);">
                  <strong style="color: var(--primary-dark);">💬 Pharmacy Remarks:</strong> ${escapeHtml(p.notes)}
                </div>
              `
              : ''
          }

          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border-color);">
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
              ${
                hasCoordinates
                  ? `
                    <button type="button" class="btn btn-sm btn-outline" onclick="focusPharmacyOnMap(${p.latitude}, ${p.longitude}, '${escapeJsString(p.pharmacy_name)}')">
                      🗺️ View on Map
                    </button>
                    <a href="${navigationUrl}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-primary">
                      🧭 Navigate (Google Maps)
                    </a>
                  `
                  : ''
              }
              ${
                p.phone
                  ? `
                    <a href="tel:${escapeHtml(p.phone)}" class="btn btn-sm btn-secondary">
                      📞 Call Pharmacy
                    </a>
                  `
                  : ''
              }
            </div>

            <div style="font-size: 0.75rem; color: var(--text-light);">
              ${
                p.has_responded && p.created_at
                  ? `Replied: ${new Date(p.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
                  : `Broadcasted within ${req.search_radius_km} km`
              }
            </div>
          </div>
        </div>
      `;
    });

    modalContent.innerHTML = itemsHtml;
  } catch (err) {
    console.error('Error loading request responses:', err);
    modalContent.innerHTML = `
      <div class="alert alert-danger">
        Error retrieving pharmacy details. Please try again.
      </div>
    `;
  }
}

/**
 * Silently refreshes the modal if it is already open (called by background interval)
 */
async function refreshResponsesModalSilently(reqId) {
  const modalBackdrop = document.getElementById('responses-modal-backdrop');
  if (!modalBackdrop || !modalBackdrop.classList.contains('open')) return;

  try {
    const res = await fetch(`/api/patient/requests/${reqId}/responses`);
    if (!res.ok) return;
    const data = await res.json();
    const req = data.request;
    const pharmacies = data.pharmacies || data.responses || [];

    const modalStats = document.getElementById('modal-pharmacy-stats');
    const respondedCount = pharmacies.filter((p) => p.has_responded).length;
    const totalNearby = pharmacies.length;

    if (modalStats) {
      modalStats.innerHTML = `
        <strong>${totalNearby} verified ${totalNearby === 1 ? 'pharmacy' : 'pharmacies'}</strong> found within <strong>${req.search_radius_km} km</strong>
        &bull; <span style="color: ${respondedCount > 0 ? 'var(--success)' : 'var(--warning)'};">${respondedCount} responded</span>
      `;
    }
  } catch (e) {
    // Ignore background polling errors
  }
}

/* =========================================================
   INTERACTIVE MAP ENGINE
   ========================================================= */

function togglePharmacyMap() {
  const mapWrapper = document.getElementById('pharmacy-map-wrapper');
  const btnToggle = document.getElementById('btn-toggle-map');

  if (!mapWrapper) return;

  if (mapWrapper.style.display === 'none' || mapWrapper.style.display === '') {
    mapWrapper.style.display = 'block';
    isMapVisible = true;
    if (btnToggle) btnToggle.textContent = '🗺️ Hide Map';

    if (!pharmacyMap) {
      initModalMap();
    } else {
      setTimeout(() => {
        pharmacyMap.invalidateSize();
      }, 150);
    }
  } else {
    mapWrapper.style.display = 'none';
    isMapVisible = false;
    if (btnToggle) btnToggle.textContent = '🗺️ View on Map';
  }
}

function initModalMap() {
  const mapElement = document.getElementById('pharmacy-map');
  if (!mapElement || typeof L === 'undefined') return;

  pharmacyMap = L.map('pharmacy-map').setView([17.385, 78.4867], 13);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(pharmacyMap);

  setTimeout(() => {
    pharmacyMap.invalidateSize();
  }, 200);
}

function renderPharmacyMap(req, pharmacies) {
  if (typeof L === 'undefined') return;

  if (!pharmacyMap) {
    initModalMap();
  }

  if (!pharmacyMap) return;

  // Clear previous markers
  pharmacyMarkers.forEach((m) => pharmacyMap.removeLayer(m));
  pharmacyMarkers = [];

  if (patientMarker) {
    pharmacyMap.removeLayer(patientMarker);
    patientMarker = null;
  }

  const bounds = [];

  // 1. Patient Location Marker
  const pLat = req.patient_lat || currentPatientLocation.lat;
  const pLng = req.patient_lng || currentPatientLocation.lng;

  if (pLat && pLng) {
    const patientLatLng = [parseFloat(pLat), parseFloat(pLng)];
    bounds.push(patientLatLng);

    patientMarker = L.marker(patientLatLng)
      .addTo(pharmacyMap)
      .bindPopup(`
        <div style="font-size: 0.9rem; line-height: 1.4;">
          <strong style="color: var(--primary);">📍 Your Request Location</strong><br>
          <span style="font-size: 0.8rem; color: #64748b;">Search Radius: ${req.search_radius_km} km</span>
        </div>
      `);
  }

  // 2. Pharmacy Markers
  pharmacies.forEach((p) => {
    if (p.latitude !== null && p.longitude !== null) {
      const pharmLatLng = [parseFloat(p.latitude), parseFloat(p.longitude)];
      bounds.push(pharmLatLng);

      let statusText = '🟡 Awaiting Response';
      if (p.has_responded) {
        if (p.availability_status === 'all_available') statusText = '🟢 All Medicines Available';
        else if (p.availability_status === 'some_available') statusText = '🟠 Some Medicines Available';
        else statusText = '🔴 Not Available';
      }

      let navUrl = `https://www.google.com/maps/dir/?api=1&origin=${pLat || ''},${pLng || ''}&destination=${p.latitude},${p.longitude}&travelmode=driving`;

      const marker = L.marker(pharmLatLng)
        .addTo(pharmacyMap)
        .bindPopup(`
          <div style="font-size: 0.9rem; line-height: 1.4; min-width: 180px;">
            <strong style="color: var(--primary-dark); font-size: 0.95rem;">🏪 ${escapeHtml(p.pharmacy_name)}</strong><br>
            <span style="font-size: 0.82rem; font-weight: 600;">${statusText}</span><br>
            <span style="font-size: 0.8rem; color: #64748b;">Distance: ${p.distance_km} km</span><br>
            <span style="font-size: 0.78rem; color: #64748b;">${escapeHtml(p.address)}</span>
            <div style="margin-top: 8px;">
              <a href="${navUrl}" target="_blank" rel="noopener noreferrer" style="display: inline-block; padding: 4px 10px; font-size: 0.8rem; background: var(--primary); color: #fff; border-radius: 4px; text-decoration: none; font-weight: 600;">
                🧭 Directions
              </a>
              ${p.phone ? `<a href="tel:${escapeHtml(p.phone)}" style="display: inline-block; margin-left: 6px; padding: 4px 10px; font-size: 0.8rem; background: var(--bg-muted); color: var(--text-main); border-radius: 4px; text-decoration: none; border: 1px solid var(--border-color); font-weight: 600;">📞 Call</a>` : ''}
            </div>
          </div>
        `);

      pharmacyMarkers.push(marker);
    }
  });

  // Fit bounds if we have points
  if (bounds.length > 0) {
    pharmacyMap.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
  }

  if (isMapVisible) {
    setTimeout(() => {
      pharmacyMap.invalidateSize();
    }, 200);
  }
}

function focusPharmacyOnMap(lat, lng, pharmacyName) {
  const mapWrapper = document.getElementById('pharmacy-map-wrapper');
  const btnToggle = document.getElementById('btn-toggle-map');

  if (mapWrapper && (mapWrapper.style.display === 'none' || mapWrapper.style.display === '')) {
    mapWrapper.style.display = 'block';
    isMapVisible = true;
    if (btnToggle) btnToggle.textContent = '🗺️ Hide Map';
  }

  if (!pharmacyMap) {
    initModalMap();
  }

  if (!pharmacyMap) return;

  const position = [parseFloat(lat), parseFloat(lng)];

  pharmacyMap.invalidateSize();
  pharmacyMap.setView(position, 16, { animate: true });

  // Scroll to map smoothly
  if (mapWrapper) {
    mapWrapper.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Find and open marker popup
  const marker = pharmacyMarkers.find((m) => {
    const mPos = m.getLatLng();
    return Math.abs(mPos.lat - position[0]) < 0.0001 && Math.abs(mPos.lng - position[1]) < 0.0001;
  });

  if (marker) {
    setTimeout(() => {
      marker.openPopup();
    }, 250);
  }
}

/* =========================================================
   MODAL CLOSE & ESCAPE HANDLERS
   ========================================================= */

function closeModal() {
  currentViewingReqId = null;
  const modalBackdrop = document.getElementById('responses-modal-backdrop');
  if (modalBackdrop) {
    modalBackdrop.classList.remove('open');
  }
}

window.addEventListener('click', (e) => {
  const modalBackdrop = document.getElementById('responses-modal-backdrop');
  if (e.target === modalBackdrop) {
    closeModal();
  }
  const locModalBackdrop = document.getElementById('location-modal-backdrop');
  if (e.target === locModalBackdrop) {
    closeLocationModal();
  }
});

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeModal();
    closeLocationModal();
  }
});

/* =========================================================
   SECURITY HELPERS
   ========================================================= */

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeJsString(str) {
  if (!str) return '';
  return String(str)
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r');
}
