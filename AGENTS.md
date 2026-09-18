# AI Agent Instructions

If you are an AI coding assistant interacting with this project, please follow these guidelines to understand the architecture, run tests, and maintain code quality.

## Project Overview

This is a codeathon project with the following goals:
- Automate downloading of papers and supplementary materials as much as
  possible
    - Summarize sources of AST data and genomes and see whether it is
      appropriate
- Extract from a paper the MIC values for a drug and species and associate them
  with a sequence identifier.
    - Need to get a table of drug synonyms (abbreviations should be standard,
      but pu lled from paper text because there are some that are used in
      multiple places, e.  g., amoxicillin-clavulanic acid is amx, amc, aug,
      etc.)
- Develop code to do the extraction in an automated fashion when given a paper
  or PMID.
    - Parse paper to find out if AST data is in text or supplement
        - Extract AST data
            - From supplementary data
            - Match up internal identifiers to biosample accessions if
              necessary
            - Final output in correct format
            - Extract for all drugs
- Stretch goal: extract additional metadata associated with the isolate such as
  date of collection, genotype, growth conditions, or phenotyping standard.


## Testing Strategy (IMPORTANT)

This project strictly follows Red/Green TDD

## New feature ceremony

Whenver a prompt asks to implement, build, or add a new feature or data: 

- Interview me relentlessly about every aspect of this until we reach a shared
understanding. Walk down each branch of the decision tree, resolving
dependencies between decisions one-by-one. For each question, provide your
recommended answer.
- Ask the questions one at a time, waiting for feedback on each question before
continuing. Asking multiple questions at once is bewildering.
- If a fact can be found by exploring the environment (filesystem, tools, etc.),
look it up rather than asking me. The decisions, though, are mine — put
each one to me and wait for my answer.

Do not act on it until I confirm we have reached a shared understanding.

## Output

- no em dashes, smart quotes, or Unicode. ASCII only.
- Be concise, If unsure, say so. Never guess. Ask questions.

## Override Rule
User instructions always override this file.
