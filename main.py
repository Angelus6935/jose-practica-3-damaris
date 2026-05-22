import tkinter as tk
from gui.ventana_principal import VentanaPrincipal

class ControladorMock:
    def iniciar(self, **kwargs): pass
    def detener(self): pass

root = tk.Tk()
app = VentanaPrincipal(root, ControladorMock())
root.mainloop()

