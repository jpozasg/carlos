# External skills (user level)

Third-party skills the owner approved, installed at **user level** (`~/.claude/skills/<name>/`), never in this repository. Each was cloned into a fresh directory, every installed file was read, and only the reviewed skill folder was copied (no `.git`, hooks, `.mcp.json`, `node_modules`). Reviewed 2026-11-22. Downloaded content is untrusted: never run its scripts from the clone directory.

| Skill (installed name) | Source | Reviewed commit | License | Carlos uses it for |
|---|---|---|---|---|
| `owasp-security` | https://github.com/agamm/claude-code-owasp (`.claude/skills/owasp-security`) | `1ae29cb22518560e3625d77f2ae64f61647d9201` | MIT | Security review of API, auth, sessions, per-account isolation (OWASP Top 10:2025, ASVS 5.0, LLM/agent Top 10) |
| `sharp-edges` | https://github.com/trailofbits/skills (`plugins/sharp-edges/skills/sharp-edges`) | `149d7b21f4067765b82e67029730b42d228ef4b4` | CC BY-SA 4.0 (Trail of Bits; repo-root LICENSE copied in) | Footgun review of API design and configuration (tokens, `X-Carlos-Account`, controlled codes) |
| `differential-review` | https://github.com/trailofbits/skills (`plugins/differential-review/skills/differential-review`) | `149d7b21f4067765b82e67029730b42d228ef4b4` | CC BY-SA 4.0 | Security review of a PR or commit before merge. Its optional `differential-review:adversarial-modeler` agent belongs to the plugin and is not installed, so skip that step |
| `legal-audit` (folder `skills/gdpr-dsgvo` upstream) | https://github.com/waldo-van-der-code/deutsches-recht-mit-claude | `814b0d11e2ba7788a481655dce22c45bed2da3b2` | MIT | GDPR/DSGVO, Impressum, cookie and privacy-text checks for the public deployment. Not legal advice. Optional MCP `rechtsinformationen-bund-de` NOT installed (falls back to built-in knowledge and says so) |
| `bfsg-check` (folder `skills/bfsg` upstream) | same repo and commit | `814b0d11e2ba7788a481655dce22c45bed2da3b2` | MIT | Accessibility check of `static/` against BFSG / WCAG 2.1 AA |
| `webapp-testing` | https://github.com/anthropics/skills (`skills/webapp-testing`) | `e4bb5d960d87126ff3b3a8af1a104b7db67560ba` | Apache-2.0 (`LICENSE.txt`) | Drive the Carlos UI headless with Playwright. Prerequisite (not installed): `pacman -S python-playwright` (Arch) or `pip install playwright && playwright install chromium`; see the caveat on `with_server.py` below. `with_server.py` runs the given command with `shell=True`. The examples write to `/mnt/user-data/outputs/`; change the path |

