#!/bin/bash

# ================================================================================
# Copyright (c) 2014-2023 VMware, Inc.  All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the “License”); you may not
# use this file except in compliance with the License.  You may obtain a copy of
# the License at:
#
#              http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an “AS IS” BASIS, without warranties or
# conditions of any kind, EITHER EXPRESS OR IMPLIED.  See the License for the
# specific language governing permissions and limitations under the License.
# ================================================================================

[ -f /etc/open-vmdk.conf ] && . /etc/open-vmdk.conf

[ ! -n "$PREFIX" ] && PREFIX=/usr
[ ! -n "$DATADIR" ] && DATADIR=${PREFIX}/share/open-vmdk
# default template should be the latest:
[ ! -n "$OVFTEMPL" ] && OVFTEMPL=${DATADIR}/template-hw20.ovf

[ ! -n "$NUM_CPUS" ] && NUM_CPUS=2
[ ! -n "$MEM_SIZE" ] && MEM_SIZE=1024
[ ! -n "$FIRMWARE" ] && FIRMWARE="efi"

usage() {
    echo "Usage: $0"
    echo "          [-n|--num-cpus <num_cpus>]"
    echo "          [-m|--mem-size <mem_size>]"
    echo "          [-f|--firmware efi|bios]"
    echo "          [--hw <version>]"
    echo "          [--template <path_to_template>]"
    echo "          [--ovf]"
    echo "          ova_name disk1.vmdk [disk2.vmdk [...]]"
    echo ""
    echo "Create an OVA template from VMDK files"
    echo ""
    echo "Environment variables can be used to change OVA settings:"
    echo "* NUM_CPUS: The CPU numbers of the OVA template. Default value is 2."
    echo "* MEM_SIZE: The memory size in MB of the OVA template. Default value is 1024."
    echo "* FIRMWARE: The firmware of the OVA template: efi or bios. Default value is efi."
}

OPTS=$(getopt -o n:m:f: --long num-cpus:,mem-size:,firmware:,hw:,template:,ovf -n $0 -- "$@")
if [ $? != 0 ] ; then
    usage
    echo "Terminating." >&2
    exit 1
fi

eval set -- "$OPTS"

ovftempl=${OVFTEMPL}
ovf=false

while true; do
    case "$1" in
        -n | --num-cpus) NUM_CPUS=${2} ; shift 2 ;;
        -m | --mem-size) MEM_SIZE=${2} ; shift 2 ;;
        -f | --firmware) FIRMWARE=${2} ; shift 2 ;;
        --hw) ovftempl=${DATADIR}/template-hw${2}.ovf ; shift 2 ;;
        --template) ovftempl=${2} ; shift 2 ;;
        --ovf) ovf="true" ; shift ;;
        --) shift; break ;;
        *) break ;;
    esac
done

if [ "$#" -lt 2 ] ; then
    echo "need at least 2 arguments" >&2
    usage
    echo "Terminating." >&2
    exit 1
fi

name=$1
shift
# for backwards compatibility:
if [ "${1: -4}" == ".ovf" ] ; then
    echo "Specifying the template as an argument is deprecated. Please use the --template or the --hw option."
    ovftempl=$1
    shift
fi
vmdks=$@
vmdks_num=$#

echo "Starting to create ${name}.ova with ${vmdks_num} disk(s) with template ${ovftempl}"
echo "Number of CPUs: ${NUM_CPUS}"
echo "Memory in MB: ${MEM_SIZE}"
echo "Firmware Type: ${FIRMWARE}"

for vmdk in $vmdks; do
    if [ ! -f "$vmdk" ] ; then
        echo "$vmdk not found"
        exit 2
    fi
done

if [ ! -f "$ovftempl" ] ; then
    echo "$ovftempl not found"
    exit 2
fi

hw_version=$(grep "<vssd:VirtualSystemType>" $ovftempl | sed 's#</*vssd:VirtualSystemType>##g' | cut -d '-' -f 2)
if [ $hw_version -le 12 ]; then
    sha_alg=1
elif [ $hw_version -eq 13 ] || [ $hw_version -eq 14 ]; then
    sha_alg=256
elif [ $hw_version -gt 14 ]; then
    sha_alg=512
fi

# If there are more than one vmdk, we need to know what is the next available instance id for other disks
max_id=0
for id in `grep InstanceID $ovftempl | sed 's/[^0-9]*//g'`; do
    if [ $id -gt $max_id ]; then
        max_id=$id
    fi
done
next_id=$((max_id+1))

