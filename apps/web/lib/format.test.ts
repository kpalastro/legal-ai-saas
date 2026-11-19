import { describe, expect, it } from "vitest";

import { lines, parties } from "./format";

describe("lines", () => {
  it("splits, trims and drops blanks", () => {
    expect(lines(" one \n\n two \n  ")).toEqual(["one", "two"]);
  });
});

describe("parties", () => {
  it("parses a name and role", () => {
    expect(parties("A. Plaintiff — plaintiff")).toEqual([
      { name: "A. Plaintiff", role: "plaintiff" },
    ]);
  });

  it("defaults the role when no separator is present", () => {
    expect(parties("B. Defendant")).toEqual([
      { name: "B. Defendant", role: "party" },
    ]);
  });
});
