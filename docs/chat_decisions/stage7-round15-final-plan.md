## Round 15 — the final plan: from a working prototype to a finished solution (2026-11-12): PROPOSED (the team answers D15-1 to D15-4)

**Inputs:**
- the team's 12-point feedback;
- the 2026-11-12 session transcript (`chat_decisions/round15_session_transcript.txt`);
- the router code as it is (`src/router/`, Round 14);
- `logs/questions.jsonl`.

**Goal of the product (the team's words, kept as the north star):** Flamo is a voice copilot that sits **side by side** with the astronaut in a simulated environment (cabin, Moon base, suit). It does two jobs equally well:
1. **Crew:** fast, calm, correct help when something happens, plus quick answers about the conditions they are in.
2. **Learners:** students, undergraduates, aerospace researchers and engineers. It explains concepts, finds the evidence, compares tests and investigations, and is honest about what the data does not cover.

Everything below serves those two jobs and makes them visible to a judge in 5 minutes.

### 15.0 What the session shows (the root causes, not the symptoms)
| what the user did | what happened | root cause |
|---|---|---|
| "what's ignition I see on screen?" / "what does O₂ = 18 % mean?" / "what does a high spread rate mean?" / "explain how spread rate affects fabric" | not covered, a vague line, or a ranking | **No "explain" path.** The router only knows data lookups; a meaning / concept question has no tool, and the RAG composer is told to say nothing beyond the chunks. |
| "tell me about test 19115A1" / pasting a table row "19150A1 C2H₄ 39.8 14.8 – danger?" | not covered / only moved the sliders | **No test-level tool.** A test id is not recognised; the pasted row was read as conditions only. |
| "I want tests at 40 %" | not covered | **No "nearest value" search.** The O₂ value went to the sliders, not to a test search. |
| "what's the best paper that appears a lot in sources?" → "I said paper" | an investigation ranking, then not covered | **No paper catalogue tool.** The word "best" matched the ranking intent. |
| "ok what do they cover?" (after FLEX) | not covered | **The follow-up lost the subject.** "they" was not resolved to the ranked list on screen. |
| Ranking answers | read the method aloud ("ranked by registry tier, flight before ground…") | Answers explain the machinery instead of the meaning. |
| Questions asked on the home screen | the voice answered, the dashboard never appeared | **The answer card is sent to a dashboard that is not mounted** on `/home`. |
| "It means that at 18 percent oxygen, the tests showed how flames behave" | a vacuous sentence | **No interpretation layer:** values are returned, never put in context (vs the ISS 21 %, vs the findings near that value). |

**Conclusion:** the remaining failures are mostly **missing question types** (explain, test lookup, nearest value, paper catalogue, interpret a value) and **missing context** (home screen, follow-ups). The data and the RAG are good enough. The plan adds those question types, a fixed answer shape, a new dashboard layout, guided scenario cards, and an evaluation that proves it.

### 15.1 Answer engine v3 (the router gets the missing question types)
**1. Understanding: rules + a small model.**
- A fast model call (Gemini Flash-Lite, falling back to Groq; ≤ 600 ms; JSON schema; temperature 0) classifies the question into one of the **12 question types** below and extracts the entities.
- The current rules stay as the fallback and as the source of names (PSI, materials, fields, test ids from the db vocabulary). The model's entities are accepted only if they exist in the vocabulary.
- Logged as `understanding: {by: model | rules, type, entities, confidence}`.

**2. The 12 question types and what answers them:**
| type | example | tools (server) |
|---|---|---|
| emergency now | "there's smoke from the rack" | `declare_fire_emergency` (fast path, no RAG) |
| procedure / what-if | "what should I do if a fire starts in the suit?" | the procedure line + `ask_sources` |
| **explain a concept** (new) | "what is ignition?", "what is a cool flame?", "what does spread rate mean?" | `explain(term)`: the glossary (15.2) + `ask_sources` + one data example |
| **interpret a value** (new) | "what does 18 % oxygen mean?", "is 39.8 % at 14.8 psi dangerous?" | `interpret_conditions(o2, p)`: where the value sits (vs the ISS / Moon base / suit / sea level) + `nearest_tests` outcomes + the closest evidence lines + the coverage note |
| **a test** (new) | "tell me about test 19115A1", a pasted table row | `get_test(test_id)`: all fields, its investigation, what the test measured, its source page; plus `similar_tests` |
| **compare tests / investigations** | "compare 19150A1 and 19115A1", "BASS vs Saffire" | `compare_tests(ids)` (new) / `compare(psi_a, psi_b)` |
| **nearest value** (new) | "tests at 40 %", "anything near 8 psi with fabric" | `nearest_tests` (it exists) used as a search, with a material filter, and returns the rows |
| data catalogue | "what materials?", "O₂ range?", "how many tests in Saffire-III?" | `list_materials`, `data_ranges`, `find_tests`, `get_investigation` (count fallback) |
| **papers** (new) | "which paper appears most?", "papers on BASS-II" | `list_papers(psi=None, topic=None)`: papers ranked by findings / citations in the sources, with DOI |
| effect / why | "does flow make fabric burn faster?", "why are flames round?" | `get_findings` + `ask_sources` (the RAG line is always kept for these) |
| relevance ranking | "which experiments matter most for prevention?" | `rank_investigations` |
| navigation / off-topic | "go back", "weather on Mars" | actions / redirect |

**3. One answer shape for every question type** (spoken ≤ 3 sentences; the screen shows all parts):
1. **Direct answer:** the one sentence that answers the question asked.
2. **Evidence:** the number, test or finding behind it, with its source.
3. **Meaning:** what it means for the crew or the learner (from the interpretation templates, glossary or RAG; never invented).
4. **Coverage note:** when coverage is low, say so in one clause, and still give what exists ("Only 3 tests reach 40 % oxygen, all burner flames, so treat this as a hint").
5. **Next step:** one offer that names what it will show ("Want the 3 tests at 40 %?").

Ranking answers drop the method sentence from speech; it stays on screen as a footnote.

**4. Vague questions: ask, but smartly.**
- A question is vague when the type confidence is < 0.6 or ≥ 2 types tie.
- Flamo asks one short question with 2–3 options **that have data** ("Do you mean what ignition is, or the ignition tests in the data?"). The options appear as chips.
- After 1 clarify, it never asks again on that turn; it takes the best option and says which.

**5. Follow-ups.**
- The session keeps the last result's **rows and list** (investigations, tests, papers on screen), not only the PSI / material.
- "they / them / these / the first one / the best of them / compare them / a random one" resolve against that list.
- Gemini is no longer the gatekeeper: every final user turn that is not an action runs `answer()` on the server, even if Gemini did not call it (Round 14 leak: about 5 of 40 turns).

**6. "Not covered" becomes rare and specific.**
- Before "not covered": the glossary, the RAG unscoped, the nearest-value search, the probe.
- When it is said, it is one of 3 worded cases (Round 13 §13.3), plus what does exist.
- **Target on the eval set: "not covered" < 5 %, every one reviewed.**

**7. Speed.**
- Understanding (≤ 0.6 s) runs in parallel with an unscoped RAG prefetch; the SQL branches run in milliseconds.
- Widening is SQL-only.
- After 1.5 s Flamo says a short filler ("Let me check the papers").
- **Target: p50 ≤ 2.5 s, p95 ≤ 4.5 s.**

**8. Adaptive retrieval depth: when the search returns too little, search wider (team, 2026-11-12 21:39).**
- **First pass (as today):**
  - vector top 40 + keyword top 40 inside the scope;
  - the rerank keeps the best 8;
  - the composer gets the chunks above the score cutoff.
- **"Too little" means any of:**
  - fewer than 10 candidates survive the scope filter;
  - fewer than 3 chunks pass the rerank cutoff;
  - the best rerank score is below the cutoff (Round 9 §9.3);
  - the composer drops every sentence (no citation / number not in chunk).
- **Second pass** (only if ≥ 1.5 s are left in the budget; one pass at most), in this order until "enough":
  1. **Deeper:** vector and keyword top 120 in the same scope; rerank the best 50.
  2. **Wider scope:** one level up: the PSI → its family / pillar's PSIs; the material → its family; the scenario dropped.
  3. **Expanded query:** add the glossary synonyms and the question type's key terms (e.g. "ignition" → ignite, ignition delay, autoignition; "spread rate" → flame spread, spread velocity).
- **More context for the composer:** for each kept chunk, also pass its neighbour chunks on the same page (±1), so a sentence cut by the chunker is complete. The citation stays the kept chunk's page.
- **Logged:** `retrieval: {pass: 1 | 2, k, candidates, passing, best_score, widened: "deeper | scope | query", ms}`.
- **The eval (15.8) compares** hit@5 and the answer rate with adaptive depth on vs off. It stays on only if it improves them without breaking p95 ≤ 4.5 s.

### 15.2 Learning content: glossary and explanations (D15-1)
- **`glossary.json`:** about 40 terms a learner meets on screen (ignition, flame spread rate, opposed / concurrent flow, cool flame, extinction, soot / smoke point, LOI / oxygen index, partial pressure, microgravity vs normal gravity, burner stream vs ambient, PMMA, SIBAL, Nomex, droplet combustion, inverse flame…).
- **Each entry:**
  - a plain 1–2 sentence definition;
  - "why it matters in space" (1 sentence);
  - a PSI example (an investigation + a finding or test);
  - its source: a chunk id / paper page from the corpus, or the challenge text.
- **Built semi-automatically:** the RAG drafts from the corpus, then the team reviews and edits each entry once. It is stored with the reviewer's name and date.
- **On screen:** underlined terms in answers and on the dashboard open a small definition popover (no model call).
- **D15-1 (policy):** when neither the glossary nor the RAG has a definition, may Flamo give **one sentence of general background**, clearly labelled "general background, not from the PSI data", with no numbers? Proposed: **yes, for "what is / what does X mean" only.** Learners need it, and the label keeps the evidence rule honest.

### 15.3 Flamo's persona and the two modes (new system prompt)
**Persona:** Flamo is the crew's fire-safety copilot riding along in the simulation (cabin, Moon base, suit). It is calm, warm and precise. It speaks like a mission specialist who is also a good teacher.

**Two modes, chosen automatically, with a toggle on screen (D15-2):**
- **Crew mode** (in a scene, or an emergency / procedure / conditions question):
  - short;
  - action first;
  - numbers only from data;
  - the emergency path in under 1 second (no RAG).
- **Learn mode** (concept, why, compare, paper questions; or the toggle):
  - explains step by step;
  - gives the definition, the evidence and an example;
  - offers to go deeper;
  - may be 4 sentences;
  - the dashboard shows the "Explain" card (definition + diagram + source).
- **The evidence rules stay in both modes:** no number not in a result, no "safest", no Mars numbers, "the authors report" kept, and coverage stated honestly.

**The prompt is rewritten** around the 12 question types and the answer shape (15.1.3), with 2 example dialogues per mode. It is kept under about 1,200 words.

### 15.4 Home screen and navigation
- **An answer on the home screen opens its dashboard:** the frontend queues `answer.show` / `view.open` while no dashboard is mounted, navigates to `/solution?cat=<answer pillar>&env=<scenario>`, then replays the queued commands. The hub card of that pillar pulses for 0.5 s before the transition.
- **Route by the answer:** the answer's pillar picks the category (D3-2). A cross-pillar answer (e.g. a paper list) opens a neutral "Answer" view, not a random category.
- **Breadcrumb at the top of the dashboard:** Home › Flammability › "Is 39.8 % at 14.8 psi dangerous?" with Back (view history, Round 13 §13.8).

### 15.5 Dashboard v2: entry speed, layout and charts
**Speed:**
- The server precomputes the 4 pillars × 3 scenarios overviews at startup (12 payloads, cached, invalidated with `serving.db`'s hash).
- The hub prefetches on hover. Entry renders the cached payload at once (target < 300 ms); live parts (the nearest tests) fill in after.
- **No full-page skeleton after the first load.** Only the sections that change show a spinner.

**One layout for the middle dashboard** (all pillars and answers, top to bottom, single column, max 3 sections visible without scrolling at 1440×900):
1. **Header:** the question (or the category title on entry), a scenario chip, a coverage badge (High / Medium / Low with a one-line reason), and the mode badge (Crew / Learn).
2. **Answer card:** the 3 spoken sentences with superscript source numbers, with a "Meaning" line highlighted. For Learn mode, an "Explain" box with the glossary definition.
3. **Evidence chart:** ONE chart chosen by question type (15.5 chart rules), with a 1-line caption saying what it shows and how many tests.
4. **Where you are:** the conditions map + the oxygen ladder + nearest tests (Round 11), collapsible.
5. **Tests / findings table:** sortable; a click opens the test drawer (`get_test`).
6. **Sources:** numbered in reading order, with the viewer.

**Chart rules** (one design system: the same fonts, sizes, colours by investigation, nice ticks, psi first, a legend always, tooltips with the test id + material + conditions + outcome, and a click to open the test drawer):
| question type | chart |
|---|---|
| a value / conditions | the O₂-vs-pressure map with the user's point + scenario markers (log-psi axis) |
| an effect (X vs Y) | a scatter of Y vs X by investigation, with the finding's statement as the annotation |
| compare | side-by-side bars or a dumbbell per measurement for the 2–3 items |
| catalogue / ranges | a horizontal range bar per investigation (min–max, count) |
| ranking | ranked bars with tier chips; the method in the footnote |
| a test | a "test card" (all fields) + its position on the map + similar tests |
| explain | a small concept diagram from a fixed set (flame spread opposed vs concurrent; buoyant vs microgravity flame; ambient vs burner stream; partial pressure) |

**Interactions:**
- hover → tooltip;
- click a point / row → the test drawer;
- "Compare" checkboxes on rows → `compare_tests`;
- "Ask about this" on any card → it sends a prepared question.

### 15.6 Scenario cards: the guided "Try this" deck (for judges and new users)
Under the conditions panel (right side), a deck of cards for the **current category × scenario**. Each card is one tap. It sets the sliders / scenario if needed, and sends a prepared question or action. Six card types, each with its own icon and colour:
| card type | example (Flammability × Moon base) |
|---|---|
| Emergency drill | "Smoke from a rack in the habitat": runs the emergency flow, banner + steps, then "clear" |
| Conditions what-if | "34 % O₂ at 10.2 psi: what burned near here?" (moves the sliders) |
| Science question | "Does airflow make fabric burn faster in microgravity?" |
| Explain a concept | "What is a cool flame?" (Learn mode) |
| Compare | "BRE at 34 % vs the ISS at 21 %: what changes?" |
| Vague on purpose | "Is it dangerous here?" (shows the clarifying question with options) |

- **Content:** `scenario_cards.json`, 4 pillars × 3 scenarios × 6 types = **72 cards**, written once, each with its expected question type and key facts.
- Each card is a golden in the eval (15.8). A card that fails the eval is hidden, never shown broken.
- **Demo safety (D15-3):** the answers to the 72 cards are cached after a passing eval run. When the APIs are slow or out of quota, the card plays its cached answer (marked "cached" in the log, not on screen).

### 15.7 Voice and chat experience
- **The chat box does not open suddenly:**
  - the chat is a docked panel with a smooth height transition;
  - focusing the input never moves the layout;
  - a typing / thinking indicator shows while waiting;
  - Enter sends, Shift+Enter makes a new line;
  - chips under the input show the next-step offers.
- **Voice:**
  - echo guard (Round 13 §13.8);
  - barge-in (the user can interrupt);
  - the filler at 1.5 s;
  - one language per session unless the user switches;
  - Arabic replies keep the numbers as digits.
- **Category entry:**
  - each hub card shows real counts (investigations · tests · flight %) and "You can ask: …";
  - entering a category plays one short intro (≤ 2 sentences) and highlights the deck.

### 15.8 Evaluation: proof that the solution is solid (for the judges)
**A fixed eval set, versioned in the repo** (`eval/`), about 150 items:
- the 72 scenario cards;
- 40 real logged questions (incl. this session and Rounds 10 / 13);
- 20 general → specific pairs (Round 14);
- 15 adversarial items (vague, off-topic, unsafe, "safest", Mars numbers, a pasted table row, Arabic).

Each item has its expected question type, tool(s), key facts / numbers, source ids, and an "allowed to clarify" flag.

**Metrics (an automatic script, `eval/run.py`, run before each demo):**
| metric | how | target |
|---|---|---|
| routing accuracy | type + tool vs expected | ≥ 90 % |
| retrieval hit@5 | the expected source in the top 5 chunks | ≥ 80 % |
| citation precision | spoken / shown sentences whose cited chunk supports them (the checker + a model judge on a sample, with a human check of 30) | ≥ 95 % |
| number faithfulness | every spoken number appears in the tool / chunk text | 100 % |
| answer rate | answered or clarified with real options (not "not covered") | ≥ 95 % |
| forbidden-word checks | "safest", Mars numbers, "coverage" for the suit … | 0 violations |
| latency | p50 / p95 of `answer()` | ≤ 2.5 s / ≤ 4.5 s |

**Judge-facing proof:**
- an **"Evaluation" page in the app** (a tab on the home screen): the metric table from the last run, the date, the corpus size (papers, NASA documents, tests, findings), 5 example traces (question → understanding → tools → sources → answer), and how to rerun it;
- the same numbers in the README and the demo video.

### 15.9 Reliability for the demo
- **Health panel** (`/api/health` + a small badge): RAG ON / OFF, Postgres, Cohere / Gemini / Groq key pools (calls left), `serving.db` hash, last eval run.
- **Quotas:**
  - one Cohere embed + one rerank per question; cached embeddings for the cards;
  - Gemini Live on its own key, never shared with the composer pool.
- **Fallbacks:** RAG down → FTS; composer down → the extractive answer; Gemini Live down → the typed chat still works through `answer()` (REST), so the dashboard and cards still demo.

### 15.10 Decisions for the team
- **D15-1:** one sentence of labelled general background for "what is / what does X mean" when the glossary and the RAG have nothing. **Proposed: yes.**
- **D15-2:** Crew / Learn mode. (a) Automatic + a toggle; (b) a toggle only. **Proposed: (a).**
- **D15-3:** cached answers for the scenario cards as a demo fallback. **Proposed: yes**, refreshed by each passing eval run.
- **D15-4:** the understanding step uses a small model (Flash-Lite / Groq) with the rules as the fallback. **Proposed: yes** (the rules alone mis-type long, typo'd or Arabic questions).

### 15.11 Phases (each ends with a STOP and a review in the chat)
| phase | content | STOP evidence |
|---|---|---|
| **P1: answer engine** | 15.1 (model understanding, 5 new tools: `explain`, `interpret_conditions`, `get_test`, `compare_tests`, `list_papers`; the answer shape; follow-up lists; the server runs `answer()` on every question turn; speed; adaptive retrieval depth), 15.2 glossary draft | the replay of this session + Round 13 / 14 replays: a table question → type → tools → first spoken line; the not-covered count before / after; latency p50 / p95 |
| **P2: persona + home + chat** | 15.3 prompt + modes, 15.4 home routing + breadcrumb, 15.7 chat / voice | a screen recording: a question on the home screen opening the dashboard; Crew vs Learn answers to the same question |
| **P3: dashboard v2** | 15.5 caching, layout, chart rules, test drawer, compare | screenshots at 1440×900 for each chart type; entry time < 300 ms cached |
| **P4: scenario deck** | 15.6, 72 cards + their goldens | a screenshot of the deck per scenario; the card eval results |
| **P5: evaluation + reliability** | 15.8 eval set, `eval/run.py`, the Evaluation page, 15.9 health + fallbacks | the metric table vs targets; the Evaluation page screenshot |
| **P6: final live test** | the chat browser test + the team's voice test (English + Arabic) with headphones | the logs; the go / no-go list for the demo |

Rounds 12–14 open items are folded into P1–P3. Nothing in this round changes the data rules: every number from flameo, sources on screen, honest coverage.

### 15.12 P1 review (2026-11-12 22:50): ACCEPTED with a short P1.1 fix list before P2
**P1 result** (Claude Code report):
- 5 new tools + goldens in psi_stage1, vendored;
- replay of 87 questions: **0 "not covered"** (was 6 of 19 in the Round 15 session);
- the Round 15 transcript scores 19 / 19;
- `answer()` latency p50 1.3 s, p95 4.0 s;
- tests 481 + 164 green;
- glossary draft of 44 terms.

**Good:** the explain / test / nearest / papers / interpret question types work, and "what they cover" resolves to the 3 ranked investigations.

**P1.1 (fix before P2, about 1–2 hours):**
1. **The interpretation wording is wrong:** "18 percent oxygen is about the same as the 21 percent of the ISS cabin".
   - Rule: compare by the actual difference. "About the same" only within ±1 point; otherwise "below / above the ISS cabin's 21 %", and say by how much only if flameo returns the number.
   - Add goldens for 18 %, 21 %, 26 %, 34 %, 40 % and 100 %.
2. **The answer to "what's the best paper (appears a lot)" starts with a count** ("168 papers have findings in the data"). The first line must answer the question: the paper with the most findings (title, investigation, n findings), then the next 2, then the count.
3. **"What does the screen say?"** went to a clarify (SPICE or BASS-II).
   - Add a `screen` question type → speak the current view's `overview_speak` / answer headline from `DashboardState` (what is actually on screen).
   - Golden: on the Prevention overview → the Prevention overview line.
4. **The understanding model times out on 22 of 41 calls (1.3 s each)**, so on those turns it adds latency and gives nothing.
   - Keep it asynchronous: start the rules plan and the RAG prefetch at once, and accept the model's result only if it arrives within 0.9 s. Otherwise go on with the rules (no wait).
   - Pick the fastest available classification model from the provider's model list (Groq first), and give the understanding step its own key from the pool.
   - Report the model's success rate and the latency it adds (p50 / p95 with vs without it).
5. **Adaptive depth fires too often** (the second pass on about 38 of 59 RAG calls). Change the trigger to:
   - 0 chunks above the cutoff,
   - or fewer than 10 candidates in scope,
   - or the composer dropped every sentence.

   Drop "fewer than 3 pass the cutoff". Rerun the 30-question eval **twice** for both off and on when the Gemini quota is back; report the run-to-run spread. Keep it on only if the answer rate is ≥ off and hit@5 is within the spread.
6. **The explain example must be on topic:** use a finding as the example only if its text contains the term (or a glossary synonym). Otherwise show no example (ignition currently shows a reignition finding).
7. **Rerun the live replay after these fixes** (the BRE fix is not in the current report).
8. **Send 10 random full answers from the replay** (question, spoken lines, sources, the chunk quotes behind them) for a correctness check by the chat. 0 "not covered" is good only if the answers are right.

**Glossary (team, in parallel with P1.1):**
- the 44 terms are Claude Code's drafts from general knowledge, and 20 have no source;
- the team splits them (about 11 each across 4 people), checks each definition, adds a corpus source or marks it "general background" (D15-1), and fills `reviewer` / date;
- unreviewed terms are not spoken; the screen shows them labelled "draft".

**Other notes:**
- **Quota:** the Gemini keys hit 429 during the replay. For the demo:
  - Gemini Live gets its own key, used by nothing else;
  - the composer uses Groq first when Gemini is out;
  - the health badge (P5) shows the calls left.
- **Git:** `src/agent.py` was committed with some of the team's earlier uncommitted lines (the deploy / `LIVEKIT_PUBLIC_URL` work). The team checks that commit's diff; `src/api.py` is still uncommitted.
- **Not done in P1 and moved to P2:**
  - the voice catch-up path (Gemini skips the tool → the server's answer is spoken);
  - the 1.5 s filler.
- **Postgres:** can keep running.

**STOP for P1.1:** the new replay table (only the changed rows + totals), the model success / added latency, the adaptive on / off × 2 table, and the 10 sample answers. Then P2.
