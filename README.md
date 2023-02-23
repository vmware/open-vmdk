# Open VMDK

Open VMDK is an assistant tool for creating [Open Virtual Appliance (OVA)](https://en.wikipedia.org/wiki/Virtual_appliance). An OVA is a tar archive file with [Open Virtualization Format (OVF)](https://en.wikipedia.org/wiki/Open_Virtualization_Format) files inside, which is composed of an OVF descriptor with extension .ovf, a virtual machine disk image file with extension .vmdk, and a manifest file with extension .mf.

OVA requires stream optimized disk image file (.vmdk) so that it can be easily streamed over a network link. This tool can convert flat disk image or sparse disk image to stream optimized disk image,  and then create OVA with the converted stream optimized disk image by using an OVF descriptor template.

The VMDK format specification can be downloaded at https://www.vmware.com/app/vmdk/?src=vmdk (pdf).

## Getting Started

### Installation
Clone the repository, like `git clone https://github.com/vmware/open-vmdk`.

Alternatively, download and extract it:
```
curl -O https://github.com/vmware/open-vmdk/archive/master.tar.gz
tar zxf master.tar.gz
```
or if you prefer `wget` and `zip`:
```
$ wget https://github.com/vmware/open-vmdk/archive/master.zip
$ unzip master.zip
```

Run below commands to build and install:

```
$ cd open-vmdk-master
$ make
$ make install
```

You can change the prefix with `PREXIX` (default is `usr`) or the installation directory with `DESTDIR` for packaging, for example:
```
$ make DESTDIR=/tmp/open-vmdk install
```

### Usage

#### Existing VM

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

#### New VM

`vmdk-convert` can process raw disk images to streamable `vmdk` images. For example:
```
dd if=/dev/zero of=testvm.img bs=1M count=4096
LOOP_DEVICE=$(losetup --show -f testvm.img)
... format disk to loop device and install OS into image ...
losetup -d $LOOP_DEVICE
vmdk-convert testvm.img testvm.vmdk
```

#### Set the VMware Tools version

Set the VMware Tools version installed in your VM disk by adding the `-t` option.
The tools version is a number calculated from the version string `x.y.z` using the formulae `1024*x + 32*y + z`.
So for example for the version `12.1.5` the number would be `1024 * 12 + 1 * 32 + 5` = `12325`.
```
$ vmdk-convert -t 12325 testvm-flat.vmdk disk1.vmdk
```
This will set `ddb.toolsVersion` to 12325 in the metadata of disk1.vmdk. By default, the `ddb.toolsVersion` will be set to 2147483647.
See https://packages.vmware.com/tools/versions for all released VMware Tools versions.
See https://kb.vmware.com/s/article/83068 for instructions to add `ddb.toolsVersion` to an exiting OVF/OVA template.

#### Create an OVA

Hardware Options

By default, the OVA will be created with 2 cpus and 1024 MB memory. For VMs with hardware version 15 or later, the default OVA firmware is efi.
These defaults can be changed with options to `mkova.sh`:

* `--num-cpus`: The number of CPUs of the OVA template. Default value is `2`.
* `--mem-size`: The memory size in MB of the OVA template. Default value is `1024`.
* `--firmware`: The firmare of the OVA template (`efi` or `bios`). Default value is `efi`.

(these settings can also be set with the environment variables `NUM_CPUS`, `MEM_SIZE` and `FIRMWARE`)

Example: run `mkova.sh` to create OVA with specific hardware version:
```
$ mkova.sh --num-cpus 4 --mem-size 4096 --firmware bios ova_name path_to_ovf_template disk1.vmdk
```
Where,
* _ova_name_ is your OVA name without .ova suffix.
* _dst.vmdk_ is the new vmdk file converted in step 2.
* _path_to_ovf_template_ is the path to .ovf template file. Below .ovf templates files can be used.
    * `templates/template.ovf` is the template for BIOS VM with hardware version 7.
    * `templates/template-hw10.ovf` is the template for BIOS VM with hardware version 10.
    * `templates/template-hw11-bios.ovf` is the template for BIOS VM with hardware version 11.
    * `templates/template-hw11-uefi.ovf` is the template for EFI VM with hardware version 11.
    * `templates/template-hw13-bios.ovf` is the template for BIOS VM with hardware version 13.
    * `templates/template-hw13-uefi.ovf` is the template for EFI VM with hardware version 13.
    * `templates/template-hw14-bios.ovf` is the template for BIOS VM with hardware version 14.
    * `templates/template-hw14-uefi.ovf` is the template for EFI VM with hardware version 14.
    * `templates/template-hw15.ovf` is the template for EFI or BIOS VM with hardware version 15.
    * `templates/template-hw17.ovf` is the template for EFI or BIOS VM with hardware version 17.
    * `templates/template-hw18.ovf` is the template for EFI or BIOS VM with hardware version 18.
    * `templates/template-hw19.ovf` is the template for EFI or BIOS VM with hardware version 19.
    * `templates/template-hw20.ovf` is the template for EFI or BIOS VM with hardware version 20.

You can add multiple disks by adding them to the command line, for example:
```
$ mkova.sh ova_name path_to_ovf_template disk1.vmdk disk2.vmdk disk3.vmdk
```
Multiple disks are only supported to be attached to one SCSI controller, and at most 15 disks can be added in one OVA.

When `mkova.sh` completes, you should see the final OVA under iun the current directory.
