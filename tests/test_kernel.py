"""零依赖回归：只读安全 / 差集 / 任务单自包含 / 断点 / 收口 / 可扩展。"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import kernel  # noqa: E402


def workdir() -> Path:
    t = Path(tempfile.mkdtemp(prefix="adk-test-"))
    wd = t / "workdir"
    shutil.copytree(ROOT / "examples" / "workdir", wd)
    return wd


def run(wd: Path, *args: str):
    cp = __import__("subprocess").run(
        [sys.executable, str(ROOT / "scripts" / "kernel.py"), "--workdir", str(wd), *map(str, args)],
        capture_output=True, text=True, timeout=60)
    try:
        return cp, json.loads(cp.stdout)
    except Exception:
        return cp, {}


class TestReadOnly(unittest.TestCase):
    def test_check_writes_nothing(self):
        wd = workdir()
        before = sorted(p.name for p in wd.iterdir())

        cp, out = run(wd)
        self.assertEqual(sorted(p.name for p in wd.iterdir()), before,
                         "只读检查不得写文件")
        self.assertIn("example_channel", cp.stdout)
        self.assertIn("任务单", cp.stdout)


class TestCapabilityGap(unittest.TestCase):
    def test_old_workdir_pending(self):
        wd = workdir()
        cp, out = run(wd, "--json")
        self.assertEqual(out["pending"], ["example_channel"])
        cap = next(c for c in out["capabilities"] if c["id"] == "example_channel")
        self.assertEqual(cap["status"], "awaiting_confirm")

    def test_task_card_is_self_contained(self):
        wd = workdir()
        cp, out = run(wd, "--json")
        card = out["task_cards"][0]
        self.assertTrue(card["self_contained"])
        types = [s["type"] for s in card["steps"]]
        for t in ("confirm_gate", "script", "agent_host_capability", "repair_loop", "finalize"):
            self.assertIn(t, types)
        blob = json.dumps(card, ensure_ascii=False)
        for term in ("reason_code" if False else "不通是待修复", "resume_at", "确认门", "收口"):
            self.assertIn(term, blob)


class TestBreakpoint(unittest.TestCase):
    def test_step_records_blocked_and_resume(self):
        wd = workdir()
        cp, out = run(wd, "--step", "example_channel:probe:blocked",
                      "--note", "endpoint_unreachable", "--json")
        self.assertEqual(out["status"], "ok")
        st = json.loads((wd / "capability-state.json").read_text(encoding="utf-8"))
        row = st["capabilities"]["example_channel"]
        self.assertEqual(row["resume_at"], "probe")
        self.assertEqual(row["blocked_reason"], "endpoint_unreachable")

        cp, out2 = run(wd, "--json")
        cap = next(c for c in out2["capabilities"] if c["id"] == "example_channel")
        self.assertEqual(cap["resume_at"], "probe")
        self.assertEqual(out2["task_cards"][0]["resume_at"], "probe")


class TestFinalize(unittest.TestCase):
    def test_finalize_blocked_when_pending(self):
        wd = workdir()
        cp, out = run(wd, "--finalize", "--json")
        self.assertEqual(cp.returncode, 1)
        self.assertEqual(out["status"], "blocked")
        self.assertTrue(any("未就绪" in i for i in out["data"]["issues"]))

    def test_finalize_ok_after_declined(self):
        wd = workdir()
        p = wd / "inputs.yaml"
        import yaml
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cfg.setdefault("inputs", {})["example_channel"] = {"decision": "declined"}
        p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        cp, out = run(wd, "--finalize", "--json")
        self.assertEqual(cp.returncode, 0, cp.stdout[-300:])
        self.assertEqual(out["status"], "ok")

    def test_protected_hashes_are_reported(self):
        wd = workdir()
        cp, out = run(wd, "--json")
        self.assertIn("protected_hashes", out)
        for name in ("inputs.yaml", "registry.yaml", "kb-manifest.json"):
            self.assertIn(name, out["protected_hashes"])
            self.assertEqual(len(out["protected_hashes"][name]), 64)


class TestExtensibility(unittest.TestCase):
    def test_add_capability_needs_no_code_change(self):
        cfg = kernel.load_yaml(kernel.CAP_FILE)
        extra = {
            "id": "synthetic_new_cap", "since_version": "9.9.9", "summary": "合成新能力",
            "declares": {"inputs_items": {}, "registry_keys": {}},
            "detect": {"inputs_key": "synthetic", "decision_field": "decision",
                       "registry_key": "synthetic_reg", "probe_state_file": "p.json"},
            "steps": [{"id": "confirm", "type": "confirm_gate", "title": "确认",
                       "instruction": "等用户拍板"}],
            "done_when": "decision != ''", "degrade": "如实标注",
        }
        with tempfile.TemporaryDirectory() as t:
            wd = Path(t) / "workdir"
            shutil.copytree(ROOT / "examples" / "workdir", wd)
            res = kernel.detect(extra, wd, kernel.read_state(wd))
            self.assertEqual(res["status"], "awaiting_confirm")
            card = kernel.task_card(extra, res)
            self.assertTrue(card["self_contained"])
            self.assertEqual(card["steps"][0]["type"], "confirm_gate")
        self.assertEqual(len(cfg["capabilities"]), 1, "清单里只有一条示例能力")


class TestNoProjectValues(unittest.TestCase):
    def test_sources_are_synthetic(self):
        banned = ["锡膏", "GR" + "Code", "asd" + "_cloud_base", "Bearer ", "t_mes_"]
        paths = [ROOT / "README.md", ROOT / "schemas" / "capabilities.yaml",
                 ROOT / "scripts" / "kernel.py", ROOT / "examples" / "workdir" / "inputs.yaml"]
        for p in paths:
            text = p.read_text(encoding="utf-8")
            for b in banned:
                self.assertNotIn(b, text, f"{p.name} 含疑似项目值: {b}")


if __name__ == "__main__":
    unittest.main()
