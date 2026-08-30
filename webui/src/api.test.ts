import { describe, expect, it } from "vitest";
import { humanizeError } from "./api";

describe("humanizeError", () => {
  it("turns undeclared graph tools into a recovery step", () => {
    expect(humanizeError("RT012 tool 'web_search' was not declared by this graph node")).toContain(
      "Edit the failed card",
    );
  });

  it("explains empty optional OAP sections", () => {
    expect(humanizeError("[] should be non-empty; {} should be non-empty")).toContain(
      "leave the section unset",
    );
  });
});
