import type {CSSProperties} from "react";
import {
  Easing,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

import {PALETTE} from "../config";

type BandRegion = {
  left: number;
  right: number;
  top: number;
  bottom: number;
  bands: number;
  stagger: number;
  revealDuration?: number;
};

export type InkRevealProps = {
  clean: string;
  annotated: string;
  wipeAngle?: number;
  startFrame: number;
  durationInFrames: number;
  bandRegion?: BandRegion;
  style?: CSSProperties;
};

const clamp = {
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

const imageStyle: CSSProperties = {
  position: "absolute",
  inset: 0,
  width: "100%",
  height: "100%",
  objectFit: "fill",
};

export const InkReveal: React.FC<InkRevealProps> = ({
  clean,
  annotated,
  wipeAngle = 135,
  startFrame,
  durationInFrames,
  bandRegion,
  style,
}) => {
  const frame = useCurrentFrame();
  const progress = interpolate(
    frame,
    [startFrame, startFrame + durationInFrames],
    [0, 1],
    {
      ...clamp,
      easing: Easing.bezier(0.45, 0, 0.2, 1),
    },
  );
  const edge = interpolate(progress, [0, 1], [-7, 107], clamp);
  const glowOpacity =
    progress <= 0 || progress >= 1
      ? 0
      : interpolate(progress, [0, 0.12, 0.88, 1], [0, 0.78, 0.72, 0], clamp);

  return (
    <div style={{position: "absolute", inset: 0, overflow: "hidden", ...style}}>
      <Img src={staticFile(clean)} style={imageStyle} />
      <Img
        src={staticFile(annotated)}
        style={{
          ...imageStyle,
          clipPath: bandRegion
            ? `inset(0 ${100 - bandRegion.left}% 0 0)`
            : undefined,
          WebkitMaskImage: `linear-gradient(${wipeAngle}deg, #000 0%, #000 ${edge - 4}%, rgba(0,0,0,.65) ${edge}%, transparent ${edge + 5}%)`,
          maskImage: `linear-gradient(${wipeAngle}deg, #000 0%, #000 ${edge - 4}%, rgba(0,0,0,.65) ${edge}%, transparent ${edge + 5}%)`,
        }}
      />

      {bandRegion
        ? Array.from({length: bandRegion.bands}, (_, index) => {
            const bandHeight = (bandRegion.bottom - bandRegion.top) / bandRegion.bands;
            const top = bandRegion.top + bandHeight * index;
            const bottom = top + bandHeight + 1.2;
            const bandProgress = interpolate(
              frame,
              [
                startFrame + index * bandRegion.stagger,
                startFrame +
                  index * bandRegion.stagger +
                  (bandRegion.revealDuration ?? 11),
              ],
              [0, 1],
              {
                ...clamp,
                easing: Easing.bezier(0.16, 1, 0.3, 1),
              },
            );
            return (
              <Img
                key={`${annotated}-${index}`}
                src={staticFile(annotated)}
                style={{
                  ...imageStyle,
                  clipPath: `inset(${top}% ${100 - bandRegion.right}% ${100 - bottom}% ${bandRegion.left}%)`,
                  WebkitMaskImage: `linear-gradient(to bottom, #000 0%, #000 ${bandProgress * 94}%, transparent ${Math.min(100, bandProgress * 94 + 6)}%)`,
                  maskImage: `linear-gradient(to bottom, #000 0%, #000 ${bandProgress * 94}%, transparent ${Math.min(100, bandProgress * 94 + 6)}%)`,
                }}
              />
            );
          })
        : null}

      <div
        style={{
          position: "absolute",
          inset: "-12%",
          opacity: glowOpacity,
          background: `linear-gradient(${wipeAngle}deg, transparent ${edge - 2.2}%, rgba(232,180,90,.04) ${edge - 0.8}%, ${PALETTE.amber} ${edge}%, rgba(232,180,90,.05) ${edge + 1.4}%, transparent ${edge + 3.1}%)`,
          filter: "blur(12px)",
          mixBlendMode: "screen",
          pointerEvents: "none",
        }}
      />

      {Array.from({length: 10}, (_, index) => {
        const x = (17 + index * 29) % 96;
        const offset = ((index * 17) % 11) - 5;
        const y = edge * 1.28 - x * 0.72 + offset;
        const visible = y > 1 && y < 98 && glowOpacity > 0;
        const twinkle = 0.45 + 0.4 * Math.sin(frame * 0.31 + index * 1.9);
        const size = 3 + (index % 3) * 2;
        return (
          <div
            key={index}
            style={{
              position: "absolute",
              left: `${x}%`,
              top: `${y}%`,
              width: size,
              height: size,
              borderRadius: "50%",
              opacity: visible ? glowOpacity * twinkle : 0,
              backgroundColor: PALETTE.amber,
              boxShadow: `0 0 ${size * 3}px ${PALETTE.amber}`,
            }}
          />
        );
      })}
    </div>
  );
};
