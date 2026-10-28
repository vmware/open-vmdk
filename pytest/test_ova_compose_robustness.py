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
    # secure boot is enabled by default also without default configs, unless the firmware is bios
    ({"no_default_configs": "true"}, "", None, "true"),
    ({"no_default_configs": "true", "secure_boot": "false"}, "", None, "false"),
    ({"no_default_configs": "true", "firmware": "bios"}, "", "bios", "false"),
    # bios can also be set in hardware.config
    ({}, "\n    config:\n        firmware: bios\n", "bios", "false"),
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


@pytest.mark.parametrize("units,expected", [
    ("byte", 1536 * 1024),
    ("KB", 1536),
    # 1.5 MB must be rounded up
    ("MB", 2),
    ("GB", 1),
])
def test_disk_capacity_rounded_up(units, expected):
    process = subprocess.run(["dd", "if=/dev/zero", "of=odd.img", "bs=1024", "count=1536"], cwd=WORK_DIR)
    assert process.returncode == 0
    process = subprocess.run([VMDK_CONVERT, "odd.img", "odd.vmdk"], cwd=WORK_DIR)
    assert process.returncode == 0

    yaml_text = BASE_YAML.replace("disk_image: dummy.vmdk", f"disk_image: odd.vmdk\n        units: {units}\n        disk_id: rootdisk")
    process, ovf = compose(yaml_text)
    assert process.returncode == 0, process.stderr
    assert disks(ovf)['rootdisk']['@ovf:capacity'] == str(expected)


SIGN_P7S = os.path.join(THIS_DIR, "..", "ova-compose", "sign-p7s.sh")


@pytest.fixture(scope='module')
def rsa_key():
    """an RSA key and certificate in one PEM file, in WORK_DIR"""
    if shutil.which("openssl") is None:
        pytest.skip("openssl not installed")
    process = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                              "-subj", "/CN=ova-compose-test", "-keyout", "key.pem", "-out", "cert.pem"],
                             cwd=WORK_DIR, capture_output=True)
    assert process.returncode == 0, process.stderr
    with open(os.path.join(WORK_DIR, "rsa.pem"), "w") as fout:
        for name in ["key.pem", "cert.pem"]:
            with open(os.path.join(WORK_DIR, name)) as fin:
                fout.write(fin.read())
    return "rsa.pem"


@pytest.mark.parametrize("output", ["out.ovf", "out.ova", "out-dir"])
def test_sign_script_relative_paths(rsa_key, output):
    """relative paths in the sign script are relative to the directory ova-compose runs in"""
    # the key is given relative to the working directory, as in the example in sign-p7s.sh
    script = f"{SIGN_P7S} -a {{sign_alg}} {{mf_file}} {{p7s_file}} {rsa_key}"
    args = ["--sign-format", "p7s", "--sign-script", script]
    if output == "out-dir":
        args += ["--format", "dir"]
    process, _ = compose(BASE_YAML, output=output, args=args)
    assert process.returncode == 0, process.stderr

    if output == "out.ova":
        members = subprocess.check_output(["tar", "tf", output], cwd=WORK_DIR, text=True).split()
        assert members[:3] == ["out.ovf", "out.mf", "out.p7s"]
    elif output == "out-dir":
        assert os.path.isfile(os.path.join(WORK_DIR, output, "out-dir.p7s"))
    else:
        assert os.path.isfile(os.path.join(WORK_DIR, "out.p7s"))


@pytest.mark.parametrize("output", ["my vm.ova", "my vm.ovf", "x$(touch pwned).ovf"])
def test_sign_script_quoting(rsa_key, output):
    """file names are quoted for the shell running the sign script"""
    script = f"{SIGN_P7S} -a {{sign_alg}} {{mf_file}} {{p7s_file}} {rsa_key}"
    process, _ = compose(BASE_YAML, output=output, args=["--sign-format", "p7s", "--sign-script", script])
    assert process.returncode == 0, process.stderr
    assert not os.path.exists(os.path.join(WORK_DIR, "pwned"))
    if output.endswith(".ova"):
        members = subprocess.check_output(["tar", "tf", output], cwd=WORK_DIR, text=True).splitlines()
        assert members[:3] == ["my vm.ovf", "my vm.mf", "my vm.p7s"]
    else:
        assert os.path.isfile(os.path.join(WORK_DIR, output[:-len(".ovf")] + ".p7s"))


