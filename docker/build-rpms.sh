#!/bin/bash
set -e

PACKAGE=$1

tdnf install -y ${TDNF_OPTIONS} rpm-build git tar build-essential createrepo_c

SPEC=${PACKAGE}.spec
VERSION=$(rpmspec -q --srpm --queryformat "[%{VERSION}\n]" ${SPEC})
FULLNAME=${PACKAGE}-${VERSION}

saved_IFS=${IFS}
IFS=$'\n' BUILD_REQUIRES=( $(rpmspec -q --buildrequires ${SPEC} 2>/dev/null) )
IFS=${saved_IFS}

TARBALL=$(rpmspec -q --srpm --queryformat "[%{SOURCE}\n]" ${SPEC})
ARCH=$(uname -m)
RPM_BUILD_DIR="/usr/src/photon"
DIST=.ph5

echo BuildRequires: "${BUILD_REQUIRES[@]}"

# if checked out as a submodule .git is a file, pointing to the parent
# if pwd is mounted the parent is not accessible
# if checked out as sub module it's presumably clean so we can just pack all files
if [ -d .git ] ; then
    # https://github.com/actions/checkout/issues/760
    git config --global --add safe.directory $(pwd)

    tar zcf ${TARBALL} --transform "s,^,${FULLNAME}/," $(git ls-files)
else
    # prevent "tar: .: file changed as we read it"
    touch ${TARBALL}
    tar zcf ${TARBALL} --exclude=${TARBALL} --transform "s,^./,${FULLNAME}/," .
fi

tdnf install -y ${TDNF_OPTIONS} "${BUILD_REQUIRES[@]}"

mkdir -p ${RPM_BUILD_DIR}
mkdir -p ${RPM_BUILD_DIR}/{SOURCES,BUILD,RPMS,SRPMS}
mv ${TARBALL} ${RPM_BUILD_DIR}/SOURCES/

rpmbuild --nodeps -D "dist ${DIST}" -D "_topdir ${RPM_BUILD_DIR}" -ba ${SPEC}
createrepo_c ${RPM_BUILD_DIR}/RPMS
