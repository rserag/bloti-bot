# Security policy

## Supported versions

Only the latest revision on the default branch is supported. Older commits, development branches,
and unofficial container images do not receive security fixes.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability and do not include credentials, Telegram
session data, private chat content, or personal information in any report.

Use [GitHub private vulnerability reporting](https://github.com/rserag/bloti-bot/security/advisories/new).
Include the affected revision, impact, reproduction steps, and any suggested mitigation. Use test
credentials and redact logs before attaching them.

The maintainer aims to acknowledge a report within two business days and provide an initial
assessment within seven days. Disclosure timing will be coordinated with the reporter after a fix
or mitigation is available.

## Deployment secrets

Production credentials belong only on the deployment host in protected secret files. This project
will never request real Telegram credentials in an issue, pull request, test fixture, workflow log,
or container image.
