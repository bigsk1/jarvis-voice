/**
 * Proactive Notification Manager
 * Handles alerts and reminders from jarvis-api
 */

class ProactiveManager {
  constructor(socket, app) {
    this.socket = socket;
    this.app = app;
    this.alerts = [];
    this.reminders = [];
    this.counts = { alerts: 0, reminders: 0 };
    this.pollInterval = null;
    this.notificationPermission = 'default';
    
    // UI Elements
    this.badge = null;
    this.panel = null;
    
    this._init();
  }
  
  _init() {
    // Request notification permission
    this._requestNotificationPermission();
    
    // Setup socket listeners
    this._setupSocketListeners();
    
    // Create UI elements
    this._createUI();
    
    // Start polling
    this._startPolling();
    
    // Subscribe to notifications
    this.socket.emit('proactive:subscribe', {});
  }
  
  async _requestNotificationPermission() {
    if (!('Notification' in window)) {
      console.log('[Proactive] Browser does not support notifications');
      return;
    }
    
    if (Notification.permission === 'granted') {
      this.notificationPermission = 'granted';
    } else if (Notification.permission !== 'denied') {
      try {
        const permission = await Notification.requestPermission();
        this.notificationPermission = permission;
      } catch (e) {
        console.log('[Proactive] Notification permission request failed:', e);
      }
    }
  }
  
  _setupSocketListeners() {
    // Counts update
    this.socket.on('proactive:counts', (data) => {
      console.log('[Proactive] Counts:', data);
      this.counts = data;
      this._updateBadge();
    });
    
    // New alert
    this.socket.on('proactive:alert', (data) => {
      console.log('[Proactive] New alert:', data);
      this._handleNewAlert(data.alert);
    });
    
    // New reminder
    this.socket.on('proactive:reminder', (data) => {
      console.log('[Proactive] New reminder:', data);
      this._handleNewReminder(data.reminder);
    });
    
    // Acknowledgment success
    this.socket.on('proactive:ack_success', (data) => {
      console.log('[Proactive] Acknowledged:', data);
      Utils.toast(`${data.type} acknowledged`, 'success');
      this._removeFromPanel(data.type, data.id);
    });
    
    // Error
    this.socket.on('proactive:error', (data) => {
      console.error('[Proactive] Error:', data);
      Utils.toast(data.error, 'error');
    });
  }
  
  _createUI() {
    // Create notification badge in header
    const header = document.querySelector('.header-actions');
    if (header) {
      const badgeContainer = document.createElement('div');
      badgeContainer.className = 'notification-badge-container';
      badgeContainer.innerHTML = `
        <button class="notification-badge-btn" title="Alerts & Reminders">
          <span class="notification-icon">🔔</span>
          <span class="notification-count" style="display: none;">0</span>
        </button>
      `;
      
      // Insert before settings button
      const settingsBtn = header.querySelector('.settings-btn');
      if (settingsBtn) {
        header.insertBefore(badgeContainer, settingsBtn);
      } else {
        header.appendChild(badgeContainer);
      }
      
      this.badge = badgeContainer.querySelector('.notification-count');
      
      // Click handler for badge
      badgeContainer.querySelector('.notification-badge-btn').addEventListener('click', () => {
        this._togglePanel();
      });
    }
    
    // Create notification panel
    this._createPanel();
  }
  
  _createPanel() {
    const panel = document.createElement('div');
    panel.className = 'notification-panel';
    panel.style.display = 'none';
    panel.innerHTML = `
      <div class="notification-panel-header">
        <h3>Notifications</h3>
        <button class="close-panel-btn">&times;</button>
      </div>
      <div class="notification-panel-content">
        <div class="notification-section alerts-section">
          <h4>🚨 Alerts</h4>
          <div class="alerts-list"></div>
        </div>
        <div class="notification-section reminders-section">
          <h4>⏰ Reminders</h4>
          <div class="reminders-list"></div>
        </div>
      </div>
      <div class="notification-panel-footer">
        <button class="refresh-btn">🔄 Refresh</button>
        <button class="ack-all-btn">✓ Acknowledge All</button>
      </div>
    `;
    
    document.body.appendChild(panel);
    this.panel = panel;
    
    // Event listeners
    panel.querySelector('.close-panel-btn').addEventListener('click', () => {
      this._hidePanel();
    });
    
    panel.querySelector('.refresh-btn').addEventListener('click', () => {
      this._checkNow();
    });
    
    panel.querySelector('.ack-all-btn').addEventListener('click', () => {
      this._acknowledgeAll();
    });
    
    // Close on outside click
    document.addEventListener('click', (e) => {
      if (this.panel.style.display !== 'none' && 
          !this.panel.contains(e.target) && 
          !e.target.closest('.notification-badge-container')) {
        this._hidePanel();
      }
    });
  }
  
  _updateBadge() {
    const total = (this.counts.alerts || 0) + (this.counts.reminders || 0);
    
    if (this.badge) {
      if (total > 0) {
        this.badge.textContent = total > 99 ? '99+' : total;
        this.badge.style.display = 'flex';
        this.badge.parentElement.classList.add('has-notifications');
      } else {
        this.badge.style.display = 'none';
        this.badge.parentElement.classList.remove('has-notifications');
      }
    }
  }
  
