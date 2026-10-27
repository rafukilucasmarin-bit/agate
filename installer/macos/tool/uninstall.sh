#!/bin/bash
# Desinstala Agate/Geode de esta app. Se ejecuta desde <App>/Contents/Resources/agate/
set -euo pipefail
CONTENTS="$(cd "$(dirname "$0")/../.." && pwd)"
FW="$CONTENTS/Frameworks"
if [ -f "$FW/restore_fmod.dylib" ]; then
  cp -p "$FW/restore_fmod.dylib" "$FW/libfmod.dylib"
  rm -f "$FW/restore_fmod.dylib"
fi
rm -f "$FW/Geode.dylib" "$FW/GeodeBootstrapper.dylib"
rm -f "$CONTENTS/geode/mods/agate.autoport.geode"
rm -rf "$CONTENTS/Resources/agate"
echo "Agate/Geode desinstalado. Tus otros mods en Contents/geode/ no se han tocado."
