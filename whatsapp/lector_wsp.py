"""
whatsapp/lector_wsp.py
Flujo:
  Pasada 1 - Imagenes: calendario -> carrusel adelante
  Pasada 2 - PDFs: calendario -> uno por uno
  Pasada 3 - Imagenes desde final (solo si pasada 1 = 0):
             abre ultima imagen -> va al ultimo del carrusel -> recorre hacia atras
"""

import os
import re
import time
import datetime as dt

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    NoSuchElementException,
)
from webdriver_manager.chrome import ChromeDriverManager


SEL_SEARCH_BOX     = 'input[aria-label="Buscar un chat o iniciar uno nuevo"]'
SEL_CONV_MESSAGES  = 'div[data-testid="conversation-panel-messages"]'
SEL_MSG            = '[data-testid^="conv-msg-"]'
SEL_DOC_THUMB      = '[data-testid="document-thumb"]'
SEL_IMG_THUMB      = '[data-testid="image-thumb"]'
SEL_BTN_DESCARGAR  = '[aria-label="Descargar"]'
SEL_BTN_CERRAR     = '[aria-label="Cerrar"]'
SEL_BTN_SIGUIENTE  = '[aria-label="Siguiente"]'
SEL_BTN_ANTERIOR   = '[aria-label="Anterior"]'
SEL_FECHA_VISOR    = '[data-testid="cell-frame-secondary"]'
SEL_TEXTO_MSG      = "span.selectable-text"
SEL_BTN_BUSCAR     = '[aria-label="Buscar"]'
SEL_BTN_CALENDARIO = '[aria-label="Ir a la fecha"]'
SEL_BTN_MES_ANT    = '[aria-label="Mes anterior"]'
SEL_BTN_MES_SIG    = '[aria-label="Mes siguiente"]'

EXT_VALIDAS = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic")

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}


