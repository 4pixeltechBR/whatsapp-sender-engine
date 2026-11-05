"""
Live Telemetry, Monitoring Engine, and Executive Reporting Service for WhatsApp Sender Engine.
Alinhado rigorosamente com PROJECT.md, ORIGINAL_REQUEST.md e Milestone 4 (M4 - R4).

Recursos Implementados:
1. Central de Telemetria em Tempo Real:
   - Monitoramento dinâmico de contadores: Total, Enviados com Sucesso, Falhas, Pendentes e Cancelados.
   - Cálculo estocástico de ETA (tempo estimado restante) modelando:
     * Tempo médio por mensagem (média de jitter [min, max] + overhead biomecânico de digitação + latência de rede/DOM).
     * Quantidade de pausas inteligentes por lote restantes (N_pendentes // batch_size * batch_pause_seconds).
     * Congelamento automático em estado PAUSED e desativação em COMPLETED/ABORTED.
   - Taxa instantânea de envio (MPM - Mensagens Por Minuto) calculada via janela deslizante (sliding window)
     dos envios mais recentes e média histórica consolidada.
2. Histórico Estruturado de Logs por Contato:
   - Registro cronológico e detalhado de cada evento: (Numero, Nome, DataHora, Status, Detalhes, ErrorCode).
   - Terminal de eventos de sistema com níveis (INFO, WARNING, ERROR, SUCCESS).
3. Exportação Executiva em 1 Clique para Excel (.xlsx):
   - Arquivo salvo em `data/reports/` e formatado para download imediato.
   - Colunas obrigatórias: Numero, Status, DataHora, Detalhes.
   - Formatação obrigatória da coluna de telefone como Texto (`@`), garantindo que números
     como `5562994912937` nunca sejam corrompidos por notação científica (`5.56E+12`) no Microsoft Excel.
   - Segunda aba `Resumo_Executivo` com metadados da campanha, total de contatos, enviados,
     falhas, taxa de entrega (%) e velocidade média.
4. Exportação em 1 Clique para CSV (.csv):
   - Codificação `utf-8-sig` (com BOM UTF-8 `\\xef\\xbb\\xbf`) e delimitador `;` para compatibilidade
     nativa no Excel Windows sem janelas de conversão nem caracteres acentuados corrompidos.
   - Colunas obrigatórias: Numero, Status, DataHora, Detalhes.
5. Transmissão em Tempo Real via Server-Sent Events (SSE):
   - Gerador assíncrono para streaming contínuo de snapshots de telemetria e logs para a UI Desktop.
"""

import asyncio
from collections import deque
import csv
from datetime import datetime
from enum import Enum
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, AsyncGenerator, Callable, Deque, Dict, List, Optional, Set, Tuple, Union

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# Garante importações absolutas do projeto
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.core.constants import ContactStatus, QueueState
from app.models.schemas import ContactRecord, SendMessageResult, TelemetrySnapshot

