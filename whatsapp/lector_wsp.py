"""
whatsapp/lector_wsp.py
Controla Chrome via Selenium para leer mensajes de WhatsApp Web.
Anti-StaleElement: siempre re-localiza por data-id antes de interactuar.
Descarga: snapshot previo para detectar archivos nuevos.
Filtro: lee fecha del visor antes de descargar.
Carrusel: navega desde el último hacia la izquierda.
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
SEL_BTN_SIGUIENTE = '[aria-label="Siguiente"]'
SEL_BTN_ANTERIOR  = '[aria-label="Anterior"]'
SEL_FECHA_VISOR   = '[data-testid="cell-frame-secondary"]'
SEL_TEXTO_MSG     = "span.selectable-text"

EXT_VALIDAS    = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic")
MAX_REINTENTOS = 3
IGNORADO       = "IGNORADO"


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
                    resultado.append({
                        "tipo":    "adjunto",
                        "data_id": data_id,
                        "es_pdf":  tiene_pdf,
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

    # ------------------------------------------------------------------ #
    # Fecha del visor
    # ------------------------------------------------------------------ #
    def _leer_fecha_visor(self) -> dt.date | None:
        try:
            elem = self.driver.find_element(
                By.CSS_SELECTOR, SEL_FECHA_VISOR)
            texto = elem.text.strip()
            m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', texto)
            if m:
                dia  = int(m.group(1))
                mes  = int(m.group(2))
                anio = int(m.group(3))
                self.log(f"📅 Fecha visor: {dia}/{mes}/{anio}")
                return dt.date(anio, mes, dia)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------ #
    # Contador del carrusel  ej: "3 de 7"
    # ------------------------------------------------------------------ #
    def _leer_contador_carrusel(self) -> tuple[int, int] | None:
        try:
            elems = self.driver.find_elements(By.XPATH, '//*[text()]')
            for el in elems:
                txt = el.text.strip()
                m = re.match(r'^(\d+) de (\d+)$', txt)
                if m:
                    return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------ #
    # Descarga de adjunto principal
    # ------------------------------------------------------------------ #
    def descargar_adjunto(self, msg: dict, fecha_inicio: dt.date) -> list[str]:
        """
        Retorna lista de archivos descargados (puede ser vacía).
        Para imágenes recorre el carrusel desde el último hacia la izquierda.
        Para PDFs descarga directo.
        """
        data_id = msg["data_id"]
        es_pdf  = msg.get("es_pdf", False)
        self.log(f"⬇ Abriendo adjunto {data_id[:10]}...")

        for intento in range(1, MAX_REINTENTOS + 1):
            # Re-localizar y hacer clic en thumb
            resultado = self._abrir_visor(msg, data_id, intento)
            if resultado == "STALE":
                self._scroll_al_final()
                time.sleep(1.5)
                continue
            if resultado == "ERROR":
                return []
            break
        else:
            self.log(f"❌ No se pudo abrir el visor tras {MAX_REINTENTOS} intentos")
            return []

        time.sleep(2)

        if es_pdf:
            return self._descargar_pdf(fecha_inicio)
        else:
            return self._descargar_carrusel(fecha_inicio)

    def _abrir_visor(self, msg: dict, data_id: str, intento: int) -> str:
        try:
            msg_elem = self.driver.find_element(
                By.CSS_SELECTOR, f'[data-id="{data_id}"]')
        except NoSuchElementException:
            self.log(f"⚠ [{intento}] Mensaje no encontrado en DOM")
            return "ERROR"

        try:
            thumb_sel = SEL_DOC_THUMB if msg.get("es_pdf") else SEL_IMG_THUMB
            thumb = msg_elem.find_element(By.CSS_SELECTOR, thumb_sel)
            self.driver.execute_script(
                "arguments[0].scrollIntoView(true);", thumb)
            time.sleep(0.5)
            thumb.click()
            return "OK"
        except StaleElementReferenceException:
            self.log(f"⚠ [{intento}] StaleElement — reintentando...")
            return "STALE"
        except Exception as e:
            self.log(f"⚠ [{intento}] Error abriendo visor: {e}")
            return "ERROR"

    # ------------------------------------------------------------------ #
    # Descarga PDF
    # ------------------------------------------------------------------ #
    def _descargar_pdf(self, fecha_inicio: dt.date) -> list[str]:
        fecha_visor = self._leer_fecha_visor()
        if fecha_visor is not None and fecha_visor < fecha_inicio:
            self.log(f"⏭ PDF del {fecha_visor} anterior a fecha inicio — ignorado")
            self._cerrar_visor()
            return []

        archivo = self._click_descargar()
        self._cerrar_visor()
        return [archivo] if archivo else []

    # ------------------------------------------------------------------ #
    # Descarga carrusel de imágenes
    # ------------------------------------------------------------------ #
    def _descargar_carrusel(self, fecha_inicio: dt.date) -> list[str]:
        """
        Navega al último del carrusel, luego va hacia la izquierda
        descargando mientras fecha >= fecha_inicio.
        """
        archivos = []

        # Ir al último
        self._ir_al_ultimo_carrusel()
        time.sleep(1)

        while True:
            fecha_visor = self._leer_fecha_visor()

            if fecha_visor is not None and fecha_visor < fecha_inicio:
                self.log(f"⏭ Imagen del {fecha_visor} anterior a fecha inicio — deteniendo carrusel")
                break

            # Descargar imagen actual
            archivo = self._click_descargar()
            if archivo:
                self.log(f"🖼 Imagen descargada: {os.path.basename(archivo)}")
                archivos.append(archivo)

            # Mover a la izquierda
            if not self._click_anterior():
                self.log("ℹ Llegué al inicio del carrusel")
                break

            time.sleep(1)

        self._cerrar_visor()
        return archivos

    def _ir_al_ultimo_carrusel(self):
        """Hace clic en Siguiente hasta llegar al último."""
        max_intentos = 50
        for _ in range(max_intentos):
            try:
                btn = self.driver.find_element(
                    By.CSS_SELECTOR, SEL_BTN_SIGUIENTE)
                btn.click()
                time.sleep(0.5)
            except NoSuchElementException:
                break
            except Exception:
                break

    def _click_anterior(self) -> bool:
        try:
            btn = self.driver.find_element(
                By.CSS_SELECTOR, SEL_BTN_ANTERIOR)
            btn.click()
            return True
        except NoSuchElementException:
            return False
        except Exception:
            return False

    def _click_descargar(self) -> str | None:
        archivos_previos = self._snapshot_descargas()
        try:
            btn_dl = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, SEL_BTN_DESCARGAR))
            )
            btn_dl.click()
        except TimeoutException:
            self.log("⚠ Botón Descargar no apareció")
            return None
        return self._esperar_archivo_nuevo(archivos_previos)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
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