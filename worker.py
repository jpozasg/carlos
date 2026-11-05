"""Shared research worker (issue #113). Runs on the owner's always-on desktop, not on the Pi: polls the site for research
requests, runs Claude Code headless with docs/prompts/research-request.md for each one, and reports the listing it wrote
into the requester's account (or why it failed). One request at a time.

Environment: CAR_API (the site, e.g. https://carlos.example.net), AGENT_TOKEN (an admin's agent token; or .env),
WORKER_NAME (default: the host name), POLL_SECONDS (60), CLAUDE_CMD ('claude -p'), WORKER_TIMEOUT_MIN (120),
WORKER_LOGS (worker-logs/, one log per request).
Run: python worker.py [--once]   (--once: handle at most one request, then exit)"""
import os, re, shlex, socket, subprocess, sys, time
from pathlib import Path
from capture_listing import Api, ApiError, load_token

ROOT = Path(__file__).resolve().parent
RESULT = re.compile(r'CARLOS_RESULT (?:listing_id=(\d+)|failed: (.*))')


def outcome(output):
    """The finish payload from the agent's last line: CARLOS_RESULT listing_id=<id> | CARLOS_RESULT failed: <reason>."""
    lines = [x.strip() for x in output.strip().splitlines()]
    m = RESULT.fullmatch(lines[-1]) if lines else None
    if m and m[1]:
        return {'status': 'DONE', 'listing_id': int(m[1]), 'result': 'Listing written by the worker'}
    return {'status': 'FAILED', 'result': m[2] if m else 'No CARLOS_RESULT line. Log tail:\n' + '\n'.join(lines[-30:])}


def prompt_for(req):
    text = (ROOT / 'docs' / 'prompts' / 'research-request.md').read_text(encoding='utf-8').split('\n---\n', 1)[1]
    for k, v in {'{URL}': req['url'], '{NOTE}': req['note'] or '(none)', '{ACCOUNT}': req['owner_id'],
                 '{REQUEST_ID}': req['id'], '{REPO}': ROOT}.items():
        text = text.replace(k, str(v))
    return text.strip()


def work_one(api, name, cmd, logs, timeout_s):
    """Claims and handles one request; False when the queue is empty."""
    req = api.call('POST', '/api/worker/claim', {'worker': name})['request']
    if not req:
        return False
    # print mode stops background tasks 10 min after the last turn, which left request 4 hanging (issue #137): wait for them
    env = {**os.environ, 'CAR_API': api.base, 'AGENT_TOKEN': api.token, 'CARLOS_ACCOUNT': str(req['owner_id']),
           'CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS': '0'}
    log = Path(logs) / f'request-{req["id"]}.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run(shlex.split(cmd) + [prompt_for(req)], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=timeout_s)
        out = p.stdout
        result = outcome(out) if p.returncode == 0 else {
            'status': 'FAILED', 'result': f'Exit code {p.returncode}. Log tail:\n' + '\n'.join(out.splitlines()[-30:])}
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b'').decode(errors='replace')
        result = {'status': 'FAILED', 'result': f'Timed out after {timeout_s // 60} minutes'}
    log.write_text(out, encoding='utf-8')
    try:
        api.call('POST', f'/api/worker/requests/{req["id"]}', result)
    except ApiError as e:  # e.g. the reported listing is not the requester's: record a failure instead
        result = {'status': 'FAILED', 'result': f'{e}\n{result.get("result") or ""}'}
        api.call('POST', f'/api/worker/requests/{req["id"]}', result)
    print(f'request {req["id"]}: {result["status"]} (log {log})', flush=True)
    return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.environ.pop('CARLOS_ACCOUNT', None)  # the worker itself claims and finishes as the admin
    api = Api(os.environ.get('CAR_API', 'http://127.0.0.1:8000'), load_token())
    name, cmd = os.environ.get('WORKER_NAME') or socket.gethostname(), os.environ.get('CLAUDE_CMD', 'claude -p')
    logs = os.environ.get('WORKER_LOGS', str(ROOT / 'worker-logs'))
    timeout_s, poll = int(os.environ.get('WORKER_TIMEOUT_MIN', '120')) * 60, int(os.environ.get('POLL_SECONDS', '60'))
    while True:
        try:
            worked = work_one(api, name, cmd, logs, timeout_s)
        except (ApiError, OSError) as e:  # site unreachable or a bad answer: report and keep polling
            print(f'worker: {e}', file=sys.stderr, flush=True)
            worked = False
        if '--once' in argv:
            return
        if not worked:
            time.sleep(poll)


if __name__ == '__main__':
    main()
