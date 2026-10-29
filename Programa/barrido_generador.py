# -*- coding: utf-8 -*-
"""
Sistema de Barrido Automatizado de Frecuencias
TP 8 - Medidas Electronicas I (UTN FRC)

Dependencias:
    pip install customtkinter pillow pyserial matplotlib numpy

Modos:
  - Barrido simple (sin Bode): automatico (con tiempo entre frecuencias) o manual.
  - Barrido con Bode: en cada frecuencia cargas a mano el Vpp que lees en el
    osciloscopio; el programa grafica la ganancia, detecta el punto de maxima
    ganancia, los puntos de -3 dB y calcula el Q.

La tension del generador se puede cambiar en cualquier momento (manda el comando).
Si no hay generador conectado, funciona en modo simulacion (los comandos se
muestran por consola) para que puedas probarlo en tu casa.
"""
import csv
import os
import platform
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont

import customtkinter as ctk
import numpy as np
import serial
import serial.tools.list_ports
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, NullFormatter, NullLocator
from PIL import Image, ImageOps, ImageTk

# ===================== CONFIGURACION GENERAL ===================== #

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("dark-blue")
FUENTE = "TkDefaultFont"   # se reemplaza al crear la ventana por la mejor fuente disponible

IMAGEN_GENERADOR = "Generador.png"
PUERTO_DEFECTO = "COM3" if platform.system() == "Windows" else "/dev/ttyUSB0"
BAUDIOS = 9600

VPP_DEFECTO = 5.0      # el TP pide 5 Vpp
FACTOR_AMPL = 0.5      # valor enviado = Vpp * FACTOR_AMPL. El GFG-3015 entrega el doble de
                       # lo que se le manda en ":AMPL:VOLT", asi que se envia la mitad para
                       # que la tension que escribis en el programa sea realmente pico a pico.
                       # Si algun dia el generador entrega justo lo que se manda, poner 1.0.
MAX_PUNTOS = 1000

# Formas de onda: nombre -> (codigo que va en ":FUNC:WAV <codigo>", abreviatura para la
# pantalla del generador, ¿codigo confirmado?).
# Codigos del GFG-3015 confirmados: 1 = senoidal, 3 = cuadrada, 2 = triangular.
FORMAS_ONDA = {
    "Senoidal": (1, "SIN", True),
    "Cuadrada": (3, "SQR", True),
    "Triangular": (2, "TRI", True),
}
FORMA_DEFECTO = "Senoidal"

# --- Foto del generador con pantalla superpuesta ---
GEN_ANCHO, GEN_ALTO = 520, 230   # tamaño maximo de la foto en pantalla
# Posicion del display del GW Instek GFG-3015 como FRACCION de la foto:
# (x1, y1, x2, y2), donde 0 es el borde izquierdo/superior y 1 el derecho/inferior.
# Asi se adapta solo al tamaño con que se muestre la foto.
PANTALLA_REL = (0.088, 0.190, 0.355, 0.560)
# True: al hacer clic sobre la foto se imprimen en la consola las fracciones x, y
# (sirve para reajustar PANTALLA_REL si usas otra foto).
CALIBRAR = False

# ===================== COLORES ===================== #
COLOR_PRINCIPAL = "#3B6FF0"       # azul de acento
COLOR_HOVER = "#2D57C4"
COLOR_DETENER = "#E5484D"
COLOR_DETENER_HOVER = "#C03A3F"
COLOR_NARANJA = "#F59E0B"
COLOR_NARANJA_HOVER = "#D18208"
COLOR_TURQUESA = "#12A4B5"
COLOR_TURQUESA_HOVER = "#0E8795"
COLOR_FONDO_FRAME = "#F2F4F8"     # fondo general de la ventana
COLOR_PANEL = "#FFFFFF"           # tarjetas
COLOR_BORDE = "#E1E6EF"
COLOR_CAMPO = "#F6F8FC"           # fondo de los campos de texto
COLOR_TITULO = "#0F1B33"          # azul marino (titulos, encabezado)
COLOR_TEXTO = "#26324A"
COLOR_SUAVE = "#66748B"           # textos secundarios
COLOR_OK = "#1E9E5A"
COLOR_ERROR = "#D64545"
COLOR_AVISO = "#B7791F"
COLOR_PANTALLA = "#0b1a0b"
COLOR_TEXTO_LED = "#39ff14"


# ===================== FUNCIONES AUXILIARES ===================== #

def parse_num(texto):
    """Convierte '1000', '1,5', '10k' o '10kHz' a float."""
    t = str(texto).strip().lower().replace(",", ".").replace(" ", "")
    mult = 1.0
    if t.endswith("khz"):
        t, mult = t[:-3], 1e3
    elif t.endswith("hz"):
        t = t[:-2]
    elif t.endswith("k"):
        t, mult = t[:-1], 1e3
    if not t:
        raise ValueError("Falta un numero.")
    try:
        return float(t) * mult
    except ValueError:
        raise ValueError(f"'{texto}' no es un numero valido.") from None


def parse_voltaje(texto):
    """Convierte '5.2', '5,2', '800mV' o '5.2Vpp' a volts (> 0)."""
    msg = "Ingresa el Vpp como un numero mayor que 0 (ej. 5.2 o 800mV)."
    t = str(texto).strip().lower().replace(",", ".").replace(" ", "")
    mult = 1.0
    for suf in ("mvpp", "mv"):
        if t.endswith(suf):
            t, mult = t[:-len(suf)], 1e-3
            break
    else:
        for suf in ("vpp", "v"):
            if t.endswith(suf):
                t = t[:-len(suf)]
                break
    try:
        v = float(t) * mult
    except ValueError:
        raise ValueError(msg) from None
    if v <= 0:
        raise ValueError(msg)
    return v


def parse_offset(texto):
    """Convierte '0', '1,5', '-0.5' o '500mV' a volts (puede ser negativo o cero)."""
    msg = "Ingresá el offset en volts (ej. 0, 1.5, -0.5 o 500mV)."
    t = str(texto).strip().lower().replace(",", ".").replace(" ", "")
    mult = 1.0
    for suf in ("mv",):
        if t.endswith(suf):
            t, mult = t[:-len(suf)], 1e-3
            break
    else:
        if t.endswith("v"):
            t = t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        raise ValueError(msg) from None


def parse_lista(texto):
    """'1k 2.5k; 5000' -> [1000.0, 2500.0, 5000.0] (respeta el orden escrito)."""
    tokens = [t for t in re.split(r"[;\s]+", texto.strip()) if t]
    if not tokens:
        raise ValueError("Escribí al menos una frecuencia (ej. 1k 2.5k 5k 10k).")
    frs = []
    for t in tokens:
        try:
            f = parse_num(t)
        except ValueError:
            raise ValueError(f"No entiendo «{t}» como frecuencia.") from None
        if f <= 0:
            raise ValueError(f"La frecuencia {t} debe ser mayor que 0.")
        frs.append(f)
    if len(frs) > MAX_PUNTOS:
        raise ValueError(f"Son demasiadas frecuencias ({len(frs)}). El máximo es {MAX_PUNTOS}.")
    return frs


def fmt_hz(f):
    if f >= 1e6:
        return f"{f / 1e6:.5g} MHz"
    if f >= 1e3:
        return f"{f / 1e3:.5g} kHz"
    return f"{f:.5g} Hz"


def fmt_cmd(f):
    """Frecuencia para el comando SCPI, sin notacion cientifica."""
    return f"{f:.3f}".rstrip("0").rstrip(".")


def generar_frecuencias(inicio, fin, n, escala):
    if escala == "Logarítmica":
        fr = np.geomspace(inicio, fin, n)
    else:
        fr = np.linspace(inicio, fin, n)
    return [round(float(x), 3) for x in fr]


def analizar_bode(f, g):
    """Busca el pico y los puntos de -3 dB (interpolando en log f). Devuelve dict o None."""
    if len(f) < 3:
        return None
    datos = sorted(zip(f, g))
    fs = np.array([d[0] for d in datos], dtype=float)
    gs = np.array([d[1] for d in datos], dtype=float)
    i = int(np.argmax(gs))
    res = {"f_res": float(fs[i]), "g_pico": float(gs[i]),
           "f1": None, "f2": None, "bw": None, "q": None}
    objetivo = gs[i] - 3.0
    lf = np.log10(fs)
    for j in range(i - 1, -1, -1):
        if gs[j] <= objetivo:
            t = (objetivo - gs[j]) / (gs[j + 1] - gs[j])
            res["f1"] = float(10 ** (lf[j] + t * (lf[j + 1] - lf[j])))
            break
    for j in range(i + 1, len(fs)):
        if gs[j] <= objetivo:
            t = (objetivo - gs[j - 1]) / (gs[j] - gs[j - 1])
            res["f2"] = float(10 ** (lf[j - 1] + t * (lf[j] - lf[j - 1])))
            break
    if res["f1"] and res["f2"]:
        res["bw"] = res["f2"] - res["f1"]
        res["q"] = res["f_res"] / res["bw"]
    return res


