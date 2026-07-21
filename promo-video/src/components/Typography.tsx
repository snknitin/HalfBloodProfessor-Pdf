import type {CSSProperties} from "react";
import {Easing, interpolate, useCurrentFrame, useVideoConfig} from "remotion";

import {PALETTE, type PromoVariant} from "../config";
import {FONT_HAND, FONT_SERIF} from "../fonts";

export const PromoTitle: React.FC<{
  children: string;
  variant: PromoVariant;
  enterAt?: number;
  exitAt?: number;
  align?: "left" | "center";
  style?: CSSProperties;
}> = ({children, variant, enterAt = 6, exitAt, align = "left", style}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const enter = interpolate(frame, [enterAt, enterAt + 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const exit = exitAt
    ? interpolate(frame, [exitAt, exitAt + 8], [1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.in(Easing.cubic),
      })
    : 1;

  return (
    <div
      style={{
        position: "absolute",
        zIndex: 20,
        left: variant === "wide" ? width * 0.055 : width * 0.07,
        right: variant === "wide" ? width * 0.54 : width * 0.07,
        top: variant === "wide" ? height * 0.1 : height * 0.065,
        color: PALETTE.paper,
        fontFamily: FONT_SERIF,
        fontSize: variant === "wide" ? 82 : 68,
        lineHeight: 1.05,
        letterSpacing: "-0.025em",
        textAlign: align,
        opacity: enter * exit,
        translate: `0 ${interpolate(enter, [0, 1], [22, 0])}px`,
        textShadow: "0 3px 18px rgba(0,0,0,.72), 0 0 24px rgba(232,180,90,.12)",
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const PromoCaption: React.FC<{
  children: string;
  variant: PromoVariant;
  enterAt: number;
  bottom?: number;
  style?: CSSProperties;
}> = ({children, variant, enterAt, bottom, style}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const opacity = interpolate(frame, [enterAt, enterAt + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  return (
    <div
      style={{
        position: "absolute",
        zIndex: 24,
        left: variant === "wide" ? width * 0.055 : width * 0.07,
        right: variant === "wide" ? width * 0.47 : width * 0.07,
        bottom: bottom ?? (variant === "wide" ? height * 0.09 : height * 0.1),
        color: PALETTE.paper,
        fontFamily: FONT_HAND,
        fontSize: variant === "wide" ? 56 : 48,
        lineHeight: 1.05,
        opacity,
        translate: `0 ${interpolate(opacity, [0, 1], [14, 0])}px`,
        padding: variant === "wide" ? "14px 120px 14px 22px" : "14px 70px 14px 20px",
        background:
          "linear-gradient(90deg, rgba(13,10,7,.92) 0%, rgba(13,10,7,.76) 68%, transparent 100%)",
        textShadow: "0 3px 15px rgba(0,0,0,.95)",
        ...style,
      }}
    >
      {children}
    </div>
  );
};
