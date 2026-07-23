# fdga-mobile — Claude's Braindump

A scratchpad of my thinking on the FDGA mobile companion app concept, captured
2026-06-23. Not a plan, not a spec — a snapshot of the reasoning so we can
pick up the conversation later. The user is writing a parallel braindump
(`fdga-mobile.vgana.md` or similar); we'll reconcile when we revisit.

---

## The reframe (what we're actually building)

Not a port of `fdex`. `fdex` is an **analyst's** tool — pan the map, switch
plans, toggle overlays. This is a **constituent's** tool — "tell me about my
district and what I can do about it." They share underlying data and almost
nothing else.

Working name: **FDGA Voter Companion**.

The mental shift that unlocks everything: in `fdex` the Mapbox map is the
whole product. Here, the map shrinks to a small widget. The app is ~85%
content (rep info, demographics, election results, FDGA news), ~10% address
→ district lookup, ~5% map widget. That changes the tech math from my
earlier KMP analysis — most of the cross-platform pain goes away when the
map is no longer central.

---

## The voter's mental model (what the app answers in 5 seconds)

1. **"Who represents me?"** — name, photo, party, contact
2. **"What does my district look like?"** — small map, key demographics
3. **"How did my district vote recently?"** — last 2-3 elections, top-line
4. **"What can I do about it?"** — message my rep with FDGA-aligned templates
5. **"What's FDGA doing right now?"** — news / events / current campaign

Every screen should map to one of those questions. Anything that doesn't is
scope creep.

---

## Recommended stack

**PWA first, native shell later via Capacitor.**

Why:
- Svelte 5 toolchain is already in-house (`fdex`, `fdensemble`) — same
  components for charts, drawers, legends carry over.
