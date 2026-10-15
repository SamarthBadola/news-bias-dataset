# Annotation Guideline — News Bias & Fake News Detection Platform

Version 1.1. This is a living document. Any disagreement during labeling that the guideline doesn't resolve should be written up and folded back in, not silently decided by one annotator.

---

## 1. Purpose and Scope

This guideline governs manual labeling for four bias axes: political ideology, gender bias, communal & caste bias, and cultural bias. Two annotators will label roughly 40-50 examples for each of political ideology and gender bias. This set is held out purely for evaluation, since those classifiers are trained through weak supervision. Communal/caste and cultural bias need fewer examples, because an LLM classifies them from a small number of few-shot exemplars. Their labeled bundles are split between those exemplars and an evaluation portion, and the target count is agreed before labeling starts.

Every label needs a one-line rationale attached. A label without a rationale is not a finished label, it's a guess with a category attached to it.

---

## 2. Annotation Units

Political ideology and gender bias are labeled at the **single-article level**. The bias, if present, is visible in the article on its own.

Communal & caste bias and cultural bias are labeled at the **case bundle level**: a group of two or more articles covering comparable events or practices, where at least one dimension (community, caste, country of origin) differs between them. Neither of these two biases is reliably visible from one article read in isolation, since the definition itself is comparative. Labeling a single article on these axes means relying on an annotator's private memory of "what similar cases usually look like," which is not reproducible and won't survive scrutiny. A bundle, with the comparison written out, is something a second annotator can check.

### 2a. What the annotator reads

**Axes 1 and 2 (political, gender):** headline plus lede, nothing else. The outlet name, URL and byline are hidden and items are shuffled, so the label can't come from the outlet's reputation.

- **Why headline and lede.** Most readers see only the headline, sensationalism is concentrated there, and outlets often put more careful wording lower in the article. The platform fetches the article page at request time, so the classifier sees the same input in production that annotators see here.
- **What the label covers.** It describes the headline and lede, not the whole article, and the platform's output says "headline and opening".
- **Lede definition.** The first two body paragraphs after removing bylines, datelines and boilerplate, cut to 120 words at the last full sentence if that keeps at least 60 words, otherwise at 120 words. The collection script applies this rule, so annotators don't extract it by hand.
- **Headline and lede carry the label.** A balanced paragraph further down doesn't offset a framed headline and lede. If the headline and lede point in different directions, label the combination and set confidence to low.

**Axes 3 and 4 (communal/caste, cultural):** start from headline plus lede, then read the full article before labeling a bundle. Identity disclosure often sits in the third or fourth paragraph. The rationale names the paragraph it relies on.

**Which rows are eligible.** Only rows with `lede_status` of `ok` go to annotators. Live blogs, paywall stubs and failed fetches are excluded, since they have no real lede.

**Opinion pieces are in scope.** Opinion is news too, and columnists present nuanced views. Every row carries an `article_type` (news, wire, analysis or opinion), so results can be reported per type.

**Syndicated copy.** When a wire agency wrote the body, record `original_source` and set `syndicated` to true. Annotators label the text in front of them, not the republishing outlet, and weak labels derived from the outlet are unreliable for these rows.

**Pilot check.** During the pilot batch, annotators also record whether the label would have been the same from the standfirst (the feed description) alone. This measures how much the lede adds over the standfirst.

---

## 3. Axis 1: Political Ideology

**Classes:** Left / Right / Center, judged from an Indian political context.

**Decision approach:** This axis is trained through weak supervision, bootstrapped from outlets with a publicly documented leaning. Manual labels here exist to check the classifier's output, not to teach it, so precision on your part matters more than volume.

**Definitions:**
- **Left:** Framing that is critical of the current ruling party's positions and policy record, or sympathetic to opposition and progressive causes, in a way that goes beyond straight reporting of facts.
- **Right:** Framing that is favorable to the current ruling party and its record, or critical of opposition parties, again beyond straight factual reporting.
- **Center:** Reporting that states facts, attributes claims to named sources, and does not editorialize in either direction. Wire-service copy is the clearest example.

