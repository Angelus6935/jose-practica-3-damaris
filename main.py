import tkinter as tk
from gui.ventana_principal import VentanaPrincipal

class ControladorMock:
    def iniciar(self, **kwargs): pass
    def detener(self): pass

root = tk.Tk()
app = VentanaPrincipal(root, ControladorMock())
root.mainloop()

import json
from excel.gestor_excel import GestorExcel

def log(msg): print(msg)

with open("config/config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

gestor = GestorExcel(config, log)
gestor.cargar_operaciones_existentes()
