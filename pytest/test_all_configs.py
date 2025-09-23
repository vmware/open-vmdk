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
import test_envelope_configs


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR=os.path.join(THIS_DIR, "configs")


@pytest.mark.parametrize('get_configs', glob.glob(os.path.join(CONFIG_DIR, "*.yaml")), indirect=True)
class TestAllConfigs:
    ''' Test configs under each section '''

    @pytest.fixture(autouse=True)
    def setup_class(self, setup_test, get_configs):
        self.config, self.ovf = get_configs


    def assert_values(self, val1, val2):
        if val1 is not None:
            if isinstance(val1, bool):
                val2 = {"true": True, "false": False}[val2]
            assert val1 == val2


    def test_product_sections_configs(self):
        #ProductSection

        if 'product_sections' not in self.config:
            pytest.skip("no 'product_sections' in config")

        cfg_product_sections = self.config["product_sections"]
        cfg_vmw_ovf = self.ovf['Envelope']['VirtualSystem']['ProductSection']

        transports = []
        key_dict_product = {'instance': '@ovf:instance', 'class': '@ovf:class', 'vendor': 'Vendor',
                            'product': 'Product', 'info': 'Info', 'version': 'Version', 'full_version': 'FullVersion'}

        key_dict_properties = {'type': '@ovf:type', 'value': '@ovf:value', 'description': 'Description', 'label': 'Label'}

        for i, cfg_product_section in enumerate(cfg_product_sections):
            for el1, el2 in key_dict_product.items():
                self.assert_values(cfg_product_section.get(el1), cfg_vmw_ovf[i].get(el2))

            if cfg_product_section.get('properties'):
                properties = cfg_vmw_ovf[i]['Property'] if isinstance(cfg_vmw_ovf[i]['Property'], list) else [cfg_vmw_ovf[i]['Property']]
                for key in cfg_product_sections[i]['properties']:
                     j = 0
                     for j in range(len(properties)):
                         if key == properties[j]['@ovf:key']:
                             break
                     self.assert_values(key, properties[j]['@ovf:key'])
                     for el1, el2 in key_dict_properties.items():
                         self.assert_values(cfg_product_section['properties'][key].get(el1), properties[j].get(el2))
                     self.assert_values(cfg_product_section['properties'][key].get('user_configurable'), properties[j].get('@ovf:userConfigurable'))
                     self.assert_values(cfg_product_section['properties'][key].get('password'), properties[j].get('@ovf:password'))

            if 'categories' in cfg_product_section:
                cfg_categories = cfg_product_section['categories']
                ovf_categories = cfg_vmw_ovf[i].get('Category')
                if len(cfg_categories) == 1:
                    assert next(iter(cfg_categories.values())) == ovf_categories
                else:
                    assert len(cfg_categories) == len(ovf_categories)
                    for k, v in cfg_categories.items():
                        assert v in ovf_categories

            if 'transports' in cfg_product_section:
                transports.extend(cfg_product_section['transports'])

        if transports:
            self.assert_values(set(transports), set(self.ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']['@ovf:transport'].split()))


    def test_annotation_configs(self):
        #Annotation Section

        if 'annotation' not in self.config:
            pytest.skip("no 'annotation' in config")

        cfg_annotation_section = self.config['annotation']
        cfg_vmw_ovf =  self.ovf['Envelope']['VirtualSystem']['AnnotationSection']

        if cfg_annotation_section.get('file'):
            with open(cfg_annotation_section['file'], 'r') as f:
                self.assert_values(f.read()[:-1], cfg_vmw_ovf.get('Annotation'))
        else:
            self.assert_values(cfg_annotation_section.get('text').strip(), cfg_vmw_ovf.get('Annotation').strip())
        self.assert_values(cfg_annotation_section.get('info'), cfg_vmw_ovf.get('Info'))


    def test_networks_configs(self):
        #Network Section

        if 'networks' not in self.config:
            pytest.skip("no 'networks' in config")

        cfg_networks_section = self.config['networks']
        cfg_vmw_ovf = self.ovf['Envelope']['NetworkSection']['Network']
        cfg_vmw_ovf = cfg_vmw_ovf if isinstance(cfg_vmw_ovf, list) else [cfg_vmw_ovf]

        for idx, key in enumerate(cfg_networks_section):
            self.assert_values(cfg_networks_section[key]['name'], cfg_vmw_ovf[idx]['@ovf:name'])
            self.assert_values(f"The {cfg_networks_section[key]['name']} Network", cfg_vmw_ovf[idx]['Description'])


    def test_envelope_configs(self):
        #Envelope Section

        test_envelope_configs.test_envelope_configs(None, (self.config, self.ovf))


    def test_system_configs(self):
        # Operating System Section

        cfg_system_section = self.config['system']
        cfg_vmw_ovf =  self.ovf['Envelope']['VirtualSystem']
        vmw_configs = cfg_vmw_ovf['VirtualHardwareSection']['vmw:Config']

        self.assert_values(cfg_system_section['name'], cfg_vmw_ovf['Name'])
        self.assert_values(cfg_system_section['type'], cfg_vmw_ovf['VirtualHardwareSection']['System']['vssd:VirtualSystemType'])
        self.assert_values(cfg_system_section['os_vmw'], cfg_vmw_ovf['OperatingSystemSection']['@vmw:osType'])
        self.assert_values(cfg_system_section.get('os_cim'), int(cfg_vmw_ovf['OperatingSystemSection']['@ovf:id']))
        self.assert_values(cfg_system_section.get('os_name'), cfg_vmw_ovf['OperatingSystemSection'].get('Description'))

        for vmw_config in vmw_configs:
            if vmw_config['@vmw:key'] == "firmware":
                self.assert_values(cfg_system_section.get('firmware', "bios"), vmw_config['@vmw:value'])


    def test_virtual_hardware_configs(self):
        #Hardware Section

        cfg_hardware_section = self.config['hardware']
        cfg_vmw_ovf = self.ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']['Item']

        for idx, key in enumerate(cfg_hardware_section):
            self.assert_values(key, cfg_vmw_ovf[idx]['rasd:ElementName'])

            if key in ["cpus", "memory"]:
                if isinstance(cfg_hardware_section[key], int):
                    self.assert_values(cfg_hardware_section[key], int(cfg_vmw_ovf[idx]['rasd:VirtualQuantity']))
                else:
                    self.assert_values(cfg_hardware_section[key]['size'], int(cfg_vmw_ovf[idx]['rasd:VirtualQuantity']))
            else:
                self.assert_values(cfg_hardware_section[key].get('subtype'), cfg_vmw_ovf[idx].get('rasd:ResourceSubType'))
                self.assert_values(cfg_hardware_section[key].get('connected'), cfg_vmw_ovf[idx].get('rasd:AutomaticAllocation'))

            if isinstance(cfg_hardware_section[key], dict) and cfg_hardware_section[key].get('config') is not None:
                cfg_config = cfg_hardware_section[key]['config']
                ovf_config = cfg_vmw_ovf[idx].get('vmw:Config')
                for i, cfg in enumerate(cfg_config):
                    if isinstance(ovf_config, list):
                        ovf_keys = [props['@vmw:key'] for props in ovf_config]
                        ovf_values = [props['@vmw:value'] for props in ovf_config]
                        assert cfg in ovf_keys
                        cfg_value = cfg_config[cfg]
                        if type(cfg_value) is bool:
                            cfg_value = "true" if cfg_value else "false"
                        assert cfg_value == ovf_values[ovf_keys.index(cfg)]
                    else:
                        assert cfg == ovf_config['@vmw:key']
                        self.assert_values(cfg_config[cfg], ovf_config['@vmw:value'])


    def test_configuration_configs(self):
        #Deployment Option Section

        if 'configurations' not in self.config:
            pytest.skip("no 'configurations' in config")

        cfg_configuration_section = self.config['configurations']
        cfg_vmw_ovf = self.ovf['Envelope']['DeploymentOptionSection']['Configuration']
        cfg_vmw_ovf = cfg_vmw_ovf if isinstance(cfg_vmw_ovf, list) else [cfg_vmw_ovf]

        for idx, key in enumerate(cfg_configuration_section):
            self.assert_values(key, cfg_vmw_ovf[idx]['@ovf:id'])
            self.assert_values(cfg_configuration_section[key]['label'], cfg_vmw_ovf[idx]['Label'])
            self.assert_values(cfg_configuration_section[key]['description'], cfg_vmw_ovf[idx]['Description'])
