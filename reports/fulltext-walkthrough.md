# Full-text test walkthrough: VDORA1

Actual API test output; this is a demonstration, not an accuracy benchmark.

Paper: Vitamin D Oral Replacement in Children With Obesity Related Asthma: VDORA1 Randomized Clinical Trial.

Source: https://europepmc.org/articles/PMC10990434

In the dashboard: Run a Review → Read the full paper → select VDORA1 → Read these in full → From the full paper.

## 1. Data tables

Three tables were parsed from the publisher XML. The dashboard shows them under Tables (3).

### Table 1: Participant characteristics

|  | Part 1: Dose finding | Part 2: Dose confirming |  |  |  |  |  |  |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Variables | Cohort A (N = 13) | Cohort B (N = 12) | Cohort C (N = 11) | Cohort D (N = 12) | Total (N = 48) | Cohort E (N = 43) | Cohort F (N = 21) | Total (N = 64) |
| Female, N (%) | 6 (46) | 7 (58) | 5 (45) | 5 (42) | 23 (48) | 20 (47) | 10 (48) | 30 (47) |
| Age, mean ± SD | 12.8 ± 3.1 | 12.3 ± 3.4 | 11.5 ± 3.6 | 12.5 ± 2.9 | 12.3 ± 3.2 | 12.2 ± 2.5 | 11.7 ± 2.6 | 12 ± 2.5 |
| Ethnicity, N (%) |  |  |  |  |  |  |  |  |
| Hispanic | 5 (38) | 2 (17) | 2 (18) | 1 (8) | 10 (21) | 7 (16) | 3 (14) | 10 (16) |
| Non-Hispanic | 7 (54) | 10 (83) | 8 (73) | 10 (83) | 35 (73) | 33 (77) | 18 (86) | 51 (80) |
| Unknown/prefer not to answer | 1 (8) | 0 (0) | 1 (9) | 1 (8) | 3 (6) | 3 (7) | 0 (0) | 3 (5) |
| Race, N (%) |  |  |  |  |  |  |  |  |
| Black or African American | 6 (46) | 4 (33) | 5 (45) | 6 (50) | 21 (44) | 15 (35) | 9 (43) | 24 (38) |
| White | 4 (31) | 5 (42) | 3 (27) | 5 (42) | 17 (35) | 19 (44) | 10 (48) | 29 (45) |
| Other | 3 (23) | 3 (25) | 3 (27) | 1 (8) | 10 (21) | 9 (21) | 2 (10) | 11 (17) |
| RUCAM code, N (%) |  |  |  |  |  |  |  |  |
| Metropolitan | 13 (100) | 10 (83) | 9 (82) | 11 (92) | 43 (90) | 32 (74) | 17 (81) | 49 (77) |
| Non-Metropolitan | 0 (0) | 2 (17) | 2 (18) | 1 (8) | 5 (10) | 11 (26) | 4 (19) | 15 (23) |
| BMI at baseline (visit 2) Mean ± SD | 33.9 ± 8.4 | 29.7 ± 6.4 | 30.1 ± 4.3 | 32.2 ± 9.2 | 31.6 ± 7.4 | 30.8 ± 6.9 | 30.3 ± 8.2 | 30.6 ± 7.3 |
| BMI-percentile, N (%) |  |  |  |  |  |  |  |  |
| ≥ 85th to < 95th | 3 (23) | 2 (17) | 2 (18) | 3 (25) | 10 (21) | 9 (21) | 5 (24) | 14 (22) |
| ≥ 95th to < 99th | 4 (31) | 3 (25) | 2 (18) | 3 (25) | 12 (25) | 16 (37) | 8 (38) | 24 (38) |
| ≥ 99th | 6 (46) | 7 (58) | 7 (64) | 6 (50) | 26 (54) | 18 (42) | 8 (38) | 26 (41) |
| Urine Ca+/Cr ratio >0.37, N (%)a | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 1 (2) | 0 (0) | 1 (2) |

### Table 2: Descriptive statistics and 25(OH) D measurements ≥ 40 ng/mL by study visit

|  | Visit 2 (baseline) | Visit 6 (week 16) | Δ(25(OH) D)a |  |
| --- | --- | --- | --- | --- |
|  |  | Measurements ≥ 40 ng/mL |  |  |
|  | Mean ± SD | Mean ± SD | N (%) with 95% CI | Mean ± SD |
| Part 1: Dose finding |  |  |  |  |
| Cohort A (n = 13) | 18.3 ± 6.5 | 44.3 ± 16.6 | 8 (66.7) [39.1, 86.2] | 23.2 ± 14.2 |
| Cohort B (n = 12) | 20.8 ± 7.2 | 52.9 ± 19.4 | 8 (72.7) [43.4, 90.3] | 31.3 ± 20.1 |
| Cohort C (n = 11) | 19.0 ± 5.2 | 47.4 ± 17.6 | 5 (50.0) [23.7, 76.3] | 27.8 ± 18.9 |
| Cohort D (n = 12) | 17.6 ± 5.8 | 22.4 ± 6.4 | 0 (0) [0, 24.2] | 4.8 ± 4.8 |
| Total (N = 48) | 18.9 ± 6.2 | 41.3 ± 19.2 | 21 (46.7) [32.9, 60.9] | 21.3 ± 18.2 |
| Part 2: Dose confirming |  |  |  |  |
| Cohort E (n = 43) | 17.7 ± 6.0 | 58.4 ± 23.7 | 33 (78.6) [64.1, 88.3] | 40.1 ± 22.9 |
| Cohort F (n = 21) | 16.3 ± 5.2 | 17.8 ± 4.8 | 0 (0) [0, 17.6] | 1.2 ± 6.0 |
| Total (N = 64) | 17.3 ± 5.8 | 46.2 ± 27.4 | 33 (55.0) [42.5, 66.9] | 28.3 ± 26.4 |

