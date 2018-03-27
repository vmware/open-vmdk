# Open VMDK

Open VMDK is an assistant tool for making OVA from vSphere virtual machine.

## Getting Started

### Prerequisites

Before you use open-vmdk, you need to have [jq](https://stedolan.github.io/jq/) installed in your machine. Please refer to https://stedolan.github.io/jq/download/ for jq installation.

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
**Note**: After installation, `/usr/bin/vmdk-converter` and `/usr/bin/mkova.sh` will be installed. If you hope to change default installation place, such as `$HOME/bin/vmdk-converter`, specify "PREFIX" while running `make install`:
```
$ PREFIX=$HOME make install
```
Thus, you will see the binary `vmdk-converter` and script `mkova.sh` under `$HOME/bin/`. In such case, make sure you have added `$HOME/bin` in your `PATH` environment variable.


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
$ cd $TESTSVM_FOLDER
$ vmdk-converter testvm-flat.vmdk
```
After converting, a new vmdk file `dst.vmdk` will be created under `$TESTSVM_FOLDER` folder.

3. Run `mkova.sh` to create OVA.
```
$ mkova.sh testvm dst.vmdk $OPENVMDK_PATH/ova/template-hw10.ovf
```
Where `$OPENVMDK_PATH` is the full path to your `open-vmdk-master` folder.

4. Now you would be able to see the final OVA `testvm.ova` under your working directory.
