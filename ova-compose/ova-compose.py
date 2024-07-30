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
from lxml import etree as ET
import hashlib
import tempfile
import shutil

APP_NAME = "ova-compose"

VMDK_CONVERT = "vmdk-convert"

NS_CIM = "http://schemas.dmtf.org/wbem/wscim/1/common"
NS_OVF = "http://schemas.dmtf.org/ovf/envelope/1"
NS_RASD = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"
NS_VMW = "http://www.vmware.com/schema/ovf"
NS_VSSD = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

NS_MAP = {
    None: NS_OVF,
    "cim" : NS_CIM,
    "ovf" : NS_OVF,
    "rasd" : NS_RASD,
    "vmw" : NS_VMW,
    "vssd" : NS_VSSD,
    "xsi" : NS_XSI
}


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
    elem = ET.Element(tag)
    elem.text = value
    return elem


def xml_config(key, val):
    return ET.Element('{%s}Config' % NS_VMW, { '{%s}required' % NS_OVF: 'false', '{%s}key' % NS_VMW: key, '{%s}value' % NS_VMW: val})


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
        elem = ET.Element(tag)
        elem.text = value
        return elem


    def xml_element(self, tag, value):
        return self.new_text_element("{%s}%s" % (NS_VSSD, tag), str(value))


    def xml_item(self, element_name):
        attrs = {}
        item = ET.Element('{%s}System' % NS_OVF, attrs)
        
        item.append(self.xml_element('ElementName', element_name))
        item.append(self.xml_element('InstanceID', 0))
        item.append(self.xml_element('VirtualSystemIdentifier', self.identifier))
        item.append(self.xml_element('VirtualSystemType', self.type))

        return item


class RasdItem(VirtualHardware):
    last_instance_id = 0
    description = "Virtual Hardware Item"
    config = {}
    connectable = False
    configuration = None

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
        elem = ET.Element(tag)
        elem.text = value
        return elem


    def xml_element(self, tag, value):
        return self.new_text_element("{%s}%s" % (NS_RASD, tag), str(value))


    def xml_item(self, required, element_name):
        attrs = {}

        if not required:
            attrs["{%s}required" % NS_OVF] = 'false'
        if self.configuration:
            attrs["{%s}configuration" % NS_OVF] = self.configuration

        item = ET.Element('{%s}Item' % NS_OVF, attrs)
        
        item.append(self.xml_element('ResourceType', self.resource_type))
        item.append(self.xml_element('InstanceID', self.instance_id))
        item.append(self.xml_element('Description', self.description))
        item.append(self.xml_element('ElementName', element_name))

        for key, val in sorted(self.config.items()):
            item.append(xml_config(key, val))

        if self.connectable:
            item.append(self.xml_element('AutomaticAllocation', "true" if self.connected else "false"))

        return item


class RasdCpus(RasdItem):
    resource_type = 3
    description = "Virtual CPUs"


    def __init__(self, num):
        super().__init__()
        self.num = int(num)


    @classmethod
    def from_dict(cls, d):
        if type(d) is int:
            item = cls(d)
        else:
            item = cls(d['number'])
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
        self.size = int(size)


    @classmethod
    def from_dict(cls, d):
        if type(d) is int:
            item = cls(d)
        else:
            item = cls(d['size'])
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


class RasdNvmeController(RasdController):
    resource_type = 20
    description = "NVME Controller"


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', 'vmware.nvme.controller'))
        
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
    DEFAULT_CONFIG = {
        "connectable.allowGuestControl":"true"
    }
    connectable = True


    def __init__(self, parent_id, image, connected=False):
        super().__init__(parent_id)
        self.image = image
        self.config = self.DEFAULT_CONFIG.copy()
        self.connected = connected


    @classmethod
    def from_dict(cls, d):
        item = cls(d['parent'], d.get('image', None), d.get('connected', False))
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


class RasdUsb3Controller(RasdItem):
    resource_type = 23
    description = "USB3 Controller"


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', 'vmware.usb.xhci'))
        return item


class RasdVmci(RasdItem):
    resource_type = 1
    description = "VMCI"


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', 'vmware.vmci'))
        return item


