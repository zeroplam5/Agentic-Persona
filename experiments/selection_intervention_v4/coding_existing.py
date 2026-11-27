"""Single-coder category coding of pilot v3 structured records (Dior, Canva, Mastercard).

Coder: Claude (analysis session 2026-11-23), reading the English originals. NOT human-verified.
Unit: one candidate (`core_idea` + title) or one final proposal (`final_proposal.title` + `.idea`).
Level coded: CORE MECHANISM (what the idea does to solve the problem). Problem frame and execution
elements are coded separately (problem frames in the Dior report; auxiliary elements in analyze_existing.py).

Rule: the LLM bucket (data/buckets.jsonl, gpt-6-astra) is the DEFAULT; an item is re-assigned when its text
shows a different core mechanism (OVERRIDES below, each with a short reason). Same codebook is applied to
candidates and finals of a brand. Mixed ideas get the mechanism named in the title + first two sentences;
the rest is treated as auxiliary.
"""

# ---------------------------------------------------------------- codebooks (core mechanism)
CODEBOOK = {
    "Dior": {  # from results/dior_convergence_analysis.md section 3.2 (prior work), unchanged
        "A": "artisan-signed / visible repair mark as status signal",
        "B": "repair history record, passport, certified resale",
        "C": "public repair of anyone's clothes, repair teaching, open atelier, store closure day",
        "D": "new collection / runway from archive, offcuts or clients' clothes",
        "E": "designed to be altered (extra seam allowance, lifetime alteration promise)",
        "F": "Second Fitting: couture fitting ritual extended over the garment's life / to next owner",
        "G": "permission to wear (stop saving pieces)",
        "H": "wardrobe diagnosis / consultation",
    },
    "Canva": {
        "A": "payslip decoded: redesign the first payslip so it is understandable (explainer)",
        "B": "keepsake: turn the first paycheck into a frameable / shareable memento",
        "C": "what it became: story of what the first pay bought or turned into",
        "D": "paid for what you made: show the work that earned the first pay",
        "E": "first invoice / freelancer pricing kit",
        "F": "employer-side first-payday / onboarding kit for new hires",
        "F2": "the employer's own first payroll (founder who signs the first paycheck)",
        "G": "look professional / belong on day one: first-job template kit",
        "H": "value beyond the payslip: case for your next paycheck, hidden contributions",
        "I": "thank-you to the person who got you there",
        "J": "the resume that got paid",
        "K": "Canva creates first paid commissions",
        "Z": "other (single occurrences)",
    },
    "Mastercard": {
        "A1": "recognition at the tap: terminal shows chosen name / regular signal",
        "A2": "Regulars programme: certify / fund local merchants that know their regulars",
        "A3": "Slow Lane / Take Your Time: unhurried checkout, slower payment sound",
        "B": "paid invitation: pre-paid treat or plan, often unlocks only when both tap together",
        "C": "settle in person: a debt / IOU becomes a reason to meet",
        "D": "open seat / communal table for solo diners or strangers",
        "E": "connection index / loneliness map from aggregated spend data",
        "F": "missed you: merchant or contact nudged when a routine lapses",
        "G": "solo tax: remove the extra price of being alone",
        "H": "commitment money: shared pots, deposits, caps, social budgets, rewards for togetherness",
        "Z": "other (single occurrences)",
    },
}
# coarse family for Mastercard (problem frame 'the till lost its human moment' vs others)
FAMILY = {"Mastercard": {"A1": "A", "A2": "A", "A3": "A"}}

# ---------------------------------------------------------------- candidate defaults (bucket -> code)
BUCKET_DEFAULT = {
    "Dior": {3: "A", 1: "B", 12: "B", 0: "C", 2: "C", 5: "C", 6: "C", 7: "D", 13: "D", 14: "D",
             10: "E", 11: "E", 4: "F", 9: "G", 8: "H"},
    "Canva": {0: "H", 1: "D", 2: "E", 3: "G", 4: "B", 5: "Z", 6: "I", 7: "C", 8: "C", 9: "E", 10: "C",
              11: "A", 12: "H", 13: "H", 14: "Z", 15: "D", 16: "A", 17: "Z", 18: "J", 19: "C", 20: "G",
              21: "F", 22: "Z", 23: "K", 24: "B", 25: "C"},
    "Mastercard": {0: "A2", 1: "Z", 2: "Z", 3: "B", 4: "E", 5: "C", 6: "H", 7: "B", 8: "B", 9: "H",
                   10: "D", 11: "D", 12: "Z", 13: "F", 14: "G", 15: "D", 16: "Z", 17: "Z", 18: "D", 19: "Z",
                   20: "H", 21: "Z", 22: "H", 23: "Z", 24: "D", 25: "E"},
}

