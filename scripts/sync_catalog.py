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

MANIFEST_COLUMNS = ("model", "name", "clone_url", "commit", "pin_status")
MANIFEST_HEADER = "# " + "\t".join(MANIFEST_COLUMNS)

# 设计文档 §5.5.2 的一致性校验规则（1~9）里要检查的字段
REQUIRED_KEYS = ("name", "model", "tier", "repository", "license", "status", "notes",
                 "commit", "clone_url", "pin_status", "source")
PIN_STATUSES = ("valid", "broken", "unresolvable")
SOURCES = ("mirror", "none")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
# broken 条目的 notes 必须「说明失效原因」——用内容判定而不是数条目个数。
# 一条写好的合并说明也算数，所以不要求 >= 2 条。
_BREAKAGE_HINT_RE = re.compile(r"不存在|失效|not our ref|404|取不到|无此 commit")


class CatalogError(Exception):
    """catalog / 仓库状态异常（向用户报一行人话，而不是抛 traceback）。"""

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

    值里不允许出现 TAB / CR / LF —— 它们会让该行变成 6 列，破坏 lockfile 的
    定宽不变量。当前 catalog 数据不可达，但一旦可达就是**静默损坏**，所以这里
    直接抛 ValueError（fail loud）；`check_schema` 会在更早的位置给出可读的问题
    描述，使 `--check` 以退出码 1 收场而不是抛栈。
    """
    lines = [MANIFEST_HEADER]
    for entry in entries:
        row = []
        for col in MANIFEST_COLUMNS:
            value = entry.get(col)
            if value is None or value == "":
                row.append("-")
                continue
            text = str(value)
            if any(ch in text for ch in ("\t", "\r", "\n")):
                raise ValueError(
                    "%s: 字段 %s 含 TAB/CR/LF，无法安全写入 manifest: %r"
                    % (entry.get("name") or "<未命名条目>", col, text))
            row.append(text)
        lines.append("\t".join(row))
    return "\n".join(lines) + "\n"


def _norm_eol(text):
    """把 CRLF 归一化成 LF。

    仓内 blob 是 LF，但 Windows 工作区因 core.autocrlf=true 会是 CRLF ——
    比对前必须归一化，否则同一份内容会因行尾差异被判为「不一致」。
    """
    return text.replace("\r\n", "\n")


def _gitlinks(repo_root):
    """读取 gitlink（mode 160000）路径 -> SHA 映射。"""
    try:
        out = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "-s"],
            capture_output=True, text=True, check=True,
        ).stdout
    except FileNotFoundError:
        raise CatalogError("找不到 git 可执行文件")
    except subprocess.CalledProcessError:
        raise CatalogError("%s 不是 git 仓库（或尚未 git init），无法读取 gitlink" % repo_root)
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
    try:
        with open(catalog_path, "r", encoding="utf-8", newline="") as fh:
            entries = parse_catalog(fh.read())
    except FileNotFoundError:
        raise CatalogError("找不到 catalog：%s" % catalog_path)
    links = _gitlinks(repo_root)
    for entry in entries:
        name = entry.get("name")
        if not name:
            raise CatalogError("catalog 里有条目缺少 name 字段：%r" % (entry,))
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
    # 行尾：取占多数的那种，按它重建（混合行尾时不再把整个文件当成一行）
    eol = "\r\n" if raw.count("\r\n") * 2 > raw.count("\n") else "\n"
    normalized = _norm_eol(raw)
    trailing = normalized.endswith("\n")
    lines = normalized.split("\n")
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


def check_schema(entries):
    """校验 catalog 的字段级不变量。

    对应设计文档 §5.5.2「一致性校验规则」的 1/3/4/5/6/7 条：
      1. 每条必须有非空 pin_status，取值在 {valid, broken, unresolvable}
      3. broken  → commit 允许为 null，但 notes 必须说明失效原因与受影响的笔记
      4. unresolvable → source 必须为 none，commit 与 clone_url 必须为 null
      5. source: mirror → clone_url 必须非空
      6. model + '/' + name 必须等于 submodule path（由 sync_catalog 的字段比对保证）
      7. catalog 有条目但 .gitmodules 无对应 → 仅当 source: none 时合法
    返回问题描述列表（空列表 = 全部通过）。
    """
    problems = []
    for entry in entries:
        name = entry.get("name") or "<未命名条目>"
        for key in REQUIRED_KEYS:
            if key not in entry:
                problems.append("! %s: 缺少必填字段 %s" % (name, key))

        # 含 TAB/CR/LF 的字段会破坏 manifest 的定宽列（见 render_manifest）
        for key in MANIFEST_COLUMNS:
            value = entry.get(key)
            if isinstance(value, str) and any(ch in value for ch in ("\t", "\r", "\n")):
                problems.append("! %s: 字段 %s 含 TAB/CR/LF，会破坏 manifest 的定宽列: %r"
                                % (name, key, value))

        status = entry.get("pin_status")
        source = entry.get("source")
        commit = entry.get("commit")
        clone_url = entry.get("clone_url")
        notes = entry.get("notes")

        if status not in PIN_STATUSES:
            problems.append("! %s: pin_status 非法 %r" % (name, status))
        if source not in SOURCES:
            problems.append("! %s: source 非法 %r" % (name, source))

        if status == "valid":
            if not (isinstance(commit, str) and _SHA_RE.fullmatch(commit)):
                problems.append("! %s: pin_status=valid 但 commit 不是 40 位 hex: %r" % (name, commit))
            if not clone_url:
                problems.append("! %s: pin_status=valid 但 clone_url 为空" % name)
        elif status == "broken":
            if commit is not None:
                problems.append("! %s: pin_status=broken 但 commit 非空: %r" % (name, commit))
            if not isinstance(notes, list) or not notes:
                problems.append("! %s: pin_status=broken 但 notes 为空" % name)
            elif not _BREAKAGE_HINT_RE.search(" ".join(str(n) for n in notes)):
                problems.append("! %s: pin_status=broken 但 notes 未说明失效原因与受影响的笔记" % name)
        elif status == "unresolvable":
            if source != "none":
                problems.append("! %s: pin_status=unresolvable 但 source 不是 none" % name)
            if commit is not None:
                problems.append("! %s: pin_status=unresolvable 但 commit 非空" % name)
            if clone_url is not None:
                problems.append("! %s: pin_status=unresolvable 但 clone_url 非空" % name)

        if source == "mirror" and not clone_url:
            problems.append("! %s: source=mirror 但 clone_url 为空" % name)
    return problems


def check_manifest(repo_root, entries=None):
    """校验 fetch-manifest.txt 与 catalog 生成结果一致（设计文档 §5.5.2 规则 9）。

    比对前把两边都归一化成 LF —— 仓内 blob 是 LF，Windows 工作区因
    core.autocrlf=true 可能是 CRLF，直接比原始字节会误判。
    返回问题描述列表（空列表 = 一致）。
    """
    if entries is None:
        entries = compute_entries(repo_root)
    manifest_path = os.path.join(repo_root, MANIFEST_RELPATH)
    if not os.path.exists(manifest_path):
        return ["! fetch-manifest.txt 不存在: %s" % manifest_path]
    with open(manifest_path, "r", encoding="utf-8", newline="") as fh:
        on_disk = fh.read()
    expected = render_manifest(entries)
    disk_lines = _norm_eol(on_disk).split("\n")
    want_lines = _norm_eol(expected).split("\n")
    if disk_lines == want_lines:
        return []
    problems = []
    for i, (got, want) in enumerate(zip(disk_lines, want_lines), 1):
        if got != want:
            problems.append("! fetch-manifest.txt 第 %d 行不一致：磁盘 %r / 期望 %r" % (i, got, want))
    if len(disk_lines) != len(want_lines):
        problems.append("! fetch-manifest.txt 行数不一致：磁盘 %d 行 / 期望 %d 行" % (
            len(disk_lines), len(want_lines)))
    return problems


def summarize(entries):
    counts = {"valid": 0, "broken": 0, "unresolvable": 0}
    for entry in entries:
        status = entry.get("pin_status")
        if status in counts:
            counts[status] += 1
    return "%d entries, %d valid, %d broken, %d unresolvable" % (
        len(entries), counts["valid"], counts["broken"], counts["unresolvable"])


def summarize_sources(entries):
    """source 分布：mirror 95 / none 2（校验用 mirror 数，不是总数 97）。"""
    counts = {"mirror": 0, "none": 0}
    for entry in entries:
        source = entry.get("source")
        if source in counts:
            counts[source] += 1
    return "%d mirror, %d none" % (counts["mirror"], counts["none"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="catalog.yml 四字段同步工具")
    parser.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--check", action="store_true", help="校验 catalog 与 manifest 是否一致（退出码 0=一致）")
    parser.add_argument("--apply", action="store_true", help="把四字段写回 catalog.yml")
    parser.add_argument("--write-manifest", action="store_true", help="重建 fetch-manifest.txt")
    args = parser.parse_args(argv)

    if not (args.check or args.apply or args.write_manifest):
        parser.print_help()
        return 0

    repo_root = os.path.abspath(args.repo_root)
    try:
        entries = compute_entries(repo_root)

        # 校验必须在重建之前做 —— 否则 --write-manifest 先把 manifest 改对，
        # 再去校验就永远通过，--check 形同虚设。
        check_rc = None
        if args.check:
            # 校验「磁盘上的文件」，不是「脚本推导出来的值」——
            # compute_entries 会用推导值覆盖 commit/clone_url/pin_status/source，
            # 拿它做字段不变量检查就等于拿自己的期望检查自己，删掉一个 null 字段也发现不了。
            with open(os.path.join(repo_root, CATALOG_RELPATH), "r",
                      encoding="utf-8", newline="") as fh:
                on_disk_entries = parse_catalog(fh.read())
            diff = sync_catalog(repo_root, apply=False)
            problems = check_schema(on_disk_entries) + check_manifest(repo_root, entries)
            if diff or problems:
                print("校验未通过，%d 处问题：" % (len(diff) + len(problems)))
                for line in (diff + problems)[:50]:
                    print("  " + line)
                check_rc = 1
            else:
                # stdout 必须逐字等于 "97 entries, 91 valid, 4 broken, 2 unresolvable"
                print(summarize(entries))
                # source 分布只是补充信息，走 stderr，别污染 stdout 的契约
                print(summarize_sources(entries), file=sys.stderr)
                check_rc = 0

        if args.write_manifest:
            path = write_manifest(repo_root)
            print("wrote %s" % path)

        if check_rc is not None:
            return check_rc

        if args.apply:
            diff = sync_catalog(repo_root, apply=True)
            print("applied %d changes" % len(diff))
            for line in diff[:50]:
                print("  " + line)
    except CatalogError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
