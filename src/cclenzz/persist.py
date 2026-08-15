from __future__ import annotations

"""Session-result persistence (FEATURE-session-persistence.md §3, §5, §6, §9-§11).

Every path here is joined only from ``paths.state_root``; no write path is ever
built from the projects glob, ``session.path``, or any ``~/.claude`` prefix (§10
hard invariant). Every operation degrades to "as if there were no cache" — never
a traceback. ``persist`` and ``retention`` are read from the injected
``Settings``; the state root and live-set glob from the injected ``AppPaths``."""

import glob
import json
import os
import time
from datetime import datetime, timezone

from . import VERSION
from .configwrite import _atomic_write_text
from .identity import (_prompt_ordinal_of, build_key_index, item_key, item_sig)

SCHEMA_VERSION = 1               # per-session sidecar schema (§3.3)
ORPHAN_PRUNE_CAP = 200           # cap sidecars pruned per launch so startup stays fast


def session_state_path(paths, session):
    # session.path is  ~/.claude/projects/<slug>/<session-id>.jsonl — reuse the
    # SAME <slug> Claude used (the parent dir name) so the mirror is exact and we
    # never re-derive a slug from cwd (§3.2).
    slug = os.path.basename(os.path.dirname(session.path))
    sid = session.session_id
    return os.path.join(paths.sessions_state_dir(), slug, f"{sid}.json")


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_doc(session):
    slug = os.path.basename(os.path.dirname(session.path))
    return {
        "schema": SCHEMA_VERSION,
        "cclenzz_version": VERSION,
        "session_id": session.session_id,
        "project_slug": slug,
        "updated_at": iso_now(),
        "cost_usd": 0.0,
        "audit": {},
        "explain": {},
    }


def load_session_doc(paths, settings, session):
    """Parsed sidecar dict, or None on missing/unreadable/invalid file (§11)."""
    if not settings.persist:
        return None
    path = session_state_path(paths, session)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _atomic_write_json(settings, path, doc):
    """Best-effort atomic JSON write for the disposable sidecar cache; swallows
    errors (a failed cache write must never crash the TUI)."""
    if not settings.persist:
        return
    try:
        _atomic_write_text(path, json.dumps(doc, ensure_ascii=False, indent=2))
    except OSError:
        pass


def write_session_doc(paths, settings, session, doc):
    doc["updated_at"] = iso_now()
    doc["cclenzz_version"] = VERSION
    doc["schema"] = SCHEMA_VERSION
    _atomic_write_json(settings, session_state_path(paths, session), doc)


def _fresh_doc_for(paths, settings, session):
    """Load the current sidecar, or start fresh — discarding an unknown/newer
    schema rather than merging into an incompatible shape (§11 v1 tradeoff)."""
    doc = load_session_doc(paths, settings, session)
    if not doc or doc.get("schema") != SCHEMA_VERSION:
        return new_doc(session)
    return doc


def _verdict_view(v):
    """A persisted verdict, reshaped into exactly what the render path reads
    (the same fields store_verdicts puts into tab.audit_by_prompt)."""
    return {
        "ask": v.get("ask"),
        "delivered": v.get("delivered"),
        "alignment": v.get("alignment"),
        "confidence": v.get("confidence"),
        "reason": v.get("reason"),
        "defects": v.get("defects") or [],
        "evidence_gaps": v.get("evidence_gaps") or [],
        "scope": v.get("scope"),
        "model": v.get("model"),
    }


def persist_audit(paths, settings, tab, res, index_map, prompt_map):
    """Write the whole-session audit verdicts to the sidecar (§5.1). Called only
    on a successful audit; the newest audit supersedes the last."""
    if not settings.persist:
        return
    ord_of = {id(p): n for n, p in prompt_map.items()}
    verdicts = []
    for v in res.get("verdicts") or []:
        p = prompt_map.get(v.get("prompt_idx"))
        if p is None:
            continue
        flagged_keys = []
        for fi in v.get("flagged_items") or []:
            tgt = index_map.get(fi)
            k = item_key(tgt, ord_of.get(id(tgt))) if tgt is not None else None
            if k:
                flagged_keys.append(k)
        pk = item_key(p, ord_of.get(id(p)))
        if not pk:
            continue
        verdicts.append({
            "prompt_key": pk,
            "ask": v.get("ask"), "delivered": v.get("delivered"),
            "alignment": v.get("alignment"), "confidence": v.get("confidence"),
            "reason": v.get("reason"), "defects": v.get("defects") or [],
            "evidence_gaps": v.get("evidence_gaps") or [],
            "scope": v.get("scope"), "model": v.get("model"),
            "flagged_item_keys": flagged_keys,
        })
    doc = _fresh_doc_for(paths, settings, tab.session)
    sig = tab.audit_signature or (len(tab.items), tab.last_mtime)
    doc["audit"] = {
        "signature": {"n_items": sig[0], "last_mtime": sig[1]},
        "verdicts": verdicts,
    }
    doc["cost_usd"] = tab.audit_cost
    write_session_doc(paths, settings, tab.session, doc)


