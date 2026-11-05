# Project: WhatsApp Sender Engine

## Architecture
- **Paradigma**: Arquitetura Desacoplada e Resiliente — Motor de Automação Backend Local (Python 3.12 + FastAPI / Uvicorn + Playwright) integrado com Interface Desktop Moderna (Edge WebView2 / Janela de Aplicação com UI responsiva HTML5/Tailwind/JS e telemetria SSE em tempo real).
- **Motor de Automação**:
  - `Playwright 1.62.0` com `playwright-stealth 2.0.3` executando canal nativo Chrome/Chromium visível (`headless=False`, `--disable-blink-features=AutomationControlled`).
  - Persistência obrigatória de sessão em `D:\Nova pasta\whatsapp_sender_engine\data\session\` via `launch_persistent_context` (preservando IndexedDB e tokens de autenticação entre reinicializações sem exigir novo QR Code).
- **Processamento e Higienização de Contatos (R1)**:
  - Ingestão massiva em streaming via `openpyxl` (`read_only=True`) e `csv.DictReader` / `pandas 3.0.5`, suportando >5.000 linhas com sub-segundo e <15MB de RAM.
  - Sanitização rigorosa no padrão brasileiro E.164: blindagem contra conversão float/notação científica do Excel, validação estrita dos 67 DDDs oficiais da Anatel, preservação e injeção do DDI 55, preservação integral do 9º dígito em celulares (`62994912937` -> `5562994912937`) e telefones fixos (8 dígitos).
  - Deduplicação determinística por chave canônica E.164 com consolidação de variáveis (First Wins + merge) e alerta prévio de métricas.
- **Motor de Disparo Anti-Ban com Simulação Humana (R3)**:
  - Concorrência unitária estrita (`concurrency = 1`), eliminando conflitos de sessão ou abas concorrentes.
  - Simulação de digitação humana: Intervalos Inter-Keystroke (IKI) baseados em WPM com ruído gaussiano (Transformada de Box-Muller), pausas reflexivas em pontuações fortes/fracas, micro-erros com autocorreção e modo híbrido para mensagens longas.
  - Jitter estocástico entre envios: Normal Truncada [10s, 25s] ($\mu=17.5\text{s}, \sigma=2.5\text{s}$) com injeção de cauda longa (5% chance de delay 15-40s) para quebrar classificadores ML.
  - Pausas estocásticas por lote: blocos de $20 \pm 3$ envios com repouso aperiódico de 2 a 5 minutos.
  - Interpolação de variáveis dinâmicas (`{nome}`, etc.) e resolução de Spintax multinível (`{Olá|Oi|E aí}`).
  - Resiliência total a erros: detecção e auto-dismiss do diálogo modal de número sem WhatsApp / URL inválida (`div[role="dialog"] button:has-text("OK")`), marcando o contato como `FAILED` e avançando a fila sem travamento.
- **Telemetria e Relatório Executivo (R4)**:
  - Dashboard ao vivo com streaming SSE: progresso, enviados, falhas, pendentes e cálculo de ETA estocástico.
  - Exportação em 1 clique para Excel (`.xlsx` com formato de texto `@` para celular e aba de resumo executivo) e CSV (`utf-8-sig` com `;`), contendo as colunas `Numero`, `Status`, `DataHora` e `Detalhes`.

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---|---|---|---|
| 1 | Ingestão Excel/CSV Massiva | Leitura streaming de .xlsx, .xls e .csv para bases >5.000 contatos sem congelamento | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Colagem Manual de Contatos | Suporte a inserção direta de listas textuais de números e nomes | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Sanitização E.164 Brasil | Normalização estrita: DDI 55, 67 DDDs Anatel, preservação integral do 9º dígito (`62994912937` -> `5562994912937`) | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Blindagem contra Float Excel | Prevenção contra perda de precisão ou notação científica (`6.299E+10`) | M1 | Survey Spec Miner |
| 5 | Deduplicação Determinística | Descarte de repetidos por chave canônica com estatísticas de aproveitamento | M1 | ORIGINAL_REQUEST §R1 |
| 6 | Prévia Tabular de Contatos | Tabela interativa com total lidos, válidos, duplicados e inválidos | M1 | ORIGINAL_REQUEST §R1 |
| 7 | Navegador Integrado WhatsApp Web | Exibição visual da tela oficial para escaneamento direto do QR Code | M2 | ORIGINAL_REQUEST §R2 |
| 8 | Persistência Segura de Sessão | Armazenamento de IndexedDB em `userDataDir` para login permanente | M2 | ORIGINAL_REQUEST §R2 |
| 9 | Monitor de Estado de Conexão | Detecção em tempo real: Desconectado, Aguardando QR, Conectado/Pronto | M2 | ORIGINAL_REQUEST §R2 |
| 10 | Evasão e Stealth | Desativação de flags de automação e injeção de scripts stealth indetectáveis | M2 | Survey Env Explorer |
| 11 | Fila Assíncrona de Disparo | Fila com concorrência unitária e ciclo de vida completo por contato | M3 | ORIGINAL_REQUEST §R3 |
| 12 | Simulação de Digitação Humana | Digitação WPM com Box-Muller, pausas em pontuações e micro-typos | M3 | ORIGINAL_REQUEST §R3 |
| 13 | Jitter Estocástico Anti-Ban | Intervalos variáveis normais [10s, 25s] com anomalia de cauda longa | M3 | ORIGINAL_REQUEST §R3 |
| 14 | Pausas Inteligentes por Lote | Repouso aperiódico de 2 a 5 minutos a cada bloco de ~20 envios | M3 | ORIGINAL_REQUEST §R3 |
| 15 | Interpolação & Spintax | Suporte a tags dinâmicas (`{nome}`) e rotação de texto `{Oi|Olá}` | M3 | ORIGINAL_REQUEST §R3 |
| 16 | Suporte a Imagens e Anexos | Envio de arquivos multimídia (JPEG/PNG/PDF/DOCX) com legenda | M3 | ORIGINAL_REQUEST §R3 |
| 17 | Controles de Fila em Tempo Real | Botões Pausar (sem perda de estado), Continuar e Abortar | M3 | ORIGINAL_REQUEST §R3 |
| 18 | Resiliência a Números Inválidos | Auto-dismiss de modais de erro sem interromper a fila de disparo | M3 | ORIGINAL_REQUEST §R3 |
| 19 | Telemetria ao Vivo com ETA | Painel com barra de progresso, contadores e estimativa dinâmica de término | M4 | ORIGINAL_REQUEST §R4 |
| 20 | Log Estruturado por Contato | Histórico detalhado em tempo real (`Numero`, `Nome`, `DataHora`, `Status`, `Detalhes`) | M4 | ORIGINAL_REQUEST §R4 |
| 21 | Exportação Excel (.xlsx) | Relatório com formato `@` texto para telefones e aba resumo | M4 | ORIGINAL_REQUEST §R4 |
| 22 | Exportação CSV (.csv) | Relatório com encoding `utf-8-sig` e delimitador `;` para abertura direta | M4 | ORIGINAL_REQUEST §R4 |
| 23 | Suíte Independente E2E | Testes automatizados Tiers 1-4 cobrindo 100% dos critérios de aceite | E2E | ORIGINAL_REQUEST §Acceptance |
| 24 | Adversarial Hardening (Tier 5) | Testes de estresse com números corrompidos, arquivos gigantes e quedas de rede | M5 | Governance Rule |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| E2E | E2E Testing Track | Criação da infraestrutura de testes independentes (`tests/e2e_test_suite.py`) cobrindo Tiers 1-4 e publicação de `TEST_READY.md` | none | DONE |
| M1 | Desktop GUI & Gestão de Contatos (R1) | Interface Desktop moderna, streaming parser Excel/CSV, sanitizador E.164 brasileiro (DDI 55, DDD, 9º dígito), deduplicador | none | DONE |
| M2 | Motor WhatsApp Web (R2) | Automação Playwright Chromium, persistência `userDataDir`, QR Code visual, monitor de conexão e stealth | none | DONE |
| M3 | Algoritmo Anti-Ban de Envio (R3) | Fila assíncrona, simulação de digitação Box-Muller, jitter estocástico [10-25s], pausas por bloco, spintax, controles e resiliência | M1, M2 | DONE |
| M4 | Telemetria e Relatório Executivo (R4) | Dashboard ao vivo via SSE, ETA dinâmico, log por contato, exportador .xlsx e .csv em 1 clique | M1, M3 | DONE |
| M5 | Integração Final & Validação E2E | Execução 100% verde da suíte E2E, hardening adversarial (Tier 5) e auditoria forense de integridade | E2E, M1, M2, M3, M4 | DONE |

---

## Interface Contracts

### 1. Ingestion ↔ Queue Dispatcher
```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

