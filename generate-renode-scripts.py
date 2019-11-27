#!/usr/bin/env python3
"""
Copyright (c) 2019 Antmicro

Renode platform definition (repl) and script (resc) generator for LiteX SoC.

This script parses LiteX 'csr.csv' file and generates scripts for Renode
necessary to emulate the given configuration of the LiteX SoC.
"""

import sys
import zlib
import argparse

from litex.configuration import Configuration

# those memory regions are handled in a special way
# and should not be generated automatically
non_generated_mem_regions = ['ethmac', 'csr']

configuration = None


def generate_sysbus_registration(descriptor,
                                 skip_braces=False, region=None, skip_size=False):
    """ Generates system bus registration information
    consisting of a base address and an optional shadow
    address.

    Args:
        descriptor (dict): dictionary containing 'address',
                          'shadowed_address' (might be None) and
                          optionally 'size' fields
        skip_braces (bool): determines if the registration info should
                            be put in braces
        region (str or None): name of the region, if None the default
                              one is assumed
        skip_size (bool): if set to true do not set size

    Returns:
        string: registration information
    """

    def generate_registration_entry(address, size=None, name=None):
        if name:
            if not size:
                raise Exception('Size must be provided when registering non-default region')
            return 'sysbus new Bus.BusMultiRegistration {{ address: {}; size: {}; region: "{}" }}'.format(hex(address), hex(size), name)
        if size:
            return "sysbus <{}, +{}>".format(hex(address), hex(size))
        return "sysbus {}".format(hex(address))

    address = descriptor['address']
    shadowed_address = descriptor['shadowed_address']
    size = descriptor['size'] if 'size' in descriptor and not skip_size else None

    if shadowed_address:
        result = "{}; {}".format(
            generate_registration_entry(address, size, region),
            generate_registration_entry(shadowed_address, size, region))
    else:
        result = generate_registration_entry(address, size, region)

    if not skip_braces:
        result = "{{ {} }}".format(result)

    return result


def generate_ethmac(peripheral, **kwargs):
    """ Generates definition of 'ethmac' peripheral.

    Args:
        peripheral (dict): peripheral description
        kwargs (dict): additional parameters, including 'buffer'

    Returns:
        string: repl definition of the peripheral
    """
    buf = kwargs['buffer']()
    phy = kwargs['phy']()

    # FIXME: Get litex to generate CSR region size into output information
    # currently only a base address is present
    phy['size'] = 0x800

    result = """
ethmac: Network.LiteX_Ethernet @ {{
    {};
    {};
    {}
}}
""".format(generate_sysbus_registration(peripheral,
                                        skip_braces=True),
           generate_sysbus_registration(buf,
                                        skip_braces=True, region='buffer'),
           generate_sysbus_registration(phy,
                                        skip_braces=True, region='phy'))

    if 'interrupt' in peripheral['constants']:
        result += '    -> cpu@{}\n'.format(
            peripheral['constants']['interrupt'])

    result += """

ethphy: Network.EthernetPhysicalLayer @ ethmac 0
    VendorSpecific1: 0x4400 // MDIO status: 100Mbps + link up
"""

    return result


def generate_memory_region(region_descriptor):
    """ Generates definition of memory region.

    Args:
        region_descriptor (dict): memory region description

    Returns:
        string: repl definition of the memory region
    """

    return """
{}: Memory.MappedMemory @ {}
    size: {}
""".format(region_descriptor['name'],
           generate_sysbus_registration(region_descriptor, skip_size=True),
           hex(region_descriptor['size']))


def generate_silencer(peripheral, **kwargs):
    """ Silences access to a memory region.

    Args:
        peripheral (dict): peripheral description
        kwargs (dict): additional parameters, not used

    Returns:
        string: repl definition of the silencer
    """
    return """
sysbus:
    init add:
        SilenceRange <{} 0x200> # {}
""".format(peripheral['address'], peripheral['name'])


def generate_cpu(time_provider):
    """ Generates definition of a CPU.

    Returns:
        string: repl definition of the CPU
    """
    kind = configuration.constants['config_cpu_type']['value'].upper()
    if 'config_cpu_variant' in configuration.constants:
        variant = configuration.constants['config_cpu_variant']['value'].upper()
    else:
        variant = None

    if kind == 'VEXRISCV':
        result = """
cpu: CPU.VexRiscv @ sysbus
"""
        if variant == 'LINUX':
            result += """
    cpuType: "rv32ima"
    privilegeArchitecture: PrivilegeArchitecture.Priv1_10
"""
        else:
            result += """
    cpuType: "rv32im"
"""
        if time_provider:
            result += """
    timeProvider: {}
""".format(time_provider)
        return result
    elif kind == 'PICORV32':
        return """
cpu: CPU.PicoRV32 @ sysbus
    cpuType: "rv32imc"
"""
    else:
        raise Exception('Unsupported cpu type: {}'.format(kind))


