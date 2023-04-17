#!/usr/bin/env python3

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

import sys
import os
import subprocess
import getopt
import datetime
import yaml
import json
import xml.etree.ElementTree
import hashlib
import tempfile
import shutil


APP_NAME = "ova-compose"

NS_CIM = "http://schemas.dmtf.org/wbem/wscim/1/common"
NS_OVF = "http://schemas.dmtf.org/ovf/envelope/1"
NS_RASD = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"
NS_VMW = "http://www.vmware.com/schema/ovf"
NS_VSSD = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def xml_indent(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            xml_indent(elem, level+1)
    if not elem.tail or not elem.tail.strip():
        elem.tail = i


def xml_text_element(tag, value):
    elem = xml.etree.ElementTree.Element(tag)
    elem.text = value
    return elem


def xml_config(key, val):
    return xml.etree.ElementTree.Element('{%s}Config' % NS_VMW, { '{%s}required' % NS_OVF: 'false', '{%s}key' % NS_VMW: key, '{%s}value' % NS_VMW: val})


class ValidationError(Exception):
    pass


class VirtualHardware(object):
    pass


class VssdSystem(VirtualHardware):

    def __init__(self, identifier, type):
        self.identifier = identifier
        self.type = type


    @classmethod
    def from_dict(cls, d):
        system = d['system']
        return cls(system['name'], system['type'])


    def new_text_element(self, tag, value):
        elem = xml.etree.ElementTree.Element(tag)
        elem.text = value
        return elem


    def xml_element(self, tag, value):
        return self.new_text_element("{%s}%s" % (NS_VSSD, tag), str(value))


    def xml_item(self, element_name):
        attrs = {}
        item = xml.etree.ElementTree.Element('{%s}System' % NS_OVF, attrs)
        
        item.append(self.xml_element('ElementName', element_name))
        item.append(self.xml_element('InstanceID', 0))
        item.append(self.xml_element('VirtualSystemIdentifier', self.identifier))
        item.append(self.xml_element('VirtualSystemType', self.type))

        return item


class RasdItem(VirtualHardware):
    last_instance_id = 0
    description = "Virtual Hardware Item"

    def __init__(self, subtype=None):
        RasdItem.last_instance_id += 1
        self.instance_id = RasdItem.last_instance_id


    @classmethod
    def from_dict(cls, d):
        return cls()


    def connect(self, ovf):
        pass


    def xml_references(self):
        return None


    def xml_disks(self):
        return None


    def new_text_element(self, tag, value):
        elem = xml.etree.ElementTree.Element(tag)
        elem.text = value
        return elem


    def xml_element(self, tag, value):
        return self.new_text_element("{%s}%s" % (NS_RASD, tag), str(value))


    def xml_item(self, required, element_name):
        attrs = {}

        if not required:
            attrs["{%s}required" % NS_OVF] = 'false'

        item = xml.etree.ElementTree.Element('{%s}Item' % NS_OVF, attrs)
        
        item.append(self.xml_element('ResourceType', self.resource_type))
        item.append(self.xml_element('InstanceID', self.instance_id))
        item.append(self.xml_element('Description', self.description))
        item.append(self.xml_element('ElementName', element_name))

        return item


class RasdCpus(RasdItem):
    resource_type = 3
    description = "Virtual CPUs"


    def __init__(self, num):
        super().__init__()
        self.num = num

    @classmethod
    def from_dict(cls, d):
        item = cls(d)
        return item


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('AllocationUnits', 'hertz * 10^6'))
        item.append(self.xml_element('VirtualQuantity', self.num))
        
        return item


class RasdMemory(RasdItem):
    resource_type = 4
    description = "Virtual Memory"


    def __init__(self, size):
        super().__init__()
        self.size = size


    @classmethod
    def from_dict(cls, d):
        item = cls(d)
        return item


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('AllocationUnits', 'byte * 2^20'))
        item.append(self.xml_element('VirtualQuantity', self.size))
        
        return item


class RasdController(RasdItem):

    def __init__(self, subtype):
        super().__init__()
        self.next_child_address = 0
        self.subtype = subtype


    @classmethod
    def from_dict(cls, d):
        item = cls(d.get('subtype', None))
        subtype = d.get('subtype', None)
        return item


    def add_child(self, child):
        child.address_on_parent = self.next_child_address
        self.next_child_address += 1


