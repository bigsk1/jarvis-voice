/* Recipe editing operations shared by the classic-script UI and Node tests. */
(function (root) {
    'use strict';
    const clone = value => JSON.parse(JSON.stringify(value));
    function createRecipe() {
        return {id: '', name: 'Untitled workflow', description: '', enabled: true,
            allow_workflow_tool: false, triggers: {explicit: []}, variables: {}, steps: []};
    }
    function moveStep(definition, from, to) {
        const result = clone(definition);
        if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to < 0 ||
            from >= result.steps.length || to >= result.steps.length) return result;
        const [step] = result.steps.splice(from, 1);
        result.steps.splice(to, 0, step);
        return result;
    }
    function dropStepBefore(definition, from, before) {
        if (!Number.isInteger(before) || before < 0 || before > definition.steps.length) return clone(definition);
        return moveStep(definition, from, Math.min(before > from ? before - 1 : before, definition.steps.length - 1));
    }
    function insertStep(definition, tool, index) {
        const result = clone(definition);
        if (!Array.isArray(result.steps)) result.steps = [];
        const label = Math.max(0, ...result.steps.map(step => Number.isInteger(step?.step) ? step.step : 0)) + 1;
        const params = {};
        for (const [key, schema] of Object.entries(tool.parameters?.properties || {})) {
            if (Object.hasOwn(schema, 'default')) params[key] = clone(schema.default);
        }
        result.steps.splice(Math.max(0, Math.min(index, result.steps.length)), 0,
            {step: label, tool: tool.name, params, required: true});
        return result;
    }
    function bindings(value) {
        const matches = new Set();
        function visit(item) {
            if (typeof item === 'string') {
                for (const match of item.matchAll(/\$\{([^}]+)\}/g)) matches.add(match[1]);
            } else if (Array.isArray(item)) item.forEach(visit);
            else if (item && typeof item === 'object') Object.values(item).forEach(visit);
        }
        visit(value);
        return [...matches];
    }
    function outputsBefore(definition, index) {
        const outputs = new Set(['query', 'topic', 'content', 'workflow_id', 'timestamp', 'filename_timestamp']);
        Object.keys(definition.variables || {}).forEach(name => outputs.add(name));
        (Array.isArray(definition.steps) ? definition.steps : []).slice(0, index).forEach(step => {
            if (!step || typeof step !== 'object') return;
            ['output_var', 'search_output_var', 'validated_output_var'].forEach(key => {
                if (step[key]) outputs.add(step[key]);
            });
            if (step.for_each && !step.output_var) outputs.add(`step${step.step}_results`);
            Object.keys(step.extract || {}).forEach(name => outputs.add(name));
            Object.keys(step.set_variables_on_success || {}).forEach(name => outputs.add(name));
            Object.keys(step.set_variables_on_skip || {}).forEach(name => outputs.add(name));
        });
        return [...outputs];
    }
    function queryPreview(definition, query) {
        const preview = {query, topic: query, content: query};
        for (const [name, rule] of Object.entries(definition.variables || {})) {
            if (!rule || typeof rule !== 'object' || Array.isArray(rule)) {
                preview[name] = rule;
                continue;
            }
            if (rule.from === 'env') { preview[name] = '[environment reference; value hidden]'; continue; }
            if (rule.from === 'static') { preview[name] = rule.value; continue; }
            if (rule.transform || rule.from && rule.from !== 'query') {
                preview[name] = '[resolved at run time]'; continue;
            }
            switch (rule.extract || 'main_subject') {
                case 'main_subject': preview[name] = query || rule.default || ''; break;
                case 'first_words': preview[name] = query.trim().split(/\s+/).slice(0, rule.max_words || 4).join('_'); break;
                case 'url': preview[name] = query.match(/https?:\/\/[^\s]+/)?.[0] || '[resolved at run time]'; break;
                default: preview[name] = '[resolved at run time]';
            }
        }
        return preview;
    }
    function publicationChanges(before, after) {
        const original = before || {};
        const oldVariables = Object.keys(original.variables || {});
        const commands = value => Array.isArray(value) ? value.filter(command => typeof command === 'string') : [];
        return {
            commandsBefore: commands(original.triggers?.explicit), commandsAfter: commands(after.triggers?.explicit),
            removedVariables: oldVariables.filter(key => !Object.hasOwn(after.variables || {}, key)),
            autonomous: after.allow_workflow_tool !== false,
        };
    }
    function stepEventStatus(type, result = {}) {
        result = result && typeof result === 'object' ? result : {};
        if (type.startsWith('item_')) return 'running';
        if (type === 'step_rejected') return 'rejected';
        if (result.cancelled || type.includes('cancel')) return 'cancelled';
        if (type.includes('fail') || result.ok === false || result.error) return 'failed';
        if (type.includes('skip')) return 'skipped';
        if (type === 'step_finished' || type === 'step_completed') return 'completed';
        return 'running';
    }
    function runStatusLabel(run) {
        if (run.status === 'partial' || run.status === 'completed' && run.partial) return 'partial completion';
        return String(run.status || 'unknown').replaceAll('_', ' ');
    }
    class History {
        constructor(definition) { this.reset(definition); }
        reset(definition) { this.current = clone(definition); this.undoStack = []; this.redoStack = []; }
        commit(definition) {
            if (JSON.stringify(this.current) === JSON.stringify(definition)) return false;
            this.undoStack.push(this.current);
            if (this.undoStack.length > 60) this.undoStack.shift();
            this.current = clone(definition); this.redoStack = []; return true;
        }
        undo() {
            if (!this.undoStack.length) return this.current;
            this.redoStack.push(this.current); this.current = this.undoStack.pop(); return clone(this.current);
        }
        redo() {
            if (!this.redoStack.length) return this.current;
            this.undoStack.push(this.current); this.current = this.redoStack.pop(); return clone(this.current);
        }
    }
    const api = {clone, createRecipe, moveStep, dropStepBefore, insertStep, bindings, outputsBefore, queryPreview, publicationChanges, stepEventStatus, runStatusLabel, History};
    root.WorkflowModel = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