class ContactStatus(str, Enum):
    PENDING = "PENDENTE"
    PROCESSING = "PROCESSANDO"
    SENT = "ENVIADO"
    FAILED = "FALHA"
    CANCELLED = "CANCELADO"

@dataclass
class ContactRecord:
    id: str
    raw_phone: str
    canonical_phone: str          # Formato E.164: 5562994912937
    name: str
    variables: Dict[str, str] = field(default_factory=dict)
    status: ContactStatus = ContactStatus.PENDING
    timestamp: Optional[datetime] = None
    error_detail: Optional[str] = None

@dataclass
class IngestionResult:
    total_rows: int
    valid_contacts: List[ContactRecord]
    duplicate_count: int
    invalid_count: int
    warning_messages: List[str]
```

### 2. Browser Automation ↔ Queue Dispatcher
```python
class SessionStatus(str, Enum):
    DISCONNECTED = "DESCONECTADO"
    AWAITING_QR = "AGUARDANDO_QR"
    SYNCING = "SINCRONIZANDO"
    READY = "CONECTADO_PRONTO"

@dataclass
class SendMessageResult:
    canonical_phone: str
    success: bool
    status: ContactStatus
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
```

### 3. Queue Dispatcher ↔ Telemetry Hub
```python
class QueueState(str, Enum):
    IDLE = "OCIOSO"
    RUNNING = "EXECUTANDO"
    PAUSED = "PAUSADO"
    ABORTED = "ABORTADO"
    COMPLETED = "CONCLUIDO"

