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
    def argv(self, rw=(), masks=()):
        return worker.sandbox_argv(Path(ROOT_FAKE), Path('/tmp/carlos-run-x'), rw, masks)

    def test_each_token_file_is_masked_by_an_empty_file(self):
        tokens = worker.token_files('/home/w')
        self.assertTrue(tokens)
        a = self.argv(masks=tokens)
        for t in tokens:
            i = a.index(str(t))
            self.assertEqual(a[i - 2:i + 1], ['--ro-bind', '/dev/null', str(t)])

    def test_nothing_binds_a_token_file_read_write(self):
        tokens = [str(t) for t in worker.token_files('/home/w')]
        a = self.argv(rw=[Path('/home/w/.config')], masks=worker.token_files('/home/w'))  # even under a bound parent
        for t in tokens:
            for i, arg in enumerate(a):
                if arg == t:
                    self.assertEqual(a[i - 2:i], ['--ro-bind', '/dev/null'], t)
            self.assertLess(a.index('/home/w/.config'), a.index(t))  # the mask comes after the parent's bind and wins

    def test_the_mask_is_on_the_argument_list_only_when_given(self):
        self.assertNotIn('/dev/null', self.argv())

    def test_the_token_file_is_masked_in_a_run_that_has_it(self):
        home = Path(tempfile.mkdtemp())
        (home / '.config').mkdir()
        (home / '.config' / 'carlos-worker.env').write_text('WORKER_TOKEN=x')
        with mock.patch.dict(os.environ, {'HOME': str(home)}):
            self.assertEqual(worker.token_masks(), worker.token_files())
        a = self.argv(masks=worker.token_masks(home))
        self.assertIn(str(home / '.config' / 'carlos-worker.env'), a)
        self.assertEqual(worker.token_masks(Path(tempfile.mkdtemp())), [])  # no file, nothing to mask (no failing bind)

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


class BusAndSymlinkTest(unittest.TestCase):
    def test_the_user_runtime_dir_is_hidden_under_a_tmpfs(self):  # S1: the user bus socket and systemd --user are unreachable
        a = worker.sandbox_argv(Path(ROOT_FAKE), Path('/tmp/carlos-run-x'), hidden=[Path('/run/user/1000')])
        self.assertEqual(a[a.index('/run/user/1000') - 1:a.index('/run/user/1000') + 1], ['--tmpfs', '/run/user/1000'])
        self.assertEqual(a[-1], '--')

    def test_bus_dir_is_listed_only_when_it_exists(self):
        self.assertEqual(worker.bus_dirs(uid=os.getuid() + 100000), [])
        with mock.patch.object(worker.Path, 'is_dir', return_value=True):
            self.assertEqual(worker.bus_dirs(uid=1000), [Path('/run/user/1000')])

    def test_the_run_environment_has_no_bus_variables(self):  # S1
        env = {'PATH': '/usr/bin', 'HOME': '/home/w', 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus',
               'XDG_RUNTIME_DIR': '/run/user/1000', 'XDG_CONFIG_HOME': '/home/w/.config',
               'WORKER_PASS_ENV': 'DBUS_SESSION_BUS_ADDRESS,XDG_RUNTIME_DIR'}
        with mock.patch.dict(os.environ, env, clear=True):
            e = worker.run_env(FakeApi(), req())
        self.assertNotIn('DBUS_SESSION_BUS_ADDRESS', e)
        self.assertNotIn('XDG_RUNTIME_DIR', e)
        self.assertEqual(e['XDG_CONFIG_HOME'], '/home/w/.config')  # other XDG variables still pass

    def test_a_symlinked_token_file_is_masked_at_its_link_and_its_real_path(self):  # S2
        home = Path(tempfile.mkdtemp()).resolve()
        (home / '.config').mkdir()
        real = home / 'vault' / 'tok.env'
        real.parent.mkdir()
        real.write_text('WORKER_TOKEN=x')
        link = home / '.config' / 'carlos-worker.env'
        link.symlink_to(real)
        masks = worker.token_masks(home)
        self.assertEqual(masks, [link, real])
        a = worker.sandbox_argv(Path(ROOT_FAKE), Path('/tmp/carlos-run-x'), masks=masks)
        for p in (link, real):
            i = a.index(str(p))
            self.assertEqual(a[i - 2:i + 1], ['--ro-bind', '/dev/null', str(p)])


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

    def test_the_sandboxed_run_masks_the_worker_token_file(self):
        home = Path(tempfile.mkdtemp())
        (home / '.config').mkdir()
        tok = home / '.config' / 'carlos-worker.env'
        tok.write_text('WORKER_TOKEN=x')
        argv, _ = self.run_once({'CARLOS_SANDBOX': 'bwrap', 'PATH': '/usr/bin', 'HOME': str(home)})
        i = argv.index(str(tok))
        self.assertEqual(argv[i - 2:i + 1], ['--ro-bind', '/dev/null', str(tok)])

    def test_the_sandboxed_run_hides_the_user_runtime_dir(self):  # S1
        with mock.patch.object(worker, 'bus_dirs', return_value=[Path('/run/user/1000')]):
            argv, _ = self.run_once({'CARLOS_SANDBOX': 'bwrap', 'PATH': '/usr/bin', 'HOME': '/home/w'})
        i = argv.index('/run/user/1000')
        self.assertEqual(argv[i - 1:i + 1], ['--tmpfs', '/run/user/1000'])

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
