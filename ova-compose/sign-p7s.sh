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
# With -c, also writes a legacy .cert file, signed by the first keyfile. The
# .cert format only supports RSA and EC keys, so with -c the first keyfile
# must be an RSA or EC key. Without -c, the order of the keyfiles does not matter.
#
# Example:
#   ova-compose -i photon.yaml -o photon.ova --sign-format both \
#     --sign-script "sign-p7s.sh -a {sign_alg} -c {cert_file} {mf_file} {p7s_file} rsa.pem mldsa.pem"

set -e
set -o pipefail

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

if ! command -v openssl >/dev/null 2>&1; then
    echo "$0: openssl not found in PATH" >&2
    exit 1
fi

mf_file=$1
p7s_file=$2
shift 2

signer_args=()
for keyfile in "$@"; do
    signer_args+=(-signer "${keyfile}")
done

if [ -n "${cert_file}" ]; then
    cert_keyfile=$1

    # the legacy .cert format only supports RSA and EC keys
    key_alg=$(openssl x509 -in "${cert_keyfile}" -noout -text | sed -n 's/^ *Public Key Algorithm: *//p')
    case "${key_alg}" in
        rsaEncryption|id-ecPublicKey) ;;
        *)
            echo "$0: cannot sign the .cert with ${cert_keyfile} (${key_alg}), only RSA and EC keys are supported, so with -c the first keyfile must be an RSA or EC key." >&2
            exit 1
            ;;
    esac
fi

openssl cms -sign -binary -nosmimecap -cades -md "${sign_alg}" \
    "${signer_args[@]}" -in "${mf_file}" -outform DER -out "${p7s_file}"

if [ -n "${cert_file}" ]; then
    signature=$(openssl dgst -"${sign_alg}" -sign "${cert_keyfile}" -out - "${mf_file}" | od -An -v -tx1 | tr -d ' \n')
    echo "${sign_alg^^}($(basename "${mf_file}"))= ${signature}" > "${cert_file}"
    sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' "${cert_keyfile}" >> "${cert_file}"
fi
