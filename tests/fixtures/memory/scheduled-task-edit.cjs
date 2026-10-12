const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [sourcePath, scenario] = process.argv.slice(2);
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) {
    const classes = new Set();
    nodes.set(id, {
      value: '', textContent: '', innerHTML: '', checked: false, disabled: false, hidden: true, style: {},
      classList: {
        add: name => classes.add(name), remove: name => classes.delete(name),
        contains: name => classes.has(name), toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
      },
    });
  }
  return nodes.get(id);
}
const modal = element('scheduledTaskModal');
const view = element('viewModal');
const toast = [];
let submitted;
const workflow = {id: 'inbox', name: 'Inbox', input_fields: [], tools_used: ['email_inbox']};
const task = {
  id: 24, name: 'Inbox', task_type: 'workflow', task_target: 'inbox',
  task_payload: JSON.stringify({when_original: 'every 30 minutes'}),
  metadata: JSON.stringify({other_setting: {keep: true}}),
  max_retries: 0, timeout_seconds: 600, enabled: true, mode: 'cloud',
};
const api = {
  mode: 'cloud', listScheduledTaskWorkflows: async () => ({workflows: [workflow]}),
  getScheduledTask: async () => ({task}),
  updateScheduledTask: async (id, data) => {submitted = {id, data};},
  createScheduledTask: async data => {submitted = {data};},
};
const sandbox = {
  api, console, Intl, URLSearchParams,
  document: {
    addEventListener() {}, getElementById: element,
    querySelectorAll: selector => selector === '.modal-overlay' ? [modal, view] : [],
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(sourcePath, 'utf8'), sandbox);
vm.runInContext(`
  closeSidebar = () => {};
  showToast = (message, type) => recordToast(message, type);
  escapeHtml = text => String(text);
  loadScheduledTasks = async () => {};
`, Object.assign(sandbox, {recordToast: (...args) => toast.push(args)}));
const defer = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {resolve = a; reject = b;});
  return {promise, resolve, reject};
};
const active = node => node.classList.contains('active');
const save = () => sandbox.handleScheduledTaskSubmit({preventDefault() {}});
const status = element('scheduledTaskWorkflowLoadStatus');
const button = element('scheduledTaskSave');

