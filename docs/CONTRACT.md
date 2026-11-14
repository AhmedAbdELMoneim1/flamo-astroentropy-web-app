# Flamo: front/back contract

For the React developer. You should not need to read Python. Sources of truth:
`frontend/src/protocol.js` (names, encoding) and `frontend/src/DashboardContext.jsx` (state and actions).
`src/bridge.py` is the same contract on the Python side.

## How it works

Voice is the main interface. The astronaut talks, the agent calls a tool, and the screen mirrors it.
**The frontend has no content of its own**: every number, table, chart, ranking, headline and coverage level arrives from the
agent (`view.open`, `answer.show`), and the agent takes it from `flameo_tools` / `serving.db`. The only fixed text on screen is the
catalog's `texts`, the category names, the intros and the "Ask me" chips (decisions Stage 7).

Every packet, both directions, is a LiveKit reliable data packet carrying this JSON (UTF-8):

```json
{ "v": 1, "type": "view.open", "payload": { }, "ts": 1730000000000 }
```

| Topic | Direction |
|---|---|
| `ui.command` | agent -> frontend ("make the screen do X") |
| `ui.event` | frontend -> agent ("the user did X") |

Ids (pillars, views, scenarios, input ranges) come from `GET /api/categories`. Never hardcode them.

## Commands (agent -> frontend, topic `ui.command`)

| Type | Payload example | Fires when |
|---|---|---|
| `view.open` | `{"pillar":"suppression","view":"suppression","focus":null,"scenario":"iss","coverage":"High","coverage_note":null,"headline":"...","key_points":["..."],"dashboard":{...},"ranking":{...},"suggestions":["..."]}` | The agent opens a category overview; the user taps a category (reply to `view.selected`); the scenario changes while a view is open. Replace the overview of that category (and any answer shown in it). |
| `conditions.set` | `{"scenario":"spacesuit","inputs":{"oxygen_pct":100,"pressure_psi":4.3}}` | The agent sets conditions by voice ("at spacesuit pressure"), or opens a view with a scenario. `inputs` holds only the changed values: merge them. `scenario: null` means custom conditions. Sent **before** the `view.open` that follows it. |
| `alert.set` | `{"level":"emergency","title":"Smoke from rack","steps":["Alert the crew and ground control","..."]}` and `{"level":"clear","title":"","steps":[]}` | The astronaut reports a fire (emergency) or says it is over (clear). Show or hide an emergency banner. |
| `note.add` | `{"text":"Checked the extinguisher"}` | The astronaut asks flamo to log something. Append to the mission log. |

| `answer.show` | `{"request_id":"a1b2c3d4","metric":"rank_agents","tool":"rank_agents","question":"...","pillar":"suppression","speak":["..."],"kpis":[],"charts":[],"table":{...},"gaps":[],"cards":[],"source":{"mock":false,...},"ranking":{...}}` | The agent answers a question. Show the **answer state**: it replaces the overview panels of `pillar` (the frontend switches to that category when `pillar` differs from the one on screen; `null` = stay). Keep the ranking panel. A chip goes back to the overview. |

Notes on `view.open`:
- `coverage` is `"High"`, `"Medium"` or `"Low"` for a named scenario, **`"None"`** for a named scenario with no test (the spacesuit atmosphere) and `null` for custom conditions. Badge text: "Data coverage: High"; for `"None"`: "Spacesuit atmosphere: none tested" (never "Data coverage: None") plus a second chip from `coverage_note {label, level}` ("Oxygen-rich flames (burner stream, not the atmosphere): Medium").
- Custom conditions (`scenario: null`) show **all** PSI tests: `headline` starts with "All PSI tests (not filtered to your conditions)" and the last gap says coverage is rated only for the ISS, Moon base and spacesuit atmospheres. Draw the user's point on the O2-vs-pressure chart from the slider values.
- `dashboard` = `{view, scenario, coverage, headline, key_points, kpis (<=4, with basis and trust), charts (<=2), table {columns (<=6), rows (<=12), footer "12 of N rows"}, gaps (<=3), cards (<=3), note?, source}`; always < 8000 bytes.
- `ranking` = the "Most relevant investigations" panel: `{pillar, scenario, rows[{rank|null, group, psi, name, tier, pillars, tests, tests_label, findings}], tier_label, divider, note, footer?}`. Bar length = `tests` (a real count, label `tests_label`). Rows with `rank: null` sit below the `divider` ("No tests at these conditions"). It comes **only** from `rank_investigations`; never sort a bar chart into a ranking.
- `suggestions` = the "Ask me" chips (chips marked `pending_review` are not sent).
- A chart may carry `ref` (for example `/api/charts/o2_vs_pressure`) instead of `series`: fetch it once and draw all series (8+ colours, hollow markers for `marker: "hollow"`, labelled crosses for `marker: "cross"`).
- `focus` is an optional sub-topic (the catalog lists `focus_options` per view).

## Events (frontend -> agent, topic `ui.event`)

