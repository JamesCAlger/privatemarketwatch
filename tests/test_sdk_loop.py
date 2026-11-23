"""SDK fund loop (scripts/sdk_loop): state machine with stub agents and a fake environment, plus
policy, checks and orchestrator limits. No API call, no build, no write outside tmp_path."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "sdk_loop"))
sys.path.insert(0, str(ROOT / "scripts" / "sdk_review"))

import checks  # noqa: E402
import orchestrator as orch  # noqa: E402
from agents import AgentResult  # noqa: E402
from config import MAX_ROUNDS, allowed_paths  # noqa: E402
from driver import Driver  # noqa: E402
from policy import Policy, check_shell_fund  # noqa: E402
from state import Budget, Run  # noqa: E402

CIK = "0001786108"
CAPS = {"fund_agent": 8.0, "reviewer": 4.0, "reader": 1.0, "orchestrator": 1.0, "investigator": 5.0, "shared_fix": 8.0}


# --- fakes -----------------------------------------------------------------------
class FakeEnv:
    """Scripted outcomes by round. review[r] / sample[r] / checks[r] are dicts of rejected items."""

    def __init__(self, checks=None, review=None, sample=None, gate=None, rulings=None, observations=None, routes=None,
                 shared_ok=True, skip=""):
        self.checks_by_round = checks or {}
        self.review_by_round = review or {}
        self.sample_by_round = sample or {}
        self.gate_by_round = gate or {}
        self.rulings = rulings or {}
        self.observations = observations or []
        self.routes = routes or {}
        self.shared_ok = shared_ok
        self.skip = skip
        self.recorded = 0
        self.rounds_started = []

    def prepare(self, run, fs):
        return {"skip": self.skip} if self.skip else {"worktree": str(ROOT), "branch": "b", "before": "lbl0"}

    def new_round(self, run, fs):
        self.rounds_started.append(fs.round)

    def checks(self, run, fs):
        problems = self.checks_by_round.get(fs.round, [])
        return {"ok": not problems, "problems": problems, "label": "lbl%d" % fs.round}

    def digest(self, run, fs):
        return "d" * 64

    def review_items(self, run, fs):
        return dict(self.review_by_round.get(fs.round, {}))

    def dispute_rulings(self, run, fs):
        return dict(self.rulings)

    def draw_sample(self, run, fs):
        return {"cards": "c.md", "labels": str(run.folder / "labels.json")}

    def sample_items(self, run, fs):
        return dict(self.sample_by_round.get(fs.round, {}))

    def final_gate(self, run, fs):
        problems = self.gate_by_round.get(fs.round, [])
        return {"ok": not problems, "problems": problems}

    def record(self, run, fs):
        self.recorded += 1
        return {"commit": "abc"}

    def open_observation_keys(self, run):
        return self.observations

    def observation_outcome(self, run, key):
        return {"route": self.routes.get(key, "left_open")}

    def prepare_shared(self, run, key):
        return {"worktree": str(ROOT)}

    def shared_fix_checks(self, run, key):
        return {"ok": self.shared_ok, "problems": [] if self.shared_ok else ["moved an unpredicted fund"]}


class StubRunner:
    def __init__(self, cost=0.5, decisions=None, errors=None):
        self.cost, self.calls = cost, []
        self.decisions = list(decisions or [])        # orchestrator proposals, in order
        self.errors = dict(errors or {})              # role -> number of error results to return first

    def __call__(self, spec):
        self.calls.append((spec.role, spec.task, spec.prompt))
        if self.errors.get(spec.role, 0) > 0:
            self.errors[spec.role] -= 1
            return AgentResult(ok=False, exit="error", summary="boom")
        structured = None
        if spec.role == "orchestrator":
            structured = self.decisions.pop(0) if self.decisions else {"decision": "continue", "reason": "default"}
        return AgentResult(ok=True, cost_usd=self.cost, turns=3, exit="success", structured=structured)

    def roles(self):
        return [c[0] for c in self.calls]


def make(tmp_path, env, runner=None, run_cap=100.0, fund_cap=50.0):
    run = Run.create(tmp_path / "run", {"run_id": "20261114T000000", "batch": "b1", "label_prefix": {CIK: "y8108"}})
    runner = runner or StubRunner()
    return Driver(run, runner, env, Budget(run, run_cap, fund_cap, CAPS), today="2026-11-14"), runner, run


# --- state machine -------------------------------------------------------------------
def test_pass_first_round_records_once(tmp_path):
    d, runner, run = make(tmp_path, FakeEnv())
    fs = d.run_fund(CIK)
    assert fs.stage == "recorded" and fs.round == 1
    assert runner.roles() == ["fund_agent", "reviewer", "reader"]
    assert d.env.recorded == 1
    assert len(run.calls()) == 3 and abs(fs.cost_usd - 1.5) < 1e-9


def test_reject_then_pass_returns_items_to_fund_agent(tmp_path):
    d, runner, _ = make(tmp_path, FakeEnv(review={1: {"RVQ_1": "coverage misses two contexts"}}))
    fs = d.run_fund(CIK)
    assert fs.stage == "recorded" and fs.round == 2
    second_fund_prompt = [c[2] for c in runner.calls if c[0] == "fund_agent"][1]
    assert "Returned to you" in second_fund_prompt and "RVQ_1" in second_fund_prompt
    assert d.env.rounds_started == [1, 2]


def test_round_limit_parks_and_asks_owner(tmp_path):
    review = {r: {"RVQ_%d" % r: "different reason %d" % r} for r in range(1, MAX_ROUNDS + 1)}
    d, _, run = make(tmp_path, FakeEnv(review=review))
    fs = d.run_fund(CIK)
    assert fs.stage == "parked" and fs.round == MAX_ROUNDS and "round limit" in fs.stop_reason
    assert d.env.recorded == 0
    assert "after %d rounds" % MAX_ROUNDS in (run.folder / "owner_questions.md").read_text()


def test_same_rejection_twice_parks_early(tmp_path):
    same = {"RVQ_1": "the quote is not on the page"}
    d, _, _ = make(tmp_path, FakeEnv(review={1: same, 2: same, 3: same}))
    fs = d.run_fund(CIK)
    assert fs.stage == "parked" and fs.round == 2 and "same reason" in fs.stop_reason


def test_agent_errors_twice_marks_failed(tmp_path):
    d, runner, _ = make(tmp_path, FakeEnv(), runner=StubRunner(errors={"fund_agent": 2}))
    fs = d.run_fund(CIK)
    assert fs.stage == "failed" and "errored 2 times" in fs.stop_reason
    assert runner.roles() == ["fund_agent", "fund_agent"]


def test_one_error_then_success_continues(tmp_path):
    d, _, _ = make(tmp_path, FakeEnv(), runner=StubRunner(errors={"fund_agent": 1}))
    assert d.run_fund(CIK).stage == "recorded"


def test_run_budget_stops_cleanly_before_an_agent_call(tmp_path):
    d, runner, run = make(tmp_path, FakeEnv(), run_cap=3.0)   # fund agent expected 4.0 (half its cap)
    summary = d.run_all([CIK])
    assert "run budget" in summary["stopped"] and runner.calls == []
    assert run.load_fund(CIK).stage == "fund_agent"            # resumable


def test_fund_budget_parks_the_fund(tmp_path):
    d, _, _ = make(tmp_path, FakeEnv(review={1: {"RVQ_1": "x"}, 2: {"RVQ_2": "y"}}), fund_cap=6.0)
    fs = d.run_fund(CIK)
    assert fs.stage == "parked" and "fund budget" in fs.stop_reason


def test_agent_cap_never_exceeds_run_or_fund_left(tmp_path):
    d, _, run = make(tmp_path, FakeEnv(), run_cap=10.0, fund_cap=3.0)
    fs = run.load_fund(CIK)
    assert d.budget.agent_cap("fund_agent", fs) == 3.0


def test_resume_does_not_rerun_finished_stages(tmp_path):
    d, runner, run = make(tmp_path, FakeEnv())
    fs = run.load_fund(CIK)
    fs.move("review", "simulated crash after checks")
    fs.labels = ["lbl1"]
    run.save_fund(fs)
    fs = d.run_fund(CIK)
    assert fs.stage == "recorded" and "fund_agent" not in runner.roles()


def test_failed_checks_go_back_with_check_items(tmp_path):
    d, runner, _ = make(tmp_path, FakeEnv(checks={1: ["not allowed for this fund: data/overrides/x.json"]}))
    fs = d.run_fund(CIK)
    assert fs.stage == "recorded" and fs.round == 2
    assert runner.roles()[:3] == ["fund_agent", "orchestrator", "fund_agent"]


def test_dispute_overturned_moves_on_to_sample(tmp_path):
    env = FakeEnv(review={1: {"RVQ_1": "wrong"}}, rulings={"RVQ_1": "overturned"})
    runner = StubRunner(decisions=[{"decision": "dispute_to_reviewer", "reason": "counter-evidence", "items": ["RVQ_1"]}])
    d, runner, _ = make(tmp_path, env, runner=runner)
    fs = d.run_fund(CIK)
    assert fs.stage == "recorded" and fs.round == 1
    assert runner.roles() == ["fund_agent", "reviewer", "orchestrator", "reviewer", "reader"]


def test_dispute_upheld_returns_to_fund_agent(tmp_path):
    env = FakeEnv(review={1: {"RVQ_1": "wrong"}}, rulings={"RVQ_1": "upheld"})
    runner = StubRunner(decisions=[{"decision": "dispute_to_reviewer", "reason": "x", "items": ["RVQ_1"]}])
    d, _, _ = make(tmp_path, env, runner=runner)
    fs = d.run_fund(CIK)
    assert fs.stage == "recorded" and fs.round == 2


def test_sample_flags_return_and_recheck_can_clear_them(tmp_path):
    env = FakeEnv(sample={1: {"card7/issuer_name": "misread cash line"}}, rulings={"card7/issuer_name": "overturned"})
    runner = StubRunner(decisions=[{"decision": "recheck_sample_row", "reason": "looks like a misread", "items": ["card7/issuer_name"]}])
    d, _, _ = make(tmp_path, env, runner=runner)
    fs = d.run_fund(CIK)
    assert fs.stage == "recorded" and fs.round == 1


def test_orchestrator_cannot_record_and_off_menu_is_continue(tmp_path):
    env = FakeEnv(review={1: {"RVQ_1": "x"}})
    runner = StubRunner(decisions=[{"decision": "accept_everything", "reason": "trust me"}])
    d, _, run = make(tmp_path, env, runner=runner)
    fs = d.run_fund(CIK)
    assert fs.round == 2 and d.env.recorded == 1                 # returned, then recorded on its own merit
    log = (run.folder / "orchestrator.jsonl").read_text()
    assert "off-menu" in log


def test_orchestrator_stop_run_ends_the_run(tmp_path):
    env = FakeEnv(review={1: {"RVQ_1": "x"}})
    runner = StubRunner(decisions=[{"decision": "stop_run", "reason": "every fund fails the same check"}])
    d, _, _ = make(tmp_path, env, runner=runner)
    summary = d.run_all([CIK])
    assert "orchestrator" in summary["stopped"]


def test_ask_owner_parks_the_named_items(tmp_path):
    env = FakeEnv(review={1: {"RVQ_1": "scope question"}})
    runner = StubRunner(decisions=[{"decision": "ask_owner", "reason": "owner scope", "items": ["RVQ_1"],
                                    "question": "Is the 2022 HTML lane in scope?"}])
    d, _, run = make(tmp_path, env, runner=runner)
    fs = d.run_fund(CIK)
    assert fs.stage == "parked" and "2022 HTML lane" in (run.folder / "owner_questions.md").read_text()


def test_skip_parks_without_any_agent_call(tmp_path):
    d, runner, _ = make(tmp_path, FakeEnv(skip="uncommitted changes in the main checkout"))
    fs = d.run_fund(CIK)
    assert fs.stage == "parked" and runner.calls == []


# --- orchestrator enforcement ------------------------------------------------------------
def test_enforce_limits():
    assert orch.enforce("after_review", {"decision": "return_with_notes", "reason": "x"}, round_no=MAX_ROUNDS)["decision"] == "park"
    e = orch.enforce("after_review", {"decision": "dispute_to_reviewer", "reason": "x", "items": ["A", "Z"]}, round_no=1, items_known={"A"})
    assert e["items"] == ["A"] and "unknown" in e["overridden"]
    assert orch.enforce("after_review", {"decision": "dispute_to_reviewer", "reason": "x", "items": ["Z"]}, round_no=1, items_known={"A"})["decision"] == "continue"
    assert orch.enforce("after_checks", {"decision": "dispute_to_reviewer", "reason": "x", "items": ["A"]}, round_no=1)["decision"] == "continue"
    assert orch.enforce("after_review", None, round_no=1)["decision"] == "continue"
    assert orch.enforce("after_review", {"decision": "ask_owner", "reason": "x"}, round_no=1)["decision"] == "continue"


# --- observation loop ------------------------------------------------------------------------
def test_observation_routes_and_shared_fix_parked_when_unpredicted_fund_moves(tmp_path):
    obs = [{"key": "floor_rate", "entries_path": "e.json", "cik": CIK}, {"key": "swap", "entries_path": "e.json", "cik": CIK}]
    env = FakeEnv(observations=obs, routes={"floor_rate": "shared", "swap": "not_real"}, shared_ok=False)
    d, runner, _ = make(tmp_path, env)
    out = d.observation_loop()
    assert out[0]["shared_fix"]["outcome"] == "parked" and out[1]["route"] == "not_real"
    assert runner.roles() == ["investigator", "reviewer", "shared_fix", "investigator", "reviewer"]


# --- policy ------------------------------------------------------------------------------------
@pytest.fixture
def fund_policy(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    return Policy(role="fund_agent", worktree=wt, allowed_res=allowed_paths(CIK), write_roots=(tmp_path / "round",),
                  read_roots=(wt,), shell=True, max_builds=2), wt


def test_fund_agent_writes_only_its_own_paths(fund_policy):
    p, wt = fund_policy
    ok = ["data/overrides/bdc_xbrl_wrappers/%s.json" % CIK, "data/overrides/row_corrections.csv",
          "data/overrides/agent_investigate_rules/%s/r1.json" % CIK, "scratch/fund_runs/%s/notes.md" % CIK,
          "pipeline/unified_holdings.py", "tests/test_new_thing.py"]
    bad = ["data/overrides/bdc_xbrl_wrappers/0001287750.json", "data/decisions/%s.jsonl" % CIK, "AGENTS.md",
           ".claude/skills/x/SKILL.md", "data/reference/quarter_acceptance_thresholds.json",
           "scripts/v05_evidence/fund_gate.py", "data/output/private_markets_holdings.csv"]
    for rel in ok:
        assert p.check("Write", {"file_path": str(wt / rel)}, wt) is None, rel
    for rel in bad:
        assert p.check("Edit", {"file_path": str(wt / rel)}, wt) is not None, rel


def test_fund_agent_shell_rules(fund_policy):
    p, wt = fund_policy
    for cmd in ["git commit -m x", "git stash", "python scripts/decide.py append x --actor y",
                "python scripts/run_batch.py --batch-id x", "python scripts/fund_ledger_trial.py --label x",
                "bash scratch/my_build.sh x 1", "echo x > data/output/foo.csv", "python - <<EOF\nx\nEOF"]:
        assert p.check("Bash", {"command": cmd}, wt) is not None, cmd
    assert check_shell_fund("bash scripts/v05_evidence/build_fund.sh y8108a 0001786108", cwd=wt) is None


def test_build_limit_counts_builds(fund_policy):
    p, wt = fund_policy
    cmd = {"command": "bash scripts/v05_evidence/build_fund.sh y8108a 0001786108"}
    assert p.check("Bash", cmd, wt) is None and p.check("Bash", cmd, wt) is None
    assert "build limit" in p.check("Bash", cmd, wt)


def test_read_only_roles_have_no_shell_or_edit(tmp_path):
    p = Policy(role="reader", write_roots=(tmp_path / "s",), read_roots=(ROOT,))
    assert p.check("Bash", {"command": "ls"}, ROOT) is not None
    assert p.check("Write", {"file_path": str(ROOT / "AGENTS.md")}, ROOT) is not None
    assert p.check("Write", {"file_path": str(tmp_path / "s" / "labels.json")}, ROOT) is None


# --- checks ------------------------------------------------------------------------------------
def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "data/overrides/bdc_xbrl_wrappers").mkdir(parents=True)
    (r / "data/overrides/row_corrections.csv").write_text("cik,field,value\n0001786108,a,1\n0001287750,b,2\n")
    (r / ("data/overrides/bdc_xbrl_wrappers/%s.json" % CIK)).write_text("{}\n")
    _git(r, "init", "-q")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return r


def test_diff_check_own_lines_pass_foreign_lines_fail(repo):
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    rc = repo / "data/overrides/row_corrections.csv"
    rc.write_text(rc.read_text() + "0001786108,c,3\n")
    assert checks.diff_check(repo, base, CIK)["ok"]
    rc.write_text(rc.read_text().replace("0001287750,b,2", "0001287750,b,9"))
    res = checks.diff_check(repo, base, CIK)
    assert not res["ok"] and "do not belong" in res["problems"][0]


def test_diff_check_other_fund_wrapper_fails(repo):
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    (repo / "data/overrides/bdc_xbrl_wrappers/0001287750.json").write_text("{}\n")
    res = checks.diff_check(repo, base, CIK)
    assert not res["ok"] and "0001287750" in res["problems"][0]


def test_snapshot_catches_a_planted_write(tmp_path):
    (tmp_path / "data/output").mkdir(parents=True)
    (tmp_path / "data/output/a.csv").write_text("x")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    before = checks.main_snapshot(tmp_path)
    (tmp_path / "data/output/b.csv").write_text("planted")
    res = checks.compare_snapshot(before, checks.main_snapshot(tmp_path))
    assert not res["ok"] and "data/output/b.csv" in res["problems"][0]
    assert checks.compare_snapshot(before, checks.main_snapshot(tmp_path), allow_prefixes=("data/output/b",))["ok"]


def test_parse_published_errors(tmp_path):
    import env_real
    p = tmp_path / "results.md"
    p.write_text("x\n\nPublished errors: 1\n\n| Card | Quarter | Field | Published | Cause | Note |\n|---|---|---|---|---|---|\n"
                 "| c07 | 2025-06-30 | issuer_name | wrong | pipeline | Orchard printed as Digilens |\n")
    assert env_real.parse_published_errors(p) == {"c07/issuer_name": "2025-06-30 wrong pipeline: Orchard printed as Digilens"}
    p.write_text("Published errors: 0\n")
    assert env_real.parse_published_errors(p) == {}


def test_cohort_sql_placeholder():
    pytest.importorskip("claude_agent_sdk")  # scripts/sdk_review/tools.py imports it; not installed in CI
    import tools
    assert tools.sql_problem("SELECT count(*) FROM read_parquet('{P}/private_markets_holdings.parquet')", placeholder="{P}") is None
    assert tools.sql_problem("SELECT * FROM read_parquet('{S}/x.parquet')", placeholder="{P}") is not None
    assert tools.sql_problem("SELECT * FROM read_json('C:/Users/x/.claude/settings.json')", placeholder="{P}") is not None
