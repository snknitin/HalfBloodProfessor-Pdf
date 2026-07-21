export const FPS = 30;
export const DURATION_IN_FRAMES = 300;

// Keep the editorial rhythm visible in Remotion Studio. Each new scene overlaps
// the previous one for a slow, readable dissolve rather than a hard cut.
export const SCENE_TIMING = {
  marginNotes: {
    from: 0,
    duration: 118,
    pageMove: 104,
    revealStart: 8,
    revealDuration: 72,
    titleEnter: 12,
    titleExit: 95,
  },
  factCheck: {
    from: 100,
    duration: 105,
    pageMove: 92,
    revealStart: 10,
    revealDuration: 62,
    captionEnter: 35,
  },
  diagram: {
    from: 187,
    duration: 82,
    pageMove: 72,
    revealStart: 8,
    revealDuration: 58,
    captionEnter: 34,
  },
  outro: {
    from: 251,
    duration: 49,
  },
} as const;

export const PALETTE = {
  paper: "#f4ecd8",
  ink: "#241f1a",
  amber: "#e8b45a",
  purple: "#6a4c93",
  teal: "#2e6b5e",
  yellow: "#ffd23f",
  background: "#0d0a07",
  backgroundWarm: "#24170d",
} as const;

export const PAGE_ASSETS = {
  marginNotes: {
    clean: "ch1_p3_clean.png",
    annotated: "ch1_p3_annotated.png",
    width: 1500,
    height: 1850,
    focal: {x: 0.3, y: 0.62},
  },
  factCheck: {
    clean: "ch1_p5_clean.png",
    annotated: "ch1_p5_annotated.png",
    width: 1500,
    height: 1850,
    focal: {x: 0.68, y: 0.47},
  },
  diagram: {
    clean: "ch6_p261_clean.png",
    annotated: "ch6_p261_annotated.png",
    width: 1400,
    height: 1838,
    focal: {x: 0.89, y: 0.72},
  },
} as const;

export const COPY = {
  marginNotesTitle: "Proofread and studied by an expert.",
  factCheckCaption: "Corrections. Fact-checks. Right in the margins.",
  diagramCaption: "Even the diagrams — sketched into the margins.",
  outroTitle: "Upload a PDF. Watch it transform.",
} as const;

export type PromoVariant = "wide" | "portrait";

export type HbPdfPromoProps = {
  variant: PromoVariant;
  pageAssets: typeof PAGE_ASSETS;
  palette: typeof PALETTE;
  copy: typeof COPY;
};

export const DEFAULT_PROMO_PROPS: HbPdfPromoProps = {
  variant: "wide",
  pageAssets: PAGE_ASSETS,
  palette: PALETTE,
  copy: COPY,
};
