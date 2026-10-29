# Account-wide Git secret guard

Uses Betterleaks 1.9.x (or later stable 1.x), the existing Homebrew Python 3
standard library, and Git's native configured hooks (Git 2.54+). No daemon,
network credential validation, hook manager, or per-clone installation.

## Protection

`~/.gitconfig` registers:

- `hook.secret-guard-index` on `pre-commit` and `pre-merge-commit`.
- `hook.secret-guard-commit` on `commit-msg` (files rechecked plus message).

Repository hooks still run. The helper scans the **full raw staged contents of
changed files**, respecting partial staging, `-a`, explicit path commits, and
worktrees. It does not run clean/smudge/textconv filters or follow symlinks.
Gitlinks are pointers; commit inside the submodule to scan its contents.

Missing binaries, policy/template files, unreadable Git objects, snapshot
collisions, unsupported versions, reported scanner errors/warnings, and expiry
of the external 60-second scan watchdog block the operation. Betterleaks' own
timeout is deliberately not used: version 1.9 can incorrectly return success
when that internal timer expires. Git inspection ignores replace refs and
disables lazy fetching, so it sees stored objects without contacting remotes.
No diagnostic source lines or secret values are printed. Findings contain
only rule ID and quoted filename/line. Temporary copies are private and removed
on normal exit. Scanner archive temporaries are contained inside the same
snapshot. Abrupt termination can still leave private temporary files. Python
runs in isolated mode, ignoring PYTHONPATH and user-site startup hooks.

The policy extends upstream defaults without replacing their filters. Additional
rules cover short credential assignments in `.env*`/`secrets.yaml` and literal
Kubernetes Secret `data`/`stringData` blocks. Base64 is **not** encryption.
Encrypted envelopes and template references are allowed. Detection remains
heuristic: upstream file exclusions, arbitrary passwords, unusual YAML syntax,
binary/LFS content, and archive/decoding limits can leave gaps. In particular:

- Betterleaks silently skips some MIME types (including RTF and text with binary
  magic), UTF-16 text, archives without recognized extensions, and upstream
  excluded paths such as names containing `gitleaks.toml`.
- Upstream's global filter can suppress a value containing `false`. The upstream
  filter is retained rather than silently replaced by a local fork.
- Extra strict short-password coverage is scoped to `.env*` and `secrets.yaml`.
  Other filenames/keys, such as `stack.env`, `.envrc`, `vault.yml`, or passphrase
  fields, have upstream coverage only. Variable expressions with literal
  fallbacks may also escape heuristic detection.
- The Kubernetes addition supports tested block-style documents/list items,
  CRLF, header comments, and Helm control lines; it is not a complete YAML parser.

## Check installation and run tests

```sh
git hook list --show-scope pre-commit
git hook list --show-scope pre-merge-commit
git hook list --show-scope commit-msg
/Users/mko/.config/git/secret-guard/test.sh
```

Run the hook-list checks inside each coding agent's shell as well: an agent
that changes HOME/GIT_CONFIG_GLOBAL or uses another Git implementation may not
inherit the account hooks. A successful `hook list` can still list `disabled`
or `event-disabled` entries: check the output, not just its exit code. Behavioural
activation tests are the stronger check. No client-side hook is an enforcement boundary.
Rebase/cherry-pick/revert/patch application can skip ordinary commit hooks;
explicit hook disabling also bypasses them. Tag, note, and stash creation do
not run the commit hooks; the optional homelab push backstop covers pushed tags,
not notes or stash contents as general object types.

Tests use real Git/Betterleaks but only synthetic credentials, disposable repos,
isolated configuration, and local bare remotes. They do not read credential
stores or scan your repositories. Tests create signed-off synthetic commits
with an Assisted-By trailer, never commits in a real repository.

## A blocked commit

Remove the credential from the staged version, not just the working copy.
Prefer environment/secret-manager references or encrypted files. Real exposed
credentials must be revoked/rotated; deleting a file does not repair history.

An existing secret elsewhere in a changed file can block the commit because
whole files are scanned. The approved marker values `changeme`, `replace-me`,
`your-token-here`, and their narrowly recognized variants are allowed only in
`.env.example`, `.env.sample`, and `.env.template`; this is not a file exemption.
Live `.env` files and real-looking defaults such as `postgres` remain strict.
Noncredential settings (`TOKEN_TTL`, `PASSWORD_MIN_LENGTH`, `*_PASSWORD_FILE`)
are not treated as credential assignments. Other placeholders use upstream filters;
inline `gitleaks:allow`/`betterleaks:allow` and repository ignore/config files do
not weaken this guard. Add only reviewed, narrowly scoped **additive** policy
exceptions, with a positive and a negative test. Do not replace a built-in
rule's `filter` or the top-level `filter`/`prefilter`: that replaces upstream
false-positive handling rather than extending it.

The full message file is scanned. With verbose commits, deleted diff lines can
therefore trigger findings even when removing a secret. Retry with verbose
mode disabled rather than bypassing protection. The helper does not guess which
scissors sections your command-line cleanup flags would discard. Avoid staging
from another application while a commit editor is open; hooks cannot make
concurrent index editing transactional.

## Homelab push backstop

The optional local `hook.secret-guard-push` registration in
`/Users/mko/git/homelab/.git/config` runs `guard push` on `pre-push`.
Activation is gated on reviewing the history preflight; check its current
status with `git hook list --show-scope pre-push` inside homelab.

It reads every proposed update, scans all newly reachable commits' changed
raw files and stored commit messages, and checks annotated tag objects.
Intermediate secrets removed at the tip and merge-resolution secrets still
block. Only locally available **destination old tips** are excluded; tracking
refs on other remotes never grant an exemption. New refs or unavailable old
objects conservatively trigger full reachable history scans, which can be
slow or flag historical findings. Deletions introduce no content. Tags pointing
to non-commit objects fail closed and need manual review.

Use a full, non-shallow, non-partial homelab clone. Missing history/blob objects
fail closed without lazy network fetches. Large imports and full-history pushes
can be slow because export starts one Git process per changed blob. The 60-second
watchdog bounds the scanner, not total export time; a larger history may require
reviewed performance work instead of bypassing protection.

No history is rewritten and no baseline is automatically created. Enable
provider-side push protection where available; CI runs after upload and cannot
prevent the initial disclosure.

## Maintenance and rollback

Betterleaks was installed with Homebrew and pinned. An upgrade requires an
explicit unpin, reviewing CLI/config changes, rerunning `test.sh`, and re-pinning.
The helper rejects v2 instead of interpreting changed flags unsafely.
`guard --scanner /absolute/binary ...` is available for controlled upgrade tests;
installed hooks use the default `/opt/homebrew/bin/betterleaks`.

Before activation, the original Git configuration is backed up privately under
this directory's `backups/`. To roll back deliberately, disable/remove only the
named `secret-guard-index`, `secret-guard-commit`, and (if enabled) local
`secret-guard-push` settings. Leave all unrelated Git settings and repository
hooks intact. Do not overwrite the whole live config from an old backup if it
has since acquired other changes. Removing the helper while registrations are
active blocks operations rather than silently disabling protection.
