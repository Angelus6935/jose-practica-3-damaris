import tkinter as tk
from gui.ventana_principal import VentanaPrincipal

class ControladorMock:
    def iniciar(self, **kwargs): pass
    def detener(self): pass

root = tk.Tk()
app = VentanaPrincipal(root, ControladorMock())
root.mainloop()

import datetime as dt
from lotes.gestor_lotes import GestorLotes

def log(msg): print(msg)

lotes = GestorLotes(log)
lotes.configurar(
    modo_lotes=False,
    cliente_fijo="Damaris",
    timeout_min=10,
    fecha_inicio=dt.datetime.now()
)

datos_ocr = {
    "banco": "Mercado Pago", "cod_cta": "153",
    "titular_receptor": "OTERO MARIA", "titular": "XX",
    "monto": "300.000,00", "nro_operacion": "MP 123456",
    "fecha_comprobante": "15/05/2026"
}

registro = lotes.construir_registro(datos_ocr, "OK")
print("✅ Registro construido:")
for k, v in registro.items():
    print(f"  {k}: {v}")