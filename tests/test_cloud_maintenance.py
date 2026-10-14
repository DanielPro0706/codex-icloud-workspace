import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]


class MaintenanceTests(unittest.TestCase):
    def fixture(self):
        base = ROOT / 'work/maintenance-tests' / uuid.uuid4().hex
        repo = base / 'codex-portable'
        (repo / 'scripts').mkdir(parents=True)
        for name in ('cloud_bootstrap.py', 'cloud_root.py', 'portable_sync.py'):
            shutil.copy2(ROOT / 'scripts' / name, repo / 'scripts' / name)
        content = b'---\nname: sample\ndescription: Synthetic maintenance fixture.\n---\n'
        relative = '.agents/skills/sample/SKILL.md'
        source = repo / 'snapshot/files' / relative
        source.parent.mkdir(parents=True)
        source.write_bytes(content)
        (repo / 'snapshot/manifest.json').write_text(json.dumps({
            'id': 'synthetic', 'version': 1,
            'files': {relative: hashlib.sha256(content).hexdigest()},
        }))
        gateway = repo / '.agents/skills/icloud-codex-gateway/SKILL.md'
        gateway.parent.mkdir(parents=True)
        gateway.write_text('---\nname: icloud-codex-gateway\ndescription: Synthetic gateway.\n---\n')
        (base / 'AGENTS.md').write_text('Owner guidance remains.\n')
        self.bootstrap(base, repo)
        return base, repo

    def bootstrap(self, base, repo):
        result = subprocess.run([sys.executable, str(repo / 'scripts/cloud_bootstrap.py'),
                                 '--cloud-root', str(base)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def inventory(self, base):
        return {str(p.relative_to(base)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in base.rglob('*') if p.is_file()}

    def doctor(self, base, repo):
        spec = importlib.util.spec_from_file_location('maintenance_doctor', ROOT / 'scripts/cloud_doctor.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.inspect_workspace(repo, base)

    def test_unchanged_bootstrap_does_not_rewrite_state_or_create_backups(self):
        base, repo = self.fixture()
        before = self.inventory(base)
        result = self.bootstrap(base, repo)
        self.assertEqual(result['installed_files'], 0)
        self.assertEqual(self.inventory(base), before)

    def test_doctor_is_read_only_and_does_not_inspect_task_files(self):
        base, repo = self.fixture()
        private = repo / 'work/icloud-active/checkout/files/owner.txt'
        private.parent.mkdir(parents=True)
        private.write_text('PRIVATE_SENTINEL_NOT_IN_REPORT')
        before = self.inventory(base)
        report = self.doctor(base, repo)
        self.assertTrue(report['ok'], report)
        self.assertTrue(report['task_binding_present'])
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(report))
        self.assertEqual(self.inventory(base), before)

    def test_doctor_rejects_installed_skill_tampering_without_repair(self):
        base, repo = self.fixture()
        target = repo / '.agents/skills/sample/SKILL.md'
        target.write_text('OWNER_EDIT_MUST_REMAIN')
        before = self.inventory(base)
        report = self.doctor(base, repo)
        self.assertFalse(report['ok'])
        self.assertFalse(report['checks']['installed_snapshot_skills'])
        self.assertEqual(self.inventory(base), before)

    def test_doctor_rejects_unowned_index_and_guidance(self):
        base, repo = self.fixture()
        agents = base / 'AGENTS.md'
        agents.write_text(agents.read_text().replace('workspace.py activate', 'owner custom command'))
        report = self.doctor(base, repo)
        self.assertFalse(report['ok'])
        self.assertFalse(report['checks']['managed_guidance'])
        index = base / '.codex-portable-skills.json'
        index.write_text('{}')
        report = self.doctor(base, repo)
        self.assertFalse(report['checks']['skill_index'])

    def test_publication_gate_refuses_a_real_task_binding_without_touching_it(self):
        base, repo = self.fixture()
        shutil.copy2(ROOT / 'scripts/cloud_doctor.py', repo / 'scripts/cloud_doctor.py')
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        def git(*args):
            result = subprocess.run(['git', '-C', str(repo), *args], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        git('init')
        git('remote', 'add', 'origin', 'https://github.com/OWNER/PRIVATE-PORTABLE-REPO.git')
        git('add', 'scripts', 'snapshot', '.agents')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-m', 'Synthetic source')
        binding = repo / 'work/icloud-active/selection.json'
        binding.parent.mkdir(parents=True)
        binding.write_text('{"folder":"owner-work"}')
        before = self.inventory(base)
        result = subprocess.run([sys.executable, str(repo / 'scripts/cloud_doctor.py'),
                                 '--cloud-root', str(base), '--publication'],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['checks']['trusted_origin'])
        self.assertTrue(report['checks']['clean_tracked_source'])
        self.assertFalse(report['checks']['no_task_binding_in_baseline'])
        self.assertEqual(self.inventory(base), before)


if __name__ == '__main__':
    unittest.main()
