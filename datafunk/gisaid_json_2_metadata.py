import json
import argparse
import sys
from datetime import datetime
import warnings
import re
import pycountry

from datafunk.travel_history import *
from datafunk.travel_history import cities_dict, countries_list, subdivisions_dict, others

"""
Don't edit these two lists please:
"""
_fields_gisaid = ['covv_accession_id', 'covv_virus_name', 'covv_location', 'covv_collection_date', \
                 'covv_add_host_info', 'covv_assembly_method', 'covv_gender', 'covv_host',  \
                 'covv_passage', 'covv_patient_age', 'covv_seq_technology', \
                 'covv_specimen', 'covv_subm_date']

_fields_edin = ['edin_admin_0', 'edin_admin_1', 'edin_admin_2', \
                'edin_lineage', 'edin_travel', \
                'edin_omitted', 'edin_date_stamp', 'edin_flag']


"""
You can edit this list:
"""
fields = ['edin_epi_week', 'edin_annotation']


def parse_omissions_file(file):
    """
    Parse a file of records to omit.
    Relies on there being a regex match to "EPI_ISL_\d{6}" in a line.
    Only returns the first match to the regex
    """
    # TO DO: allow regexes to e.g. 'bat', 'pangolin' in the omissions file

    IDs = []
    regex = re.compile('EPI_ISL_\d{6}')
    file_is_fasta = file.split('.')[-1][0:2].lower() == 'fa'

    with open(file, 'r') as f:
        for line in f:
            if file_is_fasta:
                if line[0] != '>':
                    continue
            elif line.startswith("#"):
                continue
            match = re.search(regex, line)
            if match:
                ID = match.group()
                IDs.append(ID)

    return(IDs)


def fix_gisaid_json_dict(gisaid_json_dict):
    """
    Remove commas from fields inside json dict
    """

    newDict = {}
    for x,y in gisaid_json_dict.items():
        newDict[x] = str(y).replace(',', '')

    return(newDict)


def get_admin_levels_from_json_dict(gisaid_json_dict, warnings = True):
    """
    get location strings from the gisaid location field
    use pycountry /
    """
    location_strings = [x.strip() for x in gisaid_json_dict['covv_location'].split("/")]

    while len(location_strings) < 4:
        location_strings.append("")

    continent = location_strings[0]
    country = location_strings[1]
    subdivision = location_strings[2]
    subsubdivision = location_strings[3]

    if any([x == country for x in ['England', 'Northern Ireland', 'Scotland', 'Wales']]):
        country = 'United Kingdom'
        subdivision = location_strings[1]
        subsubdivision = location_strings[2]

    if any([x == country for x in ['Alaska']]):
        country = 'USA'
        subdivision = location_strings[1]
        subsubdivision = location_strings[2]

    # some check here that there's a match to a real country
    # using pycountries?
    # First, these countries are known exceptions:
    if warnings:
        if all([country != x for x in ['Iran', 'South Korea', 'Russia', 'Korea', 'Democratic Republic of the Congo']]):
            try:
                pycountry.countries.lookup(country)
            except LookupError:
                warnings.warn('Check country flagged for ' + gisaid_json_dict['covv_accession_id'] + \
                              '  ("' + country + '")')

                if len(gisaid_json_dict['edin_flag']) == 0:
                    gisaid_json_dict['edin_flag'] = 'check_country'
                elif len(gisaid_json_dict['edin_flag']) > 0:
                    gisaid_json_dict['edin_flag'] = gisaid_json_dict['edin_flag'] + ':check_country'

    if country == 'United Kingdom':
        country = 'UK'

    if country == 'Korea':
        country = 'South Korea'

    if country == 'Democratic Republic of the Congo':
        country = 'DRC'

    gisaid_json_dict['edin_admin_0'] = country
    gisaid_json_dict['edin_admin_1'] = subdivision
    gisaid_json_dict['edin_admin_2'] = subsubdivision

    return(gisaid_json_dict)


