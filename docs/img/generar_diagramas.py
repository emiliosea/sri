"""Genera los diagramas del detector de caídas (SVG) para la documentación.

    python3 docs/img/generar_diagramas.py

Crea docs/img/algoritmo-flujo.svg y docs/img/algoritmo-senal.svg. Solo usa la biblioteca
estándar de Python. Colores del proyecto: blanco y negro + azul (resalto) y rojo (alertas).
"""

import math
import os
from xml.sax.saxutils import escape

AQUI = os.path.dirname(os.path.abspath(__file__))
FG, FG2, FG3, LINE, BG2 = "#000000", "#444444", "#777777", "#d0d0d0", "#f2f2f2"
BLUE, RED, RED_BG = "#0047ff", "#e00000", "#ffe5e5"
FONT = 'font-family="DejaVu Sans Mono, Menlo, Consolas, monospace"'


class Svg:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" {FONT}>',
                    f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
                    '<defs><marker id="f" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"'
                    f' orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{FG2}"/></marker></defs>']

    def add(self, s):
        self.out.append(s)

    def text(self, x, y, s, size=13, color=FG, anchor="middle", weight="normal"):
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}"'
                 f' font-weight="{weight}">{escape(s)}</text>')

    def line(self, pts, color=FG2, width=1.5, arrow=True, dash=None):
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        extra = ' marker-end="url(#f)"' if arrow else ""
        extra += f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<path d="{d}" stroke="{color}" stroke-width="{width}" fill="none"{extra}/>')

    def box(self, cx, y, w, lines, stroke=FG, fill="#ffffff", h=None, bold_first=False):
        h = h or 18 * len(lines) + 16
        self.add(f'<rect x="{cx - w / 2:.1f}" y="{y:.1f}" width="{w}" height="{h}" fill="{fill}"'
                 f' stroke="{stroke}" stroke-width="1.5"/>')
        color = "#ffffff" if fill in (RED, BLUE) else FG
        for i, s in enumerate(lines):
            self.text(cx, y + 22 + 18 * i, s, color=color, weight="bold" if bold_first and i == 0 else "normal")
        return y + h

    def diamond(self, cx, y, w, h, lines):
        self.add(f'<path d="M{cx},{y} L{cx + w / 2},{y + h / 2} L{cx},{y + h} L{cx - w / 2},{y + h / 2} Z"'
                 f' fill="{BG2}" stroke="{FG}" stroke-width="1.5"/>')
        for i, s in enumerate(lines):
            self.text(cx, y + h / 2 - 9 * (len(lines) - 1) + 18 * i + 5, s)
        return y + h

    def save(self, name):
        self.add("</svg>")
        with open(os.path.join(AQUI, name), "w", encoding="utf-8") as f:
            f.write("\n".join(self.out))