- Content apps are PWA's sweet spot. Iteration in days, not weeks.
- Shareable URLs are first-class (each district + tab is a deep link with
  OG tags for nice social previews — that's the *whole* shareability story).
- When push notifications, native share sheet, or App Store presence
  actually matter, wrap the same codebase with **Capacitor** → real iOS/Android
  binaries in ~1 week of integration work. No rewrite.

Why **not** KMP / Compose Multiplatform: it shines when you have heavy shared
business logic. A civic info app doesn't — it's mostly UI bound to JSON. The
sharing dividend isn't worth the dual-UI cost.

Why **not** Flutter / React Native: third stack to maintain alongside Svelte
+ Python. Not justified by the marginal performance gain on a content app.

---

## Integrations — piggyback selectively

Use other people's data, keep FDGA's brand and framing:

| Integration | Use for | Why |
|---|---|---|
| **OpenStates API** | GA legislator directory — names, contact, committees, votes, bills | Free, well-maintained, solves the freshness problem. Don't bake rep data into the app. |
| **Mapbox Geocoding API** | Address → lat/lng | Already paid for via `fdex`; reuse the token |
| **Mapbox Static Images API** | District map widget | Cheaper than GL JS for a small thumbnail; no SDK weight |
| **Census Bureau API** | Live demographics for the data tab | Pull rather than bake; reduces sync burden |
| **5 Calls API** | Federal action templates if redistricting-relevant | Don't reinvent the "what to say" copy library |
| **FDGA RSS / JSON manifest** | News feed | Don't build a CMS. Whatever FDGA's website publisher already does → expose as a feed |

What I'd **not** do: become a thin skin over BallotReady, TurboVote, or Vote.org.
You lose the brand and the FDGA-specific framing — which is the whole point.
"Your district was drawn this way; here's what to do about it" is the unique
value. Don't dilute it.

---

## Information architecture (MVP)

```
Home
├── Address entry (or "use my location")
│
├── My District [/d/:chamber/:id]
│   ├── Overview tab        ← small map, name, current rep, top-line stats
│   ├── Representatives tab ← from OpenStates: state house, state senate,
│   │                          congress; tap → call / email / write
│   ├── Demographics tab    ← VAP%, income, education, etc. (from fdp)
│   ├── Elections tab       ← last 2-3 results, partisan lean
│   └── Take Action tab     ← FDGA-aligned message templates with
│                             personalization prompt; share sheet to email/SMS
│
└── FDGA Now
    ├── Current campaign banner
    ├── Recent posts / events
    └── About FDGA / donate / volunteer
```

Each tab is its own URL with OG tags. That's the shareability story —
no clever native magic, just good web hygiene.

---

## Risks worth designing around upfront

### 1. "Contact your rep" can become astroturf
And FDGA's credibility takes the hit if it does. Mitigations:
- **Personalization gate** — minimum character count on top of the template,
  or a required free-text "in your own words" field.
- **Clear FDGA branding** in the message footer so reps know this is
  organized advocacy, not bot spam.
- **Rate limiting** at the device level (one message per rep per topic per
  week, say).
- **Template diversity** — multiple opening lines rotated, not one canned
  paragraph hitting inboxes 10,000 times identically.

### 2. Rep contact data goes stale fast
Resolved by *not* baking it in. OpenStates is the source of truth; the app
queries it. If OpenStates goes down, fall back to a cached snapshot.

### 3. FDGA's content pipeline must be lightweight
Whoever updates the FDGA website is also the content owner for the app. If
publishing to the app requires a separate workflow, it won't get used.
Pull from RSS / a JSON manifest hosted on `fairdistrictsga.org`.

### 4. Scope creep
Every civic app gets the same requests: voter registration check, polling
place finder, ballot preview, candidate guide. Decide what's in/out for v1
and hold the line. My take for v1: in = the five tabs above. Out =
everything else, including registration check.

### 5. "Your district" ambiguity
A Georgia voter is in *three* districts (Congress, State House, State
Senate). The address lookup should resolve all three and let the user
toggle. Don't force them to pick one upfront — that's a confusion bomb.

### 6. Privacy
Address entry should be local-only (geocode in-browser, never log the
address server-side). Make this visible in the UI — civic apps live or die
on trust.

---

## Open questions for the user (don't build until answered)

1. **Who at FDGA owns the content pipeline?** Whoever updates the FDGA
   website/socials is also the content owner for the app. Confirm this
   exists and is willing.
2. **Is "contact your rep" an existing FDGA motion** (templates, voice,
   campaigns) or is this a new thing? If existing, the app should match
   their voice. If new, FDGA leadership needs to agree on tone first.
3. **iOS day-one or Android first?** PWA-first sidesteps this for a while,
   but eventually we have to commit. Drives push-notification UX and
   app-store review timelines.
4. **Success metric?** Installs, messages-sent, share-throughs, time on
   district pages, donation conversions? Drives what we instrument and what
   we A/B test.
5. **Is FDGA OK with a "donate" button?** Civic apps that don't ask leave
   money on the table; civic apps that ask poorly feel sleazy. Worth
   deciding before designing the home screen.
6. **2026 election cycle pressure?** If FDGA wants this live for a specific
   campaign window, that shapes MVP scope hard.

---

## Suggested MVP scope (target: 2-3 months solo)

- Address entry → resolves to all three chambers
- District overview page with shareable URL
- Five tabs as outlined above
- OpenStates integration for reps
- Mapbox geocoder + static map widget
- Demographics + election data from existing `fdp` parquet files
  (exported as JSON at build time, served alongside the bundle — same
  pattern as `fdex`)
- One templated "contact your rep" flow with personalization gate
- FDGA news feed (RSS/JSON pull) on home screen
- PWA install prompt + service worker for offline read

**Explicitly out of v1:** push notifications, native app store presence,
ballot/candidate info, voter registration check, in-app donation flow
(link out to FDGA's existing donation page), accounts/login.

**v2 candidates:** push notifications for FDGA campaigns, native app store
binaries via Capacitor, "compare proposed maps" link back to `fdex` for
power users, offline mode for the whole district, sharing as an image
(react-to-png style) not just a URL.

---

## How this fits in the `fgdp` repo layout

Following the existing pattern (`fdex`, `fdensemble`, `fdworkbench`, etc.),
this would live at:

```
~/codebox/fgdp/fdga-mobile/
├── frontend/         ← Svelte 5 + Vite + Tailwind, same as fdex
├── data/             ← synced from fdp (demographics, election results)
├── config/           ← FDGA branding, rep templates, news feed URL
├── scripts/
│   └── sync_data.sh  ← reuses fdp's sync mechanism
└── README.md         ← parallel to fdex/README.md
```

Same data plumbing as `fdex` — `fdp sync-app fdga-mobile --dest ./data`.
This means the data layer is free and stays in sync as new election cycles
land in `fdp`.

If we end up wrapping in Capacitor, that's an additional `mobile/` subdir
with iOS/Android shells around the same web build output.

---

## What I'd push back on if asked to start coding tomorrow

- **Don't start with the map.** It's the most tempting thing to build first
  because it's familiar from `fdex`, but it's a 5% widget here. Start with
  the address → reps flow. That's the spine.
- **Don't build accounts.** Civic apps without accounts have higher
  engagement and zero data-breach surface. Keep it stateless.
- **Don't build offline mode in v1.** Service worker caching of the shell
  is enough. Real offline (cached district data) is a v2 problem.
- **Don't write a CMS.** I'll keep repeating this. FDGA already publishes
  content somewhere; pull from there.
- **Don't piggyback fully on another civic app's UX.** The framing is the
  whole product.

---

## Things I'm uncertain about

- **How much demand actually exists?** The user's instinct ("FDGA info needs
  to be more accessible") is plausible but unvalidated. Worth a quick survey
  of FDGA's existing supporters before committing to 2-3 months.
- **Does OpenStates have full GA coverage for the new 2024+ districts?**
  Need to verify before designing around it. If not, fallback is scraping
  `legis.ga.gov`.
- **Mapbox costs at consumer scale.** `fdex` is low-traffic; a consumer
  app could push beyond the free tier. Static map images are way cheaper
  than GL JS sessions — worth modeling.
- **Whether FDGA wants to gate "Take Action" behind email signup** to grow
  their list. Strong product argument both ways; not my call.

---

## Bottom line

This is a fundamentally better-shaped product than "fdex but mobile." It
plays to FDGA's actual mission (mobilization), uses existing data plumbing,
and ships as a PWA in weeks rather than months. The map question disappears
once we accept the map is a widget, not the product.

Biggest open product question: **does FDGA's content pipeline + voice
already exist, or are we inventing it alongside the app?** That answer
determines whether MVP is 8 weeks or 16.
