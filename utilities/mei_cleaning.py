import xml.etree.ElementTree as ET
from itertools import combinations
import argparse
import re
import os

parser = argparse.ArgumentParser(description="Utilities for cleaning mei files")
parser.add_argument('mei_path', type = str, nargs = '?', help = "Path to mei file for cleaning. If a directory, cleans all mei files in the directory.",action = 'store')
parser.add_argument('--remove_unreferenced_bounding_boxes', action = 'store_true', help = "If flagged, removes zones/bounding boxes that are defined but not referenced anywhere in the body.")
parser.add_argument('--remove_identical_duplicates', action = 'store_true', help = "If flagged, removes duplicate zones/bounding boxes and duplicate objects that reference those bounding boxes.")
parser.add_argument('--raise_nonidentical_duplicates', action = 'store_true', help = "Find and record instances where duplicate zones/bounding boxes are referenced by different, non-identical objects.")
parser.add_argument('--destination_path', action = 'store', default = None, type = str, nargs = '?', help = "If provided, the cleaned file is save here. If omitted, file is save to mei_path location. If mei_path is a directory, this should also be a directory.")
parser.add_argument('--report_file', action = 'store', default = None, type =str, nargs = '?', help = "File in which to report any raised non-identical duplicates. If not given, results are printed.")
args = parser.parse_args()

MEINS = "{http://www.music-encoding.org/ns/mei}"
XMLNS = "{http://www.w3.org/XML/1998/namespace}"

ET.register_namespace("","http://www.music-encoding.org/ns/mei")

class MEIFileCleaner:
    
    def __init__(self, remove_unreferenced_bounding_boxes,
                remove_identical_duplicates,
                raise_nonidentical_duplicates,
                report_file = None):
        """See argument parser for a description of these arguments."""
        self.remove_unreferenced_bounding_boxes = remove_unreferenced_bounding_boxes
        self.remove_identical_duplicates = remove_identical_duplicates
        self.raise_nonidentical_duplicates = raise_nonidentical_duplicates
        self.report_file = report_file

    def parse_zones(self, mei):
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

    def find_duplicate_zones(self, mei):
        zones = self.parse_zones(mei)
        dupe_zone_list = []
        for z1, z2 in combinations(zones.keys(), 2):
            if zones[z1] == zones[z2]:
                dupe_zone_list.append((z1,z2))
        return dupe_zone_list

    def remove_unreferenced_zones(self, mei):
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
        return None

    def get_elements_with_duplicate_references(self, mei):
        """Finds elements that reference duplicate bounding boxes.
        Returns a list of lists, one for each set of duplicate bouding boxes,
        each of which contains two dictionaries. These dictionaries have:
         - "element": the ElementTree object of one of the elements
         - "bb_id": the id of the zone/bounding box of that element
         - "parent": the ElementTree object of the parent of that element (necessary to remove an element)"""
        duplicate_zones = self.find_duplicate_zones(mei)
        layer = mei.find(f'./{MEINS}music/{MEINS}body/{MEINS}mdiv/{MEINS}score/{MEINS}section/{MEINS}staff/{MEINS}layer')
        duplicate_references_list = []
        for dup_zone_pair in duplicate_zones:
            elems = [layer.find(f".//*[@facs='{dup}']") for dup in dup_zone_pair]
            parent_elems = [layer.find(f".//*[@facs='{dup}']/..") for dup in dup_zone_pair]
            dup_ref_list = [{'element': elems[0], 'bb_id': dup_zone_pair[0],'parent': parent_elems[0]},
                            {'element': elems[1], 'bb_id': dup_zone_pair[1], 'parent': parent_elems[1]}]
            duplicate_references_list.append(dup_ref_list)
        return duplicate_references_list

    def check_element_identity(self, elem1, elem2):
        elem_attribs = [elem1.attrib.copy(),
                        elem2.attrib.copy()]
        for a in elem_attribs:
            a.pop(f'{XMLNS}id')
            a.pop('facs')
        if (elem_attribs[0] == elem_attribs[1]) and elem1.text == elem2.text:
            return True
        else:
            return False
        
    def delete_element_and_referenced_zone(self, surface, element, parent, zone_id):
        elem_id = element.attrib[f'{XMLNS}id']
        parent.remove(element)
        zone_to_del = surface.find(f"*[@{XMLNS}id='{zone_id.replace('#','')}']")
        surface.remove(zone_to_del)
        print(f"Identical zone and referencing element removed: {zone_id} & {elem_id}")
        return None

    def register_nonidentical_duplicates(self, dup_dict_1, dup_dict_2):
        str_to_print = f"""
                        ###### NON-IDENTICAL DUPLICATE FOUND ###### \n
                        {dup_dict_1['bb_id']} > \n
                        \t {dup_dict_1['element'].attrib} {dup_dict_1['element'].text} \n
                        {dup_dict_2['bb_id']} > \n
                        \t {dup_dict_2['element'].attrib} {dup_dict_2['element'].text} \n
                        """
        if self.report_file:
            with open(self.report_file, 'wa') as rf:
                rf.write(str_to_print)
        else:
            print(str_to_print)
        return None

    def handle_referenced_duplicates(self, mei):
        dup_ref_list = self.get_elements_with_duplicate_references(mei)
        for dup_ref in dup_ref_list:
            identical = self.check_element_identity(dup_ref[0]['element'],
                                                dup_ref[1]['element'])
            if identical:
                if self.remove_identical_duplicates:
                    surface = mei.find(f'{MEINS}music/{MEINS}facsimile/{MEINS}surface')
                    self.delete_element_and_referenced_zone(surface = surface,
                                                        element = dup_ref[1]['element'],
                                                        parent = dup_ref[1]['parent'],
                                                        zone_id = dup_ref[1]['bb_id'])
            else:
                if self.raise_nonidentical_duplicates:
                    self.register_nonidentical_duplicates(dup_ref[0], dup_ref[1])
        if self.raise_nonidentical_duplicates:
            if self.report_file:
                print(f'Non-identical duplicates checked and raised in {self.report_file}')
        return None

    def clean_mei(self, filepath):
        print(f"CLEANING MEI FILE: {filepath}")
        if self.report_file:
            with open(self.report_file, 'wa') as rf:
                rf.write(f"CLEANING MEI FILE: {filepath}")
        xml_tree, xml_declarations = read_mei_file(filepath)
        mei = xml_tree.getroot()
        if self.remove_unreferenced_bounding_boxes:
            self.remove_unreferenced_zones(mei)
        self.handle_referenced_duplicates(mei)
        return mei, xml_declarations

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

