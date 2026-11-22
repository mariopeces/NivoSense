// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "../test/dom";
import CreditBar from "./CreditBar";

describe("CreditBar", () => {
  it("links to Darwin Geospatial in a new tab with an accessible name", () => {
    render(<CreditBar />);
    const link = screen.getByRole("link", { name: /Realizado por Darwin Geospatial/ });
    expect(link.getAttribute("href")).toBe("https://darwingeospatial.com");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.textContent).toBe("Realizado por Darwin Geospatial");
  });
});
