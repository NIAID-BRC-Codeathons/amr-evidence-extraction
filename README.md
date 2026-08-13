# AMR-Evidence Extraction, Integration, and Interoperability

**NIAID-BRCs AI Codeathon 2.0** · September 16–18, 2026 · Argonne National Laboratory

Extracting antimicrobial susceptibility and genotype–phenotype evidence from literature, harmonizing AMR and virulence databases, and combining that evidence with genome-based predictive models.

Project page: https://niaid-brc-codeathons.github.io/projects/amr-evidence-extraction/

---

> **This is a draft pitch, not a plan.**
>
> What follows is a one-slide proposal from the organizing team. It exists
> to seed a team, not to constrain one. Scope, methods, target organism,
> and success criteria are all still open — expect them to change
> substantially. Turning this into a real plan is the team's first job, and
> it lands in the project charter due August 28, 2026.

---

## Goal (proposed)

Extract antimicrobial susceptibility and genotype–phenotype evidence from literature, harmonize AMR and virulence databases, and combine literature-derived knowledge with genome-based predictive models.

## Three-Day MVP (proposed)

Use *Salmonella* and *Staphylococcus aureus* as demonstration organisms. Screen a defined PubMed/PMC corpus, extract AST measurements and genotype associations, normalize drug names and breakpoints, and link the evidence to BV-BRC genomes, AMRFinderPlus entities, CARD, VFDB, and related resources.

A small predictive component could combine literature-derived evidence with BV-BRC genomic features to predict resistance phenotype or rank plausible resistance mechanisms.

## Evaluation (proposed)

Manually curate 75–100 paper passages. Report extraction precision/recall, accession-linking accuracy, prediction F1/AUROC, provenance completeness, and disagreement with current AMR annotations.

## Leads

- Marcus Nguyen
- Arjun Prasad

Team assignments are still being finalized. Participants can review their project, and request a reassignment, in the participant spreadsheet circulated by the organizing team.

## Working here

This repository is the team's working space for the codeathon — code, notebooks, data pointers, and notes. Replace this README with the real thing once the charter is written. Team members get access through the [NIAID-BRC-Codeathons](https://github.com/NIAID-BRC-Codeathons) organization; accept the invitation if you have not already.
