---
description: Clone target repo and run pyreverse + pydeps extractors
argument-hint: <github-url-or-local-path>
---

Run the extractor and seeder in sequence on `$ARGUMENTS`, then summarize what
was found (packages, class count, top external imports).

```bash
python scripts/extract.py $ARGUMENTS --out build/raw
python scripts/seed_structurizr.py build/raw --out out/workspace.dsl
```

After both succeed, read `build/raw/manifest.json` and report:
- target repo
- list of packages detected
- number of `.mmd` class diagrams produced
- next suggested step (`/l4`)
