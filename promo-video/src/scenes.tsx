import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import type {HbPdfPromoProps, PromoVariant} from "./config";
import {PALETTE, SCENE_TIMING} from "./config";
import {AmberBloom} from "./components/Atmosphere";
import {InkReveal} from "./components/InkReveal";
import {QuillMagicGesture} from "./components/QuillMagicGesture";
import {
  getMarginNotesOpeningLayout,
  PageStage,
  type PageLayout,
} from "./components/PageStage";
import {PromoCaption, PromoTitle} from "./components/Typography";
import {FONT_SERIF} from "./fonts";

const clamp = {
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

const fadeWindow = (
  frame: number,
  duration: number,
  fadeIn: number,
  fadeOut: number,
  startsVisible = false,
) => {
  const enter = startsVisible
    ? 1
    : interpolate(frame, [0, fadeIn], [0, 1], {
        ...clamp,
        easing: Easing.bezier(0.16, 1, 0.3, 1),
      });
  const exit = interpolate(frame, [duration - fadeOut, duration], [1, 0], {
    ...clamp,
    easing: Easing.in(Easing.cubic),
  });
  return enter * exit;
};

const pageLayout = (
  variant: PromoVariant,
  width: number,
  height: number,
  assetWidth: number,
  assetHeight: number,
  heightScale: number,
  leftWide: number,
  topWide: number,
  leftPortrait: number,
  topPortrait: number,
): PageLayout => {
  const pageHeight = height * heightScale;
  return {
    width: pageHeight * (assetWidth / assetHeight),
    height: pageHeight,
    left: variant === "wide" ? leftWide * width : leftPortrait * width,
    top: variant === "wide" ? topWide * height : topPortrait * height,
  };
};

const FactCheckArrow: React.FC = () => {
  const frame = useCurrentFrame();
  const draw = interpolate(frame, [34, 62], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.45, 0, 0.2, 1),
  });
  return (
    <svg
      viewBox="0 0 1500 1850"
      style={{position: "absolute", inset: 0, width: "100%", height: "100%"}}
    >
      <path
        d="M 1268 780 C 1100 735, 800 690, 360 704"
        fill="none"
        stroke={PALETTE.teal}
        strokeWidth={6}
        strokeLinecap="round"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - draw}
        opacity={0.78}
      />
      <path
        d="M 360 704 L 389 686 M 360 704 L 390 720"
        fill="none"
        stroke={PALETTE.teal}
        strokeWidth={6}
        strokeLinecap="round"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - draw}
        opacity={0.78}
      />
      <circle
        cx={360}
        cy={704}
        r={14}
        fill={PALETTE.amber}
        opacity={interpolate(draw, [0.9, 1], [0, 0.9], clamp)}
        style={{filter: "drop-shadow(0 0 16px #e8b45a)"}}
      />
    </svg>
  );
};

const DiagramSweepArrow: React.FC = () => {
  const frame = useCurrentFrame();
  const draw = interpolate(frame, [20, 57], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.45, 0, 0.2, 1),
  });
  return (
    <svg
      viewBox="0 0 1400 1838"
      style={{position: "absolute", inset: 0, width: "100%", height: "100%"}}
    >
      <path
        d="M 165 1020 C 120 830, 132 610, 235 470"
        fill="none"
        stroke={PALETTE.teal}
        strokeWidth={5.5}
        strokeLinecap="round"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - draw}
        opacity={0.74}
      />
      <path
        d="M 235 470 L 214 496 M 235 470 L 244 508"
        fill="none"
        stroke={PALETTE.teal}
        strokeWidth={5.5}
        strokeLinecap="round"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - draw}
        opacity={0.74}
      />
    </svg>
  );
};

