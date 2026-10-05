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

import os
import pytest
import re
import shutil
import subprocess
import sys
import tarfile


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OVA_COMPOSE = os.path.join(THIS_DIR, "..", "ova-compose", "ova-compose.py")
SIGN_P7S = os.path.join(THIS_DIR, "..", "ova-compose", "sign-p7s.sh")

VMDK_CONVERT = os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")

CONFIG_DIR = os.path.join(THIS_DIR, "configs")

WORK_DIR = os.path.join(os.getcwd(), "pytest-signing-p7s")

IN_YAML = os.path.join(CONFIG_DIR, "basic.yaml")


def openssl_version():
    out = subprocess.check_output(["openssl", "version"]).decode()
    m = re.match(r"OpenSSL (\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def create_key(work_dir, name, newkey, pkeyopts=[]):
    """Create a PEM file with a private key and a self-signed certificate"""
    keyfile = os.path.join(work_dir, f"{name}.pem")
    args = ["openssl", "req", "-x509", "-nodes", "-days", "365",
            "-newkey", newkey, "-keyout", keyfile, "-out", keyfile,
            "-subj", f"/CN={name}"]
    for opt in pkeyopts:
        args += ["-pkeyopt", opt]
    subprocess.run(args, check=True, cwd=work_dir, capture_output=True)
    return keyfile


def run_compose(work_dir, name, out_format, sign_args):
    """Run ova-compose, return (process, directory containing the package files, basename)"""
    if out_format == "ovf":
        output = os.path.join(work_dir, f"{name}.ovf")
        extra = ["-m"]
    elif out_format == "ova":
        output = os.path.join(work_dir, f"{name}.ova")
        extra = []
    else:
        output = os.path.join(work_dir, name)
        extra = ["--format", "dir"]
        if os.path.isdir(output):
            shutil.rmtree(output)
        elif os.path.exists(output):
            os.remove(output)

    args = [OVA_COMPOSE, "-i", IN_YAML, "-o", output, "--vmdk-convert", VMDK_CONVERT] + extra + sign_args
    process = subprocess.run(args, cwd=work_dir, capture_output=True, text=True)

    pkg_dir = work_dir
    if process.returncode == 0:
        if out_format == "ova":
            pkg_dir = os.path.join(work_dir, f"{name}-extracted")
            if os.path.exists(pkg_dir):
                shutil.rmtree(pkg_dir)
            os.makedirs(pkg_dir)
            subprocess.run(["tar", "xf", output], cwd=pkg_dir, check=True)
        elif out_format == "dir":
            pkg_dir = output
    return process, pkg_dir


def verify_p7s(p7s_file, mf_file, ca_files):
    ca_file = p7s_file + ".ca.pem"
    with open(ca_file, "wt") as fout:
        for f in ca_files:
            with open(f, "rt") as fin:
                fout.write(fin.read())
    process = subprocess.run(["openssl", "cms", "-verify", "-binary", "-inform", "DER",
                              "-in", p7s_file, "-content", mf_file,
                              "-CAfile", ca_file, "-purpose", "any", "-out", "/dev/null"],
                             capture_output=True, text=True)
    assert process.returncode == 0, f"verification failed: {process.stderr}"


def print_p7s(p7s_file):
    return subprocess.check_output(["openssl", "cms", "-cmsout", "-print", "-inform", "DER",
                                    "-in", p7s_file]).decode()


def cert_of(pem_file):
    """Return the (first) certificate of a PEM file, normalized"""
    with open(pem_file, "rt") as f:
        content = f.read()
    m = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", content, re.S)
    assert m is not None, f"no certificate in {pem_file}"
    return m.group(0)


@pytest.mark.parametrize("setup_test", [WORK_DIR], indirect=True)
@pytest.mark.parametrize("out_format", ["ovf", "ova", "dir"])
class TestP7sSigning:

    @pytest.fixture(autouse=True)
    def setup_class(self, setup_test, out_format):
        self.work_dir = WORK_DIR
        self.out_format = out_format
        self.rsa_key = create_key(self.work_dir, "rsa", "rsa:2048")
        self.ec_key = create_key(self.work_dir, "ec", "ec", ["ec_paramgen_curve:P-384"])

    def test_single_signer(self):
        name = f"p7s_single_{self.out_format}"
        script = f"{SIGN_P7S} -a {{sign_alg}} {{mf_file}} {{p7s_file}} {self.rsa_key}"
        process, pkg_dir = run_compose(self.work_dir, name, self.out_format,
                                       ["--sign-format", "p7s", "--sign-script", script])
        assert process.returncode == 0, process.stderr

        p7s_file = os.path.join(pkg_dir, f"{name}.p7s")
        mf_file = os.path.join(pkg_dir, f"{name}.mf")
        assert os.path.isfile(p7s_file)
        assert not os.path.exists(os.path.join(pkg_dir, f"{name}.cert"))

        verify_p7s(p7s_file, mf_file, [self.rsa_key])
        dump = print_p7s(p7s_file)
        assert "eContent: <ABSENT>" in dump
        assert "id-smime-aa-signingCertificateV2" in dump

        # the signature file must not be part of the manifest
        with open(mf_file, "rt") as f:
            assert ".p7s" not in f.read()

    def test_multiple_signers(self):
        name = f"p7s_multi_{self.out_format}"
        script = f"{SIGN_P7S} -a {{sign_alg}} {{mf_file}} {{p7s_file}} {self.rsa_key} {self.ec_key}"
        process, pkg_dir = run_compose(self.work_dir, name, self.out_format,
                                       ["--sign-format", "p7s", "--sign-script", script, "--sign-alg", "sha512"])
        assert process.returncode == 0, process.stderr

        p7s_file = os.path.join(pkg_dir, f"{name}.p7s")
        verify_p7s(p7s_file, os.path.join(pkg_dir, f"{name}.mf"), [self.rsa_key, self.ec_key])
        dump = print_p7s(p7s_file)
        assert dump.count("signatureAlgorithm:") == 2
        assert "sha512" in dump

    def test_both(self):
        name = f"p7s_both_{self.out_format}"
        script = f"{SIGN_P7S} -a {{sign_alg}} -c {{cert_file}} {{mf_file}} {{p7s_file}} {self.rsa_key} {self.ec_key}"
        process, pkg_dir = run_compose(self.work_dir, name, self.out_format,
                                       ["--sign-format", "both", "--sign-script", script])
        assert process.returncode == 0, process.stderr

        p7s_file = os.path.join(pkg_dir, f"{name}.p7s")
        cert_file = os.path.join(pkg_dir, f"{name}.cert")
        assert os.path.isfile(p7s_file)
        assert os.path.isfile(cert_file)
        verify_p7s(p7s_file, os.path.join(pkg_dir, f"{name}.mf"), [self.rsa_key, self.ec_key])

        # the .cert signer must be one of the .p7s signers
        p7s_certs = subprocess.check_output(["openssl", "pkcs7", "-inform", "DER", "-in", p7s_file,
                                             "-print_certs"]).decode()
        assert cert_of(cert_file) in p7s_certs

    def test_ova_file_order(self):
        if self.out_format != "ova":
            pytest.skip("only for ova")
        name = "p7s_order"
        script = f"{SIGN_P7S} -a {{sign_alg}} -c {{cert_file}} {{mf_file}} {{p7s_file}} {self.rsa_key}"
        process, _ = run_compose(self.work_dir, name, self.out_format,
                                 ["--sign-format", "both", "--sign-script", script])
        assert process.returncode == 0, process.stderr

        with tarfile.open(os.path.join(self.work_dir, f"{name}.ova")) as tar:
            names = tar.getnames()
        assert names[:4] == [f"{name}.ovf", f"{name}.mf", f"{name}.cert", f"{name}.p7s"]

    def test_hybrid_mldsa(self):
        if openssl_version() < (3, 5):
            pytest.skip("ML-DSA requires OpenSSL 3.5 or later")
        mldsa_key = create_key(self.work_dir, "mldsa", "mldsa65")
        name = f"p7s_mldsa_{self.out_format}"
        script = f"{SIGN_P7S} -a {{sign_alg}} {{mf_file}} {{p7s_file}} {self.rsa_key} {mldsa_key}"
        process, pkg_dir = run_compose(self.work_dir, name, self.out_format,
                                       ["--sign-format", "p7s", "--sign-script", script, "--sign-alg", "sha512"])
        assert process.returncode == 0, process.stderr
        verify_p7s(os.path.join(pkg_dir, f"{name}.p7s"), os.path.join(pkg_dir, f"{name}.mf"),
                   [self.rsa_key, mldsa_key])


@pytest.mark.parametrize("setup_test", [WORK_DIR], indirect=True)
class TestP7sSigningErrors:

    @pytest.fixture(autouse=True)
    def setup_class(self, setup_test):
        self.work_dir = WORK_DIR
        self.rsa_key = create_key(self.work_dir, "rsa", "rsa:2048")

    def write_script(self, name, body):
        script = os.path.join(self.work_dir, name)
        with open(script, "wt") as f:
            f.write("#!/bin/bash\n" + body)
        os.chmod(script, 0o755)
        return script

    def test_p7s_not_created(self):
        script = self.write_script("no_p7s.sh", "exit 0\n")
        process, _ = run_compose(self.work_dir, "err_missing", "ova",
                                 ["--sign-format", "p7s", "--sign-script", script])
        assert process.returncode != 0
        assert "not created" in process.stderr

    def test_p7s_empty(self):
        script = self.write_script("empty_p7s.sh", 'touch "$1"\n')
        process, _ = run_compose(self.work_dir, "err_empty", "ova",
                                 ["--sign-format", "p7s", "--sign-script", f"{script} {{p7s_file}}"])
        assert process.returncode != 0
        assert "is empty" in process.stderr

    def test_p7s_not_der(self):
        script = self.write_script("pem_p7s.sh", 'echo "-----BEGIN CMS-----" > "$1"\n')
        process, _ = run_compose(self.work_dir, "err_not_der", "ova",
                                 ["--sign-format", "p7s", "--sign-script", f"{script} {{p7s_file}}"])
        assert process.returncode != 0
        assert "not DER encoded" in process.stderr

    def test_p7s_not_signed_data(self):
        # a DER file that is not a CMS SignedData (a certificate)
        script = self.write_script("cert_p7s.sh", f'openssl x509 -in {self.rsa_key} -outform DER -out "$1"\n')
        process, _ = run_compose(self.work_dir, "err_not_sd", "ova",
                                 ["--sign-format", "p7s", "--sign-script", f"{script} {{p7s_file}}"])
        assert process.returncode != 0
        assert "not a CMS SignedData" in process.stderr

    def test_both_cert_missing(self):
        script = f"{SIGN_P7S} {{mf_file}} {{p7s_file}} {self.rsa_key}"
        process, _ = run_compose(self.work_dir, "err_both", "ova",
                                 ["--sign-format", "both", "--sign-script", script])
        assert process.returncode != 0
        assert "certificate file" in process.stderr

    def test_script_fails(self):
        script = self.write_script("fail.sh", "exit 1\n")
        process, _ = run_compose(self.work_dir, "err_fail", "ova",
                                 ["--sign-format", "p7s", "--sign-script", script])
        assert process.returncode != 0

    def test_p7s_requires_script(self):
        process, _ = run_compose(self.work_dir, "err_noscript", "ova",
                                 ["--sign-format", "p7s", "--sign", self.rsa_key])
        assert process.returncode != 0
        assert "requires --sign-script" in process.stderr

    def test_p7s_rejects_sha1(self):
        script = f"{SIGN_P7S} -a {{sign_alg}} {{mf_file}} {{p7s_file}} {self.rsa_key}"
        process, _ = run_compose(self.work_dir, "err_sha1", "ova",
                                 ["--sign-format", "p7s", "--sign-script", script, "--sign-alg", "sha1"])
        assert process.returncode != 0
        assert "sha1" in process.stderr

    def test_invalid_sign_format(self):
        process, _ = run_compose(self.work_dir, "err_format", "ova",
                                 ["--sign-format", "pkcs7", "--sign", self.rsa_key])
        assert process.returncode != 0

    def test_p7s_with_embedded_content(self):
        # an attached (non detached) signature must be rejected
        script = self.write_script("attached_p7s.sh",
            f'openssl cms -sign -binary -nosmimecap -nodetach -in "$1" -signer {self.rsa_key} -outform DER -out "$2"\n')
        process, _ = run_compose(self.work_dir, "err_attached", "ova",
                                 ["--sign-format", "p7s", "--sign-script", f"{script} {{mf_file}} {{p7s_file}}"])
        assert process.returncode != 0
        assert "detached" in process.stderr

    def test_cert_signature_failure_is_detected(self):
        # if the digest/sign step for the .cert fails, the script must fail
        # instead of writing a .cert without signature
        real_openssl = shutil.which("openssl")
        shim_dir = os.path.join(self.work_dir, "shim-bin")
        os.makedirs(shim_dir, exist_ok=True)
        shim = os.path.join(shim_dir, "openssl")
        with open(shim, "wt") as f:
            f.write(f'#!/bin/bash\n[ "$1" = "dgst" ] && exit 1\nexec {real_openssl} "$@"\n')
        os.chmod(shim, 0o755)

        script = f"{SIGN_P7S} -a {{sign_alg}} -c {{cert_file}} {{mf_file}} {{p7s_file}} {self.rsa_key}"
        args = [sys.executable, OVA_COMPOSE, "-i", IN_YAML, "-o", os.path.join(self.work_dir, "err_dgst.ova"),
                "--vmdk-convert", VMDK_CONVERT, "--sign-format", "both", "--sign-script", script]
        process = subprocess.run(args, cwd=self.work_dir, capture_output=True, text=True,
                                 env=dict(os.environ, PATH=shim_dir + os.pathsep + os.environ["PATH"]))
        assert process.returncode != 0

    def test_p7s_sha1_default_message(self):
        # sha1 comes from the checksum-type default here, the message must say so
        script = f"{SIGN_P7S} {{mf_file}} {{p7s_file}} {self.rsa_key}"
        process, _ = run_compose(self.work_dir, "err_sha1_default", "ova",
                                 ["--sign-format", "p7s", "--sign-script", script, "--checksum-type", "sha1"])
        assert process.returncode != 0
        assert "checksum-type" in process.stderr
        assert "--sign-alg sha256" in process.stderr

    def test_sign_without_openssl(self):
        # --sign uses openssl, so it must fail early with a clear message
        empty_bin = os.path.join(self.work_dir, "empty-bin")
        os.makedirs(empty_bin, exist_ok=True)
        args = [sys.executable, OVA_COMPOSE, "-i", IN_YAML, "-o", os.path.join(self.work_dir, "err_noopenssl.ova"),
                "--vmdk-convert", VMDK_CONVERT, "--sign", self.rsa_key]
        process = subprocess.run(args, cwd=self.work_dir, capture_output=True, text=True,
                                 env=dict(os.environ, PATH=empty_bin))
        assert process.returncode != 0
        assert "openssl is required" in process.stderr

    def test_script_signing_without_openssl(self):
        # a script that does not need openssl (e.g. a signing server) must still work,
        # the p7s check is skipped. Create a p7s beforehand and have the script copy it.
        good = os.path.join(self.work_dir, "prebuilt.p7s")
        mf = os.path.join(self.work_dir, "prebuilt.mf")
        with open(mf, "wt") as f:
            f.write("x\n")
        subprocess.run(["openssl", "cms", "-sign", "-binary", "-nosmimecap", "-in", mf, "-signer", self.rsa_key,
                        "-outform", "DER", "-out", good], check=True)
        script = f"/bin/cp {good} {{p7s_file}}"
        empty_bin = os.path.join(self.work_dir, "empty-bin")
        os.makedirs(empty_bin, exist_ok=True)
        args = [sys.executable, OVA_COMPOSE, "-i", IN_YAML, "-o", os.path.join(self.work_dir, "noossl.ovf"),
                "--vmdk-convert", VMDK_CONVERT, "--sign-format", "p7s", "--sign-script", script]
        process = subprocess.run(args, cwd=self.work_dir, capture_output=True, text=True,
                                 env=dict(os.environ, PATH=empty_bin))
        assert process.returncode == 0, process.stderr
        assert os.path.isfile(os.path.join(self.work_dir, "noossl.p7s"))
        assert "openssl not found" in process.stderr
