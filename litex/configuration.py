#!/usr/bin/env python3
"""
Copyright (c) 2019 Antmicro

LiteX configuration parser.

This module provides class for parsing LiteX configuration
exported in 'csr.csv' file.
"""

import csv
import itertools


class Configuration(object):

    def __init__(self, conf_file):
        self.peripherals = {}
        self.constants = {}
        self.registers = {}
        self.mem_regions = {}

        with open(conf_file) as csvfile:
            self._parse_csv(list(csv.reader(Configuration._remove_comments(csvfile))))
            self._normalize_addresses()

    @staticmethod
    def _remove_comments(data):
        for line in data:
            if not line.lstrip().startswith('#'):
                yield line

    def _parse_csv(self, data):
        """ Parses LiteX CSV file.

        Args:
            data (list): list of CSV file lines
        """

        # scan for CSRs first, so it's easier to resolve CSR-related constants
        # in the second pass
        for _type, _name, _address, _, __ in data:
            if _type == 'csr_base':
                self.peripherals[_name] = {'name': _name,
                                           'address': int(_address, 0),
                                           'constants': {}}

        for _type, _name, _val, _val2, _val3 in data:
            if _type == 'csr_base':
                # CSRs have already been parsed
                pass
            elif _type == 'csr_register':
                # csr_register,info_dna_id,0xe0006800,8,ro
                self.registers[_name] = {'name': _name,
                                         'address': int(_val, 0),
                                         'size': int(_val2, 0),
                                         'r': _val3}
            elif _type == 'constant':
                found = False
                for _csr_name in self.peripherals:
                    if _name.startswith(_csr_name):
                        local_name = _name[len(_csr_name) + 1:]
                        self.peripherals[_csr_name]['constants'][local_name] = _val
                        found = True
                        break
                if not found:
                    # if it's not a CSR-related constant, it must be a global one
                    self.constants[_name] = {'name': _name, 'value': _val}
            elif _type == 'memory_region':
                self.mem_regions[_name] = {'name': _name,
                                           'address': int(_val, 0),
                                           'size': int(_val2, 0),
                                           'type': _val3}
            else:
                print('Skipping unexpected CSV entry: {} {}'.format(_type, _name))

    def _normalize_addresses(self):
        shadow_base = (int(self.constants['shadow_base']['value'], 0)
                       if 'shadow_base' in self.constants
                       else None)

        for r in itertools.chain(self.mem_regions.values(), self.registers.values(), self.peripherals.values()):
            if shadow_base is None:
                r['shadowed_address'] = None
            else:
                r['shadowed_address'] = r['address'] | shadow_base
                if r['shadowed_address'] == r['address']:
                    r['address'] &= ~shadow_base