### Table 3: Adverse events

|  | AEs N (%) | Related to vitamin D AEs N (%) | Related to procedure AEs N (%) | SAEs N (%) | Related to Vitamin D SAEs N (%) | Related to procedure SAEs N (%) |
| --- | --- | --- | --- | --- | --- | --- |
| Part 1: Dose finding |  |  |  |  |  |  |
| Cohort A (N = 13) | 11 (85) | 0 (0) | 1 (8) | 0 (0) | 0 (0) | 0 (0) |
| Cohort B (N = 12) | 9 (75) | 3 (25) | 0 (0) | 1 (8) | 0 (0) | 0 (0) |
| Cohort C (N = 11) | 11 (100) | 0 (0) | 0 (0) | 1 (9) | 0 (0) | 0 (0) |
| Cohort D (N = 12) | 10 (83) | 0 (0) | 1 (8) | 1 (8) | 0 (0) | 0 (0) |
| Total (N = 48) | 41 (85) | 3 (6) | 2 (4) | 3 (6) | 0 (0) | 0 (0) |
| Part 2: Dose confirming |  |  |  |  |  |  |
| Cohort E (N = 43) | 19 (44) | 1 (2) | 0 | 0 | 0 | 0 |
| Cohort F (N = 21) | 12 (57) | 0 | 1 (5) | 1 (5) | 0 | 0 |
| Total (N = 64) | 31 (48) | 1 (2) | 1 (2) | 1 (2) | 0 | 0 |

## 2. Heat maps

No heat-map image was extracted. The current pipeline does not fetch or interpret figure images. A returned caption does not establish heat-map values.

## 3. Graphs and charts

The source returned one figure, a participant-flow diagram. The dashboard shows its caption and author mentions under Figures (1); it does not show or digitize the image.

Figure 1: Part 2 – Dose confirming phase – Consolidated Standards of Reporting Trials (CONSORT) diagram outlining participant flow. SoC, standard of care.

> For part 2 (dose-confirming), 88 participants were assessed for eligibility and 64 participants were ultimately randomized (Figure 1).

## 4. Statistical results

**Primary Outcome: unverified**

Value withheld; no verified answer to display.

Returned quote (accepted only when status is verified):

> The average 25(OH)D level among participants in cohort E was 58.4 ng/mL compared with 17.8 ng/mL in cohort F. The difference in 25(OH)D at visit 6 (16 weeks) was highly significant with mean difference of 40.5 ng/mL (95% CI: 32.8, 48.2; P < 0.0001). In cohort E, 78.6% of participants (33/42; 95% CI: 64.1%, 88.3%) achieved the target serum 25(OH)D level of ≥ 40 ng/mL, with a mean change in 25(OH)D of 40.1 ± 22.9 ng/mL (Table 2). As expected, the test statistic based on a one-sided z-test was highly significant with P < 0.0001. In contrast, cohort F had no participants that (0/18; 95% CI: 0, 17.6) achieved the target serum 25(OH)D level of ≥ 40 ng/mL, with a mean change in 25(OH)D of 1.2 ± 6.0 ng/mL.

**Effect Size: verified**

40.5 ng/mL

Returned quote (accepted only when status is verified):

> The difference in 25(OH)D at visit 6 (16 weeks) was highly significant with mean difference of 40.5 ng/mL (95% CI: 32.8, 48.2; P < 0.0001).

## 5. Methods

**Statistical Methods: verified**

Two-sided z-test with a significance level of 0.05

Returned quote (accepted only when status is verified):

> using a two-sided z-test with a significance level of 0.05. We report the difference in proportions along with the 95% CI and P value.

**Sample Characteristics: verified**

48 participants were randomized to receive 1 of 4 possible vitamin D dose regimens (Table S1). The mean age was 12.3 years and mean BMI was 31.6 kg/m2, with 54% of participants having a baseline BMI > 99th percentile for age and sex.

Returned quote (accepted only when status is verified):

> During the dose-finding part 1 (dose-finding) of this study, 78 eligible participants were assessed; 25 did not meet inclusion criteria at screening or baseline visit (Figure S1). Four were lost to follow-up and one withdrew consent. Ultimately, 48 participants were randomized to receive 1 of 4 possible vitamin D dose regimens (Table S1). The mean age was 12.3 years and mean BMI was 31.6 kg/m2, with 54% of participants having a baseline BMI > 99th percentile for age and sex.

## 6. Equations and models

Zero displayed equations were parsed from this paper. The dashboard omits the Equations block when the list is empty. General model descriptions are not a dedicated extracted field.

## 7. Supplementary files

Not downloaded or parsed by the current pipeline. References to Table S1 or Figure S1 in the text are not extraction of their underlying files.

## 8. Limitations

**Status: unverified**

The model proposed a limitations sentence that failed source verification. It is withheld. This does not mean the paper contains no limitations.

## Raw output

[API response](../data/fulltext-demo-result.json)

[Parsed source inventory](../data/fulltext-demo-source.json)