class RasdScsiController(RasdController):
    resource_type = 6
    description = "SCSI Controller"


    def __init__(self, subtype):
        super().__init__(subtype)
        self.next_child_address = 0
        # TODO: maintain valid settings in a structure instead of code:
        if self.subtype is None:
            self.subtype = 'VirtualSCSI'
        elif self.subtype.lower() in ['virtualscsi', 'lsilogic']:
            self.subtype = subtype
        else:
            raise Exception(f"invalid SCSI subtype '{self.subtype}'")


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', self.subtype))
        
        return item


class RasdSataController(RasdController):
    resource_type = 20
    description = "SATA Controller"

    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', 'vmware.sata.ahci'))
        
        return item


class RasdIdeController(RasdController):
    resource_type = 5
    description = "IDE Controller"


class RasdControllerItem(RasdItem):

    def __init__(self, parent_id):
        super().__init__()
        self.parent_id = parent_id
        self.rasd_parent = None


    @classmethod
    def from_dict(cls, d):
        item = cls(d['parent'])
        return item


    def connect(self, ovf):
        self.rasd_parent = ovf.rasd_items[self.parent_id]
        self.rasd_parent.add_child(self)


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('Parent', self.rasd_parent.instance_id))
        item.append(self.xml_element('AddressOnParent', self.address_on_parent))

        return item


class RasdCdDrive(RasdControllerItem):
    resource_type = 15
    description = "CD Drive"

    def __init__(self, parent_id, image):
        super().__init__(parent_id)
        self.image = image


    @classmethod
    def from_dict(cls, d):
        item = cls(d['parent'], d.get('image', None))
        return item


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', 'vmware.cdrom.remotepassthrough'))
        if self.image is not None:
            item.append(self.xml_element('HostResource', self.image.host_resource()))

        return item


class RasdUsbController(RasdItem):
    resource_type = 23
    description = "USB Controller"


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', 'vmware.usb.ehci'))
        item.append(xml_config('ehciEnabled', 'true'))
        return item


class RasdVmci(RasdItem):
    resource_type = 1
    description = "VMCI"


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', 'vmware.vmci'))
        return item


class RasdVideoCard(RasdItem):
    resource_type = 24
    description = "Video Card"
    DEFAULT_CONFIG = {
        "useAutoDetect" : "false",
        "videoRamSizeInKB" : "4096",
        "enable3DSupport" : "false",
        "use3dRenderer" : "automatic"
    }


    def __init__(self):
        super().__init__()
        self.config = RasdVideoCard.DEFAULT_CONFIG.copy()


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        # maybe move to parent class:
        for key, val in sorted(self.config.items()):
            item.append(xml_config(key, val))
        return item


class RasdHardDisk(RasdControllerItem):
    resource_type = 17
    description = "Hard Disk"


    def __init__(self, parent_id, disk):
        super().__init__(parent_id)
        self.disk = disk


    @classmethod
    def from_dict(cls, d):
        item = cls(d['parent'], d['disk'])
        return item


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('HostResource', self.disk.host_resource()))

        return item


class RasdEthernet(RasdItem):
    resource_type = 10
    description = "Ethernet Adapter"
    DEFAULT_CONFIG = {
        "wakeOnLanEnabled":"true",
        "connectable.allowGuestControl":"true"
    }

    def __init__(self, network_id, subtype):
        super().__init__()
        self.config = RasdEthernet.DEFAULT_CONFIG.copy()
        self.network_id = network_id
        self.subtype = subtype


    @classmethod
    def from_dict(cls, d):
        item = cls(d['network'], d['subtype'])
        return item


    def connect(self, ovf):
        self.network = ovf.networks[self.network_id]


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', self.subtype))
        item.append(self.xml_element('Connection', self.network.name))
        # maybe move to parent class:
        for key, val in sorted(self.config.items()):
            item.append(xml_config(key, val))
        
        return item


class OVFNetwork(object):

    def __init__(self, name, description):
        self.name = name


    @classmethod
    def from_dict(cls, d):
        item = cls(d['name'], d['description'])
        return item


    def xml_item(self):
        item = xml.etree.ElementTree.Element('{%s}Network' % NS_OVF, {'{%s}name' % NS_OVF : self.name})
        item_desc = xml.etree.ElementTree.Element('{%s}Description' % NS_OVF)
        item_desc.text = f"The {self.name} Network"
        item.append(item_desc)
        
        return item


