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
CONFIG_DIR = os.path.join(THIS_DIR, "configs")


def assert_values(val1, val2):
    if val1:
        assert val1 == val2


@pytest.mark.parametrize('get_configs', [os.path.join(CONFIG_DIR, "all.yaml")], indirect=True)
def test_envelope_configs(setup_test, get_configs):
    #Envelope Section

    config, ovf = get_configs

    cfg_hardware_section =  config['hardware']
    cfg_vmw_ovf = ovf['Envelope']['References']['File']
    cfg_vmw_ovf = cfg_vmw_ovf if isinstance(cfg_vmw_ovf, list) else [cfg_vmw_ovf]

    j = 0
    for key in cfg_hardware_section:
        if isinstance(cfg_hardware_section[key], dict):
            image_path = cfg_hardware_section[key].get('disk_image') or cfg_hardware_section[key].get('raw_image')
            if image_path:
                image_path = image_path if image_path.endswith('.vmdk') else os.path.splitext(image_path)[0] + '.vmdk'
                assert_values(image_path, cfg_vmw_ovf[j]['@ovf:href'])
                assert_values(cfg_hardware_section[key].get('file_id'), cfg_vmw_ovf[j]['@ovf:id'])
                j += 1
