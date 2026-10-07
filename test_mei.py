"""Sanity checks for the production MEI files.

The checks that fail are problems that break the tools reading these files:

- every @facs must point to a zone or surface in the same file (Cantus
  Ultimus looks bounding boxes up by @facs when indexing);
- xml:ids must be unique (libxml2, which Neon validates with, rejects
  duplicates);
- zones must not have negative coordinates: the MEI schema forbids them, and
  when such a zone is referenced, Neon deletes the referencing element on
  load (DDMAL/MEI_encoding#26).

These are reported as warnings:

- unreferenced zones, all-zero zones and zones outside the page. Neon
  removes unreferenced and all-zero zones itself when it opens a file
  (DDMAL/Neon#1147) and warns about content outside the page, so they don't
  break anything, but they often point to lost content or OMR noise.

Missing zone coordinates count as 0, as in Cantus Ultimus.
"""

import os
import sys
import unittest
from collections import Counter, defaultdict
import xml.etree.ElementTree as ET

MEI = "{http://www.music-encoding.org/ns/mei}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
COORDS = ("ulx", "uly", "lrx", "lry")
MAX_LISTED = 5


def find_mei_files(root="."):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for f in sorted(filenames):
            if f.endswith(".mei"):
                yield os.path.join(dirpath, f)


def listed(items):
    items = sorted(items)
    more = f" (+{len(items) - MAX_LISTED} more)" if len(items) > MAX_LISTED else ""
    return ", ".join(items[:MAX_LISTED]) + more


class MEIFile:
    """The parts of an MEI file that the checks look at."""

    def __init__(self, path):
        root = ET.parse(path).getroot()
        self.body = root.find(f".//{MEI}body")

        id_counts = Counter(e.get(XML_ID) for e in root.iter() if e.get(XML_ID))
        self.duplicate_ids = [i for i, n in id_counts.items() if n > 1]

        self.surfaces = set()
        self.zones = {}  # zone id -> (ulx, uly, lrx, lry, page width, page height)
        for surface in root.iter(f"{MEI}surface"):
            self.surfaces.add(surface.get(XML_ID))
            width, height = int(surface.get("lrx", 0)), int(surface.get("lry", 0))
            for zone in surface.iter(f"{MEI}zone"):
                box = tuple(int(zone.get(c, 0)) for c in COORDS)
                self.zones[zone.get(XML_ID)] = box + (width, height)

        self.facs = []  # ids referenced by @facs inside <body>
        if self.body is not None:
            for element in self.body.iter():
                for target in element.get("facs", "").split():
                    self.facs.append(target.lstrip("#"))

    @property
    def referenced(self):
        return set(self.facs)

    @property
    def unreferenced_zones(self):
        return [z for z in self.zones if z not in self.referenced]

    def outside_page(self, zone_id):
        ulx, uly, lrx, lry, width, height = self.zones[zone_id]
        return lrx > width or lry > height


class TestMEIFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {}
        cls.parse_errors = {}
        for path in find_mei_files():
            try:
                cls.files[path] = MEIFile(path)
            except ET.ParseError as e:
                cls.parse_errors[path] = str(e)

    @classmethod
    def tearDownClass(cls):
        """Report the warnings, which don't fail the tests."""
        warnings = defaultdict(Counter)
        for path, mei in cls.files.items():
            folder = os.path.basename(os.path.dirname(path))
            unref = mei.unreferenced_zones
            if unref:
                warnings[folder]["files with unreferenced zones"] += 1
                warnings[folder]["unreferenced zones"] += len(unref)
            all_zero = [z for z, box in mei.zones.items() if not any(box[:4])]
            if all_zero:
                warnings[folder]["files with all-zero zones"] += 1
                warnings[folder]["all-zero zones"] += len(all_zero)
            outside = [z for z in mei.zones if mei.outside_page(z)]
            if outside:
                warnings[folder]["files with zones outside the page"] += 1
                warnings[folder]["zones outside the page"] += len(outside)

        in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
        for folder, counts in sorted(warnings.items()):
            summary = "; ".join(f"{n} {what}" for what, n in counts.items())
            if in_ci:
                print(f"::warning title=MEI warnings in {folder}::{summary}")
            else:
                print(f"\nWARNING {folder}: {summary}", file=sys.stderr)

    def test_files_parse(self):
        for path, error in self.parse_errors.items():
            with self.subTest(filepath=path):
                self.fail(f"Not well-formed XML: {error}")
        for path, mei in self.files.items():
            with self.subTest(filepath=path):
                self.assertIsNotNone(mei.body, "No <body> element.")

    def test_no_dangling_facs(self):
        for path, mei in self.files.items():
            known = set(mei.zones) | mei.surfaces
            dangling = {t for t in mei.facs if t not in known}
            with self.subTest(filepath=path):
                self.assertFalse(
                    dangling,
                    f"{len(dangling)} @facs point to no zone or surface: {listed(dangling)}",
                )

    def test_no_duplicate_ids(self):
        for path, mei in self.files.items():
            with self.subTest(filepath=path):
                self.assertFalse(
                    mei.duplicate_ids,
                    f"Duplicate xml:ids: {listed(mei.duplicate_ids)}",
                )

    def test_no_negative_coordinates(self):
        for path, mei in self.files.items():
            negative = [z for z, box in mei.zones.items() if min(box[:4]) < 0]
            with self.subTest(filepath=path):
                self.assertFalse(
                    negative,
                    f"{len(negative)} zones with negative coordinates: {listed(negative)}",
                )


if __name__ == "__main__":
    unittest.main()
