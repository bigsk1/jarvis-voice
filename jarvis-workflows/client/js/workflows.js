/* Standalone, dependency-free workflow editor. */
(function () {
    'use strict';
    const M = window.WorkflowModel;
    const $ = id => document.getElementById(id);
    const state = {workflow: null, source: null, baseline: null, draft: null, sources: [], tools: [],
        selected: null, dirty: false, generation: 0, history: null, saving: null, tab: 'lane',
        insertAt: 0, dragIndex: null, dragTool: null, run: null, cursor: 0, pollTimer: null, saveTimer: null,
        rawDirty: false, approvals: new Set(), statuses: new Map()};
    let noticeTimer, fieldSequence = 0, activeHelp = null;
    function node(tag, attributes = {}, ...children) {
        const element = document.createElement(tag);
        for (const [key, value] of Object.entries(attributes)) {
            if (key.startsWith('on')) element.addEventListener(key.slice(2), value);
            else if (key === 'class') element.className = value;
            else if (key === 'text') element.textContent = value;
            else if (value !== null && value !== undefined && value !== false) element.setAttribute(key, value === true ? '' : value);
        }
        for (const child of children.flat()) if (child !== null && child !== undefined) {
            element.append(typeof child === 'string' ? document.createTextNode(child) : child);
        }
        return element;
    }
    function notice(message, error = false) {
        $('notice').textContent = message; $('notice').classList.toggle('error', error);
        $('notice').hidden = false; clearTimeout(noticeTimer);
        noticeTimer = setTimeout(() => { $('notice').hidden = true; }, error ? 9000 : 4500);
    }
    function handled(action) { return (...args) => Promise.resolve().then(() => action(...args)).catch(error => notice(error.message, true)); }
    function token() {
        const cookie = document.cookie.split(';').map(part => part.trim()).find(part => part.startsWith('jarvis_auth='));
        return cookie ? decodeURIComponent(cookie.slice('jarvis_auth='.length)) : localStorage.getItem('jarvis_auth_token');
    }
    async function api(path, method = 'GET', body) {
        const headers = {};
        if (token()) headers.Authorization = `Bearer ${token()}`;
        if (body !== undefined) headers['Content-Type'] = 'application/json';
        const response = await fetch(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)});
        if (response.status === 401) { location.assign('/login?redirect=' + encodeURIComponent(location.pathname + location.search)); throw new Error('Sign in to continue.'); }
        let data;
        try { data = await response.json(); } catch (_) { throw new Error('The server returned an unreadable response.'); }
        if (!response.ok || data.ok === false) {
            if (data.errors) showDiagnostics(data);
            throw new Error(data.error || 'The request could not be completed.');
        }
        return data;
    }
    const definitionOf = value => value.workflow || value.definition;
    function setStatus(text) { $('saveState').textContent = text; }
    function canonical(value) {
        if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
        if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
        return JSON.stringify(value);
    }
    function publishedUnchanged() {
        return Boolean(state.source?.hash && state.baseline && state.source.effective &&
            canonical(state.workflow) === canonical(state.baseline) && !state.rawDirty);
    }
    function updateHeading() {
        $('recipeTitle').textContent = state.workflow?.name || state.workflow?.id || 'Build your next workflow';
        $('recipeDescription').textContent = state.workflow?.description || 'Connect your tools to a useful outcome.';
        $('sourceLabel').textContent = state.source ? `${state.source.tier === 'shared' ? 'BUNDLED RECIPE' : 'PERSONAL RECIPE'} · ${state.source.filename}` : 'PERSONAL DRAFT';
        for (const id of ['settingsButton', 'validateButton', 'publishButton', 'undoButton', 'redoButton']) $(id).disabled = !state.workflow;
        $('undoButton').disabled = !state.history?.undoStack.length;
        $('redoButton').disabled = !state.history?.redoStack.length;
        $('runButton').disabled = !publishedUnchanged() || Boolean(state.run && !terminal(state.run.status));
        $('runHint').textContent = publishedUnchanged() ? 'Runs use real tools and update real state. Review the effects before starting.' : 'Publish your current changes before a live run.';
    }
    async function refreshLibrary() {
        const [recipes, drafts] = await Promise.all([api('/api/workflows'), api('/api/drafts')]);
        state.sources = recipes.workflows || []; renderLibrary();
        $('draftList').replaceChildren(...(drafts.drafts || []).map(draft => {
            const definition = definitionOf(draft) || {};
            return node('button', {class: 'recipe-item', onclick: handled(() => openDraft(draft.id))},
                node('strong', {text: definition.name || definition.id || draft.name || 'Untitled draft'}), node('small', {text: 'Draft · ' + (draft.updated_at || '')}));
        }));
        if (!$('draftList').children.length) $('draftList').append(node('p', {class: 'muted', text: 'No saved drafts yet.'}));
    }
    function renderLibrary() {
        const query = $('librarySearch').value.toLowerCase();
        const commands = source => Array.isArray(source.commands) ? source.commands.filter(command => typeof command === 'string').join(' ') : '';
        $('recipeList').replaceChildren(...state.sources.filter(source =>
            `${source.id} ${source.name} ${source.description} ${commands(source)}`.toLowerCase().includes(query)).map(source => {
            const flags = [source.tier, source.shadowed ? 'shadowed' : '', source.enabled === false ? 'disabled' : '',
                source.duplicate_id || source.duplicate ? 'duplicate ID' : '', source.errors?.length ? 'invalid' : ''].filter(Boolean);
            return node('button', {class: 'recipe-item' + (state.source?.source_id === source.source_id ? ' active' : ''),
                onclick: handled(() => openSource(source.source_id))}, node('strong', {text: source.name || source.id || source.filename}),
            node('small', {text: flags.join(' · ')}), node('code', {text: commands(source)}));
        }));
    }
    async function beforeNavigation() {
        if (state.rawDirty && !window.confirm('Discard the JSON changes you have not applied?')) return false;
        state.rawDirty = false; await flushSave(); return true;
    }
    function loadDocument(workflow, draft = null, source = null, baseline = null) {
        clearTimeout(state.saveTimer); state.workflow = M.clone(workflow); state.draft = draft; state.source = source;
        state.baseline = baseline && M.clone(baseline); state.selected = null; state.dirty = false; state.rawDirty = false;
        state.generation++; state.history = new M.History(state.workflow); state.statuses.clear();
        $('diagnostics').hidden = true; setStatus(draft ? 'Draft saved' : 'Published'); render(); renderInspector(); renderLibrary();
        if (draft) sessionStorage.setItem('jarvis_workflow_draft', draft.id);
        else sessionStorage.removeItem('jarvis_workflow_draft');
    }
    async function openSource(id) {
        if (!await beforeNavigation()) return;
        let data;
        try { data = await api('/api/workflows/' + encodeURIComponent(id)); }
        catch (error) {
            const source = state.sources.find(item => item.source_id === id);
            if (source?.errors?.length) showDiagnostics({errors: source.errors, warnings: []});
            throw error;
        }
        loadDocument(definitionOf(data), null, data.source, definitionOf(data));
    }
    async function openDraft(id) {
        if (!await beforeNavigation()) return;
        const {draft} = await api('/api/drafts/' + encodeURIComponent(id));
        let source = null, baseline = null;
        if (draft.source_id) {
            try { const data = await api('/api/workflows/' + encodeURIComponent(draft.source_id)); source = data.source; baseline = definitionOf(data); } catch (_) { /* A removed source remains an editable draft. */ }
        }
        loadDocument(definitionOf(draft), draft, source, baseline);
    }
    async function createDraft(workflow = M.createRecipe()) {
        if (!await beforeNavigation()) return;
        const {draft} = await api('/api/drafts', 'POST', {workflow});
        loadDocument(definitionOf(draft), draft); await refreshLibrary(); renderInspector();
    }
    function commit(workflow, {inspector = false, explicitAutonomy = false} = {}) {
        if (!state.workflow) return;
        if (!state.draft && !Object.hasOwn(workflow, 'builder_policy_version') && !explicitAutonomy) workflow.allow_workflow_tool = false;
        if (!state.history.commit(workflow)) return;
        state.workflow = M.clone(workflow); state.dirty = true; state.generation++;
        setStatus('Saving draft…'); render(); if (inspector) renderInspector(); scheduleSave();
    }
    function scheduleSave() { clearTimeout(state.saveTimer); state.saveTimer = setTimeout(handled(flushSave), 700); }
    async function flushSave() {
        clearTimeout(state.saveTimer);
        if (state.saving) { await state.saving; if (state.dirty) return flushSave(); return; }
        if (!state.dirty || !state.workflow) return;
        state.saving = (async () => {
            while (state.dirty) {
                const generation = state.generation, definition = M.clone(state.workflow);
                const data = state.draft ? await api('/api/drafts/' + encodeURIComponent(state.draft.id), 'PATCH',
                    {workflow: definition, revision: state.draft.revision}) : await api('/api/drafts', 'POST',
                    {source_id: state.source?.source_id, workflow: definition});
                state.draft = data.draft;
                sessionStorage.setItem('jarvis_workflow_draft', state.draft.id);
                if (generation === state.generation) {
                    state.workflow = M.clone(definitionOf(state.draft)); state.dirty = false; setStatus('Draft saved');
                    if (!state.rawDirty) $('recipeJSON').value = JSON.stringify(state.workflow, null, 2);
                }
            }
        })();
        try { await state.saving; } catch (error) { setStatus('Draft not saved'); throw error; }
        finally { state.saving = null; updateHeading(); }
    }
    function render() {
        updateHeading(); $('editorEmpty').hidden = Boolean(state.workflow);
        $('laneView').hidden = !state.workflow || state.tab !== 'lane'; $('jsonView').hidden = !state.workflow || state.tab !== 'json';
        if (!state.workflow) return;
        if (!state.rawDirty) $('recipeJSON').value = JSON.stringify(state.workflow, null, 2);
        const lane = $('stepLane'); lane.replaceChildren();
        lane.append(makeCard(null));
        const steps = Array.isArray(state.workflow.steps) ? state.workflow.steps : [];
        steps.forEach((step, index) => { lane.append(makeConnector(index), makeCard(index)); });
        lane.append(makeConnector(steps.length), node('div', {class: 'node-card terminal-card'},
            node('div', {class: 'node-top'}, node('span', {class: 'node-icon', text: '✓'}), node('div', {class: 'node-copy'},
                node('strong', {text: 'Complete'}), node('small', {text: 'Return the result and completion speech'})))));
    }
    function makeConnector(index) {
        const connector = node('div', {class: 'connector'}, node('button', {class: 'insert-btn', title: 'Insert tool here',
            'aria-label': `Insert tool at position ${index + 1}`, onclick: handled(() => openTools(index))}, '+'));
        connector.addEventListener('dragover', event => { if (state.dragTool || state.dragIndex !== null) { event.preventDefault(); connector.classList.add('drop-target'); } });
        connector.addEventListener('dragleave', () => connector.classList.remove('drop-target'));
        connector.addEventListener('drop', event => {
            event.preventDefault(); connector.classList.remove('drop-target');
            if (state.dragTool) { insertTool(state.dragTool, index); state.dragTool = null; }
            else if (state.dragIndex !== null) reorderBefore(state.dragIndex, index);
        });
        return connector;
    }
    function makeCard(index) {
        const start = index === null, rawStep = start ? null : state.workflow.steps[index];
        const step = start ? null : rawStep && typeof rawStep === 'object' ? rawStep : {tool: 'Invalid step — edit JSON', step: '?'};
        const card = node('div', {class: 'node-card' + (state.selected === index ? ' selected' : ''), tabindex: '0', role: 'button',
            'aria-label': start ? 'Query and workflow settings' : `Position ${index + 1}: ${step.tool}, label ${step.step}`,
            onclick: () => select(index), onkeydown: event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(index); } }});
        const copy = node('div', {class: 'node-copy'}, node('strong', {text: start ? 'Query' : step.description || step.tool}),
            node('small', {text: start ? 'One query string · variable extraction' : `${index + 1} of ${state.workflow.steps.length} · step label ${step.step} · ${step.tool}`}));
        const top = node('div', {class: 'node-top'}, node('span', {class: 'node-icon', text: start ? '↗' : String(index + 1).padStart(2, '0')}), copy);
        if (!start) {
            const actions = node('div', {class: 'node-actions'});
            for (const [symbol, label, callback, disabled] of [
                ['↑', 'Move step up', () => reorder(index, index - 1), index === 0],
                ['↓', 'Move step down', () => reorder(index, index + 1), index === state.workflow.steps.length - 1],
            ]) actions.append(node('button', {class: 'icon-btn', 'aria-label': label, title: label, disabled,
                onclick: event => { event.stopPropagation(); callback(); }}, symbol));
            top.append(actions); card.draggable = true; card.dataset.index = index;
            card.addEventListener('dragstart', event => { state.dragIndex = index; event.dataTransfer.setData('text/plain', String(index)); event.dataTransfer.effectAllowed = 'move'; card.classList.add('dragging'); });
            card.addEventListener('dragend', () => { state.dragIndex = null; card.classList.remove('dragging'); });
            card.addEventListener('dragover', event => { if (state.dragIndex !== null || state.dragTool) { event.preventDefault(); card.classList.add('drop-target'); } });
            card.addEventListener('dragleave', () => card.classList.remove('drop-target'));
            card.addEventListener('drop', event => { event.preventDefault(); card.classList.remove('drop-target'); if (state.dragTool) { insertTool(state.dragTool, index); state.dragTool = null; } else if (state.dragIndex !== null) reorderBefore(state.dragIndex, index); });
            const sameRecipe = state.run?.source_id === state.source?.source_id &&
                state.run?.hash === state.source?.hash && publishedUnchanged();
            const status = sameRecipe ? state.statuses.get(index) : null;
            if (status) { card.dataset.runStatus = status; copy.append(node('span', {class: 'node-status ' + status, text: status.replaceAll('_', ' ')})); }
        }
        card.append(top);
        if (step) {
            const badges = node('div', {class: 'node-badges'});
            if (step.for_each) badges.append(node('span', {class: 'node-badge', text: '↻ Repeat'}));
            if (step.condition) badges.append(node('span', {class: 'node-badge', text: 'Condition'}));
            if (step.llm_prompt) badges.append(node('span', {class: 'node-badge', text: 'LLM prompt'}));
            if (step.required === false) badges.append(node('span', {class: 'node-badge', text: 'Optional'}));
            M.bindings(step).slice(0, 5).forEach(binding => badges.append(node('span', {class: 'binding-chip', text: '${' + binding + '}'})));
            if (badges.children.length) card.append(badges);
        }
        return card;
    }
    function select(index) { state.selected = index; render(); renderInspector(); }
    function reorder(from, to) { state.selected = to; commit(M.moveStep(state.workflow, from, to), {inspector: true}); }
    function reorderBefore(from, before) {
        state.selected = Math.min(before > from ? before - 1 : before, state.workflow.steps.length - 1);
        commit(M.dropStepBefore(state.workflow, from, before), {inspector: true});
    }
    function patch(path, value) {
        const workflow = M.clone(state.workflow); let target = workflow;
        for (const key of path.slice(0, -1)) { if (!target[key] || typeof target[key] !== 'object') target[key] = {}; target = target[key]; }
        if (value === undefined) delete target[path.at(-1)]; else target[path.at(-1)] = value;
        commit(workflow, {explicitAutonomy: path.length === 1 && path[0] === 'allow_workflow_tool'});
    }
    function addFieldHelp(container, heading, title, help, input) {
        if (!help) return;
        const helpId = 'workflow-help-' + fieldSequence;
        let pinned = false;
        const button = node('button', {type: 'button', class: 'field-help-button', 'aria-label': 'Help for ' + title,
            'aria-controls': helpId, 'aria-expanded': 'false'}, '?');
        const panel = node('div', {id: helpId, class: 'field-help-panel', role: 'note', 'aria-label': title + ' examples', hidden: true},
            node('p', {text: help.description}), node('strong', {text: help.format + ' example'}),
            node('pre', {tabindex: '0', text: help.example}), help.note ? node('p', {class: 'muted', text: help.note}) : null);
        const close = () => { panel.hidden = true; pinned = false; button.setAttribute('aria-expanded', 'false'); if (activeHelp === close) activeHelp = null; };
        const show = () => { if (activeHelp && activeHelp !== close) activeHelp(); activeHelp = close; panel.hidden = false; button.setAttribute('aria-expanded', 'true'); };
        heading.addEventListener('pointerenter', event => { if (event.pointerType !== 'touch') show(); });
        button.addEventListener('focus', show);
        button.addEventListener('click', () => { if (pinned) close(); else { pinned = true; show(); } });
        container.addEventListener('pointerleave', () => { if (!pinned && !container.contains(document.activeElement)) close(); });
        container.addEventListener('focusout', event => { if (!pinned && !container.contains(event.relatedTarget)) close(); });
        container.addEventListener('keydown', event => { if (event.key === 'Escape') { close(); event.stopPropagation(); } });
        input.setAttribute('aria-describedby', helpId); heading.append(button); container.append(panel);
    }
    function field(parent, title, path, {kind = 'text', description = '', choices = null, value, binding = false, help = window.WorkflowHelp.forField(path)} = {}) {
        const container = node('div', {class: 'field'}); let input;
        const inputId = 'workflow-field-' + (++fieldSequence);
        const fieldLabel = node('label', {text: title, for: inputId});
        const heading = node('div', {class: 'field-heading'}, fieldLabel); container.append(heading);
        if (kind === 'json') {
            input = node('textarea', {spellcheck: 'false', 'aria-label': title}); input.value = value === undefined ? '' : JSON.stringify(value, null, 2);
        } else if (choices && !binding) {
            input = node('select', {'aria-label': title});
            input.append(node('option', {value: '', text: 'Use default'}));
            choices.forEach(choice => input.append(node('option', {value: String(choice), text: String(choice)})));
            input.value = value === undefined ? '' : String(value);
        } else if (kind === 'boolean' && !binding) {
            input = node('select', {'aria-label': title});
            [['', 'Use default'], ['true', 'True'], ['false', 'False']].forEach(([v, text]) => input.append(node('option', {value: v, text})));
            input.value = value === undefined ? '' : String(value);
        } else {
            input = node(kind === 'textarea' ? 'textarea' : 'input', {'aria-label': title, spellcheck: 'false'});
            input.value = value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
            if (binding) input.placeholder = '${topic} or ${previous_output.path}';
            if (kind === 'number' && !binding) input.type = 'number';
        }
        input.id = inputId;
        input.addEventListener('focus', () => { state.focusedInput = input; });
        input.addEventListener('change', () => {
            try {
                let next = input.value === '' ? undefined : input.value;
                if (next !== undefined && kind === 'json' && !/^\$\{[^}]+\}$/.test(next)) next = JSON.parse(next);
                else if (next !== undefined && kind === 'number' && !String(next).includes('${')) { next = Number(next); if (!Number.isFinite(next)) throw new Error('Enter a number.'); }
                else if (next !== undefined && kind === 'boolean' && !String(next).includes('${')) next = next === 'true';
                input.setCustomValidity(''); patch(path, next);
            } catch (error) { input.setCustomValidity(error.message); input.reportValidity(); }
        });
        addFieldHelp(container, heading, title, help, input); container.append(input);
        if (description) container.append(node('p', {class: 'field-description', text: description}));
        parent.append(container); return input;
    }
    function check(parent, title, path, value) {
        const input = node('input', {type: 'checkbox'}); input.checked = value === true;
        input.addEventListener('change', () => patch(path, input.checked));
        parent.append(node('label', {class: 'checkbox-field'}, input, node('span', {text: title})));
    }
    function advanced(parent, title, entries, prefix, object) {
        const section = node('details', {}, node('summary', {text: title}));
        for (const [key, label, kind] of entries) field(section, label, [...prefix, key], {kind: kind || 'json', value: object[key]});
        parent.append(section);
    }
    function preservedFields(parent, object, fields) {
        const present = fields.filter(([key]) => Object.hasOwn(object, key));
        if (!present.length) return;
        const section = node('details', {class: 'preserved-fields'}, node('summary', {text: 'Unused fields (preserved)'}),
            node('p', {class: 'field-description', text: 'These values stay in the recipe JSON, but do not affect execution.'}));
        present.forEach(([key, note]) => section.append(node('strong', {text: key}), node('p', {class: 'field-description', text: note}), node('pre', {text: JSON.stringify(object[key], null, 2)})));
        parent.append(section);
    }
    function renderInspector() {
        if (activeHelp) activeHelp();
        const body = $('inspectorBody'); body.replaceChildren(); state.focusedInput = null;
        if (!state.workflow) { $('inspectorTitle').textContent = 'Make it yours'; body.append(node('p', {class: 'muted', text: 'Select a step to configure its inputs, conditions, and outputs.'})); return; }
        if (state.selected === null) {
            const workflow = state.workflow; $('inspectorTitle').textContent = 'Recipe settings';
            field(body, 'Workflow ID', ['id'], {value: workflow.id, description: 'New IDs use lowercase letters, digits, and underscores.'});
            field(body, 'Name', ['name'], {value: workflow.name}); field(body, 'Description', ['description'], {value: workflow.description, kind: 'textarea'});
            field(body, 'Commands', ['triggers', 'explicit'], {kind: 'json', value: workflow.triggers?.explicit, description: 'A JSON list, such as ["/my_recipe"]. Matching uses the longest prefix.'});
            check(body, 'Allow Jarvis to choose this recipe autonomously', ['allow_workflow_tool'], workflow.allow_workflow_tool !== false);
            check(body, 'Disable provider-side tools in workflow LLM calls', ['disable_server_side_tools'], workflow.disable_server_side_tools);
            field(body, 'Variables / query extraction', ['variables'], {kind: 'json', value: workflow.variables || {}, description: 'Optional: leave {} to use the built-in ${topic}. Open ? for formats and examples.'});
            advanced(body, 'Tool defaults and validation', [['tool_defaults', 'Tool defaults'], ['validation_policy', 'Validation policy'], ['workflow_llm_options', 'Workflow LLM options']], [], workflow);
            advanced(body, 'Completion speech', [['success_speech', 'Success speech', 'textarea'], ['abort_speech', 'Abort speech', 'textarea'], ['success_speech_llm_prompt', 'Completion LLM prompt', 'textarea']], [], workflow);
            preservedFields(body, workflow, [['retry', 'Use step Retry settings to limit loop candidates, and Validation policy for the total failure limit.'], ['partial_speech', 'Partial live runs use their own completion message.']]);
            const actions = node('div', {class: 'inspector-actions'}, node('button', {class: 'ghost-btn', onclick: exportRecipe}, 'Export JSON'));
            if (state.source?.tier === 'personal') actions.append(node('button', {class: 'danger-btn', onclick: handled(removePersonal)}, 'Remove personal recipe'));
            body.append(actions); return;
        }
        const index = state.selected, step = state.workflow.steps[index], prefix = ['steps', index];
        if (!step || typeof step !== 'object') { $('inspectorTitle').textContent = 'Invalid step'; body.append(node('p', {class: 'error-text', text: 'Open JSON to repair this step. Its original value is preserved.'})); return; }
        $('inspectorTitle').textContent = step.tool;
        body.append(node('p', {class: 'muted', text: `Position ${index + 1} · step label ${step.step} (preserved when reordered)`}));
        field(body, 'Step description', [...prefix, 'description'], {value: step.description});
        const tool = state.tools.find(item => item.name === step.tool);
        if (!tool) body.append(node('p', {class: 'field-description', text: 'Schema not cached. Existing parameters remain editable below; explicitly refresh MCP tools to discover more.'}));
        else if (tool.available === false) body.append(node('p', {class: 'error-text', text: tool.unavailable_reason || tool.reason || 'Unavailable in this mode.'}));
        const properties = tool?.parameters?.properties || {};
        const keys = [...new Set([...Object.keys(properties), ...Object.keys(step.params || {})])];
        const required = new Set(tool?.parameters?.required || []);
        const availableOutputs = M.outputsBefore(state.workflow, index);
        const options = node('details', {}, node('summary', {text: 'Use an earlier output'}));
        const chips = node('div', {class: 'binding-options'});
        availableOutputs.forEach(output => chips.append(node('button', {class: 'binding-chip', onmousedown: event => event.preventDefault(), onclick: () => {
            const input = state.focusedInput;
            if (!input || input.tagName === 'SELECT') { notice('Focus a parameter text field, then choose an output.'); return; }
            input.value = '${' + output + '}'; input.dispatchEvent(new Event('change')); input.focus();
        }}, '${' + output + '}'))); options.append(chips, node('p', {class: 'field-description', text: 'Add a path such as .urls[:3]. Output schemas are not always known.'})); body.append(options);
        for (const key of keys) {
            const schema = properties[key] || {}, value = step.params?.[key];
            const expression = typeof value === 'string' && value.includes('${');
            let kind = ['object', 'array'].includes(schema.type) || value && typeof value === 'object' ? 'json' : ['integer', 'number'].includes(schema.type) ? 'number' : schema.type === 'boolean' ? 'boolean' : 'text';
            const box = node('div'); body.append(box);
            field(box, key + (required.has(key) ? ' *' : ''), [...prefix, 'params', key], {kind: expression ? 'text' : kind, value, choices: expression ? null : schema.enum, description: schema.description || '', binding: expression, help: window.WorkflowHelp.parameter(schema)});
            if (schema.enum || ['boolean', 'number', 'json'].includes(kind)) box.append(node('button', {class: 'text-btn', onclick: () => {
                const input = box.querySelector('input,select,textarea'); input.value = '${topic}'; patch([...prefix, 'params', key], '${topic}'); renderInspector();
            }}, 'Use a variable expression'));
        }
        if (!keys.includes('action')) field(body, 'Action', [...prefix, 'action'], {value: step.action});
        check(body, 'Required step', [...prefix, 'required'], step.required !== false);
        field(body, 'Output variable', [...prefix, 'output_var'], {value: step.output_var});
        advanced(body, 'Output extraction and search bindings', [['extract', 'Extract paths (relative to tool data)'], ['search_output_var', 'Normalized search output', 'text'], ['validated_output_var', 'Validated loop output', 'text']], prefix, step);
        advanced(body, 'Conditions and repeat', [['condition', 'Condition'], ['for_each', 'Repeat over expression', 'text'], ['process_all', 'Process all items', 'boolean'], ['required_success_count', 'Required successes', 'number'], ['on_all_fail', 'When all items fail', 'text']], prefix, step);
        advanced(body, 'LLM prompt and validation', [['llm_prompt', 'LLM prompt', 'textarea'], ['llm_output_validation', 'LLM output validation'], ['validation', 'Result validation'], ['llm_variable_max_chars', 'Prompt variable character limit', 'number']], prefix, step);
        preservedFields(body, step, [['llm_hints', 'For a single step, put generation instructions in LLM prompt instead.']]);
        advanced(body, 'Failure handling and variable assignments', [['on_fail', 'On failure', 'text'], ['retry', 'Retry settings'], ['set_variables_on_success', 'Variables on success'], ['set_variables_on_skip', 'Variables on skip']], prefix, step);
        body.append(node('div', {class: 'inspector-actions'}, node('button', {class: 'ghost-btn', disabled: !publishedUnchanged(), onclick: handled(() => prepareRun(index + 1))}, 'Run through this step'),
            node('button', {class: 'danger-btn', onclick: () => { const workflow = M.clone(state.workflow); workflow.steps.splice(index, 1); state.selected = null; commit(workflow, {inspector: true}); }}, 'Remove step')));
    }
    async function loadTools(refresh = false) {
        const mode = $('modeSelect').value;
        const data = refresh ? await api('/api/tools/refresh', 'POST', {mode}) : await api('/api/tools?mode=' + encodeURIComponent(mode));
        state.tools = data.tools || []; renderTools(); renderPalette();
    }
    function insertTool(tool, index) { state.selected = index; commit(M.insertStep(state.workflow, tool, index), {inspector: true}); }
    function renderPalette() {
        const query = $('paletteSearch').value.toLowerCase();
        $('paletteTools').replaceChildren(...state.tools.filter(tool => `${tool.name} ${tool.description}`.toLowerCase().includes(query)).map(tool => {
            const button = node('button', {class: 'palette-tool', title: tool.description || tool.name, onclick: () => {
                if (!state.workflow) { notice('Create or open a workflow first.'); return; }
                insertTool(tool, state.workflow.steps?.length || 0);
            }}, tool.name);
            button.draggable = true;
            button.addEventListener('dragstart', event => { state.dragTool = tool; event.dataTransfer.setData('text/plain', tool.name); event.dataTransfer.effectAllowed = 'copy'; });
            button.addEventListener('dragend', () => { state.dragTool = null; });
            return button;
        }));
    }
    async function openTools(index) { if (!state.workflow) return; state.insertAt = index; $('toolSearch').value = ''; $('toolDialog').showModal(); await loadTools(); }
    function renderTools() {
        const query = $('toolSearch').value.toLowerCase();
        $('toolList').replaceChildren(...state.tools.filter(tool => `${tool.name} ${tool.description}`.toLowerCase().includes(query)).map(tool =>
            node('button', {class: 'tool-option', onclick: () => { state.selected = state.insertAt; commit(M.insertStep(state.workflow, tool, state.insertAt), {inspector: true}); $('toolDialog').close(); }},
                node('strong', {text: tool.name}), node('p', {text: tool.description || ''}), tool.available === false ? node('small', {text: tool.unavailable_reason || tool.reason || 'Unavailable in this mode'}) : null)));
        if (!$('toolList').children.length) $('toolList').append(node('p', {class: 'muted', text: 'No matching tools in the cached catalog.'}));
    }
    function showDiagnostics(data) {
        const box = $('diagnostics'); box.hidden = false; box.replaceChildren(node('h2', {text: 'Validation'}));
        for (const [key, kind] of [['errors', 'error'], ['warnings', 'warning']]) (data[key] || []).forEach(item => box.append(node('div', {class: 'diagnostic ' + kind, text: typeof item === 'string' ? item : `${item.path ? item.path + ': ' : ''}${item.message}`})));
        if (!data.errors?.length && !data.warnings?.length) box.append(node('p', {text: 'Recipe structure is valid. Tool availability is checked again before execution.'}));
        if (data.publication_compatibility) box.append(...publicationNotes(data.publication_compatibility));
    }
    function publicationNotes(compatibility, trustChoice = false) {
        const notes = [];
        for (const report of compatibility.modes || []) {
            const approvals = report.approval_steps || [], unknown = report.unknown_steps || [];
            if (!approvals.length && !unknown.length && !(report.unavailable_steps || []).length) continue;
            const warning = node('div', {class: 'publication-warning'}, node('h3', {text: `${report.mode === 'local' ? 'Local' : 'Cloud'} execution`}));
            if (approvals.length) warning.append(node('p', {text: 'Without recipe trust, commands, API calls, and schedules will refuse this recipe before any steps run. These steps require approval, including optional or conditional steps:'}),
                node('ul', {}, approvals.map(step => node('li', {text: `Position ${step.index + 1} · step ${step.step} · ${step.tool}${step.optional ? ' · optional' : ''}${step.conditional ? ' · conditional' : ''}`}))));
            if (unknown.length) warning.append(node('p', {text: 'Permission metadata is unavailable or cached for these tools. Unattended eligibility cannot be verified until execution:'}),
                node('ul', {}, unknown.map(step => node('li', {text: `Position ${step.index + 1} · ${step.tool}`}))));
            if (report.unavailable_steps?.length) warning.append(node('p', {text: 'Currently unavailable tools:'}), node('ul', {}, report.unavailable_steps.map(step => node('li', {text: `${step.tool}: ${step.reason || 'Unavailable in this mode'}`}))));
            notes.push(warning);
        }
        if (trustChoice && compatibility.trustable_tools?.length) {
            const input = node('input', {id: 'trustUnattended', type: 'checkbox'});
            notes.push(node('label', {class: 'checkbox-field'}, input, node('span', {text: 'Trust this recipe for unattended runs'})),
                node('p', {class: 'muted', text: `Authorizes ${compatibility.trustable_tools.join(', ')} without per-call prompts for this exact published revision, including future query and model-generated arguments. This also applies to builder runs. Global tool blocks still apply. Editing and publishing again requires a new choice.`}));
        }
        return notes;
    }
    function applyJSON() {
        try {
            const workflow = JSON.parse($('recipeJSON').value);
            if (!workflow || typeof workflow !== 'object' || Array.isArray(workflow) || !Array.isArray(workflow.steps)) throw new Error('A recipe must be an object with a steps array.');
            state.rawDirty = false; $('jsonError').textContent = ''; commit(workflow, {inspector: true}); return true;
        } catch (error) { $('jsonError').textContent = error.message; throw error; }
    }
    async function validate() {
        if (!state.workflow) return;
        if (state.rawDirty) applyJSON();
        const data = await api('/api/validate', 'POST', {workflow: state.workflow, source_id: state.source?.source_id}); showDiagnostics(data); return data;
    }
    function review(title, content, confirmText = 'Confirm') {
        $('reviewTitle').textContent = title; $('reviewBody').replaceChildren(...content); $('reviewConfirm').textContent = confirmText;
        $('reviewConfirm').hidden = false; $('reviewCancel').hidden = false; $('reviewDialog').showModal();
        return new Promise(resolve => {
            const close = () => { $('reviewConfirm').removeEventListener('click', accept); $('reviewDialog').removeEventListener('close', cancel); resolve(false); };
            const accept = () => { $('reviewConfirm').removeEventListener('click', accept); $('reviewDialog').removeEventListener('close', cancel); $('reviewDialog').close(); resolve(true); };
            const cancel = () => close();
            $('reviewConfirm').addEventListener('click', accept); $('reviewDialog').addEventListener('close', cancel, {once: true});
        });
    }
    async function publish() {
        if (!state.workflow) return;
        if (state.rawDirty) applyJSON();
        if (!state.draft && !state.dirty && state.source?.tier === 'shared') {
            commit({...state.workflow, allow_workflow_tool: false});
        }
        await flushSave();
        if (!state.draft) { state.dirty = true; await flushSave(); }
        const draftId = state.draft.id;
        const preview = await api('/api/drafts/' + encodeURIComponent(draftId) + '/publish-preview', 'POST', {revision: state.draft.revision});
        showDiagnostics(preview); if (preview.errors?.length) return;
        const changes = M.publicationChanges(state.baseline, state.workflow);
        const content = [node('p', {text: 'This publishes the personal recipe. Review its command changes and execution permissions below.'}),
            node('pre', {text: `Commands: ${changes.commandsBefore.join(', ') || '(new)'} → ${changes.commandsAfter.join(', ') || '(none)'}\nAutonomous routing: ${changes.autonomous ? 'enabled' : 'disabled'}\nRemoved variables: ${changes.removedVariables.join(', ') || '(none)'}`}),
            node('p', {class: 'muted', text: 'Command and variable changes can affect existing scheduled tasks. Bundled files are preserved.'}),
            ...publicationNotes(preview.publication_compatibility || {}, true)];
        if (!await review('Publish personal recipe', content, 'Publish')) return;
        const data = await api('/api/drafts/' + encodeURIComponent(draftId) + '/publish', 'POST', {revision: preview.revision,
            preview_hash: preview.recipe_hash, trust_unattended: $('trustUnattended')?.checked === true,
            trust_tools: preview.publication_compatibility?.trustable_tools || []});
        loadDocument(definitionOf(data.draft), data.draft, data.source, definitionOf(data.draft));
        setStatus('Published'); await refreshLibrary(); notice('Personal recipe published.');
    }
    function exportRecipe() {
        if (!state.workflow) return;
        const workflow = {...state.workflow, builder_policy_version: 1};
        const url = URL.createObjectURL(new Blob([JSON.stringify(workflow, null, 2) + '\n'], {type: 'application/json'}));
        const anchor = node('a', {href: url, download: `${workflow.id || 'workflow'}.json`}); anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    async function removePersonal() {
        if (!await review('Remove personal recipe', [node('p', {text: 'This removes the personal runtime definition. If a bundled recipe has the same ID, it becomes active again. Saved drafts and run history are retained.'})], 'Remove personal recipe')) return;
        await api('/api/workflows/' + encodeURIComponent(state.source.source_id) + '/personal', 'DELETE', {hash: state.source.hash});
        state.source = null; state.baseline = null; updateHeading(); await refreshLibrary(); notice('Personal recipe removed; any bundled definition is restored.');
    }
    function terminal(status) { return ['succeeded', 'failed', 'cancelled', 'timed_out', 'interrupted', 'partial', 'completed', 'rejected'].includes(status); }
    async function prepareRun(stopAfter = null) {
        if (!publishedUnchanged()) throw new Error('Publish your current changes before a live run.');
        const data = await api('/api/runs/prepare', 'POST', {source_id: state.source.source_id, hash: state.source.hash,
            query: $('runQuery').value, mode: $('modeSelect').value, stop_after: stopAfter, timeout_seconds: Number($('runDeadline').value)});
        const partial = data.partial ?? (stopAfter !== null && stopAfter < state.workflow.steps.length);
        const content = [node('p', {text: partial ? `Live execution stops after position ${stopAfter}. Earlier steps still change real state.` : 'This is a live run using real tools. It may update pages, files, ledgers, alerts, and external services.'})];
        if (data.model_use) content.push(node('p', {class: 'muted', text: 'Query extraction or completion speech may also call the configured model.'}));
        (data.effects || []).forEach(effect => content.push(node('div', {class: 'effect-row'}, node('strong', {text: `${Number.isInteger(effect.index) ? effect.index + 1 : effect.step}: ${effect.tool}${effect.action ? ' · ' + effect.action : ''}`}),
            node('small', {text: [effect.description, ...(effect.state_effects || []), effect.model_use ? 'May use model' : '', ...Object.entries(effect.permissions || {}).filter(([key, enabled]) => enabled && key !== 'auto_approve').map(([key]) => key), effect.requires_approval ? 'Exact-call approval required' : effect.unattended_authorized ? 'Authorized by this recipe’s published trust choice' : ''].filter(Boolean).join(' · ')}))));
        content.push(node('p', {class: 'muted', text: `Mode: ${$('modeSelect').value} · deadline: ${$('runDeadline').value} seconds. Cancellation cannot undo completed actions.`}));
        if (!await review(partial ? 'Review partial live run' : 'Review live run', content, 'Confirm and run')) return;
        // The server's unique preparation token also makes repeated submissions idempotent on plain HTTP.
        const result = await api('/api/runs', 'POST', {confirmation_token: data.confirmation_token, confirmed: true, idempotency_key: 'builder-' + data.confirmation_token});
        await watchRun(result.run);
    }
    async function watchRun(run) {
        clearTimeout(state.pollTimer); state.run = run; state.cursor = 0; state.approvals.clear(); state.statuses.clear();
        $('runEvents').replaceChildren(); $('approvalList').replaceChildren(); $('activeRun').hidden = false;
        sessionStorage.setItem('jarvis_workflow_run', run.id); await pollRun();
    }
    async function pollRun() {
        if (!state.run) return;
        clearTimeout(state.pollTimer);
        const runId = state.run.id;
        try {
            const data = await api('/api/runs/' + encodeURIComponent(runId) + '?after=' + state.cursor);
            if (state.run?.id !== runId) return;
            state.run = data.run; $('runStatus').textContent = `${data.run.name || data.run.workflow_id || 'Run'} · ${data.run.id.slice(0, 8)} · ${M.runStatusLabel(data.run)}`;
            $('cancelRun').hidden = terminal(data.run.status);
            for (const event of data.events || []) {
                if (event.sequence <= state.cursor) continue; state.cursor = Math.max(state.cursor, event.sequence);
                const payload = event.payload || event;
                const type = event.type || payload.type || 'progress';
                const item = node('li', {}, node('span', {text: `${type.replaceAll('_', ' ')}${payload.tool ? ' · ' + payload.tool : ''}${payload.step !== undefined ? ' · step ' + payload.step : ''}${payload.message ? ': ' + payload.message : ''}`}));
                if (payload.preview || payload.result || payload.recovery || payload.data) item.append(node('details', {}, node('summary', {text: 'Details'}), node('pre', {text: JSON.stringify(payload.preview || payload.result || payload.recovery || payload.data, null, 2)})));
                $('runEvents').append(item);
                while ($('runEvents').children.length > 200) $('runEvents').firstChild.remove();
                if (Number.isInteger(payload.index)) state.statuses.set(payload.index, M.stepEventStatus(type, payload.result));
            }
            renderApprovals(data.approvals || []); render();
            // A finished run can still have more persisted event pages to recover.
            if ((data.events || []).length >= 300) state.pollTimer = setTimeout(pollRun, 0);
            else if (terminal(data.run.status)) sessionStorage.removeItem('jarvis_workflow_run');
            else state.pollTimer = setTimeout(pollRun, 1000);
        } catch (error) { notice(error.message, true); state.pollTimer = setTimeout(pollRun, 4000); }
    }
    function renderApprovals(approvals) {
        $('approvalList').replaceChildren(...approvals.filter(approval => approval.status === 'pending').map(approval => {
            const payload = approval.payload || approval;
            const act = async approved => {
                await api('/api/approvals/' + encodeURIComponent(approval.id), 'POST', {approved, call_hash: payload.call_hash}); await pollRun();
            };
            return node('div', {class: 'approval-card'}, node('h3', {text: 'Approval required · ' + payload.tool}),
                node('p', {text: 'Review this prepared call. Approval applies once to the complete invocation identified by its call hash.'}),
                node('p', {class: 'muted', text: payload.arguments_preview?.truncated ? 'Argument preview is shortened and redacted. Approval includes content omitted from this preview.' : 'Argument preview is redacted; credentials and private runtime data are hidden.'}),
                node('pre', {text: JSON.stringify(payload.arguments || {}, null, 2)}),
                node('div', {class: 'dialog-actions'}, node('button', {class: 'danger-btn', onclick: handled(() => act(false))}, 'Decline and stop'), node('button', {class: 'primary-btn', onclick: handled(() => act(true))}, 'Approve call')));
        }));
    }
    async function showHistory() {
        const data = await api('/api/runs');
        $('reviewTitle').textContent = 'Builder run history'; $('reviewBody').replaceChildren(...(data.runs || []).map(run =>
            node('button', {class: 'recipe-item', onclick: handled(async () => { $('reviewDialog').close(); await watchRun(run); })},
                node('strong', {text: `${run.workflow_id || run.id.slice(0, 8)} · ${M.runStatusLabel(run)}`}), node('small', {text: `${run.mode || ''} · ${run.created_at || ''}`}))));
        if (!$('reviewBody').children.length) $('reviewBody').append(node('p', {class: 'muted', text: 'No builder runs yet.'}));
        $('reviewConfirm').hidden = true; $('reviewCancel').hidden = true; $('reviewDialog').showModal();
    }
    function setTab(tab) {
        state.tab = tab; $('laneTab').classList.toggle('active', tab === 'lane'); $('jsonTab').classList.toggle('active', tab === 'json');
        $('laneTab').setAttribute('aria-pressed', tab === 'lane'); $('jsonTab').setAttribute('aria-pressed', tab === 'json'); render();
    }
    function travel(backward) {
        if (!state.history) return;
        state.workflow = backward ? state.history.undo() : state.history.redo();
        state.dirty = true; state.generation++; state.selected = null; setStatus('Saving draft…'); render(); renderInspector(); scheduleSave();
    }
    async function init() {
        $('webLink').href = window.JarvisUINavigation?.url('web', `http://${location.hostname}:5001`) || `http://${location.hostname}:5001`;
        const bootstrap = await api('/api/bootstrap');
        (bootstrap.modes || []).forEach(mode => $('modeSelect').append(node('option', {value: mode, text: mode === 'local' ? 'Local' : 'Cloud'})));
        $('modeSelect').value = bootstrap.startup_mode || bootstrap.modes?.[0] || 'cloud';
        await refreshLibrary(); await loadTools(); render();
        const draftId = sessionStorage.getItem('jarvis_workflow_draft');
        if (draftId) { try { await openDraft(draftId); } catch (error) { notice(error.message, true); } }
        const runId = bootstrap.active_run?.id || sessionStorage.getItem('jarvis_workflow_run');
        if (runId) { try { const data = await api('/api/runs/' + encodeURIComponent(runId)); await watchRun(data.run); } catch (_) { sessionStorage.removeItem('jarvis_workflow_run'); } }
    }
    for (const id of ['newRecipe', 'emptyNewRecipe']) $(id).addEventListener('click', handled(() => createDraft()));
    $('refreshLibrary').addEventListener('click', handled(refreshLibrary)); $('librarySearch').addEventListener('input', renderLibrary);
    $('settingsButton').addEventListener('click', () => select(null)); $('validateButton').addEventListener('click', handled(validate));
    $('publishButton').addEventListener('click', handled(publish)); $('laneTab').addEventListener('click', () => setTab('lane')); $('jsonTab').addEventListener('click', () => setTab('json'));
    $('recipeJSON').addEventListener('input', () => { state.rawDirty = true; updateHeading(); }); $('applyJSON').addEventListener('click', handled(applyJSON));
    $('undoButton').addEventListener('click', () => travel(true)); $('redoButton').addEventListener('click', () => travel(false));
    $('toolSearch').addEventListener('input', renderTools); $('refreshTools').addEventListener('click', handled(async () => { $('refreshTools').disabled = true; try { await loadTools(true); notice('Tool catalog refreshed.'); } finally { $('refreshTools').disabled = false; } }));
    $('paletteSearch').addEventListener('input', renderPalette);
    $('modeSelect').addEventListener('change', handled(async () => { await loadTools(); renderInspector(); }));
    $('runButton').addEventListener('click', handled(() => prepareRun())); $('historyButton').addEventListener('click', handled(showHistory));
    $('cancelRun').addEventListener('click', handled(async () => { await api('/api/runs/' + encodeURIComponent(state.run.id) + '/cancel', 'POST', {}); await pollRun(); }));
    $('queryPreviewButton').addEventListener('click', () => { if (!state.workflow) return; $('reviewTitle').textContent = 'Query extraction preview'; $('reviewBody').replaceChildren(node('pre', {text: JSON.stringify(M.queryPreview(state.workflow, $('runQuery').value), null, 2)}), node('p', {class: 'muted', text: 'No tools or models were called. Dynamic extraction and decisions resolve during a live run.'})); $('reviewConfirm').hidden = true; $('reviewCancel').hidden = true; $('reviewDialog').showModal(); });
    $('reviewCancel').addEventListener('click', () => $('reviewDialog').close());
    document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
    $('importRecipe').addEventListener('click', () => $('importFile').click());
    $('importFile').addEventListener('change', handled(async event => {
        const file = event.target.files[0]; if (!file) return;
        if (file.size > 2 * 1024 * 1024) throw new Error('Recipe imports must be smaller than 2 MB.');
        const definition = JSON.parse(await file.text()); definition.allow_workflow_tool = false; await createDraft(definition); event.target.value = '';
    }));
    window.addEventListener('beforeunload', event => { if (state.dirty || state.rawDirty || state.saving) { event.preventDefault(); event.returnValue = ''; } });
    document.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !event.target.closest('input,textarea,select,[contenteditable]')) { event.preventDefault(); travel(!event.shiftKey); }
    });
    handled(init)();
})();
