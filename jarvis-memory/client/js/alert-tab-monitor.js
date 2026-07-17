/**
 * Background alert monitoring for the Jarvis Memory browser tab.
 *
 * Existing pending alerts establish a silent baseline. Newly observed pending
 * alert IDs can animate the title/favicon and play one optional ding per poll.
 */
class AlertTabMonitor {
  constructor(options) {
    this.api = options.api;
    this.document = options.documentRef || document;
    this.window = options.windowRef || window;
    this.storage = options.storage || this.window.localStorage;
    this.soundButton = options.soundButton || null;
    this.isAlertsViewActive = options.isAlertsViewActive || (() => false);
    this.onPendingChange = options.onPendingChange || (() => {});
    this.onSoundChange = options.onSoundChange || (() => {});
    this.onSoundUnavailable = options.onSoundUnavailable || (() => {});
    this.pollIntervalMs = options.pollIntervalMs || 10000;

    this.baseTitle = this.document.title || 'Jarvis Memory';
    this.favicon = this.document.querySelector('#memoryFavicon') || this.document.querySelector('link[rel="icon"]');
    this.baseFaviconHref = this.favicon?.href || this._emojiFavicon('🧠');
    this.alertFaviconHref = this._emojiFavicon('🚨');

    this.storageKey = 'jarvis-memory-alert-sound';
    this.soundEnabled = this._readStoredSoundPreference();
    this.audioContext = null;
    this.knownPendingIds = new Set();
    this.pendingCount = 0;
    this.initialized = false;
    this.attentionActive = false;
    this.flashFrame = false;
    this.pollTimer = null;
    this.flashTimer = null;
    this.pollInFlight = false;
    this.generation = 0;
    this.requestSequence = 0;

    this._handleVisibilityChange = () => {
      if (!this.document.hidden) this.acknowledgeAttention();
    };
    this._handleWindowFocus = () => this.acknowledgeAttention();
    this._handleSoundClick = () => this.toggleSound();
  }

  async init() {
    this.soundButton?.addEventListener('click', this._handleSoundClick);
    this.document.addEventListener('visibilitychange', this._handleVisibilityChange);
    this.window.addEventListener('focus', this._handleWindowFocus);
    this._updateSoundButton();
    await this.reset();
    this.start();
  }

  destroy() {
    this.stop();
    this._stopFlashing();
    this.soundButton?.removeEventListener('click', this._handleSoundClick);
    this.document.removeEventListener('visibilitychange', this._handleVisibilityChange);
    this.window.removeEventListener('focus', this._handleWindowFocus);
  }

  start() {
    if (this.pollTimer) return;
    this.pollTimer = this.window.setInterval(() => this.check(), this.pollIntervalMs);
  }

