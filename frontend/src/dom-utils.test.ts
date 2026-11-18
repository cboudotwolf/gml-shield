import { beforeEach, describe, expect, it } from "vitest";
import { parseHTML } from "linkedom";

import { createWarehouseCodeElement, setTextContent } from "./dom-utils";
import { createDriverMessageElement } from "./driver-messages";

describe("safe rendering of user-provided text", () => {
  beforeEach(() => {
    const testDom = parseHTML("<html><body></body></html>");
    globalThis.document = testDom.document as unknown as Document;
  });

  it("renders script markup as message text without creating a script element", () => {
    const element = createDriverMessageElement({
      id: 1,
      content: "<script>alert(1)</script>",
      created_at: "2026-01-01T10:00:00Z",
    });

    expect(element.querySelector("script")).toBeNull();
    expect(element.querySelector("p")?.textContent).toBe("<script>alert(1)</script>");
  });

  it("sets warehouse codes through the DOM without parsing quote characters as attributes", () => {
    const warehouseCode = '"><svg onload=alert(1)>';
    const element = createWarehouseCodeElement(warehouseCode);

    expect(element.dataset.value).toBe(warehouseCode);
    expect(element.attributes.length).toBe(1);
    expect(element.querySelector("svg")).toBeNull();
  });

  it("writes API error content as plain text", () => {
    const feedbackElement = document.createElement("p");
    setTextContent(feedbackElement, "<img src=x onerror=alert(1)>");

    expect(feedbackElement.querySelector("img")).toBeNull();
    expect(feedbackElement.textContent).toBe("<img src=x onerror=alert(1)>");
  });
});
