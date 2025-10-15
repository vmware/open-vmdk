# Copyright (c) 2023 VMware, Inc.  All Rights Reserved.
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

import os
import pytest
import shutil
import subprocess
import yaml
import xmltodict


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OVA_COMPOSE = os.path.join(THIS_DIR, "..", "ova-compose", "ova-compose.py")

VMDK_CONVERT=os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")

CONFIG_DIR=os.path.join(THIS_DIR, "configs")

WORK_DIR=os.path.join(os.getcwd(), "pytest-sectorsize")


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)

    process = subprocess.run(["dd", "if=/dev/zero", "of=dummy.img", "bs=1024", "count=1024"], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run([VMDK_CONVERT, "dummy.img", "dummy.vmdk"], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run([VMDK_CONVERT, "--sector-size", "512", "dummy.img", "dummy-512.vmdk"], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run([VMDK_CONVERT, "--sector-size", "4096", "dummy.img", "dummy-4k.vmdk"], cwd=WORK_DIR)
    assert process.returncode == 0

    yield
    shutil.rmtree(WORK_DIR)


def yaml_param(loader, node):
    params = loader.app_params
    default = None
    key = node.value

    assert type(key) is str, f"param name must be a string"

    if '=' in key:
        key, default = [t.strip() for t in key.split('=', maxsplit=1)]
        default = yaml.safe_load(default)
    value = params.get(key, default)

    assert value is not None, f"no param set for '{key}', and there is no default"

    return value


def test_config():
    basename = "sector_size"
    out_ovf = os.path.join(WORK_DIR, f"{basename}.ovf")
    in_yaml = os.path.join(CONFIG_DIR, f"{basename}.yaml")

    process = subprocess.run([OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "--vmdk-convert", VMDK_CONVERT, "--param", "disk=dummy.vmdk"], cwd=WORK_DIR)
    assert process.returncode == 0

    with open(in_yaml) as f:
        yaml_loader = yaml.SafeLoader
        yaml_loader.app_params = {}
        yaml.add_constructor("!param", yaml_param, Loader=yaml_loader)
        config = yaml.load(f, Loader=yaml_loader)

    with open(out_ovf) as f:
        ovf = xmltodict.parse(f.read())

    cfg_hardware_section = config['hardware']
    cfg_vmw_ovf = ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']['Item']

    disk_map = {
        'dummydisk': "native_512",                                         # set sector size by default
        'dummy512disk': "native_512", 'dummy4kdisk': "native_4k",          # get sector size from disk
        'dummy512disk_set': "native_512", 'dummy4kdisk_set': "native_4k",  # get sector size from yaml
        'dummydisk_config': "emulated_512",                                # get sector size from config
        'dummydisk_config_null': None,                                     # unset sector size from config
        'dummydisk_config_null2': None,                                    # unset sector size from itherwise non-empty config
    }
    disk_found = {}
    for k in disk_map.keys():
        disk_found[k] = False

    for disk_name, v_disk_fmt in disk_map.items():
        for hw_item in cfg_vmw_ovf:
            if hw_item['rasd:ElementName'] == disk_name:
                disk_found[disk_name] = True
                if v_disk_fmt is not None:
                    assert 'vmw:Config' in hw_item
                    config = hw_item['vmw:Config']
                    if not isinstance(config, list):
                        config = [config]
                    for cfg_item in config:
                        if cfg_item['@vmw:key'] == "virtualDiskFormat":
                            found = True
                            assert cfg_item['@vmw:value'] == v_disk_fmt, f"virtualDiskFormat for {disk_name} not expected"
                else:
                    if 'vmw:Config' in hw_item:
                        config = hw_item['vmw:Config']
                        if not isinstance(config, list):
                            config = [config]
                        for cfg_item in config:
                            assert cfg_item['@vmw:key'] != "virtualDiskFormat", "no 'virtualDiskFormat' expected in 'vmw:Config'"


    assert (all(disk_found.values())), f"not all values of {', '.join(disk_found.keys())} were tested - missing in config?"
