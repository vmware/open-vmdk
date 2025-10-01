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
import json
import os
import pytest
import shutil
import subprocess
import urllib


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR=os.path.join(THIS_DIR, "configs")
VMDK_CONVERT=os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")
WORK_DIR=os.path.join(os.getcwd(), "pytest-vmdk")


#PHOTON_OVA_URL = "https://packages-prod.broadcom.com/photon/5.0/RC/ova/photon-uefi-hw14-5.0-4d5974638.aarch64.ova"
PHOTON_OVA_URL = "https://packages.vmware.com/photon/5.0/RC/ova/photon-uefi-hw14-5.0-4d5974638.aarch64.ova"
PHOTON_OVA_SHA512 = "d02d9f8c4e35aa4a1d425174dd531983572809d39cf18854d236147213d84917db960d61ae53cefbf6ac15826d45143cd39012ff3ff4ee36ad65d9c937bc792e"
PHOTON_VMDK = "photon-disk1.vmdk"
PHOTON_RAWIMAGE_PATH = os.path.join(WORK_DIR, "photon-disk1.img")
PHOTON_DISK2_TYPE = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"
PHOTON_DISK2_UUID = "ABC1D7E1-B1EF-43F2-849D-9D5955B228BF"


def download(url: str, local_filepath: str):
    print(f"Starting download from: {url}")
    with urllib.request.urlopen(url) as response, open(local_filepath, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)


def get_hash(filename, hash_type="sha256"):
    blocksz = 1024 * 1024
    hash = hashlib.new(hash_type)
    with open(filename, "rb") as f:
        while True:
            buf = f.read(blocksz)
            if not buf:
                break
            hash.update(buf)
    return hash.hexdigest()


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)

    # this creates a mixed random file, with uncompressable data, zeros (skipped in the sparse vmdk), and compressible text
    cmd = "( for i in $(seq 1 10) ; do dd if=/dev/zero count=1024 bs=1024 ; dd if=/dev/random count=1024 bs=1024 ; base64 /dev/urandom | dd count=1024 bs=1024 ; done ) > random.img"
    process = subprocess.run(
            ["/bin/sh", "-c", cmd],
            cwd=WORK_DIR)
    assert process.returncode == 0

    photon_ova = os.path.basename(PHOTON_OVA_URL)
    photon_ova_path = os.path.join(WORK_DIR, photon_ova)
    if not os.path.exists(photon_ova_path):
        download(PHOTON_OVA_URL, photon_ova_path)

    sha512 = get_hash(photon_ova_path, hash_type="sha512")
    assert sha512 == PHOTON_OVA_SHA512, f"sha512 of {photon_ova_path} ({sha512}) does not match {PHOTON_OVA_SHA512}"

    subprocess.check_call(["tar", "xf", photon_ova_path], cwd=WORK_DIR)
    assert os.path.exists(os.path.join(WORK_DIR, PHOTON_VMDK))

    yield
#    try:
#        os.remove(PHOTON_IMAGE_PATH_TMP)
#    except OSError:
#        pass
#    shutil.rmtree(WORK_DIR)


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
    assert hash == orig_hash, f"hash of {img_name_back} ({hash[0:8]}) does not match that of original {img_name} ({orig_hash[0:8]})"


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
    assert hash == orig_hash, f"hash of {img_name_back} ({hash}) does not match that of original {img_name} ({orig_hash})"


# test reading a VMDK generated with VMware disklik
def test_photon_vmdk(setup_test):

    vmdk_path = os.path.join(WORK_DIR, PHOTON_VMDK)

    # get detailed info from VMDK
    detailed_dict = json.loads(subprocess.check_output([VMDK_CONVERT, "-i", "--detailed", vmdk_path], text=True, cwd=WORK_DIR))

    # and check a few expected values
    assert detailed_dict.get('sparseHeader') is not None
    # disklib generated VMDKs have this, our own do not
    assert detailed_dict['sparseHeader']['hasFooter']

    # decompress VMDK
    process = subprocess.run([VMDK_CONVERT, vmdk_path, PHOTON_RAWIMAGE_PATH], cwd=WORK_DIR)
    assert process.returncode == 0

    # and check its partition table to make sure it's a valid disk image
    sfdisk_dict = json.loads(subprocess.check_output(["sfdisk", "-J", PHOTON_RAWIMAGE_PATH], text=True))

    # and check a few expected values
    assert sfdisk_dict['partitiontable']['partitions'][1]['type'] == PHOTON_DISK2_TYPE
    assert sfdisk_dict['partitiontable']['partitions'][1]['uuid'] == PHOTON_DISK2_UUID
