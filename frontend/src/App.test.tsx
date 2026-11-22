// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { repoFile } from "./test/dom";
import App from "./App";

// MapLibre needs WebGL, which jsdom lacks: the map is replaced by a stub that shows the props the shell
// passes and lets a test click a basin the way the real map's click handler does.
vi.mock("./components/Map", () => ({
  default: (props: {
    selectedBasinId: string | null;
    basemap: string;
    terrain: boolean;
    inset: { left: number; bottom: number };
    onBasinSelect: (id: string | null) => void;
  }) => (
    <div
      data-testid="map"
      data-selected={props.selectedBasinId ?? ""}
      data-basemap={props.basemap}
      data-inset-left={props.inset.left}
    >
      <button type="button" onClick={() => props.onBasinSelect("604456")}>
        map-click-604456
      </button>
    </div>
  ),
}));

// The site's own static files, served as the static site serves them; anything else (the optional backend,
// the observation manifest that the static site does not have) answers 404.
const FILES: Record<string, string> = {
  "/data/basins.geojson": "frontend/public/data/basins.geojson",
  "/data/webcams.json": "frontend/src/test-fixtures/webcams.json",
  "/data/snow-model/manifest.json": "frontend/public/data/snow-model/manifest.json",
  "/weather/manifest.json": "frontend/public/weather/manifest.json",
};

beforeEach(() => {
  vi.stubEnv("VITE_API_URL", "");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost/").pathname;
      const file = FILES[path];
      return file ? new Response(repoFile(file), { status: 200 }) : new Response("", { status: 404 });
    }),
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
});

async function renderApp() {
  render(<App />);
  await screen.findByText("Aún no hay escenas publicadas.");
}

const map = () => screen.getByTestId("map");
const panelTitle = () => within(screen.getByRole("tabpanel")).getByRole("heading", { level: 2 }).textContent;

// Rendering the whole shell (Recharts, every section) under jsdom is slow on a cold run.
describe("App shell", { timeout: 20_000 }, () => {
  it("renders the rail, the Nieve panel and the map together, with honest empty states", async () => {
    await renderApp();
    const nav = screen.getByRole("navigation");
    expect(within(nav).getAllByRole("tab")).toHaveLength(5);
    expect(nav.compareDocumentPosition(map()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(panelTitle()).toBe("Sierra Nevada");
    expect(map().dataset.basemap).toBe("claro");
    expect(map().dataset.insetLeft).toBe("384");
    // The repo's snow-model manifest says the model has not run: every layer row is Pendiente.
    expect(await screen.findAllByText("Pendiente")).toHaveLength(5);
  });

  it("gives the map back the panel's width when the panel is collapsed", async () => {
    await renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Ocultar" }));
    expect(map().dataset.insetLeft).toBe("64");
    fireEvent.click(screen.getByRole("button", { name: "Mostrar" }));
    expect(map().dataset.insetLeft).toBe("384");
  });

  it("switches the panel with the rail sections", async () => {
    await renderApp();
    const titles: Record<string, string> = {
      Agua: "Cuencas",
      Webcams: "Cámaras",
      Meteo: "Previsión",
      Método: "Cómo se hace cada capa",
      Nieve: "Sierra Nevada",
    };
    for (const [tab, title] of Object.entries(titles)) {
      fireEvent.click(screen.getByRole("tab", { name: tab }));
      expect(panelTitle()).toBe(title);
    }
  });

  it("lists the real basins by area and selects one through the same path as the map", async () => {
    await renderApp();
    fireEvent.click(screen.getByRole("tab", { name: "Agua" }));
    const rows = await screen.findAllByRole("button", { name: /km²$/ });
    expect(rows.map((row) => row.textContent)).toEqual([
      "Río Guadalquivir520,7 km²",
      "Río Guadalfeo o Río Cádiar492,3 km²",
      "Río Andarax486,1 km²",
      "Río Adra o Grande o Verde223,2 km²",
    ]);
    fireEvent.click(rows[1]);
    expect(map().dataset.selected).toBe("604456");
    expect(screen.getByRole("heading", { level: 3 }).textContent).toBe("Río Guadalfeo o Río Cádiar");
    expect(screen.getByText("492,3 km² en la zona estudiada")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Todas las cuencas" }));
    expect(map().dataset.selected).toBe("");
  });

  it("opens Agua and the panel when a basin is clicked on the map", async () => {
    await renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Ocultar" }));
    fireEvent.click(screen.getByRole("button", { name: "map-click-604456" }));
    expect(screen.getByRole("tab", { selected: true }).textContent).toBe("Agua");
    expect(screen.getByRole("button", { name: "Ocultar" }).getAttribute("aria-expanded")).toBe("true");
    expect(map().dataset.selected).toBe("604456");
    expect(await screen.findByText("Río Guadalfeo o Río Cádiar")).toBeTruthy();
  });

  it("shows the webcam catalogue as it is: no camera with an image today", async () => {
    await renderApp();
    fireEvent.click(screen.getByRole("tab", { name: "Webcams" }));
    expect(await screen.findByText("Ninguna cámara con imagen en este momento.")).toBeTruthy();
    const offline = JSON.parse(repoFile("frontend/src/test-fixtures/webcams.json")).filter((c: { status: string }) => c.status === "offline");
    expect(screen.getAllByText("Sin imagen", { selector: "span.text-caption" })).toHaveLength(offline.length);
  });
});
