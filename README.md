
<div align="center">

# ⚡ Inciflow

### *From Issue Chaos to Actionable Resolution.*

**Inciflow** is an AI-powered, agentic issue-management workflow that transforms GitHub issues into structured, actionable engineering tasks. It combines automated triage, AI-driven classification, evidence-based resolution planning, and **Human-in-the-Loop (HITL)** validation to reduce repetitive manual work while keeping engineers in control.

<p>
  <img src="https://img.shields.io/badge/Project-Agentic%20AI-7C3AED?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Automation-n8n-EA4B71?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Integration-GitHub-181717?style=for-the-badge&logo=github&logoColor=white" />
  <img src="https://img.shields.io/badge/AI-LLM%20Powered-2563EB?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Human%20Review-HITL-228B22?style=for-the-badge" />
</p>

<p>
  <img src="https://img.shields.io/badge/Workflow-AI%20Orchestrated-0F766E?style=flat-square" />
  <img src="https://img.shields.io/badge/Tracking-Google%20Sheets-34A853?style=flat-square&logo=googlesheets&logoColor=white" />
  <img src="https://img.shields.io/badge/Language-Python-3776AB?style=flat-square&logo=python&logoColor=white" />
</p>

### 🧠 Understand the issue. Find the evidence. Plan the resolution.

**AI recommends → Human validates → Authorized workflow acts.**

</div>

---

# 🚨 The Problem

Software teams receive a continuous stream of GitHub issues, including bugs, feature requests, performance problems, configuration errors, and incomplete reports.

Before an issue becomes actionable, someone often needs to:

- Read and interpret the issue.
- Determine its category, severity, and priority.
- Search for related issues and existing context.
- Identify possible causes and investigation steps.
- Document recommendations.
- Update issue labels, status, or assignments.

This repetitive process creates triage overhead, delays engineering work, and can lead to inconsistent prioritization.

## 💡 The Solution

**Inciflow introduces an AI-assisted triage and resolution-planning layer between GitHub and engineering teams.**

Using n8n to orchestrate APIs, LLM-powered analysis, conditional routing, and human review, Inciflow converts incoming issues into structured recommendations that engineers can review and act upon.

The goal is not to replace developers or autonomously modify code. It is to reduce the manual effort required to understand, prioritize, and prepare issues for resolution.

---

# ✨ Features

### 🔄 Automated Issue Intake
Receive supported GitHub issue events and retrieve the relevant issue metadata through the GitHub REST API.

### 🧹 Validation & Deduplication
Normalize issue data, validate required fields, and prevent duplicate processing from creating redundant records.

### 🏷️ AI-Powered Classification
Analyze issue descriptions and recommend categories such as bugs, feature requests, performance, security, documentation, and configuration.

### 🎯 Severity & Priority Recommendations
Evaluate available context and explain why an issue may require attention. Keep severity distinct from priority.

### 🔎 Context & Evidence Gathering
Use available issue descriptions, comments, labels, and related-issue references to provide additional context for analysis.

### 🧠 Agentic Resolution Planning
Generate potential root-cause hypotheses, supporting evidence, investigation steps, recommended next actions, and requests for missing information.

### 👤 Human-in-the-Loop Validation
Allow authorized reviewers to approve, edit, reject, or request more information before consequential actions proceed.

### 🔗 Controlled GitHub Actions
Support approved issue updates, such as adding labels, posting triage summaries, or assigning issues, according to configured permissions.

### 📊 Operational Tracking
Record issue recommendations, review decisions, processing status, timestamps, and outcomes in Google Sheets.

### 🛡️ Reliability & Error Handling
Validate AI outputs, handle API failures, record errors, and route uncertain recommendations for human review.

---

# 🚀 Why Inciflow?

Traditional issue automation often follows a fixed sequence of rules.

Inciflow adds AI-assisted interpretation and planning to that sequence.

| Traditional Issue Handling | Inciflow |
|---|---|
| Manual issue interpretation | AI-assisted classification |
| Inconsistent prioritization | Structured priority recommendations |
| Manual context gathering | Context and evidence retrieval |
| Unstructured investigation notes | Actionable resolution plans |
| Manual tracking | Structured workflow records |
| Unreviewed AI actions are risky | Human approval before authorized actions |

