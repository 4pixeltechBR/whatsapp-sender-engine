"""
Unit and Integration Tests for BrowserService (Milestone 2 - R2 WhatsApp Web Engine).
Validates Playwright persistent context, stealth evasions, DOM state detection
(DISCONNECTED, AWAITING_QR, SYNCING, READY), QR Code extraction/reload, message & attachment
sending with modal auto-dismiss, and session persistence across restarts.
"""

import asyncio
import base64
from datetime import datetime
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

# Adiciona o diretório raiz ao sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.constants import ContactStatus, SessionStatus
from app.models.schemas import SendMessageResult
from app.services.browser_service import (
    BrowserService,
    ensure_clean_session_lock,
    DEFAULT_CHROME_ARGS,
    DEFAULT_USER_AGENT,
)


class TestBrowserServiceUnitAndIntegration(unittest.TestCase):
    """
    Testes unitários e de integração real para BrowserService via Playwright.
    Executa instâncias reais em modo headless com diretórios temporários isolados.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="wse_session_test_")
        self.session_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. Testes de Configuração, Contratos e Limpeza de Locks Órfãos
    # --------------------------------------------------------------------------

    def test_browser_service_initial_state_and_contracts(self):
        """Valida valores padrão, diretório de sessão e estado inicial desconectado."""
        service = BrowserService(session_dir=self.session_path, headless=True)
        self.assertEqual(service.session_dir, self.session_path)
        self.assertTrue(service.headless)
        self.assertEqual(service.current_status, SessionStatus.DISCONNECTED)
        self.assertFalse(service.is_connected())

    def test_ensure_clean_session_lock_removes_orphaned_locks(self):
        """Garante que arquivos SingletonLock, SingletonCookie e SingletonSocket sejam removidos."""
        lock_file = self.session_path / "SingletonLock"
        cookie_file = self.session_path / "SingletonCookie"
        socket_file = self.session_path / "SingletonSocket"

        lock_file.write_text("dummy_lock_content", encoding="utf-8")
        cookie_file.write_text("dummy_cookie_content", encoding="utf-8")
        socket_file.write_text("dummy_socket_content", encoding="utf-8")

        self.assertTrue(lock_file.exists())
        self.assertTrue(cookie_file.exists())
        self.assertTrue(socket_file.exists())

        cleaned = ensure_clean_session_lock(self.session_path)
        self.assertTrue(cleaned)
        self.assertFalse(lock_file.exists(), "SingletonLock deve ser removido")
        self.assertFalse(cookie_file.exists(), "SingletonCookie deve ser removido")
        self.assertFalse(socket_file.exists(), "SingletonSocket deve ser removido")

    # --------------------------------------------------------------------------
    # 2. Testes de Inicialização, Evasão e Stealth
    # --------------------------------------------------------------------------

    def test_stealth_evasion_and_browser_launch(self):
        """
        Inicia o BrowserService em headless=True e valida:
        - Contexto persistente funcional
        - navigator.webdriver == False (Stealth ativo)
        - User-Agent realista sem tag 'Headless'
        """
        async def run():
            service = BrowserService(
                session_dir=self.session_path,
                headless=True,
                channel=None,  # Usa Chromium padrão para portabilidade máxima
            )
            try:
                await service.start(target_url="about:blank")
                self.assertTrue(service.is_connected())
                self.assertIsNotNone(service.page)

                # Verifica se navigator.webdriver foi neutralizado
                webdriver_val = await service.page.evaluate("() => navigator.webdriver")
                self.assertFalse(webdriver_val, "navigator.webdriver deve ser False sob stealth")

                # Verifica User-Agent realista
                ua = await service.page.evaluate("() => navigator.userAgent")
                self.assertIn("Windows NT", ua)
                self.assertIn("Chrome", ua)
                self.assertNotIn("HeadlessChrome", ua, "User-Agent não deve conter 'HeadlessChrome'")
            finally:
                await service.close()
                self.assertFalse(service.is_connected())
                self.assertEqual(service.current_status, SessionStatus.DISCONNECTED)

        asyncio.run(run())

    # --------------------------------------------------------------------------
    # 3. Testes da Máquina de Estados da Sessão (DOM Detection)
    # --------------------------------------------------------------------------

    def test_session_state_detection_awaiting_qr(self):
        """Valida detecção de AWAITING_QR com base em seletores de QR Code."""
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")
                # Simula tela do WhatsApp Web aguardando leitura do QR Code
                html = """
                <html>
                <body>
                    <div data-testid="qrcode-container">
                        <div data-testid="qrcode" data-ref="test_ref_12345">
                            <canvas width="120" height="120"></canvas>
                        </div>
                    </div>
                </body>
                </html>
                """
                await service.page.set_content(html)
                status = await service.get_session_status()
                self.assertEqual(status, SessionStatus.AWAITING_QR)
                self.assertEqual(service.current_status, SessionStatus.AWAITING_QR)
            finally:
                await service.close()

        asyncio.run(run())

    def test_session_state_detection_syncing(self):
        """Valida detecção de SYNCING com base no indicador de carregamento de mensagens."""
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")
                # Simula tela de sincronização inicial
                html = """
                <html>
                <body>
                    <div data-testid="chat-list-initial-loading">
                        <div role="progressbar"></div>
                        <span>Baixando mensagens...</span>
                    </div>
                </body>
                </html>
                """
                await service.page.set_content(html)
                status = await service.get_session_status()
                self.assertEqual(status, SessionStatus.SYNCING)
                self.assertEqual(service.current_status, SessionStatus.SYNCING)
            finally:
                await service.close()

        asyncio.run(run())

    def test_session_state_detection_ready(self):
        """Valida detecção de READY quando o painel principal de conversas é carregado."""
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")
                # Simula tela autenticada com lista de chats
                html = """
                <html>
                <body>
                    <header data-testid="chatlist-header"></header>
                    <div id="pane-side">
                        <div data-testid="chat-list">
                            <div data-testid="cell-frame-container">Chat 1</div>
                        </div>
                    </div>
                </body>
                </html>
                """
                await service.page.set_content(html)
                status = await service.get_session_status()
                self.assertEqual(status, SessionStatus.READY)
                self.assertEqual(service.current_status, SessionStatus.READY)
            finally:
                await service.close()

        asyncio.run(run())

    # --------------------------------------------------------------------------
    # 4. Testes de Extração e Reload do QR Code
    # --------------------------------------------------------------------------

    def test_qr_code_extraction_and_screenshot(self):
        """Valida captura de imagem Base64, data-ref e flag de expiração do QR Code."""
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")
                html = """
                <html>
                <body>
                    <div data-testid="qrcode" data-ref="ref_qr_code_token_999" style="width:100px; height:100px; background:black;">
                        <canvas width="100" height="100"></canvas>
                    </div>
                </body>
                </html>
                """
                await service.page.set_content(html)
                qr_info = await service.get_qr_code()

                self.assertIsNotNone(qr_info)
                self.assertTrue(qr_info["visible"])
                self.assertFalse(qr_info["expired"])
                self.assertEqual(qr_info["data_ref"], "ref_qr_code_token_999")
                self.assertTrue(qr_info["screenshot_base64"].startswith("data:image/png;base64,"))
            finally:
                await service.close()

        asyncio.run(run())

    def test_reload_qr_code_when_expired(self):
        """Valida que reload_qr_code_if_expired clica no botão de recarregar quando o QR expira."""
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")
                html = """
                <html>
                <body>
                    <div data-testid="qrcode">
                        <button data-testid="qrcode-reload" id="btn-reload" onclick="this.setAttribute('data-clicked', 'true')">
                            Recarregar QR Code
                        </button>
                    </div>
                </body>
                </html>
                """
                await service.page.set_content(html)
                reloaded = await service.reload_qr_code_if_expired()
                self.assertTrue(reloaded)

                # Verifica se o evento de clique foi acionado
                clicked_attr = await service.page.locator("#btn-reload").get_attribute("data-clicked")
                self.assertEqual(clicked_attr, "true")
            finally:
                await service.close()

        asyncio.run(run())

    # --------------------------------------------------------------------------
    # 5. Teste de Resiliência a Modal de Erro / Número Inválido (Auto-Dismiss)
    # --------------------------------------------------------------------------

    def test_send_message_invalid_number_modal_auto_dismiss(self):
        """
        Valida que send_message detecta o modal de número inválido / sem WhatsApp,
        clica automaticamente no botão 'OK', registra ERR_INVALID_PHONE e retorna SendMessageResult(success=False).
        """
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")

                # Cria mock da navegação com surgimento dinâmico do modal de erro
                mock_page_html = """
                <html>
                <body>
                    <div id="app">Aguardando...</div>
                    <script>
                        setTimeout(() => {
                            const modal = document.createElement('div');
                            modal.setAttribute('role', 'dialog');
                            modal.innerHTML = `
                                <div data-testid="popup-contents">
                                    <p>O número de telefone compartilhado por url é inválido.</p>
                                    <button id="ok-btn" onclick="this.parentElement.parentElement.remove()">OK</button>
                                </div>
                            `;
                            document.body.appendChild(modal);
                        }, 300);
                    </script>
                </body>
                </html>
                """
                # Sobrescreve URL para simular SPA interna do WhatsApp
                await service.page.goto(f"data:text/html;charset=utf-8,{mock_page_html}")

                # Dispara envio para número inválido
                res = await service.send_message(
                    canonical_phone="5523999999999",
                    text="Teste",
                    timeout_seconds=5.0,
                    navigate=False,
                )

                self.assertFalse(res.success)
                self.assertEqual(res.status, ContactStatus.FAILED)
                self.assertEqual(res.error_code, "ERR_INVALID_PHONE")
                self.assertIn("inválido", res.error_detail.lower())

                # Valida que o modal foi dispensado (removido do DOM após clique no OK)
                modal_count = await service.page.locator('div[role="dialog"]').count()
                self.assertEqual(modal_count, 0, "O modal deve ser removido após o clique em OK")
            finally:
                await service.close()

        asyncio.run(run())

    # --------------------------------------------------------------------------
    # 6. Teste de Envio de Mensagem de Texto com Sucesso
    # --------------------------------------------------------------------------

    def test_send_message_valid_contact_text_success(self):
        """
        Valida que send_message localiza o campo de composição,
        digita o texto, clica no botão de envio e retorna SendMessageResult(success=True).
        """
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")

                # Simula página com caixa de composição e botão de envio
                mock_page_html = """
                <html>
                <body>
                    <div id="main">
                        <footer>
                            <div data-testid="conversation-compose-box-input" contenteditable="true" id="compose-box"></div>
                            <button data-testid="compose-btn-send" id="send-btn" onclick="this.setAttribute('data-sent', 'true')">
                                Enviar
                            </button>
                        </footer>
                    </div>
                </body>
                </html>
                """
                await service.page.goto(f"data:text/html;charset=utf-8,{mock_page_html}")

                res = await service.send_message(
                    canonical_phone="5562994912937",
                    text="Olá, esta é uma mensagem de teste!",
                    timeout_seconds=5.0,
                    typing_delay_ms=0.0,
                    navigate=False,
                )

                self.assertTrue(res.success)
                self.assertEqual(res.status, ContactStatus.SENT)
                self.assertIsNone(res.error_code)

                # Verifica se o texto foi digitado no campo
                typed_text = await service.page.locator("#compose-box").text_content()
                self.assertIn("Olá, esta é uma mensagem de teste!", typed_text)

                # Verifica se o botão de envio foi clicado
                sent_attr = await service.page.locator("#send-btn").get_attribute("data-sent")
                self.assertEqual(sent_attr, "true")
            finally:
                await service.close()

        asyncio.run(run())

    # --------------------------------------------------------------------------
    # 7. Teste de Envio de Mensagem com Anexo Multimídia
    # --------------------------------------------------------------------------

    def test_send_message_with_attachment_success(self):
        """
        Valida que send_message com anexo injeta o arquivo no input[type='file'],
        insere legenda e dispara o envio.
        """
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")

                # Cria arquivo temporário de anexo
                temp_file = Path(self.temp_dir) / "teste_anexo.txt"
                temp_file.write_text("Conteudo do documento de teste", encoding="utf-8")

                mock_page_html = """
                <html>
                <body>
                    <footer>
                        <input type="file" id="file-input" onchange="document.getElementById('media-preview').style.display='block'">
                        <div data-testid="conversation-compose-box-input" contenteditable="true"></div>
                    </footer>
                    <div id="media-preview" style="display:none;">
                        <div data-testid="media-caption-input-container">
                            <div contenteditable="true" id="caption-input"></div>
                        </div>
                        <button data-testid="send" id="media-send-btn" onclick="this.setAttribute('data-media-sent', 'true')">
                            Enviar Mídia
                        </button>
                    </div>
                </body>
                </html>
                """
                await service.page.goto(f"data:text/html;charset=utf-8,{mock_page_html}")

                res = await service.send_message(
                    canonical_phone="5562994912937",
                    text="Veja o anexo em anexo!",
                    attachment_path=str(temp_file),
                    timeout_seconds=5.0,
                    typing_delay_ms=0.0,
                    navigate=False,
                )

                self.assertTrue(res.success)
                self.assertEqual(res.status, ContactStatus.SENT)

                # Verifica se o botão de envio de mídia foi acionado
                sent_attr = await service.page.locator("#media-send-btn").get_attribute("data-media-sent")
                self.assertEqual(sent_attr, "true")
            finally:
                await service.close()

        asyncio.run(run())

    def test_send_message_missing_attachment_returns_error(self):
        """Valida que informar caminho de anexo inexistente retorna erro ERR_ATTACHMENT_NOT_FOUND."""
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")

                fake_path = Path(self.temp_dir) / "arquivo_fantasma.pdf"
                res = await service.send_message(
                    canonical_phone="5562994912937",
                    text="Olá",
                    attachment_path=str(fake_path),
                    timeout_seconds=3.0,
                    navigate=False,
                )

                self.assertFalse(res.success)
                self.assertEqual(res.status, ContactStatus.FAILED)
                self.assertEqual(res.error_code, "ERR_ATTACHMENT_NOT_FOUND")
            finally:
                await service.close()

        asyncio.run(run())

    # --------------------------------------------------------------------------
    # 8. Teste de Persistência de Sessão entre Reinicializações (Critério R2)
    # --------------------------------------------------------------------------

    def test_session_persistence_across_restarts_r2_acceptance(self):
        """
        Critério de Aceite R2:
        Comprova que dados de sessão (IndexedDB / LocalStorage) gravados no userDataDir
        são preservados intactos ao fechar e reabrir o BrowserService no mesmo diretório.
        """
        async def run():
            target_profile_dir = Path(self.temp_dir) / "persistent_profile"
            
            # Cria página HTML com origem de arquivo válida para suportar LocalStorage
            test_html_page = Path(self.temp_dir) / "storage_test.html"
            test_html_page.write_text("<html><body><h1>Storage Test</h1></body></html>", encoding="utf-8")
            page_uri = test_html_page.as_uri()

            # 1ª Execução: Inicializa sessão e grava token no LocalStorage / IndexedDB
            service1 = BrowserService(session_dir=target_profile_dir, headless=True, channel=None)
            try:
                await service1.start(target_url=page_uri)
                # Grava chave de autenticação simulando token Signal / WAPersistence
                await service1.page.evaluate("""() => {
                    localStorage.setItem('wa_auth_token_secret', 'SIGNAL_KEY_AUTHENTICATED_123456');
                    localStorage.setItem('wa_user_jid', '5562994912937@c.us');
                }""")
                # Confirma gravação na 1ª sessão
                stored_val = await service1.page.evaluate("() => localStorage.getItem('wa_auth_token_secret')")
                self.assertEqual(stored_val, "SIGNAL_KEY_AUTHENTICATED_123456")
            finally:
                # Fecha completamente o navegador garantindo flush no disco
                await service1.close()

            self.assertFalse(service1.is_connected())

            # 2ª Execução: Reabre nova instância de BrowserService apontando para o MESMO diretório
            service2 = BrowserService(session_dir=target_profile_dir, headless=True, channel=None)
            try:
                await service2.start(target_url=page_uri)
                self.assertTrue(service2.is_connected())

                # Lê as credenciais persistidas no perfil
                restored_token = await service2.page.evaluate("() => localStorage.getItem('wa_auth_token_secret')")
                restored_jid = await service2.page.evaluate("() => localStorage.getItem('wa_user_jid')")

                self.assertEqual(
                    restored_token,
                    "SIGNAL_KEY_AUTHENTICATED_123456",
                    "Token de autenticação deve persistir no mesmo userDataDir sem solicitar novo login"
                )
                self.assertEqual(
                    restored_jid,
                    "5562994912937@c.us",
                    "JID do usuário deve persistir no mesmo userDataDir"
                )
            finally:
                await service2.close()

        asyncio.run(run())

    # --------------------------------------------------------------------------
    # 9. Teste de Encerramento Seguro e Reconexão
    # --------------------------------------------------------------------------

    def test_safe_restart_and_close(self):
        """Valida que restart() fecha e reabre o contexto sem erros ou travamento de lock."""
        async def run():
            service = BrowserService(session_dir=self.session_path, headless=True, channel=None)
            try:
                await service.start(target_url="about:blank")
                self.assertTrue(service.is_connected())

                # Executa restart
                await service.restart(target_url="about:blank")
                self.assertTrue(service.is_connected())
                self.assertIsNotNone(service.page)
            finally:
                await service.close()
                self.assertFalse(service.is_connected())

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
