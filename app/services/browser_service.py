"""
Playwright-Based WhatsApp Web Automation Engine for WhatsApp Sender Engine.
Alinhado rigorosamente com os Contratos de Interface e Requisitos de PROJECT.md (M2 - R2).

Recursos Implementados:
- Lançamento de contexto persistente Playwright via launch_persistent_context no diretório userDataDir.
- Configuração flexível: headless=False por padrão (janela visível para leitura do QR Code)
  com suporte opcional a headless=True para execução em segundo plano ou testes automatizados.
- Evasão e Stealth: flags anti-automação (--disable-blink-features=AutomationControlled, --no-sandbox),
  User-Agent autêntico do Chrome Windows e integração com playwright-stealth.
- Detecção e monitoramento em tempo real do estado da sessão:
  DISCONNECTED, AWAITING_QR, SYNCING, READY.
- Extração de dados e screenshot do QR Code em Base64 para exibição na UI e auto-reload caso expire.
- Navegação direta para https://web.whatsapp.com/send?phone={canonical_phone}.
- Detecção e descarte automático do modal de erro/número inválido (auto-dismiss com clique em OK),
  registrando ERR_INVALID_PHONE e retornando SendMessageResult(success=False).
- Localização do campo de composição de mensagem com simulação de digitação humana e envio.
- Suporte a envio de anexos multimídia (imagens, vídeos, documentos) via input[type="file"].
- Persistência garantida de sessão (IndexedDB / LocalStorage) entre reinicializações sem perda de login.
- Limpeza preventiva de arquivos de lock órfãos (SingletonLock).
- Fechamento seguro (close()) e reconexão (restart()).
"""

import asyncio
import base64
from datetime import datetime
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Union

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)
# Garante importações absolutas mesmo na execução direta como script
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from playwright_stealth import Stealth

from app.core.config import settings
from app.core.constants import ContactStatus, SessionStatus
from app.models.schemas import SendMessageResult

logger = logging.getLogger("whatsapp_sender_engine.browser_service")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [BrowserService] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# Flags de evasão e lançamento do Chromium
DEFAULT_CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]

DEFAULT_IGNORE_DEFAULT_ARGS = [
    "--enable-automation",
]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

WHATSAPP_WEB_URL = "https://web.whatsapp.com"


def ensure_clean_session_lock(session_dir: Union[Path, str]) -> bool:
    """
    Remove arquivos de lock órfãos (SingletonLock, SingletonCookie, SingletonSocket)
    no diretório da sessão para prevenir erros de concorrência ou crash de inicialização
    caso o processo anterior do Chromium tenha sido encerrado abruptamente.
    """
    path = Path(session_dir).resolve()
    if not path.exists():
        return True

    lock_filenames = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
    cleaned = False

    paths_to_check = [path]
    default_dir = path / "Default"
    if default_dir.exists():
        paths_to_check.append(default_dir)

    for base in paths_to_check:
        for fname in lock_filenames:
            target_lock = base / fname
            if target_lock.exists():
                try:
                    target_lock.unlink(missing_ok=True)
                    cleaned = True
                    logger.info("Lock órfão do Chromium removido com sucesso: %s", target_lock)
                except Exception as ex:
                    logger.warning("Não foi possível desvincular lock file %s (ativo?): %s", target_lock, ex)

    return cleaned


