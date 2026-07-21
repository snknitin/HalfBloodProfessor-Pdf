import {loadFont} from "@remotion/fonts";
import {staticFile} from "remotion";

void loadFont({
  family: "Caveat",
  url: staticFile("fonts/Caveat.ttf"),
  format: "truetype",
  display: "block",
});

void loadFont({
  family: "Homemade Apple",
  url: staticFile("fonts/HomemadeApple-Regular.ttf"),
  format: "truetype",
  display: "block",
});

export const FONT_SERIF = "Georgia, 'Times New Roman', serif";
export const FONT_HAND = "Caveat, cursive";