The central principle is simple:

> **Turn incoming issues into evidence-backed, reviewable engineering actions—not just another list of tickets.**

---

# 🔄 End-to-End Workflow

```text
                 ┌─────────────────────────┐
                 │         GitHub          │
                 │ Issues & Metadata       │
                 └────────────┬────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │      n8n Trigger         │
                 │ Webhook / GitHub Event   │
                 └────────────┬────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │ Validate & Normalize    │
                 │ Deduplicate Events      │
                 └────────────┬────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │     LLM Analysis        │
                 │ Classification           │
                 │ Severity & Priority      │
                 └────────────┬────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │ Evidence Gathering      │
                 │ Comments & Related Data │
                 └────────────┬────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │ Resolution Planning     │
                 │ Hypotheses & Next Steps │
                 └────────────┬────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │ Google Sheets           │
                 │ Pending Review Record   │
                 └────────────┬────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │ HUMAN-IN-THE-LOOP       │
                 │ Approve / Edit / Reject │
                 └────────────┬────────────┘
                              │
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
              APPROVE        EDIT         REJECT
                 │            │            │
                 │            ▼            ▼
                 │       Re-evaluate    Log Decision
                 │            │
                 └────────────┤
                              ▼
                 ┌─────────────────────────┐
                 │ Approved GitHub Actions│
                 │ Verify & Record Outcome│
                 └────────────┬────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │ Performance Evaluation  │
                 └─────────────────────────┘
```

---

# 🧠 How the AI Reasoning Works

Inciflow separates issue understanding from resolution planning.

### 1. Understand
Interpret the issue title, description, labels, and available context.

### 2. Classify
Recommend an issue category and explain the classification.

### 3. Assess
Evaluate potential severity and priority using available impact signals.

### 4. Gather Evidence
Retrieve relevant issue context before proposing potential causes.

### 5. Plan
Generate hypotheses, investigation steps, and recommended next actions.

### 6. Validate
Present the recommendation to a human reviewer.

### 7. Execute
Perform only the GitHub actions permitted by the approval policy.

### 8. Evaluate
Record corrections, execution outcomes, and operational metrics.

**Important:** Potential root causes remain hypotheses until verified. AI-generated confidence values are estimates and should not be treated as calibrated probabilities without evaluation.

---

# 👤 Human-in-the-Loop (HITL)

Human oversight is a core design principle of Inciflow.

Before configured GitHub changes are executed, a reviewer can choose one of four outcomes.

| Decision | Workflow Behavior |
|---|---|
| ✅ Approve | Continue with the authorized action |
| ✏️ Edit | Apply the reviewed changes before proceeding |
| ❌ Reject | Record the decision and stop the proposed action |
| 🔎 Request Information | Seek clarification or reassess with additional context |

This approach helps reduce the risk of incorrect classification, unsupported root-cause claims, and unintended issue updates.

> **AI proposes. Humans decide. The workflow enforces the decision.**

---

# 🏗 Architecture

```text
                        GitHub
                           │
                           ▼
                    GitHub REST API
                           │
                           ▼
                    n8n Orchestrator
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Validation    LLM Analysis   Deduplication
              │            │
              │            ▼
              │      Evidence Gathering
              │            │
              │            ▼
              │      Resolution Planning
              │            │
              └────────────┤
                           ▼
                    Structured Output
                           │
                ┌──────────┴──────────┐
                ▼                     ▼
          Google Sheets          Human Review
                ▲                     │
                │                     ▼
                └──────────── Approved Actions
                                      │
                                      ▼
                              GitHub Updates
                                      │
                                      ▼
                              Outcome Tracking
```

### Architectural Principles

- **Deterministic validation:** Use explicit rules for required fields, routing, and action checks.
- **Structured AI output:** Validate model responses before downstream processing.
- **Evidence-aware planning:** Separate retrieved facts from generated hypotheses.
- **Least-privilege access:** Grant integrations only the permissions they require.
- **Human authorization:** Gate consequential actions behind the configured approval process.
- **Traceability:** Record recommendations, decisions, and execution outcomes.

---

# 📊 Evaluation & Success Metrics

Inciflow should be evaluated against a documented manual-triage baseline.