@dataclass
class TelemetrySnapshot:
    state: QueueState
    total_contacts: int
    sent_count: int
    failed_count: int
    pending_count: int
    eta_seconds: float
    current_contact: Optional[str]
    messages_per_minute: float
```

---

## Code Layout
```
whatsapp_sender_engine\
├── app\
│   ├── __init__.py
│   ├── main.py                     # Entrypoint Desktop e Servidor FastAPI local (127.0.0.1:8765)
│   ├── core\
│   │   ├── __init__.py
│   │   ├── config.py               # Configurações de diretórios, delays e portas
│   │   └── constants.py            # Lista oficial Anatel 67 DDDs, regexes, Enums
│   ├── models\
│   │   ├── __init__.py
│   │   └── schemas.py              # Modelos Pydantic / Dataclasses de Contatos, Mensagens e Telemetria
│   ├── services\
│   │   ├── __init__.py
│   │   ├── contact_service.py      # Streaming parser Excel/CSV, Sanitizador E.164, Deduplicador
│   │   ├── browser_service.py      # Playwright Chromium, userDataDir, QR Code, Stealth, detecção DOM
│   │   ├── dispatcher_service.py   # Fila assíncrona, Box-Muller typing, Jitter, Pausas por lote, Spintax
│   │   └── reporting_service.py    # Telemetria SSE em tempo real, gerador de .xlsx e .csv
│   └── static\
│       ├── index.html              # Interface Desktop moderna (Design System limpo e profissional)
│       ├── css\
│       │   └── styles.css          # Estilização moderna, tema dark/light, responsividade
│       └── js\
│           └── app.js              # Controlador do cliente, upload, preview, SSE e controles da fila
├── data\
│   ├── session\                    # Diretório persistente userDataDir do WhatsApp Web (IndexedDB)
│   ├── uploads\                    # Planilhas temporárias importadas e anexos
│   └── reports\                    # Relatórios exportados (.xlsx e .csv)
├── tests\
│   ├── __init__.py
│   ├── test_runner.py              # Runner mestre executável dos testes
│   ├── test_contact_service.py     # Testes Tier 1: sanitização 9º dígito, >5000 linhas, deduplicação
│   ├── test_dispatcher.py          # Testes Tier 1/2: máquina de estados, jitter estocástico, pausas
│   ├── test_reporting.py           # Testes Tier 1: geração de .xlsx formatado e .csv utf-8-sig
│   └── test_e2e_flow.py            # Testes Tier 3/4: fluxo completo ponta a ponta simulado
├── run.py                          # Script de inicialização 1-clique com verificação de ambiente
├── requirements.txt                # Dependências fixadas (já disponíveis no host)
└── PROJECT.md                      # Documentação viva do projeto
```
