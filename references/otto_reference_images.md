# Otto Reference Images

Place your Otto reference images here for Leonardo.ai character consistency:

- `references/otto_with_kobi.png` — Otto on the bed with Kobi the plush dragon
- `references/otto_standing.png` — Otto standing, full body shot

These images are used by the Leonardo.ai image-to-image pipeline to ensure
every generated b-roll frame looks like Otto (consistent breed, color, features).

## How to add your images

Copy your images into this directory with the exact filenames above:

```bash
cp /path/to/your/otto-bed-photo.png references/otto_with_kobi.png
cp /path/to/your/otto-standing-photo.png references/otto_standing.png
```

The pipeline will automatically use the first available reference image
when generating b-roll frames via Leonardo.ai.
