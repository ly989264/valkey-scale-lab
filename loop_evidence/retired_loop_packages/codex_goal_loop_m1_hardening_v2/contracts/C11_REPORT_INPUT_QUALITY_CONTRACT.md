# C11 Report input quality contract

The Chinese offline report stage must validate its inputs before rendering PASS:

- exact-scale report PASS must cite accepted exact-scale M1 claims;
- no fixture-only source can back milestone report PASS;
- report index must include offline policy;
- report must include setup, command audit, management, workload, fault, system metrics, cleanup, missing metrics sections;
- every chart/table must have a source artifact reference;
- if source claims are blocked, report status may be PASS for rendering but milestone status must remain BLOCKED.