class RasdFloppy(RasdItem):
    resource_type = 14
    description = "Floppy Drive"
    DEFAULT_CONFIG = {
        "connectable.allowGuestControl":"true"
    }
    connectable = True


    def __init__(self, image, connected=False):
        super().__init__()
        self.image = image
        self.config = self.DEFAULT_CONFIG.copy()
        self.connected = connected


    @classmethod
    def from_dict(cls, d):
        item = cls(d.get('image', None), d.get('connected', False))
        return item


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        if self.image is not None:
            item.append(self.xml_element('HostResource', self.image.host_resource()))

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
    connectable = True
    connected = False


    def __init__(self):
        super().__init__()
        self.config = RasdVideoCard.DEFAULT_CONFIG.copy()


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)

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
        "wakeOnLanEnabled":"false",
        "connectable.allowGuestControl":"true"
    }
    connectable = True


    def __init__(self, network_id, subtype, connected=True):
        super().__init__()
        self.config = RasdEthernet.DEFAULT_CONFIG.copy()
        self.network_id = network_id
        self.subtype = subtype
        self.connected = connected


    @classmethod
    def from_dict(cls, d):
        item = cls(d['network'], d['subtype'], d.get('connected', True))
        return item


    def connect(self, ovf):
        self.network = ovf.networks[self.network_id]


    def xml_item(self, required, element_name):
        item = super().xml_item(required, element_name)
        item.append(self.xml_element('ResourceSubType', self.subtype))
        item.append(self.xml_element('Connection', self.network.name))
        
        return item


class OVFNetwork(object):

    def __init__(self, name, description):
        self.name = name


    @classmethod
    def from_dict(cls, d):
        item = cls(d['name'], d['description'])
        return item


    def xml_item(self):
        item = ET.Element('{%s}Network' % NS_OVF, {'{%s}name' % NS_OVF : self.name})
        item_desc = ET.Element('{%s}Description' % NS_OVF)
        item_desc.text = f"The {self.name} Network"
        item.append(item_desc)
        
        return item


class OVFFile(object):
    next_id = 0

    def __init__(self, path, file_id=None):
        self.path = os.path.abspath(path)
        if file_id is None:
            self.id = f"file{OVFFile.next_id}"
            OVFFile.next_id += 1
        else:
            self.id = file_id
        self.size = os.path.getsize(self.path)


    def host_resource(self):
        return f"ovf:/file/{self.id}"


    def xml_item(self):
        return ET.Element('{%s}File' % NS_OVF, {
            '{%s}href' % NS_OVF: os.path.basename(self.path),
            '{%s}id' % NS_OVF: self.id,
            '{%s}size' % NS_OVF: str(self.size)
        })


class OVFDisk(object):
    next_id = 0

    allocation_units_map = {
            'byte' : "byte",
            'KB' : "byte * 2^10",
            'MB' : "byte * 2^20",
            'GB' : "byte * 2^30",
            'TB' : "byte * 2^40",
        }

    allocation_factors = {
            'byte' : 1,
            'byte * 2^10' : 2 ** 10,
            'byte * 2^20' : 2 ** 20,
            'byte * 2^30' : 2 ** 30,
            'byte * 2^40' : 2 ** 40,
    }

    def __init__(self, path, units=None, disk_id=None, file_id=None, raw_image=None):
        if disk_id is None:
            self.id = f"vmdisk{OVFDisk.next_id}"
            OVFDisk.next_id += 1
        else:
            self.id = disk_id

        # units can be unspecified (default: byte),
        # one of KB, MB, ...
        # or byte * 2^10, ... with exponents 10-40
        if units is None:
            units = "byte"
        elif units in self.allocation_units_map:
            units = self.allocation_units_map[units]
        elif units in self.allocation_factors:
            pass
        else:
            assert False, "invalid units used"
        self.units = units

        if raw_image is not None:
            if os.path.exists(raw_image):
                # check if the vmdk exists, and if it does if it's newer than the raw image
                # if not, create vmdk from raw image
                if not os.path.exists(path) or os.path.getctime(raw_image) > os.path.getctime(path):
                    subprocess.check_call([VMDK_CONVERT, raw_image, path])
            else:
                print(f"warning: raw image file {raw_image} does not exist, using {path}")

        self.file = OVFFile(path, file_id=file_id)
        disk_info = OVF._disk_info(path)
        self.capacity = int(disk_info['capacity'] / self.allocation_factors[self.units])
        self.used = disk_info['used']


    def host_resource(self):
        return f"ovf:/disk/{self.id}"


    def xml_item(self):
        return ET.Element('{%s}Disk' % NS_OVF, {
            '{%s}diskId' % NS_OVF: self.id,
            '{%s}capacity' % NS_OVF: str(self.capacity),
            '{%s}capacityAllocationUnits' % NS_OVF: self.units,
            '{%s}fileRef' % NS_OVF: self.file.id,
            '{%s}populatedSize' % NS_OVF: str(self.used),
            '{%s}format' % NS_OVF: 'http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized'
        })