def test_sign_script_braces(rsa_key):
    """literal braces must be doubled, and give a clear error if they are not"""
    script = f"K={rsa_key} ; {SIGN_P7S} -a {{sign_alg}} {{mf_file}} {{p7s_file}} ${{{{K}}}}"
    process, _ = compose(BASE_YAML, args=["--sign-format", "p7s", "--sign-script", script])
    assert process.returncode == 0, process.stderr

    script = f"K={rsa_key} ; {SIGN_P7S} -a {{sign_alg}} {{mf_file}} {{p7s_file}} ${{K}}"
    process, _ = compose(BASE_YAML, args=["--sign-format", "p7s", "--sign-script", script])
    assert process.returncode != 0
    assert "literal braces must be doubled" in process.stderr


def files(ovf):
    return as_list(ovf['Envelope']['References'].get('File'))


def cdrom_yaml(file_id, image="cd.iso"):
    with open(os.path.join(WORK_DIR, image), "wb") as f:
        f.write(b"\0" * 2048)
    return BASE_YAML + f"""
    ide1:
        type: ide_controller
    cdrom1:
        type: cd_drive
        parent: ide1
        image: {image}
        file_id: {file_id}
"""


def test_explicit_file_id_not_generated():
    """an explicit file id must not collide with a generated one"""
    process, ovf = compose(cdrom_yaml("file0"))
    assert process.returncode == 0, process.stderr
    ids = [f['@ovf:id'] for f in files(ovf)]
    assert sorted(ids) == sorted(set(ids)), f"duplicate file ids {ids}"
    assert "file0" in ids


def test_explicit_disk_id_not_generated():
    """an explicit disk id must not collide with a generated one"""
    yaml_text = BASE_YAML + """
    datadisk:
        type: hard_disk
        parent: sata1
        disk_capacity: 10
        disk_id: vmdisk0
"""
    process, ovf = compose(yaml_text)
    assert process.returncode == 0, process.stderr
    ids = [d['@ovf:diskId'] for d in as_list(ovf['Envelope']['DiskSection']['Disk'])]
    assert len(ids) == 2
    assert len(set(ids)) == 2, f"duplicate disk ids {ids}"
    assert "vmdisk0" in ids


def test_duplicate_explicit_ids():
    yaml_text = BASE_YAML.replace("disk_image: dummy.vmdk", "disk_image: dummy.vmdk\n        file_id: same")
    process, _ = compose(cdrom_yaml("same").replace(BASE_YAML, yaml_text))
    assert process.returncode != 0
    assert "duplicate file id(s): same" in process.stderr


@pytest.mark.parametrize("output", ["out.ovf", "out.ova"])
def test_same_file_name(output):
    """two different files with the same name cannot be in one OVF"""
    os.makedirs(os.path.join(WORK_DIR, "sub"), exist_ok=True)
    shutil.copy(os.path.join(WORK_DIR, "dummy.vmdk"), os.path.join(WORK_DIR, "sub", "dummy.vmdk"))
    yaml_text = BASE_YAML + """
    datadisk:
        type: hard_disk
        parent: sata1
        disk_image: sub/dummy.vmdk
"""
    process, _ = compose(yaml_text, output=output)
    assert process.returncode != 0
    assert "have the same file name 'dummy.vmdk'" in process.stderr


