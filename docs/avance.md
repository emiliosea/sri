# Avance del proyecto

Bitácora por etapas del desarrollo del Sistema de Respuesta Inmediata (SRI) con el nodo **RABANITO**
(Seeed SenseCAP T1000-E). Fechas en hora de Monterrey (CST).

| Etapa | Fecha | Resultado |
|---|---|---|
| 1. Interfaz base con Meshtastic (USB) | 5 nov 2026 | Mapa, telemetría y ping funcionando |
| 2. Bluetooth y "visto por última vez" | 5-6 nov 2026 | Conexión inalámbrica estable; última posición guardada |
| 3. Migración a MeshCore | 9 nov 2026 | Nodo con MeshCore v1.18.0; radio en 915 MHz |
| 4. Detector de caídas (v1) | 9 nov 2026 | Firmware propio que usa el acelerómetro |
| 5. Detector v2, gráfica y calibración | 9-10 nov 2026 | Algoritmo pico - reposo, ±32 g, calibración de 6 caras |
| 6. Ruta, interfaz tipo Excel y GitHub | 10 nov 2026 | Ruta automática, eventos en CSV, repositorio público |
| 7. Terreno y elevación | 10-11 nov 2026 | Relieve 3D (curvas + mapa), alturas y perfil de la ruta |
| 8. Información ambiental | 12 nov 2026 | Cuerpos de agua en el terreno y cuáles cruza la ruta |
| 9. Clima | 12 nov 2026 | Clima en el nodo (Open-Meteo) con avisos para salir a campo |
| 10. Programa para la estación (fase 1) | 12 nov 2026 | Paquete .deb con servicio systemd y pantalla completa |
| 11. Sin internet (fase 3) | 13 nov 2026 | Paquete de región de La Huasteca: mapa, relieve, agua y clima guardado |
| 12. Actualizaciones y "Actualizar todo" | 14 nov 2026 | Repositorio apt firmado (sudo apt upgrade) y botón para refrescar todo |
| 13. Modos y Red LoRa | 15 nov 2026 | Tiempo real / Demo desde la interfaz; agregar y quitar nodos de la red LoRa |
| 14. Alertas por LoRa | 15 nov 2026 | El nodo de campo manda su caída por radio a la base (firmware sri2) |
| 15. Ventana nativa | 15 nov 2026 | SRI sin navegador: ventana propia GTK + WebKit |

---

## Etapa 1 - Interfaz base con Meshtastic por USB (5 nov)

- Servidor en Python (Flask) con la librería oficial `meshtastic`; página web con mapa Leaflet.
- Modo **demo** con nodos simulados para trabajar sin hardware.
- Coordenadas en decimal y grados/minutos/segundos, con botones Copiar y Google Maps.
- **Ping** al nodo con prueba de que la respuesta es real: el ID del paquete de respuesta coincide con el enviado.
- Uptime en vivo e información del dispositivo (ID único del chip, MAC, firmware, radio).
- GPS del nodo activado (venía apagado de fábrica).

## Etapa 2 - Bluetooth y "visto por última vez" (5-6 nov)

- Conexión por **Bluetooth** desde Linux. Problemas encontrados y resueltos (detalle en [conexion.md](conexion.md)):
  - `bleak` 3.x se colgaba: se fijó `bleak` 1.x.
  - El Bluetooth del nodo con PIN no respondía desde Linux: se usó modo sin PIN.
  - Enlaces Bluetooth "medio abiertos" que impedían reconectar: el servidor los cierra antes de conectar.
- **Visto por última vez**: la última posición GPS se guarda en disco y se muestra aunque el GPS pierda señal.
- Horas en **CST**, tema **claro/oscuro**, fuente monoespaciada, paleta blanco/negro con azul y rojo.
- Panel para **cambiar entre USB y Bluetooth** sin reiniciar el servidor.
- Nombre del nodo: **RABANITO (RABA)**.
- Incidencia: el nodo entró dos veces en un ciclo de reinicios cada 101 s; se resolvió apagándolo por completo.

## Etapa 3 - Migración a MeshCore (9 nov)

- El nodo se flasheó con **MeshCore v1.18.0** (companion). La interfaz se adaptó con la librería `meshcore`.
- MeshCore entrega además **temperatura** y **luz** (lux).
- La radio venía en **869.6 MHz** (banda europea); se cambió a **915 MHz**, dentro de la banda permitida en México
  (902-928 MHz).