# Get vmdk parent id
disk_parent_id=`sed -n '/Hard Disk 1/,+3p' $ovftempl | grep Parent | sed 's/[^0-9]*//g'`

TMPDIR=$(mktemp -p . -d XXXXXXXX)

index=1
for vmdk in $vmdks; do
   vmdk_name="${name}-disk${index}.vmdk"

   echo "Adding $vmdk as ${vmdk_name}"
   cp "$vmdk" $TMPDIR/"${vmdk_name}"

   vmdk_file_size=$(du -b $TMPDIR/"${vmdk_name}" | cut -f1)
   echo "$vmdk file size is $vmdk_file_size bytes"
   vmdk_capacity=$(vmdk-convert -i "$vmdk" | cut -d ',' -f 1 | awk '{print $NF}')
   echo "$vmdk capacity is $vmdk_capacity bytes"

   if [ $index -eq 1 ]; then
      sed ${ovftempl} \
          -e "s/@@NAME@@/${name}/g" \
          -e "s/@@VMDK_FILE_SIZE@@/$vmdk_file_size/g" \
          -e "s/@@VMDK_CAPACITY@@/$vmdk_capacity/g" \
          -e "s/@@NUM_CPUS@@/$NUM_CPUS/g" \
          -e "s/@@MEM_SIZE@@/$MEM_SIZE/g" \
          -e "s/@@FIRMWARE@@/$FIRMWARE/g" \
          > $TMPDIR/${name}.ovf
   else
       # Insert disk file information for Hard Disk 2, 3, 4, etc
       last_index=$((index-1))
       sed -i \
           -e "/${name}-disk${last_index}.vmdk/a \
              <File ovf:href=\"${vmdk_name}\" ovf:id=\"file${index}\" ovf:size=\"${vmdk_file_size}\"/>" \
           -e "/ovf:fileRef=\"file${last_index}\"/a \
              <Disk ovf:capacity=\"${vmdk_capacity}\" ovf:capacityAllocationUnits=\"byte\" ovf:diskId=\"vmdisk${index}\" ovf:fileRef=\"file${index}\" ovf:format=\"http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized\" ovf:populatedSize=\"0\"/>" \
          $TMPDIR/"${name}".ovf

       # Insert hardware item information for Hard Disk 2, 3, 4, etc
       insert_after=`grep -n '</Item>' $TMPDIR/"${name}".ovf | tail -n 1 | cut -d: -f 1`

       # There is no scsi0:7, so we need to skip it.
       if [ $last_index -lt 7 ]; then
           address_on_parent=$last_index
       else
           address_on_parent=$((last_index+1))
       fi

       sed -i -e "${insert_after}a \
             <Item>\n\
                <rasd:AddressOnParent>${address_on_parent}</rasd:AddressOnParent>\n\
                <rasd:ElementName>Hard Disk $index</rasd:ElementName>\n\
                <rasd:HostResource>ovf:/disk/vmdisk$index</rasd:HostResource>\n\
                <rasd:InstanceID>${next_id}</rasd:InstanceID>\n\
                <rasd:Parent>$disk_parent_id</rasd:Parent>\n\
                <rasd:ResourceType>17</rasd:ResourceType>\n\
                <vmw:Config ovf:required=\"false\" vmw:key=\"backing.writeThrough\" vmw:value=\"false\"/>\n\
             </Item>" \
          $TMPDIR/"${name}".ovf

       next_id=$((next_id+1))
   fi

   index=$((index+1))

   # Get the sha checksum of the vmdk file
   echo "SHA${sha_alg}($vmdk_name)= $(sha${sha_alg}sum $TMPDIR/${vmdk_name} | cut -d' ' -f1)" >> $TMPDIR/${name}.mf
done

# Get the sha checksum of the ovf file
echo "SHA${sha_alg}(${name}.ovf)= $(sha${sha_alg}sum $TMPDIR/${name}.ovf | cut -d' ' -f1)" >> $TMPDIR/${name}.mf

if [ ${ovf} == "true" ] ; then
    if [ -d ${name} ] ; then
        echo "directory ${name} exists" >&2
        echo "Terminating." >&2
        exit 3
    fi
    mv $TMPDIR ${name}
    echo "Completed to create ovf files in directory ${name}"
else
    pushd $TMPDIR
    tar --format=ustar -cf ../${name}.ova *.ovf *.mf *.vmdk
    popd

    echo "Completed to create ${name}.ova"

    rm -rf $TMPDIR
fi

