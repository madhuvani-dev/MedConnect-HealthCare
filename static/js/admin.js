/**
 * MedConnect - Admin Dashboard JavaScript
 * Handles platform statistics, pending pharmacy verification & approval,
 * and user registry monitoring.
 */

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    initAdminDashboard();
  });
} else {
  initAdminDashboard();
}

async function initAdminDashboard() {
  await loadAdminStats();
  await loadPendingPharmacies();
  await loadAllPharmacies();
  await loadAllUsers();
}

/**
 * Loads high level counts
 */
async function loadAdminStats() {
  try {
    const res = await fetch('/api/admin/stats');
    const data = await res.json();
    if (res.ok && data.stats) {
      const s = data.stats;
      document.getElementById('stat-total-patients').textContent = s.total_patients;
      document.getElementById('stat-approved-pharmacies').textContent = s.approved_pharmacies;
      document.getElementById('stat-pending-pharmacies').textContent = s.pending_pharmacies;
      document.getElementById('stat-total-requests').textContent = s.total_requests;
      document.getElementById('stat-total-responses').textContent = s.total_responses;
    }
  } catch (err) {
    console.error('Failed to load stats:', err);
  }
}

/**
 * Loads pending pharmacy registrations requiring verification
 */
async function loadPendingPharmacies() {
  try {
    const res = await fetch('/api/admin/pharmacies?status=pending');
    const data = await res.json();
    const tbody = document.getElementById('pending-pharmacies-tbody');
    const emptyState = document.getElementById('no-pending-message');

    if (!tbody) return;

    if (!data.pharmacies || data.pharmacies.length === 0) {
      tbody.innerHTML = '';
      if (emptyState) emptyState.style.display = 'block';
      return;
    }

    if (emptyState) emptyState.style.display = 'none';

    let rowsHtml = '';
    data.pharmacies.forEach((p) => {
      rowsHtml += `
        <tr>
          <td>
            <strong>${escapeHtml(p.pharmacy_name)}</strong>
          </td>
          <td>${escapeHtml(p.owner_name)}</td>
          <td><span class="badge badge-neutral" style="font-family: monospace; font-size: 0.9rem;">${escapeHtml(p.dl_number)}</span></td>
          <td>
            <small>${escapeHtml(p.address)}</small><br/>
            <small class="text-muted">GPS: ${p.latitude.toFixed(4)}, ${p.longitude.toFixed(4)}</small>
          </td>
          <td>
            ${escapeHtml(p.contact_name)}<br/>
            <small class="text-muted">${escapeHtml(p.phone)} | ${escapeHtml(p.email)}</small>
          </td>
          <td><span class="badge badge-pending">Pending Review</span></td>
          <td>
            <div style="display: flex; gap: 8px;">
              <button onclick="approvePharmacy(${p.id}, '${escapeHtml(p.pharmacy_name)}')" class="btn btn-sm btn-success">
                ✓ Approve
              </button>
              <button onclick="rejectPharmacy(${p.id}, '${escapeHtml(p.pharmacy_name)}')" class="btn btn-sm btn-danger">
                ✕ Reject
              </button>
            </div>
          </td>
        </tr>
      `;
    });

    tbody.innerHTML = rowsHtml;
  } catch (err) {
    console.error('Error fetching pending pharmacies:', err);
  }
}

/**
 * Approve Pharmacy registration
 */
async function approvePharmacy(id, name) {
  if (!confirm(`Are you sure you want to APPROVE the Drug License and registration for "${name}"?`)) return;

  try {
    const res = await fetch(`/api/admin/pharmacies/${id}/approve`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      alert(data.message);
      await loadAdminStats();
      await loadPendingPharmacies();
      await loadAllPharmacies();
    } else {
      alert(data.error || 'Failed to approve pharmacy.');
    }
  } catch (err) {
    alert('Error communicating with server.');
  }
}

/**
 * Reject Pharmacy registration
 */
async function rejectPharmacy(id, name) {
  if (!confirm(`Are you sure you want to REJECT the registration for "${name}"?`)) return;

  try {
    const res = await fetch(`/api/admin/pharmacies/${id}/reject`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      alert(data.message);
      await loadAdminStats();
      await loadPendingPharmacies();
      await loadAllPharmacies();
    } else {
      alert(data.error || 'Failed to reject pharmacy.');
    }
  } catch (err) {
    alert('Error communicating with server.');
  }
}

/**
 * Loads all pharmacies (approved, pending, rejected)
 */
async function loadAllPharmacies() {
  try {
    const res = await fetch('/api/admin/pharmacies');
    const data = await res.json();
    const tbody = document.getElementById('all-pharmacies-tbody');

    if (!tbody) return;

    if (!data.pharmacies || data.pharmacies.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center">No pharmacies found.</td></tr>';
      return;
    }

    let rowsHtml = '';
    data.pharmacies.forEach((p) => {
      let statusBadge = '<span class="badge badge-pending">Pending</span>';
      if (p.status === 'approved') statusBadge = '<span class="badge badge-approved">Approved</span>';
      if (p.status === 'rejected') statusBadge = '<span class="badge badge-rejected">Rejected</span>';

      rowsHtml += `
        <tr>
          <td>#${p.id}</td>
          <td><strong>${escapeHtml(p.pharmacy_name)}</strong></td>
          <td>${escapeHtml(p.owner_name)}</td>
          <td><code>${escapeHtml(p.dl_number)}</code></td>
          <td>${escapeHtml(p.phone)}</td>
          <td>${statusBadge}</td>
        </tr>
      `;
    });

    tbody.innerHTML = rowsHtml;
  } catch (err) {
    console.error('Error fetching all pharmacies:', err);
  }
}

/**
 * Loads registered patients & user directory
 */
async function loadAllUsers() {
  try {
    const res = await fetch('/api/admin/users');
    const data = await res.json();
    const tbody = document.getElementById('all-users-tbody');

    if (!tbody) return;

    if (!data.users || data.users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center">No users registered yet.</td></tr>';
      return;
    }

    let rowsHtml = '';
    data.users.forEach((u) => {
      let roleBadge = '<span class="badge badge-neutral">Patient</span>';
      if (u.role === 'pharmacy') roleBadge = '<span class="badge badge-some">Pharmacy</span>';
      if (u.role === 'admin') roleBadge = '<span class="badge badge-all">Admin</span>';

      const loc = (u.latitude && u.longitude)
        ? `${parseFloat(u.latitude).toFixed(4)}, ${parseFloat(u.longitude).toFixed(4)}`
        : '<span class="text-muted">Not Set</span>';

      rowsHtml += `
        <tr>
          <td>#${u.id}</td>
          <td><strong>${escapeHtml(u.name)}</strong></td>
          <td>${escapeHtml(u.email)}</td>
          <td>${escapeHtml(u.phone)}</td>
          <td>${roleBadge}</td>
          <td>${loc}</td>
        </tr>
      `;
    });

    tbody.innerHTML = rowsHtml;
  } catch (err) {
    console.error('Error fetching users:', err);
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