- Se sincroniza la hora del nodo con la PC en cada conexión.

## Etapa 4 - Detector de caídas, primera versión (9 nov)

- El MeshCore oficial **no usa el acelerómetro** del T1000-E (QMA6100P): se escribió un **firmware modificado**
  (`v1.18.0-rabanito`) que lo lee 50 veces por segundo.
- Primera versión: alerta cuando la aceleración pasa un umbral; distingue caída (con caída libre antes) y golpe.
- La alarma queda **enganchada** en el nodo hasta que la interfaz la borra.
- En la interfaz: **foco rojo** junto a "este nodo", alarma sonora y registro de eventos en disco.
- Versión **Bluetooth** del firmware sin PIN en el canal de datos (la actualización por Bluetooth sigue con PIN).

## Etapa 5 - Detector v2, gráfica en vivo y calibración (9-10 nov)

- **Algoritmo v2** (propuesto en este proyecto): banco de 5 s; cuando el nodo queda en reposo se compara el último
  pico con el valor en reposo y se alerta si `pico - reposo >= dif. mínima`. Así, sacudir el nodo mientras se
  carga no dispara la alarma. Ver [detector-de-caidas.md](detector-de-caidas.md).
- Pestaña **Gráfica**: aceleración en vivo; el firmware reporta el mínimo y máximo entre lecturas para que se
  vean los golpes de milisegundos.
- Rango del acelerómetro ampliado a **±32 g** (antes ±16 g, que se saturaba en golpes fuertes).
- **Calibración de 6 caras**: el eje Z tenía un offset de **0.274 g**; tras calibrar, en reposo marca **1.00 g**
  en cualquier posición.

## Etapa 6 - Ruta, interfaz tipo Excel y GitHub (10 nov)

- **Ruta automática** desde esta computadora hasta la última ubicación del nodo (a pie, en coche o línea recta),
  con distancia y tiempo; se dibuja sola y se destaca al detectar una caída.
- La PC no tiene GPS: se ubica **reconociendo lugares por sus redes Wi-Fi** (todo local).
- Interfaz reorganizada **al estilo Excel**: cinta de opciones, barra de fórmulas, hojas abajo
  (Mapa, Gráfica, Eventos, Dispositivo) y barra de estado. Ver [interfaz.md](interfaz.md).
- Hoja **Eventos** con exportación a **CSV** para análisis en Excel.
- Código publicado en GitHub.

## Etapa 7 - Terreno y elevación (10 nov)

- Hoja **Terreno**, primero con **MapLibre GL 5.24** (mapa 3D con sombreado de relieve). Era pesado (WebGL,
  mosaicos de mapa y de relieve), así que se cambió por una **malla de alambre** propia: el servidor arma una
  rejilla de 90x90 alturas y la página la dibuja en un canvas 2D, ocultando las líneas tapadas. Solo se redibuja
  al girar o al cambiar los datos (~12 ms por cuadro) y ya no hace falta cargar MapLibre (~1 MB).
- Vista **Curvas + mapa** (a partir de un boceto): el mapa de calles en blanco y negro como piso del 3D y las
  curvas de nivel encima, de gris (suelo) a azul, morado y rojo (cima). Las curvas se calculan una vez por
  malla (marching squares) y cada mosaico del mapa se dibuja con una transformación afín: ~1 ms por cuadro.
  La malla de alambre sigue como segundo modo, y debajo hay un mapa normal del mismo recuadro.
- Elevación con **AWS Terrain Tiles** (gratis, sin clave). El servidor calcula la altura de cualquier punto
  con interpolación bilineal.
- Altura del nodo y de la PC, y **perfil de elevación de la ruta** con subida/bajada acumulada y pendiente.
- Ejemplo real: nodo a 654 m (GPS: 700 m), PC a 386 m; ruta de 38 km a pie que sube 558 m y baja 290 m.

## Etapa 8 - Información ambiental: cuerpos de agua (12 nov)

- Ríos, arroyos, canales, drenes, lagos, presas y estanques de **OpenStreetMap** (Overpass) en el área del terreno.
- Colores: el relieve en **gris/blanco** según el tema (se probó gris -> rojo por altura) y el **azul queda solo
  para el agua**.
