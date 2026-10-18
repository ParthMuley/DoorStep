# Doorstep Post-Calamity Agent (DEMO)

**Simulation only. Fictional recovery organizations. Never files claims or applications; never promises housing.**

After a resident's simulated arrival, and only with their consent, asks the Doorstep backend to match recovery organizations by help type (temporary housing, insurance guidance, supplies, medical-equipment replacement) and sends each matched organization's agent only the minimal, consent-scoped referral. Reports each referral as requested, accepted, unresolved, or completed (completed only with evidence). "Housing secured" is never claimed from a referral alone.

Messages: `RecoveryRequest` → `RecoveryResponse`; `ReferralRequest/Response` with organization agents (schema 2.0).
