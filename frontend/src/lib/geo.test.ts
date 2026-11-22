import { describe, expect, it } from "vitest";
import { prettifyBasinName } from "./geo";

describe("prettifyBasinName", () => {
  it("re-cases the four basin names of data/basins.geojson with their official accents", () => {
    expect(prettifyBasinName("RIO GUADALQUIVIR")).toBe("Río Guadalquivir");
    expect(prettifyBasinName("RIO GUADALFEO O RIO CADIAR")).toBe("Río Guadalfeo o Río Cádiar");
    expect(prettifyBasinName("RIO ADRA O GRANDE O VERDE")).toBe("Río Adra o Grande o Verde");
    expect(prettifyBasinName("RIO ANDARAX")).toBe("Río Andarax");
  });
});
