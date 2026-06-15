# PitchForge — Privacy Policy

**Version:** 1.0.0 · **Effective date:** 2026-06-09 · **Previous version:** —

This Privacy Policy explains how **CARGOFFER INVESTMENTS SRL** ("we", "us")
processes your personal data when you use PitchForge (the "Service"). It is
compliant with the **EU General Data Protection Regulation (GDPR) 2016/679**
and the **Spanish LOPDGDD (Organic Law 3/2018)**.

## 1. Data Controller

- **Controller:** CARGOFFER INVESTMENTS SRL
- **CIF:** B16805855
- **Address:** Calle Illas Baleares, 25 5C, 36203 Vigo, Spain
- **Privacy contact:** [email protected]

## 2. Personal Data We Collect

| Category | Examples | Lawful basis (GDPR Art. 6) |
|----------|----------|----------------------------|
| **Account data** | Name, email, password (hashed via Clerk) | Contract (b) |
| **Billing data** | Stripe customer ID, plan, invoices | Contract (b), Legal (c) |
| **Usage data** | Projects, research queries, generated artifacts | Contract (b) |
| **Technical data** | IP address, user agent, timestamps, error logs | Legitimate interest (f) |
| **Cookies** | Per our [Cookie Policy](/legal/cookies) | Consent (a) for non-essential |
| **Communications** | Support emails, surveys | Consent (a) / Legitimate interest (f) |
| **API key data** | Key name, prefix (last 4), last used timestamp | Contract (b) |

We do **not** knowingly collect data from children under 16.

## 3. How We Use Your Data

We process your personal data to:

1. **Provide the Service** — create projects, run research, generate artifacts.
2. **Authenticate you** — via Clerk (see §7).
3. **Process payments** — via Stripe (see §7).
4. **Communicate** — service announcements, security alerts, billing notices.
5. **Improve the Service** — aggregated, anonymized analytics (only with your
   cookie consent; see [Cookie Policy](/legal/cookies)).
6. **Comply with legal obligations** — tax records (6 years), fraud prevention.

We **do not** sell your data. We **do not** use your projects or prompts to
train third-party AI models.

## 4. Your Rights (GDPR / LOPDGDD)

You may exercise the following rights at any time by emailing
[email protected]:

| Right | Description |
|-------|-------------|
| **Access** | Get a copy of the data we hold about you. |
| **Rectification** | Correct inaccurate or incomplete data. |
| **Erasure** ("right to be forgotten") | Delete your data (with legal exceptions). |
| **Restriction** | Limit how we process your data while a complaint is resolved. |
| **Portability** | Receive your data in a structured, machine-readable format (JSON). |
| **Objection** | Object to processing based on legitimate interest. |
| **Withdraw consent** | For cookies, marketing, or optional features. |

We respond within **30 days** (extendable to 60 days for complex requests,
notifying you of the delay).

## 5. Data Export and Deletion

- **Export:** From Settings → Privacy → "Download my data". We deliver a
  JSON file containing all data we hold about you, within 30 days.
- **Soft delete:** From Settings → Privacy → "Delete account". Your account
  is deactivated immediately; data is **retained for 30 days** in case you
  change your mind (you can cancel the deletion from the login screen).
- **Hard delete:** After 30 days, all personal data is permanently removed
  from production systems. Backups are scrubbed within 90 days. Anonymized
  aggregates (e.g., "X research calls in June") may be retained.

## 6. International Transfers

We primarily store data in the **EU** (MongoDB Atlas region: `eu-west-1`).
Some sub-processors (see §7) are based in the US; we ensure transfers are
covered by **EU Standard Contractual Clauses (SCCs)** and equivalent
safeguards.

## 7. Sub-processors

| Sub-processor | Purpose | Location |
|---------------|---------|----------|
| **Clerk** | Authentication | US (SCC) |
| **Stripe** | Payment processing | US (SCC) |
| **MongoDB Atlas** | Database hosting | EU (Ireland) |
| **Cloudflare** | CDN, security | Global |
| **Anthropic / OpenAI / Perplexity** | LLM inference | US (SCC, no training opt-out) |
| **Resend** | Transactional email | US (SCC) |
| **Backblaze B2** | Encrypted backups | EU (Amsterdam) |

A current list is maintained at <https://pitchforge.io/sub-processors>.

## 8. Data Retention

| Data | Retention |
|------|-----------|
| Account data | Lifetime of account + 30d after deletion |
| Billing records | 6 years (Spanish tax law) |
| Generated artifacts | Lifetime of account, deletable on request |
| Server logs | 90 days |
| Backups | 90 days rolling, encrypted |
| Anonymized analytics | Indefinite |

## 9. Security

We protect your data with:

- TLS 1.3 in transit; AES-256 at rest.
- HSTS, strict CSP, defense-in-depth HTTP headers.
- Two-factor authentication (2FA) for account login (TOTP).
- Role-based access control for staff; least-privilege defaults.
- Annual third-party security review (planned Q4 2026).

If we discover a breach affecting your personal data, we notify you and the
**AEPD** (Spanish Data Protection Authority) within **72 hours**, as required
by GDPR Art. 33.

## 10. Automated Decision-Making

We do **not** use your data for automated decision-making with legal effects
(GDPR Art. 22). LLM-generated outputs are reviewed by you before any
action is taken.

## 11. Changes to this Policy

Material changes are notified at least 30 days in advance. A version history
is maintained in our [Legal changelog](https://github.com/TheBoomer-Channel/pitchforge/blob/main/docs/legal/CHANGELOG.md).

## 12. Complaints

You may lodge a complaint with the **Agencia Española de Protección de Datos
(AEPD)** at <https://www.aepd.es> or with your local supervisory authority.

We would, however, appreciate the chance to address your concerns directly
first — contact [email protected].

## 13. Contact

- **Data Protection:** [email protected]
- **General:** [email protected]
- **Postal:** CARGOFFER INVESTMENTS SRL, Calle Illas Baleares, 25 5C,
  36203 Vigo, Spain
