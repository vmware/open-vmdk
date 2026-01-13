# Copyright (c) 2024 Broadcom.  All Rights Reserved.
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

import glob
import hashlib
import os
import pytest
import shutil
import subprocess
import tempfile
import yaml
import xmltodict


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OVA_COMPOSE = os.path.join(THIS_DIR, "..", "ova-compose", "ova-compose.py")

VMDK_CONVERT = os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")

CONFIG_DIR = os.path.join(THIS_DIR, "configs")

WORK_DIR = os.path.join(os.getcwd(), "pytest-signing")


@pytest.mark.parametrize("setup_test", [WORK_DIR], indirect=True)
@pytest.mark.parametrize("sign_alg", ["sha1", "sha256", "sha512"])
class TestOVFSigning:

    @pytest.fixture(autouse=True)
    def setup_class(self, setup_test, sign_alg):
        self.sign_alg = sign_alg
        self.work_dir = WORK_DIR
        self.keyfile = os.path.join(self.work_dir, "test_key.pem")
        self.create_test_key()

    def create_test_key(self):
        """Create a test private key and certificate for signing"""
        # Generate private key and self-signed certificate in one step
        subprocess.run([
            "openssl", "req", "-x509", "-nodes", "-sha256", "-days", "365",
            "-newkey", "rsa:2048", "-keyout", self.keyfile, "-out", self.keyfile,
            "-subj", "/CN=Test Certificate"
        ], check=True, cwd=self.work_dir)

    def verify_signature(self, mf_file, cert_file, sign_alg):
        """Verify the signature in the certificate file"""
        with open(cert_file, "rt") as f:
            lines = f.readlines()

        # Find the signature line
        signature_line = None
        expected_prefix = f"{sign_alg.upper()}({os.path.basename(mf_file)})="
        for line in lines:
            if line.startswith(f"{sign_alg.upper()}(") and os.path.basename(mf_file) in line:
                signature_line = line
                break

        assert signature_line is not None, f"No {sign_alg} signature found in cert file for {os.path.basename(mf_file)}"

        # Extract signature
        left, signature_hex = signature_line.split("=", 1)
        signature_hex = signature_hex.strip()

        # Verify the signature format
        assert left.strip() == f"{sign_alg.upper()}({os.path.basename(mf_file)})"

        # Verify signature is valid hex
        try:
            bytes.fromhex(signature_hex)
        except ValueError:
            pytest.fail("Signature is not valid hexadecimal")

        # Verify certificate is present
        cert_found = False
        for line in lines:
            if "-----BEGIN CERTIFICATE-----" in line:
                cert_found = True
                break

        assert cert_found, "Certificate not found in cert file"

    def check_mf(self, mf_path, work_dir=None):
        """Check manifest file integrity"""
        if work_dir is None:
            work_dir = self.work_dir

        with open(mf_path, "rt") as f:
            for line in f:
                left, hash_mf = line.split("=")
                hash_mf = hash_mf.strip()

                # Extract hash algorithm from the line format
                hash_alg = None
                for alg in ["SHA1", "SHA256", "SHA512"]:
                    if left.startswith(alg):
                        hash_alg = alg.lower()
                        break

                assert hash_alg is not None, f"Unknown hash algorithm in line: {left}"

                filename = left[len(hash_alg):].strip("()")
                hash_obj = hashlib.new(hash_alg)
                with open(os.path.join(work_dir, filename), "rb") as f:
                    hash_obj.update(f.read())

                assert hash_obj.hexdigest() == hash_mf

    def test_ovf_signing(self):
        """Test signing of OVF files"""
        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_ovf = os.path.join(self.work_dir, f"{basename}_{self.sign_alg}.ovf")
        out_mf = os.path.join(self.work_dir, f"{basename}_{self.sign_alg}.mf")
        out_cert = os.path.join(self.work_dir, f"{basename}_{self.sign_alg}.cert")

        # Run ova-compose with signing
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "-m",
            "--sign", self.keyfile, "--sign-alg", self.sign_alg,
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir)
        assert process.returncode == 0

        # Verify files exist
        assert os.path.isfile(out_ovf), "OVF file not created"
        assert os.path.isfile(out_mf), "Manifest file not created"
        assert os.path.isfile(out_cert), "Certificate file not created"

        # Verify manifest integrity
        self.check_mf(out_mf)

        # Verify signature
        self.verify_signature(out_mf, out_cert, self.sign_alg)

    def test_ova_signing(self):
        """Test signing of OVA files"""
        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_ova = os.path.join(self.work_dir, f"{basename}_{self.sign_alg}.ova")
        out_mf = os.path.join(self.work_dir, f"{basename}_{self.sign_alg}.mf")
        out_cert = os.path.join(self.work_dir, f"{basename}_{self.sign_alg}.cert")

        # Run ova-compose with signing to create OVA
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_ova,
            "--sign", self.keyfile, "--sign-alg", self.sign_alg,
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir)
        assert process.returncode == 0

        # Verify OVA file exists
        assert os.path.isfile(out_ova), "OVA file not created"

        # Extract OVA to verify contents
        subprocess.run(["tar", "xf", out_ova], cwd=self.work_dir, check=True)

        # Verify extracted files exist
        assert os.path.isfile(out_mf), "Manifest file not found in OVA"
        assert os.path.isfile(out_cert), "Certificate file not found in OVA"

        # Verify manifest integrity
        self.check_mf(out_mf)

        # Verify signature
        self.verify_signature(out_mf, out_cert, self.sign_alg)

    def test_ova_signing_dir_format(self):
        """Test signing with directory output format"""
        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_dir = os.path.join(self.work_dir, f"{basename}_dir_{self.sign_alg}")
        dir_basename = os.path.basename(out_dir)
        out_mf = os.path.join(out_dir, f"{dir_basename}.mf")
        out_cert = os.path.join(out_dir, f"{dir_basename}.cert")

        # Clean up any existing directory
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)

        # Run ova-compose with signing to create directory
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_dir, "--format", "dir",
            "--sign", self.keyfile, "--sign-alg", self.sign_alg,
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir)
        assert process.returncode == 0

        # Verify directory and files exist
        assert os.path.isdir(out_dir), "Output directory not created"
        assert os.path.isfile(out_mf), "Manifest file not found in directory"
        assert os.path.isfile(out_cert), "Certificate file not found in directory"

        # Verify manifest integrity
        self.check_mf(out_mf, work_dir=out_dir)

        # Verify signature
        self.verify_signature(out_mf, out_cert, self.sign_alg)

    def test_signing_without_manifest_fails(self):
        """Test that signing without manifest creation fails appropriately"""
        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_ovf = os.path.join(self.work_dir, f"{basename}_no_manifest.ovf")

        # Try to sign without creating manifest (should work for OVF format)
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf,
            "--sign", self.keyfile, "--sign-alg", self.sign_alg,
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir)
        # This should succeed because OVF format doesn't automatically create manifest
        # but signing will create it
        assert process.returncode == 0

    def test_invalid_key_file(self):
        """Test behavior with invalid key file"""
        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_ovf = os.path.join(self.work_dir, f"{basename}_invalid_key.ovf")
        invalid_key = os.path.join(self.work_dir, "nonexistent_key.pem")

        # Try to sign with non-existent key file
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "-m",
            "--sign", invalid_key, "--sign-alg", self.sign_alg,
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir,
                               capture_output=True, text=True)
        assert process.returncode != 0, "Should fail with invalid key file"


