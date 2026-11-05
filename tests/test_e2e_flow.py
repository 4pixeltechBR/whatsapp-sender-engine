"""
End-to-End (E2E) Flow and Realistic Application Scenario Tests (Tier 3 & Tier 4).
Covers the entire lifecycle from massive file ingestion to sanitization, deduplication,
queue dispatch with anti-ban simulation, live telemetry, and final executive reporting.
"""

from datetime import datetime
from pathlib import Path
import tempfile
import time
import unittest
from typing import Dict, List

import openpyxl

from app.core.constants import ContactStatus, QueueState
from app.models.schemas import ContactRecord, SendMessageResult
from app.services.contact_service import contact_service
from app.services.dispatcher_service import QueueDispatcherEngine, SpintaxEngine
from app.services.reporting_service import ReportingService as ReportExporterEngine
from tests.harness import SyntheticDataGenerator


class TestE2ECrossFeatureInteractions(unittest.TestCase):
    """
    Tier 3 - Cross-Feature Interactions:
    Testa a esteira integrada completa:
    Carga de 5.000 contatos -> Sanitização E.164 -> Deduplicação Determinística
    -> Fila de Envio com Simulação Humana -> Telemetria -> Exportação de Relatório.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_integrated_pipeline_with_5000_contacts(self):
        """
        Executa a esteira ponta a ponta:
        1. Gera arquivo CSV com 5.000 contatos sintéticos variados.
        2. Ingestão via contact_service (sanitização 9º dígito e deduplicação).
        3. Alimenta a fila com os contatos válidos únicos.
        4. Despacha os primeiros 100 contatos na fila (simulando campanha de lote inicial).
        5. Captura telemetria (progresso, ETA, MPM).
        6. Exporta relatórios em Excel (.xlsx com formato @) e CSV (utf-8-sig com ';').
        7. Valida a integridade dos relatórios gerados.
        """
        # 1. Geração de 5.000 contatos
        total_rows = 5000
        dataset = SyntheticDataGenerator.generate_contact_dataset(
            total_rows=total_rows,
            duplicate_ratio=0.06,  # ~300 duplicatas
            invalid_ratio=0.04,    # ~200 inválidos (DDD 23/70, curtos)
        )
        csv_file = self.temp_path / "campanha_5000.csv"
        SyntheticDataGenerator.export_to_csv_file(dataset, csv_file, delimiter=";")

        # 2. Ingestão e Sanitização
        t0 = time.perf_counter()
        ingestion = contact_service.parse_file(csv_file)
        t_ingest = time.perf_counter() - t0

        self.assertEqual(ingestion.total_rows, total_rows)
        self.assertGreater(len(ingestion.valid_contacts), 4200)
        self.assertGreater(ingestion.duplicate_count, 200)
        self.assertGreater(ingestion.invalid_count, 150)
        self.assertLess(t_ingest, 2.0, "Ingestão de 5.000 contatos deve ocorrer em < 2.0s")

        # 3. Configuração da Fila de Disparo para o lote da campanha
        campaign_batch = ingestion.valid_contacts[:100]
        template = "{Oi|{Olá|E aí}} {nome}, temos condições exclusivas para a {empresa}!"

        dispatcher = QueueDispatcherEngine(
            contacts=campaign_batch,
            message_template=template,
            batch_size=20,
            batch_pause_seconds=120.0,
        )

        # 4. Execução da Fila
        dispatcher.start()

        self.assertEqual(dispatcher.state, QueueState.COMPLETED)
        self.assertEqual(dispatcher.sent_count, 100)
        self.assertEqual(dispatcher.failed_count, 0)
        self.assertEqual(len(dispatcher.delays_recorded), 100)
        # Em 100 envios com blocos de 20: pausas nos itens 20, 40, 60, 80, 100
        self.assertEqual(dispatcher.batch_pauses_triggered, 5)

        # 5. Telemetria
        telemetry = dispatcher.get_telemetry()
        self.assertEqual(telemetry.sent_count, 100)
        self.assertEqual(telemetry.pending_count, 0)
        self.assertEqual(telemetry.state, QueueState.COMPLETED)

        # 6. Exportação de Relatórios
        excel_report = self.temp_path / "relatorio_final_5000.xlsx"
        csv_report = self.temp_path / "relatorio_final_5000.csv"

        ReportExporterEngine.export_excel(dispatcher.results, excel_report, campaign_title="Campanha Massiva 5k")
        ReportExporterEngine.export_csv(dispatcher.results, csv_report)

        # 7. Auditoria dos Relatórios Gerados
        self.assertTrue(excel_report.exists())
        self.assertTrue(csv_report.exists())

        # Validação do Excel
        wb = openpyxl.load_workbook(excel_report)
        ws_data = wb["Relatorio_Disparos"]
        self.assertEqual(ws_data.max_row, 101)  # 1 cabeçalho + 100 contatos
        # Valida formatação @ texto da primeira linha de dados e tamanho canônico (12 fixo ou 13 celular)
        self.assertEqual(ws_data.cell(row=2, column=1).number_format, "@")
        self.assertIn(len(str(ws_data.cell(row=2, column=1).value)), (12, 13))
        wb.close()

        # Validação do CSV
        csv_text = csv_report.read_text(encoding="utf-8-sig")
        lines = [l for l in csv_text.splitlines() if l.strip()]
        self.assertEqual(len(lines), 101)
        self.assertEqual(lines[0], "Numero;Status;DataHora;Detalhes")


class TestE2ERealWorldScenarios(unittest.TestCase):
    """
    Tier 4 - Cenários Reais de Aplicação:
    Simulação fiel de fluxos de produção e incidentes operacionais reais.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # --------------------------------------------------------------------------
    # Cenário Real 1: Campanha Comercial de Varejo com Spintax e Lotes
    # --------------------------------------------------------------------------

    def test_scenario_retail_campaign_with_spintax_and_batch_pauses(self):
        """
        Cenário: Loja varejista dispara promoção para 60 clientes cadastrados.
        - Cada mensagem utiliza saudação Spintax ({Bom dia|Olá|Oi}), nome e cupom personalizado.
        - Sistema aciona pausas por bloco a cada 20 envios.
        - Todos os clientes recebem mensagens perfeitamente renderizadas sem erros de sintaxe.
        - Relatório final comprova 100% de entrega e KPIs consolidados.
        """
        contacts = [
            ContactRecord(
                id=f"c_{i}",
                raw_phone=f"1199999{i:04d}",
                canonical_phone=f"551199999{i:04d}",
                name=f"Cliente {i}",
                variables={"cupom": f"DESCONTO_{i * 5}"},
            )
            for i in range(1, 61)  # 60 clientes
        ]

        template = "{Bom dia|{Olá|Oi}} {nome}, seu cupom {cupom} está disponível hoje!"

        dispatcher = QueueDispatcherEngine(
            contacts=contacts,
            message_template=template,
            batch_size=20,
            batch_pause_seconds=180.0,
        )

        dispatcher.start()

        self.assertEqual(dispatcher.state, QueueState.COMPLETED)
        self.assertEqual(dispatcher.sent_count, 60)
        self.assertEqual(dispatcher.batch_pauses_triggered, 3)

        # Exporta e valida relatório
        report_xlsx = self.temp_path / "varejo_report.xlsx"
        ReportExporterEngine.export_excel(dispatcher.results, report_xlsx, campaign_title="Promoção Varejo")

        wb = openpyxl.load_workbook(report_xlsx)
        ws_summary = wb["Resumo_Executivo"]
        kpi_map = {row[0]: row[1] for row in ws_summary.iter_rows(values_only=True) if row}
        self.assertEqual(kpi_map.get("Total de Contatos na Fila"), 60)
        self.assertEqual(kpi_map.get("Enviados com Sucesso"), 60)
        self.assertEqual(kpi_map.get("Taxa de Entrega (%)"), "100.0%")
        wb.close()

    # --------------------------------------------------------------------------
    # Cenário Real 2: Campanha com Números sem WhatsApp e Pausa Manual
    # --------------------------------------------------------------------------

    def test_scenario_campaign_with_non_whatsapp_numbers_and_manual_pause(self):
        """
        Cenário: Empresa envia 40 mensagens, onde 10 contatos não possuem WhatsApp
        e disparam o modal de erro no WhatsApp Web.
        - O sistema detecta o modal e executa o auto-dismiss clicando em 'OK'.
        - O operador pausa o disparo na mensagem 20 para conferência.
        - O operador retoma a campanha até o fim.
        - O relatório final discrimina exatamente 30 SUCESSOS e 10 FALHAS com detalhes.
        """
        # Contatos com ID múltiplo de 4 não possuem WhatsApp
        contacts = [
            ContactRecord(
                id=f"c_{i}",
                raw_phone=f"6299888{i:04d}",
                canonical_phone=f"556299888{i:04d}",
                name=f"Lead {i}",
                variables={},
            )
            for i in range(1, 41)  # 40 leads
        ]

        def mock_whatsapp_web_sender(contact: ContactRecord, message: str) -> SendMessageResult:
            c_idx = int(contact.id.split("_")[1])
            if c_idx % 4 == 0:
                # Simula modal de número inválido / sem WhatsApp e auto-dismiss com clique em OK
                return SendMessageResult(
                    canonical_phone=contact.canonical_phone,
                    success=False,
                    status=ContactStatus.FAILED,
                    error_code="MODAL_NUMERO_SEM_WHATSAPP",
                    error_detail="Número não possui WhatsApp (modal OK auto-dismissed)",
                    timestamp=datetime.now(),
                )
            return SendMessageResult(
                canonical_phone=contact.canonical_phone,
                success=True,
                status=ContactStatus.SENT,
                error_detail="Mensagem enviada com sucesso",
                timestamp=datetime.now(),
            )

        dispatcher = QueueDispatcherEngine(
            contacts=contacts,
            message_template="Olá {nome}!",
            send_fn=mock_whatsapp_web_sender,
            batch_size=20,
        )

        # 1. Inicia até o item 20
        dispatcher.start(max_steps=20)
        self.assertEqual(dispatcher.current_index, 20)

        # 2. Operador aciona Pausa
        dispatcher.pause()
        self.assertEqual(dispatcher.state, QueueState.PAUSED)

        # 3. Operador aciona Retomada e conclui os 20 restantes
        dispatcher.resume()
        self.assertEqual(dispatcher.state, QueueState.COMPLETED)
        self.assertEqual(dispatcher.current_index, 40)

        # Exatamente 10 falhas (4, 8, 12, 16, 20, 24, 28, 32, 36, 40) e 30 sucessos
        self.assertEqual(dispatcher.sent_count, 30)
        self.assertEqual(dispatcher.failed_count, 10)

        # Exporta relatório e valida discriminação das falhas
        csv_report = self.temp_path / "mixed_campaign.csv"
        ReportExporterEngine.export_csv(dispatcher.results, csv_report)

        text = csv_report.read_text(encoding="utf-8-sig")
        self.assertIn("FALHA", text)
        self.assertIn("modal OK auto-dismissed", text)
        self.assertIn("ENVIADO", text)

    # --------------------------------------------------------------------------
    # Cenário Real 3: Campanha com Interrupção de Emergência (Aborto Súbito)
    # --------------------------------------------------------------------------

    def test_scenario_large_campaign_with_emergency_abort(self):
        """
        Cenário: Campanha corporativa de 150 contatos.
        Após enviar 35 mensagens, o operador detecta erro de template e clica em 'Abortar'.
        - A fila interrompe instantaneamente.
        - As 35 mensagens já enviadas mantêm status 'ENVIADO'.
        - As 115 mensagens pendentes são marcadas como 'CANCELADO'.
        - Relatório parcial é emitido imediatamente com a contagem exata e status preservados.
        """
        contacts = [
            ContactRecord(
                id=f"c_{i}",
                raw_phone=f"6299111{i:04d}",
                canonical_phone=f"556299111{i:04d}",
                name=f"Contato {i}",
                variables={},
            )
            for i in range(1, 151)  # 150 contatos
        ]

        dispatcher = QueueDispatcherEngine(
            contacts=contacts,
            message_template="Mensagem urgente para {nome}",
            batch_size=20,
        )

        # Dispara os primeiros 35
        dispatcher.start(max_steps=35)
        self.assertEqual(dispatcher.current_index, 35)

        # Clique de Aborto de Emergência
        dispatcher.abort()
        self.assertEqual(dispatcher.state, QueueState.ABORTED)

        # Emissão imediata do relatório parcial
        partial_excel = self.temp_path / "relatorio_parcial_abortado.xlsx"
        ReportExporterEngine.export_excel(dispatcher.results, partial_excel, campaign_title="Campanha Abortada")

        wb = openpyxl.load_workbook(partial_excel)
        ws_data = wb["Relatorio_Disparos"]
        ws_summary = wb["Resumo_Executivo"]

        # 150 contatos no total
        self.assertEqual(ws_data.max_row, 151)

        # Contagem na aba de resumo
        kpis = {r[0]: r[1] for r in ws_summary.iter_rows(values_only=True) if r}
        self.assertEqual(kpis.get("Total de Contatos na Fila"), 150)
        self.assertEqual(kpis.get("Enviados com Sucesso"), 35)
        self.assertEqual(kpis.get("Cancelados / Abortados"), 115)
        wb.close()


if __name__ == "__main__":
    unittest.main()
