# Starter Paper AST and BioSample Classification

This document classifies the 9 starter papers in `data/starter` by:
1. Location of AST data (main text XML, PDF only, supplementary files, or combinations).
2. Association with BioSample accessions (direct single table vs multi-table mapping vs none).
3. Measurement type (quantitative MIC values vs qualitative SIR interpretations).

## Classification Table

| PMID | Title | First Author | Year | AST Location | BioSample Linkage | Details |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| [27381390](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/27381390) | Whole-Genome Sequencing for Detecting Antimicrobial Resistance in Nontyphoidal Salmonella | McDermott, P. | 2016 | `supplement` | `multi_table` | Isolate-level qualitative resistance profiles (SIR) in supplements zac009165488sd1.xlsx (Table S1) and zac009165488sd2.xlsx (Table S2). Main text Table 1 has summary concordance only. Links via GenBank WGS nucleotide accessions (e.g. JYTM00000000) and CVM/CDC IDs; secondary lookup needed for BioSamples. |
| [29678910](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/29678910) | Serotype Diversity and Antimicrobial Resistance among Salmonella enterica Isolates from Patients with Diarrhea | Leon, I. | 2018 | `supplement` | `multi_table` | Negative control. Main text contains narrative prose and aggregate resistance percentages. Supplementary PDF (AEM.02829-17_zam012188570s1.pdf) Tables S4-S6 and Fig S4 list qualitative resistance patterns for 36 resistant isolates; no tabular per-isolate quantitative MIC. Mentions BioProject PRJNA434253; secondary lookup needed for BioSamples. |
| [31266463](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/31266463) | Determining antimicrobial susceptibility in Salmonella enterica serovar Typhimurium through whole genome sequencing | Mensah, N. | 2019 | `supplement` | `multi_table` | Quantitative broth/agar MICs and disk zones in supplement 12866_2019_1520_MOESM1_ESM.xlsx (Table S2). Main text Tables 1-3 report aggregate sensitivity/specificity. Table S2 uses internal isolate codes; Table S3 maps isolate codes to SRA run IDs (ERR numbers); secondary lookup required for BioSamples. |
| [34515028](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/34515028) | Multiple introductions of multidrug-resistant typhoid associated with acute international travel | Kariuki, S. | 2021 | `supplement` | `multi_table` | Disk diffusion zone diameters (mm) and qualitative SIR interpretations in supplement elife-67852-supp1.xlsx (Supplementary Table 1). Main text Tables 1-4 give epidemiological summaries. Supplement lists ERR run accessions; secondary lookup needed for BioSamples. |
| [34907895](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/34907895) | Genomic diversity of antimicrobial resistance in non-typhoidal Salmonella | Sia, C. | 2022 | `supplement` | `direct` | Qualitative disk/agar SIR determinations in supplement Supplementary Tables.xlsx / mgen-7-0725-s003.xlsx (Supplementary Table S1); no quantitative MICs. Directly includes BioSample accessions (SAMN numbers) in the same table row alongside isolate IDs and AST calls. |
| [35651495](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/35651495) | Whole Genome Sequencing, Antibiotic Resistance, and Epidemiology Features of Nontyphoidal Salmonella | Zhao, W. | 2022 | `supplement` | `direct` | Both quantitative MIC values and qualitative SIR calls across 13 antibiotics in supplement Table_3.XLSX. Main text Table 2 reports aggregate resistance percentages. Directly includes BioSample accessions (SAMN numbers) in the AST data table. |
| [37316492](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/37316492) | A global genomic analysis of Salmonella Concord reveals lineages with high antimicrobial resistance | Cuypers, W. | 2023 | `supplement` | `multi_table` | Quantitative Sensititre broth microdilution MICs in supplement 41467_2023_38902_MOESM5_ESM.xlsx (sheet sensititre). Main text Table 1 lists AMR gene distributions. Sensititre sheet uses sequencing_id / sample_id_lab; BioSample accessions (ERS/SAMEA) and SRA run accessions (ERR) require joining with separate supplement 41467_2023_38902_MOESM4_ESM.csv. |
| [40867962](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/40867962) | Resistance Response and Regulatory Mechanisms of Ciprofloxacin-Induced Resistant Salmonella enterica Serovar Enteritidis | Yang, X. | 2024 | `xml_text` | `multi_table` | Quantitative MIC values and SIR calls for strains M and H1 across 21 drugs in main-text Table 1 (fulltext.xml and PDF). No supplement tables. Strains M and H1 map to BioProject PRJNA851351 in text; secondary lookup needed for BioSamples. |
| [42587319](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/42587319) | WaaL-WaaP receptor cross-talk drives phage-induced collateral sensitivity to colistin in Salmonella Pullorum | Wang, M. | 2025 | `xml_text` | `none` | Quantitative MIC values across 16 antibiotics for 8 strains in main-text Table 2 (fulltext.xml and PDF). No BioSample accessions exist for the bacterial strains in the paper or public repositories (accessions in paper PV208391.1 and PX021923.1 are for phages only). |

## Paper Summaries

### PMID [27381390](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/27381390): Whole-Genome Sequencing for Detecting Antimicrobial Resistance in Nontyphoidal Salmonella

