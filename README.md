# Sistema de Barrido Automatizado de Frecuencias

Aplicación de escritorio en Python para controlar un generador de funciones desde la computadora mediante comandos SCPI por puerto serie (RS232). Permite realizar barridos de frecuencia automáticos o manuales y construir el diagrama de Bode de un circuito a partir de las mediciones del osciloscopio.

Fue desarrollada para el **Trabajo Práctico de Laboratorio Nro. 8: Sistemas para automatización de mediciones** de la materia **Medidas Electrónicas I** (4to año de Ingeniería Electrónica, Universidad Tecnológica Nacional, Facultad Regional Córdoba, año 2026).

## Objetivo

El trabajo práctico propone dos objetivos:

* Diseñar un sistema automático de generación de señales.
* Determinar mediante experimentación el factor de calidad Q de un sistema LC.

En entornos donde una misma medición debe repetirse muchas veces, automatizar la toma de datos reduce el tiempo de trabajo y la posibilidad de errores. Esta aplicación resuelve esa tarea para un barrido en frecuencia y va un paso más allá de lo pedido en la consigna al agregar una interfaz gráfica y una herramienta de análisis de Bode.

## Características

* Interfaz gráfica desarrollada con `customtkinter`.
* Comunicación con el generador por puerto serie con comandos SCPI en formato ASCII.
* Prueba de conexión desde el menú mediante la consulta de identificación del equipo.
* **Barrido simple**:
  * Modo automático con tiempo configurable entre frecuencias, con opción de pausar y reanudar.
  * Modo manual con avance frecuencia por frecuencia.
  * Envío de una frecuencia puntual fuera de la secuencia.
  * Tabla con la secuencia de frecuencias que indica cuáles ya fueron enviadas y cuál está activa.
  * Imagen del generador con un display que muestra la frecuencia y la amplitud en curso.
* **Barrido con Bode**:
  * El usuario fija la tensión de entrada y en cada frecuencia carga la tensión de salida medida con el osciloscopio.
  * Cálculo de la ganancia en decibeles y gráfico en tiempo real con `matplotlib`.
  * Detección automática de la frecuencia de resonancia, de las frecuencias de corte a 3 dB, del ancho de banda y del factor de calidad Q.
  * Exportación de los datos en CSV y del gráfico en PNG.
  * Posibilidad de volver al punto anterior para corregir una medición.
* Definición flexible de las frecuencias: escala lineal, escala logarítmica o lista libre. En escala lineal se puede definir la cantidad de puntos o el tamaño del paso. El barrido actual puede pasarse a modo lista para editar o eliminar frecuencias.
* Configuración de forma de onda (senoidal, triangular o cuadrada), amplitud y offset, con posibilidad de modificarlos durante el barrido.
* Registro de los comandos enviados dentro de la interfaz y también por la terminal.
* **Modo simulación**: si no hay un generador conectado, los comandos solo se muestran en la consola. Permite probar la aplicación sin el equipo.

## Equipamiento utilizado

* Generador de funciones GW Instek GFG-3015 con entrada RS232.
* Osciloscopio Tektronix TDS1001. La aplicación no lo controla. Las mediciones se leen en el instrumento y se cargan a mano en el modo Bode.
* Cable USB a RS232.
* Computadora con un puerto USB disponible.
* Circuito RLC de pruebas con una resistencia en serie de al menos 50 ohm para proteger la salida del generador, ya que la impedancia del conjunto LC en resonancia es prácticamente nula.

## Requisitos de software

* Python 3.8 o superior.
* Las siguientes librerías:

| Librería | Uso |
|---|---|
| `customtkinter` | Interfaz gráfica |
| `pillow` | Imagen del generador |
| `pyserial` | Comunicación por puerto serie |
| `matplotlib` | Diagrama de Bode |
| `numpy` | Cálculos numéricos |

`tkinter` viene incluido con Python en Windows y macOS. En Linux puede requerir instalación aparte.

## Instalación

1. Clonar el repositorio:

```bash
git clone <URL_DEL_REPOSITORIO>
cd <NOMBRE_DEL_REPOSITORIO>
```

2. Instalar las dependencias:

```bash
pip install customtkinter pillow pyserial matplotlib numpy
```

3. Solo en Linux, instalar `tkinter` si no está disponible:

