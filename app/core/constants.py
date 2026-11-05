"""
Constants, Enums, and Regulatory Telephony Tables for WhatsApp Sender Engine.
"""

from enum import Enum
import re
from typing import Dict, Set

# Lista oficial dos 67 DDDs homologados pela Anatel no Brasil
ANATEL_DDDS: Set[int] = {
    # Região 1 (São Paulo)
    11, 12, 13, 14, 15, 16, 17, 18, 19,
    # Região 2 (Rio de Janeiro e Espírito Santo)
    21, 22, 24, 27, 28,
    # Região 3 (Minas Gerais)
    31, 32, 33, 34, 35, 37, 38,
    # Região 4 (Paraná e Santa Catarina)
    41, 42, 43, 44, 45, 46, 47, 48, 49,
    # Região 5 (Rio Grande do Sul)
    51, 53, 54, 55,
    # Região 6 (Centro-Oeste e Tocantins, Acre, Rondônia)
    61, 62, 63, 64, 65, 66, 67, 68, 69,
    # Região 7 (Bahia e Sergipe)
    71, 73, 74, 75, 77, 79,
    # Região 8 (Nordeste - PE, AL, PB, RN, CE, PI)
    81, 82, 83, 84, 85, 86, 87, 88, 89,
    # Região 9 (Norte - PA, AM, RR, AP, MA)
    91, 92, 93, 94, 95, 96, 97, 98, 99,
}

# String set para checagens O(1) de alta performance
ANATEL_DDDS_STR: Set[str] = {f"{ddd:02d}" for ddd in ANATEL_DDDS}

# Mapeamento descritivo de DDD para Estado/Região
DDD_REGION_MAP: Dict[str, str] = {
    "11": "SP - São Paulo e Região Metropolitana",
    "12": "SP - Vale do Paraíba e Litoral Norte",
    "13": "SP - Baixada Santista e Vale do Ribeira",
    "14": "SP - Bauru, Marília, Jaú, Botucatu",
    "15": "SP - Sorocaba e Itapetininga",
    "16": "SP - Ribeirão Preto, Franca, São Carlos",
    "17": "SP - São José do Rio Preto, Barretos",
    "18": "SP - Presidente Prudente, Araçatuba",
    "19": "SP - Campinas, Piracicaba, Americana",
    "21": "RJ - Rio de Janeiro e Região Metropolitana",
    "22": "RJ - Campos dos Goytacazes, Macaé, Cabo Frio",
    "24": "RJ - Volta Redonda, Petrópolis, Angra dos Reis",
    "27": "ES - Vitória e Região Metropolitana",
    "28": "ES - Cachoeiro de Itapemirim e Sul do ES",
    "31": "MG - Belo Horizonte e Região Metropolitana",
    "32": "MG - Juiz de Fora e Zona da Mata",
    "33": "MG - Governador Valadares e Vale do Rio Doce",
    "34": "MG - Uberlândia, Uberaba e Triângulo Mineiro",
    "35": "MG - Poços de Caldas, Varginha, Pouso Alegre",
    "37": "MG - Divinópolis e Centro-Oeste de MG",
    "38": "MG - Montes Claros e Norte de MG",
    "41": "PR - Curitiba e Região Metropolitana",
    "42": "PR - Ponta Grossa e Guarapuava",
    "43": "PR - Londrina e Apucarana",
    "44": "PR - Maringá e Campo Mourão",
    "45": "PR - Foz do Iguaçu e Cascavel",
    "46": "PR - Francisco Beltrão e Pato Branco",
    "47": "SC - Joinville, Blumenau, Itajaí",
    "48": "SC - Florianópolis e Criciúma",
    "49": "SC - Chapecó, Lages, Caçador",
    "51": "RS - Porto Alegre e Região Metropolitana",
    "53": "RS - Pelotas e Rio Grande",
    "54": "RS - Caxias do Sul e Passo Fundo",
    "55": "RS - Santa Maria e Uruguaiana",
    "61": "DF/GO - Brasília e Entorno do DF",
    "62": "GO - Goiânia e Região Metropolitana",
    "63": "TO - Palmas e Todo o Estado do Tocantins",
    "64": "GO - Rio Verde, Itumbiara, Caldas Novas",
    "65": "MT - Cuiabá e Região Metropolitana",
    "66": "MT - Rondonópolis e Sinop",
    "67": "MS - Campo Grande e Todo o Mato Grosso do Sul",
    "68": "AC - Rio Branco e Todo o Estado do Acre",
    "69": "RO - Porto Velho e Todo o Estado de Rondônia",
    "71": "BA - Salvador e Região Metropolitana",
    "73": "BA - Ilhéus, Itabuna e Porto Seguro",
    "74": "BA - Juazeiro e Irecê",
    "75": "BA - Feira de Santana e Alagoinhas",
    "77": "BA - Vitória da Conquista e Barreiras",
    "79": "SE - Aracaju e Todo o Estado de Sergipe",
    "81": "PE - Recife e Região Metropolitana",
    "82": "AL - Maceió e Todo o Estado de Alagoas",
    "83": "PB - João Pessoa, Campina Grande",
    "84": "RN - Natal, Mossoró",
    "85": "CE - Fortaleza e Região Metropolitana",
    "86": "PI - Teresina, Parnaíba",
    "87": "PE - Petrolina, Caruaru, Garanhuns",
    "88": "CE - Juazeiro do Norte, Sobral",
    "89": "PI - Picos, Floriano",
    "91": "PA - Belém e Região Metropolitana",
    "92": "AM - Manaus e Região Metropolitana",
    "93": "PA - Santarém e Oeste do Pará",
    "94": "PA - Marabá e Sudeste do Pará",
    "95": "RR - Boa Vista e Todo o Estado de Roraima",
    "96": "AP - Macapá e Todo o Estado do Amapá",
    "97": "AM - Interior do Estado do Amazonas",
    "98": "MA - São Luís e Região Metropolitana",
    "99": "MA - Imperatriz e Interior do Maranhão",
}

