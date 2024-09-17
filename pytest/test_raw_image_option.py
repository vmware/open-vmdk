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
import test_envelope_configs

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OVA_COMPOSE = os.path.join(THIS_DIR, "..", "ova-compose", "ova-compose.py")

VMDK_CONVERT=os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")

CONFIG_DIR=os.path.join(THIS_DIR, "configs")

WORK_DIR=os.path.join(os.getcwd(), "pytest-configs")


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)

    # Dont create vmdk
    process = subprocess.run(["dd", "if=/dev/zero", "of=dummy.img", "bs=1024", "count=1024"], cwd=WORK_DIR)
    assert process.returncode == 0

    yield
    shutil.rmtree(WORK_DIR)


@pytest.mark.parametrize('get_configs', [os.path.join(CONFIG_DIR, "raw-image.yaml")], indirect=True)
def test_raw_image_configs(setup_test, get_configs):
    # test raw_image and other configs
    test_envelope_configs.test_envelope_configs(None, get_configs)