def aplicar_tema():
    """Ajusta el aspecto por defecto de los widgets de CustomTkinter (campos, botones, etc.)."""
    th = ctk.ThemeManager.theme

    def poner(widget, **valores):
        for k, v in valores.items():
            if k in th.get(widget, {}):
                th[widget][k] = v

    poner("CTkLabel", text_color=[COLOR_TEXTO, COLOR_TEXTO])
    poner("CTkEntry", corner_radius=8, border_width=1, fg_color=[COLOR_CAMPO, COLOR_CAMPO],
          border_color=["#CBD3E1", "#CBD3E1"], text_color=[COLOR_TEXTO, COLOR_TEXTO],
          placeholder_text_color=["#9AA6BA", "#9AA6BA"])
    poner("CTkButton", corner_radius=9, fg_color=[COLOR_PRINCIPAL, COLOR_PRINCIPAL],
          hover_color=[COLOR_HOVER, COLOR_HOVER], text_color=["white", "white"],
          text_color_disabled=["#D5DCEA", "#D5DCEA"])
    poner("CTkSegmentedButton", corner_radius=8, border_width=3, fg_color=["#9AA6BC", "#9AA6BC"],
          selected_color=[COLOR_PRINCIPAL, COLOR_PRINCIPAL],
          selected_hover_color=[COLOR_HOVER, COLOR_HOVER],
          unselected_color=["#9AA6BC", "#9AA6BC"], unselected_hover_color=["#8794AC", "#8794AC"],
          text_color=["#FFFFFF", "#FFFFFF"], text_color_disabled=["#E3E8F1", "#E3E8F1"])
    poner("CTkOptionMenu", corner_radius=8, fg_color=[COLOR_PRINCIPAL, COLOR_PRINCIPAL],
          button_color=[COLOR_HOVER, COLOR_HOVER], button_hover_color=["#244796", "#244796"])
    poner("CTkComboBox", corner_radius=8, border_width=1, fg_color=[COLOR_CAMPO, COLOR_CAMPO],
          border_color=["#CBD3E1", "#CBD3E1"], button_color=["#CBD3E1", "#CBD3E1"],
          button_hover_color=["#B3BED2", "#B3BED2"], text_color=[COLOR_TEXTO, COLOR_TEXTO])
    poner("CTkProgressBar", fg_color=["#DDE3EE", "#DDE3EE"],
          progress_color=[COLOR_PRINCIPAL, COLOR_PRINCIPAL])
    poner("CTkTextbox", corner_radius=8, border_width=1, fg_color=[COLOR_CAMPO, COLOR_CAMPO],
          border_color=["#CBD3E1", "#CBD3E1"], text_color=[COLOR_TEXTO, COLOR_TEXTO])


def elegir_fuente_ui():
    """Fuente de la interfaz: la primera moderna que haya instalada."""
    disponibles = set(tkfont.families())
    for nombre in ("Inter", "Segoe UI", "SF Pro Text", "Ubuntu", "Noto Sans", "Cantarell",
                   "Roboto", "Helvetica Neue", "Open Sans", "DejaVu Sans"):
        if nombre in disponibles:
            return nombre
    return tkfont.nametofont("TkDefaultFont").actual("family")


def tarjeta(master, **kw):
    """Panel blanco con borde suave y esquinas redondeadas."""
    opciones = dict(fg_color=COLOR_PANEL, corner_radius=14, border_width=1, border_color=COLOR_BORDE)
    opciones.update(kw)
    return ctk.CTkFrame(master, **opciones)


def titulo_tarjeta(master, texto, **grid):
    """Titulo de seccion dentro de una tarjeta."""
    return ctk.CTkLabel(master, text=texto, font=(FUENTE, 15, "bold"), text_color=COLOR_TITULO,
                        anchor="w")


def configurar_estilos():
    """Estilo de las tablas (ttk) para que combinen con el resto de la interfaz."""
    st = ttk.Style()
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure("Treeview", rowheight=28, font=(FUENTE, 11), background="white",
                 fieldbackground="white", foreground=COLOR_TEXTO, borderwidth=0, relief="flat")
    st.configure("Treeview.Heading", font=(FUENTE, 10, "bold"), background="#EDF1F8",
                 foreground=COLOR_SUAVE, relief="flat", borderwidth=0, padding=(6, 6))
    st.map("Treeview.Heading", background=[("active", "#E3E9F4")])
    st.map("Treeview", background=[("selected", "#DCE7FF")],
           foreground=[("selected", COLOR_TITULO)])
    st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    for orient in ("Vertical", "Horizontal"):
        st.configure(f"{orient}.TScrollbar", background="#CBD3E1", troughcolor="#F2F4F8",
                     bordercolor="#F2F4F8", arrowcolor="#66748B", relief="flat", gripcount=0)


# ===================== PUERTO SERIE ===================== #

