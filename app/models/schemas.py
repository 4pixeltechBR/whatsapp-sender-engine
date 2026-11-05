"""
Data models, schemas, and dataclasses for WhatsApp Sender Engine.
Alinhado rigorosamente com os Contratos de Interface de PROJECT.md.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.constants import ContactStatus, SessionStatus, QueueState

# ==============================================================================
# Contratos Oficiais Dataclass (PROJECT.md)
# ==============================================================================

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "raw_phone": self.raw_phone,
            "canonical_phone": self.canonical_phone,
            "name": self.name,
            "variables": self.variables,
            "status": self.status.value if isinstance(self.status, ContactStatus) else str(self.status),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "error_detail": self.error_detail,
        }

@dataclass
class IngestionResult:
    total_rows: int
    valid_contacts: List[ContactRecord]
    duplicate_count: int
    invalid_count: int
    warning_messages: List[str]

    @property
    def valid_count(self) -> int:
        return len(self.valid_contacts)

    @property
    def efficiency_percentage(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return round((len(self.valid_contacts) / self.total_rows) * 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "valid_count": self.valid_count,
            "duplicate_count": self.duplicate_count,
            "invalid_count": self.invalid_count,
            "efficiency_percentage": self.efficiency_percentage,
            "warning_messages": self.warning_messages,
            "valid_contacts": [c.to_dict() for c in self.valid_contacts],
        }

@dataclass
class SendMessageResult:
    canonical_phone: str
    success: bool
    status: ContactStatus
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_phone": self.canonical_phone,
            "success": self.success,
            "status": self.status.value if isinstance(self.status, ContactStatus) else str(self.status),
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "timestamp": self.timestamp.isoformat(),
        }

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value if isinstance(self.state, QueueState) else str(self.state),
            "total_contacts": self.total_contacts,
            "sent_count": self.sent_count,
            "failed_count": self.failed_count,
            "pending_count": self.pending_count,
            "eta_seconds": self.eta_seconds,
            "current_contact": self.current_contact,
            "messages_per_minute": self.messages_per_minute,
        }

# ==============================================================================
# Modelos Pydantic para API e Validação
# ==============================================================================

class SanitizedNumber(BaseModel):
    raw: str
    canonical: Optional[str] = None
    valid: bool = False
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    ddd: Optional[str] = None
    region: Optional[str] = None
    phone_type: Optional[str] = None  # "MOBILE" ou "LANDLINE"

class ManualPasteRequest(BaseModel):
    text: str = Field(..., description="Texto contendo contatos (um por linha ou tabulado)")
    default_name_prefix: str = Field("Contato", description="Prefixo para nomes não informados")

class CampaignConfig(BaseModel):
    message_template: str = Field(..., description="Template com variáveis como {nome}")
    jitter_min_seconds: float = Field(10.0, ge=1.0, le=60.0)
    jitter_max_seconds: float = Field(25.0, ge=2.0, le=120.0)
    batch_size: int = Field(20, ge=5, le=100)
    batch_pause_seconds: float = Field(120.0, ge=10.0, le=600.0)
    attachment_path: Optional[str] = None
    spintax_enabled: bool = True

__all__ = [
    "ContactStatus",
    "SessionStatus",
    "QueueState",
    "ContactRecord",
    "IngestionResult",
    "SendMessageResult",
    "TelemetrySnapshot",
    "SanitizedNumber",
    "ManualPasteRequest",
    "CampaignConfig",
]
