#!/bin/bash

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
VMDK_CAPACITY=$(vmdk-convert -i "$vmdk" | jq .capacity)
echo "vmdk capacity is $VMDK_CAPACITY"
sed ${ovftempl} \
	-e "s/@@NAME@@/${name}/g" \
	-e "s/@@VMDK_FILE_SIZE@@/$VMDK_FILE_SIZE/g" \
	-e "s/@@VMDK_CAPACITY@@/$VMDK_CAPACITY/g" \
	-e "s/@@NUM_CPUS@@/$NUM_CPUS/g" \
	-e "s/@@MEM_SIZE@@/$MEM_SIZE/g" \
	> $TMPDIR/${name}.ovf

echo "SHA1(${name}-disk1.vmdk)= $(sha1sum $TMPDIR/${name}-disk1.vmdk | cut -d' ' -f1)" > $TMPDIR/${name}.mf
echo "SHA1(${name}.ovf)= $(sha1sum $TMPDIR/${name}.ovf | cut -d' ' -f1)" >> $TMPDIR/${name}.mf

pushd $TMPDIR 
tar cf ../${name}.ova *.ovf *.mf *.vmdk
popd

rm -rf $TMPDIR
