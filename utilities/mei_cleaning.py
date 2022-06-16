import xml.etree.ElementTree as ET
from itertools import combinations
import argparse
import re
import os

parser = argparse.ArgumentParser(description="Utilities for cleaning mei files")
parser.add_argument('mei_path', type = str, nargs = '?', help = "Path to mei file for cleaning. If a directory, cleans all mei files in the directory.",action = 'store')
parser.add_argument('--remove_unreferenced_zones', action = 'store_true', help = "If flagged, removes zones/bounding boxes that are defined but not referenced anywhere in the body.")
parser.add_argument('--remove_identical_duplicates', action = 'store_true', help = "If flagged, removes duplicate zones/bounding boxes and duplicate objects that reference those bounding boxes.")
parser.add_argument('--destination_path', action = 'store', default = None, type = str, nargs = '?', help = "If provided, the cleaned file is save here. If omitted, file is save to mei_path location. If mei_path is a directory, this should also be a directory.")
args = parser.parse_args()

MEINS = "{http://www.music-encoding.org/ns/mei}"
XMLNS = "{http://www.w3.org/XML/1998/namespace}"

ET.register_namespace("","http://www.music-encoding.org/ns/mei")

def clean_mei_files(path, destination_path = None,
                    remove_unreferenced = True,
                    remove_identical_duplicates = True):
    if os.path.isfile(path):
        cleaned_mei, xml_declarations = clean_mei(path, remove_unreferenced=remove_unreferenced,remove_identical_duplicates=remove_identical_duplicates)
        if destination_path:
            save_mei_file(cleaned_mei, xml_declarations, destination_path)
        else:
            save_mei_file(cleaned_mei, xml_declarations, path)
    if os.path.isdir(path):
        mei_files = [file for file in os.listdir(path) if file.endswith('.mei')]
        for mei_f in mei_files:
            cleaned_mei, xml_declarations = clean_mei(os.path.join(path, mei_f), remove_unreferenced=remove_unreferenced,remove_identical_duplicates=remove_identical_duplicates)
            if destination_path:
                save_mei_file(cleaned_mei, xml_declarations, os.path.join(destination_path, mei_f))
            else:
                save_mei_file(cleaned_mei, xml_declarations, os.path.join(path, mei_f))
    

def clean_mei(filepath,
                    remove_unreferenced = True,
                    remove_identical_duplicates = True):
    print(f"CLEANING MEI FILE: {filepath}")
    xml_tree, xml_declarations = read_mei_file(filepath)
    mei = xml_tree.getroot()
    if remove_unreferenced:
        mei = remove_unreferenced_zones(mei)
    if remove_identical_duplicates:
        mei = remove_identical_elements(mei)
    return mei, xml_declarations

def parse_zones(mei):
    """Get the zones (bounding boxes) from an MEI root element."""
    zones = {}
    for zone in mei.iter(f"{MEINS}zone"):
        zone_id = zone.get(f"{XMLNS}id")
        coordinate_names = ["ulx", "uly", "lrx", "lry"]
        coordinates = [int(zone.get(c, -1)) for c in coordinate_names]
        rotate = float(zone.get("rotate", 0.0))
        zones[f"#{zone_id}"] = {
            "coordinates": tuple(coordinates),
            "rotate": rotate,
        }
    return zones

def find_duplicate_zones(mei):
    zones = parse_zones(mei)
    dupe_zone_list = []
    for z1, z2 in combinations(zones.keys(), 2):
        if zones[z1] == zones[z2]:
            dupe_zone_list.append((z1,z2))
    return dupe_zone_list

def remove_unreferenced_zones(mei):
    """Removes any zones defined in the facsimile section of mei (ie.
    zone elements for which coordinates are defined) but that are not
    associated with any mei element in the score."""
    music = mei.find(f'{MEINS}music')
    surface = music.find(f'{MEINS}facsimile/{MEINS}surface')
    defined_zones = surface.findall(f'{MEINS}zone')
    body_str = ET.tostring(music.find(f'{MEINS}body'), encoding = 'unicode')
    for def_z in defined_zones:
        zone_id = def_z.get(f'{XMLNS}id')
        if zone_id not in body_str:
            surface.remove(def_z)
            print(f"Unreferenced zone removed: {zone_id}")
    return mei

def remove_identical_elements(mei):
    """Removes elements that are identical and associated with
    two bounding boxes with the same coordinates."""
    duplicate_zones = find_duplicate_zones(mei)
    surface = mei.find(f'{MEINS}music/{MEINS}facsimile/{MEINS}surface')
    layer = mei.find(f'./{MEINS}music/{MEINS}body/{MEINS}mdiv/{MEINS}score/{MEINS}section/{MEINS}staff/{MEINS}layer')
    for dup_zone_pair in duplicate_zones:
        parent_elems = [layer.find(f".//*[@facs='{dup}']/..") for dup in dup_zone_pair]
        elems = [layer.find(f".//*[@facs='{dup}']") for dup in dup_zone_pair]
        attribs = [elem.attrib for elem in elems]
        attribs_copy = [a.copy() for a in attribs]
        for a in attribs_copy:
            a.pop(f'{XMLNS}id')
            a.pop('facs')
        if attribs_copy[0] == attribs_copy[1]:
            parent_elems[1].remove(elems[1])
            zone_id_to_del = dup_zone_pair[1]
            zone_id_to_del = zone_id_to_del.replace('#','')
            zone_to_del = surface.find(f"*[@{XMLNS}id='{zone_id_to_del}']")
            surface.remove(zone_to_del)
            print(f"Identical zones/elements removed: {zone_id_to_del}")
    return mei

def read_mei_file(filepath):
    xml_tree = ET.parse(filepath)
    declarations = []
    with open(filepath, 'r') as in_file:
        for f_line in in_file:
            if re.fullmatch("^<\?.*\?>\n$", f_line):
                declarations.append(f_line)
            else:
                break
    xml_declarations = ''.join(declarations)
    return xml_tree, xml_declarations

def save_mei_file(xml_tree, xml_declarations, filepath):
    xml_str = ET.tostring(xml_tree, encoding = 'unicode')
    formatted_xml_str = re.sub(" \/>", "/>", xml_str)
    formatted_xml_str = ''.join([xml_declarations, formatted_xml_str])
    with open(filepath, 'w') as out_file:
        out_file.write(formatted_xml_str)

if __name__ == "__main__":
    clean_mei_files(path = args.mei_path, destination_path = args.destination_path, remove_unreferenced=args.remove_unreferenced_zones,
                                remove_identical_duplicates=args.remove_identical_duplicates)