```bash
sudo apt install python3-tk
```

4. Opcional: colocar en la misma carpeta que el script una foto del generador llamada `Generador.png`. Si el archivo no existe, la aplicación dibuja un recuadro genérico en su lugar.

## Permisos del puerto serie

Durante el desarrollo se encontraron problemas de permisos de acceso a los puertos en Windows. Por este motivo el sistema se probó en Linux, donde la configuración resultó más sencilla.

En Linux el usuario debe pertenecer al grupo `dialout` para poder abrir el puerto:

```bash
sudo usermod -aG dialout $USER
```

Luego hay que cerrar sesión y volver a iniciarla. El adaptador USB a RS232 suele aparecer como `/dev/ttyUSB0`. Se puede verificar con:

```bash
ls /dev/ttyUSB*
```

En Windows el puerto aparece como `COMx` y se puede consultar en el Administrador de dispositivos.

## Ejecución

```bash
python3 barrido_frecuencias.py
```

La aplicación se ejecuta desde la terminal y cada comando enviado también se imprime allí. Cada línea indica si el comando fue transmitido al equipo (`TX`) o simulado (`SIM`).

## Uso

### Menú principal

1. Elegir el puerto serie en la lista desplegable. El botón de actualizar vuelve a buscar los puertos disponibles.
2. Presionar **Conectar**.
3. Presionar **Probar conexión**. La aplicación envía `*IDN?` y, si no hay respuesta, `ID?`. Si la conexión es correcta se muestra la identificación del generador.
4. Elegir **Barrido simple** o **Barrido con Bode**.

### Barrido simple

1. Definir el barrido en el panel izquierdo: frecuencia inicial, final, escala y cantidad de puntos o paso. También se puede elegir la escala **Lista** e ingresar las frecuencias separadas por espacio o punto y coma.
2. Fijar la amplitud, la forma de onda y el offset.
3. Elegir el modo automático (con el tiempo entre frecuencias) o manual.
4. Presionar **Iniciar**. En modo manual usar **Siguiente frecuencia** para avanzar.
5. Con **Detener** se interrumpe el barrido y con **Pausar** se detiene temporalmente el modo automático.

### Barrido con Bode

1. Definir el barrido y la tensión de entrada, igual que en el barrido simple.
2. Presionar **Iniciar**. La aplicación envía la primera frecuencia al generador.
3. Medir con el osciloscopio la tensión de salida pico a pico y cargarla en el campo correspondiente.
4. Presionar **Registrar y siguiente** o la tecla Enter. La aplicación avanza a la frecuencia siguiente y actualiza el gráfico.
5. Repetir hasta completar la secuencia.
6. Exportar los resultados con **Exportar CSV** y **Guardar gráfico**.

La ganancia se calcula como:

```
G = 20 · log10(Vout / Vin)
```

A partir de tres puntos cargados la aplicación detecta el máximo de ganancia como frecuencia de resonancia y busca por interpolación logarítmica las frecuencias donde la ganancia cae 3 dB a cada lado. Con ellas calcula:

```
BW = f2 - f1
Q  = f_res / BW
```

El CSV exportado contiene las columnas `frecuencia_Hz`, `Vin_Vpp`, `Vout_Vpp` y `ganancia_dB`.

### Formatos de entrada aceptados

| Campo | Ejemplos |
|---|---|
| Frecuencia | `1000`, `1,5`, `10k`, `10kHz` |
| Tensión | `5`, `2,5`, `800mV`, `5Vpp` |
| Offset | `0`, `-0,5`, `500mV` |
| Lista de frecuencias | `1k 2k 5k 10k 20k 50k 100k` |

El máximo permitido es de 1000 puntos por barrido.

## Comandos SCPI utilizados

| Comando | Función |
|---|---|
| `:FREQ <f>` | Configura la frecuencia de la señal de salida |
| `:AMPL:VOLT <v>` | Configura la amplitud de la señal de salida |
| `:FUNC:WAV <n>` | Selecciona la forma de onda: 1 senoidal, 2 triangular, 3 cuadrada |
| `:OFFS <v>` | Configura la tensión de offset |
| `*IDN?` y `ID?` | Consultan la identificación del instrumento |

La comunicación se realiza a **9600 baudios**. Cada comando se envía terminado con un salto de línea.

## Configuración

Las constantes se encuentran al inicio del script:

| Constante | Descripción |
|---|---|
| `PUERTO_DEFECTO` | Puerto serie inicial (`COM3` en Windows y `/dev/ttyUSB0` en Linux) |
| `BAUDIOS` | Velocidad de transmisión |
| `VPP_DEFECTO` | Tensión pico a pico inicial (5 V según la consigna) |
| `FACTOR_AMPL` | Factor entre la tensión ingresada y el valor enviado en `:AMPL:VOLT` |
| `FORMAS_ONDA` | Códigos de forma de onda del generador |
| `IMAGEN_GENERADOR` | Archivo de la foto del generador |
| `PANTALLA_REL` | Posición del display sobre la foto, como fracción de su tamaño |
| `CALIBRAR` | Si vale `True`, al hacer clic sobre la foto se imprimen las coordenadas para ajustar `PANTALLA_REL` |

### Criterio de la amplitud

El display del GFG-3015 indica la amplitud como tensión pico a pico. Sin embargo, al medir con el osciloscopio se comprobó que el valor del comando `:AMPL:VOLT` corresponde a la tensión pico. Por este motivo, para este generador se debe usar `FACTOR_AMPL = 0.5`. De esta forma el usuario ingresa la tensión pico a pico deseada y la aplicación envía la mitad.

Con otro generador que interprete el comando de manera distinta hay que ajustar este factor. Si el comando ya recibe tensión pico a pico, el valor correcto es `1.0`.

## Estructura del código

| Clase | Función |
|---|---|
| `Puerto` | Envuelve el puerto serie y funciona en modo simulación sin conexión |
| `GeneradorVisual` | Foto del generador con el display superpuesto |
| `PanelConfig` | Panel de configuración del barrido y validación de los datos |
| `GraficoBode` | Gráfico de Bode con `matplotlib` |
| `App` | Ventana principal |
| `MenuFrame` | Menú principal y prueba de conexión |
| `BarridoFrame` | Pantalla de barrido simple y de barrido con Bode |

Las funciones `parse_num`, `parse_voltaje`, `parse_offset` y `parse_lista` interpretan los valores ingresados por el usuario y `analizar_bode` realiza la detección de resonancia, frecuencias de corte y Q.

## Ejemplo de uso: circuito RLC

El experimento del trabajo práctico se realizó con un circuito RLC serie con R = 47 ohm, L = 20 mH (núcleo de aire) y C = 7 nF. La frecuencia de resonancia teórica es:

```
f_res = 1 / (2 · π · √(L · C)) ≈ 13,45 kHz
```

Configuración usada:

* Señal senoidal de 5 Vpp y offset de 0 V.
* Barrido en modo lista de 1 kHz a 100 kHz con un segundo entre saltos.
* Barrido detallado de 3 kHz a 99 kHz con paso de 2 kHz, que luego se pasó a modo lista para eliminar frecuencias altas con poca información.

## Solución de problemas

| Problema | Posible causa y solución |
|---|---|
| No se puede abrir el puerto | Falta de permisos. En Linux agregar el usuario al grupo `dialout`. Verificar que otro programa no esté usando el puerto |
| El generador no responde a `*IDN?` ni a `ID?` | Revisar el cable, el puerto elegido y la velocidad de 9600 baudios. Algunos equipos requieren configurar la interfaz RS232 desde su panel |
| La señal medida no coincide con la amplitud configurada | Ajustar `FACTOR_AMPL` según cómo interprete el comando el generador |
| El display de la imagen no queda sobre la pantalla del generador | Poner `CALIBRAR = True`, hacer clic en las esquinas de la pantalla y actualizar `PANTALLA_REL` |
| Aparece el aviso de modo simulación | No hay un puerto abierto. Los comandos solo se muestran por consola |

## Limitaciones y posibles mejoras

* La tensión de salida del circuito se carga a mano. Una mejora sería leerla directamente del osciloscopio mediante comandos SCPI para automatizar también la medición.
* Los comandos y el formato de amplitud están adaptados al GFG-3015. Otros generadores pueden requerir cambios.
* Las frecuencias de corte se calculan a partir de los puntos cargados. La precisión depende de la cantidad de puntos cerca de la resonancia.

## Autores

Completar con los autores del trabajo.

## Licencia

Completar con la licencia elegida para el repositorio.
