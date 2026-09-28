#!/bin/bash

# Copyright (c) 2026 Broadcom.  All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License.  You may obtain a copy of
# the License at:
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, without warranties or
# conditions of any kind, EITHER EXPRESS OR IMPLIED.  See the License for the
# specific language governing permissions and limitations under the License.

# Example signing script for ova-compose --sign-format p7s|both.
#
# Creates a detached, DER encoded CMS SignedData (.p7s) over the manifest,
# with one signer per keyfile. Each keyfile is a PEM file containing both
# the private key and the certificate. All signers use the same digest.
# ML-DSA keys require OpenSSL 3.5 or later.
#
# With -c, also writes a legacy .cert file signed by the first keyfile.
#
# Example:
#   ova-compose -i photon.yaml -o photon.ova --sign-format both \
#     --sign-script "sign-p7s.sh -a {sign_alg} -c {cert_file} {mf_file} {p7s_file} rsa.pem mldsa.pem"

set -e

usage() {
    echo "Usage: $0 [-a <digest>] [-c <cert_file>] <mf_file> <p7s_file> <keyfile> [<keyfile> ...]" >&2
    exit 2
}

sign_alg=sha256
cert_file=

while getopts "a:c:h" opt; do
    case ${opt} in
        a) sign_alg=${OPTARG} ;;
        c) cert_file=${OPTARG} ;;
        *) usage ;;
    esac
done
shift $((OPTIND - 1))

[ $# -ge 3 ] || usage

mf_file=$1
p7s_file=$2
shift 2

signer_args=()
for keyfile in "$@"; do
    signer_args+=(-signer "${keyfile}")
done

openssl cms -sign -binary -nosmimecap -cades -md "${sign_alg}" \
    "${signer_args[@]}" -in "${mf_file}" -outform DER -out "${p7s_file}"

if [ -n "${cert_file}" ]; then
    keyfile=$1
    signature=$(openssl dgst -"${sign_alg}" -sign "${keyfile}" -out - "${mf_file}" | od -An -v -tx1 | tr -d ' \n')
    echo "${sign_alg^^}($(basename "${mf_file}"))= ${signature}" > "${cert_file}"
    sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' "${keyfile}" >> "${cert_file}"
fi
