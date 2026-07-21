import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from "remotion";

import {PALETTE} from "../config";

export const Atmosphere: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const phase = (frame / durationInFrames) * Math.PI * 2;
  const flicker = 1 + Math.sin(phase * 3) * 0.014 + Math.sin(phase * 7) * 0.006;
  const drift = interpolate(Math.sin(phase), [-1, 1], [-2, 2]);

  return (
    <AbsoluteFill
      style={{
        overflow: "hidden",
        backgroundColor: PALETTE.background,
        filter: `brightness(${flicker})`,
      }}
    >
      <AbsoluteFill
        style={{
          background: [
            `radial-gradient(circle at ${78 + drift}% 16%, rgba(232,180,90,.24), transparent 30%)`,
            "radial-gradient(circle at 56% 48%, rgba(91,57,28,.22), transparent 54%)",
            `linear-gradient(132deg, ${PALETTE.background} 3%, ${PALETTE.backgroundWarm} 52%, #080604 100%)`,
          ].join(","),
        }}
      />
      <AbsoluteFill
        style={{
          opacity: 0.16,
          mixBlendMode: "soft-light",
          backgroundImage:
            "repeating-radial-gradient(circle at 20% 30%, rgba(255,255,255,.16) 0 0.7px, transparent 0.9px 4px)",
          backgroundSize: "13px 11px",
        }}
      />
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 46%, rgba(5,3,2,.3) 72%, rgba(2,1,1,.82) 100%)",
        }}
      />
    </AbsoluteFill>
  );
};

export const AmberBloom: React.FC<{progress: number}> = ({progress}) => (
  <AbsoluteFill
    style={{
      opacity: Math.sin(Math.min(1, progress) * Math.PI) * 0.64,
      mixBlendMode: "screen",
      background:
        "radial-gradient(circle at 58% 48%, rgba(232,180,90,.75), rgba(232,180,90,.16) 22%, transparent 58%)",
      filter: "blur(10px)",
    }}
  />
);
