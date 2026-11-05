"""
Desktop Server Application and REST/SSE API for WhatsApp Sender Engine.
Alinhado rigorosamente com PROJECT.md, ORIGINAL_REQUEST.md e Milestone 4 (M4 - R4).

Recursos e Endpoints Implementados:
- Ingestão de Contatos:
  * POST /api/contacts/upload: Upload de planilhas Excel (.xlsx, .xls) e CSV (.csv, .txt) via contact_service.
  * POST /api/contacts/manual: Ingestão de texto bruto colado pelo usuário.
  * GET /api/contacts: Lista contatos carregados e métricas de higienização.
  * DELETE /api/contacts: Limpa lista de contatos em memória.
- Sessão WhatsApp Web:
  * GET /api/session/status: Estado da conexão (DESCONECTADO, AGUARDANDO_QR, SINCRONIZANDO, CONECTADO_PRONTO).
  * GET /api/session/qr: Obtenção do QR Code em Base64 para escaneamento.
  * POST /api/session/start: Lançamento do navegador Chromium persistente.
  * POST /api/session/close: Fechamento seguro da sessão.
- Fila e Controles Anti-Ban:
  * POST /api/queue/start: Início do disparo com concorrência unitária, jitter estocástico e pausas por bloco.
  * POST /api/queue/pause: Pausa atômica sem perda de progresso.
  * POST /api/queue/resume: Retomada a partir do próximo contato pendente.
  * POST /api/queue/abort: Aborto imediato com cancelamento de pendentes.
- Telemetria e Relatórios:
  * GET /api/telemetry/snapshot: Snapshot instantâneo de métricas, contadores e ETA estocástico.
  * GET /api/telemetry/stream: Streaming SSE em tempo real (Server-Sent Events) para UI Desktop.
  * GET /api/reports/export/excel: Download do relatório executivo .xlsx com formato @ texto e aba de resumo.
  * GET /api/reports/export/csv: Download do relatório .csv com BOM utf-8-sig e delimitador ';'.
  * GET /api/reports/logs: Logs estruturados por contato e histórico do sistema.
- Interface Desktop:
  * Montagem de arquivos estáticos de app/static/ e rota raiz index.html.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import logging
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Garante que a raiz do projeto esteja no sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.core.constants import ContactStatus, QueueState, SessionStatus
from app.models.schemas import (
    CampaignConfig,
    ContactRecord,
    IngestionResult,
    ManualPasteRequest,
    SendMessageResult,
    TelemetrySnapshot,
)
from app.services.browser_service import browser_service
from app.services.contact_service import contact_service
from app.services.dispatcher_service import QueueEngineState, dispatcher_service
from app.services.reporting_service import reporting_service

logger = logging.getLogger("whatsapp_sender_engine.main")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [MainServer] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ==============================================================================
# Estado Global da Aplicação em Memória
# ==============================================================================

class AppState:
    """Mantém a sessão e o conjunto de dados da campanha carregada no Desktop."""

    def __init__(self):
        self.contacts: List[ContactRecord] = []
        self.ingestion_result: Optional[IngestionResult] = None
        self.last_uploaded_path: Optional[Path] = None
        self.campaign_template: str = ""
        self.attachment_path: Optional[str] = None
        self.active_dispatch_task: Optional[asyncio.Task] = None

    def clear(self):
        self.contacts.clear()
        self.ingestion_result = None
        self.last_uploaded_path = None
        self.campaign_template = ""
        self.attachment_path = None
        if self.active_dispatch_task and not self.active_dispatch_task.done():
            self.active_dispatch_task.cancel()
        self.active_dispatch_task = None


app_state = AppState()


# ==============================================================================
# Modelos de Requisição da API
# ==============================================================================

class RemapColumnsRequest(BaseModel):
    phone_column: Optional[str] = Field(None, description="Coluna selecionada para telefone")
    name_column: Optional[str] = Field(None, description="Coluna selecionada para nome")


class QueueStartRequest(BaseModel):
    template: Optional[str] = Field(None, description="Template de mensagem com Spintax e variáveis")
    contacts: Optional[List[Dict[str, Any]]] = Field(None, description="Lista opcional de contatos para envio")
    jitter_min: Optional[float] = Field(10.0, ge=1.0, le=60.0, description="Delay mínimo entre mensagens (segundos)")
    jitter_max: Optional[float] = Field(25.0, ge=2.0, le=120.0, description="Delay máximo entre mensagens (segundos)")
    batch_size: Optional[int] = Field(20, ge=5, le=100, description="Tamanho do lote para pausa")
    batch_pause_seconds: Optional[float] = Field(120.0, ge=5.0, le=600.0, description="Tempo de pausa por lote")
    attachment_path: Optional[str] = Field(None, description="Caminho do anexo a ser enviado")
    campaign_title: Optional[str] = Field("Campanha WhatsApp", description="Título descritivo da campanha")
    simulate_if_disconnected: Optional[bool] = Field(True, description="Executa simulação se o navegador não estiver conectado")
    enable_anti_ban_delays: Optional[bool] = Field(None, description="Habilita delays estocásticos e pausas de lote (True por padrão em sessão real)")


# ==============================================================================
# Ciclo de Vida da Aplicação (FastAPI Lifespan)
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialização e encerramento seguro dos serviços e recursos."""
    logger.info("Iniciando WhatsApp Sender Engine Desktop Server...")
    settings.ensure_directories()
    reporting_service.attach_to_dispatcher(dispatcher_service)
    yield
    logger.info("Encerrando WhatsApp Sender Engine Desktop Server...")
    try:
        if browser_service.is_connected():
            await browser_service.close()
    except Exception as ex:
        logger.debug("Aviso ao encerrar navegador no shutdown: %s", ex)


