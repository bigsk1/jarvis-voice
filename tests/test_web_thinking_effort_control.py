"""Behavioral Web tests for model-aware thinking-effort presentation."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_control_refreshes_options_and_hides_unprofiled_models():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/app.js', 'utf8');
const appSource = source.slice(
  source.indexOf('class JarvisApp'),
  source.indexOf('// Initialize app when DOM is ready')
);
eval(appSource + '\nglobal.JarvisApp = JarvisApp;');

global.Option = function(text, value) {
  this.text = text;
  this.value = value;
};

const group = {hidden: true};
const effort = {
  value: 'medium',
  disabled: true,
  options: [],
  replaceChildren(option) {
    this.options = [option];
    this.value = '';
  },
  add(option) {
    this.options.push(option);
  }
};
const label = {className: '', textContent: ''};
const model = {value: 'glm-5.3:cloud'};
const elements = {
  'thinking-effort-group': group,
  'setting-thinking-effort': effort,
  'thinking-effort-default': label,
  'setting-llm-model': model
};
global.document = {getElementById: id => elements[id] || null};

const app = Object.create(global.JarvisApp.prototype);
app.socket = {mode: 'cloud'};
app._settingsData = {
  mode: 'cloud',
  llm: {model: {default: 'glm-5.3:cloud'}, thinking_effort: {default: 'auto'}},
  provider_model_defaults: {
    ollama: 'glm-5.3:cloud',
    openai: 'gpt-5.4'
  },
  provider_models: {
    ollama: [{
      id: 'glm-5.3:cloud',
      thinking_effort: {profiled: true, options: ['low', 'high', 'max']}
    }],
    openai: [{
      id: 'gpt-5.4',
      thinking_effort: {profiled: false, options: []}
    }]
  }
};

app._updateThinkingEffortControl('ollama', {
  is_override: true,
  value: 'high',
  default: 'auto'
});
if (group.hidden || effort.disabled) throw new Error('Profiled control stayed hidden');
if (effort.value !== 'high') throw new Error(`Expected high override, got ${effort.value}`);
if (effort.options.map(option => option.value).join(',') !== ',low,high,max') {
  throw new Error('GLM options were not refreshed from its profile');
}

model.value = 'gpt-5.4';
app._updateThinkingEffortControl('openai');
if (!group.hidden || !effort.disabled) throw new Error('Unprofiled control stayed visible');
if (effort.value !== '') throw new Error('Stale effort survived an unprofiled model change');
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
