"""Shared research worker (issue #113). Runs on the owner's always-on desktop, not on the Pi: polls the site for research
requests, runs Claude Code headless with the unit prompt of each one (docs/prompts/units/), and reports the listing it wrote
into the requester's account (or why it failed). One request at a time.

Environment: CAR_API (the site, e.g. https://carlos.example.net), WORKER_TOKEN (this worker's token, created by an
admin on the Accounts page; issue #141), WORKER_NAME (default: the host name; with a worker token the registered name
counts), POLL_SECONDS (60), CLAUDE_CMD ('claude -p'), WORKER_MODEL ('haiku': the research runs on Haiku; added as
--model unless CLAUDE_CMD has one), WORKER_TIMEOUT_MIN (120), WORKER_RESEARCH_TIMEOUT_MIN (150, the RESEARCH_A/B runs), WORKER_LOGS (worker-logs/, one log per request).
The headless run gets only the per-request token of the request it works on (the requester's account and the shared
catalogue, dead when the request ends) and an allow-listed environment (RUN_ENV; WORKER_PASS_ENV adds names), never
WORKER_TOKEN or an admin token. Without WORKER_TOKEN the worker refuses to start (the admin fallback was removed 2026-11-22).
Only the current units run: a request without a unit or with a retired unit is refused with its reason (carlos/research_units.refusal). It also refuses to
start from a checkout that holds .env or data/ (the server's secrets and database) unless WORKER_ALLOW_SHARED_CHECKOUT=1;
run it as another OS user from a code-only checkout (docs/deployment.md). A `claude` run gets docs/worker-settings.json
(deny rules for .env, data/, sqlite3: speed bumps, the OS user is the control) and no skills (--disable-slash-commands).
CARLOS_SANDBOX=bwrap runs each headless claude inside bubblewrap (docs/deployment.md, "Sandbox"): the checkout hidden, a code-only
copy as the working directory, a private process list; the worker refuses to start if bwrap is missing or cannot run here.
Run: python worker.py [--once]   (--once: handle at most one request, then exit)"""
import datetime, json, os, re, shlex, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path
from capture_listing import Api, ApiError
from carlos import research_units as ru, urlcheck

ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / 'docs' / 'worker-settings.json'  # deny rules of the headless claude (tracked: .claude/ is git-ignored)
# the run's environment is an allow-list (#386): Claude Code itself and Chrome need these; nothing of the worker's own secrets
RUN_ENV = ('PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'LANGUAGE', 'TERM', 'TMPDIR', 'DISPLAY', 'WAYLAND_DISPLAY',
           'DBUS_SESSION_BUS_ADDRESS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY',
           'https_proxy', 'http_proxy', 'no_proxy')
RUN_ENV_PREFIXES = ('LC_', 'XDG_', 'ANTHROPIC_', 'CLAUDE_')  # locale, desktop session, Claude's own settings and login
NEVER_PASSED = {'WORKER_TOKEN', 'AGENT_TOKEN', 'CARLOS_ACCOUNT'}
NO_WORKER_TOKEN = 'no WORKER_TOKEN: the worker refuses to start (set WORKER_TOKEN, docs/deployment.md); there is no admin fallback'
RESULT = re.compile(r'CARLOS_RESULT (?:listing_id=(\d+)|failed: (.*)|done: (.*))')  # done: a follow-up without a listing (#168)


def outcome(output):
    """The finish payload from the agent's last CARLOS_RESULT line: CARLOS_RESULT listing_id=<id> | CARLOS_RESULT failed: <reason>."""
    lines = [x.strip().strip('`*_ ') for x in output.strip().splitlines()]  # the agent may wrap the line in markdown
    hits = [m for m in map(RESULT.search, lines) if m]  # the last result line, wherever the agent put it
    m = hits[-1] if hits else None
    if m and m[1]:
        return {'status': 'DONE', 'listing_id': int(m[1]), 'result': 'Listing written by the worker'}
    if m and m[3]:
        return {'status': 'DONE', 'result': m[3]}
    return {'status': 'FAILED', 'result': m[2] if m else 'No CARLOS_RESULT line. Log tail:\n' + '\n'.join(lines[-30:])}


