import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_catalog import (parse_catalog, render_manifest, check_schema,
                          check_manifest, _catalog_text, main)
import io
import contextlib
import subprocess
import tempfile

CATALOG_CRLF = "projects:\r\n  - name: faiss\r\n    model: vector\r\n    tier: core\r\n"
CATALOG_LF = CATALOG_CRLF.replace("\r\n", "\n")


class TestParse(unittest.TestCase):
    def test_parses_crlf(self):
        """G4: catalog.yml 当前是 CRLF 行尾，解析器必须能读。"""
        entries = parse_catalog(CATALOG_CRLF)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "faiss")
        self.assertEqual(entries[0]["model"], "vector")

    def test_parses_lf(self):
        """F3: 编辑器把 CRLF 改成 LF 后仍须能解析。"""
        entries = parse_catalog(CATALOG_LF)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "faiss")

    def test_parses_notes_list(self):
        """notes 是 YAML 列表，不是标量。"""
        text = ("projects:\n  - name: x\n    model: vector\n"
                "    notes:\n      - 说明一\n      - 说明二\n")
        entries = parse_catalog(text)
        self.assertEqual(entries[0]["notes"], ["说明一", "说明二"])


class TestRender(unittest.TestCase):
    def test_manifest_has_five_columns(self):
        """manifest 是 5 列 lockfile：model/name/clone_url/commit/pin_status。"""
        entries = [{
            "name": "faiss", "model": "vector",
            "clone_url": "https://example/faiss.git",
            "commit": "0" * 40, "pin_status": "valid",
        }]
        lines = [l for l in render_manifest(entries).split("\n") if l.strip()]
        header = lines[0]
        self.assertIn("commit", header)
        self.assertIn("pin_status", header)
        row = lines[1].split("\t")
        self.assertEqual(len(row), 5)
        self.assertEqual(row[3], "0" * 40)
        self.assertEqual(row[4], "valid")

    def test_manifest_uses_dash_for_empty(self):
        """空值用 '-'，避免与 YAML null 混淆。"""
        entries = [{
            "name": "oceanbase", "model": "distributed-sql",
            "clone_url": None, "commit": None, "pin_status": "unresolvable",
        }]
        row = [l for l in render_manifest(entries).split("\n")
               if l.strip() and not l.startswith("#")][0].split("\t")
        self.assertEqual(row[2], "-")
        self.assertEqual(row[3], "-")
        self.assertEqual(row[4], "unresolvable")


class TestCheckSchema(unittest.TestCase):
    """设计文档 §5.5.2 一致性校验规则 1/3/4/5 —— 字段级不变量。"""

    def _entry(self, **over):
        e = {
            "name": "tdengine", "model": "time-series", "tier": "core",
            "repository": "https://example/tdengine.git",
            "mirror": "https://example/tdengine.git",
            "license": "AGPL-3.0", "status": "active",
            "notes": ["时序数据库", "pin 失效：上游不存在该 commit"],
            "commit": None, "clone_url": "https://example/tdengine.git",
            "pin_status": "broken", "source": "mirror",
        }
        e.update(over)
        return e

    def test_broken_entry_without_explanation_is_rejected(self):
        """规则 3：broken 的 notes 必须说明失效原因与受影响的笔记。"""
        problems = check_schema([self._entry(notes=["时序数据库"])])
        self.assertTrue(any("notes" in p for p in problems), problems)

    def test_broken_entry_with_explanation_passes(self):
        self.assertEqual(check_schema([self._entry()]), [])

    def test_broken_entry_with_commit_is_rejected(self):
        """规则 3：broken 的 commit 必须为 null（不得照抄伪造 SHA）。"""
        problems = check_schema([self._entry(commit="a" * 40)])
        self.assertTrue(any("commit" in p for p in problems), problems)

    def test_valid_entry_requires_hex_commit(self):
        problems = check_schema([self._entry(
            pin_status="valid", commit="not-a-sha", clone_url="https://e/x.git")])
        self.assertTrue(any("40 位 hex" in p for p in problems), problems)

    def test_valid_entry_requires_clone_url(self):
        problems = check_schema([self._entry(
            pin_status="valid", commit="a" * 40, clone_url=None)])
        self.assertTrue(any("clone_url" in p for p in problems), problems)

    def test_unresolvable_requires_source_none(self):
        problems = check_schema([self._entry(
            pin_status="unresolvable", source="mirror",
            clone_url=None, commit=None)])
        self.assertTrue(any("source" in p for p in problems), problems)

    def test_unresolvable_requires_null_clone_url(self):
        problems = check_schema([self._entry(
            pin_status="unresolvable", source="none", commit=None,
            clone_url="https://e/x.git")])
        self.assertTrue(any("clone_url" in p for p in problems), problems)

    def test_missing_required_field_is_reported(self):
        e = self._entry()
        del e["license"]
        problems = check_schema([e])
        self.assertTrue(any("license" in p for p in problems), problems)

    def test_illegal_pin_status_is_reported(self):
        problems = check_schema([self._entry(pin_status="whatever")])
        self.assertTrue(any("pin_status" in p for p in problems), problems)


