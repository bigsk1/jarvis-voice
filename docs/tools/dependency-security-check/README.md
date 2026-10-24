# Dependency security check

`dependency_security_check` checks Jarvis Python package versions against current
[OSV advisories](https://google.github.io/osv.dev/api/). It reads package metadata
and dependency inventories without importing the installed packages, running a
dependency resolver, or installing anything. It needs no API key or additional
Python package.

## Run and inspect

Run `/jarvis_security_check` in Jarvis Web or the production CLI. The workflow
refreshes **Workflows/Jarvis Dependency Security** on Canvas and creates a
deduplicated alert when it finds affected versions or cannot complete its checks.
It makes no model calls. An unchanged clean result updates Canvas quietly.

The underlying tool accepts `{}` or `{"action": "check"}`. It has no upgrade,
command, interpreter, or arbitrary path argument. Its restricted child
environment inherits common runtime/TLS/proxy settings, with no provider keys.
Package names and versions are sent to the fixed OSV API over HTTPS.

The report separates the executing Python environment from repository lockfile
entries and any available development environment. A universal lockfile can
include packages for other platforms; a lockfile match does not prove that
package is installed on this host. Missing or malformed required inventories,
unavailable advisory responses, and bounded-request limits produce an
**incomplete** report rather than an all-clear result. Positive findings remain
visible if another part of the audit fails.

Known-advisory matches do not establish exploitability. Published fixed versions
are evidence for an upgrade review, not a dependency compatibility guarantee.
Review the report with Codex before applying updates.

## Weekly schedule

In Jarvis Memory's **Scheduled Tasks**, create a workflow task for **Jarvis
Dependency Security Check** (`jarvis_dependency_security_check`). No workflow
input is needed. For example:

- Schedule: `every Sunday at 9am`
- Timezone: `America/Los_Angeles`
- Execution timeout: 120 seconds
- Overlapping runs: disabled
- Alert on task failure: enabled

Choose one mode for this host audit; scheduling it in both modes duplicates the
same host inventory check. The task runs through the existing Jarvis scheduler
on the server. A Windows client or Codex does not need to be open. The server
and scheduler must be running; overdue occurrences outside the scheduler's
grace period are recorded as missed and skipped, rather than replayed on startup.
**Run now** performs a manual check without waiting for the weekly slot.

Audit findings and incomplete checks produce workflow alerts. Wrapper crashes,
tool timeouts, unavailable required tools, and Canvas failures fail the workflow;
the scheduled task's alert-on-failure setting covers those failures. A workflow
can successfully publish an incomplete diagnostic report, so inspect the audit
status inside the report rather than treating the outer task status as an
all-clear.

## Coverage boundaries

This is a known-advisory Python dependency check. It does not audit Ubuntu
packages, the standalone `uv` executable, credentials, application source code,
running container images, or packages installed on remote services such as a
Craft gateway. In Docker, the executing environment is the container, not the
host. Repository install files describe planned dependencies, not proof that a
running container or remote deployment has adopted them.

The current Canvas page replaces older findings so resolved versions do not
remain in its current status. Scheduled run history retains each run's structured
tool result. Alerts use a stable result identity to suppress duplicate pending
alerts; they do not apply fixes or close earlier alerts automatically.

Disable the scheduled task to stop recurring checks. Remove the tool/workflow
files to remove the feature; no database migration or extra service is involved.
