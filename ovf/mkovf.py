#! /usr/bin/python3

# Copyright (c) 2014-2021 VMware, Inc.  All Rights Reserved.
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

import json
import os.path
import subprocess
import sys
import xml.etree.ElementTree

class VMConfig:
    def __init__(self, dirname):
        self.dirname = dirname
        self.config = dict()

    def getString(self, default, name):
        return self.config.get(name.lower(), default)

    def get(self, name):
        return self.getString(None, name)

    def getBool(self, default, name):
        v = self.get(name)
        if v is not None:
            v = v.lower()
            if v in ["", "t", "true", "y", "yes", "on", "1"]:
                return True
            if v in ["f", "false", "n", "no", "off", "0"]:
                return False
        return default

    def getInt(self, default, name):
        v = self.get(name)
        if v is not None:
           try:
              return int(v)
           except:
              pass
        return default

    def dump(self):
        for k, v in self.config.items():
            print("%s => %s" % (k, v))

    def getPath(self, path):
        if os.path.isabs(path):
            return path
        return os.path.join(self.dirname, path)


def unescape(value):
    ret = bytearray()
    state = None
    for c in bytearray(value, 'utf-8'):
        if state is None:
            if c == ord('|'):
                state = bytearray()
            else:
                ret.append(c)
            continue
        state.append(c)
        if c not in b"0123456789ABCDEFabcdef":
            ret += "|"
            ret += state
            state = None
            continue
        if len(state) < 2:
            continue
        ret.append(int(state, 16))
        state = None
    if state is not None:
        ret.append(ord('|'))
        ret += state
    return ret.decode("utf-8")

def parseLine(line):
    name = ''
    value = ''
    state = 0
    for c in line:
        if state == 0:
            if c in [' ', '\t']:
                continue
            state = 1
        if state == 1:
            if c not in [' ', '\t', '#', '=', '\n', '\r']:
                name += c
                continue
            if not name:
                return None
            state = 2
        if state == 2:
            if c in [' ', '\t']:
                continue
            if c not in ['=']:
                return None
            state = 4
            continue
        if state == 4:
            if c in [' ', '\t']:
                continue
            if c == '"':
                state = 105
                continue
            else:
                state = 5
        if state == 5:
            if c not in [' ', '\t', '#', '\n', '\r']:
                value += c
                continue
            state = 6
        if state == 6:
            if c in [' ', '\t']:
                continue
            if c not in ['#', '\r', '\n']:
                return None
            state = 7
            break
        if state == 105:
            if c != '"':
                value += c
                continue
            state = 6
            continue
        return None
    # State will be 4 for 'xxx = '
    # State will be 5 for 'xxx = yyy'
    # State will be 6 for 'xxx = yyy '
    # State will be 7 for 'xxx = yyy #'
    if state not in [ 4, 5, 6, 7 ]:
        return None
    return [ name, unescape(value) ]

def parseConfig(dirname, f):
	vmc = VMConfig(dirname)
	for line in f.readlines():
		r = parseLine(line)
		if r is not None:
			vmc.config[r[0].lower()] = r[1]
	return vmc

class Disks:
    def __init__(self, vmc):
        self.vmc = vmc
        self.disks = dict()
        self.getDisks()

    def dump(self):
        for k, v in self.disks.items():
            print("%s => %s" % (k, v))

    def getDisksDisk(self, device):
        if self.vmc.getBool(False, "%s.present" % device):
            self.disks[device] = [ self.vmc.get("%s.fileName" % device), None, None, None ]

    def getDisksAdapter(self, adapter, maxDevice):
        if self.vmc.getBool(False, "%s.present" % adapter):
            for i in range(0, maxDevice):
                self.getDisksDisk("%s:%u" % (adapter, i))

    def getDisksAdapters(self, adapter, maxAdapter, maxDevice):
        for i in range(0, maxAdapter):
            self.getDisksAdapter("%s%u" % (adapter, i), maxDevice)

    def getDisks(self):
        self.getDisksAdapters("scsi", 4, 256)
        self.getDisksAdapters("ide", 2, 2)
        self.getDisksAdapters("sata", 4, 30)


'''
static int
writeXML(FILE *f,
         const char *v)
{
	const char *p = v;
	int c;

	while ((c = *v) != 0) {
		const char *spec;

		switch (c) {
		case '&': spec = "&amp;"; break;
		case '"': spec = "&quot;"; break;
		case '\'': spec = "&apos;"; break;
		case '<': spec = "&lt;"; break;
		case '>': spec = "&gt;"; break;
		default: spec = NULL; break;
		}
		if (spec) {
			if (p != v) {
				if (fwrite(p, 1, v - p, f) != v - p) {
					return -1;
				}
				p = v + 1;
			}
			if (fwrite(spec, 1, strlen(spec), f) != strlen(spec)) {
				return -1;
			}
		}
		v++;
	}
	if (p != v) {
		if (fwrite(p, 1, v - p, f) != v - p) {
			return -1;
		}
	}
	return 0;
}
'''