  _handleNewAlert(alert) {
    // Add to local list
    this.alerts.push(alert);
    
    // Update panel
    this._addToPanel('alert', alert);
    
    // Show browser notification
    this._showBrowserNotification(
      `🚨 Alert: ${alert.title}`,
      alert.description || `Source: ${alert.source}`,
      alert.severity
    );
    
    // Play TTS if enabled
    if (this.app.audioEnabled) {
      const message = `Alert: ${alert.title}. ${alert.description || ''}`;
      this.app._generateAndPlayTTS(message);
    }
    
    // Update counts
    this.counts.alerts = (this.counts.alerts || 0) + 1;
    this._updateBadge();
    
    // Flash the badge
    this._flashBadge();
  }
  
  _handleNewReminder(reminder) {
    // Add to local list
    this.reminders.push(reminder);
    
    // Update panel
    this._addToPanel('reminder', reminder);
    
    // Show browser notification
    this._showBrowserNotification(
      `⏰ Reminder: ${reminder.title}`,
      reminder.description || ''
    );
    
    // Play TTS if enabled
    if (this.app.audioEnabled) {
      const message = `Reminder: ${reminder.title}. ${reminder.description || ''}`;
      this.app._generateAndPlayTTS(message);
    }
    
    // Update counts
    this.counts.reminders = (this.counts.reminders || 0) + 1;
    this._updateBadge();
    
    // Flash the badge
    this._flashBadge();
  }
  
  _showBrowserNotification(title, body, severity = 'medium') {
    if (this.notificationPermission !== 'granted') {
      return;
    }
    
    try {
      const notification = new Notification(title, {
        body: body,
        icon: '/favicon.ico',
        tag: `jarvis-${Date.now()}`,
        requireInteraction: severity === 'critical' || severity === 'high'
      });
      
      // Focus window on click
      notification.onclick = () => {
        window.focus();
        this._showPanel();
        notification.close();
      };
      
      // Auto-close after 10 seconds (unless critical)
      if (severity !== 'critical') {
        setTimeout(() => notification.close(), 10000);
      }
    } catch (e) {
      console.error('[Proactive] Browser notification error:', e);
    }
  }
  
  _addToPanel(type, item) {
    const listSelector = type === 'alert' ? '.alerts-list' : '.reminders-list';
    const list = this.panel.querySelector(listSelector);
    
    if (!list) return;
    
    const itemEl = document.createElement('div');
    itemEl.className = `notification-item ${type}-item`;
    itemEl.dataset.id = item.id;
    
    const severityClass = item.severity ? `severity-${item.severity}` : '';
    
    itemEl.innerHTML = `
      <div class="notification-item-content ${severityClass}">
        <div class="notification-item-title">${Utils.escapeHtml(item.title)}</div>
        ${item.description ? `<div class="notification-item-desc">${Utils.escapeHtml(item.description)}</div>` : ''}
        <div class="notification-item-meta">
          ${item.source ? `<span class="source">${item.source}</span>` : ''}
          ${item.severity ? `<span class="severity ${item.severity}">${item.severity}</span>` : ''}
          ${item.trigger_time ? `<span class="time">${new Date(item.trigger_time).toLocaleString()}</span>` : ''}
        </div>
      </div>
      <button class="ack-btn" title="Acknowledge">✓</button>
    `;
    
    // Acknowledge button handler
    itemEl.querySelector('.ack-btn').addEventListener('click', () => {
      this._acknowledge(type, item.id);
    });
    
    list.appendChild(itemEl);
  }
  
  _removeFromPanel(type, id) {
    const listSelector = type === 'alert' ? '.alerts-list' : '.reminders-list';
    const list = this.panel.querySelector(listSelector);
    
    if (!list) return;
    
    const item = list.querySelector(`[data-id="${id}"]`);
    if (item) {
      item.remove();
    }
    
    // Update local list
    if (type === 'alert') {
      this.alerts = this.alerts.filter(a => a.id !== id);
    } else {
      this.reminders = this.reminders.filter(r => r.id !== id);
    }
  }
  
  _acknowledge(type, id) {
    if (type === 'alert') {
      this.socket.emit('proactive:ack_alert', { alert_id: id });
    } else {
      this.socket.emit('proactive:ack_reminder', { reminder_id: id });
    }
  }
  
  _acknowledgeAll() {
    // Acknowledge all visible items
    for (const alert of this.alerts) {
      this.socket.emit('proactive:ack_alert', { alert_id: alert.id });
    }
    for (const reminder of this.reminders) {
      this.socket.emit('proactive:ack_reminder', { reminder_id: reminder.id });
    }
    
    Utils.toast('Acknowledging all notifications...', 'info');
  }
  
  _togglePanel() {
    if (this.panel.style.display === 'none') {
      this._showPanel();
    } else {
      this._hidePanel();
    }
  }
  
  _showPanel() {
    this.panel.style.display = 'flex';
    this._checkNow(); // Refresh when opening
  }
  
  _hidePanel() {
    this.panel.style.display = 'none';
  }
  
  _flashBadge() {
    if (!this.badge) return;
    
    this.badge.classList.add('flash');
    setTimeout(() => {
      this.badge.classList.remove('flash');
    }, 1000);
  }
  
  _startPolling() {
    // Poll every 10 seconds
    this.pollInterval = setInterval(() => {
      this._checkNow();
    }, 10000);
  }
  
  _checkNow() {
    this.socket.emit('proactive:check', {});
  }
  
  stopPolling() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }
}

// Export for use in app.js
window.ProactiveManager = ProactiveManager;

