#!/usr/bin/env python3
"""Explicitly authorized live acceptance, synthetic files only; never auto-discovered."""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'.agents/skills/icloud-codex-gateway/scripts'))
import autosave as a
import workspace as w


def emit(stage, **values):
    print(json.dumps({'stage': stage, **values}), flush=True)


def wait_worker_stopped(base):
    deadline = time.monotonic()+90
    while a.worker_running(base) and time.monotonic() < deadline:
        time.sleep(.5)
    assert not a.worker_running(base), 'in-flight worker did not finish; retain it and diagnose'


def wait_state(base, path, expected, timeout=180):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        info = a.status(base)['files'][path]
        if info['state'] == expected:
            return info
        if info['state'] == 'blocked' and expected != 'blocked':
            raise ValueError('queue blocked: '+json.dumps(info))
        time.sleep(1)
    raise TimeoutError('acceptance wait timed out for '+path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorized', action='store_true')
    args = parser.parse_args()
    if not args.authorized:
        raise SystemExit('Explicit synthetic test write authorization required')
    run = str(uuid.uuid4())
    output = ROOT/'work/autosave-live'/run
    output.mkdir(parents=True)
    base = output/'controller'
    remote = 'CodexGatewayTest/runs/'+run+'/autosave'
    report = {'run': run, 'remote_folder': remote, 'controller': str(base), 'checks': {}, 'expected': {}}
    a.atomic_json(output/'report.json', report)
    g = a.QueueGateway()
    g.listing(depth='0')
    w.ensure_parents(g, remote+'/note.txt')
    w.demand_workspace(g, remote, base, 32*1024*1024)
    emit('prepared', remote_folder=remote, report=str(output/'report.json'))
    try:
        note = base/'files/note.txt'
        first = ('Autosave acceptance '+run+' first save\n').encode()
        note.write_bytes(first)
        a.enable(base, ['note.txt'], [], True, settle=2)
        a.start(base)
        a.wait(base, 180)
        report['checks']['background_first_save'] = True
        second = ('Autosave acceptance '+run+' second save\n').encode()
        note.write_bytes(second)
        a.wait(base, 180)
        report['checks']['background_second_save'] = True
        report['expected']['note.txt'] = {'sha256': w.digest(second), 'bytes': len(second)}
        emit('source_saves_verified')

        build = output/'build'
        build.mkdir()
        tex = build/'sample.tex'
        tex.write_text(r'\documentclass{article}\begin{document}Automatic save queue verification. '
                       r'$1+1=2$.\end{document}'+'\n')
        process = subprocess.run(['xelatex', '-interaction=nonstopmode', '-halt-on-error',
                                  '-output-directory', str(build), str(tex)],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        (build/'compile-output.log').write_bytes(process.stdout)
        assert process.returncode == 0, 'PDF compilation failed; log retained'
        payload = (build/'sample.pdf').read_bytes()
        # Structural PDF validation; this tests publication, not a document layout.
        import fitz
        document = fitz.open(stream=payload, filetype='pdf')
        assert len(document) == 1 and 'Automatic save queue' in document[0].get_text()
        (base/'files/sample.pdf').write_bytes(payload)
        a.enable(base, [], ['sample.pdf'], True, settle=2)
        wait_state(base, 'sample.pdf', 'awaiting-ready')
        try:
            with g.req('HEAD', remote+'/sample.pdf'):
                raise AssertionError('Unreleased PDF unexpectedly published')
        except urllib.error.HTTPError as error:
            assert error.code == 404
        report['checks']['generated_file_held_before_ready'] = True
        a.ready(base, ['sample.pdf'])
        a.wait(base, 180)
        report['checks']['compiled_pdf_published_after_validation'] = True
        report['expected']['sample.pdf'] = {'sha256': w.digest(payload), 'bytes': len(payload), 'pages': 1}
        emit('generated_pdf_verified', bytes=len(payload))

        # Pause/resume saves rather than killing a live transfer.
        a.pause(base)
        wait_worker_stopped(base)
        third = ('Autosave acceptance '+run+' resumed save\n').encode()
        note.write_bytes(third)
        a.enable(base, ['note.txt'], [], True, settle=2)
        a.start(base)
        a.wait(base, 180)
        report['checks']['worker_resume_with_saved_queue'] = True
        report['expected']['note.txt'] = {'sha256': w.digest(third), 'bytes': len(third)}
        emit('resume_verified')

        # Inject one local transient error, never change proxy/VPN/firewall/auth.
        a.pause(base)
        wait_worker_stopped(base)
        retry_payload = ('Retry acceptance '+run+'\n').encode()
        (base/'files/retry.txt').write_bytes(retry_payload)
        a.enable(base, ['retry.txt'], [], True, settle=2)
        class OfflineOnce(a.QueueGateway):
            def req(self, *args, **kwargs):
                raise urllib.error.URLError('synthetic single-attempt outage')
        now = time.time()
        a.cycle(base, OfflineOnce(), now=now)
        a.cycle(base, OfflineOnce(), now=now+3)
        assert a.status(base)['files']['retry.txt']['state'] == 'retry'
        a.start(base)
        a.wait(base, 180)
        report['checks']['injected_transient_then_real_gateway_retry'] = True
        report['expected']['retry.txt'] = {'sha256': w.digest(retry_payload), 'bytes': len(retry_payload)}
        emit('automatic_retry_verified')

        # Remote conflict only on this run's synthetic file; never touch user work.
        a.pause(base)
        wait_worker_stopped(base)
        remote_edit = ('Other-device synthetic change '+run+'\n').encode()
        g.upload(remote+'/note.txt', remote_edit, w.digest(third))
        note.write_text('Conflicting local edit retained for review '+run+'\n')
        a.enable(base, ['note.txt'], [], True, settle=2)
        a.start(base)
        wait_state(base, 'note.txt', 'blocked')
        with g.req('GET', remote+'/note.txt') as response:
            assert response.read() == remote_edit
        report['checks']['remote_conflict_stops_without_overwrite'] = True
        report['expected']['note.txt'] = {'sha256': w.digest(remote_edit), 'bytes': len(remote_edit)}
        emit('conflict_preserved')
        report['complete'] = all(report['checks'].values())
    finally:
        if (base/'autosave/config.json').exists():
            a.pause(base)
            wait_worker_stopped(base)
            report['final_status'] = a.status(base)
        a.atomic_json(output/'report.json', report)
        emit('report', path=str(output/'report.json'), checks=report['checks'], complete=report.get('complete', False))


if __name__ == '__main__':
    main()