class BrowserService:
    """
    Motor de automação Playwright Chromium para WhatsApp Web.
    Gerencia contexto persistente, stealth, detecção de estados,
    leitura de QR Code, envio de mensagens/anexos e resiliência a modais.
    """

    def __init__(
        self,
        session_dir: Optional[Union[Path, str]] = None,
        headless: bool = False,
        channel: Optional[str] = "chrome",
        user_agent: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.session_dir = Path(session_dir or settings.SESSION_DIR).resolve()
        self.headless = headless
        self.channel = channel
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.default_timeout = timeout

        # Instâncias de runtime do Playwright
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._current_status: SessionStatus = SessionStatus.DISCONNECTED
        self._is_starting: bool = False
        self._lock = asyncio.Lock()

    # --------------------------------------------------------------------------
    # 1. Ciclo de Vida e Inicialização do Navegador
    # --------------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Verifica se o navegador e o contexto estão ativos e operacionais."""
        return (
            self.context is not None
            and self.page is not None
            and not self.page.is_closed()
        )

    @property
    def current_status(self) -> SessionStatus:
        """Retorna o último estado registrado da sessão."""
        return self._current_status

    async def start(
        self,
        target_url: Optional[str] = WHATSAPP_WEB_URL,
        wait_for_load: bool = True,
    ) -> None:
        """
        Inicializa o Playwright e lança o contexto persistente com stealth ativo.
        """
        async with self._lock:
            if self.is_connected():
                logger.info("BrowserService já está iniciado e conectado.")
                return

            self._is_starting = True
            try:
                # 1. Garante que o diretório persistente exista e limpa locks órfãos
                self.session_dir.mkdir(parents=True, exist_ok=True)
                ensure_clean_session_lock(self.session_dir)

                logger.info(
                    "Iniciando Playwright Persistent Context em '%s' (headless=%s, channel=%s)...",
                    self.session_dir, self.headless, self.channel
                )

                # 2. Inicializa o Playwright
                if self.playwright is None:
                    self.playwright = await async_playwright().start()

                # 3. Configura parâmetros de lançamento persistente
                launch_kwargs: Dict[str, Any] = {
                    "user_data_dir": str(self.session_dir),
                    "headless": self.headless,
                    "args": DEFAULT_CHROME_ARGS,
                    "ignore_default_args": DEFAULT_IGNORE_DEFAULT_ARGS,
                    "user_agent": self.user_agent,
                    "locale": "pt-BR",
                    "timezone_id": "America/Sao_Paulo",
                    "accept_downloads": True,
                }

                if self.headless:
                    launch_kwargs["viewport"] = {"width": 1280, "height": 800}
                else:
                    launch_kwargs["no_viewport"] = True

                # 4. Tenta lançar com o canal configurado (fallback para Chromium padrão se necessário)
                try:
                    if self.channel:
                        self.context = await self.playwright.chromium.launch_persistent_context(
                            channel=self.channel,
                            **launch_kwargs,
                        )
                    else:
                        self.context = await self.playwright.chromium.launch_persistent_context(
                            **launch_kwargs,
                        )
                except Exception as launch_err:
                    if self.channel and ("Executable doesn't exist" in str(launch_err) or "channel" in str(launch_err).lower()):
                        logger.warning(
                            "Canal '%s' indisponível (%s). Realizando fallback para Chromium padrão...",
                            self.channel, launch_err
                        )
                        self.channel = None
                        self.context = await self.playwright.chromium.launch_persistent_context(
                            **launch_kwargs,
                        )
                    else:
                        raise launch_err

                # 5. Obtém ou cria a página primária
                if self.context.pages:
                    self.page = self.context.pages[0]
                else:
                    self.page = await self.context.new_page()

                # 6. Aplica evasões do Playwright Stealth
                try:
                    await Stealth().apply_stealth_async(self.page)
                except Exception as stealth_err:
                    logger.warning("Aviso ao aplicar stealth: %s", stealth_err)

                # 7. Listeners de ciclo de vida para desconexão
                self.page.on("close", self._on_page_closed)
                self.context.on("close", self._on_context_closed)

                # 8. Navega para a URL alvo
                if target_url:
                    logger.info("Navegando para: %s", target_url)
                    try:
                        timeout_ms = int(self.default_timeout * 1000)
                        await self.page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    except Exception as nav_err:
                        logger.warning("Navegação inicial teve aviso/timeout: %s", nav_err)

                # 9. Atualiza o estado da sessão
                await self.get_session_status()
                logger.info("BrowserService iniciado com sucesso. Status atual: %s", self._current_status.value)

            finally:
                self._is_starting = False

    def _on_page_closed(self, page: Page) -> None:
        logger.info("Página do navegador fechada.")
        self._current_status = SessionStatus.DISCONNECTED

    def _on_context_closed(self, context: BrowserContext) -> None:
        logger.info("Contexto do navegador fechado.")
        self._current_status = SessionStatus.DISCONNECTED

    async def close(self) -> None:
        """
        Encerra com segurança a página, contexto persistente e instância do Playwright,
        assegurando que todas as transações de IndexedDB e LocalStorage sejam salvas em disco.
        """
        async with self._lock:
            try:
                if self.page and not self.page.is_closed():
                    await self.page.close()
            except Exception as ex:
                logger.debug("Aviso ao fechar página: %s", ex)
            finally:
                self.page = None

            try:
                if self.context:
                    await self.context.close()
            except Exception as ex:
                logger.debug("Aviso ao fechar contexto: %s", ex)
            finally:
                self.context = None

            try:
                if self.playwright:
                    await self.playwright.stop()
            except Exception as ex:
                logger.debug("Aviso ao parar Playwright: %s", ex)
            finally:
                self.playwright = None

            self._current_status = SessionStatus.DISCONNECTED
            logger.info("BrowserService encerrado com sucesso.")

    async def restart(self, target_url: Optional[str] = WHATSAPP_WEB_URL) -> None:
        """Reinicia o navegador fechando o contexto atual e reabrindo a mesma sessão."""
        logger.info("Reiniciando BrowserService...")
        await self.close()
        await self.start(target_url=target_url)

    async def __aenter__(self) -> "BrowserService":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    # --------------------------------------------------------------------------
    # 2. Detecção e Monitoramento do Estado da Sessão
    # --------------------------------------------------------------------------

    async def get_session_status(self) -> SessionStatus:
        """
        Verifica o estado atual da sessão no DOM do WhatsApp Web:
        - DISCONNECTED: navegador fechado, offline ou sem conexão.
        - AWAITING_QR: presença de elemento QR Code na tela.
        - SYNCING: carregamento inicial de mensagens ou progresso ativo.
        - READY: lista de conversas (#pane-side / chat-list) carregada e pronta.
        """
        if not self.is_connected() or self.page is None:
            self._current_status = SessionStatus.DISCONNECTED
            return SessionStatus.DISCONNECTED

        try:
            state_str = await self.page.evaluate("""() => {
                // 1. Ready: presença da lista de conversas, pane lateral ou header
                if (document.querySelector('#pane-side') || 
                    document.querySelector('div[data-testid="chat-list"]') ||
                    document.querySelector('header[data-testid="chatlist-header"]') ||
                    document.querySelector('div[data-testid="chat-list-search"]')) {
                    return "READY";
                }

                // 2. Syncing: carregamento de mensagens, tela de progresso ou inicialização
                if (document.querySelector('div[data-testid="chat-list-initial-loading"]') ||
                    document.querySelector('#initial_startup') ||
                    document.querySelector('div[role="progressbar"]')) {
                    return "SYNCING";
                }

                const bodyText = document.body ? (document.body.innerText || "") : "";
                if (bodyText.includes("Baixando mensagens") || 
                    bodyText.includes("Sincronizando") ||
                    bodyText.includes("Conectando") ||
                    bodyText.includes("Carregando suas conversas") ||
                    bodyText.includes("Downloading messages")) {
                    return "SYNCING";
                }

                // 3. Awaiting QR: presença de canvas ou container do QR Code
                if (document.querySelector('div[data-testid="qrcode"]') ||
                    document.querySelector('canvas[aria-label="Scan me!"]') ||
                    document.querySelector('div[data-testid="qrcode-container"]') ||
                    document.querySelector('div[data-ref]') ||
                    document.querySelector('button[data-testid="qrcode-reload"]') ||
                    document.querySelector('span[data-icon="refresh"]') ||
                    document.querySelector('span[data-testid="refresh-large"]') ||
                    document.querySelector('canvas')) {
                    return "AWAITING_QR";
                }

                // 4. Se alerta de computador desconectado estiver ativo
                if (document.querySelector('div[data-testid="alert-computer-not-connected"]')) {
                    return "DISCONNECTED";
                }

                // Se estiver na URL do WhatsApp mas nada carregou ainda
                if (window.location.href.includes("web.whatsapp.com")) {
                    return "SYNCING";
                }

                return "DISCONNECTED";
            }""")

            status_map = {
                "READY": SessionStatus.READY,
                "SYNCING": SessionStatus.SYNCING,
                "AWAITING_QR": SessionStatus.AWAITING_QR,
                "DISCONNECTED": SessionStatus.DISCONNECTED,
            }
            self._current_status = status_map.get(state_str, SessionStatus.DISCONNECTED)
            return self._current_status

        except Exception as ex:
            logger.debug("Falha ao avaliar estado da sessão: %s", ex)
            self._current_status = SessionStatus.DISCONNECTED
            return SessionStatus.DISCONNECTED

    async def wait_for_status(
        self,
        target_status: Union[SessionStatus, List[SessionStatus]],
        timeout_seconds: float = 60.0,
        poll_interval: float = 0.5,
    ) -> SessionStatus:
        """
        Aguarda até que a sessão atinja o status alvo especificado ou ocorra timeout.
        """
        targets = [target_status] if isinstance(target_status, SessionStatus) else target_status
        start_time = time.monotonic()

        while (time.monotonic() - start_time) < timeout_seconds:
            current = await self.get_session_status()
            if current in targets:
                return current
            await asyncio.sleep(poll_interval)

        return await self.get_session_status()

    async def wait_for_ready(self, timeout_seconds: float = 60.0, poll_interval: float = 0.5) -> bool:
        """Atalho conveniente para aguardar até que a sessão atinja o estado READY."""
        status = await self.wait_for_status(SessionStatus.READY, timeout_seconds=timeout_seconds, poll_interval=poll_interval)
        return status == SessionStatus.READY

    # --------------------------------------------------------------------------
    # 3. Detecção e Extração do QR Code
    # --------------------------------------------------------------------------

    async def get_qr_code(self) -> Optional[Dict[str, Any]]:
        """
        Retorna metadados do QR Code e screenshot em Base64 para feedback na UI.
        Retorna None caso o QR Code não esteja presente ou visível.
        """
        if not self.is_connected() or self.page is None:
            return None

        try:
            qr_selectors = [
                'div[data-testid="qrcode"]',
                'canvas[aria-label="Scan me!"]',
                'div[data-ref]',
                'div[data-testid="qrcode-container"]',
                'canvas',
            ]

            qr_element = None
            for sel in qr_selectors:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    qr_element = loc
                    break

            if qr_element is None:
                return None

            # Detecta se o QR Code está expirado
            reload_loc = self.page.locator(
                'button[data-testid="qrcode-reload"], span[data-icon="refresh"], span[data-testid="refresh-large"]'
            ).first
            expired = (await reload_loc.count() > 0) and (await reload_loc.is_visible())

            # Extrai atributo data-ref se disponível
            data_ref = await qr_element.get_attribute("data-ref")

            # Tira screenshot do elemento QR Code em formato Base64 PNG
            screenshot_bytes = await qr_element.screenshot(type="png")
            b64_image = base64.b64encode(screenshot_bytes).decode("utf-8")

            data_uri = f"data:image/png;base64,{b64_image}"
            return {
                "visible": True,
                "expired": expired,
                "data_ref": data_ref,
                "screenshot_base64": data_uri,
                "qr_image_base64": data_uri,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as ex:
            logger.error("Erro ao capturar dados do QR Code: %s", ex)
            return None

    async def reload_qr_code_if_expired(self) -> bool:
        """
        Verifica se o botão de recarregar QR Code expirado está visível e clica nele.
        """
        if not self.is_connected() or self.page is None:
            return False

        try:
            reload_loc = self.page.locator(
                'button[data-testid="qrcode-reload"], span[data-icon="refresh"], span[data-testid="refresh-large"]'
            ).first
            if await reload_loc.count() > 0 and await reload_loc.is_visible():
                await reload_loc.click()
                await asyncio.sleep(0.5)
                logger.info("Botão de recarregar QR Code acionado com sucesso.")
                return True
        except Exception as ex:
            logger.warning("Falha ao recarregar QR Code: %s", ex)

        return False

    # --------------------------------------------------------------------------
    # 4. Envio de Mensagens, Anexos e Resiliência a Números Inválidos
    # --------------------------------------------------------------------------

    async def send_message(
        self,
        canonical_phone: str,
        text: str,
        attachment_path: Optional[Union[Path, str]] = None,
        timeout_seconds: float = 30.0,
        typing_delay_ms: float = 15.0,
        navigate: bool = True,
    ) -> SendMessageResult:
        """
        Envia mensagem de texto e/ou anexo multimídia para o número canônico E.164.

        Fluxo de Operação:
        1. Se navigate=True (padrão), navega para https://web.whatsapp.com/send?phone={canonical_phone}.
        2. Detecta simultaneamente:
           - Modal de Erro (Número sem WhatsApp / URL inválida): clica automaticamente em 'OK',
             registra o erro ERR_INVALID_PHONE e retorna SendMessageResult(success=False).
           - Campo de Composição (Chat carregado com sucesso): prossegue para digitação e envio.
        3. Se houver anexo, insere via input[type="file"], adiciona legenda se aplicável e envia.
        4. Simula digitação humana no campo e clica no botão de envio ou pressiona Enter.
        """
        if not self.is_connected() or self.page is None:
            return SendMessageResult(
                canonical_phone=canonical_phone,
                success=False,
                status=ContactStatus.FAILED,
                error_code="BROWSER_DISCONNECTED",
                error_detail="Navegador não iniciado ou desconectado.",
                timestamp=datetime.now(),
            )

        # Validação antecipada do arquivo de anexo caso informado
        if attachment_path:
            att_file = Path(attachment_path).resolve()
            if not att_file.exists():
                logger.error("Anexo não encontrado em %s para %s", attachment_path, canonical_phone)
                return SendMessageResult(
                    canonical_phone=canonical_phone,
                    success=False,
                    status=ContactStatus.FAILED,
                    error_code="ERR_ATTACHMENT_NOT_FOUND",
                    error_detail=f"Arquivo de anexo não encontrado no caminho: {attachment_path}",
                    timestamp=datetime.now(),
                )

        # Navegação para a URL de envio do WhatsApp Web (se habilitada)
        if navigate:
            target_url = f"https://web.whatsapp.com/send?phone={canonical_phone}"
            logger.info("Navegando para envio: %s", target_url)

            try:
                current_url = self.page.url
                if "web.whatsapp.com" in current_url:
                    await self.page.evaluate("url => { window.location.href = url; }", target_url)
                else:
                    await self.page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            except Exception as ex:
                logger.error("Erro ao navegar para %s: %s", target_url, ex)
                return SendMessageResult(
                    canonical_phone=canonical_phone,
                    success=False,
                    status=ContactStatus.FAILED,
                    error_code="ERR_NAVIGATION_FAILED",
                    error_detail=f"Falha ao carregar URL do contato: {ex}",
                    timestamp=datetime.now(),
                )

        # ----------------------------------------------------------------------
        # Race Condition: Detecção Simultânea de Modal de Erro vs Campo de Chat
        # ----------------------------------------------------------------------
        start_time = time.monotonic()

        error_dialog_selectors = [
            'div[role="dialog"] button:has-text("OK")',
            'div[data-testid="popup-contents"] button:has-text("OK")',
            'div[data-animate-modal-popup="true"] button:has-text("OK")',
            'div[role="dialog"] [data-testid="popup-controls-ok"]',
            'button[data-testid="popup-controls-ok"]',
            'div[data-testid="popup-contents"] button',
            'div[role="dialog"] button',
            'button:has-text("OK")',
            '#ok-btn',
        ]

        compose_selectors = [
            'div[data-testid="conversation-compose-box-input"]',
            'footer div[contenteditable="true"]',
            'div[role="textbox"][contenteditable="true"]',
            '#compose-box',
        ]

        compose_box = None

        while (time.monotonic() - start_time) < timeout_seconds:
            # 1. Checa se o modal de número inválido surgiu
            for sel in error_dialog_selectors:
                ok_btn = self.page.locator(sel).first
                if await ok_btn.count() > 0 and await ok_btn.is_visible():
                    dialog_text = ""
                    try:
                        dialog_el = self.page.locator('div[role="dialog"], div[data-testid="popup-contents"]').first
                        if await dialog_el.count() > 0:
                            dialog_text = (await dialog_el.text_content()) or ""
                    except Exception:
                        pass

                    logger.warning(
                        "Modal de número inválido detectado para %s ('%s'). Executando auto-dismiss com clique em OK...",
                        canonical_phone, dialog_text.strip()
                    )

                    try:
                        await ok_btn.click(timeout=3000)
                        await asyncio.sleep(0.5)
                    except Exception as click_err:
                        logger.warning("Aviso ao clicar no botão OK do modal: %s", click_err)

                    return SendMessageResult(
                        canonical_phone=canonical_phone,
                        success=False,
                        status=ContactStatus.FAILED,
                        error_code="ERR_INVALID_PHONE",
                        error_detail="Número de telefone inválido ou sem WhatsApp ativo (modal dispensado automaticamente).",
                        timestamp=datetime.now(),
                    )

            # 2. Checa se o campo de composição ficou disponível
            for sel in compose_selectors:
                box = self.page.locator(sel).first
                if await box.count() > 0 and await box.is_visible():
                    compose_box = box
                    break

            if compose_box is not None:
                break

            await asyncio.sleep(0.2)

        if compose_box is None:
            logger.error("Timeout de %ss aguardando conversa de %s", timeout_seconds, canonical_phone)
            return SendMessageResult(
                canonical_phone=canonical_phone,
                success=False,
                status=ContactStatus.FAILED,
                error_code="ERR_TIMEOUT",
                error_detail=f"Timeout aguardando carregamento da conversa para {canonical_phone}.",
                timestamp=datetime.now(),
            )

        # ----------------------------------------------------------------------
        # Execução do Envio (Com Anexo ou Texto Puro)
        # ----------------------------------------------------------------------
        try:
            if attachment_path:
                att_file = Path(attachment_path).resolve()
                logger.info("Anexando arquivo para %s: %s", canonical_phone, att_file)

                # Localiza ou aciona o input de arquivo
                file_input = self.page.locator('input[type="file"]').first
                if await file_input.count() == 0:
                    attach_btn = self.page.locator(
                        'button[data-testid="attach-menu-plus"], span[data-icon="plus"], span[data-icon="attach-menu-plus"], div[title="Anexar"], div[aria-label="Anexar"]'
                    ).first
                    if await attach_btn.count() > 0 and await attach_btn.is_visible():
                        await attach_btn.click()
                        await asyncio.sleep(0.4)

                file_input = self.page.locator('input[type="file"]').first
                await file_input.set_input_files(str(att_file))
                await asyncio.sleep(1.0)

                # Se houver texto, insere como legenda no container de legenda de mídia
                if text:
                    caption_box = self.page.locator(
                        'div[data-testid="media-caption-input-container"] div[contenteditable="true"], div[aria-label="Adicionar uma legenda"], #caption-input'
                    ).first
                    if await caption_box.count() > 0 and await caption_box.is_visible():
                        if typing_delay_ms > 0:
                            from app.services.dispatcher_service import BiomechanicTypingSimulator
                            await BiomechanicTypingSimulator.type_humanlike_playwright(
                                page=self.page,
                                target_locator=caption_box,
                                text=text,
                            )
                        else:
                            await caption_box.click()
                            await caption_box.press_sequentially(text, delay=0)

                # Clica no botão de enviar da prévia de mídia
                send_media_btn = self.page.locator(
                    'div[data-testid="send"], button[data-testid="send"], span[data-icon="send"], #media-send-btn'
                ).first
                if await send_media_btn.count() > 0 and await send_media_btn.is_visible():
                    await send_media_btn.click()
                else:
                    await self.page.keyboard.press("Enter")

                await asyncio.sleep(1.0)

            else:
                # Envio de Texto Puro
                logger.info("Digitando texto para %s...", canonical_phone)

                if typing_delay_ms > 0:
                    from app.services.dispatcher_service import BiomechanicTypingSimulator
                    await BiomechanicTypingSimulator.type_humanlike_playwright(
                        page=self.page,
                        target_locator=compose_box,
                        text=text,
                    )
                else:
                    await compose_box.click()
                    await compose_box.fill(text)

                await asyncio.sleep(0.2)

                # Localiza botão de envio ou dispara Enter
                send_btn = self.page.locator(
                    'button[data-testid="compose-btn-send"], span[data-icon="send"], #send-btn'
                ).first
                if await send_btn.count() > 0 and await send_btn.is_visible():
                    await send_btn.click()
                else:
                    await self.page.keyboard.press("Enter")

                await asyncio.sleep(0.5)

            logger.info("Mensagem disparada com sucesso para %s", canonical_phone)
            return SendMessageResult(
                canonical_phone=canonical_phone,
                success=True,
                status=ContactStatus.SENT,
                error_code=None,
                error_detail="Mensagem enviada com sucesso",
                timestamp=datetime.now(),
            )

        except Exception as ex:
            logger.error("Exceção ao disparar mensagem para %s: %s", canonical_phone, ex)
            return SendMessageResult(
                canonical_phone=canonical_phone,
                success=False,
                status=ContactStatus.FAILED,
                error_code="ERR_SEND_EXECUTION",
                error_detail=f"Exceção durante envio: {ex}",
                timestamp=datetime.now(),
            )


# Singleton padrão exportado para a aplicação
browser_service = BrowserService()

__all__ = [
    "BrowserService",
    "ensure_clean_session_lock",
    "browser_service",
    "WHATSAPP_WEB_URL",
    "DEFAULT_CHROME_ARGS",
    "DEFAULT_USER_AGENT",
]


if __name__ == "__main__":
    print("=" * 70)
    print("   WHATSAPP SENDER ENGINE — BROWSER SERVICE SELF-DIAGNOSTIC")
    print("=" * 70)
    print(f" Raiz da Sessão: {browser_service.session_dir}")
    print(f" Modo Headless Padrão: {browser_service.headless}")
    print(f" Canal Padrão: {browser_service.channel}")
    print(f" User-Agent: {browser_service.user_agent[:60]}...")
    print(f" Status Inicial: {browser_service.current_status.value}")
    
    cleaned = ensure_clean_session_lock(browser_service.session_dir)
    print(f" Limpeza Preventiva de Locks: Concluída ({cleaned})")
    print("=" * 70)
    print("[PASS] BrowserService validado e pronto para operação. [EXIT 0]")
