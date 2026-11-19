# Writing niche.json

`niche.json` tells the discover step who counts as a lookalike. Bad queries give you lookalikes in the wrong niche, and a wrong-niche brand list is useless. Read the profile output (title, recent titles, tags, topics, language) before you write it.

```json
{
  "niche": "calisthenics / bodyweight strength training",
  "language": "it",
  "region": "IT",
  "queries": [
    "calisthenics principianti",
    "allenamento corpo libero a casa",
    "muscle up tutorial",
    "come fare la verticale",
    "scheda calisthenics",
    "trazioni alla sbarra progressione",
    "street workout italia",
    "front lever tutorial",
    "planche progressione",
    "dieta calisthenics"
  ],
  "queries_en": ["calisthenics workout routine", "muscle up progression", "bodyweight training at home"],
  "cpm_bucket": "fitness",
  "exclude_terms": ["kids", "news", "compilation", "asmr"]
}
```

## Fields

- **niche**: one human-readable line. It's used in the pitches.
- **language**: an ISO 639-1 code (`it`, `en`, `es`, `de`, `fr`, `pt`). It's the language the channel speaks, not the one its titles happen to use.
- **region**: an ISO 3166-1 alpha-2 country code (`IT`, `US`, `ES`). If the audience is international, use `null`.
- **queries**: 10-12 searches in the channel's language. Write what a viewer of this channel would actually type into YouTube:
  - Mix topic queries ("planche progression"), format queries ("full body workout at home"), and problem queries ("how to do a muscle up").
  - Make them specific enough to stay in the niche. "fitness" alone pulls in everything.
  - **Never** include brand names, channel names, or the creator's own name.
  - Cover the 2-3 sub-themes the channel actually covers, judged from the recent titles, not just its main keyword.
- **queries_en**: 2-4 English queries, only for non-English channels. They surface international brands, and ranking already discounts brands that only sponsor other-language creators. Use `[]` for English channels.
- **cpm_bucket**: one key from `cpm.json` (tech, finance, business, software, education, productivity, science, fitness, health, beauty, fashion, lifestyle, food, travel, parenting, outdoors, automotive, gaming, entertainment, vlog, comedy, music). Pick the one a sponsor's media buyer would file this channel under.
- **exclude_terms**: lowercase words that mark off-niche channels by their title or matched video titles. Keep it short, because over-excluding loses real lookalikes. You'll prune by hand at the candidates step anyway.

## Budget

Each query costs 100 API units, and the config caps a run at 15 queries in total (`queries` + `queries_en`). Searches are cached for the week, so rerunning the same queries is free and a new query costs 100.
