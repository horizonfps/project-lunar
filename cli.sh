#!/bin/bash
set -e

VERSION=${VERSION:-latest}
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

case "$ARCH" in
x86_64) ARCH="amd64" ;;
arm64|aarch64) ARCH="arm64" ;;
*) echo "unsupported architecture: $ARCH" && exit 1 ;;
esac

# set install dir
if [ "$(id -u)" -ne 0 ] && [ -z "$INSTALL_DIR" ]; then
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
add_path() { [ -f "$1" ] && grep -q '\.local/bin' "$1" || echo "$PATH_LINE" >> "$1"; }
if [ "$OS" = "darwin" ]; then
add_path "$HOME/.zshrc"
add_path "$HOME/.bash_profile"
else
add_path "$HOME/.bashrc"
fi

export PATH="$INSTALL_DIR:$PATH"
else
INSTALL_DIR=${INSTALL_DIR:-/usr/local/bin}
fi

# resolve download url
if [ "$VERSION" = "latest" ]; then
URL=$(curl -fsSL https://dist.inference.sh/cli/manifest.json | grep -o "\"$OS-$ARCH\":{[^}]*}" | grep -o 'https[^"]*')
else
URL="https://dist.inference.sh/cli/inferencesh-cli-${VERSION}-${OS}-${ARCH}.tar.gz"
fi

NAME=$(basename "$URL" .tar.gz)
TARBALL_NAME=$(basename "$URL")
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "downloading cli $VERSION for $OS-$ARCH..."
curl -fsSL "$URL" -o "$TMP/$TARBALL_NAME"

# verify checksum
echo "verifying checksum..."
curl -fsSL https://dist.inference.sh/cli/checksums.txt -o "$TMP/checksums.txt"
EXPECTED=$(grep "$TARBALL_NAME" "$TMP/checksums.txt" | awk '{print $1}')
if [ -z "$EXPECTED" ]; then
echo "warning: no checksum found for $TARBALL_NAME, skipping verification"
else
if command -v sha256sum >/dev/null 2>&1; then
ACTUAL=$(sha256sum "$TMP/$TARBALL_NAME" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
ACTUAL=$(shasum -a 256 "$TMP/$TARBALL_NAME" | awk '{print $1}')
else
echo "warning: no sha256sum or shasum found, skipping verification"
ACTUAL="$EXPECTED"
fi
if [ "$ACTUAL" != "$EXPECTED" ]; then
echo "error: checksum mismatch!"
echo " expected: $EXPECTED"
echo " got: $ACTUAL"
echo "the download may be corrupted or tampered with."
exit 1
fi
echo "checksum verified."
fi

# verify cosign signature on checksums (optional)
COSIGN_IDENTITY="${COSIGN_IDENTITY:-omerkarisman@gmail.com}"
COSIGN_OIDC_ISSUER="${COSIGN_OIDC_ISSUER:-https://github.com/login/oauth}"
DIST_BASE="https://dist.inference.sh/cli"

if command -v cosign >/dev/null 2>&1; then
echo "verifying signature..."
BUNDLE="$TMP/checksums.txt.bundle"
curl -fsSL "$DIST_BASE/checksums.txt.bundle" -o "$BUNDLE" 2>/dev/null && \
cosign verify-blob "$TMP/checksums.txt" \
--bundle "$BUNDLE" \
--certificate-identity="$COSIGN_IDENTITY" \
--certificate-oidc-issuer="$COSIGN_OIDC_ISSUER" && \
echo "signature verified." || \
echo "warning: signature verification failed, continuing with checksum-only."
fi

tar -xzf "$TMP/$TARBALL_NAME" -C "$TMP"
BIN="$TMP/$NAME"

chmod +x "$BIN"
rm -f "$INSTALL_DIR/inferencesh" "$INSTALL_DIR/infsh"
mv "$BIN" "$INSTALL_DIR/inferencesh"
ln -sf "$INSTALL_DIR/inferencesh" "$INSTALL_DIR/infsh"

echo "installed to $INSTALL_DIR"
echo "run 'inferencesh' or 'infsh'"