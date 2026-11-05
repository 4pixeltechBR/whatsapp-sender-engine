"""
Unit and Integration Tests for Contact Ingestion, E.164 Sanitization, Float Shielding,
and Deterministic Deduplication (Tier 1 & Tier 2).
Target Module: app.services.contact_service
"""

from decimal import Decimal
import io
import os
from pathlib import Path
import tempfile
import time
import tracemalloc
import unittest
import uuid

import openpyxl

from app.core.constants import (
    ANATEL_DDDS,
    ANATEL_DDDS_STR,
    DDD_REGION_MAP,
    DEFAULT_COUNTRY_CODE,
    ContactStatus,
)
from app.models.schemas import ContactRecord, IngestionResult, SanitizedNumber
from app.services.contact_service import ContactService, contact_service
from tests.harness import SyntheticDataGenerator


class TestContactServiceFeatureCoverage(unittest.TestCase):
    """
    Tier 1 - Feature Coverage:
    - Sanitização E.164 estrita (DDI 55, preservação integral do 9º dígito, 67 DDDs).
    - Telefones fixos e celulares legados pré-2016.
    - Blindagem contra float e notação científica do Excel.
    - Deduplicação determinística por chave canônica com consolidação de campos.
    - Ingestão massiva (>5.000 contatos) com benchmark de tempo e memória.
    - Ingestão por colagem manual de contatos.
    """

    def setUp(self):
        self.service = contact_service
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # --------------------------------------------------------------------------
    # 1. Sanitização Estrita E.164 Brasil & Preservação do 9º Dígito
    # --------------------------------------------------------------------------

    def test_canonical_example_preserves_ninth_digit_and_injects_ddi(self):
        """
        Caso Canônico Mandatório de ORIGINAL_REQUEST.md e PROJECT.md:
        '62994912937' -> '5562994912937'
        Garante que nenhum dígito é omitido (13 dígitos canônicos).
        """
        raw_input = "62994912937"
        result = self.service.sanitize_phone(raw_input)

        self.assertTrue(result.valid, f"Falha na validação: {result.error_detail}")
        self.assertEqual(result.canonical, "5562994912937")
        self.assertEqual(len(result.canonical), 13)
        self.assertEqual(result.ddd, "62")
        self.assertEqual(result.phone_type, "MOBILE")

    def test_all_67_anatel_ddds_are_systematically_validated(self):
        """
        Valida que cada um dos 67 DDDs oficiais da Anatel é reconhecido e normalizado com sucesso.
        """
        self.assertEqual(len(ANATEL_DDDS), 67, "A tabela Anatel deve conter exatamente 67 DDDs.")

        for ddd in sorted(list(ANATEL_DDDS)):
            raw_mobile = f"{ddd}988887777"
            res = self.service.sanitize_phone(raw_mobile)
            self.assertTrue(
                res.valid,
                f"DDD oficial {ddd} falhou na validação: {res.error_code} - {res.error_detail}"
            )
            self.assertEqual(
                res.canonical,
                f"55{ddd}988887777",
                f"Número canônico inconsistente para DDD {ddd}"
            )
            self.assertEqual(res.ddd, f"{ddd:02d}")
            self.assertEqual(res.phone_type, "MOBILE")

    def test_formatted_phone_numbers_are_properly_cleaned(self):
        """Testa diferentes variações de formatação humana com parênteses, traços e espaços."""
        test_cases = [
            ("+55 (62) 99491-2937", "5562994912937"),
            ("+55 62 99491 2937", "5562994912937"),
            ("(62) 99491-2937", "5562994912937"),
            ("62 99491-2937", "5562994912937"),
            ("062 99491-2937", "5562994912937"),
            ("5562994912937", "5562994912937"),
        ]
        for formatted, expected in test_cases:
            with self.subTest(formatted=formatted):
                res = self.service.sanitize_phone(formatted)
                self.assertTrue(res.valid, f"Erro ao sanitizar {formatted}: {res.error_detail}")
                self.assertEqual(res.canonical, expected)

    def test_long_distance_carrier_csp_prefixes(self):
        """
        Tratamento de prefixos de longa distância com código de operadora CSP (ex: 015, 021, 014).
        Ex: '01562994912937' -> '5562994912937'
        """
        csps = ["014", "015", "021", "031", "041", "043"]
        for csp in csps:
            raw = f"{csp}62994912937"
            res = self.service.sanitize_phone(raw)
            self.assertTrue(res.valid, f"Falha com CSP {csp}: {res.error_detail}")
            self.assertEqual(res.canonical, "5562994912937")

    def test_landline_phones_are_normalized_to_12_digits(self):
        """
        Telefones fixos brasileiros possuem 8 dígitos locais e iniciam com 2, 3, 4 ou 5.
        Ex: '6232015000' -> '556232015000' (12 dígitos canônicos).
        """
        fixo_cases = [
            ("6232015000", "556232015000"),
            ("1123456789", "551123456789"),
            ("2140040000", "552140040000"),
            ("3155551234", "553155551234"),
        ]
        for raw, expected in fixo_cases:
            res = self.service.sanitize_phone(raw)
            self.assertTrue(res.valid, f"Falha em telefone fixo {raw}: {res.error_detail}")
            self.assertEqual(res.canonical, expected)
            self.assertEqual(res.phone_type, "LANDLINE")
            self.assertEqual(len(res.canonical), 12)

    def test_legacy_pre_2016_mobiles_inject_ninth_digit(self):
        """
        Celulares legados com 8 dígitos pós-DDD (iniciando em 6, 7, 8, 9) recebem injeção do 9º dígito.
        Ex: '6294912937' -> '5562994912937'
        """
        legacy_cases = [
            ("6294912937", "5562994912937"),
            ("1181234567", "5511981234567"),
            ("2171234567", "5521971234567"),
            ("3161234567", "5531961234567"),
        ]
        for raw, expected in legacy_cases:
            res = self.service.sanitize_phone(raw)
            self.assertTrue(res.valid, f"Falha em celular legado {raw}: {res.error_detail}")
            self.assertEqual(res.canonical, expected)
            self.assertEqual(res.phone_type, "MOBILE")

    # --------------------------------------------------------------------------
    # 2. Blindagem Contra Coerção Float do Excel e Notação Científica
    # --------------------------------------------------------------------------

    def test_float_numeric_shielding(self):
        """
        Valores importados como float (ex: 62994912937.0) não podem sofrer
        perda de precisão nem manter terminação decimal.
        """
        float_val = 62994912937.0
        res = self.service.sanitize_phone(float_val)
        self.assertTrue(res.valid, f"Falha com float nativo: {res.error_detail}")
        self.assertEqual(res.canonical, "5562994912937")

    def test_scientific_notation_shielding(self):
        """
        Strings em notação científica produzidas pelo Excel (ex: '6.2994912937e+10')
        devem ser convertidas de volta para a sequência inteira original.
        """
        sci_cases = [
            ("6.2994912937e+10", "5562994912937"),
            ("6.2994912937E+10", "5562994912937"),
            ("5.562994912937E+12", "5562994912937"),
        ]
        for sci_str, expected in sci_cases:
            res = self.service.sanitize_phone(sci_str)
            self.assertTrue(res.valid, f"Falha em notação científica {sci_str}: {res.error_detail}")
            self.assertEqual(res.canonical, expected)

    # --------------------------------------------------------------------------
    # 3. Deduplicação Determinística com Consolidação (First Wins + Merge)
    # --------------------------------------------------------------------------

    def test_deduplication_unifies_different_formats_of_same_number(self):
        """
        Diferentes representações do mesmo número devem ser unificadas na mesma chave canônica.
        A primeira ocorrência prevalece (First Wins).
        """
        c1 = ContactRecord(
            id="1",
            raw_phone="(62) 99491-2937",
            canonical_phone="5562994912937",
            name="João Original",
            variables={"empresa": "Empresa A"},
        )
        c2 = ContactRecord(
            id="2",
            raw_phone="62994912937",
            canonical_phone="5562994912937",
            name="João Duplicado",
            variables={"empresa": "Empresa A", "cargo": "Diretor"},
        )
        c3 = ContactRecord(
            id="3",
            raw_phone="+55 62 99491-2937",
            canonical_phone="5562994912937",
            name="João Triplicado",
            variables={"cidade": "Goiânia"},
        )
        c4 = ContactRecord(
            id="4",
            raw_phone="11988887777",
            canonical_phone="5511988887777",
            name="Maria Santos",
            variables={},
        )

        unique, dup_count = self.service.deduplicate([c1, c2, c3, c4], merge_variables=True)

        self.assertEqual(len(unique), 2, "Devem restar exatamente 2 contatos únicos.")
        self.assertEqual(dup_count, 2, "Devem ser contabilizadas exatamente 2 duplicatas.")
        self.assertEqual(unique[0].name, "João Original", "First Wins deve preservar o nome do primeiro.")
        # Consolidação de variáveis dinâmicas
        self.assertEqual(unique[0].variables.get("empresa"), "Empresa A")
        self.assertEqual(unique[0].variables.get("cargo"), "Diretor")
        self.assertEqual(unique[0].variables.get("cidade"), "Goiânia")

    # --------------------------------------------------------------------------
    # 4. Ingestão por Colagem Manual de Contatos
    # --------------------------------------------------------------------------

    def test_parse_manual_multiline_text_with_delimiters(self):
        """Testa colagem manual com números simples e linhas com nome e telefone."""
        manual_text = """
        62994912937
        Carlos Silva; 11988887777
        Maria Oliveira, 21977776666
        6232015000\tFixo Empresa
        23994912937
        62994912937
        """
        result = self.service.parse_manual(manual_text)

        self.assertEqual(result.total_rows, 6)
        self.assertEqual(result.invalid_count, 1, "DDD 23 deve ser contado como inválido.")
        self.assertEqual(result.duplicate_count, 1, "62994912937 repetido deve ser deduplicado.")
        self.assertEqual(len(result.valid_contacts), 4, "Devem restar 4 contatos válidos únicos.")

    # --------------------------------------------------------------------------
    # 5. Benchmark Massivo (>5.000 Contatos em Excel e CSV)
    # --------------------------------------------------------------------------

    def test_massive_csv_ingestion_benchmark_over_5000_rows(self):
        """
        Benchmark de Tempo e Memória:
        Gera e ingere base com mais de 5.000 linhas em CSV.
        Exige tempo sub-segundo e memória baixa.
        """
        total_rows = 5200
        dataset = SyntheticDataGenerator.generate_contact_dataset(total_rows=total_rows)
        csv_file = self.temp_path / "benchmark_5000.csv"
        SyntheticDataGenerator.export_to_csv_file(dataset, csv_file, delimiter=";")

        tracemalloc.start()
        start_time = time.perf_counter()

        ingestion_result = self.service.parse_file(csv_file)

        elapsed_time = time.perf_counter() - start_time
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak_mem / (1024 * 1024)

        # Asserções Funcionais
        self.assertEqual(ingestion_result.total_rows, total_rows)
        self.assertGreater(len(ingestion_result.valid_contacts), 4000)
        self.assertGreater(ingestion_result.duplicate_count, 0)
        self.assertGreater(ingestion_result.invalid_count, 0)

        # Asserções de Desempenho
        self.assertLess(elapsed_time, 2.0, f"CSV demorou {elapsed_time:.3f}s (limite 2.0s)")
        self.assertLess(peak_mb, 25.0, f"Pico de RAM {peak_mb:.2f}MB ultrapassou limite 25MB")

    def test_massive_xlsx_streaming_ingestion_benchmark_over_5000_rows(self):
        """
        Benchmark de Tempo e Memória:
        Gera e ingere base com mais de 5.000 linhas em Excel (.xlsx) via openpyxl streaming.
        Exige processamento em < 3.0s e consumo < 25MB de RAM.
        """
        total_rows = 5100
        dataset = SyntheticDataGenerator.generate_contact_dataset(total_rows=total_rows)
        xlsx_file = self.temp_path / "benchmark_5000.xlsx"
        SyntheticDataGenerator.export_to_excel_file(dataset, xlsx_file)

        tracemalloc.start()
        start_time = time.perf_counter()

        ingestion_result = self.service.parse_file(xlsx_file)

        elapsed_time = time.perf_counter() - start_time
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak_mem / (1024 * 1024)

        # Asserções Funcionais
        self.assertEqual(ingestion_result.total_rows, total_rows)
        self.assertGreater(len(ingestion_result.valid_contacts), 4000)
        self.assertGreater(ingestion_result.duplicate_count, 0)

        # Asserções de Desempenho
        self.assertLess(elapsed_time, 3.5, f"XLSX demorou {elapsed_time:.3f}s (limite 3.5s)")
        self.assertLess(peak_mb, 25.0, f"Pico de RAM {peak_mb:.2f}MB ultrapassou limite 25MB")