# ---------------------------------------------------------------------------
# 1) Diagrama de flujo del algoritmo
# ---------------------------------------------------------------------------
def flujo():
    s = Svg(900, 1170)
    cx = 360
    s.text(450, 32, "Detector de caídas y golpes - algoritmo en el nodo (firmware v1.18.0-rabanito)", 15, weight="bold")
    s.text(450, 52, "Corre dentro de RABANITO 50 veces por segundo; la interfaz solo lee el resultado.", 12, FG2)

    y = s.box(cx, 72, 400, ["1. Leer acelerómetro QMA6100P", "ejes x, y, z (rango ±32 g) cada 20 ms"])
    top_mid = 72 + 25
    s.line([(cx, y), (cx, y + 24)]); y += 24
    y = s.box(cx, y, 400, ["2. Corregir calibración por eje", "a = (crudo - offset) / ganancia"])
    s.line([(cx, y), (cx, y + 24)]); y += 24
    y = s.box(cx, y, 400, ["3. Magnitud  |a| = raíz(x² + y² + z²)", "(en reposo vale ~1 g: la gravedad)"])
    s.line([(cx, y), (cx, y + 24)]); y += 24
    y = s.box(cx, y, 400, ["4. Guardar |a| en el banco circular", "últimos 5 s = 250 lecturas"], stroke=BLUE)
    s.line([(cx, y), (cx, y + 24)]); y += 24

    # 5. ¿reposo?
    d5 = y
    y = s.diamond(cx, y, 500, 120, ["5. ¿Pasó de MOVIMIENTO a REPOSO?", "(máx - mín) del último segundo",
                                     "<= 0.15 g"])
    left = cx - 250
    s.line([(left, d5 + 60), (50, d5 + 60), (50, top_mid), (cx - 200, top_mid)])
    for i, t in enumerate(["no:", "siguiente", "lectura"]):
        s.text(58, d5 - 150 + 16 * i, t, 12, FG2, "start")
    s.line([(cx, y), (cx, y + 30)]); s.text(cx + 10, y + 20, "sí", 12, FG2, "start"); y += 30

    y = s.box(cx, y, 440, ["6. Revisar el banco de 5 s", "reposo = promedio del último segundo",
                            "pico   = |a| máximo del banco", "dif    = pico - reposo"])
    s.line([(cx, y), (cx, y + 24)]); y += 24

    # 7. ¿dif >= mínima?
    d7 = y
    y = s.diamond(cx, y, 400, 96, ["7. ¿dif >= dif. mínima?", "(ajustable desde la interfaz)"])
    nx = 750
    s.line([(cx + 200, d7 + 48), (nx, d7 + 48), (nx, d7 + 72)])
    s.text(cx + 212, d7 + 40, "no", 12, FG2, "start")
    s.box(nx, d7 + 72, 250, ["Se informa como", "'último movimiento'", "(no alerta)"])
    s.line([(cx, y), (cx, y + 30)]); s.text(cx + 10, y + 20, "sí", 12, FG2, "start"); y += 30

    # 8. ¿caída libre antes del pico?
    d8 = y
    w8 = 500
    y = s.diamond(cx, y, w8, 110, ["8. ¿Hubo caída libre ANTES del pico?", ">= 3 lecturas seguidas (60 ms)",
                                    "con |a| < 0.35 g"])
    lx, rx = cx - w8 / 2, cx + w8 / 2
    yb = y + 20
    s.line([(lx, d8 + 55), (lx, yb)]); s.text(lx - 8, d8 + 48, "sí", 12, FG2, "end")
    s.line([(rx, d8 + 55), (rx, yb)]); s.text(rx + 8, d8 + 48, "no", 12, FG2, "start")
    s.box(lx, yb, 190, ["CAÍDA"], stroke=RED, fill=RED, h=40, bold_first=True)
    s.box(rx, yb, 190, ["GOLPE"], stroke=RED, fill=RED, h=40, bold_first=True)
    yc = yb + 40

    # 9. alarma enganchada
    y9 = yc + 34
    s.line([(lx, yc), (lx, y9 + 34), (cx - 220, y9 + 34)])
    s.line([(rx, yc), (rx, y9 + 34), (cx + 220, y9 + 34)])
    y = s.box(cx, y9, 440, ["9. Alarma ENGANCHADA en el nodo", "tipo, pico, reposo, dif, hora, cuenta",
                             "se vacía el banco (no contar dos veces)"], stroke=RED, fill=RED_BG)
    s.line([(cx, y), (cx, y + 24)]); y += 24
    y = s.box(cx, y, 520, ["10. La interfaz lee el nodo cada 1 s (USB o Bluetooth)",
                            "foco rojo + sonido + evento guardado + ruta en el mapa",
                            "hasta que se presiona 'Borrar alarma'"], stroke=BLUE)
    s.text(450, y + 40, "Parámetros: 50 Hz | banco 5 s | reposo <= 0.15 g en 1 s | caída libre < 0.35 g por 60 ms"
                        " | dif. mínima ajustable", 11, FG2)
    s.h = y + 60
    s.out[0] = s.out[0].replace('height="1170" viewBox="0 0 900 1170"', f'height="{s.h:.0f}" viewBox="0 0 900 {s.h:.0f}"')
    s.out[1] = f'<rect width="900" height="{s.h:.0f}" fill="#ffffff"/>'
    s.save("algoritmo-flujo.svg")


# ---------------------------------------------------------------------------
# 2) Señal de ejemplo: cómo se ve una caída y qué mide el algoritmo
# ---------------------------------------------------------------------------
def senal_ejemplo():
    """|a| (g) cada 20 ms: movimiento, caída libre, impacto, rebotes y reposo (datos ilustrativos)."""
    pts = []
    for i in range(0, 300):           # 6 s a 50 Hz
        t = i * 0.02
        if t < 1.2:                   # en la mano, moviéndose un poco
            g = 1.0 + 0.18 * math.sin(t * 9) + 0.06 * math.sin(t * 23)
        elif t < 1.6:                 # caída libre (~0.4 s ~ 80 cm)
            g = 0.08 + 0.03 * math.sin(t * 40)
        elif t < 1.62:
            g = 9.4                   # impacto
        elif t < 2.4:                 # rebotes que se apagan
            k = (t - 1.62) / 0.78
            g = 1.0 + 3.2 * math.exp(-4 * k) * abs(math.sin(t * 28))
        else:                         # en reposo en el suelo
            g = 1.02 + 0.01 * math.sin(t * 13)
        pts.append((t, g))
    return pts


