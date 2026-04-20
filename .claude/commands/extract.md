---
description: Clone target repo and run the multi-language unit + import extractor
argument-hint: <github-url-or-local-path>
---

Run extractor + seeder in sequence on `$ARGUMENTS`.

```bash
python scripts/extract.py $ARGUMENTS --out build/raw
python scripts/seed_structurizr.py build/raw --out out/workspace.dsl
```

After both succeed, read `build/raw/manifest.json` and report:
- languages detected
- count of units per language
- cross-unit edges (from `units[*].cross_unit_to`)
- top externals per unit (for L1 refinement)
- next suggested step (`/l3`)
