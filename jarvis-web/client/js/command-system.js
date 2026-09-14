/**
 * Workflow and Prompt System
 * Handles /workflows and @prompts for enhanced chat interaction
 */
class CommandSystem {
  constructor() {
    this.prompts = {};     // @prompt registry
    this.workflows = {};   // /workflow registry (multi-tool pipelines)
    this.tools = {};       // #tool hint registry
    this.maxToolHints = 5;
    this.loaded = false;
    this._registryRequestId = 0;
    this._loadRegistry();
  }

  _resolveMode(mode = null) {
    const selected = mode
      || window.jarvisApp?.modeSelect?.value
      || window.jarvisSocket?.mode
      || Utils.storage.get('mode', 'cloud');
    return selected === 'local' ? 'local' : 'cloud';
  }

  /**
   * Load prompts and workflows from server
   */
  async _loadRegistry(mode = null) {
    const selectedMode = this._resolveMode(mode);
    const modeQuery = `mode=${encodeURIComponent(selectedMode)}`;
    const requestId = ++this._registryRequestId;
    try {
      // Load prompts, workflows, and enabled tools in parallel
      const [promptsRes, workflowsRes, toolsRes] = await Promise.all([
        fetch(`/api/prompts?${modeQuery}`),
        fetch(`/api/workflows?${modeQuery}`),
        fetch(`/api/tools?summary=true&include_blocked=false&${modeQuery}`)
      ]);

      // A rapid mode switch can finish requests out of order. Only the newest
      // selected-mode snapshot may update slash commands and tool hints.
      if (requestId !== this._registryRequestId) return;

      if (promptsRes.ok) {
        const data = await promptsRes.json();
        this.prompts = data.prompts || {};
      }

      if (workflowsRes.ok) {
        const data = await workflowsRes.json();
        this.workflows = data.workflows || {};
      }

      if (toolsRes.ok) {
        const data = await toolsRes.json();
        this._setToolsFromList(data.tools || []);
      }

      this.loaded = true;
      console.log('[Commands] Loaded:', Object.keys(this.prompts).length, 'prompts,',
                  Object.keys(this.workflows || {}).length, 'workflows,',
                  Object.keys(this.tools || {}).length, 'tools');
    } catch (err) {
      console.warn('[Commands] Failed to load registry:', err);
    }
  }

  _setToolsFromList(tools) {
    this.tools = {};
    for (const tool of tools || []) {
      if (!tool || !tool.name || tool.blocked || tool.enabled === false) continue;
      this.tools[tool.name] = tool;
    }
  }

  async refreshTools(mode = null) {
    const selectedMode = this._resolveMode(mode);
    const modeQuery = `mode=${encodeURIComponent(selectedMode)}`;
    const requestId = ++this._registryRequestId;
    try {
      const [toolsRes, promptsRes, workflowsRes] = await Promise.all([
        fetch(`/api/tools?summary=true&include_blocked=false&${modeQuery}`),
        fetch(`/api/prompts?${modeQuery}`),
        fetch(`/api/workflows?${modeQuery}`)
      ]);
      if (requestId !== this._registryRequestId) return;
      if (toolsRes.ok) {
        const data = await toolsRes.json();
        this._setToolsFromList(data.tools || []);
      }
      if (promptsRes.ok) {
        const data = await promptsRes.json();
        this.prompts = data.prompts || {};
      }
      if (workflowsRes.ok) {
        const data = await workflowsRes.json();
        this.workflows = data.workflows || {};
      }
    } catch (err) {
      console.warn('[Commands] Failed to refresh tools/prompts/workflows:', err);
    }
  }

  _toolMatchesQuery(name, query) {
    if (!query) return true;
    const lowered = name.toLowerCase();
    const q = query.toLowerCase();
    return lowered.startsWith(q) || lowered.split(/[_-]/).some(part => part.startsWith(q));
  }

  getTool(name) {
    const tool = this.tools?.[name];
    if (!tool || tool.blocked || tool.enabled === false) return null;
    return tool;
  }

