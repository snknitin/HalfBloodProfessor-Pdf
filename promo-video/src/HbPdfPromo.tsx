import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import type {HbPdfPromoProps, PromoVariant} from "./config";
import {SCENE_TIMING} from "./config";
import {Atmosphere} from "./components/Atmosphere";
import {
  DiagramScene,
  FactCheckScene,
  MarginNotesScene,
  OutroScene,
} from "./scenes";

const clamp = {
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

const PersistentBrandMark: React.FC<{variant: PromoVariant}> = ({variant}) => {
  const frame = useCurrentFrame();
  const {width, height, durationInFrames} = useVideoConfig();
  const reveal = interpolate(frame, [74, 84], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const settle = interpolate(frame, [96, 116], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const loopExit = interpolate(frame, [durationInFrames - 12, durationInFrames - 1], [1, 0], {
    ...clamp,
    easing: Easing.in(Easing.cubic),
  });
  const writtenX = variant === "wide" ? width * 0.05 + 195 : width * 0.07 + width * 0.31;
  const writtenY = variant === "wide" ? height * 0.34 + 70 : height * 0.225 + 60;
  const cornerX = variant === "wide" ? 48 : 38;
  const cornerY = variant === "wide" ? 38 : 36;
  const startSize = variant === "wide" ? 112 : 98;
  const cornerSize = variant === "wide" ? 72 : 64;

  return (
    <div
      style={{
        position: "absolute",
        zIndex: 90,
        left: interpolate(settle, [0, 1], [writtenX, cornerX], clamp),
        top: interpolate(settle, [0, 1], [writtenY, cornerY], clamp),
        width: interpolate(settle, [0, 1], [startSize, cornerSize], clamp),
        height: interpolate(settle, [0, 1], [startSize, cornerSize], clamp),
        display: "grid",
        placeItems: "center",
        opacity: reveal * loopExit,
        scale: interpolate(reveal, [0, 1], [0.72, 1], clamp),
        filter: "drop-shadow(0 0 20px rgba(232,180,90,.58))",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: -16,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(232,180,90,.32), transparent 68%)",
          opacity: interpolate(frame, [74, 82, 100], [0, 1, 0.3], clamp),
        }}
      />
      <Img
        src={staticFile("halfblood-professor-mark.svg")}
        style={{width: "100%", height: "100%", objectFit: "contain"}}
      />
    </div>
  );
};

export const HbPdfPromo: React.FC<HbPdfPromoProps> = (props) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const phase = (frame / durationInFrames) * Math.PI * 2;
  const candlelight = 1 + Math.sin(phase * 3) * 0.012 + Math.sin(phase * 7) * 0.005;

  return (
    <AbsoluteFill style={{overflow: "hidden", backgroundColor: props.palette.background}}>
      <Atmosphere />
      <AbsoluteFill style={{filter: `brightness(${candlelight})`}}>
        <Sequence
          from={SCENE_TIMING.marginNotes.from}
          durationInFrames={SCENE_TIMING.marginNotes.duration}
        >
          <MarginNotesScene {...props} />
        </Sequence>
        <Sequence
          from={SCENE_TIMING.factCheck.from}
          durationInFrames={SCENE_TIMING.factCheck.duration}
        >
          <FactCheckScene {...props} />
        </Sequence>
        <Sequence
          from={SCENE_TIMING.diagram.from}
          durationInFrames={SCENE_TIMING.diagram.duration}
        >
          <DiagramScene {...props} />
        </Sequence>
        <Sequence
          from={SCENE_TIMING.outro.from}
          durationInFrames={SCENE_TIMING.outro.duration}
        >
          <OutroScene {...props} />
        </Sequence>
      </AbsoluteFill>
      <PersistentBrandMark variant={props.variant} />
    </AbsoluteFill>
  );
};

export const HbPdfPromoPortrait: React.FC<HbPdfPromoProps> = (props) => (
  <HbPdfPromo {...props} variant="portrait" />
);
