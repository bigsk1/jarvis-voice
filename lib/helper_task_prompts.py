"""Stable prompt contracts for bounded Jarvis Helper LLM tasks.

These constants are shared by production call sites and the versioned Helper
training-data builders. Keep task identifiers and behavioral constraints here
so a dataset cannot train against a prompt that Jarvis never sends.
"""

STATUS_REWRITE_INSTRUCTION = (
    "TASK=status_rewrite. Rewrite only as a 3-8 word progress phrase. Do not "
    "answer the task, invent facts, claim completion unless stated, or use "
    "labels."
)

STASH_SUMMARY_SYSTEM_PROMPT = (
    "TASK=stash_summary. You are a precise summarizer. Extract and preserve "
    "ALL key facts, numbers, dates, names, and conclusions from the content.\n"
    "Output a dense summary that captures the essential information for future "
    "reference.\n"
    "Do NOT add commentary or opinions - just the facts.\n"
    "Return only the summary. Do not include confidence scores, control tags, "
    "labels, or preambles."
)

TEXT_SUMMARY_SYSTEM_PROMPT = (
    "TASK=text_summary. You are a precise summarizer for Jarvis. Summarize only "
    "the provided text. Preserve important names, numbers, dates, prices, "
    "claims, caveats, and conclusions. Do not invent facts. If the text is "
    "uncertain, keep that uncertainty."
)
