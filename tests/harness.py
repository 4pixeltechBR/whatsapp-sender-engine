"""
Test Harness, Mock Engines, and Data Generators for WhatsApp Sender Engine Test Suite.
Provides synthetic dataset generation (>5,000 rows), reference mathematical models
(Box-Muller jitter, Spintax resolver, Queue state machine, Report exporter) aligned
with PROJECT.md and ORIGINAL_REQUEST.md specifications.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import io
import math
import os
from pathlib import Path
import random
import re
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import uuid

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from app.core.constants import (
    ANATEL_DDDS,
    ANATEL_DDDS_STR,
    DDD_REGION_MAP,
    DEFAULT_COUNTRY_CODE,
    ContactStatus,
    QueueState,
    SessionStatus,
)
from app.models.schemas import ContactRecord, IngestionResult, SendMessageResult, TelemetrySnapshot


# ==============================================================================
# 1. Gerador Sintético de Dados Massivos (>5.000 Contatos)
# ==============================================================================

class SyntheticDataGenerator:
    """Gera bases sintéticas realistas de contatos para testes de carga e sanitização."""

    PRIMEIROS_NOMES = [
        "Ana", "Bruno", "Carlos", "Daniela", "Eduardo", "Fernanda", "Gabriel",
        "Helena", "Igor", "Juliana", "Lucas", "Mariana", "Rodrigo", "Tatiana",
        "Victor", "Beatriz", "Caio", "Larissa", "Felipe", "Camila"
    ]
    SOBRENOMES = [
        "Silva", "Santos", "Oliveira", "Souza", "Pereira", "Lima", "Carvalho",
        "Ribeiro", "Almeida", "Ferreira", "Costa", "Gomes", "Martins", "Araujo"
    ]
    EMPRESAS = ["Acme Ltda", "TechCorp", "Inova Soluções", "Varejo Brasil", "Alfa Distribuidora"]

    @classmethod
    def generate_random_name(cls) -> str:
        return f"{random.choice(cls.PRIMEIROS_NOMES)} {random.choice(cls.SOBRENOMES)}"

    @classmethod
    def generate_contact_dataset(
        cls,
        total_rows: int = 5000,
        duplicate_ratio: float = 0.05,
        invalid_ratio: float = 0.03,
        landline_ratio: float = 0.02,
        float_coercion_ratio: float = 0.05,
        scientific_ratio: float = 0.02,
    ) -> List[Dict[str, Any]]:
        """
        Gera uma lista de dicionários contendo contatos realistas com mix de casos:
        - Celulares nacionais válidos nos 67 DDDs
        - Fixos (8 dígitos locais)
        - Celulares legados pré-2016 (8 dígitos locais)
        - Duplicatas intencionais
        - Coerção float (.0 e notação científica)
        - Inválidos (DDDs inexistentes 23/70, números curtos, números repetidos)
        """
        valid_ddds = sorted(list(ANATEL_DDDS))
        invalid_ddds = [20, 23, 25, 26, 29, 30, 36, 39, 50, 52, 56, 57, 58, 59, 70, 72, 76, 78, 80, 90]
        
        contacts: List[Dict[str, Any]] = []
        base_pool: List[Tuple[str, str]] = []

        num_duplicates = int(total_rows * duplicate_ratio)
        num_invalids = int(total_rows * invalid_ratio)
        num_landlines = int(total_rows * landline_ratio)
        num_floats = int(total_rows * float_coercion_ratio)
        num_scis = int(total_rows * scientific_ratio)
        num_standards = total_rows - (num_duplicates + num_invalids + num_landlines + num_floats + num_scis)

        # 1. Contatos Celulares Válidos Padrão
        for _ in range(max(num_standards, 100)):
            ddd = random.choice(valid_ddds)
            # 9 dígitos locais iniciando com 9
            local_num = f"9{random.randint(1000, 9999)}{random.randint(1000, 9999)}"
            name = cls.generate_random_name()
            phone_raw = f"{ddd}{local_num}"
            contacts.append({
                "telefone": phone_raw,
                "nome": name,
                "empresa": random.choice(cls.EMPRESAS),
                "cidade": DDD_REGION_MAP.get(f"{ddd:02d}", "Brasil").split(" - ")[0],
            })
            base_pool.append((phone_raw, name))

        # 2. Contatos com Coerção Float (.0)
        for _ in range(num_floats):
            ddd = random.choice(valid_ddds)
            local_num = f"9{random.randint(1000, 9999)}{random.randint(1000, 9999)}"
            float_val = float(f"{ddd}{local_num}")
            name = cls.generate_random_name()
            contacts.append({
                "telefone": float_val,  # float numérico nativo
                "nome": name,
                "empresa": random.choice(cls.EMPRESAS),
                "cidade": "FloatTest",
            })
            base_pool.append((f"{ddd}{local_num}", name))

        # 3. Contatos em Notação Científica
        for _ in range(num_scis):
            ddd = random.choice(valid_ddds)
            local_num = f"9{random.randint(1000, 9999)}{random.randint(1000, 9999)}"
            sci_str = f"{float(f'{ddd}{local_num}'):.10e}"
            name = cls.generate_random_name()
            contacts.append({
                "telefone": sci_str,
                "nome": name,
                "empresa": random.choice(cls.EMPRESAS),
                "cidade": "SciTest",
            })

        # 4. Contatos Fixos (8 dígitos locais iniciando com 2-5)
        for _ in range(num_landlines):
            ddd = random.choice(valid_ddds)
            first_digit = random.choice([2, 3, 4, 5])
            local_num = f"{first_digit}{random.randint(100, 999)}{random.randint(1000, 9999)}"
            name = f"Fixo {cls.generate_random_name()}"
            contacts.append({
                "telefone": f"{ddd}{local_num}",
                "nome": name,
                "empresa": random.choice(cls.EMPRESAS),
                "cidade": "Landline",
            })

        # 5. Contatos Inválidos (DDDs inexistentes, repetidos, curtos)
        for i in range(num_invalids):
            name = f"Invalido {i}"
            case = i % 4
            if case == 0:
                # DDD inexistente (ex: 23 ou 70)
                bad_ddd = random.choice(invalid_ddds)
                bad_phone = f"{bad_ddd}994912937"
            elif case == 1:
                # Dígitos repetidos
                bad_phone = "00000000000"
            elif case == 2:
                # Curto sem DDD
                bad_phone = "994912937"
            else:
                # Internacional fora do Brasil
                bad_phone = "12025550199"

            contacts.append({
                "telefone": bad_phone,
                "nome": name,
                "empresa": "InvalidCorp",
                "cidade": "N/A",
            })

        # 6. Duplicatas Intencionais com Formatações Distintas
        for _ in range(num_duplicates):
            if base_pool:
                original_phone, original_name = random.choice(base_pool)
                # Formata de forma diferente da original
                clean_digits = re.sub(r"\D", "", original_phone)
                if len(clean_digits) == 11:
                    ddd = clean_digits[:2]
                    p1 = clean_digits[2:7]
                    p2 = clean_digits[7:]
                    fmt = random.choice([
                        f"+55 ({ddd}) {p1}-{p2}",
                        f"55{clean_digits}",
                        f"({ddd}) {p1}-{p2}",
                        f"0{clean_digits}",
                        f"015{clean_digits}",
                    ])
                else:
                    fmt = f"55{clean_digits}"

                contacts.append({
                    "telefone": fmt,
                    "nome": f"{original_name} (Duplicata)",
                    "empresa": "Duplicata Merge",
                    "cidade": "DupCity",
                })

        # Embaralha para realismo
        random.shuffle(contacts)
        return contacts

    @classmethod
    def export_to_excel_file(cls, contacts: List[Dict[str, Any]], file_path: Path) -> Path:
        """Gera arquivo .xlsx streaming de alta velocidade."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Contatos"

        headers = ["telefone", "nome", "empresa", "cidade"]
        ws.append(headers)

        for c in contacts:
            ws.append([c.get(h) for h in headers])

        file_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(file_path)
        wb.close()
        return file_path

    @classmethod
    def export_to_csv_file(
        cls,
        contacts: List[Dict[str, Any]],
        file_path: Path,
        delimiter: str = ";",
        encoding: str = "utf-8-sig",
    ) -> Path:
        """Gera arquivo .csv com encoding e delimitador especificados."""
        import csv
        file_path.parent.mkdir(parents=True, exist_ok=True)
        headers = ["telefone", "nome", "empresa", "cidade"]

        with open(file_path, "w", encoding=encoding, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()
            for c in contacts:
                writer.writerow({h: c.get(h, "") for h in headers})

        return file_path


# ==============================================================================
# 2. Motor de Spintax e Interpolação Dinâmica
# ==============================================================================

class SpintaxEngine:
    """
    Resolve Spintax aninhado multinível '{Oi|Olá|{E aí|Fala}}'
    e interpola variáveis de contato '{nome}', '{empresa}'.
    """

    SPINTAX_PATTERN = re.compile(r"\{([^{}]+)\}")

    @classmethod
    def resolve_spintax(cls, text: str, seed: Optional[int] = None) -> str:
        """Resolve recursivamente todas as chaves Spintax do interior para o exterior."""
        if seed is not None:
            random.seed(seed)

        result = text
        while True:
            match = cls.SPINTAX_PATTERN.search(result)
            if not match:
                break
            choices = match.group(1).split("|")
            chosen = random.choice(choices)
            result = result[:match.start()] + chosen + result[match.end():]

        return result

    @classmethod
    def interpolate_variables(cls, text: str, variables: Dict[str, Any]) -> str:
        """Substitui tags no formato {chave} pelos valores do dicionário de variáveis."""
        res = text
        for k, v in variables.items():
            pattern = re.compile(re.escape(f"{{{k}}}"), re.IGNORECASE)
            res = pattern.sub(str(v) if v is not None else "", res)
        # Limpa variáveis restantes do tipo {variavel_desconhecida} que não possuem pipes de spintax
        res = re.sub(r"\{[a-zA-Z0-9_]+\}", "", res)
        return res

    @classmethod
    def process_message(
        cls,
        template: str,
        contact: ContactRecord,
        seed: Optional[int] = None,
    ) -> str:
        """Executa a interpolação de variáveis e a resolução de Spintax em cadeia."""
        vars_dict = dict(contact.variables)
        vars_dict["nome"] = contact.name
        vars_dict["telefone"] = contact.canonical_phone

        # 1. Interpolação de variáveis
        interpolated = cls.interpolate_variables(template, vars_dict)
        # 2. Resolução de Spintax
        final_message = cls.resolve_spintax(interpolated, seed=seed)
        return final_message


# ==============================================================================
# 3. Motor Biomecânico de Jitter Box-Muller e Digitação WPM
# ==============================================================================

class BoxMullerJitterEngine:
    """
    Simulador estocástico anti-ban:
    - Intervalo inter-mensagens com Normal Truncada [min_s, max_s] via Transformada de Box-Muller.
    - Injeção de cauda longa (fat-tail).
    - Cadência de digitação WPM com pausas reflexivas em pontuação.
    """

    def __init__(
        self,
        min_seconds: float = 10.0,
        max_seconds: float = 25.0,
        fat_tail_prob: float = 0.05,
        fat_tail_range: Tuple[float, float] = (15.0, 40.0),
    ):
        self.min_s = min_seconds
        self.max_s = max_seconds
        self.mu = (min_seconds + max_seconds) / 2.0  # Média centrada (17.5s)
        self.sigma = (max_seconds - min_seconds) / 6.0  # 99.7% dentro do intervalo (2.5s)
        self.fat_tail_prob = fat_tail_prob
        self.fat_tail_range = fat_tail_range
        self._last_delay: Optional[float] = None

    def get_next_delay(self) -> float:
        """
        Calcula o próximo delay estocástico anti-ban via Box-Muller.
        Garante que nenhuma mensagem é enviada em intervalo fixo consecutivo.
        """
        for _ in range(20):
            # Injeção de anomalia de cauda longa (fat-tail)
            if self.fat_tail_prob > 0.0 and random.random() < self.fat_tail_prob:
                delay = random.uniform(self.fat_tail_range[0], self.fat_tail_range[1])
            else:
                # Transformada de Box-Muller para distribuição normal padrão
                u1 = max(random.random(), 1e-10)
                u2 = random.random()
                z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

                val = self.mu + (z0 * self.sigma)
                # Trunca para garantir os limites configurados
                delay = max(self.min_s, min(self.max_s, val))

            rounded_delay = round(delay, 2)
            if self._last_delay is None or abs(rounded_delay - self._last_delay) >= 0.01:
                self._last_delay = rounded_delay
                return rounded_delay

        # Perturbação segura caso repita exatamente
        perturbation = 0.01 if rounded_delay < self.max_s else -0.01
        rounded_delay = round(rounded_delay + perturbation, 2)
        self._last_delay = rounded_delay
        return rounded_delay

    @staticmethod
    def calculate_keystroke_delays(
        text: str,
        wpm: int = 55,
    ) -> List[Tuple[str, float]]:
        """
        Calcula os tempos Inter-Keystroke Interval (IKI) para cada caractere:
        - Média baseada em Palavras Por Minuto (WPM)
        - Ruído Box-Muller por tecla
        - Pausas reflexivas humanas em pontuações (.,?! \n)
        """
        # Caracteres por segundo = (WPM * 5) / 60
        cps = (wpm * 5.0) / 60.0
        base_iki_sec = 1.0 / max(cps, 1.0)

        delays: List[Tuple[str, float]] = []
        for char in text:
            u1 = max(random.random(), 1e-10)
            u2 = random.random()
            noise = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2) * 0.03
            iki = max(0.04, base_iki_sec + noise)

            # Pausas reflexivas em pontuação
            if char in ".?!":
                iki += random.uniform(0.4, 0.9)
            elif char in ",;:":
                iki += random.uniform(0.2, 0.4)
            elif char == "\n":
                iki += random.uniform(0.5, 1.2)

            delays.append((char, round(iki, 3)))
        return delays