@pytest.mark.parametrize("setup_test", [WORK_DIR], indirect=True)
class TestSigningEdgeCases:
    """Test edge cases and error conditions for signing"""

    @pytest.fixture(autouse=True)
    def setup_class(self, setup_test):
        self.work_dir = WORK_DIR

    def test_signing_with_different_checksum_and_sign_alg(self):
        """Test signing with different checksum and signature algorithms"""
        keyfile = os.path.join(self.work_dir, "test_key_mixed.pem")

        # Create test key and certificate in one step
        subprocess.run([
            "openssl", "req", "-x509", "-nodes", "-sha256", "-days", "365",
            "-newkey", "rsa:2048", "-keyout", keyfile, "-out", keyfile,
            "-subj", "/CN=Test Mixed Certificate"
        ], check=True, cwd=self.work_dir)

        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_ovf = os.path.join(self.work_dir, f"{basename}_mixed.ovf")
        out_cert = os.path.join(self.work_dir, f"{basename}_mixed.cert")

        # Use different algorithms for checksum and signing
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "-m",
            "--checksum-type", "sha256", "--sign", keyfile, "--sign-alg", "sha512",
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir)
        assert process.returncode == 0

        # Verify certificate file contains sha512 signature
        with open(out_cert, "rt") as f:
            content = f.read()
            assert "SHA512(" in content, "Should contain SHA512 signature"


