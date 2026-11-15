#!/usr/bin/env bash
# Publica el .deb de la versión actual en el repositorio apt de SRI (rama gh-pages -> GitHub Pages).
# Después, en cualquier computadora con SRI instalado:  sudo apt update && sudo apt upgrade
#
#   empaquetar/construir.sh      # primero construir la versión
#   empaquetar/publicar.sh       # firma el índice y sube la rama gh-pages (pide usuario y token de GitHub)
#
# La llave de firma vive en ~/.config/sri-firma (NO se sube). Respáldala: sin ella no se pueden publicar
# actualizaciones que las computadoras acepten.
set -euo pipefail
umask 022

AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/.." && pwd)"
VERSION="$(grep -oP 'VERSION = "\K[^"]+' "$RAIZ/sri_config.py")"
export GNUPGHOME="${SRI_FIRMA:-$HOME/.config/sri-firma}"
W="$AQUI/build/gh-pages"
CONSERVAR=3                                        # versiones que se quedan en el repositorio por arquitectura

DEBS=("$AQUI"/dist/sri_"${VERSION}"_*.deb)
[ -e "${DEBS[0]}" ] || { echo "No hay paquete de la versión $VERSION. Corre primero empaquetar/construir.sh"; exit 1; }
gpg --list-secret-keys "SRI paquetes" >/dev/null 2>&1 || { echo "No está la llave de firma en $GNUPGHOME"; exit 1; }

cd "$RAIZ"
echo "== Rama gh-pages"
git fetch -q origin gh-pages 2>/dev/null || true
git worktree remove --force "$W" 2>/dev/null || rm -rf "$W"
git worktree prune
if git show-ref --verify --quiet refs/remotes/origin/gh-pages; then
  git worktree add -q --detach "$W" origin/gh-pages
else
  git worktree add -q --detach "$W"
  git -C "$W" rm -rq --ignore-unmatch .
fi

echo "== Paquetes"
cp "${DEBS[@]}" "$W/"
cd "$W"
for arq in $(ls sri_*_*.deb | sed -E 's/.*_([a-z0-9]+)\.deb/\1/' | sort -u); do
  ls sri_*_"$arq".deb | sort -V | head -n -"$CONSERVAR" | xargs -r rm -f      # quitar las más viejas
done
ls -1 sri_*.deb

echo "== Índice firmado"
apt-ftparchive packages . > Packages
gzip -9kf Packages
apt-ftparchive -o APT::FTPArchive::Release::Origin="SRI" -o APT::FTPArchive::Release::Label="SRI" \
  -o APT::FTPArchive::Release::Description="Sistema de Respuesta Inmediata (github.com/emiliosea/sri)" \
  release . > Release
gpg --batch --yes --local-user "SRI paquetes" --clearsign -o InRelease Release
gpg --batch --yes --local-user "SRI paquetes" -abs -o Release.gpg Release
cp "$AQUI/apt/sri-archive-keyring.gpg" "$AQUI/apt/sri-archive-keyring.asc" "$AQUI/apt/sri.sources" .
touch .nojekyll
cat > index.html <<EOF
<!doctype html><meta charset="utf-8"><title>SRI - repositorio apt</title>
<pre>SRI - Sistema de Respuesta Inmediata: repositorio apt (versión más reciente: $VERSION)

Primera instalación (después se actualiza con: sudo apt update &amp;&amp; sudo apt upgrade):

  sudo curl -fsSLo /usr/share/keyrings/sri-archive-keyring.gpg https://emiliosea.github.io/sri/sri-archive-keyring.gpg
  sudo curl -fsSLo /etc/apt/sources.list.d/sri.sources https://emiliosea.github.io/sri/sri.sources
  sudo apt update &amp;&amp; sudo apt install sri

Código: https://github.com/emiliosea/sri</pre>
EOF

echo "== Commit (la rama gh-pages se reescribe en un solo commit para no crecer con cada versión)"
git checkout -q --orphan "publicar-$$"
git add -A
git -c user.name="$(git -C "$RAIZ" config user.name)" -c user.email="$(git -C "$RAIZ" config user.email)" \
  commit -q -m "Repositorio apt: SRI $VERSION"
git branch -f gh-pages HEAD
cd "$RAIZ"
echo "== Subir (usuario de GitHub y token)"
git push -f origin gh-pages
git worktree remove --force "$W"
echo "Publicado SRI $VERSION. En las computadoras: sudo apt update && sudo apt upgrade"
