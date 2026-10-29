"""Integration tests: real Git and Betterleaks, isolated config, synthetic data.

Breaks caught: wrong index/worktree selection, lost whole-file context, bypassed
policy, leaked output, dropped Git hook events, and silently accepted failures.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import tempfile
import unittest


PROFILE = Path(__file__).resolve().parent
GUARD = PROFILE / "guard"
GIT = os.environ.get("TEST_GIT", "/opt/homebrew/bin/git")
TOKEN = "ghp_" + hashlib.sha256(b"secret-guard-synthetic-fixture").hexdigest()[:36]
OTHER = "unmatched-adjacent-value-" + hashlib.sha256(b"do-not-print").hexdigest()


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="test-", dir=PROFILE)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = os.environ.copy()
        for key in tuple(self.env):
            if key.startswith(("GIT_", "BETTERLEAKS_", "GITLEAKS_")):
                del self.env[key]
        self.env.update({
            "GIT_CONFIG_GLOBAL": str(self.root / "global.gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": ":",
            "TMPDIR": str(self.root),
        })
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Secret Guard Test")
        self.run_git("config", "user.email", "secret-guard-test@example.invalid")
        self.run_git("config", "commit.gpgsign", "false")
        self.register("secret-guard-index", "index", "pre-commit", "pre-merge-commit")
        self.register("secret-guard-commit", "commit", "commit-msg")

    def run_git(self, *args, expected=0, cwd=None, input=None):
        result = subprocess.run([GIT, *args], cwd=cwd or self.repo, env=self.env,
                                input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stderr.decode(errors="replace"))
        return result

    def register(self, name, mode, *events, profile=PROFILE, options=()):
        command = shlex.join([sys.executable, "-I", str(profile / "guard"), *options, mode])
        self.run_git("config", "--global", f"hook.{name}.command", command)
        for event in events:
            self.run_git("config", "--global", "--add", f"hook.{name}.event", event)

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def commit(self, *extra, message="synthetic test", cwd=None):
        return self.run_git("commit", "-s", "--trailer", "Assisted-By: GPT-6.1 Sol", "-m", message, *extra, expected=None, cwd=cwd)

    def head(self):
        return self.run_git("rev-parse", "--verify", "HEAD", expected=None).stdout

    def assert_blocked(self, result, previous=b""):
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, "secret-containing commit unexpectedly succeeded")
        self.assertIn(b"secret-guard:", output, output.decode(errors="replace"))
        self.assertNotIn(TOKEN.encode(), output, "hook output disclosed the synthetic token")
        self.assertNotIn(OTHER.encode(), output, "hook output disclosed adjacent context")
        self.assertEqual(self.head(), previous, "blocked commit changed HEAD")

    def clean_base(self):
        self.write("README.md", "Clean starting point.\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return self.head()

    def fixture_commit(self, message="unhooked synthetic fixture"):
        # Only for constructing unsafe synthetic history to exercise the push gate.
        env = self.env.copy()
        env["GIT_CONFIG_GLOBAL"] = str(self.root / "fixture-only.gitconfig")
        result = subprocess.run([GIT, "commit", "-s", "--trailer", "Assisted-By: GPT-6.1 Sol", "-m", message], cwd=self.repo,
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, "could not construct synthetic history")


class GuardTests(GitFixture):

    def test_clean_first_commit(self):
        self.clean_base()

    def test_guard_test_source_can_be_committed(self):
        self.write("test_guard.py", (PROFILE / "test_guard.py").read_text())
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_staged_token_blocks_without_printing_context(self):
        self.write("config.yaml", f"notes: {OTHER}\ncredential: {TOKEN}\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_clean_worktree_cannot_hide_staged_secret(self):
        previous = self.clean_base()
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.write("config.yaml", "credential: ${API_TOKEN}\n")
        self.assert_blocked(self.commit(), previous)

    def test_unstaged_secret_does_not_block_clean_index(self):
        self.clean_base()
        self.write("config.yaml", "credential: ${API_TOKEN}\n")
        self.run_git("add", ".")
        self.write("config.yaml", f"credential: {TOKEN}\n")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertNotIn(TOKEN.encode(), self.run_git("show", "HEAD:config.yaml").stdout)

    def test_commit_all_scans_git_temporary_index(self):
        previous = self.clean_base()
        self.write("README.md", f"credential: {TOKEN}\n")
        self.assert_blocked(self.commit("-a"), previous)

    def test_explicit_path_commit_scans_only_its_temporary_index(self):
        self.clean_base()
        self.write("README.md", "Clean update.\n")
        self.write("other.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", "other.yaml")
        result = self.commit("--", "README.md")
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertNotIn(b"other.yaml", self.run_git("ls-tree", "--name-only", "HEAD").stdout)

    def test_explicit_path_secret_is_blocked(self):
        previous = self.clean_base()
        self.write("README.md", f"credential: {TOKEN}\n")
        self.assert_blocked(self.commit("--", "README.md"), previous)

    def test_amend_secret_is_blocked(self):
        previous = self.clean_base()
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit("--amend"), previous)

    def test_commit_message_secret_is_blocked(self):
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit(message="Accidental paste " + TOKEN))

    def test_literal_scissors_marker_does_not_hide_committed_secret(self):
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        message = "Subject\n\n# ------------------------ >8 ------------------------\n" + TOKEN
        self.assert_blocked(self.commit("--cleanup=verbatim", message=message))

    def test_existing_formatter_cannot_stage_a_secret_after_early_scan(self):
        previous = self.clean_base()
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nprintf '%s\\n' '" + TOKEN + "' > generated.yaml\ngit add generated.yaml\n")
        hook.chmod(0o700)
        self.write("README.md", "Clean update.\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit(), previous)

    def test_existing_hook_still_runs_on_clean_commit(self):
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nprintf 'ran' > hook-ran\n")
        hook.chmod(0o700)
        self.clean_base()
        self.assertEqual((self.repo / "hook-ran").read_text(), "ran")

    def test_policy_and_ignore_files_in_repo_cannot_disable_detection(self):
        self.write(".betterleaks.toml", "title='untrusted empty policy'\n")
        self.write(".gitleaks.toml", "title='another empty policy'\n")
        self.write(".betterleaksignore", "config.yaml:github-pat:1\n")
        self.write("config.yaml", f"credential: {TOKEN} # betterleaks:allow\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_token_with_unusual_filename_is_blocked(self):
        self.write("sub dir/-é\nquoted\".yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit(cwd=self.repo / "sub dir"))

    def test_symlink_target_is_not_followed(self):
        outside = self.root / "outside.yaml"
        outside.write_text(f"credential: {TOKEN}\n")
        (self.repo / "link.yaml").symlink_to(outside)
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_deletion_does_not_scan_removed_content(self):
        previous = self.clean_base()
        self.write("old.yaml", "temporary: ordinary-data\n")
        self.run_git("add", ".")
        self.assertEqual(self.commit().returncode, 0)
        self.run_git("rm", "old.yaml")
        self.assertEqual(self.commit().returncode, 0)
        self.assertNotEqual(self.head(), previous)

    def test_whole_file_context_catches_value_only_kubernetes_change(self):
        self.clean_base()
        self.write("secret.yaml", "apiVersion: v1\nkind: Secret\ndata:\n  value: \"\"\n")
        self.run_git("add", ".")
        self.assertEqual(self.commit().returncode, 0)
        previous = self.head()
        encoded = base64.b64encode(b"plain-service-password-42").decode()
        self.write("secret.yaml", f"apiVersion: v1\nkind: Secret\ndata:\n  value: {encoded}\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit(), previous)

    def test_base64_encoded_token_is_blocked(self):
        encoded = base64.b64encode(TOKEN.encode()).decode()
        self.write("encoded.txt", encoded + "\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_plain_service_password_is_blocked(self):
        self.write("service.yaml", "username: operator\npassword: believable-password-42\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_missing_scanner_fails_closed(self):
        options = ("--scanner", str(self.root / "missing-scanner"))
        self.run_git("config", "--global", "--remove-section", "hook.secret-guard-index")
        self.register("secret-guard-index", "index", "pre-commit", options=options)
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_missing_policy_fails_closed(self):
        profile = self.root / "broken-profile"
        profile.mkdir()
        if GUARD.exists():
            (profile / "guard").write_bytes(GUARD.read_bytes())
        self.run_git("config", "--global", "--remove-section", "hook.secret-guard-index")
        self.register("secret-guard-index", "index", "pre-commit", profile=profile)
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_short_env_password_is_blocked(self):
        self.write(".env", "DB_PASS=5937\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_short_password_in_named_secrets_file_is_blocked(self):
        self.write("secrets.yaml", "db_password: '5937'\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_stringdata_non_password_key_is_blocked(self):
        self.write("secret.yaml", "apiVersion: v1\nkind: Secret\nstringData:\n  access: '5937'\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_stringdata_plaintext_after_encrypted_value_is_blocked(self):
        self.write("secret.yaml", "kind: Secret\nstringData:\n  protected: ENC[AES256_GCM,data:ZmFrZQ==]\n  access: '5937'\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_encrypted_and_template_references_are_allowed(self):
        self.write(".env", "DB_PASSWORD=${DB_PASSWORD}\nPORT=8080\n")
        self.write("service.yaml", "password: ENC[AES256_GCM,data:ZmFrZQ==,iv:ZmFrZQ==,tag:ZmFrZQ==,type:str]\n")
        self.write("secrets.yaml", "db_password: !secret database_password\n")
        self.write("secret.yaml", "kind: Secret\nstringData:\n  access: ENC[AES256_GCM,data:ZmFrZQ==]\n  token: '${API_TOKEN}'\n")
        self.write("vault.txt", "$ANSIBLE_VAULT;1.1;AES256\n" + "616263646566" * 12 + "\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_private_key_header_is_blocked(self):
        key = "-----BEGIN " + "RSA PRIVATE KEY-----\n"
        self.write("private.pem", key + base64.b64encode(b"synthetic-not-a-valid-key" * 8).decode() + "\n-----END RSA PRIVATE KEY-----\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_credential_url_is_blocked(self):
        # Assemble the synthetic URI so the test source itself is safe to commit.
        self.write("service.conf", "dsn=postgresql:" + "//operator:plausible-secret-937@db.internal/service\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_type_change_to_symlink_with_secret_link_text_is_blocked(self):
        self.write("link.yaml", "Clean initial content.\n")
        self.run_git("add", ".")
        self.assertEqual(self.commit().returncode, 0)
        previous = self.head()
        (self.repo / "link.yaml").unlink()
        (self.repo / "link.yaml").symlink_to(TOKEN)
        self.run_git("add", ".")
        self.assert_blocked(self.commit(), previous)

    def test_worktree_secret_is_blocked(self):
        self.clean_base()
        worktree = self.root / "worktree"
        self.run_git("worktree", "add", "--detach", str(worktree), "HEAD")
        (worktree / "config.yaml").write_text(f"credential: {TOKEN}\n")
        self.run_git("add", ".", cwd=worktree)
        result = self.commit(cwd=worktree)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"secret-guard:", result.stderr)
        self.assertNotIn(TOKEN.encode(), result.stdout + result.stderr)

    def test_missing_template_fails_closed(self):
        profile = self.root / "missing-template"
        profile.mkdir()
        for name in ("guard", "policy.toml"):
            if (PROFILE / name).exists():
                (profile / name).write_bytes((PROFILE / name).read_bytes())
        self.run_git("config", "--global", "--remove-section", "hook.secret-guard-index")
        self.register("secret-guard-index", "index", "pre-commit", profile=profile)
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def fake_scanner(self, version, code):
        path = self.root / "fake-scanner"
        path.write_text("#!/bin/sh\nif [ \"$1\" = --version ]; then\n  printf '%s\\n' 'betterleaks version " + version + "'\nelse\n  printf '%s\\n' '" + TOKEN + "' >&2\n  exit " + str(code) + "\nfi\n")
        path.chmod(0o700)
        self.run_git("config", "--global", "--remove-section", "hook.secret-guard-index")
        self.register("secret-guard-index", "index", "pre-commit", options=("--scanner", str(path)))

    def test_unsupported_major_version_fails_closed(self):
        self.fake_scanner("2.0.0", 0)
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_scanner_error_fails_closed_without_replaying_diagnostics(self):
        self.fake_scanner("1.9.0", 126)
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_invalid_central_policy_fails_closed(self):
        profile = self.root / "invalid-policy"
        profile.mkdir()
        for name in ("guard", "findings.tmpl"):
            if (PROFILE / name).exists():
                (profile / name).write_bytes((PROFILE / name).read_bytes())
        (profile / "policy.toml").write_text("not valid TOML !!!\n")
        self.run_git("config", "--global", "--remove-section", "hook.secret-guard-index")
        self.register("secret-guard-index", "index", "pre-commit", profile=profile)
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_short_base64_kubernetes_value_is_blocked(self):
        self.write("secret.yaml", "kind: Secret\ndata:\n  access: NTkzNw==\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_noncredential_env_names_are_not_password_suffix_matches(self):
        self.write(".env", "COMPASS=5937\nPORT=8080\nBYPASS=0\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_stringdata_blank_line_cannot_hide_later_literal(self):
        self.write("secret.yaml", "kind: Secret\nstringData:\n  protected: '${API_TOKEN}'\n\n  access: '5937'\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_automatic_merge_with_secret_is_blocked_by_premerge_event(self):
        previous = self.clean_base()
        branch = self.run_git("branch", "--show-current").stdout.strip().decode()
        self.run_git("checkout", "-q", "-b", "feature")
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        self.run_git("checkout", "-q", branch)
        self.run_git("config", "--global", "--remove-section", "hook.secret-guard-commit")
        result = self.run_git("merge", "--no-ff", "-m", "synthetic merge", "feature", expected=None)
        self.assert_blocked(result, previous)

    def test_sha256_first_commit_is_scanned(self):
        self.repo = self.root / "sha256"
        self.repo.mkdir()
        self.run_git("init", "-q", "--object-format=sha256")
        self.run_git("config", "user.name", "Secret Guard Test")
        self.run_git("config", "user.email", "secret-guard-test@example.invalid")
        self.run_git("config", "commit.gpgsign", "false")
        self.clean_base()
        previous = self.head()
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit(), previous)

    def test_checkout_and_textconv_filters_are_not_executed(self):
        driver = self.root / "unsafe-driver"
        driver.write_text("#!/bin/sh\nprintf '%s\\n' '" + TOKEN + "'\nprintf 'ran' > '" + str(self.root / "driver-ran") + "'\n")
        driver.chmod(0o700)
        self.write(".gitattributes", "*.enc filter=decrypt diff=decrypt\n")
        self.run_git("config", "filter.decrypt.clean", "cat")
        self.run_git("config", "filter.decrypt.smudge", str(driver))
        self.run_git("config", "diff.decrypt.textconv", str(driver))
        self.write("archive.enc", "Opaque encrypted contents.\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertFalse((self.root / "driver-ran").exists(), "raw snapshot executed a checkout/textconv filter")

    def test_gitlink_is_not_treated_as_a_blob(self):
        self.clean_base()
        oid = self.head().strip().decode()
        self.run_git("update-index", "--add", "--cacheinfo", "160000," + oid + ",submodule")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_case_colliding_paths_are_not_silently_overwritten(self):
        probe = self.root / "CaseProbe"
        probe.write_text("probe")
        folds_case = (self.root / "caseprobe").exists()
        oid = self.run_git("hash-object", "-w", "--stdin", input=b"Clean data.\n").stdout.strip().decode()
        for path in ("Case.yaml", "case.yaml"):
            self.run_git("update-index", "--add", "--cacheinfo", "100644," + oid + "," + path)
        result = self.commit()
        if folds_case:
            self.assert_blocked(result)
        else:
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_missing_blob_cannot_produce_an_empty_successful_scan(self):
        missing = "1" * 40
        self.run_git("update-index", "--add", "--cacheinfo", "100644," + missing + ",missing.yaml")
        result = subprocess.run([sys.executable, str(GUARD), "index"], cwd=self.repo,
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"secret-guard:", result.stderr)

    def test_internal_scanner_timeout_cannot_silently_approve(self):
        scanner = self.root / "timeout-scanner"
        scanner.write_text("#!/bin/sh\nif [ \"$1\" = --version ]; then\n echo 'betterleaks version 1.9.0'; exit 0\nfi\nfor arg do\n [ \"$arg\" != --timeout ] || exit 0\ndone\nprintf '%s\\n' 'synthetic-rule \"repo/config.yaml\":1'\nexit 3\n")
        scanner.chmod(0o700)
        self.run_git("config", "--global", "--remove-section", "hook.secret-guard-index")
        self.register("secret-guard-index", "index", "pre-commit", options=("--scanner", str(scanner)))
        self.run_git("config", "--global", "hook.secret-guard-commit.command",
                     shlex.join([sys.executable, str(GUARD), "--scanner", str(scanner), "commit"]))
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_external_watchdog_aborts_a_hung_scanner(self):
        scanner = self.root / "hung-scanner"
        scanner.write_text("#!/bin/sh\nsleep 0.2\nexit 0\n")
        scanner.chmod(0o700)
        snapshot = self.root / "watchdog-snapshot"
        snapshot.mkdir()
        module = runpy.run_path(str(GUARD), run_name="guard_test")
        module["scan"].__globals__["TIMEOUT"] = 0.02
        with self.assertRaises(subprocess.TimeoutExpired):
            module["scan"](snapshot, str(scanner))

    def test_replace_ref_cannot_hide_a_staged_blob(self):
        previous = self.clean_base()
        unsafe = self.run_git("hash-object", "-w", "--stdin", input=(TOKEN + "\n").encode()).stdout.strip().decode()
        clean = self.run_git("hash-object", "-w", "--stdin", input=b"Clean replacement.\n").stdout.strip().decode()
        self.run_git("update-index", "--add", "--cacheinfo", "100644," + unsafe + ",config.yaml")
        self.run_git("replace", unsafe, clean)
        self.assert_blocked(self.commit(), previous)

    def test_partial_clone_inspection_never_fetches_missing_blobs(self):
        self.clean_base()
        self.write("historical.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        unsafe = self.run_git("rev-parse", "HEAD:historical.yaml").stdout.strip()
        self.run_git("rm", "historical.yaml")
        self.fixture_commit()
        server = self.root / "promisor.git"
        client = self.root / "partial"
        self.run_git("clone", "-q", "--bare", str(self.repo), str(server))
        self.run_git("--git-dir", str(server), "config", "uploadpack.allowFilter", "true")
        self.run_git("clone", "-q", "--filter=blob:none", "--no-checkout", server.as_uri(), str(client))
        env = {**self.env, "GIT_NO_LAZY_FETCH": "1"}
        before = subprocess.run([GIT, "cat-file", "-e", unsafe.decode()], cwd=client, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(before.returncode, 0, "fixture unexpectedly downloaded historical blobs")
        trace = self.root / "fetch-trace.jsonl"
        env = {**self.env, "GIT_TRACE2_EVENT": str(trace)}
        oid = self.run_git("rev-parse", "HEAD").stdout.strip()
        record = b"refs/heads/main " + oid + b" refs/heads/main " + b"0" * 40 + b"\n"
        result = subprocess.run([sys.executable, str(GUARD), "push", "origin", "local-test"],
                                cwd=client, env=env, input=record,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        self.assertFalse(any(e.get("event") == "cmd_name" and e.get("name") == "fetch" for e in events),
                         "guard performed a promisor fetch during inspection")
        self.assertNotEqual(result.returncode, 0, "unreadable historical blobs did not fail closed")
        self.assertNotIn(TOKEN.encode(), result.stdout + result.stderr)

    def test_binary_magic_at_start_of_message_cannot_hide_token(self):
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit(message="MZ\nAccidental paste " + TOKEN))

    def test_scanner_warning_cannot_approve_an_unreadable_archive(self):
        self.write("broken.zip", "Not really an archive.\n" + TOKEN + "\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_scanner_nested_temporary_files_are_cleaned_with_snapshot(self):
        record = self.root / "scanner-tmpdir"
        scanner = self.root / "temp-scanner"
        scanner.write_text("#!/bin/sh\nif [ \"$1\" = --version ]; then\n echo 'betterleaks version 1.9.0'; exit 0\nfi\nprintf '%s' \"$TMPDIR\" > " + shlex.quote(str(record)) + "\nprintf 'synthetic temp data' > \"$TMPDIR/nested-archive-copy\"\n")
        scanner.chmod(0o700)
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        result = subprocess.run([sys.executable, str(GUARD), "--scanner", str(scanner), "index"],
                                cwd=self.repo, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0)
        child_temp = Path(record.read_text()) / "nested-archive-copy"
        self.assertFalse(child_temp.exists(), "scanner left a nested archive copy outside snapshot cleanup")

    def test_entrypoint_ignores_untrusted_pythonpath(self):
        modules = self.root / "untrusted-modules"
        modules.mkdir()
        (modules / "subprocess.py").write_text("raise SystemExit(0)\n")
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        result = subprocess.run([str(GUARD), "index"], cwd=self.repo,
                                env={**self.env, "PYTHONPATH": str(modules)},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0, "PYTHONPATH bypassed the installed entrypoint")
        self.assertIn(b"potential secrets", result.stderr)
        self.assertNotIn(TOKEN.encode(), result.stdout + result.stderr)

    def test_example_placeholders_are_allowed_only_in_named_examples(self):
        for suffix in ("example", "sample", "template"):
            self.write(".env." + suffix, "DB_PASSWORD=changeme\nAPI_TOKEN=your-token-here\nSECRET_KEY=replace-me\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_live_env_still_blocks_placeholder_literals(self):
        self.write(".env", "DB_PASSWORD=changeme\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_example_still_blocks_real_token(self):
        self.write(".env.example", f"API_TOKEN={TOKEN}\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_example_does_not_exempt_real_default_passwords(self):
        self.write(".env.example", "POSTGRES_PASSWORD=postgres\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_noncredential_env_settings_and_file_references_are_allowed(self):
        self.write(".env", "PASSWORD_MIN_LENGTH=12\nTOKEN_TTL=3600\nOIDC_TOKEN_URL=https://idp.internal/token\nPASS_THROUGH=1\nPOSTGRES_PASSWORD_FILE=/run/secrets/db_password\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_crlf_env_short_password_is_blocked(self):
        self.write(".env", "DB_PASS=5937\r\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_crlf_kubernetes_secret_is_blocked(self):
        self.write("secret.yaml", "kind: Secret\r\nstringData:\r\n  access: '5937'\r\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_list_item_kubernetes_secret_is_blocked(self):
        self.write("secret.yaml", "- kind: Secret\n  stringData:\n    access: '5937'\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_kubernetes_data_header_comment_does_not_hide_literal(self):
        self.write("secret.yaml", "kind: Secret\ndata:  # short encoded credential\n  access: NTkzNw==\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_configmap_in_another_document_is_not_a_secret(self):
        self.write("combined.yaml", "kind: Secret\nstringData:\n  access: '${API_TOKEN}'\n---\nkind: ConfigMap\ndata:\n  greeting: hello-world\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_configmap_in_another_list_item_is_not_a_secret(self):
        self.write("list.yaml", "kind: List\nitems:\n- apiVersion: v1\n  kind: Secret\n  stringData:\n    access: '${API_TOKEN}'\n- apiVersion: v1\n  kind: ConfigMap\n  data:\n    greeting: hello-world\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_helm_control_lines_are_not_literal_secret_values(self):
        self.write("secret.yaml", "kind: Secret\ndata:\n  {{- if .Values.enabled }}\n  access: {{ .Values.access | b64enc }}\n  {{- end }}\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_list_secret_sibling_metadata_is_not_part_of_data(self):
        self.write("list.yaml", "- apiVersion: v1\n  data:\n    access: '${API_TOKEN}'\n  kind: Secret\n  metadata:\n    name: service-key\n")
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))


class BpiArchiveFalsePositiveTests(GitFixture):
    """Reviewed noncredentials: exact values AND exact paths, never file exemptions."""
    PIN_PATH = "research/orchestration/stock_forced10.py"
    CERT_PATH = "evidence/key/orchestration/peer-restart/post-failure-readonly/result.json"
    CONTENT_SHA256 = "fab68c5bea1d77e081a31e534b729dc7df1b85e840e284922267b7d2617ff332"
    PUBLIC_CERT_FINGERPRINT = "26cec8782c11c638fed1afe92844648534e0b83c"
    SYNTHETIC_OTHER = hashlib.sha256(b"inert exception-boundary regression not a credential").hexdigest()

    def pin_source(self, value):
        return "PINS = {'native-upload-api-check.json': '" + value + "'}\n"

    def certificate_log(self, value):
        return json.dumps({"stdout": "Loaded X.509 cert 'Fedora kernel signing key: " + value + "'"}) + "\n"

    def test_exact_artifact_hash_at_pin_path_allowed(self):
        self.write(self.PIN_PATH, self.pin_source(self.CONTENT_SHA256))
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_unlisted_hash_at_pin_path_blocked(self):
        self.write(self.PIN_PATH, self.pin_source(self.SYNTHETIC_OTHER))
        self.run_git("add", ".")
        result = self.commit()
        self.assert_blocked(result)
        self.assertNotIn(self.SYNTHETIC_OTHER.encode(), result.stdout + result.stderr)

    def test_exact_pin_at_other_path_blocked(self):
        self.write("other.py", self.pin_source(self.CONTENT_SHA256))
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_exact_public_certificate_at_log_path_allowed(self):
        self.write(self.CERT_PATH, self.certificate_log(self.PUBLIC_CERT_FINGERPRINT))
        self.run_git("add", ".")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_unlisted_fingerprint_at_log_path_blocked(self):
        self.write(self.CERT_PATH, self.certificate_log(self.SYNTHETIC_OTHER[:40]))
        self.run_git("add", ".")
        result = self.commit()
        self.assert_blocked(result)
        self.assertNotIn(self.SYNTHETIC_OTHER[:40].encode(), result.stdout + result.stderr)

    def test_exact_public_fingerprint_at_other_path_blocked(self):
        self.write("other.json", self.certificate_log(self.PUBLIC_CERT_FINGERPRINT))
        self.run_git("add", ".")
        self.assert_blocked(self.commit())

    def test_added_synthetic_credential_in_allowed_file_blocked(self):
        self.write(self.PIN_PATH, self.pin_source(self.CONTENT_SHA256) + "credential = '" + TOKEN + "'\n")
        self.run_git("add", ".")
        self.assert_blocked(self.commit())


class PushTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.remote = self.root / "remote.git"
        self.run_git("init", "-q", "--bare", str(self.remote))
        self.run_git("remote", "add", "origin", str(self.remote))
        command = shlex.join([sys.executable, str(GUARD), "push"])
        self.run_git("config", "hook.secret-guard-push.command", command)
        self.run_git("config", "hook.secret-guard-push.event", "pre-push")

    def push(self, *refs):
        return self.run_git("push", "origin", *(refs or ("HEAD:refs/heads/main",)), expected=None)

    def remote_tip(self, ref="refs/heads/main"):
        return self.run_git("--git-dir", str(self.remote), "rev-parse", "--verify", ref, expected=None).stdout

    def assert_push_blocked(self, result, previous=b"", ref="refs/heads/main", finding=True):
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, "unsafe push unexpectedly succeeded")
        self.assertIn(b"secret-guard:", output)
        if finding:
            self.assertIn(b"potential secrets", output, "push failed for a reason other than detecting the fixture")
        self.assertNotIn(TOKEN.encode(), output)
        self.assertNotIn(OTHER.encode(), output)
        self.assertEqual(self.remote_tip(ref), previous, "blocked push updated the remote")

    def test_push_clean_new_branch(self):
        self.clean_base()
        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(self.remote_tip().strip(), self.head().strip())

    def test_push_intermediate_secret_removed_at_tip_is_blocked(self):
        self.clean_base()
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        self.write("config.yaml", "credential: ${API_TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        self.assert_push_blocked(self.push())

    def test_push_stored_commit_message_secret_is_blocked(self):
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.fixture_commit(message="Accidental message " + TOKEN)
        self.assert_push_blocked(self.push())

    def test_push_stored_message_scissors_does_not_hide_secret(self):
        self.write("README.md", "Clean file.\n")
        self.run_git("add", ".")
        self.fixture_commit(message="Subject\n\n# ------------------------ >8 ------------------------\n" + TOKEN)
        self.assert_push_blocked(self.push())

    def test_push_checks_all_updated_refs(self):
        self.clean_base()
        self.run_git("branch", "safe")
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        self.assert_push_blocked(self.push("safe:refs/heads/safe", "HEAD:refs/heads/main"))
        self.assertEqual(self.remote_tip("refs/heads/safe"), b"")

    def test_push_does_not_trust_another_remotes_tracking_ref(self):
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        self.run_git("update-ref", "refs/remotes/private/main", "HEAD")
        self.assert_push_blocked(self.push())

    def test_push_update_scans_new_commits(self):
        self.clean_base()
        self.assertEqual(self.push().returncode, 0)
        previous = self.remote_tip()
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        self.assert_push_blocked(self.push(), previous)

    def test_push_force_update_scans_rewritten_commits(self):
        self.clean_base()
        self.assertEqual(self.push().returncode, 0)
        previous = self.remote_tip()
        self.run_git("checkout", "-q", "--orphan", "rewritten")
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        self.assert_push_blocked(self.push("+HEAD:refs/heads/main"), previous)

    def test_push_deletion_is_allowed(self):
        self.clean_base()
        self.assertEqual(self.push().returncode, 0)
        result = self.push(":refs/heads/main")
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(self.remote_tip(), b"")

    def test_push_annotated_tag_message_is_scanned(self):
        self.clean_base()
        self.run_git("-c", "tag.gpgsign=false", "tag", "-a", "release", "-m", "Accidental tag " + TOKEN)
        self.assert_push_blocked(self.push("refs/tags/release"), ref="refs/tags/release")

    def test_push_clean_lightweight_tag_is_allowed(self):
        self.clean_base()
        self.run_git("tag", "release")
        result = self.push("refs/tags/release")
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_push_blob_tag_fails_closed(self):
        self.clean_base()
        blob = self.run_git("hash-object", "-w", "--stdin", input=b"not a commit\n").stdout.strip().decode()
        self.run_git("tag", "blob-tag", blob)
        self.assert_push_blocked(self.push("refs/tags/blob-tag"), ref="refs/tags/blob-tag", finding=False)

    def test_push_merge_resolution_is_scanned(self):
        self.clean_base()
        branch = self.run_git("branch", "--show-current").stdout.strip().decode()
        self.run_git("checkout", "-q", "-b", "feature")
        self.write("feature.txt", "Clean feature.\n")
        self.run_git("add", ".")
        self.assertEqual(self.commit().returncode, 0)
        self.run_git("checkout", "-q", branch)
        self.run_git("merge", "--no-ff", "--no-commit", "feature")
        self.write("merge.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        self.assert_push_blocked(self.push())

    def test_push_replace_graft_cannot_hide_intermediate_history(self):
        base = self.clean_base().strip().decode()
        self.write("config.yaml", f"credential: {TOKEN}\n")
        self.run_git("add", ".")
        self.fixture_commit()
        self.run_git("rm", "config.yaml")
        self.fixture_commit()
        self.run_git("replace", "--graft", "HEAD", base)
        self.assert_push_blocked(self.push())

    def test_push_accepts_source_revision_expressions_with_spaces(self):
        self.clean_base()
        result = self.push("HEAD^{/synthetic test}:refs/heads/main")
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
