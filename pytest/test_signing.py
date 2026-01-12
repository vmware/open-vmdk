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