#!/usr/bin/env bash
# Construye el programa SRI empaquetado (PyInstaller) y el paquete .deb para esta arquitectura.
#
#   empaquetar/construir.sh            -> dist/sri/ (programa) y dist/sri_<versión>_<arq>.deb
#
# Requiere: uv, dpkg-deb. La primera vez crea empaquetar/.venv-build con las dependencias y PyInstaller.
set -euo pipefail
umask 022

AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/.." && pwd)"
VERSION="$(grep -oP 'VERSION = "\K[^"]+' "$RAIZ/sri_config.py")"
ARQ="$(dpkg --print-architecture)"            # amd64 o arm64
VENV="$AQUI/.venv-build"
TRABAJO="$AQUI/build"
DIST="$AQUI/dist"

if [ ! -x "$VENV/bin/pyinstaller" ]; then
  uv venv -q "$VENV"
  uv pip install -q -p "$VENV" -r "$RAIZ/requirements.txt" pyinstaller
fi

echo "== PyInstaller (SRI $VERSION, $ARQ)"
rm -rf "$TRABAJO" "$DIST/sri"
cd "$RAIZ"
"$VENV/bin/pyinstaller" server.py --name sri --onedir --noconfirm --clean \
  --distpath "$DIST" --workpath "$TRABAJO" --specpath "$TRABAJO" \
  --add-data "$RAIZ/static:static" \
  --collect-submodules bleak --collect-submodules dbus_fast \
  --collect-all meshcore --collect-submodules meshtastic \
  --log-level WARN

echo "== Paquete .deb"
PKG="$TRABAJO/deb"
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/lib/systemd/system" "$PKG/etc/sri" \
         "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/scalable/apps"
cp -a "$DIST/sri" "$PKG/opt/sri"
for x in sri-app sri-kiosco sri-estacion; do
  install -m 755 "$AQUI/$x" "$PKG/opt/sri/$x"
  ln -s "/opt/sri/$x" "$PKG/usr/bin/$x"
done
ln -s /opt/sri/sri "$PKG/usr/bin/sri"
install -m 644 "$AQUI/sri-kiosco.desktop" "$PKG/opt/sri/sri-kiosco.desktop"    # lo usa sri-estacion activar
install -m 644 "$AQUI/sri.service" "$PKG/lib/systemd/system/sri.service"
install -m 644 "$AQUI/config.toml" "$PKG/etc/sri/config.toml"
install -m 644 "$AQUI/sri.desktop" "$PKG/usr/share/applications/sri.desktop"
install -m 644 "$AQUI/iconos/sri.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/sri.svg"
install -D -m 644 "$AQUI/iconos/sri-symbolic.svg" "$PKG/usr/share/icons/hicolor/symbolic/apps/sri-symbolic.svg"
for s in postinst prerm postrm; do install -m 755 "$AQUI/debian/$s" "$PKG/DEBIAN/$s"; done
echo "/etc/sri/config.toml" > "$PKG/DEBIAN/conffiles"
chmod -R go-w "$PKG"
TAM="$(du -sk "$PKG" | cut -f1)"
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARQ@/$ARQ/" -e "s/@TAM@/$TAM/" "$AQUI/debian/control" > "$PKG/DEBIAN/control"
mkdir -p "$DIST"
dpkg-deb --root-owner-group --build "$PKG" "$DIST/sri_${VERSION}_${ARQ}.deb" >/dev/null
echo "Listo: $DIST/sri/sri  y  $DIST/sri_${VERSION}_${ARQ}.deb"
