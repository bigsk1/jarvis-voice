/**
 * Prompt Library Settings
 * Manages private @prompts without changing chat command parsing semantics.
 */
class PromptLibrary {
  constructor(app) {
    this.app = app;
    this.modal = document.getElementById('settingsModal');
    this.panel = document.getElementById('settings-prompts');
    this.modeSelect = document.getElementById('prompt-preview-mode');
    this.contextLabel = document.getElementById('prompt-context-label');
    this.searchInput = document.getElementById('promptSearch');
    this.list = document.getElementById('promptList');
    this.status = document.getElementById('promptLibraryStatus');
    this.empty = document.getElementById('promptEditorEmpty');
    this.editor = document.getElementById('promptEditor');
    this.nameInput = document.getElementById('promptName');
    this.contentInput = document.getElementById('promptContent');
    this.toolSelect = document.getElementById('promptToolSelect');
    this.preview = document.getElementById('promptParsedPreview');
    this.validation = document.getElementById('promptValidation');
    this.saveButton = document.getElementById('savePromptBtn');
    this.duplicateButton = document.getElementById('duplicatePromptBtn');
    this.restoreButton = document.getElementById('restorePromptBtn');
    this.deleteButton = document.getElementById('deletePromptBtn');
    this.cancelButton = document.getElementById('cancelPromptBtn');

    this.records = [];
    this.tools = [];
    this.context = null;
    this.currentRecord = null;
    this.editorMode = null;
    this.cleanSnapshot = null;
    this.loading = false;
    this._requestId = 0;
    this._previewRequestId = 0;

    if (this.panel) this._bind();
  }

  _bind() {
    document.getElementById('newPromptBtn')?.addEventListener('click', () => this.newPrompt());
    document.getElementById('addPromptToolBtn')?.addEventListener('click', () => this.addSelectedTool());
    this.searchInput?.addEventListener('input', () => this.renderList());
    this.nameInput?.addEventListener('input', () => this.updateDraftPreview());
    this.contentInput?.addEventListener('input', () => this.updateDraftPreview());
    this.saveButton?.addEventListener('click', () => void this.save());
    this.duplicateButton?.addEventListener('click', () => this.duplicate());
    this.restoreButton?.addEventListener('click', () => void this.removePersonal(true));
    this.deleteButton?.addEventListener('click', () => void this.removePersonal(false));
    this.cancelButton?.addEventListener('click', () => this.cancelEdit());
    this.list?.addEventListener('click', event => {
      const button = event.target.closest('[data-prompt-name]');
      if (button) this.select(button.dataset.promptName);
    });
    this.modeSelect?.addEventListener('change', () => void this.changePreviewMode());
  }

  activeMode() {
    const value = this.app?.modeSelect?.value || this.app?.socket?.mode || 'cloud';
    return value === 'local' ? 'local' : 'cloud';
  }

  async setActive(active) {
    const wasActive = this._active === true;
    this._active = active;
    this.modal?.querySelector('.modal')?.classList.toggle('settings-modal-prompts', active);
    if (!active) return;
    if (wasActive && this.isDirty()) return;
    if (this.modeSelect && !this.isDirty()) this.modeSelect.value = this.activeMode();
    await this.load(this.modeSelect?.value || this.activeMode());
  }

  async changePreviewMode() {
    const selectedMode = this.modeSelect?.value === 'local' ? 'local' : 'cloud';
    const previewRequestId = ++this._previewRequestId;
    const modeLabel = selectedMode === 'local' ? 'Local' : 'Cloud';
    this.setStatus(`Refreshing ${modeLabel} availability…`);

    try {
      const response = await fetch(
        `/api/tools/refresh?mode=${encodeURIComponent(selectedMode)}`,
        {method: 'POST'}
      );
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || `Unable to refresh ${modeLabel} tools`);
      }
      if (previewRequestId !== this._previewRequestId) return;