def generate_peripheral(peripheral, **kwargs):
    """ Generates definition of a peripheral.

    Args:
        peripheral (dict): peripheral description
        kwargs (dict): additional parameterss, including
                       'model' and 'properties'

    Returns:
        string: repl definition of the peripheral
    """

    result = '\n{}: {} @ {}\n'.format(
        kwargs['name'] if 'name' in kwargs else peripheral['name'],
        kwargs['model'],
        generate_sysbus_registration(peripheral))

    for constant, val in peripheral['constants'].items():
        if constant == 'interrupt':
            result += '    -> cpu@{}\n'.format(val)
        elif 'ignored_constants' not in kwargs or constant not in kwargs['ignored_constants']:
            result += '    {}: {}\n'.format(constant, val)

    if 'properties' in kwargs:
        for prop, val in kwargs['properties'].items():
            result += '    {}: {}\n'.format(prop, val())

    if 'interrupts' in kwargs:
        for prop, val in kwargs['interrupts'].items():
            result += '    {} -> {}\n'.format(prop, val())

    return result


def generate_spiflash(peripheral, **kwargs):
    """ Generates definition of an SPI controller with attached flash memory.

    Args:
        peripheral (dict): peripheral description
        kwargs (dict): additional parameterss, including
                       'model' and 'properties'

    Returns:
        string: repl definition of the peripheral
    """

    result = """
spi: SPI.LiteX_SPI_Flash @ {{
    {}
}}

mt25q: SPI.Micron_MT25Q @ spi
    underlyingMemory: spiflash
""".format(
        generate_sysbus_registration(peripheral, skip_braces=True))
    return result


def generate_cas(peripheral, **kwargs):
    result = generate_peripheral(peripheral, model='GPIOPort.LiteX_ControlAndStatus', ignored_constants=['leds_count', 'switches_count', 'buttons_count'])

    leds_count = int(peripheral['constants']['leds_count'])
    switches_count = int(peripheral['constants']['switches_count'])
    buttons_count = int(peripheral['constants']['buttons_count'])

    for i in range(leds_count):
        result += """
    {} -> led{}@0
""".format(i, i)

    for i in range(leds_count):
        result += """
led{}: Miscellaneous.LED @ cas {}
""".format(i, i)

    for i in range(switches_count):
        result += """
switch{}: Miscellaneous.Button @ cas {}
    -> cas@{}
""".format(i, i + 32, i + 32)

    for i in range(buttons_count):
        result += """
button{}: Miscellaneous.Button @ cas {}
    -> cas@{}
""".format(i, i + 64, i + 64)

    return result


def get_clock_frequency():
    """
    Returns:
        int: system clock frequency
    """
    # in different LiteX versions this property
    # has different names
    return configuration.constants['config_clock_frequency' if 'config_clock_frequency' in configuration.constants else 'system_clock_frequency']['value']


def generate_repl():
    """ Generates platform definition.

    Returns:
        string: platform defition containing all supported
                peripherals and memory regions
    """
    result = ""

    # defines mapping of LiteX peripherals to Renode models
    name_to_handler = {
        'uart': {
            'handler': generate_peripheral,
            'model': 'UART.LiteX_UART'
        },
        'timer0': {
            'handler': generate_peripheral,
            'model': 'Timers.LiteX_Timer',
            'properties': {
                'frequency':
                    lambda: get_clock_frequency()
            }
        },
        'ethmac': {
            'handler': generate_ethmac,
            'buffer': lambda: configuration.mem_regions['ethmac'],
            'phy': lambda: configuration.peripherals['ethphy']
        },
        'cas': {
            'handler': generate_cas,
        },
        'cpu': {
            'name': 'cpu_timer',
            'handler': generate_peripheral,
            'model': 'Timers.LiteX_CPUTimer',
            'properties': {
                'frequency':
                    lambda: get_clock_frequency()
            },
            'interrupts': {
                # IRQ #100 in Renode's VexRiscv model is mapped to Machine Timer Interrupt
                'IRQ': lambda: 'cpu@100'
            }
        },
        'ddrphy': {
            'handler': generate_silencer
        },
        'sdram': {
            'handler': generate_silencer
        },
        'spiflash': {
            'handler': generate_spiflash
        }
    }

    # RISC-V CPU in Renode requires memory region size
    # to be a multiple of 4KB - this is a known limitation
    # (not a bug) and there are no plans to handle smaller
    # memory regions for now
    for mem_region in filter_memory_regions(list(configuration.mem_regions.values()), alignment=0x1000):
        result += generate_memory_region(mem_region)

    result += generate_cpu('cpu_timer' if 'cpu' in configuration.peripherals else None)

    for name, peripheral in configuration.peripherals.items():
        if name not in name_to_handler:
            print('Skipping unsupported peripheral `{}` at {}'
                  .format(name, hex(peripheral['address'])))
            continue

        h = name_to_handler[name]
        result += h['handler'](peripheral, **h)

    return result