# def get_field_list(dict_of_dicts):
#     """
#     Get a set of all second-level field names from a dict of dicts
#     """
#     first = True
#     for key in dict_of_dicts:
#         d = EPI_dict[key]
#         if first:
#             field_list_master = list(d.keys())
#             first = False
#             continue
#         field_list = list(d.keys())
#         for x in field_list:
#             if x not in field_list_master:
#                 field_list_master.append(x)
#
#     return(set(field_list_master))


def expand_dict(dict, fields_list_required, fields_list_optional):
    """
    check fields in a dict
    make/delete them as appropriate
    """

    for x in fields_list_required:
        if x not in dict:
            dict[x] = ''

    for x in fields_list_optional:
        if x not in dict:
            dict[x] = ''

    # poplist = []
    # for x in dict:
    #     if x not in fields_list_required + fields_list_optional:
    #         poplist.append(x)
    # for x in poplist:
    #     dict.pop(x)

    return(dict)


def get_csv_order_and_record_dict(csv_file, fields_list_required, fields_list_optional):
    """
    Read all info in a csv metadata file into memory.

    old_records is a nested dict with EPI_IDs as the
    top-level keys and a dict of key: value pairs
    as the top-level values
    """
    first = True
    old_records = {}
    record_order = []
    with open(csv_file, 'r') as f:
        for line in f:
            l = line.strip().split(',')
            if first:
                keys = l
                first = False
                continue

            if len(l) != len(keys):
                sys.exit('Badly formatted csv file: ' + csv_file.csv + ', exiting program')

            d = {x: y for x,y in zip(keys, l)}
            d = expand_dict(dict = d, fields_list_required = fields_list_required, fields_list_optional = fields_list_optional)

            ID = d['covv_accession_id']
            record_order.append(ID)
            old_records[ID] = d

    return(record_order, old_records)


def get_json_order_and_record_dict(json_file, fields_list_required, fields_list_optional):
    """
    Read all info in a GISAID json dump into memory.

    all_records is a nested dict with EPI_IDs as the
    top-level keys and a dict of key: value pairs
    as the top-level values
    """
    all_records = {}
    record_order = []
    with open(json_file, 'r') as f:
        for jsonObj in f:

            d = fix_gisaid_json_dict(json.loads(jsonObj))
            d = expand_dict(dict = d, fields_list_required = fields_list_required, fields_list_optional = fields_list_optional)

            ID = d['covv_accession_id']
            record_order.append(ID)
            all_records[ID] = d

    return(record_order, all_records)


def get_lineage_info(lineage_file):
    """

    """
    myDict= {}
    First = True
    with open(lineage_file, 'r') as f:
        for line in f:
            l = line.rstrip().split(',')
            if First:
                header = l
                First = False
            taxon = l[0]
            ID = l[1]
            lineage = l[2]

            myDict[ID] = {'taxon': taxon, 'ID': ID, 'lineage': lineage}

    return(myDict)


def check_gisaid_date(dict):
    """

    """
    date = dict['covv_collection_date']
    regex = re.compile('\d{4}-\d{2}-\d{2}')
    match = re.search(regex, date)
    if not match:
        if len(dict['edin_flag']) == 0:
            dict['edin_flag'] = 'check_date'
        elif len(dict['edin_flag']) > 0:
            dict['edin_flag'] = dict['edin_flag'] + ':check_date'

    return(dict)


def update_edin_lineage_field(dict, lineage_dict):
    """
    update omission field to True if record
    is in omissions file
    """
    ID = dict['covv_accession_id']
    if ID in lineage_dict:
        dict['edin_lineage'] = lineage_dict[ID]['lineage']
    else:
        ID2 = dict['covv_virus_name'].split('/')[2]
        if ID2 in lineage_dict:
            dict['edin_lineage'] = lineage_dict[ID2]['lineage']

    return(dict)


def update_edin_omitted_field(dict, omit_set):
    """
    update omission field to True if record
    is in omissions file
    """
    if omit_set:
        if dict['covv_accession_id'] in omit_set:
            dict['edin_omitted'] = 'True'
    return(dict)


