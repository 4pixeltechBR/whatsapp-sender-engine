"""
ADVERSARIAL STRESS & CORNER CASE TEST HARNESS (TIER 5)
WhatsApp Sender Engine — Autonomous Empirical Challenger Verification Suite

Scope of Verification:
1. Massive Ingestion & Sanitization Stress (>10,000 Contacts)
   - Bizarre numbers, Unicode invisible characters, emojis, extreme accents,
     corrupted floats, scientific notations, invalid DDDs, and deduplication.
   - Ingestion of both CSV (12,000 rows) and XLSX (10,000 rows).
   - Memory benchmark (tracemalloc) and execution timing.
2. Strict Unitary Concurrency Lock (concurrency = 1)
   - Parallel workers attempting simultaneous queue dispatch.
   - Verification of _concurrency_lock, state machine transitions, and FastAPI /api/queue/start.
3. High-Speed Abort & Partial Report Integrity
   - Rapid emergency abort during active dispatch.
   - Integrity of state transitions, cancelled items, and partial XLSX/CSV generation.
   - Forensic audit of ReportingService integration during abort.
4. Report Column & Encoding Integrity
   - Preservation of '@' text format in Excel (.xlsx) preventing 13-digit scientific notation.
   - Verification of UTF-8 with BOM (\\xef\\xbb\\xbf) and ';' delimiter in CSV (.csv).
"""

import asyncio
import csv
from datetime import datetime
import io
import math
from pathlib import Path
import random
import shutil
import sys
import time
import tracemalloc
import unittest

from fastapi.testclient import TestClient
import openpyxl

# Absolute imports from repository root
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.constants import (
    ANATEL_DDDS,
    ANATEL_DDDS_STR,
    ContactStatus,
    QueueState,
)
from app.models.schemas import ContactRecord, SendMessageResult, TelemetrySnapshot
from app.services.contact_service import ContactService, contact_service
from app.services.dispatcher_service import (
    DispatcherService,
    QueueDispatcherEngine,
    QueueEngineState,
    dispatcher_service,
)
from app.services.reporting_service import ReportingService, reporting_service
from app.main import app, app_state


