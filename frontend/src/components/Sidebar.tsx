export default function Sidebar() {
  return (
    <aside className="w-[360px] shrink-0 bg-slate-950 border-r border-slate-800 flex flex-col">
      <header className="px-5 py-4 border-b border-slate-800">
        <h1 className="text-xl font-semibold tracking-tight">NivoSense</h1>
        <div className="mt-3">
          <label className="block text-xs uppercase tracking-wide text-slate-400 mb-1">
            Región
          </label>
          <select
            className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm"
            defaultValue="sierra-nevada"
          >
            <option value="sierra-nevada">Sierra Nevada</option>
          </select>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <Section title="Snow Cover">
          <p className="text-2xl font-semibold text-slate-200">—</p>
          <p className="text-xs text-slate-500">Pendiente de cargar capa</p>
        </Section>

        <Section title="Snow Change">
          <p className="text-2xl font-semibold text-slate-200">—</p>
          <p className="text-xs text-slate-500">Variación respecto al día anterior</p>
        </Section>

        <Section title="Stats">
          <p className="text-sm text-slate-500">
            Selecciona una cuenca para ver % de cobertura y tendencia.
          </p>
        </Section>

        <Section title="Snow Routes">
          <ul className="text-sm text-slate-400 space-y-1">
            <li>Ski touring</li>
            <li>Snowshoe</li>
          </ul>
        </Section>
      </div>

      <footer className="px-5 py-3 border-t border-slate-800 text-xs text-slate-500">
        Powered by{" "}
        <a
          href="https://darwingeospatial.com"
          target="_blank"
          rel="noreferrer"
          className="text-slate-300 hover:text-white underline underline-offset-2"
        >
          Darwin Geospatial
        </a>
      </footer>
    </aside>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="px-5 py-4 border-b border-slate-800">
      <h2 className="text-xs uppercase tracking-wide text-slate-400 mb-2">
        {title}
      </h2>
      {children}
    </section>
  );
}
