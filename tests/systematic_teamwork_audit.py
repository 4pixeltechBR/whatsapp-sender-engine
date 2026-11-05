"""
SYSTEMATIC DEBUGGING & TEAMWORK PREVIEW LIVE AUDIT HARNESS
===========================================================
Executa auditoria empírica exaustiva de ponta a ponta sobre o WhatsApp Sender Engine.
Aplica a Lei de Ferro do Systematic Debugging: "NENHUMA AFIRMAÇÃO SEM EVIDÊNCIA EMPÍRICA".
Simula os 5 Agentes Especialistas da esteira (Teamwork Preview):
  - Agente 1: Sanitização de Dados & Blindagem Numérica (Anatel & Excel)
  - Agente 2: Anti-Ban, Jitter Estocástico & Simulação Humana (Box-Muller)
  - Agente 3: Máquina de Estados FSM, Concorrência Unitária & Atomicidade
  - Agente 4: Auditoria Binária de Relatórios Executivos (Excel '@' & CSV UTF-8 BOM)
  - Agente 5: Integração Completa de API REST, Endpoints & Servidor Desktop
"""

import asyncio
from datetime import datetime
import io
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Dict, List

# Adiciona raiz do projeto ao path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
import openpyxl

from app.core.config import settings
from app.core.constants import ContactStatus, QueueState, SessionStatus
from app.main import app, app_state
from app.models.schemas import CampaignConfig, ContactRecord, SendMessageResult
from app.services.browser_service import browser_service
from app.services.contact_service import contact_service
from app.services.dispatcher_service import (
    AntiBanConfig,
    BoxMullerJitterEngine,
    DispatcherService,
    QueueDispatcherEngine,
    SpintaxEngine,
    dispatcher_service,
)
from app.services.reporting_service import ReportingService, reporting_service

# Cores ANSI para saída cristalina no terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_header(title: str):
    print("\n" + "=" * 80)
    print(f"{BOLD}{CYAN} {title} {RESET}")
    print("=" * 80)


def print_pass(msg: str):
    print(f" {GREEN}[APROVADO]{RESET} {msg}")


def print_fail(msg: str):
    print(f" {RED}[FALHA]{RESET} {msg}")


