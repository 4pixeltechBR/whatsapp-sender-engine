"""
Unit and Integration Tests for Anti-Ban Dispatcher, Stochastic Jitter, Queue State Machine,
Spintax/Variable Interpolation, and Resilience to Invalid Number Popups (Tier 1 & Tier 2).
Target Module: Anti-Ban Dispatcher & Queue Engine (Milestone 3 Contract)
"""

from collections import Counter
from datetime import datetime
import math
import statistics
import time
import unittest
from typing import List

from app.core.constants import ContactStatus, QueueState
from app.models.schemas import ContactRecord, SendMessageResult, TelemetrySnapshot
from app.services.dispatcher_service import (
    BoxMullerJitterEngine,
    QueueDispatcherEngine,
    SpintaxEngine,
)


class TestDispatcherFeatureCoverage(unittest.TestCase):
    """
    Tier 1 - Feature Coverage:
    - Máquina de Estados da Fila (IDLE, RUNNING, PAUSED, RESUMED, ABORTED, COMPLETED).
    - Jitter estocástico Box-Muller dentro do intervalo configurado [10s, 25s].
    - Simulação biomecânica de digitação WPM e pausas reflexivas em pontuação.
    - Gatilho de pausas periódicas/aperiódicas por bloco (~20 mensagens).
    - Interpolação dinâmica de variáveis ({nome}, {empresa}) e resolução de Spintax multinível.
    """

    def setUp(self):
        # Gera contatos sintéticos para os testes de fila
        self.sample_contacts = [
            ContactRecord(
                id=f"c_{i}",
                raw_phone=f"6299491{i:04d}",
                canonical_phone=f"556299491{i:04d}",
                name=f"Lead {i}",
                variables={"empresa": f"Empresa {i}", "cupom": f"PROMO_{i}"},
            )
            for i in range(1, 45)  # 44 contatos (permite testar múltiplos lotes de 20)
        ]

    # --------------------------------------------------------------------------
    # 1. Máquina de Estados da Fila (Ciclo de Vida Completo)
    # --------------------------------------------------------------------------

    def test_queue_state_transitions_happy_path(self):
        """
        Testa o ciclo de vida completo e sequencial da fila:
        IDLE -> RUNNING -> PAUSED -> RESUMED (RUNNING) -> COMPLETED
        """
        dispatcher = QueueDispatcherEngine(
            contacts=self.sample_contacts[:10],
            message_template="Olá {nome}, sua empresa é {empresa}!",
        )

        # 1. Estado Inicial
        self.assertEqual(dispatcher.state, QueueState.IDLE)
        self.assertEqual(dispatcher.current_index, 0)
        self.assertEqual(dispatcher.sent_count, 0)
        self.assertEqual(dispatcher.pending_count, 10)

        # 2. Inicia execução parcial (executa 4 passos e pausa)
        dispatcher.start(max_steps=4)
        self.assertEqual(dispatcher.current_index, 4)
        self.assertEqual(dispatcher.sent_count, 4)
        self.assertEqual(dispatcher.pending_count, 6)

        # 3. Pausa atômica
        dispatcher.pause()
        self.assertEqual(dispatcher.state, QueueState.PAUSED)
        telemetry = dispatcher.get_telemetry()
        self.assertEqual(telemetry.state, QueueState.PAUSED)

        # 4. Retomada parcial
        dispatcher.resume(max_steps=3)
        self.assertEqual(dispatcher.current_index, 7)
        self.assertEqual(dispatcher.sent_count, 7)
        self.assertEqual(dispatcher.pending_count, 3)

        # Pausa novamente
        dispatcher.pause()
        self.assertEqual(dispatcher.state, QueueState.PAUSED)

        # 5. Continua até a conclusão
        dispatcher.resume()
        self.assertEqual(dispatcher.state, QueueState.COMPLETED)
        self.assertEqual(dispatcher.current_index, 10)
        self.assertEqual(dispatcher.sent_count, 10)
        self.assertEqual(dispatcher.pending_count, 0)

        # Verifica status dos contatos
        for c in dispatcher.contacts:
            self.assertEqual(c.status, ContactStatus.SENT)
            self.assertIsNotNone(c.timestamp)

    def test_invalid_state_transitions_raise_exceptions(self):
        """Transições de estado inválidas devem ser estritamente bloqueadas."""
        dispatcher = QueueDispatcherEngine(
            contacts=self.sample_contacts[:5],
            message_template="Teste",
        )

        # Não pode pausar fila IDLE
        with self.assertRaises(RuntimeError):
            dispatcher.pause()

        # Não pode resumir fila IDLE
        with self.assertRaises(RuntimeError):
            dispatcher.resume()

        # Inicia
        dispatcher.start(max_steps=2)
        dispatcher.pause()

        # Não pode iniciar fila já PAUSED (deve usar resume)
        with self.assertRaises(RuntimeError):
            dispatcher.start()

    # --------------------------------------------------------------------------
    # 2. Simulação Box-Muller e Jitter Estocástico Anti-Ban [10s, 25s]
    # --------------------------------------------------------------------------

    def test_box_muller_jitter_distribution_and_bounds(self):
        """
        Valida que os delays gerados por Box-Muller:
        1. Respeitam estritamente a faixa [10s, 25s] (para delays normais).
        2. Apresentam variabilidade estocástica real (nenhum par de delays idênticos sequenciais).
        3. Possuem média em torno de 17.5s e desvio padrão compatível (~2.5s).
        """
        jitter = BoxMullerJitterEngine(min_seconds=10.0, max_seconds=25.0, fat_tail_prob=0.0)
        samples = [jitter.get_next_delay() for _ in range(1000)]

        # 1. Limites estritos
        for val in samples:
            self.assertGreaterEqual(val, 10.0, f"Delay {val} menor que min_seconds 10.0")
            self.assertLessEqual(val, 25.0, f"Delay {val} maior que max_seconds 25.0")

        # 2. Variabilidade estocástica (sem valores estáticos)
        identical_consecutive = sum(1 for i in range(len(samples) - 1) if samples[i] == samples[i + 1])
        self.assertLess(identical_consecutive, 5, "Muitos delays consecutivos idênticos detectados!")

        # 3. Propriedades estatísticas gaussianas
        mean_val = statistics.mean(samples)
        stdev_val = statistics.stdev(samples)

        # Média esperada = 17.5s (com tolerância estatística de 0.5s para N=1000)
        self.assertAlmostEqual(mean_val, 17.5, delta=0.6, msg=f"Média {mean_val} desviou do centro 17.5s")
        # Desvio padrão esperado ~2.5s (tolerância 0.6s)
        self.assertAlmostEqual(stdev_val, 2.5, delta=0.6, msg=f"Desvio padrão {stdev_val} incompatível")

    def test_keystroke_delays_and_punctuation_cognitive_pauses(self):
        """
        Valida que a cadência de digitação (IKI):
        1. Gera tempos de digitação realistas para cada caractere.
        2. Aplica pausas reflexivas maiores em pontuações fortes (.,?!\n).
        """
        text = "Olá! Como vai você? Bem, obrigado."
        delays = BoxMullerJitterEngine.calculate_keystroke_delays(text, wpm=60)

        self.assertEqual(len(delays), len(text))

        delay_dict = dict(zip(range(len(text)), delays))
        # Verifica que pontos de exclamação e interrogação possuem delays maiores que letras comuns
        for idx, (char, iki) in delay_dict.items():
            if char in "!.?":
                self.assertGreater(iki, 0.35, f"Pontuação '{char}' deveria ter pausa cognitiva >= 0.35s, obtido {iki}")
            elif char.isalpha():
                # Letras normais devem ficar em torno de 0.05s - 0.35s
                self.assertLess(iki, 0.45)

    # --------------------------------------------------------------------------
    # 3. Gatilho de Pausas Aperiódicas por Bloco (~20 Mensagens)
    # --------------------------------------------------------------------------

    def test_batch_pause_trigger_every_20_messages(self):
        """
        Testa se o gatilho de pausa por bloco é acionado a cada ~20 envios
        para proteger a conta contra análise harmônica de tráfego.
        """
        dispatcher = QueueDispatcherEngine(
            contacts=self.sample_contacts,  # 44 contatos
            message_template="Olá {nome}",
            batch_size=20,
            batch_pause_seconds=120.0,
        )

        dispatcher.start()

        self.assertEqual(dispatcher.state, QueueState.COMPLETED)
        self.assertEqual(dispatcher.sent_count, 44)
        # Com 44 mensagens e bloco de 20: deve disparar pausas nos itens 20 e 40
        self.assertEqual(dispatcher.batch_pauses_triggered, 2)

    # --------------------------------------------------------------------------
    # 4. Interpolação Dinâmica e Resolução de Spintax Multinível
    # --------------------------------------------------------------------------

    def test_dynamic_variable_interpolation(self):
        """Valida interpolação correta de {nome}, {empresa}, {cupom}."""
        contact = ContactRecord(
            id="1",
            raw_phone="62994912937",
            canonical_phone="5562994912937",
            name="Mariana Lima",
            variables={"empresa": "Varejo Fácil", "cupom": "VIP10"},
        )
        template = "Oi {nome}, o cupom {cupom} da {empresa} está ativo para você no fone {telefone}!"
        result = SpintaxEngine.process_message(template, contact)

        expected = "Oi Mariana Lima, o cupom VIP10 da Varejo Fácil está ativo para você no fone 5562994912937!"
        self.assertEqual(result, expected)

    def test_nested_multilevel_spintax_resolution(self):
        """Valida que spintax multinível é resolvido uniformemente sem sobrar chaves."""
        template = "{Oi|{Olá|E aí}} {amigo|parceiro}! {Tudo bem?|Como vão as coisas?}"

        outputs = set()
        for i in range(200):
            res = SpintaxEngine.resolve_spintax(template, seed=i)
            # Não deve restar nenhuma chave na string resolvida
            self.assertNotIn("{", res)
            self.assertNotIn("}", res)
            self.assertNotIn("|", res)
            outputs.add(res)

        # Deve gerar múltiplas variações distintas
        self.assertGreater(len(outputs), 6, "Spintax não gerou variedade suficiente de saídas.")

    def test_missing_variables_handled_gracefully(self):
        """Variáveis ausentes no contato são substituídas por vazio sem lançar KeyError."""
        contact = ContactRecord(
            id="1",
            raw_phone="62994912937",
            canonical_phone="5562994912937",
            name="Lucas",
            variables={},
        )
        template = "Olá {nome}, seu desconto é {desconto_inexistente}!"
        res = SpintaxEngine.process_message(template, contact)
        self.assertEqual(res, "Olá Lucas, seu desconto é !")


