"""
Unified Master Test Runner for WhatsApp Sender Engine.
Executes the comprehensive 4-Tier Test Suite and outputs an executive audit report.
Usage:
    python tests/test_runner.py
    python tests/test_runner.py --tier 1
    python tests/test_runner.py --tier 2
    python tests/test_runner.py --tier 3
    python tests/test_runner.py --tier 4
    python tests/test_runner.py --verbose
"""

import argparse
import io
import os
from pathlib import Path
import sys
import time
import unittest

# Adiciona o diretório raiz ao sys.path para garantir imports absolutos
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Importa as classes de teste de cada módulo
from tests.test_contact_service import (
    TestContactServiceFeatureCoverage,
    TestContactServiceBoundaryAndCornerCases,
)
from tests.test_dispatcher import (
    TestDispatcherFeatureCoverage,
    TestDispatcherBoundaryAndCornerCases,
)
from tests.test_reporting import (
    TestReportingFeatureCoverage,
    TestReportingBoundaryAndCornerCases,
)
from tests.test_e2e_flow import (
    TestE2ECrossFeatureInteractions,
    TestE2ERealWorldScenarios,
)


# Garante encoding UTF-8 no terminal Windows se suportado
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


TIER_MAPPING = {
    1: {
        "name": "Tier 1 - Feature Coverage",
        "description": "Ingestão >5k, sanitização E.164 (67 DDDs, 9º dígito), float shield, deduplicação, estados da fila, Box-Muller, spintax e relatórios.",
        "test_classes": [
            TestContactServiceFeatureCoverage,
            TestDispatcherFeatureCoverage,
            TestReportingFeatureCoverage,
        ],
    },
    2: {
        "name": "Tier 2 - Boundary & Corner Cases",
        "description": "DDDs inexistentes (23, 70), arquivos corrompidos/vazios, números repetidos, aborto súbito da fila e modal de número sem WhatsApp.",
        "test_classes": [
            TestContactServiceBoundaryAndCornerCases,
            TestDispatcherBoundaryAndCornerCases,
            TestReportingBoundaryAndCornerCases,
        ],
    },
    3: {
        "name": "Tier 3 - Cross-Feature Interactions",
        "description": "Fluxo integrado completo: Carga 5.000 contatos -> Sanitização -> Deduplicação -> Fila -> Telemetria -> Exportação XLSX/CSV.",
        "test_classes": [
            TestE2ECrossFeatureInteractions,
        ],
    },
    4: {
        "name": "Tier 4 - Cenários Reais de Aplicação",
        "description": "Cenários de produção: Varejo com Spintax, campanha com números sem WhatsApp e pausa manual, e interrupção de emergência.",
        "test_classes": [
            TestE2ERealWorldScenarios,
        ],
    },
}


class ColoredText:
    """Suporte a cores no terminal com fallback automático."""
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @classmethod
    def format(cls, text: str, color: str) -> str:
        if os.name == "nt":
            # Habilita cores ANSI no terminal Windows se suportado
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                pass
        return f"{color}{text}{cls.RESET}"


def run_test_suite(
    selected_tier: int = 0,
    verbosity: int = 1,
) -> bool:
    """
    Executa a suíte de testes selecionada e exibe sumário executivo.
    Retorna True se todos os testes passarem, False caso contrário.
    """
    start_time = time.perf_counter()

    tiers_to_run = [selected_tier] if selected_tier in TIER_MAPPING else [1, 2, 3, 4]

    print("\n" + "=" * 80)
    print(ColoredText.format("   WHATSAPP SENDER ENGINE — SUÍTE DE TESTES E2E UNIFICADA", ColoredText.CYAN + ColoredText.BOLD))
    print("=" * 80)
    print(f" Raiz do Projeto: {ROOT_DIR}")
    print(f" Data/Hora: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" Tiers Selecionados: {', '.join(str(t) for t in tiers_to_run)}")
    print("=" * 80 + "\n")

    tier_results = []
    total_tests_run = 0
    total_failures = 0
    total_errors = 0

    for tier_id in tiers_to_run:
        tier_info = TIER_MAPPING[tier_id]
        print(ColoredText.format(f"[>] Executando {tier_info['name']}...", ColoredText.BLUE + ColoredText.BOLD))
        print(f"  {tier_info['description']}")

        suite = unittest.TestSuite()
        loader = unittest.TestLoader()

        for test_cls in tier_info["test_classes"]:
            suite.addTests(loader.loadTestsFromTestCase(test_cls))

        tier_start = time.perf_counter()
        runner = unittest.TextTestRunner(verbosity=verbosity, stream=sys.stdout)
        result = runner.run(suite)
        tier_elapsed = time.perf_counter() - tier_start

        tests_count = result.testsRun
        fails_count = len(result.failures)
        errors_count = len(result.errors)

        total_tests_run += tests_count
        total_failures += fails_count
        total_errors += errors_count

        status = "PASSED" if (fails_count == 0 and errors_count == 0) else "FAILED"
        tier_results.append({
            "tier": tier_id,
            "name": tier_info["name"],
            "tests": tests_count,
            "failures": fails_count,
            "errors": errors_count,
            "time": tier_elapsed,
            "status": status,
        })
        print("-" * 80 + "\n")

    total_elapsed = time.perf_counter() - start_time

    # ==========================================================================
    # Relatório e Matriz de Cobertura Final
    # ==========================================================================
    print("=" * 80)
    print(ColoredText.format("   MATRIZ CONSOLIDADA DE RESULTADOS POR TIER", ColoredText.BOLD))
    print("=" * 80)
    print(f"{'Tier':<8}{'Nome da Suíte':<38}{'Testes':<10}{'Falhas':<10}{'Tempo':<10}{'Status':<10}")
    print("-" * 80)

    for r in tier_results:
        color = ColoredText.GREEN if r["status"] == "PASSED" else ColoredText.RED
        status_str = ColoredText.format(r["status"], color)
        print(f"Tier {r['tier']:<3} {r['name']:<38}{r['tests']:<10}{r['failures'] + r['errors']:<10}{r['time']:.3f}s   {status_str}")

    print("=" * 80)
    print(f" Total de Asserções Executadas : {total_tests_run}")
    print(f" Falhas Encontradas            : {total_failures}")
    print(f" Erros de Execução             : {total_errors}")
    print(f" Duração Total                 : {total_elapsed:.3f} segundos")

    overall_success = (total_failures == 0 and total_errors == 0)
    if overall_success:
        print(ColoredText.format("\n[PASS] TODOS OS TESTES PASSARAM COM 100% DE SUCESSO! [EXIT 0]\n", ColoredText.GREEN + ColoredText.BOLD))
    else:
        print(ColoredText.format(f"\n[FAIL] FALHA NA SUÍTE: {total_failures + total_errors} PROBLEMAS DETECTADOS! [EXIT 1]\n", ColoredText.RED + ColoredText.BOLD))

    return overall_success


def main():
    parser = argparse.ArgumentParser(description="WhatsApp Sender Engine Test Runner")
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        default=0,
        help="Executa apenas um tier específico (1 a 4). Padrão: executa todos.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Exibe saída detalhada de cada caso de teste.",
    )
    args = parser.parse_args()

    verbosity = 2 if args.verbose else 1
    success = run_test_suite(selected_tier=args.tier, verbosity=verbosity)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
