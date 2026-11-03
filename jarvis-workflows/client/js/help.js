/* Local, runtime-checked authoring examples. No services are used to show help. */
(function (root) {
    'use strict';
    const json = (description, value, note = '') => ({description, format: 'JSON', example: JSON.stringify(value, null, 2), note});
    const text = (description, example, note = '') => ({description, format: 'Text', example, note});
    const fields = {
        id: text('A stable name for this recipe. New names use lowercase letters, numbers, and underscores.', 'weekly_report'),
        name: text('The friendly name shown in the recipe library.', 'Weekly report'),
        description: text('Describe the outcome so you can recognize this recipe later.', 'Find recent news and save a short report to Canvas.'),
        explicit: json('Commands that start this recipe. Each command is a quoted item in a JSON list.', ['/weekly_report'], 'For example, /weekly_report garden ideas runs it with garden ideas as the topic. Matching ignores case and uses the longest prefix.'),
        variables: json('Optional names for values used by steps. You can leave this as {}: ${topic} already contains the query text.', {
            subject: {from: 'query', extract: 'main_subject', default: 'weekly news'},
            source_url: {from: 'query', extract: 'url'},
            max_sources: 3,
        }, 'Use ${subject} or ${source_url} in a parameter. Do not put ${...} around the names on the left. main_subject takes the topic; it does not parse arbitrary attributes. short_title is resolved at run time and may call a model. Environment bindings are restricted to reviewed nonsecret settings.'),
        tool_defaults: json('Default input values for a tool throughout this recipe. A step can override them.', {calculator: {expression: '2+2'}}, 'Use actual input names from that tool. Defaults are literal values; template substitutions belong in step parameters.'),
        validation_policy: json('Limit the total failed or invalid loop candidates across the recipe.', {max_total_retries: 3}, 'This does not retry a failed single step. Other retry-policy keys are not used by the current engine.'),
        workflow_llm_options: json('Optional settings for workflow model calls. Leave blank to use the configured defaults.', {xai_reasoning_effort: 'low', xai_request_timeout_seconds: 120}, 'These options apply to xAI. This field does not select a different provider or model.'),
        success_speech: text('The message returned after the whole workflow finishes.', 'Saved the report about ${topic}.'),
        abort_speech: text('The message returned if a required step fails.', 'The report could not be completed.'),
        success_speech_llm_prompt: text('Ask the configured model to write the final completion message.', 'Briefly confirm that the report about ${topic} was saved.', 'This uses a model call. Success speech is the fallback. Partial live runs omit whole-workflow completion speech.'),
        action: text('An action supported by this tool, when the tool uses action names.', 'search', 'Choose an action from the tool schema; names differ between tools.'),
        output_var: text('Give this step’s output a name so later steps can use it. Enter the name alone.', 'answer', 'Later, use ${answer.result} if the output contains a result field. Output paths depend on the tool; inspect a published live run to confirm them.'),
        extract: json('Save selected values from a successful single step under short variable names.', {first_url: 'results[0].url', all_urls: 'results[*].url'}, 'Paths start inside the tool’s data object: omit the data. prefix. Later use ${first_url}. Inspect the tool output to find the correct paths. This extraction does not apply to loop steps.'),
        search_output_var: text('Name the normalized search output for later steps.', 'search_results', 'For search tools, use ${search_results.urls} for URLs, or ${search_results.data} for structured search data.'),
        validated_output_var: text('Name the collection of successful, validated loop results.', 'valid_pages', 'Loop results contain tool-result envelopes. Their nested paths depend on the tool. Leave blank if no later step needs this collection.'),
        condition: json('Run this step only when a comparison is true. Leave blank to run it normally.', {left: '${topic}', op: 'contains', right: 'report'}, 'Use eq, ne, lt, lte, gt, gte, contains, contains_any, exists, not_exists, or truthy. Combine comparisons with {"all": [...]} or {"any": [...]}; do not write JavaScript or Python.'),
        for_each: text('Repeat this tool over a list from an earlier step.', '${search_results.urls[:3]}', 'This example tries up to three URLs. String items become the tool’s url parameter; object items merge into its parameters. There is no ${item} variable. A loop normally stops after one successful result.'),
        process_all: text('Choose True to visit every item instead of stopping after enough successes.', 'True', 'The item-attempt and total-failure limits still apply.'),
        required_success_count: text('How many usable loop results to collect before stopping.', '2', 'Use with Process all items set to False or left at its default.'),
        on_all_fail: text('What to do if a loop produces fewer successful results than required.', 'abort_with_message', 'Allowed values: abort_with_message or continue. Approval denial and policy rejection always stop execution.'),
        llm_prompt: text('For a single step, ask the model to generate the tool’s content parameter using earlier values.', 'Write a concise summary of ${topic} using ${search_results.data}.', 'This uses a model call. The target is tool-specific, such as send_email.body or canvas.content. It does not fill every arbitrary parameter. Loop steps do not use this prompt.'),
        llm_output_validation: json('Check model-generated text before sending it to the tool.', {param: 'body', min_length: 40, required_patterns: ['Summary'], reject_patterns: ['I cannot']}, 'Set param to the generated input name: body for email, content for Canvas, or text for Stash. Patterns are case-insensitive text matches.'),
        validation: json('Decide whether a tool result is usable, especially when trying loop candidates.', {type: 'heuristic', min_length: 200, reject_patterns: ['access denied']}, 'For normalized search results, min_urls can require a URL count. LLM or hybrid validation can make additional model calls.'),
        llm_variable_max_chars: text('Limit each structured list/object inserted into an LLM prompt.', '6000', 'The default is 3000 characters; supported values are 500–50000. Ordinary string values are not shortened by this setting.'),
        on_fail: text('How to handle an ordinary failure of this step.', 'continue', 'Use continue to proceed after an ordinary tool failure. Required steps normally abort. Approval denial, cancellation, and policy rejection cannot be skipped.'),
        retry: json('Cap how many different loop input items can be attempted.', {max_attempts: 3}, 'This is a candidate limit, not three executions of the same failed call. Single steps are not retried by this setting.'),
        set_variables_on_success: json('Set variables after a successful single step with an output variable.', {report_saved: true}, 'For this example, give the step an Output variable too. These assignments are not applied to loop steps.'),
        set_variables_on_skip: json('Set fallback variables when the condition is false or an optional tool is unavailable.', {report_saved: false}, 'Use these defaults when later steps depend on a value that might not be produced.'),
    };
    function forField(path) {
        if (path[0] === 'steps' && path.at(-1) === 'description') return text('Explain what this step contributes to the workflow.', 'Save the final report');
        return fields[path.at(-1)] || null;
    }
    function parameter(schema = {}) {
        const type = schema.type || 'string';
        const sample = schema.examples?.[0] ?? schema.example ?? schema.default ?? schema.enum?.[0];
        const description = schema.description || 'Enter this tool input directly, or use a value from an earlier step.';
        const note = 'A binding such as ${topic} or ${answer.result} uses an existing value. Choose an earlier output from the chips above; its path must match that tool’s result.';
        if (sample !== undefined) return ['object', 'array'].includes(type) ? json(description, sample, note) : text(description, String(sample), note);
        if (type === 'object') return json(description, {}, note);
        if (type === 'array') return json(description, [], note);
        if (type === 'boolean') return text(description, 'True', note);
        if (['integer', 'number'].includes(type)) return text(description, String(schema.minimum ?? 1), note);
        return text(description, '${topic}', note);
    }
    const api = {forField, parameter};
    root.WorkflowHelp = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