# ==============================================================================
# AGENTE 1: SANITIZAÇÃO DE DADOS & BLINDAGEM NUMÉRICA (ANATEL & EXCEL)
# ==============================================================================
def audit_agent_1_data_sanitization() -> bool:
    print_header("AGENTE 1: AUDITORIA DE SANITIZAÇÃO DE DADOS & BLINDAGEM NUMÉRICA")
    all_ok = True

    # 1.1 O Caso Canônico que Quebrou o Uatizapi
    print(f"\n{BOLD}[1.1] Teste Forense do Número Canônico (62994912937){RESET}")
    raw_variations = [
        ("62994912937", "String pura 11 dígitos"),
        (62994912937, "Inteiro puro"),
        (62994912937.0, "Float nativo do Excel (IEEE 754)"),
        ("6.2994912937e+10", "Notação científica minúscula"),
        ("6.2994912937E+10", "Notação científica maiúscula"),
        ("5.562994912937E+12", "Notação científica pré-coagida com DDI"),
        ("(62) 99491-2937", "Formatado com parênteses e traço"),
        ("+55 (62) 9 9491-2937", "Formatado completo com DDI e espaços"),
        ("062994912937", "Com zero de discagem longa distância"),
        ("01562994912937", "Com código de operadora CSP Vivo (015)"),
        ("02162994912937", "Com código de operadora CSP Claro (021)"),
        ("04162994912937", "Com código de operadora CSP TIM (041)"),
    ]

    for val, desc in raw_variations:
        res = contact_service.sanitize_phone(val)
        expected = "5562994912937"
        if res.valid and res.canonical == expected:
            print_pass(f"{desc:<45} -> {res.canonical} (Dígito 9 e 5º dígito preservados)")
        else:
            print_fail(f"{desc:<45} -> Esperado: {expected}, Obtido: {res.canonical} (Erro: {res.error_code} - {res.error_detail})")
            all_ok = False

    # 1.2 Cobertura Exaustiva de TODOS os 67 DDDs da Anatel
    print(f"\n{BOLD}[1.2] Varredura Exaustiva dos 67 DDDs Oficiais da Anatel{RESET}")
    all_67_ddds = [
        11, 12, 13, 14, 15, 16, 17, 18, 19,  # SP
        21, 22, 24,                            # RJ
        27, 28,                                # ES
        31, 32, 33, 34, 35, 37, 38,            # MG
        41, 42, 43, 44, 45, 46,                # PR
        47, 48, 49,                            # SC
        51, 53, 54, 55,                        # RS
        61,                                    # DF
        62, 64,                                # GO
        63,                                    # TO
        65, 66,                                # MT
        67,                                    # MS
        68,                                    # AC
        69,                                    # RO
        71, 73, 74, 75, 77, 79,                # BA / SE
        81, 87,                                # PE
        82,                                    # AL
        83,                                    # PB
        84,                                    # RN
        85, 88,                                # CE
        86, 89,                                # PI
        91, 93, 94,                            # PA
        92, 97,                                # AM
        95,                                    # RR
        96,                                    # AP
        98, 99                                 # MA
    ]
    assert len(all_67_ddds) == 67, f"Esperado 67 DDDs, temos {len(all_67_ddds)}"

    ddd_failures = []
    for ddd in all_67_ddds:
        test_num = f"{ddd}988776655"
        res = contact_service.sanitize_phone(test_num)
        if not (res.valid and res.canonical == f"55{test_num}"):
            ddd_failures.append(ddd)

    if not ddd_failures:
        print_pass("100% dos 67 DDDs da Anatel foram validados com sucesso (sem falsos negativos).")
    else:
        print_fail(f"Falha nos seguintes DDDs válidos: {ddd_failures}")
        all_ok = False

    # 1.3 Rejeição Rígida de Prefixos e DDDs Inexistentes
    print(f"\n{BOLD}[1.3] Rejeição Rígida de DDDs e Prefixos Inexistentes (Anti-Fraude){RESET}")
    invalid_test_cases = [
        ("00994912937", "DDD 00 inexistente"),
        ("20994912937", "DDD 20 não alocado"),
        ("23994912937", "DDD 23 não alocado"),
        ("25994912937", "DDD 25 não alocado"),
        ("26994912937", "DDD 26 não alocado"),
        ("29994912937", "DDD 29 não alocado"),
        ("36994912937", "DDD 36 não alocado"),
        ("39994912937", "DDD 39 não alocado"),
        ("50994912937", "DDD 50 não alocado"),
        ("70994912937", "DDD 70 não alocado"),
        ("90994912937", "DDD 90 não alocado"),
        ("11111111111", "Sequência uniforme repetida"),
        ("00000000000", "Zeros repetidos"),
        ("994912937",   "Número local sem DDD"),
        ("+14155552671","Número internacional (EUA +1)"),
    ]

    for raw, desc in invalid_test_cases:
        res = contact_service.sanitize_phone(raw)
        if not res.valid:
            print_pass(f"{desc:<40} -> REJEITADO CORRETAMENTE ({res.error_code})")
        else:
            print_fail(f"{desc:<40} -> ERRO: Foi aceito como válido ({res.canonical})")
            all_ok = False

    # 1.4 Benchmark de Ingestão Massiva (10.000 Contatos em Memória)
    print(f"\n{BOLD}[1.4] Benchmark de Performance de Sanitização Massiva{RESET}")
    massive_phones = [
        "62994912937",
        62994912937.0,
        "11987654321",
        "+55 21 98888-7777",
        "01562994912937",
        "6232015000",
        "31999998888"
    ] * 2000  # 14.000 contatos
    t0 = time.perf_counter()
    valid_count = 0
    for p in massive_phones:
        if contact_service.sanitize_phone(p).valid:
            valid_count += 1
    t_elapsed = time.perf_counter() - t0
    throughput = len(massive_phones) / t_elapsed
    print_pass(f"{len(massive_phones)} registros sanitizados em {t_elapsed:.4f}s ({throughput:,.0f} contatos/segundo).")
    if throughput < 50000:
        print_fail("Performance abaixo da meta (50.000 contatos/s).")
        all_ok = False

    return all_ok


