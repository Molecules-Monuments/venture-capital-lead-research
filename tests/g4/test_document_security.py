import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "document_cases.json").read_text(encoding="utf-8"))
HELPER = Path(os.environ.get("VCOPS_HELPER", ""))
PYTHON = os.environ.get("G4_PYTHON", sys.executable)


def write_ooxml(path: Path, sheet_xml: str, *, macro: bool = False, external: bool = False, extra=None):
    content_types = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
    ]
    if macro:
        content_types.append('<Override PartName="/xl/vbaProject.bin" ContentType="application/vnd.ms-office.vbaProject"/>')
    if external:
        content_types.append('<Override PartName="/xl/externalLinks/externalLink1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml"/>')
    content_types.append("</Types>")
    workbook_rels = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>',
    ]
    if external:
        workbook_rels.append('<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink" Target="externalLinks/externalLink1.xml"/>')
    workbook_rels.append("</Relationships>")
    files = {
        "[Content_Types].xml": "".join(content_types),
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": "".join(workbook_rels),
        "xl/worksheets/sheet1.xml": sheet_xml,
    }
    if macro:
        files["xl/vbaProject.bin"] = b"malicious macro placeholder"
    if external:
        files["xl/externalLinks/externalLink1.xml"] = '<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><externalBook r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></externalLink>'
        files["xl/externalLinks/_rels/externalLink1.xml.rels"] = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath" Target="https://attacker.invalid/payload.xlsx" TargetMode="External"/></Relationships>'
    if extra:
        files.update(extra)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)


def write_pptx(path: Path, *, macro: bool = False, external: bool = False, doctype: bool = False, embedded: bool = False):
    slide = (
        '<?xml version="1.0"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Acme pitch deck</a:t>'
        '</a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
    )
    if doctype:
        slide = '<!DOCTYPE p:sld [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>' + slide
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0"?><Types '
            'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slides/slide1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            '</Types>'
        ),
        "ppt/presentation.xml": (
            '<?xml version="1.0"?><p:presentation '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
        ),
        "ppt/slides/slide1.xml": slide,
    }
    if macro:
        files["ppt/vbaProject.bin"] = b"macro"
    if embedded:
        files["ppt/embeddings/oleObject1.bin"] = b"embedded"
    if external:
        files["ppt/slides/_rels/slide1.xml.rels"] = (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="image" Target="https://attacker.invalid/x" '
            'TargetMode="External"/></Relationships>'
        )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)


def sheet(rows: int = 1, formula: bool = False):
    cells = '<c r="A1"><f>1+1</f><v>2</v></c>' if formula else '<c r="A1" t="inlineStr"><is><t>safe</t></is></c>'
    row_xml = [f'<row r="1">{cells}</row>']
    row_xml.extend(f'<row r="{idx}"><c r="A{idx}"><v>{idx}</v></c></row>' for idx in range(2, rows + 1))
    return '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(row_xml) + "</sheetData></worksheet>"