class OVFFile(object):

    next_id = 0

    def __init__(self, path):
        self.id = f"file{OVFFile.next_id}"
        OVFFile.next_id += 1
        self.path = os.path.abspath(path)
        self.size = os.path.getsize(self.path)


    def host_resource(self):
        return f"ovf:/file/{self.id}"


    def xml_item(self):
        return xml.etree.ElementTree.Element('{%s}File' % NS_OVF, {
            '{%s}href' % NS_OVF: os.path.basename(self.path),
            '{%s}id' % NS_OVF: self.id,
            '{%s}size' % NS_OVF: str(self.size)
        })


class OVFDisk(object):

    next_id = 0

    def __init__(self, path):
        self.id = f"vmdisk{OVFFile.next_id}"
        OVFDisk.next_id += 1
        self.file = OVFFile(path)

        disk_info = OVF._disk_info(path)
        self.capacity = disk_info['capacity']
        self.used = disk_info['used']


    def host_resource(self):
        return f"ovf:/disk/{self.id}"


    def xml_item(self):
        return xml.etree.ElementTree.Element('{%s}Disk' % NS_OVF, {
            '{%s}capacity' % NS_OVF: str(self.capacity),
            '{%s}capacityAllocationUnits' % NS_OVF: 'byte',
            '{%s}diskId' % NS_OVF: self.id,
            '{%s}fileRef' % NS_OVF: self.file.id,
            '{%s}populatedSize' % NS_OVF: str(self.used),
            '{%s}format' % NS_OVF: 'http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized'
        })


def to_camel_case(snake_str):
    return ''.join(x.title() for x in snake_str.split('_'))


class OVFProduct(object):

    # snake case will be converted to camel case in XML
    keys = ['info', 'product', 'vendor', 'version', 'full_version']

    def __init__(self, **kwargs):
        self.info = "Information about the installed software"
        self.__dict__.update((k, v) for k, v in kwargs.items() if k in self.keys)


    @classmethod
    def from_dict(cls, d):
        item = cls(**d)
        return item


    def xml_item(self):
        xml_product = xml.etree.ElementTree.Element('{%s}ProductSection' % NS_OVF)

        for k in self.keys:
            if hasattr(self, k) and getattr(self, k) is not None:
                xml_name = to_camel_case(k)
                xml_product.append(xml_text_element('{%s}%s' % (NS_OVF, xml_name), getattr(self, k)))
        return xml_product


# abstract base class for OVFAnnotation and OVFEula
class OVFTextBlock(object):

    # snake case will be converted to camel case in XML
    keys = ['info', 'text', 'file']
    info_text = ""
    xml_name = "TextBlock"
    xml_text_name = "TextBlock"


    def __init__(self, **kwargs):
        self.info = "Information about the installed software"
        self.__dict__.update((k, v) for k, v in kwargs.items() if k in self.keys)
        if hasattr(self, 'file'):
            file_name = self.file
            with open(file_name, 'rt') as f:
                self.text = f.read()
                self.file = None


    @classmethod
    def from_dict(cls, d):
        item = cls(**d)
        return item


    def _xml_element(self):
        return xml.etree.ElementTree.Element('{%s}%s' % (NS_OVF, self.xml_name))


    def xml_item(self):
        item = self._xml_element()
        for k in self.keys:
            if hasattr(self, k):
                if k == 'text':
                    xml_name = self.xml_text_name
                    item.append(xml_text_element('{%s}%s' % (NS_OVF, xml_name), getattr(self, k)))
                elif getattr(self, k) is not None:
                    xml_name = to_camel_case(k)
                    item.append(xml_text_element('{%s}%s' % (NS_OVF, xml_name), getattr(self, k)))
        return item


class OVFAnnotation(OVFTextBlock):
    info = "Description of the Product"
    xml_name = "AnnotationSection"
    xml_text_name = "Annotation"


class OVFEula(OVFTextBlock):
    info = "End User License Agreement"
    xml_name = "EulaSection"
    xml_text_name = "License"


    def _xml_element(self):
        return xml.etree.ElementTree.Element('{%s}%s' % (NS_OVF, self.xml_name), { '{%s}msgid' % NS_OVF: "eula"})