def parse_usage(out):
    """(text, usage) of a `claude --output-format json` run (#291): the agent's final text and tokens/cost/time/turns; the
    output unchanged and None when it is not that JSON (a failed start, another command)."""
    for line in reversed(out.strip().splitlines()):
        if line.startswith('{'):
            try:
                j = json.loads(line)
            except ValueError:
                return out, None
            if not isinstance(j, dict) or 'result' not in j:
                return out, None
            u = j.get('usage') or {}
            return str(j['result']), {'input': u.get('input_tokens'), 'output': u.get('output_tokens'),
                                      'cache_read': u.get('cache_read_input_tokens'), 'cache_write': u.get('cache_creation_input_tokens'),
                                      'cost_usd': j.get('total_cost_usd'), 'seconds': round((j.get('duration_ms') or 0) / 1000),
                                      'turns': j.get('num_turns'), 'runs': 1}
    return out, None


FENCE_MARKERS = re.compile(r'<{3,}|>{3,}')


def fenced(value):
    """Text of a requester, a web page or an earlier run, made safe to sit between the UNTRUSTED markers of a prompt: it cannot
    carry a marker of its own (<<< or >>>), so it cannot end the fence and write instructions outside it (#386)."""
    return FENCE_MARKERS.sub('...', str(value))


def prompt_for(req):
    """The prompt of one research unit (#218 phase 2): shared rules + docs/prompts/units/<unit>.md."""
    d = ROOT / 'docs' / 'prompts' / 'units'
    name = 'research' if req['unit'] in ('RESEARCH_A', 'RESEARCH_B') else req['unit'].lower()  # the two runs get the same prompt (#253)
    text = (d / '_header.md').read_text(encoding='utf-8') + (d / f'{name}.md').read_text(encoding='utf-8')
    scope = req.get('scope')
    scope = json.loads(scope) if isinstance(scope, str) else scope
    for k, v in {'{SCOPE}': ', '.join(f'{col.removesuffix("_id").replace("_", " ")} {i}' for col, i in scope or []) or '(see the to-do)',
                 '{UNIT}': req['unit'], '{LISTING_ID}': req.get('listing_id') or '(none yet)', '{LEVEL_ID}': req.get('level_id') or '(none)',
                 '{PARENT_ID}': req.get('parent_id') or req['id'], '{MISSING}': ', '.join(map(str, req.get('missing') or [])) or '(all items of the unit)',
                 '{ATTEMPT}': (req.get('attempts') or 0) + 1, '{PREVIOUS_RESULT}': fenced(req.get('result') or '(none)'),
                 '{URL}': fenced(req.get('url') or '(see the listing)'), '{NOTE}': fenced(req.get('note') or '(none)'), '{ACCOUNT}': req['owner_id'],
                 '{REQUEST_ID}': req['id'], '{REPO}': ROOT}.items():
        text = text.replace(k, str(v))
    return text.strip()


def run_env(api, req):
    """The environment of the headless run (#386): an allow-list, so WORKER_TOKEN and the rest of the worker's environment never reach it;
    the per-request token is its AGENT_TOKEN, the only credential a run gets (the admin fallback was removed 2026-11-22).
    CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0: print mode stops background tasks 10 min after the last turn, which left request 4 hanging
    (issue #137), so it waits for them."""
    if not req.get('request_token'):
        raise ApiError('no request token: the run is not started')
    extra = {x.strip() for x in os.environ.get('WORKER_PASS_ENV', '').split(',')} - NEVER_PASSED
    env = {k: v for k, v in os.environ.items() if k in RUN_ENV or k.startswith(RUN_ENV_PREFIXES) or k in extra}
    env.update(CAR_API=api.base, CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS='0', AGENT_TOKEN=req['request_token'])
    return env


def refuse_shared_checkout():
    """The worker must not run from the server's checkout (#386): its run could read .env (the admin token) and data/. An explicit
    WORKER_ALLOW_SHARED_CHECKOUT=1 (a development machine, e.g. the owner's pilot) lets it start with a warning."""
    held = ' and '.join(n for n in ('.env', 'data') if (ROOT / n).exists())
    if held and os.environ.get('WORKER_ALLOW_SHARED_CHECKOUT') != '1':
        raise SystemExit(f'worker: {ROOT} holds {held}: run the worker from a code-only checkout as another OS user (docs/deployment.md); '
                         'WORKER_ALLOW_SHARED_CHECKOUT=1 overrides this on a development machine')
    if held:
        print(f'worker: WARNING: this checkout holds {held}; the headless run can read them', file=sys.stderr, flush=True)


SAFE_FLAGS = ('-p', '--print', '--model', '--output-format', '--settings', '--disable-slash-commands')  # N8: the flags the worker's own defaults use