logger = logging.getLogger("whatsapp_sender_engine.reporting_service")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [ReportingService] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class ReportingService:
    """
    Central de telemetria em tempo real, monitoramento de campanha
    e exportação executiva de relatórios (.xlsx e .csv).
    """

    MANDATORY_COLUMNS = ["Numero", "Status", "DataHora", "Detalhes"]

    def __init__(
        self,
        reports_dir: Optional[Union[Path, str]] = None,
        jitter_min: float = 10.0,
        jitter_max: float = 25.0,
        batch_size: int = 20,
        batch_pause_seconds: float = 120.0,
        typing_overhead_seconds: float = 3.5,
        browser_overhead_seconds: float = 2.0,
    ):
        self.reports_dir = Path(reports_dir or settings.REPORTS_DIR).resolve()
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        # Configurações de tempo para cálculo estocástico de ETA
        self.jitter_min = float(jitter_min)
        self.jitter_max = float(jitter_max)
        self.batch_size = max(1, int(batch_size))
        self.batch_pause_seconds = float(batch_pause_seconds)
        self.typing_overhead_seconds = float(typing_overhead_seconds)
        self.browser_overhead_seconds = float(browser_overhead_seconds)

        # Estado da Campanha e Contadores
        self.campaign_title: str = "WhatsApp Bulk Campaign"
        self.state: QueueState = QueueState.IDLE
        self.total_contacts: int = 0
        self.sent_count: int = 0
        self.failed_count: int = 0
        self.cancelled_count: int = 0
        self.current_contact: Optional[str] = None
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

        # Históricos Estruturados
        self._results: List[SendMessageResult] = []
        self._contact_logs: List[Dict[str, Any]] = []
        self._system_logs: List[Dict[str, Any]] = []

        # Janela deslizante para taxa de disparo (MPM)
        self._recent_timestamps: Deque[float] = deque(maxlen=25)

        # Assinantes SSE (Server-Sent Events)
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

        # Log inicial do serviço
        self.log_system_event("INFO", "ReportingService inicializado com sucesso.")

    # --------------------------------------------------------------------------
    # 1. Gestão de Estado e Ciclo de Vida da Campanha
    # --------------------------------------------------------------------------

    @property
    def pending_count(self) -> int:
        """Contatos pendentes na fila."""
        if self.state == QueueState.ABORTED:
            return 0
        processed = self.sent_count + self.failed_count + self.cancelled_count
        return max(0, self.total_contacts - processed)

    @property
    def processed_count(self) -> int:
        """Total de contatos já finalizados (sucesso + falha + cancelado)."""
        return self.sent_count + self.failed_count + self.cancelled_count

    @property
    def progress_percentage(self) -> float:
        """Percentual de progresso concluído (0.0 a 100.0)."""
        if self.total_contacts <= 0:
            return 0.0
        return round((self.processed_count / self.total_contacts) * 100.0, 1)

    def reset_campaign(
        self,
        total_contacts: int,
        campaign_title: str = "WhatsApp Bulk Campaign",
        jitter_min: Optional[float] = None,
        jitter_max: Optional[float] = None,
        batch_size: Optional[int] = None,
        batch_pause_seconds: Optional[float] = None,
    ) -> None:
        """Reinicializa a central de telemetria para uma nova campanha."""
        self.campaign_title = campaign_title
        self.state = QueueState.IDLE
        self.total_contacts = max(0, total_contacts)
        self.sent_count = 0
        self.failed_count = 0
        self.cancelled_count = 0
        self.current_contact = None
        self.start_time = None
        self.end_time = None

        if jitter_min is not None:
            self.jitter_min = float(jitter_min)
        if jitter_max is not None:
            self.jitter_max = float(jitter_max)
        if batch_size is not None:
            self.batch_size = max(1, int(batch_size))
        if batch_pause_seconds is not None:
            self.batch_pause_seconds = float(batch_pause_seconds)

        self._results.clear()
        self._contact_logs.clear()
        self._recent_timestamps.clear()

        self.log_system_event(
            "INFO",
            f"Nova campanha '{campaign_title}' configurada com {self.total_contacts} contatos."
        )
        self._broadcast_telemetry_update()

    def update_state(
        self,
        new_state: Union[QueueState, str],
        current_contact: Optional[str] = None,
    ) -> None:
        """Atualiza a máquina de estados e registra transições de ciclo de vida."""
        if isinstance(new_state, str):
            try:
                state_enum = QueueState(new_state)
            except ValueError:
                # Procura por valor correspondente
                state_enum = next((s for s in QueueState if s.value == new_state), QueueState.IDLE)
        else:
            state_enum = new_state

        old_state = self.state
        self.state = state_enum
        if current_contact is not None:
            self.current_contact = current_contact

        now = time.time()
        if self.state == QueueState.RUNNING and self.start_time is None:
            self.start_time = now

        if self.state in (QueueState.COMPLETED, QueueState.ABORTED):
            self.end_time = now
            self.current_contact = None

        if old_state != self.state:
            self.log_system_event("INFO", f"Estado da fila alterado: {old_state.value} -> {self.state.value}")
            self._broadcast_telemetry_update()

    # --------------------------------------------------------------------------
    # 2. Métricas e Modelagem Estocástica de ETA e MPM
    # --------------------------------------------------------------------------

    def calculate_mpm(self) -> float:
        """
        Calcula a taxa de velocidade em Mensagens Por Minuto (MPM):
        - Utiliza janela deslizante (últimos envios) para refletir velocidade instantânea.
        - Se poucos dados, utiliza a média histórica desde start_time.
        """
        if self.state == QueueState.IDLE or not self.start_time:
            return 0.0

        if len(self._recent_timestamps) >= 2:
            time_span_seconds = self._recent_timestamps[-1] - self._recent_timestamps[0]
            if time_span_seconds > 0.5:
                msgs = len(self._recent_timestamps) - 1
                return round((msgs / (time_span_seconds / 60.0)), 2)

        # Fallback para média global
        elapsed_sec = max(0.1, time.time() - self.start_time)
        total_completed = self.sent_count + self.failed_count
        if total_completed > 0:
            return round((total_completed / (elapsed_sec / 60.0)), 2)

        return 0.0

    def calculate_eta(self) -> float:
        """
        Cálculo estocástico do tempo estimado restante (ETA) em segundos:
        Fórmula:
          ETA = (N_pendentes * T_medio_msg) + (N_pausas_restantes * T_pausa_lote)
        Onde:
          - T_medio_msg = Media(jitter_min, jitter_max) + typing_overhead + browser_overhead
          - N_pausas_restantes = N_pendentes // batch_size
        """
        if self.state in (QueueState.COMPLETED, QueueState.ABORTED):
            return 0.0

        pending = self.pending_count
        if pending <= 0:
            return 0.0

        # Média estocástica por mensagem
        avg_jitter = (self.jitter_min + self.jitter_max) / 2.0
        avg_msg_time = avg_jitter + self.typing_overhead_seconds + self.browser_overhead_seconds

        # Quantidade de pausas em lote remanescentes
        remaining_batches = pending // self.batch_size if self.batch_size > 0 else 0
        total_batch_pause = remaining_batches * self.batch_pause_seconds

        eta_total = (pending * avg_msg_time) + total_batch_pause
        return round(max(0.0, eta_total), 1)

    def format_eta_string(self, eta_seconds: Optional[float] = None) -> str:
        """Formata os segundos restantes no formato legível HH:MM:SS ou badge de status."""
        if self.state == QueueState.PAUSED:
            return "PAUSADO"
        if self.state == QueueState.ABORTED:
            return "ABORTADO"
        if self.state == QueueState.COMPLETED:
            return "00:00:00"
        if self.state == QueueState.IDLE and self.total_contacts == 0:
            return "--:--:--"

        sec = self.calculate_eta() if eta_seconds is None else max(0.0, eta_seconds)
        total_secs = int(round(sec))
        hours = total_secs // 3600
        minutes = (total_secs % 3600) // 60
        seconds = total_secs % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def get_snapshot(self) -> TelemetrySnapshot:
        """Gera snapshot instantâneo compatível com o dataclass TelemetrySnapshot oficial."""
        return TelemetrySnapshot(
            state=self.state,
            total_contacts=self.total_contacts,
            sent_count=self.sent_count,
            failed_count=self.failed_count,
            pending_count=self.pending_count,
            eta_seconds=self.calculate_eta(),
            current_contact=self.current_contact,
            messages_per_minute=self.calculate_mpm(),
        )

    def get_telemetry_dict(self) -> Dict[str, Any]:
        """Dicionário enriquecido para consumo pela API Desktop e painel UI."""
        snap = self.get_snapshot()
        return {
            "state": snap.state.value if isinstance(snap.state, QueueState) else str(snap.state),
            "state_raw": snap.state.name if isinstance(snap.state, QueueState) else str(snap.state),
            "campaign_title": self.campaign_title,
            "total_contacts": snap.total_contacts,
            "sent_count": snap.sent_count,
            "failed_count": snap.failed_count,
            "pending_count": snap.pending_count,
            "cancelled_count": self.cancelled_count,
            "processed_count": self.processed_count,
            "progress_percentage": self.progress_percentage,
            "eta_seconds": snap.eta_seconds,
            "eta_formatted": self.format_eta_string(snap.eta_seconds),
            "current_contact": snap.current_contact,
            "messages_per_minute": snap.messages_per_minute,
            "timestamp": datetime.now().isoformat(),
        }

    # --------------------------------------------------------------------------
    # 3. Registro de Eventos e Logs por Contato
    # --------------------------------------------------------------------------

    def record_contact_start(self, canonical_phone: str, name: Optional[str] = None) -> None:
        """Registra o início do envio para um contato."""
        self.current_contact = canonical_phone
        self.log_system_event(
            "INFO",
            f"Processando contato: {name or 'Destinatário'} ({canonical_phone})..."
        )
        self._broadcast_telemetry_update()

    def record_result(
        self,
        result: SendMessageResult,
        name: Optional[str] = None,
    ) -> None:
        """
        Registra a conclusão do envio de um contato na fila:
        - Atualiza contadores de enviados, falhas ou cancelados.
        - Registra timestamp para cálculo deslizante de MPM.
        - Adiciona aos históricos estruturados.
        - Emite evento em tempo real via SSE.
        """
        now = time.time()
        self._recent_timestamps.append(now)
        self._results.append(result)

        if result.success or result.status == ContactStatus.SENT:
            self.sent_count += 1
            log_level = "SUCCESS"
        elif result.status == ContactStatus.CANCELLED:
            self.cancelled_count += 1
            log_level = "WARNING"
        else:
            self.failed_count += 1
            log_level = "ERROR"

        status_str = result.status.value if isinstance(result.status, Enum) else str(result.status)
        dt_str = result.timestamp.strftime("%Y-%m-%d %H:%M:%S") if result.timestamp else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        detail_str = result.error_detail or ("Mensagem enviada com sucesso" if result.success else "Falha no envio")

        contact_entry = {
            "Numero": str(result.canonical_phone),
            "Nome": name or "",
            "DataHora": dt_str,
            "Status": status_str,
            "Detalhes": detail_str,
            "ErrorCode": result.error_code,
            "Success": result.success,
        }
        self._contact_logs.append(contact_entry)

        # Emite log no terminal do sistema
        self.log_system_event(
            log_level,
            f"[{status_str}] {result.canonical_phone} — {detail_str}"
        )

        # Broadcast SSE específico de contato processado
        self.broadcast_event("contact_log", contact_entry)
        self._broadcast_telemetry_update()

    def log_system_event(
        self,
        level: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Registra log no terminal interno do sistema e dispara aos clientes SSE."""
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "datetime": datetime.now().isoformat(),
            "level": level.upper(),
            "message": message,
            "details": details or {},
        }
        self._system_logs.append(entry)
        if len(self._system_logs) > 500:
            self._system_logs = self._system_logs[-500:]

        self.broadcast_event("system_log", entry)

    def get_contact_logs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retorna os logs estruturados por contato da campanha atual."""
        if limit is not None and limit > 0:
            return self._contact_logs[-limit:]
        return list(self._contact_logs)

    def get_system_logs(self, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
        """Retorna os logs de sistema para exibição no terminal."""
        if limit is not None and limit > 0:
            return self._system_logs[-limit:]
        return list(self._system_logs)

    # --------------------------------------------------------------------------
    # 4. Exportação Profissional para Excel (.xlsx)
    # --------------------------------------------------------------------------

    @classmethod
    def export_excel(
        cls,
        results: Optional[List[Union[SendMessageResult, Dict[str, Any]]]] = None,
        file_path: Optional[Union[Path, str]] = None,
        campaign_title: str = "WhatsApp Bulk Campaign",
    ) -> Path:
        """
        Exporta relatório executivo em Excel (.xlsx):
        - Colunas obrigatórias: Numero, Status, DataHora, Detalhes.
        - Formatação estrita da coluna 'Numero' como Texto (@), blindando
          números de 13 dígitos como '5562994912937' contra notação científica do Excel.
        - Segunda aba 'Resumo_Executivo' com KPIs sumarizados de entrega.
        """
        target_path: Path
        if file_path is not None:
            target_path = Path(file_path).resolve()
        else:
            settings.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"relatorio_disparos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            target_path = settings.REPORTS_DIR / filename

        target_path.parent.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()

        # 1. Aba Primária: Relatorio_Disparos
        ws_data = wb.active
        ws_data.title = "Relatorio_Disparos"

        # Paleta de Cores e Estilos Executivos
        header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        border_thin = Border(
            left=Side(style="thin", color="E5E7EB"),
            right=Side(style="thin", color="E5E7EB"),
            top=Side(style="thin", color="E5E7EB"),
            bottom=Side(style="thin", color="E5E7EB"),
        )

        # Cabeçalho da tabela de dados
        ws_data.append(cls.MANDATORY_COLUMNS)
        for col_idx in range(1, len(cls.MANDATORY_COLUMNS) + 1):
            cell = ws_data.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        items = results or []
        sent_count = 0
        failed_count = 0
        cancelled_count = 0

        # Preenchimento de Linhas de Dados
        for row_idx, item in enumerate(items, start=2):
            if isinstance(item, SendMessageResult):
                phone_val = str(item.canonical_phone or "")
                status_val = item.status.value if isinstance(item.status, Enum) else str(item.status)
                dt_val = item.timestamp.strftime("%Y-%m-%d %H:%M:%S") if item.timestamp else ""
                detail_val = item.error_detail or ("Mensagem enviada com sucesso" if item.success else "Falha no envio")
                is_success = item.success
                is_cancelled = item.status == ContactStatus.CANCELLED
            elif isinstance(item, dict):
                phone_val = str(item.get("Numero") or item.get("canonical_phone") or item.get("telefone") or "")
                status_val = str(item.get("Status") or item.get("status") or "")
                dt_val = str(item.get("DataHora") or item.get("timestamp") or "")
                detail_val = str(item.get("Detalhes") or item.get("error_detail") or "")
                is_success = item.get("Success", status_val in ("ENVIADO", "SENT", "SUCESSO"))
                is_cancelled = status_val in ("CANCELADO", "CANCELLED", "ABORTADO")
            else:
                phone_val = str(getattr(item, "canonical_phone", ""))
                status_val = str(getattr(item, "status", ""))
                dt_val = str(getattr(item, "timestamp", ""))
                detail_val = str(getattr(item, "error_detail", ""))
                is_success = getattr(item, "success", False)
                is_cancelled = "CANCEL" in status_val.upper()

            if is_success:
                sent_count += 1
            elif is_cancelled:
                cancelled_count += 1
            else:
                failed_count += 1

            # Célula 1: Telefone com formatação obrigatória de Texto '@'
            c_phone = ws_data.cell(row=row_idx, column=1, value=phone_val)
            c_phone.number_format = "@"
            c_phone.alignment = Alignment(horizontal="center", vertical="center")
            c_phone.border = border_thin

            # Célula 2: Status
            c_status = ws_data.cell(row=row_idx, column=2, value=status_val)
            c_status.alignment = Alignment(horizontal="center", vertical="center")
            c_status.border = border_thin
            if is_success:
                c_status.font = Font(name="Calibri", size=10, bold=True, color="059669")
            elif is_cancelled:
                c_status.font = Font(name="Calibri", size=10, bold=True, color="D97706")
            else:
                c_status.font = Font(name="Calibri", size=10, bold=True, color="DC2626")

            # Célula 3: DataHora
            c_date = ws_data.cell(row=row_idx, column=3, value=dt_val)
            c_date.alignment = Alignment(horizontal="center", vertical="center")
            c_date.border = border_thin

            # Célula 4: Detalhes
            c_detail = ws_data.cell(row=row_idx, column=4, value=detail_val)
            c_detail.alignment = Alignment(horizontal="left", vertical="center")
            c_detail.border = border_thin

        # Ajuste de largura das colunas da aba de dados
        col_widths = {"A": 20, "B": 16, "C": 22, "D": 45}
        for col_letter, width in col_widths.items():
            ws_data.column_dimensions[col_letter].width = width

        # 2. Aba Secundária: Resumo_Executivo
        ws_sum = wb.create_sheet(title="Resumo_Executivo")
        total = len(items)
        success_rate = round((sent_count / total * 100.0), 1) if total > 0 else 0.0

        summary_data = [
            ["Métrica da Campanha", "Valor"],
            ["Título da Campanha", campaign_title],
            ["Total de Contatos na Fila", total],
            ["Enviados com Sucesso", sent_count],
            ["Falhas / Sem WhatsApp", failed_count],
            ["Cancelados / Abortados", cancelled_count],
            ["Taxa de Entrega (%)", f"{success_rate}%"],
            ["Data do Relatório", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ]

        for r in summary_data:
            ws_sum.append(r)

        for col_num in (1, 2):
            header_cell = ws_sum.cell(row=1, column=col_num)
            header_cell.fill = header_fill
            header_cell.font = header_font
            header_cell.alignment = Alignment(horizontal="left", vertical="center")

        for r_idx in range(2, len(summary_data) + 1):
            ws_sum.cell(row=r_idx, column=1).font = Font(name="Calibri", size=10, bold=True)
            ws_sum.cell(row=r_idx, column=1).border = border_thin
            ws_sum.cell(row=r_idx, column=2).border = border_thin

        ws_sum.column_dimensions["A"].width = 28
        ws_sum.column_dimensions["B"].width = 32

        wb.save(target_path)
        wb.close()
        logger.info("Relatório Excel exportado com sucesso em: %s", target_path)
        return target_path

    # --------------------------------------------------------------------------
    # 5. Exportação Universal para CSV (.csv) com BOM e ';'
    # --------------------------------------------------------------------------

    @classmethod
    def export_csv(
        cls,
        results: Optional[List[Union[SendMessageResult, Dict[str, Any]]]] = None,
        file_path: Optional[Union[Path, str]] = None,
    ) -> Path:
        """
        Exporta relatório em CSV universal para Windows/Excel:
        - Codificação 'utf-8-sig' (inicia com BOM UTF-8: \\xef\\xbb\\xbf).
        - Delimitador ';' (ponto-e-vírgula).
        - Colunas obrigatórias: Numero, Status, DataHora, Detalhes.
        - Preserva integralmente acentuação e caracteres especiais.
        """
        target_path: Path
        if file_path is not None:
            target_path = Path(file_path).resolve()
        else:
            settings.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"relatorio_disparos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            target_path = settings.REPORTS_DIR / filename

        target_path.parent.mkdir(parents=True, exist_ok=True)

        items = results or []

        with open(target_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(cls.MANDATORY_COLUMNS)

            for item in items:
                if isinstance(item, SendMessageResult):
                    phone_val = str(item.canonical_phone or "")
                    status_val = item.status.value if isinstance(item.status, Enum) else str(item.status)
                    dt_val = item.timestamp.strftime("%Y-%m-%d %H:%M:%S") if item.timestamp else ""
                    detail_val = item.error_detail or ("Mensagem enviada com sucesso" if item.success else "Falha no envio")
                elif isinstance(item, dict):
                    phone_val = str(item.get("Numero") or item.get("canonical_phone") or item.get("telefone") or "")
                    status_val = str(item.get("Status") or item.get("status") or "")
                    dt_val = str(item.get("DataHora") or item.get("timestamp") or "")
                    detail_val = str(item.get("Detalhes") or item.get("error_detail") or "")
                else:
                    phone_val = str(getattr(item, "canonical_phone", ""))
                    status_val = str(getattr(item, "status", ""))
                    dt_val = str(getattr(item, "timestamp", ""))
                    detail_val = str(getattr(item, "error_detail", ""))

                writer.writerow([phone_val, status_val, dt_val, detail_val])

        logger.info("Relatório CSV exportado com sucesso em: %s", target_path)
        return target_path

    # Métodos de instância convenientes que delegam aos métodos de classe
    def export_current_campaign_excel(self, file_path: Optional[Union[Path, str]] = None) -> Path:
        """Exporta os resultados da campanha em andamento/concluída para Excel."""
        return self.export_excel(
            results=self._results,
            file_path=file_path,
            campaign_title=self.campaign_title,
        )

    def export_current_campaign_csv(self, file_path: Optional[Union[Path, str]] = None) -> Path:
        """Exporta os resultados da campanha em andamento/concluída para CSV."""
        return self.export_csv(
            results=self._results,
            file_path=file_path,
        )

    # --------------------------------------------------------------------------
    # 6. Streaming SSE (Server-Sent Events)
    # --------------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        """Cria e registra uma fila de mensagens para um novo cliente SSE."""
        q = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a fila de mensagens de um cliente SSE desconectado."""
        self._subscribers.discard(q)

    def broadcast_event(self, event_type: str, data: Any) -> None:
        """Envia mensagem para todos os clientes SSE conectados de forma não-bloqueante."""
        payload = {"event": event_type, "data": data}
        for q in list(self._subscribers):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(payload)
            except Exception as ex:
                logger.debug("Erro ao enviar evento SSE para fila: %s", ex)

    def _broadcast_telemetry_update(self) -> None:
        """Atalho para transmitir o snapshot mais recente para os assinantes SSE."""
        self.broadcast_event("telemetry", self.get_telemetry_dict())

    async def sse_stream(self) -> AsyncGenerator[str, None]:
        """
        Gerador assíncrono que transmite Server-Sent Events (SSE) contínuos:
        - Envia snapshot imediato no momento da conexão.
        - Emite eventos sob demanda (telemetria, logs de contatos e logs de sistema).
        - Envia heartbeat (comentário SSE) periódico para prevenir desconexão de proxies.
        """
        q = self.subscribe()
        try:
            # 1. Envia snapshot inicial imediatamente
            initial_data = self.get_telemetry_dict()
            yield f"event: telemetry\ndata: {json.dumps(initial_data, ensure_ascii=False)}\n\n"

            # 2. Loop de consumo da fila SSE
            while True:
                try:
                    # Aguarda nova mensagem com timeout para envio de heartbeat
                    msg = await asyncio.wait_for(q.get(), timeout=5.0)
                    evt_type = msg.get("event", "message")
                    data_obj = msg.get("data", {})
                    data_str = json.dumps(data_obj, ensure_ascii=False)
                    yield f"event: {evt_type}\ndata: {data_str}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat keep-alive para SSE
                    snap = self.get_telemetry_dict()
                    yield f"event: telemetry\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n"
        finally:
            self.unsubscribe(q)

    # --------------------------------------------------------------------------
    # 7. Integração Automática com DispatcherService
    # --------------------------------------------------------------------------

    def attach_to_dispatcher(self, dispatcher: Any) -> None:
        """
        Conecta os callbacks de ciclo de vida do DispatcherService ao ReportingService.
        """
        if not hasattr(dispatcher, "add_listener"):
            return

        dispatcher.add_listener("STATE_CHANGED", self._on_dispatcher_state_changed)
        dispatcher.add_listener("CONTACT_STARTED", self._on_dispatcher_contact_started)
        dispatcher.add_listener("CONTACT_COMPLETED", self._on_dispatcher_contact_completed)
        dispatcher.add_listener("BATCH_PAUSE_START", self._on_dispatcher_batch_pause_start)
        dispatcher.add_listener("BATCH_PAUSE_END", self._on_dispatcher_batch_pause_end)
        dispatcher.add_listener("QUEUE_ABORTED", self._on_dispatcher_queue_aborted)
        dispatcher.add_listener("QUEUE_COMPLETED", self._on_dispatcher_queue_completed)
        logger.info("ReportingService acoplado com sucesso aos eventos do DispatcherService.")

    def _on_dispatcher_state_changed(self, new_state: Any) -> None:
        if isinstance(new_state, (tuple, list)) and len(new_state) == 2:
            target = new_state[1]
        else:
            target = new_state
        state_val = getattr(target, "value", str(target))
        self.update_state(state_val)

    def _on_dispatcher_contact_started(self, contact_data: Any) -> None:
        if isinstance(contact_data, (tuple, list)) and len(contact_data) >= 1:
            contact = contact_data[0]
        else:
            contact = contact_data
        phone = getattr(contact, "canonical_phone", "")
        name = getattr(contact, "name", "")
        self.record_contact_start(phone, name)

    def _on_dispatcher_contact_completed(self, data: Any) -> None:
        if isinstance(data, (tuple, list)) and len(data) == 2:
            contact, result = data
            name = getattr(contact, "name", "")
            self.record_result(result, name=name)
        elif isinstance(data, SendMessageResult):
            self.record_result(data)
        else:
            self.record_result(data)

    def _on_dispatcher_batch_pause_start(self, duration_sec: Any) -> None:
        self.log_system_event(
            "WARNING",
            f"Pausa inteligente de lote ativada: repouso de {duration_sec}s para proteção anti-ban..."
        )

    def _on_dispatcher_batch_pause_end(self, _: Any = None) -> None:
        self.log_system_event(
            "INFO",
            "Pausa de lote finalizada com sucesso. Retomando envio da fila."
        )

    def _on_dispatcher_queue_aborted(self, results: Any = None) -> None:
        self.update_state(QueueState.ABORTED)
        if results and isinstance(results, list):
            for item in results:
                if getattr(item, "status", None) == ContactStatus.CANCELLED:
                    if item not in self._results:
                        self.record_result(item)
        self.log_system_event("WARNING", "Campanha abortada pelo operador.")

    def _on_dispatcher_queue_completed(self, _: Any = None) -> None:
        self.update_state(QueueState.COMPLETED)
        self.log_system_event("SUCCESS", "Todos os contatos da fila foram processados!")


# Singleton padrão exportado para toda a aplicação
reporting_service = ReportingService()

__all__ = [
    "ReportingService",
    "reporting_service",
]
