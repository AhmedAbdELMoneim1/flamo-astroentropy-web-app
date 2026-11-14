"""The conversation context kept by the agent code, not by Gemini's memory (Round 13 §13.5, Round 14 §14.1 step 1).

"here / this experiment / there" resolve to `psi` or `scenario`; "yes / the data behind it / show me" run `offer`; the reply to a clarifying question is matched against `pending`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Session:
    psi: str | None = None
    material: str | None = None
    family: str | None = None
    scenario: str | None = None
    last_tool: str | None = None
    last_args: dict = field(default_factory=dict)
    last_question: str = ""
    offer: dict | None = None        # {"label": "the Saffire-II test data", "branches": [{"tool": "find_tests", "args": {...}}]}: what "yes" shows
    pending: dict | None = None      # {"question": original, "entities": {...}, "options": [{"label", "entities"}]}: a clarifying question was asked
    options: list = field(default_factory=list)   # the last offered options (for "compare between them")
    rows: dict | None = None         # Round 15: the list on screen, {"kind": "investigations" | "tests" | "papers", "items": [{"psi"|"test"|"paper_id", "label"}]}: "they / the first one / compare them" resolve against it
    last_term: str | None = None     # the concept last explained ("it", "and in space?")
    last_conditions: dict | None = None   # the oxygen / pressure last asked about ("what does it mean?")
    clarified: bool = False          # one clarifying question per turn: after it, the best option is taken

    def remember(self, entities: dict, tool: str | None, args: dict | None, question: str) -> None:
        self.material = self.family = None            # a material is in context only for the answer right after it was asked about
        for k in ("psi", "material", "family", "scenario"):
            v = entities.get(k)
            if k == "psi":
                v = v[0] if isinstance(v, list) and len(v) == 1 else (v if isinstance(v, str) else None)
            if v:
                setattr(self, k, v)
        self.last_tool, self.last_args, self.last_question = tool, dict(args or {}), question
        self.clarified = False
        if entities.get("o2") is not None:
            self.last_conditions = {"o2": entities["o2"], "pressure_psi": entities.get("pressure_psi")}

    def snapshot(self) -> dict:
        return {"psi": self.psi, "material": self.material, "family": self.family, "scenario": self.scenario, "last_tool": self.last_tool, "offer": (self.offer or {}).get("label"),
                "pending": [o["label"] for o in (self.pending or {}).get("options", [])],
                "rows": {"kind": self.rows["kind"], "n": len(self.rows["items"])} if self.rows else None}
