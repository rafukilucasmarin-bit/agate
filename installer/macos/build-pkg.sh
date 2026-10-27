#!/bin/bash
# Uso: build-pkg.sh <payload-mac-dir> <agate-autoport> <agate.autoport.geode> <version> <salida.pkg>
# Requiere macOS (pkgbuild / productbuild).
set -euo pipefail
PAYLOAD="$1"; AUTOPORT="$2"; MOD="$3"; VERSION="$4"; OUT="$5"
HERE="$(cd "$(dirname "$0")" && pwd)"
STAGE="$(mktemp -d)"
ROOT="$STAGE/root/usr/local/share/agate"
mkdir -p "$ROOT/payload" "$ROOT/tool"

cp -R "$PAYLOAD/." "$ROOT/payload/"
cp "$AUTOPORT" "$ROOT/tool/agate-autoport"
cp "$MOD" "$ROOT/tool/agate.autoport.geode"
cp "$HERE/tool/uninstall.sh" "$ROOT/tool/uninstall.sh"
chmod 755 "$ROOT/tool/agate-autoport" "$ROOT/tool/uninstall.sh" "$HERE/scripts/postinstall"

pkgbuild --root "$STAGE/root" \
         --identifier io.github.agate.loader \
         --version "$VERSION" \
         --install-location / \
         --scripts "$HERE/scripts" \
         "$STAGE/agate-component.pkg"

sed "s/@VERSION@/$VERSION/g" "$HERE/distribution.xml" > "$STAGE/distribution.xml"
productbuild --distribution "$STAGE/distribution.xml" \
             --resources "$HERE/resources" \
             --package-path "$STAGE" \
             "$OUT"

# Opcional: firmar con un certificado "Developer ID Installer" (y luego notarizar con notarytool)
if [ -n "${MACOS_INSTALLER_IDENTITY:-}" ]; then
  productsign --sign "$MACOS_INSTALLER_IDENTITY" "$OUT" "$OUT.signed" && mv "$OUT.signed" "$OUT"
fi
echo "Creado: $OUT"