- Marcadores **"~ AGUA | nombre"** en el 3D y en el mapa; franjas azules en el perfil donde la ruta cruza agua.
- Análisis de la ruta: cruces exactos (intersección de segmentos) y cuerpos de agua a menos de 200 m.
- Optimización: de ~1,250 cuerpos de agua (~30,000 puntos) solo se dibujan los importantes y los que cruza la ruta
  (~50, ~600 puntos tras simplificar); el análisis solo se repite si cambia la ruta o el área, y el mapa de abajo
  usa canvas. Dibujo del 3D: de ~6 ms a <1 ms por cuadro.
- Ejemplo real (ruta en coche de 30 km): cruza el **Río Santa Catarina** dos veces y un arroyo sin nombre, y pasa
  cerca de Arroyo El Perdido, un dren, un lago y estanques.

## Etapa 9 - Clima en el nodo (12 nov)

- Tarjeta **Clima en el nodo** con datos de **Open-Meteo** (gratis, sin clave) para la última posición del nodo:
  condiciones actuales, próximas 12 horas, sol y UV.
- **Avisos** calculados en el servidor: tormenta, lluvia, ráfagas, calor/frío, niebla, poca luz o noche, UV alto.
- Se combina con la información ambiental: si se espera lluvia y la ruta cruza ríos o arroyos, aviso de
  posible crecida.
- Aviso de **GPS apagado en el nodo** con botón para encenderlo (el GPS de RABANITO apareció apagado, probablemente
  por 4 pulsaciones del botón).

## Etapa 10 - Programa para la estación, fase 1 (12 nov)

- Plan para la estación al aire libre: [plan-estacion.md](plan-estacion.md) (mini PC x86_64, posible Raspberry
  Pi, pantalla y red, sin internet o intermitente).
- El programa se empaqueta con **PyInstaller** (Python incluido) en un **.deb**: servicio **systemd** que arranca
  solo y se reinicia si falla, usuario sin privilegios, datos en `/var/lib/sri`, configuración en
  `/etc/sri/config.toml`, y ventana de **pantalla completa** que se reabre si se cierra.
- Guardado seguro ante cortes de luz (escritura atómica con `fsync`).
- Probado: el programa empaquetado se conectó a RABANITO por Bluetooth y respondió el ping (283 ms).
- Guía: [instalacion.md](instalacion.md).
- Después: SRI como **programa de escritorio** (menú de aplicaciones, ventana propia que vigila el seguimiento);
  el modo estación se activa aparte con `sudo sri-estacion activar`.

## Etapa 11 - Sin internet: paquete de región (13 nov)

- Zona: **Parque La Huasteca** (Santa Catarina) y la zona metropolitana de Monterrey (~45 x 33 km).
- Mapa propio en blanco y negro dibujado con MapLibre a partir de datos de **Protomaps/OpenStreetMap**
  (7,026 mosaicos, 75 MB), relieve de AWS Terrain Tiles (645 mosaicos, 56 MB) y 1,531 cuerpos de agua.
- El servidor usa el paquete primero y la red solo como respaldo: sin internet funcionan el mapa, el relieve,
  la hoja Terreno, el agua y los cruces de la ruta; la ruta queda en línea recta y el clima usa el último
  pronóstico guardado.
- Probado simulando la falta de internet (`SRI_SIN_INTERNET=1`) con el programa en código y empaquetado.

## Etapa 12 - Actualizaciones con apt y botón "Actualizar todo" (14 nov)

- **Repositorio apt firmado** en GitHub Pages (`https://emiliosea.github.io/sri/`): el paquete 0.3.0 agrega la
  fuente y la llave; las versiones nuevas llegan con `sudo apt update && sudo apt upgrade`. Se publican con
  `empaquetar/publicar.sh`. Probado en local: apt ofrece la actualización y rechaza un índice alterado.
- **Actualizar todo**: botón que vuelve a revisar internet, pide todo al nodo (y le pone la hora), el clima, la
  ruta, el terreno y el agua. Se hace solo cuando vuelve internet; antes, tras perder la conexión, la interfaz se
  quedaba mostrando datos de "sin internet".
- Programa: barra de título solo con el logo y "SRI", indicadores rectangulares y mapa nítido con internet
  (OpenStreetMap; el paquete de región solo sin conexión).

## Etapa 13 - Modos Tiempo real / Demo y Red LoRa (15 nov)

- **Modos**: selector Tiempo real / Demo en la cinta Conexión, etiqueta EN VIVO / DEMO en la barra de título y
  entrada **SRI Demo** en el menú (puerto 5001, ventana propia). Al volver de la demo se reconecta a la última
  conexión real.
