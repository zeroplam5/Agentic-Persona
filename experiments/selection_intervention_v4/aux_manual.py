"""Manual (single-coder) stage-of-entry judgements for recurring auxiliary elements, after reading
selected candidate core_idea, selection.rejected, revisions_after_selection and final_proposal in full.
Auto keyword stages (results/existing_aux_elements_auto.csv) were only a screen; these override them.

Stage codes (earliest point the element appears in the run's record):
  S1  already in the SELECTED candidate's core_idea
  S2  rejection reason of another candidate plans to absorb it -> revision adds it
  S3  revision adds it; a home candidate existed but its rejection deferred / did not plan absorption
  S4  revision adds it; no candidate in the run had it as core mechanism (no recorded source)
  REV_ONLY  revision records adding it but the final text does not contain it
  absent
Dior rows reproduce the prior report (dior_convergence_analysis.md section 4.5: types 2/3/4).
"""
MANUAL = {
    "Dior:MARK (home A)": {
        "S1": ["Dior|BASE|3", "Dior|LK_O_L|0"],
        "S2": ["Dior|BASE|1", "Dior|SB_AVG|3", "Dior|SB_O_H|2", "Dior|SB_O_H|3", "Dior|SB_O_L|1", "Dior|LK_AVG|3"],
        "S4": ["Dior|BASE|0"],
        "MAIN": 19,
    },
    "Canva:EMPLOYER_KIT (home F/F2)": {
        "S1": ["Canva|BASE|2", "Canva|LK_AVG|3", "Canva|LK_O_H|2", "Canva|LK_O_H|3", "Canva|SB_AVG|2",
               "Canva|BASE|0", "Canva|LK_O_L|2", "Canva|LK_O_H|0", "Canva|LK_O_L|3", "Canva|LK_O_L|1",
               "Canva|LK_O_L|0", "Canva|LK_O_H|1"],
        "S2": ["Canva|BASE|1", "Canva|SB_O_H|1"],
        "S3": ["Canva|SB_O_H|2"],
        "S4": ["Canva|BASE|3", "Canva|SB_O_H|3", "Canva|SB_O_L|0", "Canva|SB_O_L|3", "Canva|SB_O_L|2",
               "Canva|SB_AVG|0", "Canva|SB_O_L|1", "Canva|LK_AVG|0", "Canva|LK_AVG|1"],
        "absent": ["Canva|SB_O_H|0", "Canva|SB_AVG|1", "Canva|LK_AVG|2", "Canva|SB_AVG|3"],
        "MAIN": 0,
    },
    "Canva:KEEPSAKE (home B)": {
        "S1": ["Canva|LK_O_H|3", "Canva|SB_AVG|2", "Canva|LK_O_L|1"],
        "S2": ["Canva|SB_O_L|3", "Canva|SB_O_L|0", "Canva|LK_O_L|0", "Canva|SB_AVG|3", "Canva|LK_AVG|2",
               "Canva|LK_AVG|0"],
        "S4": ["Canva|BASE|1", "Canva|LK_O_H|2", "Canva|BASE|0"],
        "absent": ["Canva|SB_O_H|2", "Canva|BASE|3", "Canva|SB_O_H|3", "Canva|SB_AVG|0", "Canva|SB_O_H|0",
                   "Canva|SB_O_L|1", "Canva|SB_AVG|1", "Canva|SB_O_L|2", "Canva|LK_O_H|0", "Canva|LK_O_L|3",
                   "Canva|LK_O_H|1"],
        "MAIN": 5,
    },
    "Mastercard:MERCHANT_RECOGNITION (home A1/A2/A3) in non-A finals": {
        "S2": ["Mastercard|SB_O_H|3", "Mastercard|SB_O_L|2", "Mastercard|SB_AVG|1", "Mastercard|SB_AVG|3"],
        "REV_ONLY": ["Mastercard|SB_O_H|1", "Mastercard|LK_AVG|1", "Mastercard|LK_O_L|2"],
        "absent": ["Mastercard|LK_O_H|0", "Mastercard|LK_AVG|2", "Mastercard|SB_O_L|0", "Mastercard|LK_AVG|0",
                   "Mastercard|SB_AVG|2", "Mastercard|LK_O_L|1", "Mastercard|BASE|0", "Mastercard|LK_O_L|0",
                   "Mastercard|BASE|3", "Mastercard|SB_O_L|3", "Mastercard|LK_O_L|3"],
        "MAIN": 10,
    },
    # within family A: finals that combine >= 2 of A1 (name at tap) / A2 (Regulars programme) / A3 (slow lane, sound)
    "Mastercard:A-subtype mixing within A finals": {
        "mixed": ["Mastercard|SB_O_L|1", "Mastercard|LK_O_H|1", "Mastercard|SB_O_H|2", "Mastercard|SB_AVG|0",
                  "Mastercard|LK_AVG|3", "Mastercard|LK_O_H|3", "Mastercard|BASE|1", "Mastercard|LK_O_H|2"],
        "single": ["Mastercard|SB_O_H|0", "Mastercard|BASE|2"],
    },
}

NOTES = {
    "Dior|BASE|3": "revision says 'Added the dated, signed label' but the selected candidate already had it",
    "Mastercard|SB_O_H|2": "revision says 'Added ... chosen name shown on the terminal' but selected C1 already had it",
    "Canva|SB_O_H|0": "employer candidate C3 explicitly deferred: 'Moved the work-team angle (C3) to a later phase'",
    "Mastercard|SB_O_H|1": "revision: 'Positioned C1's Take Your Time signal as an optional merchant layer'; not in final",
    "Canva|SB_O_L|3": "keepsake absorbed from rejected C1 (coded D, contains keepsake artefact): 'Its best element, the keepsake artefact, is folded into the recommended idea'",
    "Canva|LK_O_H|2": "keepsake + employer: selected core already had employer templates; keepsake added in revision without a B candidate",
}