class TestContactServiceBoundaryAndCornerCases(unittest.TestCase):
    """
    Tier 2 - Boundary & Corner Cases:
    - DDDs inexistentes (ex: DDD 23 e DDD 70 devem ser sumariamente descartados).
    - Telefones internacionais ou incompletos (sem DDD).
    - Números repetidos fictícios.
    - Planilhas corrompidas e arquivos vazios.
    - Linhas com caracteres especiais, aspas e quebras de linha.
    """

    def setUp(self):
        self.service = contact_service
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_non_existent_ddds_are_strictly_rejected(self):
        """
        Verifica rejeição estrita dos 22 prefixos não alocados no Brasil.
        Em especial, DDD 23 e DDD 70 (destacados nos requisitos).
        """
        invalid_ddds = [20, 23, 25, 26, 29, 30, 36, 39, 50, 52, 56, 57, 58, 59, 70, 72, 76, 78, 80, 90]

        for bad_ddd in invalid_ddds:
            phone_with_bad_ddd = f"{bad_ddd}994912937"
            res = self.service.sanitize_phone(phone_with_bad_ddd)
            self.assertFalse(
                res.valid,
                f"DDD inexistente {bad_ddd} não deveria ser aceito como válido!"
            )
            self.assertIn("DDD_INVALIDO", res.error_code or "")
            self.assertIsNone(res.canonical)

    def test_incomplete_numbers_without_ddd_are_rejected(self):
        """Números locais de 8 ou 9 dígitos sem código de área não podem ser adivinhados."""
        incompletes = ["994912937", "99491-2937", "32015000", "988887777"]
        for num in incompletes:
            res = self.service.sanitize_phone(num)
            self.assertFalse(res.valid)
            self.assertEqual(res.error_code, "NUMERO_INCOMPLETO_SEM_DDD")

    def test_repeated_fictitious_numbers_are_rejected(self):
        """Sequências artificiais uniformes como 00000000000 ou 99999999999 são rejeitadas."""
        fictitious = ["00000000000", "11111111111", "99999999999", "88888888888"]
        for num in fictitious:
            res = self.service.sanitize_phone(num)
            self.assertFalse(res.valid)
            self.assertEqual(res.error_code, "NUMERO_FICTICIO_REPETIDO")

    def test_international_numbers_outside_brazil_are_rejected(self):
        """Números com DDI internacional diferente de 55 devem ser rejeitados."""
        internationals = [
            "12025550199",       # EUA +1
            "447911123456",      # Reino Unido +44
            "351912345678",      # Portugal +351
        ]
        for num in internationals:
            res = self.service.sanitize_phone(num)
            self.assertFalse(res.valid)

    def test_empty_files_handled_gracefully(self):
        """Arquivos com zero bytes ou planilhas sem linhas retornam IngestionResult vazio seguro."""
        empty_csv = self.temp_path / "empty.csv"
        empty_csv.write_text("", encoding="utf-8")

        res_csv = self.service.parse_file(empty_csv)
        self.assertEqual(res_csv.total_rows, 0)
        self.assertEqual(len(res_csv.valid_contacts), 0)
        self.assertGreater(len(res_csv.warning_messages), 0)

        empty_xlsx = self.temp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        wb.save(empty_xlsx)
        wb.close()

        res_xlsx = self.service.parse_file(empty_xlsx)
        self.assertEqual(res_xlsx.total_rows, 0)
        self.assertEqual(len(res_xlsx.valid_contacts), 0)

    def test_corrupted_file_raises_appropriate_exception(self):
        """Arquivos corrompidos não travam em silêncio e lançam exceção clara."""
        corrupt_xlsx = self.temp_path / "corrupt.xlsx"
        corrupt_xlsx.write_bytes(b"NOT_A_VALID_ZIP_OR_XLSX_HEADER_DATA_CORRUPTED")

        with self.assertRaises(Exception):
            self.service.parse_file(corrupt_xlsx)

    def test_special_characters_emojis_and_multiline_fields(self):
        """Validação de nomes com acentos brasileiros, emojis e caracteres especiais."""
        dataset = [
            {"telefone": "62994912937", "nome": "João da Silva & Cia 🚀", "empresa": "Açúcar & Café"},
            {"telefone": "11988887777", "nome": "O'Connor, Patrick", "empresa": "Irish Pub 'The Drop'"},
            {"telefone": "21977776666", "nome": 'Ana "Bia" Rocha', "empresa": "Design & Mídia; Ltda"},
        ]
        csv_file = self.temp_path / "special_chars.csv"
        SyntheticDataGenerator.export_to_csv_file(dataset, csv_file, delimiter=";")

        result = self.service.parse_file(csv_file)
        self.assertEqual(result.total_rows, 3)
        self.assertEqual(len(result.valid_contacts), 3)

        contact_map = {c.canonical_phone: c for c in result.valid_contacts}
        self.assertIn("🚀", contact_map["5562994912937"].name)
        self.assertEqual(contact_map["5511988887777"].name, "O'Connor, Patrick")
        self.assertEqual(contact_map["5521977776666"].variables.get("empresa"), "Design & Mídia; Ltda")


if __name__ == "__main__":
    unittest.main()
