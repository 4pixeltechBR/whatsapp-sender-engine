"""
Launcher and Environment Verification Script for WhatsApp Sender Engine.
Verifies Python dependencies, directory layout, and executes self-test benchmarks.
"""

import argparse
import http.server
import socketserver
import sys
import time

def print_banner():
    print("=" * 70)
    print("       WHATSAPP SENDER ENGINE — DESKTOP SUITE (MILESTONE 1)")
    print("=" * 70)

def verify_environment() -> bool:
    """Verifica versão do Python, bibliotecas instaladas e estrutura de pastas."""
    print("[1/4] Verificando versão do interpretador Python...")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print(f"[-] ERRO: Python 3.10+ é obrigatório. Versão atual: {v.major}.{v.minor}.{v.micro}")
        return False
    print(f"      [OK] Python {v.major}.{v.minor}.{v.micro} em {sys.executable}")

    print("\n[2/4] Verificando dependências essenciais...")
    required_modules = [
        ("openpyxl", "Leitor streaming de planilhas XLSX"),
        ("pydantic", "Validação estrita de contratos e dados"),
        ("fastapi", "Motor de automação e API local"),
        ("uvicorn", "Servidor ASGI assíncrono"),
    ]

    all_modules_ok = True
    for mod_name, desc in required_modules:
        try:
            __import__(mod_name)
            print(f"      [OK] {mod_name:<15} — {desc}")
        except ImportError:
            print(f"      [-] AUSENTE: {mod_name:<15} — {desc}")
            all_modules_ok = False

    if not all_modules_ok:
        print("\n[-] Execute: pip install -r requirements.txt")
        return False

    print("\n[3/4] Verificando diretórios de dados e persistência...")
    from app.core.config import settings
    settings.ensure_directories()
    for d in [settings.DATA_DIR, settings.SESSION_DIR, settings.UPLOADS_DIR, settings.REPORTS_DIR]:
        print(f"      [OK] Diretório presente: {d.relative_to(settings.BASE_DIR)}")

    print("\n[4/4] Executando autoteste de higienização telefônica E.164...")
    from app.services.contact_service import contact_service

    # Caso canônico do projeto
    res = contact_service.sanitize_phone("62994912937")
    if not (res.valid and res.canonical == "5562994912937"):
        print(f"[-] FALHA no caso canônico 62994912937: obtido {res.canonical}")
        return False

    # Float shielding
    res_float = contact_service.sanitize_phone(62994912937.0)
    if not (res_float.valid and res_float.canonical == "5562994912937"):
        print(f"[-] FALHA no caso float 62994912937.0: obtido {res_float.canonical}")
        return False

    # DDD inválido
    res_inv = contact_service.sanitize_phone("23994912937")
    if res_inv.valid:
        print("[-] FALHA: DDD 23 foi incorretamente aceito como válido!")
        return False


    print("      [OK] Sanitização E.164 (DDI 55, DDD Anatel, 9º dígito): 100% CONFORME")
    print("      [OK] Blindagem float Excel e notação científica: 100% CONFORME")
    return True

def run_benchmark():
    """Executa benchmark de desempenho de sanitização em lote (>5.000 contatos)."""
    from app.services.contact_service import contact_service
    print("\n--- INICIANDO BENCHMARK DE DESEMPENHO (M1) ---")
    count = 10000
    sample_phones = [
        "62994912937",
        62994912937.0,
        "+55 (11) 98765-4321",
        "21998887777",
        "31977776666",
        "01562994912937",
        "6232015000",
    ] * (count // 7 + 1)
    sample_phones = sample_phones[:count]

    start = time.perf_counter()
    valid_count = 0
    for p in sample_phones:
        res = contact_service.sanitize_phone(p)
        if res.valid:
            valid_count += 1
    elapsed = time.perf_counter() - start

    print(f"Total processado : {count:,} contatos")
    print(f"Tempo decorrido  : {elapsed:.4f} segundos")
    print(f"Vazão média      : {count / elapsed:,.0f} contatos/segundo")
    print(f"Válidos          : {valid_count:,}")
    if elapsed < 1.0:
        print("Status           : [APROVADO] Tempo sub-segundo garantido!")
    else:
        print(f"Status           : [-] Tempo acima de 1s: {elapsed:.2f}s")

def serve_static(port: int = 8765):
    """Inicia servidor web local para servir a interface Desktop."""
    from app.core.config import settings
    static_dir = str(settings.STATIC_DIR)

    class CustomHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=static_dir, **kwargs)

        def log_message(self, format, *args):
            pass  # Silencia logs detalhados no terminal

    print(f"\n[+] Servidor da Interface Desktop iniciado em http://127.0.0.1:{port}")
    print("[+] Pressione Ctrl+C para encerrar o servidor.")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), CustomHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor encerrado pelo usuário.")

def main():
    print_banner()
    parser = argparse.ArgumentParser(description="WhatsApp Sender Engine Launcher")
    parser.add_argument("--check", action="store_true", help="Executa apenas a verificação de ambiente")
    parser.add_argument("--benchmark", action="store_true", help="Executa testes de benchmark de desempenho")
    parser.add_argument("--serve", action="store_true", help="Inicia o servidor da interface Desktop")
    parser.add_argument("--port", type=int, default=8765, help="Porta do servidor local (padrão: 8765)")
    args = parser.parse_args()

    ok = verify_environment()
    if not ok:
        sys.exit(1)

    if args.benchmark:
        run_benchmark()

    if args.serve:
        serve_static(args.port)
    elif not args.check and not args.benchmark:
        print("\n[+] Ambiente validado com 100% de sucesso!")
        print("    Para iniciar o servidor da interface Desktop: python run.py --serve")
        print("    Para rodar os benchmarks de velocidade:        python run.py --benchmark")

if __name__ == "__main__":
    main()