class Puerto:
    """Envuelve el puerto serie. Sin conexion funciona en modo simulacion."""

    def __init__(self):
        self.ser = None
        self.nombre = None
        self.error = None
        self.on_tx = None      # funcion opcional: se llama con cada comando enviado
        self._lock = threading.Lock()

    @property
    def conectado(self):
        return self.ser is not None and self.ser.is_open

    def conectar(self, nombre, baudios=BAUDIOS):
        self.cerrar()
        self.ser = serial.Serial(nombre, baudrate=baudios, timeout=1)
        self.nombre = nombre
        self.error = None

    def cerrar(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.nombre = None

    def enviar(self, comando):
        with self._lock:
            print(f"[{'TX' if self.conectado else 'SIM'}] {comando}")
            if self.conectado:
                try:
                    self.ser.write((comando + "\n").encode())
                except (serial.SerialException, OSError) as e:
                    self.error = str(e)
        if self.on_tx:
            try:
                self.on_tx(comando)
            except Exception:
                pass

    def consultar(self, comando):
        if not self.conectado:
            return None
        with self._lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write((comando + "\n").encode())
                resp = self.ser.readline().decode(errors="ignore").strip()
            except (serial.SerialException, OSError) as e:
                self.error = str(e)
                return None
        return resp or None

    def set_amplitud(self, vpp):
        self.enviar(f":AMPL:VOLT {vpp * FACTOR_AMPL:g}")

    def set_forma(self, codigo):
        self.enviar(f":FUNC:WAV {int(codigo)}")

    def set_offset(self, volts):
        self.enviar(f":OFFS {volts:g}")

    def configurar_senal(self, vpp, codigo=1, offset=0.0):
        self.set_amplitud(vpp)
        time.sleep(0.05)
        self.set_forma(codigo)
        time.sleep(0.05)
        self.set_offset(offset)

    def set_frecuencia(self, f):
        self.enviar(f":FREQ {fmt_cmd(f)}")


# ===================== FOTO DEL GENERADOR CON DISPLAY ===================== #

def elegir_fuente(preferidas):
    """Primera fuente de la lista que exista en el sistema (o la monoespaciada de Tk)."""
    disponibles = set(tkfont.families())
    for nombre in preferidas:
        if nombre in disponibles:
            return nombre
    return tkfont.nametofont("TkFixedFont").actual("family")


class GeneradorVisual(tk.Canvas):
    def __init__(self, master, max_ancho=GEN_ANCHO, max_alto=GEN_ALTO):
        super().__init__(master, width=max_ancho, height=max_alto,
                         highlightthickness=0, bg=COLOR_PANEL)
        if os.path.exists(IMAGEN_GENERADOR):
            img = ImageOps.contain(Image.open(IMAGEN_GENERADOR), (max_ancho, max_alto))
            self._foto = ImageTk.PhotoImage(img)   # guardar referencia
            ancho, alto = img.size
            self.configure(width=ancho, height=alto)   # el canvas calza justo con la foto
            self.create_image(0, 0, image=self._foto, anchor="nw")
        else:
            ancho, alto = max_ancho, max_alto
            self.create_rectangle(4, 4, ancho - 4, alto - 4,
                                  fill="#d9dde3", outline="#8a929c", width=3)
            self.create_text(ancho // 2, alto - 28, text="GENERADOR DE FUNCIONES",
                             fill="#42505f", font=(FUENTE, 11, "bold"))

        fx1, fy1, fx2, fy2 = PANTALLA_REL
        x1, y1, x2, y2 = int(fx1 * ancho), int(fy1 * alto), int(fx2 * ancho), int(fy2 * alto)
        self._pw, self._ph = x2 - x1, y2 - y1
        self.create_rectangle(x1, y1, x2, y2, fill=COLOR_PANTALLA, outline="#050505", width=2)

        familia = elegir_fuente(["DSEG7 Classic", "DejaVu Sans Mono", "Liberation Mono",
                                 "Courier New", "Courier"])
        mono = elegir_fuente(["DejaVu Sans Mono", "Liberation Mono", "Courier New", "Courier"])
        self._k = 0.8 if familia == "DSEG7 Classic" else 0.62   # ancho de caracter / alto
        self._f_freq = tkfont.Font(family=familia, size=-12, weight="bold")
        self._f_info = tkfont.Font(family=mono, size=-max(8, int(self._ph * 0.16)), weight="bold")
        f_sweep = tkfont.Font(family=mono, size=-max(7, int(self._ph * 0.11)), weight="bold")

        cx = (x1 + x2) // 2
        self.t_freq = self.create_text(cx, y1 + int(self._ph * 0.42), text="--- Hz",
                                       fill=COLOR_TEXTO_LED, font=self._f_freq)
        self.t_info = self.create_text(cx, y1 + int(self._ph * 0.80), text="",
                                       fill=COLOR_TEXTO_LED, font=self._f_info)
        r = max(3, int(self._ph * 0.045))
        self.create_text(x2 - 4 * r, y1 + 2 * r, text="SWEEP", anchor="e",
                         fill="#7fbf7f", font=f_sweep)
        self.led = self.create_oval(x2 - 3 * r, y1 + r, x2 - r, y1 + 3 * r,
                                    fill="#3b1111", outline="#000000")
        self._ajustar_fuente("--- Hz")
        if CALIBRAR:
            self.bind("<Button-1>",
                      lambda e: print(f"x={e.x / ancho:.3f}, y={e.y / alto:.3f}"))

    def _ajustar_fuente(self, texto):
        """Achica la fuente para que el numero siempre entre en la pantalla."""
        n = max(len(texto), 5)
        px = int(min(self._ph * 0.34, self._pw * 0.90 / (self._k * n)))
        self._f_freq.configure(size=-max(px, 8))

    def set_frecuencia(self, f):
        texto = fmt_hz(f)
        self._ajustar_fuente(texto)
        self.itemconfig(self.t_freq, text=texto)

    def set_info(self, vpp, abrev="SIN", offset=0.0):
        """Linea de abajo de la pantalla: amplitud, forma de onda y (si hay) offset."""
        texto = f"{vpp:.2f}Vpp {abrev}"
        if abs(offset) > 1e-9:
            texto += f" {offset:+.2f}V"
        px = int(min(self._ph * 0.16, self._pw * 0.92 / (0.62 * max(len(texto), 8))))
        self._f_info.configure(size=-max(px, 7))
        self.itemconfig(self.t_info, text=texto)

    def set_salida(self, activa):
        self.itemconfig(self.led, fill=COLOR_TEXTO_LED if activa else "#3b1111")


# ===================== PANEL DE CONFIGURACION DEL BARRIDO ===================== #

class PanelConfig(ctk.CTkFrame):
    """Inicio, fin, escala y cantidad de puntos o paso (se puede editar cualquiera de los dos)."""

    def __init__(self, master, on_change=None):
        super().__init__(master, fg_color=COLOR_PANEL, corner_radius=14, border_width=1,
                         border_color=COLOR_BORDE)
        self.on_change = None
        self.frecuencias = None
        self._bloqueo = False
        self._deshabilitado = False
        self._origen = "n"        # cual de los dos campos manda: "n" (cantidad) o "paso"

        self.v_ini = ctk.StringVar(value="1000")
        self.v_fin = ctk.StringVar(value="100000")
        self.v_n = ctk.StringVar(value="7")
        self.v_paso = ctk.StringVar(value="")
        self.v_escala = ctk.StringVar(value="Lineal")
        self.v_lista = ctk.StringVar(value="")
        self._base = None          # ultimo barrido lineal/log calculado (para copiarlo a la lista)

        self.columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Configuración del barrido", font=(FUENTE, 15, "bold"),
                     text_color=COLOR_TITULO).grid(row=0, column=0, columnspan=2,
                                                   padx=14, pady=(12, 6), sticky="w")
        self.e_ini = self._campo(1, "Frecuencia inicial (Hz)", self.v_ini)
        self.e_fin = self._campo(2, "Frecuencia final (Hz)", self.v_fin)

        ctk.CTkLabel(self, text="Escala", font=(FUENTE, 13)).grid(
            row=3, column=0, padx=(14, 4), pady=5, sticky="w")
        self.s_escala = ctk.CTkSegmentedButton(
            self, values=["Lineal", "Logarítmica", "Lista"], variable=self.v_escala,
            command=lambda _valor: self._editado(None))
        self.s_escala.grid(row=3, column=1, padx=(4, 14), pady=5, sticky="ew")

        self.e_n = self._campo(4, "Cantidad de puntos", self.v_n)
        self.e_paso = self._campo(5, "Paso (Hz)", self.v_paso)

        # --- convertir en lista editable ---
        ctk.CTkFrame(self, height=1, fg_color=COLOR_BORDE).grid(
            row=6, column=0, columnspan=2, padx=14, pady=(6, 6), sticky="ew")
        self.b_copiar = ctk.CTkButton(self, text="✎  Convertir en lista editable", height=28,
                                      fg_color=COLOR_TURQUESA, hover_color=COLOR_TURQUESA_HOVER,
                                      command=self.copiar_a_lista)
        self.b_copiar.grid(row=7, column=0, columnspan=2, padx=14, pady=(2, 0), sticky="ew")
        self.l_lista = ctk.CTkLabel(self, text="Lista de frecuencias (Hz, separadas por espacio o ;)",
                                    font=(FUENTE, 12), anchor="w")
        self.l_lista.grid(row=8, column=0, columnspan=2, padx=14, pady=(4, 0), sticky="w")
        self.e_lista = ctk.CTkEntry(self, textvariable=self.v_lista,
                                    placeholder_text="ej: 1k 2.5k 5k 10k 20k 50k")
        self.e_lista.grid(row=9, column=0, columnspan=2, padx=14, pady=(2, 4), sticky="ew")

        self.l_info = ctk.CTkLabel(self, text="", font=(FUENTE, 12), justify="left",
                                   anchor="w", wraplength=300)
        self.l_info.grid(row=10, column=0, columnspan=2, padx=14, pady=(6, 12), sticky="w")

        self.v_ini.trace_add("write", lambda *_: self._editado(None))
        self.v_fin.trace_add("write", lambda *_: self._editado(None))
        self.v_n.trace_add("write", lambda *_: self._editado("n"))
        self.v_paso.trace_add("write", lambda *_: self._editado("paso"))
        self.v_lista.trace_add("write", lambda *_: self._editado(None))

        self._refrescar()
        self.on_change = on_change

    def _campo(self, fila, texto, var):
        ctk.CTkLabel(self, text=texto, font=(FUENTE, 13)).grid(
            row=fila, column=0, padx=(14, 4), pady=5, sticky="w")
        e = ctk.CTkEntry(self, textvariable=var, width=110, justify="right")
        e.grid(row=fila, column=1, padx=(4, 14), pady=5, sticky="e")
        return e

    def _set(self, var, texto):
        self._bloqueo = True
        var.set(texto)
        self._bloqueo = False

    def _editado(self, origen):
        if self._bloqueo:
            return
        if origen:
            self._origen = origen
        self._refrescar()

    def _actualizar_estados(self):
        log = self.v_escala.get() == "Logarítmica"
        lista = self.v_escala.get() == "Lista"
        st = "disabled" if self._deshabilitado else "normal"
        st_rango = "disabled" if (self._deshabilitado or lista) else "normal"
        for e in (self.e_ini, self.e_fin, self.e_n):
            e.configure(state=st_rango)
        self.s_escala.configure(state=st)
        self.e_paso.configure(state="disabled" if (self._deshabilitado or log or lista) else "normal")
        self.e_lista.configure(state="normal" if (lista and not self._deshabilitado) else "disabled")
        for w in (self.l_lista, self.e_lista):
            if lista:
                w.grid()
            else:
                w.grid_remove()
        if lista:
            self.b_copiar.grid_remove()
        else:
            self.b_copiar.grid()
        self.b_copiar.configure(state="disabled" if self._deshabilitado else "normal")

    def set_lista(self, frs):
        """Carga una lista de frecuencias (en ese orden) y pasa a modo Lista."""
        self.v_lista.set(" ".join(fmt_cmd(f) for f in frs))
        self.v_escala.set("Lista")
        self._editado(None)

    def copiar_a_lista(self):
        """Pasa las frecuencias del barrido actual a la lista y cambia a modo Lista."""
        if self.frecuencias:
            self.set_lista(self.frecuencias)
        elif self._base:
            self.set_lista(self._base)

    def deshabilitar(self, valor):
        self._deshabilitado = valor
        self._actualizar_estados()

    @staticmethod
    def _resumen(frs):
        txt = ", ".join(fmt_hz(f) for f in frs[:5])
        if len(frs) > 5:
            txt += " … " + fmt_hz(frs[-1])
        return txt

    def _info(self, texto, error):
        self.l_info.configure(text=texto, text_color=COLOR_ERROR if error else COLOR_TEXTO)

    def _refrescar(self):
        log = self.v_escala.get() == "Logarítmica"
        self._actualizar_estados()
        if self.v_escala.get() == "Lista":
            try:
                frs = parse_lista(self.v_lista.get())
                self.frecuencias = frs
                self._info(f"{len(frs)} frecuencias en el orden escrito: {self._resumen(frs)}", False)
            except ValueError as e:
                self.frecuencias = None
                self._info(str(e), True)
            self._notificar()
            return
        try:
            ini = parse_num(self.v_ini.get())
            fin = parse_num(self.v_fin.get())
            if ini <= 0:
                raise ValueError("La frecuencia inicial debe ser mayor que 0.")
            if fin <= ini:
                raise ValueError("La frecuencia final debe ser mayor que la inicial.")
            extra = ""
            if self.v_paso.get().strip() == "—":     # venia de escala logaritmica
                self._origen = "n"
            if (not log) and self._origen == "paso":
                paso = parse_num(self.v_paso.get())
                if paso <= 0:
                    raise ValueError("El paso debe ser mayor que 0.")
                n = int(np.floor((fin - ini) / paso + 1e-9)) + 1
                if n < 2:
                    raise ValueError("Con ese paso queda un solo punto: achicá el paso.")
                if n > MAX_PUNTOS:
                    raise ValueError(f"Son demasiados puntos ({n}). El máximo es {MAX_PUNTOS}.")
                frs = [round(ini + k * paso, 3) for k in range(n)]
                self._set(self.v_n, str(n))
                if frs[-1] < fin - 1e-6:
                    extra = f"\nEl último punto es {fmt_hz(frs[-1])} (el paso no llega justo a la final)."
            else:
                n = int(parse_num(self.v_n.get()))
                if n < 2:
                    raise ValueError("Hacen falta al menos 2 puntos.")
                if n > MAX_PUNTOS:
                    raise ValueError(f"Son demasiados puntos ({n}). El máximo es {MAX_PUNTOS}.")
                frs = generar_frecuencias(ini, fin, n, self.v_escala.get())
                if log:
                    self._set(self.v_paso, "—")
                    extra = f"\nRazón: ×{(fin / ini) ** (1 / (n - 1)):.4g} por salto."
                else:
                    self._set(self.v_paso, f"{(fin - ini) / (n - 1):.6g}")
            self.frecuencias = frs
            self._base = list(frs)
            self._info(f"{len(frs)} puntos: {self._resumen(frs)}{extra}", False)
        except ValueError as e:
            self.frecuencias = None
            self._info(str(e), True)
        self._notificar()

    def _notificar(self):
        if self.on_change:
            self.on_change()