- **Red LoRa**: RABANITO queda como base y los demás nodos llegan por radio como contactos de MeshCore. Se pueden
  agregar (anunciar la base, código `meshcore://`, aceptar nodos escuchados), quitar y elegir como destino de la
  ruta, el clima y el terreno.
- Probado en modo demo; las funciones con el nodo real (contactos de MeshCore) quedan por probar con RABANITO y
  un segundo nodo.
- 0.4.1: una sola aplicación, **en vivo por defecto**; la demo pasó al **modo desarrollador** (3 clics en el logo y
  contraseña, verificada en el servidor) y se quitó la entrada "SRI Demo" del menú.
- 0.4.2: tras `apt upgrade` con SRI abierto, el servidor se reinicia solo con la versión nueva.
- 0.4.3: sin internet ya no aparece la pantalla de "sin conexión" del navegador: la ventana abre primero una
  página local que espera al servidor; los botones de Google Maps se desactivan sin internet y la ventana
  (Chromium) ya no usa los servicios de Google en segundo plano.

## Etapa 14 - Alertas de caída por la red LoRa (15 nov)

- **Firmware `v1.18.0-sri2`**: al detectar una caída o golpe, el nodo manda por sí solo un mensaje al canal privado
  "SRI" (tipo, diferencia, pico, posición GPS, hora y número de evento), 3 veces cada 20 s.
- **Base**: SRI escucha ese canal, junta las repeticiones en una alerta, la muestra en el detector con el nombre del
  nodo, suena la alarma, pinta el nodo de rojo y traza la ruta; la guarda en Eventos (columna Nodo y vía LoRa).
- **Canal privado**: se configura desde la hoja Red LoRa con una frase común (la llave sale de la frase).
- Probado con alertas simuladas en modo demo; la prueba por radio queda pendiente de un segundo nodo.

## Etapa 15 - Ventana nativa (15 nov)

- La interfaz ya no se abre en Chromium: **`sri-ventana`** es una ventana propia hecha con **GTK + WebKitGTK** (el motor
  de Safari y del navegador de GNOME), con el nombre y el ícono de SRI, una sola instancia, pantalla propia de
  "SRI no responde" (nunca la del navegador), enlaces externos al navegador del sistema y descargas a la carpeta de
  descargas. Sin servicios de Google y sin depender de Chromium (~300 MB menos).
- Mismo servidor e interfaz: se probaron en WebKit el mapa, el terreno 3D (con un respaldo para el piso en blanco y
  negro, porque WebKit no tiene `ctx.filter`), las alertas por LoRa y la hoja Red LoRa.
- La ventana de pantalla completa de la estación (`sri-kiosco`) usa la misma ventana con `--kiosco`.

---

## Resultados de las pruebas (hasta el 10 nov)

Pruebas manuales (dejar caer y golpear el nodo sobre la mesa y superficies blandas), registradas por el detector:

| Tipo | Eventos | Pico promedio | Pico mínimo | Pico máximo |
|---|---|---|---|---|
| Caída | 14 | 12.08 g | 5.37 g | 23.96 g |
| Golpe | 21 | 16.12 g | 2.59 g | 37.78 g |
| **Total** | **35** | | | |

- Diferencia pico - reposo (eventos del algoritmo v2): promedio **14.93 g**, máxima **36.78 g**.
- Los primeros eventos son del algoritmo v1 y del rango ±16 g; los posteriores usan ±32 g y la calibración.
- Son pruebas con el nodo solo, no con una persona: sirven para calibrar, no como validación clínica.

## Pendientes y siguientes pasos

- Ajustar la clasificación caída/golpe para **caídas de personas** (en el cuerpo la caída libre no llega a ~0 g;
  probar límite de 0.5-0.6 g y exigir que termine poco antes del pico).
- Guardar la dif. mínima y la calibración **en la memoria del nodo** (hoy se pierden al reiniciarlo; la interfaz
  reenvía la calibración al conectar).
- Probar las alertas por LoRa con un segundo nodo (alcance y tiempo de la caída a la base).
- Probar el GPS en exteriores y medir el tiempo hasta la primera posición.
- Volver a usar el **PIN de Bluetooth** si se encuentra cómo emparejar con PIN desde Linux (BlueZ).
- Pruebas con portador humano y definición de la dif. mínima definitiva.
