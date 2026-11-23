"""The optional bwrap sandbox of the headless run (CARLOS_SANDBOX=bwrap): the argument list that hides the checkout and never binds
.env or data/, the code-only copy, the refusals when bwrap is missing or cannot start, and that nothing changes when it is off.
Fakes only: no bwrap, no claude, no network."""
import os, tempfile, unittest
from pathlib import Path
from unittest import mock
import worker
from tests.test_worker_isolation import FakeApi, popen_fake, req

ROOT_FAKE = '/srv/carlos'


class ArgvTest(unittest.TestCase):
    def argv(self, rw=()):
        return worker.sandbox_argv(Path(ROOT_FAKE), Path('/tmp/carlos-run-x'), rw)

    def test_the_checkout_is_hidden_under_a_tmpfs_and_the_code_copy_is_bound_there(self):
        a = self.argv()
        i = a.index('--tmpfs')
        self.assertEqual(a[i:i + 2], ['--tmpfs', ROOT_FAKE])
        j = a.index('--bind')
        self.assertEqual(a[j:j + 3], ['--bind', '/tmp/carlos-run-x', ROOT_FAKE])
        self.assertEqual(a[a.index('--chdir') + 1], ROOT_FAKE)

    def test_the_argument_list_never_binds_env_or_data(self):
        a = self.argv(rw=[Path.home() / '.claude', Path.home() / '.claude.json'])
        for arg in a:
            self.assertFalse(arg.endswith('/.env') or arg == '.env', arg)
            self.assertFalse(arg == ROOT_FAKE + '/data' or arg.startswith(ROOT_FAKE + '/data/'), arg)

    def test_pid_namespace_and_fresh_proc_hide_the_worker_process(self):
        a = self.argv()
        self.assertIn('--unshare-pid', a)
        self.assertIn('--die-with-parent', a)
        self.assertEqual(a[a.index('--proc') + 1], '/proc')
        self.assertEqual(a[-1], '--')

    def test_claude_state_is_bound_read_write_at_the_same_path(self):
        a = self.argv(rw=['/home/w/.claude', '/home/w/.claude.json'])
        self.assertEqual(a[a.index('/home/w/.claude') - 1:a.index('/home/w/.claude') + 2], ['--bind', '/home/w/.claude', '/home/w/.claude'])
        self.assertIn('/home/w/.claude.json', a)


class CopyTest(unittest.TestCase):
    def fake_checkout(self):
        root = Path(tempfile.mkdtemp())
        files = {'.env': 'ADMIN=secret', 'data/cars.sqlite': 'db', 'AGENTS.md': 'a', 'agent_tools.py': 'x', 'capture_listing.py': 'y',
                 'worker.py': 'w', 'carlos/research.py': 'r', 'carlos/plz_de.csv': 'plz', 'carlos/cars.sqlite': 'db',
                 'docs/deployment.md': 'd', 'docs/worker-settings.json': '{}', 'docs/prompts/units/tax.md': 't',
                 'docs/legacy/old.md': 'old'}
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        return root

    def test_the_copy_holds_the_research_code_and_never_env_or_data(self):
        root, dst = self.fake_checkout(), Path(tempfile.mkdtemp())
        worker.copy_code(dst, root)
        self.assertFalse((dst / '.env').exists())
        self.assertFalse((dst / 'data').exists())
        self.assertFalse((dst / 'carlos' / 'cars.sqlite').exists())
        self.assertFalse((dst / 'carlos' / 'plz_de.csv').exists())
        self.assertFalse((dst / 'worker.py').exists())
        self.assertFalse((dst / 'docs' / 'legacy').exists())
        for keep in ('AGENTS.md', 'agent_tools.py', 'capture_listing.py', 'carlos/research.py', 'docs/deployment.md',
                     'docs/worker-settings.json', 'docs/prompts/units/tax.md'):
            self.assertTrue((dst / keep).is_file(), keep)


class RunTest(unittest.TestCase):
    def run_once(self, env):
        api = FakeApi(req())
        with mock.patch.dict(os.environ, env, clear=True), popen_fake() as popen, \
                mock.patch.object(worker, 'copy_code') as copy:
            self.assertTrue(worker.work_one(api, 'w', 'claude -p', tempfile.mkdtemp(), 30))
        return popen.call_args[0][0], copy

    def test_with_the_sandbox_the_run_starts_inside_bwrap(self):
        argv, copy = self.run_once({'CARLOS_SANDBOX': 'bwrap', 'PATH': '/usr/bin', 'HOME': '/home/w'})
        self.assertEqual(argv[0], 'bwrap')
        self.assertIn('claude', argv)
        self.assertLess(argv.index('--'), argv.index('claude'))
        self.assertIn(str(worker.ROOT), argv)
        copy.assert_called_once()

    def test_without_it_nothing_changes(self):
        argv, copy = self.run_once({'PATH': '/usr/bin', 'HOME': '/home/w'})
        self.assertEqual(argv[0], 'claude')
        self.assertNotIn('bwrap', argv)
        copy.assert_not_called()

    def test_the_sandbox_value_must_be_exactly_bwrap(self):
        argv, _ = self.run_once({'CARLOS_SANDBOX': 'off', 'PATH': '/usr/bin', 'HOME': '/home/w'})
        self.assertEqual(argv[0], 'claude')


class RefusalTest(unittest.TestCase):
    def main_with(self, env, which, probe_rc=0):
        proc = mock.Mock(returncode=probe_rc, stderr='no userns')
        with mock.patch.dict(os.environ, {'WORKER_TOKEN': 't', **env}, clear=True), \
                mock.patch.object(worker, 'refuse_shared_checkout'), mock.patch.object(worker.shutil, 'which', return_value=which), \
                mock.patch.object(worker.subprocess, 'run', return_value=proc) as run, self.assertRaises(SystemExit) as cm:
            worker.main(['--once'])
        return str(cm.exception), run

    def test_missing_bwrap_refuses_to_start(self):
        msg, run = self.main_with({'CARLOS_SANDBOX': 'bwrap'}, which=None)
        self.assertIn('bwrap is not installed', msg)
        run.assert_not_called()

    def test_bwrap_that_cannot_start_here_refuses_to_start(self):
        msg, _ = self.main_with({'CARLOS_SANDBOX': 'bwrap'}, which='/usr/bin/bwrap', probe_rc=1)
        self.assertIn('cannot start a sandbox', msg)

    def test_an_unknown_sandbox_value_refuses_instead_of_running_unsandboxed(self):
        msg, _ = self.main_with({'CARLOS_SANDBOX': 'bwrapp'}, which='/usr/bin/bwrap')
        self.assertIn('not a sandbox', msg)


if __name__ == '__main__':
    unittest.main()
