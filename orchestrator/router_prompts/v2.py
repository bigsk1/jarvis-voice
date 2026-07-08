"""v2 experiment: preserve v1 wording while removing blank lines."""

from .v1 import BASE_SYSTEM_PROMPT as V1_SYSTEM_PROMPT


# This deliberately derives from immutable, hash-validated v1 so the first
# experiment changes only blank-line whitespace. Later semantic compression
# should use a new version rather than silently broadening this experiment.
BASE_SYSTEM_PROMPT = "\n".join(
    line for line in V1_SYSTEM_PROMPT.splitlines() if line.strip()
)
BASE_SYSTEM_PROMPT_SHA256 = "2eac90483f6908db2308d1c2cedd79d35cd7e73c70704b4a2ee18a74285dbb90"
