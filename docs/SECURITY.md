# Security record

This file records the security posture of LEVEL 5 as it is actually
implemented, plus the checks that back each claim. It is written to be
reproducible: every command below can be re-run.

Last full pass: **2026-11-09**.

## 1. Secrets

| Check | Result | How it was checked |
| --- | --- | --- |
| No credentials committed to git | clean | `git grep -nIE "sk-[A-Za-z0-9]{20,}\|AKIA[0-9A-Z]{16}\|ghp_[A-Za-z0-9]{30,}\|-----BEGIN [A-Z ]*PRIVATE KEY"` |
| No `.env` / key / pem files tracked | clean | `git ls-files \| grep -iE "\.env$\|\.pem$\|\.key$\|secret"` |
| No secrets in the API responses | clean | `curl` of `/api/health`, `/api/projects`, `/api/agents`, `/api/benchmarks` matched against `sk-…`, `llm_api_key`, `bearer …` |
| No secrets in the shipped frontend bundle | clean | `grep` of `frontend/dist/assets/*` (matches were CSS `task-*` class names, not keys) |

Credentials are read from the environment (`level5/config.py`) and never
serialised into a project record or returned by an endpoint. The frontend holds
no key: all model calls happen server-side.

## 2. Path traversal

The file browser and the preview asset server both resolve a requested path and
refuse anything that leaves the project root. Verified live, with the raw
(non-normalised) path so the guard is what rejects it, not curl:

```
$ curl --path-as-is "…/api/projects/<id>/files?path=../../../../etc/passwd"
{"detail":"path escapes workspace"}

$ curl --path-as-is -o /dev/null -w '%{http_code}' "…/api/projects/<id>/preview/../../../../etc/passwd"
404
```

Uploads strip any directory component (`Path(name).name`) and reject `.` / `..`,
and are size-capped at `LEVEL5_MAX_ATTACHMENT_BYTES` (25 MiB default).

## 3. Execution isolation

Agent work runs inside the OpenHands Agent Server, which provides the sandbox,
tool execution and action-confirmation policy (`level5/runtime/agent_server.py`,
`confirmation_policy: NeverConfirm` for the platform's own automated runs, with
per-project workspaces isolated from the platform repository).

## 4. Dependency audit — `filelock` (accepted risk, documented)

`pip-audit` reports 13 advisories against the transitive dependency
`filelock==3.32.7`. The finding is real (confirmed against OSV:

```
$ python -c 'import httpx; print(len(httpx.post("https://api.osv.dev/v1/query",
  json={"package":{"name":"filelock","ecosystem":"PyPI"},"version":"3.32.7"}).json()["vulns"]))'
13
```

**Why the fix cannot be applied in the current supported stack.** The advisory
fix versions are `filelock>=4.2.1`. The dependency chain is:

```
openhands-sdk 1.60.1  →  litellm <1.106,>=1.104.3
litellm 1.105.x       →  filelock <4.0,>=3.16.1
```

Every `litellm` version that `openhands-sdk 1.60.1` permits (the entire 1.105.x
line) pins `filelock<4.0`. `openhands-sdk` is pinned to the running Agent Server
version (`1.60.1`), so moving off it is out of scope for this pass. Installing
`filelock 4.2.9` against the pinned litellm was tested: imports succeed and the
full suite passes, but `pip check` reports the unmet `filelock<4.0` constraint —
a broken resolution we do not ship.

**Why the residual risk is low in this deployment.**

- `filelock` is transitive. It is used only by `litellm`'s proxy **CLI**
  (`litellm/proxy/client/cli/…`), a code path LEVEL 5 never invokes. LEVEL 5
  uses litellm only for direct model calls.
- The advisories describe local, co-tenant races on lock paths: a Windows
  oplock on a soft-lock marker, symlink/hard-link swaps, and `mode` being
  ignored on Windows. They require another local user who can create files at
  the lock path.
- LEVEL 5's own project workspaces are per-project and not shared with
  untrusted co-tenants; the platform runs its agents in the Agent Server
  sandbox.

**Follow-up (owner action, not automatic).** When `openhands-sdk` advances to a
release whose litellm pin allows `filelock>=4.2.1`, upgrade `filelock` and drop
this note. This is recorded in `ROADMAP.md`.

## 5. What is not claimed

No penetration test, fuzzing campaign, or third-party security review has been
performed. This record states what was checked and how; it is not a statement
that the system is free of vulnerabilities.
