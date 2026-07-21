import {Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

import {PALETTE, type PromoVariant} from "../config";
import {FONT_HAND} from "../fonts";

const clamp = {
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

const sparkleOpacity = (frame: number, start: number) =>
  interpolate(frame, [start, start + 4, start + 12], [0, 1, 0], {
    ...clamp,
    easing: Easing.inOut(Easing.sin),
  });

export const QuillMagicGesture: React.FC<{variant: PromoVariant}> = ({variant}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const sceneEnter = interpolate(frame, [16, 26], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const dip = interpolate(frame, [22, 28, 34], [0, 1, 0], {
    ...clamp,
    easing: Easing.inOut(Easing.cubic),
  });
  const moveToPage = interpolate(frame, [32, 40], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const write = interpolate(frame, [40, 62], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.45, 0, 0.55, 1),
  });
  const flourish = interpolate(frame, [57, 67], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.45, 0, 0.55, 1),
  });
  const quillExit = interpolate(frame, [66, 75], [1, 0], {
    ...clamp,
    easing: Easing.in(Easing.cubic),
  });
  const writingExit = interpolate(frame, [69, 80], [1, 0], {
    ...clamp,
    easing: Easing.in(Easing.cubic),
  });
  const vignetteExit = interpolate(frame, [72, 84], [1, 0], {
    ...clamp,
    easing: Easing.inOut(Easing.cubic),
  });

  const startX = 0;
  const startY = -5 + dip * 13;
  const pageX = 64 + write * 238;
  const pageY = -44 + Math.sin(write * Math.PI * 5) * 7;
  const quillX = interpolate(moveToPage, [0, 1], [startX, pageX], clamp);
  const quillY = interpolate(moveToPage, [0, 1], [startY, pageY], clamp);
  const quillRotation = interpolate(moveToPage, [0, 1], [-7, -14], clamp) + Math.sin(write * Math.PI * 4) * 2;

  return (
    <div
      style={{
        position: "absolute",
        zIndex: 21,
        left: variant === "wide" ? width * 0.05 : width * 0.07,
        top: variant === "wide" ? height * 0.34 : height * 0.225,
        width: variant === "wide" ? 480 : width * 0.82,
        height: variant === "wide" ? 255 : 230,
        opacity: sceneEnter,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          overflow: "hidden",
          borderRadius: 8,
          opacity: vignetteExit,
          maskImage: "radial-gradient(ellipse 88% 82% at 50% 51%, #000 62%, transparent 100%)",
          WebkitMaskImage: "radial-gradient(ellipse 88% 82% at 50% 51%, #000 62%, transparent 100%)",
          boxShadow: "0 18px 46px rgba(0,0,0,.48)",
        }}
      >
        <Img
          src={staticFile("annotated-open-book.png")}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: "cover",
            objectPosition: "center 54%",
            filter: "brightness(.82) sepia(.12) saturate(.88)",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "radial-gradient(ellipse at 53% 54%, rgba(232,180,90,.13), transparent 48%), linear-gradient(90deg, rgba(4,3,2,.3), transparent 24%, transparent 78%, rgba(4,3,2,.22))",
          }}
        />
      </div>

      <svg
        viewBox="0 0 480 255"
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          overflow: "visible",
        }}
      >
        <defs>
          <clipPath id="hbPdfBookReveal">
            <rect x="90" y="78" width={interpolate(write, [0, 1], [0, 278], clamp)} height="78" />
          </clipPath>
        </defs>
        <text
          x="94"
          y="143"
          clipPath="url(#hbPdfBookReveal)"
          fill={PALETTE.amber}
          fontFamily={FONT_HAND}
          fontSize={66}
          fontWeight={600}
          letterSpacing={1.4}
          opacity={writingExit}
          style={{filter: "drop-shadow(0 0 7px rgba(232,180,90,.82)) drop-shadow(0 2px 2px rgba(0,0,0,.72))"}}
        >
          hb-pdf
        </text>
        <path
          d="M94 151 C154 161 226 157 309 145 C333 141 349 129 342 121 C336 114 324 123 331 133 C342 150 363 145 376 131"
          fill="none"
          stroke={PALETTE.amber}
          strokeWidth={3.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - flourish}
          opacity={0.96 * writingExit}
          style={{filter: "drop-shadow(0 0 6px rgba(232,180,90,.78)) drop-shadow(0 2px 2px rgba(0,0,0,.7))"}}
        />

        {[
          {x: 64, y: 178, start: 29, size: 8},
          {x: 184, y: 109, start: 48, size: 7},
          {x: 310, y: 111, start: 58, size: 9},
          {x: 378, y: 121, start: 66, size: 10},
        ].map((sparkle) => (
          <g key={sparkle.x} opacity={sparkleOpacity(frame, sparkle.start) * writingExit}>
            <path
              d={`M${sparkle.x} ${sparkle.y - sparkle.size} L${sparkle.x + 2} ${sparkle.y - 2} L${sparkle.x + sparkle.size} ${sparkle.y} L${sparkle.x + 2} ${sparkle.y + 2} L${sparkle.x} ${sparkle.y + sparkle.size} L${sparkle.x - 2} ${sparkle.y + 2} L${sparkle.x - sparkle.size} ${sparkle.y} L${sparkle.x - 2} ${sparkle.y - 2}Z`}
              fill={PALETTE.amber}
              style={{filter: "drop-shadow(0 0 7px rgba(232,180,90,.85))"}}
            />
          </g>
        ))}
      </svg>

      <Img
        src={staticFile("amber-quill.png")}
        style={{
          position: "absolute",
          zIndex: 3,
          left: quillX,
          top: quillY,
          width: variant === "wide" ? 196 : 176,
          height: variant === "wide" ? 196 : 176,
          objectFit: "contain",
          opacity: quillExit,
          rotate: `${quillRotation}deg`,
          transformOrigin: "8% 95%",
          filter: `drop-shadow(0 8px 9px rgba(0,0,0,.62)) ${dip > 0.25 ? "brightness(.82)" : "brightness(1)"}`,
        }}
      />
    </div>
  );
};
