"""
ocr/lector_ocr.py
Motor OCR multi-banco para WSP Comprobantes.
Detecta banco DESTINO por CBU/CVU de 22 digitos.
Preprocesamiento de imagenes para mejorar OCR.
"""

import os
import re
import json
import datetime as dt

import pytesseract
from PIL import Image, ImageEnhance
import pdfplumber
from pdf2image import convert_from_path


BANCOS_PATH = os.path.join("config", "bancos.json")

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12
}

CORTE_NOMBRE = [
    "CBU", "CVU", "CUIT", "CUIL", "BANCO", "MOTIVO",
    "DOMICILIO", "EMAIL", "TELEFONO", "ALIAS",
    "CUENTA", "TIPO DE"
]

PATRONES_NRO_OP = [
    (r"N[uú]mero\s+de\s+operaci[oó]n\s+de\s+Mercado\s+Pago\s+(\d+)", "MP"),
    (r"N[uú]mero\s+de\s+transacci[oó]n\s+(\d+)",                      ""),
    (r"N[uú]mero\s+de\s+referencia\s+(\d+)",                          ""),
    (r"N[°º]\s*de\s+operaci[oó]n\s+(\d+)",                            ""),
    (r"Identificador\s+de\s+operaci[oó]n\s+(\w+)",                    "CIUDAD"),
    (r"N[°º]\s+de\s+la\s+operaci[oó]n\s+(\d+)",                      "PP"),
    (r"ID\s+de\s+la\s+transacci[oó]n\s+(\w+)",                        "LEM"),
    (r"ID\s+de\s+la\s+transacci[oó]n\s*\n(\w+)",                      "LEM"),
    (r"N[°º]\s*[Oo]peraci[oó]n\s*[:\-]?\s*(\d+)",                    ""),
    (r"Referencia\s*[:\-]?\s*(\d+)",                                   ""),
    (r"N[uú]mero\s+de\s+operaci[oó]n\s*[:\-]?\s*(\d+)",              ""),
    (r"COELSA\s+ID\s*\n(\w+)",                                         ""),
    (r"N[°º]\s*de\s+operaci[oó]n\s*\n(\d+)",                         "GAL"),
]