# item id format: '<brand>|<cond>|<rep>|C<n>' (NODEDUP k0..k3 -> C1..C4)
OVERRIDES = {
    # Dior (prior report section 3.2 note)
    "Dior|LK_O_L|0|C1": ("F", "'The Second Fitting' fitting ritual; bucket c10 (E)"),
    # Canva
    "Canva|SB_O_L|1|C2": ("G", "'Paid to look like you know what you're doing' = day-one competence kit"),
    "Canva|SB_O_H|3|C2": ("D", "'Paid By Design' shows artifacts made before the pay"),
    "Canva|NODEDUP|2|C2": ("D", "'The Thing That Got You Paid'"),
    "Canva|SB_O_L|2|C1": ("A", "payslip made 'beautiful and understandable' (explainer)"),
    "Canva|SB_O_L|1|C1": ("A", "restyle payslip so people understand it"),
    "Canva|LK_O_H|0|C1": ("A", "payslip redesigned with plain-language labels"),
    "Canva|NODEDUP|3|C3": ("A", "'Worth Framing' but body = redesign payslip as neglected brief"),
    "Canva|BASE|1|C1": ("F", "HR moment kit"),
    "Canva|LK_O_H|2|C3": ("F", "first payday kit for managers"),
    "Canva|SB_O_H|0|C3": ("F", "employer / HR first-payday kits"),
    "Canva|SB_O_H|2|C3": ("F2", "'The Signer' founder running first payroll"),
    "Canva|SB_AVG|2|C4": ("F2", "'The First Paycheck You Sign' founder"),
    # Mastercard: bucket 0 merged three mechanisms -> split
    **{f"Mastercard|{k}": ("A1", "name / regular signal shown at tap") for k in [
        "NODEDUP|1|C3", "NODEDUP|3|C3", "NODEDUP|3|C1", "NODEDUP|1|C1", "NODEDUP|0|C4", "SB_O_L|1|C4",
        "SB_O_L|3|C4", "BASE|3|C3", "SB_AVG|0|C2", "LK_O_H|3|C1", "LK_O_H|2|C1"]},
    **{f"Mastercard|{k}": ("A3", "slow / unhurried checkout, sound cue") for k in [
        "NODEDUP|1|C2", "NODEDUP|2|C1", "NODEDUP|3|C2", "NODEDUP|3|C4", "NODEDUP|0|C3", "LK_AVG|2|C1",
        "SB_O_H|3|C1", "BASE|3|C1", "LK_O_H|1|C1", "SB_O_H|0|C1", "SB_O_H|1|C1", "SB_AVG|0|C1",
        "SB_AVG|3|C1", "BASE|1|C1", "BASE|2|C2"]},
    "Mastercard|LK_O_L|1|C1": ("B", "receipt carries a pre-paid second-seat invitation"),
    "Mastercard|BASE|0|C4": ("B", "give the second seat to someone outside your circle"),
}

