#!/usr/bin/env python3
"""Read-only integrity/prepublication checks. Never print credentials or task files."""
import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess

P = pathlib.Path
TRUSTED_ORIGINS = {
    'https://github.com/OWNER/PRIVATE-PORTABLE-REPO',
    'https://github.com/OWNER/PRIVATE-PORTABLE-REPO.git',
}


def module(name):
    spec = importlib.util.spec_from_file_location(name, P(__file__).with_name(name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inspect_workspace(repo, cloud_root):
    repo, cloud_root = repo.resolve(), cloud_root.resolve()
    checks = {'repository_inside_cloud_root': repo != cloud_root and repo.is_relative_to(cloud_root)}
    report = {'scope': 'local_integrity_only', 'checks': checks,
              'task_binding_present': (repo / 'work/icloud-active').exists(),
              'gateway_live_check': 'not_requested'}
    if not checks['repository_inside_cloud_root']:
        return dict(report, ok=False)
    portable, root_tools = module('portable_sync'), module('cloud_root')
    try:
        manifest = portable.validate(repo / 'snapshot')
        report['snapshot_id'] = manifest['id']
        expected_files = {}
        for relative, digest in manifest['files'].items():
            parts = P(relative).parts
            if len(parts) < 4 or parts[1] != 'skills':
                continue
            key = str(P(*parts[2:]))
            if key in expected_files and expected_files[key] != digest:
                raise ValueError('conflicting manifest aliases')
            expected_files[key] = digest
        checks['snapshot'] = True
    except (OSError, ValueError, KeyError, TypeError):
        checks['snapshot'] = False
        return dict(report, ok=False)
    try:
        for relative, digest in expected_files.items():
            target = repo / '.agents/skills' / relative
            if target.is_symlink() or not target.resolve().is_relative_to(repo / '.agents/skills'):
                raise ValueError('unsafe installed path')
            if sha(target.read_bytes()) != digest:
                raise ValueError('installed content differs')
        checks['installed_snapshot_skills'] = True
    except (OSError, ValueError):
        checks['installed_snapshot_skills'] = False
    try:
        state_path = repo / '.portable-state.json'
        if state_path.is_symlink():
            raise ValueError('symlinked import state')
        state = json.loads(state_path.read_text())
        checks['import_state'] = state == {'files': expected_files, 'snapshot': manifest['id']}
    except (OSError, ValueError, TypeError):
        checks['import_state'] = False
    try:
        record_path = cloud_root / '.codex-portable-root.json'
        index_path = cloud_root / '.codex-portable-skills.json'
        agents_path = cloud_root / 'AGENTS.md'
        if any(p.is_symlink() for p in (record_path, index_path, agents_path)):
            raise ValueError('symlinked root configuration')
        record = json.loads(record_path.read_text())
        checks['root_record_repository'] = record.get('repository') == str(repo)
        index_bytes = index_path.read_bytes()
        index = json.loads(index_bytes)
        expected_paths = {repo / '.agents/skills' / key for key in expected_files if P(key).name == 'SKILL.md'}
        expected_paths.add(repo / '.agents/skills/icloud-codex-gateway/SKILL.md')
        expected = {}
        for path in expected_paths:
            if path.is_symlink() or not path.resolve().is_relative_to(repo):
                raise ValueError('unsafe indexed path')
            expected[str(path)] = root_tools.skill_metadata(path)
        actual = {entry['path']: entry for entry in index['skills']}
        checks['skill_index'] = (len(actual) == len(index['skills']) and actual == expected
                                 and index['repository'] == str(repo)
                                 and sha(index_bytes) == record['skills_index_sha256'])
        report['indexed_skills'] = len(index['skills'])
        report['skill_discovery'] = record.get('skill_discovery')
        checks['guidance_only'] = record.get('skill_discovery') == 'guidance-index'
        text = agents_path.read_text()
        if text.count(root_tools.START) != 1 or text.count(root_tools.END) != 1:
            raise ValueError('invalid guidance markers')
        block = text[text.index(root_tools.START):text.index(root_tools.END) + len(root_tools.END)]
        checks['managed_guidance'] = sha(block.encode()) == record['block_sha256']
    except (OSError, ValueError, KeyError, TypeError):
        checks.setdefault('skill_index', False)
        checks.setdefault('managed_guidance', False)
        checks.setdefault('guidance_only', False)
    return dict(report, ok=all(checks.values()))


def command(args, cwd=None, timeout=20):
    try:
        result = subprocess.run(args, cwd=cwd, env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-root', type=P, default=P('/workspace'))
    parser.add_argument('--publication', action='store_true', help='Also reject dirty sources or real task bindings')
    parser.add_argument('--dependencies', action='store_true', help='Check Python, XeLaTeX and Noto CJK')
    parser.add_argument('--gateway', action='store_true', help='Perform a read-only authenticated WebDAV check')
    args = parser.parse_args()
    repo = P(__file__).resolve().parents[1]
    report = inspect_workspace(repo, args.cloud_root)
    checks = report['checks']
    report['source_commit'] = command(['git', 'rev-parse', 'HEAD'], repo)
    if args.publication:
        origin = command(['git', 'remote', 'get-url', 'origin'], repo)
        dirty = command(['git', 'status', '--porcelain', '--untracked-files=no'], repo)
        checks['trusted_origin'] = origin in TRUSTED_ORIGINS
        commit = report['source_commit'] or ''
        checks['source_commit_known'] = len(commit) == 40 and all(c in '0123456789abcdef' for c in commit)
        checks['clean_tracked_source'] = dirty == ''
        checks['no_task_binding_in_baseline'] = not report['task_binding_present']
    if args.dependencies:
        checks['python_supported'] = sys.version_info >= (3, 11)
        checks['xelatex'] = command(['xelatex', '--version']) is not None
        font = command(['fc-match', '-f', '%{family}', 'Noto Serif CJK SC:lang=zh-cn'])
        checks['noto_cjk_font'] = font is not None and 'Noto' in font and 'CJK' in font
    if args.gateway:
        client = repo / '.agents/skills/icloud-codex-gateway/scripts/gateway.py'
        result = command([sys.executable, str(client), 'check'], repo, timeout=90)
        try:
            response = json.loads(result or '{}')
            passed = isinstance(response, dict) and response.get('authenticated_webdav') == 'PASS'
        except (ValueError, TypeError):
            passed = False
        checks['authenticated_webdav'] = passed
        report['gateway_live_check'] = 'passed' if passed else 'failed_or_unavailable'
    report['ok'] = all(checks.values())
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