class OVF(object):

    CONFIG_DEFAULTS = {
        "cpuHotAddEnabled": "false",
        "cpuHotRemoveEnabled": "false",
        "memoryHotAddEnabled": "false",
        "firmware": "bios",
        "tools.syncTimeWithHost": "false",
        "tools.afterPowerOn": "true",
        "tools.afterResume": "true",
        "tools.beforeGuestShutdown": "true",
        "tools.beforeGuestStandby": "true",
        "tools.toolsUpgradePolicy": "manual",
        "powerOpInfo.powerOffType": "soft",
        "powerOpInfo.resetType": "soft",
        "powerOpInfo.suspendType": "hard",
        "nestedHVEnabled": "false",
        "virtualICH7MPresent": "false",
        "virtualSMCPresent": "false",
        "flags.vvtdEnabled": "false",
        "flags.vbsEnabled": "false",
        "bootOptions.efiSecureBootEnabled": "false",
        "powerOpInfo.standbyAction": "checkpoint"
    }


    def __init__(self, system, files, disks, networks, vssd_system, rasd_items, product, annotation, eula):
        self.hardware_config = OVF.CONFIG_DEFAULTS.copy()
        self.name = system['name']
        self.os_cim = system.get('os_cim', 100)
        self.os_vmw = system.get('os_vmw', "other4xLinux64Guest")
        if 'firmware' in system:
            if system['firmware'] not in ['bios','efi']:
                raise ValidationError("os.firmware must be 'bios' or 'efi'")
            self.hardware_config['firmware'] = system['firmware']
        if 'secure_boot' in system:
            if type(system['secure_boot']) is not bool:
                raise ValidationError("os.secure_boot must be boolean")
            self.hardware_config['bootOptions.efiSecureBootEnabled'] = "true" if system['secure_boot'] else "false"
        self.files = files
        self.disks = disks
        self.networks = networks
        self.vssd_system = vssd_system
        self.rasd_items = rasd_items
        self.product = product
        self.annotation = annotation
        self.eula = eula
        self.connect()


    @classmethod
    def from_dict(cls, config):

        # search for files and disks in hardware config:
        files = []
        disks = []
        product = None
        annotation = None
        hardware = config['hardware']
        for hw_id, hw in hardware.items():
            if isinstance(hw, dict):
                if 'iso_image' in hw:
                    file = OVFFile(hw['iso_image'])
                    files.append(file)
                    hw['image'] = file
                elif 'disk_image' in hw:
                    disk = OVFDisk(hw['disk_image'])
                    disks.append(disk)
                    files.append(disk.file)
                    hw['disk'] = disk

        networks = {}
        for nw_id, nw in config['networks'].items():
            network = OVFNetwork.from_dict(nw)
            networks[nw_id] = network

        vssd_system = VssdSystem.from_dict(config)
        rasd_items = cls.rasd_items_from_dict(config)
        if 'product' in config:
            product = OVFProduct.from_dict(config['product'])
        if 'annotation' in config:
            annotation = OVFAnnotation.from_dict(config['annotation'])
        if 'eula' in config:
            eula = OVFEula.from_dict(config['eula'])

        ovf = cls(config['system'], files, disks, networks, vssd_system, rasd_items, product, annotation, eula)

        return ovf


    @classmethod
    def rasd_items_from_dict(cls, config):
        rasd_items = {}
        hardware = config['hardware']
        for hw_id, hw_config in hardware.items():
            if hw_id == 'memory':
                cl_name = "RasdMemory"
            elif hw_id == 'cpus':
                cl_name = "RasdCpus"
            else:
                hw_type = hw_config['type']
                cl_name = "Rasd" + hw_type.title().replace("_", "")
            try:
                cl = getattr(sys.modules[__name__], cl_name)
                rasd_item = cl.from_dict(hw_config)
                rasd_items[hw_id] = rasd_item
            except AttributeError:
                print(f"no class {cl_name}")
        return rasd_items


    def connect(self):
        for hw_id, rasd_item in self.rasd_items.items():
            rasd_item.connect(self)


    @staticmethod
    def _disk_info(filename):
        out = subprocess.check_output(["vmdk-convert", "-i", filename]).decode("UTF-8")
        return json.loads(out)


    def to_xml(self):
        xml.etree.ElementTree.register_namespace("cim", NS_CIM)
        xml.etree.ElementTree.register_namespace("ovf", NS_OVF)
        xml.etree.ElementTree.register_namespace("rasd", NS_RASD)
        xml.etree.ElementTree.register_namespace("vmw", NS_VMW)
        xml.etree.ElementTree.register_namespace("vssd", NS_VSSD)
        xml.etree.ElementTree.register_namespace("xsi", NS_XSI)

        envelope = xml.etree.ElementTree.Element('{%s}Envelope' % NS_OVF)

        # References (files)
        references = xml.etree.ElementTree.Element('{%s}References' % NS_OVF)
        for file in self.files:
            references.append(file.xml_item())
        envelope.append(references)

        # DiskSection
        disk_section = xml.etree.ElementTree.Element('{%s}DiskSection' % NS_OVF)
        disk_section.append(xml_text_element('{%s}Info' % NS_OVF, "Virtual disk information"))

        for disk in self.disks:
            disk_section.append(disk.xml_item())
        envelope.append(disk_section)

        # NetworkSection
        network_section = xml.etree.ElementTree.Element('{%s}NetworkSection' % NS_OVF)
        network_section.append(xml_text_element('{%s}Info' % NS_OVF, "Virtual Networks"))
        for nw_id, nw in self.networks.items():
            network_section.append(nw.xml_item())        
        envelope.append(network_section)

        # VirtualSystem
        virtual_system = xml.etree.ElementTree.Element('{%s}VirtualSystem' % NS_OVF, { '{%s}id' % NS_OVF: 'vm' })
        virtual_system.append(xml_text_element('{%s}Info' % NS_OVF, "Virtual System"))
        envelope.append(virtual_system)

        virtual_system.append(xml_text_element('{%s}Name' % NS_OVF, self.vssd_system.identifier))
        oss = xml.etree.ElementTree.Element('{%s}OperatingSystemSection' % NS_OVF, { '{%s}id' % NS_OVF: str(self.os_cim), '{%s}osType' % NS_VMW: self.os_vmw })
        oss.append(xml_text_element('{%s}Info' % NS_OVF, "Operating System"))
        virtual_system.append(oss)

        hw = xml.etree.ElementTree.Element('{%s}VirtualHardwareSection' % NS_OVF)
        hw.append(xml_text_element('{%s}Info' % NS_OVF, "Virtual Hardware"))
        virtual_system.append(hw)

        hw.append(self.vssd_system.xml_item("Virtual Hardware Family"))
        for hw_id, rasd_item in self.rasd_items.items():
            xml_item = rasd_item.xml_item(True, hw_id)
            # sort rasd elements by tag:
            xml_item[:] = sorted(xml_item, key=lambda child: child.tag)
            hw.append(xml_item)

        for key, val in sorted(self.hardware_config.items()):
            hw.append(xml_config(key, val))

        if self.product:
            virtual_system.append(self.product.xml_item())
        if self.annotation:
            virtual_system.append(self.annotation.xml_item())
        if self.eula:
            virtual_system.append(self.eula.xml_item())

        xml_indent(envelope)
        doc = xml.etree.ElementTree.ElementTree(envelope)
        return doc


    def write_xml(self, ovf_file=None):
        if ovf_file == None:
            ovf_file = f"{self.name}.ovf"
        doc = self.to_xml()
        with open(ovf_file, "wt") as f:
            doc.write(f, "unicode", True, "http://schemas.dmtf.org/ovf/envelope/1", "xml")

        # if you know an easier way to produce a time stamp with the local tz, please fix:
        timestamp = datetime.datetime.now(
            datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo).strftime("%d-%m-%Y %H:%M:%S %z")

        # ugly hack to insert a comment (there should be a better way)
        with open(ovf_file, "rt") as f:
            with open(f"{ovf_file}.tmp", "wt") as fout:
                line = f.readline()
                fout.write(line)
                fout.write(f"<!-- Generated by {APP_NAME} {timestamp} -->\n")
                for line in f.readlines():
                    fout.write(line)
        os.rename(f"{ovf_file}.tmp", ovf_file)


    @staticmethod
    def _get_sha512(filename):
        with open(filename, "rb") as f:
            hash = hashlib.sha512(f.read()).hexdigest();
        return hash


    def write_manifest(self, ovf_file=None, mf_file=None):
        if ovf_file == None:
            ovf_file = f"{self.name}.ovf"
        if mf_file == None:
            mf_file = f"{self.name}.mf"
        filenames = [ovf_file]

        for file in self.files:
            filenames.append(file.path)
        with open(mf_file, "wt") as f:
            for fname in filenames:
                hash = OVF._get_sha512(fname)
                fname = os.path.basename(fname)
                f.write(f"SHA512({fname})= {hash}\n")


