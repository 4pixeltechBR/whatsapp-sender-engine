# WhatsApp Sender Engine 🚀

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.46+-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)](https://playwright.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success?style=for-the-badge)]()

**Motor profissional e desacoplado de automação para disparo em massa via WhatsApp Web com simulação de comportamento humano biomecânico, proteção anti-ban estocástica (Box-Muller), persistência resiliente de sessão e ingestão de planilhas de alta performance.**

[🇧🇷 Português](README.md) • [🇺🇸 English](README.en.md)

</div>

---

## 📌 Por que o WhatsApp Sender Engine?

A maioria dos disparadores de WhatsApp do mercado falha devido a problemas estruturais conhecidos:
1. **Banimentos Imediatos da Meta:** Disparos realizados com intervalos robóticos estáticos ou automações sem digitação humana real acionam rapidamente os algoritmos de detecção de spam.
2. **Corrupção de Números de Telefone:** Planilhas do Excel frequentemente convertem números longos em notação científica, removem o nono dígito brasileiro ou 'engolem' algarismos durante o parsing.
3. **Travamentos e Fugas de Memória:** Bibliotecas comuns carregam planilhas inteiras na memória, travando a máquina em listas com mais de 5.000 contatos.
4. **Perda de Conexão Contínua:** Sessões que exigem nova leitura de QR Code a cada reinício do software.

O **WhatsApp Sender Engine** foi arquitetado do zero para resolver definitivamente cada uma dessas falhas, combinando uma API assíncrona robusta em **FastAPI**, automação com **Playwright Chromium Stealth** e uma interface desktop moderna e fluida.