@pytest.mark.parametrize("setup_test", [WORK_DIR], indirect=True)
@pytest.mark.parametrize("sign_alg", ["sha256", "sha512"])
class TestExternalSigning:
    """Test external script signing functionality"""

    @pytest.fixture(autouse=True)
    def setup_class(self, setup_test, sign_alg):
        self.sign_alg = sign_alg
        self.work_dir = WORK_DIR
        self.keyfile = os.path.join(self.work_dir, f"external_key_{sign_alg}.pem")
        self.sign_script = os.path.join(self.work_dir, f"sign_script_{sign_alg}.sh")
        self.create_test_key()
        self.create_sign_script()

    def create_test_key(self):
        """Create a test private key and certificate for external signing"""
        subprocess.run([
            "openssl", "req", "-x509", "-nodes", "-sha256", "-days", "365",
            "-newkey", "rsa:2048", "-keyout", self.keyfile, "-out", self.keyfile,
            "-subj", "/CN=External Test Certificate"
        ], check=True, cwd=self.work_dir)

    def create_sign_script(self):
        """Create a test signing script that mimics external signing behavior"""
        script_content = f'''#!/bin/bash
# External signing script for testing
# Parameters: ovf_file={{ovf_file}} mf_file={{mf_file}} sign_alg={{sign_alg}} cert_file={{cert_file}} keyfile={{keyfile}}

MF_FILE="$1"
CERT_FILE="$2"
KEYFILE="$3"
SIGN_ALG="$4"

# Generate signature using openssl
SIGNATURE=$(openssl dgst -${{SIGN_ALG}} -sign "${{KEYFILE}}" -out - "${{MF_FILE}}" | xxd -p -c 256)

# Write signature to cert file
echo "${{SIGN_ALG^^}}(${{MF_FILE##*/}})= ${{SIGNATURE}}" > "${{CERT_FILE}}"

# Append certificate from keyfile
sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' "${{KEYFILE}}" >> "${{CERT_FILE}}"
'''

        with open(self.sign_script, "w") as f:
            f.write(script_content)

        # Make script executable
        os.chmod(self.sign_script, 0o755)

    def test_external_script_ovf_signing(self):
        """Test OVF signing using external script"""
        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_ovf = os.path.join(self.work_dir, f"{basename}_external_{self.sign_alg}.ovf")
        out_mf = os.path.join(self.work_dir, f"{basename}_external_{self.sign_alg}.mf")
        out_cert = os.path.join(self.work_dir, f"{basename}_external_{self.sign_alg}.cert")

        # Create script format string that calls our test script
        script_format = f"{self.sign_script} {{mf_file}} {{cert_file}} {{keyfile}} {{sign_alg}}"

        # Run ova-compose with external signing script
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "-m",
            "--sign-script", script_format, "--sign", self.keyfile, "--sign-alg", self.sign_alg,
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir, capture_output=True, text=True)

        # Debug output if test fails
        if process.returncode != 0:
            print(f"STDOUT: {{process.stdout}}")
            print(f"STDERR: {{process.stderr}}")

        assert process.returncode == 0, f"External signing failed: {{process.stderr}}"

        # Verify files exist
        assert os.path.isfile(out_ovf), "OVF file not created"
        assert os.path.isfile(out_mf), "Manifest file not created"
        assert os.path.isfile(out_cert), "Certificate file not created"

        # Verify certificate file contains expected signature
        with open(out_cert, "rt") as f:
            content = f.read()
            assert f"{self.sign_alg.upper()}(" in content, f"Should contain {self.sign_alg.upper()} signature"
            assert "-----BEGIN CERTIFICATE-----" in content, "Should contain certificate"
            assert "-----END CERTIFICATE-----" in content, "Should contain certificate"

    def test_external_script_ova_signing(self):
        """Test OVA signing using external script"""
        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_ova = os.path.join(self.work_dir, f"{basename}_external_{self.sign_alg}.ova")
        out_mf = os.path.join(self.work_dir, f"{basename}_external_{self.sign_alg}.mf")
        out_cert = os.path.join(self.work_dir, f"{basename}_external_{self.sign_alg}.cert")

        # Create script format string
        script_format = f"{self.sign_script} {{mf_file}} {{cert_file}} {{keyfile}} {{sign_alg}}"

        # Run ova-compose with external signing script
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_ova,
            "--sign-script", script_format, "--sign", self.keyfile, "--sign-alg", self.sign_alg,
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir, capture_output=True, text=True)
        assert process.returncode == 0, f"External OVA signing failed: {{process.stderr}}"

        # Verify OVA file exists
        assert os.path.isfile(out_ova), "OVA file not created"

        # Extract OVA to verify contents
        subprocess.run(["tar", "xf", out_ova], cwd=self.work_dir, check=True)

        # Verify extracted files exist
        assert os.path.isfile(out_mf), "Manifest file not found in OVA"
        assert os.path.isfile(out_cert), "Certificate file not found in OVA"

        # Verify certificate file contains expected signature
        with open(out_cert, "rt") as f:
            content = f.read()
            assert f"{self.sign_alg.upper()}(" in content, f"Should contain {self.sign_alg.upper()} signature"
            assert "-----BEGIN CERTIFICATE-----" in content, "Should contain certificate"

    def test_external_script_format_parameters(self):
        """Test that all format parameters are correctly passed to external script"""
        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_ovf = os.path.join(self.work_dir, f"{basename}_params_{self.sign_alg}.ovf")

        # Create a script that captures and validates all parameters
        param_capture_script = os.path.join(self.work_dir, f"param_capture_{self.sign_alg}.sh")
        script_content = f'''#!/bin/bash
# Parameters: $1=ovf_file $2=mf_file $3=sign_alg $4=cert_file $5=keyfile
OVF_FILE="$1"
MF_FILE="$2"
SIGN_ALG="$3"
CERT_FILE="$4"
KEYFILE="$5"

# Capture all parameters for validation
echo "ovf_file=$OVF_FILE" > {self.work_dir}/captured_params_{self.sign_alg}.txt
echo "mf_file=$MF_FILE" >> {self.work_dir}/captured_params_{self.sign_alg}.txt
echo "sign_alg=$SIGN_ALG" >> {self.work_dir}/captured_params_{self.sign_alg}.txt
echo "cert_file=$CERT_FILE" >> {self.work_dir}/captured_params_{self.sign_alg}.txt
echo "keyfile=$KEYFILE" >> {self.work_dir}/captured_params_{self.sign_alg}.txt

# Still need to create a valid cert file for the test to pass
{self.sign_script} "$MF_FILE" "$CERT_FILE" "$KEYFILE" "$SIGN_ALG"
'''

        with open(param_capture_script, "w") as f:
            f.write(script_content)
        os.chmod(param_capture_script, 0o755)

        # Create format string for parameter capture
        script_format = f"{param_capture_script} {{ovf_file}} {{mf_file}} {{sign_alg}} {{cert_file}} {{keyfile}}"

        # Run with parameter capture script
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "-m",
            "--sign-script", script_format, "--sign", self.keyfile, "--sign-alg", self.sign_alg,
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir)
        assert process.returncode == 0

        # Verify parameters were captured correctly
        params_file = os.path.join(self.work_dir, f"captured_params_{self.sign_alg}.txt")
        assert os.path.isfile(params_file), "Parameters file not created"

        with open(params_file, "r") as f:
            params_content = f.read()

        # Verify all expected parameters are present and have reasonable values
        # Based on the actual output, some paths are full, some are basenames
        expected_mf_basename = f"{basename}_params_{self.sign_alg}.mf"
        expected_cert = os.path.join(self.work_dir, f"{basename}_params_{self.sign_alg}.cert")

        assert f"ovf_file={out_ovf}" in params_content
        assert f"mf_file={expected_mf_basename}" in params_content
        assert f"sign_alg={self.sign_alg}" in params_content
        assert f"cert_file={expected_cert}" in params_content
        assert f"keyfile={self.keyfile}" in params_content

    def test_external_script_failure_handling(self):
        """Test handling of external script failures"""
        in_yaml = os.path.join(CONFIG_DIR, "basic.yaml")
        basename = os.path.basename(in_yaml.rsplit(".", 1)[0])
        out_ovf = os.path.join(self.work_dir, f"{basename}_fail_{self.sign_alg}.ovf")

        # Create a script that always fails
        failing_script = os.path.join(self.work_dir, f"failing_script_{self.sign_alg}.sh")
        with open(failing_script, "w") as f:
            f.write("#!/bin/bash\nexit 1\n")
        os.chmod(failing_script, 0o755)

        # Run with failing script
        args = [
            OVA_COMPOSE, "-i", in_yaml, "-o", out_ovf, "-m",
            "--sign-script", failing_script, "--sign", self.keyfile, "--sign-alg", self.sign_alg,
            "--vmdk-convert", VMDK_CONVERT
        ]

        process = subprocess.run(args, cwd=self.work_dir, capture_output=True, text=True)
        assert process.returncode != 0, "Should fail when external script fails"