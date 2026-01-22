/**
 * Log Panel Manager - Real-time server log streaming
 */

class LogPanelManager {
    constructor(socket) {
        this.socket = socket;
        this.isSubscribed = false;
        this.autoScroll = true;
        this.maxEntries = 500;  // Keep last 500 entries
        this.enabledSources = new Set(['llm', 'tool', 'workflow']);  // Default: LLM, Tools, and Workflows
        
        // DOM elements
        this.panel = document.getElementById('logPanel');
        this.header = document.getElementById('logPanelHeader');
        this.toggle = document.getElementById('logPanelToggle');
        this.content = document.getElementById('logPanelContent');
        this.entries = document.getElementById('logEntries');
        this.sourceToggles = document.getElementById('logSourceToggles');
        this.clearBtn = document.getElementById('logClearBtn');
        this.scrollBtn = document.getElementById('logScrollBtn');
        this.resizeHandle = document.getElementById('logPanelResize');
        
        // Default height
        this.panelHeight = 200;
        this.isCollapsed = true;
        
        this._init();
    }
    
    _init() {
        // Start collapsed
        this.panel.classList.add('collapsed');
        this.panel.style.height = '40px';
        
        // Toggle collapse
        this.header.addEventListener('click', (e) => {
            // Don't toggle if clicking controls
            if (e.target.closest('.log-panel-controls')) return;
            this._toggleCollapse();
        });
        
        // Source toggles
        this.sourceToggles.querySelectorAll('.log-source-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const source = btn.dataset.source;
                btn.classList.toggle('active');
                
                if (btn.classList.contains('active')) {
                    this.enabledSources.add(source);
                } else {
                    this.enabledSources.delete(source);
                }
                
                // Update server-side filtering
                this._updateSourceFilter();
            });
        });
        
        // Clear button
        this.clearBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._clearEntries();
        });
        
        // Auto-scroll toggle
        this.scrollBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.autoScroll = !this.autoScroll;
            this.scrollBtn.dataset.enabled = this.autoScroll;
        });
        
        // Resize handle
        this._setupResize();
        
        // Socket events
        this._setupSocketEvents();
        
        // Load saved state
        this._loadState();
    }
    
    _toggleCollapse() {
        this.isCollapsed = !this.isCollapsed;
        
        if (this.isCollapsed) {
            this.panel.classList.add('collapsed');
            this.panel.style.height = '40px';
            document.body.classList.remove('log-panel-open');
            this._unsubscribe();
        } else {
            this.panel.classList.remove('collapsed');
            this.panel.style.height = `${this.panelHeight}px`;
            document.body.classList.add('log-panel-open');
            document.body.style.setProperty('--log-panel-height', `${this.panelHeight}px`);
            this._subscribe();
        }
        
        this._saveState();
    }
    
    _setupResize() {
        let startY, startHeight;
        
        const onMouseMove = (e) => {
            const deltaY = startY - e.clientY;
            const newHeight = Math.min(Math.max(startHeight + deltaY, 100), 600);
            this.panelHeight = newHeight;
            this.panel.style.height = `${newHeight}px`;
            document.body.style.setProperty('--log-panel-height', `${newHeight}px`);
        };
        
        const onMouseUp = () => {
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            this._saveState();
        };
        
        this.resizeHandle.addEventListener('mousedown', (e) => {
            e.preventDefault();
            startY = e.clientY;
            startHeight = this.panel.offsetHeight;
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    }
    
    _setupSocketEvents() {
        console.log('[LOGS] Setting up socket events, socket:', this.socket ? 'exists' : 'null');
        
        // Subscribed confirmation
        this.socket.on('logs:subscribed', (data) => {
            console.log('[LOGS] Subscribed to sources:', data.sources);
            this.isSubscribed = true;
            this._addSystemEntry('Connected - showing new log entries');
        });
        
        // Unsubscribed
        this.socket.on('logs:unsubscribed', () => {
            console.log('[LOGS] Unsubscribed from logs');
            this.isSubscribed = false;
        });
        
        // Log entry received
        this.socket.on('logs:entry', (entry) => {
            // Only show if source is enabled locally
            if (this.enabledSources.has(entry.source)) {
                this._addEntry(entry);
            }
        });
        
        // Sources updated
        this.socket.on('logs:sources_updated', (sources) => {
            console.log('[LOGS] Sources updated:', sources);
        });
    }
    
    _subscribe() {
        if (this.isSubscribed) return;
        
        this.socket.emit('logs:subscribe', {
            sources: Array.from(this.enabledSources)
        });
    }
    
    _unsubscribe() {
        if (!this.isSubscribed) return;
        
        this.socket.emit('logs:unsubscribe');
        this.isSubscribed = false;
    }
    
    _updateSourceFilter() {
        this.socket.emit('logs:set_sources', {
            sources: Object.fromEntries(
                ['llm', 'tool', 'workflow', 'opencode', 'thinking', 'feedback'].map(s => 
                    [s, this.enabledSources.has(s)]
                )
            )
        });
    }
    
    _addEntry(entry) {
        const div = document.createElement('div');
        div.className = `log-entry log-entry-${entry.level}`;
        
        // Make expandable if has details
        if (entry.details && Object.keys(entry.details).length > 0) {
            div.classList.add('expandable');
            div.addEventListener('click', () => {
                div.classList.toggle('expanded');
            });
        }
        
        // Format timestamp
        const time = new Date(entry.timestamp);
        const timeStr = time.toLocaleTimeString('en-US', { 
            hour12: false, 
            hour: '2-digit', 
            minute: '2-digit', 
            second: '2-digit' 
        });
        
        div.innerHTML = `
            <span class="log-time">${timeStr}</span>
            <span class="log-source log-source-${entry.source}">${entry.source.toUpperCase()}</span>
            <span class="log-message">${this._escapeHtml(entry.title)}</span>
            ${this._formatDetails(entry.details)}
        `;
        
        // Highlight new entry
        div.classList.add('new');
        setTimeout(() => div.classList.remove('new'), 1000);
        
        this.entries.appendChild(div);
        
        // Trim old entries
        while (this.entries.children.length > this.maxEntries) {
            this.entries.removeChild(this.entries.firstChild);
        }
        
        // Auto-scroll
        if (this.autoScroll) {
            this.entries.scrollTop = this.entries.scrollHeight;
        }
    }
    
    _addSystemEntry(message) {
        const div = document.createElement('div');
        div.className = 'log-entry log-entry-info';
        
        const time = new Date();
        const timeStr = time.toLocaleTimeString('en-US', { 
            hour12: false, 
            hour: '2-digit', 
            minute: '2-digit', 
            second: '2-digit' 
        });
        
        div.innerHTML = `
            <span class="log-time">${timeStr}</span>
            <span class="log-source log-source-sys">SYS</span>
            <span class="log-message">${this._escapeHtml(message)}</span>
        `;
        
        this.entries.appendChild(div);
        
        if (this.autoScroll) {
            this.entries.scrollTop = this.entries.scrollHeight;
        }
    }
    
    _formatDetails(details) {
        if (!details || Object.keys(details).length === 0) return '';
        
        const items = Object.entries(details)
            .filter(([k, v]) => v !== null && v !== undefined && v !== '')
            .map(([k, v]) => {
                let displayValue = v;
                if (typeof v === 'object') {
                    displayValue = JSON.stringify(v);
                } else if (typeof v === 'number' && k.includes('cost')) {
                    displayValue = `$${v.toFixed(4)}`;
                } else if (typeof v === 'number' && k.includes('duration')) {
                    displayValue = `${v.toFixed(0)}ms`;
                }
                // Format key nicely
                const formattedKey = k.replace(/_/g, ' ');
                return `<div><strong>${formattedKey}:</strong> ${this._escapeHtml(String(displayValue))}</div>`;
            })
            .join('');
        
        return `<div class="log-details">${items}</div>`;
    }
    
    _clearEntries() {
        // Keep only the system message
        this.entries.innerHTML = '';
        this._addSystemEntry('Logs cleared');
    }
    
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    _saveState() {
        localStorage.setItem('jarvis_log_panel', JSON.stringify({
            height: this.panelHeight,
            collapsed: this.isCollapsed,
            autoScroll: this.autoScroll,
            enabledSources: Array.from(this.enabledSources)
        }));
    }
    
    _loadState() {
        try {
            const saved = localStorage.getItem('jarvis_log_panel');
            if (saved) {
                const state = JSON.parse(saved);
                this.panelHeight = state.height || 200;
                this.autoScroll = state.autoScroll !== false;
                
                if (state.enabledSources) {
                    this.enabledSources = new Set(state.enabledSources);
                    
                    // Update UI toggles
                    this.sourceToggles.querySelectorAll('.log-source-btn').forEach(btn => {
                        const source = btn.dataset.source;
                        if (this.enabledSources.has(source)) {
                            btn.classList.add('active');
                        } else {
                            btn.classList.remove('active');
                        }
                    });
                }
                
                this.scrollBtn.dataset.enabled = this.autoScroll;
            }
        } catch (e) {
            console.warn('[LOGS] Failed to load saved state:', e);
        }
    }
    
    // Public method to programmatically open/close
    toggle() {
        this._toggleCollapse();
    }
    
    open() {
        if (this.isCollapsed) {
            this._toggleCollapse();
        }
    }
    
    close() {
        if (!this.isCollapsed) {
            this._toggleCollapse();
        }
    }
}

// Export for use in app.js
window.LogPanelManager = LogPanelManager;