def check_command(cmd):
    """N8: CLAUDE_CMD may carry only SAFE_FLAGS; a permission bypass or any other flag stops the worker before it claims a request."""
    bad = [t for t in shlex.split(cmd)[1:] if t.startswith('-') and t.split('=', 1)[0] not in SAFE_FLAGS]
    if bad:
        raise SystemExit(f'worker: CLAUDE_CMD has flag(s) outside the allow-list: {" ".join(bad)} (allowed: {" ".join(SAFE_FLAGS)})')


CODE_FILES = ('AGENTS.md', 'agent_tools.py', 'capture_listing.py')  # the research run's code (plus docs/ and carlos/ below)


def copy_code(dst, root=ROOT):
    """A code-only copy of the checkout for a sandboxed run: the research code, prompts and docs, never .env, data/ or the
    postcode table (only what the run reads is copied; a missing file is an error, not a silent gap)."""
    for name in CODE_FILES:
        shutil.copy2(root / name, dst / name)
    shutil.copytree(root / 'carlos', dst / 'carlos', ignore=shutil.ignore_patterns('__pycache__', '*.csv', '*.sqlite'))
    (dst / 'docs').mkdir()
    for f in [*(root / 'docs').glob('*.md'), root / 'docs' / 'worker-settings.json']:
        shutil.copy2(f, dst / 'docs' / f.name)
    shutil.copytree(root / 'docs' / 'prompts', dst / 'docs' / 'prompts')


def token_files(home=None):
    """The worker's token files on disk: the systemd EnvironmentFile of docs/deployment.md. worker.py reads none itself (WORKER_TOKEN
    comes from the environment), so a sandboxed run must not be able to read them either."""
    return [Path(home or Path.home()) / '.config' / 'carlos-worker.env']


def token_masks(home=None):
    """The token files that exist (a bind of /dev/null needs an existing mount point): masked inside a sandboxed run."""
    return [p for p in token_files(home) if p.exists()]


def sandbox_argv(root, workdir, rw=(), masks=()):
    """The bwrap prefix of a sandboxed run (pure, so it is tested without bwrap): the real checkout `root` hidden under a tmpfs,
    the code-only copy `workdir` bound at the same path (the prompts' {REPO} still works), the paths in `rw` (claude's state) bound
    read-write, the paths in `masks` (the worker's token files) replaced by an empty file, a fresh /proc in a new pid namespace (the
    worker's process and environment are not visible), and dies with the worker. The run's environment is already the allow-list
    of run_env. Ends with `--`; the claude argv follows."""
    args = ['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
            '--tmpfs', str(root), '--bind', str(workdir), str(root),
            '--unshare-pid', '--die-with-parent', '--chdir', str(root)]
    for p in rw:
        args += ['--bind', str(p), str(p)]
    for p in masks:  # after rw, so a mask always wins over a bind of its parent
        args += ['--ro-bind', '/dev/null', str(p)]
    return args + ['--']


def claude_state(home=None):
    """Claude Code's own state, which a sandboxed run writes (sessions, login, settings): bound read-write, only what exists."""
    home = Path(home or Path.home())
    cands = [home / '.claude', home / '.claude.json']
    if os.environ.get('CLAUDE_CONFIG_DIR'):
        cands.append(Path(os.environ['CLAUDE_CONFIG_DIR']))
    return [p for p in cands if p.exists()]


def check_sandbox():
    """CARLOS_SANDBOX=bwrap: refuses to start unless bwrap is installed and can make a sandbox here (unprivileged user namespaces).
    Never falls back to an unsandboxed run."""
    if shutil.which('bwrap') is None:
        raise SystemExit('worker: CARLOS_SANDBOX=bwrap but bwrap is not installed (package bubblewrap); the worker will not run unsandboxed')
    probe = subprocess.run(['bwrap', '--ro-bind', '/', '/', '--unshare-pid', '--die-with-parent', '--', 'true'],
                           capture_output=True, text=True)
    if probe.returncode:
        raise SystemExit('worker: bwrap cannot start a sandbox here (needs unprivileged user namespaces, docs/deployment.md): '
                         + probe.stderr.strip()[:300])


def command(cmd, model):
    """The headless command with --model <model> after the claude executable, unless one is given (owner: the worker runs on Haiku)."""
    parts = shlex.split(cmd)
    if model and parts and Path(parts[0]).name == 'claude' and not any(p == '--model' or p.startswith('--model=') for p in parts):
        parts[1:1] = ['--model', model]
    return parts


