import "./index.css";
import {Composition} from "remotion";

import {DEFAULT_PROMO_PROPS, DURATION_IN_FRAMES, FPS} from "./config";
import {HbPdfPromo, HbPdfPromoPortrait} from "./HbPdfPromo";
import "./fonts";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="HbPdfPromo"
        component={HbPdfPromo}
        durationInFrames={DURATION_IN_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{...DEFAULT_PROMO_PROPS, variant: "wide"}}
      />
      <Composition
        id="HbPdfPromoPortrait"
        component={HbPdfPromoPortrait}
        durationInFrames={DURATION_IN_FRAMES}
        fps={FPS}
        width={1080}
        height={1350}
        defaultProps={{...DEFAULT_PROMO_PROPS, variant: "portrait"}}
      />
    </>
  );
};
