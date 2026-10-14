# Codex Cloud maintenance

The saved **Codex Cloud** environment is reusable. A setup conversation is a release workspace, not the only maintenance entry point. The repository is the durable source of the installation, startup guidance, client and recovery procedure. Never depend on a conversation ID to recover the configuration.

## Ordinary work and Skills updates

Use a normal task from **Codex Cloud**. Its root guidance runs `scripts/cloud_refresh.py`: bounded fetch, trusted origin, clean-tree/fast-forward checks, preserved previous versions, verified Skills and guidance-only discovery. An unchanged bootstrap does not rewrite its state or add another backup. Existing edits, bindings and active configuration remain protected.

Do not republish for each Skills snapshot or repository instruction change. Do not rerun the full test suite for a directory listing. Use a setup edit only for a change to the prepared tools, install/start fields, environment variables, network secrets or VPN configuration.

Read-only diagnostics:

```bash
cd /workspace/codex-portable
python3 scripts/cloud_doctor.py
python3 scripts/cloud_doctor.py --gateway
```

The first command checks snapshot/import hashes, root index ownership/metadata and managed guidance. It does not read user task contents or reveal credentials. `--gateway` additionally performs an authenticated read through the gateway. Neither check grants write authorization or proves cross-device propagation.

## Change the reusable environment

1. Open Settings → Codex Cloud → **Codex Cloud** → **Edit**. Keep the old environment and every prior setup chat. Do not use an already published setup chat as the execution workspace.
2. Before changing anything, verify the new setup's source version, real Linux terminal, repository HEAD, dirty files and retained backups. Read the current draft. Back up only its non-sensitive install/start fields to a unique directory under `/workspace/retained/cloud-maintenance/`; keep private values in their official vault/input controls.
3. Finish all configuration input while the setup is idle. Confirm the selected gateway hostname, saved credential binding and VPN configuration in the official UI. Do not generate/revoke credentials or change ACLs merely because a readiness observation is unknown.
4. Read the runtime/networking instructions. Run the existing `cloud_refresh.py` using the supported execution path, then `bash environment/install.sh` for changes requiring full preparation. For documentation/Skills-only changes, refresh and focused tests are sufficient. Verify the latest intended commit rather than fixing the number of Skills forever.
5. Run `python3 scripts/cloud_doctor.py --publication --dependencies`. This rejects an untrusted/dirty source or a real `work/icloud-active` task binding in the baseline. Review other prepared files too: this targeted guard is not a scan of every possible personal file. Keep backups; do not delete or move user files just to make a check pass.
6. Validate the gateway where possible with `cloud_doctor.py --gateway`. Compare the **saved draft** with the **selected executor's** non-sensitive policy. A saved VPN change can apply to future tasks while the existing executor still reports `vpn_configured:false`; those are distinct states. Record that limitation rather than repeatedly replacing keys.
7. When the checks/edits have finished and the conversation is idle, review and save the two fields below. Publish **once**. Do not send new commands or change fields during publication. A running publication is observed until an explicit result; do not start another attempt solely because a polling call timed out.
8. After the official UI says **Environment published**, stop executing in that setup chat. Create a normal task using **Codex Cloud** and issue an ordinary file request. Verify real WebDAV success, the expected default folder, current source version and effective VPN policy. Do not treat the publish badge alone as runtime acceptance. Keep that task and its evidence.

Install field (stable entry point; its first command exists in earlier published baselines):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /workspace/codex-portable
python3 scripts/cloud_refresh.py
bash environment/install.sh
```

Start field: use the complete text of `environment/start.md`. Detailed instructions remain in this repository and are refreshed with normal tasks. Do not substitute an untested script or save user files, bindings or credentials into the prepared baseline.

## Failure handling without losing work

- **Refresh cannot reach the proxy:** if classified `network-path-unavailable`, retry the identical bounded command once through the actual execution tool's normal approval route (`sandbox_permissions: require_escalated` only if that schema supports it). Keep `HTTP_PROXY`, `HTTPS_PROXY`, CA trust and placeholders unchanged. The script does not change approval policy itself. An unavailable runtime Skill is not permission to guess a path, fabricate a tool or scan `/`; use the actual supplied schema and report missing capabilities.
- **Auth, destination policy, local edits or hash conflict:** stop at that boundary, preserve all versions and diagnose the specific failure. Do not use force/reset or a broader execution path to bypass it.
- **Published setup cannot execute:** use the same saved environment's Edit flow for maintenance, and normal tasks for work. Do not delete the old VM/files or equate a stopped observer with a platform startup failure. This workflow avoids relying on the old setup; it does not prove every executor error has this cause.
- **Starting environment:** use one supported readiness wait, resume the same confirmed-live handle, and distinguish an observation timeout from a terminal platform result. A terminated or missing handle is not still running. Once the platform reports failure, stop the loop and retain the error and identifiers.
- **Publishing says settings changed/in use:** confirm no active command or publication is still running. Preserve the current draft/edits; reload and review the current saved revision through the official UI. Do not blindly keep clicking Retry or invoke hidden endpoints. If the error persists, preserve evidence and use the supported Edit/recovery workflow; support escalation needs the owner's authorization.
- **Saved settings were not published:** they may not be in the next task's source version. Compare draft/base/source version IDs and configuration presence. Copy no raw credential values through chat, logs or repository files; the owner supplies missing values in official controls.

## Credentials and recovery records

Keep Tailscale reusable enrollment keys in the owner's password manager and official VPN input. Record their expiry outside source credentials; replace an expiring key through an authorized official workflow, preserving existing devices and old keys until the replacement is verified. Keys are not permanent. Do not assume an already joined node's availability proves a future VM can enroll.

Apple login remains on ECS. Existing health notifications and the owner's phone SSH `icloud-reconnect` workflow handle reauthorization; no routine new Apple login is needed for a Cloud environment update. Never collect Apple passwords, 2FA, SSH private keys or raw gateway authorization in a chat.

For each release retain: the repository commit/snapshot ID, non-sensitive field backup, test/preflight results, official publication result, source configuration/version IDs and normal-task read verification. Track gateway writes and native-device propagation separately when those are in scope. Do not claim a fresh writeback test from a read-only check.

The phone directory-selection page is shared by compatible Cloud tasks. It does not migrate old chats or bind to one environment name; new tasks use its current selection, while old tasks keep their own binding. On the phone, select **Codex Cloud** when starting new work.

Official workflow reference: https://learn.chatgpt.com/docs/environments/cloud-environments
