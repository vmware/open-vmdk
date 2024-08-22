# Introduction

Open VMDK is an assistant tool for creating [Open Virtual Appliance (OVA)](https://en.wikipedia.org/wiki/Virtual_appliance). An OVA is a tar archive file with [Open Virtualization Format (OVF)](https://en.wikipedia.org/wiki/Open_Virtualization_Format) files inside, which is composed of an OVF descriptor with extension `.ovf`, one or more virtual machine disk image files with extension `.vmdk`, and a manifest file with extension `.mf`.

This tool consists of two parts:

## vmdk-convert

OVA files require stream optimized disk image files (`.vmdk`) so that they can be easily streamed over a network link. `vmdk-convert` can convert raw disk images, and flat or sparse vmdk images to the stream optimized disk image format.

## ova-compose

The OVF file that will be embedded can be generated using `ova-compose` from a simple yaml config file.

`ova-compose` will then create the final OVA from the OVF file, the vmdk images and a manifest (a file that contains checksums of the other files).


There is also the legacy tool `mkova.sh` that generates OVF files from templates.

## Specifications

The VMDK format specification can be downloaded at https://www.vmware.com/app/vmdk/?src=vmdk (pdf).

The OVF/OVA specification can be found at https://www.dmtf.org/standards/ovf

# Getting Started

## Installation
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

You can change the prefix with `PREFIX` (default is `usr`) or the installation directory with `DESTDIR` for packaging, for example:
```
$ make DESTDIR=/tmp/open-vmdk install
```

## Usage

`open-vmdk` basically has two parts:
* `vmdk-convert` to convert raw disk image files to `vmdk` format (and back)
* `ova-compose` to create an OVA (or OVF) file from a `vmdk` and a configuration file describing a VM

There is also a legacy tool `mkova.sh` that uses OVF templates. This is less flexible than `ova-compose` and will be deprecated.

### New VM

`vmdk-convert` can process raw disk images to streamable `vmdk` images. For example (as root):
```
dd if=/dev/zero of=testvm.img bs=1M count=4096
LOOP_DEVICE=$(losetup --show -f testvm.img)
... format disk to loop device and install OS into image ...
losetup -d $LOOP_DEVICE
vmdk-convert testvm.img testvm.vmdk
```

### Set the VMware Tools version

Set the VMware Tools version installed in your VM disk by adding the `-t` option.
The tools version is a number calculated from the version string `x.y.z` using the formulae `1024*x + 32*y + z`.
So for example for the version `12.1.5` the number would be `1024 * 12 + 1 * 32 + 5` = `12325`.
```
$ vmdk-convert -t 12325 testvm-flat.vmdk disk1.vmdk
```
This will set `ddb.toolsVersion` to 12325 in the metadata of disk1.vmdk. By default, the `ddb.toolsVersion` will be set to 2147483647 (MAXINT, or `2^31-1`).
See https://packages.vmware.com/tools/versions for all released VMware Tools versions.
See https://kb.vmware.com/s/article/83068 for instructions to add `ddb.toolsVersion` to an exiting OVF/OVA template.

### Existing VM

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

### Create an OVA with ova-compose

#### Config File
```
system:
    name: example
    type: vmx-17
    os_vmw: other4xLinux64Guest
    firmware: efi
    secure_boot: true
    default_configuration: grande

networks:
    vm_network:
        name: "VM Network"
        description: "The VM Network network"

hardware:
    cpus: 2
    memory: 2048
    sata1:
        type: sata_controller
    scsi1:
        type: scsi_controller
    cdrom1:
        type: cd_drive
        parent: sata1
    rootdisk:
        type: hard_disk
        parent: scsi1
        disk_image: example.vmdk
    usb1:
        type: usb_controller
    ethernet1:
        type: ethernet
        subtype: VmxNet3
        network: vm_network
    videocard1:
        type: video_card
    vmci1:
        type: vmci

configurations:
    tall:
        label: Tall
        description: too little for the money
    grande:
        label: Grande
        description: just right
    venti:
        label: Venti
        description: too much

environment:
    transports:
        - com.vmware.guestInfo
        - iso
    categories:
        email: Email Settings
    properties:
        guestinfo.admin.email:
            value: admin@company.org
            user_configurable: true
            type: string
            description: "The Admin's email address"
            label: "Email Address"
            category: email

extra_configs:
    feature.enabled:
        required: false
        value: true
    log.rotateSize:
        value: 2048000

product:
    product: An Example VM
    vendor: A Company Inc.

annotation:
    text: the password is top secret

eula:
    file: eula.txt
```

The config file has 3 mandatory and 4 optional sections. `system`, `networks` and `hardware` are mandatory.
* `system` describes basic properties of the whole system, like name, hardware compatibility version and others.
* `networks` describes the network used. Each entry is a unique id. Each of these entries needs a `name` and a `description`.
* `hardware` describes the hardware components. Every entry is a unique id that can be any name, except the reserved ids `cpus` and `memory`. Each components except `cpus` and `memory` must have a `type`. The type can be one of the values described below.
  The reserved ids:
  * `cpus`: set to the number of CPUs
  * `memory`: set to the memory size in megabytes

  The other ids can have these types:
  *  `scsi_controller`, `sata_controller` or `ide_controller`: a controller. Each controller can have 0 or more other devices attached.
  * `scsi_controller` can have a `subtype` set to one of `VirtualSCSI` (aka "pvscsi") or `lsilogic`.
  * `cd_drive`: a CD drive, optionally with an ISO image set with `image`. The file will be packed within the OVA. The controller to attach to must be set with `parent` to the id of the controller. Set `connected = true` to have the image connected on startup (default is `false`)
  * `floppy`: a floppy device. Very similar to `cd_drive`, but does not need to be connected to a controller.
  * `hard_disk`: a hard disk. This can be set to an image in streamable vmdk format with `disk_image`. The file will be packed within the OVA. Alternatively, if `disk_capacity` is set, an empty disk will be created.
  * `ethernet`: an ethernet device. The network must be set with `network` to one of the networks defined in the main `networks` section. Set `connected = false` to have the device disconnected on startup (default is `true`)
  * `usb_controller`, `video_card` and `vmci`: USB controller, video card and VMCI device.
  Optionally, each `hardware` item can have ` configuration` setting. If set, the hardware item will be present only for that particular `configuration`. This is useful to have different memory sizes, number of CPUs perconfiguration, or make hardware items only present for a particular configuration.
  * `cpus` can be set as a hardware type. In this case, the field `number` sets the number of CPUs. This is useful for different configurations.
  * `memory` can also be set as a hardware type. The size is specified with `size`.

These sections are optional:
* `product` describes the product. It has the fields `info`, `product`, `vendor`, `version` and `full_version`.
* `configurations` describes different OVF configurations that can be selected at deployment time. It is a map with the configuration id as key, and the fields `label`, `description` and optionally `default`: 
```
configurations:
    tall:
        label: Tall
        description: too little for the money
    grande:
        default: true
        label: Grande
        description: just right
```
The default can also be set with `default_configuration` in the `system` section.
* `environment` is for setting OVF properties. Variables are added under the new `environment` section as a `properties` map. The key is the name of the variable. Each variable has a mandatory `type`. `value`, `user_configurable` (default: `false`), `qualifiers`, `password` (default `false`),`label`, `description` are optional. Additionally, `transports` can be set in a list. Valid values are `iso` and `com.vmware.guestInfo`. Note that at least one of them must be set to make the properties visible inside the guest. Optionally, categories are set with `categories` to a map with an id as key and a description as value. Each property can have a `category` set to a category id.
* `extra_configs` is a map of settings with the fields `value` and optionally the boolean `required`.
* `annotation` has the fields `info`, `text` and `file`. `text` and `file` are mutually exclusive - `text` is text inline, `file` can be set to a text file that will be filled in. The annotation text will appear for example as a comment in VMware Fusion.
* `eula` also has the fields `info`, `text` and `file`. It contains the EULA agreement the user has to agree to when deploying the VM.

#### Parameters

Values can be filled in with parameters from the command line. This makes the yaml file reusable for different VMs. For example, the hard disk can be set via command line:
```
    rootdisk:
        type: hard_disk
        parent: scsi1
        disk_image: !param rootdisk
```
When invoking `ova-compose` (see below) the value can be set with `--param rootdisk=example.vmdk`.

Default values can also be set in case `ova-compose` is invoked without the parameter. Example:
```
hardware:
    cpus: !param cpus=2
    memory: !param memory=2048
```
In this case, setting the parameters `cpus` and `memory` will be optional.

If `ova-compose` is invoked without setting a parameter for which no default is set, it will throw an error.

#### Usage

`ova-compose -i|--input_file <input_file> -o|--output_file <output_file> [ --format <format> ] [[--param <key=value>] ...] [-q]`
Options:
* `-i|--input_file <input_file>` : the config file to use
* `-o|--output_file <output_file>`: the output file or directory
* `--format <format>` : the format, one of: `ova`, `ovf` or `dir`. If not set, the format will be guessed from the output file extension if it is `ova` or `ovf`
  * `ova` to create an OVA file
  * `ovf` to create just the OVF file
  * `dir` to create a directory containing the OVF file, the manifest and the files used for the cdrom and harddisk devices.
* `--param <key=value>`: set parameter `<key>` to `<value>`.
* `--param <key=value>`: set parameter `<key>` to `<value>`
* `--checksum-type sha256|sha512`: the checksum type used for the manifest file. The default is `sha256`.

Example:
```
$ ova-compose.py -i minimal.yaml -o minimal.ova
creating 'minimal.ova' with format 'ova' from 'minimal.yaml'
done.
```

### Create an OVA - Legacy (mkova.sh)

#### Hardware Options

By default, the OVA will be created with 2 CPUs and 1024 MB memory. For VMs with hardware version 11 or later, the default OVA firmware is `efi`.
These defaults can be changed with options to `mkova.sh`:

* `--num-cpus`: The number of CPUs of the OVA template. Default value is `2`.
* `--mem-size`: The memory size in MB of the OVA template. Default value is `1024`.
* `--firmware`: The firmare of the OVA template (`efi` or `bios`). Default value is `efi`.

These settings can also be set with the environment variables `NUM_CPUS`, `MEM_SIZE` and `FIRMWARE`,
for example in the configuration file (see below).

For hardware versions 7 and 10 only `bios` is supported as firmware.

#### Selecting the Template

The template is an OVF file with place holders and provides settings for a pre-configured VM.
It will be used to create the final OVF.
The template file can be selected in two ways - either directly with the `--template` option,
or by using the `--hw` option to specify the hardware version.

By default, the latest available template will be used.

Example: run `mkova.sh` to create OVA with specific hardware version (20):
```
$ mkova.sh --num-cpus 4 --mem-size 4096 --firmware bios --hw 20 ova_name disk1.vmdk
```

Note that templates do not exist for every possible hardware version.

Example: run `mkova.sh` to create OVA with a specific template:
```
$ mkova.sh --num-cpus 4 --mem-size 4096 --firmware bios --template /usr/share/open-vmdk/template-hw20.ovf ova_name disk1.vmdk
```

Where,
* _ova_name_ is your OVA name without .ova suffix.
* _dst.vmdk_ is the new vmdk file converted in step 2.
* _path_to_ovf_template_ is the path to .ovf template file. Below .ovf templates files can be used.
    * `templates/template-hw7.ovf` is the template for a VM with BIOS firmware with hardware version 7.
    * `templates/template-hw10.ovf` is the template for a VM with BIOS firmware with hardware version 10.
    * `templates/template-hw11.ovf` is the template for hardware version 11.
    * `templates/template-hw13.ovf` is the template for hardware version 13.
    * `templates/template-hw14.ovf` is the template for hardware version 14.
    * `templates/template-hw15.ovf` is the template for hardware version 15.
    * `templates/template-hw17.ovf` is the template for hardware version 17.
    * `templates/template-hw18.ovf` is the template for hardware version 18.
    * `templates/template-hw19.ovf` is the template for hardware version 19.
    * `templates/template-hw20.ovf` is the template for hardware version 20.

#### Create OVF File in Directory

Optionally, when the `--ovf` option is used, `mkova.sh` skips creating the OVA file and just creates a directory with the files that
would be have been packed into the OVA. The directory will be created in the current directory with the supplied
OVA name.

#### Multiple Disks

You can add multiple disks by adding them to the command line, for example:
```
$ mkova.sh ova_name path_to_ovf_template disk1.vmdk disk2.vmdk disk3.vmdk
```
Multiple disks are only supported to be attached to one SCSI controller, and at most 15 disks can be added in one OVA.

When `mkova.sh` completes, you should see the final OVA under the current directory.

#### Configuration File

`mkova.sh` will look for a configuration file at `/etc/open-vmdk.conf`.
This is a simple shell script that can be used to set default values.

