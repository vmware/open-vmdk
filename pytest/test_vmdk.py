# Copyright (c) 2025 Broadcom.  All Rights Reserved.
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


import hashlib
import os
import pytest
import shutil
import subprocess


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR=os.path.join(THIS_DIR, "configs")
VMDK_CONVERT=os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")
WORK_DIR=os.path.join(os.getcwd(), "pytest-vmdk")


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)

    # this creates a mixed random file, with uncompressable data, zeros (skipped in the sparse vmdk), and compressible text
    cmd = "( for i in $(seq 1 10) ; do dd if=/dev/zero count=1024 bs=1024 ; dd if=/dev/random count=1024 bs=1024 ; base64 /dev/urandom | dd count=1024 bs=1024 ; done ) > random.img"
    process = subprocess.run(
            ["/bin/sh", "-c", cmd],
            cwd=WORK_DIR)
    assert process.returncode == 0

    yield
#    shutil.rmtree(WORK_DIR)


def get_hash(filename):
    hash_type = "sha256"
    blocksz = 1024 * 1024
    hash = hashlib.new(hash_type)
    with open(filename, "rb") as f:
        while True:
            buf = f.read(blocksz)
            if not buf:
                break
            hash.update(buf)
    return hash.hexdigest()


def test_no_option(setup_test):
    img_name = "random.img"
    img_name_back = "random-back.img"
    vmdk_name = "random.vmdk"

    orig_hash = get_hash(os.path.join(WORK_DIR, img_name))

    process = subprocess.run([VMDK_CONVERT, img_name, vmdk_name], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run([VMDK_CONVERT, vmdk_name, img_name_back], cwd=WORK_DIR)
    assert process.returncode == 0

    hash = get_hash(os.path.join(WORK_DIR, img_name_back))
    assert hash == orig_hash, f"hash of {img_name_back} ({hash[0:8]}) does not match that of original {img_name} ({orig_hash[0:8]}) for n={n}"


def test_num_threads(setup_test):
    img_name = "random.img"
    img_name_back = "random-back.img"
    vmdk_name = "random.vmdk"

    orig_hash = get_hash(os.path.join(WORK_DIR, img_name))

    for n in range(1, 8):
        process = subprocess.run([VMDK_CONVERT, "-n", str(n), img_name, vmdk_name], cwd=WORK_DIR)
        assert process.returncode == 0

        process = subprocess.run([VMDK_CONVERT, vmdk_name, img_name_back], cwd=WORK_DIR)
        assert process.returncode == 0

        hash = get_hash(os.path.join(WORK_DIR, img_name_back))
        assert hash == orig_hash, f"hash of {img_name_back} ({hash}) does not match that of original {img_name} ({orig_hash}) for n={n}"


def test_compression_levels(setup_test):
    img_name = "random.img"
    img_name_back = "random-back.img"
    vmdk_name = "random.vmdk"

    orig_hash = get_hash(os.path.join(WORK_DIR, img_name))

    for n in range(1, 9):
        process = subprocess.run([VMDK_CONVERT, "-c", str(n), img_name, vmdk_name], cwd=WORK_DIR)
        assert process.returncode == 0

        process = subprocess.run([VMDK_CONVERT, vmdk_name, img_name_back], cwd=WORK_DIR)
        assert process.returncode == 0

        hash = get_hash(os.path.join(WORK_DIR, img_name_back))
        assert hash == orig_hash, f"hash of {img_name_back} ({hash}) does not match that of original {img_name} ({orig_hash}) for n={n}"


def test_both(setup_test):
    img_name = "random.img"
    img_name_back = "random-back.img"
    vmdk_name = "random.vmdk"

    orig_hash = get_hash(os.path.join(WORK_DIR, img_name))

    process = subprocess.run([VMDK_CONVERT, "-c", "6", "-n", "4", img_name, vmdk_name], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run([VMDK_CONVERT, vmdk_name, img_name_back], cwd=WORK_DIR)
    assert process.returncode == 0

    hash = get_hash(os.path.join(WORK_DIR, img_name_back))
    assert hash == orig_hash, f"hash of {img_name_back} ({hash}) does not match that of original {img_name} ({orig_hash}) for n={n}"