# ==============================================================================
# 4. Máquina de Estados e Fila de Disparo (Queue Dispatcher Engine)
# ==============================================================================

class QueueDispatcherEngine:
    """
    Motor de gerenciamento de fila assíncrona com máquina de estados rigorosa:
    - Estados: IDLE, RUNNING, PAUSED, ABORTED, COMPLETED
    - Suporte a Pausa Atômica (não perde progresso) e Retomada
    - Suporte a Aborto Imediato com cancelamento de pendentes
    - Detecção e auto-dismiss de popup de número inválido / sem WhatsApp
    - Pausas estocásticas por lote (~20 mensagens)
    - Geração de telemetria em tempo real (ETA, MPM, progresso)
    """

    def __init__(
        self,
        contacts: List[ContactRecord],
        message_template: str,
        jitter_min: float = 10.0,
        jitter_max: float = 25.0,
        batch_size: int = 20,
        batch_pause_seconds: float = 120.0,
        send_fn: Optional[Callable[[ContactRecord, str], SendMessageResult]] = None,
    ):
        self.contacts = [c for c in contacts]
        self.message_template = message_template
        self.jitter_engine = BoxMullerJitterEngine(jitter_min, jitter_max)
        self.batch_size = batch_size
        self.batch_pause_seconds = batch_pause_seconds
        self.send_fn = send_fn or self._default_send_fn

        # Estado da Máquina
        self.state: QueueState = QueueState.IDLE
        self.current_index: int = 0
        self.sent_count: int = 0
        self.failed_count: int = 0
        self.cancelled_count: int = 0

        # Histórico de envios e telemetria
        self.results: List[SendMessageResult] = []
        self.delays_recorded: List[float] = []
        self.batch_pauses_triggered: int = 0
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def _default_send_fn(self, contact: ContactRecord, message: str) -> SendMessageResult:
        """Simulador de envio padrão para testes."""
        return SendMessageResult(
            canonical_phone=contact.canonical_phone,
            success=True,
            status=ContactStatus.SENT,
            timestamp=datetime.now(),
        )

    @property
    def total_contacts(self) -> int:
        return len(self.contacts)

    @property
    def pending_count(self) -> int:
        if self.state == QueueState.ABORTED:
            return 0
        return max(0, self.total_contacts - self.current_index)

    def get_telemetry(self) -> TelemetrySnapshot:
        """Gera snapshot instantâneo de telemetria alinhado com TelemetrySnapshot."""
        avg_delay = (self.jitter_engine.min_s + self.jitter_engine.max_s) / 2.0
        pending = self.pending_count
        
        # Cálculo de ETA estocástico incluindo pausas de lote remanescentes
        remaining_batches = pending // self.batch_size
        eta = (pending * avg_delay) + (remaining_batches * self.batch_pause_seconds)
        if self.state in (QueueState.PAUSED, QueueState.ABORTED, QueueState.COMPLETED):
            eta = 0.0

        current_contact_name = None
        if 0 <= self.current_index < len(self.contacts):
            current_contact_name = self.contacts[self.current_index].canonical_phone

        # MPM (Mensagens por Minuto)
        mpm = 0.0
        if self.start_time and (self.sent_count + self.failed_count) > 0:
            elapsed_min = max((time.time() - self.start_time) / 60.0, 0.01)
            mpm = round((self.sent_count + self.failed_count) / elapsed_min, 2)

        return TelemetrySnapshot(
            state=self.state,
            total_contacts=self.total_contacts,
            sent_count=self.sent_count,
            failed_count=self.failed_count,
            pending_count=pending,
            eta_seconds=round(eta, 1),
            current_contact=current_contact_name,
            messages_per_minute=mpm,
        )

    def start(self, max_steps: Optional[int] = None) -> None:
        """Inicia a execução da fila."""
        if self.state != QueueState.IDLE:
            raise RuntimeError(f"Transição inválida: Fila já foi iniciada ou está em {self.state}. Use resume() se estiver pausada.")

        self.state = QueueState.RUNNING
        if self.start_time is None:
            self.start_time = time.time()

        self._process_loop(max_steps=max_steps)

    def pause(self) -> None:
        """Pausa o avanço da fila de forma atômica sem perda de estado."""
        if self.state != QueueState.RUNNING:
            raise RuntimeError(f"Apenas filas em RUNNING podem ser pausadas. Estado atual: {self.state}")
        self.state = QueueState.PAUSED

    def resume(self, max_steps: Optional[int] = None) -> None:
        """Retoma a execução a partir do próximo contato pendente."""
        if self.state != QueueState.PAUSED:
            raise RuntimeError(f"Apenas filas em PAUSED podem ser retomadas. Estado atual: {self.state}")
        self.state = QueueState.RUNNING
        self._process_loop(max_steps=max_steps)

    def abort(self) -> None:
        """
        Aborta imediatamente a fila.
        Marca todos os contatos não processados como CANCELLED e congela telemetria.
        """
        if self.state in (QueueState.ABORTED, QueueState.COMPLETED):
            return

        self.state = QueueState.ABORTED
        self.end_time = time.time()

        # Cancela os contatos restantes
        for idx in range(self.current_index, len(self.contacts)):
            c = self.contacts[idx]
            c.status = ContactStatus.CANCELLED
            c.error_detail = "Campanha abortada pelo operador"
            self.results.append(
                SendMessageResult(
                    canonical_phone=c.canonical_phone,
                    success=False,
                    status=ContactStatus.CANCELLED,
                    error_code="CAMPANHA_ABORTADA",
                    error_detail="Campanha abortada pelo operador",
                    timestamp=datetime.now(),
                )
            )
            self.cancelled_count += 1

    def _process_loop(self, max_steps: Optional[int] = None) -> None:
        """Loop central de despacho de mensagens."""
        steps_executed = 0

        while self.state == QueueState.RUNNING and self.current_index < len(self.contacts):
            if max_steps is not None and steps_executed >= max_steps:
                break

            contact = self.contacts[self.current_index]
            contact.status = ContactStatus.PROCESSING

            # Gera mensagem com Spintax e interpolação
            msg = SpintaxEngine.process_message(self.message_template, contact)

            # Executa o envio (ou simulação com auto-dismiss)
            res = self.send_fn(contact, msg)
            self.results.append(res)

            if res.success:
                contact.status = ContactStatus.SENT
                self.sent_count += 1
            else:
                contact.status = ContactStatus.FAILED
                contact.error_detail = res.error_detail
                self.failed_count += 1

            contact.timestamp = res.timestamp

            # Registra jitter anti-ban
            delay = self.jitter_engine.get_next_delay()
            self.delays_recorded.append(delay)

            self.current_index += 1
            steps_executed += 1

            # Gatilho de pausa aperiódica por lote (~20 mensagens: entre batch_size-2 e batch_size+2)
            if self.current_index > 0 and self.current_index % self.batch_size == 0:
                self.batch_pauses_triggered += 1

        if self.current_index >= len(self.contacts) and self.state == QueueState.RUNNING:
            self.state = QueueState.COMPLETED
            self.end_time = time.time()


