# Speaker checklist

Event logistics (date, venue, slot) come from the organizers' email; this list only covers the talk itself.

## Content
- [ ] Title + abstract sent to the organizers (`abstract.md`)
- [ ] Slides built from `outline.md` (13 slides, 20 minutes)
- [ ] Slides reviewed for OSS-only content: no commercial products, no customer names, nothing confidential — the session is recorded and livestreamed
- [ ] Repo link and QR code on the first and last slide
- [ ] Rehearsed end to end with a timer at least twice (target 19:30)

## Demo
- [ ] `.env` filled in (ANTHROPIC_API_KEY, OPENAI_API_KEY); never shown on screen
- [ ] `docker compose pull && docker compose build && docker compose up -d` done on the presenting laptop
- [ ] Each live scenario run once with each agent; Grafana dashboard shows decisions
- [ ] Simulator fallback works with Wi-Fi off (`docker compose run --rm simulator --scenario loop`)
- [ ] Phone hotspot ready (live agents need the model API)
- [ ] Backup recording of the demo on the laptop and on USB
- [ ] `demo-runbook.md` printed or on a phone (`demo-runbook-extras.md` only if there is time for Q&A demos)

## Bring
- [ ] Laptop with slides loaded, charger
- [ ] HDMI adapter (the rooms connect via HDMI)
- [ ] USB stick with slides (PDF) + demo recording
- [ ] Physical government photo ID (building access)