      const draft = this.isDirty() ? this.captureDraft() : null;
      await this.load(selectedMode, {preserveDraft: draft});
    } catch (error) {
      if (previewRequestId !== this._previewRequestId) return;
      if (this.modeSelect && this.context?.mode) this.modeSelect.value = this.context.mode;
      this.setStatus(error.message || `Unable to refresh ${modeLabel} tools`, true);
    }
  }

  isDirty() {
    if (!this.editorMode || !this.cleanSnapshot) return false;
    return JSON.stringify(this.captureDraft()) !== JSON.stringify(this.cleanSnapshot);
  }

  confirmDiscard() {
    if (!this.isDirty()) return true;
    if (!window.confirm('Discard unsaved prompt changes?')) return false;
    this.resetEditor();
    return true;
  }

  captureDraft() {
    return {
      name: this.nameInput?.value || '',
      content: this.contentInput?.value || '',
      editorMode: this.editorMode,
      originName: this.currentRecord?.name || null
    };
  }

  async load(mode = null, { preserveDraft = null } = {}) {
    const selectedMode = mode === 'local' ? 'local' : 'cloud';
    const requestId = ++this._requestId;
    this.loading = true;
    this.setStatus('Loading prompts…');
    try {
      const response = await fetch(`/api/prompts/manage?mode=${encodeURIComponent(selectedMode)}`);
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to load prompts');
      if (requestId !== this._requestId) return;
      this.records = Array.isArray(data.prompts) ? data.prompts : [];
      this.tools = Array.isArray(data.tools) ? data.tools : [];
      this.context = data.context || { mode: selectedMode, tool_profile: 'default' };
      if (this.modeSelect) this.modeSelect.value = selectedMode;
      this.renderContext();
      this.renderToolPicker();
      this.renderList();
      this.setStatus(`${this.records.length} prompt${this.records.length === 1 ? '' : 's'}`);

      if (preserveDraft) {
        this.restoreDraft(preserveDraft);
      } else if (this.currentRecord) {
        const refreshed = this.records.find(item => item.name === this.currentRecord.name);
        if (refreshed) this.openRecord(refreshed, { skipDiscard: true });
        else this.resetEditor();
      }
    } catch (error) {
      if (requestId !== this._requestId) return;
      this.setStatus(error.message || 'Unable to load prompts', true);
    } finally {
      if (requestId === this._requestId) this.loading = false;
    }
  }

  renderContext() {
    if (!this.contextLabel || !this.context) return;
    const mode = this.context.mode === 'local' ? 'Local' : 'Cloud';
    this.contextLabel.textContent = (
      `Availability preview: ${mode} · ${this.context.tool_profile || 'default'} profile. `
      + 'Preview only — prompts are shared across modes.'
    );
  }

  setStatus(message, error = false) {
    if (!this.status) return;
    this.status.textContent = message;
    this.status.dataset.tone = error ? 'error' : 'neutral';
  }

  statusLabel(record) {
    const labels = {
      available: 'Available now',
      not_in_menu: 'Not in current @ menu',
      available_with_reduced_hints: 'Available with reduced hints',
      available_without_active_hints: 'Available without active hints',
      needs_repair: 'Needs repair'
    };
    return labels[record.availability_status] || 'Unknown';
  }

  sourceLabel(record) {
    if (record.overrides_shared) return 'Personal override';
    return record.source === 'personal' ? 'Personal' : 'Built-in';
  }

  _toolByName(name) {
    return this.tools.find(tool => tool?.name === name) || null;
  }

  _draftHintIsActive(name) {
    const tool = this._toolByName(name);
    return Boolean(tool && tool.enabled !== false && !tool.blocked);
  }

  _draftUnavailableReason(name) {
    const tool = this._toolByName(name);
    if (!tool) return `#${name} is not in the current tool registry`;
    if (tool.blocked) return `#${name} is blocked in Jarvis Web`;
    if (tool.available === false) {
      const missing = (tool.missing || []).map(String).filter(value => value.trim());
      return `#${name} is missing configuration${missing.length ? `: ${missing.join(', ')}` : ''}`;
    }
    if (tool.enabled === false) {
      const mode = this.context?.mode === 'local' ? 'Local' : 'Cloud';
      const profile = this.context?.tool_profile || 'default';
      return `#${name} is disabled by ${mode} · ${profile}`;
    }
    return `#${name} is not in the current tool registry`;
  }

  _draftDiagnostics(parsed, errors = []) {
    const toolHints = parsed.hints || [];
    const activeToolHints = toolHints.filter(name => this._draftHintIsActive(name));
    const inactiveToolHints = toolHints.filter(name => !activeToolHints.includes(name));
    if (errors.length) {
      return {
        availability_status: 'needs_repair',
        unavailable_reason: errors[0],
        active_tool_hints: activeToolHints,
        inactive_tool_hints: inactiveToolHints
      };
    }

    let runtimeVisible = true;
    if (toolHints.length === 1) {
      const tool = this._toolByName(toolHints[0]);
      runtimeVisible = Boolean(
        tool && tool.enabled !== false && tool.available !== false && !tool.blocked
      );
    }

    let availabilityStatus = 'available';
    let unavailableReason = null;
    if (!runtimeVisible) {
      availabilityStatus = 'not_in_menu';
      unavailableReason = this._draftUnavailableReason(toolHints[0]);
    } else if (toolHints.length > 1 && activeToolHints.length === 0) {
      availabilityStatus = 'available_without_active_hints';
    } else if (toolHints.length > 1 && activeToolHints.length < toolHints.length) {
      availabilityStatus = 'available_with_reduced_hints';
    }
    return {
      availability_status: availabilityStatus,
      unavailable_reason: unavailableReason,
      active_tool_hints: activeToolHints,
      inactive_tool_hints: inactiveToolHints
    };
  }

  _draftWarnings(content, parsed) {
    const warnings = [];
    if (!parsed.title) {
      warnings.push({message: 'Add a level-one heading for the prompt label.'});
    }
    if (content.length > 12000) {
      warnings.push({message: 'This prompt is unusually long and will consume substantial model context.'});
    }
    const hasAffirmativeSideEffect = (parsed.body || '').split(/\r?\n/).some(line => {
      const candidate = line.replace(/^[\s>*#\-\d.)]+/, '').trim();
      if (!candidate || /^(?:do not|don't|never|avoid|without)\b/i.test(candidate)) return false;
      return /^(?:always\s+)?(?:save|send|publish|remember|delete|modify)\b/i.test(candidate);
    });
    if (hasAffirmativeSideEffect) {
      warnings.push({message: 'Review unconditional save, send, publish, remember, delete, or modify instructions.'});
    }
    if (parsed.hints.length > 1) {
      warnings.push({message: 'Multiple hints keep the prompt visible as a group; inactive hints are filtered at send time.'});
    }
    for (const name of parsed.hints) {
      const tool = this._toolByName(name);
      if (!tool) {
        warnings.push({message: `#${name} is not in the current tool registry.`});
      } else if (tool.blocked) {
        warnings.push({message: `#${name} is blocked in Jarvis Web.`});
      } else if (tool.enabled === false) {
        warnings.push({message: `#${name} is disabled in the current mode or tool profile.`});
      } else if (tool.available === false) {
        warnings.push({message: `#${name} is missing required configuration.`});
      }
    }
    return warnings;
  }

  renderList() {
    if (!this.list) return;
    this.list.replaceChildren();
    const query = (this.searchInput?.value || '').trim().toLowerCase();
    const visible = this.records.filter(record => {
      const haystack = [
        record.name, record.description,
        ...(record.tool_hints || []), ...(record.key_points || [])
      ].join(' ').toLowerCase();
      return !query || haystack.includes(query);
    });

    if (!visible.length) {
      const note = document.createElement('p');
      note.className = 'prompt-list-empty';
      note.textContent = query ? 'No prompts match this search.' : 'No prompts found.';
      this.list.append(note);
      return;
    }

    for (const record of visible) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'prompt-list-item';
      button.dataset.promptName = record.name;
      button.classList.toggle('active', this.currentRecord?.name === record.name);

      const heading = document.createElement('span');
      heading.className = 'prompt-list-heading';
      const command = document.createElement('strong');
      command.textContent = `@${record.name}`;
      const source = document.createElement('span');
      source.className = `prompt-source-badge source-${record.overrides_shared ? 'override' : record.source}`;
      source.textContent = this.sourceLabel(record);
      heading.append(command, source);

      const title = document.createElement('span');
      title.className = 'prompt-list-title';
      title.textContent = record.description || 'Untitled prompt';

      const state = document.createElement('span');
      state.className = `prompt-availability status-${record.availability_status}`;
      state.textContent = this.statusLabel(record);
      if (record.unavailable_reason) state.title = record.unavailable_reason;

      const reason = document.createElement('span');
      reason.className = 'prompt-unavailable-reason';
      reason.textContent = record.unavailable_reason || '';
      reason.hidden = !record.unavailable_reason;

      const chips = document.createElement('span');
      chips.className = 'prompt-hint-row';
      for (const hint of record.tool_hints || []) {
        const chip = document.createElement('span');
        chip.className = `prompt-hint-chip ${(record.active_tool_hints || []).includes(hint) ? 'active' : 'inactive'}`;
        chip.textContent = `#${hint}`;
        chips.append(chip);
      }
      if ((record.warnings || []).length) {
        const warning = document.createElement('span');
        warning.className = 'prompt-warning-dot';
        warning.title = `${record.warnings.length} advisory warning${record.warnings.length === 1 ? '' : 's'}`;
        warning.textContent = '⚠';
        chips.append(warning);
      }

      button.append(heading, title, state, reason, chips);
      this.list.append(button);
    }
  }

  select(name) {
    const record = this.records.find(item => item.name === name);
    if (record) this.openRecord(record);
  }

  openRecord(record, { skipDiscard = false } = {}) {
    if (!skipDiscard && this.isDirty() && !this.confirmDiscard()) return;
    this.currentRecord = record;
    this.editorMode = record.source === 'personal' ? 'edit' : 'override';
    this.showEditor();
    this.nameInput.value = record.name;
    this.nameInput.disabled = true;
    this.contentInput.value = record.content || '';
    this.saveButton.textContent = record.source === 'personal'
      ? 'Save personal prompt'
      : 'Save personal override';
    this.restoreButton.hidden = !record.overrides_shared;
    this.deleteButton.hidden = record.source !== 'personal' || record.overrides_shared;
    this.duplicateButton.hidden = false;
    this.cleanSnapshot = this.captureDraft();
    this.renderList();
    this.updateDraftPreview();
  }

  showEditor() {
    if (this.empty) this.empty.hidden = true;
    if (this.editor) this.editor.hidden = false;
  }

  resetEditor() {
    this.currentRecord = null;
    this.editorMode = null;
    this.cleanSnapshot = null;
    if (this.editor) this.editor.hidden = true;
    if (this.empty) this.empty.hidden = false;
    if (this.validation) this.validation.replaceChildren();
    this.renderList();
  }

  newPrompt() {
    if (this.isDirty() && !this.confirmDiscard()) return;
    this.currentRecord = null;
    this.editorMode = 'new';
    this.showEditor();
    this.nameInput.disabled = false;
    this.nameInput.value = '';
    this.contentInput.value = '# Prompt title\n\nApply this guidance to the user\'s request.\n\n## Behavior\n\n- Preserve the user\'s explicit scope and constraints.\n\n## Output\n\n- Provide a clear, useful response.\n';
    this.saveButton.textContent = 'Save personal prompt';
    this.restoreButton.hidden = true;
    this.deleteButton.hidden = true;
    this.duplicateButton.hidden = true;
    this.cleanSnapshot = this.captureDraft();
    this.updateDraftPreview();
    this.nameInput.focus();
  }

  duplicate() {
    if (!this.editorMode) return;
    const draft = this.captureDraft();
    let base = `${draft.originName || draft.name || 'prompt'}_copy`.slice(0, 64);
    base = base.replace(/_+$/g, '') || 'prompt_copy';
    let candidate = base;
    let suffix = 2;
    while (this.records.some(item => item.name === candidate)) {
      candidate = `${base.slice(0, 61)}_${suffix++}`;
    }
    this.currentRecord = null;
    this.editorMode = 'new';
    this.nameInput.disabled = false;
    this.nameInput.value = candidate;
    this.contentInput.value = draft.content;
    this.saveButton.textContent = 'Save personal prompt';
    this.restoreButton.hidden = true;
    this.deleteButton.hidden = true;
    this.duplicateButton.hidden = true;
    this.cleanSnapshot = {
      name: '', content: '', editorMode: 'new', originName: null
    };
    this.updateDraftPreview();
    this.nameInput.focus();
    this.nameInput.select();
  }

  restoreDraft(draft) {
    this.currentRecord = draft.originName
      ? this.records.find(item => item.name === draft.originName) || null
      : null;
    this.editorMode = draft.editorMode;
    this.showEditor();
    this.nameInput.value = draft.name;
    this.nameInput.disabled = draft.editorMode !== 'new';
    this.contentInput.value = draft.content;
    this.saveButton.textContent = draft.editorMode === 'override'
      ? 'Save personal override'
      : 'Save personal prompt';
    this.restoreButton.hidden = !this.currentRecord?.overrides_shared;
    this.deleteButton.hidden = this.currentRecord?.source !== 'personal' || this.currentRecord?.overrides_shared;
    this.duplicateButton.hidden = draft.editorMode === 'new';
    this.renderList();
    this.updateDraftPreview();
  }

  cancelEdit() {
    if (this.isDirty() && !this.confirmDiscard()) return;
    this.resetEditor();
  }

  clientErrors() {
    const errors = [];
    const name = this.nameInput.value.trim();
    const content = this.contentInput.value;
    if (!name) errors.push('Prompt name is required.');
    else if (name.length > 64) errors.push('Prompt name must be at most 64 characters.');
    else if (!/^[a-z0-9]+(?:_[a-z0-9]+)*$/.test(name)) {
      errors.push('Use lowercase letters, numbers, and single underscores for the name.');
    } else if (['readme', 'manage', 'personal'].includes(name)) {
      errors.push(`@${name} is a reserved name.`);
    }
    if (!content.trim()) errors.push('Prompt content cannot be empty.');
    if (new TextEncoder().encode(content).length > 65536) errors.push('Prompt content must be 64 KiB or smaller.');
    const parsed = this.parseDraft(content);
    if (parsed.frontmatterOpen && !parsed.frontmatterClosed) errors.push('YAML frontmatter needs a closing --- delimiter.');
    if (new Set(parsed.hints).size !== parsed.hints.length) errors.push('Remove duplicate tool hints.');
    if (parsed.hints.length > 5) errors.push('Use no more than five tool hints.');
    return errors;
  }

  parseDraft(content) {
    const result = {
      title: '', hints: [], points: [], body: '',
      frontmatterOpen: false, frontmatterClosed: true
    };
    let body = content || '';
    const trimmed = body.trimStart();
    if (trimmed.startsWith('---')) {
      result.frontmatterOpen = true;
      const lines = trimmed.split(/\r?\n/);
      const closing = lines.findIndex((line, index) => index > 0 && line.trim() === '---');
      if (closing < 0) {
        result.frontmatterClosed = false;
      } else {
        const meta = lines.slice(1, closing);
        const hintLine = meta.findIndex(line => /^tool_hints\s*:/.test(line));
        if (hintLine >= 0) {
          const inline = meta[hintLine].match(/^tool_hints\s*:\s*\[(.*)\]\s*$/);
          if (inline) {
            result.hints = inline[1].split(',').map(item => item.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
          } else {
            for (const line of meta.slice(hintLine + 1)) {
              const match = line.match(/^\s*-\s*([^#]+?)(?:\s+#.*)?$/);
              if (!match) {
                if (/^[A-Za-z_][\w-]*\s*:/.test(line)) break;
                continue;
              }
              result.hints.push(match[1].trim().replace(/^['"]|['"]$/g, ''));
            }
          }
        }
        body = lines.slice(closing + 1).join('\n');
      }
    }
    result.body = body;
    const heading = body.match(/^#\s+(.+)$/m);
    result.title = heading ? heading[1].trim() : '';
    for (const line of body.split(/\r?\n/)) {
      const point = line.match(/^\s*(?:[-*•]|\d+[.):])\s+(.+)/);
      const section = line.match(/^##+\s+(.+)/);
      const text = point?.[1] || section?.[1];
      if (text) result.points.push(text.trim().slice(0, 80));
      if (result.points.length >= 5) break;
    }
    return result;
  }

  updateDraftPreview() {
    if (!this.editorMode) return;
    const content = this.contentInput.value;
    const parsed = this.parseDraft(content);
    const matchesLoadedRecord = Boolean(
      this.currentRecord
      && this.nameInput.value === this.currentRecord.name
      && content === (this.currentRecord.content || '')
    );
    const errors = this.clientErrors();
    if (matchesLoadedRecord && this.currentRecord?.parse_error) {
      errors.push(this.currentRecord.parse_error);
    }
    const diagnostics = matchesLoadedRecord
      ? this.currentRecord
      : this._draftDiagnostics(parsed, errors);
    const warnings = matchesLoadedRecord
      ? (this.currentRecord?.warnings || [])
      : this._draftWarnings(content, parsed);
    if (this.preview) {
      this.preview.replaceChildren();
      const fields = [
        ['Title', parsed.title || 'Missing level-one heading'],
        ['Source', this.editorMode === 'override' ? 'Personal override after save' : (this.currentRecord ? this.sourceLabel(this.currentRecord) : 'Personal after save')],
        ['Availability', this.statusLabel(diagnostics)],
        ['Tool hints', parsed.hints.length ? parsed.hints.map(name => `#${name}`).join(', ') : 'None'],
        ['Tooltip points', parsed.points.length ? parsed.points.join(' · ') : 'None']
      ];
      for (const [label, value] of fields) {
        const row = document.createElement('div');
        const key = document.createElement('strong');
        key.textContent = label;
        const text = document.createElement('span');
        text.textContent = value;
        row.append(key, text);
        this.preview.append(row);
      }
      if (diagnostics.unavailable_reason) {
        const reason = document.createElement('p');
        reason.textContent = diagnostics.unavailable_reason;
        this.preview.append(reason);
      }
    }
    this.renderValidation(errors, warnings);
  }

  renderValidation(errors = [], warnings = []) {
    if (!this.validation) return;
    this.validation.replaceChildren();
    for (const message of errors) {
      const item = document.createElement('p');
      item.className = 'prompt-validation-error';
      item.textContent = message;
      this.validation.append(item);
    }
    for (const warning of warnings) {
      const item = document.createElement('p');
      item.className = 'prompt-validation-warning';
      item.textContent = warning.message || String(warning);
      this.validation.append(item);
    }
  }

  renderToolPicker() {
    if (!this.toolSelect) return;
    const selected = this.toolSelect.value;
    this.toolSelect.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select an exact tool name…';
    this.toolSelect.append(placeholder);
    for (const tool of this.tools) {
      if (!tool?.name) continue;
      const option = document.createElement('option');
      option.value = tool.name;
      const inactive = tool.blocked || tool.enabled === false || tool.available === false;
      option.textContent = `#${tool.name}${inactive ? ' (inactive)' : ''}`;
      this.toolSelect.append(option);
    }
    if ([...this.toolSelect.options].some(option => option.value === selected)) {
      this.toolSelect.value = selected;
    }
  }

  addSelectedTool() {
    const name = this.toolSelect?.value;
    if (!name || !this.editorMode) return;
    const parsed = this.parseDraft(this.contentInput.value);
    if (parsed.hints.includes(name)) {
      const errors = [`#${name} is already in tool_hints.`, ...this.clientErrors()];
      this.renderValidation(
        errors,
        this._draftWarnings(this.contentInput.value, parsed)
      );
      return;
    }
    let content = this.contentInput.value;
    const trimmed = content.trimStart();
    if (!trimmed.startsWith('---')) {
      content = `---\ntool_hints:\n  - ${name}\n---\n\n${content}`;
    } else {
      const lines = content.split(/\r?\n/);
      const opening = lines.findIndex(line => line.trim() === '---');
      const closing = lines.findIndex((line, index) => index > opening && line.trim() === '---');
      const hintIndex = lines.findIndex((line, index) => index > opening && index < closing && /^tool_hints\s*:/.test(line));
      if (closing < 0) {
        this.renderValidation(['Close the YAML frontmatter before adding a tool hint.']);
        return;
      }
      if (hintIndex < 0) {
        lines.splice(closing, 0, 'tool_hints:', `  - ${name}`);
      } else {
        const inline = lines[hintIndex].match(/^tool_hints\s*:\s*\[(.*)\]\s*$/);
        if (inline) {
          const existing = parsed.hints.map(hint => `  - ${hint}`);
          lines.splice(hintIndex, 1, 'tool_hints:', ...existing, `  - ${name}`);
        } else {
          let insertAt = hintIndex + 1;
          while (insertAt < closing && /^\s*-\s*/.test(lines[insertAt])) insertAt += 1;
          lines.splice(insertAt, 0, `  - ${name}`);
        }
      }
      content = lines.join('\n');
    }
    this.contentInput.value = content;
    this.updateDraftPreview();
    this.contentInput.focus();
  }

  async save() {
    const errors = this.clientErrors();
    if (errors.length) {
      this.renderValidation(errors, this.currentRecord?.warnings || []);
      return;
    }
    const name = this.nameInput.value.trim();
    const isUpdate = this.editorMode === 'edit' && this.currentRecord?.source === 'personal';
    const endpoint = isUpdate
      ? `/api/prompts/personal/${encodeURIComponent(name)}?mode=${encodeURIComponent(this.modeSelect.value)}`
      : `/api/prompts/personal?mode=${encodeURIComponent(this.modeSelect.value)}`;
    const payload = {
      name,
      content: this.contentInput.value,
      override_shared: this.editorMode === 'override'
    };
    this.saveButton.disabled = true;
    try {
      const response = await fetch(endpoint, {
        method: isUpdate ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to save prompt');
      this.cleanSnapshot = this.captureDraft();
      await this.load(this.modeSelect.value);
      this.select(name);
      await window.commandSystem?.refreshTools?.(this.activeMode());
      Utils.toast(data.message || `Saved @${name}`, 'success');
    } catch (error) {
      this.renderValidation([error.message || 'Unable to save prompt']);
    } finally {
      this.saveButton.disabled = false;
    }
  }

  async removePersonal(restore) {
    const record = this.currentRecord;
    if (!record || record.source !== 'personal') return;
    const action = restore ? 'restore the built-in prompt' : 'delete this personal prompt';
    if (!window.confirm(`@${record.name}: ${action}?`)) return;
    try {
      const response = await fetch(
        `/api/prompts/personal/${encodeURIComponent(record.name)}?mode=${encodeURIComponent(this.modeSelect.value)}`,
        { method: 'DELETE' }
      );
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to remove prompt');
      this.resetEditor();
      await this.load(this.modeSelect.value);
      await window.commandSystem?.refreshTools?.(this.activeMode());
      Utils.toast(data.message, 'success');
    } catch (error) {
      this.renderValidation([error.message || 'Unable to remove prompt']);
    }
  }
}

window.PromptLibrary = PromptLibrary;