def filter_memory_regions(raw_regions, alignment=None):
    """ Filters memory regions skipping those of linker type
        and those from `non_generated_mem_regions` list
        and verifying if they have proper size and do not overlap.

        Args:
            raw_regions (list): list of memory regions parsed from
                                the configuration file
            alignment (int or None): memory size boundary

        Returns:
            list: reduced, sorted list of memory regions to be generated
                  in a repl file
    """
    previous_region = None

    raw_regions.sort(key=lambda x: x['address'])
    for r in raw_regions:
        if 'linker' in r['type']:
            print('Skipping linker region: {}'.format(r['name']))
            continue

        if r['name'] in non_generated_mem_regions:
            print('Skipping pre-defined memory region: {}'.format(r['name']))
            continue

        if alignment is not None and r['size'] % alignment != 0:
            print('Error: `{}` memory region size ({}) is not aligned to {}'.format(r['name'], hex(r['size']), hex(alignment)))
            sys.exit(1)

        if previous_region is not None and (previous_region['address'] + previous_region['size']) > (r['address'] + r['size']):
            print("Error: detected overlaping memory regions: `{}` and `{}`".format(r['name'], previous_region['name']))
            sys.exit(1)

        previous_region = r
        yield r


def generate_resc(repl_file, host_tap_interface=None, bios_binary=None, firmware_binary=None):
    """ Generates platform definition.

    Args:
        repl_file (string): path to Renode platform definition file
        host_tap_interface (string): name of the tap interface on host machine
                                     or None if no network should be configured
        bios_binary (string): path to the binary file of LiteX BIOS or None
                              if it should not be loaded into ROM
        firmware_binary (string): path to the firmware binary file or None
                                  if it should not be loaded into flash

    Returns:
        string: platform defition containing all supported peripherals
                and memory regions
    """
    cpu_type = configuration.constants['config_cpu_type']['value']

    result = """
using sysbus
mach create "litex-{}"
machine LoadPlatformDescription @{}
machine StartGdbServer 10001
showAnalyzer sysbus.uart
showAnalyzer sysbus.uart Antmicro.Renode.Analyzers.LoggingUartAnalyzer
""".format(cpu_type, repl_file)

    rom_base = configuration.mem_regions['rom']['address']
    if rom_base is not None and bios_binary:
        # load LiteX BIOS to ROM
        result += """
sysbus LoadBinary @{} {}
cpu PC {}
""".format(bios_binary, rom_base, rom_base)

    if host_tap_interface:
        # configure network to allow netboot
        result += """
emulation CreateSwitch "switch"
emulation CreateTap "{}" "tap"
connector Connect ethmac switch
connector Connect host.tap switch
""".format(host_tap_interface)
    elif firmware_binary and 'flash_boot_address' in configuration.constants:
        # load firmware binary to spiflash to boot from there

        firmware_data = open(firmware_binary, 'rb').read()
        crc32 = zlib.crc32(firmware_data)

        flash_boot_address = int(configuration.constants['flash_boot_address']['value'], 0)

        result += 'sysbus WriteDoubleWord {} {}\n'.format(hex(flash_boot_address), hex(len(firmware_data)))
        result += 'sysbus WriteDoubleWord {} {}\n'.format(hex(flash_boot_address + 4), hex(crc32))
        result += 'sysbus LoadBinary @{} {}\n'.format(firmware_binary, hex(flash_boot_address + 8))

    result += 'start'
    return result


def print_or_save(filepath, lines):
    """ Prints given string on standard output or to the file.

    Args:
        filepath (string): path to the file lines should be written to
                           or '-' to write to a standard output
        lines (string): content to be printed/written
    """
    if filepath == '-':
        print(lines)
    else:
        with open(filepath, 'w') as f:
            f.write(lines)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('conf_file',
                        help='CSV configuration generated by LiteX')
    parser.add_argument('--resc', action='store',
                        help='Output script file')
    parser.add_argument('--repl', action='store',
                        help='Output platform definition file')
    parser.add_argument('--configure-network', action='store',
                        help='Generate virtual network and connect it to host')
    parser.add_argument('--bios-binary', action='store',
                        help='Path to the BIOS binary')
    parser.add_argument('--firmware-binary', action='store',
                        help='Path to the binary to load into boot flash')
    args = parser.parse_args()

    return args


def main():
    global configuration
    args = parse_args()

    configuration = Configuration(args.conf_file)

    if args.repl:
        print_or_save(args.repl, generate_repl())

    if args.resc:
        if not args.repl:
            print("REPL is needed when generating RESC file")
            sys.exit(1)
        else:
            print_or_save(args.resc, generate_resc(args.repl,
                                                   args.configure_network,
                                                   args.bios_binary,
                                                   args.firmware_binary))


if __name__ == '__main__':
    main()
