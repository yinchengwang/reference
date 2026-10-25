#!/usr/bin/env python3
"""catalog.yml 四字段同步工具：commit / clone_url / pin_status / source。

设计要点
--------
* 只用标准库（G11：环境无 PyYAML），catalog.yml 结构规整，手写解析足够。
* catalog.yml 当前是 CRLF 行尾（G4），读写一律用 ``newline=''``，
  解析前统一 ``replace('\\r\\n', '\\n')``，写回时按原行尾重建。
* 写回采用「外科式插入」：只在条目内新增/更新 4 个字段行，
  其余字节原样保留 —— 保证 diff 只包含预期字段的增删。
* pin 判定表来自人工实测（任务书 Step 5），逐字录入，不做自动推断。
"""

import argparse
import os
import re
import subprocess
import sys

CATALOG_RELPATH = os.path.join("reference", "catalog.yml")
MANIFEST_RELPATH = os.path.join("reference", "fetch-manifest.txt")

MANIFEST_HEADER = "# model\tname\tclone_url\tcommit\tpin_status"
MANIFEST_COLUMNS = ("model", "name", "clone_url", "commit", "pin_status")

# --- Step 5：人工实测确认的 pin 状态表（逐字取自任务书，不得自动推断） ---
# name -> (pin_status, commit, clone_url)
#   commit 为 None 表示写回 YAML 的 null（不得照抄 gitlink SHA，G5）
#   clone_url 为 None 表示写回 YAML 的 null
PIN_OVERRIDES = {
    "druid": ("broken", None, "https://github.com/apache/druid.git"),
    "pebble": ("broken", None, "https://github.com/cockroachdb/pebble.git"),
    "tdengine": ("broken", None, "https://github.com/taosdata/TDengine.git"),
    "dragonfly": ("broken", None, "https://github.com/dragonflydb/dragonfly.git"),
    "oceanbase": ("unresolvable", None, None),
    "pklite": ("unresolvable", None, None),
}

# --- clone_url 取 GitHub 官方地址（而非 mirror / gitee 镜像） ---
# catalog 里 repository 非 github.com 的条目，在此给出 GitHub 官方地址。
# openGauss 的 GitHub 官方地址是 openGauss-mirror 组织
# （openGauss.org 明确列出 github.com/opengauss-mirror 为官方镜像仓库），
# github.com/opengauss/openGauss-server 不存在（HTTP 404）。
GITHUB_OFFICIAL = {
    "openGauss": "https://github.com/opengauss-mirror/openGauss-server.git",
}

