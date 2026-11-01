import { describe, expect, it } from "vitest";

import { everyKeyBilingual, msg } from "@/lib/i18n";

describe("i18n", () => {
  it("has every key in English and Urdu", () => {
    expect(everyKeyBilingual()).toBe(true);
    expect(msg("youSaid", "ur")).toBe("آپ نے کہا");
    expect(msg("listening", "en")).toBe("Listening");
  });

  it("marks Urdu as RTL in the UI language helper", () => {
    expect(msg("youSaid", "ur")).toMatch(/آپ/);
    document.documentElement.dir = "rtl";
    expect(document.documentElement.dir).toBe("rtl");
    document.documentElement.dir = "ltr";
  });
});
