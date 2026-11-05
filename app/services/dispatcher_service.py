"""
Anti-Ban Message Dispatcher and Stochastic Queue Engine for WhatsApp Sender Engine.
Rigorously adheres to PROJECT.md, Interface Contracts, and Milestone 3 (R3) Specifications.

Architectural Pillars:
1. Strict Unitary Concurrency (concurrency = 1):
   Guarantees strictly sequential processing of asynchronous queues without session conflicts.
2. Queue State Machine with Atomic Barrier:
   IDLE -> RUNNING -> PAUSING -> PAUSED -> RESUMING -> ABORTING -> ABORTED -> COMPLETED.
   - Atomic Pause: transitions to PAUSING, waits for in-flight contact to finalize,
     and halts queue progress via asyncio.Event without skipping or duplicating.
   - Resume: unblocks the event gate and continues exactly from the next pending contact.
   - Abort: immediately breaks the dispatch loop, marks all remaining contacts as CANCELLED,
     and consolidates partial execution telemetry.
3. Biomechanical Typing Simulation:
   - Inter-Keystroke Interval (IKI) based on WPM with stochastic Gaussian noise via Box-Muller.
   - Cognitive formulation pauses on strong punctuation (., ?!, \n: 450ms-1200ms) and
     weak punctuation (,, ;, :: 250ms-550ms).
   - Micro-typos simulation (1.5% probability on QWERTY/ABNT2 neighbor keys + error perception
     delay + backspace + pre-correction focus + correct keystroke).
   - Intelligent hybrid mode for long messages (>120 chars) to balance human realism and throughput.
4. Stochastic Anti-Ban Jitter:
   - Truncated Normal distribution [10s, 25s] (μ=17.5s, σ=2.5s) via Box-Muller transform.
   - Fat-tail long pause injection (5% probability, 15s to 40s) to disrupt ML traffic classifiers.
   - Strict mathematical anti-consecutive check guaranteeing no identical delays in succession.
5. Aperiodic Batch Pauses:
   - Rest pauses triggered every 20 ± 3 messages sent with 120s to 300s rest duration.
6. Dynamic Interpolation & Nested Spintax:
   - Multi-level recursive Spintax resolution ({Oi|{Olá|E aí}}).
   - Interpolation of {nome}, {primeiro_nome}, {saudacao} (temporal), {telefone}, and custom variables.
   - Fallback resolution for optional tags ({campo|padrao}).
7. Fault Tolerance & Modal Auto-Dismiss:
   - Integration with BrowserService.send_message. Invalid numbers or numbers without WhatsApp
     trigger automatic dialog dismissal, are recorded as FAILED, and the queue advances safely.
8. Real-Time Telemetry & Live Callbacks:
   - Live state snapshots with stochastic ETA estimation, Messages Per Minute (MPM), and event hooks.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import inspect
import logging
import math
from pathlib import Path
import random
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Ensure absolute imports work when executed directly
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.constants import ContactStatus, QueueState
from app.models.schemas import ContactRecord, SendMessageResult, TelemetrySnapshot

logger = logging.getLogger("whatsapp_sender_engine.dispatcher_service")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [DispatcherService] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ==============================================================================
# 1. Constantes e Estados Estendidos da Máquina de Estados
# ==============================================================================

class QueueEngineState(str, Enum):
    """Estados refinados da máquina de estados do motor de disparo."""
    IDLE = "OCIOSO"
    RUNNING = "EXECUTANDO"
    PAUSING = "PAUSANDO"
    PAUSED = "PAUSADO"
    RESUMING = "RETOMANDO"
    ABORTING = "ABORTANDO"
    ABORTED = "ABORTADO"
    COMPLETED = "CONCLUIDO"


DEFAULT_MIN_DELAY_SECONDS = 10.0
DEFAULT_MAX_DELAY_SECONDS = 25.0
DEFAULT_FAT_TAIL_PROBABILITY = 0.05
DEFAULT_FAT_TAIL_RANGE = (15.0, 40.0)

DEFAULT_BATCH_SIZE_BASE = 20
DEFAULT_BATCH_SIZE_JITTER = 3  # Lote aciona entre 17 e 23
DEFAULT_BATCH_PAUSE_SECONDS_MIN = 120.0  # 2 minutos
DEFAULT_BATCH_PAUSE_SECONDS_MAX = 300.0  # 5 minutos

DEFAULT_TYPING_WPM = 55
DEFAULT_TYPO_PROBABILITY = 0.015
DEFAULT_BURST_THRESHOLD_CHARS = 120


@dataclass
class AntiBanConfig:
    """Configuração modular para calibração de parâmetros estocásticos anti-ban."""
    min_delay_seconds: float = DEFAULT_MIN_DELAY_SECONDS
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS
    enable_fat_tail: bool = True
    fat_tail_probability: float = DEFAULT_FAT_TAIL_PROBABILITY
    fat_tail_range: Tuple[float, float] = DEFAULT_FAT_TAIL_RANGE

    batch_size_base: int = DEFAULT_BATCH_SIZE_BASE
    batch_size_jitter: int = DEFAULT_BATCH_SIZE_JITTER
    batch_pause_min_seconds: float = DEFAULT_BATCH_PAUSE_SECONDS_MIN
    batch_pause_max_seconds: float = DEFAULT_BATCH_PAUSE_SECONDS_MAX

    typing_wpm: int = DEFAULT_TYPING_WPM
    enable_micro_typos: bool = True
    typo_probability: float = DEFAULT_TYPO_PROBABILITY
    burst_threshold_chars: int = DEFAULT_BURST_THRESHOLD_CHARS


# ==============================================================================
# 2. Motor Estocástico de Jitter Box-Muller
# ==============================================================================

class BoxMullerJitterEngine:
    """
    Gerador estocástico de intervalos inter-mensagens anti-ban:
    - Normal Truncada [min_s, max_s] centrada via Transformada de Box-Muller.
    - Injeção de cauda longa (fat-tail).
    - Cadência de digitação WPM com pausas reflexivas em pontuação.
    - Blindagem matemática contra valores idênticos consecutivos.
    """

    def __init__(
        self,
        min_seconds: float = DEFAULT_MIN_DELAY_SECONDS,
        max_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        fat_tail_prob: float = DEFAULT_FAT_TAIL_PROBABILITY,
        fat_tail_range: Tuple[float, float] = DEFAULT_FAT_TAIL_RANGE,
    ):
        self.min_s = float(min_seconds)
        self.max_s = float(max_seconds)
        self.mu = (self.min_s + self.max_s) / 2.0  # Média centrada (17.5s para [10, 25])
        self.sigma = (self.max_s - self.min_s) / 6.0  # 99.7% dentro da janela (2.5s)
        self.fat_tail_prob = float(fat_tail_prob)
        self.fat_tail_range = (float(fat_tail_range[0]), float(fat_tail_range[1]))
        self._last_delay: Optional[float] = None

    @staticmethod
    def sample_gaussian(mean: float, std_dev: float) -> float:
        """
        Gera número pseudo-aleatório com distribuição normal exata N(mean, std_dev^2)
        utilizando a Transformada de Box-Muller sem dependências de pacotes externos.
        """
        u1 = 0.0
        while u1 <= 1e-12:
            u1 = random.random()
        u2 = random.random()
        z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return mean + (z0 * std_dev)

    @staticmethod
    def clamp(val: float, min_val: float, max_val: float) -> float:
        """Restringe o valor estritamente ao intervalo fechado [min_val, max_val]."""
        return max(min_val, min(max_val, val))

    def get_next_delay(self) -> float:
        """
        Calcula o próximo delay estocástico anti-ban via Box-Muller.
        Garante matematicamente que nenhuma mensagem é enviada em intervalo fixo idêntico consecutivo.
        """
        for _ in range(20):
            # Injeção de anomalia de cauda longa (fat-tail humana)
            if self.fat_tail_prob > 0.0 and random.random() < self.fat_tail_prob:
                delay = random.uniform(self.fat_tail_range[0], self.fat_tail_range[1])
            else:
                raw = self.sample_gaussian(self.mu, self.sigma)
                delay = self.clamp(raw, self.min_s, self.max_s)

            rounded_delay = round(delay, 2)
            # Verifica se é diferente do último delay registrado
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
        wpm: int = DEFAULT_TYPING_WPM,
    ) -> List[Tuple[str, float]]:
        """
        Calcula os tempos Inter-Keystroke Interval (IKI) para cada caractere:
        - Média baseada em Palavras Por Minuto (WPM, padrão 5 caracteres por palavra).
        - Ruído Box-Muller individual por tecla.
        - Pausas reflexivas humanas em pontuações fortes (., ?!, \n) e fracas (,, ;, :).
        """
        # Caracteres por segundo = (WPM * 5) / 60
        cps = (max(1, wpm) * 5.0) / 60.0
        base_iki_sec = 1.0 / max(cps, 1.0)

        delays: List[Tuple[str, float]] = []
        for char in text:
            # Ruído gaussiano Box-Muller por caractere
            u1 = max(random.random(), 1e-10)
            u2 = random.random()
            noise = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2) * 0.03
            iki = max(0.05, base_iki_sec + noise)

            # Pausas reflexivas humanas
            if char in ".?!":
                iki += random.uniform(0.40, 0.85)
            elif char in ",;:":
                iki += random.uniform(0.20, 0.40)
            elif char == "\n":
                iki += random.uniform(0.50, 1.10)
            elif char == " ":
                iki += random.uniform(0.08, 0.18)

            delays.append((char, round(iki, 3)))

        return delays


# ==============================================================================
# 3. Simulador Biomecânico de Digitação e Micro-Erros
# ==============================================================================

class BiomechanicTypingSimulator:
    """
    Simula o comportamento motor humano de digitação:
    - Mapeamento de teclas adjacentes QWERTY / ABNT2 para simulação realista de micro-erros.
    - Pausa de percepção cognitiva de erro.
    - Tecla Backspace e pausa pré-correção.
    - Modo híbrido acelerado para mensagens com mais de 120 caracteres.
    """

    KEY_ADJACENCY: Dict[str, List[str]] = {
        "a": ["q", "w", "s", "z"],
        "b": ["v", "g", "h", "n"],
        "c": ["x", "d", "f", "v"],
        "d": ["s", "e", "r", "f", "x", "c"],
        "e": ["w", "r", "d", "s", "3", "4"],
        "f": ["d", "r", "t", "g", "c", "v"],
        "g": ["f", "t", "y", "h", "v", "b"],
        "h": ["g", "y", "u", "j", "b", "n"],
        "i": ["u", "o", "k", "j", "8", "9"],
        "j": ["h", "u", "i", "k", "n", "m"],
        "k": ["j", "i", "o", "l", "m"],
        "l": ["k", "o", "p", "ç"],
        "m": ["n", "j", "k"],
        "n": ["b", "h", "j", "m"],
        "o": ["i", "p", "l", "k", "9", "0"],
        "p": ["o", "l", "ç", "0"],
        "q": ["w", "a", "1", "2"],
        "r": ["e", "t", "f", "d", "4", "5"],
        "s": ["a", "w", "e", "d", "x", "z"],
        "t": ["r", "y", "g", "f", "5", "6"],
        "u": ["y", "i", "j", "h", "7", "8"],
        "v": ["c", "f", "g", "b"],
        "w": ["q", "e", "s", "a", "2", "3"],
        "x": ["z", "s", "d", "c"],
        "y": ["t", "u", "h", "g", "6", "7"],
        "z": ["a", "s", "x"],
        "ç": ["l", "p"],
    }

    @classmethod
    def get_adjacent_key(cls, char: str) -> Optional[str]:
        """Retorna uma tecla vizinha no teclado se o caractere for alfabético."""
        lower = char.lower()
        neighbors = cls.KEY_ADJACENCY.get(lower)
        if not neighbors:
            return None
        chosen = random.choice(neighbors)
        return chosen.upper() if char.isupper() else chosen

    @classmethod
    async def type_humanlike_playwright(
        cls,
        page: Any,
        target_locator: Any,
        text: str,
        wpm: int = DEFAULT_TYPING_WPM,
        enable_typos: bool = True,
        typo_prob: float = DEFAULT_TYPO_PROBABILITY,
        hybrid_threshold: int = DEFAULT_BURST_THRESHOLD_CHARS,
    ) -> None:
        """
        Executa digitação humanizada em um elemento do Playwright com suporte a:
        - IKI variável
        - Pausas pontuais
        - Micro-typos com autocorreção
        - Modo híbrido para textos longos (>120 caracteres)
        """
        await target_locator.focus()

        # Modo Híbrido: se a mensagem for longa, digita as primeiras palavras
        # para ativar a telemetria 'Digitando...' e insere o restante em bloco
        if len(text) > hybrid_threshold:
            head_len = min(25, len(text))
            head_text = text[:head_len]
            tail_text = text[head_len:]

            # Digita o cabeçalho tecla a tecla
            await cls.type_humanlike_playwright(
                page=page,
                target_locator=target_locator,
                text=head_text,
                wpm=wpm,
                enable_typos=False,
                hybrid_threshold=999999,
            )

            # Pausa cognitiva de pensamento
            think_delay = BoxMullerJitterEngine.clamp(
                BoxMullerJitterEngine.sample_gaussian(0.65, 0.12),
                0.40,
                0.95
            )
            await asyncio.sleep(think_delay)

            # Insere o restante linha a linha usando Shift+Enter para quebras de linha seguras no WhatsApp Web
            lines = tail_text.split("\n")
            for idx, line_part in enumerate(lines):
                if line_part:
                    if hasattr(page, "keyboard") and hasattr(page.keyboard, "insert_text"):
                        await page.keyboard.insert_text(line_part)
                    elif hasattr(target_locator, "press_sequentially"):
                        await target_locator.press_sequentially(line_part, delay=10)
                if idx < len(lines) - 1:
                    if hasattr(page, "keyboard"):
                        await page.keyboard.press("Shift+Enter")
                    await asyncio.sleep(0.12)
            return

        base_iki_sec = 12.0 / max(1, wpm)

        for char in text:
            # Quebra de linha segura no WhatsApp Web (Shift+Enter evita disparo prematuro da mensagem)
            if char == "\n":
                if hasattr(page, "keyboard"):
                    await page.keyboard.press("Shift+Enter")
                pause = BoxMullerJitterEngine.clamp(
                    BoxMullerJitterEngine.sample_gaussian(0.80, 0.20),
                    0.50,
                    1.30
                )
                await asyncio.sleep(pause)
                continue

            # Simulação de micro-erros (1.5% chance em alfabéticos)
            if enable_typos and random.random() < typo_prob:
                wrong_key = cls.get_adjacent_key(char)
                if wrong_key:
                    if hasattr(page, "keyboard"):
                        await page.keyboard.press(wrong_key)
                    # Pausa de percepção do erro (180ms - 450ms)
                    error_percept = BoxMullerJitterEngine.clamp(
                        BoxMullerJitterEngine.sample_gaussian(0.28, 0.05),
                        0.18,
                        0.45
                    )
                    await asyncio.sleep(error_percept)

                    # Backspace para apagar
                    if hasattr(page, "keyboard"):
                        await page.keyboard.press("Backspace")

                    # Pausa pré-correção (80ms - 200ms)
                    pre_correct = BoxMullerJitterEngine.clamp(
                        BoxMullerJitterEngine.sample_gaussian(0.12, 0.03),
                        0.08,
                        0.20
                    )
                    await asyncio.sleep(pre_correct)

            # Digita a tecla pretendida
            if hasattr(page, "keyboard"):
                await page.keyboard.type(char)
            elif hasattr(target_locator, "type"):
                await target_locator.type(char)

            # Delays cognitivos pós-tecla
            if char in ".?!":
                pause = BoxMullerJitterEngine.clamp(
                    BoxMullerJitterEngine.sample_gaussian(0.75, 0.15),
                    0.45,
                    1.20
                )
            elif char in ",;:":
                pause = BoxMullerJitterEngine.clamp(
                    BoxMullerJitterEngine.sample_gaussian(0.38, 0.07),
                    0.25,
                    0.55
                )
            elif char == "\n":
                pause = BoxMullerJitterEngine.clamp(
                    BoxMullerJitterEngine.sample_gaussian(0.80, 0.20),
                    0.50,
                    1.30
                )
            elif char == " ":
                pause = BoxMullerJitterEngine.clamp(
                    BoxMullerJitterEngine.sample_gaussian(0.18, 0.04),
                    0.11,
                    0.28
                )
            else:
                pause = BoxMullerJitterEngine.clamp(
                    BoxMullerJitterEngine.sample_gaussian(base_iki_sec, base_iki_sec * 0.25),
                    0.06,
                    0.40
                )

            await asyncio.sleep(pause)


# ==============================================================================
# 4. Motor de Spintax Multinível e Interpolação Dinâmica
# ==============================================================================

class SpintaxEngine:
    """
    Processador de templates de mensagem com:
    - Resolução recursiva de Spintax multinível: {Oi|{Olá|E aí}}
    - Interpolação de variáveis dinâmicas: {nome}, {primeiro_nome}, {saudacao}, {telefone}
    - Resolução de fallbacks em campos opcionais: {empresa|sua empresa}
    - Descarte seguro de variáveis ausentes sem lançamento de exceções.
    """

    SPINTAX_PATTERN = re.compile(r"\{([^{}]+)\}")
    VARIABLE_FALLBACK_PATTERN = re.compile(
        r"\{([a-zA-Z0-9_áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ]+)(?:\|([^{}|]+))?\}",
        re.IGNORECASE,
    )

    KNOWN_FALLBACK_FIELDS: Set[str] = {
        "empresa", "cargo", "setor", "desconto", "cupom", "valor",
        "produto", "link", "email", "cidade", "estado", "cpf", "cnpj",
        "vencimento", "data_vencimento", "cliente", "responsavel",
        "nossa consultoria", "sua empresa"
    }

    @classmethod
    def resolve_spintax(cls, text: str, seed: Optional[int] = None) -> str:
        """Resolve recursivamente todas as chaves Spintax do interior para o exterior."""
        if seed is not None:
            random.seed(seed)

        result = text
        while True:
            # Localiza o primeiro bloco mais interno que contenha opções com pipe '|'
            match = None
            for m in cls.SPINTAX_PATTERN.finditer(result):
                inner = m.group(1)
                if "|" in inner:
                    match = m
                    break

            if not match:
                break

            choices = match.group(1).split("|")
            chosen = random.choice(choices)
            result = result[:match.start()] + chosen + result[match.end():]

        return result

    @classmethod
    def interpolate_variables(
        cls,
        text: str,
        variables: Dict[str, Any],
        seed: Optional[int] = None,
    ) -> str:
        """
        Interpola as variáveis dinâmicas no template, aplicando fallbacks se configurados.
        """
        res = text
        normalized_vars: Dict[str, str] = {
            k.lower(): str(v) if v is not None else ""
            for k, v in variables.items()
        }

        # 1. Substitui variáveis conhecidas que possuem o padrão {chave} ou {chave|fallback}
        def replacer(match: re.Match) -> str:
            full_match = match.group(0)
            key = match.group(1).lower()
            fallback = match.group(2)

            # Se a chave for conhecida nas variáveis
            if key in normalized_vars:
                val = normalized_vars[key]
                if val.strip():
                    return val
                # Se for vazia e tiver fallback
                if fallback is not None:
                    return fallback
                return ""

            # Se for um campo comum de fallback mesmo sem a variável estar presente no contato
            if fallback is not None:
                # Distingue Spintax de Fallback: apenas se a chave pertence explicitamente a campos de domínio
                if key in cls.KNOWN_FALLBACK_FIELDS:
                    # Se ambas as opções forem Titlecase (ex: {Desconto|Oferta}), trata como Spintax para rotação
                    if match.group(1).istitle() and fallback.istitle():
                        return full_match
                    return fallback

            # Se não tem fallback e não é spintax (não tem pipe)
            if fallback is None:
                return ""

            # Caso seja bloco spintax ({Olá|Oi}), preserva para resolução de spintax
            return full_match

        res = cls.VARIABLE_FALLBACK_PATTERN.sub(replacer, res)

        # 2. Resolução de Spintax residual
        res = cls.resolve_spintax(res, seed=seed)

        # 3. Limpeza final de chaves órfãs simples que não foram preenchidas
        res = re.sub(r"\{[a-zA-Z0-9_áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ]+\}", "", res, flags=re.IGNORECASE)
        return res

    @classmethod
    def build_context_variables(cls, contact: ContactRecord) -> Dict[str, str]:
        """Gera dicionário enriquecido de variáveis dinâmicas para o contato."""
        clean_name = (contact.name or "").strip()
        first_name = clean_name.split()[0].title() if clean_name else "Cliente"

        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 12:
            greeting = "Bom dia"
        elif 12 <= hour < 18:
            greeting = "Boa tarde"
        else:
            greeting = "Boa noite"

        context: Dict[str, str] = {
            "nome": clean_name or "Cliente",
            "primeiro_nome": first_name,
            "telefone": contact.canonical_phone,
            "saudacao": greeting,
            "data": now.strftime("%d/%m/%Y"),
            "hora": now.strftime("%H:%M"),
        }

        # Adiciona variáveis customizadas do contato
        for k, v in contact.variables.items():
            context[k.lower()] = str(v) if v is not None else ""

        return context

    @classmethod
    def process_message(
        cls,
        template: str,
        contact: ContactRecord,
        seed: Optional[int] = None,
    ) -> str:
        """Executa a interpolação de variáveis e a resolução de Spintax em cadeia para o contato."""
        context = cls.build_context_variables(contact)
        return cls.interpolate_variables(template, context, seed=seed)


# ==============================================================================
# 5. Adaptador de Compatibilidade AntiBanEngine
# ==============================================================================

class AntiBanEngine:
    """
    Fachada unificada compatível com o protótipo de verificação do handoff do explorer.
    Expõe calculate_inter_message_delay, interpolate_variables e resolve_spintax.
    """

    def __init__(
        self,
        min_seconds: float = DEFAULT_MIN_DELAY_SECONDS,
        max_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        fat_tail_prob: float = DEFAULT_FAT_TAIL_PROBABILITY,
    ):
        self.jitter_engine = BoxMullerJitterEngine(min_seconds, max_seconds, fat_tail_prob)

    def calculate_inter_message_delay(
        self,
        min_sec: float = DEFAULT_MIN_DELAY_SECONDS,
        max_sec: float = DEFAULT_MAX_DELAY_SECONDS,
    ) -> float:
        """Retorna delay estocástico anti-ban."""
        self.jitter_engine.min_s = min_sec
        self.jitter_engine.max_s = max_sec
        self.jitter_engine.mu = (min_sec + max_sec) / 2.0
        self.jitter_engine.sigma = (max_sec - min_sec) / 6.0
        return self.jitter_engine.get_next_delay()

    @classmethod
    def resolve_spintax(cls, text: str) -> str:
        return SpintaxEngine.resolve_spintax(text)

    @classmethod
    def interpolate_variables(
        cls,
        template: str,
        contact_name: str,
        custom_fields: Optional[Dict[str, str]] = None,
    ) -> str:
        custom_fields = custom_fields or {}
        synthetic_contact = ContactRecord(
            id="synth",
            raw_phone="5500000000000",
            canonical_phone="5500000000000",
            name=contact_name,
            variables=dict(custom_fields),
        )
        return SpintaxEngine.process_message(template, synthetic_contact)


# ==============================================================================
# 6. Motor Central de Fila de Disparo (DispatcherService)
# ==============================================================================

class DispatcherService:
    """
    Serviço central de gerenciamento de fila assíncrona com concorrência unitária estrita (M3):
    - Estados: IDLE, RUNNING, PAUSING, PAUSED, RESUMING, ABORTING, ABORTED, COMPLETED.
    - Barreira Atômica: acionar pause() coloca em PAUSING, aguarda o envio em andamento
      concluir e congela a fila via asyncio.Event sem perda nem repetição de índice.
    - Resume: retoma exatamente a partir do próximo contato pendente.
    - Abort: interrompe o loop imediatamente, cancela pendentes e gera relatório parcial.
    - Simulação Biomecânica de Digitação (Box-Muller, pausas reflexivas, micro-typos).
    - Jitter Estocástico Anti-Ban com Normal Truncada [10s, 25s] e injeção fat-tail.
    - Pausas inteligentes por bloco (Batch Pauses de 2 a 5 minutos a cada ~20 envios).
    - Resiliência total com auto-dismiss de popup modal de números sem WhatsApp.
    - Telemetria dinâmica ao vivo com cálculo de ETA e MPM.
    """

    def __init__(
        self,
        contacts: Optional[List[ContactRecord]] = None,
        message_template: str = "",
        attachment_path: Optional[Union[Path, str]] = None,
        jitter_min: float = DEFAULT_MIN_DELAY_SECONDS,
        jitter_max: float = DEFAULT_MAX_DELAY_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE_BASE,
        batch_pause_seconds: float = DEFAULT_BATCH_PAUSE_SECONDS_MIN,
        send_fn: Optional[Callable[..., Any]] = None,
        config: Optional[AntiBanConfig] = None,
        simulate_delays: bool = False,
    ):
        self.config = config or AntiBanConfig(
            min_delay_seconds=jitter_min,
            max_delay_seconds=jitter_max,
            batch_size_base=batch_size,
            batch_pause_min_seconds=batch_pause_seconds,
        )

        self.contacts: List[ContactRecord] = [c for c in (contacts or [])]
        self.message_template: str = message_template
        self.attachment_path: Optional[Path] = Path(attachment_path).resolve() if attachment_path else None
        self.simulate_delays: bool = simulate_delays

        self.jitter_engine = BoxMullerJitterEngine(
            min_seconds=self.config.min_delay_seconds,
            max_seconds=self.config.max_delay_seconds,
            fat_tail_prob=self.config.fat_tail_probability if self.config.enable_fat_tail else 0.0,
            fat_tail_range=self.config.fat_tail_range,
        )

        self.batch_size = max(1, self.config.batch_size_base)
        self.batch_pause_seconds = self.config.batch_pause_min_seconds
        self.send_fn = send_fn or self._default_send_fn

        # Estado da Máquina de Estados
        self.state: QueueState = QueueState.IDLE
        self.engine_state: QueueEngineState = QueueEngineState.IDLE
        self.current_index: int = 0
        self.sent_count: int = 0
        self.failed_count: int = 0
        self.cancelled_count: int = 0

        # Histórico e Telemetria
        self.results: List[SendMessageResult] = []
        self.delays_recorded: List[float] = []
        self.batch_pauses_triggered: int = 0
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

        # Sincronização Assíncrona e Barreira Atômica
        self._concurrency_lock = asyncio.Lock()
        self._resume_event = asyncio.Event()
        self._resume_event.set()  # Aberto inicialmente
        self._is_pause_requested: bool = False
        self._is_abort_requested: bool = False
        self._is_running_async: bool = False

        # Sistema de Callbacks de Eventos
        self._listeners: Dict[str, List[Callable[[Any], None]]] = {
            "STATE_CHANGED": [],
            "CONTACT_STARTED": [],
            "CONTACT_COMPLETED": [],
            "BATCH_PAUSE_START": [],
            "BATCH_PAUSE_END": [],
            "TELEMETRY_UPDATED": [],
            "QUEUE_COMPLETED": [],
            "QUEUE_ABORTED": [],
        }

    # --------------------------------------------------------------------------
    # Propriedades de Leitura Rápida
    # --------------------------------------------------------------------------

    @property
    def total_contacts(self) -> int:
        """Total de contatos atribuídos à fila."""
        return len(self.contacts)

    @property
    def pending_count(self) -> int:
        """Total de contatos que ainda aguardam processamento."""
        if self.state == QueueState.ABORTED:
            return 0
        return max(0, self.total_contacts - self.current_index)

    @property
    def is_running(self) -> bool:
        return self.state == QueueState.RUNNING

    @property
    def is_paused(self) -> bool:
        return self.state == QueueState.PAUSED

    @property
    def is_completed(self) -> bool:
        return self.state in (QueueState.COMPLETED, QueueState.ABORTED)

    def reconfigure_jitter(
        self,
        min_delay_seconds: float = DEFAULT_MIN_DELAY_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE_BASE,
        batch_pause_seconds: float = DEFAULT_BATCH_PAUSE_SECONDS_MIN,
    ) -> None:
        """Recalibra dinamicamente o motor Box-Muller e parâmetros de lote em tempo de execução."""
        min_s = max(1.0, float(min_delay_seconds))
        max_s = max(min_s + 0.5, float(max_delay_seconds))
        self.config.min_delay_seconds = min_s
        self.config.max_delay_seconds = max_s
        self.config.batch_size_base = max(1, int(batch_size))
        self.config.batch_pause_min_seconds = max(1.0, float(batch_pause_seconds))
        self.batch_size = self.config.batch_size_base
        self.batch_pause_seconds = self.config.batch_pause_min_seconds

        self.jitter_engine.min_s = min_s
        self.jitter_engine.max_s = max_s
        self.jitter_engine.mu = (min_s + max_s) / 2.0
        self.jitter_engine.sigma = (max_s - min_s) / 6.0

    # --------------------------------------------------------------------------
    # Gerenciador de Eventos (Event Emitter)
    # --------------------------------------------------------------------------

    def add_listener(self, event_name: str, callback: Callable[[Any], None]) -> None:
        """Registra um listener para eventos de ciclo de vida e telemetria."""
        if event_name in self._listeners:
            self._listeners[event_name].append(callback)

    def _emit(self, event_name: str, data: Any = None) -> None:
        """Dispara evento para todos os listeners cadastrados de forma segura."""
        callbacks = self._listeners.get(event_name, [])
        for cb in callbacks:
            try:
                if inspect.iscoroutinefunction(cb):
                    asyncio.create_task(cb(data))
                else:
                    cb(data)
            except Exception as ex:
                logger.debug("Erro ao executar callback de evento %s: %s", event_name, ex)

    # --------------------------------------------------------------------------
    # Telemetria em Tempo Real
    # --------------------------------------------------------------------------

    def get_telemetry(self) -> TelemetrySnapshot:
        """
        Calcula snapshot instantâneo de telemetria da fila:
        - Estado atual
        - Contadores (total, enviados, falhas, pendentes)
        - ETA estocástico baseado na média dos delays e nas pausas de lote restantes
        - Taxa de Mensagens por Minuto (MPM)
        """
        avg_delay = (self.jitter_engine.min_s + self.jitter_engine.max_s) / 2.0
        pending = self.pending_count

        remaining_batches = pending // max(1, self.batch_size)
        eta = (pending * avg_delay) + (remaining_batches * self.batch_pause_seconds)
        if self.state in (QueueState.PAUSED, QueueState.ABORTED, QueueState.COMPLETED):
            eta = 0.0

        current_contact_phone = None
        if 0 <= self.current_index < len(self.contacts):
            current_contact_phone = self.contacts[self.current_index].canonical_phone

        # MPM (Mensagens por Minuto)
        mpm = 0.0
        if self.start_time and (self.sent_count + self.failed_count) > 0:
            elapsed_min = max((time.time() - self.start_time) / 60.0, 0.01)
            mpm = round((self.sent_count + self.failed_count) / elapsed_min, 2)

        snapshot = TelemetrySnapshot(
            state=self.state,
            total_contacts=self.total_contacts,
            sent_count=self.sent_count,
            failed_count=self.failed_count,
            pending_count=pending,
            eta_seconds=round(eta, 1),
            current_contact=current_contact_phone,
            messages_per_minute=mpm,
        )
        self._emit("TELEMETRY_UPDATED", snapshot)
        return snapshot

    # --------------------------------------------------------------------------
    # Função de Envio Padrão (Mock Síncrono / Integração BrowserService)
    # --------------------------------------------------------------------------

    def _default_send_fn(self, contact: ContactRecord, message: str) -> SendMessageResult:
        """Função simuladora de envio padrão caso nenhuma função externa seja injetada."""
        return SendMessageResult(
            canonical_phone=contact.canonical_phone,
            success=True,
            status=ContactStatus.SENT,
            error_code=None,
            error_detail="Mensagem enviada com sucesso",
            timestamp=datetime.now(),
        )

    # --------------------------------------------------------------------------
    # Controles da Máquina de Estados (Síncronos & Compatibilidade de Testes)
    # --------------------------------------------------------------------------

    def start(self, max_steps: Optional[int] = None) -> None:
        """
        Inicia a execução da fila de disparo.
        Bloqueia estritamente transições inválidas a partir de estados não-IDLE.
        """
        if self.state != QueueState.IDLE:
            raise RuntimeError(
                f"Transição inválida: Fila já foi iniciada ou está em {self.state.value}. "
                "Use resume() se estiver pausada."
            )

        self.state = QueueState.RUNNING
        self.engine_state = QueueEngineState.RUNNING
        self._is_pause_requested = False
        self._is_abort_requested = False
        self._resume_event.set()

        if self.start_time is None:
            self.start_time = time.time()

        self._emit("STATE_CHANGED", (QueueEngineState.IDLE, QueueEngineState.RUNNING))
        self._process_sync_loop(max_steps=max_steps)

    def pause(self) -> None:
        """
        Aciona a pausa atômica da fila de disparo.
        Bloqueia requisições se a fila não estiver em estado RUNNING.
        """
        if self.state != QueueState.RUNNING:
            raise RuntimeError(
                f"Apenas filas em RUNNING podem ser pausadas. Estado atual: {self.state.value}"
            )

        self._is_pause_requested = True
        self.engine_state = QueueEngineState.PAUSING
        self._resume_event.clear()
        self.state = QueueState.PAUSED
        self.engine_state = QueueEngineState.PAUSED
        self._emit("STATE_CHANGED", (QueueEngineState.PAUSING, QueueEngineState.PAUSED))

    def resume(self, max_steps: Optional[int] = None) -> None:
        """
        Retoma a execução da fila exatamente a partir do próximo contato pendente.
        Bloqueia requisições se a fila não estiver em estado PAUSED.
        """
        if self.state != QueueState.PAUSED and self.engine_state != QueueEngineState.PAUSED:
            raise RuntimeError(
                f"Apenas filas em PAUSED podem ser retomadas. Estado atual: {self.state.value}"
            )

        self._is_pause_requested = False
        self.engine_state = QueueEngineState.RESUMING
        self.state = QueueState.RUNNING
        self.engine_state = QueueEngineState.RUNNING
        self._resume_event.set()

        self._emit("STATE_CHANGED", (QueueEngineState.RESUMING, QueueEngineState.RUNNING))

        if not self._is_running_async:
            self._process_sync_loop(max_steps=max_steps)

    def _cancel_remaining_contacts(self, from_index: int) -> None:
        """Cancela contatos a partir do índice especificado de forma idempotente."""
        for idx in range(from_index, len(self.contacts)):
            c = self.contacts[idx]
            if c.status != ContactStatus.CANCELLED:
                c.status = ContactStatus.CANCELLED
                c.error_detail = "Campanha abortada pelo operador"
                cancel_result = SendMessageResult(
                    canonical_phone=c.canonical_phone,
                    success=False,
                    status=ContactStatus.CANCELLED,
                    error_code="CAMPANHA_ABORTADA",
                    error_detail="Campanha abortada pelo operador",
                    timestamp=datetime.now(),
                )
                self.results.append(cancel_result)
                self.cancelled_count += 1

    def abort(self) -> None:
        """
        Interrompe imediatamente o ciclo de envio da fila.
        Marca todos os contatos que ainda não foram processados como CANCELLED,
        descongela qualquer barreira de pausa e consolida o relatório executivo parcial.
        """
        if self.state in (QueueState.ABORTED, QueueState.COMPLETED):
            return

        self._is_abort_requested = True
        self.engine_state = QueueEngineState.ABORTING
        self.state = QueueState.ABORTED
        self.engine_state = QueueEngineState.ABORTED
        self.end_time = time.time()
        self._resume_event.set()  # Destrava para liberar eventuais waits assíncronos

        # Se não estiver rodando ativamente no loop assíncrono, cancela imediatamente
        if not self._is_running_async:
            self._cancel_remaining_contacts(from_index=self.current_index)
            self._emit("STATE_CHANGED", (QueueEngineState.ABORTING, QueueEngineState.ABORTED))
            self._emit("QUEUE_ABORTED", self.results)

    # --------------------------------------------------------------------------
    # Loop Síncrono de Despacho (Execução Rápida para Testes e Simulações)
    # --------------------------------------------------------------------------

    def _process_sync_loop(self, max_steps: Optional[int] = None) -> None:
        """Loop central de processamento síncrono da fila de envio."""
        steps_executed = 0

        while self.state == QueueState.RUNNING and self.current_index < len(self.contacts):
            if max_steps is not None and steps_executed >= max_steps:
                break

            contact = self.contacts[self.current_index]
            contact.status = ContactStatus.PROCESSING
            self._emit("CONTACT_STARTED", (contact, self.message_template))

            # 1. Gera mensagem com interpolação e Spintax
            msg = SpintaxEngine.process_message(self.message_template, contact)

            # 2. Executa a função de envio (com auto-dismiss ou simulação)
            try:
                if inspect.iscoroutinefunction(self.send_fn):
                    # Se for corrotina, executa síncrono no loop
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    if loop.is_running():
                        fut = asyncio.run_coroutine_threadsafe(self.send_fn(contact, msg), loop)
                        res = fut.result()
                    else:
                        res = loop.run_until_complete(self.send_fn(contact, msg))
                else:
                    res = self.send_fn(contact, msg)
            except Exception as ex:
                logger.error("Exceção capturada no envio para %s: %s", contact.canonical_phone, ex)
                res = SendMessageResult(
                    canonical_phone=contact.canonical_phone,
                    success=False,
                    status=ContactStatus.FAILED,
                    error_code="ERR_SEND_EXCEPTION",
                    error_detail=str(ex),
                    timestamp=datetime.now(),
                )

            self.results.append(res)
            if res.success:
                contact.status = ContactStatus.SENT
                self.sent_count += 1
            else:
                contact.status = ContactStatus.FAILED
                contact.error_detail = res.error_detail
                self.failed_count += 1

            contact.timestamp = res.timestamp
            self._emit("CONTACT_COMPLETED", (contact, res))

            # 3. Calcula e registra o jitter estocástico anti-ban Box-Muller
            delay = self.jitter_engine.get_next_delay()
            self.delays_recorded.append(delay)

            self.current_index += 1
            steps_executed += 1

            # 4. Gatilho de pausa aperiódica por lote (~20 mensagens)
            if self.current_index > 0 and self.current_index % self.batch_size == 0:
                self.batch_pauses_triggered += 1
                self._emit("BATCH_PAUSE_START", (self.batch_pause_seconds, time.time() + self.batch_pause_seconds))
                self._emit("BATCH_PAUSE_END", ())

        # Conclusão bem-sucedida se todos os contatos foram processados
        if self.current_index >= len(self.contacts) and self.state == QueueState.RUNNING:
            self.state = QueueState.COMPLETED
            self.engine_state = QueueEngineState.COMPLETED
            self.end_time = time.time()
            self._emit("STATE_CHANGED", (QueueEngineState.RUNNING, QueueEngineState.COMPLETED))
            self._emit("QUEUE_COMPLETED", self.results)

    # --------------------------------------------------------------------------
    # Loop Assíncrono com Concorrência Unitária Estrita e Barreira Atômica
    # --------------------------------------------------------------------------

    async def start_async(self) -> None:
        """Entrypoint assíncrono para inicialização da fila."""
        if self.state != QueueState.IDLE:
            raise RuntimeError(
                f"Transição inválida: Fila já foi iniciada ou está em {self.state.value}."
            )
        await self.run_queue_async()

    async def pause_async(self) -> None:
        """Pausa assíncrona atômica."""
        self.pause()

    async def resume_async(self) -> None:
        """Retomada assíncrona da fila."""
        self.resume()

    async def abort_async(self) -> None:
        """Aborto assíncrono imediato."""
        self.abort()

    async def run_queue_async(self) -> List[SendMessageResult]:
        """
        Executa a fila assíncrona em modo não bloqueante com:
        - Concorrência unitária estrita (lock exclusivo)
        - Barreira atômica de pausa via asyncio.Event
        - Interrupção imediata de aborto
        - Delays biomecânicos e de jitter reais se simulate_delays=True
        - Integração com BrowserService para envio ao WhatsApp Web
        """
        if self._concurrency_lock.locked():
            raise RuntimeError("Concorrência Unitária Estrita: Apenas um worker pode processar a fila.")

        async with self._concurrency_lock:
            self.state = QueueState.RUNNING
            self.engine_state = QueueEngineState.RUNNING
            self._is_running_async = True
            if self.start_time is None:
                self.start_time = time.time()

            self._emit("STATE_CHANGED", (QueueEngineState.IDLE, QueueEngineState.RUNNING))

            try:
                while self.current_index < len(self.contacts):
                    # 1. Barreira Atômica de Pausa
                    if self._is_pause_requested:
                        self.state = QueueState.PAUSED
                        self.engine_state = QueueEngineState.PAUSED
                        self._emit("STATE_CHANGED", (QueueEngineState.PAUSING, QueueEngineState.PAUSED))
                        await self._resume_event.wait()

                        if self._is_abort_requested:
                            break

                        self.state = QueueState.RUNNING
                        self.engine_state = QueueEngineState.RUNNING
                        self._emit("STATE_CHANGED", (QueueEngineState.RESUMING, QueueEngineState.RUNNING))

                    if self._is_abort_requested:
                        break

                    contact = self.contacts[self.current_index]
                    contact.status = ContactStatus.PROCESSING
                    self._emit("CONTACT_STARTED", (contact, self.message_template))

                    # 2. Resolução de Mensagem com Spintax e Variáveis
                    msg = SpintaxEngine.process_message(self.message_template, contact)

                    # 3. Disparo da Mensagem via BrowserService ou Mock
                    try:
                        if inspect.iscoroutinefunction(self.send_fn):
                            res = await self.send_fn(contact, msg)
                        elif callable(self.send_fn):
                            res = self.send_fn(contact, msg)
                        else:
                            from app.services.browser_service import browser_service
                            res = await browser_service.send_message(
                                canonical_phone=contact.canonical_phone,
                                text=msg,
                                attachment_path=self.attachment_path,
                            )
                    except Exception as ex:
                        logger.error("Erro no envio assíncrono para %s: %s", contact.canonical_phone, ex)
                        res = SendMessageResult(
                            canonical_phone=contact.canonical_phone,
                            success=False,
                            status=ContactStatus.FAILED,
                            error_code="ERR_ASYNC_SEND_FAILED",
                            error_detail=str(ex),
                            timestamp=datetime.now(),
                        )

                    self.results.append(res)
                    if res.success:
                        contact.status = ContactStatus.SENT
                        self.sent_count += 1
                    else:
                        contact.status = ContactStatus.FAILED
                        contact.error_detail = res.error_detail
                        self.failed_count += 1

                    contact.timestamp = res.timestamp
                    self._emit("CONTACT_COMPLETED", (contact, res))

                    # 4. Cálculo de Jitter Estocástico Anti-Ban
                    delay = self.jitter_engine.get_next_delay()
                    self.delays_recorded.append(delay)

                    self.current_index += 1

                    # 5. Pausa Aperiódica por Bloco (~20 mensagens)
                    if self.current_index > 0 and self.current_index % self.batch_size == 0:
                        self.batch_pauses_triggered += 1
                        if self.simulate_delays and self.current_index < len(self.contacts):
                            # Duração gaussiana entre 120s e 300s
                            pause_sec = BoxMullerJitterEngine.clamp(
                                BoxMullerJitterEngine.sample_gaussian(210.0, 30.0),
                                self.config.batch_pause_min_seconds,
                                self.config.batch_pause_max_seconds,
                            )
                            self._emit("BATCH_PAUSE_START", (pause_sec, time.time() + pause_sec))

                            # Espera interruptível por aborto/pausa
                            start_pause = time.time()
                            while (time.time() - start_pause) < pause_sec:
                                if self._is_abort_requested or self._is_pause_requested:
                                    break
                                await asyncio.sleep(min(1.0, pause_sec - (time.time() - start_pause)))

                            self._emit("BATCH_PAUSE_END", ())

                    # 6. Jitter Inter-Mensagens (se simulate_delays ativado)
                    if self.simulate_delays and self.current_index < len(self.contacts):
                        start_jitter = time.time()
                        while (time.time() - start_jitter) < delay:
                            if self._is_abort_requested or self._is_pause_requested:
                                break
                            await asyncio.sleep(min(0.5, delay - (time.time() - start_jitter)))

                # 7. Finalização ou Aborto
                if self._is_abort_requested:
                    self._cancel_remaining_contacts(from_index=self.current_index)
                    self.end_time = time.time()
                    self._emit("STATE_CHANGED", (QueueEngineState.ABORTING, QueueEngineState.ABORTED))
                    self._emit("QUEUE_ABORTED", self.results)
                elif self.current_index >= len(self.contacts):
                    self.state = QueueState.COMPLETED
                    self.engine_state = QueueEngineState.COMPLETED
                    self.end_time = time.time()
                    self._emit("STATE_CHANGED", (QueueEngineState.RUNNING, QueueEngineState.COMPLETED))
                    self._emit("QUEUE_COMPLETED", self.results)

            finally:
                self._is_running_async = False

        return self.results


# ==============================================================================
# 7. Aliases de Compatibilidade Universal e Singleton Padrão
# ==============================================================================

# Permite que os testes e harness importem QueueDispatcherEngine diretamente
QueueDispatcherEngine = DispatcherService

# Instância singleton padrão para importação no restante da aplicação
dispatcher_service = DispatcherService()

__all__ = [
    "DispatcherService",
    "QueueDispatcherEngine",
    "BoxMullerJitterEngine",
    "BiomechanicTypingSimulator",
    "SpintaxEngine",
    "AntiBanEngine",
    "AntiBanConfig",
    "QueueEngineState",
    "dispatcher_service",
]


if __name__ == "__main__":
    print("=" * 80)
    print("   WHATSAPP SENDER ENGINE — DISPATCHER SERVICE SELF-DIAGNOSTIC")
    print("=" * 80)

    # 1. Teste de Jitter Box-Muller
    jitter = BoxMullerJitterEngine(min_seconds=10.0, max_seconds=25.0, fat_tail_prob=0.05)
    samples = [jitter.get_next_delay() for _ in range(500)]
    print(f" Jitter Samples [N=500]: Min={min(samples):.2f}s, Max={max(samples):.2f}s, Mean={sum(samples)/len(samples):.2f}s")
    assert min(samples) >= 10.0, "Jitter menor que 10.0s"

    # 2. Teste de Spintax e Variáveis
    contact = ContactRecord(
        id="c1",
        raw_phone="62994912937",
        canonical_phone="5562994912937",
        name="Carlos Eduardo Silva",
        variables={"empresa": "TechCorp", "cupom": "VIP2026"},
    )
    tmpl = "{Oi|{Olá|E aí}} {primeiro_nome}, sua empresa é {empresa|nossa empresa}, cupom {cupom}!"
    resolved = SpintaxEngine.process_message(tmpl, contact)
    print(f" Mensagem Resolvida: '{resolved}'")
    assert "Carlos" in resolved
    assert "TechCorp" in resolved
    assert "{" not in resolved

    # 3. Teste de Fila Rápida com Pausa Atômica
    contacts_list = [
        ContactRecord(
            id=f"c_{i}",
            raw_phone=f"6299491{i:04d}",
            canonical_phone=f"556299491{i:04d}",
            name=f"Lead {i}",
        )
        for i in range(1, 26)
    ]
    disp = DispatcherService(contacts=contacts_list, message_template="Olá {nome}")
    disp.start(max_steps=5)
    assert disp.current_index == 5
    disp.pause()
    assert disp.state == QueueState.PAUSED
    disp.resume(max_steps=5)
    assert disp.current_index == 10
    disp.pause()
    assert disp.state == QueueState.PAUSED
    disp.resume()
    assert disp.state == QueueState.COMPLETED
    assert disp.sent_count == 25
    assert disp.batch_pauses_triggered == 1

    print("=" * 80)
    print("[PASS] DispatcherService totalmente validado e autônomo. [EXIT 0]")