class OVFEmptyDisk(OVFDisk):

    def __init__(self, capacity, units="MB", disk_id=None):
        if disk_id is None:
            self.id = f"vmdisk{OVFDisk.next_id}"
            OVFDisk.next_id += 1
        else:
            self.id = disk_id
        self.capacity = capacity
        if units in self.allocation_units_map:
            units = self.allocation_units_map[units]
        self.units = units


    def xml_item(self):
        return ET.Element('{%s}Disk' % NS_OVF, {
            '{%s}capacity' % NS_OVF: str(self.capacity),
            '{%s}capacityAllocationUnits' % NS_OVF: self.units,
            '{%s}diskId' % NS_OVF: self.id,
            '{%s}format' % NS_OVF: 'http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized'
        })


def to_camel_case(snake_str):
    return ''.join(x.title() for x in snake_str.split('_'))


class OVFProperty(object):

    def __init__(self, key, type,
                 password = False,
                 value=None,
                 user_configurable=False, qualifiers=None,
                 label=None, description=None, category=None):
        self.key = key
        self.type = type
        self.password = password
        self.value = value
        self.user_configurable = user_configurable
        self.qualifiers = qualifiers
        self.label = label
        self.description = description
        self.category = category


    @classmethod
    def from_dict(cls, key, type, d):
        item = cls(key, type, **d)
        return item


    def xml_item(self):
        xml_attrs = {
            '{%s}key' % NS_OVF: self.key,
            '{%s}type' % NS_OVF: self.type
        }
        if self.value is not None:
            xml_attrs['{%s}value' % NS_OVF] = str(self.value)
        if self.qualifiers is not None:
            xml_attrs['{%s}qualifiers' % NS_OVF] = self.qualifiers
        if self.user_configurable:
            xml_attrs['{%s}userConfigurable' % NS_OVF] = "true"
        if self.password:
            xml_attrs['{%s}password' % NS_OVF] = "true"
        xml_property = ET.Element('{%s}Property' % NS_OVF, xml_attrs)
        if self.label is not None:
            xml_property.append(xml_text_element('{%s}Label' % NS_OVF, self.label))
        if self.description is not None:
            xml_property.append(xml_text_element('{%s}Description' % NS_OVF, self.description))
        return xml_property


class OVFProduct(object):
    # snake case will be converted to camel case in XML
    keys = ['info', 'product', 'vendor', 'version', 'full_version']
    attr_keys = ['class', 'instance', 'required']

    def __init__(self, **kwargs):
        self.info = "Information about the installed software"
        self.__dict__.update((k, v) for k, v in kwargs.items() if k in self.keys)
        self.__dict__.update((k, v) for k, v in kwargs.items() if k in self.attr_keys)

        self.properties = []
        if 'properties' in kwargs:
            props = kwargs['properties']
            if props is not None:
                for k, v in props.items():
                    self.properties.append(OVFProperty(k, **v))

        self.transports = kwargs.get('transports', [])
        self.categories = kwargs.get('categories', {})

        # if a property references a non-existing category it will be dropped
        for prop in self.properties:
            assert prop.category is None or prop.category in self.categories,\
                f"property '{prop.key}' references unknown category '{prop.category}'"


    @classmethod
    def from_dict(cls, d):
        item = cls(**d)
        return item


    def xml_item(self):
        xml_attrs = {}
        for k in self.attr_keys:
            if hasattr(self, k) and getattr(self, k) is not None:
                xml_attrs['{%s}%s' % (NS_OVF, k)] = getattr(self, k)
        xml_product = ET.Element('{%s}ProductSection' % NS_OVF, xml_attrs)

        for k in self.keys:
            if hasattr(self, k) and getattr(self, k) is not None:
                xml_name = to_camel_case(k)
                xml_product.append(xml_text_element('{%s}%s' % (NS_OVF, xml_name), getattr(self, k)))

        # append category-less properties first
        for prop in self.properties:
            if prop.category is None:
                xml_product.append(prop.xml_item())
        # then go through all categories, and append matching props
        for cat_id, cat_name in self.categories.items():
            xml_product.append(xml_text_element('{%s}Category' % NS_OVF, cat_name))
            for prop in self.properties:
                if prop.category == cat_id:
                    xml_product.append(prop.xml_item())

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
        return ET.Element('{%s}%s' % (NS_OVF, self.xml_name))


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
        return ET.Element('{%s}%s' % (NS_OVF, self.xml_name), { '{%s}msgid' % NS_OVF: "eula"})