NS_CIM = "http://schemas.dmtf.org/wbem/wscim/1/common"
NS_OVF = "http://schemas.dmtf.org/ovf/envelope/1"
NS_RASD = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"
NS_VMW = "http://www.vmware.com/schema/ovf"
NS_VSSD = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

def indent(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level+1)
    if not elem.tail or not elem.tail.strip():
        elem.tail = i

def newTextElement(tag, value):
    elem = xml.etree.ElementTree.Element(tag)
    elem.text = value
    return elem

def rasdElement(item, tag, value):
    item.append(newTextElement("{%s}%s" % (NS_RASD, tag), str(value)))

def addConfigVal(vmc, hw, ovfKey, val):
    if val is not None:
        el = xml.etree.ElementTree.Element('{%s}Config' % NS_VMW, { '{%s}required' % NS_OVF: 'false', '{%s}key' % NS_VMW: ovfKey, '{%s}value' % NS_VMW: val})
        hw.append(el)

def addConfig(vmc, hw, ovfKey, vmxKey):
    addConfigVal(vmc, hw, ovfKey, vmc.getString(None, vmxKey))

instanceId = 0

def addItem(parent, required, elementName, resourceType):
    global instanceId

    attrs = {}
    if not required:
        attrs["{%s}required" % NS_OVF] = 'false'
    item = xml.etree.ElementTree.Element('{%s}Item' % NS_OVF, attrs)
    rasdElement(item, 'ResourceType', resourceType)
    instanceId += 1
    rasdElement(item, 'InstanceID', instanceId)
    rasdElement(item, 'ElementName', elementName)
    parent.append(item)
    return item

