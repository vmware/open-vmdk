# GitHub Workflows for open-vmdk

This directory contains GitHub Actions workflows for building, testing, and releasing Debian packages for open-vmdk.

## Workflows

### 1. `debian-build-test.yml` - Build and Test Debian Packages

**Triggers:**
- Push to `main` or `master` branch
- Pull requests to `main` or `master` branch  
- Manual workflow dispatch

**What it does:**
- Builds Debian packages on multiple Ubuntu versions (20.04, 22.04, 24.04)
- Handles fakeroot issues by falling back to manual build method
- Tests package installation and basic functionality
- Runs lintian quality checks
- Uploads built packages as artifacts

**Matrix strategy:** Tests on Ubuntu 20.04, 22.04, and 24.04

### 2. `multi-arch-test.yml` - Multi-Architecture Package Test

**Triggers:**
- Push to `main` or `master` branch
- Push of version tags (`v*`)
- Pull requests to `main` or `master` branch
- Manual workflow dispatch

**What it does:**
- Builds and tests packages on multiple architectures (amd64, arm64)
- Uses Docker with QEMU for cross-architecture testing
- Verifies packages work correctly on different CPU architectures
- Uploads packages from amd64 build as artifacts

### 3. `release.yml` - Create Release Packages

**Triggers:**
- Push of version tags (`v*`)
- Manual workflow dispatch with tag input

**What it does:**
- Builds release-quality Debian packages
- Updates changelog with release version and date
- Runs quality checks with lintian
- Creates SHA256 checksums for packages

## Usage

### For Development

The build and test workflows run automatically on every push and pull request, ensuring packages build correctly across different environments.

### Downloading Artifacts

Built packages are available as workflow artifacts:
- Go to the Actions tab
- Click on a completed workflow run
- Download the "debian-packages-*" artifacts

## Environment Handling

The workflows handle common build environment issues:

- **Fakeroot problems:** Automatically falls back to manual build using sudo
- **Multi-architecture:** Uses QEMU for cross-compilation testing
- **Dependency resolution:** Installs all required build and runtime dependencies
- **Permission fixes:** Ensures proper file ownership after sudo operations

## Package Testing

Each workflow includes comprehensive testing:

1. **Build verification:** Ensures packages build successfully
2. **Content verification:** Checks package contents and metadata
3. **Installation testing:** Installs packages and resolves dependencies
4. **Functionality testing:** Tests that installed binaries work
5. **Configuration testing:** Verifies config files and directories are created
6. **Quality checks:** Runs lintian for Debian policy compliance

## Artifacts and Releases

- **Development builds:** Available as workflow artifacts (30-day retention)
- **Release builds:** Attached to GitHub releases with checksums
- **Build logs:** Available as artifacts when builds fail (7-day retention)

## Troubleshooting

If workflows fail:

1. Check the workflow logs for specific error messages
2. Common issues:
   - Dependency installation failures
   - Fakeroot/permission issues (handled automatically)
   - Network timeouts during package downloads
   - Architecture-specific build failures

3. Build logs and artifacts are preserved for debugging

## Customization

To customize the workflows:

- **Add new test platforms:** Modify the matrix strategy in `debian-build-test.yml`
- **Change retention periods:** Adjust `retention-days` in upload-artifact steps
- **Add new architectures:** Extend the arch matrix in `multi-arch-test.yml`
- **Modify release format:** Update the release body template in `release.yml`
