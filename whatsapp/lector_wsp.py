"""
whatsapp/lector_wsp.py
Controla Chrome via Selenium para leer mensajes de WhatsApp Web.
Anti-StaleElement: siempre re-localiza por data-id antes de interactuar.
Descarga: snapshot previo para detectar archivos nuevos.
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


# ── Selectores centralizados ──────────────────────────────────────────────
SEL_SEARCH_BOX    = 'input[aria-label="Buscar un chat o iniciar uno nuevo"]'
SEL_CONV_MESSAGES = 'div[data-testid="conversation-panel-messages"]'
SEL_MSG           = '[data-testid^="conv-msg-"]'
SEL_DOC_THUMB     = '[data-testid="document-thumb"]'
SEL_IMG_THUMB     = '[data-testid="image-thumb"]'
SEL_BTN_DESCARGAR = '[aria-label="Descargar"]'
SEL_BTN_CERRAR    = '[aria-label="Cerrar"]'
SEL_TEXTO_MSG     = "span.selectable-text"

EXT_VALIDAS    = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic")
MAX_REINTENTOS = 3


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
    # Sesión
    # ------------------------------------------------------------------ #
    def iniciar_sesion(self):
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
        self.log("📱 Esperando WhatsApp Web... (escaneá QR si es primera vez)")

        try:
            self._wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SEL_SEARCH_BOX))
            )
        except TimeoutException:
            self.log("⚠ WhatsApp Web tardó más de 60s en cargar")

        self.log("✅ WhatsApp Web listo")
        self._abrir_grupo()

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
            raise RuntimeError(
                f"No se encontró el grupo '{self.nombre_grupo}'"
            )

        time.sleep(2)
        self._scroll_al_final()
        self.log(f"📂 Grupo abierto: {self.nombre_grupo}")

    def _scroll_al_final(self):
        try:
            panel = self.driver.find_element(
                By.CSS_SELECTOR, SEL_CONV_MESSAGES)
            self.driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight;", panel)
            time.sleep(1)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Lectura de mensajes
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
                    fecha_msg = self._leer_fecha_mensaje(msg)
                    resultado.append({
                        "tipo":      "adjunto",
                        "data_id":   data_id,
                        "es_pdf":    tiene_pdf,
                        "fecha_msg": fecha_msg,
                    })
                    self._mensajes_procesados.add(data_id)
                    continue

                # Texto
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

    def _tiene_selector(self, elemento, selector: str) -> bool:
        try:
            elemento.find_element(By.CSS_SELECTOR, selector)
            return True
        except (NoSuchElementException, StaleElementReferenceException):
            return False

    def _leer_fecha_mensaje(self, msg_elem) -> dt.date:
        try:
            divs = msg_elem.find_elements(
                By.XPATH, './/div[contains(text(), "/202")]')
            for div in divs:
                texto = div.text.strip()
                m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', texto)
                if m:
                    dia  = int(m.group(1))
                    mes  = int(m.group(2))
                    anio = int(m.group(3))
                    return dt.date(anio, mes, dia)
        except Exception:
            pass
        return dt.date.today()

    # ------------------------------------------------------------------ #
    # Descarga de adjunto
    # ------------------------------------------------------------------ #
    def descargar_adjunto(self, msg: dict) -> str | None:
        data_id = msg["data_id"]
        self.log(f"⬇ Descargando adjunto {data_id[:10]}...")

        for intento in range(1, MAX_REINTENTOS + 1):
            resultado = self._intentar_descarga(msg, data_id, intento)
            if resultado:
                return resultado
            self._scroll_al_final()
            time.sleep(1.5)

        self.log(f"❌ Falló descarga tras {MAX_REINTENTOS} intentos")
        return None

    def _intentar_descarga(self, msg: dict, data_id: str, intento: int):
        archivos_previos = self._snapshot_descargas()

        try:
            msg_elem = self.driver.find_element(
                By.CSS_SELECTOR, f'[data-id="{data_id}"]')
        except NoSuchElementException:
            self.log(f"⚠ [{intento}] Mensaje no encontrado en DOM")
            return None

        try:
            thumb_sel = SEL_DOC_THUMB if msg.get("es_pdf") else SEL_IMG_THUMB
            thumb = msg_elem.find_element(By.CSS_SELECTOR, thumb_sel)
            self.driver.execute_script(
                "arguments[0].scrollIntoView(true);", thumb)
            time.sleep(0.5)
            thumb.click()
        except StaleElementReferenceException:
            self.log(f"⚠ [{intento}] StaleElement en thumb — reintentando...")
            return None
        except Exception as e:
            self.log(f"⚠ [{intento}] No se pudo abrir adjunto: {e}")
            return None

        time.sleep(2)

        try:
            btn_dl = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, SEL_BTN_DESCARGAR))
            )
            btn_dl.click()
        except TimeoutException:
            self.log(f"⚠ [{intento}] Botón Descargar no apareció")
            self._cerrar_visor()
            return None

        archivo = self._esperar_archivo_nuevo(archivos_previos)
        self._cerrar_visor()
        return archivo

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

    def _esperar_archivo_nuevo(self, archivos_previos: set):
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
                    self.log(f"💾 Descargado: {os.path.basename(candidato)}")
                    return candidato
            time.sleep(1)
        self.log("⚠ Timeout esperando descarga")
        return None

    def _cerrar_visor(self):
        try:
            self.driver.find_element(
                By.CSS_SELECTOR, SEL_BTN_CERRAR).click()
        except Exception:
            try:
                self.driver.find_element(
                    By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
        time.sleep(0.5)

    # ------------------------------------------------------------------ #
    # Detener
    # ------------------------------------------------------------------ #
    def detener(self):
        self._activo = False
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
        except Exception:
            pass