def update_edin_date_stamp_field(dict):
    """
    date stamp the new records to write
    """
    mydate = str(datetime.date(datetime.now()))
    dict['edin_date_stamp'] = mydate
    return(dict)


def get_one_line(dict, fields_list, sep = ','):
    """
    return a string of dict.values() formatted
    for writing in the order in fields_list

    l is a 'sep'-separated string formatted for printing
    """
    l = sep.join([dict[x] for x in fields_list]) + '\n'
    return(l)


def write_output(output, \
                  new_records_list, \
                  new_records_dict, \
                  old_records_list, \
                  old_records_dict, \
                  fields_list):

    """
    write a csv-format outfile to file
    """
    if output == 'stdout':
        out = sys.stdout
    else:
        out = open(output, 'w')

    out.write(','.join(fields_list) + '\n')

    for record in old_records_list:
        do = old_records_dict[record]
        lo = get_one_line(dict=do, fields_list=fields_list)
        out.write(lo)

    for record in new_records_list:
        dn = new_records_dict[record]
        ln = get_one_line(dict=dn, fields_list=fields_list)
        out.write(ln)

    if output != 'stdout':
        out.close()
    pass


def gisaid_json_2_metadata(json, output, args_csv, args_omit_file_list, args_lineages):

    # logfile = open(output + '.log', 'w')
    if args_omit_file_list:
        temp = []
        for file in args_omit_file_list:
            temp.extend(parse_omissions_file(file))

        omitted_IDs = set(temp)
    else:
        omitted_IDs = False

    if args_lineages:
        lineages = get_lineage_info(args_lineages)

    if args_csv != 'False':
        # Check that all required fields were in the csv file
        csv_header = next(open(args_csv, 'r')).strip().split(',')
        if not all([x in csv_header for x in _fields_gisaid + _fields_edin]):
            sys.exit('There were missing mandatory fields in ' + args_csv)

        # add optional fields from the old csv file to the output
        for x in csv_header:
            if x not in _fields_gisaid + _fields_edin:
                if x not in fields:
                    fields.append(x)


        old_records = get_csv_order_and_record_dict(args_csv, \
                                                    fields_list_required = _fields_gisaid + _fields_edin, \
                                                    fields_list_optional = fields)

        old_records_list = old_records[0]
        old_records_dict = old_records[1]

    else:
        old_records_list = []
        old_records_dict = {}


    all_records = get_json_order_and_record_dict(json, \
                                                fields_list_required = _fields_gisaid + _fields_edin, \
                                                fields_list_optional = fields)

    all_records_list = all_records[0]
    all_records_dict = all_records[1]

    new_records_list = [x for x in all_records_list if x not in set(old_records_list)]
    new_records_dict = {x: all_records_dict[x] for x in all_records_list if x not in set(old_records_list)}

    # update omitted field
    new_records_dict = {x: update_edin_omitted_field(all_records_dict[x], omitted_IDs) for x in new_records_dict.keys()}

    # update date stamp field
    new_records_dict = {x: update_edin_date_stamp_field(all_records_dict[x]) for x in new_records_dict.keys()}

    # update admin level
    new_records_dict = {x: get_admin_levels_from_json_dict(all_records_dict[x]) for x in new_records_dict.keys()}

    # check gisaid collection date
    new_records_dict = {x: check_gisaid_date(all_records_dict[x]) for x in new_records_dict.keys()}

    # get travel history
    new_records_dict = {x: get_travel_history(all_records_dict[x]) for x in new_records_dict.keys()}

    # update lineages
    if args_lineages:
        new_records_dict = {x: update_edin_lineage_field(all_records_dict[x], lineages) for x in new_records_dict.keys()}

    write_output(output = output,
                  new_records_list = new_records_list,
                  new_records_dict = new_records_dict,
                  old_records_list = old_records_list,
                  old_records_dict = old_records_dict,
                  fields_list = _fields_edin + fields + _fields_gisaid)

    # logfile.close()
    pass
