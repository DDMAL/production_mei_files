"""Repair the zone problems that test_mei.py reports, where that is lossless.

Every repair removes something that carries no usable information:

- unreferenced zones with negative or all-zero coordinates, or lying outside
  their page, are deleted;
- referenced zones with negative or all-zero coordinates are deleted, and the
  reference to them is removed from @facs (the element keeps its content, it
  just no longer claims a meaningless position);
- @facs references that point to no zone or surface are removed;
- exact copies of an element that repeat its xml:id are deleted.

Only the bad references are removed from a @facs: "#good #missing" becomes
"#good", and the attribute goes only when no reference is left. References are
looked for in the whole file, not only in <body>, so a zone that a header
element points to is never treated as unused.

Files are edited as text, so everything else (formatting, line endings, XML
declarations) is left byte-for-byte as it was. Matches inside comments, CDATA
sections and processing instructions are never edited. Each edited file is
re-parsed and compared against the original, including its comments and text,
to confirm nothing else changed.

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

# Markup whose content is not elements, so it must never be edited
PROTECTED = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>", re.S)


class FixError(Exception):
    pass


def parse(text):
    """Parse keeping comments and processing instructions, so they are compared too."""
    builder = ET.TreeBuilder(insert_comments=True, insert_pis=True)
    return ET.fromstring(text.encode("utf-8"), parser=ET.XMLParser(target=builder))


def tag_name(element):
    return element.tag.replace(MEI, "")


def zone_box(zone):
    # Missing coordinates count as 0, as in Cantus Ultimus.
    return tuple(int(zone.get(c, 0)) for c in COORDS)


def invalid_box(box):
    return min(box) < 0 or not any(box)


def remaining_facs(value, targets):
    """@facs with the given targets (ids without '#') removed."""
    return " ".join(t for t in value.split() if t.lstrip("#") not in targets)


def plan_changes(root, all_unreferenced=False):
    """Decide what to change. Returns (zones, facs, duplicates, changes).

    zones: zone ids to delete
    facs: element id -> the @facs targets to remove from it
    duplicates: ids of elements whose later identical copies are deleted
    changes: rows for the report
    """
    surfaces = {s.get(XML_ID) for s in root.iter(f"{MEI}surface")}
    zones = {}
    for surface in root.iter(f"{MEI}surface"):
        width, height = int(surface.get("lrx", 0)), int(surface.get("lry", 0))
        for zone in surface.iter(f"{MEI}zone"):
            zones[zone.get(XML_ID)] = (zone_box(zone), width, height)

    # The whole document, not only <body>: a header element such as a title
    # can point to a zone too.
    referrers = {}  # zone id -> [elements]
    dangling = []
    for element in root.iter():
        for target in element.get("facs", "").split():
            target = target.lstrip("#")
            if target in zones:
                referrers.setdefault(target, []).append(element)
            elif target not in surfaces:
                dangling.append((element, target))

    remove_zones, changes = set(), []
    removals = []  # (element, target, reason, coordinates)

    for zone_id, (box, width, height) in zones.items():
        coords = " ".join(map(str, box))
        if zone_id in referrers:
            if invalid_box(box):
                remove_zones.add(zone_id)
                changes.append(("delete referenced zone", zone_id, "zone",
                                "negative or all-zero coordinates", coords))
                for element in referrers[zone_id]:
                    removals.append((element, zone_id, f"pointed to deleted zone {zone_id}", coords))
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
        removals.append((element, target, f"pointed to missing zone {target}", ""))

    remove_facs = {}
    for element, target, _, _ in removals:
        if element.get(XML_ID) is None:
            raise FixError(f"a {tag_name(element)} with a @facs to change has no xml:id")
        remove_facs.setdefault(element.get(XML_ID), set()).add(target)
    for element, target, reason, coords in removals:
        left = remaining_facs(element.get("facs"), remove_facs[element.get(XML_ID)])
        action = "remove from @facs" if left else "remove @facs"
        changes.append((action, element.get(XML_ID), tag_name(element), reason, coords))

    ids = Counter(e.get(XML_ID) for e in root.iter() if e.get(XML_ID))
    duplicates = {i for i, n in ids.items() if n > 1}
    for dup in sorted(duplicates):
        changes.append(("delete duplicate element", dup, "", f"{ids[dup] - 1} identical copies", ""))

    return remove_zones, remove_facs, duplicates, changes


def unprotected_matches(pattern, text):
    """Matches of pattern that don't start inside a comment, CDATA section or
    processing instruction."""
    spans = [m.span() for m in PROTECTED.finditer(text)]
    return [m for m in pattern.finditer(text)
            if not any(start <= m.start() < end for start, end in spans)]


def start_tag_pattern(element_id):
    return re.compile(r'<[A-Za-z]+\b[^<>]*\sxml:id="' + re.escape(element_id) + r'"[^<>]*>')


def delete_element(text, element_id, keep_first):
    """Delete a self-closing element by id, with its line if it has one to itself."""
    pattern = re.compile(r'(\r?\n[ \t]*)?<[A-Za-z]+\b[^<>]*\sxml:id="'
                         + re.escape(element_id) + r'"[^<>]*/>')
    matches = unprotected_matches(pattern, text)
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


def remove_facs_targets(text, element_id, targets):
    """Remove targets from the element's @facs, and the attribute if none are left."""
    matches = unprotected_matches(start_tag_pattern(element_id), text)
    if len(matches) != 1:
        raise FixError(f"start tag of {element_id} found {len(matches)} times")
    m = matches[0]
    tag = m.group(0)
    attrs = list(re.finditer(r'(\s+)facs="([^"]*)"', tag))
    if len(attrs) != 1:
        raise FixError(f"{element_id} has {len(attrs)} @facs")
    a = attrs[0]
    left = remaining_facs(a.group(2), targets)
    replacement = f'{a.group(1)}facs="{left}"' if left else ""
    new_tag = tag[:a.start()] + replacement + tag[a.end():]
    return text[:m.start()] + new_tag + text[m.end():]


