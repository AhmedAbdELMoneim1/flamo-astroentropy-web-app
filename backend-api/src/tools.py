"""
Function tools for the flamo agent, kept separate from the agent wiring.

Pattern for every tool that changes the screen:
    1. update server-side DashboardState
    2. send a ui.command through the bridge  (the frontend reacts)
    3. return a small dict the model uses to talk about it

Content comes only from flameo_tools (src/content.py + src/adapter.py): nine intent tools, one per question kind,
and show_dashboard (the category overview). `flamoTools` is a mixin: the host Agent must provide `self.bridge` and `self.state`.
"""

from __future__ import annotations

import logging

from livekit.agents import RunContext, function_tool

from src import adapter, alerts, emergency, qlog
from src.bridge import Cmd, UiBridge
from src.categories import PILLARS, SCENARIOS, VIEWS, find_view
from src.content import Runner, chips_for, push_view, scene_arrival
from src.state import DashboardState

logger = logging.getLogger("tools")

EMERGENCY_STEPS = [
    "Alert the crew and ground control",
    "Isolate power to the affected equipment",
    "Stop ventilation to the affected area",
    "Put on protective breathing equipment",
    "Use the extinguisher following your mission fire procedure",
]

CUSTOM_LINE = (
    "These are custom conditions. Data is rated only for the ISS, Moon base and suit; the chart shows where your point "
    "sits among the tested conditions."
)