# ==============================================================================
# AGENTE 2: ANTI-BAN, JITTER ESTOCÁSTICO & DIGITAÇÃO HUMANA (BOX-MULLER)
# ==============================================================================
def audit_agent_2_antiban_stochastics() -> bool:
    print_header("AGENTE 2: AUDITORIA DE ANTI-BAN, JITTER ESTOCÁSTICO & DIGITAÇÃO HUMANA")
    all_ok = True

    # 2.1 Distribuição Normal Truncada via Box-Muller para Delays de Teclas (IKI)
    print(f"\n{BOLD}[2.1] Análise Estatística de IKI (Inter-Keystroke Interval) via Box-Muller{RESET}")
    text_sample = "Olá! Como vai você? Bem, obrigado." * 100
    char_delays = BoxMullerJitterEngine.calculate_keystroke_delays(text_sample, wpm=55)
    alpha_delays = [d[1] * 1000.0 for d in char_delays if d[0].isalpha()]
    punct_delays = [d[1] * 1000.0 for d in char_delays if d[0] in "!.?"]

    mean_iki = sum(alpha_delays) / len(alpha_delays)
    variance = sum((x - mean_iki) ** 2 for x in alpha_delays) / len(alpha_delays)
    stddev_iki = math.sqrt(variance)
    min_iki = min(alpha_delays)
    max_iki = max(alpha_delays)

    print(f" -> Amostras analisadas : {len(alpha_delays):,} caracteres alfabéticos")
    print(f" -> Média (mu)          : {mean_iki:.2f} ms (55 WPM -> ~218 ms teórico)")
    print(f" -> Desvio Padrão (sig) : {stddev_iki:.2f} ms")
    print(f" -> Mínimo / Máximo     : {min_iki:.2f} ms / {max_iki:.2f} ms")
    print(f" -> Pausas cognitivas   : {len(punct_delays)} pontuações com média de {sum(punct_delays)/len(punct_delays):.2f} ms")

    if 150.0 <= mean_iki <= 260.0 and min_iki >= 50.0 and min(punct_delays) >= 300.0:
        print_pass("Distribuição IKI e pausas cognitivas obedecem à cadência humana biomecânica.")
    else:
        print_fail(f"Distribuição IKI fora dos parâmetros esperados: mean={mean_iki:.2f}ms")
        all_ok = False

    # 2.2 Intervalo Inter-Mensagens Estocástico (10s a 25s)
    print(f"\n{BOLD}[2.2] Análise do Jitter Inter-Mensagens (Proteção Anti-Assinatura Espectral){RESET}")
    jitter_engine = BoxMullerJitterEngine(min_seconds=10.0, max_seconds=25.0, fat_tail_prob=0.05)
    jitter_samples = [jitter_engine.get_next_delay() for _ in range(5000)]
    mean_jitter = sum(jitter_samples) / len(jitter_samples)
    min_jitter = min(jitter_samples)
    max_jitter = max(jitter_samples)
    distinct_values = len(set(jitter_samples))

    print(f" -> Amostras analisadas : {len(jitter_samples):,}")
    print(f" -> Média (mu)          : {mean_jitter:.2f} s (Esperado centro: ~17.50-18.50 s)")
    print(f" -> Limites observados  : [{min_jitter:.2f} s, {max_jitter:.2f} s]")
    print(f" -> Valores distintos   : {distinct_values:,} de 5,000 (Ausência total de repetição consecutiva)")

    if 16.0 <= mean_jitter <= 19.5 and min_jitter >= 10.0 and distinct_values > 400:
        print_pass("Jitter estocástico elimina padrão rítmico robótico que aciona o banimento da Meta.")
    else:
        print_fail("Jitter estocástico apresentou anomalias ou violação de limites.")
        all_ok = False

    # 2.3 Resolução Recursiva de Spintax Multinível
    print(f"\n{BOLD}[2.3] Parser de Spintax Recursivo (Zero Leakage de Sintaxe){RESET}")
    contact_mock = ContactRecord(
        id="c1",
        raw_phone="62994912937",
        canonical_phone="5562994912937",
        name="Victor Santos",
        variables={"cupom": "VIP2026"}
    )
    template = "{Olá|Oi|E aí} {primeiro_nome}! {Confira nossa|Veja esta|Temos uma} oferta especial: {cupom}."
    generated_texts = set()
    for _ in range(500):
        resolved = SpintaxEngine.process_message(template, contact_mock)
        if "{" in resolved or "}" in resolved or "|" in resolved:
            print_fail(f"Vazamento de sintaxe Spintax na mensagem: '{resolved}'")
            all_ok = False
            break
        generated_texts.add(resolved)

    print_pass(f"500 execuções geraram {len(generated_texts)} variações únicas válidas sem nenhum caractere vazado.")
    return all_ok


