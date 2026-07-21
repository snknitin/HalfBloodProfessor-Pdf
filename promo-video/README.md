# hb-pdf promo video

A silent, ten-second Remotion promo built from real clean and annotated PDF page renders. The animation presents AI-generated annotations as handwritten-style marginalia, scribbles, corrections, and diagrams without claiming that a person drew them.

## Preview and render

```powershell
npm install
npm run dev
npm run render:wide
npm run render:portrait
```

The compositions are:

- `HbPdfPromo`: 1920 x 1080 (16:9)
- `HbPdfPromoPortrait`: 1080 x 1350 (4:5)

Both run at 30 fps for 300 frames. Rendered files are written to the repository's `outputs` folder.

## Landing-page embed

Autoplay and looping are browser behavior, so the site should embed the rendered file like this:

```html
<video autoplay muted loop playsinline preload="metadata">
  <source src="/hb-pdf-promo-16x9.mp4" type="video/mp4" />
</video>
```

Keep `muted` and `playsinline`; browsers commonly require them for reliable autoplay.