# ===================== GRAFICO DE BODE ===================== #

class GraficoBode(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color=COLOR_PANEL, corner_radius=14, border_width=1,
                         border_color=COLOR_BORDE)
        self.fig = Figure(figsize=(5.6, 3.6), dpi=100, facecolor=COLOR_PANEL)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().configure(bg=COLOR_PANEL, highlightthickness=0)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        self.rango = (800.0, 125000.0)
        self.dibujar([], [], None)

    def set_rango(self, fmin, fmax):
        self.rango = (fmin * 0.8, fmax * 1.25)

    def _ticks(self):
        """Marcas del eje X (1-2-5, mas finas si el rango es corto), siempre >= 5 si se puede."""
        lo, hi = self.rango
        e0, e1 = int(np.floor(np.log10(lo))) - 1, int(np.ceil(np.log10(hi))) + 1
        t = []
        for mults in ((1,), (1, 2, 5), (1, 2, 3, 5, 7), (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9)):
            t = [m * 10.0 ** e for e in range(e0, e1 + 1) for m in mults]
            t = [x for x in t if lo <= x <= hi]
            if len(t) >= 5:
                break
        return t

    def dibujar(self, f, g, an):
        ax = self.ax
        ax.clear()
        ax.set_facecolor(COLOR_PANEL)
        ax.set_xscale("log")
        ax.set_xticks(self._ticks())
        ax.xaxis.set_major_formatter(
            FuncFormatter(lambda x, _: fmt_hz(x).replace(" Hz", "").replace(" ", "")))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_xlabel("Frecuencia (Hz)", color=COLOR_SUAVE, fontsize=9)
        ax.set_ylabel("Ganancia (dB) = 20·log10(Vout/Vin)", color=COLOR_SUAVE, fontsize=9)
        ax.grid(True, which="major", color="#E6EAF2", lw=0.8)
        ax.set_axisbelow(True)
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
        for lado in ("left", "bottom"):
            ax.spines[lado].set_color("#CBD3E1")
        ax.tick_params(colors=COLOR_SUAVE, labelsize=8.5, length=3)

        if f:
            fo, go = zip(*sorted(zip(f, g)))
            ax.plot(fo, go, "-", color=COLOR_PRINCIPAL, lw=2, zorder=2)
            ax.plot(fo, go, "o", color="white", mec=COLOR_PRINCIPAL, mew=2, ms=6.5, zorder=3,
                    label="Medido")
        if an:
            ax.axvline(an["f_res"], color=COLOR_OK, ls=(0, (4, 3)), lw=1, zorder=1)
            ax.axhline(an["g_pico"] - 3, color="#98A3B8", ls=(0, (4, 3)), lw=1, zorder=1)
            ax.plot([an["f_res"]], [an["g_pico"]], "D", color=COLOR_OK, ms=8, zorder=4,
                    label=f"Máx. ganancia {fmt_hz(an['f_res'])}")
            etiqueta = "−3 dB"
            for k in ("f1", "f2"):
                if an[k]:
                    ax.plot([an[k]], [an["g_pico"] - 3], "s", color=COLOR_NARANJA, ms=7, zorder=4,
                            label=etiqueta)
                    etiqueta = "_nolegend_"
        ax.set_xlim(*self.rango)
        if ax.get_legend_handles_labels()[0]:
            leg = ax.legend(fontsize=8, loc="best", frameon=True, framealpha=0.95,
                            edgecolor=COLOR_BORDE)
            for t in leg.get_texts():
                t.set_color(COLOR_TEXTO)
        self.fig.tight_layout()
        self.canvas.draw_idle()


# ===================== APP ===================== #

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Sistema de Barrido Automatizado de Frecuencias")
        self.geometry("1240x940")
        self.minsize(1100, 820)
        self.configure(fg_color=COLOR_FONDO_FRAME)
        global FUENTE
        FUENTE = elegir_fuente_ui()
        aplicar_tema()
        configurar_estilos()

        self.puerto = Puerto()
        self.ultimo_puerto = PUERTO_DEFECTO
        try:
            self.puerto.conectar(PUERTO_DEFECTO)
        except (serial.SerialException, OSError):
            pass   # queda en modo simulacion

        self.current_frame = None
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.show_menu()

    def _quitar_frame(self):
        if self.current_frame is not None:
            if hasattr(self.current_frame, "detener"):
                self.current_frame.detener(silencioso=True)
            self.current_frame.destroy()
            self.current_frame = None

    def show_menu(self):
        self._quitar_frame()
        self.current_frame = MenuFrame(self)
        self.current_frame.pack(fill="both", expand=True)

    def show_barrido(self, con_bode):
        self._quitar_frame()
        self.current_frame = BarridoFrame(self, con_bode)
        self.current_frame.pack(fill="both", expand=True)

    def cerrar(self):
        self._quitar_frame()
        self.puerto.cerrar()
        self.destroy()


# ===================== FRAME: MENU PRINCIPAL ===================== #

class MenuFrame(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color=COLOR_FONDO_FRAME)
        self.app = master

        # --- banda superior ---
        banda = ctk.CTkFrame(self, fg_color=COLOR_TITULO, corner_radius=0, height=112)
        banda.pack(fill="x")
        banda.pack_propagate(False)
        ctk.CTkFrame(banda, height=3, corner_radius=0, fg_color=COLOR_PRINCIPAL).pack(
            side="bottom", fill="x")
        ctk.CTkButton(banda, text="Salir", width=84, height=32, font=(FUENTE, 13, "bold"),
                      fg_color="#21345C", hover_color=COLOR_DETENER, border_width=1,
                      border_color="#3A5185", command=master.cerrar).place(
            relx=1.0, x=-24, y=16, anchor="ne")
        ctk.CTkLabel(banda, text="Sistema de Barrido Automatizado de Frecuencias",
                     font=(FUENTE, 26, "bold"), text_color="white").pack(pady=(24, 2))
        ctk.CTkLabel(banda, text="Medidas Electrónicas I  ·  Respuesta en frecuencia de un circuito",
                     font=(FUENTE, 13), text_color="#9FB0CF").pack()

        centro = ctk.CTkFrame(self, fg_color="transparent")
        centro.pack(expand=True)

        # --- conexion ---
        con = tarjeta(centro)
        con.pack(pady=(26, 18), ipadx=10)
        if os.path.exists(IMAGEN_GENERADOR):
            img = ImageOps.contain(Image.open(IMAGEN_GENERADOR), (560, 150))
            banner = ctk.CTkImage(light_image=img, size=img.size)
            ctk.CTkLabel(con, image=banner, text="").pack(padx=16, pady=(14, 4))
        ctk.CTkLabel(con, text="Conexión con el generador", font=(FUENTE, 15, "bold"),
                     text_color=COLOR_TITULO).pack(pady=(6, 6))
        caja = ctk.CTkFrame(con, fg_color="transparent")
        caja.pack(padx=16)
        ctk.CTkLabel(caja, text="Puerto serie", font=(FUENTE, 13), text_color=COLOR_SUAVE).pack(
            side="left", padx=(0, 8))
        self.combo = ctk.CTkComboBox(caja, values=self._puertos(), width=170)
        self.combo.set(master.ultimo_puerto)
        self.combo.pack(side="left", padx=4)
        ctk.CTkButton(caja, text="↻", width=34, fg_color="#E3E8F1", hover_color="#D3DAE8",
                      text_color=COLOR_TEXTO, command=self._actualizar_lista).pack(side="left", padx=4)
        ctk.CTkButton(caja, text="Conectar", width=100, command=self.conectar).pack(side="left", padx=4)
        ctk.CTkButton(caja, text="Probar conexión", width=140, fg_color=COLOR_TURQUESA,
                      hover_color=COLOR_TURQUESA_HOVER, command=self.probar).pack(side="left", padx=4)

        self.l_con = ctk.CTkLabel(con, text="", font=(FUENTE, 13, "bold"))
        self.l_con.pack(pady=(10, 0))
        self.l_id = ctk.CTkLabel(con, text="", font=(FUENTE, 12), text_color=COLOR_TEXTO,
                                 wraplength=520)
        self.l_id.pack(pady=(2, 14))
        self._estado_conexion()

        # --- modos ---
        modos = ctk.CTkFrame(centro, fg_color="transparent")
        modos.pack(pady=(0, 30))

        def modo(col, icono, titulo, texto, boton, bode):
            c = tarjeta(modos, width=340, height=238)
            c.grid(row=0, column=col, padx=12, sticky="ns")
            c.pack_propagate(False)
            ctk.CTkLabel(c, text=icono, font=(FUENTE, 30), text_color=COLOR_PRINCIPAL).pack(
                pady=(18, 0))
            ctk.CTkLabel(c, text=titulo, font=(FUENTE, 18, "bold"), text_color=COLOR_TITULO).pack(
                pady=(2, 4))
            ctk.CTkLabel(c, text=texto, font=(FUENTE, 12), text_color=COLOR_SUAVE, wraplength=290,
                         justify="center").pack(padx=24)
            ctk.CTkButton(c, text=boton, height=44, font=(FUENTE, 15, "bold"), corner_radius=10,
                          command=lambda: master.show_barrido(bode)).pack(
                fill="x", padx=24, pady=(14, 20))

        modo(0, "Hz", "Barrido simple",
             "Recorre una lista de frecuencias en el generador, en modo automático o manual, "
             "sin graficar.", "Empezar barrido simple", False)
        modo(1, "dB", "Barrido con Bode",
             "Cargás el Vpp medido en cada frecuencia y el programa grafica, y calcula la "
             "punto de máxima ganancia, los puntos de −3 dB y el Q.", "Empezar con Bode", True)

    @staticmethod
    def _puertos():
        lista = [p.device for p in serial.tools.list_ports.comports()]
        return lista or [PUERTO_DEFECTO]

    def _actualizar_lista(self):
        self.combo.configure(values=self._puertos())

    def _estado_conexion(self):
        p = self.app.puerto
        if p.conectado:
            self.l_con.configure(text=f"✅ Conectado a {p.nombre}", text_color=COLOR_OK)
        else:
            self.l_con.configure(
                text="⚠️ Sin conexión: modo simulación (los comandos solo se muestran en la consola)",
                text_color=COLOR_AVISO)

    def conectar(self):
        nombre = self.combo.get().strip()
        self.l_id.configure(text="")
        try:
            self.app.puerto.conectar(nombre)
            self.app.ultimo_puerto = nombre
        except (serial.SerialException, OSError, ValueError) as e:
            self.app.puerto.cerrar()
            self.l_id.configure(text=f"No se pudo abrir {nombre}: {e}", text_color=COLOR_ERROR)
        self._estado_conexion()

    def probar(self):
        p = self.app.puerto
        if not p.conectado:
            self.l_id.configure(text="No hay un puerto abierto: conectá primero.", text_color=COLOR_ERROR)
            return
        resp = p.consultar("*IDN?") or p.consultar("ID?")
        if resp:
            self.l_id.configure(text=f"Respuesta del generador: {resp}", text_color=COLOR_OK)
        else:
            self.l_id.configure(text="El generador no respondió a *IDN? ni a ID?. Revisá cable, puerto y baudios.",
                                text_color=COLOR_ERROR)


