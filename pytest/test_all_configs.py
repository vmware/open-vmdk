# Copyright (c) 2024 Broadcom.  All Rights Reserved.
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


def assert_values(val1, val2):
    if val1:
        assert val1 == val2


@pytest.fixture(scope='module')
def get_configs(setup_test):
    in_yaml =  os.path.join(CONFIG_DIR, "all.yaml")
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

    yield config, ovf


def test_product_sections_configs(get_configs):
    #ProductSection
    config, ovf = get_configs

    cfg_product_sections = config["product_sections"]
    cfg_vmw_ovf = ovf['Envelope']['VirtualSystem']['ProductSection']

    transports = []
    key_dict_product = {'instance': '@ovf:instance', 'class': '@ovf:class', 'vendor': 'Vendor',
                        'product': 'Product', 'info': 'Info', 'version': 'Version', 'full_version': 'FullVersion'}

    key_dict_properties = {'type': '@ovf:type', 'value': '@ovf:value', 'description': 'Description', 'label': 'Label'}

    for i, cfg_product_section in enumerate(cfg_product_sections):
        for el1, el2 in key_dict_product.items():
            assert_values(cfg_product_section.get(el1), cfg_vmw_ovf[i].get(el2))

        if cfg_product_section.get('properties'):
            properties = cfg_vmw_ovf[i]['Property'] if isinstance(cfg_vmw_ovf[i]['Property'], list) else [cfg_vmw_ovf[i]['Property']]
            for key in cfg_product_sections[i]['properties']:
                 j = 0
                 for j in range(len(properties)):
                     if key == properties[j]['@ovf:key']:
                         break
                 assert_values(key, properties[j]['@ovf:key'])
                 for el1, el2 in key_dict_properties.items():
                     assert_values(cfg_product_section['properties'][key].get(el1), properties[j].get(el2))
                 assert_values(cfg_product_section['properties'][key].get('user_configurable'),  bool(properties[j].get('@ovf:userConfigurable')))
                 assert_values(cfg_product_section['properties'][key].get('password'),  bool(properties[j].get('@ovf:password')))

        if 'categories' in cfg_product_section:
            assert_values(list(cfg_product_section['categories'].values()), list(cfg_vmw_ovf[i].get('Category')))

        if 'transports' in cfg_product_section:
            transports.extend(cfg_product_section['transports'])

    if transports:
        assert_values(set(transports), set(ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']['@ovf:transport'].split()))


def test_annotation_configs(get_configs):
    #Annotation Section
    config, ovf = get_configs

    cfg_annotation_section = config['annotation']
    cfg_vmw_ovf =  ovf['Envelope']['VirtualSystem']['AnnotationSection']

    if cfg_annotation_section.get('file'):
        with open(cfg_annotation_section['file'], 'r') as f:
            assert_values(f.read()[:-1], cfg_vmw_ovf.get('Annotation'))
    else:
        assert_values(cfg_annotation_section.get('text'), cfg_vmw_ovf.get('Annotation'))
    assert_values(cfg_annotation_section.get('info'), cfg_vmw_ovf.get('Info'))


def test_networks_configs(get_configs):
    #Network Section
    config, ovf = get_configs

    cfg_networks_section = config['networks']
    cfg_vmw_ovf = ovf['Envelope']['NetworkSection']['Network']
    cfg_vmw_ovf = cfg_vmw_ovf if isinstance(ovf['Envelope']['NetworkSection']['Network'], list) else [ovf['Envelope']['NetworkSection']['Network']]

    for idx, key in enumerate(cfg_networks_section):
        assert_values(cfg_networks_section[key]['name'], cfg_vmw_ovf[idx]['@ovf:name'])
        assert_values(f"The {cfg_networks_section[key]['name']} Network", cfg_vmw_ovf[idx]['Description'])


def test_envelope_configs(get_configs):
    #Envelope Section
    config, ovf = get_configs

    cfg_hardware_section =  config['hardware']
    cfg_vmw_ovf = ovf['Envelope']['References']['File']
    cfg_vmw_ovf = cfg_vmw_ovf if isinstance(ovf['Envelope']['References']['File'], list) else [ovf['Envelope']['References']['File']]

    j = 0
    for key in cfg_hardware_section:
        if isinstance(cfg_hardware_section[key], dict):
            image_path = cfg_hardware_section[key].get('disk_image') or cfg_hardware_section[key].get('raw_image')
            if image_path:
                image_path = image_path if image_path.endswith('.vmdk') else os.path.splitext(image_path)[0] + '.vmdk'
                assert_values(image_path, cfg_vmw_ovf[j]['@ovf:href'])
                assert_values(cfg_hardware_section[key].get('file_id'), cfg_vmw_ovf[j]['@ovf:id'])
                j += 1


def test_virtual_hardware_configs():
    # TODO
    pass
