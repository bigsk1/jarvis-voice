"""Background job foundation. Importing this package starts no services or storage.

Web admission and continuation are integrated through the Web-owned service.
The shared supervised runner serves convert_file through local_skill_v1 and
the three media generators plus create_social_clip through conservative
remote_skill_v1 semantics.
Direct task callbacks use the separate webhook_integrations inbox and explicit
local-service bindings. Provider-specific cancellation/recovery remains deferred.
"""

from .models import Admission, AdmissionDenied, Conflict, LostLease, ReceiptEvidence, TaskError
from .store import TaskStore

__all__ = [
    "Admission",
    "AdmissionDenied",
    "Conflict",
    "LostLease",
    "ReceiptEvidence",
    "TaskError",
    "TaskStore",
]
