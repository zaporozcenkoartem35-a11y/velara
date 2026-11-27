from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    birth_date: Optional[str]
    utm_source: str
    referrer_id: Optional[int]
    free_tarot_credits: int
    paid_tarot_credits: int
    first_seen: str
    last_seen: str

    @property
    def total_tarot_credits(self) -> int:
        return self.free_tarot_credits + self.paid_tarot_credits


@dataclass
class Payment:
    id: int
    user_id: int
    product_type: str
    stars_amount: int
    telegram_payment_charge_id: str
    created_at: str


@dataclass
class Event:
    id: int
    user_id: int
    event_name: str
    payload: Optional[str]
    created_at: str
