// Local display preference only; stored values and API payloads stay intact.
export const HIDE_NUMBERS = process.env.REACT_APP_HIDE_NUMBERS === "true";
export const HIDDEN_VALUE = "••••";
export const privateValue = (value) => HIDE_NUMBERS ? HIDDEN_VALUE : value;
export const privateText = (value) => HIDE_NUMBERS
  ? String(value ?? "").replace(/\d[\d.,]*/g, HIDDEN_VALUE)
  : value;