# 条目首行 `  - name: xxx`，字段行 4 空格缩进，notes 列表项 6 空格缩进
_ENTRY_RE = re.compile(r"^  - ([A-Za-z0-9_.-]+):\s*(.*)$")
_FIELD_RE = re.compile(r"^    ([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
_NOTE_RE = re.compile(r"^      - (.*)$")
_NULL_TOKENS = ("null", "Null", "NULL", "~", "")


def _scalar(raw):
    """标量值 -> Python 值（YAML null 记为 None）。"""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if value in _NULL_TOKENS:
        return None
    return value


def parse_catalog(text):
    """解析 catalog.yml 文本，返回条目列表。

    容忍 CRLF 与 LF 混合行尾（G4）。不依赖 PyYAML（G11）。
    返回的每个 dict 含 name/model/tier/repository/mirror/license/status/notes，
    以及可选的 commit/clone_url/pin_status/source。
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    entries = []
    current = None
    last_key = None
    for line in lines:
        if not line.strip():
            continue
        m = _ENTRY_RE.match(line)
        if m:
            current = {m.group(1): _scalar(m.group(2))}
            entries.append(current)
            last_key = m.group(1)
            continue
        m = _NOTE_RE.match(line)
        if m and current is not None:
            if not isinstance(current.get(last_key), list):
                current[last_key] = [] if current.get(last_key) is None else [current[last_key]]
            current[last_key].append(_scalar(m.group(1)))
            continue
        m = _FIELD_RE.match(line)
        if m and current is not None:
            key, raw = m.group(1), m.group(2)
            current[key] = _scalar(raw)
            last_key = key
            if raw.strip() == "":
                # 可能是一个列表（如 notes:）—— 先占位，后面遇到 `- xxx` 会补上
                current[key] = []
            continue
    return entries


def render_manifest(entries):
    """渲染 5 列 manifest 文本。

    列：model<TAB>name<TAB>clone_url<TAB>commit<TAB>pin_status
    首行为 '#' 开头的表头注释。空值写 '-'。
    """
    lines = [MANIFEST_HEADER]
    for entry in entries:
        row = []
        for col in MANIFEST_COLUMNS:
            value = entry.get(col)
            row.append("-" if value is None or value == "" else str(value))
        lines.append("\t".join(row))
    return "\n".join(lines) + "\n"


def _gitlinks(repo_root):
    """读取 gitlink（mode 160000）路径 -> SHA 映射。"""
    out = subprocess.run(
        ["git", "-C", repo_root, "ls-files", "-s"],
        capture_output=True, text=True, check=True,
    ).stdout
    links = {}
    for line in out.split("\n"):
        if not line.startswith("160000"):
            continue
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 2:
            links[path] = parts[1]
    return links


def _clone_url(entry):
    """clone_url 取 GitHub 官方地址。

    优先 GITHUB_OFFICIAL 里显式给出的 GitHub 官方地址；
    否则用 catalog 的 repository 字段（96/97 条本身就是 github.com）。
    不使用 mirror 字段 —— 镜像最不可靠。
    """
    name = entry["name"]
    if name in GITHUB_OFFICIAL:
        return GITHUB_OFFICIAL[name]
    repository = entry.get("repository") or ""
    return repository or None


def compute_entries(repo_root):
    """算出补齐四字段后的条目列表（与磁盘上的 catalog 无关）。"""
    catalog_path = os.path.join(repo_root, CATALOG_RELPATH)
    with open(catalog_path, "r", encoding="utf-8", newline="") as fh:
        entries = parse_catalog(fh.read())
    links = _gitlinks(repo_root)
    for entry in entries:
        name = entry["name"]
        path = "reference/%s/%s" % (entry.get("model"), name)
        sha = links.get(path)
        if name in PIN_OVERRIDES:
            pin_status, commit, clone_url = PIN_OVERRIDES[name]
        else:
            pin_status = "valid"
            commit = sha
            clone_url = _clone_url(entry)
        entry["pin_status"] = pin_status
        entry["commit"] = commit
        entry["clone_url"] = clone_url
        entry["source"] = "mirror" if sha else "none"
    return entries


def _render_value(value):
    if value is None:
        return "null"
    return str(value)


NEW_FIELDS = ("commit", "clone_url", "pin_status", "source")


def _entry_name(line):
    """取条目首行的名字（`- name: xxx` 的值部分）。"""
    m = _ENTRY_RE.match(line)
    return m.group(2).strip() if m else None


def _split_blocks(lines):
    """把 catalog.yml 切成 (前言行, [条目块]) —— 块内含条目的全部行。"""
    head = []
    blocks = []
    current = None
    for line in lines:
        if _ENTRY_RE.match(line):
            current = [line]
            blocks.append(current)
            continue
        if current is None:
            head.append(line)
        else:
            current.append(line)
    return head, blocks


def _catalog_text(repo_root, entries):
    """在原 catalog.yml 文本上外科式写入四字段，保持原行尾（CRLF）。

    只动四个字段：已有的就地更新、没有的按 `status:` 之后插入。
    其余行（含 notes 列表）逐字节原样保留。
    """
    catalog_path = os.path.join(repo_root, CATALOG_RELPATH)
    with open(catalog_path, "r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    trailing = raw.endswith(eol)
    lines = raw.split(eol)
    if trailing:
        lines = lines[:-1]

    by_name = {e["name"]: e for e in entries}
    head, blocks = _split_blocks(lines)

    out = list(head)
    for block in blocks:
        name = _entry_name(block[0])
        entry = by_name.get(name)
        if entry is None:
            out.extend(block)
            continue
        # 去掉已存在的四字段行，稍后按统一顺序重写
        kept = []
        for line in block[1:]:
            m = _FIELD_RE.match(line)
            if m and m.group(1) in NEW_FIELDS:
                continue
            kept.append(line)
        new_lines = ["    %s: %s" % (k, _render_value(entry.get(k))) for k in NEW_FIELDS]
        # 插到 status: 之后（status 缺失时插到块尾）
        insert_at = len(kept)
        for i, line in enumerate(kept):
            m = _FIELD_RE.match(line)
            if m and m.group(1) == "status":
                insert_at = i + 1
                break
        out.append(block[0])
        out.extend(kept[:insert_at])
        out.extend(new_lines)
        out.extend(kept[insert_at:])

    text = eol.join(out)
    if trailing:
        text += eol
    return text


def sync_catalog(repo_root, apply=False):
    """补齐 catalog.yml 的四个字段。

    apply=False 时只返回差异报告（不落盘）；apply=True 时写回 catalog.yml。
    返回差异报告行列表。
    """
    catalog_path = os.path.join(repo_root, CATALOG_RELPATH)
    with open(catalog_path, "r", encoding="utf-8", newline="") as fh:
        current = parse_catalog(fh.read())
    expected = compute_entries(repo_root)

    diff = []
    for entry in expected:
        name = entry["name"]
        actual = next((e for e in current if e["name"] == name), None)
        if actual is None:
            diff.append("+ %s: 条目缺失" % name)
            continue
        for key in ("commit", "clone_url", "pin_status", "source"):
            want = entry.get(key)
            got = actual.get(key)
            if got != want:
                diff.append("~ %s.%s: %r -> %r" % (name, key, got, want))

    if apply and diff:
        text = _catalog_text(repo_root, expected)
        with open(catalog_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return diff


def write_manifest(repo_root):
    """重建 reference/fetch-manifest.txt（5 列 TAB 分隔）。

    行序沿用 catalog.yml 的条目顺序（旧 manifest 亦为 catalog 顺序的子序列）。
    """
    entries = compute_entries(repo_root)
    manifest_path = os.path.join(repo_root, MANIFEST_RELPATH)
    with open(manifest_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(render_manifest(entries))
    return manifest_path


def summarize(entries):
    counts = {"valid": 0, "broken": 0, "unresolvable": 0}
    for entry in entries:
        status = entry.get("pin_status")
        if status in counts:
            counts[status] += 1
    return "%d entries, %d valid, %d broken, %d unresolvable" % (
        len(entries), counts["valid"], counts["broken"], counts["unresolvable"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="catalog.yml 四字段同步工具")
    parser.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--check", action="store_true", help="校验 catalog 是否已补齐（退出码 0=一致）")
    parser.add_argument("--apply", action="store_true", help="把四字段写回 catalog.yml")
    parser.add_argument("--write-manifest", action="store_true", help="重建 fetch-manifest.txt")
    args = parser.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)
    entries = compute_entries(repo_root)

    if args.write_manifest:
        path = write_manifest(repo_root)
        print("wrote %s" % path)

    if args.check:
        diff = sync_catalog(repo_root, apply=False)
        if diff:
            print("catalog 不一致，%d 处差异：" % len(diff))
            for line in diff[:50]:
                print("  " + line)
            return 1
        print(summarize(entries))
        return 0

    if args.apply:
        diff = sync_catalog(repo_root, apply=True)
        print("applied %d changes" % len(diff))
        for line in diff[:50]:
            print("  " + line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
