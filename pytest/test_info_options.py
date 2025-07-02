# Copyright (c) 2025 Broadcom.  All Rights Reserved.
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


import json
import os
import pytest
import shutil
import subprocess


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
VMDK_CONVERT = os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")
WORK_DIR = os.path.join(os.getcwd(), "pytest-info")


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)

    # Create a small raw disk image for testing
    process = subprocess.run(["dd", "if=/dev/zero", "of=test.img", "bs=1024", "count=1024"], cwd=WORK_DIR)
    assert process.returncode == 0

    # Create a sparse VMDK from the raw image
    process = subprocess.run([VMDK_CONVERT, "test.img", "test.vmdk"], cwd=WORK_DIR)
    assert process.returncode == 0

    # Create a mixed content file for more realistic testing
    cmd = "( dd if=/dev/zero count=512 bs=1024 ; dd if=/dev/random count=256 bs=1024 ; dd if=/dev/zero count=256 bs=1024 ) > mixed.img"
    process = subprocess.run(["/bin/sh", "-c", cmd], cwd=WORK_DIR)
    assert process.returncode == 0

    # Convert mixed content to sparse VMDK
    process = subprocess.run([VMDK_CONVERT, "mixed.img", "mixed.vmdk"], cwd=WORK_DIR)
    assert process.returncode == 0

    yield
    # Cleanup commented out for debugging, uncomment if needed
    # shutil.rmtree(WORK_DIR)


