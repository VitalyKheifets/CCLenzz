# Security Policy

## Supported versions

Only the **latest release** is supported. There are no backports — if you hit a
security issue, first confirm you're on the newest version (`cclenzz update`,
then `cclenzz --version`).

| Version | Supported |
|---|---|
| Latest release | ✅ |
| Anything older | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub security advisories:
[**Report a vulnerability**](https://github.com/VitalyKheifets/CCLenzz/security/advisories/new).
This is a solo-maintained project, so response is best-effort; you'll get an
acknowledgement as soon as the maintainer sees it, and a fix or explanation
follows once the report is triaged. Please give a reasonable window to address
the issue before any public disclosure.

Include, as far as you can: affected version (`cclenzz --version`), OS/terminal,
a minimal reproduction, and the impact you observed.

## Threat model

CCLenzz's design deliberately keeps the attack surface small — worth knowing
when you assess a report:

- **Read-only.** CCLenzz never writes under `~/.claude` and never modifies your
  session transcripts; it only tails and renders them. Diffs are reconstructed
  from logged tool input, never by reading the filesystem. All of its own state
  lives under `~/.cclenzz`.
- **No API keys, no endpoints.** CCLenzz holds no credentials and never calls a
  network endpoint itself. The optional intent audit shells out to *your* own
  `claude` CLI (already logged in on your `PATH`), running it with tools
  disabled and `--no-session-persistence` so it leaves no history behind.
- **Stdlib only.** No third-party runtime dependencies means no third-party
  supply chain in the shipped artifact. The distributed `cclenzz-<ver>.pyz` is a
  plain, inspectable Python zipapp, and `install.sh` verifies its SHA-256
  checksum against the published `SHA256SUMS` before installing.
- **Handling other people's data.** The parser is built to degrade rather than
  crash on malformed or schema-drifted transcripts. A crash on hostile input is
  a bug worth reporting; a way to make CCLenzz *write* outside `~/.cclenzz`, exfiltrate
  transcript contents, or execute unexpected code is a security issue.