@pytest.mark.parametrize("explicit_id_on_second", [False, True])
def test_same_image_twice(explicit_id_on_second):
    """the same image can be used by more than one device, and is referenced once"""
    yaml_text = cdrom_yaml("cdimage") + """
    cdrom2:
        type: cd_drive
        parent: ide1
        image: cd.iso
"""
    if explicit_id_on_second:
        yaml_text = yaml_text.replace("        file_id: cdimage\n", "") + "        file_id: cdimage\n"
    process, ovf = compose(yaml_text, output="out.ovf")
    assert process.returncode == 0, process.stderr
    hrefs = [f['@ovf:href'] for f in files(ovf)]
    assert hrefs.count("cd.iso") == 1
    assert next(f for f in files(ovf) if f['@ovf:href'] == "cd.iso")['@ovf:id'] == "cdimage"
    items = as_list(ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']['Item'])
    assert [i['rasd:HostResource'] for i in items if i['rasd:ResourceType'] == "15"] == ["ovf:/file/cdimage"] * 2

    process, _ = compose(yaml_text, output="out.ova")
    assert process.returncode == 0, process.stderr


@pytest.mark.parametrize("output", ["out.ovf", "out.ova"])
@pytest.mark.parametrize("explicit_id_on", [None, "first", "second"])
@pytest.mark.parametrize("image_source", ["disk_image: dummy.vmdk", "raw_image: dummy.img"])
def test_same_disk_image_twice(output, explicit_id_on, image_source):
    """the same disk image can be used by more than one disk, it is referenced once"""
    yaml_text = BASE_YAML.replace("disk_image: dummy.vmdk", "disk_image: dummy.vmdk\n        disk_id: disk1") + f"""
    datadisk:
        type: hard_disk
        parent: sata1
        {image_source}
        disk_id: disk2
"""
    if explicit_id_on is not None:
        disk_id = "disk1" if explicit_id_on == "first" else "disk2"
        yaml_text = yaml_text.replace(f"        disk_id: {disk_id}\n", f"        disk_id: {disk_id}\n        file_id: shared\n")
    process, ovf = compose(yaml_text, output=output)
    assert process.returncode == 0, process.stderr
    if ovf is not None:
        assert [f['@ovf:href'] for f in files(ovf)] == ["dummy.vmdk"]
        file_id = files(ovf)[0]['@ovf:id']
        if explicit_id_on is not None:
            assert file_id == "shared"
        assert {d['@ovf:fileRef'] for d in disks(ovf).values()} == {file_id}
        assert set(disks(ovf).keys()) == {"disk1", "disk2"}


def test_same_image_conflicting_file_ids():
    yaml_text = cdrom_yaml("first") + """
    cdrom2:
        type: cd_drive
        parent: ide1
        image: cd.iso
        file_id: second
"""
    process, _ = compose(yaml_text)
    assert process.returncode != 0
    assert "conflicting file ids" in process.stderr


NON_STRING_PRODUCT = """
product:
    product: Robustness
    vendor: Broadcom
    version: 5
    full_version: 5.1
    required: false
    instance: 1
    transports:
        - iso
    properties:
        port:
            type: uint16
            value: 80
            qualifiers: 0
            label: 8080
            description: 42
            user_configurable: true
"""


def test_non_string_values():
    """numbers and booleans in the config are written as strings"""
    process, ovf = compose(BASE_YAML + NON_STRING_PRODUCT)
    assert process.returncode == 0, process.stderr
    product = ovf['Envelope']['VirtualSystem']['ProductSection']
    assert product['Version'] == "5"
    assert product['FullVersion'] == "5.1"
    assert product['@ovf:required'] == "false"
    assert product['@ovf:instance'] == "1"
    prop = product['Property']
    assert prop['@ovf:value'] == "80"
    assert prop['@ovf:qualifiers'] == "0"
    assert prop['Label'] == "8080"
    assert prop['Description'] == "42"


@pytest.mark.parametrize("configuration,error", [
    ("        label: Small\n", "configuration 'small' needs a 'description'"),
    ("        description: A small one\n", "configuration 'small' needs a 'label'"),
])
def test_configuration_incomplete(configuration, error):
    process, _ = compose(BASE_YAML + "\nconfigurations:\n    small:\n" + configuration)
    assert process.returncode != 0
    assert error in process.stderr


def test_default_configuration_unknown():
    yaml_text = with_system(default_configuration="large") + """
configurations:
    small:
        label: Small
        description: A small one
"""
    process, _ = compose(yaml_text)
    assert process.returncode != 0
    assert "default_configuration 'large' is not in configurations" in process.stderr


def test_network_without_description():
    process, ovf = compose(BASE_YAML.replace('        description: "The VM Network"\n', ''))
    assert process.returncode == 0, process.stderr
    network = ovf['Envelope']['NetworkSection']['Network']
    assert network['@ovf:name'] == "VM Network"
    assert network['Description'] == "The VM Network Network"


def transport_yaml(transports):
    """two product sections, the second one with the transports in reverse order"""
    yaml_text = BASE_YAML + "\nproduct_sections:\n"
    for name, product_transports in [("P1", transports), ("P2", list(reversed(transports)))]:
        yaml_text += f"    - product: {name}\n      transports:\n"
        yaml_text += "".join(f"          - {t}\n" for t in product_transports)
    return yaml_text


def test_transports_ordered():
    """the transports are in the order of the config, so the output is reproducible"""
    for _ in range(5):
        process, ovf = compose(transport_yaml(["iso", "com.vmware.guestInfo"]))
        assert process.returncode == 0, process.stderr
        hw = ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']
        assert hw['@ovf:transport'] == "iso com.vmware.guestInfo"


def test_no_transports():
    """no empty transport attribute if there are no transports"""
    process, ovf = compose(BASE_YAML + "\nproduct:\n    product: P1\n")
    assert process.returncode == 0, process.stderr
    assert '@ovf:transport' not in ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']


def test_text_block_info():
    """annotation and EULA have their own default Info, which can be overridden"""
    yaml_text = BASE_YAML + """
annotation:
    text: an annotation
eula:
    text: a license
"""
    process, ovf = compose(yaml_text)
    assert process.returncode == 0, process.stderr
    vs = ovf['Envelope']['VirtualSystem']
    assert vs['AnnotationSection']['Info'] == "Description of the Product"
    assert vs['EulaSection']['Info'] == "End User License Agreement"

    process, ovf = compose(yaml_text.replace("    text: a license\n", "    text: a license\n    info: My License\n"))
    assert process.returncode == 0, process.stderr
    assert ovf['Envelope']['VirtualSystem']['EulaSection']['Info'] == "My License"


def controller_yaml(controller_type, num_disks):
    yaml_text = BASE_YAML + f"""
    ctrl1:
        type: {controller_type}
"""
    for i in range(num_disks):
        yaml_text += f"""
    disk{i}:
        type: hard_disk
        parent: ctrl1
        disk_capacity: 10
"""
    return yaml_text


def addresses_on(ovf, controller):
    items = as_list(ovf['Envelope']['VirtualSystem']['VirtualHardwareSection']['Item'])
    instance_id = next(i['rasd:InstanceID'] for i in items if i['rasd:ElementName'] == controller)
    return [int(i['rasd:AddressOnParent']) for i in items if i.get('rasd:Parent') == instance_id]


def test_scsi_unit_7_skipped():
    process, ovf = compose(controller_yaml("scsi_controller", 9))
    assert process.returncode == 0, process.stderr
    assert addresses_on(ovf, "ctrl1") == [0, 1, 2, 3, 4, 5, 6, 8, 9]


@pytest.mark.parametrize("controller_type,maximum", [("ide_controller", 2), ("sata_controller", 30)])
def test_controller_limits(controller_type, maximum):
    process, ovf = compose(controller_yaml(controller_type, maximum))
    assert process.returncode == 0, process.stderr
    assert addresses_on(ovf, "ctrl1") == list(range(maximum))

    process, _ = compose(controller_yaml(controller_type, maximum + 1))
    assert process.returncode != 0
    assert f"the maximum is {maximum}" in process.stderr


@pytest.mark.parametrize("subtype,system_type,maximum", [
    ("buslogic", "vmx-20", 15),
    ("lsilogic", "vmx-20", 15),
    ("lsilogicas", "vmx-20", 15),
    ("VirtualSCSI", "vmx-13", 15),
    ("VirtualSCSI", "vmx-14", 64),
    ("virtualscsi", "vmx-20", 64),
    (None, "vmx-20", 64),
    (None, "vmx-14 vmx-20", 64),
    (None, "vmx-13 vmx-20", 15),
    (None, "other-platform", 15),
])
def test_scsi_controller_limits(subtype, system_type, maximum):
    def config(num_disks):
        yaml_text = controller_yaml("scsi_controller", num_disks)
        yaml_text = yaml_text.replace("type: vmx-20", f"type: {system_type}")
        # Put the controller after its children to exercise order independence.
        controller = "    ctrl1:\n        type: scsi_controller\n"
        yaml_text = yaml_text.replace(controller, "") + controller
        if subtype is not None:
            yaml_text += f"        subtype: {subtype}\n"
        return yaml_text

    process, ovf = compose(config(maximum))
    assert process.returncode == 0, process.stderr
    assert addresses_on(ovf, "ctrl1") == [i for i in range(maximum + 1) if i != 7]

    process, _ = compose(config(maximum + 1))
    assert process.returncode != 0
    assert f"the maximum is {maximum}" in process.stderr


def test_sign_p7s_no_partial_files(rsa_key):
    """sign-p7s.sh does not leave partial signature files if signing fails"""
    with open(os.path.join(WORK_DIR, "partial.mf"), "w") as f:
        f.write("SHA256(partial.ovf)= 00\n")
    for name in ["partial.p7s", "partial.cert"]:
        if os.path.exists(os.path.join(WORK_DIR, name)):
            os.remove(os.path.join(WORK_DIR, name))

    # the second signer does not exist, so openssl cms fails
    process = subprocess.run([SIGN_P7S, "-a", "sha256", "-c", "partial.cert", "partial.mf", "partial.p7s",
                              rsa_key, "does-not-exist.pem"], cwd=WORK_DIR, capture_output=True, text=True)
    assert process.returncode != 0
    leftovers = [f for f in os.listdir(WORK_DIR) if f.startswith("partial.") and f != "partial.mf"]
    assert leftovers == []