def test_info_option_basic(setup_test):
    """Test basic -i option functionality"""
    process = subprocess.run([VMDK_CONVERT, "-i", "test.vmdk"], 
                           cwd=WORK_DIR, capture_output=True, text=True)
    assert process.returncode == 0
    
    # Verify output is valid JSON
    try:
        data = json.loads(process.stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(f"Output is not valid JSON: {process.stdout}")
    
    # Verify required fields are present
    assert "capacity" in data
    assert "used" in data
    assert isinstance(data["capacity"], int)
    assert isinstance(data["used"], int)
    assert data["capacity"] > 0
    assert data["used"] >= 0


def test_info_option_with_flat_file(setup_test):
    """Test -i option with flat (non-sparse) file"""
    process = subprocess.run([VMDK_CONVERT, "-i", "test.img"], 
                           cwd=WORK_DIR, capture_output=True, text=True)
    assert process.returncode == 0
    
    # Verify output is valid JSON
    data = json.loads(process.stdout.strip())
    
    # For flat files, capacity should equal used space
    assert data["capacity"] == data["used"]
    assert data["capacity"] == 1024 * 1024  # 1MB file


def test_detailed_option_with_sparse_vmdk(setup_test):
    """Test --detailed option with sparse VMDK file"""
    process = subprocess.run([VMDK_CONVERT, "-i", "--detailed", "test.vmdk"], 
                           cwd=WORK_DIR, capture_output=True, text=True)
    assert process.returncode == 0
    
    # Verify output is valid JSON
    data = json.loads(process.stdout.strip())
    
    # Verify basic fields
    assert "capacity" in data
    assert "used" in data
    
    # Verify sparse header information is present
    assert "sparseHeader" in data
    header = data["sparseHeader"]
    
    # Verify all expected sparse header fields
    required_fields = [
        "version", "flags", "flagsDecoded", "numGTEsPerGT", 
        "compressAlgorithm", "compressAlgorithmName", "uncleanShutdown",
        "grainSize", "grainSizeBytes", "descriptorOffset", "descriptorSize",
        "rgdOffset", "gdOffset", "overHead"
    ]
    
    for field in required_fields:
        assert field in header, f"Missing field: {field}"
    
    # Verify flag decoding structure
    flags_decoded = header["flagsDecoded"]
    expected_flag_fields = ["validNewlineDetector", "useRedundant", "compressed", "embeddedLBA"]
    for field in expected_flag_fields:
        assert field in flags_decoded, f"Missing flag field: {field}"
        assert isinstance(flags_decoded[field], bool)
    
    # Verify data types and ranges
    assert isinstance(header["version"], int)
    assert isinstance(header["flags"], int)
    assert isinstance(header["numGTEsPerGT"], int)
    assert isinstance(header["compressAlgorithm"], int)
    assert header["compressAlgorithmName"] in ["none", "deflate", "unknown"]
    assert isinstance(header["uncleanShutdown"], int)
    assert isinstance(header["grainSize"], int)
    assert isinstance(header["grainSizeBytes"], int)
    assert header["grainSizeBytes"] == header["grainSize"] * 512  # Verify calculation
    

def test_detailed_option_with_mixed_content(setup_test):
    """Test --detailed option with mixed content VMDK file"""
    process = subprocess.run([VMDK_CONVERT, "-i", "--detailed", "mixed.vmdk"], 
                           cwd=WORK_DIR, capture_output=True, text=True)
    assert process.returncode == 0
    
    data = json.loads(process.stdout.strip())
    
    # Verify sparse VMDK has less used space than capacity (due to zero blocks)
    assert data["used"] < data["capacity"]
    
    # Verify detailed header is present
    assert "sparseHeader" in data
    header = data["sparseHeader"]
    
    # Verify compression is enabled for this file
    assert header["flagsDecoded"]["compressed"] is True
    assert header["compressAlgorithmName"] == "deflate"


def test_detailed_option_with_flat_file(setup_test):
    """Test --detailed option with flat (non-sparse) file"""
    process = subprocess.run([VMDK_CONVERT, "-i", "--detailed", "test.img"], 
                           cwd=WORK_DIR, capture_output=True, text=True)
    assert process.returncode == 0
    
    data = json.loads(process.stdout.strip())
    
    # Verify basic fields
    assert "capacity" in data
    assert "used" in data
    
    # Verify error message for non-sparse files
    assert "error" in data
    assert "detailed information only available for sparse VMDK files" in data["error"]


def test_detailed_option_without_info_fails(setup_test):
    """Test that --detailed option fails when used without -i"""
    process = subprocess.run([VMDK_CONVERT, "--detailed", "test.vmdk"], 
                           cwd=WORK_DIR, capture_output=True, text=True)
    assert process.returncode == 1
    assert "--detailed can only be used with -i option" in process.stderr


def test_info_option_nonexistent_file(setup_test):
    """Test -i option with nonexistent file"""
    process = subprocess.run([VMDK_CONVERT, "-i", "nonexistent.vmdk"], 
                           cwd=WORK_DIR, capture_output=True, text=True)
    # The application prints error to stderr but still returns 0
    assert process.returncode == 0
    assert "Cannot open source disk" in process.stderr
    assert process.stdout.strip() == ""  # No output to stdout when file can't be opened


def test_detailed_option_comprehensive_values(setup_test):
    """Test that --detailed option returns reasonable values"""
    process = subprocess.run([VMDK_CONVERT, "-i", "--detailed", "test.vmdk"], 
                           cwd=WORK_DIR, capture_output=True, text=True)
    assert process.returncode == 0
    
    data = json.loads(process.stdout.strip())
    header = data["sparseHeader"]
    
    # Test specific value ranges and relationships
    assert header["version"] >= 1  # Version should be at least 1
    assert header["numGTEsPerGT"] > 0  # Should have some GTEs per GT
    assert header["grainSize"] > 0  # Grain size should be positive
    assert header["grainSize"] <= 128  # Typical maximum grain size
    assert header["descriptorSize"] > 0  # Should have a descriptor
    assert header["overHead"] >= header["descriptorOffset"] + header["descriptorSize"]  # Overhead should include descriptor
    
    # Test flag consistency
    if header["flagsDecoded"]["compressed"]:
        assert header["compressAlgorithm"] != 0  # Should have compression algorithm if compressed
    
    if header["flagsDecoded"]["embeddedLBA"]:
        assert header["flagsDecoded"]["compressed"]  # Embedded LBA requires compression


def test_json_output_format_consistency(setup_test):
    """Test that JSON output format is consistent between -i and -i --detailed"""
    # Test basic -i output
    process1 = subprocess.run([VMDK_CONVERT, "-i", "test.vmdk"], 
                             cwd=WORK_DIR, capture_output=True, text=True)
    assert process1.returncode == 0
    data1 = json.loads(process1.stdout.strip())
    
    # Test -i --detailed output
    process2 = subprocess.run([VMDK_CONVERT, "-i", "--detailed", "test.vmdk"], 
                             cwd=WORK_DIR, capture_output=True, text=True)
    assert process2.returncode == 0
    data2 = json.loads(process2.stdout.strip())
    
    # Verify basic fields are the same
    assert data1["capacity"] == data2["capacity"]
    assert data1["used"] == data2["used"]
    
    # Verify detailed output has additional sparseHeader field
    assert "sparseHeader" not in data1
    assert "sparseHeader" in data2


def test_help_option_includes_detailed(setup_test):
    """Test that help output includes the --detailed option"""
    process = subprocess.run([VMDK_CONVERT, "--help"], 
                           cwd=WORK_DIR, capture_output=True, text=True)
    assert process.returncode == 1  # Help exits with code 1
    assert "--detailed" in process.stdout
    assert "detailed sparse extent header information" in process.stdout 