# Repository guidance

This is the public, sanitized server-edition source. Read README.md and docs before deployment.

- Preserve user files, local edits, credentials, VPN/proxy settings and other services. Any requested file deletion must move the exact file to Trash; never purge or recursively delete.
- Do not run deployment/reference scripts as a batch. They preserve historical steps, not a current turnkey installer.
- Do not export this machine's personal Skills or snapshot into this public repository. Production snapshot synchronization requires a separate verified PRIVATE repository.
- Never read or print Apple credentials, raw network secrets, SSH private keys or account configuration dumps. Use placeholders in public examples.
- Keep the published behavior within the verified server architecture. State clearly when a change has only synthetic testing or needs new deployment acceptance.
- For actual Cloud iCloud tasks, read .agents/skills/icloud-codex-gateway/SKILL.md and the installed root guidance. Repository maintenance itself stays in this checkout.
- In a configured, bound iCloud workspace, every task that creates, edits or generates files includes automatic writeback to those task destinations. Do not require a separate “save/write back” phrase or confirmation. The agent enrolls exact task paths, validates generated outputs before release, and waits for verified completion. Explicit no-save/local-only/no-edit requests override this default; pause the relevant queue first. Reading alone makes no changes. This does not authorize unrelated paths, overriding remote conflicts or deletions.
- Run focused tests for behavior changes. Before public release run Python tests, Go helper tests, secret scanning, privacy scanning and source/license checks.
