from __future__ import annotations

"""The single configuration surface: ``~/.cclenzz/config.toml``. Parsing plus a
frozen ``Settings`` record that replaces the mutable ``CLAUDE_BIN`` /
``*_MODEL_DEFAULT`` / ``PERSIST_ENABLED`` / ``STATE_RETENTION_DAYS`` globals.

``tomllib`` is imported locally inside ``load_config`` (as before), keeping this
module import-safe on pre-3.11 interpreters for the version-gate path (§4)."""

import dataclasses
import os
import sys

# The complete set of recognized config keys — the guardrail that makes a
# single-surface, hand-editable config safe (an unknown key is a warning, not a
# silent no-op). Keep this in sync with CONFIG_TEMPLATE and write_config.
CONFIG_KEYS = {"theme", "icons", "color", "auto_audit", "audit_model",
               "explain_model", "interval", "ambiwidth", "projects_glob",
               "claude_bin", "persist", "state_retention_days"}


def load_config(config_path):
    """Parse ~/.cclenzz/config.toml. Absent file → {}. Malformed TOML is a hard
    error (degrade-never-crash applies to session *data*, not the user's own
    config). Python >= 3.11 is guaranteed by the gate at the top of `main`."""
    path = config_path
    if not os.path.exists(path):
        return {}
    import tomllib
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except Exception as e:
        sys.stderr.write(f"cclenzz: bad config at {path}: {e}\n")
        raise SystemExit(1)
    for k in data:
        if k not in CONFIG_KEYS:
            sys.stderr.write(f"cclenzz: unknown config key {k!r} (ignored)\n")
    return data


@dataclasses.dataclass(frozen=True)
class Settings:
    claude_bin: str = "claude"
    audit_model: str = "opus"
    explain_model: str = "haiku"
    interval: float = 1.0
    auto_audit: bool = False
    persist: bool = True
    state_retention_days: "float | None" = None

    @classmethod
    def from_config(cls, cfg: dict) -> "Settings":
        """Reproduce `main`'s config-application rules exactly: truthy-check for
        claude_bin/audit_model/explain_model (empty string falls back to
        default), `"persist" in cfg` → bool, state_retention_days applied when
        not None, interval/auto_audit coerced with defaults."""
        claude_bin = cfg["claude_bin"] if cfg.get("claude_bin") else "claude"
        audit_model = cfg["audit_model"] if cfg.get("audit_model") else "opus"
        explain_model = cfg["explain_model"] if cfg.get("explain_model") else "haiku"
        persist = bool(cfg.get("persist")) if "persist" in cfg else True
        retention = None
        if cfg.get("state_retention_days") is not None:
            retention = cfg.get("state_retention_days")
        interval = float(cfg.get("interval", 1.0))
        auto_audit = bool(cfg.get("auto_audit", False))
        return cls(
            claude_bin=claude_bin, audit_model=audit_model,
            explain_model=explain_model, interval=interval,
            auto_audit=auto_audit, persist=persist,
            state_retention_days=retention,
        )
