# arXiv Submission — Three Articles for CCS 2026 Reviewer Onboarding

## Purpose

CCS 2026 Cycle B reviewer onboarding requires linking up to 5 recent publications in the HotCRP profile. These three articles provide strong linkable publications. Combined with the AVE Database, you'll have 4 out of 5 slots filled.

---

## Article 1: arXiv Preprint (Paper 6 — Taxonomy TR)

**Title:** A Taxonomy of 13 Agentic Pathologies: Empirical Evidence from 31 Experiments Across 5 Model Families with Quantum-Classical Hybrid Defenses

**File:** `Paper6_Pathology_Taxonomy_TR.md` → convert to LaTeX for arXiv submission

### arXiv Submission Details

| Field | Value |
|-------|-------|
| **Primary category** | `cs.CR` (Cryptography and Security) |
| **Cross-list** | `cs.AI`, `cs.MA`, `cs.LG` |
| **License** | arXiv non-exclusive license (perpetual) |
| **Comments** | Technical report, 15 pages, 8 tables, 13 references |
| **ACM classes** | K.6.5 (Security and Protection), I.2.11 (Distributed AI — Multiagent Systems) |
| **MSC classes** | 68T42 (Agent technology), 68M25 (Security) |
| **Journal-ref** | (leave blank — submit to JAIR later) |

---

## Article 2: arXiv Preprint (Paper 1 — Confused Deputy)

**Title:** The Confused Deputy Revisited: Universal Tool-Trust Exploitation in Frontier LLM Agents

**File:** `Paper1_Confused_Deputy.md` → convert to LaTeX for arXiv submission

### arXiv Submission Details

| Field | Value |
|-------|-------|
| **Primary category** | `cs.CR` (Cryptography and Security) |
| **Cross-list** | `cs.AI`, `cs.CL` |
| **License** | arXiv non-exclusive license (perpetual) |
| **Comments** | 16 pages, 7 tables, cross-model study, CCS 2026 Cycle B submission |
| **ACM classes** | K.6.5 (Security and Protection), D.4.6 (Security and Protection — Access Controls) |
| **MSC classes** | 68T42 (Agent technology), 68M25 (Security) |
| **Journal-ref** | (leave blank) |

### CCS Profile Usage

```
Dillman Leigh. "The Confused Deputy Revisited: Universal Tool-Trust Exploitation in Frontier LLM Agents." arXiv preprint arXiv:2604.XXXXX, April 2026.
```

---

## Article 3: arXiv Preprint (Paper 5 — Epistemic Contagion)

**Title:** Epistemic Contagion in Multi-Agent LLM Systems: 100% Transmission Rates, Self-Validating Audit Failures, and a Content Firewall Defense Achieving 90% R₀ Reduction

**File:** `Paper5_Epistemic_Contagion.md` → convert to LaTeX for arXiv submission

### arXiv Submission Details

| Field | Value |
|-------|-------|
| **Primary category** | `cs.CR` (Cryptography and Security) |
| **Cross-list** | `cs.MA`, `cs.AI`, `cs.SI` |
| **License** | arXiv non-exclusive license (perpetual) |
| **Comments** | 14 pages, 6 tables, epidemic modeling of AI belief propagation, CCS 2026 Cycle B submission |
| **ACM classes** | K.6.5 (Security and Protection), I.2.11 (Distributed AI — Multiagent Systems) |
| **MSC classes** | 68T42 (Agent technology), 92D30 (Epidemiology) |
| **Journal-ref** | (leave blank) |

### CCS Profile Usage

```
Dillman Leigh. "Epistemic Contagion in Multi-Agent LLM Systems: 100% Transmission Rates, Self-Validating Audit Failures, and a Content Firewall Defense." arXiv preprint arXiv:2604.XXXXX, April 2026.
```

---

## Article 4: GitHub Citeable Dataset (AVE Database)

**Title:** AVE Database: Agentic Vulnerabilities & Exposures — A Structured Catalogue of 36 AI Agent Failure Modes

**Repository:** https://github.com/NAIL-INSTITUTE-FOR-AGENTIC-SECURITY/ave-database

### Steps to Make Citeable

1. Push `CITATION.cff` to the repo (already created)
2. Create a **GitHub Release** (tag: `v1.0.0`, title: `AVE Database v1.0 — 36 Vulnerability Cards`)
3. **Optional but recommended:** Create a Zenodo DOI
   - Go to https://zenodo.org
   - Link your GitHub account
   - Enable the `ave-database` repo
   - Create the release → Zenodo automatically archives it and mints a DOI
   - DOI looks like: `10.5281/zenodo.XXXXXXX`
   - URL: `https://doi.org/10.5281/zenodo.XXXXXXX`

