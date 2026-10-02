"""Repair the zone problems that test_mei.py reports, where that is lossless.

Every repair removes something that carries no usable information:

- unreferenced zones with negative or all-zero coordinates, or lying outside
  their page, are deleted;
- referenced zones with negative or all-zero coordinates are deleted, and the
  @facs pointing to them is removed (the element keeps its content, it just no
  longer claims a meaningless position);
- @facs that point to no zone or surface are removed;
- exact copies of an element that repeat its xml:id are deleted.

Files are edited as text, so everything else (formatting, line endings, XML
declarations) is left byte-for-byte as it was. Each edited file is re-parsed
and compared against the original to confirm nothing else changed.

Without --write, nothing is modified and the changes are only reported.

    python utilities/fix_zones.py 123606 123723 --report changes.csv
    python utilities/fix_zones.py 123606 123723 --report changes.csv --write
"""

import argparse
import csv
import os
import re
import sys
from collections import Counter
import xml.etree.ElementTree as ET

MEI = "{http://www.music-encoding.org/ns/mei}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
COORDS = ("ulx", "uly", "lrx", "lry")


class FixError(Exception):
    pass


def tag_name(element):
    return element.tag.replace(MEI, "")


def zone_box(zone):
    # Missing coordinates count as 0, as in Cantus Ultimus.
    return tuple(int(zone.get(c, 0)) for c in COORDS)


def invalid_box(box):
    return min(box) < 0 or not any(box)


def plan_changes(root, all_unreferenced=False):
    """Decide what to change. Returns (zones, facs, duplicates, changes).

    zones: zone ids to delete
    facs: ids of elements whose @facs is removed
    duplicates: ids of elements whose later identical copies are deleted
    changes: rows for the report
    """
    body = root.find(f".//{MEI}body")
    surfaces = {s.get(XML_ID) for s in root.iter(f"{MEI}surface")}
    zones = {}
    for surface in root.iter(f"{MEI}surface"):
        width, height = int(surface.get("lrx", 0)), int(surface.get("lry", 0))
        for zone in surface.iter(f"{MEI}zone"):
            zones[zone.get(XML_ID)] = (zone_box(zone), width, height)

    referrers = {}  # zone id -> [elements]
    dangling = []
    for element in body.iter():
        for target in element.get("facs", "").split():
            target = target.lstrip("#")
            if target in zones:
                referrers.setdefault(target, []).append(element)
            elif target not in surfaces:
                dangling.append((element, target))

    remove_zones, remove_facs, changes = set(), set(), []

    for zone_id, (box, width, height) in zones.items():
        coords = " ".join(map(str, box))
        if zone_id in referrers:
            if invalid_box(box):
                remove_zones.add(zone_id)
                changes.append(("delete referenced zone", zone_id, "zone",
                                "negative or all-zero coordinates", coords))
                for element in referrers[zone_id]:
                    remove_facs.add(element.get(XML_ID))
                    changes.append(("remove @facs", element.get(XML_ID), tag_name(element),
                                    f"pointed to deleted zone {zone_id}", coords))
            continue
        if invalid_box(box):
            reason = "unreferenced, negative or all-zero coordinates"
        elif box[2] > width or box[3] > height:
            reason = "unreferenced, outside the page"
        elif all_unreferenced:
            reason = "unreferenced"
        else:
            continue
        remove_zones.add(zone_id)
        changes.append(("delete unreferenced zone", zone_id, "zone", reason, coords))

    for element, target in dangling:
        remove_facs.add(element.get(XML_ID))
        changes.append(("remove @facs", element.get(XML_ID), tag_name(element),
                        f"pointed to missing zone {target}", ""))

    ids = Counter(e.get(XML_ID) for e in root.iter() if e.get(XML_ID))
    duplicates = {i for i, n in ids.items() if n > 1}
    for dup in sorted(duplicates):
        changes.append(("delete duplicate element", dup, "", f"{ids[dup] - 1} identical copies", ""))

    if None in remove_facs:
        raise FixError("an element with a @facs to remove has no xml:id")
    return remove_zones, remove_facs, duplicates, changes


