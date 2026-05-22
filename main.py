"""
main.py
WSP Comprobantes — controlador principal.
Orquesta: GUI ↔ LectorWhatsApp ↔ LectorOCR ↔ GestorExcel ↔ GestorLotes
"""

import os
import json
import threading
import datetime as dt
import tkinter as tk

from gui.ventana_principal import VentanaPrincipal
from whatsapp.lector_wsp import LectorWhatsApp
from ocr.lector_ocr import LectorOCR
from excel.gestor_excel import GestorExcel
from lotes.gestor_lotes import GestorLotes

CONFIG_PATH = os.path.join("config", "config.json")


class Controlador:
    def __init__(self, ui_log_callback):
        self.log = ui_log_callback
        self._correr = False
        self._hilo: threading.Thread | None = None

        self.config = self._cargar_config()
        self.ocr    = LectorOCR(self.log)
        self.excel  = GestorExcel(self.config, self.log)
        self.lotes  = GestorLotes(self.log)
        self.wsp:   LectorWhatsApp | None = None

    def _cargar_config(self) -> dict:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------ #
    # API pública para la GUI
    # ------------------------------------------------------------------ #
    def iniciar(self, nombre_grupo: str, fecha_inicio_str: str,
                hora_inicio_str: str, modo_lotes: bool,
                cliente_fijo: str, timeout_lotes_min: int):

        if self._correr:
            self.log("⚠ Ya hay una sesión activa.")
            return

        try:
            fecha_inicio = dt.datetime.strptime(
                f"{fecha_inicio_str} {hora_inicio_str}", "%d/%m/%Y %H:%M"
            )
        except ValueError:
            self.log("❌ Fecha u hora inválida. Formato: dd/mm/yyyy y hh:mm")
            return

        self._correr = True
        self.excel.cargar_operaciones_existentes()

        self.lotes.configurar(
            modo_lotes   = modo_lotes,
            cliente_fijo = cliente_fijo,
            timeout_min  = timeout_lotes_min,
            fecha_inicio = fecha_inicio,
        )

        def flush_lote(registros):
            for reg in registros:
                self._registrar_en_excel(reg)

        self.lotes.set_flush_callback(flush_lote)

        self.wsp = LectorWhatsApp(
            nombre_grupo      = nombre_grupo,
            carpeta_descargas = self.config["carpeta_descargas"],
            intervalo_lectura = self.config["intervalo_lectura_segundos"],
            espera_descarga   = self.config["espera_descarga_segundos"],
            log_callback      = self.log,
        )

        self._hilo = threading.Thread(
            target=self._loop_principal,
            args=(fecha_inicio,),
            daemon=True,
        )
        self._hilo.start()
        self.log("▶ Sesión iniciada.")

    def detener(self):
        self._correr = False
        if self.wsp:
            self.wsp.detener()
        self.log("⏹ Sesión detenida.")

    # ------------------------------------------------------------------ #
    # Loop principal
    # ------------------------------------------------------------------ #
    def _loop_principal(self, fecha_inicio: dt.datetime):
        try:
            self.wsp.iniciar_sesion()

            while self._correr:
                mensajes = self.wsp.leer_mensajes_recientes()

                for msg in mensajes:
                    if not self._correr:
                        break

                    if msg["tipo"] == "adjunto":
                        self._procesar_adjunto(msg, fecha_inicio)

                    elif msg["tipo"] == "texto":
                        registros = self.lotes.registrar_nombre_cliente(
                            msg["texto"]
                        )
                        for reg in registros:
                            self._registrar_en_excel(reg)

        except Exception as e:
            self.log(f"❌ Error en loop: {e}")
        finally:
            self._correr = False
            self.log("ℹ Loop finalizado.")

    # ------------------------------------------------------------------ #
    # Procesar adjunto
    # ------------------------------------------------------------------ #
    def _procesar_adjunto(self, msg: dict, fecha_inicio: dt.datetime):
        archivos = self.wsp.descargar_adjunto(msg, fecha_inicio.date())
        if not archivos:
            return

        for archivo in archivos:
            datos  = self.ocr.procesar_archivo(archivo)
            estado = "OK"

            nro_op = datos.get("nro_operacion", "XX")
            if self.excel.es_duplicado(nro_op):
                self.log(f"⏭ Duplicado ignorado: {nro_op}")
                continue

            registro = self.lotes.construir_registro(datos_ocr=datos, estado=estado)

            if self.lotes.modo_lotes:
                self.log(
                    f"📥 Acumulado en lote: {nro_op} | {datos['banco']} | ${datos['monto']}"
                )
                continue

            self._registrar_en_excel(registro)

    # ------------------------------------------------------------------ #
    def _registrar_en_excel(self, registro: dict):
        self.excel.registrar(registro)
        self.log(
            f"✅ Registrado → {registro['nro_operacion']} | "
            f"{registro['banco']} | ${registro['monto']} | "
            f"Cliente: {registro['cliente']} | {registro['estado']}"
        )


# ═══════════════════════════════════════════════════════════════════════════ #
if __name__ == "__main__":
    root = tk.Tk()
    app_ref = []

    def log_callback(msg: str):
        if app_ref:
            app_ref[0].agregar_log(msg)

    controlador = Controlador(ui_log_callback=log_callback)
    app = VentanaPrincipal(root, controlador)
    app_ref.append(app)

    root.mainloop()