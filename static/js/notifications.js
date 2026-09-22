/**
 * MedConnect - Real-time Notifications Client Engine
 * Manages navigation bell badge, dropdown alerts, polling, and dedicated notifications page.
 */

(function () {
  'use strict';

  let currentUnreadCount = 0;
  let activePageFilter = 'all';
  let pollInterval = null;

  // DOM Elements for Navigation Bell
  const bellBtn = document.getElementById('nav-notif-btn');
  const bellBadge = document.getElementById('nav-notif-badge');
  const dropdown = document.getElementById('nav-notif-dropdown');
  const dropdownList = document.getElementById('nav-notif-list');
  const dropdownHeaderBadge = document.getElementById('nav-notif-header-badge');
  const dropdownMarkAllBtn = document.getElementById('nav-notif-mark-all-btn');

  // DOM Elements for Full Notifications Page
  const pageContainer = document.getElementById('notifications-full-container');
  const pageMarkAllBtn = document.getElementById('btn-page-mark-all');

  function init() {
    if (bellBtn && dropdown) {
      initBellDropdown();
    }

    // Initial check for unread count & notifications list
    fetchUnreadCount();
    fetchNotifications();

    // Start background polling (every 10 seconds)
    if (!pollInterval) {
      pollInterval = setInterval(async () => {
        await fetchUnreadCount();
        await fetchNotifications();
      }, 10000);
    }

    // Initialize full notifications page if on /notifications
    if (pageContainer) {
      initNotificationsPage();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /**
   * Helper: Format relative or human-readable time
   */
  function formatRelativeTime(dateString) {
    if (!dateString) return '';
    // SQLite timestamps: "YYYY-MM-DD HH:MM:SS" (stored in UTC)
    // Normalize to ISO format
    let isoString = dateString.includes('T') ? dateString : dateString.replace(' ', 'T') + 'Z';
    const date = new Date(isoString);
    if (isNaN(date.getTime())) {
      // Fallback for non-standard formats
      return dateString;
    }

    const now = new Date();
    const diffSecs = Math.floor((now - date) / 1000);

    if (diffSecs < 60) return 'Just now';
    if (diffSecs < 3600) return `${Math.floor(diffSecs / 60)}m ago`;
    if (diffSecs < 86400) return `${Math.floor(diffSecs / 3600)}h ago`;
    if (diffSecs < 172800) return 'Yesterday';

    // Formatted date
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  /**
   * Helper: Map notification type to icon & styling
   */
  function getTypeMeta(type) {
    switch (type) {
      case 'request_new':
        return { icon: '💊', badgeClass: 'badge-primary', label: 'Medicine Inquiry' };
      case 'request_response':
        return { icon: '🏪', badgeClass: 'badge-approved', label: 'Store Response' };
      case 'request_status':
        return { icon: '🔄', badgeClass: 'badge-neutral', label: 'Request Update' };
      case 'pharmacy_approval':
        return { icon: '✓', badgeClass: 'badge-approved', label: 'Verification Approved' };
      case 'pharmacy_rejection':
        return { icon: '✕', badgeClass: 'badge-rejected', label: 'Action Required' };
      case 'pharmacy_registration':
        return { icon: '📋', badgeClass: 'badge-pending', label: 'New Registration' };
      default:
        return { icon: '🔔', badgeClass: 'badge-neutral', label: 'Notification' };
    }
  }

  /**
   * Helper: Determine destination route for notification click
   */
  function getNotificationDestination(notif) {
    if (notif.type === 'pharmacy_registration') {
      return '/admin/dashboard';
    }
    if (notif.type === 'pharmacy_approval' || notif.type === 'pharmacy_rejection') {
      return '/pharmacy/dashboard';
    }
    if (notif.related_request_id) {
      return `/patient/dashboard?request_id=${notif.related_request_id}`;
    }
    return '/notifications';
  }

  /**
   * 1. Navigation Bell Dropdown Logic
   */
  function initBellDropdown() {
    // Toggle dropdown
    bellBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      const isVisible = dropdown.style.display === 'block';
      if (isVisible) {
        closeDropdown();
      } else {
        openDropdown();
      }
    });

    // Mark all as read button in dropdown
    if (dropdownMarkAllBtn) {
      dropdownMarkAllBtn.addEventListener('click', async function (e) {
        e.stopPropagation();
        await markAllNotificationsAsRead();
      });
    }

    // Close dropdown on outside click
    document.addEventListener('click', function (e) {
      if (dropdown && dropdown.style.display === 'block') {
        if (!dropdown.contains(e.target) && !bellBtn.contains(e.target)) {
          closeDropdown();
        }
      }
    });

    // Close on Escape key
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && dropdown && dropdown.style.display === 'block') {
        closeDropdown();
      }
    });
  }

  function openDropdown() {
    dropdown.style.display = 'block';
    bellBtn.setAttribute('aria-expanded', 'true');
    loadDropdownNotifications();
  }

  function closeDropdown() {
    dropdown.style.display = 'none';
    bellBtn.setAttribute('aria-expanded', 'false');
  }

  /**
   * Fetches unread count and updates the badge
   */
  async function fetchUnreadCount() {
    try {
      const res = await fetch('/api/notifications/unread-count');
      if (!res.ok) return;
      const data = await res.json();
      updateBadgeUI(data.unread_count);
    } catch (err) {
      // Silent error during polling
    }
  }

  function updateBadgeUI(count) {
    currentUnreadCount = parseInt(count, 10) || 0;
    if (bellBadge) {
      if (currentUnreadCount > 0) {
        bellBadge.textContent = currentUnreadCount > 99 ? '99+' : currentUnreadCount;
        bellBadge.style.display = 'flex';
      } else {
        bellBadge.style.display = 'none';
      }
    }
    if (dropdownHeaderBadge) {
      dropdownHeaderBadge.textContent = `${currentUnreadCount} new`;
    }
  }

  /**
   * Fetches latest notifications from /api/notifications and refreshes UI
   */
  async function fetchNotifications() {
    try {
      const res = await fetch('/api/notifications?limit=10');
      if (!res.ok) return;
      const data = await res.json();
      if (typeof data.unread_count !== 'undefined') {
        updateBadgeUI(data.unread_count);
      }
      if (data.notifications && dropdownList) {
        renderDropdownItems(data.notifications);
      }
      window.dispatchEvent(new CustomEvent('medconnect:notifications-updated', { detail: data }));
      return data;
    } catch (err) {
      console.error('Error fetching notifications:', err);
    }
  }

  /**
   * Renders notification item cards into navigation dropdown
   */
  function renderDropdownItems(items) {
    if (!dropdownList) return;

    if (!items || items.length === 0) {
      dropdownList.innerHTML = `
        <div class="nav-notif-empty-state">
          <div style="font-size: 1.8rem; margin-bottom: 6px;">🔔</div>
          <strong style="color: var(--text-main); font-size: 0.9rem;">No notifications yet</strong>
          <p style="margin: 4px 0 0; font-size: 0.8rem; color: var(--text-muted);">
            Updates about your medicine requests and responses will appear here.
          </p>
        </div>
      `;
      return;
    }

    dropdownList.innerHTML = '';
    items.forEach((notif) => {
      const meta = getTypeMeta(notif.type);
      const itemEl = document.createElement('div');
      itemEl.className = `nav-notif-item-card ${notif.is_read ? 'read' : 'unread'}`;
      itemEl.setAttribute('data-id', notif.id);

      itemEl.innerHTML = `
        <div class="nav-notif-icon-col">
          <span class="nav-notif-type-icon">${meta.icon}</span>
        </div>
        <div class="nav-notif-content-col">
          <div class="nav-notif-item-title-row">
            <span class="nav-notif-item-title">${escapeHtml(notif.title)}</span>
            ${!notif.is_read ? '<span class="unread-dot" title="Unread"></span>' : ''}
          </div>
          <div class="nav-notif-item-msg">${escapeHtml(notif.message)}</div>
          <div class="nav-notif-item-footer">
            <span class="nav-notif-time">${formatRelativeTime(notif.created_at)}</span>
            ${
              !notif.is_read
                ? `<button class="btn-link-xs btn-mark-read" data-id="${notif.id}" type="button">Mark read</button>`
                : ''
            }
          </div>
        </div>
      `;

      // Click item to mark as read and navigate if applicable
      itemEl.addEventListener('click', async function (e) {
        if (e.target.classList.contains('btn-mark-read')) {
          e.stopPropagation();
          await markSingleNotificationRead(notif.id);
          itemEl.classList.remove('unread');
          itemEl.classList.add('read');
          const dot = itemEl.querySelector('.unread-dot');
          if (dot) dot.remove();
          e.target.remove();
          return;
        }

        if (!notif.is_read) {
          await markSingleNotificationRead(notif.id);
        }

        const targetUrl = getNotificationDestination(notif);
        if (targetUrl) {
          if (window.location.pathname === '/patient/dashboard' && notif.related_request_id && typeof window.viewResponsesModal === 'function') {
            closeDropdown();
            window.viewResponsesModal(notif.related_request_id);
          } else {
            window.location.href = targetUrl;
          }
        }
      });

      dropdownList.appendChild(itemEl);
    });
  }

  /**
   * Loads recent notifications into navigation dropdown
   */
  async function loadDropdownNotifications() {
    if (!dropdownList) return;

    try {
      const res = await fetch('/api/notifications?limit=10');
      if (!res.ok) {
        dropdownList.innerHTML = '<div class="nav-notif-empty-state">Unable to load notifications.</div>';
        return;
      }

      const data = await res.json();
      updateBadgeUI(data.unread_count);
      renderDropdownItems(data.notifications || []);
    } catch (err) {
      console.error('Error loading dropdown notifications:', err);
      dropdownList.innerHTML = '<div class="nav-notif-empty-state">Network error. Please try again.</div>';
    }
  }

  /**
   * 2. Notifications Management API Calls
   */
  async function markSingleNotificationRead(notifId) {
    try {
      const res = await fetch(`/api/notifications/${notifId}/read`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        updateBadgeUI(data.unread_count);
        // Refresh full page data if open
        if (pageContainer) {
          loadNotificationsPageData();
        }
      }
    } catch (err) {
      console.error('Error marking notification read:', err);
    }
  }

  async function markAllNotificationsAsRead() {
    try {
      const res = await fetch('/api/notifications/mark-all-read', { method: 'POST' });
      if (res.ok) {
        updateBadgeUI(0);
        if (dropdown.style.display === 'block') {
          loadDropdownNotifications();
        }
        if (pageContainer) {
          loadNotificationsPageData();
        }
      }
    } catch (err) {
      console.error('Error marking all notifications read:', err);
    }
  }

  async function deleteNotification(notifId) {
    try {
      const res = await fetch(`/api/notifications/${notifId}`, { method: 'DELETE' });
      if (res.ok) {
        const data = await res.json();
        updateBadgeUI(data.unread_count);
        if (pageContainer) {
          loadNotificationsPageData();
        }
      }
    } catch (err) {
      console.error('Error deleting notification:', err);
    }
  }

  async function toggleNotificationUnread(notifId) {
    try {
      const res = await fetch(`/api/notifications/${notifId}/unread`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        updateBadgeUI(data.unread_count);
        if (pageContainer) {
          loadNotificationsPageData();
        }
      }
    } catch (err) {
      console.error('Error marking notification unread:', err);
    }
  }

  /**
   * 3. Dedicated Notifications Page (`/notifications`) Logic
   */
  window.initNotificationsPage = function () {
    const filterBtns = document.querySelectorAll('.notif-filter-btn');
    filterBtns.forEach((btn) => {
      btn.addEventListener('click', function () {
        filterBtns.forEach((b) => b.classList.remove('active'));
        this.classList.add('active');
        activePageFilter = this.getAttribute('data-filter') || 'all';
        loadNotificationsPageData();
      });
    });

    if (pageMarkAllBtn) {
      pageMarkAllBtn.addEventListener('click', async function () {
        await markAllNotificationsAsRead();
      });
    }

    loadNotificationsPageData();
  };

  window.loadNotificationsPageData = async function () {
    if (!pageContainer) return;

    pageContainer.innerHTML = `
      <div class="card" style="text-align: center; padding: 32px;">
        <div style="font-size: 1.5rem; margin-bottom: 8px;">⏳</div>
        <p class="text-muted" style="margin: 0;">Loading notifications...</p>
      </div>
    `;

    try {
      const res = await fetch(`/api/notifications?filter=${activePageFilter}&limit=100`);
      if (!res.ok) {
        pageContainer.innerHTML = `
          <div class="card" style="text-align: center; padding: 32px;">
            <p style="color: var(--danger); margin: 0;">Failed to load notifications. Please refresh.</p>
          </div>
        `;
        return;
      }

      const data = await res.json();
      updateBadgeUI(data.unread_count);

      // Update tab counter badges
      updateFilterCounts();

      const items = data.notifications || [];
      if (items.length === 0) {
        let emptyTitle = 'No notifications found';
        let emptyDesc = 'You do not have any notifications in this view.';
        if (activePageFilter === 'unread') {
          emptyTitle = 'All caught up!';
          emptyDesc = 'You have read all your notifications.';
        } else if (activePageFilter === 'read') {
          emptyTitle = 'No read notifications';
          emptyDesc = 'Read notifications will be archived here.';
        }

        pageContainer.innerHTML = `
          <div class="card empty-state" style="padding: 48px 24px; text-align: center;">
            <div class="empty-state-icon" style="font-size: 3rem; margin-bottom: 12px;">🎉</div>
            <h3 style="font-size: 1.25rem; font-weight: 700; margin-bottom: 6px; color: var(--text-main);">${emptyTitle}</h3>
            <p class="text-muted" style="max-width: 440px; margin: 0 auto;">${emptyDesc}</p>
          </div>
        `;
        return;
      }

      pageContainer.innerHTML = '';
      items.forEach((notif) => {
        const meta = getTypeMeta(notif.type);
        const card = document.createElement('div');
        card.className = `notification-page-card ${notif.is_read ? 'read' : 'unread'}`;
        card.setAttribute('data-id', notif.id);

        const destination = getNotificationDestination(notif);
        let actionBtnHtml = '';
        if (notif.related_request_id) {
          actionBtnHtml = `<a href="${destination}" class="btn btn-sm btn-outline">View Request #${notif.related_request_id}</a>`;
        } else if (notif.type.startsWith('pharmacy_')) {
          actionBtnHtml = `<a href="${destination}" class="btn btn-sm btn-outline">Go to Dashboard</a>`;
        }

        card.innerHTML = `
          <div class="notif-card-main">
            <div class="notif-card-icon-box ${meta.badgeClass}">
              <span>${meta.icon}</span>
            </div>
            
            <div class="notif-card-body">
              <div class="notif-card-header-row">
                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                  <span class="badge ${meta.badgeClass}">${meta.label}</span>
                  ${
                    !notif.is_read
                      ? '<span class="badge badge-warning" style="font-size: 0.72rem;">New</span>'
                      : '<span class="text-muted" style="font-size: 0.8rem;">Read</span>'
                  }
                </div>
                <span class="notif-card-time">${formatRelativeTime(notif.created_at)}</span>
              </div>

              <h4 class="notif-card-title">${escapeHtml(notif.title)}</h4>
              <p class="notif-card-message">${escapeHtml(notif.message)}</p>

              <div class="notif-card-actions">
                ${actionBtnHtml}
                ${
                  !notif.is_read
                    ? `<button class="btn btn-sm btn-secondary btn-mark-read-page" data-id="${notif.id}">✓ Mark as read</button>`
                    : `<button class="btn btn-sm btn-secondary btn-mark-unread-page" data-id="${notif.id}">Mark unread</button>`
                }
                <button class="btn btn-sm btn-link-danger btn-delete-notif" data-id="${notif.id}" title="Delete notification">🗑 Delete</button>
              </div>
            </div>
          </div>
        `;

        // Event listeners for card buttons
        const btnMarkRead = card.querySelector('.btn-mark-read-page');
        if (btnMarkRead) {
          btnMarkRead.addEventListener('click', async () => {
            await markSingleNotificationRead(notif.id);
          });
        }

        const btnMarkUnread = card.querySelector('.btn-mark-unread-page');
        if (btnMarkUnread) {
          btnMarkUnread.addEventListener('click', async () => {
            await toggleNotificationUnread(notif.id);
          });
        }

        const btnDelete = card.querySelector('.btn-delete-notif');
        if (btnDelete) {
          btnDelete.addEventListener('click', async () => {
            if (confirm('Are you sure you want to remove this notification?')) {
              await deleteNotification(notif.id);
            }
          });
        }

        pageContainer.appendChild(card);
      });
    } catch (err) {
      console.error('Error loading notifications page:', err);
      pageContainer.innerHTML = `
        <div class="card" style="text-align: center; padding: 32px;">
          <p style="color: var(--danger); margin: 0;">An error occurred while loading notifications.</p>
        </div>
      `;
    }
  };

  /**
   * Helper: Update tab filter counts on the page
   */
  async function updateFilterCounts() {
    try {
      const [resAll, resUnread, resRead] = await Promise.all([
        fetch('/api/notifications?filter=all&limit=1'),
        fetch('/api/notifications?filter=unread&limit=1'),
        fetch('/api/notifications?filter=read&limit=1')
      ]);

      if (resAll.ok) {
        const dataAll = await resAll.json();
        const countAllEl = document.getElementById('count-all');
        if (countAllEl) countAllEl.textContent = dataAll.notifications ? (dataAll.notifications.length === 0 ? 0 : '•') : 0;
      }

      if (resUnread.ok) {
        const dataUnread = await resUnread.json();
        const countUnreadEl = document.getElementById('count-unread');
        if (countUnreadEl) countUnreadEl.textContent = dataUnread.unread_count;
      }
    } catch (e) {
      // Non-critical count update
    }
  }

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Expose public API on window for integration across patient & pharmacy dashboards
  window.updateNotificationBadge = updateBadgeUI;
  window.fetchUnreadCount = fetchUnreadCount;
  window.fetchNotifications = fetchNotifications;
  window.loadDropdownNotifications = loadDropdownNotifications;
  window.loadNotificationsPageData = loadNotificationsPageData;
  window.initNotificationsPage = initNotificationsPage;
  window.markSingleNotificationRead = markSingleNotificationRead;
  window.markAllNotificationsAsRead = markAllNotificationsAsRead;
})();
