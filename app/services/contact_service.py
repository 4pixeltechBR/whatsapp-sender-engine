"""
High-Performance Contact Management and Ingestion Service for WhatsApp Sender Engine.
Handles streaming file parsing (Excel/CSV), strict E.164 sanitization (Anatel 67 DDDs,
9th digit preservation, float shielding), and deterministic deduplication.
"""

import csv
from decimal import Decimal
import math
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union
import uuid

import openpyxl

from app.core.constants import (
    ANATEL_DDDS,
    ANATEL_DDDS_STR,
    DDD_REGION_MAP,
    DEFAULT_COUNTRY_CODE,
    ContactStatus,
    RE_NON_DIGITS,
    RE_PHONE_HEADER,
    RE_NAME_HEADER,
)
from app.models.schemas import ContactRecord, IngestionResult, SanitizedNumber



class ContactService:
    """Serviço principal de ingestão, sanitização e desduplicação de contatos."""

    def __init__(self):
        self.anatel_ddds = ANATEL_DDDS
        self.anatel_ddds_str = ANATEL_DDDS_STR

    # --------------------------------------------------------------------------
    # 1. Blindagem contra Float e Conversão Estrita de Tipos
    # --------------------------------------------------------------------------

    @staticmethod
    def _extract_raw_digits_string(value: Any) -> str:
        """
        Extrai a representação textual pura de qualquer valor,
        blindando contra coerção float do Excel e notação científica.
        Ex: 62994912937.0 -> "62994912937"
        Ex: "6.2994912937e+10" -> "62994912937"
        """
        if value is None:
            return ""

        if isinstance(value, int):
            return str(value)

        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return ""
            try:
                # Utiliza Decimal para evitar perda de precisão em ponto flutuante
                d = Decimal(str(value))
                return f"{d:.0f}"
            except Exception:
                return f"{value:.0f}"

        val_str = str(value).strip()
        if not val_str:
            return ""

        # Verifica notação científica em formato texto (ex: "6.2994912937e+10" ou "5.56299E+12")
        if ("e" in val_str or "E" in val_str) and any(c.isdigit() for c in val_str):
            try:
                d = Decimal(val_str)
                return f"{d:.0f}"
            except Exception:
                try:
                    f = float(val_str)
                    if not (math.isnan(f) or math.isinf(f)):
                        return f"{f:.0f}"
                except Exception:
                    pass

        # Trata números terminados em .0 ou .00 provenientes de exportações tabulares
        if val_str.endswith(".0"):
            val_str = val_str[:-2]
        elif "." in val_str:
            parts = val_str.split(".", 1)
            if len(parts) == 2 and parts[1].isdigit() and set(parts[1]) <= {"0"}:
                val_str = parts[0]

        return val_str

    # --------------------------------------------------------------------------
    # 2. Sanitização E.164 Rigorosa (Padrão Brasil Anatel)
    # --------------------------------------------------------------------------

    def sanitize_phone(self, raw_value: Any) -> SanitizedNumber:
        """
        Higieniza e normaliza qualquer número para o padrão internacional E.164 brasileiro.
        - Injeta DDI 55
        - Valida estritamente contra os 67 DDDs oficiais da Anatel
        - Preserva integralmente o 9º dígito em celulares (ex: 62994912937 -> 5562994912937)
        - Injeta o 9º dígito em celulares legados pré-2016
        - Suporta telefones fixos (8 dígitos locais, ex: 556232015000)
        - Remove códigos de operadora (CSP: 015, 021, etc.) e zeros de longa distância
        """
        raw_str = self._extract_raw_digits_string(raw_value)
        if not raw_str:
            return SanitizedNumber(
                raw=str(raw_value) if raw_value is not None else "",
                valid=False,
                error_code="VAZIO_OU_NULO",
                error_detail="Número não informado ou nulo",
            )

        # Remove todos os caracteres não numéricos
        digits = RE_NON_DIGITS.sub("", raw_str)
        if not digits:
            return SanitizedNumber(
                raw=str(raw_value),
                valid=False,
                error_code="SEM_DIGITOS",
                error_detail="A entrada não contém dígitos numéricos",
            )

        # Rejeita números com dígitos uniformemente repetidos (ex: 00000000000, 99999999999)
        if len(digits) >= 8 and digits[0] * len(digits) == digits:
            return SanitizedNumber(
                raw=str(raw_value),
                valid=False,
                error_code="NUMERO_FICTICIO_REPETIDO",
                error_detail="Número fictício com todos os dígitos idênticos",
            )

        # Rejeita entradas com menos de 10 dígitos (impossível conter DDD + número com segurança)
        if len(digits) < 10:
            return SanitizedNumber(
                raw=str(raw_value),
                valid=False,
                error_code="NUMERO_INCOMPLETO_SEM_DDD",
                error_detail=f"Número possui apenas {len(digits)} dígitos; DDD obrigatório",
            )

        # Tratamento de prefixo de longa distância com CSP (Código de Seleção de Prestadora)
        # Ex: 01562994912937 (14 dígitos) -> CSP 15, DDD 62 -> remove 015 -> 11 dígitos
        # Ex: 0156232015000 (13 dígitos) -> CSP 15, DDD 62 -> remove 015 -> 10 dígitos
        if digits.startswith("0") and len(digits) in (13, 14) and digits[1:3].isdigit():
            digits = digits[3:]
        # Ex: 062994912937 (12 dígitos com zero inicial) -> remove 0 -> 11 dígitos
        elif digits.startswith("0") and len(digits) in (11, 12):
            digits = digits[1:]
        # Ex: 5501562994912937 (16 dígitos com DDI 55 + 015) -> remove 015
        elif digits.startswith("550") and len(digits) in (15, 16):
            digits = "55" + digits[5:]
        # Ex: 55062994912937 (14 dígitos com DDI 55 + 0) -> remove 0
        elif digits.startswith("550") and len(digits) in (13, 14):
            digits = "55" + digits[3:]

        # Pipeline de resolução por comprimento de dígitos
        canonical: Optional[str] = None
        ddd_code: Optional[str] = None
        phone_type: Optional[str] = None
        error_code: Optional[str] = None
        error_detail: Optional[str] = None

        # CASO 1: 11 dígitos (Padrão celular nacional sem DDI: DDD + 9 dígitos)
        # Exemplo canônico do projeto: 62994912937
        if len(digits) == 11:
            ddd_code = digits[:2]
            if ddd_code not in self.anatel_ddds_str:
                error_code = f"DDD_INVALIDO_{ddd_code}"
                error_detail = f"O DDD {ddd_code} não é homologado pela Anatel"
            elif digits[2] == "9":
                # Celular moderno de 9 dígitos
                canonical = f"{DEFAULT_COUNTRY_CODE}{digits}"
                phone_type = "MOBILE"
            else:
                error_code = "CELULAR_11_DIGITOS_SEM_NONO_DIGITO"
                error_detail = "Celulares de 11 dígitos no Brasil devem ter o 9 como primeiro dígito local"

        # CASO 2: 13 dígitos (Padrão celular nacional com DDI: 55 + DDD + 9 dígitos)
        # Exemplo: 5562994912937
        elif len(digits) == 13:
            if not digits.startswith(DEFAULT_COUNTRY_CODE):
                error_code = "DDI_INVALIDO_NAO_BRASIL"
                error_detail = f"DDI inicial '{digits[:2]}' não corresponde ao Brasil (55)"
            else:
                ddd_code = digits[2:4]
                if ddd_code not in self.anatel_ddds_str:
                    error_code = f"DDD_INVALIDO_{ddd_code}"
                    error_detail = f"O DDD {ddd_code} não é homologado pela Anatel"
                elif digits[4] == "9":
                    canonical = digits
                    phone_type = "MOBILE"
                else:
                    error_code = "CELULAR_13_DIGITOS_SEM_NONO_DIGITO"
                    error_detail = "Número celular de 13 dígitos deve ter '9' após o DDD"

        # CASO 3: 10 dígitos (DDD + 8 dígitos - Fixo ou Celular legado pré-2016)
        # Exemplo fixo: 6232015000 -> 556232015000
        # Exemplo celular legado: 6294912937 -> 5562994912937
        elif len(digits) == 10:
            ddd_code = digits[:2]
            if ddd_code not in self.anatel_ddds_str:
                error_code = f"DDD_INVALIDO_{ddd_code}"
                error_detail = f"O DDD {ddd_code} não é homologado pela Anatel"
            else:
                first_local = digits[2]
                if first_local in "2345":
                    # Telefone fixo brasileiro (8 dígitos)
                    canonical = f"{DEFAULT_COUNTRY_CODE}{digits}"
                    phone_type = "LANDLINE"
                elif first_local in "6789":
                    # Celular legado pré-2016 sem 9º dígito: injeta o '9'
                    canonical = f"{DEFAULT_COUNTRY_CODE}{ddd_code}9{digits[2:]}"
                    phone_type = "MOBILE"
                else:
                    error_code = "PREFIXO_LOCAL_INVALIDO"
                    error_detail = f"Prefixo local '{first_local}' inválido para telefonia brasileira"

        # CASO 4: 12 dígitos (55 + DDD + 8 dígitos - Fixo com DDI ou Celular legado com DDI)
        # Exemplo fixo com 55: 556232015000 -> 556232015000
        # Exemplo celular legado com 55: 556294912937 -> 5562994912937
        elif len(digits) == 12:
            if not digits.startswith(DEFAULT_COUNTRY_CODE):
                error_code = "DDI_INVALIDO_NAO_BRASIL"
                error_detail = f"Número de 12 dígitos com DDI desconhecido: '{digits[:2]}'"
            else:
                ddd_code = digits[2:4]
                if ddd_code not in self.anatel_ddds_str:
                    error_code = f"DDD_INVALIDO_{ddd_code}"
                    error_detail = f"O DDD {ddd_code} não é homologado pela Anatel"
                else:
                    first_local = digits[4]
                    if first_local in "2345":
                        # Telefone fixo com DDI
                        canonical = digits
                        phone_type = "LANDLINE"
                    elif first_local in "6789":
                        # Celular legado com DDI sem o 9º dígito: injeta o '9'
                        canonical = f"{DEFAULT_COUNTRY_CODE}{ddd_code}9{digits[4:]}"
                        phone_type = "MOBILE"
                    else:
                        error_code = "PREFIXO_LOCAL_INVALIDO"
                        error_detail = f"Prefixo local '{first_local}' inválido para telefonia brasileira"

        else:
            error_code = f"COMPRIMENTO_INVALIDO_{len(digits)}_DIGITOS"
            error_detail = f"Número com {len(digits)} dígitos não é compatível com o plano de numeração nacional"

        if canonical:
            region_name = DDD_REGION_MAP.get(ddd_code or "", "Brasil")
            return SanitizedNumber(
                raw=str(raw_value),
                canonical=canonical,
                valid=True,
                error_code=None,
                error_detail=None,
                ddd=ddd_code,
                region=region_name,
                phone_type=phone_type,
            )

        return SanitizedNumber(
            raw=str(raw_value),
            canonical=None,
            valid=False,
            error_code=error_code,
            error_detail=error_detail,
            ddd=ddd_code,
            region=None,
            phone_type=None,
        )

    # --------------------------------------------------------------------------
    # 3. Mapeamento Heurístico Inteligente de Colunas
    # --------------------------------------------------------------------------

    def detect_column_mapping(
        self,
        headers: List[str],
        sample_rows: List[List[Any]],
    ) -> Dict[str, Optional[str]]:
        """
        Identifica automaticamente qual coluna corresponde ao Telefone e qual ao Nome.
        Utiliza regex nos cabeçalhos e validação por amostragem de dados.
        """
        phone_col: Optional[str] = None
        name_col: Optional[str] = None

        clean_headers = [str(h).strip() if h is not None else "" for h in headers]

        # 1. Tenta identificar pelos nomes dos cabeçalhos
        for h in clean_headers:
            if not h:
                continue
            if not phone_col and RE_PHONE_HEADER.search(h):
                phone_col = h
            elif not name_col and RE_NAME_HEADER.search(h):
                name_col = h

        # 2. Se a coluna de telefone não foi identificada, testa os dados das primeiras linhas
        if not phone_col and sample_rows and clean_headers:
            best_phone_score = -1
            best_col = None

            for col_idx, h in enumerate(clean_headers):
                valid_count = 0
                total_tested = 0
                for row in sample_rows[:20]:
                    if col_idx < len(row) and row[col_idx] is not None:
                        val = row[col_idx]
                        total_tested += 1
                        res = self.sanitize_phone(val)
                        if res.valid:
                            valid_count += 1
                if total_tested > 0:
                    score = valid_count / total_tested
                    if score > best_phone_score and score >= 0.3:
                        best_phone_score = score
                        best_col = h

            if best_col:
                phone_col = best_col

        # 3. Se a coluna de nome ainda não foi identificada, escolhe a primeira coluna textual restante
        if not name_col and clean_headers:
            for h in clean_headers:
                if h != phone_col:
                    name_col = h
                    break

        return {
            "phone_column": phone_col,
            "name_column": name_col,
        }

    # --------------------------------------------------------------------------
    # 4. Leitor Streaming de Planilhas Excel (.xlsx) via openpyxl
    # --------------------------------------------------------------------------

    def read_excel_streaming(
        self,
        file_path: Union[str, Path],
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Lê arquivos .xlsx em streaming (read_only=True, data_only=True).
        Consumo O(1) de memória (<15MB RAM) mesmo para >50.000 linhas.
        """
        wb = openpyxl.load_workbook(filename=str(file_path), read_only=True, data_only=True)
        try:
            sheet = wb.active
            if sheet is None:
                return

            header_row: Optional[List[str]] = None

            for row in sheet.iter_rows(values_only=True):
                # Ignora linhas totalmente vazias
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue

                if header_row is None:
                    # Primeira linha válida define os cabeçalhos
                    header_row = [
                        str(cell).strip() if cell is not None else f"coluna_{idx}"
                        for idx, cell in enumerate(row)
                    ]
                    continue

                # Mapeia os valores para os cabeçalhos
                row_dict: Dict[str, Any] = {}
                for idx, col_name in enumerate(header_row):
                    val = row[idx] if idx < len(row) else None
                    row_dict[col_name] = val

                yield row_dict

        finally:
            wb.close()

    # --------------------------------------------------------------------------
    # 5. Leitor Streaming de CSV com Auto-Detecção de Encoding e Delimitador
    # --------------------------------------------------------------------------

    def read_csv_streaming(
        self,
        file_path: Union[str, Path],
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Lê arquivos CSV com detecção automática de delimitadores (;, ,, \\t, |)
        e encodings (utf-8-sig, utf-8, cp1252, iso-8859-1).
        """
        encodings_to_try = ["utf-8-sig", "utf-8", "cp1252", "iso-8859-1", "latin-1"]
        target_path = Path(file_path)

        chosen_encoding: Optional[str] = None
        for enc in encodings_to_try:
            try:
                with open(target_path, "r", encoding=enc) as f:
                    f.read(4096)
                chosen_encoding = enc
                break
            except (UnicodeDecodeError, Exception):
                continue

        if not chosen_encoding:
            chosen_encoding = "utf-8-sig"

        # Detecta delimitador a partir de amostra do arquivo
        with open(target_path, "r", encoding=chosen_encoding, errors="replace") as f:
            sample = f.read(4096)

        delimiter = ";"
        try:
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(sample, delimiters=[";", ",", "\t", "|"])
            delimiter = dialect.delimiter
        except Exception:
            # Heurística de contagem simples caso o Sniffer falhe
            first_line = sample.splitlines()[0] if sample else ""
            counts = {
                ";": first_line.count(";"),
                ",": first_line.count(","),
                "\t": first_line.count("\t"),
                "|": first_line.count("|"),
            }
            best_delim = max(counts, key=counts.get)
            if counts[best_delim] > 0:
                delimiter = best_delim

        with open(target_path, "r", encoding=chosen_encoding, errors="replace") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                # Remove espaços em branco das chaves e valores
                cleaned_row = {
                    (k.strip() if k else f"col_{i}"): (v.strip() if isinstance(v, str) else v)
                    for i, (k, v) in enumerate(row.items())
                    if k is not None
                }
                yield cleaned_row

    # --------------------------------------------------------------------------
    # 6. Deduplicação Determinística com Consolidação (First Wins + Merge)
    # --------------------------------------------------------------------------

    def deduplicate(
        self,
        contacts: List[ContactRecord],
        merge_variables: bool = True,
    ) -> Tuple[List[ContactRecord], int]:
        """
        Deduplica contatos pela chave canônica E.164.
        Mantém a primeira ocorrência (First Wins) e consolida variáveis extras
        presentes em duplicatas subsequentes.
        """
        seen_phones: Dict[str, ContactRecord] = {}
        unique_contacts: List[ContactRecord] = []
        duplicate_count = 0

        for contact in contacts:
            canon = contact.canonical_phone
            if not canon:
                continue

            if canon in seen_phones:
                duplicate_count += 1
                if merge_variables:
                    primary = seen_phones[canon]
                    # Preenche nome se estava em branco no original
                    if not primary.name and contact.name:
                        primary.name = contact.name
                    # Merge de variáveis dinâmicas ausentes ou vazias
                    for k, v in contact.variables.items():
                        if v and (k not in primary.variables or not primary.variables[k]):
                            primary.variables[k] = v
            else:
                seen_phones[canon] = contact
                unique_contacts.append(contact)

        return unique_contacts, duplicate_count

    # --------------------------------------------------------------------------
    # 7. Ingestão Completa de Arquivos (.xlsx, .csv, .xls)
    # --------------------------------------------------------------------------

    def parse_file(
        self,
        file_path: Union[str, Path],
        phone_col: Optional[str] = None,
        name_col: Optional[str] = None,
        max_rows: Optional[int] = None,
    ) -> IngestionResult:
        """
        Processa arquivo completo de contatos em streaming com sanitização e deduplicação.
        Retorna IngestionResult com métricas completas de conformidade.
        """
        target_path = Path(file_path)
        if not target_path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {target_path}")

        suffix = target_path.suffix.lower()
        warnings: List[str] = []

        # Obtém o gerador de streaming adequado
        if suffix in (".xlsx", ".xlsm"):
            stream_gen = self.read_excel_streaming(target_path)
        elif suffix in (".csv", ".tsv", ".txt"):
            stream_gen = self.read_csv_streaming(target_path)
        elif suffix == ".xls":
            # Tenta fallback via pandas para arquivos XLS legados
            try:
                import pandas as pd
                df = pd.read_excel(target_path, dtype=str)
                stream_gen = (row.to_dict() for _, row in df.iterrows())
            except Exception as e:
                raise ValueError(
                    f"Erro ao ler arquivo .xls legado. Converta para .xlsx ou .csv: {e}"
                )
        else:
            raise ValueError(f"Formato de arquivo não suportado: '{suffix}'")

        # Lê uma pequena amostra para auto-detectar mapeamento de colunas se não especificado
        initial_rows: List[Dict[str, Any]] = []
        try:
            for _ in range(25):
                row = next(stream_gen)
                initial_rows.append(row)
        except StopIteration:
            pass

        if not initial_rows:
            return IngestionResult(
                total_rows=0,
                valid_contacts=[],
                duplicate_count=0,
                invalid_count=0,
                warning_messages=["O arquivo está vazio ou não possui linhas válidas"],
            )

        headers = list(initial_rows[0].keys())
        sample_matrix = [[r.get(h) for h in headers] for r in initial_rows]

        if not phone_col or not name_col:
            detected = self.detect_column_mapping(headers, sample_matrix)
            if not phone_col:
                phone_col = detected["phone_column"]
            if not name_col:
                name_col = detected["name_column"]

        if not phone_col:
            # Fallback definitivo: utiliza a primeira coluna
            phone_col = headers[0]
            warnings.append(
                f"Coluna de telefone não identificada explicitamente. Utilizando '{phone_col}'."
            )

        # Processamento das linhas
        total_rows = 0
        valid_records: List[ContactRecord] = []
        invalid_count = 0

        def process_single_row(row_data: Dict[str, Any]):
            nonlocal total_rows, invalid_count
            total_rows += 1

            raw_phone_val = row_data.get(phone_col)
            sanitized = self.sanitize_phone(raw_phone_val)

            name_val = ""
            if name_col and name_col in row_data and row_data[name_col] is not None:
                name_val = str(row_data[name_col]).strip()
            if not name_val:
                name_val = f"Contato {total_rows}"

            # Coleta todas as outras colunas como variáveis dinâmicas
            variables: Dict[str, str] = {}
            for col_k, col_v in row_data.items():
                if col_k not in (phone_col, name_col) and col_v is not None:
                    variables[col_k] = str(col_v).strip()

            if sanitized.valid and sanitized.canonical:
                record = ContactRecord(
                    id=str(uuid.uuid4()),
                    raw_phone=str(raw_phone_val) if raw_phone_val is not None else "",
                    canonical_phone=sanitized.canonical,
                    name=name_val,
                    variables=variables,
                    status=ContactStatus.PENDING,
                )
                valid_records.append(record)
            else:
                invalid_count += 1

        # Processa as linhas iniciais já consumidas da amostra
        for r in initial_rows:
            if max_rows and total_rows >= max_rows:
                break
            process_single_row(r)

        # Continua consumindo o restante do stream
        for r in stream_gen:
            if max_rows and total_rows >= max_rows:
                break
            process_single_row(r)

        # Deduplica os contatos válidos por chave canônica E.164
        unique_valid, duplicate_count = self.deduplicate(valid_records, merge_variables=True)

        return IngestionResult(
            total_rows=total_rows,
            valid_contacts=unique_valid,
            duplicate_count=duplicate_count,
            invalid_count=invalid_count,
            warning_messages=warnings,
        )

    # --------------------------------------------------------------------------
    # 8. Ingestão por Colagem Manual de Contatos
    # --------------------------------------------------------------------------

    def parse_manual(
        self,
        text: str,
        default_name_prefix: str = "Contato",
    ) -> IngestionResult:
        """
        Processa texto colado manualmente com suporte a linhas simples ou delimitadas
        por vírgula, ponto-e-vírgula ou tabulação (ex: 'Nome, Telefone' ou apenas 'Telefone').
        """
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if not lines:
            return IngestionResult(
                total_rows=0,
                valid_contacts=[],
                duplicate_count=0,
                invalid_count=0,
                warning_messages=["Nenhum contato colado"],
            )

        total_rows = 0
        valid_records: List[ContactRecord] = []
        invalid_count = 0

        for idx, line in enumerate(lines, start=1):
            total_rows += 1

            # Detecta se a linha possui delimitador com nome
            raw_phone_part: str = line
            name_part: str = ""

            for delim in [";", "\t", ","]:
                if delim in line:
                    tokens = [t.strip() for t in line.split(delim)]
                    if len(tokens) >= 2:
                        # Identifica qual token é o telefone
                        res0 = self.sanitize_phone(tokens[0])
                        res1 = self.sanitize_phone(tokens[1])
                        if res0.valid:
                            raw_phone_part = tokens[0]
                            name_part = tokens[1]
                        elif res1.valid:
                            name_part = tokens[0]
                            raw_phone_part = tokens[1]
                        else:
                            raw_phone_part = tokens[0]
                            name_part = tokens[1]
                        break

            sanitized = self.sanitize_phone(raw_phone_part)
            if not name_part:
                name_part = f"{default_name_prefix} {idx}"

            if sanitized.valid and sanitized.canonical:
                rec = ContactRecord(
                    id=str(uuid.uuid4()),
                    raw_phone=raw_phone_part,
                    canonical_phone=sanitized.canonical,
                    name=name_part,
                    variables={},
                    status=ContactStatus.PENDING,
                )
                valid_records.append(rec)
            else:
                invalid_count += 1

        unique_valid, duplicate_count = self.deduplicate(valid_records, merge_variables=True)

        return IngestionResult(
            total_rows=total_rows,
            valid_contacts=unique_valid,
            duplicate_count=duplicate_count,
            invalid_count=invalid_count,
            warning_messages=[],
        )


# Singleton exportado para uso em toda a aplicação
contact_service = ContactService()
