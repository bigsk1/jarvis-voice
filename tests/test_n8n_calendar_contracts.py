"""Exercise saved workflow expressions with representative webhook/event data."""

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CALENDAR_ID = 'configured.calendar+sample@example.test'

# n8n's $node[...].parameter proxy unwraps stored resourceLocator objects.
# Model that boundary, rather than substituting an already-resolved string.
# Upstream: packages/workflow/src/workflow-data-proxy.ts, nodeParameterGetter.
CALENDAR_EXPRESSION_RUNTIME = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const $json = input.event;
const $node = Object.fromEntries(input.nodes.map(node => [node.name, {
  parameter: new Proxy(node.parameters, {
    get(target, name) {
      const stored = target[name];
      return stored && typeof stored === 'object' && stored.__rl === true ? stored.value : stored;
    }
  })
}]));
const DateTime = {fromISO: () => ({toUTC: () => ({toFormat: () => '2030-01-01T12:00:00Z'})})};
const $now = {toISO: () => '2030-01-01T11:00:00Z'};
let result;
if (input.expression.startsWith('={{')) {
  result = JSON.parse(eval(input.expression.slice(3, -2)));
} else {
  result = input.expression.slice(1).replace(/{{(.*?)}}/g, (_, expression) => eval(expression));
}
process.stdout.write(JSON.stringify(result));
"""


def workflow(name):
    return json.loads((ROOT / 'docs/n8n/workflows' / name).read_text())


def javascript(source, value):
    result = subprocess.run(['node', '-e', source], input=json.dumps(value), text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def configured_calendar(saved, node_name, field, mode):
    saved = deepcopy(saved)
    node = next(item for item in saved['nodes'] if item['name'] == node_name)
    stored = node['parameters'][field]
    assert stored['__rl'] is True and isinstance(stored['value'], str)
    if mode == 'string':
        node['parameters'][field] = CALENDAR_ID
    else:
        stored.update(value=CALENDAR_ID, mode=mode)
        if mode == 'list':
            stored['cachedResultName'] = 'Display label, not the calendar ID'
    return saved


def calendar_expression(expression, saved, event):
    return javascript(CALENDAR_EXPRESSION_RUNTIME, {
        'expression': expression, 'nodes': saved['nodes'], 'event': event,
    })


@pytest.mark.parametrize('body,expected', [
    ({'action': 'create', 'reminder': {'title': 'Sample', 'trigger_time': '2030-01-01T12:00:00Z'}}, True),
    ({'action': 'test', 'reminder': {'title': 'Sample', 'trigger_time': '2030-01-01T12:00:00Z'}}, False),
    ({'action': 'create', 'reminder': {'title': 'Sample'}}, False),
    ({'action': 'create', 'reminder': {'trigger_time': '2030-01-01T12:00:00Z'}}, False),
    ({}, False),
])
def test_saved_switch_rejects_unsupported_actions_and_incomplete_reminders(body, expected):
    saved = workflow('Jarvis → Google Calendar Sync.json.example')
    switch = next(node for node in saved['nodes'] if node['name'] == 'Check Action')
    matched = javascript(r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const $json = {body: input.body};
function value(text) {
  if (typeof text === 'string' && text.startsWith('={{')) {
    return eval(text.slice(3, -2));
  }
  return text;
}
const rule = input.parameters.rules.values[0].conditions;
const result = rule.conditions.map(c => {
  const left = value(c.leftValue), right = value(c.rightValue);
  if (c.operator.operation === 'equals') return left === right;
  if (c.operator.operation === 'notEmpty') return typeof left === 'string' && left.length > 0;
  throw new Error('Unexpected comparison operator');
});
process.stdout.write(JSON.stringify(rule.combinator === 'and' ? result.every(Boolean) : result.some(Boolean)));
""", {'body': body, 'parameters': switch['parameters']})
    assert matched is expected
    assert switch['parameters']['options']['fallbackOutput'] == 'extra'
    assert saved['connections']['Check Action']['main'][1][0]['node'] == 'Respond Error'


@pytest.mark.parametrize('node_name,trigger', [
    ('Create Jarvis Reminder', 'GCal Event Created'),
    ('Update Jarvis Reminder', 'GCal Event Updated'),
])
@pytest.mark.parametrize('mode', ['id', 'list', 'string'])
def test_incoming_json_escapes_event_text_and_uses_configured_calendar(node_name, trigger, mode):
    saved = configured_calendar(workflow('Google Calendar → Jarvis Sync.json.example'),
                               trigger, 'calendarId', mode)
    node = next(item for item in saved['nodes'] if item['name'] == node_name)
    event = {'id': 'sample-event', 'summary': 'Sample "quoted" appointment',
             'description': 'Two lines\nwith "quotes"',
             'organizer': {'email': 'other.organizer@example.test'},
             'start': {'dateTime': '2030-01-01T12:00:00Z'}}
    result = calendar_expression(node['parameters']['jsonBody'], saved, event)
    assert result['title'] == event['summary']
    assert result['description'] == event['description']
    assert result['metadata']['gcal_calendar_id'] == CALENDAR_ID


@pytest.mark.parametrize('node_name,trigger', [
    ('Update Jarvis Reminder', 'GCal Event Updated'),
    ('Cancel Jarvis Reminder', 'GCal Event Cancelled'),
])
@pytest.mark.parametrize('mode', ['id', 'list', 'string'])
def test_calendar_url_uses_encoded_resolved_id(node_name, trigger, mode):
    from urllib.parse import parse_qs, urlsplit

    saved = configured_calendar(workflow('Google Calendar → Jarvis Sync.json.example'),
                               trigger, 'calendarId', mode)
    node = next(item for item in saved['nodes'] if item['name'] == node_name)
    url = calendar_expression(node['parameters']['url'], saved, {'id': 'sample-event'})
    parsed = urlsplit(url)
    assert parsed.path.endswith('/by-gcal/sample-event')
    assert parse_qs(parsed.query) == {'calendar_id': [CALENDAR_ID]}
    assert '%2B' in parsed.query and '%40' in parsed.query


@pytest.mark.parametrize('mode', ['id', 'list', 'string'])
def test_outgoing_success_receipt_uses_resolved_calendar_id(mode):
    saved = configured_calendar(workflow('Jarvis → Google Calendar Sync.json.example'),
                               'Create Calendar Event', 'calendar', mode)
    node = next(item for item in saved['nodes'] if item['name'] == 'Respond Success')
    result = calendar_expression(node['parameters']['responseBody'], saved, {'id': 'sample-event'})
    assert result['ok'] is True and result['gcal_event_id'] == 'sample-event'
    assert result['gcal_calendar_id'] == CALENDAR_ID
