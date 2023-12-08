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

SRC := flat.c sparse.c mkdisk.c
OUTPUTDIR := ../build/vmdk
EXE := $(OUTPUTDIR)/vmdk-convert

PREFIX ?= /usr

CC := gcc
CFLAGS := -W -Wall -O2 -g $(CFLAGS)
LDFLAGS := -g -lz $(LDFLAGS)

OBJS := $(addprefix $(OUTPUTDIR)/, $(SRC:%.c=%.o))

default: all

all: $(EXE)

$(EXE): $(OBJS) $(OUTPUTDIR)
	$(CC) -o $@ $(OBJS) $(LDFLAGS)

$(OUTPUTDIR)/%.o: %.c | $(OUTPUTDIR)
	$(CC) $(CFLAGS) -c -o $@ $<

$(OUTPUTDIR):
	mkdir -p $(OUTPUTDIR)

$(addprefix $(OUTPUTDIR)/,mkdisk.o flat.o sparse.o): diskinfo.h

$(addprefix $(OUTPUTDIR)/,sparse.o): vmware_vmdk.h

check:
	sparse -Wsparse-all -I/usr/include/x86_64-linux-gnu $(SRC)

install:
	mkdir -p $(DESTDIR)/$(PREFIX)/bin && cp $(EXE) $(DESTDIR)/$(PREFIX)/bin/

clean:
	rm -rf $(OUTPUTDIR)
