# Agate AutoPort

Al abrir Geometry Dash, busca mods cuyo `mod.json` apunte a una versión de GD anterior a la última y:

1. Descarga del Geode Index la versión del mod para la última GD (SHA-256 verificado).
2. Si es un mod solo de recursos, actualiza su `mod.json`.
3. (Opcional, ajustes) Intenta recompilarlo desde su repositorio.

Las versiones anteriores se guardan en `geode/agate/backups`.
Reversión: `agate-autoport rollback <id-del-mod>`.