class LectorOCR:
    def __init__(self, log_callback):
        self.log = log_callback
        pytesseract.pytesseract.tesseract_cmd = \
            r"C:\Program Files\Tesseract-OCR\tesseract.exe"

        with open(BANCOS_PATH, "r", encoding="utf-8") as f:
            self.bancos_cfg = json.load(f)["bancos"]

    # ------------------------------------------------------------------ #
    # Punto de entrada
    # ------------------------------------------------------------------ #
    def procesar_archivo(self, ruta: str) -> dict:
        ext = os.path.splitext(ruta)[1].lower()

        if ext == ".pdf":
            texto = self._texto_pdf(ruta)
        elif ext in (".jpg", ".jpeg", ".png", ".webp"):
            texto = self._texto_imagen(ruta)
        elif ext == ".heic":
            texto = self._texto_heic(ruta)
        else:
            self.log(f"Formato no soportado: {ext}")
            return self._plantilla_vacia()

        texto = texto.replace("\r\n", "\n").replace("\r", "\n")

        if not texto.strip():
            self.log("OCR no extrajo texto")
            return self._plantilla_vacia()

        return self._extraer_campos(texto)

    # ------------------------------------------------------------------ #
    # Extraccion de texto
    # ------------------------------------------------------------------ #
    def _texto_pdf(self, ruta: str) -> str:
        try:
            with pdfplumber.open(ruta) as pdf:
                texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
            if texto.strip():
                return texto
        except Exception as e:
            self.log(f"pdfplumber fallo: {e}")

        try:
            paginas = convert_from_path(ruta, dpi=200)
            return "\n".join(
                pytesseract.image_to_string(
                    self._preprocesar(img), lang="spa")
                for img in paginas
            )
        except Exception as e:
            self.log(f"OCR PDF fallo: {e}")
            return ""

    def _texto_imagen(self, ruta: str) -> str:
        try:
            img = Image.open(ruta)
            img = self._preprocesar(img)
            return pytesseract.image_to_string(img, lang="spa")
        except Exception as e:
            self.log(f"OCR imagen fallo: {e}")
            return ""

    def _texto_heic(self, ruta: str) -> str:
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            img = Image.open(ruta)
            img = self._preprocesar(img)
            return pytesseract.image_to_string(img, lang="spa")
        except Exception as e:
            self.log(f"OCR HEIC fallo: {e}")
            return ""

    def _preprocesar(self, img: Image.Image) -> Image.Image:
        """Preprocesamiento para mejorar OCR en fotos de pantalla."""
        img = img.convert('L')
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        return img

    # ------------------------------------------------------------------ #
    # Extraccion de campos
    # ------------------------------------------------------------------ #
    def _extraer_campos(self, texto: str) -> dict:
        cbu_cvu = self._buscar_cbu_cvu(texto)
        banco, cod_cta = self._detectar_banco(cbu_cvu)
        prefijo_op = self._prefijo_op(banco)

        return {
            "banco":             banco,
            "cod_cta":           str(cod_cta),
            "titular_receptor":  self._extraer_receptor(texto),
            "titular":           self._extraer_emisor(texto),
            "monto":             self._extraer_monto(texto),
            "nro_operacion":     self._extraer_nro_operacion(texto, prefijo_op),
            "fecha_comprobante": self._extraer_fecha(texto),
        }

    def _buscar_cbu_cvu(self, texto: str):
        m = re.search(r"\b(\d{22})\b", texto)
        if m:
            return m.group(1)
        m = re.search(r"\b(\d[\d\s\-]{20,23}\d)\b", texto)
        if m:
            limpio = re.sub(r"\D", "", m.group(1))
            if len(limpio) == 22:
                return limpio
        return None

    def _detectar_banco(self, cbu_cvu):
        if not cbu_cvu:
            return "XX", "XX"
        for banco in self.bancos_cfg:
            for pref in banco.get("cvu_prefijos", []):
                if cbu_cvu.startswith(pref):
                    return banco["nombre"], banco["cod_cta"]
            for pref in banco.get("cbu_prefijos", []):
                if cbu_cvu.startswith(pref):
                    return banco["nombre"], banco["cod_cta"]
        return "XX", "XX"

    def _prefijo_op(self, banco: str) -> str:
        for b in self.bancos_cfg:
            if b["nombre"] == banco:
                return b.get("prefijo_op", "")
        return ""

    def _extraer_receptor(self, texto: str) -> str:
        patrones = [
            r"Para[:\n]\s*(.+)",
            r"Recibe[:\n]\s*(.+)",
            r"Beneficiario[:\n]\s*(.+)",
            r"Destinatario[:\n]\s*(.+)",
            r"Env[ií]o\s+de\s+dinero\s+a[:\n]\s*(.+)",
            r"Persona\s+destinataria\s*\n.*?Nombre\s+(.+)",
            r"Nombre\s+(.+)",
        ]
        return self._primer_patron(texto, patrones)

    def _extraer_emisor(self, texto: str) -> str:
        patrones = [
            r"De[:\n]\s*(.+)",
            r"Env[ií]a[:\n]\s*(.+)",
            r"Enviado\s+por[:\n]\s*(.+)",
            r"Titular[:\n]\s*(.+)",
            r"Ordenante[:\n]\s*(.+)",
            r"Enviado\s+por\s+(.+)",
        ]
        return self._primer_patron(texto, patrones)

    def _primer_patron(self, texto: str, patrones: list) -> str:
        for pat in patrones:
            m = re.search(pat, texto, re.IGNORECASE)
            if m:
                limpio = self._limpiar_nombre(m.group(1).strip())
                if limpio and limpio != "XX":
                    return limpio
        return "XX"

    def _limpiar_nombre(self, nombre: str) -> str:
        lineas = nombre.splitlines()
        resultado = []
        for linea in lineas:
            if any(tok in linea.upper() for tok in CORTE_NOMBRE):
                break
            limpia = linea.strip()
            if limpia:
                resultado.append(limpia)
        return " ".join(resultado).strip() or "XX"

    def _extraer_monto(self, texto: str) -> str:
        patrones = [
            r"ARS\s*([\d\.]+,\d{2})",
            r"\$\s*([\d\.]+,\d{2})",
            r"\$\s*([\d\.]+)",
            r"\b([\d]{1,3}(?:\.\d{3})+,\d{2})\b",
            r"\b(\d+,\d{2})\b",
        ]
        for pat in patrones:
            m = re.search(pat, texto)
            if m:
                valor = m.group(1).replace(".", "").replace(",", ",")
                # Normalizar a formato argentino
                if "," not in valor:
                    valor = valor + ",00"
                # Formatear con puntos de miles
                partes = valor.split(",")
                entero = partes[0]
                decimal = partes[1] if len(partes) > 1 else "00"
                # Agregar puntos de miles
                if len(entero) > 3:
                    entero_fmt = ""
                    for i, c in enumerate(reversed(entero)):
                        if i > 0 and i % 3 == 0:
                            entero_fmt = "." + entero_fmt
                        entero_fmt = c + entero_fmt
                    return f"{entero_fmt},{decimal}"
                return f"{entero},{decimal}"
        return "XX"

    def _extraer_nro_operacion(self, texto: str, prefijo_op: str) -> str:
        for patron, prefijo_fijo in PATRONES_NRO_OP:
            m = re.search(patron, texto, re.IGNORECASE)
            if m:
                num = m.group(1).strip()
                pref = prefijo_op or prefijo_fijo
                return f"{pref} {num}".strip() if pref else num
        return "XX"

    def _extraer_fecha(self, texto: str) -> str:
        resultados = []

        for m in re.finditer(r"\b(\d{2}/\d{2}/\d{4})\b", texto):
            resultados.append(m.group(1))

        for m in re.finditer(r"\b(\d{2})-(\d{2})-(\d{4})\b", texto):
            resultados.append(f"{m.group(1)}/{m.group(2)}/{m.group(3)}")

        for m in re.finditer(r"\b(\d{4})/(\d{2})/(\d{2})\b", texto):
            resultados.append(f"{m.group(3)}/{m.group(2)}/{m.group(1)}")

        # 19/05/2026 . 08:55 h (Galicia)
        for m in re.finditer(r"\b(\d{2}/\d{2}/\d{4})\s*[·•]\s*\d{2}:\d{2}", texto):
            resultados.append(m.group(1))

        patron_texto = (
            r"\b(\d{1,2})\s+(?:de\s+)?("
            + "|".join(MESES_ES.keys())
            + r")(?:\s+de)?\s+(\d{4})\b"
        )
        for m in re.finditer(patron_texto, texto, re.IGNORECASE):
            dia  = int(m.group(1))
            mes  = MESES_ES[m.group(2).lower()]
            anio = int(m.group(3))
            resultados.append(f"{dia:02d}/{mes:02d}/{anio}")

        return resultados[0] if resultados else "XX"

    def parsear_fecha(self, fecha_str: str) -> dt.datetime:
        for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
            try:
                return dt.datetime.strptime(fecha_str, fmt)
            except ValueError:
                continue
        raise ValueError(f"No se pudo parsear: {fecha_str}")

    def _plantilla_vacia(self) -> dict:
        return {
            "banco": "XX", "cod_cta": "XX",
            "titular_receptor": "XX", "titular": "XX",
            "monto": "XX", "nro_operacion": "XX",
            "fecha_comprobante": "XX"
        }