app = FastAPI(
    title="WhatsApp Sender Engine",
    description="Motor Desktop Local de Automação, Disparo Anti-Ban e Telemetria em Tempo Real",
    version="1.0.0",
    lifespan=lifespan,
)

# Configuração de CORS para permitir acesso local de qualquer interface
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# 1. Endpoints de Gestão e Ingestão de Contatos (R1)
# ==============================================================================

@app.post("/api/contacts/upload", summary="Upload de planilhas Excel/CSV")
async def upload_contacts_file(file: UploadFile = File(...)):
    """
    Recebe arquivo (.xlsx, .xls, .csv, .txt), executa ingestão em streaming,
    sanitização estrita E.164 brasileira e deduplicação determinística.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".txt"):
        raise HTTPException(
            status_code=400,
            detail=f"Formato '{suffix}' não suportado. Envie arquivos .xlsx, .csv ou .txt."
        )

    settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    temp_filename = f"upload_{int(time.time())}_{Path(file.filename).name}"
    temp_path = settings.UPLOADS_DIR / temp_filename

    try:
        # Salva o arquivo em buffer temporário
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Executa ingestão e higienização através do contact_service
        ingestion_result = contact_service.parse_file(temp_path)

        # Atualiza o estado da aplicação
        app_state.contacts = ingestion_result.valid_contacts
        app_state.ingestion_result = ingestion_result
        app_state.last_uploaded_path = temp_path

        # Inicializa o reporting service com o total de contatos válidos
        reporting_service.reset_campaign(
            total_contacts=len(ingestion_result.valid_contacts),
            campaign_title=f"Campanha {file.filename}",
        )
        reporting_service.log_system_event(
            "INFO",
            f"Arquivo '{file.filename}' carregado: {ingestion_result.total_rows} lidos, "
            f"{len(ingestion_result.valid_contacts)} válidos, {ingestion_result.duplicate_count} duplicatas."
        )

        return JSONResponse(content=ingestion_result.to_dict())

    except Exception as ex:
        logger.error("Erro durante processamento do upload: %s", ex, exc_info=True)
        reporting_service.log_system_event("ERROR", f"Falha no upload de '{file.filename}': {ex}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar planilha: {ex}")
    finally:
        # Remove arquivo temporário se desejado ou mantém em uploads
        pass


@app.post("/api/contacts/remap", summary="Reprocessa a última planilha com novo mapeamento de colunas")
async def remap_contacts_columns(request: RemapColumnsRequest):
    """
    Reprocessa o último arquivo enviado utilizando as colunas de Telefone e Nome
    escolhidas manualmente pelo usuário na interface.
    """
    if not app_state.last_uploaded_path or not app_state.last_uploaded_path.exists():
        raise HTTPException(
            status_code=400,
            detail="Nenhum arquivo recente carregado para remapeamento de colunas."
        )

    try:
        ingestion_result = contact_service.parse_file(
            app_state.last_uploaded_path,
            phone_col=request.phone_column or None,
            name_col=request.name_column or None,
        )
        app_state.contacts = ingestion_result.valid_contacts
        app_state.ingestion_result = ingestion_result

        reporting_service.reset_campaign(
            total_contacts=len(ingestion_result.valid_contacts),
            campaign_title=f"Campanha {app_state.last_uploaded_path.name}",
        )
        reporting_service.log_system_event(
            "INFO",
            f"Colunas remapeadas (Tel='{request.phone_column}', Nome='{request.name_column}'): "
            f"{len(ingestion_result.valid_contacts)} contatos válidos."
        )
        return JSONResponse(content=ingestion_result.to_dict())
    except Exception as ex:
        logger.error("Erro no remapeamento de colunas: %s", ex, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao remapear colunas: {ex}")


@app.post("/api/attachments/upload", summary="Upload de arquivo de mídia/anexo para a campanha")
async def upload_attachment_file(file: UploadFile = File(...)):
    """
    Salva um arquivo de mídia ou documento (.png, .jpg, .pdf, .mp4, etc.) no diretório
    de uploads para envio junto às mensagens da campanha.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo de anexo inválido.")

    settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    saved_filename = f"att_{int(time.time())}_{safe_name}"
    saved_path = settings.UPLOADS_DIR / saved_filename

    try:
        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        app_state.attachment_path = str(saved_path.resolve())
        reporting_service.log_system_event("INFO", f"Anexo carregado para campanha: {safe_name}")
        return {
            "success": True,
            "filename": safe_name,
            "attachment_path": str(saved_path.resolve()),
        }
    except Exception as ex:
        logger.error("Erro ao salvar anexo: %s", ex, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Falha ao salvar anexo: {ex}")


@app.post("/api/contacts/manual", summary="Ingestão de texto bruto colado")
async def manual_contacts_ingestion(request: ManualPasteRequest):
    """
    Processa lista de números ou pares Nome;Telefone colados na interface.
    """
    try:
        ingestion_result = contact_service.parse_manual(
            text=request.text,
            default_name_prefix=request.default_name_prefix or "Contato",
        )

        app_state.contacts = ingestion_result.valid_contacts
        app_state.ingestion_result = ingestion_result

        reporting_service.reset_campaign(
            total_contacts=len(ingestion_result.valid_contacts),
            campaign_title="Campanha Manual",
        )
        reporting_service.log_system_event(
            "INFO",
            f"Entrada manual processada: {ingestion_result.total_rows} linhas, "
            f"{len(ingestion_result.valid_contacts)} válidos."
        )

        return JSONResponse(content=ingestion_result.to_dict())

    except Exception as ex:
        logger.error("Erro na ingestão manual: %s", ex, exc_info=True)
        reporting_service.log_system_event("ERROR", f"Falha na ingestão manual: {ex}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar texto: {ex}")


@app.get("/api/contacts", summary="Consulta contatos carregados")
async def get_loaded_contacts(limit: int = Query(200, ge=1, le=1000)):
    """Retorna os contatos atualmente carregados e as métricas de aproveitamento."""
    contacts_slice = [c.to_dict() for c in app_state.contacts[:limit]]
    metrics = app_state.ingestion_result.to_dict() if app_state.ingestion_result else {
        "total_rows": len(app_state.contacts),
        "valid_count": len(app_state.contacts),
        "duplicate_count": 0,
        "invalid_count": 0,
        "efficiency_percentage": 100.0,
    }
    return {
        "total_loaded": len(app_state.contacts),
        "metrics": metrics,
        "contacts": contacts_slice,
    }


@app.delete("/api/contacts", summary="Limpa lista de contatos em memória")
async def clear_contacts():
    """Limpa a base de contatos carregada e reseta os contadores."""
    app_state.clear()
    reporting_service.reset_campaign(total_contacts=0, campaign_title="Campanha Vazia")
    return {"success": True, "message": "Lista de contatos limpa com sucesso."}


# ==============================================================================
# 2. Endpoints de Sessão WhatsApp Web (R2)
# ==============================================================================

@app.get("/api/session/status", summary="Estado da sessão WhatsApp Web")
async def get_session_status():
    """Retorna o estado da conexão: DESCONECTADO, AGUARDANDO_QR, SINCRONIZANDO, CONECTADO_PRONTO."""
    try:
        status_val = await browser_service.get_session_status()
        is_conn = browser_service.is_connected()
        return {
            "status": status_val.value,
            "status_raw": status_val.name,
            "is_connected": is_conn,
            "session_dir": str(browser_service.session_dir),
        }
    except Exception as ex:
        logger.error("Erro ao verificar status da sessão: %s", ex)
        return {
            "status": SessionStatus.DISCONNECTED.value,
            "status_raw": SessionStatus.DISCONNECTED.name,
            "is_connected": False,
            "error": str(ex),
        }


@app.get("/api/session/qr", summary="Obtenção do QR Code em Base64")
async def get_session_qr():
    """Retorna a captura do QR Code para leitura no aplicativo móvel."""
    try:
        qr_info = await browser_service.get_qr_code()
        current_st = browser_service.current_status
        return {
            "status": current_st.value,
            "has_qr": qr_info is not None,
            "qr_code": qr_info,
        }
    except Exception as ex:
        logger.error("Erro ao extrair QR Code: %s", ex)
        return {"status": SessionStatus.DISCONNECTED.value, "has_qr": False, "error": str(ex)}


@app.post("/api/session/start", summary="Inicia navegador WhatsApp Web")
async def start_browser_session():
    """Abre o navegador Chromium visível e navega até web.whatsapp.com."""
    try:
        reporting_service.log_system_event("INFO", "Iniciando sessão do WhatsApp Web...")
        await browser_service.start()
        status_val = await browser_service.get_session_status()
        reporting_service.log_system_event("INFO", f"Navegador aberto. Status da sessão: {status_val.value}")
        return {"success": True, "status": status_val.value}
    except Exception as ex:
        logger.error("Erro ao iniciar navegador: %s", ex)
        reporting_service.log_system_event("ERROR", f"Falha ao iniciar navegador: {ex}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(ex)})


@app.post("/api/session/close", summary="Encerra sessão do navegador")
async def close_browser_session():
    """Fecha o navegador com salvamento garantido do IndexedDB."""
    try:
        await browser_service.close()
        reporting_service.log_system_event("INFO", "Sessão do navegador encerrada com sucesso.")
        return {"success": True, "status": SessionStatus.DISCONNECTED.value}
    except Exception as ex:
        logger.error("Erro ao fechar navegador: %s", ex)
        return JSONResponse(status_code=500, content={"success": False, "error": str(ex)})


# ==============================================================================
# 3. Endpoints de Disparo e Fila Anti-Ban (R3)
# ==============================================================================

@app.post("/api/queue/start", summary="Inicia disparo em massa da campanha")
async def start_campaign_dispatch(request: Optional[QueueStartRequest] = None):
    """
    Inicia a fila assíncrona de disparo com simulação humana, jitter estocástico
    e pausas inteligentes por lote.
    """
    req = request or QueueStartRequest()

    # 1. Determina a lista de contatos a utilizar
    contacts_to_dispatch: List[ContactRecord] = []
    if req.contacts:
        for idx, item in enumerate(req.contacts, start=1):
            raw_phone = item.get("telefone") or item.get("Numero") or item.get("phone") or ""
            sanitized = contact_service.sanitize_phone(raw_phone)
            if sanitized.valid and sanitized.canonical:
                rec = ContactRecord(
                    id=str(idx),
                    raw_phone=str(raw_phone),
                    canonical_phone=sanitized.canonical,
                    name=item.get("nome") or item.get("name") or f"Contato {idx}",
                    variables=item.get("variables") or {},
                )
                contacts_to_dispatch.append(rec)
    elif app_state.contacts:
        contacts_to_dispatch = [c for c in app_state.contacts]

    if not contacts_to_dispatch:
        raise HTTPException(
            status_code=400,
            detail="Nenhum contato válido carregado para disparo. Faça upload de uma lista primeiro."
        )

    # 2. Valida estado da fila atual
    if dispatcher_service.state == QueueState.RUNNING:
        raise HTTPException(status_code=400, detail="A fila já está em execução.")

    template = req.template or app_state.campaign_template or "Olá {nome}, tudo bem?"
    app_state.campaign_template = template
    app_state.attachment_path = req.attachment_path

    # 3. Configura o ReportingService para a campanha
    reporting_service.reset_campaign(
        total_contacts=len(contacts_to_dispatch),
        campaign_title=req.campaign_title or "WhatsApp Bulk Campaign",
        jitter_min=req.jitter_min or 10.0,
        jitter_max=req.jitter_max or 25.0,
        batch_size=req.batch_size or 20,
        batch_pause_seconds=req.batch_pause_seconds or 120.0,
    )

    # 4. Configura o DispatcherService e sincroniza motor de Jitter Gaussiano
    dispatcher_service.contacts = contacts_to_dispatch
    dispatcher_service.message_template = template
    dispatcher_service.attachment_path = req.attachment_path
    dispatcher_service.reconfigure_jitter(
        min_delay_seconds=req.jitter_min or 10.0,
        max_delay_seconds=req.jitter_max or 25.0,
        batch_size=req.batch_size or 20,
        batch_pause_seconds=req.batch_pause_seconds or 120.0,
    )
    dispatcher_service.current_index = 0
    dispatcher_service.sent_count = 0
    dispatcher_service.failed_count = 0
    dispatcher_service.cancelled_count = 0
    dispatcher_service.results.clear()
    dispatcher_service.delays_recorded.clear()
    dispatcher_service.start_time = None
    dispatcher_service.end_time = None
    dispatcher_service.state = QueueState.IDLE
    dispatcher_service.engine_state = QueueEngineState.IDLE
    dispatcher_service._is_pause_requested = False
    dispatcher_service._is_abort_requested = False
    dispatcher_service._resume_event.set()

    # 5. Configura a função de envio e política Anti-Ban
    # Se o navegador estiver conectado, usa o browser_service real e ativa os delays Anti-Ban.
    # Caso contrário, e simulate_if_disconnected estiver ativo, simula o envio realista.
    is_connected = browser_service.is_connected()
    dispatcher_service.simulate_delays = (
        req.enable_anti_ban_delays
        if req.enable_anti_ban_delays is not None
        else is_connected
    )

    if is_connected:
        async def send_via_browser(contact: ContactRecord, message: str) -> SendMessageResult:
            return await browser_service.send_message(
                canonical_phone=contact.canonical_phone,
                text=message,
                attachment_path=dispatcher_service.attachment_path,
            )
        dispatcher_service.send_fn = send_via_browser
        reporting_service.log_system_event(
            "INFO",
            f"Modo de envio ativo: WhatsApp Web via Playwright (Anti-Ban Jitter: "
            f"{dispatcher_service.config.min_delay_seconds:.0f}s-{dispatcher_service.config.max_delay_seconds:.0f}s)."
        )
    else:
        if not req.simulate_if_disconnected:
            raise HTTPException(
                status_code=400,
                detail="Sessão do WhatsApp Web não está conectada. Conecte o QR Code antes de iniciar o disparo."
            )
        logger.info("Navegador não conectado. Executando envio em modo simulado realista.")
        reporting_service.log_system_event("INFO", "Navegador não conectado. Disparando em modo demonstração/simulação.")

        async def send_simulated(contact: ContactRecord, message: str) -> SendMessageResult:
            await asyncio.sleep(0.05)  # Delay não-bloqueante na event loop para simulação assíncrona fluida
            # Simulação: 95% sucesso, 5% erro de número sem WhatsApp para demonstrar auto-dismiss
            is_valid_sim = not contact.canonical_phone.endswith("9999")
            if is_valid_sim:
                return SendMessageResult(
                    canonical_phone=contact.canonical_phone,
                    success=True,
                    status=ContactStatus.SENT,
                    error_detail="Mensagem enviada com sucesso",
                    timestamp=datetime.now(),
                )
            return SendMessageResult(
                canonical_phone=contact.canonical_phone,
                success=False,
                status=ContactStatus.FAILED,
                error_code="MODAL_NUMERO_SEM_WHATSAPP",
                error_detail="Número não possui WhatsApp ativo (modal OK)",
                timestamp=datetime.now(),
            )
        dispatcher_service.send_fn = send_simulated

    # 6. Inicia a execução assíncrona em segundo plano
    app_state.active_dispatch_task = asyncio.create_task(dispatcher_service.run_queue_async())
    reporting_service.update_state(QueueState.RUNNING)

    return {
        "success": True,
        "message": "Fila de disparo iniciada com sucesso.",
        "total_contacts": len(contacts_to_dispatch),
        "state": QueueState.RUNNING.value,
    }


@app.post("/api/queue/pause", summary="Pausa a fila de disparo de forma atômica")
async def pause_campaign_dispatch():
    """Congela imediatamente o avanço da fila sem perder o progresso atual."""
    try:
        if dispatcher_service.state != QueueState.RUNNING:
            return JSONResponse(
                status_code=200,
                content={
                    "success": False,
                    "message": f"Fila não está em execução ({dispatcher_service.state.value}).",
                    "state": dispatcher_service.state.value,
                }
            )
        dispatcher_service.pause()
        reporting_service.update_state(QueueState.PAUSED)
        return {"success": True, "state": QueueState.PAUSED.value}
    except Exception as ex:
        logger.warning("Aviso ao pausar fila: %s", ex)
        return JSONResponse(
            status_code=200,
            content={"success": False, "message": str(ex), "state": dispatcher_service.state.value}
        )


@app.post("/api/queue/resume", summary="Retoma a fila a partir do próximo contato")
async def resume_campaign_dispatch():
    """Retoma o envio da fila a partir do contato pendente."""
    try:
        if dispatcher_service.state != QueueState.PAUSED:
            return JSONResponse(
                status_code=200,
                content={
                    "success": False,
                    "message": f"Fila não está pausada ({dispatcher_service.state.value}).",
                    "state": dispatcher_service.state.value,
                }
            )
        dispatcher_service.resume()
        reporting_service.update_state(QueueState.RUNNING)
        return {"success": True, "state": QueueState.RUNNING.value}
    except Exception as ex:
        logger.warning("Aviso ao retomar fila: %s", ex)
        return JSONResponse(
            status_code=200,
            content={"success": False, "message": str(ex), "state": dispatcher_service.state.value}
        )


@app.post("/api/queue/abort", summary="Aborta o disparo e cancela contatos pendentes")
async def abort_campaign_dispatch():
    """Interrompe a fila imediatamente e gera o relatório dos contatos processados."""
    try:
        dispatcher_service.abort()
        reporting_service.update_state(QueueState.ABORTED)
        return {"success": True, "state": QueueState.ABORTED.value}
    except Exception as ex:
        logger.error("Erro ao abortar fila: %s", ex)
        return JSONResponse(
            status_code=200,
            content={"success": False, "message": str(ex), "state": dispatcher_service.state.value}
        )


# ==============================================================================
# 4. Endpoints de Telemetria e Relatórios Executivos (R4)
# ==============================================================================

@app.get("/api/telemetry/snapshot", summary="Snapshot instantâneo de telemetria")
async def get_telemetry_snapshot():
    """Retorna métricas em tempo real: contadores, progresso, velocidade MPM e ETA."""
    return reporting_service.get_telemetry_dict()


@app.get("/api/telemetry/stream", summary="Streaming SSE em tempo real de telemetria e logs")
async def stream_telemetry():
    """
    Canal Server-Sent Events (SSE) transmitindo atualizações em tempo real
    para o painel de monitoramento da interface Desktop.
    """
    return StreamingResponse(
        reporting_service.sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/reports/logs", summary="Logs estruturados da campanha")
async def get_campaign_logs(limit: int = Query(100, ge=1, le=1000)):
    """Retorna o histórico de logs por contato e eventos do sistema."""
    return {
        "contact_logs": reporting_service.get_contact_logs(limit=limit),
        "system_logs": reporting_service.get_system_logs(limit=limit),
    }


@app.get("/api/reports/export/excel", summary="Download em 1 clique do relatório Excel (.xlsx)")
async def download_excel_report(title: Optional[str] = None):
    """
    Gera e faz download do relatório executivo em Excel (.xlsx) com:
    - Colunas obrigatórias: Numero, Status, DataHora, Detalhes.
    - Coluna de telefone formatada como Texto (@) para nunca corromper números de 13 dígitos.
    - Segunda aba 'Resumo_Executivo' com KPIs sumarizados de entrega.
    """
    try:
        campaign_title = title or reporting_service.campaign_title or "Campanha WhatsApp"
        target_path = reporting_service.export_current_campaign_excel()

        return FileResponse(
            path=str(target_path),
            filename=target_path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as ex:
        logger.error("Erro ao gerar relatório Excel: %s", ex, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao exportar Excel: {ex}")


@app.get("/api/reports/export/csv", summary="Download em 1 clique do relatório CSV (.csv)")
async def download_csv_report():
    """
    Gera e faz download do relatório CSV universal:
    - Codificação utf-8-sig (com BOM) para abertura direta no Microsoft Excel Windows.
    - Delimitador ';' e integridade total de acentos e caracteres especiais.
    - Colunas obrigatórias: Numero, Status, DataHora, Detalhes.
    """
    try:
        target_path = reporting_service.export_current_campaign_csv()

        return FileResponse(
            path=str(target_path),
            filename=target_path.name,
            media_type="text/csv; charset=utf-8-sig",
        )
    except Exception as ex:
        logger.error("Erro ao gerar relatório CSV: %s", ex, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao exportar CSV: {ex}")


# ==============================================================================
# 5. Montagem da Interface Estática Desktop
# ==============================================================================

# Rota principal para a aplicação desktop
@app.get("/", summary="Interface Desktop Principal")
async def serve_desktop_ui():
    index_file = settings.STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse({"message": "WhatsApp Sender Engine API Online. Frontend index.html não encontrado."})

# Monta arquivos estáticos de css e js diretamente e sob /static
if (settings.STATIC_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(settings.STATIC_DIR / "css")), name="css")
if (settings.STATIC_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(settings.STATIC_DIR / "js")), name="js")
if settings.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")


# ==============================================================================
# Entrypoint de Execução Direta
# ==============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