class OVFConfiguration(object):
    keys = ['label', 'description', 'default']

    def __init__(self, id, **kwargs):
        self.id = id
        self.default = False
        self.info = "Information about the installed software"
        self.__dict__.update((k, v) for k, v in kwargs.items() if k in self.keys)


    @classmethod
    def from_dict(cls, d):
        item = cls(**d)
        return item


    def xml_item(self):
        attrs = {'{%s}id' % NS_OVF: self.id}
        if self.default:
            attrs['{%s}default' % NS_OVF] = "true"
        elem = ET.Element('{%s}Configuration' % NS_OVF, attrs)
        elem.append(xml_text_element('{%s}%s' % (NS_OVF, 'Label'), getattr(self, 'label')))
        elem.append(xml_text_element('{%s}%s' % (NS_OVF, 'Description'), getattr(self, 'description')))
        return elem


class VmwExtraConfigItem(object):

    def __init__(self, key, value, required=None):
        self.key = key
        self.value = value
        self.required = required


    @classmethod
    def from_dict(cls, d):
        item = cls(**d)
        return item


    def xml_item(self):
        value = self.value
        if type(value) is bool:
            value = "true" if value else "false"
        elif type(value) is not str:
            value = str(value)

        attrs = {'{%s}key' % NS_VMW: self.key, '{%s}value' % NS_VMW: value}
        if self.required is not None:
            attrs['{%s}required' % NS_VMW] = "true" if self.required else "false"
        elem = ET.Element('{%s}ExtraConfig' % NS_VMW, attrs)
        return elem


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


    def __init__(self,
                 system, files, disks,
                 networks,
                 vssd_system, rasd_items, extra_configs,
                 products, annotation, eula,
                 configurations):
        self.hardware_config = {}
        if not system.get('no_default_configs', False):
            self.hardware_config.update(OVF.CONFIG_DEFAULTS)
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
        self.extra_configs = extra_configs
        self.products = products
        self.annotation = annotation
        self.eula = eula
        self.configurations = configurations

        if 'default_configuration' in system:
            dflt_cfg = system['default_configuration']
            self.configurations[dflt_cfg].default = True

        self.connect()


    @classmethod
    def from_dict(cls, config):

        # search for files and disks in hardware config:
        files = []
        disks = []
        product = None
        annotation = None
        eula = None

        assert 'hardware' in config, "config needs a 'hardware' section"

        hardware = config['hardware']
        for hw_id, hw in hardware.items():
            if isinstance(hw, dict):
                if 'image' in hw:
                    file = OVFFile(hw['image'],
                                   file_id=hw.get('file_id', None))
                    files.append(file)
                    hw['image'] = file
                elif 'disk_image' in hw or 'raw_image' in hw:
                    if 'disk_image' not in hw:
                        # if vmdk file is unset, use the raw image name and replace the extension
                        hw['disk_image'] = os.path.splitext(hw['raw_image'])[0] + ".vmdk"
                    disk = OVFDisk(hw['disk_image'],
                                   units=hw.get('units', None),
                                   raw_image=hw.get('raw_image', None),
                                   disk_id=hw.get('disk_id', None),
                                   file_id=hw.get('file_id', None))
                    disks.append(disk)
                    files.append(disk.file)
                    hw['disk'] = disk
                elif 'disk_capacity' in hw:
                    disk = OVFEmptyDisk(hw['disk_capacity'],
                                        disk_id=hw.get('disk_id', None))
                    disks.append(disk)
                    hw['disk'] = disk

        networks = {}
        if 'networks' in config:
            for nw_id, nw in config['networks'].items():
                network = OVFNetwork.from_dict(nw)
                networks[nw_id] = network

        vssd_system = VssdSystem.from_dict(config)
        rasd_items = cls.rasd_items_from_dict(config)
        extra_configs = cls.vmw_extra_config_items_from_dict(config)

        products = []
        assert not ('product' in config and 'product_sections' in config), "can only have one of 'product' or 'product_sections'"

        # we want properties in their own section ('environment')
        # but in OVF they are part of the ProductSection, so copy it
        if 'environment' in config:
            env = config['environment']
            if 'product' not in config:
                config['product'] = {}
            for cfg in ['transports', 'properties', 'categories']:
                if cfg in env:
                    config['product'][cfg] = env[cfg]

        if 'product' in config:
            product = OVFProduct.from_dict(config['product'])

        if product:
            products.append(product)

        if 'product_sections' in config:
            for p in config['product_sections']:
                products.append(OVFProduct.from_dict(p))

        if 'annotation' in config:
            annotation = OVFAnnotation.from_dict(config['annotation'])

        if 'eula' in config:
            eula = OVFEula.from_dict(config['eula'])

        configurations = {}
        if 'configurations' in config:
            for k, v in config['configurations'].items():
                configurations[k] = OVFConfiguration(k, **v)

        ovf = cls(config['system'], files, disks,
                  networks, vssd_system, rasd_items, extra_configs,
                  products, annotation, eula,
                  configurations)

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
                if type(hw_config) is dict:
                    rasd_item.configuration = hw_config.get('configuration', None)
                rasd_items[hw_id] = rasd_item
            except AttributeError:
                print(f"no class {cl_name}")
        return rasd_items


    @classmethod
    def vmw_extra_config_items_from_dict(cls, config):
        xtra_cfgs = []
        xconfigs = config.get('extra_configs', None)
        if xconfigs is None:
            return []
        for key, cfg in xconfigs.items():
            cfg['key'] = key
            xtra_cfg_item = VmwExtraConfigItem.from_dict(cfg)
            xtra_cfgs.append(xtra_cfg_item)
        return xtra_cfgs


    def connect(self):
        for hw_id, rasd_item in self.rasd_items.items():
            rasd_item.connect(self)


    @staticmethod
    def _disk_info(filename):
        out = subprocess.check_output([VMDK_CONVERT, "-i", filename]).decode("UTF-8")
        return json.loads(out)


    def to_xml(self):
        envelope = ET.Element('{%s}Envelope' % NS_OVF, nsmap=NS_MAP)

        # References (files)
        references = ET.Element('{%s}References' % NS_OVF)
        for file in self.files:
            references.append(file.xml_item())
        envelope.append(references)

        # DiskSection
        disk_section = ET.Element('{%s}DiskSection' % NS_OVF)
        disk_section.append(xml_text_element('{%s}Info' % NS_OVF, "Virtual disk information"))

        for disk in self.disks:
            disk_section.append(disk.xml_item())
        envelope.append(disk_section)

        if self.configurations:
            dos = ET.Element('{%s}DeploymentOptionSection' % NS_OVF)
            dos.append(xml_text_element('{%s}Info' % NS_OVF, "List of profiles"))
            for id, config in self.configurations.items():
                dos.append(config.xml_item())
            envelope.append(dos)

        # NetworkSection
        network_section = ET.Element('{%s}NetworkSection' % NS_OVF)
        network_section.append(xml_text_element('{%s}Info' % NS_OVF, "Virtual Networks"))
        for nw_id, nw in self.networks.items():
            network_section.append(nw.xml_item())        
        envelope.append(network_section)

        # VirtualSystem
        virtual_system = ET.Element('{%s}VirtualSystem' % NS_OVF, { '{%s}id' % NS_OVF: 'vm' })
        virtual_system.append(xml_text_element('{%s}Info' % NS_OVF, "Virtual System"))
        envelope.append(virtual_system)

        virtual_system.append(xml_text_element('{%s}Name' % NS_OVF, self.vssd_system.identifier))
        oss = ET.Element('{%s}OperatingSystemSection' % NS_OVF, { '{%s}id' % NS_OVF: str(self.os_cim), '{%s}osType' % NS_VMW: self.os_vmw })
        oss.append(xml_text_element('{%s}Info' % NS_OVF, "Operating System"))
        virtual_system.append(oss)

        hw_attrs = None
        if self.products:
            transports = []
            for p in self.products:
                if p.transports:
                    transports.extend(p.transports)
            transports = list(set(transports))
            hw_attrs = {'{%s}transport' % NS_OVF: " ".join(transports)}

        hw = ET.Element('{%s}VirtualHardwareSection' % NS_OVF, hw_attrs)

        hw.append(xml_text_element('{%s}Info' % NS_OVF, "Virtual Hardware"))
        virtual_system.append(hw)

        hw.append(self.vssd_system.xml_item("Virtual Hardware Family"))
        for hw_id, rasd_item in self.rasd_items.items():
            xml_item = rasd_item.xml_item(True, hw_id)
            # sort rasd elements by tag:
            xml_item[:] = sorted(xml_item, key=lambda child: child.tag)
            hw.append(xml_item)

        for xcfg in self.extra_configs:
            hw.append(xcfg.xml_item())

        for key, val in sorted(self.hardware_config.items()):
            hw.append(xml_config(key, val))

        if self.products:
            for p in self.products:
                virtual_system.append(p.xml_item())

        if self.annotation:
            virtual_system.append(self.annotation.xml_item())
        if self.eula:
            virtual_system.append(self.eula.xml_item())

        xml_indent(envelope)
        doc = ET.ElementTree(envelope)
        ET.cleanup_namespaces(doc)
        return doc


    def write_xml(self, ovf_file=None):
        if ovf_file == None:
            ovf_file = f"{self.name}.ovf"
        doc = self.to_xml()
        with open(ovf_file, "wb") as f:
            doc.write(f, pretty_print=True, exclusive=True, xml_declaration=True, encoding="UTF-8")

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
    def _get_hash(filename, hash_type, blocksz=1024 * 1024):
        hash = hashlib.new(hash_type)
        with open(filename, "rb") as f:
            while True:
                buf = f.read(blocksz)
                if not buf:
                    break
                hash.update(buf)
        return hash.hexdigest()


    def write_manifest(self, ovf_file=None, mf_file=None, hash_type="sha512"):
        if ovf_file == None:
            ovf_file = f"{self.name}.ovf"
        if mf_file == None:
            mf_file = f"{self.name}.mf"
        filenames = [ovf_file]

        for file in self.files:
            filenames.append(file.path)
        with open(mf_file, "wt") as f:
            for fname in filenames:
                hash = OVF._get_hash(fname, hash_type)
                fname = os.path.basename(fname)
                f.write(f"{hash_type.upper()}({fname})= {hash}\n")


    def sign_manifest(self, keyfile, ovf_file=None, mf_file=None, sign_alg="sha512"):
        if ovf_file == None:
            ovf_file = f"{self.name}.ovf"
        if mf_file == None:
            mf_file = f"{self.name}.mf"
        cert_file = os.path.splitext(ovf_file)[0] + ".cert"

        with open(cert_file, "wt") as f:
            signature = subprocess.check_output(["openssl", "dgst", f"-{sign_alg}", "-sign", keyfile, "-out", "-", mf_file])
            f.write(f"{sign_alg.upper()}({mf_file})= {signature.hex()}\n")

            with open(keyfile, "rt") as fin:
                do_copy = False
                for line in fin:
                    if (line.startswith("-----BEGIN CERTIFICATE")):
                        do_copy = True
                    if do_copy:
                        f.write(line)
                    if (line.startswith("-----END CERTIFICATE")):
                        break
                assert do_copy, f"no certificate found in {keyfile}"


