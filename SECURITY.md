# Security Policy

## Reporting a Vulnerability

The AVE Database catalogues agentic AI vulnerabilities — which means some submissions may describe findings that could be weaponized against production systems.

### For Severe / Weaponizable Findings

If you discover a vulnerability that could enable **immediate exploitation** of deployed AI agent systems, please:

1. **DO NOT** submit it as a public GitHub Issue
2. **DO** use one of these channels:
   - 📧 Email: **security@nailinstitute.org** (PGP key available on request)
   - 🔒 GitHub: [Private Disclosure template](https://github.com/dleighsystem/nailinstitute/issues/new?template=private-disclosure.yml)

### What Qualifies as "Severe"

- Active exploit chains against production AI agent frameworks (LangChain, CrewAI, AutoGen, etc.)
- Credential harvesting techniques that work against real deployments
- Remote code execution via agent tool chains
- Cross-tenant data exfiltration in multi-agent platforms
- Any finding that could cause **immediate harm** if publicly disclosed

### What Can Be Publicly Submitted

- Behavioural failure modes (deadlocks, drift, sycophancy, resource waste)
- Theoretical attack paths with described mechanisms
- Demonstrated exploits against **local/sandboxed** test environments
- Defences and mitigations for existing AVE cards

## Responsible Disclosure Timeline

| Day | Action |
|-----|--------|
| 0 | Researcher reports via private channel |
| 2 | NAIL acknowledges receipt, assigns reviewer |
| 7 | NAIL confirms validity and assigns embargoed AVE ID |
| 14 | NAIL notifies affected framework maintainers (if applicable) |
| 30 | Coordinate on mitigation timeline |
| 90 | Public disclosure (or earlier if fix is deployed and researcher agrees) |

### Extensions

The 90-day window may be extended if:
- A fix is actively being developed and near completion
- The researcher agrees to an extension
- The vulnerability affects critical infrastructure

### Early Disclosure

We support early public disclosure if:
- The vulnerability is already being actively exploited in the wild
- The affected party has been non-responsive for 30+ days
- A fix has been deployed and the researcher wants to publish

## Recognition

Private disclosure reporters receive:
- Credit in the published AVE card (unless anonymity is requested)
- NAIL Research Fellow recognition for critical findings
- Inclusion in our annual security acknowledgements

## Scope

This policy covers:
- The AVE Database and all associated tooling
- The NAIL SDK packages (rmap, ave, canary, arena, ctf, diagnostic, horizon, integration, threatfeed)
- NAIL-operated infrastructure (Canary Fleet, DGX Arena, CTF events)

For vulnerabilities in third-party frameworks (LangChain, CrewAI, etc.), please report directly to those projects. We will help coordinate if the finding involves agentic-specific attack vectors.

---

*This policy is based on industry best practices from [CERT/CC](https://www.sei.cmu.edu/about/divisions/cert/index.cfm) and the [Google Project Zero disclosure policy](https://googleprojectzero.blogspot.com/p/vulnerability-disclosure-policy.html).*