def clean_mei_files(path, destination_path = None,
                    remove_unreferenced_bounding_boxes = True,
                    remove_identical_duplicates = True,
                    raise_nonidentical_duplicates = True,
                    report_file = None):
    mei_cleaner = MEIFileCleaner(remove_unreferenced_bounding_boxes=remove_unreferenced_bounding_boxes,
                                    remove_identical_duplicates=remove_identical_duplicates,
                                    raise_nonidentical_duplicates=raise_nonidentical_duplicates,
                                    report_file=report_file)
    if os.path.isfile(path):
        cleaned_mei, xml_declarations = mei_cleaner.clean_mei(path)
        if destination_path:
            save_mei_file(cleaned_mei, xml_declarations, destination_path)
        else:
            save_mei_file(cleaned_mei, xml_declarations, path)
    if os.path.isdir(path):
        mei_files = [file for file in os.listdir(path) if file.endswith('.mei')]
        for mei_f in mei_files:
            cleaned_mei, xml_declarations = mei_cleaner.clean_mei(os.path.join(path, mei_f))
            if destination_path:
                save_mei_file(cleaned_mei, xml_declarations, os.path.join(destination_path, mei_f))
            else:
                save_mei_file(cleaned_mei, xml_declarations, os.path.join(path, mei_f))

if __name__ == "__main__":
    clean_mei_files(path = args.mei_path, 
                        destination_path = args.destination_path, 
                        remove_unreferenced_bounding_boxes = args.remove_unreferenced_bounding_boxes,
                        remove_identical_duplicates = args.remove_identical_duplicates,
                        raise_nonidentical_duplicates = args.raise_nonidentical_duplicates,
                        report_file = args.report_file
                        )