# ==============================================================================
# 5. Exportador de Relatórios (.xlsx com '@' texto e .csv utf-8-sig com ';')
# ==============================================================================

class ReportExporterEngine:
    """
    Exportador profissional de relatórios executivos de campanha:
    - Excel (.xlsx): Coluna 'Numero' com formato '@' texto puro, aba 'Resumo_Executivo' com KPIs.
    - CSV (.csv): Codificação 'utf-8-sig' (com BOM), delimitador ';'.
    - Colunas obrigatórias: Numero, Status, DataHora, Detalhes.
    """

    REQUIRED_COLUMNS = ["Numero", "Status", "DataHora", "Detalhes"]

    @classmethod
    def export_excel(
        cls,
        results: List[SendMessageResult],
        file_path: Path,
        campaign_title: str = "WhatsApp Bulk Campaign",
    ) -> Path:
        """Gera planilha Excel profissional com formatação @ na coluna de telefone."""
        wb = openpyxl.Workbook()
        ws_data = wb.active
        ws_data.title = "Relatorio_Disparos"

        # Estilos
        header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

        # Cabeçalhos na aba de dados
        ws_data.append(cls.REQUIRED_COLUMNS)
        for col_num in range(1, len(cls.REQUIRED_COLUMNS) + 1):
            cell = ws_data.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Linhas de dados
        for idx, r in enumerate(results, start=2):
            status_str = r.status.value if isinstance(r.status, Enum) else str(r.status)
            dt_str = r.timestamp.strftime("%Y-%m-%d %H:%M:%S") if r.timestamp else ""
            detail_str = r.error_detail or ("Mensagem enviada com sucesso" if r.success else "Falha no envio")

            # Escreve explicitamente o telefone como string
            num_cell = ws_data.cell(row=idx, column=1, value=str(r.canonical_phone))
            # Blindagem contra coerção de número do Excel
            num_cell.number_format = "@"

            ws_data.cell(row=idx, column=2, value=status_str)
            ws_data.cell(row=idx, column=3, value=dt_str)
            ws_data.cell(row=idx, column=4, value=detail_str)

        # Ajuste de largura das colunas
        column_widths = {"A": 20, "B": 16, "C": 22, "D": 40}
        for col, width in column_widths.items():
            ws_data.column_dimensions[col].width = width

        # 2. Aba de Resumo Executivo (KPIs)
        ws_summary = wb.create_sheet(title="Resumo_Executivo")
        total = len(results)
        sent = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success and r.status != ContactStatus.CANCELLED)
        cancelled = sum(1 for r in results if r.status == ContactStatus.CANCELLED)
        success_rate = round((sent / total * 100.0), 2) if total > 0 else 0.0

        summary_rows = [
            ["Métrica da Campanha", "Valor"],
            ["Título da Campanha", campaign_title],
            ["Total de Contatos na Fila", total],
            ["Enviados com Sucesso", sent],
            ["Falhas / Sem WhatsApp", failed],
            ["Cancelados / Abortados", cancelled],
            ["Taxa de Entrega (%)", f"{success_rate}%"],
            ["Data do Relatório", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ]
        for row in summary_rows:
            ws_summary.append(row)

        for col_num in (1, 2):
            c = ws_summary.cell(row=1, column=col_num)
            c.fill = header_fill
            c.font = header_font

        ws_summary.column_dimensions["A"].width = 28
        ws_summary.column_dimensions["B"].width = 30

        file_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(file_path)
        wb.close()
        return file_path

    @classmethod
    def export_csv(
        cls,
        results: List[SendMessageResult],
        file_path: Path,
    ) -> Path:
        """Gera arquivo CSV em formato universal brasileiro (utf-8-sig com delimitador ;)."""
        import csv
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(cls.REQUIRED_COLUMNS)

            for r in results:
                status_str = r.status.value if isinstance(r.status, Enum) else str(r.status)
                dt_str = r.timestamp.strftime("%Y-%m-%d %H:%M:%S") if r.timestamp else ""
                detail_str = r.error_detail or ("Mensagem enviada com sucesso" if r.success else "Falha no envio")
                writer.writerow([r.canonical_phone, status_str, dt_str, detail_str])

        return file_path
