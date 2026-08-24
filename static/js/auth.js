/**
 * MedConnect - Authentication & Registration Location Picker
 * Clean, standard vanilla JavaScript for Flask session-based authentication
 */

(function () {
  'use strict';

  let regPatientMap = null;
  let regPatientMarker = null;
  let regPharmacyMap = null;
  let regPharmacyMarker = null;

  function initApp() {
    initRegistrationTabs();
    initPatientLocationPicker();
    initPharmacyLocationPicker();
    initAuthForms();
    initLogoutHandlers();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }

  /**
   * 1. Registration Tab Switching
   */
  function initRegistrationTabs() {
    const tabPatient = document.getElementById('tab-patient-btn');
    const tabPharmacy = document.getElementById('tab-pharmacy-btn');
    const formPatient = document.getElementById('form-patient-container');
    const formPharmacy = document.getElementById('form-pharmacy-container');

    if (!tabPatient || !tabPharmacy || !formPatient || !formPharmacy) return;

    function switchTab(role) {
      if (role === 'pharmacy') {
        tabPharmacy.classList.add('active');
        tabPatient.classList.remove('active');
        formPharmacy.classList.add('active');
        formPatient.classList.remove('active');

        setTimeout(() => {
          if (regPharmacyMap) {
            regPharmacyMap.invalidateSize();
          }
        }, 150);
      } else {
        tabPatient.classList.add('active');
        tabPharmacy.classList.remove('active');
        formPatient.classList.add('active');
        formPharmacy.classList.remove('active');

        setTimeout(() => {
          if (regPatientMap) {
            regPatientMap.invalidateSize();
          }
        }, 150);
      }
    }

    tabPatient.addEventListener('click', () => switchTab('patient'));
    tabPharmacy.addEventListener('click', () => switchTab('pharmacy'));

    // Check query params to pre-select tab (e.g. /register?role=pharmacy)
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('role') === 'pharmacy') {
      switchTab('pharmacy');
    }
  }

  /**
   * Geocoding Helpers (Forward & Reverse via Nominatim OpenStreetMap)
   */
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

  /**
   * 2. Interactive Location Picker for Patient Registration
   */
  function initPatientLocationPicker() {
    const mapContainer = document.getElementById('patient-reg-map');
    if (!mapContainer || typeof L === 'undefined') return;

    const defaultLat = 17.3850;
    const defaultLng = 78.4867;

    try {
      regPatientMap = L.map('patient-reg-map').setView([defaultLat, defaultLng], 12);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      }).addTo(regPatientMap);

      // Click on map to select location
      regPatientMap.on('click', async (e) => {
        const lat = e.latlng.lat;
        const lng = e.latlng.lng;
        await setPatientLocation(lat, lng, null);
      });

      // Search location input & button
      const searchInput = document.getElementById('patient-loc-search');
      const searchBtn = document.getElementById('btn-patient-search-loc');

      const performPatientSearch = async () => {
        if (!searchInput) return;
        const query = searchInput.value.trim();
        if (!query) return;

        if (searchBtn) {
          searchBtn.disabled = true;
          searchBtn.textContent = 'Searching...';
        }

        const result = await searchLocationQuery(query);
        if (searchBtn) {
          searchBtn.disabled = false;
          searchBtn.textContent = '🔍 Search';
        }

        if (result) {
          regPatientMap.setView([result.lat, result.lng], 15);
          await setPatientLocation(result.lat, result.lng, result.displayName);
        } else {
          setPatientFeedback('Location not found. Please try another place name.', 'warning');
        }
      };

      if (searchBtn) {
        searchBtn.addEventListener('click', performPatientSearch);
      }
      if (searchInput) {
        searchInput.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            performPatientSearch();
          }
        });
      }

      // Geolocation "Use My Current Location" button
      const btnDetect = document.getElementById('btn-patient-detect-loc');
      if (btnDetect) {
        btnDetect.addEventListener('click', () => {
          if (!navigator.geolocation) {
            setPatientFeedback('Geolocation is not supported by your browser.', 'danger');
            return;
          }

          const originalText = btnDetect.textContent;
          btnDetect.textContent = '⏳ Detecting...';
          btnDetect.disabled = true;

          navigator.geolocation.getCurrentPosition(
            async (pos) => {
              const lat = pos.coords.latitude;
              const lng = pos.coords.longitude;
              regPatientMap.setView([lat, lng], 15);
              await setPatientLocation(lat, lng, null);
              btnDetect.textContent = originalText;
              btnDetect.disabled = false;
              setPatientFeedback('📍 Current location detected successfully.', 'success');
            },
            (err) => {
              console.warn('Patient geolocation error:', err);
              setPatientFeedback(
                'Location permission was denied. You can search for your location or select it manually on the map.',
                'warning'
              );
              btnDetect.textContent = originalText;
              btnDetect.disabled = false;
            },
            { enableHighAccuracy: true, timeout: 10000 }
          );
        });
      }
    } catch (e) {
      console.error('Error initializing Patient registration map:', e);
    }
  }

  async function setPatientLocation(lat, lng, explicitAddress) {
    const latInput = document.getElementById('patient-lat');
    const lngInput = document.getElementById('patient-lng');
    const addressDisplay = document.getElementById('patient-selected-address');

    if (latInput && lngInput) {
      latInput.value = parseFloat(lat).toFixed(6);
      lngInput.value = parseFloat(lng).toFixed(6);
    }

    if (!regPatientMarker && regPatientMap) {
      regPatientMarker = L.marker([lat, lng], { draggable: true }).addTo(regPatientMap);
      regPatientMarker.on('dragend', async (e) => {
        const pos = e.target.getLatLng();
        await setPatientLocation(pos.lat, pos.lng, null);
      });
    } else if (regPatientMarker) {
      regPatientMarker.setLatLng([lat, lng]);
    }

    if (addressDisplay) {
      if (explicitAddress) {
        addressDisplay.textContent = explicitAddress;
      } else {
        addressDisplay.textContent = 'Fetching address...';
        const fetchedAddress = await reverseGeocodeCoords(lat, lng);
        addressDisplay.textContent = fetchedAddress || `${parseFloat(lat).toFixed(4)}, ${parseFloat(lng).toFixed(4)}`;
      }
    }
  }

  function setPatientFeedback(msg, type) {
    const feedback = document.getElementById('patient-loc-action-feedback');
    if (!feedback) return;
    feedback.textContent = msg;
    if (type === 'danger' || type === 'warning') {
      feedback.style.color = 'var(--danger)';
    } else if (type === 'success') {
      feedback.style.color = 'var(--success)';
    } else {
      feedback.style.color = 'var(--text-muted)';
    }
  }

  /**
   * 3. Interactive Location Picker for Pharmacy Registration
   */
  function initPharmacyLocationPicker() {
    const mapContainer = document.getElementById('pharmacy-reg-map');
    if (!mapContainer || typeof L === 'undefined') return;

    const defaultLat = 17.3850;
    const defaultLng = 78.4867;

    try {
      regPharmacyMap = L.map('pharmacy-reg-map').setView([defaultLat, defaultLng], 12);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      }).addTo(regPharmacyMap);

      // Click on map to select location
      regPharmacyMap.on('click', async (e) => {
        const lat = e.latlng.lat;
        const lng = e.latlng.lng;
        await setPharmacyLocation(lat, lng, null);
      });

      // Search location input & button
      const searchInput = document.getElementById('pharmacy-loc-search');
      const searchBtn = document.getElementById('btn-pharmacy-search-loc');

      const performPharmacySearch = async () => {
        if (!searchInput) return;
        const query = searchInput.value.trim();
        if (!query) return;

        if (searchBtn) {
          searchBtn.disabled = true;
          searchBtn.textContent = 'Searching...';
        }

        const result = await searchLocationQuery(query);
        if (searchBtn) {
          searchBtn.disabled = false;
          searchBtn.textContent = '🔍 Search';
        }

        if (result) {
          regPharmacyMap.setView([result.lat, result.lng], 15);
          await setPharmacyLocation(result.lat, result.lng, result.displayName);
        } else {
          setPharmacyFeedback('Location not found. Please try another place name.', 'warning');
        }
      };

      if (searchBtn) {
        searchBtn.addEventListener('click', performPharmacySearch);
      }
      if (searchInput) {
        searchInput.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            performPharmacySearch();
          }
        });
      }

      // Geolocation "Use My Current Location" button
      const btnDetect = document.getElementById('btn-pharmacy-detect-loc');
      if (btnDetect) {
        btnDetect.addEventListener('click', () => {
          if (!navigator.geolocation) {
            setPharmacyFeedback('Geolocation is not supported by your browser.', 'danger');
            return;
          }

          const originalText = btnDetect.textContent;
          btnDetect.textContent = '⏳ Detecting...';
          btnDetect.disabled = true;

          navigator.geolocation.getCurrentPosition(
            async (pos) => {
              const lat = pos.coords.latitude;
              const lng = pos.coords.longitude;
              regPharmacyMap.setView([lat, lng], 15);
              await setPharmacyLocation(lat, lng, null);
              btnDetect.textContent = originalText;
              btnDetect.disabled = false;
              setPharmacyFeedback('📍 Current pharmacy location detected successfully.', 'success');
            },
            (err) => {
              console.warn('Pharmacy geolocation error:', err);
              setPharmacyFeedback(
                'Location permission was denied. You can search for your location or select it manually on the map.',
                'warning'
              );
              btnDetect.textContent = originalText;
              btnDetect.disabled = false;
            },
            { enableHighAccuracy: true, timeout: 10000 }
          );
        });
      }
    } catch (e) {
      console.error('Error initializing Pharmacy registration map:', e);
    }
  }

  async function setPharmacyLocation(lat, lng, explicitAddress) {
    const latInput = document.getElementById('pharmacy-lat');
    const lngInput = document.getElementById('pharmacy-lng');
    const addressDisplay = document.getElementById('pharmacy-selected-address');

    if (latInput && lngInput) {
      latInput.value = parseFloat(lat).toFixed(6);
      lngInput.value = parseFloat(lng).toFixed(6);
    }

    if (!regPharmacyMarker && regPharmacyMap) {
      regPharmacyMarker = L.marker([lat, lng], { draggable: true }).addTo(regPharmacyMap);
      regPharmacyMarker.on('dragend', async (e) => {
        const pos = e.target.getLatLng();
        await setPharmacyLocation(pos.lat, pos.lng, null);
      });
    } else if (regPharmacyMarker) {
      regPharmacyMarker.setLatLng([lat, lng]);
    }

    if (addressDisplay) {
      if (explicitAddress) {
        addressDisplay.textContent = explicitAddress;
      } else {
        addressDisplay.textContent = 'Fetching address...';
        const fetchedAddress = await reverseGeocodeCoords(lat, lng);
        addressDisplay.textContent = fetchedAddress || `${parseFloat(lat).toFixed(4)}, ${parseFloat(lng).toFixed(4)}`;
      }
    }
  }

  function setPharmacyFeedback(msg, type) {
    const feedback = document.getElementById('pharmacy-loc-action-feedback');
    if (!feedback) return;
    feedback.textContent = msg;
    if (type === 'danger' || type === 'warning') {
      feedback.style.color = 'var(--danger)';
    } else if (type === 'success') {
      feedback.style.color = 'var(--success)';
    } else {
      feedback.style.color = 'var(--text-muted)';
    }
  }

  /**
   * 4. Form Submissions
   */
  function initAuthForms() {
    // Patient Registration Submission
    const formRegisterPatient = document.getElementById('form-register-patient');
    if (formRegisterPatient) {
      formRegisterPatient.addEventListener('submit', async (e) => {
        e.preventDefault();
        const alertBox = document.getElementById('patient-reg-alert');
        if (alertBox) alertBox.style.display = 'none';

        const name = document.getElementById('patient-name').value.trim();
        const email = document.getElementById('patient-email').value.trim();
        const phone = document.getElementById('patient-phone').value.trim();
        const password = document.getElementById('patient-password').value;
        const latVal = document.getElementById('patient-lat').value;
        const lngVal = document.getElementById('patient-lng').value;

        // Validation: Location selection is required
        if (!latVal || !lngVal) {
          showFormAlert(
            alertBox,
            'Please select your location on the map so MedConnect can find nearby pharmacies.',
            'warning'
          );
          const mapElem = document.getElementById('patient-reg-map');
          if (mapElem) mapElem.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }

        const latitude = parseFloat(latVal);
        const longitude = parseFloat(lngVal);

        const btnSubmit = document.getElementById('btn-patient-submit');
        if (btnSubmit) {
          btnSubmit.disabled = true;
          btnSubmit.textContent = 'Registering Account...';
        }

        try {
          const response = await fetch('/api/auth/register-patient', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, email, phone, password, latitude, longitude })
          });

          const data = await response.json();
          if (!response.ok) {
            showFormAlert(alertBox, data.error || 'Registration failed.', 'danger');
            if (btnSubmit) {
              btnSubmit.disabled = false;
              btnSubmit.textContent = 'Complete Patient Registration';
            }
            return;
          }

          window.location.href = data.redirect || '/patient/dashboard';
        } catch (err) {
          console.error('Patient registration error:', err);
          showFormAlert(alertBox, 'Network error. Please check your connection and try again.', 'danger');
          if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.textContent = 'Complete Patient Registration';
          }
        }
      });
    }

    // Pharmacy Registration Submission
    const formRegisterPharmacy = document.getElementById('form-register-pharmacy');
    if (formRegisterPharmacy) {
      formRegisterPharmacy.addEventListener('submit', async (e) => {
        e.preventDefault();
        const alertBox = document.getElementById('pharmacy-reg-alert');
        if (alertBox) alertBox.style.display = 'none';

        const pharmacyName = document.getElementById('pharmacy-name').value.trim();
        const ownerName = document.getElementById('pharmacy-owner').value.trim();
        const dlNumber = document.getElementById('pharmacy-dl').value.trim();
        const address = document.getElementById('pharmacy-address').value.trim();
        const contactName = document.getElementById('pharmacy-contact-name').value.trim();
        const email = document.getElementById('pharmacy-email').value.trim();
        const phone = document.getElementById('pharmacy-phone').value.trim();
        const password = document.getElementById('pharmacy-password').value;

        const latVal = document.getElementById('pharmacy-lat').value;
        const lngVal = document.getElementById('pharmacy-lng').value;

        // Validation: Pharmacy map location is required
        if (!latVal || !lngVal) {
          showFormAlert(alertBox, 'Please select your pharmacy location on the map.', 'warning');
          const mapElem = document.getElementById('pharmacy-reg-map');
          if (mapElem) mapElem.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }

        const payload = {
          name: contactName,
          email,
          phone,
          password,
          pharmacy_name: pharmacyName,
          owner_name: ownerName,
          dl_number: dlNumber,
          address,
          latitude: parseFloat(latVal),
          longitude: parseFloat(lngVal)
        };

        const submitBtn = formRegisterPharmacy.querySelector('button[type="submit"]');
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.textContent = 'Submitting Application...';
        }

        try {
          const response = await fetch('/api/auth/register-pharmacy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });

          const data = await response.json();
          if (!response.ok) {
            showFormAlert(alertBox, data.error || 'Pharmacy registration failed.', 'danger');
            if (submitBtn) {
              submitBtn.disabled = false;
              submitBtn.textContent = 'Submit Pharmacy Registration for Approval';
            }
            return;
          }

          window.location.href = data.redirect || '/login?registered=pending';
        } catch (err) {
          console.error('Pharmacy registration error:', err);
          showFormAlert(alertBox, 'Network error. Please try again.', 'danger');
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Submit Pharmacy Registration for Approval';
          }
        }
      });
    }

    // Unified Login Form Submission
    const loginForm = document.getElementById('form-login') || document.getElementById('login-form');
    if (loginForm) {
      // Check query parameter for pending pharmacy notification
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('registered') === 'pending') {
        const alertBox = document.getElementById('login-alert');
        showFormAlert(
          alertBox,
          'Pharmacy registration submitted! Your account is pending admin verification before you can log in.',
          'info'
        );
      }

      async function handleLoginSubmission(e) {
        if (e && e.preventDefault) {
          e.preventDefault();
        }

        const alertBox = document.getElementById('login-alert');
        if (alertBox) {
          alertBox.style.display = 'none';
        }

        const emailInput = document.getElementById('login-email');
        const passwordInput = document.getElementById('login-password');
        const btnSubmit = document.getElementById('btn-login-submit') || loginForm.querySelector('button[type="submit"]');

        const email = emailInput ? emailInput.value.trim() : '';
        const password = passwordInput ? passwordInput.value : '';

        if (!email || !password) {
          showFormAlert(alertBox, 'Please enter both email and password.', 'warning');
          return;
        }

        if (btnSubmit) {
          btnSubmit.disabled = true;
          btnSubmit.textContent = 'Signing in...';
        }

        try {
          const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json'
            },
            body: JSON.stringify({ email, password })
          });

          const data = await response.json();

          if (!response.ok) {
            console.error('Login failed response:', data);
            showFormAlert(alertBox, data.error || 'Invalid email or password.', 'danger');
            if (btnSubmit) {
              btnSubmit.disabled = false;
              btnSubmit.textContent = 'Login';
            }
            return;
          }

          // Successful login: redirect to role dashboard
          let targetUrl = data.redirect;
          if (!targetUrl) {
            const userRole = data.user && data.user.role;
            if (userRole === 'patient') targetUrl = '/patient/dashboard';
            else if (userRole === 'pharmacy') targetUrl = '/pharmacy/dashboard';
            else if (userRole === 'admin') targetUrl = '/admin/dashboard';
            else targetUrl = '/';
          }

          window.location.href = targetUrl;
        } catch (err) {
          console.error('Network/login error:', err);
          showFormAlert(alertBox, 'Network error while connecting to server. Please try again.', 'danger');
          if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.textContent = 'Login';
          }
        }
      }

      loginForm.addEventListener('submit', handleLoginSubmission);
    }
  }

  /**
   * 5. Logout Handler
   */
  function initLogoutHandlers() {
    const logoutButtons = document.querySelectorAll('.btn-logout');
    logoutButtons.forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        try {
          await fetch('/api/auth/logout', { method: 'POST' });
          window.location.href = '/login';
        } catch (err) {
          window.location.href = '/login';
        }
      });
    });
  }

  /**
   * Helper to display styled notification alert
   */
  function showFormAlert(alertElement, message, type) {
    if (!alertElement) return;
    alertElement.className = `alert alert-${type || 'info'}`;
    alertElement.innerHTML = `<span>${message}</span>`;
    alertElement.style.display = 'flex';
  }
})();
