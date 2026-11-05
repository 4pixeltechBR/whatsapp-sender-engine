"""
Unit and Integration Tests for Executive Reporting, Excel (.xlsx with @ Text Format),
CSV (utf-8-sig with ';' delimiter), and Mandatory Columns (Tier 1 & Tier 2).
Target Module: Reporting Service (Milestone 4 Contract)
"""

from datetime import datetime
from pathlib import Path
import tempfile
import unittest

import openpyxl

from app.core.constants import ContactStatus
from app.models.schemas import SendMessageResult
from app.services.reporting_service import ReportingService as ReportExporterEngine


class TestReportingFeatureCoverage(unittest.TestCase):
    """
    Tier 1 - Feature Coverage:
    - Exportação Excel (.xlsx) com coluna de telefone formatada como '@' (texto).
    - Criação da aba 'Resumo_Executivo' com KPIs de entrega.
    - Exportação CSV com delimitador ';' e codificação 'utf-8-sig' (com BOM).
    - Presença obrigatória das colunas: Numero, Status, DataHora, Detalhes.
    - Integridade de acentuação e caracteres especiais em ambos os formatos.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Conjunto representativo de resultados de disparo
        self.results = [
            SendMessageResult(
                canonical_phone="5562994912937",
                success=True,
                status=ContactStatus.SENT,
                error_detail="Mensagem enviada com sucesso",
                timestamp=datetime(2026, 9, 16, 10, 30, 0),
            ),
            SendMessageResult(
                canonical_phone="5511988887777",
                success=True,
                status=ContactStatus.SENT,
                error_detail="Mensagem enviada com sucesso",
                timestamp=datetime(2026, 9, 16, 10, 30, 22),
            ),
            SendMessageResult(
                canonical_phone="5521977776666",
                success=False,
                status=ContactStatus.FAILED,
                error_code="MODAL_NUMERO_SEM_WHATSAPP",
                error_detail="Número não possui WhatsApp ativo (modal OK)",
                timestamp=datetime(2026, 9, 16, 10, 30, 45),
            ),
            SendMessageResult(
                canonical_phone="5531966665555",
                success=False,
                status=ContactStatus.CANCELLED,
                error_detail="Campanha abortada pelo operador",
                timestamp=datetime(2026, 9, 16, 10, 31, 0),
            ),
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    # --------------------------------------------------------------------------
    # 1. Exportação Excel (.xlsx) com Formatação @ Texto e Aba Resumo
    # --------------------------------------------------------------------------

    def test_export_excel_creates_valid_file_with_required_columns(self):
        """Verifica se o arquivo .xlsx gerado contém as 4 colunas obrigatórias."""
        excel_path = self.temp_path / "relatorio_teste.xlsx"
        ReportExporterEngine.export_excel(self.results, excel_path)

        self.assertTrue(excel_path.exists())
        self.assertGreater(excel_path.stat().st_size, 1000)

        wb = openpyxl.load_workbook(excel_path)
        self.assertIn("Relatorio_Disparos", wb.sheetnames)
        ws = wb["Relatorio_Disparos"]

        # Cabeçalhos
        headers = [ws.cell(row=1, column=c).value for c in range(1, 5)]
        expected_headers = ["Numero", "Status", "DataHora", "Detalhes"]
        self.assertEqual(headers, expected_headers)

        # Quantidade de linhas de dados
        self.assertEqual(ws.max_row, 5)  # 1 cabeçalho + 4 dados
        wb.close()

    def test_export_excel_applies_at_text_format_to_phone_column(self):
        """
        Critério Mandatório de Integridade:
        A coluna 'Numero' DEVE possuir number_format = '@' (texto).
        Ao abrir no Microsoft Excel, o número '5562994912937' não pode ser
        convertido para notação científica ('5.56E+12') nem truncado.
        """
        excel_path = self.temp_path / "relatorio_formato_texto.xlsx"
        ReportExporterEngine.export_excel(self.results, excel_path)

        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Relatorio_Disparos"]

        for row_idx in range(2, 6):
            cell = ws.cell(row=row_idx, column=1)
            # Verifica o formato de texto '@'
            self.assertEqual(
                cell.number_format,
                "@",
                f"Célula na linha {row_idx} não está com formato '@' texto!"
            )
            # Verifica que o valor é string com todos os 13 dígitos
            self.assertIsInstance(cell.value, str)
            self.assertEqual(len(cell.value), 13)
            self.assertTrue(cell.value.startswith("55"))

        wb.close()

    def test_export_excel_creates_executive_summary_sheet(self):
        """Valida que a aba 'Resumo_Executivo' contém os KPIs gerenciais da campanha."""
        excel_path = self.temp_path / "relatorio_kpis.xlsx"
        ReportExporterEngine.export_excel(self.results, excel_path, campaign_title="Campanha Black Friday")

        wb = openpyxl.load_workbook(excel_path)
        self.assertIn("Resumo_Executivo", wb.sheetnames)
        ws_sum = wb["Resumo_Executivo"]

        metrics = {}
        for row in ws_sum.iter_rows(values_only=True):
            if row and row[0] is not None:
                metrics[row[0]] = row[1]

        self.assertEqual(metrics.get("Título da Campanha"), "Campanha Black Friday")
        self.assertEqual(metrics.get("Total de Contatos na Fila"), 4)
        self.assertEqual(metrics.get("Enviados com Sucesso"), 2)
        self.assertEqual(metrics.get("Falhas / Sem WhatsApp"), 1)
        self.assertEqual(metrics.get("Cancelados / Abortados"), 1)
        self.assertEqual(metrics.get("Taxa de Entrega (%)"), "50.0%")
        wb.close()

    # --------------------------------------------------------------------------
    # 2. Exportação CSV com Delimitador ';' e Codificação 'utf-8-sig'
    # --------------------------------------------------------------------------

    def test_export_csv_starts_with_utf8_bom_and_uses_semicolon(self):
        """
        Valida que o arquivo CSV:
        1. Inicia com o BOM UTF-8 (\xef\xbb\xbf) para abertura direta no Excel Windows.
        2. Utiliza ';' como delimitador oficial.
        3. Contém as 4 colunas obrigatórias: Numero;Status;DataHora;Detalhes.
        4. Preserva acentos e pontuações brasileiras.
        """
        csv_path = self.temp_path / "relatorio_disparos.csv"
        ReportExporterEngine.export_csv(self.results, csv_path)

        self.assertTrue(csv_path.exists())

        # 1. Verifica BOM em nível binário
        raw_bytes = csv_path.read_bytes()
        self.assertTrue(raw_bytes.startswith(b"\xef\xbb\xbf"), "O CSV deve iniciar com BOM UTF-8.")

        # 2. Verifica leitura com utf-8-sig
        text = csv_path.read_text(encoding="utf-8-sig")
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        self.assertEqual(lines[0], "Numero;Status;DataHora;Detalhes")
        self.assertEqual(len(lines), 5)  # Cabeçalho + 4 linhas

        # Verifica preservação de acentos na linha 3 ("não possui", "ativo")
        self.assertIn("5521977776666;FALHA;2026-09-16 10:30:45;Número não possui WhatsApp ativo (modal OK)", text)


class TestReportingBoundaryAndCornerCases(unittest.TestCase):
    """
    Tier 2 - Boundary & Corner Cases:
    - Campanha vazia (0 resultados).
    - Campanha com 100% de falhas.
    - Caracteres extremos e quebras de linha nas descrições de erro.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_empty_campaign_generates_valid_headers(self):
        """Exportar relatório de campanha vazia gera arquivos estruturados com 0 dados sem erro."""
        empty_results = []
        excel_path = self.temp_path / "empty_report.xlsx"
        csv_path = self.temp_path / "empty_report.csv"

        ReportExporterEngine.export_excel(empty_results, excel_path)
        ReportExporterEngine.export_csv(empty_results, csv_path)

        # Excel vazio
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Relatorio_Disparos"]
        self.assertEqual(ws.max_row, 1)  # Apenas cabeçalho
        wb.close()

        # CSV vazio
        text = csv_path.read_text(encoding="utf-8-sig").strip()
        self.assertEqual(text, "Numero;Status;DataHora;Detalhes")

    def test_export_with_extreme_error_messages(self):
        """Trata mensagens de erro complexas com aspas, barras e caracteres exóticos."""
        special_results = [
            SendMessageResult(
                canonical_phone="5562994912937",
                success=False,
                status=ContactStatus.FAILED,
                error_detail='Erro crítico: "Element not found" / [DOM Timeout 30s] -> URL: https://web.whatsapp.com',
                timestamp=datetime.now(),
            )
        ]
        csv_path = self.temp_path / "extreme.csv"
        ReportExporterEngine.export_csv(special_results, csv_path)

        text = csv_path.read_text(encoding="utf-8-sig")
        self.assertIn("5562994912937", text)
        self.assertIn("Element not found", text)


if __name__ == "__main__":
    unittest.main()
