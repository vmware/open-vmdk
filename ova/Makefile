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

EXE=mkova.sh

PREFIX ?= /usr

all:

install:
	mkdir -p $(DESTDIR)/$(PREFIX)/bin && cp $(EXE) $(DESTDIR)/$(PREFIX)/bin/
	[ -f $(DESTDIR)/etc/open-vmdk.conf ] || mkdir -p $(DESTDIR)/etc/ && echo "PREFIX=${PREFIX}" > $(DESTDIR)/etc/open-vmdk.conf

