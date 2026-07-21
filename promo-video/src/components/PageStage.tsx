import type {CSSProperties, ReactNode} from "react";
import {Easing, interpolate, useCurrentFrame, useVideoConfig} from "remotion";

import type {PromoVariant} from "../config";

export type PageLayout = {
  left: number;
  top: number;
  width: number;
  height: number;
};
export const getMarginNotesOpeningLayout = (
  width: number,
  height: number,
  variant: PromoVariant,
): PageLayout => {
  const pageHeight = variant === "wide" ? height * 1.22 : height * 1.1;
  const pageWidth = pageHeight * (1500 / 1850);
  return {
    left: variant === "wide" ? width * 0.52 : (width - pageWidth) / 2,
    top: variant === "wide" ? -height * 0.1 : height * 0.02,
    width: pageWidth,
    height: pageHeight,
  };
};

export const PageStage: React.FC<{
  layout: PageLayout;
  focalX: number;
  focalY: number;
  scaleFrom: number;
  scaleTo: number;
  panX?: number;
  panY?: number;
  duration: number;
  children: ReactNode;
  style?: CSSProperties;
}> = ({
  layout,
  focalX,
  focalY,
  scaleFrom,
  scaleTo,
  panX = 0,
  panY = 0,
  duration,
  children,
  style,
}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const move = interpolate(frame, [0, duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.45, 0, 0.55, 1),
  });

  return (
    <div
      style={{
        position: "absolute",
        left: layout.left,
        top: layout.top,
        width: layout.width,
        height: layout.height,
        transformOrigin: `${focalX * 100}% ${focalY * 100}%`,
        scale: interpolate(move, [0, 1], [scaleFrom, scaleTo]),
        translate: `${interpolate(move, [0, 1], [0, panX])}px ${interpolate(move, [0, 1], [0, panY])}px`,
        backgroundColor: "#f4ecd8",
        boxShadow: `0 ${height * 0.03}px ${width * 0.055}px rgba(0,0,0,.66), 0 0 ${width * 0.018}px rgba(232,180,90,.18)`,
        overflow: "hidden",
        ...style,
      }}
    >
      {children}
    </div>
  );
};
