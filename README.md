# Open VMDK

Open VMDK is an assistant tool for creating [Open Virtual Appliance (OVA)](https://en.wikipedia.org/wiki/Virtual_appliance). An OVA is a tar archive file with [Open Virtualization Format (OVF)](https://en.wikipedia.org/wiki/Open_Virtualization_Format) files inside, which is composed of an OVF descriptor with extension .ovf, a virtual machine disk image file with extension .vmdk, and a manifest file with extension .mf.

OVA requires stream optimized disk image file (.vmdk) so that it can be easily streamed over a network link. This tool can convert flat disk image or sparse disk image to stream optimized disk image,  and then create OVA with the converted stream optimized disk image by using an OVF descriptor template.

## Getting Started

### Installation
Firstly, you need to download and extract [open-vmdk-master.zip](https://github.com/vmware/open-vmdk/archive/master.zip) and extract it:
```
$ wget https://github.com/vmware/open-vmdk/archive/master.zip
$ unzip master.zip
```

Then, run below commands to build and install it:

```
$ cd open-vmdk-master
$ make
$ make install
```
**Note**: After installation, `/usr/bin/vmdk-convert` and `/usr/bin/mkova.sh` will be installed. If you hope to change default installation place, such as `$HOME/bin/vmdk-convert`, specify "PREFIX" while running `make install`:
```
$ PREFIX=$HOME make install
```
Thus, you will see the binary `vmdk-convert` and script `mkova.sh` under `$HOME/bin/`. In such case, make sure you have added `$HOME/bin` in your `PATH` environment variable.


### Usage

Below example shows how to create an [Open Virtual Appliance (OVA)](https://en.wikipedia.org/wiki/Virtual_appliance) from vSphere virtual machine. Presume the virtual machine's name is `testvm`, and virtual machine files include:
```
testvm-312d29db.hlog
testvm-flat.vmdk
testvm.nvram
testvm.vmdk
testvm.vmsd
testvm.vmx
vmware.log
```
1. Copy `testvm` folder to `TESTSVM_PATH` on the machine where you have `open-vmdk` installed.
2. Convert vmfs raw data extent file of the VM to OVF streaming format.
```
$ cd $TESTSVM_PATH
$ vmdk-convert testvm-flat.vmdk
```
After converting, a new vmdk file `dst.vmdk` will be created under `$TESTSVM_PATH` folder.
Or, you can specify the new vmdk file name by running
```
$ vmdk-convert testvm-flat.vmdk disk1.vmdk
```
After converting, a new vmdk file `disk1.vmdk` will be created under `$TESTSVM_PATH` folder.

You can also set the VMware Tools version installed in your VM disk by add `-t` option
```
$ vmdk-convert -t 11264 testvm-flat.vmdk disk1.vmdk
```
This will set `ddb.toolsVersion` to 11264 in the metadata of disk1.vmdk. By default, the `ddb.toolsVersion` will be set to 2147483647.
See https://packages.vmware.com/tools/versions for all released VMware Tools versions.
See https://kb.vmware.com/s/article/83068 for instructions to add `ddb.toolsVersion` to an exiting OVF/OVA template.

3. Export environment variables for OVA settings
By default, the OVA will be created with 2 cpus and 1024 MB memory. For VM with hardware version 15 or later, the default OVA firmware is efi. To change default OVA settings, you can export below environment variables before executing `mkova.sh` command:
* `NUM_CPUS`: The number of CPUs of the OVA template. Default value is `2`.
* `MEM_SIZE`: The memory size in MB of the OVA template. Default value is `1024`.
* `FIRMWARE`: The firmare of the OVA template. Default value is `efi`.

For example,
```
export NUM_CPUS=4
export MEM_SIZE=4096
export FIRMWARE=bios
```

4. Run `mkova.sh` to create OVA with specific hardware version.
```
$ mkova.sh ova_name path_to_ovf_template disk1.vmdk
```
Where,
* _ova_name_ is your OVA name without .ova suffix.
* _dst.vmdk_ is the new vmdk file converted in step 2.
* _path_to_ovf_template_ is the path to .ovf template file. Below .ovf templates files can be used.
    * `ova/template.ovf` is the template for BIOS VM with hardware version 7.
    * `ova/template-hw10.ovf` is the template for BIOS VM with hardware version 10.
    * `ova/template-hw11-bios.ovf` is the template for BIOS VM with hardware version 11.
    * `ova/template-hw11-uefi.ovf` is the template for EFI VM with hardware version 11.
    * `ova/template-hw13-bios.ovf` is the template for BIOS VM with hardware version 13.
    * `ova/template-hw13-uefi.ovf` is the template for EFI VM with hardware version 13.
    * `ova/template-hw14-bios.ovf` is the template for BIOS VM with hardware version 14.
    * `ova/template-hw14-uefi.ovf` is the template for EFI VM with hardware version 14.
    * `ova/template-hw15.ovf` is the template for EFI or BIOS VM with hardware version 15.
    * `ova/template-hw17.ovf` is the template for EFI or BIOS VM with hardware version 17.
    * `ova/template-hw18.ovf` is the template for EFI or BIOS VM with hardware version 18.
    * `ova/template-hw19.ovf` is the template for EFI or BIOS VM with hardware version 19.
    * `ova/template-hw20.ovf` is the template for EFI or BIOS VM with hardware version 20.

If you want to add more than 1 disk into the OVA, firstly convert all flat vmdk files, and add new converted vmdk files by following path_to_ovf_template.
For example, below command creates an OVA with 3 disks
```
$ mkova.sh ova_name path_to_ovf_template disk1.vmdk disk2.vmdk disk3.vmdk
```
Here mutiple disks are only supported to be attached to one SCSI controller, and at most 15 disks can be added in one OVA.

5. After `mkova.sh` completes, you would be able to see the final OVA under `$TESTSVM_PATH` folder.