- **First Author**: McDermott, P.
- **Year**: 2016
- **AST Location**: `supplement`
- **BioSample Linkage**: `multi_table`
- **Findings**: Isolate-level qualitative resistance profiles (SIR) in supplements zac009165488sd1.xlsx (Table S1) and zac009165488sd2.xlsx (Table S2). Main text Table 1 has summary concordance only. Links via GenBank WGS nucleotide accessions (e.g. JYTM00000000) and CVM/CDC IDs; secondary lookup needed for BioSamples.

### PMID [29678910](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/29678910): Serotype Diversity and Antimicrobial Resistance among Salmonella enterica Isolates from Patients with Diarrhea

- **First Author**: Leon, I.
- **Year**: 2018
- **AST Location**: `supplement`
- **BioSample Linkage**: `multi_table`
- **Findings**: Negative control. Main text contains narrative prose and aggregate resistance percentages. Supplementary PDF (AEM.02829-17_zam012188570s1.pdf) Tables S4-S6 and Fig S4 list qualitative resistance patterns for 36 resistant isolates; no tabular per-isolate quantitative MIC. Mentions BioProject PRJNA434253; secondary lookup needed for BioSamples.

### PMID [31266463](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/31266463): Determining antimicrobial susceptibility in Salmonella enterica serovar Typhimurium through whole genome sequencing

- **First Author**: Mensah, N.
- **Year**: 2019
- **AST Location**: `supplement`
- **BioSample Linkage**: `multi_table`
- **Findings**: Quantitative broth/agar MICs and disk zones in supplement 12866_2019_1520_MOESM1_ESM.xlsx (Table S2). Main text Tables 1-3 report aggregate sensitivity/specificity. Table S2 uses internal isolate codes; Table S3 maps isolate codes to SRA run IDs (ERR numbers); secondary lookup required for BioSamples.

### PMID [34515028](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/34515028): Multiple introductions of multidrug-resistant typhoid associated with acute international travel

- **First Author**: Kariuki, S.
- **Year**: 2021
- **AST Location**: `supplement`
- **BioSample Linkage**: `multi_table`
- **Findings**: Disk diffusion zone diameters (mm) and qualitative SIR interpretations in supplement elife-67852-supp1.xlsx (Supplementary Table 1). Main text Tables 1-4 give epidemiological summaries. Supplement lists ERR run accessions; secondary lookup needed for BioSamples.

### PMID [34907895](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/34907895): Genomic diversity of antimicrobial resistance in non-typhoidal Salmonella

- **First Author**: Sia, C.
- **Year**: 2022
- **AST Location**: `supplement`
- **BioSample Linkage**: `direct`
- **Findings**: Qualitative disk/agar SIR determinations in supplement Supplementary Tables.xlsx / mgen-7-0725-s003.xlsx (Supplementary Table S1); no quantitative MICs. Directly includes BioSample accessions (SAMN numbers) in the same table row alongside isolate IDs and AST calls.

### PMID [35651495](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/35651495): Whole Genome Sequencing, Antibiotic Resistance, and Epidemiology Features of Nontyphoidal Salmonella

- **First Author**: Zhao, W.
- **Year**: 2022
- **AST Location**: `supplement`
- **BioSample Linkage**: `direct`
- **Findings**: Both quantitative MIC values and qualitative SIR calls across 13 antibiotics in supplement Table_3.XLSX. Main text Table 2 reports aggregate resistance percentages. Directly includes BioSample accessions (SAMN numbers) in the AST data table.

### PMID [37316492](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/37316492): A global genomic analysis of Salmonella Concord reveals lineages with high antimicrobial resistance

- **First Author**: Cuypers, W.
- **Year**: 2023
- **AST Location**: `supplement`
- **BioSample Linkage**: `multi_table`
- **Findings**: Quantitative Sensititre broth microdilution MICs in supplement 41467_2023_38902_MOESM5_ESM.xlsx (sheet sensititre). Main text Table 1 lists AMR gene distributions. Sensititre sheet uses sequencing_id / sample_id_lab; BioSample accessions (ERS/SAMEA) and SRA run accessions (ERR) require joining with separate supplement 41467_2023_38902_MOESM4_ESM.csv.

### PMID [40867962](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/40867962): Resistance Response and Regulatory Mechanisms of Ciprofloxacin-Induced Resistant Salmonella enterica Serovar Enteritidis

- **First Author**: Yang, X.
- **Year**: 2024
- **AST Location**: `xml_text`
- **BioSample Linkage**: `multi_table`
- **Findings**: Quantitative MIC values and SIR calls for strains M and H1 across 21 drugs in main-text Table 1 (fulltext.xml and PDF). No supplement tables. Strains M and H1 map to BioProject PRJNA851351 in text; secondary lookup needed for BioSamples.

### PMID [42587319](file:///Users/aprasad/dev/amr-evidence-extraction/data/starter/42587319): WaaL-WaaP receptor cross-talk drives phage-induced collateral sensitivity to colistin in Salmonella Pullorum

- **First Author**: Wang, M.
- **Year**: 2025
- **AST Location**: `xml_text`
- **BioSample Linkage**: `none`
- **Findings**: Quantitative MIC values across 16 antibiotics for 8 strains in main-text Table 2 (fulltext.xml and PDF). No BioSample accessions exist for the bacterial strains in the paper or public repositories (accessions in paper PV208391.1 and PX021923.1 are for phages only).