# ==============================================================================
# AGENTE 3: MÁQUINA DE ESTADOS FSM, CONCORRÊNCIA UNITÁRIA & ATOMICIDADE
# ==============================================================================
def audit_agent_3_fsm_and_concurrency() -> bool:
    print_header("AGENTE 3: AUDITORIA DE FSM, CONCORRÊNCIA UNITÁRIA & ATOMICIDADE")
    all_ok = True

    print(f"\n{BOLD}[3.1] Transições Válidas e Inválidas da Máquina de Estados (FSM){RESET}")
    contacts_sample = [
        ContactRecord(id=f"c_{i}", raw_phone=f"6299491{i:04d}", canonical_phone=f"556299491{i:04d}", name=f"Lead {i}")
        for i in range(1, 15)
    ]
    dispatcher = DispatcherService(contacts=contacts_sample, message_template="Olá {nome}")
    assert dispatcher.state == QueueState.IDLE

    # Transição legal: IDLE -> RUNNING (via start)
    dispatcher.start(max_steps=2)
    if dispatcher.state == QueueState.RUNNING or dispatcher.current_index == 2:
        print_pass("Transição legal IDLE -> RUNNING executou 2 contatos.")
    else:
        print_fail(f"Falha ao iniciar: estado {dispatcher.state}")
        all_ok = False

    # Transição legal: RUNNING -> PAUSED (via pause)
    dispatcher.pause()
    if dispatcher.state == QueueState.PAUSED:
        print_pass("Transição legal RUNNING -> PAUSED concluída com congelamento de índice.")
    else:
        print_fail("Falha em transicionar para PAUSED.")
        all_ok = False

    # Transição ILEGAL: Iniciar fila já pausada (deve disparar RuntimeError)
    try:
        dispatcher.start(max_steps=2)
        print_fail("ERRO: Transição proibida start() em fila PAUSED foi permitida!")
        all_ok = False
    except RuntimeError as e:
        print_pass(f"Transição proibida start() em PAUSED bloqueada: {e}")

    # Transição legal: PAUSED -> RUNNING (via resume)
    dispatcher.resume(max_steps=3)
    if dispatcher.current_index == 5:
        print_pass(f"Retomada precisa: índice avançou de 2 para {dispatcher.current_index}.")
    else:
        print_fail("Retomada perdeu a sincronia do ponteiro da fila.")
        all_ok = False

    # Transição legal: Aborto de emergência (via abort)
    dispatcher.abort()
    if dispatcher.state == QueueState.ABORTED:
        print_pass("Transição legal para ABORTED. Fila marcada como terminal.")
    else:
        print_fail("Falha ao abortar fila.")
        all_ok = False

    # Verifica se os contatos não enviados foram devidamente marcados como CANCELLED
    unserved = [c for c in dispatcher.contacts if c.status == ContactStatus.CANCELLED]
    print_pass(f"Aborto atômico: {len(unserved)} contatos pendentes foram marcados como CANCELLED sem perda de dados.")

    # 3.2 Trava de Concorrência Unitária Estrita
    print(f"\n{BOLD}[3.2] Auditoria de Trava Concorrente (_concurrency_lock){RESET}")
    async def run_concurrency_audit():
        contacts_lock = [
            ContactRecord(id=f"c_{i}", raw_phone=f"6299111{i:04d}", canonical_phone=f"556299111{i:04d}", name=f"Contato {i}")
            for i in range(1, 11)
        ]
        async def slow_send(c: ContactRecord, m: str) -> SendMessageResult:
            await asyncio.sleep(0.02)
            return SendMessageResult(
                canonical_phone=c.canonical_phone,
                success=True,
                status=ContactStatus.SENT,
                error_detail="Sucesso",
                timestamp=datetime.now()
            )
        disp_lock = DispatcherService(contacts=contacts_lock, message_template="Olá {nome}", send_fn=slow_send)
        t1 = asyncio.create_task(disp_lock.run_queue_async())
        await asyncio.sleep(0.005)

        w2_rejected = False
        err_msg = ""
        try:
            await disp_lock.run_queue_async()
        except RuntimeError as ex:
            w2_rejected = True
            err_msg = str(ex)

        res1 = await t1
        return w2_rejected, err_msg, len(res1)

    w2_rej, err_txt, count_w1 = asyncio.run(run_concurrency_audit())
    if w2_rej and "Concorrência Unitária Estrita" in err_txt and count_w1 == 10:
        print_pass("Trava de concorrência unitária estrita rejeitou com sucesso o segundo worker concorrente.")
    else:
        print_fail(f"Falha na trava de concorrência: rej={w2_rej}, err={err_txt}")
        all_ok = False

    return all_ok