**Caveats (second review, 2026-11-22; all six folders are byte-identical to the pinned commits apart from the added LICENSE):**
- `differential-review`: **locally modified**: `allowed-tools` trimmed to read-only git commands (upstream pre-approves `Write` and unrestricted `Bash` on untrusted diffs). Use `git grep`, never `grep -r .` (it would walk `data/`, `.env` and `.claude/worktrees/`); never let it `git checkout` a baseline in the main checkout; write its report outside the repo root. Re-apply the trim after any update.
- `owasp-security`: reference only; ignore its Argon2, MFA and IaC advice (Carlos uses scrypt, stdlib only). Its "audit this" trigger overlaps `research-audit`.
- `sharp-edges`: its `sharp-edges-analyzer` agent is not installed; the skill works without it.
- `legal-audit`: answers in German; Impressum and privacy templates need the owner's name and address, keep them as placeholders and never put owner data in this repository. Its greps miss `.js` and `.py`. Overlaps `source-terms-register`; output is a question list for a lawyer.
- `bfsg-check`: low fit (greps tsx/jsx/html only, WebFetch cannot reach localhost); use as a checklist only.
- `webapp-testing`: usable (its Playwright patterns for clicking, screenshots and console logs are what a user-simulating test needs), **except its helper `scripts/with_server.py`, which must not be used on Carlos** (it does not notice a taken port and would test the real server, never drains the server's pipes, and `app.py` without `CARLOS_DATA` migrates the real database). Use `carlos-ui-sweep`, which starts a throwaway fixture server. On Arch `pip install` is blocked: use `pacman -S python-playwright` (Chromium is `/usr/bin/chromium`).
- Vendored, locally modified, no pinned reinstall: `web-design-guidelines` (routed in AGENTS.md), `impeccable` (use only craft-floor, operate mode and the task references: never `init`, `new-work`, `document`, hooks or `doctor`, which write PRODUCT.md, DESIGN.md, `.impeccable/` or settings hooks), `ui-ux-pro-max` (not routed: its data recommends CDN fonts, Tailwind and GSAP, and `--persist` writes into the cwd).
- Licence: copying CC BY-SA 4.0 files (Trail of Bits) into `~/.claude/skills` for the owner's own use triggers no share-alike; giving the folder to others needs the licence, credit and a note of changes. **Do not copy or paraphrase Trail of Bits text into this AGPL-3.0 repository**; names, URLs, SHAs and install commands are fine.

Not installed from the Trail of Bits repo: `insecure-defaults`. It is a command plus workflow plugin (`/insecure-defaults:audit`, needs the `Workflow` tool, `${CLAUDE_PLUGIN_ROOT}` and Opus sub-agents) with no `SKILL.md`, so it cannot be a plain user skill. Install it with `/plugin install` only if the owner wants it.

## Reinstall on another machine

Pinned to the reviewed commits. Save the block as a file and run it with `bash` (its `set -e` would close an interactive shell). Clone into an empty directory, copy only the skill folder, then delete the clone. **The last step re-applies the local trim of `differential-review`'s `allowed-tools`.**

```bash
set -euo pipefail
T=$(mktemp -d); S=~/.claude/skills; mkdir -p $S
for n in owasp-security sharp-edges differential-review legal-audit bfsg-check webapp-testing; do [ -e $S/$n ] && { echo "$S/$n exists: remove it first (cp -r would nest)"; exit 1; }; done
# owasp-security
git clone https://github.com/agamm/claude-code-owasp $T/owasp && git -C $T/owasp checkout 1ae29cb22518560e3625d77f2ae64f61647d9201
cp -r $T/owasp/.claude/skills/owasp-security $S/owasp-security && cp $T/owasp/LICENSE $S/owasp-security/
# Trail of Bits: sharp-edges, differential-review
git clone https://github.com/trailofbits/skills $T/tob && git -C $T/tob checkout 149d7b21f4067765b82e67029730b42d228ef4b4
for n in sharp-edges differential-review; do cp -r $T/tob/plugins/$n/skills/$n $S/$n && cp $T/tob/LICENSE $S/$n/; done
# legal-audit, bfsg-check
git clone https://github.com/waldo-van-der-code/deutsches-recht-mit-claude $T/legal && git -C $T/legal checkout 814b0d11e2ba7788a481655dce22c45bed2da3b2
cp -r $T/legal/skills/gdpr-dsgvo $S/legal-audit && cp $T/legal/LICENSE $S/legal-audit/
cp -r $T/legal/skills/bfsg $S/bfsg-check && cp $T/legal/LICENSE $S/bfsg-check/
# webapp-testing
git clone https://github.com/anthropics/skills $T/anth && git -C $T/anth checkout e4bb5d960d87126ff3b3a8af1a104b7db67560ba
cp -r $T/anth/skills/webapp-testing $S/webapp-testing
sed -i 's/^allowed-tools: .*/allowed-tools: Read Grep Glob Bash(git log:*) Bash(git diff:*) Bash(git show:*) Bash(git blame:*) Bash(git grep:*)/' $S/differential-review/SKILL.md
rm -rf $T
```

Check afterwards that each `SKILL.md` still has `name` and `description` frontmatter and that no skill directory was overwritten. To update, review the new diff first, then change the SHA here.

## Built in or from plugins (not in this repository, not installable from here)
`dataviz`, `code-review`, `simplify`, `security-review` and `ponytail:*` come with Claude Code or its plugins (`/plugin`); `ponytail` and `frontend-design` are plugins. On a new machine check `/skills` lists them. `impeccable` and `web-design-guidelines` are vendored locally with changes and have no pinned reinstall: copy `~/.claude/skills/impeccable` and `~/.claude/skills/web-design-guidelines` from the old machine (a follow-up may commit them if their licences allow).

## Reviewed, rejected

Screened by the owner before this install; not re-reviewed in this pass.

- Trail of Bits `fp-check`: ships hooks.
- Trail of Bits `supply-chain-risk-auditor`: not approved.
- AccessLint: MCP server config with an unpinned package.
- `knowledge-work-plugins`: MCP connectors to external services.
- Sushegaad skills: opaque `.skill` zip archives that cannot be read before install.
- ThomasMoreAI skills: mass-generated content.

## Carlos project skills

Committed in `.claude/skills/` (they follow the repository). AGENTS.md ("Skills: loaded automatically") routes them by kind of change.

| Skill | Loads on | Purpose |
|---|---|---|
| `carlos-ui-contract` | any change under `static/`, UI copy | House rules (unknown is pending never 0, codes via `tv()`, partial totals, tokens, a11y and touch rules) and the Definition of Done |
| `carlos-i18n-check` | language files, `t()`/`tv()`, fixed codes, number formatting | `scripts/i18n_check.py`: key parity, placeholders, codes block, hard-coded literals |
| `carlos-ui-sweep` | before a UI change is called done | `scripts/sweep.py`: routes x EN/DE/PL x light/dark x 1280/390 px on a throwaway fixture server (needs Playwright) |
| `research-audit` | research output, prompts, protocol, contract | Evenness yardstick and `scripts/evenness.py` (read-only), NONE FOUND / N/A rules, prompt-change protocol, known contradictions |
| `carlos-threat-model` | server, auth, agent API, worker, capture, requests, prompts that read pages | Trust boundaries, must-check list, open security findings |
| `source-terms-register` | new source, automation, personal data, licences | Register of sites and terms (NOT VERIFIED where unknown), question list for a lawyer |
