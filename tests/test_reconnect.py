import importlib.util
import pathlib
import tempfile
import unittest
import contextlib
import io
from types import SimpleNamespace

path = pathlib.Path(__file__).resolve().parents[1] / 'gateway-runtime/reconnect.py'
spec = importlib.util.spec_from_file_location('owner_reconnect', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReconnectTest(unittest.TestCase):
    def workflow(self, outcomes):
        retained = path.parents[1] / 'work/reconnect-test-retained'
        retained.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.mkdtemp(prefix='synthetic-', dir=retained)
        with contextlib.redirect_stdout(io.StringIO()):
            base = pathlib.Path(temporary)
            config = base / '.config/rclone/rclone-cn.conf'
            config.parent.mkdir(parents=True)
            config.write_bytes(b'synthetic protected configuration\n')
            config.chmod(0o600)
            calls = []

            def run(args, **kwargs):
                calls.append(args)
                return SimpleNamespace(returncode=outcomes[len(calls) - 1])

            result = module.reconnect(base, run)
            backups = list((base / '.local/state/icloud-gateway/auth-backups').glob('*.conf'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), config.read_bytes())
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
            return result, calls

    def test_recovery_health_after_verified_restart(self):
        result, calls = self.workflow([0, 0, 0, 0])
        self.assertEqual(result, 0)
        self.assertEqual(calls[2][-2:], ['restart', 'icloud-gateway-webdav.service'])
        self.assertEqual(calls[3], ['/usr/bin/python3', '/usr/local/libexec/icloud-gateway-health.py'])

    def test_failed_login_does_not_restart(self):
        result, calls = self.workflow([1])
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 1)

    def test_failed_root_read_does_not_restart(self):
        result, calls = self.workflow([0, 1])
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)

    def test_failed_health_is_not_reported_as_success(self):
        result, calls = self.workflow([0, 0, 0, 1])
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 4)


if __name__ == '__main__':
    unittest.main()
