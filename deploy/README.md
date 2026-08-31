# Restricted Padval deployment

Production releases use one immutable `linux/amd64` image digest from
`ghcr.io/rserag/bloti-bot`. GitHub Actions can reach only a forced SSH command; it does not receive
a shell, Docker membership, application credentials, or general sudo access.

## Host layout

- `/opt/blotibot/compose.yml`: root-owned production Compose definition
- `/opt/blotibot/secrets/`: root-only directory containing three UID/GID 1000, mode-0600 files
- `/opt/blotibot/state/`: current and previous release records
- `/opt/blotibot/releases/`: immutable release records
- `/usr/local/sbin/blotibot-deploy`: root-owned validator and deployment controller
- `/usr/local/sbin/blotibot-deploy-ssh`: forced SSH entry point

Release records contain only a Git revision and an image digest. Telegram credentials remain only
on Padval and are never sent to GitHub.

## Release behavior

The controller validates the revision, GHCR repository, digest format, secret ownership, and secret
file modes. It serializes deployments, pulls only the exact image, waits for the container health
check, confirms the configured digest, and verifies that the restart count remains stable.

If a candidate fails, the controller restores the previous immutable release. During the first
rollout it can restore the existing `/home/c/blotibot` Compose stack instead. The original stack and
image must remain available until the migration is accepted and its retirement is separately
authorized.

An interactive Telegram command is still required for final end-to-end verification because a
healthy connection heartbeat cannot prove command permissions and responses.
