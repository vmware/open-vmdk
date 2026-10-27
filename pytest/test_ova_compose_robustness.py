# Copyright (c) 2026 Broadcom.  All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the “License”); you may not
# use this file except in compliance with the License.  You may obtain a copy of
# the License at:
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an “AS IS” BASIS, without warranties or
# conditions of any kind, EITHER EXPRESS OR IMPLIED.  See the License for the
# specific language governing permissions and limitations under the License.

# Tests for ova-compose with unusual but valid configs, and for its error handling.

import os
import pytest
import shutil
import subprocess
import xmltodict


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OVA_COMPOSE = os.path.join(THIS_DIR, "..", "ova-compose", "ova-compose.py")
VMDK_CONVERT = os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")
WORK_DIR = os.path.join(os.getcwd(), "pytest-ova-compose-robustness")

# a minimal config, extended by the tests
BASE_YAML = """
system:
    name: robustness
    type: vmx-20
    os_vmw: other4xLinux64Guest

networks:
    vm_network:
        name: "VM Network"
        description: "The VM Network"

hardware:
    cpus: 1
    memory: 512
    sata1:
        type: sata_controller
    rootdisk:
        type: hard_disk
        parent: sata1
        disk_image: dummy.vmdk
    ethernet1:
        type: ethernet
        subtype: VmxNet3
        network: vm_network
"""


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)

    process = subprocess.run(["dd", "if=/dev/zero", "of=dummy.img", "bs=1024", "count=1024"], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run([VMDK_CONVERT, "dummy.img", "dummy.vmdk"], cwd=WORK_DIR)
    assert process.returncode == 0

    yield
    shutil.rmtree(WORK_DIR)


def compose(yaml_text, output="out.ovf", args=[]):
    """Run ova-compose with the given config. Returns the process, and the parsed OVF if one was written."""
    yaml_path = os.path.join(WORK_DIR, "in.yaml")
    with open(yaml_path, "w") as f:
        f.write(yaml_text)

    out_path = os.path.join(WORK_DIR, output)
    if os.path.isdir(out_path):
        shutil.rmtree(out_path)
    elif os.path.exists(out_path):
        os.remove(out_path)

    process = subprocess.run([OVA_COMPOSE, "-i", yaml_path, "-o", output, "--vmdk-convert", VMDK_CONVERT] + args,
                             cwd=WORK_DIR, capture_output=True, text=True)

    ovf = None
    if process.returncode == 0 and output.endswith(".ovf"):
        with open(out_path) as f:
            ovf = xmltodict.parse(f.read())
    return process, ovf


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def vmw_configs(ovf):
    hw = ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']
    return {c['@vmw:key']: c['@vmw:value'] for c in as_list(hw.get('vmw:Config'))}


def with_system(**kwargs):
    """BASE_YAML with additional keys in the system section"""
    lines = "".join(f"    {k}: {v}\n" for k, v in kwargs.items())
    return BASE_YAML.replace("    os_vmw: other4xLinux64Guest\n", "    os_vmw: other4xLinux64Guest\n" + lines, 1)


HW_CONFIG_NO_SECURE_BOOT = """
    config:
        bootOptions.efiSecureBootEnabled: false
"""


@pytest.mark.parametrize("system,hw_config,firmware,secure_boot", [
    # defaults
    ({}, "", "efi", "true"),
    ({"secure_boot": "true"}, "", "efi", "true"),
    ({"secure_boot": "false"}, "", "efi", "false"),
    # secure boot is not possible with bios, do not use the default
    ({"firmware": "bios"}, "", "bios", "false"),
    ({"firmware": "bios", "secure_boot": "false"}, "", "bios", "false"),
    # an explicit hardware config must not be overwritten by the default
    ({}, HW_CONFIG_NO_SECURE_BOOT, "efi", "false"),
    # but system.secure_boot overrides it, like system.firmware does
    ({"secure_boot": "true"}, HW_CONFIG_NO_SECURE_BOOT, "efi", "true"),
    # without defaults, secure boot is only set when given
    ({"no_default_configs": "true"}, "", None, None),
    ({"no_default_configs": "true", "secure_boot": "true"}, "", None, "true"),
])
def test_secure_boot(system, hw_config, firmware, secure_boot):
    process, ovf = compose(with_system(**system) + hw_config)
    assert process.returncode == 0, process.stderr
    configs = vmw_configs(ovf)
    assert configs.get("firmware") == firmware
    assert configs.get("bootOptions.efiSecureBootEnabled") == secure_boot


@pytest.mark.parametrize("system", [
    {"firmware": "bios", "secure_boot": "true"},
    {"secure_boot": "yes please"},
])
def test_secure_boot_invalid(system):
    process, _ = compose(with_system(**system))
    assert process.returncode != 0
    assert "secure_boot" in process.stderr


def disks(ovf):
    return {d['@ovf:diskId']: d for d in as_list(ovf['Envelope']['DiskSection'].get('Disk'))}


def empty_disk_yaml(units=None):
    units_line = f"        units: {units}\n" if units is not None else ""
    return BASE_YAML + f"""
    datadisk:
        type: hard_disk
        parent: sata1
        disk_capacity: 10
        disk_id: datadisk
{units_line}"""


@pytest.mark.parametrize("units,expected", [
    (None, "byte * 2^20"),
    ("GB", "byte * 2^30"),
    ("KB", "byte * 2^10"),
    ('"byte * 2^40"', "byte * 2^40"),
])
def test_empty_disk_units(units, expected):
    process, ovf = compose(empty_disk_yaml(units))
    assert process.returncode == 0, process.stderr
    disk = disks(ovf)['datadisk']
    assert disk['@ovf:capacity'] == "10"
    assert disk['@ovf:capacityAllocationUnits'] == expected


def test_empty_disk_invalid_units():
    process, _ = compose(empty_disk_yaml("furlongs"))
    assert process.returncode != 0
    assert "invalid units 'furlongs'" in process.stderr
