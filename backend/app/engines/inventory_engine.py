from __future__ import annotations
from dataclasses import dataclass
from app.db.event_store import EventStore, EventType


@dataclass
class InventoryItem:
    name: str
    category: str
    source: str
    status: str  # "carried", "used", "lost"


class InventoryEngine:
    def __init__(self, event_store: EventStore):
        self._store = event_store

    def add_item(self, campaign_id: str, name: str, category: str, source: str):
        # Check for duplicates — if already carried, skip
        current = self.get_inventory(campaign_id)
        for item in current:
            if item.name.lower() == name.lower() and item.status == "carried":
                return
        self._store.append(
            campaign_id=campaign_id,
            event_type=EventType.INVENTORY,
            payload={"action": "add", "name": name, "category": category, "source": source},
            narrative_time_delta=0,
            location="current",
            entities=["player"],
        )

    def use_item(self, campaign_id: str, name: str):
        current = self.get_carried_items(campaign_id)
        if not any(i.name.lower() == name.lower() for i in current):
            return
        self._store.append(
            campaign_id=campaign_id,
            event_type=EventType.INVENTORY,
            payload={"action": "use", "name": name},
            narrative_time_delta=0,
            location="current",
            entities=["player"],
        )

    def lose_item(self, campaign_id: str, name: str):
        current = self.get_carried_items(campaign_id)
        if not any(i.name.lower() == name.lower() for i in current):
            return
        self._store.append(
            campaign_id=campaign_id,
            event_type=EventType.INVENTORY,
            payload={"action": "lose", "name": name},
            narrative_time_delta=0,
            location="current",
            entities=["player"],
        )

    def get_inventory(self, campaign_id: str) -> list[InventoryItem]:
        events = self._store.get_by_type(campaign_id, EventType.INVENTORY)
        items: dict[str, InventoryItem] = {}
        for e in events:
            p = e.payload
            action = p.get("action", "")
            name = p.get("name", "")
            key = name.lower()
            if action == "add":
                items[key] = InventoryItem(
                    name=name,
                    category=p.get("category", "misc"),
                    source=p.get("source", "unknown"),
                    status="carried",
                )
            elif action == "use" and key in items:
                items[key].status = "used"
            elif action == "lose" and key in items:
                items[key].status = "lost"
        return list(items.values())

    def get_carried_items(self, campaign_id: str) -> list[InventoryItem]:
        return [i for i in self.get_inventory(campaign_id) if i.status == "carried"]

    def format_for_prompt(self, campaign_id: str) -> str:
        items = self.get_inventory(campaign_id)
        if not items:
            return "INVENTORY: Empty."
        lines = ["INVENTORY:"]
        for item in items:
            lines.append(f"- {item.name} [{item.category}] (source: {item.source}) — status: {item.status}")
        return "\n".join(lines)
