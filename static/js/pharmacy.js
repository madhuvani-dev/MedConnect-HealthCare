/**
 * MedConnect - Pharmacy Dashboard JavaScript
 * Handles real-time feed of patient requests within search radius,
 * viewing prescriptions/medicine inquiries, and submitting availability status.
 */

let activeFeedRequests = [];

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    initPharmacyDashboard();
  });
} else {
  initPharmacyDashboard();
}

async function initPharmacyDashboard() {
  await loadPharmacyProfile();
  await loadPharmacyFeed();
  // Auto-refresh incoming requests feed every 15 seconds
  setInterval(loadPharmacyFeed, 15000);
}

/**
 * Loads pharmacy store details and verification status
 */
async function loadPharmacyProfile() {
  try {
    const res = await fetch('/api/auth/me');
    const data = await res.json();
    if (data.authenticated && data.pharmacy) {
      const p = data.pharmacy;
      document.getElementById('pharmacy-display-name').textContent = p.pharmacy_name;
      document.getElementById('pharmacy-display-owner').textContent = p.owner_name;
      document.getElementById('pharmacy-display-dl').textContent = p.dl_number;
      document.getElementById('pharmacy-display-address').textContent = p.address;
      document.getElementById('pharmacy-display-coords').textContent = `Lat: ${p.latitude.toFixed(4)}, Lng: ${p.longitude.toFixed(4)}`;
    }
  } catch (err) {
    console.error('Failed to load pharmacy profile:', err);
  }
}

/**
 * Loads active requests within distance radius
 */