def persist_explain(paths, settings, tab, item, rec):
    """Write one explanation to the sidecar (§5.2). Never persists 'running'."""
    if not settings.persist:
        return
    if rec.get("status") not in ("done", "error"):
        return
    k = item_key(item, prompt_ordinal=_prompt_ordinal_of(tab, item))
    if not k:
        return
    doc = _fresh_doc_for(paths, settings, tab.session)
    doc.setdefault("explain", {})[k] = {
        "status": rec.get("status"), "text": rec.get("text"),
        "model": rec.get("model"),
        "item_rev": item.rev, "item_sig": item_sig(item),
        "created_at": iso_now(),
    }
    doc["cost_usd"] = tab.audit_cost
    write_session_doc(paths, settings, tab.session, doc)


def rehydrate(paths, settings, tab):
    """On tab open, restore verdicts, flags, explanations and cost from the
    sidecar back onto the very dicts the renderer reads (§6.1). Degrades to a
    no-op on any missing/unknown/unparseable sidecar."""
    if not settings.persist:
        return
    try:
        doc = load_session_doc(paths, settings, tab.session)
        if not doc or doc.get("schema") != SCHEMA_VERSION:
            return
        tab.stream.refresh()                         # ensure items exist
        idx = build_key_index(tab)

        # ---- audit ----
        a = doc.get("audit") or {}
        sig = a.get("signature") or {}
        if "n_items" in sig and "last_mtime" in sig:
            tab.audit_signature = (sig["n_items"], sig["last_mtime"])
        by_prompt, flagged = {}, set()
        for v in a.get("verdicts") or []:
            p = idx.get(v.get("prompt_key"))
            if p is None:
                continue                             # prompt no longer present
            by_prompt[id(p)] = _verdict_view(v)
            for fk in v.get("flagged_item_keys") or []:
                t = idx.get(fk)
                if t is not None:
                    flagged.add(id(t))
        tab.audit_by_prompt = by_prompt
        tab.audit_flagged = flagged
        tab.audit_deltas = {}                         # transient; always fresh-empty
        tab.audit_cost = doc.get("cost_usd") or 0.0   # audit + explain spend (§3.3)
        # stale-vs-current: identical comparison the runtime makes (§6.3)
        cur_sig = (len(tab.items), tab.last_mtime)
        tab.audit_dirty = (tab.audit_signature is not None
                           and cur_sig != tab.audit_signature)

        # ---- explain ----
        for k, rec in (doc.get("explain") or {}).items():
            it = idx.get(k)
            if it is None:
                continue
            stale = (rec.get("item_rev") != it.rev
                     or rec.get("item_sig") != item_sig(it))
            tab.explain[id(it)] = {
                "status": rec.get("status"),
                "text": rec.get("text"),
                "model": rec.get("model"),
                "rev": it.rev,                        # bind to the LIVE rev
                "started": time.time(),
                "stale": stale,
            }
    except Exception:
        # Never let a bad sidecar break tab creation.
        return


def prune_state(paths, settings, cap=ORPHAN_PRUNE_CAP):
    """Startup-only chore (§9): delete sidecars whose session JSONL is gone
    (orphan prune) or older than state_retention_days (age prune, opt-in).
    Best-effort, capped, never on the render hot path."""
    if not settings.persist:
        return
    try:
        live = {os.path.splitext(os.path.basename(p))[0]
                for p in glob.glob(paths.projects_glob)}
        root = paths.sessions_state_dir()
        cutoff = None
        if settings.state_retention_days:
            try:
                cutoff = time.time() - float(settings.state_retention_days) * 86400.0
            except (TypeError, ValueError):
                cutoff = None
        removed = 0
        for path in glob.glob(os.path.join(root, "*", "*.json")):
            if removed >= cap:
                break
            sid = os.path.splitext(os.path.basename(path))[0]
            drop = sid not in live
            if not drop and cutoff is not None:
                try:
                    drop = os.path.getmtime(path) < cutoff
                except OSError:
                    drop = False
            if drop:
                try:
                    os.unlink(path)
                    removed += 1
                except OSError:
                    pass
    except Exception:
        return