# ===================== FRAME: BARRIDO ===================== #

class BarridoFrame(ctk.CTkFrame):
    def __init__(self, master, con_bode):
        super().__init__(master, fg_color=COLOR_FONDO_FRAME)
        self.app = master
        self.puerto = master.puerto
        self.con_bode = con_bode

        self.frecuencias = []
        self.index = 0
        self.activo = False
        self._token = 0             # identifica el barrido automatico en curso
        self._auto_job = None
        self._pausado = False
        self._tiempo = 1.0
        self.mediciones = []        # [(f, Vpp medido, Vin con que se midio)]
        self.vin = VPP_DEFECTO
        self._ids = []              # filas de la tabla de secuencia (modo simple)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._armar_encabezado()
        cuerpo = ctk.CTkFrame(self, fg_color=COLOR_FONDO_FRAME)
        cuerpo.grid(row=1, column=0, sticky="nsew", padx=16, pady=14)
        cuerpo.columnconfigure(1, weight=1)
        cuerpo.rowconfigure(0, weight=1)
        self._armar_izquierda(cuerpo)
        self._armar_derecha(cuerpo)

        self.puerto.on_tx = self._log_cmd
        self.cfg.on_change = self._config_cambio
        self._config_cambio()
        if not self.con_bode:
            self._modo_cambio()

    # ---------------- construccion de la interfaz ---------------- #

    def _armar_encabezado(self):
        barra = ctk.CTkFrame(self, fg_color=COLOR_TITULO, corner_radius=0, height=64)
        barra.grid(row=0, column=0, sticky="ew")
        barra.pack_propagate(False)
        ctk.CTkFrame(barra, height=3, corner_radius=0, fg_color=COLOR_PRINCIPAL).pack(
            side="bottom", fill="x")
        titulo = "Barrido con diagrama de Bode" if self.con_bode else "Barrido simple"
        sub = ("Cargá el Vpp medido en cada frecuencia y obtené máxima ganancia, ±3 dB y Q"
               if self.con_bode else "Enviá una secuencia de frecuencias al generador")
        textos = ctk.CTkFrame(barra, fg_color="transparent")
        textos.pack(side="left", padx=24)
        ctk.CTkLabel(textos, text=titulo, font=(FUENTE, 20, "bold"), text_color="white",
                     anchor="w").pack(anchor="w", pady=(10, 0))
        ctk.CTkLabel(textos, text=sub, font=(FUENTE, 12), text_color="#9FB0CF",
                     anchor="w").pack(anchor="w")
        ctk.CTkButton(barra, text="←  Menú", width=104, height=34, font=(FUENTE, 13, "bold"),
                      fg_color="#21345C", hover_color="#2E4678", border_width=1,
                      border_color="#3A5185", command=self.volver_menu).pack(
            side="right", padx=(8, 22), pady=(10, 13))
        p = self.puerto
        if p.conectado:
            chip, color = f"●  {p.nombre}", "#4ADE80"
        else:
            chip, color = "●  Simulación", "#FBBF24"
        ctk.CTkLabel(barra, text=chip, font=(FUENTE, 12, "bold"), text_color=color).pack(
            side="right", padx=8, pady=(10, 13))

    def _armar_izquierda(self, cuerpo):
        # columna con scroll: si la pantalla es chica, se baja con la rueda del mouse
        izq = ctk.CTkScrollableFrame(cuerpo, fg_color=COLOR_FONDO_FRAME, width=362, corner_radius=0,
                                     scrollbar_button_color="#CBD3E1",
                                     scrollbar_button_hover_color="#9AA6BC")
        izq.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self.cfg = PanelConfig(izq)
        self.cfg.pack(fill="x")

        # Tension del generador: se puede cambiar en cualquier momento
        caja_v = tarjeta(izq)
        caja_v.pack(fill="x", pady=(14, 0))
        caja_v.columnconfigure(1, weight=1)
        ctk.CTkLabel(caja_v, text="Tensión del generador", font=(FUENTE, 15, "bold"),
                     text_color=COLOR_TITULO).grid(row=0, column=0, columnspan=2,
                                                   padx=14, pady=(12, 4), sticky="w")
        ctk.CTkLabel(caja_v, text="Amplitud (Vpp)", font=(FUENTE, 13)).grid(
            row=1, column=0, padx=(14, 4), pady=5, sticky="w")
        self.v_vpp = ctk.StringVar(value=f"{VPP_DEFECTO:g}")
        self.e_vpp = ctk.CTkEntry(caja_v, textvariable=self.v_vpp, width=110, justify="right")
        self.e_vpp.grid(row=1, column=1, padx=(4, 14), pady=5, sticky="e")
        self.e_vpp.bind("<Return>", self.aplicar_tension)
        ctk.CTkButton(caja_v, text="Aplicar tensión (envía el comando)", fg_color=COLOR_PRINCIPAL,
                      hover_color=COLOR_HOVER, command=self.aplicar_tension).grid(
            row=2, column=0, columnspan=2, padx=14, pady=(6, 4), sticky="ew")
        self.l_vpp = ctk.CTkLabel(caja_v, text="Todavía no se envió ninguna tensión.",
                                  font=(FUENTE, 12), justify="left", anchor="w", wraplength=300)
        self.l_vpp.grid(row=3, column=0, columnspan=2, padx=14, pady=(2, 8), sticky="w")

        # Forma de onda y offset (opcional; por defecto senoidal sin offset)
        self.codigo, self.abrev, self.offset = FORMAS_ONDA[FORMA_DEFECTO][0], FORMAS_ONDA[FORMA_DEFECTO][1], 0.0
        ctk.CTkFrame(caja_v, height=1, fg_color=COLOR_BORDE).grid(
            row=4, column=0, columnspan=2, padx=14, pady=(2, 6), sticky="ew")
        ctk.CTkLabel(caja_v, text="Forma de onda y offset", font=(FUENTE, 14, "bold"),
                     text_color=COLOR_TITULO).grid(row=5, column=0, columnspan=2,
                                                   padx=14, pady=(0, 2), sticky="w")
        ctk.CTkLabel(caja_v, text="Forma", font=(FUENTE, 13)).grid(
            row=6, column=0, padx=(14, 4), pady=4, sticky="w")
        self.v_forma = ctk.StringVar(value=FORMA_DEFECTO)
        ctk.CTkOptionMenu(caja_v, variable=self.v_forma, values=list(FORMAS_ONDA), width=130,
                          fg_color=COLOR_PRINCIPAL, button_color=COLOR_HOVER,
                          command=lambda _n: self.aplicar_forma()).grid(
            row=6, column=1, padx=(4, 14), pady=4, sticky="e")
        ctk.CTkLabel(caja_v, text="Offset (V)", font=(FUENTE, 13)).grid(
            row=7, column=0, padx=(14, 4), pady=4, sticky="w")
        self.v_offset = ctk.StringVar(value="0")
        e_off = ctk.CTkEntry(caja_v, textvariable=self.v_offset, width=130, justify="right")
        e_off.grid(row=7, column=1, padx=(4, 14), pady=4, sticky="e")
        e_off.bind("<Return>", self.aplicar_forma)
        ctk.CTkButton(caja_v, text="Aplicar forma y offset", fg_color=COLOR_TURQUESA,
                      hover_color=COLOR_TURQUESA_HOVER, command=self.aplicar_forma).grid(
            row=8, column=0, columnspan=2, padx=14, pady=(6, 4), sticky="ew")
        self.l_forma = ctk.CTkLabel(caja_v, text="Por defecto: senoidal, offset 0.",
                                    font=(FUENTE, 12), justify="left", anchor="w", wraplength=300)
        self.l_forma.grid(row=9, column=0, columnspan=2, padx=14, pady=(2, 12), sticky="w")

        # Registro de comandos SCPI enviados al generador
        caja_l = tarjeta(izq)
        caja_l.pack(fill="x", pady=(14, 0))
        ctk.CTkLabel(caja_l, text="Comandos enviados", font=(FUENTE, 15, "bold"),
                     text_color=COLOR_TITULO).pack(anchor="w", padx=14, pady=(12, 4))
        fuente_log = elegir_fuente(["DejaVu Sans Mono", "Consolas", "Liberation Mono", "Courier New"])
        self.t_log = ctk.CTkTextbox(caja_l, height=110, font=(fuente_log, 12))
        self.t_log.pack(fill="x", padx=14, pady=(0, 14))
        self.t_log.configure(state="disabled")

    def _log_cmd(self, comando):
        self.t_log.configure(state="normal")
        self.t_log.insert("end", f"{time.strftime('%H:%M:%S')}  {comando}\n")
        filas = int(self.t_log.index("end-1c").split(".")[0])
        if filas > 300:
            self.t_log.delete("1.0", f"{filas - 300}.0")
        self.t_log.see("end")
        self.t_log.configure(state="disabled")

    def destroy(self):
        self.puerto.on_tx = None
        super().destroy()

    def _armar_derecha(self, cuerpo):
        der = ctk.CTkFrame(cuerpo, fg_color=COLOR_FONDO_FRAME)
        der.grid(row=0, column=1, sticky="nsew")
        der.columnconfigure(0, weight=1)

        cgen = tarjeta(der)
        cgen.grid(row=0, column=0, sticky="ew")
        if self.con_bode:
            self.gen = GeneradorVisual(cgen, 460, 205)
        else:
            self.gen = GeneradorVisual(cgen, 600, 270)
        self.gen.pack(pady=(12, 2))
        self.l_estado = ctk.CTkLabel(cgen, text="Esperando inicio...", font=(FUENTE, 17, "bold"),
                                     text_color=COLOR_TITULO)
        self.l_estado.pack(pady=(2, 6))
        self.progreso = ctk.CTkProgressBar(cgen, height=8)
        self.progreso.set(0)
        self.progreso.pack(fill="x", padx=40, pady=(0, 14))

        # --- tarjeta de controles ---
        ctrl = tarjeta(der)
        ctrl.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        if not self.con_bode:
            opc = ctk.CTkFrame(ctrl, fg_color="transparent")
            opc.pack(fill="x", padx=14, pady=(12, 0))
            ctk.CTkLabel(opc, text="Modo", font=(FUENTE, 13)).pack(side="left")
            self.v_modo = ctk.StringVar(value="Automático")
            ctk.CTkSegmentedButton(opc, values=["Automático", "Manual"], variable=self.v_modo,
                                   command=self._modo_cambio).pack(side="left", padx=(8, 24))
            ctk.CTkLabel(opc, text="Tiempo entre frecuencias (s)", font=(FUENTE, 13)).pack(side="left")
            self.v_tiempo = ctk.StringVar(value="1.0")
            self.e_tiempo = ctk.CTkEntry(opc, textvariable=self.v_tiempo, width=70, justify="right")
            self.e_tiempo.pack(side="left", padx=8)

        ir = ctk.CTkFrame(ctrl, fg_color="transparent")
        ir.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(ir, text="Ir a una frecuencia específica (Hz)", font=(FUENTE, 13)).pack(side="left")
        self.v_ir = ctk.StringVar(value="")
        e_ir = ctk.CTkEntry(ir, textvariable=self.v_ir, width=110, justify="right",
                            placeholder_text="ej. 15k")
        e_ir.pack(side="left", padx=8)
        e_ir.bind("<Return>", self.ir_a_frecuencia)
        ctk.CTkButton(ir, text="Ir", width=60, fg_color=COLOR_TURQUESA,
                      hover_color=COLOR_TURQUESA_HOVER, command=self.ir_a_frecuencia).pack(side="left")
        self.l_ir = ctk.CTkLabel(ir, text="", font=(FUENTE, 12), anchor="w")
        self.l_ir.pack(side="left", padx=10)

        fila = ctk.CTkFrame(ctrl, fg_color="transparent")
        fila.pack(fill="x", padx=10, pady=12)
        estilo = {"font": (FUENTE, 14, "bold"), "height": 42, "corner_radius": 10, "text_color": "white"}

        def boton(col, texto, color, hover, cmd):
            fila.columnconfigure(col, weight=1)
            b = ctk.CTkButton(fila, text=texto, fg_color=color, hover_color=hover, command=cmd, **estilo)
            b.grid(row=0, column=col, sticky="ew", padx=4)
            return b

        self.b_iniciar = boton(0, "Iniciar", COLOR_PRINCIPAL, COLOR_HOVER, self.iniciar)
        if self.con_bode:
            self.b_ant = boton(1, "◀ Punto anterior", COLOR_NARANJA, COLOR_NARANJA_HOVER, self.anterior)
            boton(2, "Detener", COLOR_DETENER, COLOR_DETENER_HOVER, self.detener)
        else:
            self.b_ant = boton(1, "◀ Anterior", COLOR_TURQUESA, COLOR_TURQUESA_HOVER,
                               self.anterior_simple)
            self.b_sig = boton(2, "Siguiente ▶", COLOR_PRINCIPAL, COLOR_HOVER, self.siguiente)
            self.b_pausa = boton(3, "Pausar", COLOR_NARANJA, COLOR_NARANJA_HOVER, self.alternar_pausa)
            boton(4, "Detener", COLOR_DETENER, COLOR_DETENER_HOVER, self.detener)

        if self.con_bode:
            self._armar_medicion(der)
        else:
            self._armar_secuencia(der)

    def _armar_secuencia(self, der):
        """Tabla con todas las frecuencias del barrido y cual se esta enviando."""
        der.rowconfigure(4, weight=1)
        card = tarjeta(der)
        card.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        cab = ctk.CTkFrame(card, fg_color="transparent")
        cab.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        ctk.CTkLabel(cab, text="Secuencia de frecuencias", font=(FUENTE, 15, "bold"),
                     text_color=COLOR_TITULO).pack(side="left")
        ctk.CTkButton(cab, text="Quitar seleccionadas", width=140, height=28, fg_color=COLOR_NARANJA,
                      hover_color=COLOR_NARANJA_HOVER, command=self.seq_quitar).pack(side="right")
        ctk.CTkButton(cab, text="＋ Agregar", width=100, height=28, fg_color=COLOR_TURQUESA,
                      hover_color=COLOR_TURQUESA_HOVER, command=self.seq_agregar).pack(
            side="right", padx=8)
        ctk.CTkLabel(cab, text="Doble clic en una frecuencia para editarla", font=(FUENTE, 11),
                     text_color=COLOR_SUAVE).pack(side="right", padx=8)
        cont = tk.Frame(card, bg=COLOR_PANEL)
        cont.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        cont.columnconfigure(0, weight=1)
        cont.rowconfigure(0, weight=1)
        self.tabla_seq = ttk.Treeview(cont, columns=("n", "f", "estado"), show="headings", height=5)
        for col, txt, ancho, ancla in (("n", "N°", 60, "center"), ("f", "Frecuencia", 200, "center"),
                                       ("estado", "Estado", 240, "w")):
            self.tabla_seq.heading(col, text=txt)
            self.tabla_seq.column(col, width=ancho, anchor=ancla)
        self.tabla_seq.configure(selectmode="extended")
        self.tabla_seq.bind("<Double-1>", self._seq_editar_celda)
        self.tabla_seq.bind("<Delete>", lambda e: self.seq_quitar())
        self.tabla_seq.tag_configure("pendiente", foreground=COLOR_SUAVE)
        self.tabla_seq.tag_configure("actual", background="#DCE7FF", foreground=COLOR_TITULO)
        self.tabla_seq.tag_configure("hecho", foreground=COLOR_OK)
        sb = ttk.Scrollbar(cont, orient="vertical", command=self.tabla_seq.yview)
        self.tabla_seq.configure(yscrollcommand=sb.set)
        self.tabla_seq.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

    def _armar_medicion(self, der):
        """Campo para cargar el Vpp medido + grafico de Bode + tabla de resultados."""
        der.rowconfigure(5, weight=1)
        fila = tarjeta(der)
        fila.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ctk.CTkLabel(fila, text="Vpp medido en el osciloscopio:", font=(FUENTE, 14)).pack(
            side="left", padx=(16, 8), pady=12)
        self.e_med = ctk.CTkEntry(fila, width=120, font=(FUENTE, 16), justify="right")
        self.e_med.pack(side="left", padx=4)
        self.e_med.bind("<Return>", self.registrar)
        ctk.CTkButton(fila, text="Registrar y siguiente ▶", fg_color=COLOR_PRINCIPAL,
                      hover_color=COLOR_HOVER, font=(FUENTE, 14, "bold"),
                      command=self.registrar).pack(side="left", padx=12)
        ctk.CTkLabel(fila, text="(Enter también sirve; acepta 5.2 o 800mV)", font=(FUENTE, 11),
                     text_color=COLOR_SUAVE).pack(side="left", padx=4)

        cuerpo = ctk.CTkFrame(der, fg_color=COLOR_FONDO_FRAME)
        cuerpo.grid(row=5, column=0, sticky="nsew", pady=(12, 0))
        cuerpo.columnconfigure(0, weight=1)
        cuerpo.rowconfigure(0, weight=1)
        self.graf = GraficoBode(cuerpo)
        self.graf.grid(row=0, column=0, sticky="nsew")

        lat = tarjeta(cuerpo)
        lat.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        cont = tk.Frame(lat, bg=COLOR_PANEL)
        cont.pack(fill="x", padx=10, pady=(10, 0))
        self.tabla = ttk.Treeview(cont, columns=("f", "vi", "v", "g"), show="headings", height=7)
        for col, txt, ancho in (("f", "Frec.", 82), ("vi", "Vin", 52),
                                ("v", "Vout", 60), ("g", "Gan. dB", 72)):
            self.tabla.heading(col, text=txt)
            self.tabla.column(col, width=ancho, anchor="center")
        sb = ttk.Scrollbar(cont, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=sb.set)
        self.tabla.pack(side="left")
        sb.pack(side="left", fill="y")

        self.l_res = ctk.CTkLabel(lat, text="", font=(FUENTE, 13), justify="left",
                                  anchor="w", wraplength=290)
        self.l_res.pack(fill="x", padx=12, pady=8)
        bt = ctk.CTkFrame(lat, fg_color="transparent")
        bt.pack(fill="x", padx=10, pady=(0, 12))
        ctk.CTkButton(bt, text="Exportar CSV", width=130, fg_color=COLOR_PRINCIPAL,
                      hover_color=COLOR_HOVER, command=self.exportar_csv).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bt, text="Guardar gráfico", width=130, fg_color=COLOR_PRINCIPAL,
                      hover_color=COLOR_HOVER, command=self.exportar_png).pack(side="left")

    # ---------------- utilidades de UI ---------------- #

    def _estado(self, texto, error=False):
        self.l_estado.configure(text=texto, text_color=COLOR_ERROR if error else COLOR_TITULO)

    def _modo_cambio(self, *_):
        if self.con_bode:
            return
        auto = self.v_modo.get() == "Automático"
        self.e_tiempo.configure(state="normal" if auto else "disabled")
        self.b_sig.configure(state="disabled" if auto else "normal")
        self.b_pausa.configure(state="normal" if auto else "disabled")

    def _config_cambio(self):
        if self.activo:
            return
        frs = self.cfg.frecuencias
        if self.con_bode:
            if frs:
                self.graf.set_rango(min(frs), max(frs))
                self._redibujar()
        else:
            self._llenar_secuencia(frs)

    def _mostrar_frecuencia(self, f, i, n):
        self.gen.set_frecuencia(f)
        self._estado(f"Frecuencia actual: {fmt_hz(f)}   ({i + 1}/{n})")
        self.progreso.set((i + 1) / n)
        if not self.con_bode:
            self._marcar_seq(i)

    def _error_comunicacion(self):
        self._estado(f"Error de comunicación con el generador: {self.puerto.error}", True)
        self.detener(silencioso=True)

    # ---------------- tabla de secuencia (modo simple) ---------------- #

    def _llenar_secuencia(self, frs):
        hijos = self.tabla_seq.get_children()
        if hijos:
            self.tabla_seq.delete(*hijos)
        self._ids = []
        for k, f in enumerate(frs or []):
            iid = self.tabla_seq.insert("", "end", values=(k + 1, fmt_hz(f), "pendiente"),
                                        tags=("pendiente",))
            self._ids.append(iid)

    def _seq_puede_editar(self):
        if self.activo:
            self._estado("Detené el barrido para editar la secuencia.", True)
            return None
        frs = self.cfg.frecuencias
        if not frs:
            self._estado("Primero corregí la configuración del barrido.", True)
            return None
        return list(frs)

    def _seq_editar_celda(self, event):
        """Doble clic sobre una frecuencia: aparece un campo para cambiarla."""
        iid = self.tabla_seq.identify_row(event.y)
        if not iid or self.tabla_seq.identify_column(event.x) != "#2" or iid not in self._ids:
            return
        frs = self._seq_puede_editar()
        if frs is None:
            return
        k = self._ids.index(iid)
        x, y, w, h = self.tabla_seq.bbox(iid, "f")
        entrada = tk.Entry(self.tabla_seq, justify="center", font=(FUENTE, 11), relief="solid", bd=1)
        entrada.insert(0, fmt_cmd(frs[k]))
        entrada.select_range(0, "end")
        entrada.place(x=x, y=y, width=w, height=h)
        entrada.focus_set()
        hecho = [False]

        def cerrar(guardar):
            if hecho[0]:
                return
            hecho[0] = True
            texto = entrada.get()
            entrada.destroy()
            if not guardar:
                return
            try:
                nuevo = parse_num(texto)
                if nuevo <= 0:
                    raise ValueError
            except ValueError:
                self._estado("Frecuencia inválida (ej. 15k o 15000).", True)
                return
            frs[k] = nuevo
            self.cfg.set_lista(frs)

        entrada.bind("<Return>", lambda e: cerrar(True))
        entrada.bind("<Escape>", lambda e: cerrar(False))
        entrada.bind("<FocusOut>", lambda e: cerrar(True))

    def seq_quitar(self):
        frs = self._seq_puede_editar()
        if frs is None:
            return
        sel = [self._ids.index(i) for i in self.tabla_seq.selection() if i in self._ids]
        if not sel:
            self._estado("Seleccioná una o más filas de la tabla para quitarlas.", True)
            return
        quedan = [f for k, f in enumerate(frs) if k not in sel]
        if not quedan:
            self._estado("No se pueden quitar todas las frecuencias.", True)
            return
        self.cfg.set_lista(quedan)
        self._estado(f"Se quitaron {len(sel)} frecuencias.")

    def seq_agregar(self):
        frs = self._seq_puede_editar()
        if frs is None:
            return
        dlg = ctk.CTkInputDialog(text="Frecuencia a agregar (ej. 15k o 15000 Hz).\n"
                                      "Se inserta en su lugar si la lista está ordenada.",
                                 title="Agregar frecuencia")
        texto = dlg.get_input()
        if not texto:
            return
        try:
            nueva = parse_num(texto)
            if nueva <= 0:
                raise ValueError
        except ValueError:
            self._estado("Frecuencia inválida (ej. 15k o 15000).", True)
            return
        creciente = all(a <= b for a, b in zip(frs, frs[1:]))
        if creciente:
            frs.append(nueva)
            frs.sort()
        else:
            frs.append(nueva)
        self.cfg.set_lista(frs)

    def _fila_seq(self, k, estado, tag):
        if 0 <= k < len(self._ids):
            n, f, _ = self.tabla_seq.item(self._ids[k], "values")
            self.tabla_seq.item(self._ids[k], values=(n, f, estado), tags=(tag,))

    def _marcar_seq(self, i):
        self._fila_seq(i - 1, "✓ enviada", "hecho")
        self._fila_seq(i, "● en el generador", "actual")
        if 0 <= i < len(self._ids):
            self.tabla_seq.see(self._ids[i])

    # ---------------- tension del generador ---------------- #

    def _leer_vpp(self):
        try:
            return parse_voltaje(self.v_vpp.get())
        except ValueError:
            return None

    def _msg_tension(self, vpp):
        extra = " Los puntos que cargues desde ahora usan este Vin." if self.con_bode else ""
        self.l_vpp.configure(
            text=f"✅ Enviado: :AMPL:VOLT {vpp * FACTOR_AMPL:g}  ({vpp:g} Vpp).{extra}",
            text_color=COLOR_OK)

    def aplicar_tension(self, event=None):
        """Cambia la amplitud del generador (manda el comando) en cualquier momento."""
        vpp = self._leer_vpp()
        if vpp is None:
            self.l_vpp.configure(text="Ingresá una tensión mayor que 0 (ej. 5 o 2.5).",
                                 text_color=COLOR_ERROR)
            return
        self.vin = vpp
        self.puerto.set_amplitud(vpp)
        if self.puerto.error:
            self._error_comunicacion()
            return
        self.gen.set_info(vpp, self.abrev, self.offset)
        self._msg_tension(vpp)

    def _leer_forma_offset(self):
        """Devuelve (codigo, abrev, offset) o None si el offset es inválido."""
        try:
            offset = parse_offset(self.v_offset.get())
        except ValueError as e:
            self.l_forma.configure(text=str(e), text_color=COLOR_ERROR)
            return None
        codigo, abrev, _ok = FORMAS_ONDA[self.v_forma.get()]
        return codigo, abrev, offset

    def ir_a_frecuencia(self, event=None):
        """Manda el generador a una frecuencia puntual, fuera del barrido."""
        try:
            f = parse_num(self.v_ir.get())
            if f <= 0:
                raise ValueError
        except ValueError:
            self.l_ir.configure(text="Ingresá una frecuencia > 0 (ej. 15k)", text_color=COLOR_ERROR)
            return
        self.puerto.set_frecuencia(f)
        if self.puerto.error:
            self._error_comunicacion()
            return
        self.gen.set_frecuencia(f)
        extra = ""
        if self.activo and self.con_bode and self.index < len(self.frecuencias):
            self.frecuencias[self.index] = f      # el punto actual se mide a esta frecuencia
            self._estado(f"Punto {self.index + 1}/{len(self.frecuencias)} · {fmt_hz(f)}  —  medí y cargá el Vpp")
            extra = " · punto actual"
        self.l_ir.configure(text=f"✅ :FREQ {fmt_cmd(f)}{extra}", text_color=COLOR_OK)

    def aplicar_forma(self, event=None):
        """Manda :FUNC:WAV y :OFFS al generador (se puede usar también con el barrido en curso)."""
        datos = self._leer_forma_offset()
        if datos is None:
            return
        codigo, abrev, offset = datos
        self.codigo, self.abrev, self.offset = codigo, abrev, offset
        self.puerto.set_forma(codigo)
        time.sleep(0.05)
        self.puerto.set_offset(offset)
        if self.puerto.error:
            self._error_comunicacion()
            return
        vpp = self._leer_vpp() or self.vin or VPP_DEFECTO
        self.gen.set_info(vpp, abrev, offset)
        self.l_forma.configure(
            text=f"✅ Enviado: :FUNC:WAV {codigo} ({self.v_forma.get()}) y :OFFS {offset:g}.",
            text_color=COLOR_OK)

    # ---------------- control del barrido ---------------- #

    def iniciar(self):
        frs = self.cfg.frecuencias
        if not frs:
            self._estado("Revisá la configuración del barrido (hay un error).", True)
            return
        vpp = self._leer_vpp()
        if vpp is None:
            self._estado("La amplitud tiene que ser un número mayor que 0.", True)
            return

        self._cancelar_auto()   # corta un barrido anterior si seguía corriendo
        self.frecuencias = list(frs)
        self.vin = vpp
        self.index = 0
        self.mediciones = []
        self.activo = True
        self.puerto.error = None
        self.progreso.set(0)
        self.cfg.deshabilitar(True)
        datos = self._leer_forma_offset()
        if datos is None:
            self._cancelar_auto()
            self.activo = False
            self.cfg.deshabilitar(False)
            self._estado("Revisá el offset (tiene que ser un número en volts).", True)
            return
        self.codigo, self.abrev, self.offset = datos[:3]
        self.puerto.configurar_senal(vpp, self.codigo, self.offset)
        self.gen.set_info(vpp, self.abrev, self.offset)
        self._msg_tension(vpp)
        self.gen.set_salida(True)

        if self.con_bode:
            self._limpiar_tabla()
            self.graf.set_rango(min(frs), max(frs))
            self._redibujar()
            self._enviar_actual()
            return

        self._llenar_secuencia(self.frecuencias)
        self.b_pausa.configure(text="Pausar")
        if self.v_modo.get() == "Automático":
            try:
                tiempo = parse_num(self.v_tiempo.get())
                if tiempo <= 0:
                    raise ValueError
            except ValueError:
                tiempo = 1.0
            self._estado("Iniciando barrido automático...")
            self._token += 1
            self._auto_tick(0, tiempo, self._token)
        else:
            self._estado("Modo manual listo. Presioná 'Siguiente frecuencia' para comenzar.")

    def _cancelar_auto(self):
        self._token += 1
        self._pausado = False
        if self._auto_job is not None:
            try:
                self.after_cancel(self._auto_job)
            except (tk.TclError, ValueError):
                pass
            self._auto_job = None

    def _auto_tick(self, i, tiempo, token):
        """Un paso del barrido automatico: manda la frecuencia i y agenda la siguiente."""
        if token != self._token or not self.activo:
            return
        if self._pausado:
            self._auto_job = self.after(100, self._auto_tick, i, tiempo, token)
            return
        self._tiempo = tiempo
        i = self.index          # la frecuencia que toca enviar (cambia si se vuelve atras)
        n = len(self.frecuencias)
        if i >= n:
            self._fin_barrido()
            return
        f = self.frecuencias[i]
        self.puerto.set_frecuencia(f)
        if self.puerto.error:
            self._error_comunicacion()
            return
        self.index = i + 1
        self._mostrar_frecuencia(f, i, n)
        self._auto_job = self.after(int(tiempo * 1000), self._auto_tick, i + 1, tiempo, token)

    def siguiente(self):
        if not self.activo:
            self._estado("Primero presioná 'Iniciar'.", True)
            return
        n = len(self.frecuencias)
        if self.index < n:
            f = self.frecuencias[self.index]
            self.puerto.set_frecuencia(f)
            if self.puerto.error:
                self._error_comunicacion()
                return
            self._mostrar_frecuencia(f, self.index, n)
            self.index += 1
            if self.index >= n:
                self.l_estado.configure(
                    text=self.l_estado.cget("text") + " · último punto, 'Siguiente' para terminar")
        else:
            self._fin_barrido()

    def anterior_simple(self):
        """Vuelve a mandar al generador la frecuencia anterior a la actual."""
        if not self.activo:
            self._estado("Primero presioná 'Iniciar'.", True)
            return
        k = self.index - 2          # la actual es index-1; la anterior, index-2
        if k < 0:
            self._estado("Ya estás en la primera frecuencia.", True)
            return
        n = len(self.frecuencias)
        f = self.frecuencias[k]
        self.puerto.set_frecuencia(f)
        if self.puerto.error:
            self._error_comunicacion()
            return
        self.index = k + 1
        for j in range(k + 1, len(self._ids)):      # las que quedaron adelante vuelven a "pendiente"
            self._fila_seq(j, "pendiente", "pendiente")
        self._mostrar_frecuencia(f, k, n)
        if self.v_modo.get() == "Automático" and self._auto_job is not None:
            # el automatico sigue desde aca, con el tiempo completo antes del proximo salto
            self.after_cancel(self._auto_job)
            self._auto_job = self.after(int(self._tiempo * 1000), self._auto_tick, 0,
                                        self._tiempo, self._token)

    def alternar_pausa(self):
        if not self.activo or self.v_modo.get() != "Automático":
            return
        self._pausado = not self._pausado
        self.b_pausa.configure(text="Reanudar" if self._pausado else "Pausar")

    def detener(self, silencioso=False):
        self._cancelar_auto()
        estaba = self.activo
        self.activo = False
        self.gen.set_salida(False)
        self.cfg.deshabilitar(False)
        if not self.con_bode:
            self.b_pausa.configure(text="Pausar")
        if estaba and not silencioso:
            self._estado("Barrido detenido ❌")

    def _fin_barrido(self):
        self.activo = False
        self.gen.set_salida(False)
        self.cfg.deshabilitar(False)
        self.progreso.set(1)
        if not self.con_bode:
            self._fila_seq(len(self._ids) - 1, "✓ enviada", "hecho")
        self._estado("Barrido completado ✅")

    def volver_menu(self):
        self.detener(silencioso=True)
        self.app.show_menu()

    # ---------------- modo Bode ---------------- #

    def _enviar_actual(self, prefill=""):
        f = self.frecuencias[self.index]
        self.puerto.set_frecuencia(f)
        if self.puerto.error:
            self._error_comunicacion()
            return
        self.gen.set_frecuencia(f)
        self._estado(f"Punto {self.index + 1}/{len(self.frecuencias)} · {fmt_hz(f)}  —  medí y cargá el Vpp")
        self.progreso.set(self.index / len(self.frecuencias))
        self.e_med.delete(0, "end")
        if prefill:
            self.e_med.insert(0, prefill)
        self.e_med.focus_set()

    def registrar(self, event=None):
        if not self.activo:
            self._estado("Presioná 'Iniciar' primero.", True)
            return
        try:
            v = parse_voltaje(self.e_med.get())
        except ValueError as e:
            self._estado(str(e), True)
            return
        f = self.frecuencias[self.index]
        self.mediciones.append((f, v, self.vin))
        self._tabla_agregar(f, v, self.vin)
        self._redibujar()
        self.index += 1
        if self.index >= len(self.frecuencias):
            self.e_med.delete(0, "end")
            self._fin_barrido()
        else:
            self._enviar_actual()

    def anterior(self):
        if not self.mediciones:
            self._estado("Todavía no hay puntos cargados.", True)
            return
        f, v, _ = self.mediciones.pop()
        self.index = len(self.mediciones)
        self._tabla_quitar_ultimo()
        if not self.activo:
            self.activo = True
            self.gen.set_salida(True)
            self.cfg.deshabilitar(True)
        self._redibujar()
        self._enviar_actual(prefill=f"{v:g}")

    def _ganancias(self):
        return [20 * np.log10(v / vi) for _, v, vi in self.mediciones]

    def _redibujar(self):
        f = [m[0] for m in self.mediciones]
        g = self._ganancias()
        an = analizar_bode(f, g)
        self.graf.dibujar(f, g, an)
        self._mostrar_resultados(an)

    def _mostrar_resultados(self, an):
        if an is None:
            self.l_res.configure(text="Cargá al menos 3 puntos para detectar el punto de máxima ganancia.")
            return
        lineas = [f"Frecuencia de máx. ganancia: {fmt_hz(an['f_res'])}",
                  f"Ganancia máxima: {an['g_pico']:+.2f} dB"]
        lineas.append(f"f1 (-3 dB): {fmt_hz(an['f1'])}" if an["f1"] else "f1 (-3 dB): fuera del rango medido")
        lineas.append(f"f2 (-3 dB): {fmt_hz(an['f2'])}" if an["f2"] else "f2 (-3 dB): fuera del rango medido")
        if an["q"]:
            lineas.append(f"Ancho de banda: {fmt_hz(an['bw'])}")
            lineas.append(f"Q = f_máx / BW = {an['q']:.3g}")
        self.l_res.configure(text="\n".join(lineas))

    # ---------------- tabla y exportacion ---------------- #

    def _tabla_agregar(self, f, v, vi):
        g = 20 * np.log10(v / vi)
        self.tabla.insert("", "end", values=(fmt_hz(f), f"{vi:.4g}", f"{v:.4g}", f"{g:+.2f}"))
        self.tabla.yview_moveto(1)

    def _tabla_quitar_ultimo(self):
        hijos = self.tabla.get_children()
        if hijos:
            self.tabla.delete(hijos[-1])

    def _limpiar_tabla(self):
        hijos = self.tabla.get_children()
        if hijos:
            self.tabla.delete(*hijos)

    def exportar_csv(self):
        if not self.mediciones:
            self._estado("No hay mediciones para exportar.", True)
            return
        ruta = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="barrido_bode.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not ruta:
            return
        with open(ruta, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["frecuencia_Hz", "Vin_Vpp", "Vout_Vpp", "ganancia_dB"])
            for f, v, vi in self.mediciones:
                w.writerow([f, vi, v, round(20 * np.log10(v / vi), 3)])
        self._estado(f"CSV guardado: {os.path.basename(ruta)}")

    def exportar_png(self):
        ruta = filedialog.asksaveasfilename(defaultextension=".png", initialfile="bode.png",
                                            filetypes=[("PNG", "*.png")])
        if not ruta:
            return
        self.graf.fig.savefig(ruta, dpi=200)
        self._estado(f"Gráfico guardado: {os.path.basename(ruta)}")


# ===================== MAIN ===================== #

if __name__ == "__main__":
    App().mainloop()
