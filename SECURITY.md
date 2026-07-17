# Security policy

## Supported versions

CIB is pre-1.0. Security fixes target the latest released minor version.

## Report a vulnerability

Use GitHub's private vulnerability-reporting form from the repository Security
tab. Do not open a public issue for suspected credential exposure, command
injection, sandbox escape, unsafe fixture handling, or evidence disclosure.

Include the affected version, reproduction steps, impact, and any suggested
mitigation. The maintainer will acknowledge a complete report within seven days
and will coordinate disclosure after a fix is available. This is a volunteer
project, so the policy is a target rather than a paid support guarantee.

## Security boundaries

CIB invokes coding agents and local commands. Treat benchmark fixtures and
provider output as untrusted data.

- Scientific runs use read-only agent sandboxes and `approval_policy: never`.
- Each trial receives a unique fixture, HOME, CODEX_HOME, nonce, and session.
- The default Promptfoo profile disables cache, sharing, and thread persistence.
- CIB links existing Codex auth into isolated trial homes; it never copies auth
  contents into public manifests.
- Generated `results/` may contain local paths, model output, synthetic nonces,
  and auth symlinks. Never publish it without a separate sanitization review.
- Run only benchmark cases and adapters you have inspected and authorized.

The deterministic publication check and GitHub secret scanning reduce leakage
risk, but neither replaces review of the exact files and Git history being
published.
