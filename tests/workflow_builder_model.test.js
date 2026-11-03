'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../jarvis-workflows/client/js/model.js');
const root = path.resolve(__dirname, '..');

test('every bundled recipe survives edit history without losing fields', () => {
    for (const file of fs.readdirSync(path.join(root, 'data/workflows')).filter(file => file.endsWith('.json'))) {
        const original = JSON.parse(fs.readFileSync(path.join(root, 'data/workflows', file), 'utf8'));
        const history = new M.History(original);
        history.commit({...original, name: 'A local edit'});
        assert.deepEqual(history.undo(), original, file);
        assert.deepEqual(history.redo(), {...original, name: 'A local edit'}, file);
        assert.deepEqual(original, JSON.parse(fs.readFileSync(path.join(root, 'data/workflows', file), 'utf8')), file);
    }
});
test('reordering preserves step labels, implicit variables, and comments', () => {
    const source = {id: 'test', _comment: 'keep', steps: [
        {step: 12, tool: 'crawl_url', for_each: '${urls}', _comment: 'producer'},
        {step: 39, tool: 'stash', params: {text: '${step12_results}'}}
    ]};
    const result = M.moveStep(source, 0, 1);
    assert.deepEqual(result.steps.map(step => step.step), [39, 12]);
    assert.equal(result.steps[0].params.text, '${step12_results}');
    assert.equal(result.steps[1]._comment, 'producer');
    assert.deepEqual(source.steps.map(step => step.step), [12, 39]);
});
test('card drops insert before the target in both directions while arrows retain swap semantics', () => {
    const source = {steps: ['A', 'B', 'C', 'D'].map((tool, index) => ({tool, step: (index + 1) * 10}))};
    assert.deepEqual(M.dropStepBefore(source, 0, 2).steps.map(step => step.tool), ['B', 'A', 'C', 'D']);
    assert.deepEqual(M.dropStepBefore(source, 3, 1).steps.map(step => step.tool), ['A', 'D', 'B', 'C']);
    assert.deepEqual(M.dropStepBefore(source, 0, 4).steps.map(step => step.tool), ['B', 'C', 'D', 'A']);
    assert.deepEqual(M.dropStepBefore(source, 2, 2), source);
    assert.deepEqual(M.moveStep(source, 0, 1).steps.map(step => step.tool), ['B', 'A', 'C', 'D']);
    assert.deepEqual(M.dropStepBefore(source, 0, 2).steps.map(step => step.step), [20, 10, 30, 40]);
});
test('insertion chooses an unused label and retains native parameter defaults', () => {
    const source = {steps: [{step: 8, tool: 'existing', unknown: true}]};
    const result = M.insertStep(source, {name: 'new', parameters: {properties: {count: {default: 3}, choices: {default: ['a']}, enabled: {default: false}}}}, 0);
    assert.equal(result.steps[0].step, 9);
    assert.deepEqual(result.steps[0].params, {count: 3, choices: ['a'], enabled: false});
    assert.equal(result.steps[1].unknown, true);
});
test('bindings distinguish producer outputs and never resolve environment values', () => {
    const recipe = {variables: {location: {from: 'env', key: 'JARVIS_DEFAULT_LOCATION'}, title: {from: 'query', extract: 'short_title'}}, steps: [
        {step: 7, tool: 'search', search_output_var: 'web_sources', output_var: 'raw'},
        {step: 15, tool: 'crawl_url', for_each: '${web_sources.urls[:3]}', validated_output_var: 'articles'},
    ]};
    assert.deepEqual(M.bindings(recipe.steps[1]), ['web_sources.urls[:3]']);
    assert.ok(M.outputsBefore(recipe, 2).includes('articles'));
    assert.ok(M.outputsBefore(recipe, 2).includes('step15_results'));
    const preview = M.queryPreview(recipe, 'my topic');
    assert.equal(preview.location, '[environment reference; value hidden]');
    assert.equal(preview.title, '[resolved at run time]');
    assert.equal(preview.topic, 'my topic');
});
test('publication summary identifies command and variable changes', () => {
    const changes = M.publicationChanges({triggers: {explicit: ['/old']}, variables: {old_name: {}}},
        {triggers: {explicit: ['*']}, variables: {new_name: {}}, allow_workflow_tool: false});
    assert.deepEqual(changes.removedVariables, ['old_name']);
    assert.deepEqual(changes.commandsAfter, ['*']);
    assert.equal(changes.autonomous, false);
    assert.equal(M.createRecipe().allow_workflow_tool, false);
    assert.deepEqual(M.publicationChanges({triggers: {explicit: 123}}, {triggers: {explicit: ['/repaired']}}).commandsBefore, []);
});
test('step progress reflects failed and rejected results without completing a loop on an item', () => {
    assert.equal(M.stepEventStatus('step_finished', {ok: false, error: 'Tool failed'}), 'failed');
    assert.equal(M.stepEventStatus('step_finished', {ok: false, cancelled: true}), 'cancelled');
    assert.equal(M.stepEventStatus('step_rejected'), 'rejected');
    assert.equal(M.stepEventStatus('item_finished', {ok: true}), 'running');
    assert.equal(M.stepEventStatus('item_finished', {ok: false}), 'running');
    assert.equal(M.stepEventStatus('step_finished', {ok: true}), 'completed');
});
test('partial completion stays distinct in new runs and older saved run records', () => {
    assert.equal(M.runStatusLabel({status: 'partial', partial: true}), 'partial completion');
    assert.equal(M.runStatusLabel({status: 'completed', partial: true}), 'partial completion');
    assert.equal(M.runStatusLabel({status: 'running', partial: true}), 'running');
    assert.equal(M.runStatusLabel({status: 'completed', partial: false}), 'completed');
});