def usage():
    print(f"Usage: {sys.argv[0]} -i|--input-file <input file> -o|--output-file <output file> [--format ova|ovf|dir] [-q] [-h]")
    print("")
    print("Options:")
    print("  -i, --input-file <file>     input file")
    print("  -o, --output-file <file>    output file or directory name")
    print("  -f, --format ova|ovf|dir    output format")
    print("  -q                          quiet mode")
    print("  -h                          print help")
    print("")
    print("Output formats:")
    print("  ova: create an OVA file")
    print("  ovf: create OVF file only")
    print("  dir: create a directory with the OVF file, the manifest and symlinks to the referenced files (hard disk(s) and iso image(s))")
    print("")
    print("Specifying the format is optional if the output file name ends with '.ovf' or '.ova'")
    print("")
    print("Example usage:")
    print(f"  {sys.argv[0]} -i photon.yaml -o photon.ova")


def main():
    config_file = None
    output_file = None
    output_format = None
    basename = None
    do_quiet = False

    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hi:o:q', longopts=['format=', 'input-file=', 'output-file='])
    except:
        print ("invalid option")
        sys.exit(2)

    for o, a in opts:
        if o in ['-i', '--input-file']:
            config_file = a
        elif o in ['-o', '--output-file']:
            output_file = a
        elif o in ['-f', '--format']:
            output_format = a
        elif o in ['-q']:
            do_quiet = True
        elif o in ['-h']:
            usage()
            sys.exit(0)
        else:
            assert False, f"unhandled option {o}"

    assert config_file != None, "no input file specified"
    assert output_file != None, "no output file/directory specified"

    if config_file != None:
        f = open(config_file, 'r')

    config = yaml.load(f, Loader=yaml.Loader)
    if f != sys.stdin:
        f.close()

    ovf = OVF.from_dict(config)

    if output_format is None:
        if output_file.endswith(".ova"):
            # create an ova file
            output_format = "ova"
        elif output_file.endswith(".ovf"):
            # create just the ovf file
            output_format = "ovf"

    assert output_format != None, "no output format specified"
    assert output_format in ['ova', 'ovf', 'dir'], f"invalid ouput_format '{output_format}'"

    if not do_quiet:
        print (f"creating '{output_file}' with format '{output_format}' from '{config_file}'")

    if output_format == "ovf":
        ovf_file = output_file
        ovf.write_xml(ovf_file=ovf_file)
    elif output_format == "ova" or output_format == "dir":
        if output_format == "ova":
            basename = os.path.basename(output_file)[:-4]
        else:
            basename = os.path.basename(output_file)
        pwd = os.getcwd()
        tmpdir = tempfile.mkdtemp(prefix=f"{basename}-", dir=pwd)
        try:
            os.chdir(tmpdir)
            ovf_file = f"{basename}.ovf"
            ovf.write_xml(ovf_file=ovf_file)
            mf_file = f"{basename}.mf"

            all_files = [ovf_file, mf_file]
            for file in ovf.files:
                dst = os.path.basename(file.path)
                os.symlink(os.path.join(pwd, file.path), dst)
                all_files.append(dst)

            ovf.write_manifest(ovf_file=ovf_file, mf_file=mf_file)

            if output_format == "ova":
                ret = subprocess.check_call(["tar", "--format=ustar", "-h",
                                             "--owner=0", "--group=0", "--mode=0644",
                                             "-cf",
                                             os.path.join(pwd, output_file)] + all_files)
                os.chdir(pwd)
                shutil.rmtree(tmpdir)
            else:
                os.chdir(pwd)
                shutil.move(tmpdir, output_file)
        except Exception as e:
            os.chdir(pwd)
            if os.path.isdir(tmpdir):
                shutil.rmtree(tmpdir)
            raise e

    if not do_quiet:
        print ("done.")


if __name__ == "__main__":
    main()