def start_tag_pattern(element_id):
    return re.compile(r'<[A-Za-z]+\b[^<>]*\sxml:id="' + re.escape(element_id) + r'"[^<>]*>')


def delete_element(text, element_id, keep_first):
    """Delete a self-closing element by id, with its line if it has one to itself."""
    pattern = re.compile(r'(\r?\n[ \t]*)?<[A-Za-z]+\b[^<>]*\sxml:id="'
                         + re.escape(element_id) + r'"[^<>]*/>')
    matches = list(pattern.finditer(text))
    if not matches:
        raise FixError(f"self-closing element {element_id} not found")
    if keep_first:
        tags = {m.group(0).lstrip() for m in matches}
        if len(tags) != 1:
            raise FixError(f"copies of {element_id} are not identical")
        matches = matches[1:]
    elif len(matches) != 1:
        raise FixError(f"{element_id} found {len(matches)} times")
    for m in reversed(matches):
        text = text[:m.start()] + text[m.end():]
    return text


def remove_facs_attribute(text, element_id):
    matches = list(start_tag_pattern(element_id).finditer(text))
    if len(matches) != 1:
        raise FixError(f"start tag of {element_id} found {len(matches)} times")
    m = matches[0]
    new_tag, n = re.subn(r'\s+facs="[^"]*"', "", m.group(0))
    if n != 1:
        raise FixError(f"{element_id} has {n} @facs")
    return text[:m.start()] + new_tag + text[m.end():]


def snapshot(root, drop_zones=(), drop_facs=(), dedupe=()):
    """Every element as (tag, attributes, text), after the intended changes."""
    seen = set()
    elements = []
    for e in root.iter():
        element_id = e.get(XML_ID)
        if element_id in drop_zones:
            continue
        if element_id in dedupe:
            if element_id in seen:
                continue
            seen.add(element_id)
        attrib = dict(e.attrib)
        if element_id in drop_facs:
            attrib.pop("facs", None)
        elements.append((e.tag, sorted(attrib.items()), (e.text or "").strip()))
    return elements


def fix_file(path, all_unreferenced=False, write=False):
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    root = ET.fromstring(text.encode("utf-8"))
    zones, facs, duplicates, changes = plan_changes(root, all_unreferenced)
    if not changes:
        return []

    new = text
    for element_id in duplicates:
        new = delete_element(new, element_id, keep_first=True)
    for element_id in facs:
        new = remove_facs_attribute(new, element_id)
    for zone_id in zones:
        new = delete_element(new, zone_id, keep_first=False)

    expected = snapshot(root, zones, facs, duplicates)
    if snapshot(ET.fromstring(new.encode("utf-8"))) != expected:
        raise FixError("edited file differs from the original in unexpected ways")

    if write:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new)
    return changes


def mei_files(paths):
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.endswith(".mei"):
                    yield os.path.join(path, name)
        else:
            yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+", help="MEI files or folders of MEI files")
    parser.add_argument("--write", action="store_true", help="modify the files (default: report only)")
    parser.add_argument("--all-unreferenced", action="store_true",
                        help="also delete unreferenced zones that are otherwise valid")
    parser.add_argument("--report", help="write every change to this CSV file")
    args = parser.parse_args()

    rows, failed, totals = [], [], Counter()
    for path in mei_files(args.paths):
        try:
            changes = fix_file(path, args.all_unreferenced, args.write)
        except (FixError, ET.ParseError) as e:
            failed.append((path, str(e)))
            continue
        for change in changes:
            totals[change[0]] += 1
            rows.append((path,) + change)

    if args.report:
        with open(args.report, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["file", "action", "id", "element", "reason", "coordinates"])
            writer.writerows(rows)

    verb = "Changed" if args.write else "Would change"
    print(f"{verb} {len({r[0] for r in rows})} files:")
    for action, n in totals.most_common():
        print(f"  {n:6d}  {action}")
    for path, error in failed:
        print(f"SKIPPED {path}: {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
