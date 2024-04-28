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
import hashlib
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

WORK_DIR=os.path.join(os.getcwd(), "pytest-manifest")


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)

    process = subprocess.run(["dd", "if=/dev/zero", "of=dummy.img", "bs=1024", "count=1024"], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run([VMDK_CONVERT, "dummy.img", "dummy.vmdk"], cwd=WORK_DIR)
    assert process.returncode == 0

    yield
    shutil.rmtree(WORK_DIR)


def check_mf(mf_path, hash_type, work_dir=WORK_DIR):
    with open(mf_path, "rt") as f:
        for line in f:
            left, hash_mf = line.split("=")
            hash_mf = hash_mf.strip()

            assert left.startswith(hash_type.upper())

            filename = left[len(hash_type):].strip("()")
            hash = hashlib.new(hash_type)
            with open(os.path.join(work_dir, filename), "rb") as f:
                hash.update(f.read())

            assert hash.hexdigest() == hash_mf


@pytest.mark.parametrize("hash_type", [None, "sha1", "sha256", "sha512"])
def test_ovf_manifest(hash_type):
    in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
    basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
    out_ovf = os.path.join(WORK_DIR, f"{basename}.ovf")
    out_mf = os.path.join(WORK_DIR, f"{basename}.mf")

    args = [OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "-m"]
    if hash_type is not None:
        args += ["--checksum-type", hash_type]
    else:
        hash_type = "sha256"

    process = subprocess.run(args, cwd=WORK_DIR)
    assert process.returncode == 0

    assert os.path.isfile(out_mf)

    check_mf(out_mf, hash_type)


@pytest.mark.parametrize("hash_type", [None, "sha1", "sha256", "sha512"])
def test_ova_manifest(hash_type):
    in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
    basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
    out_ova = os.path.join(WORK_DIR, f"{basename}.ova")
    out_mf = os.path.join(WORK_DIR, f"{basename}.mf")

    args = [OVA_COMPOSE, "-i", in_yaml, "-o", out_ova]
    if hash_type is not None:
        args += ["--checksum-type", hash_type]
    else:
        hash_type = "sha256"

    process = subprocess.run(args, cwd=WORK_DIR)
    assert process.returncode == 0

    subprocess.run(["tar", "xf", out_ova], cwd=WORK_DIR)

    check_mf(out_mf, hash_type)


def test_manifest_invalid_checksum_type():
    in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
    basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
    out_ovf = os.path.join(WORK_DIR, f"{basename}.ovf")
    out_mf = os.path.join(WORK_DIR, f"{basename}.mf")

    args = [OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "-m", "--checksum-type", "foobar"]
    process = subprocess.run(args, cwd=WORK_DIR)
    assert process.returncode != 0