def digest(path: Path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            value.update(block)
    return value.hexdigest()


class DocumentSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not str(HELPER) or not HELPER.is_file():
            raise AssertionError("VCOPS_HELPER must name the release vcops.py")
        cls.tmp = tempfile.TemporaryDirectory(prefix="openclaw-g4-doc-")
        cls.base = Path(cls.tmp.name)
        cls.inbox = cls.base / "inbox"
        cls.quarantine = cls.base / "quarantine"
        cls.state = cls.base / "state"
        cls.outside = cls.base / "outside"
        for directory in [cls.inbox, cls.quarantine, cls.state, cls.outside]:
            directory.mkdir()
        (cls.inbox / "valid.csv").write_text("metric,value\narr,1200000\n", encoding="utf-8")
        (cls.inbox / "formula.csv").write_text("metric,value\narr,=1+1\n", encoding="utf-8")
        (cls.outside / "outside-root.csv").write_text("secret,value\nx,1\n", encoding="utf-8")
        (cls.inbox / "unsupported.txt").write_text("not accepted", encoding="utf-8")
        (cls.inbox / "renamed-png.xlsx").write_bytes(b"\x89PNG\r\n\x1a\nnot an office document")
        (cls.inbox / "legacy.xls").write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy")
        (cls.inbox / "oversized.csv").write_bytes(b"x" * (int(CASES["environment"]["VCOPS_MAX_DOCUMENT_BYTES"]) + 1))
        write_ooxml(cls.inbox / "formula.xlsx", sheet(formula=True))
        write_ooxml(cls.inbox / "macro.xlsm", sheet(), macro=True)
        write_ooxml(cls.inbox / "macro-payload.xlsx", sheet(), macro=True)
        write_ooxml(cls.inbox / "external-link.xlsx", sheet(), external=True)
        write_ooxml(cls.inbox / "too-many-rows.xlsx", sheet(rows=6))
        write_ooxml(cls.inbox / "zip-bomb.xlsx", sheet(), extra={"xl/sharedStrings.xml": "A" * 100_000})
        # A structurally-plausible archive (valid end-of-central-directory, so
        # type detection accepts it) whose sheet member's compressed bytes are
        # corrupted: reading it raises library-level BadZipFile/zlib errors
        # rather than a typed VcopsError.
        corrupt = cls.inbox / "corrupt-member.xlsx"
        write_ooxml(corrupt, sheet())
        blob = bytearray(corrupt.read_bytes())
        marker = blob.find(b"sheet1.xml") + len(b"sheet1.xml")
        for index in range(marker, marker + 12):
            blob[index] ^= 0xFF
        corrupt.write_bytes(bytes(blob))
        write_pptx(cls.inbox / "valid.pptx")
        write_pptx(cls.inbox / "macro-payload.pptx", macro=True)
        write_pptx(cls.inbox / "external-link.pptx", external=True)
        write_pptx(cls.inbox / "doctype.pptx", doctype=True)
        write_pptx(cls.inbox / "embedded.pptx", embedded=True)
        (cls.inbox / "symlink.csv").symlink_to(cls.outside / "outside-root.csv")
        (cls.inbox / "linked-parent").symlink_to(cls.outside, target_is_directory=True)
        (cls.inbox / "sub").mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def invoke(self, command, path):
        env = os.environ.copy()
        env.update(CASES["environment"])
        env.update({
            "VCOPS_INBOX_ROOT": str(self.inbox),
            "VCOPS_QUARANTINE_ROOT": str(self.quarantine),
            "VCOPS_STATE_ROOT": str(self.state),
        })
        command_line = [PYTHON, str(HELPER), command, "--path", str(path), "--json"]
        if command == "document-extract":
            command_line.extend(["--idempotency-key", f"g4-{path.name}"])
        proc = subprocess.run(
            command_line,
            text=True,
            capture_output=True,
            env=env,
            timeout=15,
        )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"{command} did not emit one JSON object: rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}: {exc}")
        return proc, payload

    def assert_rejected(self, path, reason_fragment=None, must_quarantine=False):
        source_digest = digest(path) if must_quarantine else None
        before = {item.resolve() for item in self.quarantine.rglob("*") if item.is_file()}
        proc, payload = self.invoke("document-extract" if must_quarantine else "document-preview", path)
        self.assertNotEqual(proc.returncode, 0, (path, payload, proc.stderr))
        self.assertFalse(payload.get("ok", False), (path, payload))
        rendered = json.dumps(payload, sort_keys=True).lower()
        if reason_fragment:
            self.assertIn(reason_fragment, rendered, (path, payload))
        if must_quarantine:
            self.assertIn("quarant", rendered, (path, payload))
            self.assertTrue(path.exists(), f"read-only inbox source was removed: {path}")
            self.assertEqual(digest(path), source_digest, f"read-only inbox source was modified: {path}")
            after = {item.resolve() for item in self.quarantine.rglob("*") if item.is_file()}
            materialized = after - before
            self.assertTrue(materialized, f"no quarantine record/file materialized for {path}")
            copied_payloads = [item for item in materialized if digest(item) == source_digest]
            self.assertTrue(copied_payloads, f"quarantine did not safely copy the rejected bytes for {path}: {materialized}")

    def test_corrupt_ooxml_member_is_quarantined_with_a_review_artifact(self):
        # Library-level parser failures (BadZipFile, zlib.error, openpyxl
        # internals) must route through the same quarantine lane as typed
        # rejections: a review artifact always materializes and the error is
        # structured, never an opaque internal_error with an empty quarantine.
        self.assert_rejected(
            self.inbox / "corrupt-member.xlsx",
            "document_parse_failed",
            must_quarantine=True,
        )

    def test_valid_csv_is_accepted(self):
        proc, payload = self.invoke("document-preview", self.inbox / "valid.csv")
        self.assertEqual(proc.returncode, 0, (payload, proc.stderr))
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("document", {}).get("detected_mime"), "text/csv")

    def test_outside_and_parent_traversal_fail_closed(self):
        self.assert_rejected(self.outside / "outside-root.csv", "intake")
        self.assert_rejected(self.inbox / "sub" / ".." / ".." / "outside" / "outside-root.csv", "unsafe")

    def test_symlink_file_and_symlink_parent_fail_closed(self):
        self.assert_rejected(self.inbox / "symlink.csv", "symlink")
        self.assert_rejected(self.inbox / "linked-parent" / "outside-root.csv", "symlink")

    def test_unsupported_magic_mismatch_and_legacy_xls_quarantine(self):
        self.assert_rejected(self.inbox / "unsupported.txt", must_quarantine=True)
        self.assert_rejected(self.inbox / "renamed-png.xlsx", must_quarantine=True)
        self.assert_rejected(self.inbox / "legacy.xls", must_quarantine=True)

    def test_macro_extensions_and_payloads_quarantine(self):
        self.assert_rejected(self.inbox / "macro.xlsm", "active", must_quarantine=True)
        self.assert_rejected(self.inbox / "macro-payload.xlsx", "active", must_quarantine=True)

    def test_external_relationship_quarantines(self):
        self.assert_rejected(self.inbox / "external-link.xlsx", "external", must_quarantine=True)

    def test_zip_bomb_and_resource_limits_quarantine(self):
        self.assert_rejected(self.inbox / "zip-bomb.xlsx", must_quarantine=True)
        self.assert_rejected(self.inbox / "oversized.csv", "large")

    def test_row_limit_truncates_without_crossing_the_bound(self):
        proc, payload = self.invoke("document-extract", self.inbox / "too-many-rows.xlsx")
        self.assertEqual(proc.returncode, 0, (payload, proc.stderr))
        truncated = (
            payload.get("truncated")
            or payload.get("extraction", {}).get("stats", {}).get("truncated")
            or payload.get("extraction", {}).get("extraction_summary", {}).get("truncated")
        )
        self.assertTrue(truncated, payload)

    def test_xlsx_formula_is_flagged_and_not_evaluated(self):
        proc, payload = self.invoke("document-extract", self.inbox / "formula.xlsx")
        self.assertEqual(proc.returncode, 0, (payload, proc.stderr))
        rendered = json.dumps(payload, sort_keys=True).lower()
        self.assertIn("formula", rendered)
        self.assertNotIn('"evaluated": true', rendered)
        output_path = Path(payload["extracted_json_path"])
        self.assertEqual(output_path.parent.resolve(), (self.state / "extractions").resolve())
        self.assertEqual(output_path.name, f"{payload['extracted_sha256']}.json")
        self.assertTrue(output_path.is_file(), payload)
        extracted = output_path.read_text(encoding="utf-8").lower()
        self.assertNotIn('"computed_value"', extracted)
        self.assertNotIn('"cached_value"', extracted)
        self.assertNotRegex(extracted, r'"value"\s*:\s*(?:"2"|2)(?:\s*[,}])')

    def test_csv_formula_is_flagged_and_preserved_as_untrusted(self):
        proc, payload = self.invoke("document-extract", self.inbox / "formula.csv")
        self.assertEqual(proc.returncode, 0, (payload, proc.stderr))
        rendered = json.dumps(payload, sort_keys=True).lower()
        self.assertIn("formula", rendered)
        self.assertNotIn('"evaluated": true', rendered)
        output_path = Path(payload["extracted_json_path"])
        self.assertEqual(output_path.parent.resolve(), (self.state / "extractions").resolve())
        self.assertEqual(output_path.name, f"{payload['extracted_sha256']}.json")
        self.assertTrue(output_path.is_file(), payload)
        extracted = output_path.read_text(encoding="utf-8")
        self.assertIn("=1+1", extracted, "formula-like CSV cell must remain literal untrusted data")

    def test_valid_pptx_is_extracted_with_slide_provenance(self):
        proc, payload = self.invoke("document-extract", self.inbox / "valid.pptx")
        self.assertEqual(proc.returncode, 0, (payload, proc.stderr))
        self.assertEqual(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            payload["detected_mime"],
        )
        extracted = json.loads(Path(payload["extracted_json_path"]).read_text(encoding="utf-8"))
        self.assertEqual(1, extracted["extraction"]["slides"][0]["slide"])
        self.assertIn("Acme pitch deck", extracted["extraction"]["slides"][0]["text"])

    def test_pptx_active_external_and_xml_payloads_quarantine(self):
        for name, reason in (
            ("macro-payload.pptx", "active"),
            ("external-link.pptx", "external"),
            ("doctype.pptx", "doctype"),
            ("embedded.pptx", "active"),
        ):
            with self.subTest(name=name):
                self.assert_rejected(self.inbox / name, reason, must_quarantine=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