class LectorWhatsApp:
    def __init__(self, nombre_grupo: str, carpeta_descargas: str,
                 intervalo_lectura: int, espera_descarga: int,
                 log_callback):
        self.nombre_grupo      = nombre_grupo
        self.carpeta_descargas = os.path.abspath(carpeta_descargas)
        self.intervalo_lectura = intervalo_lectura
        self.espera_descarga   = espera_descarga
        self.log               = log_callback

        self.driver: webdriver.Chrome | None = None
        self._wait:  WebDriverWait | None    = None
        self._activo = True
        self._mensajes_procesados: set[str] = set()

        os.makedirs(self.carpeta_descargas, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Sesion
    # ------------------------------------------------------------------ #
    def iniciar_sesion(self, fecha_inicio: dt.date | None = None):
        perfil_path = os.path.abspath(
            os.path.expanduser("~/wsp_comprobantes_perfil")
        )
        opts = Options()
        opts.add_argument(f"--user-data-dir={perfil_path}")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--no-sandbox")
        opts.add_experimental_option("prefs", {
            "download.default_directory":   self.carpeta_descargas,
            "download.prompt_for_download": False,
            "download.directory_upgrade":   True,
            "profile.default_content_setting_values.automatic_downloads": 1,
        })

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=opts)
        self._wait  = WebDriverWait(self.driver, 60)

        self.driver.get("https://web.whatsapp.com")
        self.log("Esperando WhatsApp Web...")

        try:
            self._wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SEL_SEARCH_BOX))
            )
        except TimeoutException:
            self.log("WhatsApp Web tardo mas de 60s en cargar")

        self.log("WhatsApp Web listo")
        self._abrir_grupo()

    # ------------------------------------------------------------------ #
    # Abrir grupo
    # ------------------------------------------------------------------ #
    def _abrir_grupo(self):
        search_box = self._wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SEL_SEARCH_BOX))
        )
        search_box.clear()
        search_box.send_keys(self.nombre_grupo)
        time.sleep(2)

        try:
            resultado = self._wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, f'//span[@title="{self.nombre_grupo}"]')
                )
            )
            resultado.click()
        except TimeoutException:
            raise RuntimeError(f"No se encontro el grupo '{self.nombre_grupo}'")

        time.sleep(2)
        self.log(f"Grupo abierto: {self.nombre_grupo}")

    # ------------------------------------------------------------------ #
    # Pasada 1 - Imagenes metodo 1 (calendario -> adelante)
    # ------------------------------------------------------------------ #
    def procesar_imagenes(self, fecha_inicio: dt.date) -> list[str]:
        self.log("Iniciando pasada de imagenes (metodo 1 - calendario)...")

        self._ir_a_fecha(fecha_inicio)
        time.sleep(2)
        primera_img = self._encontrar_primer_thumb(SEL_IMG_THUMB)

        if not primera_img:
            self.log("Metodo 1: no encontro imagenes en fecha indicada")
            return []

        try:
            primera_img.click()
            time.sleep(2)
        except Exception as e:
            self.log(f"No se pudo abrir el carrusel: {e}")
            return []

        archivos = []

        for _ in range(500):
            if not self._activo:
                break

            fecha_visor = self._leer_fecha_visor()
            if fecha_visor is not None and fecha_visor < fecha_inicio:
                self.log(f"Imagen del {fecha_visor} anterior — deteniendo")
                break

            archivo = self._click_descargar()
            if archivo:
                archivos.append(archivo)
                self.log(f"Imagen: {os.path.basename(archivo)}")

            if not self._click_siguiente():
                self.log("Llegue al final del carrusel")
                break

            time.sleep(0.8)

        self._cerrar_visor()
        self.log(f"Imagenes metodo 1: {len(archivos)}")
        return archivos

    # ------------------------------------------------------------------ #
    # Pasada 3 - Imagenes metodo 2 (final -> ultimo -> izquierda)
    # ------------------------------------------------------------------ #
    def procesar_imagenes_desde_final(self, fecha_inicio: dt.date) -> list[str]:
        self.log("Iniciando pasada de imagenes (metodo 2 - desde el final)...")

        self._scroll_al_final()
        time.sleep(2)
        ultima_img = self._encontrar_ultima_imagen()

        if not ultima_img:
            self.log("No se encontraron imagenes en el chat")
            return []

        try:
            ultima_img.click()
            time.sleep(2)
        except Exception as e:
            self.log(f"No se pudo abrir el carrusel: {e}")
            return []

        # Ir al ultimo del carrusel
        self.log("Navegando al ultimo del carrusel...")
        self._ir_al_ultimo_carrusel()
        time.sleep(1)

        archivos = []

        for _ in range(500):
            if not self._activo:
                break

            fecha_visor = self._leer_fecha_visor()
            if fecha_visor is not None and fecha_visor < fecha_inicio:
                self.log(f"Imagen del {fecha_visor} anterior — deteniendo")
                break

            archivo = self._click_descargar()
            if archivo:
                archivos.append(archivo)
                self.log(f"Imagen: {os.path.basename(archivo)}")

            if not self._click_anterior():
                self.log("Llegue al inicio del carrusel")
                break

            time.sleep(0.8)

        self._cerrar_visor()
        self.log(f"Imagenes metodo 2: {len(archivos)}")
        return archivos

    def _ir_al_ultimo_carrusel(self):
        """Hace clic en Siguiente hasta que el boton este deshabilitado."""
        for _ in range(500):
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, SEL_BTN_SIGUIENTE)
                if btn.get_attribute("disabled"):
                    break
                btn.click()
                time.sleep(0.3)
            except NoSuchElementException:
                break
            except Exception:
                break

    # ------------------------------------------------------------------ #
    # Pasada 2 - PDFs
    # ------------------------------------------------------------------ #
    def procesar_pdfs(self, fecha_inicio: dt.date) -> list[str]:
        self.log("Iniciando pasada de PDFs...")
        self._ir_a_fecha(fecha_inicio)
        time.sleep(2)

        archivos = []
        procesados_pdf = set()

        for _ in range(100):
            if not self._activo:
                break

            msgs = self.driver.find_elements(By.CSS_SELECTOR, SEL_MSG)
            nuevos = False

            for msg in msgs:
                try:
                    data_id = msg.get_attribute("data-id")
                    if not data_id or data_id in procesados_pdf:
                        continue
                    if not self._tiene_selector(msg, SEL_DOC_THUMB):
                        continue

                    procesados_pdf.add(data_id)
                    nuevos = True

                    try:
                        thumb = msg.find_element(By.CSS_SELECTOR, SEL_DOC_THUMB)
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView(true);", thumb)
                        time.sleep(0.5)
                        thumb.click()
                        time.sleep(2)
                    except StaleElementReferenceException:
                        continue

                    fecha_visor = self._leer_fecha_visor()
                    if fecha_visor is not None and fecha_visor < fecha_inicio:
                        self.log(f"PDF del {fecha_visor} anterior — ignorado")
                        self._cerrar_visor()
                        continue

                    archivo = self._click_descargar()
                    self._cerrar_visor()

                    if archivo:
                        archivos.append(archivo)
                        self.log(f"PDF: {os.path.basename(archivo)}")

                except StaleElementReferenceException:
                    continue
                except Exception:
                    continue

            self._scroll_al_final()
            time.sleep(self.intervalo_lectura)

            if not nuevos:
                break

        self.log(f"PDFs descargados: {len(archivos)}")
        return archivos

    # ------------------------------------------------------------------ #
    # Lectura de mensajes de texto
    # ------------------------------------------------------------------ #
    def leer_mensajes_recientes(self) -> list[dict]:
        self._scroll_al_final()
        time.sleep(self.intervalo_lectura)

        resultado = []
        try:
            msgs = self.driver.find_elements(By.CSS_SELECTOR, SEL_MSG)
        except Exception:
            return []

        for msg in msgs:
            try:
                data_id = msg.get_attribute("data-id")
                if not data_id or data_id in self._mensajes_procesados:
                    continue

                tiene_pdf = self._tiene_selector(msg, SEL_DOC_THUMB)
                tiene_img = self._tiene_selector(msg, SEL_IMG_THUMB)

                if tiene_pdf or tiene_img:
                    resultado.append({
                        "tipo":    "adjunto",
                        "data_id": data_id,
                        "es_pdf":  tiene_pdf,
                    })
                    self._mensajes_procesados.add(data_id)
                    continue

                try:
                    spans = msg.find_elements(By.CSS_SELECTOR, SEL_TEXTO_MSG)
                    texto = " ".join(s.text for s in spans if s.text).strip()
                    if texto:
                        resultado.append({
                            "tipo":    "texto",
                            "data_id": data_id,
                            "texto":   texto,
                        })
                        self._mensajes_procesados.add(data_id)
                except StaleElementReferenceException:
                    pass

            except StaleElementReferenceException:
                continue
            except Exception:
                continue

        return resultado

    # ------------------------------------------------------------------ #
    # Calendario
    # ------------------------------------------------------------------ #
    def _ir_a_fecha(self, fecha: dt.date):
        try:
            btn_buscar = self.driver.find_element(
                By.CSS_SELECTOR, SEL_BTN_BUSCAR)
            btn_buscar.click()
            time.sleep(1)

            btn_cal = self.driver.find_element(
                By.CSS_SELECTOR, SEL_BTN_CALENDARIO)
            btn_cal.click()
            time.sleep(1)

            self._navegar_mes_calendario(fecha)
            self._click_dia_calendario(fecha.day)
            time.sleep(2)
            self.log(f"Saltando a: {fecha}")
        except Exception as e:
            self.log(f"No se pudo navegar al calendario: {e}")

    def _navegar_mes_calendario(self, fecha: dt.date):
        for _ in range(24):
            try:
                header = self.driver.find_element(
                    By.XPATH,
                    '//span[contains(text(),"202") and ('
                    'contains(text(),"enero") or contains(text(),"febrero") or '
                    'contains(text(),"marzo") or contains(text(),"abril") or '
                    'contains(text(),"mayo") or contains(text(),"junio") or '
                    'contains(text(),"julio") or contains(text(),"agosto") or '
                    'contains(text(),"septiembre") or contains(text(),"octubre") or '
                    'contains(text(),"noviembre") or contains(text(),"diciembre"))]'
                )
                texto = header.text.strip()
                fecha_cal = self._parsear_mes_calendario(texto)
                if fecha_cal is None:
                    break
                if fecha_cal.year == fecha.year and fecha_cal.month == fecha.month:
                    break
                if (fecha_cal.year, fecha_cal.month) > (fecha.year, fecha.month):
                    self.driver.find_element(By.CSS_SELECTOR, SEL_BTN_MES_ANT).click()
                else:
                    self.driver.find_element(By.CSS_SELECTOR, SEL_BTN_MES_SIG).click()
                time.sleep(0.5)
            except Exception:
                break

    def _parsear_mes_calendario(self, texto: str) -> dt.date | None:
        for mes_str, mes_num in MESES_ES.items():
            if mes_str in texto.lower():
                m = re.search(r'(\d{4})', texto)
                if m:
                    return dt.date(int(m.group(1)), mes_num, 1)
        return None

    def _click_dia_calendario(self, dia: int):
        divs = self.driver.find_elements(By.XPATH, '//div[@aria-hidden="true"]')
        for div in divs:
            try:
                spans = div.find_elements(By.TAG_NAME, 'span')
                for span in spans:
                    if span.text.strip() == str(dia):
                        self.driver.execute_script(
                            "arguments[0].click();",
                            div.find_element(By.XPATH, '..'))
                        return
            except Exception:
                continue

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _encontrar_primer_thumb(self, selector: str):
        try:
            msgs = self.driver.find_elements(By.CSS_SELECTOR, SEL_MSG)
            for msg in msgs:
                try:
                    return msg.find_element(By.CSS_SELECTOR, selector)
                except NoSuchElementException:
                    continue
        except Exception:
            pass
        return None

    def _encontrar_ultima_imagen(self):
        try:
            msgs = self.driver.find_elements(By.CSS_SELECTOR, SEL_MSG)
            for msg in reversed(msgs):
                try:
                    return msg.find_element(By.CSS_SELECTOR, SEL_IMG_THUMB)
                except NoSuchElementException:
                    continue
        except Exception:
            pass
        return None

    def _scroll_al_final(self):
        try:
            panel = self.driver.find_element(By.CSS_SELECTOR, SEL_CONV_MESSAGES)
            self.driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight;", panel)
            time.sleep(1)
        except Exception:
            pass

    def _tiene_selector(self, elemento, selector: str) -> bool:
        try:
            elemento.find_element(By.CSS_SELECTOR, selector)
            return True
        except (NoSuchElementException, StaleElementReferenceException):
            return False

    def _leer_fecha_visor(self) -> dt.date | None:
        try:
            elem = self.driver.find_element(By.CSS_SELECTOR, SEL_FECHA_VISOR)
            texto = elem.text.strip()
            m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', texto)
            if m:
                return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except Exception:
            pass
        return None

    def _click_descargar(self) -> str | None:
        archivos_previos = self._snapshot_descargas()
        try:
            btn_dl = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, SEL_BTN_DESCARGAR))
            )
            btn_dl.click()
        except TimeoutException:
            self.log("Boton Descargar no aparecio")
            return None
        return self._esperar_archivo_nuevo(archivos_previos)

    def _snapshot_descargas(self) -> set:
        try:
            return {
                os.path.join(self.carpeta_descargas, f)
                for f in os.listdir(self.carpeta_descargas)
                if f.lower().endswith(EXT_VALIDAS)
                and not f.endswith(".crdownload")
            }
        except Exception:
            return set()

    def _esperar_archivo_nuevo(self, archivos_previos: set) -> str | None:
        inicio = time.time()
        while time.time() - inicio < self.espera_descarga:
            actuales = self._snapshot_descargas()
            nuevos   = actuales - archivos_previos
            if nuevos:
                candidato = max(nuevos, key=os.path.getmtime)
                tam1 = os.path.getsize(candidato)
                time.sleep(1)
                tam2 = os.path.getsize(candidato)
                if tam1 == tam2 and tam1 > 0:
                    self.log(f"Descargado: {os.path.basename(candidato)}")
                    return candidato
            time.sleep(1)
        self.log("Timeout esperando descarga")
        return None

    def _cerrar_visor(self):
        try:
            self.driver.find_element(By.CSS_SELECTOR, SEL_BTN_CERRAR).click()
        except Exception:
            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
        time.sleep(0.5)

    def _click_siguiente(self) -> bool:
        try:
            self.driver.find_element(By.CSS_SELECTOR, SEL_BTN_SIGUIENTE).click()
            return True
        except (NoSuchElementException, Exception):
            return False

    def _click_anterior(self) -> bool:
        try:
            self.driver.find_element(By.CSS_SELECTOR, SEL_BTN_ANTERIOR).click()
            return True
        except (NoSuchElementException, Exception):
            return False

    def detener(self):
        self._activo = False
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
        except Exception:
            pass