class TestCheckManifest(unittest.TestCase):
    """设计文档 §5.5.2 规则 9：fetch-manifest.txt 必须与 catalog 生成结果一致。"""

    ENTRIES = [{
        "name": "faiss", "model": "vector",
        "clone_url": "https://example/faiss.git",
        "commit": "0" * 40, "pin_status": "valid",
    }]

    def _repo(self, manifest_text):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "reference"))
        with open(os.path.join(d, "reference", "fetch-manifest.txt"),
                  "w", encoding="utf-8", newline="") as fh:
            fh.write(manifest_text)
        return d

    def test_matching_manifest_passes(self):
        d = self._repo(render_manifest(self.ENTRIES))
        self.assertEqual(check_manifest(d, self.ENTRIES), [])

    def test_crlf_manifest_is_tolerated(self):
        """Windows 工作区因 core.autocrlf=true 是 CRLF —— 不该被判为不一致。"""
        d = self._repo(render_manifest(self.ENTRIES).replace("\n", "\r\n"))
        self.assertEqual(check_manifest(d, self.ENTRIES), [])

    def test_emptied_manifest_is_detected(self):
        d = self._repo("")
        self.assertTrue(check_manifest(d, self.ENTRIES))

    def test_garbage_manifest_is_detected(self):
        d = self._repo("hello world\nnot a manifest\n")
        self.assertTrue(check_manifest(d, self.ENTRIES))

    def test_flipped_sha_is_detected(self):
        text = render_manifest(self.ENTRIES).replace("0" * 40, "1" * 40)
        d = self._repo(text)
        self.assertTrue(check_manifest(d, self.ENTRIES))

    def test_missing_manifest_is_detected(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "reference"))
        self.assertTrue(check_manifest(d, self.ENTRIES))