**Worked examples, all real, all covering the same event:** On 15 February 2026, PM Modi gave a PTI interview defending Budget 2026, and the Congress responded with sharp criticism. Three outlets covered it three different ways.

1. *Left:* [Deccan Herald's headline](https://www.deccanherald.com/india/pm-jhuke-bhi-hain-aur-thake-bhi-hain-congress-calls-modis-interview-pr-exercise-3899763) led with the Congress leader's harshest line against the PM, calling the interview a "desperate PR exercise," and gave the opposition's attack multiple paragraphs of direct quotes before any government response appeared. The news lead is the attack itself, not the interview's substance.
2. *Right:* A separate Deccan Herald piece led with BJP leader Naqvi's counter-attack on the [opposition's budget criticism](https://www.deccanherald.com/india/peddlers-of-illogical-arguments-becoming-politically-irrelevant-naqvi-slams-oppositions-budget-criticism-3883288), opening on his line calling critics "peddlers of illogical arguments" who are "becoming politically irrelevant," with no opposition rebuttal included. Same publication, same story cycle, opposite direction, same mechanism: leading with one side's attack line as the news itself.
3. *Center:* [The Statesman's coverage](https://www.thestatesman.com/india/we-are-ready-moment-pm-modi-says-budget-2026-reflects-indias-yearning-to-become-a-developed-nation-1503557282.html) leads with the PM's own claim in the headline, but the body includes the Congress's "headline management" charge with its own direct quotes, giving both sides space rather than using one side's line to frame the other.

**Exclusions:** A story that simply reports a politician's statement without commentary is not automatically Left or Right, even if the politician themselves is. What tips a story into a lean is which side's framing the headline and lead paragraph adopt as the story's own voice, not whether an opposing quote appears somewhere in the piece.

For weak-supervision bootstrapping, [Media Bias Fact Check rates NDTV Left-Center](https://mediabiasfactcheck.com/ndtv/) and [rates ANI Right-Center](https://mediabiasfactcheck.com/asian-news-international-ani), giving you outlet-level anchors independent of the article-level judgment above.

---

## 4. Axis 2: Gender Bias

**Classes:** Misogynistic / Misandrist / Neutral.

A binary forced choice between misogynistic and misandrist would push every article that has nothing to do with gender into one bucket or the other, and since this axis's manual set is your evaluation set, that would quietly corrupt it. Neutral is a real, expected outcome for most articles, not an escape hatch.

**Definitions:**
- **Misogynistic:** Coverage that sexualizes, sensationalizes, or judges a woman's appearance or conduct in ways unrelated to the actual news, or that treats a woman's involvement in a story as inherently scandalous.
- **Misandrist:** Coverage that generalizes an individual man's proven conduct into a claim about men as a category, or that assumes guilt or bad faith based on gender rather than the facts of the case.
- **Neutral:** Straight reporting, regardless of the gender of the people involved.

**Worked examples:**

1. *Misogynistic, real:* [Outlook's media critique](https://www.outlookindia.com/national/when-factual-becomes-sensational-misogny-and-titillation-in-reporting-of-women-involved-in-crime) collects headlines run by mainstream Indian outlets on women connected to crime cases: NDTV's "Indrani's Jail Diary: Botox, Affairs, and Daughter's Ghost," Times Now's "Mini-Skirt Sadhvi: Radhe Maa's Bedroom Darshan Scandal!", and Hindustan Times's "Rhea Chakraborty—The Femme Fatale Behind Sushant's Demise?" None of these lead with the legal facts of the case. All three lead with the woman's appearance, personal life, or a sexualized character label.
2. *Misandrist, real:* [The Mooknayak's coverage](https://en.themooknayak.com/women-news/father-as-natural-guardian-concept-outdated-in-21st-century-india-allahabad-hcs-landmark-custody-verdict-favors-mother) of an Allahabad High Court custody ruling ran under a headline declaring the entire concept of paternal guardianship "outdated" and rooted in patriarchal bias. The court's actual finding was narrow: this specific father had fabricated a story to alienate his daughter from her mother. The headline generalizes that individual, proven finding into a claim about fathers as a category.
3. *Neutral, real contrast:* A separate Allahabad High Court ruling, on the same statute, [held that a father cannot be denied custody unless shown unfit as a guardian](https://www.deccanherald.com/india/father-cant-be-denied-custody-of-minor-daughter-unless-found-unfit-allahabad-high-court-4126563). Deccan Herald's coverage reported the bench, the holding, and the facts, with no framing in either direction. Same court, same law, opposite outcome, and the difference in coverage tone between example 2 and this one is exactly what this axis is built to catch.

**Exclusions:** Reporting that a specific man or woman lost a case, committed an offense, or made a mistake is not itself biased. The bias is in generalizing an individual's conduct to their entire gender, not in reporting the individual fact.

---

## 5. Axis 3: Communal & Caste Bias

**Definition:** Selective identity disclosure or selective outrage based on community or caste, as distinct from overt hate speech. This bias is comparative by nature and is labeled at the bundle level (see Section 2).

### 5a. Selective Identity Disclosure

**Decision tree:**
1. Is the accused's religion or caste stated in the article? If no, not applicable.
2. Is it stated because it's operationally relevant to the story, such as a hate-crime motive or an offense under the SC/ST Act? If yes, not biased, exclude.
3. Does your bundle contain a comparable case (similar offense, similar severity) involving a different community? If no, you don't have enough to label this, flag it for more sourcing rather than guessing.
4. In the comparable case, was identity disclosed at the same stage of proceedings? If no, this is selective disclosure. Label positive.

**Worked example, real:** [Newslaundry's review](https://www.newslaundry.com/2017/06/01/the-pseudo-secularism-of-the-rampur-molestation-coverage) of the 2017 Rampur molestation case tracked how national outlets covered the story before and after the accused's identity became known. When the video first went viral, NDTV's tweet led with "In Yogi Adityanath's Uttar Pradesh, 14 men molest 2 women," framing it around the state government's accountability for the incident, and outlets pursued that angle. Once the accused were identified as Muslim and the victims as Hindu, that same coverage tapered off into routine crime-blotter reporting, in a media landscape that names an accused's religion freely when the reversal would run the other way. Bundle this article with a comparable case where the accused's community was named at the same early stage, and the asymmetry becomes the label.

**Exclusion:** Withholding an accused's identity consistently, across cases and communities, is responsible reporting, not bias. The signal is the *inconsistency* between comparable cases, not the withholding itself.

### 5b. Selective Outrage

**Decision tree:**
1. Does the article criticize a practice (noise, pollution, crowding) tied to a specific community or festival?
2. Does your bundle contain a comparable event (similar scale, similar activity) tied to a different community or occasion?
3. Is the comparable event covered with the same framing, or does it get a pass?
4. If it gets a pass, label positive for selective outrage.

**Worked example, real:** [Deccan Herald's 2025 Diwali coverage](https://www.deccanherald.com/india/delhi/green-crackers-or-not-diwali-fireworks-choke-delhi-day-after-severe-aqi-over-400-recorded-at-some-places-3771290) frames firecracker use through PM2.5 spikes and "severe" AQI readings above 400, the standard treatment every year. [PTI's coverage of India's 2024 T20 World Cup win](https://www.dtnext.in/news/national/a-night-of-celebrations-in-cricket-crazy-india-after-t20-wc-win-792588) describes fans in Delhi and Kolkata bursting firecrackers deep into the night as part of the celebration, in the same cities that get heavy pollution coverage during Diwali, with no air-quality framing anywhere in the piece.

**Exclusion:** If the comparable event genuinely didn't happen at a similar scale, there's no asymmetry to label. Confirm the events are actually comparable before calling this selective.

---

## 6. Axis 4: Cultural Bias

**Definition:** Glorifying or validating a foreign, typically Western, practice while criticizing an equivalent Indian practice without scientific backing. Also comparative, also labeled at the bundle level.

**Decision tree:**
1. Does the article criticize an Indian practice, and is the criticism backed by cited scientific evidence?
2. If backed by evidence, this is legitimate critique, not bias, exclude.
3. Does your bundle contain coverage of an equivalent Western practice?
4. Is the Western equivalent framed positively or neutrally, without the same standard of evidence being applied?
5. If yes, label positive for cultural bias.

**Worked examples, real:**

1. [The Spectator's account](https://www.spectator.com.au/?p=10846154) of meditation's medical history describes it sitting on the "unproven" therapies blacklist in Western medicine until brain-imaging research in 2007 forced a reversal. The practice was rebranded as "mindfulness" for wider acceptance and is now covered as a Western wellness breakthrough, without the earlier decades of dismissal being credited back to its Asian origin.
2. The dupatta has re-emerged in global fashion coverage as the "Scandinavian scarf." An [Elle India piece](https://elle.in/fashion/when-a-dupatta-becomes-a-scandinavian-scarf-a-case-of-fashion-appropriation-again-9046074) and a [broader trend piece on the same rebranding](https://www.aureusboutique.com/blogs/articles/from-dupattas-to-jhumkas-how-fashion-keeps-rebranding-cultural-heritage) both make the same point: the dupatta had previously been dismissed as "too ethnic" or "old-fashioned" in Western fashion coverage, and the identical garment is now being celebrated as a fresh trend once it carries a European label instead of its own name.

**Exclusion:** A practice can be criticized on cultural or ethical grounds without triggering this axis, as long as an equivalent Western practice isn't being given a pass on the same grounds. The bias is in the double standard, not in criticism itself.

---

## 7. Sourcing Matched Bundles (Axes 3 and 4)

1. Start from the single article you already have.
2. Identify what makes it comparable: same offense type and severity, same practice, same scale of event.
3. Search for coverage of the comparable case or practice, changing only the community, caste, or country of origin.
4. If you can't find a genuinely comparable case, don't force one. Flag the article as unbundled and set it aside rather than inventing a weak comparison.
5. Record both articles' sources and dates alongside the label, so the comparison can be checked later.

---

## 8. Calibration Exercise

Before labeling independently, a new annotator should review 5-8 pre-labeled examples drawn from this guideline, each with its rationale, and label them again blind. Compare against the guideline's stated label before starting on the real set. Disagreement at this stage means re-reading the relevant section, not adjusting your judgment to match and moving on.

---

## 9. Inter-Annotator Agreement Protocol

With two annotators, agreement is measured with Cohen's kappa, not raw percent agreement, since percent agreement looks artificially high on any axis where Neutral or Center dominates.

1. Both annotators independently label the same 15-20 article overlap set per axis, without seeing each other's labels.
2. Calculate Cohen's kappa on the overlap set.
3. A kappa of 0.6 or above is the threshold to trust the rest of the labels. Below that, don't relabel and hope it improves. Sit down together, find where the disagreements cluster, and revise the guideline itself.
4. Log every guideline revision with the date and the disagreement that triggered it, in Section 11.

---

## 10. Checklists

### Per-item checklist (run before finalizing any single label)

- Checked the exclusion criteria for this axis before assigning a positive label
- For axes 3 and 4, sourced a genuine comparable case, not a forced one
- Wrote a one-line rationale for the label
- Confirmed the label class actually exists in this guideline (no ad hoc classes)
- For axes 1 and 2, labeled from headline and lede only, with the outlet hidden
- Confirmed `lede_status` is ok and `article_type` is set
- For axes 3 and 4, read the full article, not just the lede

### Pre-delivery checklist (run once before handing off the full labeled set)

- Every class for every axis has at least two labeled examples
- Cohen's kappa calculated on the overlap set for each axis
- Any label missing a rationale has been fixed or removed
- Bundle sourcing recorded for every axis 3 and 4 label
- Revision log updated with any guideline changes made during labeling
- No guideline example or pilot item appears in the eval split
- Pilot batch run and the standfirst-sufficient rate recorded

---

## 11. Revision Log

| Date | Change | Reason |
|---|---|---|
| — | Initial version | — |
| 2026-10-10 | Added Section 2a: headline plus lede as the annotation input, eligibility rules, syndication and opinion handling; revised label volume for the few-shot axes | Platform fetches pages at request time; API and RSS audit showed feed descriptions differ from the lede |

---

## Sources for Worked Examples

Read the full pieces before labeling against them. The rationale above is a summary, the actual sentences and word choices worth flagging are in the original articles.

**Political ideology**
- [Deccan Herald: Congress calls Modi's PTI interview a "PR exercise"](https://www.deccanherald.com/india/pm-jhuke-bhi-hain-aur-thake-bhi-hain-congress-calls-modis-interview-pr-exercise-3899763)
- [Deccan Herald: Naqvi calls opposition budget critics "peddlers of illogical arguments"](https://www.deccanherald.com/india/peddlers-of-illogical-arguments-becoming-politically-irrelevant-naqvi-slams-oppositions-budget-criticism-3883288)
- [The Statesman: "We are ready moment" — Budget 2026 coverage](https://www.thestatesman.com/india/we-are-ready-moment-pm-modi-says-budget-2026-reflects-indias-yearning-to-become-a-developed-nation-1503557282.html)
- [Media Bias Fact Check: NDTV](https://mediabiasfactcheck.com/ndtv/)
- [Media Bias Fact Check: ANI](https://mediabiasfactcheck.com/asian-news-international-ani)

**Gender bias**
- [Outlook: "When Factual Becomes Sensational" — gendered crime headlines](https://www.outlookindia.com/national/when-factual-becomes-sensational-misogny-and-titillation-in-reporting-of-women-involved-in-crime)
- [The Mooknayak: Allahabad HC custody ruling coverage](https://en.themooknayak.com/women-news/father-as-natural-guardian-concept-outdated-in-21st-century-india-allahabad-hcs-landmark-custody-verdict-favors-mother)
- [Deccan Herald: separate Allahabad HC custody ruling, neutral framing](https://www.deccanherald.com/india/father-cant-be-denied-custody-of-minor-daughter-unless-found-unfit-allahabad-high-court-4126563)

**Communal & caste bias**
- [Newslaundry: "The Pseudo-Secularism of the Rampur Molestation Coverage"](https://www.newslaundry.com/2017/06/01/the-pseudo-secularism-of-the-rampur-molestation-coverage)
- [Deccan Herald: 2025 post-Diwali AQI coverage](https://www.deccanherald.com/india/delhi/green-crackers-or-not-diwali-fireworks-choke-delhi-day-after-severe-aqi-over-400-recorded-at-some-places-3771290)
- [PTI via dtnext: T20 World Cup 2024 win celebrations](https://www.dtnext.in/news/national/a-night-of-celebrations-in-cricket-crazy-india-after-t20-wc-win-792588)

**Cultural bias**
- [The Spectator: "How the West discovered meditation"](https://www.spectator.com.au/?p=10846154)
- [Elle India: dupatta / "Scandinavian scarf" appropriation piece](https://elle.in/fashion/when-a-dupatta-becomes-a-scandinavian-scarf-a-case-of-fashion-appropriation-again-9046074)
- [Aureus Boutique: "From Dupattas to Jhumkas" — the rebranding pattern](https://www.aureusboutique.com/blogs/articles/from-dupattas-to-jhumkas-how-fashion-keeps-rebranding-cultural-heritage)