class AdversarialTier5Harness(unittest.TestCase):
    """Suíte Adversarial de Alta Intensidade (Tier 5) para WhatsApp Sender Engine."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = ROOT_DIR / "data" / "temp_adversarial_tier5"
        cls.temp_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls.temp_dir.exists():
            shutil.rmtree(cls.temp_dir, ignore_errors=True)

    # ==========================================================================
    # SUITE 1: MASSIVE STRESS TEST (>10,000 CONTACTS)
    # ==========================================================================

    def test_massive_dataset_stress_12000_csv_and_xlsx(self):
        """
        Gera e ingere base massiva com 12.000 contatos no CSV e 10.000 no XLSX contendo:
        - 6.000 celulares e fixos válidos (diversos DDDs da Anatel).
        - 2.000 duplicatas dos primeiros 2.000 com formatação e DDI diferentes para testar First Wins + merge.
        - 1.500 contatos com caracteres bizarros (emojis, acentos, caracteres invisíveis \u200b, \ufeff, \u00a0, XSS).
        - 2.500 contatos inválidos/extremos (DDDs inexistentes, floats, notações científicas, repetições, NaN).
        """
        print("\n" + "=" * 80)
        print(" [TIER 5 - TEST 1] MASSIVE DATASET STRESS TEST (12,000 CONTACTS CSV + 10,000 XLSX)")
        print("=" * 80)

        csv_path = self.temp_dir / "massive_stress_12000.csv"
        xlsx_path = self.temp_dir / "massive_stress_10000.xlsx"

        valid_ddds = list(ANATEL_DDDS_STR)
        invalid_ddds = ["20", "23", "25", "26", "29", "30", "36", "39", "50", "52", "56", "57", "58", "59", "70", "72", "76", "78", "80", "90"]

        invisible_chars = ["\u200b", "\u200c", "\u200d", "\ufeff", "\u00a0", "\t"]
        bizarre_names = [
            "Renata Açaí e Conceição 🚀",
            "José Maria d'Ávila; Jr.",
            "Dr. O'Connor & Sons <script>alert(1)</script>",
            "Müller-Lüdenscheidt 🎉💥",
            "Владимир Путин 🤖",
            "田中太郎 💎",
            "محمد عبد الله ✨",
            "Nome com espaço invisível\u200be tab\t",
            "Contato com aspas \"duplas\" e 'simples'",
            "Lead com quebra de linha tratada",
        ]

        rows_data = []

        # 1. 6.000 contatos válidos canônicos
        for i in range(1, 6001):
            ddd = valid_ddds[i % len(valid_ddds)]
            phone = f"{ddd}9912{i:04d}"
            name = f"Cliente Válido {i}"
            rows_data.append([phone, name, f"EMPRESA_{i%50}", f"CUPOM_{i%20}"])

        # 2. 2.000 duplicatas determinísticas dos primeiros 2.000 com formatação alternativa
        for i in range(1, 2001):
            ddd = valid_ddds[i % len(valid_ddds)]
            phone = f"+55 ({ddd}) 9912-{i:04d}"
            name = f"Cliente Válido {i} (Duplicata)"
            rows_data.append([phone, name, f"EMPRESA_MERGE_{i}", f"NOVO_CUPOM_{i}"])

        # 3. 1.500 contatos com caracteres invisíveis e emojis
        for i in range(1, 1501):
            ddd = valid_ddds[i % len(valid_ddds)]
            invis = invisible_chars[i % len(invisible_chars)]
            biz_name = bizarre_names[i % len(bizarre_names)] + f" {i}"
            phone = f"{invis}{ddd}9888{invis}{i:04d}{invis}"
            rows_data.append([phone, biz_name, f"TAG_{invis}_VAR", "VIP_EMOJI"])

        # 4. 2.500 contatos inválidos/extremos
        for i in range(1, 2501):
            if i % 8 == 0:
                bad_ddd = invalid_ddds[i % len(invalid_ddds)]
                phone = f"{bad_ddd}991234567"
            elif i % 8 == 1:
                phone = "9" * 11
            elif i % 8 == 2:
                phone = f"6299{i}"
            elif i % 8 == 3:
                phone = f"55629912345678901234"
            elif i % 8 == 4:
                phone = f"6299ABC{i:04d}"
            elif i % 8 == 5:
                phone = "6.29949E-05"
            elif i % 8 == 6:
                phone = f"+1 202 555 {i:04d}"
            else:
                phone = "INVALID_NUMBER_NAN"
            rows_data.append([phone, f"Contato Inválido {i}", "INVALID", "NONE"])

        random.seed(42)
        random.shuffle(rows_data)
        total_rows = len(rows_data)
        self.assertEqual(total_rows, 12000, "Base gerada deve conter exatamente 12.000 contatos")

        # Escrita e medição do CSV
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Telefone", "Nome", "Empresa", "Cupom"])
            writer.writerows(rows_data)

        tracemalloc.start()
        start_time = time.perf_counter()

        ingestion_result = contact_service.parse_file(csv_path)

        duration = time.perf_counter() - start_time
        current_ram, peak_ram = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_ram_mb = peak_ram / (1024 * 1024)
        print(f" -> CSV 12.000 Linhas Processado em : {duration:.3f} segundos")
        print(f" -> Pico de Memória RAM (tracemalloc) : {peak_ram_mb:.2f} MB")
        print(f" -> Total de Linhas Lidas           : {ingestion_result.total_rows}")
        print(f" -> Contatos Válidos Únicos         : {len(ingestion_result.valid_contacts)}")
        print(f" -> Duplicatas Identificadas        : {ingestion_result.duplicate_count}")
        print(f" -> Linhas Inválidas Descartadas    : {ingestion_result.invalid_count}")

        self.assertEqual(ingestion_result.total_rows, 12000)
        self.assertLess(duration, 3.0, "Parsing de 12.000 linhas em CSV deve ser sub-3s")
        self.assertLess(peak_ram_mb, 45.0, "Consumo de RAM para 12.000 linhas deve ser < 45MB")
        self.assertEqual(len(ingestion_result.valid_contacts), 7500)
        self.assertEqual(ingestion_result.duplicate_count, 2000)
        self.assertEqual(ingestion_result.invalid_count, 2500)

        # Geração e Ingestão de XLSX com 10.000 linhas
        print("\n [TEST 1B] Gerando e processando XLSX com 10.000 linhas via openpyxl streaming...")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Telefone", "Nome", "Empresa", "Cupom"])
        for r in rows_data[:10000]:
            ws.append(r)
        wb.save(xlsx_path)
        wb.close()

        tracemalloc.start()
        start_xlsx = time.perf_counter()
        res_xlsx = contact_service.parse_file(xlsx_path)
        duration_xlsx = time.perf_counter() - start_xlsx
        _, peak_xlsx_ram = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_xlsx_mb = peak_xlsx_ram / (1024 * 1024)
        print(f" -> XLSX 10.000 Linhas Processado em: {duration_xlsx:.3f} segundos")
        print(f" -> Pico de Memória RAM XLSX        : {peak_xlsx_mb:.2f} MB")
        print(f" -> Total de Linhas Lidas           : {res_xlsx.total_rows}")
        print(f" -> Contatos Válidos Únicos         : {len(res_xlsx.valid_contacts)}")
        print(f" -> Duplicatas Identificadas        : {res_xlsx.duplicate_count}")
        print(f" -> Linhas Inválidas Descartadas    : {res_xlsx.invalid_count}")

        self.assertEqual(res_xlsx.total_rows, 10000)
        self.assertLess(duration_xlsx, 5.0, "Parsing de 10.000 linhas em XLSX deve ser sub-5s")
        self.assertLess(peak_xlsx_mb, 45.0, "Consumo de RAM para 10.000 linhas em XLSX deve ser < 45MB")

        print(" [PASS] Suíte 1 (Estresse Massivo de Ingestão CSV + XLSX) concluída com sucesso!")

    # ==========================================================================
    # SUITE 2: STRICT UNITARY CONCURRENCY LOCK (concurrency = 1)
    # ==========================================================================

    def test_strict_concurrency_lock_prevents_simultaneous_workers(self):
        """
        Desafia a trava unitária `concurrency = 1` (_concurrency_lock) em:
        1. Execução assíncrona concorrente (run_queue_async).
        2. Transição de máquina de estados duplicada (start()).
        3. Endpoint REST da aplicação (/api/queue/start).
        """
        print("\n" + "=" * 80)
        print(" [TIER 5 - TEST 2] STRICT UNITARY CONCURRENCY LOCK (concurrency = 1)")
        print("=" * 80)

        contacts = [
            ContactRecord(
                id=f"c_{i}",
                raw_phone=f"6299111{i:04d}",
                canonical_phone=f"556299111{i:04d}",
                name=f"Contato {i}",
            )
            for i in range(1, 21)
        ]

        async def slow_send_fn(contact: ContactRecord, msg: str) -> SendMessageResult:
            await asyncio.sleep(0.05)
            return SendMessageResult(
                canonical_phone=contact.canonical_phone,
                success=True,
                status=ContactStatus.SENT,
                error_detail="Sucesso",
                timestamp=datetime.now(),
            )

        dispatcher = DispatcherService(
            contacts=contacts,
            message_template="Olá {nome}",
            send_fn=slow_send_fn,
        )

        async def run_concurrent_test():
            task1 = asyncio.create_task(dispatcher.run_queue_async())
            await asyncio.sleep(0.01)

            worker2_rejected = False
            worker2_error_msg = ""
            try:
                await dispatcher.run_queue_async()
            except RuntimeError as ex:
                worker2_rejected = True
                worker2_error_msg = str(ex)

            results1 = await task1
            return worker2_rejected, worker2_error_msg, results1

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            worker2_rejected, err_msg, results1 = loop.run_until_complete(run_concurrent_test())
        finally:
            loop.close()

        print(f" -> Worker 2 Rejeitado             : {worker2_rejected}")
        print(f" -> Mensagem de Erro do Worker 2   : '{err_msg}'")
        print(f" -> Worker 1 Concluiu Envios       : {len(results1)} contatos processados")

        self.assertTrue(worker2_rejected, "Worker 2 DEVE ser rejeitado quando o lock unitário está ativo")
        self.assertIn("Concorrência Unitária Estrita", err_msg)
        self.assertEqual(len(results1), 20)
        self.assertEqual(dispatcher.state, QueueState.COMPLETED)

        # Teste 2B: Chamada duplicada a start() síncrono quando já está em execução
        disp_sync = DispatcherService(contacts=contacts[:5], message_template="Teste")
        disp_sync.state = QueueState.RUNNING
        with self.assertRaises(RuntimeError) as ctx:
            disp_sync.start()
        print(f" -> start() em RUNNING Rejeitado  : OK ('{ctx.exception}')")
        self.assertIn("Transição inválida", str(ctx.exception))

        # Teste 2C: REST API /api/queue/start retorna HTTP 400 se a fila já estiver RUNNING
        print(" [TEST 2C] Verificando bloqueio de concorrência na API REST /api/queue/start...")
        client = TestClient(app)
        dispatcher_service.state = QueueState.RUNNING

        response = client.post(
            "/api/queue/start",
            json={
                "template": "Olá {nome}",
                "contacts": [{"telefone": "62994912937", "nome": "Cliente Teste"}],
            },
        )
        dispatcher_service.state = QueueState.IDLE  # Restaura estado
        print(f" -> POST /api/queue/start Status   : {response.status_code}")
        print(f" -> POST /api/queue/start Body     : {response.json()}")

        self.assertEqual(response.status_code, 400)
        self.assertIn("A fila já está em execução", response.json()["detail"])

        print(" [PASS] Suíte 2 (Trava de Concorrência Unitária) concluída com sucesso!")

    # ==========================================================================
    # SUITE 3: HIGH-SPEED ABORT & PARTIAL REPORT RECOVERY
    # ==========================================================================

    def test_high_speed_abort_and_partial_report_integrity(self):
        """
        Desafia o comportamento de interrupção de emergência (abort):
        - Fila de 150 contatos com envio rápido.
        - Aciona abort() súbito após 25 envios.
        - Verifica integridade de estados e resultados no DispatcherService.
        - Gera arquivos parciais .xlsx e .csv via exportador direto.
        """
        print("\n" + "=" * 80)
        print(" [TIER 5 - TEST 3] HIGH-SPEED ABORT & PARTIAL REPORT INTEGRITY")
        print("=" * 80)

        total_campaign_size = 150
        abort_trigger_step = 25

        contacts = [
            ContactRecord(
                id=f"c_{i}",
                raw_phone=f"6299222{i:04d}",
                canonical_phone=f"556299222{i:04d}",
                name=f"Contato {i}",
            )
            for i in range(1, total_campaign_size + 1)
        ]

        disp = DispatcherService(
            contacts=contacts,
            message_template="Aviso urgente {nome}",
            batch_size=20,
        )

        # Executa 25 envios e aborta
        disp.start(max_steps=abort_trigger_step)
        self.assertEqual(disp.current_index, abort_trigger_step)

        # Dispara aborto imediato
        disp.abort()

        print(f" -> Estado do Dispatcher pós-abort : {disp.state}")
        print(f" -> Dispatcher Sent Count          : {disp.sent_count}")
        print(f" -> Dispatcher Cancelled Count     : {disp.cancelled_count}")
        print(f" -> Dispatcher Total Results       : {len(disp.results)}")

        self.assertEqual(disp.state, QueueState.ABORTED)
        self.assertEqual(disp.sent_count, abort_trigger_step)
        self.assertEqual(disp.cancelled_count, total_campaign_size - abort_trigger_step)
        self.assertEqual(len(disp.results), total_campaign_size)

        # Exportação Direta via Dispatcher Results
        direct_excel = self.temp_dir / "direct_abort_partial.xlsx"
        direct_csv = self.temp_dir / "direct_abort_partial.csv"
        ReportingService.export_excel(disp.results, direct_excel, campaign_title="Aborto Direto")
        ReportingService.export_csv(disp.results, direct_csv)

        # Verifica integridade do Excel direto
        wb_dir = openpyxl.load_workbook(direct_excel)
        ws_dir_data = wb_dir["Relatorio_Disparos"]
        ws_dir_summary = wb_dir["Resumo_Executivo"]
        self.assertEqual(ws_dir_data.max_row, total_campaign_size + 1, "Excel deve conter todos os 150 contatos")

        kpis = {r[0]: r[1] for r in ws_dir_summary.iter_rows(values_only=True) if r}
        self.assertEqual(kpis.get("Total de Contatos na Fila"), total_campaign_size)
        self.assertEqual(kpis.get("Enviados com Sucesso"), abort_trigger_step)
        self.assertEqual(kpis.get("Cancelados / Abortados"), total_campaign_size - abort_trigger_step)
        wb_dir.close()

        # Verifica integridade do CSV direto
        with open(direct_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f, delimiter=";")
            csv_rows = list(reader)
            self.assertEqual(len(csv_rows), total_campaign_size + 1, "CSV deve conter todos os 150 contatos + cabeçalho")

        print(" [PASS] Suíte 3A (Aborto e Relatório Parcial no DispatcherService) validado com sucesso!")

    def test_reporting_service_abort_integration_audit(self):
        """
        AUDITORIA ADVERSARIAL CRÍTICA:
        Testa se o ReportingService acoplado aos eventos do DispatcherService
        preserva os contatos cancelados ao sofrer abort().
        """
        print("\n" + "=" * 80)
        print(" [TIER 5 - TEST 3B] AUDITORIA DE INTEGRAÇÃO: REPORTING_SERVICE PÓS-ABORT")
        print("=" * 80)

        total_contacts = 100
        sent_before_abort = 20

        contacts = [
            ContactRecord(
                id=f"c_{i}",
                raw_phone=f"6299333{i:04d}",
                canonical_phone=f"556299333{i:04d}",
                name=f"Lead {i}",
            )
            for i in range(1, total_contacts + 1)
        ]

        rep = ReportingService(reports_dir=self.temp_dir)
        rep.reset_campaign(total_contacts=total_contacts, campaign_title="Auditoria Aborto")

        disp = DispatcherService(contacts=contacts, message_template="Olá {nome}")
        rep.attach_to_dispatcher(disp)

        disp.start(max_steps=sent_before_abort)
        disp.abort()

        print(f" -> Dispatcher Sent Count      : {disp.sent_count}")
        print(f" -> Dispatcher Cancelled Count : {disp.cancelled_count}")
        print(f" -> Dispatcher Results Count   : {len(disp.results)}")
        print(f" -> Reporting Sent Count       : {rep.sent_count}")
        print(f" -> Reporting Cancelled Count  : {rep.cancelled_count}")
        print(f" -> Reporting _results Count   : {len(rep._results)}")

        excel_exported = self.temp_dir / "audit_rep_abort.xlsx"
        rep.export_current_campaign_excel(file_path=excel_exported)

        wb = openpyxl.load_workbook(excel_exported)
        ws_data = wb["Relatorio_Disparos"]
        ws_sum = wb["Resumo_Executivo"]
        data_rows = ws_data.max_row - 1
        kpis = {r[0]: r[1] for r in ws_sum.iter_rows(values_only=True) if r}
        wb.close()

        print(f" -> Linhas de dados no Excel gerado: {data_rows} (Esperado: {total_contacts})")
        print(f" -> KPIs Resumo Executivo:")
        for k, v in kpis.items():
            print(f"    * {k}: {v}")

        # Asserção formal da sincronização entre Dispatcher e ReportingService
        has_sync_defect = (rep.cancelled_count == 0 or len(rep._results) < total_contacts)
        if has_sync_defect:
            print("\n [CRITICAL DEFECT DETECTED] ReportingService._on_dispatcher_queue_aborted ignores cancelled contacts!")
            print(f" -> {total_contacts - sent_before_abort} contatos cancelados foram omitidos do relatório executivo exportado!")
            print(f" -> Taxa de entrega falsamente reportada como {kpis.get('Taxa de Entrega (%)')} em vez de 20.0%!")

        self.assertFalse(
            has_sync_defect,
            f"VULNERABILIDADE: ReportingService não sincronizou {total_contacts - sent_before_abort} contatos cancelados no abort()"
        )

    # ==========================================================================
    # SUITE 4: REPORT COLUMN & ENCODING INTEGRITY (TEXT FORMAT '@' AND UTF-8 BOM)
    # ==========================================================================

    def test_report_column_formatting_and_encoding_integrity(self):
        """
        Verifica estritamente:
        1. Formato de número '@' (texto puro) na coluna de telefone no Excel (.xlsx).
        2. Cabeçalhos exatos: Numero, Status, DataHora, Detalhes.
        3. Preservação de números com 13 dígitos ('5562994912937') sem coerção para float/científica.
        4. Encoding UTF-8 com BOM (\\xef\\xbb\\xbf) no CSV (.csv).
        5. Delimitador ';' no CSV para abertura automática no Excel Windows.
        6. Preservação de caracteres especiais, emojis e acentos.
        """
        print("\n" + "=" * 80)
        print(" [TIER 5 - TEST 4] REPORT COLUMN & ENCODING INTEGRITY")
        print("=" * 80)

        test_results = [
            SendMessageResult(
                canonical_phone="5562994912937",
                success=True,
                status=ContactStatus.SENT,
                error_detail="Mensagem entregue com sucesso 🚀",
                timestamp=datetime(2026, 9, 16, 10, 0, 0),
            ),
            SendMessageResult(
                canonical_phone="5511987654321",
                success=False,
                status=ContactStatus.FAILED,
                error_code="MODAL_NUMERO_SEM_WHATSAPP",
                error_detail="Número sem WhatsApp ativo (diálogo OK dispensado) — Atenção: Açúcar & Café",
                timestamp=datetime(2026, 9, 16, 10, 0, 15),
            ),
            SendMessageResult(
                canonical_phone="5521998887777",
                success=False,
                status=ContactStatus.CANCELLED,
                error_code="CAMPANHA_ABORTADA",
                error_detail="Campanha abortada pelo operador",
                timestamp=datetime(2026, 9, 16, 10, 0, 30),
            ),
        ]

        excel_target = self.temp_dir / "test_formatting.xlsx"
        csv_target = self.temp_dir / "test_formatting.csv"

        ReportingService.export_excel(test_results, excel_target, campaign_title="Auditoria de Formatação")
        ReportingService.export_csv(test_results, csv_target)

        # 1. Auditoria do Excel (.xlsx)
        self.assertTrue(excel_target.exists(), "Arquivo Excel deve ser gerado")
        wb = openpyxl.load_workbook(excel_target)
        self.assertIn("Relatorio_Disparos", wb.sheetnames)
        self.assertIn("Resumo_Executivo", wb.sheetnames)

        ws_data = wb["Relatorio_Disparos"]

        # Cabeçalhos exatos
        headers = [cell.value for cell in ws_data[1]]
        self.assertEqual(headers, ["Numero", "Status", "DataHora", "Detalhes"])

        # Linhas de dados e formatação '@'
        for row_idx in range(2, 5):
            cell_phone = ws_data.cell(row=row_idx, column=1)
            phone_str = str(cell_phone.value)

            self.assertEqual(cell_phone.number_format, "@", f"Linha {row_idx}: Formato da célula deve ser '@' texto")
            self.assertEqual(len(phone_str), 13, f"Linha {row_idx}: Telefone deve manter 13 dígitos")
            self.assertFalse("E+" in phone_str or "e+" in phone_str, f"Linha {row_idx}: Telefone não pode conter notação científica")
            self.assertTrue(phone_str.startswith("55"), f"Linha {row_idx}: Telefone deve iniciar com DDI 55")

        wb.close()
        print(" -> Excel .xlsx: Cabeçalhos, formato '@' e 13 dígitos preservados com sucesso!")

        # 2. Auditoria do CSV (.csv)
        self.assertTrue(csv_target.exists(), "Arquivo CSV deve ser gerado")

        with open(csv_target, "rb") as f_bin:
            bom_bytes = f_bin.read(3)
            self.assertEqual(bom_bytes, b"\xef\xbb\xbf", "Arquivo CSV DEVE iniciar com os 3 bytes do BOM UTF-8 (\\xef\\xbb\\xbf)")

        with open(csv_target, "r", encoding="utf-8-sig") as f_txt:
            content = f_txt.read()
            lines = content.splitlines()

            self.assertEqual(lines[0], "Numero;Status;DataHora;Detalhes")
            self.assertEqual(len(lines), 4, "CSV deve ter 1 cabeçalho + 3 linhas de dados")
            self.assertIn("🚀", content, "Emoji de foguete deve ser preservado no CSV")
            self.assertIn("Açúcar & Café", content, "Acentos gráficos e cedilha devem ser preservados")
            self.assertIn("5562994912937", content, "Número canônico de 13 dígitos preservado")

        print(" -> CSV .csv: BOM UTF-8 (\\xef\\xbb\\xbf), delimitador ';' e acentuação preservados com sucesso!")
        print(" [PASS] Suíte 4 (Integridade de Colunas e Formatação) concluída com sucesso!")


if __name__ == "__main__":
    unittest.main(verbosity=2)
