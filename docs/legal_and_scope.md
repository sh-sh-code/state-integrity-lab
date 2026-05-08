# Legal & scope

State Integrity Lab (SIL) is a **defensive QA / audit** tool. It is not an
offensive tool, and it must not be used as one.

This document is part of the project's "do no harm" boundary. By using SIL
you agree to operate within it.

## Permitted use

You may run SIL **only** when **all** of the following are true:

1. The target service is one you own or for which you have **explicit, written
   permission** to test (typical examples: your own account, a sandbox tenant
   you provisioned, or a Bug Bounty program whose scope explicitly includes
   the surfaces you intend to observe).
2. The data you observe belongs to you, was created by you for testing, or is
   explicitly in scope for the program.
3. The activity you perform falls within the program's published policy
   (rate, methods, allowed surfaces).
4. You read and understood the program's policy and scope **before** running
   SIL against it.

If any of those is not true: **do not run SIL against the service.**

## Forbidden use

You must **not** use SIL to:

- Access, observe, or report on data that belongs to other users.
- Bypass authentication, authorization, MFA, or rate limits.
- Brute-force credentials, tokens, or recovery flows.
- Generate denial-of-service conditions, high-load tests, or unusual traffic
  patterns.
- Drive parallel browsers / sessions to amplify load.
- Probe surfaces explicitly listed as out-of-scope by the program.
- Capture or transmit live secrets that you do not control.
- Test on production services without permission, even "lightly".

These are non-negotiable. The Phase 1 design intentionally **does not**
automate browser logins or API calls precisely so the tool cannot become a
shortcut to any of the above.

## Data hygiene

When you do find an issue:

- **Minimize evidence.** Capture only what is needed to demonstrate the
  inconsistency.
- **Redact aggressively.** The Markdown report generator masks emails, UUIDs,
  token-like strings, and IPs by default. Review the output before sharing
  and add manual redaction for anything else (free-form text, screenshots).
- **Do not include other users' data**, even after redaction. If a finding
  cannot be reproduced on test data you own, contact the program before
  capturing more.
- **Rotate any captured secret immediately.** If a screenshot accidentally
  caught a token of yours, treat it as compromised and rotate.
- **Never commit `.env`, real secrets, or live screenshots** to the
  repository. The bundled `.gitignore` excludes `.env` and the local
  `artifacts/` and `reports/` contents — keep it that way.

## Reporting

When you submit a finding to a program:

- Include the scenario hypothesis, the transition you performed, and the
  diff output that supports the finding.
- State the time deltas (immediately / 5m / 1h / 24h) clearly.
- Follow the program's preferred channel and disclosure policy. Do **not**
  publish details before the program agrees.

## Authority

This document is project policy. If a program's policy is stricter than this
document, the **program's policy wins**. SIL is a tool; the operator is
accountable for staying inside legal and authorized use.
