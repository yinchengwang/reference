import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_catalog import parse_catalog, render_manifest

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


if __name__ == "__main__":
    unittest.main()
