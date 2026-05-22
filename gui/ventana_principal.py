"""
gui/ventana_principal.py
Interfaz gráfica de WSP Comprobantes.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext


class VentanaPrincipal:
    def __init__(self, root: tk.Tk, controlador):
        self.root = root
        self.controlador = controlador

        self.root.title("WSP Comprobantes")
        self.root.geometry("820x560")
        self.root.resizable(True, True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_cerrar)

        self._construir_ui()

    def _construir_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        # Configuración
        conf = ttk.LabelFrame(main, text="Configuración", padding=10)
        conf.pack(fill="x", pady=(0, 6))

        ttk.Label(conf, text="Grupo de WhatsApp:").grid(
            row=0, column=0, sticky="e", padx=4, pady=3)
        self.entry_grupo = ttk.Entry(conf, width=44)
        self.entry_grupo.grid(row=0, column=1, columnspan=3, sticky="w", padx=4)

        ttk.Label(conf, text="Fecha inicio (dd/mm/yyyy):").grid(
            row=1, column=0, sticky="e", padx=4, pady=3)
        self.entry_fecha = ttk.Entry(conf, width=14)
        self.entry_fecha.insert(0, "01/01/2025")
        self.entry_fecha.grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(conf, text="Hora (hh:mm):").grid(
            row=1, column=2, sticky="e", padx=4)
        self.entry_hora = ttk.Entry(conf, width=8)
        self.entry_hora.insert(0, "00:00")
        self.entry_hora.grid(row=1, column=3, sticky="w", padx=4)

        self.var_lotes = tk.BooleanVar(value=False)
        self.chk_lotes = ttk.Checkbutton(
            conf,
            text="Modo lotes (el texto del grupo se usa como nombre de cliente)",
            variable=self.var_lotes,
            command=self._toggle_lotes)
        self.chk_lotes.grid(row=2, column=0, columnspan=4, sticky="w", padx=4, pady=3)

        ttk.Label(conf, text="Cliente fijo:").grid(
            row=3, column=0, sticky="e", padx=4, pady=3)
        self.entry_cliente = ttk.Entry(conf, width=36)
        self.entry_cliente.grid(row=3, column=1, columnspan=2, sticky="w", padx=4)

        ttk.Label(conf, text="Timeout lotes (min):").grid(
            row=3, column=2, sticky="e", padx=4)
        self.spin_timeout = ttk.Spinbox(conf, from_=1, to=60, width=6)
        self.spin_timeout.delete(0, "end")
        self.spin_timeout.insert(0, "10")
        self.spin_timeout.grid(row=3, column=3, sticky="w", padx=4)
        self.spin_timeout.config(state="disabled")

        # Botones
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=4)

        self.btn_iniciar = ttk.Button(
            btn_frame, text="▶  Iniciar", width=14,
            command=self._on_iniciar)
        self.btn_iniciar.pack(side="left", padx=4)

        self.btn_detener = ttk.Button(
            btn_frame, text="⏹  Detener", width=14,
            command=self._on_detener, state="disabled")
        self.btn_detener.pack(side="left", padx=4)

        self.lbl_estado = ttk.Label(
            btn_frame, text="Estado: inactivo", foreground="gray")
        self.lbl_estado.pack(side="left", padx=12)

        # Log
        ttk.Label(main, text="Log de actividad:").pack(anchor="w")
        self.txt_log = scrolledtext.ScrolledText(
            main, height=18, state="disabled",
            wrap=tk.WORD, font=("Consolas", 9))
        self.txt_log.pack(fill="both", expand=True, pady=(2, 0))

    def _toggle_lotes(self):
        if self.var_lotes.get():
            self.spin_timeout.config(state="normal")
            self.entry_cliente.config(state="disabled")
        else:
            self.spin_timeout.config(state="disabled")
            self.entry_cliente.config(state="normal")

    def _on_iniciar(self):
        grupo = self.entry_grupo.get().strip()
        fecha = self.entry_fecha.get().strip()
        hora  = self.entry_hora.get().strip()

        if not grupo:
            self.agregar_log("❌ Ingresá el nombre del grupo.")
            return
        if not fecha or not hora:
            self.agregar_log("❌ Ingresá fecha y hora de inicio.")
            return

        try:
            timeout = int(self.spin_timeout.get())
        except ValueError:
            timeout = 10

        self.btn_iniciar.config(state="disabled")
        self.btn_detener.config(state="normal")
        self.lbl_estado.config(text="Estado: corriendo ●", foreground="green")

        self.controlador.iniciar(
            nombre_grupo      = grupo,
            fecha_inicio_str  = fecha,
            hora_inicio_str   = hora,
            modo_lotes        = self.var_lotes.get(),
            cliente_fijo      = self.entry_cliente.get().strip(),
            timeout_lotes_min = timeout,
        )

    def _on_detener(self):
        self.controlador.detener()
        self.btn_iniciar.config(state="normal")
        self.btn_detener.config(state="disabled")
        self.lbl_estado.config(text="Estado: detenido", foreground="red")

    def _on_cerrar(self):
        try:
            self.controlador.detener()
        except Exception:
            pass
        self.root.destroy()

    def agregar_log(self, mensaje: str):
        self.root.after(0, self._insertar_log, mensaje)

    def _insertar_log(self, mensaje: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert(tk.END, mensaje + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.configure(state="disabled")