async function loadPharmacyFeed() {
  try {
    const res = await fetch('/api/pharmacy/feed');
    const data = await res.json();
    const tableBody = document.getElementById('pharmacy-feed-tbody');
    const emptyState = document.getElementById('no-feed-message');
    const feedCountBadge = document.getElementById('feed-count-badge');

    if (!tableBody) return;

    if (!res.ok) {
      console.error(data.error);
      return;
    }

    activeFeedRequests = data.requests || [];
    if (feedCountBadge) {
      feedCountBadge.textContent = `${activeFeedRequests.length} Active`;
    }

    if (activeFeedRequests.length === 0) {
      tableBody.innerHTML = '';
      if (emptyState) emptyState.style.display = 'block';
      return;
    }

    if (emptyState) emptyState.style.display = 'none';

    let rowsHtml = '';
    activeFeedRequests.forEach((req) => {
      const isRx = req.request_type === 'prescription';
      const itemTitle = isRx
        ? `<div>
             <strong>Prescription Document</strong><br/>
             <a href="/uploads/prescriptions/${req.prescription_file}" target="_blank" class="btn btn-sm btn-outline" style="margin-top: 4px;">
               📄 Open Prescription
             </a>
           </div>`
        : `<div>
             <span style="font-size: 1.05rem; font-weight: 700; color: var(--primary-dark);">${escapeHtml(req.medicine_name)}</span>
           </div>`;

      // Status of response by this pharmacy
      let myResponseBadge = '<span class="badge badge-pending">Not Responded</span>';
      if (req.has_responded && req.my_response) {
        const status = req.my_response.availability_status;
        if (status === 'all_available') {
          myResponseBadge = '<span class="badge badge-all">Responded: All Available</span>';
        } else if (status === 'some_available') {
          myResponseBadge = '<span class="badge badge-some">Responded: Some Available</span>';
        } else {
          myResponseBadge = '<span class="badge badge-none">Responded: Not Available</span>';
        }
      }

      const dateStr = new Date(req.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      rowsHtml += `
        <tr>
          <td><strong>#${req.id}</strong></td>
          <td>
            <strong>${escapeHtml(req.patient_name)}</strong><br/>
            <small class="text-muted"><a href="tel:${escapeHtml(req.patient_phone)}">${escapeHtml(req.patient_phone)}</a></small>
          </td>
          <td>${isRx ? '<span class="badge badge-some">Prescription</span>' : '<span class="badge badge-neutral">Medicine Name</span>'}</td>
          <td>${itemTitle}</td>
          <td>
            <strong style="color: var(--primary-dark);">${req.distance_km} km</strong>
            <small class="text-muted" style="display: block;">(Radius: ${req.search_radius_km} km)</small>
          </td>
          <td>${myResponseBadge}</td>
          <td><small class="text-muted">${dateStr}</small></td>
          <td>
            <button onclick="openResponseModal(${req.id})" class="btn btn-sm ${req.has_responded ? 'btn-secondary' : 'btn-primary'}">
              ${req.has_responded ? 'Update Response' : 'Send Availability'}
            </button>
          </td>
        </tr>
      `;
    });

    tableBody.innerHTML = rowsHtml;
  } catch (err) {
    console.error('Error loading pharmacy feed:', err);
  }
}

/**
 * Open Modal to send or update response
 */
function openResponseModal(reqId) {
  const req = activeFeedRequests.find((r) => r.id === reqId);
  if (!req) return;

  const modalBackdrop = document.getElementById('pharmacy-response-modal-backdrop');
  const reqTitle = document.getElementById('modal-pharm-req-title');
  const reqDetails = document.getElementById('modal-pharm-req-details');
  const reqIdInput = document.getElementById('response-req-id');
  const notesInput = document.getElementById('response-notes');

  reqIdInput.value = req.id;
  reqTitle.textContent = `Respond to Request #${req.id} (${req.distance_km} km away)`;

  if (req.request_type === 'prescription') {
    reqDetails.innerHTML = `
      <div style="background: var(--bg-muted); padding: 12px; border-radius: var(--radius-md); margin-bottom: 16px;">
        <p><strong>Patient:</strong> ${escapeHtml(req.patient_name)} (${escapeHtml(req.patient_phone)})</p>
        <p><strong>Prescription:</strong> <a href="/uploads/prescriptions/${req.prescription_file}" target="_blank" style="font-weight: 600; text-decoration: underline;">Click here to inspect prescription</a></p>
        <p><strong>Distance:</strong> ${req.distance_km} km</p>
      </div>
    `;
  } else {
    reqDetails.innerHTML = `
      <div style="background: var(--bg-muted); padding: 12px; border-radius: var(--radius-md); margin-bottom: 16px;">
        <p><strong>Patient:</strong> ${escapeHtml(req.patient_name)} (${escapeHtml(req.patient_phone)})</p>
        <p><strong>Requested Medicine:</strong> <span style="font-size: 1.1rem; font-weight: 700; color: var(--primary-dark);">${escapeHtml(req.medicine_name)}</span></p>
        <p><strong>Distance:</strong> ${req.distance_km} km</p>
      </div>
    `;
  }

  // Pre-fill if already responded
  if (req.has_responded && req.my_response) {
    const statusRadio = document.querySelector(`input[name="availability_status"][value="${req.my_response.availability_status}"]`);
    if (statusRadio) statusRadio.checked = true;
    notesInput.value = req.my_response.notes || '';
  } else {
    // Default to 'all_available'
    const defaultRadio = document.querySelector('input[name="availability_status"][value="all_available"]');
    if (defaultRadio) defaultRadio.checked = true;
    notesInput.value = '';
  }

  modalBackdrop.classList.add('open');
}

/**
 * Close pharmacy response modal
 */
function closePharmacyModal() {
  const modalBackdrop = document.getElementById('pharmacy-response-modal-backdrop');
  if (modalBackdrop) modalBackdrop.classList.remove('open');
}

// Handle Form Submission
document.addEventListener('DOMContentLoaded', () => {
  const formResponse = document.getElementById('form-submit-pharmacy-response');
  if (formResponse) {
    formResponse.addEventListener('submit', async (e) => {
      e.preventDefault();
      const reqId = parseInt(document.getElementById('response-req-id').value, 10);
      const availabilityElem = document.querySelector('input[name="availability_status"]:checked');
      const notes = document.getElementById('response-notes').value.trim();

      if (!availabilityElem) {
        alert('Please select an availability status.');
        return;
      }

      const availability = availabilityElem.value;
      const submitBtn = document.getElementById('btn-save-response');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Submitting...';

      try {
        const res = await fetch('/api/pharmacy/responses', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            request_id: reqId,
            availability_status: availability,
            notes: notes
          })
        });

        const data = await res.json();
        if (res.ok) {
          alert(data.message);
          closePharmacyModal();
          await loadPharmacyFeed();
        } else {
          alert(data.error || 'Failed to submit response.');
        }
      } catch (err) {
        alert('Error submitting response to server.');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit Availability Response';
      }
    });
  }
});

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