class flamoTools:
    bridge: UiBridge
    state: DashboardState

    async def _intent(self, name: str, **args) -> dict:
        return await Runner(self.bridge, self.state).intent(name, **args)

    # ── the one data tool (Round 14 §14.1) ──────────────────────────
    @function_tool
    async def answer(self, context: RunContext, question: str) -> dict:
        """Answer ANY question about the PSI data, the papers, the tests, the materials, the ranges of oxygen and pressure, or fire and combustion in space. Call it with the astronaut's own words, BEFORE you speak.

        The server decides which data tools and which paper search to use, and returns the lines to say. Speak those lines (at most three), keep every number and name, then say the details are on the screen and end with next_offer if present.
        If answered_by is "clarify", ask exactly that one short question and nothing else; pass the astronaut's reply to this tool again.
        Never say "not covered" yourself: say it only when answered_by is "not_found", using the exact sentence in reply_guidance.

        Args:
            question: What the astronaut said or typed, as they said it. For a reply to your clarifying question, pass their reply.
        """
        from src.router.answer import Router
        gate = getattr(self.state, "gate", None)
        if gate is not None:                                           # Round 15: the server may already be running this very question
            model = await gate.take(question)
            if model is not None:
                return model
        return await Router(self.bridge, self.state).answer(question)

    @function_tool
    async def go_back(self, context: RunContext) -> dict:
        """Go back to the previous view on the screen ("go back", "back to the last graph"). Call it BEFORE you speak."""
        import time

        from src.router.answer import Router
        from src.router.understand import Understanding
        u = Understanding(text="go back", intents=["navigate"], go_back=True)
        return await Router(self.bridge, self.state)._navigate("go back", u, {}, time.monotonic())

    # ── dashboard ────────────────────────────────────────────────────────────
    # Keep the ids in this docstring in sync with categories.py (the model reads it).
    @function_tool
    async def show_dashboard(
        self,
        context: RunContext,
        pillar: str,
        view: str | None = None,
        scenario: str | None = None,
    ) -> dict:
        """Open a category overview on the astronaut's screen ("open Detection", "show the suppression view for the ISS"). One call per request, always BEFORE you speak.

        Pillars and their views:
          prevention    -> materials (flame spread of the tested materials; the default), ignition (what the tests recorded about ignition)
          flammability  -> flame_spread (how fast flames spread in the tests)
          detection     -> smoke (smoke particle size and soot records; always shown for all conditions)
          suppression   -> suppression (the carbon dioxide and helium added in the experiments)
        Scenarios: iss, moon_base, spacesuit.

        Args:
            pillar: One of prevention, flammability, detection, suppression.
            view: Optional view id. Omit to open the pillar's overview.
            scenario: Optional scenario id. Pass it only when the astronaut names or implies one. Omit it to keep the current scenario.
        """
        v = find_view(pillar, view)
        if v is None:
            return {
                "status": "error",
                "reason": "unknown or mismatched pillar/view",
                "valid_pillars": list(PILLARS),
                "valid_views": {p: [x.id for x in VIEWS.values() if x.pillar == p] for p in PILLARS},
            }
        if scenario is not None and scenario not in SCENARIOS:
            return {"status": "error", "reason": "unknown scenario", "valid_scenarios": list(SCENARIOS)}

        if scenario is not None:
            updates = self.state.update_conditions(scenario=scenario)
            await self.bridge.send(Cmd.CONDITIONS_SET, {"scenario": self.state.scenario, "inputs": updates})

        first_visit = self.state.first_visit(v.pillar)
        self.state.open_view(v)
        content = await push_view(self.bridge, self.state)
        if content["status"] != "ok":
            return {"status": "error", "reason": content["reason"]}
        chips = chips_for(v.pillar)
        out = {
            "status": "shown",
            "phase": "category_entry",
            "category": PILLARS[v.pillar].label,
            "first_visit": first_visit,
            "scenario": self.state.scenario or "custom",
            "coverage": None if SCENARIOS.get(self.state.scenario or "") and SCENARIOS[self.state.scenario].coverage_note else content["coverage"],
            "overview_speak": content["speak"][:3],
            "first_gap": (content["payload"]["dashboard"]["gaps"] or [None])[0],
            "reply_guidance": (
                "The screen now shows the overview. If first_visit is true, start with the intro in your own words (no numbers added), "
                "then the first overview_speak line, then 'For example, ask me: <ask_me>'. If first_visit is false, say the first "
                "overview_speak line, then 'Ask me anything about <category>.' Add nothing that is not in overview_speak."
            ),
        }
        if first_visit:
            out["intro"] = PILLARS[v.pillar].intro
        if chips:
            out["ask_me"] = chips[0]
        return out

    # ── data questions: one tool per intent, generated from flameo_tools.tool_specs() ─
    # server-only since Round 14 (the router runs the scoped RAG)
    async def ask_sources(
        self,
        context: RunContext,
        question: str,
        o2_pct: float | None = None,
        pressure_kpa: float | None = None,
        material: str | None = None,
        fuel: str | None = None,
        psi: str | None = None,
        pillar: str | None = None,
        scenario: str | None = None,
    ) -> dict:
        """Call BEFORE you speak. The answer, with its sources, appears on the screen by itself.

        The tool for any fire, combustion or space-fire question that NO other tool answers ("Why do flames go out in microgravity?", "What did the SPICE experiment find about smoke points?", "How did soot change between normal gravity and microgravity?").
        It searches the papers and NASA documents of ONLY the investigations your parameters select, and returns sentences the checker approved, each with a source (document, page, link). It does not answer from memory.
        Fill ONLY the parameters the astronaut stated or the screen shows: o2_pct (oxygen percent), pressure_kpa, material, fuel, psi (an experiment name or id), pillar, scenario. Leave the others empty: with none, it searches everything.
        It may return status "clarify": then ask that one question and nothing else. status "not_found" means it is not covered: say it is an open question. Never for off-topic or unsafe questions.

        Args:
            question: the astronaut's question in English, as asked.
            o2_pct: oxygen concentration in percent, if stated.
            pressure_kpa: pressure in kPa, if stated.
            material: a material (PMMA, SIBAL, Kapton, ...), if stated.
            fuel: a fuel (methane, ethylene, heptane, ...), if stated.
            psi: an investigation id or name (PSI-20, BRE, SAME, FLEX, ...), if stated.
            pillar: prevention, flammability, detection or suppression, if clearly implied.
            scenario: iss, moon_base, spacesuit, exploration_10_2, exploration_8_2, high_o2, if stated or on screen.
        """
        return await Runner(self.bridge, self.state).ask_sources(question, o2_pct=o2_pct, pressure_kpa=pressure_kpa, material=material, fuel=fuel, psi=psi, pillar=pillar, scenario=scenario)

    # <generated:intent_tools>
    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def get_investigation(self, context: RunContext, psi: str) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        What is this investigation / what did it test? Use for questions such as "What is BRE?", "What did PSI-69 test?", "Tell me about FLEX".
        Argument: psi = a PSI id ("PSI-20"), a number, or a hardware / experiment name ("BRE", "BASS-II").
        Returns tests, condition ranges (ambient oxygen kept apart from burner-stream oxygen), fuels, materials, outcomes measured and how much of each field is filled by trust level.
        Never invents conditions that are not in the data; never compares PSIs (use compare).

        Args:
            psi: a PSI id, number or experiment name (for example PSI-20, 20, BRE, SAME).
        """
        return await self._intent("get_investigation", psi=psi)

    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def compare(self, context: RunContext, psi_a: str, psi_b: str) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        Compare two investigations side by side ("Compare BASS and BASS-II", "How do FLEX and CFI differ?").
        Arguments: psi_a, psi_b (ids or names). Returns a side-by-side table (hardware family, fuels / materials, oxygen / pressure / flow ranges, outcomes measured, tests, what each builds on) and says what overlaps and what is missing.
        It never ranks one PSI above the other; "not directly comparable" is said only about numeric ranking claims.

        Args:
            psi_a: first investigation (id or name).
            psi_b: second investigation (id or name).
        """
        return await self._intent("compare", psi_a=psi_a, psi_b=psi_b)

    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def rank_materials(self, context: RunContext, metric: str | None = None, scenario: str | None = None) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        Which material spreads flame faster or slower? ("Which material spreads fastest at 30 % O2?", "Rank materials by flame spread"). Arguments: metric = spread rate (the only measured metric that can be ranked), scenario = optional scenario id.
        Ranks only inside one comparable group of ONE PSI (same hardware and setup, flow direction known, oxygen / pressure / flow within tolerance; flagged cross_material_same_psi when the materials differ).
        Across PSIs it never ranks and never averages over varied conditions: one row per investigation, material class and flow direction, giving each value (3 tests or fewer) or the range and count.
        The wording is "spread faster / slower in these tests", never "safer"; spread rate alone does not rate fire safety. Limiting oxygen / flammability limits are shown only as the authors' reported findings (flight evidence first), never ranked against measured values.

        Args:
            metric: 'spread rate' (the only rankable metric) or the metric the astronaut named.
            scenario: optional: iss, moon_base, exploration_10_2, exploration_8_2, spacesuit, high_o2, Mars or partial gravity.
        """
        return await self._intent("rank_materials", metric=metric, scenario=scenario)

    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def scenario_coverage(self, context: RunContext, scenario: str) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        Which tests are near a scenario atmosphere? ("Tests near the Moon base atmosphere?", "What do we have for the ISS / spacesuit / exploration 8.2 psia?").
        Argument: scenario = iss, moon_base, exploration_10_2, exploration_8_2, spacesuit, high_o2 (aliases accepted: Moon, ISS, spacesuit).
        Counts ambient oxygen only. Burner-stream oxygen of inverse flames is separate; He / CO2 diluent tests are listed apart, never counted. Every answer says how many near tests state nitrogen or air (per test or once for the whole PSI) and how many do not state the diluent gas.
        moon_base is a requirement (at least 30 percent oxygen, at most 70.3 kilopascals): near = inside it, nearby = within the band outside. Mars and partial gravity have no PSI data; it says so.

        Args:
            scenario: optional: iss, moon_base, exploration_10_2, exploration_8_2, spacesuit, high_o2, Mars or partial gravity.
        """
        return await self._intent("scenario_coverage", scenario=scenario)

    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def get_findings(self, context: RunContext, x: str, y: str, fuel: str | None = None) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        Also the tool for 'does fire spread faster in space?': x='oxygen', y='spread rate'.

        How does Y change with X? ("How does spread rate change with oxygen?", "What affects extinction diameter?"). Arguments: x, y = field names or plain words
        (oxygen, pressure, flow, spread rate, particle size ...), fuel = optional fuel / material word.
        Returns the paper findings (each worded by its evidence basis, "on the ISS" only for flight evidence) and the supporting test points from the data, with trust per point.
        Never draws a trend line of its own.

        Args:
            x: the quantity that changes (oxygen, pressure, flow ...).
            y: the quantity that responds (spread rate, particle size, extinction diameter ...).
            fuel: optional fuel or material word.
        """
        return await self._intent("get_findings", x=x, y=y, fuel=fuel)

    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def rank_agents(self, context: RunContext, fuel_class: str | None = None) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        Which suppressant / diluent works best? ("Which suppressant works best?", "How does CO2 compare with helium?"). Argument: fuel_class = optional (liquid, gas, solid:PMMA ...).
        In these PSIs the suppression variable is the diluent in the atmosphere (carbon dioxide, helium; nitrogen is the balance gas). Per agent and PSI it returns tests with a value above zero, concentration range, oxygen / pressure range, the source of each value
        and the authors' reported effects (cards about a diluent, flight first). Extinction-diameter counts are given only for droplet PSIs and only above zero (zeros are reported with how those tests ended).
        It never computes an "amount at extinction" threshold and never ranks agents against each other. The mass or volume of an extinguisher is not in the data; it says so.

        Args:
            fuel_class: optional: liquid, gas, solid:PMMA ...
        """
        return await self._intent("rank_agents", fuel_class=fuel_class)

    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def gaps(self, context: RunContext, scenario: str | None = None) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        Also the tool for fire on the Moon or Mars, partial gravity, or a candle on the Moon: pass scenario 'partial gravity' or 'Mars'.

        What do we NOT know? ("What don't we know for Mars?", "What is missing for the spacesuit?", "Where are the gaps?"). Argument: scenario = optional scenario id, Mars or partial gravity.
        Mars: "PSI has no Mars-specific atmosphere and no partial-gravity combustion data" plus the nearest tested atmospheres and their coverage. A scenario with more oxygen than any test: the highest ambient oxygen tested (burner-stream oxygen labelled apart).
        Without a scenario: the incomplete PSI x field cells. Never gives a Mars value.

        Args:
            scenario: optional: iss, moon_base, exploration_10_2, exploration_8_2, spacesuit, high_o2, Mars or partial gravity.
        """
        return await self._intent("gaps", scenario=scenario)

    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def search_text(self, context: RunContext, query: str, psi: str | None = None) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        Only for 'find the passage about X' requests (a quick text lookup in the documents and finding cards). For any other fire, combustion or space-fire question use ask_sources, which searches only the right investigations and cites its sources. Pass 3 to 6 English key words. Never answer from memory. Never use it for off-topic or unsafe questions.

        Free-text lookup in the documents, papers and finding cards ("Why are space smoke particles bigger?", "What does the report say about soot?"). Arguments: query (words), psi = optional.
        Cards whose statement contains the query terms come first, each spoken as its full statement with its evidence wording; document and paper passages are spoken as a whole sentence with the document title and page. It does not answer from memory and gives no numbers that are not in the text.

        Args:
            query: 3 to 6 English key words.
            psi: a PSI id, number or experiment name (for example PSI-20, 20, BRE, SAME).
        """
        return await self._intent("search_text", query=query, psi=psi)

    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def rank_investigations(self, context: RunContext, pillar: str | None = None, scenario: str | None = None) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        Which investigations matter most? ("Which experiments matter most for the Moon base?", "Which investigations are most relevant to suppression?", "Rank the investigations for the ISS").
        Arguments: pillar = optional prevention | flammability | detection | suppression (the investigations whose registry description names it; none = all), scenario = optional scenario id (iss, moon_base, spacesuit ...).
        Ranks RELEVANCE, in this order: the registry tier of the investigation (A, B, C, M, from the official PSI description), flight before ground, tests near the scenario (or tests in the data), then accepted paper findings (flight findings first). The bar value is a real test count; there is no score.
        It never rates how safe anything is, never ranks materials or gases, and for the spacesuit it counts only oxygen-rich burner-stream tests (not the atmosphere).

        Args:
            pillar: optional: prevention, flammability, detection or suppression.
            scenario: optional: iss, moon_base, exploration_10_2, exploration_8_2, spacesuit, high_o2, Mars or partial gravity.
        """
        return await self._intent("rank_investigations", pillar=pillar, scenario=scenario)

    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)
    async def oxygen_effect(self, context: RunContext, scenario: str | None = None, material: str | None = None) -> dict:
        """Call BEFORE you speak. The answer appears on the screen by itself.

        What oxygen level is dangerous, and how does more oxygen change a fire? ("What oxygen level makes the spacecraft dangerous?", "Is more oxygen dangerous?", "How much oxygen makes a fire worse?").
        Arguments: scenario = optional scenario id (iss, moon_base, spacesuit, exploration_10_2, exploration_8_2, high_o2), material = optional material word (PMMA, SIBAL ...).
        Shows the oxygen of the atmosphere, the flight findings that relate oxygen to flame behaviour (flight first, each worded by its evidence basis), the BRE thesis statement on steady flames, the cool-flame limit and the oxygen-pressure chart.
        It never gives a single safe or dangerous oxygen level: the PSI data does not set one, and every answer says so.

        Args:
            scenario: optional: iss, moon_base, exploration_10_2, exploration_8_2, spacesuit, high_o2, Mars or partial gravity.
            material: optional: a material word (PMMA, SIBAL, Kapton ...) to keep only findings that name it.
        """
        return await self._intent("oxygen_effect", scenario=scenario, material=material)
    # </generated:intent_tools>

    # ── dashboard inputs ─────────────────────────────────────────────────────
    @function_tool
    async def set_conditions(
        self,
        context: RunContext,
        scenario: str | None = None,
        oxygen_pct: float | None = None,
        pressure_psi: float | None = None,
    ) -> dict:
        """Update the dashboard conditions. Only pass the values the astronaut mentioned or implied.

        Args:
            scenario: Optional preset: "iss", "moon_base" or "spacesuit". Fills oxygen and pressure. Use it when
                the astronaut names a scenario ("at spacesuit pressure", "Moon Base conditions"). For custom
                numbers leave it out and pass the values instead.
            oxygen_pct: Oxygen concentration in percent (0 to 100).
            pressure_psi: Cabin pressure in psi (0 to 75).
        """
        if scenario is not None and scenario not in SCENARIOS:
            return {"status": "error", "reason": "unknown scenario", "valid_scenarios": list(SCENARIOS)}

        previous_scenario = self.state.scenario
        updates = self.state.update_conditions(scenario=scenario, inputs={"oxygen_pct": oxygen_pct, "pressure_psi": pressure_psi})
        if not updates:
            return {"status": "nothing_changed", "reason": "no valid values given", "conditions": self.state.inputs}

        await self.bridge.send(Cmd.CONDITIONS_SET, {"scenario": self.state.scenario, "inputs": updates})

        out: dict = {"status": "updated", "scenario": self.state.scenario or "custom", "changed": updates}
        if self.state.view and self.state.scenario != previous_scenario:
            await push_view(self.bridge, self.state)
        if self.state.scenario:
            scene = await scene_arrival(self.bridge, self.state, self.state.scenario)
            out.update(phase="scene", coverage=None if SCENARIOS[self.state.scenario].coverage_note else SCENARIOS[self.state.scenario].coverage, scene_speak=scene["speak"], end_with=scene["end_with"])
            out["reply_guidance"] = (
                "Say the scene_speak lines in your own words, keeping every number, then end_with. "
                "Never call the spacesuit atmosphere covered; say what scene_speak says."
            )
        else:
            out.update(phase="custom_conditions", coverage=None, say=CUSTOM_LINE)
            out["reply_guidance"] = "Say the `say` sentence in your own words. Give no number for custom conditions."
        return out

    @function_tool
    async def get_dashboard_state(self, context: RunContext) -> dict:
        """Return what is on the astronaut's screen: pillar, view, previous_view (for "go back"), scenario, coverage, conditions, emergency status."""
        return self.state.snapshot()

    # ── trip assistance ──────────────────────────────────────────────────────
    @function_tool
    async def get_mission_context(self, context: RunContext) -> dict:
        """Return the mission details (name, destination, crew size, launch date) loaded on the astronaut's screen."""
        if not self.state.mission:
            return {"status": "not_loaded", "note": "Mission details have not been loaded on the screen yet."}
        return self.state.mission

    @function_tool
    async def add_mission_note(self, context: RunContext, text: str) -> dict:
        """Save a short note to the astronaut's on-screen mission log when they ask you to remember or log something.

        Args:
            text: The note, one short sentence.
        """
        text = text.strip()[:200]
        self.state.notes.append(text)
        await self.bridge.send(Cmd.NOTE_ADD, {"text": text})
        return {"status": "saved", "total_notes": len(self.state.notes)}

    # ── emergency mode ───────────────────────────────────────────────────────
    @function_tool
    async def declare_fire_emergency(
        self,
        context: RunContext,
        situation: str | None = None,
    ) -> dict:
        """Call IMMEDIATELY, and ONLY, when the astronaut reports a fire, smoke, a burning smell or overheating equipment that is happening NOW ("I smell burning plastic", "there is smoke from the rack", "fire in the galley").
        A QUESTION about fire ("what should I do if...", "what happens if...", "how do I...", "can I use water on a fire") is NOT an emergency: do not call this; answer it (ask_sources) and say to follow the mission fire procedure.
        Turns the screen into emergency mode with first-response steps for the place (cabin or suit) in the language of the chat.

        Args:
            situation: Very short description, e.g. "smoke from the avionics rack".
        """
        kind = emergency.classify(self.state.last_transcript)
        if kind in ("hypothetical", "ambiguous"):             # decided in code, not by the model: a question is not a fire
            qlog.log(self.state.last_transcript, "declare_fire_emergency", {"situation": situation, "refused": kind}, False, source=self.state.last_source)
            guidance = ("This is a question, not a fire. Do not declare an emergency. Say to follow the mission fire procedure, then answer the question with ask_sources."
                        if kind == "hypothetical" else
                        "It is not clear whether there is a fire. Ask once, briefly: \"Is there a fire right now?\" and call declare_fire_emergency again only if the answer is yes.")
            return {"status": "not_declared", "reason": kind, "reply_guidance": guidance}
        b = await alerts.declare(self.bridge, self.state, situation)
        return {
            "status": "emergency_active",
            "first_actions": b["steps"],
            "reply_guidance": (
                "Be terse and steady. Give the first action only, in one short sentence, then the next when asked. "
                "Remind them to follow the mission fire procedure. Speak in the language of the chat."
            ),
        }

    @function_tool
    async def clear_fire_emergency(self, context: RunContext) -> dict:
        """Call when the astronaut says the emergency is over: "there is no fire", "false alarm", "it's out", "I was only asking". The screen returns to normal."""
        await alerts.clear(self.bridge, self.state, "the model cleared it")
        return {"status": "cleared"}