def senal():
    s = Svg(900, 470)
    L, R, T, B = 70, 30, 60, 70
    pw, ph = 900 - L - R, 470 - T - B
    tmax, gmax = 6.0, 10.0
    X = lambda t: L + t / tmax * pw          # noqa: E731
    Y = lambda g: T + ph - g / gmax * ph     # noqa: E731

    s.text(450, 26, "Ejemplo de una caída: qué mide el detector", 15, weight="bold")
    s.text(450, 44, "|a| en g contra tiempo (datos ilustrativos, 50 lecturas por segundo)", 12, FG2)
    # rejilla
    for g in range(0, 11, 2):
        s.line([(L, Y(g)), (L + pw, Y(g))], LINE, 1, arrow=False)
        s.text(L - 8, Y(g) + 4, f"{g} g", 11, FG3, "end")
    for t in range(0, 7):
        s.text(X(t), T + ph + 18, f"{t} s", 11, FG3)

    # banco de 5 s al momento de evaluar (t = 5.9 s: ya lleva 1 s en reposo)
    t_eval = 5.9
    x0, x1 = X(t_eval - 5), X(t_eval)
    s.add(f'<rect x="{x0:.1f}" y="{T}" width="{x1 - x0:.1f}" height="{ph}" fill="{BLUE}" opacity="0.06"/>')
    s.line([(x0, T + ph + 30), (x1, T + ph + 30)], BLUE, 1.5, arrow=False)
    s.line([(x0, T + ph + 25), (x0, T + ph + 35)], BLUE, 1.5, arrow=False)
    s.line([(x1, T + ph + 25), (x1, T + ph + 35)], BLUE, 1.5, arrow=False)
    s.text((x0 + x1) / 2, T + ph + 48, "banco de 5 s que se revisa al quedar en reposo", 12, BLUE)

    # ventana de reposo (último segundo)
    xr0 = X(t_eval - 1)
    s.add(f'<rect x="{xr0:.1f}" y="{Y(1.6):.1f}" width="{x1 - xr0:.1f}" height="{Y(0.4) - Y(1.6):.1f}"'
          f' fill="none" stroke="{FG2}" stroke-dasharray="4 3"/>')
    s.text((xr0 + x1) / 2, Y(1.6) - 8, "reposo = promedio 1 s", 12, FG2)
    s.text((xr0 + x1) / 2, Y(1.6) - 24, "(máx - mín <= 0.15 g)", 11, FG3)

    # zona de caída libre
    s.add(f'<rect x="{X(1.2):.1f}" y="{Y(0.35):.1f}" width="{X(1.6) - X(1.2):.1f}" height="{Y(0) - Y(0.35):.1f}"'
          f' fill="{RED}" opacity="0.15"/>')
    s.line([(L, Y(0.35)), (L + pw, Y(0.35))], RED, 1, arrow=False, dash="2 3")
    s.text(L + 4, Y(0.35) - 5, "0.35 g", 11, RED, "start")
    s.text(X(0.75), Y(3.0), "caída libre", 12, RED)
    s.text(X(0.75), Y(3.0) + 15, "|a| ~ 0 g (< 0.35 g)", 11, RED)
    s.line([(X(0.95), Y(3.0) + 22), (X(1.35), Y(0.45))], RED, 1, arrow=True)

    # señal
    d = "M" + " L".join(f"{X(t):.1f},{Y(g):.1f}" for t, g in senal_ejemplo())
    s.add(f'<path d="{d}" stroke="{BLUE}" stroke-width="2" fill="none" stroke-linejoin="round"/>')

    # pico y diferencia
    tp, gp, rest = 1.61, 9.4, 1.02
    s.add(f'<circle cx="{X(tp):.1f}" cy="{Y(gp):.1f}" r="5" fill="{RED}" stroke="#ffffff" stroke-width="2"/>')
    s.text(X(tp) - 10, Y(gp) + 4, "pico = 9.40 g", 12, FG, "end", "bold")
    xd = X(3.4)
    s.line([(X(tp) + 6, Y(gp)), (xd, Y(gp))], FG3, 1, arrow=False, dash="3 3")
    s.line([(xd, Y(rest)), (xd, Y(gp))], FG, 1.5, arrow=True)
    s.line([(xd, Y(gp)), (xd, Y(rest))], FG, 1.5, arrow=True)
    s.text(xd + 10, (Y(gp) + Y(rest)) / 2 - 6, "dif = pico - reposo", 12, FG, "start", "bold")
    s.text(xd + 10, (Y(gp) + Y(rest)) / 2 + 10, "= 9.40 - 1.02 = 8.38 g", 12, FG, "start")
    s.text(xd + 10, (Y(gp) + Y(rest)) / 2 + 28, "si dif >= dif. mínima -> ALERTA", 12, RED, "start")
    s.text(xd + 10, (Y(gp) + Y(rest)) / 2 + 44, "hubo caída libre antes -> CAÍDA", 12, RED, "start")
    s.line([(X(t_eval), Y(0.1)), (X(t_eval), Y(rest) + 6)], FG2, 1.5)
    s.text(X(t_eval) - 6, Y(0.1), "se evalúa aquí", 11, FG2, "end")
    s.save("algoritmo-senal.svg")


if __name__ == "__main__":
    flujo()
    senal()
    print("ok: algoritmo-flujo.svg, algoritmo-senal.svg")