export const MarginNotesScene: React.FC<HbPdfPromoProps> = ({
  variant,
  pageAssets,
  copy,
}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const asset = pageAssets.marginNotes;
  const layout = getMarginNotesOpeningLayout(width, height, variant);

  return (
    <AbsoluteFill
      style={{
        opacity: fadeWindow(
          frame,
          SCENE_TIMING.marginNotes.duration,
          0,
          18,
          true,
        ),
      }}
    >
      <PageStage
        layout={layout}
        focalX={asset.focal.x}
        focalY={asset.focal.y}
        scaleFrom={1}
        scaleTo={1.12}
        panX={variant === "wide" ? -52 : -18}
        panY={variant === "wide" ? -34 : -52}
        duration={SCENE_TIMING.marginNotes.pageMove}
      >
        <InkReveal
          clean={asset.clean}
          annotated={asset.annotated}
          wipeAngle={135}
          startFrame={SCENE_TIMING.marginNotes.revealStart}
          durationInFrames={SCENE_TIMING.marginNotes.revealDuration}
        />
      </PageStage>
      <PromoTitle
        variant={variant}
        enterAt={SCENE_TIMING.marginNotes.titleEnter}
        exitAt={SCENE_TIMING.marginNotes.titleExit}
      >
        {copy.marginNotesTitle}
      </PromoTitle>
      <QuillMagicGesture variant={variant} />
    </AbsoluteFill>
  );
};

export const FactCheckScene: React.FC<HbPdfPromoProps> = ({
  variant,
  pageAssets,
  copy,
}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const asset = pageAssets.factCheck;
  const layout = pageLayout(
    variant,
    width,
    height,
    asset.width,
    asset.height,
    variant === "wide" ? 1.46 : 1.3,
    0.32,
    -0.24,
    -0.15,
    -0.08,
  );
  const bloom = interpolate(frame, [0, 11], [0, 1], clamp);

  return (
    <AbsoluteFill
      style={{
        opacity: fadeWindow(frame, SCENE_TIMING.factCheck.duration, 18, 18),
      }}
    >
      <PageStage
        layout={layout}
        focalX={asset.focal.x}
        focalY={asset.focal.y}
        scaleFrom={1.05}
        scaleTo={1.13}
        panX={variant === "wide" ? -36 : -58}
        panY={-20}
        duration={SCENE_TIMING.factCheck.pageMove}
      >
        <InkReveal
          clean={asset.clean}
          annotated={asset.annotated}
          wipeAngle={132}
          startFrame={SCENE_TIMING.factCheck.revealStart}
          durationInFrames={SCENE_TIMING.factCheck.revealDuration}
        />
        <FactCheckArrow />
      </PageStage>
      <AmberBloom progress={bloom} />
      <PromoCaption variant={variant} enterAt={SCENE_TIMING.factCheck.captionEnter}>
        {copy.factCheckCaption}
      </PromoCaption>
    </AbsoluteFill>
  );
};

export const DiagramScene: React.FC<HbPdfPromoProps> = ({
  variant,
  pageAssets,
  copy,
}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const asset = pageAssets.diagram;
  const layout = pageLayout(
    variant,
    width,
    height,
    asset.width,
    asset.height,
    variant === "wide" ? 1.49 : 1.36,
    0.25,
    -0.55,
    -0.42,
    -0.34,
  );

  return (
    <AbsoluteFill
      style={{
        opacity: fadeWindow(frame, SCENE_TIMING.diagram.duration, 18, 18),
      }}
    >
      <PageStage
        layout={layout}
        focalX={asset.focal.x}
        focalY={asset.focal.y}
        scaleFrom={1.03}
        scaleTo={1.1}
        panX={variant === "wide" ? -22 : -36}
        panY={-14}
        duration={SCENE_TIMING.diagram.pageMove}
      >
        <InkReveal
          clean={asset.clean}
          annotated={asset.annotated}
          wipeAngle={135}
          startFrame={SCENE_TIMING.diagram.revealStart}
          durationInFrames={SCENE_TIMING.diagram.revealDuration}
          bandRegion={{
            left: 82,
            right: 100,
            top: 58,
            bottom: 95,
            bands: 5,
            stagger: 8,
            revealDuration: 18,
          }}
        />
        <DiagramSweepArrow />
      </PageStage>
      <PromoCaption variant={variant} enterAt={SCENE_TIMING.diagram.captionEnter}>
        {copy.diagramCaption}
      </PromoCaption>
    </AbsoluteFill>
  );
};