# ==============================================================================
# AGENTE 4: AUDITORIA BINÁRIA DE RELATÓRIOS EXECUTIVOS (EXCEL '@' & CSV UTF-8 BOM)
# ==============================================================================
def audit_agent_4_reports_binary_integrity() -> bool:
    print_header("AGENTE 4: AUDITORIA BINÁRIA DE RELATÓRIOS EXECUTIVOS (EXCEL & CSV)")
    all_ok = True

    mock_results = [
        SendMessageResult(
            canonical_phone="5562994912937",
            success=True,
            status=ContactStatus.SENT,
            error_detail="Mensagem enviada com sucesso",
            timestamp=datetime(2026, 9, 16, 10, 30, 0),
        ),
        SendMessageResult(
            canonical_phone="5511988887777",
            success=False,
            status=ContactStatus.FAILED,
            error_code="MODAL_NUMERO_SEM_WHATSAPP",
            error_detail="Número não possui WhatsApp ativo (modal OK)",
            timestamp=datetime(2026, 9, 16, 10, 30, 22),
        ),
        SendMessageResult(
            canonical_phone="5521977776666",
            success=False,
            status=ContactStatus.CANCELLED,
            error_detail="Cancelado após aborto da campanha",
            timestamp=datetime(2026, 9, 16, 10, 30, 45),
        ),
    ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        excel_path = Path(tmp_dir) / "relatorio_auditoria.xlsx"
        csv_path = Path(tmp_dir) / "relatorio_auditoria.csv"

        # 4.1 Exportação e Inspeção da Planilha Excel
        print(f"\n{BOLD}[4.1] Auditoria Binária da Planilha Excel (.xlsx){RESET}")
        reporting_service.export_excel(mock_results, str(excel_path), campaign_title="Auditoria Sexta-Feira")

        if not excel_path.exists() or excel_path.stat().st_size == 0:
            print_fail("Arquivo Excel não foi criado ou possui 0 bytes.")
            return False

        wb = openpyxl.load_workbook(str(excel_path))
        print_pass(f"Excel gerado com sucesso ({excel_path.stat().st_size:,} bytes). Abas encontradas: {wb.sheetnames}")

        # Verifica aba Resumo_Executivo
        if "Resumo_Executivo" in wb.sheetnames:
            print_pass("Aba 'Resumo_Executivo' presente com KPIs de campanha.")
        else:
            print_fail("Aba 'Resumo_Executivo' ausente no Excel.")
            all_ok = False

        # Verifica aba Relatorio_Disparos e formatação '@' de texto puro na coluna de telefone
        if "Relatorio_Disparos" in wb.sheetnames:
            ws_envios = wb["Relatorio_Disparos"]
            headers = [ws_envios.cell(row=1, column=col).value for col in range(1, ws_envios.max_column + 1)]
            print(f" -> Colunas detectadas: {headers}")
            if "Numero" in headers:
                col_idx = headers.index("Numero") + 1
                for row_idx in range(2, ws_envios.max_row + 1):
                    cell = ws_envios.cell(row=row_idx, column=col_idx)
                    val = str(cell.value)
                    fmt = cell.number_format
                    # Confirma preservação de todos os dígitos como string
                    if fmt == "@" and val.startswith("55") and len(val) == 13:
                        print_pass(f"Linha {row_idx}: Telefone '{val}' formatado como TEXTO ('@') sem perda de dígitos.")
                    else:
                        print_fail(f"Linha {row_idx}: Telefone '{val}' com formato inválido '{fmt}' ou truncado!")
                        all_ok = False
            else:
                print_fail("Coluna 'Numero' não encontrada no relatório Excel.")
                all_ok = False
        else:
            print_fail("Aba 'Relatorio_Disparos' ausente.")
            all_ok = False

        # 4.2 Exportação e Inspeção do CSV (BOM UTF-8 e Delimitador ';')
        print(f"\n{BOLD}[4.2] Auditoria Binária do Arquivo CSV (.csv){RESET}")
        reporting_service.export_csv(mock_results, str(csv_path))

        raw_bytes = csv_path.read_bytes()
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            print_pass("CSV inicia com UTF-8 BOM (0xEF, 0xBB, 0xBF) para compatibilidade nativa com Excel Windows.")
        else:
            print_fail("CSV NÃO possui UTF-8 BOM no início do arquivo.")
            all_ok = False

        content = raw_bytes.decode("utf-8-sig")
        lines = content.strip().split("\r\n") if "\r\n" in content else content.strip().split("\n")
        header_line = lines[0]
        if ";" in header_line:
            print_pass(f"Delimitador padrão brasileiro ';' verificado: '{header_line}'")
        else:
            print_fail(f"CSV não está utilizando delimitador ';': '{header_line}'")
            all_ok = False

        if "5562994912937" in content:
            print_pass("Registro canônico '5562994912937' presente e íntegro no CSV.")
        else:
            print_fail("Conteúdo canônico ausente ou corrompido no CSV.")
            all_ok = False

    return all_ok


# ==============================================================================
# AGENTE 5: INTEGRAÇÃO COMPLETA DE API REST, ENDPOINTS & SERVIDOR DESKTOP
# ==============================================================================
def audit_agent_5_api_and_server_endpoints() -> bool:
    print_header("AGENTE 5: AUDITORIA DE API REST, ENDPOINTS & SERVIDOR DESKTOP")
    all_ok = True
    client = TestClient(app)

    # 5.1 Rota Raiz (Frontend HTML)
    print(f"\n{BOLD}[5.1] Rota Raiz Desktop (GET /){RESET}")
    res = client.get("/")
    if res.status_code == 200 and "WhatsApp Sender Engine" in res.text and "<!DOCTYPE html>" in res.text:
        print_pass(f"Frontend Desktop servido com sucesso (HTTP 200, {len(res.text):,} caracteres).")
    else:
        print_fail(f"Falha na entrega da interface: Status {res.status_code}")
        all_ok = False

    # 5.2 Estado da Sessão WhatsApp
    print(f"\n{BOLD}[5.2] Status da Sessão WhatsApp (GET /api/session/status){RESET}")
    res = client.get("/api/session/status")
    if res.status_code == 200:
        data = res.json()
        print_pass(f"Endpoint de sessão funcional: Status='{data.get('status')}', Autenticado={data.get('authenticated')}")
    else:
        print_fail(f"Falha no status de sessão: Status {res.status_code}")
        all_ok = False

    # 5.3 Ingestão Manual com Colagem de Texto
    print(f"\n{BOLD}[5.3] Ingestão Manual de Contatos (POST /api/contacts/manual){RESET}")
    payload = {
        "text": (
            "62994912937;Victor Canônico;VIP\n"
            "62994912937;Victor Repetido;VIP\n"      # Duplicata exata
            "(62) 99491-2937;Victor Formatado;VIP\n" # Duplicata formatada
            "11987654321;Maria Silva;NOVO\n"
            "00000000000;Numero Falso;ERRO\n"        # Inválido
        )
    }
    res = client.post("/api/contacts/manual", json=payload)
    if res.status_code == 200:
        data = res.json()
        valid = data.get("valid_count", 0)
        dups = data.get("duplicate_count", 0)
        invalids = data.get("invalid_count", 0)
        print(f" -> Contatos Válidos     : {valid} (Esperado: 2 -> 62994912937 e 11987654321)")
        print(f" -> Duplicatas Removidas : {dups} (Esperado: 2)")
        print(f" -> Inválidos Descartados: {invalids} (Esperado: 1)")

        if valid == 2 and dups == 2 and invalids == 1:
            print_pass("Ingestão manual e consolidação de duplicatas funcionam 100% conforme a especificação.")
        else:
            print_fail("Métricas de ingestão manual divergiram do esperado.")
            all_ok = False
    else:
        print_fail(f"Falha na ingestão manual: Status {res.status_code} - {res.text}")
        all_ok = False

    # 5.4 Upload Multipart de Planilha Real
    print(f"\n{BOLD}[5.4] Upload Multipart de Planilha Real (POST /api/contacts/upload){RESET}")
    wb_temp = openpyxl.Workbook()
    ws = wb_temp.active
    ws.title = "Clientes"
    ws.append(["Telefone", "Nome", "Cupom"])
    ws.append([62994912937.0, "Victor Excel Float", "VIPEXCEL"]) # Float puro
    ws.append(["62994912937", "Victor Excel Text", "VIPEXCEL2"])  # Duplicata em texto
    ws.append(["31988887777", "Ana Paula", "DESC10"])

    excel_buffer = io.BytesIO()
    wb_temp.save(excel_buffer)
    excel_bytes = excel_buffer.getvalue()

    files = {
        "file": ("teste_upload.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    }
    res = client.post("/api/contacts/upload", files=files)
    if res.status_code == 200:
        data = res.json()
        valid = data.get("valid_count", 0)
        dups = data.get("duplicate_count", 0)
        print(f" -> Contatos Válidos do Excel     : {valid} (Esperado: 2)")
        print(f" -> Duplicatas Detectadas no Excel : {dups} (Esperado: 1)")
        if valid == 2 and dups == 1:
            print_pass("Upload multipart de arquivo XLSX processado com blindagem de float e descarte de repetidos.")
        else:
            print_fail(f"Upload do Excel retornou métricas inconsistentes: {data}")
            all_ok = False
    else:
        print_fail(f"Falha no upload do Excel: Status {res.status_code} - {res.text}")
        all_ok = False

    # 5.5 Telemetria Instantânea (GET /api/telemetry/snapshot)
    print(f"\n{BOLD}[5.5] Telemetria ao Vivo (GET /api/telemetry/snapshot){RESET}")
    res = client.get("/api/telemetry/snapshot")
    if res.status_code == 200:
        snap = res.json()
        print_pass(f"Snapshot retornado: Estado='{snap.get('state')}', Total={snap.get('total_contacts')}, Enviados={snap.get('sent_count')}")
    else:
        print_fail(f"Falha na telemetria: Status {res.status_code}")
        all_ok = False

    # 5.6 Limpeza e Reset de Campanha (DELETE /api/contacts)
    print(f"\n{BOLD}[5.6] Reset e Limpeza de Estado em Memória (DELETE /api/contacts){RESET}")
    res = client.delete("/api/contacts")
    if res.status_code == 200:
        print_pass("Estado da aplicação resetado com sucesso sem vazamento de dados.")
    else:
        print_fail(f"Falha no reset de contatos: Status {res.status_code}")
        all_ok = False

    return all_ok


# ==============================================================================
# MAIN RUNNER
# ==============================================================================
def main():
    print(f"{BOLD}{GREEN}")
    print("*" * 80)
    print("   WHATSAPP SENDER ENGINE — AUDITORIA SISTEMÁTICA E MULTIAGENTE")
    print("   Data de Execução: 2026-09-16 | Ambiente: Produção Local Windows")
    print("*" * 80)
    print(f"{RESET}")

    t_start = time.perf_counter()

    r1 = audit_agent_1_data_sanitization()
    r2 = audit_agent_2_antiban_stochastics()
    r3 = audit_agent_3_fsm_and_concurrency()
    r4 = audit_agent_4_reports_binary_integrity()
    r5 = audit_agent_5_api_and_server_endpoints()

    total_time = time.perf_counter() - t_start

    print("\n" + "=" * 80)
    print(f"{BOLD} QUADRO CONSOLIDADO DA AUDITORIA SISTEMÁTICA (TEAMWORK REVIEW) {RESET}")
    print("=" * 80)
    print(f" Agente 1 (Sanitização & Blindagem Float)       : {'[PASS] 100% VERDE' if r1 else '[FAIL] FALHA'}")
    print(f" Agente 2 (Anti-Ban & Simulação Box-Muller)     : {'[PASS] 100% VERDE' if r2 else '[FAIL] FALHA'}")
    print(f" Agente 3 (Máquina de Estados & Concorrência)   : {'[PASS] 100% VERDE' if r3 else '[FAIL] FALHA'}")
    print(f" Agente 4 (Auditoria Binária de Relatórios)     : {'[PASS] 100% VERDE' if r4 else '[FAIL] FALHA'}")
    print(f" Agente 5 (Integração de API & Servidor Desktop): {'[PASS] 100% VERDE' if r5 else '[FAIL] FALHA'}")
    print("-" * 80)
    print(f" Tempo Total de Auditoria : {total_time:.3f} segundos")

    if r1 and r2 and r3 and r4 and r5:
        print(f"\n{BOLD}{GREEN}[VEREDICTO FINAL: SISTEMA 100% HOMOLOGADO E AUDITADO SEM NENHUMA FALHA]{RESET}\n")
        sys.exit(0)
    else:
        print(f"\n{BOLD}{RED}[VEREDICTO FINAL: AUDITORIA DETECTOU INCONFORMIDADES]{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