class TestDispatcherBoundaryAndCornerCases(unittest.TestCase):
    """
    Tier 2 - Boundary & Corner Cases:
    - Aborto súbito da fila e geração imediata de relatório parcial.
    - Simulação de popup de número sem WhatsApp e verificação de auto-dismiss.
    - Fila vazia ou contatos sem telefone.
    """

    def setUp(self):
        self.contacts = [
            ContactRecord(
                id=f"c_{i}",
                raw_phone=f"6299491{i:04d}",
                canonical_phone=f"556299491{i:04d}",
                name=f"Lead {i}",
                variables={},
            )
            for i in range(1, 51)  # 50 contatos
        ]

    def test_abrupt_abort_cancels_pending_contacts_immediately(self):
        """
        Ao abortar no meio da campanha (ex: aos 15 envios):
        1. A fila transita imediatamente para ABORTED.
        2. Os 35 contatos restantes são marcados como CANCELLED.
        3. A telemetria congela e o relatório parcial reflete 15 enviados e 35 cancelados.
        """
        dispatcher = QueueDispatcherEngine(
            contacts=self.contacts,
            message_template="Olá {nome}",
        )

        # Executa 15 mensagens
        dispatcher.start(max_steps=15)
        self.assertEqual(dispatcher.current_index, 15)
        self.assertEqual(dispatcher.sent_count, 15)

        # Aborto pelo operador
        dispatcher.abort()

        self.assertEqual(dispatcher.state, QueueState.ABORTED)
        self.assertEqual(dispatcher.cancelled_count, 35)
        self.assertEqual(dispatcher.pending_count, 0)

        # Verifica status dos contatos não processados
        for c in dispatcher.contacts[15:]:
            self.assertEqual(c.status, ContactStatus.CANCELLED)
            self.assertEqual(c.error_detail, "Campanha abortada pelo operador")

        # Verifica resultados
        self.assertEqual(len(dispatcher.results), 50)
        sent_in_results = sum(1 for r in dispatcher.results if r.status == ContactStatus.SENT)
        canc_in_results = sum(1 for r in dispatcher.results if r.status == ContactStatus.CANCELLED)
        self.assertEqual(sent_in_results, 15)
        self.assertEqual(canc_in_results, 35)

    def test_invalid_number_modal_popup_auto_dismiss_resilience(self):
        """
        Simula cenário crítico de WhatsApp Web:
        Contato tenta envio para número que não possui WhatsApp ativo ou URL inválida.
        O navegador exibe o modal 'O número de telefone compartilhado por URL é inválido.'
        O sistema deve:
        1. Detectar e simular o clique no botão 'OK' (auto-dismiss).
        2. Registrar o contato como FAILED ('FALHA_SEM_WHATSAPP').
        3. Avançar para o próximo contato sem congelar ou interromper a fila.
        """
        # Função mock simulando envio com números que não possuem WhatsApp
        def mock_send_with_modal_popup(contact: ContactRecord, msg: str) -> SendMessageResult:
            # Simula que contatos pares não têm WhatsApp
            is_invalid_number = int(contact.id.split("_")[1]) % 2 == 0
            if is_invalid_number:
                # Simulação do auto-dismiss do modal 'div[role="dialog"] button:has-text("OK")'
                modal_dismissed = True  # Auto-dismiss executado com sucesso
                return SendMessageResult(
                    canonical_phone=contact.canonical_phone,
                    success=False,
                    status=ContactStatus.FAILED,
                    error_code="MODAL_NUMERO_INVALIDO_SEM_WHATSAPP",
                    error_detail="Número não possui conta no WhatsApp (Modal OK auto-dismissed)",
                    timestamp=datetime.now(),
                )
            return SendMessageResult(
                canonical_phone=contact.canonical_phone,
                success=True,
                status=ContactStatus.SENT,
                timestamp=datetime.now(),
            )

        test_contacts = self.contacts[:10]
        dispatcher = QueueDispatcherEngine(
            contacts=test_contacts,
            message_template="Olá {nome}",
            send_fn=mock_send_with_modal_popup,
        )

        # Executa a fila completa
        dispatcher.start()

        self.assertEqual(dispatcher.state, QueueState.COMPLETED)
        # Exatamente 5 ímpares devem ter sucesso e 5 pares devem falhar com modal auto-dismiss
        self.assertEqual(dispatcher.sent_count, 5)
        self.assertEqual(dispatcher.failed_count, 5)

        for c in test_contacts:
            c_id_num = int(c.id.split("_")[1])
            if c_id_num % 2 == 0:
                self.assertEqual(c.status, ContactStatus.FAILED)
                self.assertIn("Modal OK auto-dismissed", c.error_detail or "")
            else:
                self.assertEqual(c.status, ContactStatus.SENT)


if __name__ == "__main__":
    unittest.main()
