"""Runs the real pytest suite in a subprocess and parses JUnit XML + coverage JSON."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from app_collector.config import PROJECT_ROOT
from app_collector.models import utcnow


def run_pytest(timeout: int = 300) -> dict:
    started = utcnow().isoformat()
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "junit.xml"
        cov = Path(tmp) / "coverage.json"
        cmd = [
            sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
            f"--junitxml={junit}", "--cov=app_collector", f"--cov-report=json:{cov}",
        ]
        try:
            proc = subprocess.run(
                cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": f"pytest timed out after {timeout}s", "started_at": started}

        tests = _parse_junit(junit) if junit.exists() else []
        coverage = _parse_coverage(cov) if cov.exists() else None

    counts = {s: sum(t["status"] == s for t in tests) for s in ("passed", "failed", "error", "skipped")}
    return {
        "status": "passed" if proc.returncode == 0 else "failed",
        "exit_code": proc.returncode,
        "started_at": started,
        "duration": round(time.perf_counter() - t0, 2),
        "counts": {**counts, "total": len(tests)},
        "tests": tests,
        "coverage": coverage,
        "output_tail": "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-25:]),
    }


def _parse_junit(path: Path) -> list[dict]:
    tests = []
    for case in ET.parse(path).getroot().iter("testcase"):
        status, message = "passed", None
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                status = "failed" if tag == "failure" else tag
                message = (node.get("message") or node.text or "").strip()[:500]
                break
        classname = case.get("classname", "")
        module = classname.split(".")[1] if classname.startswith("tests.") else classname
        tests.append({
            "module": module.split(".")[0],
            "name": case.get("name", ""),
            "classname": classname,
            "duration": round(float(case.get("time") or 0), 3),
            "status": status,
            "message": message,
        })
    return tests


def _parse_coverage(path: Path) -> dict:
    data = json.loads(path.read_text())
    files = []
    for name, info in data.get("files", {}).items():
        summary = info["summary"]
        files.append({
            "file": name.replace("\\", "/"),
            "statements": summary["num_statements"],
            "missing": summary["missing_lines"],
            "percent": round(summary["percent_covered"], 1),
        })
    files.sort(key=lambda f: f["file"])
    return {"percent": round(data["totals"]["percent_covered"], 1), "files": files}
