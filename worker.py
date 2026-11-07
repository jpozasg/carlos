"""Shared research worker (issue #113). Runs on the owner's always-on desktop, not on the Pi: polls the site for research
requests, runs Claude Code headless with docs/prompts/research-request.md for each one, and reports the listing it wrote
into the requester's account (or why it failed). One request at a time.

Environment: CAR_API (the site, e.g. https://carlos.example.net), WORKER_TOKEN (this worker's token, created by an
admin on the Accounts page; issue #141), WORKER_NAME (default: the host name; with a worker token the registered name
counts), POLL_SECONDS (60), CLAUDE_CMD ('claude -p'), WORKER_MODEL ('haiku': the research runs on Haiku; added as
--model unless CLAUDE_CMD has one), WORKER_TIMEOUT_MIN (120), WORKER_LOGS (worker-logs/, one log per request).
The headless run gets only the per-request token of the request it works on (the requester's account and the shared
catalogue, dead when the request ends). Without WORKER_TOKEN the worker falls back to AGENT_TOKEN (an admin token) and
the X-Carlos-Account header, the way it worked before #141.
Run: python worker.py [--once]   (--once: handle at most one request, then exit)"""
import datetime, os, re, shlex, socket, subprocess, sys, time
from pathlib import Path
from capture_listing import Api, ApiError, load_token

ROOT = Path(__file__).resolve().parent
RESULT = re.compile(r'CARLOS_RESULT (?:listing_id=(\d+)|failed: (.*)|done: (.*))')  # done: a follow-up without a listing (#168)


def outcome(output):
    """The finish payload from the agent's last line: CARLOS_RESULT listing_id=<id> | CARLOS_RESULT failed: <reason>."""
    lines = [x.strip() for x in output.strip().splitlines()]
    m = RESULT.fullmatch(lines[-1]) if lines else None
    if m and m[1]:
        return {'status': 'DONE', 'listing_id': int(m[1]), 'result': 'Listing written by the worker'}
    if m and m[3]:
        return {'status': 'DONE', 'result': m[3]}
    return {'status': 'FAILED', 'result': m[2] if m else 'No CARLOS_RESULT line. Log tail:\n' + '\n'.join(lines[-30:])}


def prompt_for(req):
    text = (ROOT / 'docs' / 'prompts' / 'research-request.md').read_text(encoding='utf-8').split('\n---\n', 1)[1]
    for k, v in {'{URL}': req['url'], '{NOTE}': req['note'] or '(none)', '{ACCOUNT}': req['owner_id'],
                 '{REQUEST_ID}': req['id'], '{REPO}': ROOT}.items():
        text = text.replace(k, str(v))
    if req.get('listing_id') and req.get('missing'):  # continuation after the server's grading (#218)
        text += (f"\n\nCONTINUATION (attempt {req.get('attempts', 0) + 1}): listing {req['listing_id']} exists, but the server's grading "
                 f"still finds these contract items MISSING: {', '.join(req['missing'])}.\nGrade the listing again (to-do), work only on "
                 "these ids, and for every source that cannot be reached record a `NONE FOUND` or `N/A` check with the reason. "
                 f"End with CARLOS_RESULT listing_id={req['listing_id']}.")
    return text.strip()


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


def work_one(api, name, cmd, logs, timeout_s, model='haiku'):
    """Claims and handles one request; False when the queue is empty."""
    req = api.call('POST', '/api/worker/claim', {'worker': name})['request']
    if not req:
        return False
    print(f'request {req["id"]}: picked up {req.get("url")} (model {model})', flush=True)
    # print mode stops background tasks 10 min after the last turn, which left request 4 hanging (issue #137): wait for them
    env = {**os.environ, 'CAR_API': api.base, 'CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS': '0'}
    if req.get('request_token') and is_worker(api):  # the run only ever sees the per-request token (#141)
        env.update(AGENT_TOKEN=req['request_token']); env.pop('CARLOS_ACCOUNT', None)
    else:  # admin fallback: the admin token acting for the requester
        env.update(AGENT_TOKEN=api.token, CARLOS_ACCOUNT=str(req['owner_id']))
    log = Path(logs) / f'request-{req["id"]}.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(command(cmd, model) + [prompt_for(req)], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + timeout_s
    while True:  # wait for the run, with a heartbeat every minute so the admin panel shows the worker as working
        try:
            out = p.communicate(timeout=max(1, min(60, deadline - time.time())))[0]
            result = outcome(out) if p.returncode == 0 else {
                'status': 'FAILED', 'result': f'Exit code {p.returncode}. Log tail:\n' + '\n'.join(out.splitlines()[-30:])}
            break
        except subprocess.TimeoutExpired:
            if time.time() < deadline:
                beat(api, 'working'); continue
            p.kill()
            out = p.communicate()[0]
            result = {'status': 'FAILED', 'result': f'Timed out after {timeout_s // 60} minutes'}
            break
    log.write_text(out, encoding='utf-8')
    tail = '\n'.join(out.splitlines()[-30:])
    if result['status'] == 'FAILED' and p.returncode and LIMIT.search(tail):  # not the request's fault: queue it again and pause
        api.call('POST', f'/api/worker/requests/{req["id"]}', {'status': 'QUEUED', 'result': 'Released: ' + tail.splitlines()[-1][:200]})
        print(f'request {req["id"]}: back in the queue (usage limit or API error)', flush=True)
        raise UsageLimit(pause_seconds(tail), tail.splitlines()[-1][:200])
    try:
        api.call('POST', f'/api/worker/requests/{req["id"]}', result)
    except ApiError as e:  # e.g. the reported listing is not the requester's: record a failure instead
        result = {'status': 'FAILED', 'result': f'{e}\n{result.get("result") or ""}'}
        api.call('POST', f'/api/worker/requests/{req["id"]}', result)
    print(f'request {req["id"]}: {result["status"]} (log {log})', flush=True)
    return True


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
    os.environ.pop('CARLOS_ACCOUNT', None)  # the worker itself never acts for an account
    api = Api(os.environ.get('CAR_API', 'http://127.0.0.1:8000'), os.environ.get('WORKER_TOKEN') or load_token())
    api.worker = bool(os.environ.get('WORKER_TOKEN'))
    name, cmd = os.environ.get('WORKER_NAME') or socket.gethostname(), os.environ.get('CLAUDE_CMD', 'claude -p')
    model = os.environ.get('WORKER_MODEL', 'haiku')
    logs = os.environ.get('WORKER_LOGS', str(ROOT / 'worker-logs'))
    timeout_s, poll = int(os.environ.get('WORKER_TIMEOUT_MIN', '120')) * 60, int(os.environ.get('POLL_SECONDS', '60'))
    while True:
        beat(api, 'idle')
        try:
            worked = work_one(api, name, cmd, logs, timeout_s, model)
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