# ---------------------------------------------------------------- finals (core mechanism of final_proposal)
FINAL = {
    "Dior": {  # prior report section 3.5
        **{f"Dior|{r}": "A" for r in ["BASE|2", "SB_AVG|0", "SB_AVG|1", "SB_AVG|2", "SB_O_H|0", "SB_O_H|1",
                                      "SB_O_L|0", "SB_O_L|2", "SB_O_L|3", "LK_AVG|0", "LK_AVG|1", "LK_AVG|2",
                                      "LK_O_H|0", "LK_O_H|1", "LK_O_H|2", "LK_O_H|3", "LK_O_L|1", "LK_O_L|2",
                                      "LK_O_L|3", "NODEDUP|1", "NODEDUP|2", "NODEDUP|3"]},
        **{f"Dior|{r}": "F" for r in ["BASE|3", "SB_O_L|1", "LK_O_L|0", "NODEDUP|0"]},
        "Dior|BASE|1": "D", "Dior|SB_O_H|2": "D", "Dior|SB_O_H|3": "G", "Dior|LK_AVG|3": "G",
        "Dior|SB_AVG|3": "C", "Dior|BASE|0": "E",
    },
    "Canva": {
        "Canva|BASE|1": "D", "Canva|BASE|2": "B", "Canva|SB_O_H|2": "H", "Canva|LK_AVG|3": "B",
        "Canva|BASE|3": "D", "Canva|SB_O_H|1": "B", "Canva|SB_O_H|3": "I", "Canva|SB_O_L|0": "G",
        "Canva|LK_O_H|2": "A", "Canva|SB_O_L|3": "D", "Canva|SB_O_L|2": "H", "Canva|LK_O_H|3": "A",
        "Canva|SB_AVG|0": "H", "Canva|SB_O_H|0": "D", "Canva|SB_O_L|1": "D", "Canva|SB_AVG|2": "A",
        "Canva|SB_AVG|1": "E", "Canva|LK_AVG|2": "A", "Canva|BASE|0": "A", "Canva|LK_O_L|2": "B",
        "Canva|LK_O_H|0": "A", "Canva|LK_O_L|3": "A", "Canva|LK_O_L|1": "C", "Canva|LK_O_L|0": "A",
        "Canva|LK_AVG|0": "G", "Canva|SB_AVG|3": "K", "Canva|LK_O_H|1": "A", "Canva|LK_AVG|1": "B",
        "Canva|NODEDUP|0": "A", "Canva|NODEDUP|1": "E", "Canva|NODEDUP|2": "B", "Canva|NODEDUP|3": "B",
    },
    "Mastercard": {
        "Mastercard|LK_O_H|0": "B", "Mastercard|LK_AVG|2": "B", "Mastercard|SB_O_L|1": "A1",
        "Mastercard|SB_O_L|3": "H", "Mastercard|SB_O_H|3": "B", "Mastercard|BASE|3": "C",
        "Mastercard|SB_O_L|0": "B", "Mastercard|LK_O_H|1": "A2", "Mastercard|SB_O_H|0": "A3",
        "Mastercard|SB_O_H|2": "A2", "Mastercard|SB_O_H|1": "B", "Mastercard|LK_AVG|1": "C",
        "Mastercard|LK_O_L|0": "B", "Mastercard|SB_AVG|0": "A1", "Mastercard|SB_O_L|2": "B",
        "Mastercard|LK_O_L|2": "B", "Mastercard|LK_AVG|0": "B", "Mastercard|SB_AVG|3": "B",
        "Mastercard|SB_AVG|2": "B", "Mastercard|LK_AVG|3": "A2", "Mastercard|LK_O_L|3": "H",
        "Mastercard|LK_O_H|3": "A1", "Mastercard|LK_O_L|1": "B", "Mastercard|BASE|1": "A3",
        "Mastercard|LK_O_H|2": "A1", "Mastercard|SB_AVG|1": "B", "Mastercard|BASE|2": "A3",
        "Mastercard|BASE|0": "B",
        "Mastercard|NODEDUP|0": "A3", "Mastercard|NODEDUP|1": "F", "Mastercard|NODEDUP|2": "A2",
        "Mastercard|NODEDUP|3": "A1",
    },
}

# Finals whose main mechanism differs from the selected candidate's, or is a boundary call (note for readers)
FINAL_NOTES = {
    "Canva|SB_O_L|3": "selected G (belonging); final headline device = first thing you made (D), frame still belonging",
    "Canva|SB_O_L|1": "selected G; revision added 'The First Thing I Got Paid For' device, which became the title (D). No candidate source recorded",
    "Canva|NODEDUP|3": "boundary A/B: title frame 'ritual back', body = payslip turned into keepsake + explainer",
    "Canva|NODEDUP|2": "boundary A/B: 'Worth Framing' with explainer first in the kit",
    "Dior|SB_O_L|1": "selected H (wardrobe consultation, titled 'Second Fitting' in revision) -> final F",
    "Mastercard|SB_AVG|3": "boundary B/H: shared pot that unlocks together (coded B as selected candidate)",
}
