#!/bin/bash

# ================================================================================
# Copyright (c) 2014 VMware, Inc.  All Rights Reserved.                         
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

TMPDIR=$(mktemp -p . -d XXXXXXXX)

[ ! -n "$NUM_CPUS" ] && NUM_CPUS=2
[ ! -n "$MEM_SIZE" ] && MEM_SIZE=1024

if [ "$#" -ne 3 ] ; then
	echo "$#"
	echo usage "$0 name disk.vmdk template.ovf"
	exit 1
fi

name=$1
vmdk=$2
ovftempl=$3

if [ ! -f "$vmdk" ] ; then
	echo "$vmdk not found"
	exit 2
fi

if [ ! -f "$ovftempl" ] ; then
	echo "$ovftempl not found"
	exit 2
fi

cp "$vmdk" $TMPDIR/"${name}"-disk1.vmdk

VMDK_FILE_SIZE=$(du -b $TMPDIR/"${name}-disk1.vmdk" | cut -f1)
echo "vmdk file size is $VMDK_FILE_SIZE"
VMDK_CAPACITY=$(vmdk-convert -i "$vmdk" | cut -d ',' -f 1 | awk '{print $NF}')
echo "vmdk capacity is $VMDK_CAPACITY"
sed ${ovftempl} \
	-e "s/@@NAME@@/${name}/g" \
	-e "s/@@VMDK_FILE_SIZE@@/$VMDK_FILE_SIZE/g" \
	-e "s/@@VMDK_CAPACITY@@/$VMDK_CAPACITY/g" \
	-e "s/@@NUM_CPUS@@/$NUM_CPUS/g" \
	-e "s/@@MEM_SIZE@@/$MEM_SIZE/g" \
	> $TMPDIR/${name}.ovf

hw_version=$(grep "<vssd:VirtualSystemType>" $TMPDIR/${name}.ovf | sed 's#</*vssd:VirtualSystemType>##g' | cut -d '-' -f 2)
if [ $hw_version -le 12 ]; then
    echo "SHA1(${name}-disk1.vmdk)= $(sha1sum $TMPDIR/${name}-disk1.vmdk | cut -d' ' -f1)" > $TMPDIR/${name}.mf
    echo "SHA1(${name}.ovf)= $(sha1sum $TMPDIR/${name}.ovf | cut -d' ' -f1)" >> $TMPDIR/${name}.mf
elif [ $hw_version -eq 13 ] || [ $hw_version -eq 14 ]; then
    echo "SHA256(${name}-disk1.vmdk)= $(sha256sum $TMPDIR/${name}-disk1.vmdk | cut -d' ' -f1)" > $TMPDIR/${name}.mf
    echo "SHA256(${name}.ovf)= $(sha256sum $TMPDIR/${name}.ovf | cut -d' ' -f1)" >> $TMPDIR/${name}.mf
elif [ $hw_version -gt 14 ]; then
    echo "SHA512(${name}-disk1.vmdk)= $(sha512sum $TMPDIR/${name}-disk1.vmdk | cut -d' ' -f1)" > $TMPDIR/${name}.mf
    echo "SHA512(${name}.ovf)= $(sha512sum $TMPDIR/${name}.ovf | cut -d' ' -f1)" >> $TMPDIR/${name}.mf
fi

pushd $TMPDIR 
tar cf ../${name}.ova *.ovf *.mf *.vmdk
popd

rm -rf $TMPDIR