def snapshot(root, drop_zones=(), facs=None, dedupe=()):
    """The document as a flat list of tags with their attributes, comments,
    processing instructions and text, after the intended changes.

    Text is compared with whitespace collapsed, because deleting an element's
    line changes only whitespace; text that is joined or changed in any other
    way still shows up as a difference.
    """
    facs = facs or {}
    seen = set()
    items = []

    def add_text(s):
        if s:
            items.append(("text", s))

    def walk(e):
        element_id = e.get(XML_ID)
        skip = element_id in drop_zones or (element_id in dedupe and element_id in seen)
        if element_id in dedupe:
            seen.add(element_id)
        if not skip:
            if e.tag is ET.Comment:
                items.append(("comment", e.text))
            elif e.tag is ET.ProcessingInstruction:
                items.append(("pi", e.text))
            else:
                attrib = dict(e.attrib)
                if element_id in facs:
                    left = remaining_facs(attrib.get("facs", ""), facs[element_id])
                    if left:
                        attrib["facs"] = left
                    else:
                        attrib.pop("facs", None)
                items.append(("start", e.tag, sorted(attrib.items())))
                add_text(e.text)
                for child in e:
                    walk(child)
                items.append(("end", e.tag))
        # A deleted element's tail stays in the document
        add_text(e.tail)

    walk(root)

    merged = []
    for item in items:
        if item[0] == "text" and merged and merged[-1][0] == "text":
            merged[-1] = ("text", merged[-1][1] + item[1])
        else:
            merged.append(item)
    return [("text", " ".join(i[1].split())) if i[0] == "text" else i
            for i in merged if i[0] != "text" or i[1].strip()]


def fix_file(path, all_unreferenced=False, write=False):
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    root = parse(text)
    zones, facs, duplicates, changes = plan_changes(root, all_unreferenced)
    if not changes:
        return []

    new = text
    for element_id in duplicates:
        new = delete_element(new, element_id, keep_first=True)
    for element_id, targets in facs.items():
        new = remove_facs_targets(new, element_id, targets)
    for zone_id in zones:
        new = delete_element(new, zone_id, keep_first=False)

    expected = snapshot(root, zones, facs, duplicates)
    if snapshot(parse(new)) != expected:
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