### CCS Profile Usage

In HotCRP → Profile → Recent Publications, enter:
```
Dillman Leigh. "AVE Database: Agentic Vulnerabilities & Exposures — A Structured Catalogue of 36 AI Agent Failure Modes." NAIL Institute, 2026. https://doi.org/10.5281/zenodo.XXXXXXX
```

If no Zenodo DOI, use the GitHub URL:
```
Dillman Leigh. "AVE Database: Agentic Vulnerabilities & Exposures." NAIL Institute, 2026. https://github.com/NAIL-INSTITUTE-FOR-AGENTIC-SECURITY/ave-database
```

---

## Timeline

| Step | Action | Time Required |
|------|--------|--------------|
| 1 | Register ORCID at https://orcid.org | 5 minutes |
| 2 | Push CITATION.cff to ave-database repo | 2 minutes |
| 3 | Create GitHub Release v1.0.0 for ave-database | 5 minutes |
| 4 | (Optional) Link to Zenodo for DOI | 10 minutes |
| 5 | Convert Papers 1, 5, 6 to PDF (pandoc or LaTeX) | 45 minutes |
| 6 | Submit all three to arXiv (one submission flow each) | 30 minutes |
| 7 | Wait for arXiv to process | 24-48 hours |
| 8 | Write 3 blog posts for nailinstitute.org | 2 hours |
| 9 | Enter all 4 publications in CCS HotCRP profile | 10 minutes |

**Total active time: ~3.5 hours. Allow 48 hours for arXiv processing.**

**Deadline: CCS Cycle B abstract submission opens April 22, 2026.**

---

## arXiv Submission Steps (Same for All Three Papers)

1. Go to https://arxiv.org/submit
2. Select **New Submission**
3. Upload LaTeX source (or PDF generated from Markdown)
4. Fill metadata per article tables above
5. Author: `Dillman Leigh` (add ORCID once registered)
6. Affiliation: `NAIL Institute, Neuravant AI Limited`
7. Submit → paper appears within 24-48 hours
8. Copy the arXiv URL (e.g., `https://arxiv.org/abs/2604.XXXXX`)

**Note:** You can submit all three papers in one session. arXiv processes them independently. Each gets its own unique ID.

---

## CCS HotCRP Profile — All 4 Publications

In HotCRP → Profile → Recent Publications, enter:

```
1. Dillman Leigh. "A Taxonomy of 13 Agentic Pathologies: Empirical Evidence from 31 Experiments Across 5 Model Families with Quantum-Classical Hybrid Defenses." arXiv preprint arXiv:2604.XXXXX, April 2026.

2. Dillman Leigh. "The Confused Deputy Revisited: Universal Tool-Trust Exploitation in Frontier LLM Agents." arXiv preprint arXiv:2604.XXXXX, April 2026.

3. Dillman Leigh. "Epistemic Contagion in Multi-Agent LLM Systems: 100% Transmission Rates, Self-Validating Audit Failures, and a Content Firewall Defense." arXiv preprint arXiv:2604.XXXXX, April 2026.

4. Dillman Leigh. "AVE Database: Agentic Vulnerabilities & Exposures." NAIL Institute, 2026. https://github.com/NAIL-INSTITUTE-FOR-AGENTIC-SECURITY/ave-database
```

This fills 4 of 5 slots. Slot 5 can be filled later with Paper 2 or Paper 4 arXiv preprints when posted for NeurIPS.

---

## nailinstitute.org Blog Posts

For each blog post, use this structure:

1. **Alarming hook** (1-2 sentences, accessible language)
2. **Key finding** (3-4 bullet points with numbers)
3. **Why it matters** (for practitioners, not academics)
4. **What we built** (defense/tool/database — link to GitHub)
5. **Read the full paper** → link to arXiv
6. **Explore the AVE Database** → link to GitHub

Blog posts do NOT conflict with any venue's policies. ACM, NeurIPS, USENIX, IEEE all explicitly allow preprints, blog posts, and institutional reports. Only simultaneous submission to another peer-reviewed venue is prohibited.

---

## Quick Reference: arXiv Markdown → PDF

```bash
# Using pandoc (install: sudo apt install pandoc texlive-full)
pandoc Paper6_Pathology_Taxonomy_TR.md -o Paper6_Taxonomy_TR.pdf \
  --pdf-engine=xelatex \
  -V geometry:margin=1in \
  -V fontsize=11pt \
  --number-sections

# Or for arXiv LaTeX format:
pandoc Paper6_Pathology_Taxonomy_TR.md -o Paper6_Taxonomy_TR.tex \
  --standalone \
  -V documentclass=article \
  -V geometry:margin=1in
```
