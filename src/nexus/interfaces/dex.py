"""DEX provider interface (implemented in Stage 3)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class DexQuote:
    """Executable swap quote from a DEX / aggregator."""

    provider: str
    chain: str
    token_in: str
    token_out: str
    amount_in: Decimal
    amount_out: Decimal
    gas_cost_usd: Decimal
    timestamp_ms: int


class BaseDEXProvider(ABC):
    """Base class for DEX pool / aggregator quote providers."""

    name: ClassVar[str]
    chain: ClassVar[str]

    @abstractmethod
    async def quote(self, token_in: str, token_out: str, amount_in: Decimal) -> DexQuote:
        """Quote swapping ``amount_in`` of ``token_in`` into ``token_out`` (incl. gas)."""

    @abstractmethod
    async def close(self) -> None:
        """Release network resources."""
