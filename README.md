# litex-renode
Tools for using [Renode](http://renode.io) from [Antmicro](http://antmicro.com) with [LiteX](http://github.com/enjoy-digital/litex) for simulation.

This repo hosts the parser of LiteX 'csr.csv' file generating scripts for Renode allowing to simulate the given configuration of the LiteX SoC.

### Renode

Renode was created by Antmicro as a virtual development tool for multinode embedded networks (both wired and wireless) and is intended to enable a scalable workflow for creating effective, tested and secure IoT systems.

With Renode, developing, testing, debugging and simulating unmodified software for IoT devices is fast, cost-effective and reliable.

For details, see [the official webpage](http://renode.io).

### LiteX

LiteX is a MiSoC-based SoC builder using Migen as Python DSL that can be used
to create SoCs and full FPGA designs.

LiteX provides specific building/debugging tools for high level of abstraction
and compatibily with the LiteX core ecosystem.

Think of Migen as a toolbox to create FPGA designs in Python and LiteX as a
toolbox to create/develop/debug FPGA SoCs in Python.

For details, see [the github repository](https://github.com/enjoy-digital/litex).

## Usage

First, build your LiteX platform with `--csr-csv csr.csv` switch, e.g.:

    python3 litex/boards/targets/arty.py --cpu-type vexriscv --with-ethernet --csr-csv csr.csv

Now, use the generated configuration file as an input for `generate-renode-scripts.py`:

    ./generate-renode-scripts.py csr.csv \
        --resc litex.resc \
        --repl litex.repl
        --bios-binary soc_ethernetsoc_arty/software/bios/bios.bin

This will generate two files:

* `litex.repl` - platform definition file, containing information about all the peripherals and their configuration,
* `litex.resc` - Renode script file, allowing to easily run the simulation of the generated platform.

Finally, you can run the simulation by executing the command::

    renode litex.resc

### Additional options

The script provides additional options:

#### `--firmware-binary`

Allows to set a path to the file that should be loaded into flash. Allows to use the `flashboot` command in LiteX bios.

#### `--configure-network`

Generates virtual network and connects it to the host's interface. Allows to use the `netboot` command in LiteX bios.

## Supported LiteX components

The script can generate the following elements of the LiteX SoC:

* `uart`,
* `timer0`,
* `ethmac`,
* `cas`,
* `cpu`,
* `spiflash`.

## Examples

See [litex-buildenv](https://github.com/timvideos/litex-buildenv/blob/master/scripts/build-renode.sh) for an example of use.

