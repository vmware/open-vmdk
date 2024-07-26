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

import glob
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

WORK_DIR=os.path.join(os.getcwd(), "pytest-configs")


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)

    process = subprocess.run(["dd", "if=/dev/zero", "of=dummy.img", "bs=1024", "count=1024"], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run([VMDK_CONVERT, "dummy.img", "dummy.vmdk"], cwd=WORK_DIR)
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


@pytest.mark.parametrize("in_yaml", glob.glob(os.path.join(CONFIG_DIR, "*.yaml")))
def test_configs(in_yaml):
    basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
    out_ovf = os.path.join(WORK_DIR, f"{basename}.ovf")

    process = subprocess.run([OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "--vmdk-convert", VMDK_CONVERT], cwd=WORK_DIR)
    assert process.returncode == 0

    with open(in_yaml) as f:
        yaml_loader = yaml.SafeLoader
        yaml_loader.app_params = {}
        yaml.add_constructor("!param", yaml_param, Loader=yaml_loader)
        config = yaml.load(f, Loader=yaml_loader)

    with open(out_ovf) as f:
        ovf = xmltodict.parse(f.read())

    cfg_system = config['system']
    assert cfg_system['name'] == ovf['Envelope']['VirtualSystem']['Name']
    assert cfg_system['os_vmw'] == ovf['Envelope']['VirtualSystem']['OperatingSystemSection']['@vmw:osType']
    assert cfg_system['type'] == ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']['System']['vssd:VirtualSystemType']

    vmw_configs = ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']['vmw:Config']

    # TODO: check if default is set to bios unless no_default_configs is set
    if 'firmware' in cfg_system:
        firmware = None
        if type(vmw_configs) == list:
            for vmw_config in vmw_configs:
                if vmw_config['@vmw:key'] == "firmware":
                    firmware = vmw_config['@vmw:value']
        assert cfg_system['firmware'] == firmware