| Type | Payload example | Fires when |
|---|---|---|
| `view.selected` | `{"pillar":"detection","view":"smoke","focus":null,"scenario":"iss","source":"user_tap"}` | The user taps a pillar or a view (`source: "auto"` = the screen opened its default category: the agent stays silent). `view` may be omitted to open the pillar's first view. The agent speaks one short sentence and replies with `view.open`. |
| `conditions.changed` | `{"scenario":"spacesuit"}` or `{"inputs":{"oxygen_pct":35}}` | The user taps a scenario (send `scenario` only; the agent applies the preset) or edits an input (send changed `inputs` only, no `scenario`, which makes the conditions custom). Debounce slider edits (about 250 ms) and batch them. |
| `state.sync` | `{"pillar":null,"view":null,"focus":null,"scenario":"iss","inputs":{...},"mission":null}` | Silent. Sent once when the agent joins (packets are not stored, so it must catch up) and when the user returns to the entry view (`pillar` and `view` null). |
| `question.asked` | `{"text":"What is BRE?"}` | The user tapped an "Ask me" chip. The agent answers it like a spoken question. |
| `mission.loaded` | `{"mission":{"mission":"Artemis Demo","destination":"Moon","crew_size":4,"launch_date":"2027-03-14"}}` | Silent. The mission details were loaded on screen. |

Send events with `destinationIdentities: [agent.identity]`. The agent reacts to a tap by interrupting itself and
speaking once, so only the newest tap is answered.

## Scenario rule (keep this behavior)

- Tapping a scenario selects it and fills the inputs from its preset.
- Editing any input makes the conditions **custom** (`scenario: null`, coverage `null`).
- When the scenario changes, clear the old headline and key points and wait for the `view.open` that follows.
  `DashboardContext.jsx` already does all of this.

## HTTP endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/token` | Body `{identity?, name?, room?}` (all optional). Returns `{server_url, participant_token, room, identity}`. The token also dispatches the agent into the room. |
| `GET /api/categories` | The catalog (below). |
| `GET /api/charts/o2_vs_pressure` | The full tested oxygen-against-pressure scatter (all series and points, flameo's own chart). Built once at start-up; does not depend on the question. |
| `GET /api/mission` | Demo mission details `{mission, destination, crew_size, launch_date}`. |
| `GET /health` | `{"ok": true}` |

Vite proxies `/api` to `http://localhost:8000` in dev; set `VITE_API_URL` for anything else.

`GET /api/categories` (shortened; the path name is historical, it returns the whole catalog):

```json
{
  "pillars": [
    {"id":"prevention","label":"Prevention","views":["ignition","materials"]},
    {"id":"flammability","label":"Flammability & Fire Behavior","views":["flame_spread"]},
    {"id":"detection","label":"Detection","views":["smoke"]},
    {"id":"suppression","label":"Suppression","views":["suppression"]}
  ],
  "views": [{"id":"smoke","pillar":"detection","label":"Smoke","icon":"💨","tagline":"...","focus_options":["..."]}],
  "scenarios": [
    {"id":"iss","label":"ISS","summary":"About 21% oxygen at about 14.7 psi.","inputs":{"oxygen_pct":21,"pressure_psi":14.7},"coverage":"High","coverage_note":null},
    {"id":"moon_base","label":"Moon Base / pressurized rover","inputs":{"oxygen_pct":30,"pressure_psi":10.2},"coverage":"Medium","coverage_note":null},
    {"id":"spacesuit","label":"Spacesuit","inputs":{"oxygen_pct":100,"pressure_psi":4.3},"coverage":"None","coverage_note":{"label":"Oxygen-rich flames (burner stream, not the atmosphere)","level":"Medium"}}
  ],
  "default_scenario": "iss",
  "conditions": {
    "oxygen_pct":   {"label":"Oxygen","unit":"%","kind":"number","min":15,"max":100,"step":0.5,"default":21},
    "pressure_psi": {"label":"Pressure","unit":"psi","kind":"number","min":3,"max":16,"step":0.1,"default":14.7}
  },
  "texts": {"ranking_title":"Most relevant investigations","gaps_title":"Open questions: not in the data yet","gaps_footer":"...","gravity":"Microgravity (PSI has no partial-gravity data)"}
}
```

Coverage levels are read from the data at start-up (`scenario_coverage`), not written in code. Only oxygen and pressure are inputs; gravity is fixed text.

The `pillar` ids are `prevention`, `flammability`, `detection`, `suppression`; the view ids are `ignition`, `materials`,
`flame_spread`, `smoke`, `suppression` (the last one is both a pillar and a view id; they are different namespaces).

## What to build

1. **Entry view**: four large pillar buttons.
2. **Open pillar**: tabs for its views (`pillars[].views`).
3. **View**: headline, up to three key points, a coverage badge (High / Medium / Low), and the dashboard.
4. **Conditions panel**: three scenario buttons plus the input fields (render from `conditions`).
5. **Emergency banner** from `alert.set`, and a mission log from `note.add`.

## Handoff notes

- **Keep** `protocol.js` and `DashboardContext.jsx`. They are the only files that touch LiveKit packets and state.
  Components read `useDashboard()` and call one function: `selectPillar(id)`, `selectView(id)`, `goHome()`,
  `setScenario(id)`, `changeInputs({key: value})`, `loadMission()`.
- **Replace** the components and `styles.css`.
- **Real dashboards** go in the `REPLACE ME` slot in `CategoryView.jsx`. Choose what to render by
  `{pillar, view, scenario}` (scenario is `null` for custom conditions); `inputs` is also available.
- **Turn off the event log** for production: set `SHOW_EVENT_LOG = false` in `App.jsx`.
- Keep a `Visualizer`-style component if you want a voice-state indicator; it reads `useVoiceAssistant()`.
- Changing a message name or payload shape means changing `bridge.py`, `protocol.js`, `DashboardContext.jsx`
  and this file together.
