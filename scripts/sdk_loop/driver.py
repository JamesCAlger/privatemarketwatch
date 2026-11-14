"""The fund-loop state machine (spec sections 3, 6, 7, 8).

``Driver`` decides; ``Env`` acts (worktrees, gate, page sample, recording); ``Runner`` calls agents.
Tests pass a fake Env and a stub Runner, so every transition is tested without the API or a build.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Protocol

import orchestrator as orch
from agents import AgentResult, AgentSpec, Runner, load_prompt
from config import (AGENT_CAP_USD, BRIEF_DIR, MODELS, MAX_AGENT_ERRORS, MAX_BUILDS_PER_ROUND, MAX_INVESTIGATIONS,
                    MAX_ROUNDS, MAX_SHARED_FIXES, REPO, allowed_paths)
from policy import Policy
from state import Budget, FundState, Run


class StopRun(Exception):
    """Raised to end the run cleanly: run budget, orchestrator stop_run."""


class Env(Protocol):
    def prepare(self, run: Run, fs: FundState) -> dict: ...              # worktree, packet, snapshots
    def new_round(self, run: Run, fs: FundState) -> None: ...            # snapshots for the round
    def checks(self, run: Run, fs: FundState) -> dict: ...               # {"ok", "problems", "label"}
    def digest(self, run: Run, fs: FundState) -> str: ...
    def review_items(self, run: Run, fs: FundState) -> dict: ...         # {finding_id: reason} rejected
    def dispute_rulings(self, run: Run, fs: FundState) -> dict: ...      # {item: "upheld"|"overturned"}
    def draw_sample(self, run: Run, fs: FundState) -> dict: ...          # {"cards": path, "labels": path}
    def sample_items(self, run: Run, fs: FundState) -> dict: ...         # {row_id: note} published errors
    def final_gate(self, run: Run, fs: FundState) -> dict: ...           # {"ok", "problems"}
    def record(self, run: Run, fs: FundState) -> dict: ...               # decisions + commit
    def open_observation_keys(self, run: Run) -> list[dict]: ...
    def observation_outcome(self, run: Run, key: str) -> dict: ...
    def prepare_shared(self, run: Run, key: str) -> dict: ...            # {"worktree"}
    def shared_fix_checks(self, run: Run, key: str) -> dict: ...


def _fp(text: str) -> str:
    """Fingerprint of a rejection reason: same words, same fingerprint."""
    words = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()
    return hashlib.sha1(" ".join(words[:25]).encode()).hexdigest()[:10]


class Driver:
    def __init__(self, run: Run, runner: Runner, env: Env, budget: Budget, *, today: str | None = None):
        self.run, self.runner, self.env, self.budget = run, runner, env, budget
        self.today = today or dt.date.today().isoformat()

    # --- agent calls ---------------------------------------------------------
    def actor(self, role: str, fs_or_key: str) -> str:
        return "agent:sdk-%s-%s-%s" % (role.replace("_", ""), fs_or_key[-6:], self.run.meta.get("run_id", "x")[-6:])

    def call(self, spec: AgentSpec, fs: FundState | None) -> AgentResult:
        ok, why = self.budget.allows(spec.role, fs)
        if not ok:
            if why.startswith("run budget"):
                raise StopRun(why)
            return AgentResult(ok=False, exit="fund_budget", summary=why)
        spec.max_budget_usd = self.budget.agent_cap(spec.role, fs)
        result = self.runner(spec)
        self.run.log_call({"role": spec.role, "cik": spec.cik, "round": fs.round if fs else "",
                           "model": MODELS.get(spec.role, ""), "cost_usd": round(result.cost_usd, 4),
                           "input_tokens": result.usage.get("input_tokens", ""),
                           "output_tokens": result.usage.get("output_tokens", ""),
                           "cache_read_tokens": result.usage.get("cache_read_input_tokens", ""),
                           "cache_write_tokens": result.usage.get("cache_creation_input_tokens", ""),
                           "turns": result.turns, "duration_s": result.duration_s, "exit": result.exit})
        if fs is not None:
            fs.cost_usd += result.cost_usd
            self.run.save_fund(fs)
        return result

    def decide(self, point: str, fs: FundState, default_action: str, items_known: set[str] | None = None) -> dict:
        prompt = load_prompt("orchestrator", point=point, cik=fs.cik, round=fs.round, max_rounds=MAX_ROUNDS,
                             fund_dir=self.run.fund_dir(fs.cik).as_posix(), default_action=default_action,
                             available=", ".join(orch.POINTS[point]))
        spec = AgentSpec(role="orchestrator", task="Decide at %s for fund %s." % (point, fs.cik), prompt=prompt,
                         cwd=self.run.fund_dir(fs.cik), out_dir=self.run.round_dir(fs.cik, fs.round), cik=fs.cik,
                         policy=Policy(role="orchestrator", read_roots=(self.run.folder, REPO)),
                         output_schema=orch.SCHEMA)
        result = self.call(spec, fs)
        decision = orch.enforce(point, result.structured if result.ok else None, round_no=fs.round, items_known=items_known)
        self.run.log_decision({"cik": fs.cik, "round": fs.round, "point": point, "proposal": result.structured,
                               "enforced": decision})
        if decision["decision"] == "stop_run":
            raise StopRun("orchestrator: " + decision["reason"])
        return decision

    # --- per-fund stages -----------------------------------------------------
    def run_fund(self, cik: str) -> FundState:
        fs = self.run.load_fund(cik)
        while not fs.done:
            before = (fs.stage, fs.round)
            getattr(self, "stage_" + fs.stage)(fs)
            self.run.save_fund(fs)
            if (fs.stage, fs.round) == before and not fs.done:
                continue  # a retried stage; errors are counted inside
        return fs

    def _error(self, fs: FundState, stage: str, result: AgentResult) -> bool:
        """Count an agent error; True when the fund is now failed."""
        fs.errors[stage] = fs.errors.get(stage, 0) + 1
        if fs.errors[stage] >= MAX_AGENT_ERRORS:
            fs.move("failed", "%s errored %d times: %s" % (stage, fs.errors[stage], result.summary[:200]))
            return True
        return False

    def stage_queued(self, fs: FundState) -> None:
        info = self.env.prepare(self.run, fs)
        if info.get("skip"):
            fs.move("parked", info["skip"])
            return
        fs.worktree, fs.branch, fs.before = info.get("worktree"), info.get("branch"), info.get("before")
        self.env.new_round(self.run, fs)
        fs.move("fund_agent", "prepared")

    def _fund_policy(self, fs: FundState) -> Policy:
        wt = Path(fs.worktree) if fs.worktree else REPO
        return Policy(role="fund_agent", worktree=wt, allowed_res=allowed_paths(fs.cik),
                      write_roots=(self.run.round_dir(fs.cik, fs.round),), read_roots=(wt, REPO, self.run.folder),
                      shell=True, max_builds=MAX_BUILDS_PER_ROUND)

    def stage_fund_agent(self, fs: FundState) -> None:
        rd = self.run.round_dir(fs.cik, fs.round)
        returned = ""
        if fs.returned or fs.notes:
            returned = "## Returned to you (round %d)\n\nAnswer every item: fixed (with a new build) or contested with new evidence.\n\n" % fs.round
            returned += "\n".join("- %s" % r for r in fs.returned)
            if fs.notes:
                returned += "\n\nGuidance from the orchestrator:\n" + "\n".join("- %s" % n for n in fs.notes)
        wt = fs.worktree or str(REPO)
        prompt = load_prompt(
            "fund_agent", cik=fs.cik, round=fs.round, max_rounds=MAX_ROUNDS, builds_left=MAX_BUILDS_PER_ROUND,
            worktree=wt, batch=self.run.meta.get("batch", ""), packet=(self.run.fund_dir(fs.cik) / "packet.csv").as_posix(),
            label_prefix=self.run.meta.get("label_prefix", {}).get(fs.cik, "s"), before=fs.before or "none",
            report=(rd / "report.json").as_posix(), verdicts=(rd / "verdicts.json").as_posix(),
            returned=returned, actor=self.actor("fund_agent", fs.cik), today=self.today,
            brief=(BRIEF_DIR / "fund-agent-brief.md").read_text(encoding="utf-8"),
            investigation_contract=(BRIEF_DIR / "investigation-review.md").read_text(encoding="utf-8"))
        spec = AgentSpec(role="fund_agent", task="Clear fund %s (round %d) as instructed." % (fs.cik, fs.round),
                         prompt=prompt, cwd=Path(wt), policy=self._fund_policy(fs), out_dir=rd, cik=fs.cik,
                         label=None, repo=Path(wt))
        spec.label = self.env_latest_label(fs)
        result = self.call(spec, fs)
        if result.exit == "fund_budget":
            fs.move("parked", result.summary)
            return
        if not result.ok and result.exit in ("error", "no_result"):
            self._error(fs, "fund_agent", result)
            return
        fs.errors.pop("fund_agent", None)
        if result.exit not in ("success",):  # ran out of turns or budget: let the orchestrator weigh in
            d = self.decide("agent_stopped", fs, "run the checks on what the agent left")
            if d["decision"] in ("park", "ask_owner"):
                if d["question"]:
                    self.run.add_owner_question(fs.cik, d["question"])
                fs.move("parked", "orchestrator after agent stop: " + d["reason"])
                return
        fs.move("checks", "fund agent finished: " + result.exit)

    def env_latest_label(self, fs: FundState) -> str | None:
        return fs.labels[-1] if fs.labels else fs.before

    def stage_checks(self, fs: FundState) -> None:
        res = self.env.checks(self.run, fs)
        if res.get("label"):
            if res["label"] not in fs.labels:
                fs.labels.append(res["label"])
        (self.run.round_dir(fs.cik, fs.round) / "checks.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        if res["ok"]:
            fs.move("review", "checks passed")
            return
        d = self.decide("after_checks", fs, "return the failed checks to the fund agent")
        self._route_rejection(fs, {"check: " + p: p for p in res["problems"]}, d)

    def stage_review(self, fs: FundState, disputes: dict | None = None) -> None:
        rd = self.run.round_dir(fs.cik, fs.round)
        mode = "full" if fs.round == 1 and not disputes else ("dispute" if disputes else "change-only")
        change_only = ""
        if mode == "change-only":
            prev = self.run.round_dir(fs.cik, fs.round - 1) / "review.json"
            change_only = ("Change-only re-review. Previous review: `%s`. Items returned last round: %s. Review those "
                           "items and every finding whose rows the new build changed; round-1 approvals of unchanged "
                           "rows carry forward (copy them into your review)." % (prev.as_posix(), "; ".join(fs.returned)[:3000]))
        if disputes:
            change_only = "Rule on these disputed items (write `disputes` in your review): " + json.dumps(disputes)[:4000]
        prompt = load_prompt("reviewer", cik=fs.cik, round=fs.round, mode=mode, worktree=fs.worktree or str(REPO),
                             label=self.env_latest_label(fs) or "", report=(rd / "report.json").as_posix(),
                             verdicts=(rd / "verdicts.json").as_posix(), digest=self.env.digest(self.run, fs),
                             review=(rd / ("review_dispute.json" if disputes else "review.json")).as_posix(),
                             actor=self.actor("reviewer", fs.cik), change_only=change_only,
                             investigation_contract=(BRIEF_DIR / "investigation-review.md").read_text(encoding="utf-8"))
        wt = Path(fs.worktree) if fs.worktree else REPO
        spec = AgentSpec(role="reviewer", task="Review fund %s, round %d (%s)." % (fs.cik, fs.round, mode), prompt=prompt,
                         cwd=wt, out_dir=rd, cik=fs.cik, label=self.env_latest_label(fs), repo=wt,
                         policy=Policy(role="reviewer", write_roots=(rd,), read_roots=(wt, REPO, self.run.folder)))
        result = self.call(spec, fs)
        if result.exit == "fund_budget":
            fs.move("parked", result.summary)
            return
        if not result.ok and result.exit in ("error", "no_result"):
            self._error(fs, "review", result)
            return
        fs.errors.pop("review", None)
        if disputes:
            return
        rejected = self.env.review_items(self.run, fs)
        if rejected:
            d = self.decide("after_review", fs, "return the rejected items to the fund agent", items_known=set(rejected))
            if d["decision"] == "dispute_to_reviewer" and not fs.history_has("dispute", fs.round):
                fs.history.append([dt.datetime.now().isoformat(timespec="seconds"), "review", "review", "dispute r%d" % fs.round])
                self.stage_review(fs, disputes={i: rejected[i] for i in d["items"]})
                rulings = self.env.dispute_rulings(self.run, fs)
                rejected = {i: r for i, r in rejected.items() if rulings.get(i) != "overturned"}
                if not rejected:
                    fs.move("sample", "disputes overturned every rejection")
                    return
                d = {"decision": "continue", "notes": "", "question": "", "reason": "after dispute"}
            self._route_rejection(fs, rejected, d)
            return
        fs.move("sample", "review supported every item")

    def stage_sample(self, fs: FundState) -> None:
        rd = self.run.round_dir(fs.cik, fs.round)
        paths = self.env.draw_sample(self.run, fs)
        prompt = load_prompt("reader", cards=paths["cards"], labels=paths["labels"],
                             reader_brief=paths.get("brief_text", ""))
        wt = Path(fs.worktree) if fs.worktree else REPO
        spec = AgentSpec(role="reader", task="Label the sample cards for fund %s." % fs.cik, prompt=prompt, cwd=wt,
                         out_dir=rd, cik=fs.cik, repo=wt,
                         policy=Policy(role="reader", write_roots=(Path(paths["labels"]).parent,), read_roots=(wt, REPO, self.run.folder)))
        result = self.call(spec, fs)
        if result.exit == "fund_budget":
            fs.move("parked", result.summary)
            return
        if not result.ok and result.exit in ("error", "no_result"):
            self._error(fs, "sample", result)
            return
        fs.errors.pop("sample", None)
        flags = self.env.sample_items(self.run, fs)
        gate = self.env.final_gate(self.run, fs)
        rejected = {"sample " + k: v for k, v in flags.items()}
        rejected.update({"gate: " + p: p for p in gate.get("problems", [])})
        if not rejected:
            out = self.env.record(self.run, fs)
            (rd / "recorded.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
            fs.move("recorded", "review, sample and gate passed")
            return
        d = self.decide("after_review", fs, "return the sample flags and gate problems to the fund agent",
                        items_known=set(flags))
        if d["decision"] == "recheck_sample_row":
            self.stage_review(fs, disputes={i: flags[i] for i in d["items"]})
            rulings = self.env.dispute_rulings(self.run, fs)
            rejected = {k: v for k, v in rejected.items() if not (k.startswith("sample ") and rulings.get(k[7:]) == "overturned")}
            if not rejected:
                out = self.env.record(self.run, fs)
                (rd / "recorded.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
                fs.move("recorded", "sample flags overturned by the reviewer")
                return
            d = {"decision": "continue", "notes": "", "question": "", "reason": "after recheck"}
        self._route_rejection(fs, rejected, d)

    def _route_rejection(self, fs: FundState, rejected: dict, d: dict) -> None:
        """Back to the fund agent, park, or ask the owner (spec section 6)."""
        if d["decision"] == "park":
            fs.move("parked", "orchestrator: " + d["reason"])
            return
        if d["decision"] == "ask_owner":
            self.run.add_owner_question(fs.cik, d["question"] + " (items: %s)" % ", ".join(d.get("items") or [])[:300])
            if set(d.get("items") or []) >= set(rejected):
                fs.move("parked", "owner question: " + d["question"][:200])
                return
            rejected = {k: v for k, v in rejected.items() if k not in set(d.get("items") or [])}
        stuck = []
        for item, reason in rejected.items():
            prints = fs.rejections.setdefault(item, [])
            fp = _fp(reason)
            if fp in prints:
                stuck.append(item)
            prints.append(fp)
        if stuck:
            for item in stuck:
                self.run.add_owner_question(fs.cik, "stuck: %s rejected twice for the same reason: %s" % (item, rejected[item][:300]))
            fs.move("parked", "same item rejected twice with the same reason: %s" % ", ".join(stuck)[:300])
            return
        if fs.round >= MAX_ROUNDS:
            for item, reason in rejected.items():
                self.run.add_owner_question(fs.cik, "after %d rounds: %s: %s" % (MAX_ROUNDS, item, reason[:300]))
            fs.move("parked", "round limit %d reached with %d items open" % (MAX_ROUNDS, len(rejected)))
            return
        fs.returned = ["%s: %s" % (k, v[:600]) for k, v in rejected.items()]
        fs.notes = [d["notes"]] if d.get("notes") else []
        fs.round += 1
        self.env.new_round(self.run, fs)
        fs.move("fund_agent", "returned %d items" % len(rejected))

    # --- the run ---------------------------------------------------------------
    def run_all(self, ciks: list[str], observations: bool = False) -> dict:
        summary = {"funds": {}, "stopped": ""}
        try:
            for cik in ciks:
                fs = self.run_fund(cik)
                summary["funds"][cik] = {"stage": fs.stage, "round": fs.round, "cost": round(fs.cost_usd, 2),
                                         "reason": fs.stop_reason, "branch": fs.branch}
            if observations:
                summary["observations"] = self.observation_loop()
        except StopRun as exc:
            summary["stopped"] = str(exc)
        summary["spent"] = round(self.run.spent(), 2)
        self.run.meta["summary"] = summary
        self.run.save_meta()
        return summary

    # --- loop 2 -------------------------------------------------------------------
    def observation_loop(self) -> list[dict]:
        out, fixes = [], 0
        for entry in self.env.open_observation_keys(self.run)[:MAX_INVESTIGATIONS]:
            key = entry["key"]
            od = self.run.folder / "observations" / re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:60]
            od.mkdir(parents=True, exist_ok=True)
            pseudo = FundState(cik=entry.get("cik", "cohort"))
            inv = od / "investigation.json"
            spec = AgentSpec(role="investigator", task="Investigate observation key %s." % key, out_dir=od, cwd=REPO,
                             prompt=load_prompt("investigator", key=key, entries=entry["entries_path"], out=inv.as_posix()),
                             policy=Policy(role="investigator", write_roots=(od,), read_roots=(REPO, self.run.folder)),
                             cik=entry.get("cik", ""))
            res = self.call(spec, None)
            if not res.ok:
                out.append({"key": key, "outcome": "investigator_error", "detail": res.summary[:200]})
                continue
            spec = AgentSpec(role="reviewer", task="Review the investigation of %s." % key, out_dir=od, cwd=REPO,
                             prompt=load_prompt("investigation_review", key=key, investigation=inv.as_posix(),
                                                review=(od / "review.json").as_posix()),
                             policy=Policy(role="reviewer", write_roots=(od,), read_roots=(REPO, self.run.folder)),
                             cik=entry.get("cik", ""))
            self.call(spec, None)
            outcome = self.env.observation_outcome(self.run, key)
            if outcome["route"] == "shared" and fixes < MAX_SHARED_FIXES:
                fixes += 1
                outcome["shared_fix"] = self.shared_fix(key, od, pseudo)
            out.append({"key": key, **outcome})
        (self.run.folder / "observations" / "summary.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
        return out

    def shared_fix(self, key: str, od: Path, pseudo: FundState) -> dict:
        info = self.env.prepare_shared(self.run, key)
        wt = Path(info["worktree"])
        spec = AgentSpec(role="shared_fix", task="Fix the shared cause of %s." % key, out_dir=od, cwd=wt, repo=wt,
                         prompt=load_prompt("shared_fix", investigation=(od / "investigation.json").as_posix(),
                                            worktree=wt.as_posix(), report=(od / "fix_report.json").as_posix()),
                         policy=Policy(role="shared_fix", worktree=wt, allowed_res=(r"^pipeline/", r"^scripts/", r"^tests/", r"^schemas/", r"^scratch/"),
                                       write_roots=(od,), read_roots=(wt, REPO, self.run.folder), shell=True,
                                       max_builds=MAX_BUILDS_PER_ROUND))
        res = self.call(spec, None)
        if not res.ok:
            return {"outcome": "parked", "why": "shared-fix agent: " + res.exit}
        verdict = self.env.shared_fix_checks(self.run, key)
        return {"outcome": "branch_ready" if verdict.get("ok") else "parked", **{k: v for k, v in verdict.items() if k != "worktree"}}


def _history_has(self: FundState, word: str, round_no: int) -> bool:
    return any(word in (h[3] or "") and h[3].endswith("r%d" % round_no) for h in self.history)


FundState.history_has = _history_has
