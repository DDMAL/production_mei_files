import os
import re
import unittest


class TestMEIFiles(unittest.TestCase):
    def setUp(self):
        self.files = {}
        for root, _, filenames in os.walk("."):
            for f in sorted(filenames):
                if not f.endswith(".mei"):
                    continue
                filepath = os.path.join(root, f)
                with open(filepath, "r") as fd:
                    filedata = fd.read()
                self.files[filepath] = filedata

    def test_no_unreferenced_zones(self):
        zone_id = r"zone.*xml:id=\"([a-z0-9-]*)\""
        for filepath, filedata in self.files.items():
            zones = re.findall(zone_id, filedata)
            body = filedata.split("<body>")[1]
            unref = [z for z in zones if z not in body]
            with self.subTest(filepath=filepath):
                msg = f"{len(unref)} unreferenced zones detected in this file."
                self.assertFalse(unref, msg=msg)