(async () => {
  if (['missing', 'false', 'true', 'zero'].includes(scenario)) {
    if (scenario !== 'missing') {
      task.metadata = JSON.stringify({other_setting: {keep: true}, notifications: {
        alert_on_failure: {false: false, true: true, zero: 0}[scenario],
      }});
    }
    await sandbox.openScheduledTaskModal(task);
    assert.equal(element('scheduledTaskAlertOnFailure').checked, scenario === 'true');
    await save();
    assert.equal(submitted.id, 24);
    assert.equal(submitted.data.metadata.notifications.alert_on_failure, scenario === 'true');
    assert.equal(submitted.data.max_retries, 0);
    assert.equal(submitted.data.timeout_seconds, 600);
    assert.equal(submitted.data.metadata.other_setting.keep, true);
  } else if (scenario === 'new') {
    await sandbox.openScheduledTaskModal();
    assert.equal(element('scheduledTaskAlertOnFailure').checked, true);
    assert.equal(element('scheduledTaskMaxRetries').value, 1);
  } else if (scenario === 'slow-workflows') {
    const pending = defer();
    api.listScheduledTaskWorkflows = () => pending.promise;
    const opening = sandbox.openScheduledTaskModal(task);
    assert.equal(active(modal), true, 'Form must open before workflow discovery finishes');
    assert.equal(status.hidden, false);
    assert.equal(button.disabled, false);
    await save();
    assert.equal(submitted.data.workflow_id, 'inbox');
    assert.equal(submitted.data.max_retries, 0);
    assert.equal(submitted.data.metadata.other_setting.keep, true);
    pending.resolve({workflows: [workflow]});
    await opening;
    assert.equal(active(modal), false, 'Late discovery must not reopen a saved form');
  } else if (scenario === 'new-slow-workflows') {
    const pending = defer();
    api.listScheduledTaskWorkflows = () => pending.promise;
    const opening = sandbox.openScheduledTaskModal();
    element('scheduledTaskType').value = 'workflow';
    element('scheduledTaskName').value = 'New task';
    element('scheduledTaskWhen').value = 'every 30 minutes';
    element('scheduledTaskWorkflowId').value = 'inbox';
    sandbox.handleScheduledTaskTypeChange();
    assert.equal(button.disabled, true);
    await save();
    assert.equal(submitted, undefined, 'A new workflow must wait for discovery');
    pending.resolve({workflows: [workflow]});
    await opening;
    assert.equal(status.hidden, true);
    assert.equal(button.disabled, false);
  } else if (scenario === 'empty-workflows') {
    api.listScheduledTaskWorkflows = async () => ({workflows: []});
    await sandbox.openScheduledTaskModal(task);
    assert.match(element('scheduledTaskWorkflowId').innerHTML, /not currently loaded/);
    assert(!element('scheduledTaskWorkflowId').innerHTML.includes('loading…'));
    assert.equal(status.hidden, true);
  } else if (['workflow-error', 'legacy-workflow-error', 'changed-workflow-error'].includes(scenario)) {
    if (scenario === 'legacy-workflow-error') {
      task.task_target = null;
      task.task_payload = JSON.stringify({workflow_id: 'inbox', when_original: 'every 30 minutes'});
    }
    api.listScheduledTaskWorkflows = async () => {throw Error('Unavailable');};
    await sandbox.openScheduledTaskModal(task);
    assert.equal(active(modal), true);
    assert.equal(status.hidden, false);
    assert.match(status.textContent, /Could not load workflows/);
    assert.equal(button.disabled, false);
    assert.match(status.textContent, /keep this task’s saved workflow/);
    if (scenario === 'changed-workflow-error') {
      element('scheduledTaskWorkflowId').value = 'different';
      sandbox.handleScheduledTaskTypeChange();
      assert.equal(button.disabled, true);
      await save();
      assert.equal(submitted, undefined, 'A changed workflow must require discovery');
    } else {
      await save();
      assert.equal(submitted.data.workflow_id, 'inbox');
      assert.equal(submitted.data.max_retries, 0);
      assert.equal(submitted.data.metadata.notifications.alert_on_failure, false);
      assert.equal(submitted.data.metadata.other_setting.keep, true);
    }
  } else if (scenario === 'new-workflow-error') {
    api.listScheduledTaskWorkflows = async () => {throw Error('Unavailable');};
    await sandbox.openScheduledTaskModal();
    element('scheduledTaskType').value = 'workflow';
    element('scheduledTaskName').value = 'New task';
    element('scheduledTaskWhen').value = 'every 30 minutes';
    element('scheduledTaskWorkflowId').value = 'inbox';
    sandbox.handleScheduledTaskTypeChange();
    assert.equal(button.disabled, true);
    await save();
    assert.equal(submitted, undefined);
    element('scheduledTaskType').value = 'query';
    sandbox.handleScheduledTaskTypeChange();
    assert.equal(button.disabled, false, 'Query editing must remain usable');
  } else if (scenario === 'cancel-workflows' || scenario === 'stale-workflows') {
    const pending = defer();
    api.listScheduledTaskWorkflows = () => pending.promise;
    const opening = sandbox.openScheduledTaskModal(task);
    sandbox.closeAllModals();
    if (scenario === 'stale-workflows') {
      api.listScheduledTaskWorkflows = async () => ({workflows: [workflow]});
      await sandbox.openScheduledTaskModal({...task, name: 'Newer form'});
    }
    pending.resolve({workflows: [{id: 'stale'}]});
    await opening;
    assert.equal(active(modal), scenario === 'stale-workflows');
    if (scenario === 'stale-workflows') {
      assert.equal(element('scheduledTaskName').value, 'Newer form');
      assert.equal(vm.runInContext('scheduledTaskWorkflows[0].id', sandbox), 'inbox');
      assert.equal(button.disabled, false);
    }
  } else if (scenario === 'slow-edit-catalog') {
    const taskFetch = defer();
    const catalog = defer();
    api.getScheduledTask = () => taskFetch.promise;
    api.listScheduledTaskWorkflows = () => catalog.promise;
    const trigger = element('editButton'); trigger.textContent = '✏️';
    const editing = sandbox.editScheduledTask(24, trigger);
    assert.equal(trigger.disabled, true);
    taskFetch.resolve({task});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(active(modal), true);
    assert.equal(status.hidden, false);
    assert.equal(trigger.disabled, false, 'Edit must recover before catalog finishes');
    assert.equal(trigger.textContent, '✏️');
    sandbox.closeAllModals();
    assert.equal(trigger.disabled, false, 'Closing a form must leave Edit available');
    const newerFetch = defer();
    api.getScheduledTask = () => newerFetch.promise;
    const newerEdit = sandbox.editScheduledTask(24, trigger);
    assert.equal(trigger.disabled, true);
    catalog.resolve({workflows: [{id: 'stale'}]});
    await editing;
    assert.equal(active(modal), false);
    assert.equal(trigger.disabled, true, 'Old discovery must not reset a newer task fetch');
    assert.equal(trigger.textContent, 'Loading…');
    api.listScheduledTaskWorkflows = async () => ({workflows: [workflow]});
    newerFetch.resolve({task: {...task, name: 'Newer form'}});
    await newerEdit;
    assert.equal(element('scheduledTaskName').value, 'Newer form');
    assert.equal(trigger.disabled, false);
    assert.equal(trigger.textContent, '✏️');
  } else if (['slow-task', 'task-error', 'cancel-task'].includes(scenario)) {
    const pending = defer();
    api.getScheduledTask = () => pending.promise;
    const trigger = element('editButton'); trigger.textContent = 'Edit';
    sandbox.showModal(view);
    const editing = sandbox.editScheduledTask(24, trigger);
    assert.equal(active(view), true, 'Details must stay visible while fetching task');
    assert.equal(trigger.disabled, true);
    assert.match(trigger.textContent, /Loading/);
    if (scenario === 'cancel-task') sandbox.closeAllModals();
    if (scenario === 'task-error') pending.reject(Error('Not found'));
    else pending.resolve({task});
    await editing;
    assert.equal(active(modal), scenario === 'slow-task');
    assert.equal(active(view), scenario === 'task-error');
    assert.equal(trigger.disabled, false);
    assert.equal(trigger.textContent, 'Edit');
    if (scenario === 'task-error') assert.equal(toast.length, 1);
  } else throw Error('Unknown scenario');
})().catch(error => {console.error(error);process.exitCode = 1;});