  getAmbientToolSuggestions(text, selectedNames = [], limit = 3) {
    const cleanText = (text || '').trim();
    if (cleanText.length < 8) return [];

    const selected = new Set(selectedNames || []);
    const stopwords = new Set([
      'about', 'after', 'again', 'also', 'and', 'are', 'can', 'could', 'for',
      'from', 'have', 'help', 'how', 'into', 'just', 'like', 'make', 'need',
      'please', 'show', 'that', 'the', 'this', 'use', 'want', 'what', 'when',
      'where', 'with', 'would', 'you'
    ]);
    const normalized = cleanText.toLowerCase();
    const tokens = [...new Set((normalized.match(/[a-z0-9]{3,}/g) || [])
      .filter(token => !stopwords.has(token)))];
    if (tokens.length === 0) return [];

    return Object.entries(this.tools || {})
      .filter(([name, tool]) => !selected.has(name) && tool && tool.enabled !== false && !tool.blocked)
      .map(([name, tool]) => {
        const nameLower = name.toLowerCase();
        const nameWords = nameLower.split(/[_-]+/).filter(Boolean);
        const description = (tool.description || '').toLowerCase();
        const source = (tool.source || '').toLowerCase();
        const haystack = `${nameWords.join(' ')} ${description} ${source}`;
        let score = 0;

        if (normalized.includes(nameLower)) score += 12;
        for (const word of nameWords) {
          if (word.length >= 3 && normalized.includes(word)) score += 4;
        }

        for (const token of tokens) {
          if (nameWords.some(word => word.startsWith(token) || token.startsWith(word))) {
            score += 4;
          } else if (description.includes(token)) {
            score += 2;
          } else if (haystack.includes(token)) {
            score += 1;
          }
        }

        return {
          type: 'tool',
          name,
          prefix: '#',
          icon: tool.source === 'mcp' ? '🔌' : '🛠️',
          description: tool.description || `Prefer ${name} for this request`,
          source: tool.source || 'local',
          score
        };
      })
      .filter(item => item.score >= 3)
      .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name))
      .slice(0, limit);
  }

  /**
   * Get autocomplete suggestions for input
   * @param {string} input - Current input text
   * @returns {Array} Suggestions [{type, name, icon, description}]
   */
  getSuggestions(input) {
    const suggestions = [];

    // Check for /workflow prefix
    if (input.startsWith('/')) {
      const query = input.slice(1).toLowerCase();

      // Add workflow suggestions
      for (const [id, wf] of Object.entries(this.workflows || {})) {
        // Match against workflow triggers (e.g., /research, /note)
        const triggers = wf.triggers || [];
        for (const trigger of triggers) {
          if (!trigger.startsWith('/')) continue;
          const triggerName = trigger.replace('/', '');
          if (triggerName.toLowerCase().startsWith(query) || query === '') {
            suggestions.push({
              type: 'workflow',
              name: triggerName,
              prefix: '/',
              icon: wf.icon || '🔄',
              description: wf.description || `${wf.name} (${wf.step_count} steps)`,
              workflow_id: id,
              steps: wf.steps || [],  // Include steps for tooltip
              tools_used: wf.tools_used || []
            });
            break; // Only add once per workflow
          }
        }
      }
    }

    // Check for *bookmark search prefix (Firefox-style)
    if (input.startsWith('*')) {
      const query = input.slice(1).toLowerCase();
      for (const [id, wf] of Object.entries(this.workflows || {})) {
        const triggers = wf.triggers || [];
        for (const trigger of triggers) {
          if (trigger === '*' || trigger.startsWith('*')) {
            const triggerName = trigger.replace('*', '') || 'bookmarks';
            suggestions.push({
              type: 'workflow',
              name: wf.name || 'Search bookmarks',
              prefix: '*',
              icon: '🔖',
              description: wf.description || 'Search your Firefox bookmarks',
              workflow_id: id,
              steps: wf.steps || [],
              tools_used: wf.tools_used || []
            });
            break;
          }
        }
      }
    }

    // Check for @prompt prefix
    if (input.startsWith('@')) {
      const query = input.slice(1).toLowerCase();
      for (const [name, prompt] of Object.entries(this.prompts)) {
        if (name.toLowerCase().startsWith(query) || query === '') {
          suggestions.push({
            type: 'prompt',
            name: name,
            icon: '📝',
            description: prompt.description || `Use ${name} methodology`,
            key_points: prompt.key_points || []  // Include key points for tooltip
          });
        }
      }
    }

    // Check for #tool hint prefix
    if (input.startsWith('#')) {
      const query = input.slice(1).toLowerCase();
      if ('chat_only'.startsWith(query)) {
        suggestions.push({
          type: 'policy',
          name: 'chat_only',
          prefix: '#',
          icon: '◌',
          description: 'Answer directly without Tool RAG or provider-hosted tools'
        });
      }
      for (const [name, tool] of Object.entries(this.tools || {})) {
        if (this._toolMatchesQuery(name, query)) {
          suggestions.push({
            type: 'tool',
            name: name,
            prefix: '#',
            icon: tool.source === 'mcp' ? '🔌' : '🛠️',
            description: tool.description || `Prefer ${name} for this request`,
            source: tool.source || 'local'
          });
        }
      }
    }

    const sorted = suggestions.sort((a, b) => {
      // Chat only is a sticky composer policy, not an ordinary tool hint. Pin
      // it above the alphabetical tool list so an empty # menu keeps the mode
      // immediately accessible without changing typed-prefix matching.
      if (input.startsWith('#') && a.type !== b.type) {
        if (a.type === 'policy') return -1;
        if (b.type === 'policy') return 1;
      }
      return a.name.localeCompare(b.name);
    });
    // Tool hints are intentionally scrollable: the user should be able to browse
    // every currently enabled tool, while prompts/workflows stay compact.
    if (input.startsWith('#')) {
      return sorted;
    }
    return sorted.slice(0, 30);
  }

  /**
   * Parse input and extract workflow/prompt + message
   * @param {string} input - Raw input text
   * @returns {Object} {workflow?, prompt?, message, instruction?}
   */
  parseInput(input) {
    const result = {
      prompt: null,
      workflow: null,
      toolHints: [],
      toolPolicy: null,
      message: input,
      instruction: null
    };

    // Check for *bookmark search (Firefox-style)
    if (input.startsWith('*')) {
      for (const [id, wf] of Object.entries(this.workflows || {})) {
        const triggers = wf.triggers || [];
        if (triggers.includes('*')) {
          result.workflow = id;
          result.message = input; // Keep full message for orchestrator's workflow detection
          return result;
        }
      }
    }

    // Check for /workflow
    const cmdMatch = input.match(/^\/(\w+[-\w]*)\s*(.*)/s);
    if (cmdMatch) {
      const cmdName = cmdMatch[1].toLowerCase();

      // Check if it's a workflow trigger
      for (const [id, wf] of Object.entries(this.workflows || {})) {
        const triggers = wf.triggers || [];
        for (const trigger of triggers) {
          if (trigger.startsWith('/') && trigger.replace('/', '') === cmdName) {
            result.workflow = id;
            result.message = input; // Keep full message for orchestrator's workflow detection
            return result; // Workflows don't combine with @prompts
          }
        }
      }
    }

    // Check for @prompt (only if not a workflow)
    const promptMatch = result.message.match(/^@(\w+)\s*(.*)/s);
    if (promptMatch) {
      const promptName = promptMatch[1].toLowerCase();
      const prompt = this.prompts[promptName];
      if (prompt) {
        result.prompt = promptName;
        result.message = promptMatch[2].trim();
        result.instruction = prompt.content || '';
        const promptHints = Array.isArray(prompt.tool_hints) ? prompt.tool_hints : [];
        for (const name of promptHints) {
          const tool = this.tools[name];
          if (!tool || tool.blocked || tool.enabled === false) continue;
          if (!result.toolHints.includes(name) && result.toolHints.length < this.maxToolHints) {
            result.toolHints.push(name);
          }
        }
      }
    }

    // Extract the built-in chat-only policy and standalone #tool_name hints.
    // Unknown hashtags are left alone so normal prose is not accidentally removed.
    const hints = [];
    result.message = result.message.replace(/(^|\s)#([A-Za-z0-9_-]+)(?=\s|$)/g, (full, leading, name) => {
      if (name.toLowerCase() === 'chat_only') {
        result.toolPolicy = 'none';
        return leading;
      }
      const tool = this.tools[name];
      if (!tool || tool.blocked || tool.enabled === false) return full;
      if (!hints.includes(name) && hints.length < this.maxToolHints) {
        hints.push(name);
      }
      return leading;
    }).replace(/\s{2,}/g, ' ').trim();
    for (const name of hints) {
      if (!result.toolHints.includes(name) && result.toolHints.length < this.maxToolHints) {
        result.toolHints.push(name);
      }
    }

    return result;
  }

  /**
   * Get display text for active workflow/prompt
   */
  getActiveDisplay(parsed) {
    const parts = [];
    if (parsed.toolPolicy === 'none') {
      parts.push('#chat_only ◌');
    }
    if (parsed.workflow) {
      const wf = this.workflows[parsed.workflow];
      const prefix = (wf?.triggers || []).includes('*') ? '*' : '/';
      parts.push(`${prefix}${parsed.workflow === 'bookmark_search' ? 'bookmarks' : parsed.workflow} ${wf?.icon || '🔄'}`);
    }
    if (parsed.prompt) {
      parts.push(`@${parsed.prompt} 📝`);
    }
    if (parsed.toolHints && parsed.toolHints.length > 0) {
      parts.push(parsed.toolHints.map(name => `#${name}`).join(' ') + ' 🛠️');
    }
    return parts.join(' + ');
  }

  /**
   * Rebuild prompt/tool provenance from a saved user message.
   * Historical badges describe what was selected for that turn, even if a
   * referenced prompt or tool is no longer available in the current mode.
   */
  getPersistedDisplay(data = {}) {
    const isSafeName = (value) => (
      typeof value === 'string' && /^[A-Za-z0-9_-]+$/.test(value)
    );
    const prompt = isSafeName(data?.prompt) ? data.prompt : null;
    const toolHints = [];
    for (const name of Array.isArray(data?.tool_hints) ? data.tool_hints : []) {
      if (!isSafeName(name) || toolHints.includes(name)) continue;
      toolHints.push(name);
      if (toolHints.length >= this.maxToolHints) break;
    }

    const toolPolicy = data?.tool_policy === 'none' ? 'none' : null;
    return this.getActiveDisplay({ prompt, workflow: null, toolHints, toolPolicy });
  }
}

// Global command system instance
window.commandSystem = new CommandSystem();
