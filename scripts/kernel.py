#!/usr/bin/env python3
"""一句话补接入 · 演示内核（零依赖，除 YAML 解析）

设计红线：
  - --check（默认）只读，不写任何文件；只有 --step / --finalize 才落状态。
  - 不改专家包本体、不改注册层、不重建已建底座。
  - 不自动选 decision；不通是待修复，不是跳过。
  - 收口必须断言：受保护文件哈希不变、coverage 不变、能力就绪或明确 declined。

用法:
    python kernel.py --workdir <dir>                    # 只读体检 + 任务单
    python kernel.py --workdir <dir> --json             # 机器可读
    python kernel.py --workdir <dir> --step cap:step:status --note "..."  # 断点状态位
    python kernel.py --workdir <dir> --finalize         # 收口断言
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CAP_FILE = ROOT / "schemas" / "capabilities.yaml"
STATE_FILE = "capability-state.json"
PROTECTED = ["inputs.yaml", "registry.yaml", "kb-manifest.json"]


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def envelope(step: str, status: str, reason: str = "", data=None) -> dict:
    return {"step": step, "status": status, "reason": reason,
            "data": data or {}, "generated_at": now()}


def load_yaml(path: Path):
    if yaml is None or not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise ValueError(f"{path.name} 解析失败: {e}") from e


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "(absent)"


def read_state(wd: Path) -> dict:
    p = wd / STATE_FILE
    if not p.is_file():
        return {"schema_version": 1, "capabilities": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("capabilities"), dict):
            return d
    except Exception:
        pass
    return {"schema_version": 1, "capabilities": {}}


def detect(cap: dict, wd: Path, state: dict) -> dict:
    det = cap.get("detect") or {}
    inputs = load_yaml(wd / "inputs.yaml") or {}
    reg = load_yaml(wd / "registry.yaml") or {}
    spec = ((inputs.get("inputs") or {}).get(det.get("inputs_key", "")) or {}) \
        if isinstance(inputs.get("inputs"), dict) else {}
    if not isinstance(spec, dict):
        spec = {}
    decision = str(spec.get(det.get("decision_field", "decision")) or "").strip().lower()
    declared = det.get("registry_key", "") in reg
    probe = wd / det.get("probe_state_file", "probe.json")
    probe_status = ""
    if probe.is_file():
        try:
            probe_status = str((json.loads(probe.read_text(encoding="utf-8")) or {}).get("status") or "")
        except Exception:
            probe_status = ""

    st = (state.get("capabilities") or {}).get(cap["id"]) or {}
    if decision == "declined" or spec.get("declined") is True:
        status = "declined"
    elif decision == "use" and declared and probe_status == "ok":
        status = "ready"
    elif decision == "use":
        status = "blocked"
    elif decision == "":
        status = "awaiting_confirm"
    else:
        status = "blocked"
    return {"id": cap["id"], "summary": cap.get("summary"),
            "status": status, "decision": decision or "(未定)",
            "declared": declared, "probe": probe_status or "(无)",
            "resume_at": st.get("resume_at"),
            "blocked_reason": st.get("blocked_reason"),
            "steps_done": st.get("steps_done") or []}


def task_card(cap: dict, det: dict) -> dict:
    return {"capability": cap["id"], "goal": cap.get("summary"),
            "status": det["status"], "resume_at": det.get("resume_at"),
            "steps": cap.get("steps") or [],
            "done_when": cap.get("done_when"), "degrade": cap.get("degrade"),
            "self_contained": True,
            "hard_rules": ["确认门必须等用户拍板", "不通是待修复，禁止跳过或报完成",
                           "修好后从断点续跑并收口", "不改本体、不覆盖用户配置"]}


def collect(wd: Path) -> dict:
    cfg = load_yaml(CAP_FILE) or {}
    caps = [c for c in (cfg.get("capabilities") or []) if isinstance(c, dict)]
    state = read_state(wd)
    results = [detect(c, wd, state) for c in caps]
    pending = [r for r in results if r["status"] in ("awaiting_confirm", "blocked")]
    man = {}
    if (wd / "kb-manifest.json").is_file():
        try:
            man = json.loads((wd / "kb-manifest.json").read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"workdir": str(wd), "capabilities": results,
            "pending": [p["id"] for p in pending],
            "task_cards": [task_card(c, d) for c, d in zip(caps, results)
                           if d["status"] in ("awaiting_confirm", "blocked")],
            "coverage": man.get("coverage") or {},
            "protected_hashes": {n: digest(wd / n) for n in PROTECTED}}


def render(r: dict) -> str:
    L = ["# 更新检查（只读）", "", f"工作目录：`{r['workdir']}`", "",
         "| 能力 | 状态 | decision | 声明 | 探测 |", "|---|---|---|---|---|"]
    for c in r["capabilities"]:
        L.append(f"| `{c['id']}` | **{c['status']}** | {c['decision']} | "
                 f"{'是' if c['declared'] else '否'} | {c['probe']} |")
    L += ["", f"待补接入：{r['pending'] or '无'}"]
    for card in r["task_cards"]:
        L += ["", f"## `{card['capability']}` 任务单（自包含）",
              f"断点：{card.get('resume_at') or '从头'}",
              f"完成判据：`{card['done_when']}`", ""]
        for i, s in enumerate(card["steps"], 1):
            act = s.get("command") or s.get("instruction") or s.get("then") or ""
            L.append(f"{i}. **{s.get('title', s['id'])}** [{s['type']}] — {' '.join(str(act).split())[:120]}")
        L.append("")
        L += [f"- {h}" for h in card["hard_rules"]]
    L += ["", "> 只读检查不写任何文件；`--step` 落状态，`--finalize` 收口。"]
    return "\n".join(L)


def write_state(wd: Path, r: dict, cap_id: str, step: str, status: str, note: str) -> dict:
    st = read_state(wd)
    row = st["capabilities"].get(cap_id) or {}
    done = list(dict.fromkeys((row.get("steps_done") or []) + ([step] if step else [])))
    row.update({"status": status, "last_step": step, "steps_done": done, "updated_at": now()})
    if status == "blocked":
        row["blocked_reason"] = note or "未说明"
        row["resume_at"] = step
    else:
        row.pop("blocked_reason", None)
        row.pop("resume_at", None)
    if note:
        row["note"] = note
    st["capabilities"][cap_id] = row
    (wd / STATE_FILE).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    return row


def finalize(wd: Path, r: dict) -> dict:
    issues = []
    for n, h in r["protected_hashes"].items():
        if digest(wd / n) != h:
            issues.append(f"受保护文件被改动: {n}")
    left = [c for c in r["capabilities"] if c["status"] not in ("ready", "declined")]
    if left:
        issues.append("能力未就绪: " + ", ".join(c["id"] for c in left))
    if issues:
        return envelope("finalize", "blocked", "收口断言未通过", {"issues": issues,
                        "next": "按任务单补完剩余步骤后重跑 --finalize"})
    return envelope("finalize", "ok", "收口断言通过",
                    {"next": "重生成入口文件与清单；规则上下文仍是会话启动版本，完整能力请开新会话"})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--step", default=None, help="cap_id:step_id:status")
    ap.add_argument("--note", default="")
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--plan", action="store_true", help="显示探测计划（由 agent 宿主能力执行）")
    ap.add_argument("--apply", action="store_true", help="演示：把能力声明的登记项追加到项目态")
    args = ap.parse_args()
    wd = Path(args.workdir).resolve()
    if not wd.is_dir():
        print(json.dumps({"error": "workdir 不存在"}, ensure_ascii=False))
        return 2
    try:
        r = collect(wd)
    except ValueError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2

    if args.plan:
        plan = {"checks": ["endpoint_reachable", "auth_ok", "resource_exists", "coverage"],
                "note": "实测由 agent 用宿主能力完成，内核不连外部、不实现检索",
                "next": "写观测结果交回，再 --step 落状态"}
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    if args.apply:
        cfg = load_yaml(CAP_FILE) or {}
        added = []
        inputs_p = wd / "inputs.yaml"
        reg_p = wd / "registry.yaml"
        inputs = load_yaml(inputs_p) or {}
        reg = load_yaml(reg_p) or {}
        for cap in cfg.get("capabilities") or []:
            for k, v in ((cap.get("declares") or {}).get("inputs_items") or {}).items():
                if k not in (inputs.get("inputs") or {}):
                    inputs.setdefault("inputs", {})[k] = v
                    added.append(f"inputs.{k}")
            for k, v in ((cap.get("declares") or {}).get("registry_keys") or {}).items():
                if k not in reg:
                    reg[k] = v
                    added.append(f"registry.{k}")
        if yaml is None:
            print(json.dumps({"error": "缺少 PyYAML"}, ensure_ascii=False))
            return 2
        # 备份后写入（演示：只追加，不覆盖已有键）
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        (wd / f"backup-{stamp}").mkdir(exist_ok=True)
        for p in (inputs_p, reg_p):
            if p.is_file():
                (wd / f"backup-{stamp}" / p.name).write_bytes(p.read_bytes())
        inputs_p.write_text(yaml.safe_dump(inputs, allow_unicode=True, sort_keys=False), encoding="utf-8")
        reg_p.write_text(yaml.safe_dump(reg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(json.dumps(envelope("apply", "ok", "已追加声明项（备份后写入）",
                                  {"added": added, "backup": f"backup-{stamp}"}),
                         ensure_ascii=False, indent=2))
        return 0

    if args.step:
        parts = args.step.split(":")
        if len(parts) != 3:
            print(json.dumps({"error": "--step 需为 cap_id:step_id:status"}, ensure_ascii=False))
            return 2
        row = write_state(wd, r, parts[0], parts[1], parts[2], args.note)
        print(json.dumps(envelope("step", "ok", "状态已记录", {"state": row}),
                         ensure_ascii=False, indent=2))
        return 0

    if args.finalize:
        res = finalize(wd, r)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["status"] == "ok" else 1

    print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
