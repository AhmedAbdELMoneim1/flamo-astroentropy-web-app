ask_sources [84b50c50] answer | scope 1 PSIs / 66 sources | top 5 | sentences kept 1/1 | 2159 ms | 'What oxygen level allows steady flames in the BRE tests?'
ask_sources [1d8b74a2] clarify | scope 0 PSIs / None sources | top 5 | sentences kept 0/0 | 782 ms | 'What happens to flames in the spacesuit atmosphere?'
# Voice-path transcripts (Round 9)

The real tool path (Cohere index, Gemini composer, flameo). No LiveKit session and no Gemini voice: the 'voice says' lines follow the prompt's rules.

## 1. A free question: ask_sources answers

**Astronaut:** What oxygen level allows steady flames in the BRE tests?

**Tool call:** `ask_sources(question="…", psi="BRE")`

**The model receives:**
```json
{
 "status": "ok",
 "matched": true,
 "speak": [
  "Generally, the authors of the experiment report that oxygen levels of 26 % and above can allow steady flames in the BRE tests."
 ],
 "sources": [
  {
   "n": 1,
   "label": "NASA document",
   "title": "PSI-20_Reports_Dissertation-PD-revised_",
   "page": 31
  }
 ],
 "next_offer": "Do you want the data behind it?"
}
```

**Reply guidance to the model:** Say these speak lines in your own words, keep every number and name exactly, then say once that the sources are on the screen and end with next_offer. Add nothing that is not in speak.

**The voice says** (assembled from the prompt's rules, not spoken by Gemini):

> Generally, the authors of the experiment report that oxygen levels of 26 % and above can allow steady flames in the BRE tests.
> The sources are on the screen.
> Do you want the data behind it?

**On screen (answer.show):** tool `ask_sources`, 1 spoken lines with source numbers [[1]], 1 sources:

- [1] NASA document: PSI-20_Reports_Dissertation-PD-revised_, page 31 (nasa_psi_download: https://psi.nasa.gov/geode-py/ws/studies/PSI-20/download?file=PSI-20_Reports_Dissertation-PD-revised_.pdf&version=1&redirect=true) - View

## 2. The parameters match no investigation: one clarifying question

**Astronaut:** What happens to flames in the spacesuit atmosphere?

**Tool call:** `ask_sources(question="…", scenario="spacesuit")`

**The model receives:**
```json
{
 "status": "clarify",
 "matched": false,
 "speak": [
  "Which do you mean: ACME s-Flame (PSI-23) or ACME BRE (PSI-20)?"
 ],
 "sources": [],
 "clarify": {
  "question": "Which do you mean: ACME s-Flame (PSI-23) or ACME BRE (PSI-20)?",
  "options": [
   "ACME s-Flame (PSI-23)",
   "ACME BRE (PSI-20)"
  ],
  "why": "the parameters match no investigation"
 }
}
```

**Reply guidance to the model:** Ask ONLY this question, in your own words, naming the options. Do not answer. Ask it once.

**The voice says** (assembled from the prompt's rules, not spoken by Gemini):

> Which do you mean: ACME s-Flame (PSI-23) or ACME BRE (PSI-20)?

**On screen (answer.show):** tool `ask_sources`, 1 spoken lines, 0 sources:


## 3. A danger question: oxygen_effect (never a threshold)

**Astronaut:** What oxygen level makes the spacecraft dangerous?

**Tool call:** `oxygen_effect(scenario="iss")`

**The model receives:**
```json
{
 "status": "shown",
 "matched": true,
 "speak": [
  "ISS cabin has 21 percent oxygen at 101.3 kilopascals.",
  "The PSI data does not set a single safe or dangerous oxygen level; these are the conditions where the tests still burned.",
  "In flight compared with ground tests, the authors report: In microgravity, there is still flame spread at XO2 = 17%, while flame cannot exist in normal gravity for XO2 = 18% and below."
 ],
 "first_gap": "The PSI data does not set a single safe or dangerous oxygen level; these are the conditions where the tests still burned.",
 "sources": [
  {
   "n": 1,
   "label": "Finding",
   "title": "The Effect of Gravity on Flame Spread over PMMA Cylinders",
   "page": 6
  },
  {
   "n": 2,
   "label": "Finding",
   "title": "PSI-20_Reports_Dissertation-PD-revised_",
   "page": 2
  },
  {
   "n": 3,
   "label": "Finding",
   "title": "Spherical gas-fueled cool diffusion flames",
   "page": 7
  },
  {
   "n": 4,
   "label": "NASA document",
   "title": "PSI-20_Reports_Dissertation-PD-revised_",
   "page": 31
  }
 ],
 "next_offer": "Do you want to see the oxygen against pressure chart?"
}
```

**Reply guidance to the model:** Say these speak lines in your own words, keep every number and name exactly, then say the sources are on the screen and end with next_offer if present. Add nothing that is not in speak.

**The voice says** (assembled from the prompt's rules, not spoken by Gemini):

> ISS cabin has 21 percent oxygen at 101.3 kilopascals.
> The PSI data does not set a single safe or dangerous oxygen level; these are the conditions where the tests still burned.
> In flight compared with ground tests, the authors report: In microgravity, there is still flame spread at XO2 = 17%, while flame cannot exist in normal gravity for XO2 = 18% and below.
> The sources are on the screen.
> Do you want to see the oxygen against pressure chart?

**On screen (answer.show):** tool `oxygen_effect`, 7 spoken lines, 4 sources:

- [1] Finding: The Effect of Gravity on Flame Spread over PMMA Cylinders, page 6 (doi: https://doi.org/10.1038/s41598-017-18398-4)
- [2] Finding: PSI-20_Reports_Dissertation-PD-revised_, page 2 (nasa_psi_download: https://psi.nasa.gov/geode-py/ws/studies/PSI-20/download?file=PSI-20_Reports_Dissertation-PD-revised_.pdf&version=1&redirect=true) - View
- [3] Finding: Spherical gas-fueled cool diffusion flames, page 7 (doi: https://doi.org/10.1016/j.proci.2022.07.015)
- [4] NASA document: PSI-20_Reports_Dissertation-PD-revised_, page 31 (nasa_psi_download: https://psi.nasa.gov/geode-py/ws/studies/PSI-20/download?file=PSI-20_Reports_Dissertation-PD-revised_.pdf&version=1&redirect=true) - View