def writeXMLFile(f, vmc, disks):
    xml.etree.ElementTree.register_namespace("cim", NS_CIM)
    xml.etree.ElementTree.register_namespace("ovf", NS_OVF)
    xml.etree.ElementTree.register_namespace("rasd", NS_RASD)
    xml.etree.ElementTree.register_namespace("vmw", NS_VMW)
    xml.etree.ElementTree.register_namespace("vssd", NS_VSSD)
    xml.etree.ElementTree.register_namespace("xsi", NS_XSI)

    envelope = xml.etree.ElementTree.Element('{%s}Envelope' % NS_OVF)
    files = []
    for disk in disks.disks.values():
        files.append(xml.etree.ElementTree.Element('{%s}File' % NS_OVF, { '{%s}href' % NS_OVF: disk[1], '{%s}id' % NS_OVF: disk[2], '{%s}size' % NS_OVF: str(os.stat(disk[1]).st_size) }))
    if files:
        references = xml.etree.ElementTree.Element('{%s}References' % NS_OVF)
        references.extend(files)
        envelope.append(references)
    dsk = []
    for disk in disks.disks.values():
        dsk.append(xml.etree.ElementTree.Element('{%s}Disk' % NS_OVF, { '{%s}capacity' % NS_OVF: str(disk[3]["capacity"] // 512), '{%s}capacityAllocationUnits' % NS_OVF: 'byte * 2^9',
                                                                        '{%s}diskId' % NS_OVF: disk[2], '{%s}fileRef' % NS_OVF: disk[2],
                                                                        '{%s}format' % NS_OVF: 'http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized',
                                                                        '{%s}populatedSize' % NS_OVF: str(disk[3]["used"]) }))
    if dsk:
        diskSection = xml.etree.ElementTree.Element('{%s}DiskSection' % NS_OVF)
        diskSection.extend(dsk)
        envelope.append(diskSection)

    virtualSystem = xml.etree.ElementTree.Element('{%s}VirtualSystem' % NS_OVF, { '{%s}id' % NS_OVF: 'vm' })
    envelope.append(virtualSystem)
    virtualSystem.append(newTextElement('{%s}Name' % NS_OVF, vmc.getString('Unknown', 'displayName')))
    oss = xml.etree.ElementTree.Element('{%s}OperatingSystemSection' % NS_OVF, { '{%s}id' % NS_OVF: 'os', '{%s}osType' % NS_VMW: '*other26xLinux64Guest' })
    virtualSystem.append(oss)
    hw = xml.etree.ElementTree.Element('{%s}VirtualHardwareSection' % NS_OVF)
    virtualSystem.append(hw)
    system = xml.etree.ElementTree.Element('{%s}System' % NS_OVF)
    system.append(newTextElement('{%s}ElementName' % NS_VSSD, 'Virtual Hardware Family'))
    system.append(newTextElement('{%s}InstanceID' % NS_VSSD, '0'))
    system.append(newTextElement('{%s}VirtualSystemIdentifier' % NS_VSSD, vmc.getString('Unknown', 'displayName')))
    system.append(newTextElement('{%s}VirtualSystemType' % NS_VSSD, 'vmx-%02u' % vmc.getInt(4, 'virtualHW.version')))
    hw.append(system)

    cpus = addItem(hw, True, 'cpu', 3)
    cpus.append(newTextElement('{%s}AllocationUnits' % NS_RASD, 'hertz * 10^6'))
    cpus.append(newTextElement('{%s}VirtualQuantity' % NS_RASD, "%s" % vmc.getInt(1, 'numvcpus')))

    memory = addItem(hw, True, 'memory', 4)
    rasdElement(memory, 'AllocationUnits', 'byte * 2^20')
    rasdElement(memory, 'VirtualQuantity', vmc.getInt(4, 'memsize'))

    if (vmc.getBool(False, 'usb.present')):
        # Note that this serialization is incorrect, but that is what OVFTool does...
        usb = addItem(hw, False, 'usb', 23)
        rasdElement(usb, 'Address', 0)
        rasdElement(usb, 'ResourceSubType', 'vmware.usb.ehci')
        addConfigVal(vmc, usb, 'ehciEnabled', 'true')

    for i in range(0, 4):
        aname = "scsi%u" % i
        if vmc.getBool(False, "%s.present" % aname):
            ctlr = addItem(hw, True, aname, 6)
            ctlrId = instanceId
            rasdElement(ctlr, 'Address', i)
            rasdElement(ctlr, 'ResourceSubType', 'VirtualSCSI')

            for d in range(0, 256):
                dname = "%s:%u" % (aname, d)
                if vmc.getBool(False, "%s.present" % dname):
                    dd = disks.disks[dname]
                    dsk = addItem(hw, True, dname, 17)
                    rasdElement(dsk, 'AddressOnParent', d)
                    rasdElement(dsk, 'HostResource', "ovf:/disk/%s" % dd[2])
                    rasdElement(dsk, 'Parent', ctlrId)

    if vmc.getBool(False, "vmci0.present"):
        vmci = addItem(hw, False, 'vmci', 1)
        rasdElement(vmci, 'AutomaticAllocation', 'false')
        rasdElement(vmci, 'ResourceSubType', 'vmware.vmci')

    nets = {}
    for i in range(0, 10):
        aname = "ethernet%u" % i
        if vmc.getBool(False, "%s.present" % aname):
            nname = vmc.getString(None, "%s.dvs.switchId" % aname)
            if nname is None:
                nname = vmc.getString(None, "%s.networkName" % aname)
                if nname is None:
                    nname = vmc.getString(None, "%s.connectionType" % aname)
                    if nname is None:
                        cname = "dummy"
                    else:
                        cname = "C%s" % nname.lower()
                else:
                    cname = "N%s" % nname.lower()
            else:
                cname = "D%s" % nname.lower()
            network = nets.get(cname)
            if network is None:
                ovfname = "net%u" % len(nets)
                net = xml.etree.ElementTree.Element('{%s}Network' % NS_OVF, { '{%s}name' % NS_OVF: ovfname })
                net.append(newTextElement('{%s}Description' % NS_OVF, nname))
                network = [ ovfname, net ]
                nets[cname] = network
            nic = addItem(hw, True, aname, 10)
            rasdElement(nic, 'AddressOnParent', i + 2)
            rasdElement(nic, 'AutomaticAllocation', 'true')
            rasdElement(nic, 'Connection', network[0])
            rasdElement(nic, 'ResourceSubType', 'VmxNet3')

    if nets:
        ns = xml.etree.ElementTree.Element('{%s}NetworkSection' % NS_OVF)
        for x in nets.values():
            ns.append(x[1])
        hw.append(ns)

    svga = addItem(hw, False, 'video', 24)
    rasdElement(svga, 'AutomaticAllocation', 'false')

    addConfig(vmc, hw, 'powerOpInfo.powerOffType', 'powerType.powerOff')
    addConfig(vmc, hw, 'powerOpInfo.resetType', 'powerType.reset')
    addConfig(vmc, hw, 'powerOpInfo.suspendType', 'powerType.suspend')

    indent(envelope)
    doc = xml.etree.ElementTree.ElementTree(envelope)
    doc.write(f, "unicode", True, "http://schemas.dmtf.org/ovf/envelope/1", "xml")

def convertDisks(disks):
    seq = 0
    for k, v in disks.disks.items():
        src = disks.vmc.getPath(v[0])
        dst = "disk%u.vmdk" % seq
        v[1] = dst
        v[2] = "file%u" % seq
        subprocess.check_call(["../build/vmdk/mkdisk", src, dst])
        out = subprocess.check_output(["../build/vmdk/mkdisk", "-i", src]).decode("UTF-8")
        if out.startswith("//OK"):
           v[3] = json.loads(out[4:])
        seq += 1


def main():
    with open(sys.argv[1], "r") as f:
        vmc = parseConfig(os.path.dirname(sys.argv[1]), f)
    disks = Disks(vmc)
    #vmc.dump()
    #disks.dump()
    convertDisks(disks)
    writeXMLFile(sys.stdout, vmc, disks)

main()