  stop() {
    if (!this.pollTimer) return;
    this.window.clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  async reset() {
    this.generation += 1;
    this.initialized = false;
    this.knownPendingIds.clear();
    this.pendingCount = 0;
    this.acknowledgeAttention();
    await this.check({ baseline: true, force: true });
  }

  async check({ baseline = false, force = false } = {}) {
    if (this.pollInFlight && !force) return;

    const requestGeneration = this.generation;
    const requestSequence = ++this.requestSequence;
    if (!force) this.pollInFlight = true;

    try {
      const result = await this.api.listAlerts({ status: 'pending', limit: 300 });
      if (requestGeneration !== this.generation || requestSequence !== this.requestSequence) return;
      this._processPendingAlerts(result.alerts || [], baseline);
    } catch (error) {
      console.error('[AlertTabMonitor] Unable to check alerts:', error);
    } finally {
      if (!force) this.pollInFlight = false;
    }
  }

  acknowledgeAttention() {
    this.attentionActive = false;
    this._stopFlashing();
    this._updateTabDisplay();
  }

  setControlVisible(visible) {
    if (this.soundButton) {
      this.soundButton.style.display = visible ? 'inline-flex' : 'none';
    }
  }

  async toggleSound() {
    const nextValue = !this.soundEnabled;

    if (nextValue) {
      const available = await this._playDing();
      if (!available) {
        this.soundEnabled = false;
        this._storeSoundPreference();
        this._updateSoundButton();
        this.onSoundUnavailable();
        return false;
      }
    }

    this.soundEnabled = nextValue;
    this._storeSoundPreference();
    this._updateSoundButton();
    this.onSoundChange(this.soundEnabled);
    return this.soundEnabled;
  }

  _processPendingAlerts(pendingAlerts, baseline) {
    const nextIds = new Set(pendingAlerts.map(alert => String(alert.id)));
    const hadBaseline = this.initialized && !baseline;
    const newAlerts = hadBaseline
      ? pendingAlerts.filter(alert => !this.knownPendingIds.has(String(alert.id)))
      : [];
    const changed = hadBaseline && !this._setsEqual(nextIds, this.knownPendingIds);

    this.knownPendingIds = nextIds;
    this.pendingCount = pendingAlerts.length;
    this.initialized = true;

    if (this.pendingCount === 0 && this.attentionActive) {
      this.attentionActive = false;
      this._stopFlashing();
    }

    if (newAlerts.length > 0) {
      if (this.soundEnabled) void this._playDing();
      if (!this.isAlertsViewActive()) this._startFlashing();
    }

    this._updateTabDisplay();

    if (changed) {
      Promise.resolve(this.onPendingChange({
        pendingAlerts,
        pendingCount: this.pendingCount,
        newAlerts
      })).catch(error => console.error('[AlertTabMonitor] Pending-change callback failed:', error));
    }
  }

  _startFlashing() {
    this.attentionActive = true;
    this.flashFrame = true;
    this._updateTabDisplay();

    if (!this.flashTimer) {
      this.flashTimer = this.window.setInterval(() => {
        this.flashFrame = !this.flashFrame;
        this._updateTabDisplay();
      }, 900);
    }
  }

  _stopFlashing() {
    if (this.flashTimer) {
      this.window.clearInterval(this.flashTimer);
      this.flashTimer = null;
    }
    this.flashFrame = false;
  }

  _updateTabDisplay() {
    const plural = this.pendingCount === 1 ? '' : 'S';

    if (this.attentionActive) {
      this.document.title = this.flashFrame
        ? `${this.pendingCount} NEW ALERT${plural}`
        : this.baseTitle;
      if (this.favicon) {
        this.favicon.href = this.flashFrame ? this.alertFaviconHref : this.baseFaviconHref;
      }
      return;
    }

    this.document.title = this.pendingCount > 0
      ? `${this.pendingCount} · ${this.baseTitle}`
      : this.baseTitle;
    if (this.favicon) {
      this.favicon.href = this.pendingCount > 0 ? this.alertFaviconHref : this.baseFaviconHref;
    }
  }

  async _playDing() {
    const AudioContextClass = this.window.AudioContext || this.window.webkitAudioContext;
    if (!AudioContextClass) return false;

    try {
      if (!this.audioContext) this.audioContext = new AudioContextClass();
      if (this.audioContext.state === 'suspended') await this.audioContext.resume();

      const now = this.audioContext.currentTime;
      const oscillator = this.audioContext.createOscillator();
      const gain = this.audioContext.createGain();
      oscillator.type = 'sine';
      oscillator.frequency.setValueAtTime(880, now);
      oscillator.frequency.exponentialRampToValueAtTime(660, now + 0.35);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.055, now + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.45);
      oscillator.connect(gain);
      gain.connect(this.audioContext.destination);
      oscillator.start(now);
      oscillator.stop(now + 0.46);
      return true;
    } catch (error) {
      console.error('[AlertTabMonitor] Unable to play alert sound:', error);
      return false;
    }
  }

  _readStoredSoundPreference() {
    try {
      const stored = this.storage?.getItem(this.storageKey);
      // Default on when unset; respect an explicit stored preference.
      if (stored == null) return true;
      return stored === 'true';
    } catch (_) {
      return true;
    }
  }

  _storeSoundPreference() {
    try {
      this.storage?.setItem(this.storageKey, String(this.soundEnabled));
    } catch (_) {
      // Private browsing or hardened storage settings may reject writes.
    }
  }

  _updateSoundButton() {
    if (!this.soundButton) return;
    this.soundButton.textContent = this.soundEnabled ? '🔔' : '🔕';
    this.soundButton.classList.toggle('sound-enabled', this.soundEnabled);
    this.soundButton.setAttribute('aria-pressed', String(this.soundEnabled));
    this.soundButton.setAttribute('aria-label', this.soundEnabled ? 'Turn alert sound off' : 'Turn alert sound on');
    this.soundButton.title = this.soundEnabled ? 'Alert sound is on' : 'Alert sound is off';
  }

  _setsEqual(a, b) {
    if (a.size !== b.size) return false;
    for (const value of a) {
      if (!b.has(value)) return false;
    }
    return true;
  }

  _emojiFavicon(emoji) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">${emoji}</text></svg>`;
    return `data:image/svg+xml,${encodeURIComponent(svg)}`;
  }
}

window.AlertTabMonitor = AlertTabMonitor;