class TestWriteBackMixedEol(unittest.TestCase):
    """写回路径必须容忍混合行尾 —— 纯 LF 文件里混进一个 CRLF 时不能静默 no-op。"""

    def _write_catalog(self, text):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "reference"))
        with open(os.path.join(d, "reference", "catalog.yml"),
                  "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return d

    def _entries(self):
        return [{
            "name": "x", "model": "vector", "tier": "core",
            "repository": "https://e/x.git", "license": "MIT", "status": "active",
            "notes": ["说明"], "commit": "a" * 40,
            "clone_url": "https://e/x.git", "pin_status": "valid", "source": "mirror",
        }]

    def test_mixed_eol_still_writes_the_four_fields(self):
        text = ("projects:\n  - name: x\n    model: vector\n    tier: core\n"
                "    repository: https://e/x.git\n    license: MIT\n"
                "    status: active\r\n    notes:\n      - 说明\n")
        d = self._write_catalog(text)
        out = _catalog_text(d, self._entries())
        for field in ("commit", "clone_url", "pin_status", "source"):
            self.assertIn("    %s: " % field, out)

    def test_crlf_file_keeps_crlf(self):
        text = ("projects:\r\n  - name: x\r\n    model: vector\r\n    tier: core\r\n"
                "    repository: https://e/x.git\r\n    license: MIT\r\n"
                "    status: active\r\n    notes:\r\n      - 说明\r\n")
        d = self._write_catalog(text)
        out = _catalog_text(d, self._entries())
        self.assertIn("\r\n", out)
        self.assertEqual(out.count("\n"), out.count("\r\n"))

    def test_lf_file_keeps_lf(self):
        text = ("projects:\n  - name: x\n    model: vector\n    tier: core\n"
                "    repository: https://e/x.git\n    license: MIT\n"
                "    status: active\n    notes:\n      - 说明\n")
        d = self._write_catalog(text)
        out = _catalog_text(d, self._entries())
        self.assertNotIn("\r\n", out)


class TestMainCheckExitCode(unittest.TestCase):
    """--check 的退出码是本工具的核心契约 —— 必须真的能挡住 manifest 漂移。"""

    SHA = "0123456789abcdef0123456789abcdef01234567"

    CATALOG = (
        "projects:\n"
        "  - name: x\n"
        "    model: vector\n"
        "    tier: core\n"
        "    repository: https://example/x.git\n"
        "    mirror: https://example/x.git\n"
        "    license: MIT\n"
        "    status: active\n"
        "    commit: %s\n"
        "    clone_url: https://example/x.git\n"
        "    pin_status: valid\n"
        "    source: mirror\n"
        "    notes:\n"
        "      - 说明\n"
    ) % SHA

    def _repo(self, manifest_text):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "reference"))
        with open(os.path.join(d, "reference", "catalog.yml"),
                  "w", encoding="utf-8", newline="") as fh:
            fh.write(self.CATALOG)
        with open(os.path.join(d, "reference", "fetch-manifest.txt"),
                  "w", encoding="utf-8", newline="") as fh:
            fh.write(manifest_text)
        subprocess.run(["git", "init", "-q", d], check=True, capture_output=True)
        subprocess.run(["git", "-C", d, "update-index", "--add", "--cacheinfo",
                        "160000,%s,reference/vector/x" % self.SHA],
                       check=True, capture_output=True)
        return d

    def _run(self, repo):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--check", "--repo-root", repo])
        return rc, buf.getvalue()

    def _good_manifest(self):
        return render_manifest([{
            "name": "x", "model": "vector", "clone_url": "https://example/x.git",
            "commit": self.SHA, "pin_status": "valid"}])

    def test_consistent_repo_exits_zero(self):
        d = self._repo(self._good_manifest())
        rc, out = self._run(d)
        self.assertEqual(rc, 0, out)

    def test_emptied_manifest_exits_nonzero(self):
        d = self._repo("")
        rc, out = self._run(d)
        self.assertNotEqual(rc, 0, out)

    def test_garbage_manifest_exits_nonzero(self):
        d = self._repo("hello world\n")
        rc, out = self._run(d)
        self.assertNotEqual(rc, 0, out)

    def test_missing_manifest_exits_nonzero(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "reference"))
        with open(os.path.join(d, "reference", "catalog.yml"),
                  "w", encoding="utf-8", newline="") as fh:
            fh.write(self.CATALOG)
        subprocess.run(["git", "init", "-q", d], check=True, capture_output=True)
        subprocess.run(["git", "-C", d, "update-index", "--add", "--cacheinfo",
                        "160000,%s,reference/vector/x" % self.SHA],
                       check=True, capture_output=True)
        rc, out = self._run(d)
        self.assertNotEqual(rc, 0, out)

    def test_non_git_repo_reports_clean_error(self):
        """非 git 目录要报一行人话，不是 traceback。"""
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "reference"))
        with open(os.path.join(d, "reference", "catalog.yml"),
                  "w", encoding="utf-8", newline="") as fh:
            fh.write(self.CATALOG)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--check", "--repo-root", d])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
