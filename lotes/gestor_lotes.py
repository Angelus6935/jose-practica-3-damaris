"""
lotes/gestor_lotes.py
Gestiona modo lotes (cliente variable) y cliente fijo.

Modo lotes:
  - Comprobantes se acumulan en lote_pendiente
  - Cuando llega mensaje de texto → ese texto es el nombre del cliente
  - Se asigna el cliente a todo el lote
  - Si pasan X minutos sin nombre → "Cliente no identificado"

Cliente fijo:
  - Todos los comprobantes usan el mismo cliente
"""

import datetime as dt
from threading import Timer


class GestorLotes:
    def __init__(self, log_callback):
        self.log = log_callback
        self.modo_lotes: bool = False
        self.cliente_fijo: str = ""
        self.timeout_min: int = 10
        self.fecha_inicio: dt.datetime | None = None

        self.lote_pendiente: list = []
        self._timer: Timer | None = None
        self._flush_cb = None

    # ------------------------------------------------------------------ #
    # Configuración
    # ------------------------------------------------------------------ #
    def configurar(self, modo_lotes: bool, cliente_fijo: str,
                   timeout_min: int, fecha_inicio: dt.datetime):
        self._cancelar_timer()
        self.modo_lotes = modo_lotes
        self.cliente_fijo = cliente_fijo.strip()
        self.timeout_min = timeout_min
        self.fecha_inicio = fecha_inicio
        self.lote_pendiente = []

    def set_flush_callback(self, callback):
        """Función a llamar cuando el timer cierra un lote."""
        self._flush_cb = callback

    # ------------------------------------------------------------------ #
    # Construir registro
    # ------------------------------------------------------------------ #
    def construir_registro(self, datos_ocr: dict, estado: str) -> dict:
        fecha_str = datos_ocr.get("fecha_comprobante", "XX")
        if fecha_str == "XX":
            fecha_str = dt.datetime.now().strftime("%d/%m/%Y")

        registro = {
            "fecha":            fecha_str,
            "banco":            datos_ocr.get("banco", "XX"),
            "titular_receptor": datos_ocr.get("titular_receptor", "XX"),
            "cod_cta":          datos_ocr.get("cod_cta", "XX"),
            "cliente":          "",
            "monto":            datos_ocr.get("monto", "XX"),
            "titular":          datos_ocr.get("titular", "XX"),
            "nro_operacion":    datos_ocr.get("nro_operacion", "XX"),
            "estado":           estado,
        }

        if self.modo_lotes:
            self.lote_pendiente.append(registro)
            self._reiniciar_timer()
        else:
            registro["cliente"] = self.cliente_fijo

        return registro

    # ------------------------------------------------------------------ #
    # Recibir nombre de cliente (desde mensaje de texto)
    # ------------------------------------------------------------------ #
    def registrar_nombre_cliente(self, nombre: str) -> list:
        if not self.modo_lotes:
            return []
        nombre = nombre.strip()
        if not nombre:
            return []
        self._cancelar_timer()
        return self._cerrar_lote(nombre)

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #
    def _cerrar_lote(self, nombre_cliente: str) -> list:
        if not self.lote_pendiente:
            self.log(f"ℹ Nombre recibido pero lote vacío: '{nombre_cliente}'")
            return []

        for reg in self.lote_pendiente:
            reg["cliente"] = nombre_cliente

        cerrados = list(self.lote_pendiente)
        self.log(f"📦 Lote cerrado → '{nombre_cliente}' ({len(cerrados)} comprobante/s)")
        self.lote_pendiente = []
        return cerrados

    def _reiniciar_timer(self):
        self._cancelar_timer()
        self._timer = Timer(self.timeout_min * 60, self._timeout_callback)
        self._timer.daemon = True
        self._timer.start()

    def _cancelar_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _timeout_callback(self):
        self.log("⏰ Timeout → registrando como 'Cliente no identificado'")
        cerrados = self._cerrar_lote("Cliente no identificado")
        if cerrados and self._flush_cb:
            self._flush_cb(cerrados)
            