# Sound and music: the two services

Darkness Harness can buy a game's sound effects and music from one of two services, the owner's pick, one
setting. Each sound is priced before it is made, and a project never spends more than **$2 on sound**
(`sound.max_per_project_usd`, enforced in `harness/soundprice.py`). What can't be bought is made in code, as
before, and the plan says which.

**Read on 28 November 2026** from the services' own pages (listed at the end). Prices change: the adapters
read the real charge from each service's balance before and after a call, so the harness's count follows the
service, not this page. Lines marked *(verify)* could not be confirmed on the day and are checked again when
the adapters are first tried for real.

## Ruled out

- **Suno**: no official public API; the "Suno APIs" on sale are unofficial wrappers around a consumer account
  (against its terms, can vanish, the licence of what it makes is unclear).
- **OpenRouter**: carries chat models that hear or speak, but no sound-effect or music generation that we know
  of *(verify: if that changes it becomes a third adapter behind the same interface, with the key the owner
  already has)*.
- **Lyria (Google, through Vertex)**: music only, and needs a Google Cloud project and its sign-in, a set-up the
  owner would have to leave the app for. Kept as a possible later adapter.

## The two

| | **ElevenLabs** (sound effects and Eleven Music, one key) | **Stable Audio** (Stability AI) |
|---|---|---|
| **Price** | Plans by the month. Starter **$6 a month** (the first month $1): 150 sound effects and 40 minutes of music included; Creator $22. Over the API, sound effects **$0.12 a minute** and music **$0.15 a minute** of sound made. A 2-second effect is well under a cent; a 30-second music loop about 8 cents | Pay as you go, no plan: credits at **$0.01** each. Stable Audio 2.5 (and 3.0) cost **8 credits a clip, about $0.08**, whatever its length |
| **Licence** | Music: "commercial use licensing on Starter+ plans" (its price page). Sound effects are called royalty-free; the free plan's terms for commercial use *(verify on the terms page)* | Stability's Community Licence: commercial use while yearly revenue is under $1 million (above that, an Enterprise licence); "you own outputs". Whether the API's outputs fall under the same terms *(verify on the API terms)*. No vocals |
| **API** | `POST https://api.elevenlabs.io/v1/sound-generation`, JSON `{text, duration_seconds (0.5 to 30), loop, prompt_influence (0 to 1, default 0.3), model_id}`, the key in the `xi-api-key` header; the audio comes straight back (`output_format`, default `mp3_44100_128`; WAV needs the Pro tier). Music: `POST /v1/music` *(verify the body)*. `GET /v1/user/subscription` gives the credits left | `POST https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio` *(verify the 2.5 path)*, a form with `prompt`, `duration`, `output_format` (mp3 or wav), `seed`; `Authorization: Bearer`. `GET /v1/user/balance` gives the credits left |
| **Quality** | The best we know for short, crisp game effects (jump, hit, coin, door, footsteps), and it makes seamless loops. Music in many styles, can sing | Good for ambience, loops and instrumental music beds up to about three minutes. Short effects softer and less exact. No singing |
| **Risk** | **A subscription**: about $6 a month leaves the owner's card whether or not anything is built. The $2 cap is still kept in dollars | Twenty-five clips and the $2 is gone, so a small game's many short effects mostly stay made in code. Stability has changed its prices before |

## What changed from the wave 9 plan

The plan was written from memory. On the day:

- ElevenLabs' Starter plan is **$6** a month, not $5, and the API is priced by the minute of sound made
  ($0.12 effects, $0.15 music) rather than the 40 credits a second the plan remembered.
- Stable Audio 2.5 costs **8 credits (about $0.08)** a clip, not 20 credits ($0.20). Two dollars buys about
  twenty-five clips, not ten.

So the gap is smaller than the plan said. ElevenLabs is still better and cheaper for many short effects; Stable
Audio no longer costs much more for a small game's handful of sounds, and has no monthly charge. That is the
owner's question 1 (one card in the app).

## Pages read

- <https://elevenlabs.io/pricing/api> (plans, sound effects and music by the minute, music licence)
- <https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert> (the sound effects call)
- <https://docs.stability.ai/pricing> (credits and Stable Audio 2.5's price)
- <https://stability.ai/license> (the Community Licence)