LIMIT = re.compile(r"hit your [\w-]+ limit|usage limit|rate.?limit|overloaded|API Error: (?:429|5\d\d)", re.I)
RESET = re.compile(r"resets (\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)


class UsageLimit(Exception):
    """The run stopped on a usage/rate limit or a transient API error: the request went back to the queue (#206)."""
    def __init__(self, seconds, message):
        super().__init__(message); self.seconds = seconds


def pause_seconds(text, now=None, fallback=1800):
    """Seconds until the reset time named in "resets 4am", else `fallback`.
    shortcut: the zone in brackets is ignored (local clock assumed), fine while the worker runs where the owner works."""
    m = RESET.search(text)
    if not m:
        return fallback
    now = now or datetime.datetime.now()
    hour = int(m[1]) % 12 + (12 if m[3].lower() == 'pm' else 0)
    at = now.replace(hour=hour, minute=int(m[2] or 0), second=0, microsecond=0)
    if at <= now:
        at += datetime.timedelta(days=1)
    return int((at - now).total_seconds()) + 60


def work_one(api, name, cmd, logs, timeout_s, model='haiku', research_timeout_s=None):
    """Claims and handles one request; False when the queue is empty."""
    if not is_worker(api):  # before the claim: a request must not be left RUNNING
        raise ApiError(NO_WORKER_TOKEN)
    req = api.call('POST', '/api/worker/claim', {'worker': name})['request']
    if not req:
        return False
    if req.get('unit') in ru.SERVER_UNITS:  # the merge is server code: no Claude run (#253)
        print(f'request {req["id"]}: picked up {req.get("unit")} (no Claude run)', flush=True)
        report(api, req, merge_outcome(api, req))
        return True
    why = ru.refusal(req.get('unit'))
    if why:  # the server refuses these at the claim too; a worker never runs one (owner decision 2026-11-22)
        report(api, req, {'status': 'FAILED', 'result': why})
        return True
    print(f'request {req["id"]}: picked up {req.get("url")} (model {model})', flush=True)
    if req.get('url') and not req['url'].startswith('carlos://'):  # checked when it was queued; again now (DNS and rules change)
        try:
            urlcheck.public_http_url(req['url'])
        except ValueError as e:
            report(api, req, {'status': 'FAILED', 'result': f'{e}. The run was not started.'})
            return True
    if req.get('unit') in ('RESEARCH_A', 'RESEARCH_B') and research_timeout_s:
        timeout_s = research_timeout_s
    env = run_env(api, req)
    log = Path(logs) / f'request-{req["id"]}.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = command(cmd, model)
    if Path(argv[0]).name == 'claude':
        argv[1:1] = [*(['--output-format', 'json'] if '--output-format' not in argv else []),  # the JSON result carries the usage (#291)
                     *(['--settings', str(SETTINGS)] if '--settings' not in argv else []),  # deny rules for .env and data/ (#386)
                     *(['--disable-slash-commands'] if '--disable-slash-commands' not in argv else [])]  # a run needs no skills
    workdir = Path(tempfile.mkdtemp(prefix='carlos-run-')) if os.environ.get('CARLOS_SANDBOX') == 'bwrap' else None
    try:
        if workdir:  # the run sees only this copy of the code, inside the sandbox (#386 follow-up)
            copy_code(workdir)
            argv = sandbox_argv(ROOT, workdir, claude_state(), token_masks()) + argv
        p = subprocess.Popen(argv + [prompt_for(req)], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + timeout_s
        while True:  # wait for the run, with a heartbeat every minute so the admin panel shows the worker as working
            try:
                out, usage = parse_usage(p.communicate(timeout=max(1, min(60, deadline - time.time())))[0])
                result = outcome(out) if p.returncode == 0 else {
                    'status': 'FAILED', 'result': f'Exit code {p.returncode}. Log tail:\n' + '\n'.join(out.splitlines()[-30:])}
                break
            except subprocess.TimeoutExpired:
                if time.time() < deadline:
                    beat(api, 'working'); continue
                p.kill()
                out, usage = parse_usage(p.communicate()[0])
                result = {'status': 'FAILED', 'result': f'Timed out after {timeout_s // 60} minutes'}
                break
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    log.write_text(out + (f'\n\nUSAGE {json.dumps(usage)}\n' if usage else ''), encoding='utf-8')
    if usage:
        result['usage'] = usage
    tail = '\n'.join(out.splitlines()[-30:])
    if result['status'] == 'FAILED' and p.returncode and LIMIT.search(tail):  # not the request's fault: queue it again and pause
        api.call('POST', f'/api/worker/requests/{req["id"]}', {'status': 'QUEUED', 'result': 'Released: ' + tail.splitlines()[-1][:200]})
        print(f'request {req["id"]}: back in the queue (usage limit or API error)', flush=True)
        raise UsageLimit(pause_seconds(tail), tail.splitlines()[-1][:200])
    report(api, req, result, log)
    return True


def merge_outcome(api, req):
    """Runs POST /api/agent/merge with the request's own token and builds the finish payload (the server grades the real rows)."""
    if not req.get('request_token'):
        return {'status': 'FAILED', 'result': 'Merge refused: no request token'}
    mine = Api(api.base, req['request_token'])
    try:
        out = mine.call('POST', '/api/agent/merge', {})
    except (ApiError, OSError) as e:
        return {'status': 'FAILED', 'result': f'Merge failed: {e}'}
    return {'status': 'DONE', 'result': f'Merged: {out.get("written", 0)} written, {len(out.get("skipped") or [])} skipped, '
                                         f'{len(out.get("disagreements") or [])} disagreements'}


def report(api, req, result, log=None):
    try:
        api.call('POST', f'/api/worker/requests/{req["id"]}', result)
    except ApiError as e:  # e.g. the reported listing is not the requester's: record a failure instead
        result = {'status': 'FAILED', 'result': f'{e}\n{result.get("result") or ""}'}
        api.call('POST', f'/api/worker/requests/{req["id"]}', result)
    print(f'request {req["id"]}: {result["status"]}' + (f' (log {log})' if log else ''), flush=True)


def is_worker(api):
    return getattr(api, 'worker', False)


def beat(api, state, error=None):
    """Heartbeat for the admin panel (registered workers only); a failed heartbeat never stops the work."""
    if is_worker(api):
        try:
            api.call('POST', '/api/worker/heartbeat', {'state': state, **({'error': error} if error else {})})
        except (ApiError, OSError) as e:
            print(f'worker: heartbeat failed: {e}', file=sys.stderr, flush=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.umask(0o077)  # the run logs and anything else the worker writes are owner-only (issue #414, L5)
    os.environ.pop('CARLOS_ACCOUNT', None)  # the worker itself never acts for an account
    refuse_shared_checkout()
    if not os.environ.get('WORKER_TOKEN'):
        raise SystemExit(f'worker: {NO_WORKER_TOKEN}')
    api = Api(os.environ.get('CAR_API', 'http://127.0.0.1:8000'), os.environ['WORKER_TOKEN'])
    api.worker = True
    name, cmd = os.environ.get('WORKER_NAME') or socket.gethostname(), os.environ.get('CLAUDE_CMD', 'claude -p')
    model = os.environ.get('WORKER_MODEL', 'haiku')
    check_command(cmd)
    sandbox = os.environ.get('CARLOS_SANDBOX', '')
    if sandbox not in ('', 'bwrap'):  # a typo must not run unsandboxed
        raise SystemExit(f'worker: CARLOS_SANDBOX={sandbox!r} is not a sandbox (use bwrap, or leave it unset)')
    if sandbox:
        check_sandbox()
        print('worker: sandbox: bwrap (each run is isolated from the checkout and the worker process)', flush=True)
    print(f'worker: runs start with: {" ".join(command(cmd, model))}', flush=True)  # the effective command (N8); no environment values
    extra = sorted({x.strip() for x in os.environ.get('WORKER_PASS_ENV', '').split(',')} - NEVER_PASSED - {''})
    if extra:
        print(f'worker: WORKER_PASS_ENV passes to the runs: {", ".join(extra)}', flush=True)
    logs = os.environ.get('WORKER_LOGS', str(ROOT / 'worker-logs'))
    timeout_s, poll = int(os.environ.get('WORKER_TIMEOUT_MIN', '120')) * 60, int(os.environ.get('POLL_SECONDS', '60'))
    research_s = int(os.environ.get('WORKER_RESEARCH_TIMEOUT_MIN', '150')) * 60
    while True:
        beat(api, 'idle')
        try:
            worked = work_one(api, name, cmd, logs, timeout_s, model, research_s)
        except UsageLimit as e:  # wait for the reset with a heartbeat every minute, then claim again
            left = e.seconds
            while left > 0 and '--once' not in argv:
                beat(api, 'error', f'paused: {e}'[:200]); time.sleep(min(60, left)); left -= 60
            worked = True
        except (ApiError, OSError) as e:  # site unreachable or a bad answer: report and keep polling
            print(f'worker: {e}', file=sys.stderr, flush=True)
            beat(api, 'error', str(e))
            worked = False
        if '--once' in argv:
            return
        if not worked:
            time.sleep(poll)


if __name__ == '__main__':
    main()