| Metric | Purpose |
|---|---|
| Median time to initial triage | Measure triage efficiency |
| Classification accuracy | Compare AI classifications with reviewed labels |
| Priority agreement | Measure agreement with human decisions |
| Human correction rate | Identify recommendations requiring edits |
| Rejection rate | Assess recommendation quality |
| Evidence coverage | Measure the presence of useful evidence references |
| Workflow completion rate | Track successful processing |
| Action verification rate | Confirm that approved actions reached the intended state |

### Initial Evaluation Goals

- **500+ issues:** Proposed test-set scale.
- **30% lower triage time:** Proposed improvement target.

These figures are goals, not achieved results unless verified by a repeatable benchmark. Actual outcomes should include the baseline, sample size, and measurement method.

---

# 🛡️ Reliability & Security

Inciflow should handle failures explicitly rather than assuming that every workflow step succeeds.

- Validate incoming issue data.
- Deduplicate repeated events.
- Validate LLM responses against an expected schema.
- Apply bounded retries for transient API failures.
- Route uncertain or malformed outputs for human review.
- Record failed GitHub actions instead of marking them successful.
- Treat issue descriptions and comments as untrusted input.
- Restrict GitHub credentials to the required permissions.
- Store secrets in n8n credentials or an appropriate secrets manager.
- Never commit API keys, access tokens, or private credentials.

---

# ⚙️ Getting Started

## Prerequisites

- An n8n instance (cloud or self-hosted).
- A GitHub repository with the required issue permissions.
- An LLM provider and API credentials supported by the configured workflow.
- Google Sheets credentials if spreadsheet tracking is enabled.
- Python 3.x only if custom Python code or a Python service is included.

## 1️⃣ Clone the Repository

```bash
git clone https://github.com/<your-username>/Inciflow.git
cd Inciflow
```

Replace `<your-username>` with your GitHub username and update the repository URL if necessary.

## 2️⃣ Import the Workflow

1. Open your n8n instance.
2. Import the workflow JSON file, if included in the repository.
3. Review the trigger, API endpoints, node settings, data mappings, and error branches.
4. Connect the required credentials through n8n's credential manager.
5. Replace example identifiers and placeholders with your own configuration.
6. Test the workflow with a non-production repository.

## 3️⃣ Configure Integrations

Configure the credentials for the integrations actually used:

- GitHub
- LLM provider
- Google Sheets

Use environment-specific configuration and secure credential storage. Do not hardcode secrets in workflow nodes or commit them to GitHub.

## 4️⃣ Test the Workflow

Verify that:

- GitHub events trigger the intended workflow.
- Issue data is retrieved and normalized correctly.
- Duplicate events do not create duplicate records.
- AI output follows the expected schema.
- Evidence references are valid.
- Google Sheets records are written correctly.
- Human decisions follow the correct branch.
- GitHub updates occur only after the required approval.
- Failed actions are logged and handled safely.

## 5️⃣ Activate the Workflow

Activate the workflow only after credentials, permissions, test cases, and failure-handling paths have been reviewed.

> The exact setup commands and configuration depend on the actual workflow files in this repository. No Node.js application or separate Python server is assumed by this README.

---

# 📂 Suggested Project Structure

```text
Inciflow/
├── README.md
├── workflows/
│   └── inciflow_issue_management.json
├── src/
│   └── validation.py
├── tests/
│   ├── test_validation.py
│   └── test_workflow_cases.md
├── docs/
│   ├── architecture.md
│   └── evaluation.md
├── .env.example
└── .gitignore
```

*This is a suggested structure. Keep only files and directories that exist in the actual repository.*

---

# 🧪 Testing Scenarios

A robust evaluation should include:

- A complete bug report.
- A feature request without labels.
- An incomplete or ambiguous issue.
- A duplicate webhook event.
- A malformed LLM response.
- Conflicting evidence.
- A high-impact issue requiring escalation.
- An edited or rejected recommendation.
- A GitHub API rate limit or failure.
- A human-review timeout.
- Untrusted instructions embedded in an issue description.

These scenarios help test both the AI's recommendation quality and the reliability of the surrounding workflow.

---

<div align="center">

## ⚡ Inciflow

### *Less time triaging. More time solving.*

**AI-assisted issue management with human accountability.**

⭐ If you find the project interesting, consider giving the repository a star!

</div>