def usage():
    print(f"Usage: {sys.argv[0]} -i|--input-file <input file> -o|--output-file <output file> [--format ova|ovf|dir] [-q] [-h]")
    print("")
    print("Options:")
    print("  -i, --input-file <file>     input file")
    print("  -o, --output-file <file>    output file or directory name")
    print("  -f, --format ova|ovf|dir    output format")
    print("  -m, --manifest              create manifest file along with ovf (default true for output formats ova and dir)")
    print("  --checksum-type sha1|sha256|sha512  set the checksum type for the manifest. Must be sha1, sha256 or sha512.")
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


def yaml_param(loader, node):
    params = loader.app_params
    default = None
    key = node.value

    assert type(key) is str, f"param name {key} must be a string"

    if '=' in key:
        key, default = [t.strip() for t in key.split('=', maxsplit=1)]
        default = yaml.safe_load(default)
    value = params.get(key, default)

    assert value is not None, f"no param set for '{key}', and there is no default"

    return value


def main():
    config_file = None
    output_file = None
    output_format = None
    basename = None
    do_quiet = False
    do_manifest = False
    params = {}
    checksum_type = "sha256"
    sign_keyfile = None
    sign_alg = None
    tar_format = "gnu"

    try:
        opts, args = getopt.getopt(sys.argv[1:],
            'f:hi:mo:q',
            longopts=['format=', 'input-file=', 'manifest', 'output-file=', 'param=', 'checksum-type=', 'sign=', 'sign-alg=', 'tar-format=', 'vmdk-convert='])
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
        elif o in ['-m', '--manifest']:
            do_manifest = True
        elif o in ['--checksum-type']:
            checksum_type = a
        elif o in ['--param']:
            k,v = a.split('=', maxsplit=1)
            params[k] = yaml.safe_load(v)
        elif o in ['--tar-format']:
            tar_format = a
        elif o in ['--vmdk-convert']:
            global VMDK_CONVERT
            VMDK_CONVERT = a
        elif o in ['-q']:
            do_quiet = True
        elif o in ['-s', '--sign']:
            sign_keyfile = a
        elif o in ['--sign-alg']:
            sign_alg = a
        elif o in ['-h']:
            usage()
            sys.exit(0)
        else:
            assert False, f"unhandled option {o}"

    assert config_file != None, "no input file specified"
    assert output_file != None, "no output file/directory specified"

    assert checksum_type in ["sha1", "sha512", "sha256"], f"checksum-type '{checksum_type}' is invalid"
    if sign_alg is None:
        sign_alg = checksum_type
    assert sign_alg in ["sha1", "sha512", "sha256"], f"checksum-type '{sign_alg}' is invalid"

    if sign_keyfile is not None:
        sign_keyfile = os.path.abspath(sign_keyfile)

    if config_file != None:
        f = open(config_file, 'r')

    yaml_loader = yaml.SafeLoader
    yaml_loader.app_params = params
    yaml.add_constructor("!param", yaml_param, Loader=yaml_loader)

    config = yaml.load(f, Loader=yaml_loader)
    if f != sys.stdin:
        f.close()

    ovf = OVF.from_dict(config)

    if output_format is None:
        if output_file.endswith(".ova"):
            # create an ova file
            output_format = "ova"
        elif output_file.endswith(".ovf"):
            # create just ovf (and maybe mf) file
            output_format = "ovf"

    assert output_format != None, "no output format specified"
    assert output_format in ['ova', 'ovf', 'dir'], f"invalid output_format '{output_format}'"

    if not do_quiet:
        print (f"creating '{output_file}' with format '{output_format}' from '{config_file}'")

    if output_format != "dir":
        basename = os.path.basename(output_file)[:-4]
    else:
        basename = os.path.basename(output_file)
    mf_file = f"{basename}.mf"

    if output_format == "ovf":
        ovf_file = output_file
        ovf.write_xml(ovf_file=ovf_file)
        if do_manifest:
            ovf.write_manifest(ovf_file=ovf_file, mf_file=mf_file, hash_type=checksum_type)
            if sign_keyfile is not None:
                ovf.sign_manifest(sign_keyfile, ovf_file=ovf_file, mf_file=mf_file, sign_alg=sign_alg)
    elif output_format == "ova" or output_format == "dir":
        pwd = os.getcwd()
        tmpdir = tempfile.mkdtemp(prefix=f"{basename}-", dir=pwd)
        try:
            os.chdir(tmpdir)
            ovf_file = f"{basename}.ovf"
            ovf.write_xml(ovf_file=ovf_file)

            all_files = [ovf_file, mf_file]
            for file in ovf.files:
                dst = os.path.basename(file.path)
                os.symlink(os.path.join(pwd, file.path), dst)
                all_files.append(dst)

            ovf.write_manifest(ovf_file=ovf_file, mf_file=mf_file, hash_type=checksum_type)
            if sign_keyfile is not None:
                ovf.sign_manifest(sign_keyfile, ovf_file=ovf_file, mf_file=mf_file, sign_alg=sign_alg)
                cert_file = os.path.splitext(ovf_file)[0] + ".cert"
                all_files.append(cert_file)

            if output_format == "ova":
                ret = subprocess.check_call(["tar", f"--format={tar_format}", "-h",
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