const FanPage: React.FC<{
  src: string;
  left: number;
  top: number;
  width: number;
  height: number;
  rotate: number;
  opacity: number;
  zIndex: number;
}> = ({src, left, top, width, height, rotate, opacity, zIndex}) => (
  <Img
    src={staticFile(src)}
    style={{
      position: "absolute",
      left,
      top,
      width,
      height,
      rotate: `${rotate}deg`,
      opacity,
      zIndex,
      objectFit: "fill",
      transformOrigin: "50% 88%",
      boxShadow: "0 30px 70px rgba(0,0,0,.62), 0 0 28px rgba(232,180,90,.16)",
      backgroundColor: PALETTE.paper,
    }}
  />
);

export const OutroScene: React.FC<HbPdfPromoProps> = ({
  variant,
  pageAssets,
  copy,
}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const reveal = spring({
    frame,
    fps,
    durationInFrames: 20,
    config: {damping: 190, stiffness: 105, mass: 0.8},
  });
  const loop = interpolate(frame, [28, 48], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.45, 0, 0.55, 1),
  });
  const opening = getMarginNotesOpeningLayout(width, height, variant);
  const fanHeight = variant === "wide" ? height * 0.61 : height * 0.58;
  const frontWidth = fanHeight * (1500 / 1850);
  const fanTop = variant === "wide" ? height * 0.18 : height * 0.17;
  const fanLeft = (width - frontWidth) / 2;
  const frontLayout = {
    left: interpolate(loop, [0, 1], [fanLeft, opening.left]),
    top: interpolate(loop, [0, 1], [fanTop, opening.top]),
    width: interpolate(loop, [0, 1], [frontWidth, opening.width]),
    height: interpolate(loop, [0, 1], [fanHeight, opening.height]),
  };
  const sideOpacity = (1 - loop) * reveal;
  const titleOpacity = interpolate(loop, [0, 0.72, 1], [1, 1, 0], clamp);

  return (
    <AbsoluteFill
      style={{
        opacity: interpolate(frame, [0, 7], [0, 1], {
          ...clamp,
          easing: Easing.bezier(0.16, 1, 0.3, 1),
        }),
      }}
    >
      <FanPage
        src={pageAssets.factCheck.annotated}
        left={fanLeft - width * 0.13 * reveal}
        top={fanTop + height * 0.035}
        width={frontWidth}
        height={fanHeight}
        rotate={-8 * reveal}
        opacity={sideOpacity}
        zIndex={2}
      />
      <FanPage
        src={pageAssets.diagram.annotated}
        left={fanLeft + width * 0.13 * reveal}
        top={fanTop + height * 0.035}
        width={fanHeight * (1400 / 1838)}
        height={fanHeight}
        rotate={8 * reveal}
        opacity={sideOpacity}
        zIndex={3}
      />
      <div
        style={{
          position: "absolute",
          left: frontLayout.left,
          top: frontLayout.top,
          width: frontLayout.width,
          height: frontLayout.height,
          zIndex: 5,
          rotate: `${interpolate(reveal, [0, 1], [-2.5, 0])}deg`,
          boxShadow: "0 34px 80px rgba(0,0,0,.68), 0 0 36px rgba(232,180,90,.2)",
          backgroundColor: PALETTE.paper,
        }}
      >
        <Img
          src={staticFile(pageAssets.marginNotes.annotated)}
          style={{position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 1 - loop}}
        />
        <Img
          src={staticFile(pageAssets.marginNotes.clean)}
          style={{position: "absolute", inset: 0, width: "100%", height: "100%", opacity: loop}}
        />
      </div>
      <div
        style={{
          position: "absolute",
          zIndex: 20,
          left: width * 0.08,
          right: width * 0.08,
          top: variant === "wide" ? height * 0.055 : height * 0.06,
          color: PALETTE.paper,
          textAlign: "center",
          fontFamily: FONT_SERIF,
          fontSize: variant === "wide" ? 78 : 64,
          lineHeight: 1.02,
          letterSpacing: "-0.025em",
          opacity: titleOpacity * reveal,
          textShadow: "0 3px 20px rgba(0,0,0,.9)",
        }}
      >
        {copy.outroTitle}
      </div>
    </AbsoluteFill>
  );
};
