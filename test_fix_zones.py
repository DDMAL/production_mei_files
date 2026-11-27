"""Tests for utilities/fix_zones.py, on small hand-written files."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utilities"))
import fix_zones  # noqa: E402

HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" xmlns:xlink="http://www.w3.org/1999/xlink">
  <meiHead>
    <fileDesc>
      <titleStmt>
        <title{title_facs}>Test</title>
      </titleStmt>
    </fileDesc>
  </meiHead>
  <music>
    <facsimile>
      <surface xml:id="page" ulx="0" uly="0" lrx="1000" lry="1000">
{zones}
      </surface>
    </facsimile>
    <body>
      <mdiv>
        <score>
          <section>
{content}
          </section>
        </score>
      </mdiv>
    </body>
  </music>
</mei>
"""

GOOD = '        <zone xml:id="good" ulx="10" uly="10" lrx="20" lry="20"/>'
ZERO = '        <zone xml:id="zero" ulx="0" uly="0" lrx="0" lry="0"/>'
OUTSIDE = '        <zone xml:id="outside" ulx="10" uly="10" lrx="2000" lry="20"/>'


def mei(zones, content, title_facs=""):
    return HEAD.format(zones="\n".join(zones), content=content, title_facs=title_facs)


class FixZonesTest(unittest.TestCase):
    def fix(self, text):
        """Run the script on text and return the changed text."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.mei")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            fix_zones.fix_file(path, write=True)
            with open(path, encoding="utf-8", newline="") as f:
                return f.read()

    def test_keeps_valid_target_when_another_is_missing(self):
        text = mei([GOOD], '            <syl xml:id="s" facs="#good #missing">a</syl>')
        self.assertIn('<syl xml:id="s" facs="#good">a</syl>', self.fix(text))

    def test_keeps_valid_target_when_another_zone_is_deleted(self):
        text = mei([GOOD, ZERO], '            <syl xml:id="s" facs="#good #zero">a</syl>')
        new = self.fix(text)
        self.assertIn('<syl xml:id="s" facs="#good">a</syl>', new)
        self.assertNotIn('xml:id="zero"', new)
        self.assertIn('xml:id="good"', new)

    def test_removes_attribute_when_no_target_is_left(self):
        text = mei([GOOD], '            <syl xml:id="s" facs="#missing">a</syl>')
        self.assertIn('<syl xml:id="s">a</syl>', self.fix(text))

    def test_zone_referenced_from_header_is_kept(self):
        # Outside the page, so it would be deleted if nothing referenced it
        text = mei([GOOD, OUTSIDE], '            <syl xml:id="s" facs="#good">a</syl>',
                   title_facs=' xml:id="t" facs="#outside"')
        self.assertEqual(self.fix(text), text)

    def test_dangling_reference_in_header_is_removed(self):
        text = mei([GOOD], '            <syl xml:id="s" facs="#good">a</syl>',
                   title_facs=' xml:id="t" facs="#missing"')
        self.assertIn('<title xml:id="t">Test</title>', self.fix(text))

    def test_duplicate_deletion_leaves_comments_alone(self):
        comment = '            <!-- for example: <divLine xml:id="d"/> -->'
        line = '            <divLine xml:id="d"/>'
        text = mei([GOOD], "\n".join([comment, line, line]))
        new = self.fix(text)
        self.assertIn(comment, new)
        self.assertEqual(new.count(line), 1)

    def test_zone_deletion_leaves_comments_alone(self):
        comment = '        <!-- was <zone xml:id="zero" ulx="0" uly="0" lrx="0" lry="0"/> -->'
        text = mei([GOOD, comment, ZERO], '            <syl xml:id="s" facs="#good">a</syl>')
        new = self.fix(text)
        self.assertIn(comment, new)
        self.assertNotIn(ZERO, new)

    def test_verification_catches_changed_comment(self):
        text = mei([GOOD], '            <!-- note --><syl xml:id="s" facs="#good">a</syl>')
        changed = text.replace("note", "")
        self.assertNotEqual(fix_zones.snapshot(fix_zones.parse(text)),
                            fix_zones.snapshot(fix_zones.parse(changed)))

    def test_verification_catches_changed_text(self):
        text = mei([GOOD], '            <syl xml:id="s" facs="#good">a b</syl>')
        changed = text.replace("a b", "ab")
        self.assertNotEqual(fix_zones.snapshot(fix_zones.parse(text)),
                            fix_zones.snapshot(fix_zones.parse(changed)))


if __name__ == "__main__":
    unittest.main()