# DDI Padrão do Brasil
DEFAULT_COUNTRY_CODE = "55"

# Tamanhos canônicos no padrão E.164 nacional
CANONICAL_MOBILE_LENGTH = 13    # 55 + 2 DDD + 9 celular (ex: 5562994912937)
CANONICAL_LANDLINE_LENGTH = 12  # 55 + 2 DDD + 8 fixo (ex: 556232015000)

# Enums de ciclo de vida de contatos e processos
class ContactStatus(str, Enum):
    PENDING = "PENDENTE"
    PROCESSING = "PROCESSANDO"
    SENT = "ENVIADO"
    FAILED = "FALHA"
    CANCELLED = "CANCELADO"
    DUPLICATE = "DUPLICADO"
    INVALID = "INVALIDO"

class SessionStatus(str, Enum):
    DISCONNECTED = "DESCONECTADO"
    AWAITING_QR = "AGUARDANDO_QR"
    SYNCING = "SINCRONIZANDO"
    READY = "CONECTADO_PRONTO"

class QueueState(str, Enum):
    IDLE = "OCIOSO"
    RUNNING = "EXECUTANDO"
    PAUSED = "PAUSADO"
    ABORTED = "ABORTADO"
    COMPLETED = "CONCLUIDO"

# Regexes pré-compilados de higienização e validação
RE_NON_DIGITS = re.compile(r"\D")
RE_REPEATED_DIGITS = re.compile(r"^(\d)\1+$")
RE_SCIENTIFIC_NOTATION = re.compile(r"^[+-]?\d+(?:\.\d+)?[eE][+-]?\d+$")
RE_CARRIER_CSP = re.compile(r"^0\d{2}")  # ex: 015, 021, 014, 031, 041

# Regexes para detecção heurística de colunas em planilhas
RE_PHONE_HEADER = re.compile(
    r"(telefone|celular|tel|phone|whatsapp|contato|numero|cel|fone|mobile|num|whatsapp_number)",
    re.IGNORECASE
)
RE_NAME_HEADER = re.compile(
    r"(nome|name|contato|cliente|destinatario|lead|pessoa|razao_social|first_name)",
    re.IGNORECASE
)
