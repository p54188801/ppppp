r"""把全部手写源码导出成一个 Markdown 文件，方便在 PyCharm 里一屏展示/答辩。

用法：
    .\.venv\Scripts\python.exe tools\export_all_code.py
    .\.venv\Scripts\python.exe tools\export_all_code.py --out docs\ALL_CODE.md

默认排除：第三方依赖、构建产物、运行时数据、截图、文档、单文件生成版
（`eduflow_all.py` 是后端合并产物，避免重复计算）。
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "ALL_CODE.md"

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "data",
    "__pycache__",
    ".idea",
    ".pytest_cache",
    ".mypy_cache",
}
SKIP_FILES = {"frontend/package-lock.json", "eduflow_all.py"}

LANG = {
    ".py": "python",
    ".vue": "vue",
    ".js": "javascript",
    ".mjs": "javascript",
    ".css": "css",
    ".html": "html",
    ".sql": "sql",
    ".json": "json",
    ".sh": "bash",
    ".ps1": "powershell",
    ".bat": "bat",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".txt": "text",
}

# 没有扩展名、但属于工程源码/配置的文件
NAME_LANG = {
    "Dockerfile": "dockerfile",
    "Caddyfile": "caddy",
    ".dockerignore": "text",
    ".gitignore": "text",
}

# (显示名, 判断函数, 排序)
GROUPS = [
    ("后端 Python", lambda p: p.startswith("backend/") and p.endswith(".py"), 0),
    ("前端 Vue3", lambda p: p.startswith("frontend/src/"), 1),
    ("测试", lambda p: p.startswith("tests/") and p.endswith(".py"), 2),
    ("SQL 建表", lambda p: p == "backend/db/schema.sql", 3),
    ("入口", lambda p: p == "run.py", 4),
    ("工具", lambda p: p.startswith("tools/") and p.endswith(".py"), 5),
    ("脚本", lambda p: p.startswith("scripts/"), 6),
    ("配置", lambda p: True, 7),
]


def group_of(rel: str) -> str:
    for name, predicate, _order in GROUPS:
        if predicate(rel):
            return name
    return "配置"


def collect() -> dict[str, list[tuple[str, int, str, str]]]:
    result: dict[str, list[tuple[str, int, str, str]]] = {}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in SKIP_FILES or rel.startswith("docs/"):
            continue
        lang = NAME_LANG.get(path.name) or LANG.get(path.suffix.lower())
        if not lang:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        lines = text.count("\n") + (0 if text.endswith("\n") else 1)
        result.setdefault(group_of(rel), []).append((rel, lines, text, lang))
    for items in result.values():
        items.sort(key=lambda item: item[0])
    return result


def build(out: Path) -> tuple[int, int]:
    groups = collect()
    ordered = sorted(
        groups.items(),
        key=lambda item: next(order for name, _p, order in GROUPS if name == item[0]),
    )
    total_files = sum(len(items) for items in groups.values())
    total_lines = sum(
        lines for items in groups.values() for _rel, lines, _text, _lang in items
    )

    parts: list[str] = [
        "# EduFlow 全部源码",
        "",
        f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}；"
        f"共 {total_files} 个源码文件、{total_lines:,} 行。",
        "> 不含第三方依赖（.venv / node_modules）、构建产物（dist）、运行时数据、"
        "截图、Markdown 文档与自动生成的 `eduflow_all.py`。",
        "> 重新生成：`python tools/export_all_code.py`（或在 PyCharm 中右键 Run）",
        "",
        "## 总览",
        "",
        "| 分组 | 文件数 | 行数 |",
        "|---|---:|---:|",
    ]
    for name, items in ordered:
        parts.append(
            f"| {name} | {len(items)} | {sum(lines for _r, lines, _t, _l in items):,} |"
        )
    parts.extend(
        [
            f"| **合计** | **{total_files}** | **{total_lines:,}** |",
            "",
            "## 文件目录",
            "",
        ]
    )
    for name, items in ordered:
        parts.append(f"### {name}")
        parts.append("")
        for rel, lines, _text, _lang in items:
            parts.append(f"- `{rel}`（{lines:,} 行）")
        parts.append("")

    for name, items in ordered:
        parts.append(f"## {name}")
        parts.append("")
        for rel, lines, text, lang in items:
            parts.append(f"### `{rel}`（{lines:,} 行）")
            parts.append("")
            parts.append(f"````{lang}")
            parts.append(text.rstrip("\n"))
            parts.append("````")
            parts.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return total_files, total_lines


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 EduFlow 全部源码为一个 Markdown 文件")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出文件路径")
    args = parser.parse_args()
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    files, lines = build(out)
    print(f"已生成：{out}")
    print(f"共 {files} 个文件、{lines:,} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
