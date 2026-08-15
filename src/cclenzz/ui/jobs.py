from __future__ import annotations

"""Single-flight audit / explain managers (§5.8). Each encapsulates the old
``audit = {...}`` / ``explain = {...}`` dicts and their start/finish handling.
Thread creation stays inside (daemon threads); tests inject a synchronous fake
``Judge`` so completion is observable immediately."""

import threading
import time

from ..audit.explain import build_explain_context
from ..audit.transcript import build_audit_transcript
from ..glyphs import glyph
from ..persist import persist_audit, persist_explain
from .tabstate import Toast


class AuditJob:
    def __init__(self, judge, settings, paths):
        self.judge = judge
        self.settings = settings
        self.paths = paths
        self.status = None
        self.result = None
        self.index_map = {}
        self.prompt_map = {}
        self.tab = None
        self.started = 0.0
        self.cancel = None
        self.model = None

    def start(self, tab, caps):
        if self.status == "running":
            return Toast("audit already running…", "warn")
        transcript, index_map, prompt_map = build_audit_transcript(
            list(tab.items), tab.stream)
        if not transcript.strip():
            return Toast("nothing to audit here", "warn")
        tab.audit_signature = (len(tab.items), tab.last_mtime)
        tab.audit_dirty = False
        cancel = threading.Event()
        self.status = "running"
        self.result = None
        self.index_map = index_map
        self.prompt_map = prompt_map
        self.tab = tab
        self.started = time.time()
        self.cancel = cancel
        self.model = self.settings.audit_model
        model = self.settings.audit_model

        def work():
            res = self.judge.audit(transcript, model, cancel)
            self.result = res
            self.status = "done"
        threading.Thread(target=work, daemon=True).start()
        return Toast("auditing session…", "warn")

    def store_verdicts(self, tab, res):
        index_map = self.index_map
        prompt_map = self.prompt_map
        prev = tab.audit_by_prompt
        by_prompt = {}
        flagged = set()
        deltas = {}
        model = res.get("model")
        for v in res.get("verdicts") or []:
            if model and isinstance(v, dict):
                v.setdefault("model", model)
            pit = prompt_map.get(v.get("prompt_idx"))
            if pit is not None:
                by_prompt[id(pit)] = v
                old = prev.get(id(pit))
                if old is not None:
                    try:
                        d = int(v.get("alignment")) - int(old.get("alignment"))
                        if d:
                            deltas[id(pit)] = (d, time.time())
                    except (TypeError, ValueError):
                        pass
            for fi in v.get("flagged_items") or []:
                tgt = index_map.get(fi)
                if tgt is not None:
                    flagged.add(id(tgt))
        tab.audit_by_prompt = by_prompt
        tab.audit_flagged = flagged
        tab.audit_deltas = deltas

    def consume_done(self, caps):
        """Apply a completed run: store verdicts, accrue cost, persist, and
        return {"toast": Toast|None, "beep": bool}. Re-fires once if the tab
        went dirty during the run."""
        def G(k):
            return glyph(k, caps)
        res = self.result
        self.status = None
        atab = self.tab
        out = {"toast": None, "beep": False}
        if res is not None and atab is not None:
            if res.get("cancelled"):
                out["toast"] = Toast(f"{G('read')} audit cancelled", "fg.dim")
            elif res.get("ok"):
                self.store_verdicts(atab, res)
                cost = res.get("cost")
                if isinstance(cost, (int, float)):
                    atab.audit_cost += cost
                persist_audit(self.paths, self.settings, atab, res,
                              self.index_map, self.prompt_map)
                el = int(time.time() - self.started)
                cs = f" · ${cost:.2f}" if isinstance(cost, (int, float)) else ""
                out["toast"] = Toast(
                    f"{G('live')} audit · {len(res.get('verdicts') or [])} "
                    f"verdicts{cs} · {el}s", "ok")
                # dirty queue: re-fire once if a turn completed meanwhile
                if atab.audit_dirty:
                    out["toast"] = self.start(atab, caps)
            elif res.get("auth"):
                out["beep"] = True
                out["toast"] = Toast(
                    f"{G('warn')} {res.get('error')}", "error", ttl=20.0)
            else:
                out["toast"] = Toast(
                    f"{G('warn')} audit failed · "
                    f"{res.get('error') or 'unknown error'}", "error")
        return out


class ExplainJob:
    def __init__(self, judge, settings, paths):
        self.judge = judge
        self.settings = settings
        self.paths = paths
        self.status = None
        self.item = None
        self.tab = None
        self.cancel = None
        self.started = 0.0
        self.result = None

    def start(self, tab, item, caps):
        def G(k):
            return glyph(k, caps)
        if self.status == "running":
            if self.item is item:
                self.cancel.set()
                return Toast(f"{G('read')} explain cancelled", "fg.dim")
            return Toast("explain busy — x to cancel", "warn")
        ctx = build_explain_context(item, tab)
        if not ctx.strip():
            return Toast("nothing to explain here", "fg.dim")
        cancel = threading.Event()
        self.status = "running"
        self.item = item
        self.tab = tab
        self.cancel = cancel
        self.started = time.time()
        self.result = None
        tab.explain[id(item)] = {"status": "running", "text": None,
                                 "rev": item.rev, "started": time.time(),
                                 "model": self.settings.explain_model}
        tab.expanded.add(id(item))      # auto-expand so the block is visible
        model = self.settings.explain_model

        def work():
            res = self.judge.explain(ctx, model, cancel)
            self.result = res
            self.status = "done"
        threading.Thread(target=work, daemon=True).start()
        return Toast(f"{G('prompt')} explaining line…", "warn")

    def consume_done(self, caps, tabs):
        def G(k):
            return glyph(k, caps)
        res = self.result
        etab = self.tab
        eit = self.item
        self.status = None
        self.result = None
        self.item = None
        self.tab = None
        self.cancel = None
        out = {"toast": None}
        # Guard a tab closed (d) mid-request — drop the result silently.
        if res is not None and etab is not None and etab in tabs \
                and eit is not None:
            rec = etab.explain.get(id(eit))
            keep_rev = rec.get("rev") if rec else eit.rev
            keep_started = rec.get("started") if rec else time.time()
            if res.get("cancelled"):
                if rec is not None and rec.get("status") == "running":
                    etab.explain.pop(id(eit), None)
                out["toast"] = Toast(f"{G('read')} explain cancelled", "fg.dim")
            elif res.get("ok"):
                etab.explain[id(eit)] = {
                    "status": "done", "text": res.get("text"),
                    "rev": keep_rev, "started": keep_started,
                    "model": res.get("model")}
                cost = res.get("cost")
                if isinstance(cost, (int, float)):
                    etab.audit_cost += cost
                persist_explain(self.paths, self.settings, etab, eit,
                                etab.explain[id(eit)])
                cs = f" · ~${cost:.4f}" if isinstance(cost, (int, float)) else ""
                out["toast"] = Toast(f"{G('live')} explained{cs}", "fg.dim")
            else:
                etab.explain[id(eit)] = {
                    "status": "error", "text": res.get("error") or "unknown error",
                    "rev": keep_rev, "started": keep_started,
                    "model": res.get("model")}
                persist_explain(self.paths, self.settings, etab, eit,
                                etab.explain[id(eit)])
                out["toast"] = Toast(
                    f"{G('warn')} explain failed: "
                    f"{res.get('error') or 'unknown error'}", "warn")
        return out
